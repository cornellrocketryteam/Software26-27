"""Version-3 output/continuity ingestion and receipt compatibility."""
import os,unittest,subprocess,importlib.util,json,tempfile
from pathlib import Path
import test_source_ingestion as base
MIGRATION=base.GS/'migrations/006-output-diagnostics.sql'
FIELDS=['ig1_output_active','ig1_continuity','ig1_output_valid','ig1_continuity_valid',
        'ig2_output_active','ig2_continuity','ig2_output_valid','ig2_continuity_valid',
        'qd_release_energized','qd_continuity','qd_output_valid','qd_continuity_valid']
@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for private PostgreSQL checks')
class OutputDiagnostics(base.SourceIngestionDatabase):
    def setUp(self):
        super().setUp();self.sql(MIGRATION.read_text())
    def frame(self,**extra):
        values=dict(source_metadata_version=3,operating_profile=2,load_cell_2_raw=0,
          load_cell_2_voltage=0,load_cell_2_valid='false')
        values.update({name:'true' for name in FIELDS});values.update(extra);return self.insert(**values)
    def test_false_is_valid_and_exact_retry_is_suppressed(self):
        self.sql(self.frame(ig1_output_active='false',qd_continuity='false'))
        self.sql(self.frame(ig1_output_active='false',qd_continuity='false',arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT ig1_output_active,ig1_output_valid,qd_continuity,qd_continuity_valid,source_identity_valid FROM telemetry_data;'),'f|t|f|t|t')
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
    def test_changed_diagnostic_under_same_frame_identity_is_rejected(self):
        self.sql(self.frame())
        for name in FIELDS:
            with self.subTest(name=name),self.assertRaises(subprocess.CalledProcessError):self.sql(self.frame(**{name:'false'}))
    def test_missing_configured_device_never_claims_valid_output_or_continuity(self):
        self.sql(self.frame(configured_devices_mask=0))
        self.assertEqual(self.sql('SELECT ig1_output_valid,ig2_continuity_valid,qd_output_valid,qd_continuity_valid FROM telemetry_data;'),'f|f|f|f')
    def test_old_versions_cannot_claim_new_validity(self):
        self.sql(self.frame(source_metadata_version=2))
        self.assertEqual(self.sql('SELECT ig1_output_valid,qd_continuity_valid FROM telemetry_data;'),'f|f')
    def test_profile_panels_show_valid_false_and_hide_unqualified_new_fields(self):
        spec=importlib.util.spec_from_file_location('runtime',base.GS/'provisioning/runtime.py')
        runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as d:
            runtime.build_assets(base.GS,d)
            dashboard=json.loads((Path(d)/'grafana/dashboards/hybrid-test.json').read_text())
        panels={p['id']:p for p in dashboard['panels']}
        def query(id):return panels[id]['targets'][0]['rawSql'].replace('${fill_session:sqlstring}',"'100:200'")
        self.sql(self.frame(ig1_output_active='false',qd_continuity='false'))
        self.assertEqual(self.sql(query(5)),'f|t|t|t')
        self.assertEqual(self.sql(query(4)).split('|')[-2:],['t','f'])
        self.sql(self.frame(seq=2,qd_output_valid='false',qd_continuity='false'))
        self.assertEqual(self.sql(query(4)).split('|')[-2:],['','f'])
        self.assertEqual(panels[4]['options']['reduceOptions']['calcs'],['last'])

    def test_existing_v2_receipt_survives_new_fields(self):
        self.sql((base.GS/'migrations/005-operating-profile-identity.sql').read_text())
        self.sql(self.frame(source_metadata_version=2))
        before=self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;")
        self.sql(MIGRATION.read_text());self.sql(self.frame(source_metadata_version=2,arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        self.assertEqual(self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;"),before)
for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(OutputDiagnostics,name,None)
class OutputDiagnosticPartitions(OutputDiagnostics):PARTITIONED=True
if __name__=='__main__':unittest.main()
