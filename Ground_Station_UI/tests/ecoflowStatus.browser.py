"""Cloud panel with mocked local responses only; no EcoFlow account or hardware."""
import json
from playwright.sync_api import sync_playwright, expect
expect.set_options(timeout=12000)
BASE = 'http://127.0.0.1:4173'
CONFIG = {'schemaVersion':1,'fillStationWebSocketUrl':None,'grafanaUrl':'/grafana/','fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
DEVICE = {'id':'plug','kind':'shelly','model':'Fixture plug','address':'192.168.1.120','connectedLoad':'Fixture lamp','state':'available','output':False,'metrics':{},'stale':False,'lastSuccessUnixMs':1,'canSetOutput':True}
DATA = {'schemaVersion':1,'devices':[DEVICE],'powerWritesConfigured':True,'operatorAuthorizationRequired':True}
VALUE = {'enabled':True,'state':'cloud-snapshot','readOnly':True,'deviceSampleTimeKnown':False,'ageSeconds':0,'batteryPercent':50,'inputWatts':0,'outputWatts':12}
mode = {'value':'snapshot'}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='chrome')
    try:
        context = browser.new_context(viewport={'width':1440,'height':1000})
        def route(r):
            req = r.request
            assert req.url.startswith(BASE + '/'), 'External request'
            assert req.method == 'GET', 'Unexpected write'
            if req.url.endswith('/station-config.json'): value = CONFIG
            elif req.url.endswith('/network-api/v1/devices'): value = DATA
            elif req.url.endswith('/network-api/v1/wan'):
                value = {'enabled':False,'state':'disabled','method':'tcp-connect','checkedUnixMs':None,'ageSeconds':None,'observedFailureSpanSeconds':None,'targets':[]}
            elif req.url.endswith('/ecoflow-api/v1/ecoflow'):
                if mode['value'] == 'down': r.fulfill(status=503, body='unavailable'); return
                value = dict(VALUE)
                if mode['value'] != 'snapshot':
                    value.update(state=mode['value'], batteryPercent=None, inputWatts=None, outputWatts=None)
                    if mode['value'] == 'disabled': value['enabled'] = False
            else: r.continue_(); return
            r.fulfill(content_type='application/json', body=json.dumps(value))
        context.route('**/*', route)
        page = context.new_page()
        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE + '/network')
        panel = page.get_by_label('EcoFlow monitoring', exact=True)
        expect(panel.get_by_text('Battery: 50.0%', exact=True)).to_be_visible()
        expect(panel.get_by_text('Total input: 0.0 W', exact=True)).to_be_visible()
        page.get_by_label('Operator token (this page only)').fill('fixture-operator-token-at-least-24')
        on = page.get_by_role('button', name='Turn on', exact=True)
        for state, label in [('stale','Cloud reads are stale'),('cloud-reports-offline','Cloud reports power station offline'),('down','EcoFlow monitoring unavailable'),('disabled','Monitoring not configured')]:
            mode['value'] = state
            expect(panel.get_by_text(label, exact=True)).to_be_visible()
            expect(panel.get_by_text('Battery: Unavailable', exact=True)).to_be_visible()
            expect(on).to_be_enabled()
        mode['value'] = 'snapshot'
        expect(panel.get_by_text('Total output: 12.0 W', exact=True)).to_be_visible()
        page.screenshot(path='/private/tmp/crt-ecoflow-desktop.png', full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/private/tmp/crt-ecoflow-mobile.png', full_page=True)
        assert not errors, errors
        print('EcoFlow mocked UI states, recovery, zero metrics, independent controls and mobile passed')
    finally:
        browser.close()
