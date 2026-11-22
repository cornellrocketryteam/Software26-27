"""Strict station health and explicitly requested read-only probing."""
import json
import shlex

from test_build_cli import BuildFixture


class WorkerClientTests(BuildFixture):
    def test_malformed_health_never_starts_a_remote_build(self):
        self.station_config()
        for change in ({'protocol':True}, {'platforms':'aarch64-linux'},
                       {'platforms':['aarch64-linux','unknown-system']}, {'freeBytes':True},
                       {'workerId':'../wrong'}, {'workerId':None}):
            with self.subTest(change=change):
                result = self.build('--artifact', 'fit', '--builder', 'station', HEALTH_OVERRIDE=json.dumps(change))
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('build' in r for r in self.calls('nix')))

    def test_pinned_worker_identity_must_match(self):
        config = self.station_config()
        config['station']['workerId'] = 'expected-worker'
        self.config.write_text(json.dumps(config))
        result = self.build('--artifact','fit','--builder','station')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity', result.stderr)
        self.assertFalse(any('build' in r for r in self.calls('nix')))

    def test_check_station_observes_unvalidated_configuration_without_building(self):
        config = self.station_config()
        config['station']['validated'] = False
        self.config.write_text(json.dumps(config))
        result = self.run_cli('check','--station','--build-platform','x86_64-linux')
        self.assert_ok(result)
        report = json.loads(result.stdout)
        self.assertIs(report['stationValidated'], False)
        self.assertEqual(report['station']['workerId'], 'fixture-worker')
        self.assertEqual(report['requestedBuildPlatform'], 'x86_64-linux')
        self.assertFalse(self.state.exists())
        self.assertTrue(all(c[-1]=='crt-platform-builder-health-v1' for c in self.calls('ssh')))
        self.assertFalse(any('build' in c or 'copy' in c for c in self.calls('nix')))

    def test_check_station_can_report_healthy_station_with_local_builder_down(self):
        self.station_config()
        result = self.run_cli('check','--station', LOCAL_DOWN='1')
        self.assert_ok(result)
        self.assertIn('unavailable', json.loads(result.stdout)['local'])

    def test_station_retention_requires_an_explicit_pinned_worker_identity(self):
        self.station_config()
        result = self.build('--artifact', 'fit', '--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pinned workerId', result.stderr)
        self.assertFalse(any('build' in call for call in self.calls('nix')))
        self.assertEqual(self.manifests(), [])


    def test_explicit_worker_key_is_used_for_health_retention_and_copy_back(self):
        config = self.station_config(worker_id='fixture-worker')
        key = self.base / 'worker key'
        key.write_text('private fixture'); key.chmod(0o600)
        config['station']['identityFile'] = str(key)
        self.config.write_text(json.dumps(config))
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'station'))
        calls = self.calls('ssh')
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call[call.index('-i')+1], str(key))
            self.assertIn('IdentityAgent=none', call)
        options = [shlex.split(json.loads(line)) for line in (self.base/'import-ssh-options').read_text().splitlines()]
        self.assertTrue(options)
        for opts in options:
            self.assertEqual(opts[opts.index('-i')+1], str(key))
            self.assertIn('IdentitiesOnly=yes', opts)

    def test_missing_explicit_worker_key_fails_before_network_or_build(self):
        config = self.station_config(worker_id='fixture-worker')
        config['station']['identityFile'] = str(self.base/'missing-key')
        self.config.write_text(json.dumps(config))
        result = self.build('--artifact', 'fit', '--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identityFile', result.stderr)
        self.assertEqual(self.calls('ssh'), [])
        self.assertFalse(any('build' in call for call in self.calls('nix')))
