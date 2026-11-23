"""Real PostgreSQL session query contracts; no live station access."""
import os
from pathlib import Path
import unittest
import subprocess
import test_source_ingestion as ingestion
GS = ingestion.GS

MIGRATION = GS / 'migrations/003-session-queries.sql'

@unittest.skipUnless(os.environ.get('PG_BIN'), 'set PG_BIN for isolated PostgreSQL checks')
class SessionQueries(ingestion.SourceIngestionDatabase):
    # Reuse only the isolated database fixture, not its ingestion test cases.
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sql(MIGRATION.read_text())
        cls.sql(MIGRATION.read_text())
        cls.sql((GS/'provisioning/roles.sql').read_text(), env={**os.environ,
            'CRT_INGEST_PASSWORD':'fixture-only-ingest','CRT_READER_PASSWORD':'fixture-only-reader'})

    def test_selected_head_ignores_late_lower_sequence_and_other_sessions(self):
        self.sql(self.insert(seq=9,pressure=90,arrival='2026-11-23 00:00:01+00'))
        self.sql(self.insert(seq=2,pressure=20,arrival='2026-11-23 00:00:09+00'))
        self.sql(self.insert(seq=100,hi=999,pressure=1000))
        self.assertEqual(self.sql('SELECT publisher_sequence,pt_1_pressure FROM telemetry_session_head(0,100,200);'),'9|90')
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_session_head(0,123,456);'),'0')

    def test_history_uses_sequence_even_when_source_and_arrival_times_go_backward(self):
        for seq,arrival,unix in [(3,'2026-11-23 00:00:01+00',1800000000001),
                                 (1,'2026-11-23 00:00:03+00',1800000000003),
                                 (2,'2026-11-23 00:00:02+00',1800000000002)]:
            self.sql(self.insert(seq=seq,arrival=arrival,unix=unix))
        self.assertEqual(self.sql('SELECT publisher_sequence FROM telemetry_session_history(0,100,200,1,1);'),'2')
        self.assertEqual(self.sql('SELECT publisher_sequence FROM telemetry_session_history(0,100,200,0,100);'),'1\n2\n3')

    def test_catalog_lists_sessions_without_guessing_active_and_excludes_legacy(self):
        self.sql(self.insert(seq=5,hi=18446744073709551615,lo=1))
        self.sql(self.insert(seq=1,hi=2,lo=3))
        self.sql("INSERT INTO telemetry_data(time,unit_id) VALUES(now(),0);")
        self.assertEqual(self.sql('SELECT count(*),max(last_sequence) FROM telemetry_sessions;'),'2|5')
        self.assertEqual(self.sql('SELECT session_id FROM telemetry_sessions WHERE publisher_session_hi=18446744073709551615;'),
                         'ffffffffffffffff0000000000000001')

    def test_invalid_identifiers_and_unbounded_requests_are_rejected(self):
        for args in ['0,0,0,0,10','0,-1,2,0,10','0,1.5,2,0,10',
                     '0,1,2,-1,10','0,1,2,0,0','0,1,2,0,1001',
                     '0,NULL,2,0,10','0,1,2,NULL,10','0,1,2,0,NULL']:
            with self.subTest(args=args), self.assertRaises(subprocess.CalledProcessError):
                self.sql('SELECT * FROM telemetry_session_history('+args+');')

    def test_reader_can_query_but_ingest_and_public_cannot_execute(self):
        self.sql(self.insert(seq=7))
        self.assertEqual(self.sql('SET ROLE ground_reader; SELECT publisher_sequence FROM telemetry_session_head(0,100,200);'),'7')
        for role in ['ground_ingest','session_query_stranger']:
            if role=='session_query_stranger':self.sql('CREATE ROLE session_query_stranger;')
            with self.assertRaises(subprocess.CalledProcessError):
                self.sql('SET ROLE '+role+'; SELECT * FROM telemetry_session_head(0,100,200);')
        self.sql('DROP ROLE session_query_stranger;')

# Do not repeat the base suite here; it is run separately.
for _name in list(vars(ingestion.SourceIngestionDatabase)):
    if _name.startswith('test_'):
        setattr(SessionQueries, _name, None)

class PartitionedSessionQueries(SessionQueries):
    PARTITIONED = True

class SessionQueryAssets(unittest.TestCase):
    def test_migration_is_packaged_and_applied_before_roles(self):
        root = GS.parent
        runtime = (GS/'provisioning/runtime.py').read_text()
        self.assertIn('migrations/003-session-queries.sql',
                      (root/'nix/packages/crt/ground-telemetry/package.nix').read_text())
        self.assertLess(runtime.index('(assets / "migrations/003-session-queries.sql")'),
                        runtime.index('(assets / "provisioning/roles.sql")'))

if __name__ == '__main__':unittest.main()
