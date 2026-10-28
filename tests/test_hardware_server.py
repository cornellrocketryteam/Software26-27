"""Local editor HTTP boundary, persistence and request security."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'fill-station/hardware/server.py'


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SERVER.exists(), 'The hardware editor server must exist')
        spec = importlib.util.spec_from_file_location('hardware_editor_server', SERVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.directory = root / 'fill-station/hardware/profiles'
        self.directory.mkdir(parents=True)
        self.profile = {'version': 1, 'profile': 'liquid', 'devices': [], 'buses': []}
        (self.directory/'liquid.json').write_text(json.dumps(self.profile))
        (self.directory/'hybrid.json').write_text(json.dumps({**self.profile, 'profile': 'hybrid'}))
        def compile_profile(profile):
            if profile.get('version') != 1:
                raise ValueError('Unsupported version')
            return {'report': {'assignments': [], 'idle': []}, 'runtime': {}}
        compiler = types.SimpleNamespace(BOARD={'pins': []}, CATALOG={}, compile_profile=compile_profile)
        self.server = self.module.create_server(root, port=0, compiler_module=compiler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:' + str(self.server.server_port)
        self.token = self.request('GET', '/api/bootstrap')[1]['token']

    def tearDown(self):
        if hasattr(self, 'server'):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.host)
        merged = {'Content-Type': 'application/json'}
        merged.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, merged)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data)

    def test_editor_assets_are_served_without_external_resources(self):
        connection = http.client.HTTPConnection(self.host)
        connection.request('GET', '/')
        response = connection.getresponse()
        markup = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn('id="devices"', markup)
        self.assertIn('id="headers"', markup)
        self.assertIn('type="module"', markup)
        self.assertNotIn('https://', markup)

    def auth(self):
        return {'X-Session-Token': self.token, 'Origin': 'http://' + self.host}

    def test_save_revision_is_atomic_and_stale_write_is_rejected(self):
        status, before = self.request('GET', '/api/profiles/liquid')
        self.assertEqual(status, 200)
        changed = {**self.profile, 'devices': [{'id': 'extra'}]}
        body = {'profile': changed, 'revision': before['revision']}
        status, saved = self.request('PUT', '/api/profiles/liquid', body, self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads((self.directory/'liquid.json').read_text()), changed)
        self.assertNotEqual(saved['revision'], before['revision'])
        self.assertEqual(self.request('PUT', '/api/profiles/liquid', body, self.auth())[0], 409)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['hybrid.json', 'liquid.json'])

    def test_invalid_profile_does_not_replace_saved_file(self):
        before = self.request('GET', '/api/profiles/liquid')[1]
        status, result = self.request('PUT', '/api/profiles/liquid', {'profile': {**self.profile, 'version': 2}, 'revision': before['revision']}, self.auth())
        self.assertEqual(status, 422)
        self.assertIn('Unsupported version', result['errors'][0])
        self.assertEqual(self.request('GET', '/api/profiles/liquid')[1], before)

    def test_requires_token_and_rejects_foreign_origin_and_host(self):
        body = {'profile': self.profile}
        self.assertEqual(self.request('POST', '/api/validate', body)[0], 403)
        self.assertEqual(self.request('POST', '/api/validate', body, {**self.auth(), 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/bootstrap', headers={'Host': 'evil.example'})[0], 403)
        result = self.request('POST', '/api/validate', body, self.auth())[1]
        self.assertTrue(result['valid'])
        self.assertEqual(result['report'], {'assignments': [], 'idle': []})

    def test_rejects_symlinked_profile_storage(self):
        outside = Path(self.tmp.name) / 'outside.json'
        outside.write_text(json.dumps(self.profile))
        target = self.directory / 'liquid.json'
        target.unlink()
        target.symlink_to(outside)
        self.assertEqual(self.request('GET', '/api/profiles/liquid')[0], 400)
        target.unlink()
        target.write_text(json.dumps(self.profile))
        self.directory.rename(self.directory.with_name('elsewhere'))
        self.directory.symlink_to(self.directory.with_name('elsewhere'), target_is_directory=True)
        self.assertEqual(self.request('GET', '/api/profiles/liquid')[0], 400)

    def test_rejects_arbitrary_paths_and_profile_identity_changes(self):
        self.assertEqual(self.request('GET', '/api/profiles/other')[0], 404)
        before = self.request('GET', '/api/profiles/liquid')[1]
        self.assertEqual(self.request('PUT', '/api/profiles/liquid', {'profile': {**self.profile, 'profile': 'hybrid'}, 'revision': before['revision']}, self.auth())[0], 422)
        self.assertEqual(self.request('GET', '/api/profiles/../../secret')[0], 404)


if __name__ == '__main__':
    unittest.main()
