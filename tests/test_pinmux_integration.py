"""Merge both JSON profiles into the real kernel SK DTB; requires KERNEL_DTS_DIR."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'nix/overlays/by-name/crt/fillstation-dtbo'
HARDWARE=ROOT/'fill-station/hardware'
KERNEL=os.environ.get('KERNEL_DTS_DIR')
spec=importlib.util.spec_from_file_location('compiler',HARDWARE/'compiler.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)

@unittest.skipUnless(KERNEL,'set KERNEL_DTS_DIR to the kernel source root for real-DTB integration')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='hardware-integration-');cls.work=Path(cls.temp.name)
        kernel=Path(KERNEL);dts=kernel/'arch/arm64/boot/dts/ti'
        cls.command(['clang','-E','-P','-undef','-nostdinc','-x','assembler-with-cpp','-I',str(kernel/'include'),'-I',str(dts),str(dts/'k3-am642-sk.dts'),'-o',str(cls.work/'base.dts')])
        cls.command(['dtc','-@','-I','dts','-O','dtb','-o',str(cls.work/'base.dtb'),str(cls.work/'base.dts')])
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @staticmethod
    def command(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
    def build(self,profile,name):
        result=compiler.compile_profile(profile);out=self.work/name;out.mkdir()
        for filename,key in [('hardware-pinmux.dtsi','pins'),('overlay.dts','overlay')]:
            (out/filename).write_text(result[key])
        (out/'expectations.json').write_text(json.dumps(result['expectations']))
        shutil.copyfile(SOURCE/'src/k3.h',out/'k3.h')
        self.command(['clang','-E','-P','-undef','-nostdinc','-x','assembler-with-cpp','-I',str(out),str(out/'overlay.dts'),'-o',str(out/'overlay.pp.dts')])
        self.command(['dtc','-@','-I','dts','-O','dtb','-o',str(out/'overlay.dtbo'),str(out/'overlay.pp.dts')])
        self.command(['fdtoverlay','-i',str(self.work/'base.dtb'),'-o',str(out/'merged.dtb'),str(out/'overlay.dtbo')])
        self.command(['python3',str(SOURCE/'verify-merged.py'),str(out/'merged.dtb'),str(out/'expectations.json')])
        return out
    def test_both_profiles_merge_and_preserve_board_bus(self):
        for name in ('liquid','hybrid'):
            with self.subTest(profile=name):
                out=self.build(compiler.load_profile(name),name)
                self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),'/bus@f4000/i2c@20010000','status']).strip(),'okay')
                bus='/bus@f4000/i2c@20000000'
                self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),bus,'status']).strip(),'okay' if name=='liquid' else 'disabled')
                self.assertEqual(self.command(['fdtget','-tx',str(out/'merged.dtb'),bus+'/eeprom@51','reg']).strip(),'51')
                self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),'/aliases','i2c0']).strip(),bus)

    def test_new_mcu_bus_enables_controller_and_alias(self):
        profile=compiler.load_profile('hybrid')
        profile['buses'].append(dict(id='external',controller='mcu_i2c1',connections={
            'scl':dict(pin='mcu:0x0050',function='MCU_I2C1_SCL',bias='none',schmitt=True),
            'sda':dict(pin='mcu:0x0054',function='MCU_I2C1_SDA',bias='none',schmitt=True)}))
        profile['devices'][2]['bus']='external';out=self.build(profile,'mcu-bus')
        path=self.command(['fdtget',str(out/'merged.dtb'),'/__symbols__','mcu_i2c1']).strip()
        self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),path,'status']).strip(),'okay')
        self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),'/aliases','i2c5']).strip(),path)
    def test_disabled_device_idle_gpio_is_hogged(self):
        profile=compiler.load_profile('liquid');profile['devices'][0]['enabled']=False
        out=self.build(profile,'disabled')
        path=self.command(['fdtget',str(out/'merged.dtb'),'/__symbols__','main_gpio0']).strip()
        self.assertEqual(self.command(['fdtget',str(out/'merged.dtb'),path+'/idle_line_38','gpios']).strip(),'38 0')
    def test_verifier_rejects_corrupted_register(self):
        out=self.build(compiler.load_profile('hybrid'),'corrupted')
        path=self.command(['fdtget',str(out/'merged.dtb'),'/__symbols__','config_main_gpio']).strip()
        self.command(['fdtput','-tx',str(out/'merged.dtb'),path,'pinctrl-single,pins','84','0'])
        result=subprocess.run(['python3',str(SOURCE/'verify-merged.py'),str(out/'merged.dtb'),str(out/'expectations.json')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('DTB pinmux check failed',result.stderr)

if __name__=='__main__':unittest.main()
