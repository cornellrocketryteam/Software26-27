"""Exercise generated nginx with a hostile upstream; optionally real synthetic RTSP."""
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(base, path, method='GET'):
    try:
        response = urllib.request.urlopen(urllib.request.Request(base + path, method=method), timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


seen = []
class Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append((self.command, self.path, dict(self.headers)))
        self.send_response(400 if self.headers.get_all('Host') != ['127.0.0.1'] else 500 if 'fillcam2' in self.path else 200)
        self.end_headers()
        self.wfile.write(b'rtsp://private:SECRET@camera' if 'fillcam2' in self.path else b'stream fixture')

    def do_HEAD(self):
        seen.append((self.command, self.path, dict(self.headers)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp)
    upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    webport = port()
    config = Path(os.environ['NGINX_CONFIG']).read_text()
    config = config.replace('127.0.0.1:1984', f'127.0.0.1:{upstream.server_port}')
    config = config.replace('127.0.0.1:18080', f'127.0.0.1:{webport}')
    for original, name in [('/run/nginx', 'run'), ('/var/log/nginx', 'logs'),
                           ('/var/cache/nginx', 'cache'), ('/var/spool/nginx', 'spool')]:
        (work / name).mkdir()
        config = config.replace(original, str(work / name))
    config_path = work / 'nginx.conf'
    config_path.write_text(config)
    command = ['nginx', '-e', 'stderr', '-p', str(work), '-c', str(config_path)]
    subprocess.run(command + ['-t'], check=True)
    server = subprocess.Popen(command)
    try:
        base = f'http://127.0.0.1:{webport}'
        for _ in range(100):
            try:
                if request(base, '/healthz')[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.05)
        else:
            raise AssertionError('nginx startup timeout')
        assert request(base, '/cameras/')[0] == 200
        assert request(base, '/cameras/viewer.js')[0] == 200
        for name in ('fillcam0', 'fillcam1'):
            path = f'/cameras/{name}/stream.mp4'
            for query in ('', '?src=rtsp://attacker/evil&src=fillcam2&video=evil', '?dst=x&filename=evil&duration=1'):
                status, _, body = request(base, path + query)
                assert status == 200 and body == b'stream fixture', (status, body, seen)
                assert seen[-1][1] == f'/api/stream.mp4?src={name}&video&audio=none', seen[-1]
                assert seen[-1][2].get('User-Agent') == 'ground-station-camera'
            assert request(base, path, 'HEAD')[0] == 200
            count = len(seen)
            for method in ('POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'):
                assert request(base, path, method)[0] == 405, method
            assert len(seen) == count, 'write method reached upstream'
        count = len(seen)
        for route in ('/cameras/api/config', '/cameras/api/streams', '/cameras/api/stream.mp4?src=fillcam0',
                      '/cameras/fillcam9/stream.mp4', '/cameras/credentials.py', '/cameras/unavailable.txt',
                      '/api/config', '/api/streams', '/api/stream.mp4?src=fillcam0', '/cameras/fillcam0/stream.mp4/extra'):
            assert request(base, route)[0] == 404, route
        assert len(seen) == count
        status, _, body = request(base, '/cameras/fillcam2/stream.mp4')
        assert status == 502 and b'SECRET' not in body and b'Camera unavailable' in body
        upstream.shutdown()
        upstream.server_close()
        assert request(base, '/cameras/fillcam0/stream.mp4')[0] == 502
        assert request(base, '/healthz')[0] == 200
        assert request(base, '/cameras/')[0] == 200
        print('PASS: generated nginx exact routes, query isolation, methods, private errors, offline dashboard')
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        upstream.server_close()
