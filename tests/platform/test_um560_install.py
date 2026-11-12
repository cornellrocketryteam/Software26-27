"""Offline install helper: reject wrong mounts and never select/format a disk."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'tools/platform/install-um560.sh'


class InstallHelperTests(unittest.TestCase):
    def run_helper(self, args=(), root_label='CRT-GS-ROOT', root_type='ext4',
                   efi_label='CRT-GS-EFI', efi_type='vfat', uid='0', mounted=True):
        self.assertTrue(SCRIPT.exists(), 'offline installation helper is missing')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            events = base / 'events'
            commands = {
                'id': 'printf "%s\\n" "$TEST_UID"',
                'mountpoint': 'test "$TEST_MOUNTED" = yes',
                'findmnt': '''case "$*" in
                  *LABEL*'/mnt/boot') printf '%s\\n' "$TEST_EFI_LABEL";;
                  *FSTYPE*'/mnt/boot') printf '%s\\n' "$TEST_EFI_TYPE";;
                  *LABEL*'/mnt') printf '%s\\n' "$TEST_ROOT_LABEL";;
                  *FSTYPE*'/mnt') printf '%s\\n' "$TEST_ROOT_TYPE";;
                  *) exit 97;; esac''',
                'nix': 'printf "copy %s\\n" "$*" >> "$TEST_EVENTS"',
                'nixos-install': 'printf "install %s\\n" "$*" >> "$TEST_EVENTS"',
                'nixos-enter': 'printf "enter %s\\n" "$*" >> "$TEST_EVENTS"',
            }
            for name, body in commands.items():
                p = base / name
                p.write_text('#!/bin/sh\n' + body + '\n')
                p.chmod(0o755)
            script = base / 'helper'
            script.write_text(SCRIPT.read_text().replace('@system@', '/nix/store/fixture-system'))
            env = dict(os.environ, PATH=str(base) + ':' + os.environ['PATH'],
                       TEST_UID=uid, TEST_MOUNTED='yes' if mounted else 'no',
                       TEST_ROOT_LABEL=root_label, TEST_ROOT_TYPE=root_type,
                       TEST_EFI_LABEL=efi_label, TEST_EFI_TYPE=efi_type,
                       TEST_EVENTS=str(events))
            result = subprocess.run(['bash', str(script), *args], env=env,
                                    capture_output=True, text=True)
            return result, events.read_text() if events.exists() else ''

    def test_default_does_not_install(self):
        result, events = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--install', result.stdout)
        self.assertEqual(events, '')

    def test_check_does_not_install(self):
        result, events = self.run_helper(['--check'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, '')

    def test_invalid_targets_cannot_install(self):
        for options in [dict(root_label='ubuntu'), dict(root_type='btrfs'),
                        dict(efi_label='OTHER'), dict(efi_type='ext4'),
                        dict(uid='1000'), dict(mounted=False)]:
            with self.subTest(options=options):
                result, events = self.run_helper(['--install'], **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, '')

    def test_unknown_argument_cannot_install(self):
        result, events = self.run_helper(['--erase'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, '')

    def test_install_prebuilt_offline_then_set_local_admin_password(self):
        result, events = self.run_helper(['--install'])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = events.splitlines()
        self.assertEqual(len(lines), 3, events)
        self.assertIn('copy --extra-experimental-features nix-command copy --offline --no-check-sigs --to local?root=/mnt /nix/store/fixture-system', lines[0])
        self.assertIn('--system /nix/store/fixture-system', lines[1])
        self.assertIn('--no-channel-copy', lines[1])
        self.assertIn('--no-root-passwd', lines[1])
        self.assertIn('--option substitute false', lines[1])
        self.assertIn('--option builders ', lines[1])
        self.assertEqual(lines[2], 'enter --root /mnt --command passwd ground-admin')


if __name__ == '__main__':
    unittest.main()
