"""PRU PWM ownership, timing and editor contract."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HW = Path(os.environ.get('HARDWARE_SOURCE', ROOT / 'fill-station/hardware'))
spec = importlib.util.spec_from_file_location('pru_compiler', HW / 'compiler.py')
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class PruPwmTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((HW / 'fixtures/profiles/hybrid.json').read_text())
        self.servo = next(d for d in self.profile['devices'] if d['type'] == 'mav_servo')

    def select(self, core=1, bit=2):
        offset = 0x160 + core * 0x50 + bit * 4
        self.servo['connections']['pwm'].update(
            pin=f'main:0x{offset:04x}', function=f'PRG0_PRU{core}_GPO{bit}')

    def compile(self):
        return compiler.compile_profile(self.profile)

    def test_pru_descriptor_and_exclusive_pad_ownership(self):
        self.select()
        result = self.compile()
        servo = next(d for d in result['runtime']['devices'] if d['type'] == 'mav_servo')
        self.assertEqual(servo['pwm'], dict(backend='pru', subsystem=0, core=1, bit=2))
        self.assertEqual(servo['settings'], dict(period_ns=3030303, min_pulse_us=800,
                                              max_pulse_us=2200, safe_pulse_us=883))
        self.assertNotIn(22, result['expectations']['idle_gpio_lines']['main_gpio1'])
        self.assertIn('&pru0_1', result['overlay'])
        self.assertIn('config_pru0_1', result['expectations']['pinctrl']['pru0_1'])
        self.assertEqual(result['expectations']['controllers']['icssg0'], 'okay')
        self.assertEqual(result['expectations']['controllers']['icssg0_iep0'], 'disabled')
        self.assertEqual(result['expectations']['controllers']['icssg0_iep1'], 'disabled')
        self.assertEqual(result['expectations']['pru_pwm'][0]['bit'], 2)

    def test_every_exposed_pru_output_can_be_selected(self):
        self.profile['devices'] = [self.servo]
        for core, count in ((0, 20), (1, 18)):
            for bit in range(count):
                with self.subTest(core=core, bit=bit):
                    self.select(core, bit)
                    self.compile()

    def test_linux_gpio_and_pru_cannot_claim_same_pad(self):
        self.select()
        self.profile['devices'][0]['connections']['signal'].update(pin='main:0x01b8', function='GPIO1_22')
        with self.assertRaisesRegex(ValueError, 'duplicate pad'):
            self.compile()

    def test_legacy_epwm_descriptor_is_tagged_without_wiring_change(self):
        servo = next(d for d in self.compile()['runtime']['devices'] if d['type'] == 'mav_servo')
        self.assertEqual(servo['pwm'], dict(backend='epwm', device='23040000.pwm', channel=1))

    def test_timing_validation(self):
        self.select()
        for settings in ({'period_ns': True}, {'period_ns': 1999999}, {'period_ns': 50000001},
                         {'min_pulse_us': 99}, {'max_pulse_us': 3000, 'period_ns': 3030303},
                         {'safe_pulse_us': 799}, {'safe_pulse_us': 2201},
                         {'min_pulse_us': 2200}, {'safe_pulse_us': 883.5}):
            with self.subTest(settings=settings):
                self.servo['settings'] = settings
                with self.assertRaisesRegex(ValueError, 'PWM|pulse|period'):
                    self.compile()

    def test_different_pru_periods_are_independent(self):
        self.select()
        other = copy.deepcopy(self.servo)
        other.update(id='other', role=None, settings={'period_ns': 20000000})
        other['connections']['pwm'].update(pin='main:0x01bc', function='PRG0_PRU1_GPO3')
        self.profile['devices'].append(other)
        self.assertEqual(len(self.compile()['expectations']['pru_pwm']), 2)

    def test_mav_range_must_include_existing_open_and_close_calibration(self):
        for settings in ({'min_pulse_us': 900, 'safe_pulse_us': 900}, {'max_pulse_us': 1900}):
            self.servo['settings'] = settings
            with self.assertRaisesRegex(ValueError, 'MAV.*calibrat'):
                self.compile()

    def test_shared_epwm_channels_require_one_period(self):
        other = dict(id='shared_timer', type='ereg', role=None, enabled=True,
            settings={'period_ns': 3030303}, connections={'pwm': dict(
                pin='main:0x0088', function='EHRPWM4_A', bias='none', schmitt=True)})
        self.profile['devices'].append(other)
        self.compile()
        other['settings']['period_ns'] = 20000000
        with self.assertRaisesRegex(ValueError, 'ePWM.*period'):
            self.compile()
        other['enabled'] = False
        self.compile()

    def test_disabled_pru_device_does_not_enable_core(self):
        self.select()
        self.servo['enabled'] = False
        result = self.compile()
        self.assertEqual(result['expectations'].get('pru_pwm', []), [])
        self.assertIn(22, result['expectations']['idle_gpio_lines']['main_gpio1'])

    def test_four_added_liquid_regulators_use_independent_periods(self):
        profile = json.loads((HW / 'fixtures/profiles/liquid.json').read_text())
        original = copy.deepcopy(profile)
        for index, period in enumerate((20000000, 10000000, 4000000, 3030000)):
            profile['devices'].append(dict(id=f'pru_test_{index}', type='ereg', role=None,
                enabled=True, settings={'period_ns': period}, connections={'pwm': dict(
                    pin=f'main:0x{0x1b8 + index * 4:04x}', function=f'PRG0_PRU1_GPO{2 + index}',
                    bias='pull-down', schmitt=True)}))
        result = compiler.compile_profile(profile)
        self.assertEqual(len(result['expectations']['pru_pwm']), 4)
        self.assertEqual(result['runtime']['configured_devices_mask'],
                         compiler.compile_profile(original)['runtime']['configured_devices_mask'])
        self.assertEqual([d['settings']['period_ns'] for d in result['runtime']['devices'][-4:]],
                         [20000000, 10000000, 4000000, 3030000])


if __name__ == '__main__':
    unittest.main()
