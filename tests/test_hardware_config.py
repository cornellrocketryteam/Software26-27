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

class HardwareConfigTests(unittest.TestCase):
    def setUp(self):
        self.profile = compiler.load_profile('hybrid')
    def compile(self):
        return compiler.compile_profile(self.profile)
    def test_default_profiles_exact_register_regression(self):
        baseline = json.loads((HW / 'fixtures/original-expectations.json').read_text())
        values = lambda result: {(p['domain'],p['offset']):p['value'] for p in result['pins']}
        for name in ('hybrid',):
            result=compiler.compile_profile(compiler.load_profile(name))
            self.assertEqual(values(result['expectations']),values(baseline))
            self.assertEqual(len(result['report']['assignments']),24)
            self.assertEqual(len(result['report']['idle']),61)
            self.assertEqual(len(result['runtime']['devices']),12)
            self.assertEqual(result['runtime']['configured_devices_mask'],4095)
    def test_liquid_shared_bus_without_external_devices(self):
        p=compiler.load_profile('liquid')
        result=compiler.compile_profile(p)
        self.assertEqual(result['expectations']['controllers']['main_i2c0'],'okay')
        self.assertEqual(result['runtime']['configured_devices_mask'],2047)
        self.assertNotIn('qd_stepper',[d['role'] for d in result['runtime']['devices']])
        assigned={x['offset']:x for x in result['report']['assignments'] if x['domain']=='main'}
        self.assertEqual(assigned[0x260]['signal'],'I2C0_SCL')
        self.assertEqual(assigned[0x264]['signal'],'I2C0_SDA')
        self.assertEqual(len(result['report']['assignments']),23)
        self.assertEqual(len(result['report']['idle']),63)
        for d in result['runtime']['devices']:
            if d['type']=='ads1015':self.assertEqual(d['bus'],'/dev/i2c-2')
        for d in p['devices']:
            if d['type']=='ads1015':d['enabled']=False
        self.assertEqual(compiler.compile_profile(p)['expectations']['controllers']['main_i2c0'],'okay')
    def test_liquid_preserves_every_other_register(self):
        baseline=json.loads((HW/'fixtures/original-expectations.json').read_text())
        old={(p['domain'],p['offset']):p['value'] for p in baseline['pins']}
        result=compiler.compile_profile(compiler.load_profile('liquid'))
        new={(p['domain'],p['offset']):p['value'] for p in result['expectations']['pins']}
        qd=next(d for d in compiler.load_profile('hybrid')['devices'] if d['role']=='qd_stepper')
        changed={tuple([c['pin'].split(':')[0],int(c['pin'].split(':')[1],16)]) for c in qd['connections'].values()}
        for pad,value in old.items():
            if pad not in changed:self.assertEqual(new[pad],value,pad)
    def test_shared_bus_rejects_internal_pull_and_wrong_route(self):
        for change in ('pull','route'):
            p=compiler.load_profile('liquid');bus=next(b for b in p['buses'] if b['controller']=='main_i2c0')
            if change=='pull':bus['connections']['sda']['bias']='pull-up'
            else:bus['connections']['sda']['pin']='main:0x00b4'
            with self.assertRaises(ValueError):compiler.compile_profile(p)
    def test_liquid_requires_shared_bus(self):
        p=compiler.load_profile('liquid');p['buses']=[b for b in p['buses'] if b['controller']!='main_i2c0']
        with self.assertRaisesRegex(ValueError,'shared|I2C0'):compiler.compile_profile(p)
    def test_hybrid_rejects_shared_bus(self):
        p=compiler.load_profile('hybrid');p['buses'].append(next(b for b in compiler.load_profile('liquid')['buses'] if b['controller']=='main_i2c0'))
        with self.assertRaisesRegex(ValueError,'Liquid|liquid|protected'):compiler.compile_profile(p)
    def test_liquid_qd_cannot_reclaim_clock(self):
        p=compiler.load_profile('liquid')
        next(d for d in p['devices'] if d['role']=='qd_stepper')['enabled']=True
        with self.assertRaisesRegex(ValueError,'duplicate|claimed'):compiler.compile_profile(p)
    def test_shared_bus_board_addresses_reserved(self):
        for address in (0x30,0x50,0x51):
            p=compiler.load_profile('liquid');d=next(d for d in p['devices'] if d['role']=='adc1')
            d['bus']=next(b['id'] for b in p['buses'] if b['controller']=='main_i2c0');d['address']=address
            with self.assertRaisesRegex(ValueError,'reserved'):compiler.compile_profile(p)
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
