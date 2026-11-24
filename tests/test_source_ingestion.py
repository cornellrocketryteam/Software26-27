"""Isolated PostgreSQL 17 source-metadata ingestion, rollback, ACL and race tests.

Set PG_BIN to a PostgreSQL 17 bin directory. Uses private Unix sockets only.
No Timescale container, real broker or operational database is contacted.
"""
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
GS=ROOT/'ground-station'
MIGRATION=GS/'migrations/002-source-metadata.sql'
PG_BIN=os.environ.get('PG_BIN')
MAX_U64=18446744073709551615

class SourceIngestionAssets(unittest.TestCase):
    def test_migration_exists_and_is_in_immutable_and_runtime_asset_lists(self):
        self.assertTrue(MIGRATION.is_file(),'source metadata migration not implemented')
        for path in (ROOT/'nix/packages/crt/ground-telemetry/package.nix',GS/'provisioning/runtime.py'):
            self.assertIn('migrations/002-source-metadata.sql',path.read_text())

    def test_unsigned_metadata_has_explicit_text_boundary_for_prepared_driver_parameters(self):
        rule=(GS/'emqx_rule_fill_station.sql').read_text()
        action=(GS/'emqx_action.sql').read_text()
        for name in ('publisher_session_hi','publisher_session_lo','publisher_sequence','source_monotonic_ms','source_unix_ms','adc1_sample_age_ms','adc2_sample_age_ms','fsw_receive_age_ms'):
            self.assertIn('str(payload.'+name+')',rule)
            self.assertIn('CAST(CAST(${'+name+'} AS TEXT) AS NUMERIC)',action)

@unittest.skipUnless(PG_BIN,'set PG_BIN for isolated PostgreSQL source ingestion checks')
class SourceIngestionDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not MIGRATION.exists():raise unittest.SkipTest('migration not implemented yet')
        cls.temp=tempfile.TemporaryDirectory(prefix='crt-source-db-',dir='/tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work=Path(cls.temp.name)
        cls.bin=Path(PG_BIN)
        cls.call('initdb','-D',str(cls.work/'data'),'-U','postgres','-A','trust','--no-locale')
        cls.call('pg_ctl','-D',str(cls.work/'data'),'-l',str(cls.work/'server.log'),'-o',
                 f"-k {cls.work} -c listen_addresses='' -c shared_buffers=16MB -c max_connections=12 -c timezone=UTC",'-w','start')
        cls.addClassCleanup(lambda:cls.call('pg_ctl','-D',str(cls.work/'data'),'-m','immediate','-w','stop'))
        cls.call('createdb','-h',str(cls.work),'-U','postgres','telemetry')
        schema=(GS/'create-telemetry-table.sql').read_text().replace("SELECT create_hypertable('telemetry_data', 'time');",'')
        if getattr(cls,'PARTITIONED',False):
            schema=schema.replace('\n);','\n) PARTITION BY RANGE(time);',1)
        cls.sql(schema)
        if getattr(cls,'PARTITIONED',False):
            cls.sql("CREATE TABLE telemetry_arrival_2026 PARTITION OF telemetry_data FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');"
                    "CREATE TABLE telemetry_arrival_2027 PARTITION OF telemetry_data FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');"
                    "CREATE TABLE telemetry_arrival_other PARTITION OF telemetry_data DEFAULT;")
        cls.sql((GS/'migrations/001-hardware-availability.sql').read_text())
        cls.sql("INSERT INTO telemetry_data(time,unit_id,pt_1_pressure) VALUES('2026-11-01 UTC',0,321);")
        cls.sql(MIGRATION.read_text());cls.sql(MIGRATION.read_text())
        cls.legacy_migration=cls.sql('SELECT time,pt_1_pressure,source_metadata_version,source_event_time IS NULL,received_at IS NULL FROM telemetry_data;')
        cls.sql((GS/'migrations/003-session-queries.sql').read_text())
        cls.sql((GS/'migrations/004-lc2-telemetry.sql').read_text())
        cls.sql((GS/'migrations/005-operating-profile-identity.sql').read_text())
        cls.sql((GS/'migrations/006-output-diagnostics.sql').read_text())
        cls.sql((GS/'provisioning/roles.sql').read_text(),env={**os.environ,'CRT_INGEST_PASSWORD':'fixture-only-ingest','CRT_READER_PASSWORD':'fixture-only-reader'})

    @classmethod
    def call(cls,tool,*args,**kwargs):
        return subprocess.run([str(cls.bin/tool),*args],text=True,capture_output=True,check=True,timeout=30,**kwargs).stdout.strip()

    @classmethod
    def command(cls):
        return [str(cls.bin/'psql'),'-X','-qAt','-h',str(cls.work),'-U','postgres','-d','telemetry','-v','ON_ERROR_STOP=1']

    @classmethod
    def sql(cls,text,**kwargs):
        return subprocess.run(cls.command(),input=text,text=True,capture_output=True,check=True,timeout=15,**kwargs).stdout.strip()

    def setUp(self):
        self.sql('TRUNCATE telemetry_data,ground_telemetry_private.source_receipts;')

    def insert(self,seq=1,hi=100,lo=200,arrival='2026-11-23 00:00:00+00',pressure=12.5,unix=1800000000123,valid='true',quality=1,**overrides):
        data={'time':"'"+arrival+"'",'unit_id':0,'pt_1_pressure':pressure,
              'availability_version':1,'configured_devices_mask':4095,'valid_readings_mask':7,
              'broker_arrival_ms':1800000001000,'source_metadata_version':1,
              'publisher_session_hi':hi,'publisher_session_lo':lo,'publisher_sequence':seq,
              'source_monotonic_ms':100,'source_unix_ms':unix,'source_unix_valid':valid,
              'source_time_quality':quality,'source_time_generation':1}
        data.update(overrides)
        return 'INSERT INTO telemetry_data('+','.join(data)+') VALUES('+','.join(map(str,data.values()))+');'

    def test_idempotent_migration_keeps_preexisting_history_and_does_not_invent_receipt_time(self):
        self.assertEqual(self.legacy_migration,'2026-11-01 00:00:00+00|321|0|t|t')
        self.sql("INSERT INTO telemetry_data(time,unit_id,pt_1_pressure) VALUES('2026-11-02 UTC',1,12);")
        self.sql(MIGRATION.read_text())
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'0')

    def test_shuffled_delivery_keeps_history_but_latest_uses_sequence(self):
        for seq in (3,1,2):self.sql(self.insert(seq=seq,pressure=seq))
        self.assertEqual(self.sql('SELECT publisher_sequence FROM telemetry_data ORDER BY publisher_sequence;'),'1\n2\n3')
        self.assertEqual(self.sql('SELECT publisher_sequence,pt_1_pressure FROM telemetry_latest_in_session;'),'3|3')

    def test_retry_with_different_arrival_time_is_suppressed(self):
        self.sql(self.insert());self.sql(self.insert(arrival='2027-02-01 UTC',broker_arrival_ms=1800999999999))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'1')

    def test_conflicting_payload_for_same_identity_fails_without_overwrite(self):
        self.sql(self.insert())
        with self.assertRaises(subprocess.CalledProcessError):self.sql(self.insert(pressure=999))
        self.assertEqual(self.sql('SELECT pt_1_pressure FROM telemetry_data;'),'12.5')

    def test_receipt_rolls_back_if_later_row_constraint_fails(self):
        self.sql('ALTER TABLE telemetry_data ADD CONSTRAINT fixture_positive CHECK(pt_1_pressure>=0);')
        try:
            with self.assertRaises(subprocess.CalledProcessError):self.sql(self.insert(pressure=-1))
            self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'0')
            self.sql(self.insert(pressure=1))
            self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
        finally:self.sql('ALTER TABLE telemetry_data DROP CONSTRAINT fixture_positive;')

    def test_uint64_values_are_exact_and_fractional_identity_is_not_rounded(self):
        self.sql(self.insert(seq=MAX_U64,hi=MAX_U64,lo=MAX_U64,source_monotonic_ms=MAX_U64))
        self.assertEqual(self.sql('SELECT publisher_session_hi,publisher_sequence,source_identity_valid FROM telemetry_data;'),f'{MAX_U64}|{MAX_U64}|t')
        self.sql(self.insert(seq='1.1',lo=201))
        self.assertEqual(self.sql('SELECT publisher_sequence,source_identity_valid FROM telemetry_data WHERE publisher_session_lo=201;'),'1.1|f')
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'1')

    def test_equivalent_integer_text_forms_share_a_canonical_v1_fingerprint(self):
        self.sql(self.insert(seq='1.0',hi='100.000'))
        self.sql(self.insert(seq=1,hi=100))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')

    def test_unknown_time_is_null_and_backward_clock_does_not_revert_session_latest(self):
        self.sql(self.insert(seq=1,unix=0,valid='false',quality=0))
        self.assertEqual(self.sql('SELECT source_event_time IS NULL,time_provenance FROM telemetry_data;'),'t|source-unsynchronized')
        self.sql(self.insert(seq=2,unix=1800000000000))
        self.sql(self.insert(seq=3,unix=1700000000000,source_time_generation=2))
        self.assertEqual(self.sql('SELECT publisher_sequence,source_unix_ms FROM telemetry_latest_in_session;'),'3|1700000000000')
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_event_history;'),'3')

    def test_distinct_sessions_have_separate_heads_not_random_id_recency(self):
        self.sql(self.insert(seq=20,lo=300));self.sql(self.insert(seq=1,lo=301))
        self.assertEqual(self.sql('SELECT publisher_session_lo,publisher_sequence FROM telemetry_latest_in_session ORDER BY publisher_session_lo;'),'300|20\n301|1')

    def test_ingest_role_can_insert_but_cannot_read_or_modify_private_receipts(self):
        self.sql('SET ROLE ground_ingest;'+self.insert())
        for statement in ('SELECT * FROM ground_telemetry_private.source_receipts;',
                          'DELETE FROM ground_telemetry_private.source_receipts;',
                          'UPDATE telemetry_data SET pt_1_pressure=55;'):
            with self.assertRaises(subprocess.CalledProcessError):self.sql('SET ROLE ground_ingest;'+statement)
        self.assertEqual(self.sql('SET ROLE ground_reader;SELECT count(*) FROM telemetry_latest_in_session;'),'1')

    def test_concurrent_retries_commit_only_one_receipt_and_row(self):
        processes=[]
        try:
            for _ in range(2):
                p=subprocess.Popen(self.command(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                p.stdin.write('BEGIN;'+self.insert()+'SELECT pg_sleep(0.2);COMMIT;')
                p.stdin.close();p.stdin=None;processes.append(p)
            for p in processes:
                out,err=p.communicate(timeout=15)
                self.assertEqual(p.returncode,0,out+err)
            self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
            self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'1')
        finally:
            for p in processes:
                if p.poll() is None:p.kill();p.wait()

    def test_future_table_columns_do_not_change_existing_v1_fingerprints(self):
        self.sql(self.insert())
        self.sql('ALTER TABLE telemetry_data ADD COLUMN fixture_future INTEGER;')
        try:
            self.sql(self.insert(fixture_future=77))
            self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'1')
            self.assertEqual(self.sql('SELECT fixture_future IS NULL FROM telemetry_data;'),'t')
        finally:self.sql('ALTER TABLE telemetry_data DROP COLUMN fixture_future;')

    def test_legacy_unsupported_and_malformed_source_headers_keep_arrival_semantics(self):
        self.sql(self.insert(source_metadata_version=0))
        self.sql(self.insert(source_metadata_version=99))
        self.sql(self.insert(hi=0,lo=0))
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'3')
        self.assertEqual(self.sql('SELECT count(*) FROM ground_telemetry_private.source_receipts;'),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data WHERE source_event_time IS NULL;'),'3')

    def test_actual_emqx_action_template_inserts_source_fields_and_suppresses_retry(self):
        fields=re.findall(r'\b(\w+)\s+(\w+)\s*=\s*(\d+)\s*;', (GS/'proto/telemetry.proto').read_text())
        data={name:'false' if kind=='bool' else '0' for kind,name,_ in fields}
        data.update(unit_id='0',broker_arrival_ms='1800000000123',pt_1_pressure='12.5',
                    source_metadata_version='1',publisher_session_hi=str(MAX_U64),publisher_session_lo='88',
                    publisher_sequence='42',source_monotonic_ms='100',source_time_generation='1',
                    availability_version='1',configured_devices_mask='2047',valid_readings_mask='7')
        template=(GS/'emqx_action.sql').read_text()
        render=lambda:re.sub(r'\$\{(\w+)\}',lambda match:data[match.group(1)],template)
        self.sql(render())
        data['broker_arrival_ms']='1800999999999';self.sql(render())
        self.assertEqual(self.sql('SELECT count(*),max(publisher_session_hi),max(publisher_sequence) FROM telemetry_data;'),f'1|{MAX_U64}|42')

    def test_prepared_action_binds_unsigned_fields_as_text_before_numeric_cast(self):
        fields=re.findall(r'\b(\w+)\s+(\w+)\s*=\s*(\d+)\s*;', (GS/'proto/telemetry.proto').read_text())
        data={name:'false' if kind=='bool' else '0' for kind,name,_ in fields}
        data.update(unit_id='0',broker_arrival_ms='1800000000123',source_metadata_version='1',
                    publisher_session_hi=str(MAX_U64),publisher_session_lo='1',publisher_sequence=str(MAX_U64),
                    source_monotonic_ms='10',source_time_generation='1')
        names=[]
        def parameter(match):
            names.append(match.group(1));return '$'+str(len(names))
        prepared=re.sub(r'\$\{(\w+)\}',parameter,(GS/'emqx_action.sql').read_text())
        uint64={name for kind,name,tag in fields if kind=='uint64' and int(tag)>=67}
        expected=[index for index,name in enumerate(names,1) if name in uint64]
        query='PREPARE source_fixture AS '+prepared
        query+="SELECT count(*) FROM pg_prepared_statements,unnest(parameter_types) WITH ORDINALITY AS p(t,n) WHERE name='source_fixture' AND n IN ("+','.join(map(str,expected))+") AND t='text'::regtype;"
        query+='EXECUTE source_fixture('+','.join("'"+data[name]+"'" for name in names)+');'
        self.assertEqual(self.sql(query),str(len(expected)))
        self.assertEqual(self.sql('SELECT publisher_session_hi,publisher_sequence FROM telemetry_data;'),f'{MAX_U64}|{MAX_U64}')

    def test_out_of_range_or_inconsistent_time_claims_never_create_event_time(self):
        for seq,(valid,quality,unix) in enumerate((('true',0,1800000000123),('false',1,1800000000123),('true',1,MAX_U64)),1):
            self.sql(self.insert(seq=seq,valid=valid,quality=quality,unix=unix))
        self.assertEqual(self.sql("SELECT count(*) FROM telemetry_data WHERE source_identity_valid AND source_event_time IS NULL AND time_provenance='invalid-source-time';"),'3')

class SourceIngestionPartitions(SourceIngestionDatabase):
    """Repeat against real PG time partitions; this is not a Timescale extension test."""
    PARTITIONED=True

if __name__=='__main__':unittest.main()
