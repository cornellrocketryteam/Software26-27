"""Operating intent only: ownership and channels must never silently retarget."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT/'fill-station/hardware'
SOURCE = HW/'operating_profiles.py'
spec = importlib.util.spec_from_file_location('operating_profiles', SOURCE) if SOURCE.exists() else None
contract = importlib.util.module_from_spec(spec) if spec else None
if spec:
    spec.loader.exec_module(contract)


class OperatingProfilesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contract, 'operating-profile contract implementation is missing')
        self.profiles = contract.load_profiles()
        self.wiring = {name: json.loads((HW/'profiles'/f'{name}.json').read_text()) for name in ('hybrid','liquid')}

    def validate(self, profile):
        return contract.validate_profile(profile, self.wiring[profile['hardwareProfile']])

    def test_normal_hybrid_keeps_remote_devices_remote(self):
        p = self.profiles['hybrid']
        self.assertTrue(p['fswEnabled'])
        controls = {d['id']: d for d in p['controls']}
        self.assertEqual(controls['sv2']['owner'], 'fsw')
        self.assertEqual(controls['mav']['owner'], 'fsw')
        self.assertIsNone(controls['sv2']['deviceId'])
        self.assertIn('sv2', p['disabledLocalDeviceIds'])
        sensors = {d['id']: d for d in p['sensors']}
        self.assertEqual(sensors['pt3']['owner'], 'fsw')
        self.assertEqual(sensors['pt4']['owner'], 'fsw')
        self.assertNotIn('lc2', sensors)

    def test_test_stand_has_only_local_devices_and_second_uncalibrated_load_cell(self):
        p = self.profiles['hybrid-test']
        self.assertFalse(p['fswEnabled'])
        self.assertTrue(all(d['owner']=='local' for d in p['controls']+p['sensors']))
        self.assertEqual({d['id'] for d in p['controls']}, {'sv1','sv2','ball_valve','qd','ig1','ig2','mav'})
        sensors = {d['id']: d for d in p['sensors']}
        for index in range(4):
            sensor = sensors[f'pt{index+1}']
            self.assertEqual((sensor['deviceId'],sensor['channel']), ('adc1',index))
            self.assertEqual((sensor['engineeringUnit'],sensor['range']), ('psi',[0,1500]))
        self.assertEqual((sensors['lc1']['deviceId'],sensors['lc1']['channel']), ('adc2',1))
        lc2 = sensors['lc2']
        self.assertEqual((lc2['deviceId'],lc2['channel']), ('adc2',2))
        self.assertEqual(lc2['readings'], ['raw','voltage'])
        self.assertIsNone(lc2['calibrationRef'])
        self.assertIsNone(lc2['engineeringUnit'])

    def test_qd_release_polarity_and_feedback_are_explicit(self):
        for name in ('hybrid','hybrid-test'):
            qd = next(d for d in self.profiles[name]['controls'] if d['id']=='qd')
            self.assertEqual(qd['deviceId'],'qd')
            self.assertEqual(qd['energizedAction'],'disconnect')
            self.assertFalse(qd['deenergizedReconnects'])
            self.assertEqual(qd['feedback'], ['commanded_output','continuity'])

    def test_conflicting_ownership_channel_and_calibration_are_rejected(self):
        cases = []
        p = copy.deepcopy(self.profiles['hybrid-test']); p['controls'][0]['owner']='fsw'; cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid-test']); p['sensors'][1]['channel']=p['sensors'][0]['channel']; cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid-test']); p['sensors'][-1]['readings'].append('engineering'); cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid-test']); p['sensors'][-1]['calibrationRef']='borrow-lc1'; cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid']); p['controls'][0]['deviceId']='sv2'; cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid-test']); p['controls'][0]['deviceId']='missing-device'; cases.append(p)
        p = copy.deepcopy(self.profiles['hybrid-test']); p['sensors'][0]['channel']=True; cases.append(p)
        for index, p in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError): self.validate(p)

    def test_duplicate_ids_unknown_fields_and_false_position_claims_rejected(self):
        for mutate in (
            lambda p: p['controls'].append(copy.deepcopy(p['controls'][0])),
            lambda p: p.update(automaticFill=True),
            lambda p: next(d for d in p['controls'] if d['id']=='qd').update(deenergizedReconnects=True),
            lambda p: p['controls'][0].update(owner='guessed'),
        ):
            p=copy.deepcopy(self.profiles['hybrid-test']); mutate(p)
            with self.assertRaises(ValueError): self.validate(p)

    def test_liquid_keeps_unmapped_devices_explicit_without_inventing_controls(self):
        p=self.profiles['liquid']
        self.assertEqual(p['mappingStatus'],'pending')
        self.assertEqual(p['controls'],[]); self.assertEqual(p['sensors'],[])
        self.assertEqual(set(p['unmappedDeviceIds']), {d['id'] for d in self.wiring['liquid']['devices'] if d['enabled']})

    def test_hash_tracks_semantics_not_json_key_order(self):
        p=self.profiles['hybrid-test']
        self.assertEqual(contract.profile_digest(p), contract.profile_digest(dict(reversed(list(p.items())))))
        changed=copy.deepcopy(p);changed['label']='Changed operating intent'
        self.assertNotEqual(contract.profile_digest(p),contract.profile_digest(changed))

    def test_loading_contract_does_not_change_saved_hardware_profiles(self):
        before={name:(HW/'profiles'/f'{name}.json').read_bytes() for name in self.wiring}
        contract.load_profiles()
        self.assertEqual(before,{name:(HW/'profiles'/f'{name}.json').read_bytes() for name in self.wiring})

    def test_malformed_kind_is_rejected_as_a_validation_error(self):
        p=copy.deepcopy(self.profiles['hybrid-test']);p['controls'][0]['kind']=[]
        with self.assertRaises(ValueError): self.validate(p)

    def test_loader_rejects_duplicate_fields_and_wrong_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'contract.json'
            for data in ('{"schemaVersion":1,"schemaVersion":1,"profiles":{}}',
                         '{"schemaVersion":true,"profiles":{}}'):
                path.write_text(data)
                with self.assertRaises(ValueError): contract.load_profiles(path)

    def test_cli_from_another_directory_reports_definition_and_wiring_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(SOURCE),'--profile','hybrid-test'],cwd=directory,capture_output=True,text=True,check=True)
        data=json.loads(result.stdout)
        self.assertIn('definition-only',data['scope'])
        self.assertEqual(set(data['profiles']),{'hybrid-test'})
        p=data['profiles']['hybrid-test']
        self.assertEqual(p['definitionSha256'],contract.profile_digest(self.profiles['hybrid-test']))
        self.assertEqual(p['hardwareProfileSha256'],contract.profile_digest(self.wiring['hybrid']))

if __name__ == '__main__': unittest.main()
