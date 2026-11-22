"""Explicit worker/archive identities with real local OpenSSH config inspection."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from tools.platform.config import endpoint, ssh_environment
from tools.platform.runtime import PlatformError


class EndpointIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.known = self.root/'known hosts'
        self.known.write_text('fixture host pin\n')
        self.key = self.root/'worker identity'
        self.key.write_text('private fixture, never printed')
        self.key.chmod(0o600)
        self.section = {'store':'ssh-ng://ground-builder@station.invalid',
                        'sshTarget':'ground-builder@station.invalid',
                        'knownHosts':str(self.known), 'identityFile':str(self.key)}

    def test_explicit_identity_disables_agent_and_survives_nix_option_encoding(self):
        _, target, options = endpoint(self.section)
        self.assertIn('-i', options)
        self.assertEqual(options[options.index('-i')+1], str(self.key))
        env = ssh_environment(options)
        self.assertEqual(shlex.split(env['NIX_SSHOPTS']), options)
        config = subprocess.check_output(['ssh','-G',*options,'--',target],text=True,stderr=subprocess.DEVNULL)
        for setting in ('identitiesonly yes', 'identityagent none', 'forwardagent no'):
            self.assertIn(setting, config)
        self.assertIn('identityfile '+str(self.key), config)
        self.assertNotIn('private fixture', env['NIX_SSHOPTS'])

    def test_absent_field_preserves_existing_agent_compatibility(self):
        self.section.pop('identityFile')
        _, _, options = endpoint(self.section)
        self.assertNotIn('-i', options)
        self.assertNotIn('IdentityAgent=none', options)

    def test_invalid_identity_is_rejected_before_any_connection(self):
        for value in (None, True, 42, '', 'relative-key', str(self.root/'missing'), str(self.root)):
            with self.subTest(value=value):
                self.section['identityFile'] = value
                with self.assertRaisesRegex(PlatformError, 'identityFile'):
                    endpoint(self.section)

    def test_readable_by_other_users_key_is_rejected(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(PlatformError, 'identityFile'):
            endpoint(self.section)

    def test_symlink_key_is_rejected(self):
        alias = self.root/'alias'; alias.symlink_to(self.key)
        self.section['identityFile'] = str(alias)
        with self.assertRaisesRegex(PlatformError, 'identityFile'):
            endpoint(self.section)

    @unittest.skipUnless(shutil.which('nix'), 'Nix transport option check needs local Nix')
    def test_real_nix_transport_receives_explicit_identity_without_network(self):
        _, _, options = endpoint(self.section)
        # Nix execs this capture-only SSH stub. No socket or real SSH is opened.
        fake = self.root/'bin'; fake.mkdir()
        log = self.root/'ssh-argv'
        stub = fake/'ssh'
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE_SSH"\nexit 255\n')
        stub.chmod(0o755)
        env = {**ssh_environment(options), 'PATH':str(fake)+os.pathsep+os.environ['PATH'],
               'CAPTURE_SSH':str(log)}
        result = subprocess.run(['nix','--extra-experimental-features','nix-command','store','ping',
                                 '--store',self.section['store']],env=env,text=True,capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode, 0)  # Capture-only stub cannot speak Nix RPC.
        argv = log.read_text().splitlines()
        self.assertIn('-i', argv)
        self.assertEqual(argv[argv.index('-i')+1], str(self.key))
        self.assertIn('IdentityAgent=none', argv)
        self.assertIn('UserKnownHostsFile='+str(self.known), argv)

if __name__ == '__main__':
    unittest.main()
