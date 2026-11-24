"""Normal-Hybrid v2 extension, receipt stability and filtered Grafana queries."""
import importlib.util,json,os,re,tempfile,unittest,subprocess
from pathlib import Path
import test_source_ingestion as base
spec=importlib.util.spec_from_file_location('runtime',base.GS/'provisioning/runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
MIGRATION=base.GS/'migrations/005-operating-profile-identity.sql'
@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for private PostgreSQL checks')
class HybridIdentity(base.SourceIngestionDatabase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.sql(MIGRATION.read_text());cls.sql(MIGRATION.read_text())
    def setUp(self):
        super().setUp()
        with tempfile.TemporaryDirectory() as d:
            runtime.build_assets(base.GS,d)
            self.dashboard=json.loads((Path(d)/'grafana/dashboards/hybrid.json').read_text())
        self.panels={p['id']:p for p in self.dashboard['panels']}
    def frame(self,**extra):
        values=dict(source_metadata_version=2,operating_profile=1,load_cell_2_raw=0,
          load_cell_2_voltage=0,load_cell_2_valid='false',pt3=300,pt4=400,sv_2_open='true',
          mav_open='true',configured_devices_mask=1311,fsw_receive_age_valid='true',fsw_receive_age_ms=10)
        values.update(extra);return self.insert(**values)
    def query(self,id,selection='100:200'):
        return self.panels[id]['targets'][0]['rawSql'].replace('${fill_session:sqlstring}',"'"+selection.replace("'","''")+"'")
    def test_normal_hybrid_keeps_remote_fields_without_local_sv2_mav_bits(self):
        self.sql(self.frame())
        self.assertEqual(self.sql('SELECT source_identity_valid,pt3,pt4,sv_2_open,mav_open,load_cell_2_valid FROM telemetry_data;'),'t|300|400|t|t|f')
        self.sql(self.frame(arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
    def test_unknown_fsw_age_does_not_invent_zero_pressure_or_closed_remote_valves(self):
        self.sql(self.frame(fsw_receive_age_valid='false'))
        self.assertEqual(self.sql('SELECT pt3 IS NULL,pt4 IS NULL,sv_2_open IS NULL,mav_open IS NULL,flight_mode IS NULL FROM telemetry_data;'),'t|t|t|t|t')
    def test_normal_hybrid_cannot_claim_a_second_load_cell(self):
        for extra in [dict(load_cell_2_raw=1),dict(load_cell_2_voltage=0.25),dict(load_cell_2_valid='true'),dict(operating_profile=3)]:
            with self.subTest(extra=extra),self.assertRaises(subprocess.CalledProcessError):self.sql(self.frame(**extra))
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'0')
    def test_existing_test_stand_fingerprint_survives_extension(self):
        self.sql((base.GS/'migrations/004-lc2-telemetry.sql').read_text())
        frame=self.frame(operating_profile=2,load_cell_2_raw=123,load_cell_2_voltage=0.25,load_cell_2_valid='true')
        self.sql(frame)
        before=self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;")
        self.sql(MIGRATION.read_text());self.sql(frame)
        self.assertEqual(self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;"),before)
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
    def test_v1_receipt_survives_profile_extension(self):
        self.sql((base.GS/'migrations/004-lc2-telemetry.sql').read_text())
        self.sql(self.insert())
        before=self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;")
        self.sql(MIGRATION.read_text());self.sql(self.insert(arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        self.assertEqual(self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;"),before)

    def test_profile_change_under_same_frame_identity_conflicts(self):
        self.sql(self.frame(fsw_receive_age_valid='false'))
        with self.assertRaises(subprocess.CalledProcessError):
            self.sql(self.frame(operating_profile=2,fsw_receive_age_valid='false'))
        self.assertEqual(self.sql('SELECT count(*),max(operating_profile) FROM telemetry_data;'),'1|1')

    def test_hybrid_dashboard_is_explicitly_filtered_and_uses_selected_source_fsw(self):
        self.sql(self.frame())
        self.sql(self.frame(hi=999,operating_profile=2))
        self.sql(self.insert(hi=888))
        self.assertEqual(self.dashboard['uid'],'fillops-hybrid')
        catalog=self.sql(self.dashboard['templating']['list'][0]['query'])
        self.assertIn('100:200',catalog);self.assertNotIn('999:200',catalog);self.assertNotIn('888:200',catalog)
        self.assertEqual(self.sql(self.query(35)),'10')
        self.assertNotIn('LC2',json.dumps(self.dashboard))
        for selection in ['none','legacy','999:200','888:200',"100:200' OR true --"]:
            self.assertEqual(self.sql(self.query(6,selection)),'')
        for id in [3,4,5,6,35]:self.sql('SET ROLE ground_reader; '+self.query(id))
for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(HybridIdentity,name,None)
class HybridPartitions(HybridIdentity):PARTITIONED=True
if __name__=='__main__':unittest.main()
