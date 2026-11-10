import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from test_build_cli import BuildFixture, REPO


class CacheCLI(BuildFixture):
    def cache_config(self):
        conf = self.station_config()
        conf['cache'] = {'store': 'ssh-ng://ingest@station.invalid',
                         'sshTarget': 'ingest@station.invalid',
                         'knownHosts': str(self.base / 'known_hosts')}
        self.config.write_text(json.dumps(conf))

    def pending(self):
        return [r for f in (self.state / 'outbox').glob('*.json')
                if (r := json.loads(f.read_text()))['state'] == 'pending']

    def receipts_config(self):
        self.cache_config()
        config = json.loads(self.config.read_text())
        config['cache']['receiptArchiveId'] = 'station-archive-1'
        self.config.write_text(json.dumps(config))

    def test_verified_receipt_acknowledges_and_keeps_local_release_roots(self):
        self.receipts_config()
        result = self.build('--artifact', 'fit', '--builder', 'local')
        self.assert_ok(result)
        self.assertEqual(json.loads(result.stdout)['publication'], 'acknowledged')
        self.assertEqual(self.pending(), [])
        result = self.run_cli('status'); self.assert_ok(result)
        acknowledged = json.loads(result.stdout)['acknowledged']
        self.assertEqual(len(acknowledged), 1)
        self.assertEqual(acknowledged[0]['receipt']['archiveId'], 'station-archive-1')
        self.assertTrue(all(Path(r).exists() for r in acknowledged[0]['gcRoots']))
        before = len(self.calls())
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(len(self.calls()), before)

    def test_invalid_receipts_and_disconnect_keep_pending_and_all_roots(self):
        self.receipts_config()
        for scenario in ('wrong-digest', 'wrong-archive', 'wrong-paths', 'missing-root', 'not-retained', 'invalid-json'):
            with self.subTest(scenario=scenario):
                self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local', RECEIPT_SCENARIO=scenario))
        self.assertEqual(len(self.pending()), 6)
        self.assertTrue(all(Path(root).exists() for r in self.pending() for root in r['gcRoots']))
        self.assert_ok(self.run_cli('cache-sync', SSH_FAIL='1'))
        self.assertEqual(len(self.pending()), 6)
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(len(self.pending()), 0)

    def test_acknowledged_record_survives_restart_and_manifest_recovery(self):
        self.receipts_config()
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        before = len(self.calls('ssh'))
        for _ in range(2): self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(self.pending(), [])
        self.assertEqual(len(self.calls('ssh')), before)
        record = json.loads(next((self.state / 'outbox').glob('*.json')).read_text())
        self.assertEqual(record['state'], 'acknowledged')
        self.assertTrue(Path(record['manifest']).is_file())

    def test_concurrent_sync_acknowledges_once(self):
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        self.receipts_config()
        code = 'from tools.platform.cli import main; import sys; raise SystemExit(main(sys.argv[2:], repo=sys.argv[1]))'
        cmd = [sys.executable, '-c', code, str(self.repo), '--config', str(self.config), 'cache-sync']
        processes = [subprocess.Popen(cmd, cwd=REPO, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, out + err)
        receipts = [c for c in self.calls('ssh') if c[-1] == 'crt-platform-cache-receive-v1']
        self.assertEqual(len(receipts), 1)
        self.assertEqual(self.pending(), [])

    def test_failed_local_ack_persistence_keeps_pending_for_restart(self):
        from tools.platform import cache
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        self.receipts_config()
        original = cache.atomic_json
        def interrupt(path, value):
            if value.get('state') == 'acknowledged': raise OSError('interrupted acknowledgement')
            return original(path, value)
        with patch.dict('os.environ', self.env), patch.object(cache, 'atomic_json', side_effect=interrupt):
            with self.assertRaises(OSError): cache.sync(self.state, json.loads(self.config.read_text()))
        self.assertEqual(len(self.pending()), 1)
        self.assertTrue(all(Path(p).exists() for p in self.pending()[0]['gcRoots']))
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(self.pending(), [])

    def test_copy_failure_keeps_success_and_pins_then_sync_retries(self):
        self.cache_config()
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local', COPY_FAIL='1'))
        self.assertEqual(len(self.pending()), 1)
        record = self.pending()[0]
        self.assertEqual(record['state'], 'pending')
        self.assertIn('copy', record['reason'])
        self.assertTrue(all(Path(r).is_symlink() for r in record['gcRoots']))
        result = self.run_cli('cache-sync'); self.assert_ok(result)
        self.assertEqual(len(self.pending()), 1)
        self.assertIn('receipt', self.pending()[0]['reason'])
        self.assertTrue(any('--to' in r for r in self.calls('nix')))
        self.assertTrue(list((self.base / 'remote').iterdir()))

    def test_next_build_retries_old_record_and_new_record(self):
        self.assert_ok(self.build('--artifact', 'fit'))
        self.cache_config()
        self.assert_ok(self.build('--artifact', 'sd', '--builder', 'local'))
        copies = [r for r in self.calls('nix') if 'copy' in r and '--to' in r]
        self.assertEqual(len(copies), 2)
        self.assertEqual(len(self.pending()), 2)

    def test_sync_idempotent_pending_without_receiver_and_lock_never_deadlocks(self):
        self.cache_config()
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        for _ in range(2): self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.pending()[0]['state'], 'pending')
        self.assertTrue(all(Path(p).exists() for p in self.pending()[0]['gcRoots']))

    def test_concurrent_sync_has_atomic_records(self):
        self.cache_config()
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        code = 'from tools.platform.cli import main; import sys; raise SystemExit(main(sys.argv[2:], repo=sys.argv[1]))'
        cmd = [sys.executable, '-c', code, str(self.repo), '--config', str(self.config), 'cache-sync']
        processes = [subprocess.Popen(cmd, cwd=REPO, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, out + err)
        self.assertEqual(len(self.pending()), 1)
        self.assertFalse(list((self.state / 'outbox').glob('*.tmp')))

    def test_no_cache_configuration_never_runs_ssh_and_retains_outbox(self):
        self.assert_ok(self.build('--artifact', 'fit'))
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(self.calls('ssh'), [])
        self.assertEqual(len(self.pending()), 1)
        self.assertIn('configured', self.pending()[0]['reason'])

    def test_corrupt_record_is_reported_and_never_removed(self):
        box = self.state / 'outbox'; box.mkdir(parents=True)
        bad = box / 'broken.json'; bad.write_text('{')
        result = self.run_cli('cache-sync')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(bad.exists())
        self.assertIn('broken.json', result.stderr)

    def test_unrelated_corrupt_publication_record_does_not_fail_new_local_build(self):
        box = self.state / 'outbox'; box.mkdir(parents=True)
        bad = box / 'broken.json'; bad.write_text('{')
        result = self.build('--artifact', 'fit', '--builder', 'local')
        self.assert_ok(result)
        record = json.loads(result.stdout)
        self.assertEqual(record['publication'], 'pending')
        self.assertIn('broken.json', record['warning'])
        self.assertTrue(bad.exists())

    def test_manifest_before_outbox_crash_is_recovered_on_sync(self):
        self.assert_ok(self.build('--artifact', 'fit'))
        manifest = Path(self.pending()[0]['manifest'])
        self.assertTrue(manifest.is_file())
        for path in (self.state / 'outbox').glob('*.json'): path.unlink()
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.pending()[0]['manifest'], str(manifest))

    def test_output_links_are_disposable_but_state_and_registered_gc_roots_survive(self):
        self.assert_ok(self.build('--artifact', 'fit'))
        record = self.pending()[0]
        import shutil
        shutil.rmtree(self.repo / 'outputs')
        result = subprocess.run([str(self.bin / 'nix-store'), '--gc'], env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assert_ok(result)
        self.assertTrue(Path(record['manifest']).is_file())
        self.assertTrue(all(Path(p).exists() for p in record['storePaths']))
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertEqual(len(self.pending()), 1)

    def test_changed_manifest_and_wrong_gc_root_block_copy(self):
        self.cache_config()
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local'))
        record = self.pending()[0]
        count = len([r for r in self.calls('nix') if 'copy' in r])
        manifest = Path(record['manifest']); manifest.write_text(manifest.read_text() + ' ')
        self.assert_ok(self.run_cli('cache-sync'))
        self.assertIn('digest changed', self.pending()[0]['reason'])
        self.assertEqual(len([r for r in self.calls('nix') if 'copy' in r]), count)

    def test_publication_timeout_retains_success(self):
        self.cache_config()
        config = json.loads(self.config.read_text()); config['policy']['copyTimeoutSeconds'] = 2
        self.config.write_text(json.dumps(config))
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local', COPY_SLEEP='1'))
        self.assertIn('timed out', self.pending()[0]['reason'])
        self.assertTrue(all(Path(p).exists() for p in self.pending()[0]['gcRoots']))
