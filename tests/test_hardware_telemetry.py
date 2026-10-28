"""Availability wire/schema contracts and optional real PostgreSQL trigger tests.

Set PG_BIN to a PostgreSQL bin directory to run an isolated Unix-socket database.
No configured or production database is contacted.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GS = ROOT / 'ground-station'
FIELDS = {'availability_version': 64, 'configured_devices_mask': 65, 'valid_readings_mask': 66}
MIGRATION = GS / 'migrations/001-hardware-availability.sql'

class TelemetryContracts(unittest.TestCase):
    def test_protobuf_copies_match_and_availability_fields_are_additive(self):
        fill = (ROOT/'fill-station/proto/telemetry.proto').read_text()
        self.assertEqual((GS/'proto/telemetry.proto').read_text(), fill)
        for field, number in FIELDS.items():
            self.assertRegex(fill, rf'uint32\s+{field}\s*=\s*{number}\s*;')
        self.assertRegex(fill, r'uint64\s+ms_since_boot_fill\s*=\s*63\s*;')
    def test_both_ingestion_routes_default_missing_metadata_to_legacy_zero(self):
        for name in ['emqx_rule.sql', 'emqx_rule_fill_station.sql']:
            sql = (GS/name).read_text()
            for field in FIELDS:
                self.assertRegex(sql, rf'CASE WHEN is_null\(payload\.{field}\) THEN 0 ELSE payload\.{field} END as {field}')
                self.assertIn('${'+field+'}', (GS/'emqx_action.sql').read_text())
    def test_panels_do_not_resurrect_last_valid_value(self):
        panels = json.loads((GS/'grafana.json').read_text())['panels']
        for panel in panels:
            if panel.get('id') in [3,4,5,6]:
                self.assertEqual(panel['options']['reduceOptions']['calcs'], ['last'])
                self.assertEqual(panel['fieldConfig']['defaults']['noValue'], 'Unavailable')
            if panel.get('id') == 2:
                self.assertFalse(panel['fieldConfig']['defaults']['custom']['spanNulls'])

PG_BIN = os.environ.get('PG_BIN')
@unittest.skipUnless(PG_BIN, 'set PG_BIN to run isolated PostgreSQL migration tests')
class PostgreSQLAvailability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='hardware-telemetry-')
        cls.root = Path(cls.tmp.name)
        cls.bin = Path(PG_BIN)
        cls.command('initdb', '-D', str(cls.root/'data'), '-A', 'trust', '--no-locale')
        cls.command('pg_ctl', '-D', str(cls.root/'data'), '-l', str(cls.root/'server.log'), '-o', f"-k {cls.root} -c listen_addresses=''", '-w', 'start')
        cls.psql((GS/'create-telemetry-table.sql').read_text().replace("SELECT create_hypertable('telemetry_data', 'time');", ''))
    @classmethod
    def tearDownClass(cls):
        cls.command('pg_ctl', '-D', str(cls.root/'data'), '-m', 'immediate', '-w', 'stop')
        cls.tmp.cleanup()
    @classmethod
    def command(cls, tool, *args, **kwargs):
        return subprocess.run([str(cls.bin/tool), *args], text=True, capture_output=True, check=True, **kwargs).stdout
    @classmethod
    def psql(cls, sql):
        return cls.command('psql', '-h', str(cls.root), '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-At', input=sql)
    def test_migration_idempotence_and_real_insert_update_semantics(self):
        self.assertTrue(MIGRATION.exists(), 'availability migration must exist')
        migration = MIGRATION.read_text()
        # Simulate an installed legacy table, including a stored record.
        self.psql('ALTER TABLE telemetry_data DROP COLUMN availability_version, DROP COLUMN configured_devices_mask, DROP COLUMN valid_readings_mask; INSERT INTO telemetry_data(time,unit_id,pt_1_pressure) VALUES (clock_timestamp(),0,0);')
        self.psql(migration); self.psql(migration)
        self.assertEqual(self.psql('SELECT availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure FROM telemetry_data;').strip(), '0|0|0|0')
        self.psql('TRUNCATE telemetry_data;')
        base = "pt_1_pressure,pt_2_pressure,load_cell,ball_valve_open,sv_1_open,ignition,qd_state"
        for unit,version,configured,valid in [(0,0,0,0),(1,1,0,0),(0,1,0,0),(0,1,4095,7),(0,1,18,2),(0,2,0,0)]:
            self.psql(f"INSERT INTO telemetry_data(time,unit_id,availability_version,configured_devices_mask,valid_readings_mask,{base}) VALUES (clock_timestamp(),{unit},{version},{configured},{valid},0,0,0,false,false,false,0);")
        rows = self.psql(f"SELECT unit_id,availability_version,configured_devices_mask,valid_readings_mask,{base} FROM telemetry_data ORDER BY time;").splitlines()
        self.assertEqual(rows[0], '0|0|0|0|0|0|0|f|f|f|0')
        self.assertEqual(rows[1], '1|1|0|0|0|0|0|f|f|f|0')
        self.assertEqual(rows[2], '0|1|0|0|||||||')
        self.assertEqual(rows[3], '0|1|4095|7|0|0|0|f|f|f|0')
        self.assertEqual(rows[4], '0|1|18|2||0|||f|f|')
        self.assertEqual(rows[5], '0|2|0|0|0|0|0|f|f|f|0')
        self.psql("INSERT INTO telemetry_data(time,unit_id,availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure) VALUES(clock_timestamp(),0,NULL,NULL,NULL,0);")
        self.assertEqual(self.psql('SELECT availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure FROM telemetry_data ORDER BY time DESC LIMIT 1;').strip(), '0|0|0|0')
        # UPDATE must enforce the same contract as INSERT.
        self.psql("UPDATE telemetry_data SET valid_readings_mask=0 WHERE unit_id=0 AND configured_devices_mask=4095;")
        self.assertEqual(self.psql('SELECT pt_1_pressure IS NULL AND pt_2_pressure IS NULL AND load_cell IS NULL FROM telemetry_data WHERE configured_devices_mask=4095;').strip(), 't')

if __name__ == '__main__': unittest.main()
