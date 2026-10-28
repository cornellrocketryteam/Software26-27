#!/usr/bin/env python3
"""Loopback-only editor for the two repository hardware profiles."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import webbrowser

PROFILES = frozenset(('liquid', 'hybrid'))
WEB = Path(__file__).resolve().parent / 'web'
MAX_BODY = 1024 * 1024


def create_server(repo, port=0, compiler_module=None):
    directory = Path(repo).resolve() / 'fill-station/hardware/profiles'
    if compiler_module is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        compiler_module = importlib.import_module('compiler')
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()

    def profile_path(name):
        path = directory / (name + '.json')
        if name not in PROFILES or path.is_symlink() or directory.resolve() != directory:
            raise ValueError('Only regular Liquid and Hybrid profile files can be edited')
        return path

    def read_profile(name):
        data = profile_path(name).read_bytes()
        return {'profile': json.loads(data), 'revision': hashlib.sha256(data).hexdigest()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, status, body, content_type='application/json'):
            data = json.dumps(body).encode() if content_type == 'application/json' else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def secure(self, write=False):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if host not in allowed or (origin is not None and origin != 'http://' + host):
                self.respond(403, {'errors': ['Request must come from this local editor']})
                return False
            if write and (not secrets.compare_digest(self.headers.get('X-Session-Token', ''), token) or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                self.respond(403, {'errors': ['Missing session token or JSON content type; reload the editor']})
                return False
            return True

        def body(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ValueError('Invalid request size')
            if length <= 0 or length > MAX_BODY:
                raise ValueError('Request must contain JSON smaller than 1 MiB')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError('Request must be a JSON object')
            return value

        def do_GET(self):
            if not self.secure():
                return
            path = urlsplit(self.path).path
            try:
                if path == '/api/bootstrap':
                    self.respond(200, {'token': token, 'board': compiler_module.BOARD, 'catalog': compiler_module.CATALOG,
                        'headers': {'PRU': 54, 'EXPANSION': 40, 'MCU': 28}})
                elif path.startswith('/api/profiles/') and path.removeprefix('/api/profiles/') in PROFILES:
                    with lock:
                        self.respond(200, read_profile(path.removeprefix('/api/profiles/')))
                elif path in ('/', '/index.html', '/app.js', '/style.css'):
                    name = 'index.html' if path == '/' else path[1:]
                    mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name]
                    self.respond(200, (WEB/name).read_bytes(), mime)
                else:
                    self.respond(404, {'errors': ['Unknown editor resource']})
            except (OSError, ValueError) as error:
                self.respond(400, {'errors': [str(error)]})

        def do_POST(self):
            self.mutate(False)

        def do_PUT(self):
            self.mutate(True)

        def mutate(self, save):
            if not self.secure(write=True):
                return
            path = urlsplit(self.path).path
            name = path.removeprefix('/api/profiles/')
            if (save and (not path.startswith('/api/profiles/') or name not in PROFILES)) or (not save and path != '/api/validate'):
                self.respond(404, {'errors': ['Unknown editor resource']})
                return
            try:
                body = self.body()
                profile = body.get('profile')
                if not isinstance(profile, dict):
                    raise ValueError('Profile must be a JSON object')
                if save and profile.get('profile') != name:
                    raise ValueError('Profile identity must match the selected Liquid or Hybrid file')
                compiled = compiler_module.compile_profile(profile)
                report = compiled.get('report', compiled)
                if not save:
                    self.respond(200, {'valid': True, 'errors': [], 'report': report})
                    return
                with lock:
                    current = read_profile(name)
                    if body.get('revision') != current['revision']:
                        self.respond(409, {'errors': ['This profile changed on disk. Discard changes to reload before saving.']})
                        return
                    target = profile_path(name)
                    data = (json.dumps(profile, indent=2) + '\n').encode()
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=directory, prefix='.' + name + '-', suffix='.tmp', delete=False) as stream:
                            temporary = stream.name
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, target)
                    finally:
                        if temporary and os.path.exists(temporary):
                            os.unlink(temporary)
                    self.respond(200, {**read_profile(name), 'report': report})
            except (ValueError, TypeError, KeyError) as error:
                self.respond(422, {'valid': False, 'errors': [str(error)]})
            except OSError as error:
                self.respond(500, {'errors': [f'Could not access profile: {error}']})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd(), help='Software26-27 repository root')
    parser.add_argument('--port', type=int, default=0, help='Loopback port (default: choose an available port)')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    directory = args.repo.resolve() / 'fill-station/hardware/profiles'
    if not all((directory/(name+'.json')).is_file() for name in PROFILES):
        parser.error('--repo must point to a repository containing Liquid and Hybrid hardware profiles')
    server = create_server(args.repo, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Hardware editor: {url}', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
