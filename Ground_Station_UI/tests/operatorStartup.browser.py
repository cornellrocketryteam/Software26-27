"""Production startup regression: mock every socket and block non-local HTTP."""
import json
import base64
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:4173'
SAFE = {'schemaVersion': 1, 'fillStationWebSocketUrl': None, 'grafanaUrl': None,
        'fieldMode': True, 'map': {'tileUrl': '/tiles/{z}/{x}/{y}.png', 'tilesConfigured': False}}
MOCK_SOCKETS = '''(() => {
  window.testSockets = []; window.testCommands = [];
  class LocalSocket extends EventTarget {
    static OPEN = 1; static CLOSED = 3; readyState = 0;
    constructor(url) { super(); if (window.testSocketError) throw new Error('fixture socket blocked');
      this.url = url; window.testSockets.push(this);
      setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 10); }
    send(raw) { window.testCommands.push(JSON.parse(raw)); }
    close() { this.readyState = 3; this.onclose?.({}); }
  }
  window.WebSocket = LocalSocket;
})()'''


def open_page(browser, config=SAFE, status=200, socket_error=False):
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    external = []
    context.route_web_socket('**', lambda socket: socket.close())
    context.add_init_script(MOCK_SOCKETS.replace('window.testSockets = [];',
        'window.testSocketError = ' + str(socket_error).lower() + '; window.testSockets = [];'))
    def route(request):
        if not request.request.url.startswith(BASE + '/'):
            external.append(request.request.url); request.abort(); return
        if '/tiles/' in request.request.url:
            request.fulfill(status=404, body='unprepared tile'); return
        if request.request.url.endswith('/station-config.json'):
            request.fulfill(status=status, content_type='application/json', body=json.dumps(config)); return
        request.continue_()
    context.route('**/*', route)
    page = context.new_page()
    page.set_default_timeout(5000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(BASE)
    page.get_by_role('heading', name='Select a Station').wait_for()
    return context, page, external, errors


def confirm_fixture_coords(page):
    page.get_by_role('button', name='Recovery & Payload', exact=False).click()
    page.get_by_role('heading', name='Recovery & Payload Page').wait_for()
    fields = page.locator('input[type="number"]')
    assert fields.count() == 6
    for index, value in enumerate(['10', '20', '10.1', '20.1', '10.05', '20.05']):
        fields.nth(index).fill(value)
    page.get_by_role('button', name='Confirm Coordinates', exact=True).click()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        context, page, external, errors = open_page(browser)
        page.get_by_text('Fill station: not configured', exact=True).wait_for()
        assert page.evaluate('window.testSockets.length') == 0
        assert page.locator('img[alt="CRT Logo"]').evaluate('(img) => img.complete && img.naturalWidth > 0')
        page.get_by_role('button', name='Recovery & Payload', exact=False).click()
        page.wait_for_url('**/recovery')
        page.reload(); page.get_by_role('heading', name='Recovery & Payload Page').wait_for()
        assert page.evaluate('window.testSockets.length') == 0
        assert not external, external
        assert not errors, errors
        page.screenshot(path='/private/tmp/ground-operator-ui-unconfigured.png', full_page=True)
        context.close()

        context, page, external, errors = open_page(browser, status=404)
        page.get_by_text('Station settings unavailable. Device connections are disabled.', exact=True).wait_for()
        assert page.evaluate('window.testSockets.length') == 0
        assert not errors, errors
        context.close()

        context, page, external, errors = open_page(browser)
        confirm_fixture_coords(page)
        page.get_by_text('Offline map tiles are not configured.', exact=True).wait_for()
        assert page.evaluate('navigator.onLine') is True
        assert not external, external
        assert page.evaluate('window.testCommands.length') == 0
        context.close()

        local_tiles = {**SAFE, 'map': {**SAFE['map'], 'tilesConfigured': True}}
        context, page, external, errors = open_page(browser, local_tiles)
        confirm_fixture_coords(page)
        page.get_by_text('Some map tiles could not be loaded.', exact=True).wait_for()
        assert page.locator('.leaflet-container').count() == 1
        # A later covered area/service recovery must not require an app reload.
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
        recovered = []
        def tile(request):
            recovered.append(request.request.url)
            request.fulfill(content_type='image/png', body=png)
        context.route(BASE + '/tiles/**', tile)
        page.locator('input[type="number"]').nth(0).fill('10.000001')
        page.get_by_role('button', name='Confirm Coordinates', exact=True).click()
        page.get_by_text('Lat: 10.000001°', exact=True).wait_for()
        page.get_by_role('button', name='Retry map tiles', exact=True).click()
        page.wait_for_timeout(100)
        assert recovered
        assert page.locator('.leaflet-container').count() == 1
        assert not external, external
        assert not errors, errors
        context.close()

        configured = {**SAFE, 'fillStationWebSocketUrl': 'ws://configured-fixture.invalid:9000'}
        context, page, external, errors = open_page(browser, configured, socket_error=True)
        page.get_by_text('Fill-station connection could not be opened. Check its address and browser permissions.', exact=True).wait_for()
        assert not errors, errors
        context.close()

        context, page, external, errors = open_page(browser, configured)
        page.get_by_text('Fill station: connected', exact=True).wait_for()
        page.wait_for_timeout(5200)  # Observe a scheduled read-only heartbeat.
        assert all(s == configured['fillStationWebSocketUrl']
                   for s in page.evaluate('window.testSockets.map(s => s.url)'))
        assert set(page.evaluate('window.testCommands.map(c => c.command)')) == {'get_hardware_availability', 'heartbeat'}
        page.evaluate('window.testSockets.at(-1).close()')
        page.get_by_text('Fill station: disconnected', exact=True).wait_for()
        page.get_by_text('Fill station: connected', exact=True).wait_for()
        assert set(page.evaluate('window.testCommands.map(c => c.command)')) == {'get_hardware_availability', 'heartbeat'}
        assert not external, external
        assert not errors, errors
        page.screenshot(path='/private/tmp/ground-operator-ui-configured.png', full_page=True)
        context.close()
        print('Production UI startup, assets, SPA refresh and read-only socket checks passed')
    finally:
        browser.close()
