"""Local SSH enrollment preparation; real keygen/config parser, no remote calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools.platform.cli import main


class DeploySSHTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.host_key = self.home / 'verified-host'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.host_key)], check=True)
        self.public = Path(str(self.host_key) + '.pub')

    def invoke(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'HOME': str(self.home), 'CRT_PLATFORM_STATE_DIR': str(self.home/'state')}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(['deploy-ssh-init', '--host-key', str(self.public), *extra])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_does_not_create_keys_config_or_state(self):
        code, out, err = self.invoke('--dry-run')
        self.assertEqual(code, 0, err)
        self.assertFalse((self.home/'.ssh').exists())
        self.assertFalse((self.home/'state').exists())
        self.assertFalse(json.loads(out)['boardEnrolled'])

    def test_repeat_keeps_private_key_and_existing_config_and_pins_identity(self):
        ssh = self.home/'.ssh'; ssh.mkdir(mode=0o700)
        config = ssh/'config'; original = 'Host my-other-machine\n  HostName 127.0.0.1\n'
        config.write_text(original)
        code, out, err = self.invoke(); self.assertEqual(code, 0, err)
        result = json.loads(out); key = Path(result['identityFile'])
        before = key.read_bytes(); first_config = config.read_bytes()
        code, _, err = self.invoke(); self.assertEqual(code, 0, err)
        self.assertEqual(key.read_bytes(), before); self.assertEqual(config.read_bytes(), first_config)
        self.assertTrue(config.read_text().endswith(original))
        settings = subprocess.check_output(['ssh', '-G', '-F', str(config), 'fillstation-deploy'], stderr=subprocess.DEVNULL, text=True)
        for value in ['hostname 192.168.1.106', 'user root', 'identitiesonly yes', 'identityagent none', 'forwardagent no', 'stricthostkeychecking true']:
            self.assertIn(value, settings)
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertFalse(result['boardEnrolled'])
        self.assertNotIn('PRIVATE KEY', out)

    def test_changed_host_key_is_rejected_without_replacing_anything(self):
        code, _, err = self.invoke(); self.assertEqual(code, 0, err)
        config = self.home/'.ssh/config'; before = config.read_bytes()
        second = self.home/'second'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(second)], check=True)
        self.public = Path(str(second)+'.pub')
        code, _, _ = self.invoke(); self.assertEqual(code, 1)
        self.assertEqual(config.read_bytes(), before)

    def test_unmanaged_alias_rejected_before_key_creation(self):
        ssh = self.home/'.ssh'; ssh.mkdir()
        (ssh/'config').write_text('Host fillstation-deploy\n HostName different\n')
        code, _, _ = self.invoke(); self.assertEqual(code, 1)
        self.assertFalse((ssh/'fill-station-deploy_ed25519').exists())

    def test_invalid_or_multiline_key_rejected_without_writes(self):
        self.public.write_text(self.public.read_text()+'Host evil\n')
        code, _, _ = self.invoke(); self.assertEqual(code, 1)
        self.assertFalse((self.home/'.ssh').exists())

    def test_symlink_config_is_not_overwritten(self):
        ssh = self.home/'.ssh'; ssh.mkdir()
        target = self.home/'other-config'; target.write_text('original')
        (ssh/'config').symlink_to(target)
        code, _, _ = self.invoke(); self.assertEqual(code, 1)
        self.assertEqual(target.read_text(), 'original')

if __name__ == '__main__':
    unittest.main()
