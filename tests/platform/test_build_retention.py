"""Retention transfer ordering and crash recovery; no external processes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.platform import build
from tools.platform.runtime import PlatformError, atomic_json

DRV = '/nix/store/' + 'a' * 32 + '-fixture.drv'
OUT = '/nix/store/' + 'b' * 32 + '-fixture'


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.root = self.state / 'roots' / 'release' / 'fit'
        self.root.parent.mkdir(parents=True)
        known = self.state / 'known_hosts'; known.write_text('pinned fixture')
        self.station = {'store': 'ssh-ng://worker@host', 'sshTarget': 'worker@host', 'knownHosts': str(known)}
        self.record = {'protocol': 1, 'action': 'realise', 'workerId': 'worker',
                       'token': 'a' * 32, 'drvPath': DRV, 'storePath': OUT,
                       'gcRoot': str(self.root), 'station': self.station}
        self.journal = self.state / 'transfers' / 'a.json'
        atomic_json(self.journal, self.record)
        self.events = []

    def fake_run(self, argv, **kw):
        self.events.append([str(x) for x in argv])
        if '--realise' in argv:
            self.root.symlink_to(OUT)
            return OUT
        if '--roots' in argv:
            return str(self.root) + ' -> ' + OUT + '\n'
        return ''

    def test_root_before_release_and_no_copy_then_root_gap(self):
        with patch.object(build, 'run', side_effect=self.fake_run), \
                patch.object(build, '_retention_rpc', return_value={'released': True}) as rpc:
            build.finish_transfer(self.journal, self.record, {}, None)
        self.assertFalse(self.journal.exists())
        self.assertTrue(self.root.is_symlink())
        self.assertTrue(any('--realise' in c and '--add-root' in c and 'substituters' in c for c in self.events))
        self.assertFalse(any('copy' in c for c in self.events))
        self.assertEqual(rpc.call_args.args[1]['action'], 'release')

    def test_failed_registration_does_not_release(self):
        with patch.object(build, 'run', return_value=''), patch.object(build, '_retention_rpc') as rpc:
            with self.assertRaises(PlatformError):
                build.finish_transfer(self.journal, self.record, {}, None)
        rpc.assert_not_called()
        self.assertTrue(self.journal.exists())

    def test_lost_release_ack_keeps_journal_and_local_root(self):
        with patch.object(build, 'run', side_effect=self.fake_run), \
                patch.object(build, '_retention_rpc', side_effect=PlatformError('disconnect')):
            with self.assertRaisesRegex(PlatformError, 'disconnect'):
                build.finish_transfer(self.journal, self.record, {}, None)
        self.assertTrue(self.journal.exists())
        self.assertTrue(self.root.is_symlink())

    def test_unregistered_symlink_never_authorizes_release(self):
        self.root.symlink_to(OUT)
        with patch.object(build, 'run', return_value=''), patch.object(build, '_retention_rpc') as rpc:
            with self.assertRaises(PlatformError):
                build.finish_transfer(self.journal, self.record, {}, None)
        rpc.assert_not_called()

    def test_recovery_after_lost_release_ack_does_not_realise_worker_again(self):
        with patch.object(build, 'run', side_effect=self.fake_run), \
                patch.object(build, '_retention_rpc', return_value={'released': True}) as rpc:
            build.recover_transfers(self.state, {})
        self.assertEqual([c.args[1]['action'] for c in rpc.call_args_list], ['release'])
        self.assertFalse(self.journal.exists())

    def test_recovery_after_lost_realise_reply_reuses_durable_token(self):
        self.record.pop('storePath')
        atomic_json(self.journal, self.record)
        def rpc(station, request, timeout, log=None):
            self.assertEqual(request['token'], self.record['token'])
            self.assertTrue(self.journal.exists())
            return {'storePath': OUT, 'retained': True} if request['action'] == 'realise' else {'released': True}
        with patch.object(build, 'run', side_effect=self.fake_run), \
                patch.object(build, '_retention_rpc', side_effect=rpc) as calls:
            build.recover_transfers(self.state, {})
        self.assertEqual([c.args[1]['action'] for c in calls.call_args_list], ['realise', 'release'])
        self.assertFalse(self.journal.exists())

    def test_offline_build_never_replays_remote_transfers(self):
        from types import SimpleNamespace
        args = SimpleNamespace(dry_run=False, offline=True)
        with patch.object(build, '_execute', return_value={}), \
                patch.object(build, 'recover_transfers') as recover:
            build.execute(self.state, self.state, {}, args)
        recover.assert_not_called()

    def test_rpc_rejects_identity_mismatch_and_oversize(self):
        request = {k: self.record[k] for k in ('protocol', 'action', 'workerId', 'token', 'drvPath')}
        for response in ({**request, 'retained': True, 'storePath': OUT, 'workerId': 'wrong'},
                         {**request, 'retained': True, 'storePath': '/tmp/output'},
                         {**request, 'retained': True, 'storePath': OUT, 'protocol': True},
                         {**request, 'retained': True, 'storePath': OUT, 'unknown': True}):
            with patch.object(build, 'endpoint', return_value=('ssh-ng://worker@host', 'worker@host', [])), \
                    patch.object(build, 'run', return_value=json.dumps(response)), self.assertRaises(PlatformError):
                build._retention_rpc({}, request, 3)
    def test_rpc_rejects_oversize_and_duplicate_response_keys(self):
        request = {k: self.record[k] for k in ('protocol', 'action', 'workerId', 'token', 'drvPath')}
        for raw in (' ' * 4097, '{"protocol":1,"protocol":1}'):
            with patch.object(build, 'endpoint', return_value=('ssh-ng://worker@host', 'worker@host', [])), \
                    patch.object(build, 'run', return_value=raw), self.assertRaises(PlatformError):
                build._retention_rpc({}, request, 3)



class IsolatedNixGCTests(unittest.TestCase):
    """Real import/root/GC semantics, confined to disposable local stores."""
    def test_registered_client_root_survives_gc_after_remote_release(self):
        import shutil
        import subprocess
        if not shutil.which('nix'):
            self.skipTest('Nix is not installed')
        with tempfile.TemporaryDirectory(prefix='retention-gc-') as directory:
            base = Path(directory).resolve()
            remote = 'local?root=' + str(base / 'remote')
            client = 'local?root=' + str(base / 'client')
            cache = 'file://' + str(base / 'cache')
            def nix(*argv):
                result = subprocess.run([str(a) for a in argv], text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()
            fixture = base / 'fixture'; fixture.write_text('retained result')
            control = base / 'control'; control.write_text('unrooted control')
            out = nix('nix', 'store', 'add-file', '--store', remote, fixture)
            unrooted = nix('nix', 'store', 'add-file', '--store', remote, control)
            remote_root = base / 'worker-root'
            nix('nix-store', '--store', remote, '--realise', out, '--add-root', remote_root, '--indirect')
            nix('nix-store', '--store', remote, '--gc')
            self.assertTrue((base / 'remote' / out.lstrip('/')).exists())
            self.assertFalse((base / 'remote' / unrooted.lstrip('/')).exists())
            nix('nix', 'copy', '--from', remote, '--to', cache, out)
            root = base / 'roots' / 'release' / 'fit'
            journal = base / 'transfers' / 'a.json'
            record = {'protocol': 1, 'action': 'realise', 'workerId': 'worker',
                      'token': 'a' * 32, 'drvPath': DRV, 'storePath': out,
                      'gcRoot': str(root), 'station': {}}
            atomic_json(journal, record)
            def local_run(argv, **kw):
                return nix(argv[0], '--store', client, *argv[1:]) + '\n'
            def release(station, request, timeout, log=None):
                self.assertTrue(root.is_symlink())
                remote_root.unlink()
                nix('nix-store', '--store', remote, '--gc')
                return {'released': True}
            with patch.object(build, 'endpoint', return_value=(cache, '', [])), \
                    patch.object(build, 'run', side_effect=local_run), \
                    patch.object(build, '_retention_rpc', side_effect=release):
                build.finish_transfer(journal, record, {}, None)
            nix('nix-store', '--store', client, '--gc')
            self.assertFalse((base / 'remote' / out.lstrip('/')).exists())
            self.assertTrue((base / 'client' / out.lstrip('/')).exists())
            self.assertFalse(journal.exists())


import test_build_cli as cli_fixture


class ProtocolBuildTests(cli_fixture.BuildFixture):
    def setUp(self):
        super().setUp()
        self.state = self.state.resolve()
        config = self.station_config()
        config['station']['workerId'] = 'fixture-worker'
        self.config.write_text(json.dumps(config))
        self.events = []
        self.fail_download = False
        self.lose_ack = False
        self.compiler_error = False

    def protocol_run(self, argv, **kw):
        argv = [str(a) for a in argv]
        self.events.append(argv)
        if argv[:2] == ['nix', 'build'] and '--dry-run' in argv:
            return '[]'
        if argv[:2] == ['nix', 'eval']:
            return DRV
        if argv[0] == 'ssh':
            self.assertEqual(argv[-1], build.RETENTION_COMMAND)
            request = json.loads(kw['input_data'])
            records = [json.loads(p.read_text()) for p in (self.state / 'transfers').glob('*.json')]
            self.assertTrue(any(r['token'] == request['token'] for r in records))
            if request['action'] == 'realise':
                if self.compiler_error: raise PlatformError('compiler error')
                return json.dumps({**request, 'retained': True, 'storePath': OUT})
            if self.lose_ack: raise PlatformError('lost release reply')
            return json.dumps({**request, 'released': True})
        if argv[0] == 'nix-store':
            if '--realise' in argv:
                if self.fail_download: raise PlatformError('download interrupted')
                root = Path(argv[argv.index('--add-root')+1])
                if not root.is_symlink(): root.symlink_to(OUT)
                return str(root)
            if '--check-validity' in argv: return ''
            if '--roots' in argv:
                return ''.join(str(p) + ' -> ' + OUT + '\n' for p in (self.state / 'roots').glob('*/*'))
        self.fail('unexpected build command: ' + repr(argv))

    def invoke(self):
        import contextlib
        import io
        import os
        from tools.platform.cli import main
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env), patch.object(build, 'run', side_effect=self.protocol_run), \
                patch.object(build, 'artifact_files', return_value=[]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(['--config', str(self.config), 'build', 'fill-station', '--vehicle', 'liquid',
                         '--artifact', 'fit', '--builder', 'station'], repo=self.repo)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_station_build_publishes_only_after_local_retention(self):
        code, out, err = self.invoke()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.manifests()[0]['artifacts']['fit']['storePath'], OUT)
        self.assertEqual(list((self.state / 'transfers').glob('*.json')), [])
        self.assertTrue(any('--eval-store' in c for c in self.events))
        self.assertFalse(any('copy' in c for c in self.events))
        self.assertFalse(any(c[:2] == ['nix', 'build'] and '--dry-run' not in c for c in self.events))

    def test_interrupted_download_recovers_without_rebuilding_worker(self):
        self.fail_download = True
        self.assertNotEqual(self.invoke()[0], 0)
        self.assertEqual(self.manifests(), [])
        self.assertEqual(len(list((self.state / 'transfers').glob('*.json'))), 1)
        self.fail_download = False
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(len([c for c in self.events if c[:2] == ['nix', 'eval']]), 2)
        self.assertEqual(list((self.state / 'transfers').glob('*.json')), [])

    def test_compiler_failure_does_not_start_fallback_build(self):
        self.compiler_error = True
        code, out, err = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('compiler error', err)
        self.assertEqual(len([c for c in self.events if c[0] == 'ssh']), 1)
        self.assertEqual(self.manifests(), [])

    def test_lost_release_ack_keeps_local_root_and_pending_journal(self):
        self.lose_ack = True
        self.assertNotEqual(self.invoke()[0], 0)
        record = json.loads(next((self.state / 'transfers').glob('*.json')).read_text())
        self.assertTrue(Path(record['gcRoot']).is_symlink())
        self.assertEqual(self.manifests(), [])
        self.lose_ack = False
        self.assertEqual(self.invoke()[0], 0)
        self.assertTrue(Path(record['gcRoot']).is_symlink())


if __name__ == '__main__':
    unittest.main()
