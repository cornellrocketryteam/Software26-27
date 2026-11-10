"""Shared JSON compiler contracts; independent of TI tooling and physical hardware."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HW = Path(os.environ.get('HARDWARE_SOURCE', ROOT / 'fill-station/hardware'))
spec = importlib.util.spec_from_file_location('compiler', HW / 'compiler.py')
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)

def baseline_profile(name):
    # Saved profiles are user-editable inputs, not immutable regression fixtures.
    return json.loads((HW / 'fixtures' / 'profiles' / f'{name}.json').read_text())


class HardwareConfigTests(unittest.TestCase):
    def test_saved_profiles_compile(self):
        for name in ('hybrid', 'liquid'):
            with self.subTest(profile=name):
                compiler.compile_profile(compiler.load_profile(name))
    def setUp(self):
        self.profile = baseline_profile('hybrid')
    def compile(self):
        return compiler.compile_profile(self.profile)
    def add_ads7128(self, profile=None, **overrides):
        profile = self.profile if profile is None else profile
        device = dict(id='extra_adc', type='ads7128', role=None, enabled=True,
                      connections={}, settings={}, bus=profile['buses'][0]['id'], address=0x10)
        device.update(overrides)
        profile['devices'].append(device)
        return device

    def test_ads7128_shared_bus_runtime_and_valid_addresses(self):
        for address in range(0x10, 0x18):
            with self.subTest(address=address):
                profile = baseline_profile('liquid')
                baseline = compiler.compile_profile(profile)
                bus = next(b['id'] for b in profile['buses'] if b['controller'] == 'main_i2c0')
                self.add_ads7128(profile, bus=bus, address=address)
                result = compiler.compile_profile(profile)
                self.assertEqual(result['runtime']['devices'][-1], dict(
                    id='extra_adc', type='ads7128', role=None, settings={}, connections={},
                    bus='/dev/i2c-0', address=address))
                self.assertEqual(result['runtime']['configured_devices_mask'], baseline['runtime']['configured_devices_mask'])
                self.assertEqual(result['expectations'], baseline['expectations'])

    def test_ads7128_invalid_addresses(self):
        for address in (True, False, None, '0x10', 16.0, [], {}, -1, 0x0f, 0x18, 0x80):
            with self.subTest(address=address):
                profile = baseline_profile('liquid')
                self.add_ads7128(profile, address=address)
                with self.assertRaisesRegex(ValueError, 'ADS7128 address'):
                    compiler.compile_profile(profile)

    def test_ads7128_reserved_addresses(self):
        for address in compiler.BOARD['shared_i2c0']['reserved_addresses']:
            profile = baseline_profile('liquid')
            bus = next(b['id'] for b in profile['buses'] if b['controller'] == 'main_i2c0')
            self.add_ads7128(profile, bus=bus, address=address)
            with self.assertRaisesRegex(ValueError, 'reserved'):
                compiler.compile_profile(profile)

    def test_ads7128_duplicate_address_and_disabled_runtime(self):
        self.add_ads7128()
        extra = self.add_ads7128(id='second_adc')
        with self.assertRaisesRegex(ValueError, 'duplicate I2C address'):
            self.compile()
        extra['enabled'] = False
        result = self.compile()
        self.assertNotIn('second_adc', [d['id'] for d in result['runtime']['devices']])

    def test_ads7128_bus_activation_and_disabled_bus_release(self):
        for d in self.profile['devices']:
            if d['type'] == 'ads1015':
                d['enabled'] = False
        extra = self.add_ads7128()
        self.assertEqual(self.compile()['expectations']['controllers']['main_i2c2'], 'okay')
        extra['enabled'] = False
        result = self.compile()
        self.assertEqual(result['expectations']['controllers']['main_i2c2'], 'disabled')
        self.assertNotIn('extra_adc', [d['id'] for d in result['runtime']['devices']])

    def test_ads7128_requires_defined_bus(self):
        self.add_ads7128(bus='missing')
        with self.assertRaisesRegex(ValueError, 'defined I2C bus'):
            self.compile()

    def test_ads7128_rejects_telemetry_roles(self):
        for role in ('adc1', 'adc2'):
            profile = baseline_profile('liquid')
            self.add_ads7128(profile, role=role)
            with self.assertRaisesRegex(ValueError, 'invalid role'):
                compiler.compile_profile(profile)

    def test_hybrid_register_regression_except_released_test_pin(self):
        baseline = json.loads((HW / 'fixtures/original-expectations.json').read_text())
        values = lambda result: {(p['domain'],p['offset']):p['value'] for p in result['pins']}
        for name in ('hybrid',):
            result=compiler.compile_profile(baseline_profile(name))
            expected = values(baseline)
            expected[('main', 0x164)] = 0x44007  # GPIO input with pull-down and Schmitt trigger
            self.assertEqual(values(result['expectations']), expected)
            self.assertEqual(len(result['report']['assignments']),23)
            self.assertEqual(len(result['report']['idle']),62)
            self.assertEqual(len(result['runtime']['devices']),12)
            self.assertEqual(result['runtime']['configured_devices_mask'],4095)
    def test_liquid_shared_bus_without_external_devices(self):
        p=baseline_profile('liquid')
        result=compiler.compile_profile(p)
        self.assertEqual(result['expectations']['controllers']['main_i2c0'],'okay')
        self.assertEqual(result['runtime']['configured_devices_mask'],2047)
        self.assertNotIn('qd_stepper',[d['role'] for d in result['runtime']['devices']])
        assigned={x['offset']:x for x in result['report']['assignments'] if x['domain']=='main'}
        self.assertEqual(assigned[0x260]['signal'],'I2C0_SCL')
        self.assertEqual(assigned[0x264]['signal'],'I2C0_SDA')
        self.assertEqual(len(result['report']['assignments']),22)
        self.assertEqual(len(result['report']['idle']),64)
        for d in result['runtime']['devices']:
            if d['type']=='ads1015':self.assertEqual(d['bus'],'/dev/i2c-2')
        for d in p['devices']:
            if d['type']=='ads1015':d['enabled']=False
        self.assertEqual(compiler.compile_profile(p)['expectations']['controllers']['main_i2c0'],'okay')
    def test_liquid_preserves_every_other_register(self):
        baseline=json.loads((HW/'fixtures/original-expectations.json').read_text())
        old={(p['domain'],p['offset']):p['value'] for p in baseline['pins']}
        result=compiler.compile_profile(baseline_profile('liquid'))
        new={(p['domain'],p['offset']):p['value'] for p in result['expectations']['pins']}
        qd=next(d for d in baseline_profile('hybrid')['devices'] if d['role']=='qd_stepper')
        changed={tuple([c['pin'].split(':')[0],int(c['pin'].split(':')[1],16)]) for c in qd['connections'].values()}
        changed.add(('main', 0x164))  # Released test input
        self.assertEqual(new[('main', 0x164)], 0x44007)
        for pad,value in old.items():
            if pad not in changed:self.assertEqual(new[pad],value,pad)
    def test_shared_bus_rejects_internal_pull_and_wrong_route(self):
        for change in ('pull','route'):
            p=baseline_profile('liquid');bus=next(b for b in p['buses'] if b['controller']=='main_i2c0')
            if change=='pull':bus['connections']['sda']['bias']='pull-up'
            else:bus['connections']['sda']['pin']='main:0x00b4'
            with self.assertRaises(ValueError):compiler.compile_profile(p)
    def test_liquid_requires_shared_bus(self):
        p=baseline_profile('liquid');p['buses']=[b for b in p['buses'] if b['controller']!='main_i2c0']
        with self.assertRaisesRegex(ValueError,'shared|I2C0'):compiler.compile_profile(p)
    def test_hybrid_rejects_shared_bus(self):
        p=baseline_profile('hybrid');p['buses'].append(next(b for b in baseline_profile('liquid')['buses'] if b['controller']=='main_i2c0'))
        with self.assertRaisesRegex(ValueError,'Liquid|liquid|protected'):compiler.compile_profile(p)
    def test_liquid_qd_cannot_reclaim_clock(self):
        p=baseline_profile('liquid')
        next(d for d in p['devices'] if d['role']=='qd_stepper')['enabled']=True
        with self.assertRaisesRegex(ValueError,'duplicate|claimed'):compiler.compile_profile(p)
    def test_shared_bus_board_addresses_reserved(self):
        for address in (0x30,0x50,0x51):
            p=baseline_profile('liquid');d=next(d for d in p['devices'] if d['role']=='adc1')
            d['bus']=next(b['id'] for b in p['buses'] if b['controller']=='main_i2c0');d['address']=address
            with self.assertRaisesRegex(ValueError,'reserved'):compiler.compile_profile(p)
    def test_pru_pin_14_is_available_for_solenoid_control(self):
        for name in ('liquid', 'hybrid'):
            with self.subTest(profile=name):
                profile = baseline_profile(name)
                result = compiler.compile_profile(profile)
                self.assertIn(1, result['expectations']['idle_gpio_lines']['main_gpio1'])
                valve = next(d for d in profile['devices'] if d['role'] == 'sv1')
                valve['connections']['control'].update(pin='main:0x0164', function='GPIO1_1')
                result = compiler.compile_profile(profile)
                self.assertNotIn(1, result['expectations']['idle_gpio_lines']['main_gpio1'])
                self.assertTrue(any(p['domain'] == 'main' and p['offset'] == 0x164
                                    for p in result['report']['assignments']))
    def test_duplicate_pad_across_devices_rejected(self):
        self.profile['devices'][1]['connections']['signal']=copy.deepcopy(self.profile['devices'][0]['connections']['signal'])
        with self.assertRaisesRegex(ValueError,'duplicate|claimed'):self.compile()
    def test_disabled_device_releases_pin_and_role(self):
        self.profile['devices'][0]['enabled']=False
        result=self.compile()
        self.assertFalse(result['runtime']['configured_devices_mask'] & 1)
        self.assertNotIn('ig1',[d['id'] for d in result['runtime']['devices']])
        self.assertIn(0x9c,[p['offset'] for p in result['report']['idle']])
    def test_added_instance_has_no_binding(self):
        extra=copy.deepcopy(self.profile['devices'][0]);extra.update(id='test_igniter',role=None)
        extra['connections']={'continuity':dict(pin='main:0x0168',function='GPIO1_2',bias='pull-down',schmitt=True),'signal':dict(pin='main:0x016c',function='GPIO1_3',bias='pull-down',schmitt=True)}
        self.profile['devices'].append(extra)
        result=self.compile();self.assertEqual(len(result['runtime']['devices']),13)
        self.assertEqual(result['runtime']['configured_devices_mask'],4095)
    def test_protected_pad_rejected(self):
        self.profile['devices'][0]['connections']['signal']['pin']='main:0x01f8'
        with self.assertRaisesRegex(ValueError,'protected|managed'):self.compile()
    def test_wrong_function_rejected(self):
        self.profile['devices'][0]['connections']['signal']['function']='SPI0_CLK'
        with self.assertRaisesRegex(ValueError,'function|mapping'):self.compile()
    def test_address_conflict_rejected(self):
        self.profile['devices'][3]['address']=72
        with self.assertRaisesRegex(ValueError,'address'):self.compile()
    def test_incomplete_bus_rejected(self):
        del self.profile['buses'][0]['connections']['sda']
        with self.assertRaisesRegex(ValueError,'scl|sda|SCL|SDA'):self.compile()
    def test_disabled_adcs_release_unused_bus(self):
        for d in self.profile['devices']:
            if d['type']=='ads1015':d['enabled']=False
        result=self.compile()
        self.assertEqual(result['expectations']['controllers']['main_i2c2'],'disabled')
        self.assertIn(0xb0,[p['offset'] for p in result['report']['idle']])
    def test_new_mcu_bus_automatically_enabled(self):
        self.profile['buses'].append(dict(id='sensors',controller='mcu_i2c1',connections={
            'scl':dict(pin='mcu:0x0050',function='MCU_I2C1_SCL',bias='none',schmitt=True),
            'sda':dict(pin='mcu:0x0054',function='MCU_I2C1_SDA',bias='none',schmitt=True)}))
        self.profile['devices'][2]['bus']='sensors'
        result=self.compile();self.assertEqual(result['expectations']['controllers']['mcu_i2c1'],'okay')
        self.assertEqual(result['runtime']['devices'][2]['bus'],'/dev/i2c-5')
    def test_wrong_role_type_rejected(self):
        self.profile['devices'][0]['role']='adc1'
        with self.assertRaisesRegex(ValueError,'role'):self.compile()
    def test_unknown_setting_and_malformed_value_rejected(self):
        self.profile['devices'][0]['settings']['surprise']=True
        with self.assertRaisesRegex(ValueError,'setting'):self.compile()
        self.profile['devices'][0]['settings']={};self.profile['devices'][0]['enabled']='false'
        with self.assertRaisesRegex(ValueError,'enabled'):self.compile()
    def test_duplicate_id_even_disabled_rejected(self):
        self.profile['devices'][1].update(id='ig1',enabled=False)
        with self.assertRaisesRegex(ValueError,'id'):self.compile()
    def test_pwm_output_cannot_be_allocated_twice(self):
        extra=copy.deepcopy(self.profile['devices'][9]);extra.update(id='servo2',role=None)
        self.profile['devices'].append(extra)
        with self.assertRaisesRegex(ValueError,'duplicate|claimed|PWM'):self.compile()
    def test_profile_must_be_supported_and_versioned(self):
        self.profile['version']=2
        with self.assertRaisesRegex(ValueError,'version'):self.compile()
    def test_deterministic_and_source_not_mutated(self):
        original=copy.deepcopy(self.profile);first=self.compile();second=self.compile()
        self.assertEqual(first,second);self.assertEqual(original,self.profile)

if __name__=='__main__':unittest.main()
