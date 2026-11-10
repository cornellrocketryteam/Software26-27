"""Worker policy/lifecycle tests with temporary locks and modeled local Nix."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / 'bin'; self.bin.mkdir()
        self.lock = self.base / 'session.lock'; self.lock.touch()
        self.marker = self.base / 'field-mode'
        self.binfmt = self.base / 'binfmt'; self.binfmt.mkdir()
        self.policy = {'protocol': 1, 'enabled': True, 'validated': True,
                       'remoteEnabled': True, 'fieldMode': False,
                       'minimumFreeBytes': 1, 'platforms': ['x86_64-linux'],
                       'workerId': 'fixture-worker', 'sessionTimeoutSeconds': 30}
        self.policy_path = self.base / 'policy.json'
        nix = self.bin / 'nix'
        nix.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
if os.environ.get('NIX_DOWN'): sys.exit(1)
if sys.argv[1:3] == ['store', 'ping']: print('{}')
elif sys.argv[1:3] == ['config', 'show']:
    if os.environ.get('BAD_SETTINGS'): print('not-json'); sys.exit(0)
    print(json.dumps({'system': {'value': os.environ.get('NATIVE_SYSTEM','x86_64-linux')},
                      'extra-platforms': {'value': ['aarch64-linux'] if os.environ.get('ARM') else []}}))
else: sys.exit(2)
''')
        nix.chmod(0o755)
        self.daemon = self.bin / 'nix-daemon'
        self.daemon.write_text('#!' + sys.executable + '\n' + '''
import os, pathlib, sys, time
assert sys.argv[1:] == ['--stdio', '--store', 'unix:///nix/var/nix/daemon-socket/socket']
pathlib.Path(os.environ['CHILD_PID_FILE']).write_text(str(os.getpid()))
sys.stdout.buffer.write(b'stdio-started\\n'); sys.stdout.buffer.flush()
if os.environ.get('GUARD_SLEEP'): time.sleep(20)
sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stdout.buffer.flush()
''')
        self.daemon.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'PYTHONDONTWRITEBYTECODE': '1', 'CHILD_PID_FILE': str(self.base/'child.pid')}

    def command(self, mode):
        self.policy_path.write_text(json.dumps(self.policy))
        return [sys.executable, '-m', 'tools.platform.worker', '--policy', str(self.policy_path),
                '--lock', str(self.lock), '--field-marker', str(self.marker),
                '--store-path', str(self.base), '--binfmt-root', str(self.binfmt),
                '--daemon-program', str(self.daemon), mode]

    def run_worker(self, mode='health', data=b'', **env):
        return subprocess.run(self.command(mode), cwd=REPO, env={**self.env, **env},
                              input=data, capture_output=True, timeout=12)

    def health(self, **env):
        result = self.run_worker(**env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_worker_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.platform.worker'),
                             'worker health/admission helper has not been implemented')

    def test_healthy_worker_reports_runtime_identity_and_capacity(self):
        h = self.health()
        self.assertIs(h['available'], True)
        self.assertEqual(h['protocol'], 1)
        self.assertEqual(h['workerId'], 'fixture-worker')
        self.assertEqual(h['operationalMode'], 'maintenance')
        self.assertEqual(h['platforms'], ['x86_64-linux'])
        self.assertGreater(h['freeBytes'], 0)

    def test_disabled_unvalidated_field_and_disk_states_deny_health_and_guard(self):
        for change in ({'enabled': False}, {'validated': False}, {'fieldMode': True},
                       {'remoteEnabled': False}, {'workerId': None},
                       {'minimumFreeBytes': 2**63-1}):
            with self.subTest(change=change):
                previous = self.policy.copy(); self.policy.update(change)
                self.assertIs(self.health()['available'], False)
                self.assertNotEqual(self.run_worker('guard').returncode, 0)
                self.assertFalse((self.base/'child.pid').exists())
                self.policy = previous

    def test_runtime_field_marker_inhibits_admission(self):
        self.assertTrue(self.health()['available'])
        self.marker.touch()
        h = self.health()
        self.assertFalse(h['available'])
        self.assertEqual(h['operationalMode'], 'field')
        self.assertNotEqual(self.run_worker('admit').returncode, 0)
        self.assertNotEqual(self.run_worker('guard').returncode, 0)
        self.assertFalse((self.base/'child.pid').exists())

    def test_daemon_failure_and_invalid_or_wrong_native_settings_deny_worker(self):
        for env in ({'NIX_DOWN':'1'}, {'BAD_SETTINGS':'1'}, {'NATIVE_SYSTEM':'aarch64-darwin'}):
            with self.subTest(env=env): self.assertFalse(self.health(**env)['available'])

    def test_arm_requires_configured_validated_declaration_and_live_binfmt(self):
        self.policy['platforms'].append('aarch64-linux')
        self.assertEqual(self.health(ARM='1')['platforms'], ['x86_64-linux'])
        interpreter = self.base/'qemu-aarch64'; interpreter.write_text('fixture'); interpreter.chmod(0o755)
        entry = self.binfmt/'aarch64-linux'
        entry.write_text(f'enabled\ninterpreter {interpreter}\nflags: PF\n')
        self.assertEqual(self.health(ARM='1')['platforms'], ['x86_64-linux','aarch64-linux'])
        self.assertEqual(self.health()['platforms'], ['x86_64-linux'])
        entry.write_text(f'disabled\ninterpreter {interpreter}\nflags: PF\n')
        self.assertEqual(self.health(ARM='1')['platforms'], ['x86_64-linux'])

    def test_admit_is_local_policy_only_no_daemon_or_session_lock_dependency(self):
        import fcntl
        self.policy['remoteEnabled'] = False
        with self.lock.open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_worker('admit', NIX_DOWN='1')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_and_symlink_lock_fail_closed(self):
        self.lock.unlink()
        self.assertFalse(self.health()['available'])
        other = self.base/'other'; other.touch(); self.lock.symlink_to(other)
        self.assertFalse(self.health()['available'])

    def test_guard_forwards_stdio_without_interpreting_it(self):
        result = self.run_worker('guard', data=b'fixture RPC bytes\x00;$(not-a-command)')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'stdio-started\nfixture RPC bytes\x00;$(not-a-command)')

    def start_guard(self):
        process = subprocess.Popen(self.command('guard'), cwd=REPO, env={**self.env,'GUARD_SLEEP':'1'},
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.assertEqual(process.stdout.readline(), b'stdio-started\n')
        return process

    def test_busy_session_is_denied_and_signal_releases_lock_and_child(self):
        process = self.start_guard()
        self.assertFalse(self.health()['available'])
        self.assertNotEqual(self.run_worker('guard').returncode, 0)
        child_pid = int((self.base/'child.pid').read_text())
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=8)
        self.assertNotEqual(process.returncode, 0)
        with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
        self.assertTrue(self.health()['available'])

    def test_session_deadline_terminates_child_and_releases_lock(self):
        self.policy['sessionTimeoutSeconds'] = 1
        result = self.run_worker('guard', GUARD_SLEEP='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'timed out', result.stderr)
        self.assertTrue(self.health()['available'])

    def test_killed_guard_cannot_leave_an_admitted_orphan_session(self):
        process = self.start_guard()
        child_pid = int((self.base/'child.pid').read_text())
        process.kill(); process.wait(timeout=3)
        try:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                pass  # Linux parent-death control may already have reaped it.
            else:
                available = self.health()['available']
                if sys.platform == 'linux' and available:
                    process.communicate(timeout=3)  # An exited child may briefly be a zombie.
                else:
                    self.assertFalse(available)
                    self.assertNotEqual(self.run_worker('guard').returncode, 0)
        finally:
            try: os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.communicate(timeout=3)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux parent-death syscall needs a Linux worker')
    def test_linux_parent_death_terminates_stdio_child(self):
        import time
        process = self.start_guard()
        process.kill(); process.wait(timeout=3)
        process.communicate(timeout=3)  # Child must close inherited pipes without operator cleanup.
        deadline = time.monotonic() + 2
        while not self.health()['available'] and time.monotonic() < deadline: time.sleep(0.02)
        self.assertTrue(self.health()['available'])

    def test_malformed_policy_is_rejected(self):
        for change in ({'protocol':True}, {'enabled':1}, {'minimumFreeBytes':True},
                       {'platforms':'x86_64-linux'}, {'workerId':'../bad'},
                       {'sessionTimeoutSeconds':86401}):
            with self.subTest(change=change):
                old = self.policy.copy(); self.policy.update(change)
                self.assertNotEqual(self.run_worker().returncode, 0)
                self.policy = old

    def test_missing_worker_id_is_a_named_policy_error(self):
        del self.policy['workerId']
        result = self.run_worker()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'Traceback', result.stderr)
        self.assertIn(b'workerId', result.stderr)
