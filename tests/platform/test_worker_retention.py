"""Bounded retention without SSH, a daemon, or production store access."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.platform import worker
from tools.platform.runtime import PlatformError

DRV = '/nix/store/' + 'a' * 32 + '-fixture.drv'
OUT = '/nix/store/' + 'b' * 32 + '-fixture'


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.lock = self.base / 'lock'; self.lock.touch()
        self.state = self.base / 'retention'; self.state.mkdir()
        run_patch = patch.object(worker, 'run', side_effect=self.fake_query)
        run_patch.start(); self.addCleanup(run_patch.stop)
        self.policy = {'enabled': True, 'validated': True, 'remoteEnabled': True,
                       'workerId': 'fixture', 'fieldMode': False,
                       'minimumFreeBytes': 1, 'sessionTimeoutSeconds': 3}

    def fake_query(self, argv, **kw):
        if '--roots' in argv:
            return ''.join(str(p) + ' -> ' + OUT + '\n' for p in self.state.glob('*/root'))
        if '--outputs' in argv:
            return OUT + '\n'
        return ''

    def test_unregistered_worker_root_is_never_acknowledged(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise), \
                patch.object(worker, 'run', return_value=''):
            with self.assertRaisesRegex(PlatformError, 'registered'):
                self.invoke(self.request())

    def test_nix_realise_prints_root_link_not_store_path(self):
        program = self.base / 'nix-store'
        program.write_text('#!/usr/bin/env python3\nimport sys,os\na=sys.argv\nr=a[a.index("--add-root")+1]\nos.symlink(' + repr(OUT) + ',r)\nprint(r)\n')
        program.chmod(0o755)
        with patch.dict(os.environ, PATH=str(self.base) + os.pathsep + os.environ['PATH']):
            reply = self.invoke(self.request())
        self.assertEqual(reply['storePath'], OUT)

    def request(self, action='realise', token='a' * 32, **changes):
        value = dict(protocol=1, action=action, token=token, workerId='fixture', drvPath=DRV)
        value.update(changes)
        return json.dumps(value).encode()

    def invoke(self, raw, **kw):
        return worker.retain(self.policy, raw, state=self.state, lock=self.lock,
                             field_marker=self.base / 'field', store_path=self.base, **kw)

    def fake_realise(self, drv, root, timeout, lock_fd):
        root.symlink_to(OUT)
        return OUT

    def test_strict_bounded_wire_before_any_state_change(self):
        for raw in (b'x' * 4097, b'[]', b'{"protocol":1,"protocol":1}',
                    self.request(protocol=True), self.request(protocol=2),
                    self.request(token='../escape'), self.request(drvPath='/tmp/fake.drv'),
                    self.request(extra='ignored'), self.request(workerId='other'),
                    self.request(action='shell')):
            with self.subTest(raw=raw[:100]), self.assertRaises(PlatformError):
                self.invoke(raw)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_realise_roots_in_same_operation_and_replays_without_rebuilding(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise) as realise:
            reply = self.invoke(self.request())
            self.assertTrue(reply['retained'])
            self.assertEqual(reply['storePath'], OUT)
            self.assertEqual(self.invoke(self.request()), reply)
            self.assertEqual(realise.call_count, 1)
            self.assertEqual(realise.call_args.args[0], DRV)

    def test_empty_slot_after_interrupted_release_is_recovered(self):
        (self.state / '0').mkdir()
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.assertTrue(self.invoke(self.request(), capacity=1)['retained'])

    def test_capacity_never_evicts_existing_roots(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request(), capacity=1)
            with self.assertRaisesRegex(PlatformError, 'capacity'):
                self.invoke(self.request(token='b' * 32), capacity=1)
        self.assertEqual(len(list(self.state.glob('*/root'))), 1)

    def test_corrupt_slot_state_fails_closed_without_removing_root(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request())
        next(self.state.glob('*/request.json')).write_text('[]')
        with self.assertRaises(PlatformError):
            self.invoke(self.request('release'))
        self.assertEqual(len(list(self.state.glob('*/root'))), 1)

    def test_interrupted_reservation_temporary_file_is_recovered(self):
        slot = self.state / '0'; slot.mkdir()
        (slot / '.request.json.crash.tmp').write_bytes(b'{')
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.assertTrue(self.invoke(self.request(), capacity=1)['retained'])

    def test_conflicting_replay_is_rejected(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request())
            with self.assertRaises(PlatformError):
                self.invoke(self.request(drvPath='/nix/store/' + 'c' * 32 + '-other.drv'))

    def test_release_is_idempotent_and_cannot_remove_another_token(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request())
            self.invoke(self.request('release', token='b' * 32))
            self.assertEqual(len(list(self.state.glob('*/root'))), 1)
            first = self.invoke(self.request('release'))
            self.assertEqual(self.invoke(self.request('release')), first)
            self.assertEqual(list(self.state.glob('*/root')), [])

    def test_failed_realisation_keeps_reservation_for_retry(self):
        with patch.object(worker, '_retained_realise', side_effect=PlatformError('disconnect')):
            with self.assertRaisesRegex(PlatformError, 'disconnect'):
                self.invoke(self.request())
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.assertTrue(self.invoke(self.request(), capacity=1)['retained'])

    def test_delayed_old_release_cannot_delete_reused_slot(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request(), capacity=1)
            self.invoke(self.request('release'), capacity=1)
            self.invoke(self.request(token='b'*32), capacity=1)
            self.invoke(self.request('release'), capacity=1)
        self.assertEqual(len(list(self.state.glob('*/root'))), 1)

    def test_multi_output_derivation_is_rejected_before_realisation(self):
        with patch.object(worker, 'run', return_value=OUT + '\n' + OUT + '-second\n'):
            with self.assertRaisesRegex(PlatformError, 'one statically known'):
                self.invoke(self.request())
        self.assertEqual(list(self.state.glob('*/root')), [])

    def test_field_mode_denies_realise_but_allows_release(self):
        with patch.object(worker, '_retained_realise', side_effect=self.fake_realise):
            self.invoke(self.request())
        self.policy['fieldMode'] = True
        with self.assertRaises(PlatformError):
            self.invoke(self.request(token='b' * 32))
        self.assertTrue(self.invoke(self.request('release'))['released'])


class RetentionProcessTests(unittest.TestCase):
    def setUp(self):
        import test_worker
        test_worker.WorkerTests.setUp(self)
        self.state = self.base / 'retained'; self.state.mkdir()
        self.nix_store = self.bin / 'nix-store'
        self.nix_store.write_text('#!' + __import__('sys').executable + '\n' + r'''
import os, pathlib, sys, time
args = sys.argv[1:]
out = '/nix/store/' + 'b' * 32 + '-fixture'
state = pathlib.Path(os.environ['RETENTION_STATE'])
if '--outputs' in args: print(out)
elif '--realise' in args:
    if os.environ.get('REALISE_SLEEP'):
        pathlib.Path(os.environ['CHILD_PID_FILE']).write_text(str(os.getpid()))
        time.sleep(20)
    root = pathlib.Path(args[args.index('--add-root')+1])
    root.symlink_to(out)
    print(root)
elif '--roots' in args:
    for root in state.glob('*/root'): print(str(root) + ' -> ' + out)
elif '--check-validity' not in args: sys.exit(2)
''')
        self.nix_store.chmod(0o755)
        self.env['RETENTION_STATE'] = str(self.state)

    def command(self):
        import test_worker
        cmd = test_worker.WorkerTests.command(self, 'retain')
        return cmd[:-1] + ['--retention-state', str(self.state), 'retain']

    def wire(self):
        return json.dumps(dict(protocol=1, action='realise', workerId='fixture-worker',
                               token='a'*32, drvPath=DRV)).encode()

    def test_fixed_mode_realises_and_acknowledges_a_registered_root(self):
        import subprocess
        result = subprocess.run(self.command(), env=self.env, input=self.wire(), capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['retained'])

    def test_deadline_reaps_realisation_and_unlocks(self):
        import subprocess
        self.policy['sessionTimeoutSeconds'] = 1
        result = subprocess.run(self.command(), env={**self.env, 'REALISE_SLEEP': '1'},
                                input=self.wire(), capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        pid = int((self.base / 'child.pid').read_text())
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        result = subprocess.run(self.command(), env=self.env, input=self.wire(), capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stalled_request_input_is_bounded(self):
        import subprocess
        process = subprocess.Popen(self.command(), env=self.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.wait(timeout=12)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(b'input timed out', process.stderr.read())
        finally:
            if process.poll() is None: process.kill(); process.wait()
            for stream in (process.stdin, process.stdout, process.stderr): stream.close()


if __name__ == '__main__':
    unittest.main()
