"""Manual acceptance: pinned Grafana embeds synthetic cameras; tabs retain pages.

Requires Docker, Playwright Chrome, GO2RTC and FFMPEG. No physical device access.
"""
import http.server
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright
import test_cameras_relay

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'grafana/grafana@sha256:7c064e627d9cb50c3485c9ded5ca0222de89a08e41403322a0c3ca6f1777a8d1'


def browser_check(relay):
    grafana_port = test_cameras_relay.port()
    with tempfile.TemporaryDirectory(prefix='crt-grafana-browser-') as temporary:
        work = Path(temporary)
        spec = importlib.util.spec_from_file_location('telemetry_runtime', ROOT / 'ground-station/provisioning/runtime.py')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        runtime.build_assets(ROOT / 'ground-station', work / 'assets', cameras=True)
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                self.do_GET()

            def do_GET(self):
                if self.path.startswith('/grafana/'):
                    data = self.rfile.read(int(self.headers.get('Content-Length', 0))) if self.command == 'POST' else None
                    request = urllib.request.Request(f'http://127.0.0.1:{grafana_port}' + self.path, data=data,
                                                     headers={'Content-Type': self.headers.get('Content-Type', 'application/json')}, method=self.command)
                    try:
                        response = urllib.request.urlopen(request, timeout=15)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        body = response.read()
                        self.send_response(response.status)
                        self.send_header('Content-Type', response.headers.get('Content-Type', 'application/octet-stream'))
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                elif self.path == '/':
                    body = b'<html><body><h1>Commanding acceptance fixture</h1></body></html>'
                    self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(body)
                elif self.path in ('/station/', '/station/tabs.js', '/cameras/', '/cameras/viewer.js'):
                    directory = 'display' if self.path.startswith('/station/') else 'cameras'
                    filename = 'index.html' if self.path.endswith('/') else self.path.rsplit('/', 1)[1]
                    body = (ROOT / 'ground-station' / directory / filename).read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'application/javascript' if filename.endswith('.js') else 'text/html'); self.end_headers(); self.wfile.write(body)
                elif self.path in (f'/cameras/fillcam{i}/stream.mp4' for i in range(3)):
                    name = self.path.split('/')[2]
                    try:
                        with urllib.request.urlopen(relay + f'/api/stream.mp4?src={name}&video&audio=none', timeout=8) as upstream:
                            self.send_response(200); self.send_header('Content-Type', 'video/mp4'); self.end_headers()
                            while chunk := upstream.read(16384):
                                self.wfile.write(chunk); self.wfile.flush()
                    except (OSError, BrokenPipeError):
                        pass
                else:
                    self.send_error(404)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        name = f'crt-grafana-browser-{os.getpid()}'
        environment = {
            'GF_SERVER_ROOT_URL': base + '/grafana/', 'GF_SERVER_SERVE_FROM_SUB_PATH': 'true',
            'GF_AUTH_ANONYMOUS_ENABLED': 'true', 'GF_AUTH_ANONYMOUS_ORG_ROLE': 'Viewer',
            'GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION': 'true', 'GF_SECURITY_ALLOW_EMBEDDING': 'true',
            'GF_PANELS_DISABLE_SANITIZE_HTML': 'true', 'GF_SECURITY_DISABLE_GRAVATAR': 'true',
            'GF_PLUGINS_PREINSTALL_DISABLED': 'true', 'GF_PLUGINS_PREINSTALL': '',
            'GF_ANALYTICS_REPORTING_ENABLED': 'false', 'GF_ANALYTICS_CHECK_FOR_UPDATES': 'false',
            'GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES': 'false', 'GF_USERS_ALLOW_SIGN_UP': 'false',
            'GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH': '/var/lib/grafana/dashboards/dashboard.json',
        }
        command = ['docker', 'run', '-d', '--platform', 'linux/amd64', '--name', name,
                   '-p', f'127.0.0.1:{grafana_port}:3000',
                   '-v', f'{work}/assets/grafana/provisioning:/etc/grafana/provisioning:ro',
                   '-v', f'{work}/assets/grafana/dashboards:/var/lib/grafana/dashboards:ro']
        for key, value in environment.items():
            command += ['-e', key + '=' + value]
        try:
            subprocess.run(command + [IMAGE], check=True, stdout=subprocess.DEVNULL)
            for _ in range(180):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{grafana_port}/grafana/api/health', timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(1)
            else:
                raise AssertionError('Grafana did not become ready')
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.goto(base + '/grafana/', wait_until='domcontentloaded')
                page.locator('iframe[title="Fill cameras"]').wait_for(timeout=90000)
                page.frame_locator('iframe[title="Fill cameras"]').locator('video').first.wait_for(timeout=45000)
                camera = next(frame for frame in page.frames if frame.url == base + '/cameras/')
                camera.wait_for_function("document.querySelectorAll('video').length === 3 && [...document.querySelectorAll('video')].every(v => v.currentTime > 1 && v.readyState >= 2)", timeout=45000)
                page.screenshot(path='/private/tmp/crt-grafana-embedded-cameras.png', full_page=True)
                print('PASS: pinned Grafana rendered its provisioned camera panel with three advancing synthetic feeds.')
                page.goto(base + '/station/', wait_until='domcontentloaded')
                page.frame_locator('iframe[name="commanding"]').get_by_text('Commanding acceptance fixture').wait_for(state='attached')
                commanding = page.frame(name='commanding')
                commanding.wait_for_load_state('domcontentloaded')
                commanding.evaluate('window.acceptanceMarker = 41')
                page.get_by_role('tab', name='Commanding', exact=True).click()
                page.frame_locator('iframe[name="commanding"]').get_by_text('Commanding acceptance fixture').wait_for()
                page.get_by_role('tab', name='Grafana / cameras', exact=True).click()
                assert commanding.evaluate('window.acceptanceMarker') == 41
                page.get_by_role('tab', name='Grafana / cameras', exact=True).press('ArrowRight')
                assert page.get_by_role('tab', name='Commanding', exact=True).get_attribute('aria-selected') == 'true'
                page.screenshot(path='/private/tmp/crt-commanding-tabs.png', full_page=True)
                print('PASS: single-screen mouse/keyboard tabs switch views without reloading commanding.')
                browser.close()
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    test_cameras_relay.main(browser_check=browser_check)
