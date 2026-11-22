"""No camera/network access: private initialization and runtime rendering contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'ground-station/cameras/credentials.py'


class Credentials(unittest.TestCase):
    def test_helper_exists(self):
        self.assertTrue(HELPER.exists(), 'camera credential helper is not implemented')

    def test_viewer_fixed_routes_and_no_external_assets(self):
        html = ROOT / 'ground-station/cameras/index.html'
        js = ROOT / 'ground-station/cameras/viewer.js'
        self.assertTrue(html.exists() and js.exists(), 'standalone viewer is not implemented')
        text = html.read_text() + js.read_text()
        self.assertNotIn('https://', text)
        self.assertNotIn('rtsp://', text)
        for breakout in ('window.top.location', 'parent.location', 'target="_top"', 'window.open'):
            self.assertNotIn(breakout, text)
        for name in ('fillcam0', 'fillcam1', 'fillcam2'):
            self.assertIn(name, text)
        self.assertIn('stream.mp4', text)

    def run_helper(self, *args):
        return subprocess.run([sys.executable, str(HELPER), *map(str, args)], capture_output=True)

    def test_private_reference_roundtrip_and_no_clobber(self):
        if not HELPER.exists():
            self.skipTest('helper missing; existence test covers initial red')
        with tempfile.TemporaryDirectory() as tmp:
            ref, dest, config = [Path(tmp) / name for name in ('reference.json', 'private.json', 'go2rtc.yaml')]
            password = 'synthetic:@/#?% secret'
            ref.write_text(json.dumps({'sharedSandboxPassword': password, 'devices': {
                f'fill-camera-{i}': {'username': 'admin', 'passwordRef': 'sharedSandboxPassword'} for i in range(3)}}))
            result = self.run_helper('init', '--reference', ref, '--output', dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(password.encode(), result.stdout + result.stderr)
            self.assertNotEqual(self.run_helper('init', '--reference', ref, '--output', dest).returncode, 0)
            result = self.run_helper('render', '--credentials', dest, '--output', config, '--port', 1984)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(config.read_text())  # JSON is valid YAML
            self.assertEqual(data['api']['listen'], '127.0.0.1:1984')
            self.assertEqual(data['rtsp']['listen'], '')
            self.assertEqual(data['webrtc']['listen'], '')
            self.assertEqual(data['webrtc']['ice_servers'], [])
            self.assertEqual(set(data['streams']), {'fillcam0', 'fillcam1', 'fillcam2'})
            self.assertIn('192.168.1.103:554/Preview_01_main#transport=tcp', data['streams']['fillcam0'])
            self.assertIn('synthetic%3A%40%2F%23%3F%25%20secret', data['streams']['fillcam0'])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_invalid_input_never_echoed_or_written(self):
        if not HELPER.exists():
            self.skipTest('helper missing')
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'bad.json', Path(tmp) / 'out'
            source.write_text('{"secret": "DO-NOT-ECHO"}')
            result = self.run_helper('render', '--credentials', source, '--output', dest, '--port', 1984)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'DO-NOT-ECHO', result.stdout + result.stderr)
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
