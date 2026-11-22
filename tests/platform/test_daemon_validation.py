"""Administrative daemon probe: fail closed before admitting any build."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.platform.runtime import PlatformError


class DaemonValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.group = self.root / 'system.slice/nix-daemon.service'
        self.group.mkdir(parents=True)
        for key, value in {'cpu.max': '300000 100000', 'memory.max': '6442450944',
                           'memory.swap.max': '0', 'pids.max': '512'}.items():
            (self.group / key).write_text(value)
        self.out = self.root / 'out'
        self.out.mkdir()
        (self.out / 'cgroup').write_text('0::/system.slice/nix-daemon.service\n')
        (self.out / 'user').write_text('non-root\n')
        self.settings = {'enabled': True, 'fieldMode': False, 'fieldMarker': str(self.root / 'field'),
                         'cgroupRoot': str(self.root), 'nix': '/fixture/nix',
                         'systemctl': '/fixture/systemctl',
                         'storePath': str(self.root), 'minimumFreeBytes': 1,
                         'fixtureDrv': '/nix/store/' + 'a' * 32 + '-daemon-validation.drv'}
        self.calls = []

    def execute(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[0] == '/fixture/systemctl':
            return 'ActiveState=active\nControlGroup=/system.slice/nix-daemon.service\n'
        if 'build' in argv:
            return json.dumps([{'outputs': {'out': str(self.out)}}])
        return '{}'

    def validate(self, **kwargs):
        from tools.platform.validation import validate
        return validate(self.settings, execute=self.execute, uid=kwargs.get('uid', 0))

    def test_nonroot_cannot_probe_or_build(self):
        with self.assertRaisesRegex(PlatformError, 'root'):
            self.validate(uid=1000)
        self.assertEqual(self.calls, [])

    def test_disabled_or_field_policy_blocks_before_execution(self):
        for key, value in [('enabled', False), ('fieldMode', True)]:
            with self.subTest(key=key):
                original = self.settings[key]
                self.settings[key] = value
                with self.assertRaises(PlatformError):
                    self.validate()
                self.settings[key] = original
        Path(self.settings['fieldMarker']).touch()
        with self.assertRaises(PlatformError):
            self.validate()
        self.assertEqual(self.calls, [])

    def test_low_disk_space_blocks_before_daemon_execution(self):
        with patch('tools.platform.validation.os.statvfs', return_value=SimpleNamespace(f_bavail=0, f_frsize=4096)):
            with self.assertRaisesRegex(PlatformError, 'free-space'):
                self.validate()
        self.assertEqual(self.calls, [])

    def test_unbounded_or_excessive_cgroup_rejects_without_build(self):
        for name, value in [('cpu.max', 'max 100000'), ('cpu.max', '400000 100000'),
                            ('memory.max', 'max'), ('memory.max', '7000000000'),
                            ('memory.swap.max', '1'), ('pids.max', 'max')]:
            with self.subTest(name=name, value=value):
                path = self.group / name
                old = path.read_text()
                path.write_text(value)
                self.calls.clear()
                with self.assertRaises(PlatformError):
                    self.validate()
                self.assertFalse(any('build' in c[0] for c in self.calls))
                path.write_text(old)

    def test_probe_forces_real_daemon_rebuild_and_preserves_global_policy(self):
        report = self.validate()
        builds = [c[0] for c in self.calls if 'build' in c[0]]
        self.assertEqual(len(builds), 2)
        self.assertIn('--rebuild', builds[1])
        for command in builds:
            self.assertIn('unix:///nix/var/nix/daemon-socket/socket', command)
            self.assertNotIn('local', command)
            self.assertIn(self.settings['fixtureDrv'] + '^*', command)
            self.assertIn('--offline', command)
            self.assertIn('pre-build-hook', command)
        self.assertTrue(report['rebuilt'])
        self.assertFalse(report['workerValidationChanged'])

    def test_fixture_outside_daemon_group_or_root_user_is_rejected(self):
        (self.out / 'cgroup').write_text('0::/user.slice/session.scope\n')
        with self.assertRaisesRegex(PlatformError, 'cgroup'):
            self.validate()
        (self.out / 'cgroup').write_text('0::/system.slice/nix-daemon.service\n')
        (self.out / 'user').write_text('root\n')
        with self.assertRaisesRegex(PlatformError, 'user'):
            self.validate()

    def test_sibling_prefix_is_not_daemon_descendant(self):
        (self.out / 'cgroup').write_text('0::/system.slice/nix-daemon.service-evil\n')
        with self.assertRaises(PlatformError):
            self.validate()

    def test_field_transition_or_limit_change_during_probe_fails(self):
        original = self.execute
        def change(argv, **kwargs):
            result = original(argv, **kwargs)
            if '--rebuild' in argv:
                Path(self.settings['fieldMarker']).touch()
            return result
        self.execute = change
        with self.assertRaises(PlatformError):
            self.validate()
