"""Versioned LC2 ingestion and old receipt compatibility in private PostgreSQL."""
import os
import re
import subprocess
import unittest
import test_source_ingestion as base

MIGRATION=base.GS/'migrations/004-lc2-telemetry.sql'
@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for private PostgreSQL checks')
class LC2Database(base.SourceIngestionDatabase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sql(MIGRATION.read_text());cls.sql(MIGRATION.read_text())
    def frame(self,**extra):
        values=dict(source_metadata_version=2,operating_profile=2,load_cell_2_raw=-321,
                    load_cell_2_voltage=0.125,load_cell_2_valid='true')
        values.update(extra);return self.insert(**values)
    def test_test_stand_local_validity_clears_pressure_and_actuator_placeholders(self):
        self.sql(self.frame(pt3=123,pt4=456,sv_2_open='true',mav_open='true',configured_devices_mask=0))
        self.assertEqual(self.sql('SELECT pt3 IS NULL,pt4 IS NULL,sv_2_open IS NULL,mav_open IS NULL FROM telemetry_data;'),'t|t|t|t')

    def test_v2_roundtrip_and_exact_retry(self):
        self.sql(self.frame());self.sql(self.frame(arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT source_identity_valid,load_cell_2_raw,load_cell_2_voltage,load_cell_2_valid,operating_profile FROM telemetry_data;'),'t|-321|0.125|t|2')
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_session_head(0,100,200);'),'1')
    def test_changed_lc2_same_identity_is_rejected(self):
        self.sql(self.frame())
        for extra in [dict(load_cell_2_raw=322),dict(load_cell_2_voltage=0.25),dict(load_cell_2_valid='false')]:
            with self.subTest(extra=extra),self.assertRaises(subprocess.CalledProcessError):self.sql(self.frame(**extra))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
    def test_invalid_measurements_and_wrong_profile_fail_without_receipts(self):
        for extra in [dict(load_cell_2_voltage="'NaN'"),dict(load_cell_2_raw=32768),
                      dict(operating_profile=0),dict(load_cell_2_voltage="'Infinity'")]:
            with self.subTest(extra=extra),self.assertRaises(subprocess.CalledProcessError):self.sql(self.frame(**extra))
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'0')
    def test_v1_cannot_claim_valid_lc2_without_v2_integrity(self):
        self.sql(self.frame(source_metadata_version=1))
        self.assertEqual(self.sql('SELECT load_cell_2_valid,source_identity_valid FROM telemetry_data;'),'f|t')

    def test_unavailable_lc2_stays_explicitly_invalid(self):
        self.sql(self.frame(load_cell_2_raw=0,load_cell_2_voltage=0,load_cell_2_valid='false'))
        self.assertEqual(self.sql('SELECT load_cell_2_valid,source_identity_valid FROM telemetry_data;'),'f|t')
    def test_v1_receipt_survives_extension_migration(self):
        self.sql((base.GS/'migrations/002-source-metadata.sql').read_text())
        self.sql(self.insert())
        before=self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;")
        self.sql(MIGRATION.read_text())
        self.sql(self.insert(arrival='2027-01-01 UTC'))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        self.assertEqual(self.sql("SELECT encode(payload_sha256,'hex') FROM ground_telemetry_private.source_receipts;"),before)
    def test_views_include_lc2_and_reader_permissions_survive_repeated_provisioning(self):
        self.sql(self.frame())
        self.assertEqual(self.sql('SET ROLE ground_reader; SELECT load_cell_2_raw FROM telemetry_session_head(0,100,200);'),'-321')
        self.assertEqual(self.sql('SET ROLE ground_reader; SELECT load_cell_2_voltage FROM telemetry_session_history(0,100,200);'),'0.125')
    def test_real_action_template_preserves_signed_lc2_fields(self):
        fields=re.findall(r'\b(\w+)\s+(\w+)\s*=\s*(\d+)\s*;', (base.GS/'proto/telemetry.proto').read_text())
        data={name:'false' if kind=='bool' else '0' for kind,name,_ in fields}
        data.update(availability_version='1',unit_id='0',broker_arrival_ms='1800000000123',source_metadata_version='2',
                    publisher_session_hi='100',publisher_session_lo='200',publisher_sequence='1',
                    source_time_generation='1',operating_profile='2',load_cell_2_raw='-321',
                    load_cell_2_voltage='0.125',load_cell_2_valid='true')
        template=(base.GS/'emqx_action.sql').read_text()
        self.sql(re.sub(r'\$\{(\w+)\}',lambda m:data[m.group(1)],template))
        self.assertEqual(self.sql('SELECT load_cell_2_raw,load_cell_2_voltage,source_identity_valid FROM telemetry_data;'),'-321|0.125|t')

    def test_full_migration_reapply_preserves_receipt_and_views(self):
        self.sql(self.frame())
        for file in ['001-hardware-availability.sql','002-source-metadata.sql','003-session-queries.sql','004-lc2-telemetry.sql']:
            self.sql((base.GS/'migrations'/file).read_text())
        self.sql(self.frame())
        self.assertEqual(self.sql('SET ROLE ground_reader; SELECT count(*) FROM telemetry_session_history(0,100,200);'),'1')

for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(LC2Database,name,None)
class LC2Partitions(LC2Database):PARTITIONED=True
if __name__=='__main__':unittest.main()
