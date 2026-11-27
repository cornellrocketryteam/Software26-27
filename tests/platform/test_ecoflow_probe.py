import hashlib
import hmac
import importlib.util
from pathlib import Path
import unittest
import tempfile
import os

spec = importlib.util.spec_from_file_location('ecoflow_probe', Path(__file__).resolve().parents[2] / 'ground-station/network-devices/ecoflow_probe.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class EcoflowProbeTests(unittest.TestCase):
    def test_credentials_require_private_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials'
            path.write_text('{"accessKey":"access","secretKey":"secret"}')
            path.chmod(0o600)
            self.assertEqual(m.read_credentials(path)['accessKey'], 'access')
            path.chmod(0o644)
            with self.assertRaises(m.ProbeError):
                m.read_credentials(path)
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                m.read_credentials(link)
            fifo = Path(directory) / 'fifo'
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(m.ProbeError):
                m.read_credentials(fifo)

    def test_signature_and_get(self):
        req = m.signed_request('us', {'accessKey': 'access', 'secretKey': 'secret'}, 'quota/all', {'sn': 'ABC'}, 123, 456)
        expected = hmac.new(b'secret', b'sn=ABC&accessKey=access&nonce=123&timestamp=456', hashlib.sha256).hexdigest()
        self.assertEqual(req.get_method(), 'GET')
        self.assertEqual(req.get_header('Sign'), expected)
        self.assertIsNone(req.data)

    def test_offline_never_queries_quota(self):
        calls = []
        def fetch(*args):
            calls.append(args[2])
            return [{'sn': 'ABC', 'online': 0}]
        result = m.probe('us', {}, 'ABC', fetch)
        self.assertEqual(calls, ['list'])
        self.assertEqual(result['state'], 'cloud-reports-offline')

    def test_snapshot_is_not_sample_freshness(self):
        def fetch(region, credentials, endpoint, params):
            return [{'sn': 'ABC', 'online': 1}] if endpoint == 'list' else {'bms_bmsStatus.soc': 0, 'pd.wattsInSum': 1, 'pd.wattsOutSum': 12}
        result = m.probe('us', {}, 'ABC', fetch)
        self.assertEqual(result['batteryPercent'], 0)
        self.assertFalse(result['deviceSampleTimeKnown'])
        self.assertEqual(result['outputWatts'], 12)

    def test_missing_and_invalid_values_unknown(self):
        self.assertEqual(m.metrics({'bms_bmsStatus.soc': True, 'pd.wattsInSum': float('nan'), 'pd.wattsOutSum': -1}), {'batteryPercent': None, 'inputWatts': None, 'outputWatts': None})

    def test_unenrolled_refused(self):
        with self.assertRaises(m.ProbeError):
            m.probe('us', {}, 'ABC', lambda *args: [])

    def test_redirect_refused(self):
        with self.assertRaises(m.ProbeError):
            m.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')


if __name__ == '__main__':
    unittest.main()
