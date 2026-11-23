"""Opt-in effective wiring compilation, without firmware activation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HW = Path(__file__).resolve().parents[1]/'fill-station/hardware'
spec=importlib.util.spec_from_file_location('compiler',HW/'compiler.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)

class OperatingCompiler(unittest.TestCase):
    def test_hybrid_only_drives_intended_local_devices(self):
        result=compiler.compile_operating_profile('hybrid')
        roles={d['role'] for d in result['runtime']['devices'] if d['role']}
        self.assertEqual(roles,{'ig1','ig2','adc1','adc2','sv1','sv5','ball_valve'})
        self.assertTrue(result['operating']['definition']['fswEnabled'])
        self.assertEqual(result['runtime']['configured_devices_mask'],sum(1<<compiler.ROLES.index(r) for r in roles))

    def test_test_stand_reuses_connectors_and_keeps_second_load_cell_uncalibrated(self):
        result=compiler.compile_operating_profile('hybrid-test')
        roles={d['role'] for d in result['runtime']['devices'] if d['role']}
        self.assertEqual(roles,{'ig1','ig2','adc1','adc2','sv1','sv2','sv5','mav','ball_valve'})
        self.assertFalse(result['operating']['definition']['fswEnabled'])
        sensors={s['id']:s for s in result['operating']['definition']['sensors']}
        self.assertEqual((sensors['lc2']['deviceId'],sensors['lc2']['channel']),('adc2',2))
        self.assertIsNone(sensors['lc2']['calibrationRef'])
        old={d['id']:d for d in compiler.compile_profile(compiler.load_profile('hybrid'))['runtime']['devices']}
        for d in result['runtime']['devices']:self.assertEqual(d,old[d['id']])

    def test_no_saved_wiring_mutation_and_legacy_compilation_unchanged(self):
        before=(HW/'profiles/hybrid.json').read_bytes()
        legacy=compiler.compile_profile(compiler.load_profile('hybrid'))
        first=compiler.compile_operating_profile('hybrid-test')
        second=compiler.compile_operating_profile('hybrid-test')
        self.assertEqual(first,second)
        self.assertEqual(legacy,compiler.compile_profile(compiler.load_profile('hybrid')))
        self.assertEqual(before,(HW/'profiles/hybrid.json').read_bytes())
        self.assertNotEqual(first['operating']['baseWiringSha256'],first['operating']['effectiveWiringSha256'])

    def test_pending_liquid_cannot_be_accidentally_activated(self):
        with self.assertRaisesRegex(ValueError,'pending'):compiler.compile_operating_profile('liquid')

    def test_cli_requires_one_selector_and_emits_inspectable_identity(self):
        with tempfile.TemporaryDirectory() as d:
            args=[sys.executable,str(HW/'compiler.py'),'--operating-profile','hybrid-test','--output',d]
            subprocess.run(args,check=True,capture_output=True)
            identity=json.loads((Path(d)/'operating-profile.json').read_text())
            runtime=json.loads((Path(d)/'hardware-runtime.json').read_text())
            self.assertEqual(identity['definition']['id'],'hybrid-test')
            self.assertEqual(runtime['operating_profile'],'hybrid-test')
            effective=json.loads((Path(d)/'effective-wiring.json').read_text())
            self.assertEqual({x['id'] for x in effective['devices'] if not x['enabled']},{'sv3','sv4'})
            for extra in [['--profile','hybrid'],['--profile','liquid']]:
                self.assertNotEqual(subprocess.run(args+extra,capture_output=True).returncode,0)

if __name__=='__main__':unittest.main()
