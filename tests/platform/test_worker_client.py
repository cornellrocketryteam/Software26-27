"""Strict station health and explicitly requested read-only probing."""
import json

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

    def test_matching_worker_identity_preserves_station_build_route(self):
        config = self.station_config()
        config['station']['workerId'] = 'fixture-worker'
        self.config.write_text(json.dumps(config))
        self.assert_ok(self.build('--artifact','fit','--builder','station'))
        self.assertEqual(self.manifests()[0]['build']['worker'], 'station')
