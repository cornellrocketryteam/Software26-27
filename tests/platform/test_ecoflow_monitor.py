import sys
from pathlib import Path
import unittest
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ground-station/network-devices'))
from ecoflow_monitor import Monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.result = {'state': 'cloud-snapshot', 'batteryPercent': 50, 'inputWatts': 0, 'outputWatts': 10}
        self.monitor = Monitor(lambda: self.result, interval=30, clock=lambda: self.now)

    def test_pending_then_snapshot_then_stale(self):
        self.assertEqual(self.monitor.snapshot()['state'], 'pending')
        self.monitor.tick()
        self.assertEqual(self.monitor.snapshot()['batteryPercent'], 50)
        self.now = 100
        self.assertEqual(self.monitor.snapshot()['state'], 'stale')
        self.assertIsNone(self.monitor.snapshot()['batteryPercent'])

    def test_failure_clears_old_readings_and_recovers(self):
        self.monitor.tick()
        self.monitor.fetch = lambda: (_ for _ in ()).throw(RuntimeError('SECRET'))
        self.monitor.tick()
        self.assertEqual(self.monitor.snapshot()['state'], 'unavailable')
        self.assertIsNone(self.monitor.snapshot()['outputWatts'])
        self.assertNotIn('SECRET', str(self.monitor.snapshot()))
        self.monitor.fetch = lambda: self.result
        self.monitor.tick()
        self.assertEqual(self.monitor.snapshot()['state'], 'cloud-snapshot')

    def test_offline_and_cached_reads(self):
        self.result = {'state': 'cloud-reports-offline'}
        self.monitor.tick()
        self.monitor.fetch = lambda: self.fail('snapshot must not fetch')
        self.assertEqual(self.monitor.snapshot()['state'], 'cloud-reports-offline')
        self.assertIsNone(self.monitor.snapshot()['batteryPercent'])

    def test_invalid_snapshot_is_unavailable(self):
        self.result = {'state': 'cloud-snapshot', 'batteryPercent': True}
        self.monitor.tick()
        self.assertEqual(self.monitor.snapshot()['state'], 'unavailable')

    def test_blocked_cloud_does_not_block_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        def fetch():
            entered.set()
            release.wait(2)
            return self.result
        self.monitor.fetch = fetch
        worker = threading.Thread(target=self.monitor.tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.monitor.snapshot()['state'], 'pending')
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_snapshot_copies_only_allowlisted_fields(self):
        self.result.update(secretKey='not-for-browser', sn='private-serial')
        self.monitor.tick()
        self.assertNotIn('secretKey', self.monitor.snapshot())
        self.assertNotIn('sn', self.monitor.snapshot())

if __name__ == '__main__':
    unittest.main()
