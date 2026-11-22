import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.platform import signing
from tools.platform.runtime import PlatformError

PUBLIC = 'crt-ground-station-1:' + base64.b64encode(bytes(range(32))).decode()

class SigningKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name).resolve()
        self.directory = self.parent / 'signing'
        self.settings = {'directory': str(self.directory), 'name': 'crt-ground-station-1',
                         'nix': '/fixed/nix', 'nixStore': '/fixed/nix-store'}
        self.owner = patch.object(signing, 'ROOT_UID', os.getuid())
        self.owner.start()
        self.calls = []
    def tearDown(self):
        self.owner.stop()
        self.temp.cleanup()
    def execute(self, argv, **kwargs):
        self.calls.append(argv)
        if '--generate-binary-cache-key' in argv:
            Path(argv[-2]).write_text('PRIVATE SENTINEL\n')
            Path(argv[-1]).write_text(PUBLIC + '\n')
            return ''
        self.assertEqual(kwargs['input_data'], b'PRIVATE SENTINEL\n')
        return PUBLIC + '\n'
    def provision(self):
        return signing.provision(self.settings, uid=0, execute=self.execute)
    def test_non_root_has_no_side_effects(self):
        with self.assertRaises(PlatformError):
            signing.provision(self.settings, uid=1000, execute=self.execute)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.calls, [])
    def test_create_permissions_and_public_result_only(self):
        result = self.provision()
        self.assertEqual(result['publicKey'], PUBLIC)
        self.assertNotIn('PRIVATE SENTINEL', str(result))
        self.assertEqual((self.directory.stat().st_mode & 0o777), 0o700)
        self.assertEqual(((self.directory/'cache.sec').stat().st_mode & 0o777), 0o600)
    def test_repeat_preserves_key_and_identity(self):
        self.provision(); original=(self.directory/'cache.sec').read_bytes()
        self.calls.clear(); result=self.provision()
        self.assertFalse(result['created'])
        self.assertEqual(original, (self.directory/'cache.sec').read_bytes())
        self.assertFalse(any('--generate-binary-cache-key' in a for a in self.calls))
    def test_recovers_missing_public_without_rotation(self):
        self.provision(); (self.directory/'cache.pub').unlink(); self.calls.clear()
        self.assertEqual(self.provision()['publicKey'], PUBLIC)
        self.assertEqual(len(self.calls), 1)
    def test_refuses_wrong_public_or_insecure_secret(self):
        self.provision(); (self.directory/'cache.pub').write_text('wrong\n')
        with self.assertRaises(PlatformError): self.provision()
        (self.directory/'cache.pub').write_text(PUBLIC+'\n')
        (self.directory/'cache.sec').chmod(0o644)
        with self.assertRaises(PlatformError): self.provision()
    def test_refuses_symlinks_and_uncontrolled_parent(self):
        self.directory.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(PlatformError): self.provision()
        self.directory.unlink(); self.parent.chmod(0o777)
        with self.assertRaises(PlatformError): self.provision()
    def test_partial_public_only_does_not_rotate(self):
        self.directory.mkdir(mode=0o700); (self.directory/'cache.pub').write_text(PUBLIC+'\n')
        with self.assertRaises(PlatformError): self.provision()
        self.assertFalse((self.directory/'cache.sec').exists())
    def test_secret_diagnostic_never_escapes(self):
        def fail(*args, **kwargs): raise PlatformError('PRIVATE SENTINEL')
        with self.assertRaises(PlatformError) as error:
            signing.provision(self.settings, uid=0, execute=fail)
        self.assertNotIn('PRIVATE SENTINEL', str(error.exception))

if __name__ == '__main__': unittest.main()
