"""Exercise the actual boot wrapper against isolated sysfs fixtures."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'nix/mixos-modules/fill-station-base/pru-pwm/start.sh'


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sys = self.root / 'sys'
        (self.sys / 'class/remoteproc').mkdir(parents=True)
        (self.sys / 'bus/rpmsg/devices').mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'log'
        self.executable('modprobe', '#!/bin/sh\nprintf "module:%s\\n" "$1" >> "$TEST_LOG"\n')
        self.executable('app', '#!/bin/sh\nprintf "app\\n" >> "$TEST_LOG"\n')

    def executable(self, name, body):
        p = self.bin / name
        p.write_text(body)
        p.chmod(0o755)

    def core(self, core, running=True, firmware=None):
        address = ('30034000', '30038000')[core]
        device = self.sys / f'devices/platform/30000000.icssg/{address}.pru'
        remote = device / 'remoteproc/remoteproc9'
        remote.mkdir(parents=True)
        (remote / 'name').write_text(address + '.pru\n')
        (remote / 'state').write_text('running\n' if running else 'offline\n')
        (remote / 'firmware').write_text(firmware or f'fill-station-pru0_{core}-fw\n')
        (self.sys / f'class/remoteproc/remoteproc{core}').symlink_to(remote)
        service = device / 'virtio0/rpmsg-raw-service'
        service.mkdir(parents=True)
        (service / 'name').write_text('rpmsg-raw\n')
        (service / 'dst').write_text(hex(30 + core) + '\n')
        (self.sys / f'bus/rpmsg/devices/service{core}').symlink_to(service)
        return remote

    def run_wrapper(self, cores='0'):
        self.assertTrue(SCRIPT.exists(), 'PRU startup wrapper missing')
        env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], TEST_LOG=str(self.log), PRU_PWM_WAIT_ATTEMPTS='2')
        return subprocess.run(['sh', str(SCRIPT), str(self.sys), cores, str(self.bin / 'app')], env=env, text=True, capture_output=True)

    def test_only_configured_core_is_required_and_app_starts(self):
        self.core(1)
        result = self.run_wrapper('1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('module:pru_rproc', self.log.read_text())
        self.assertTrue(self.log.read_text().endswith('app\n'))

    def test_running_foreign_firmware_is_never_replaced(self):
        remote = self.core(0, firmware='someone-else-fw\n')
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('firmware', result.stderr)
        self.assertEqual((remote / 'firmware').read_text(), 'someone-else-fw\n')
        self.assertNotIn('app\n', self.log.read_text())

    def test_missing_endpoint_prevents_application_start(self):
        self.core(0)
        (self.sys / 'bus/rpmsg/devices/service0').unlink()
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('RPMsg', result.stderr)
        self.assertNotIn('app\n', self.log.read_text())

    def test_offline_core_gets_matching_firmware_and_start_command(self):
        remote = self.core(0, running=False, firmware='am64x-pru0_0-fw\n')
        # Emulate the sysfs state machine on write("start").
        self.executable('sleep', '#!/bin/sh\nfor state in "$TEST_SYS"/class/remoteproc/*/state; do\n [ "$(cat "$state")" != start ] || printf "running\\n" > "$state"\ndone\n')
        os.environ['TEST_SYS'] = str(self.sys)
        self.addCleanup(os.environ.pop, 'TEST_SYS', None)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((remote / 'firmware').read_text().strip(), 'fill-station-pru0_0-fw')


if __name__ == '__main__':
    unittest.main()
