"""Solenoid QD compiler/compatibility contracts; no hardware access."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/'fill-station/hardware'
spec=importlib.util.spec_from_file_location('qd_compiler',HW/'compiler.py');compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)

class SolenoidQD(unittest.TestCase):
 def qd_profile(self):
  p=compiler.load_profile('hybrid')
  p['devices']=[d for d in p['devices'] if d['type']!='qd_stepper']
  d=next(d for d in p['devices'] if d['role']=='sv5');d.update(id='qd',type='quick_disconnect')
  return p
 def test_saved_hybrid_uses_distinct_qd_kind_with_unchanged_sv5_binding_and_pins(self):
  p=compiler.load_profile('hybrid');d=next(d for d in p['devices'] if d['role']=='sv5')
  self.assertEqual((d['id'],d['type']),('qd','quick_disconnect'))
  self.assertEqual(d['connections']['control']['function'],'GPIO1_48')
  self.assertEqual(d['connections']['sense']['function'],'GPIO1_46')
  self.assertFalse(any(d['type']=='qd_stepper' for d in p['devices']))
 def test_quick_disconnect_is_selectable_and_keeps_stable_wire_role_bits(self):
  result=compiler.compile_profile(self.qd_profile())
  d=next(d for d in result['runtime']['devices'] if d['role']=='sv5')
  self.assertEqual(d['type'],'quick_disconnect');self.assertEqual(d['settings']['valve_type'],'normally_closed')
  self.assertEqual(d['connections']['control'],{'chip':'gpiochip2','line':48})
  self.assertEqual(d['connections']['sense'],{'chip':'gpiochip2','line':46})
  self.assertEqual(result['runtime']['configured_devices_mask'],2047)
  self.assertEqual(compiler.ROLES.index('sv5'),8);self.assertEqual(compiler.ROLES.index('ball_valve'),10)
 def test_qd_polarity_cannot_be_overridden_even_when_disabled(self):
  for enabled in (True,False):
   p=self.qd_profile();d=next(d for d in p['devices'] if d['role']=='sv5');d['enabled']=enabled
   for value in ['normally_open','active_low',True,1,None]:
    d['settings']['valve_type']=value
    with self.assertRaises(ValueError):compiler.compile_profile(p)
 def test_qd_does_not_steal_another_application_role(self):
  p=self.qd_profile();d=next(d for d in p['devices'] if d['role']=='sv5');d['role']='sv1'
  with self.assertRaisesRegex(ValueError,'invalid role'):compiler.compile_profile(p)
 def test_unbound_selectable_instance_does_not_claim_an_application_bit(self):
  p=self.qd_profile();d=next(d for d in p['devices'] if d['role']=='sv5');d['role']=None
  result=compiler.compile_profile(p)
  self.assertEqual(result['runtime']['configured_devices_mask'],2047 & ~(1<<8))
 def test_stepper_kind_is_removed_instead_of_reused(self):
  self.assertNotIn('qd_stepper',compiler.CATALOG)
  source=(ROOT/'fill-station/src/command.rs').read_text()
  for variant in ['QdMove','QdRetract','QdExtend','GetQdState','QdState']:self.assertNotIn(variant,source)
  csv=(ROOT/'fill-station/src/csv_logger.rs').read_text();self.assertNotIn('hw.qd_stepper()',csv)

class RemovedMotorPinPolicy(unittest.TestCase):
 def test_unused_motor_pads_keep_safe_idle_without_stale_ownership_claims(self):
  result=compiler.compile_profile(compiler.load_profile('hybrid'))
  idle={p['offset']:p['value'] for p in result['expectations']['pins'] if p['domain']=='main'}
  self.assertEqual({offset:idle[offset] for offset in (0x20c,0x248,0x260)},
                   {0x20c:0x44007,0x248:0x44007,0x260:0x54007})
  self.assertNotIn('retains QD enable',compiler.BOARD['idle_exceptions'])
 def test_existing_i2c0_restriction_reports_policy_not_removed_motor_ownership(self):
  text='&main_pmx0 { test: test { pinctrl-single,pins = <AM64X_IOPAD(0x0260, PIN_INPUT|PIN_SCMITT_TRIGGER_ENABLE, 0) /* (D6) I2C0_SCL */>; }; };'
  with self.assertRaisesRegex(ValueError,'policy') as error:compiler.pinmux.generate(text,profile='hybrid')
  self.assertNotIn('QD enable',str(error.exception))

if __name__=='__main__':unittest.main()
