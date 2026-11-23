"""Execute generated Grafana SQL in disposable PostgreSQL, not a live dashboard."""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import test_source_ingestion as ingestion

spec=importlib.util.spec_from_file_location('runtime',ingestion.GS/'provisioning/runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)

@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for PostgreSQL checks')
class GrafanaSessions(ingestion.SourceIngestionDatabase):
    def setUp(self):
        super().setUp()
        with tempfile.TemporaryDirectory() as d:
            runtime.build_assets(ingestion.GS,d)
            self.dashboard=json.loads((Path(d)/'grafana/dashboards/dashboard.json').read_text())
        self.panels={p['id']:p for p in self.dashboard['panels']}

    def query(self,panel,selection):
        q=self.panels[panel]['targets'][0]['rawSql']
        q=q.replace('${fill_session:sqlstring}',"'"+selection.replace("'","''")+"'")
        return re.sub(r'\$__timeFilter\(time\)',"time BETWEEN '2026-01-01' AND '2028-01-01'",q)

    def test_explicit_default_and_catalog_values_preserve_uint64(self):
        v=self.dashboard['templating']['list'][0]
        self.assertEqual(v['current']['value'],'none')
        self.assertFalse(v['multi']);self.assertFalse(v['includeAll'])
        self.sql(self.insert(hi=18446744073709551615,lo=1))
        self.assertIn('18446744073709551615:1',self.sql(v['query']))

    def test_head_does_not_regress_or_mix_sessions(self):
        self.sql(self.insert(seq=9,pressure=90))
        self.sql(self.insert(seq=2,pressure=20,arrival='2026-11-24 UTC'))
        self.sql(self.insert(seq=99,hi=999,pressure=999))
        self.assertEqual(self.sql(self.query(6,'100:200')).split('|')[0],'90')
        for value in ['none','123:456','18446744073709551616:1',"100:200' OR true --",'1.5:200']:
            self.assertEqual(self.sql(self.query(6,value)),'')

    def test_legacy_choice_is_explicit_and_excludes_modern(self):
        self.sql("INSERT INTO telemetry_data(time,unit_id,pt_1_pressure) VALUES('2026-11-25',0,42);")
        self.sql(self.insert(pressure=99))
        self.sql("INSERT INTO telemetry_data(time,unit_id,pt_1_pressure,publisher_sequence) VALUES('2026-11-24',0,20,999);")
        self.assertEqual(self.sql(self.query(6,'legacy')).split('|')[0],'42')
        self.assertEqual(self.sql(self.query(6,'none')),'')

    def test_all_fill_queries_execute_and_flight_layout_is_preserved(self):
        self.sql(self.insert())
        original=json.loads((ingestion.GS/'grafana.json').read_text())
        for panel in original['panels']:
            generated=self.panels[panel['id']]
            self.assertEqual(panel.get('gridPos'),generated.get('gridPos'))
            self.assertEqual(panel['type'],generated['type'])
            if panel['id'] in [2,3,4,5,6,35]:
                self.sql(self.query(panel['id'],'100:200'))
                self.assertIn('arrival',generated['description'].lower())
            elif panel['id'] not in [1,23,27]:
                self.assertEqual(panel.get('targets'),generated.get('targets'))

class PartitionedGrafanaSessions(GrafanaSessions):
    PARTITIONED = True

for name in vars(ingestion.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(GrafanaSessions,name,None)

if __name__=='__main__':unittest.main()
