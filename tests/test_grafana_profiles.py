"""Generated Hybrid-test dashboard correctness in disposable PostgreSQL."""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import test_source_ingestion as base
spec=importlib.util.spec_from_file_location('runtime',base.GS/'provisioning/runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)

@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for private PostgreSQL checks')
class GrafanaProfiles(base.SourceIngestionDatabase):
    def setUp(self):
        super().setUp()
        with tempfile.TemporaryDirectory() as d:
            runtime.build_assets(base.GS,d,cameras=True)
            self.dashboard=json.loads((Path(d)/'grafana/dashboards/hybrid-test.json').read_text())
        self.panels={p['id']:p for p in self.dashboard['panels']}
    def frame(self,**extra):
        values=dict(source_metadata_version=2,operating_profile=2,load_cell_2_raw=123,
            load_cell_2_voltage=0.25,load_cell_2_valid='true',valid_readings_mask=31,
            pt3=300,pt4=400,load_cell=55)
        values.update(extra);return self.insert(**values)
    def query(self,panel,selection='100:200'):
        q=self.panels[panel]['targets'][0]['rawSql'].replace('${fill_session:sqlstring}',"'"+selection.replace("'","''")+"'")
        return re.sub(r'\$__timeFilter\(([^)]+)\)',r"\1 BETWEEN '2026-01-01' AND '2028-01-01'",q)
    def test_test_dashboard_keeps_fill_layout_and_removes_fsw(self):
        self.assertEqual(self.dashboard['uid'],'fillops-hybrid-test')
        self.assertEqual(set(self.panels),{7,1,2,3,5,35,6,4})
        old={p['id']:p for p in json.loads((base.GS/'grafana.json').read_text())['panels']}
        for id,panel in self.panels.items():self.assertEqual(panel['gridPos'],old[id]['gridPos'])
        self.assertIn('/cameras/',self.panels[1]['options']['content'])
        self.assertEqual(self.panels[35]['title'],'Load Cell 2 (uncalibrated)')
        self.assertNotIn('masslb',json.dumps(self.panels[3]))
        self.assertNotIn('fahrenheit',json.dumps(self.panels[35]))
        self.assertNotIn('flight_mode',self.query(5))
        self.assertNotIn('qd_state',self.query(5))
    def test_catalog_only_lists_explicit_test_sessions_and_defaults_to_none(self):
        self.sql(self.frame())
        self.sql(self.insert(hi=999))
        variable=self.dashboard['templating']['list'][0]
        self.assertEqual(variable['current']['value'],'none')
        choices=self.sql(variable['query'])
        self.assertIn('100:200',choices);self.assertNotIn('999:200',choices);self.assertNotIn('legacy',choices.lower())
        for selection in ['none','legacy','999:200',"100:200' OR true --"]:
            self.assertEqual(self.sql(self.query(35,selection)),'')
    def test_lc1_lc2_heads_use_sequence_and_invalid_latest_does_not_reuse_prior_value(self):
        self.sql(self.frame(seq=9,load_cell=99))
        self.sql(self.frame(seq=2,load_cell=22,arrival='2026-11-24 UTC',load_cell_2_raw=222))
        self.assertEqual(self.sql(self.query(3)),'99')
        self.assertEqual(self.sql(self.query(35)),'123|0.25')
        self.sql(self.frame(seq=10,load_cell_2_valid='false',load_cell_2_raw=0,load_cell_2_voltage=0))
        self.assertEqual(self.sql(self.query(35)),'|')
        self.assertEqual(self.panels[35]['options']['reduceOptions']['calcs'],['last'])
    def test_valid_zero_lc2_is_not_replaced_by_unavailable(self):
        self.sql(self.frame(load_cell_2_raw=0,load_cell_2_voltage=0))
        self.assertEqual(self.sql(self.query(35)),'0|0')

    def test_all_queries_execute_as_reader_and_invalid_pressure_is_null(self):
        self.sql(self.frame(valid_readings_mask=7))
        for id in [2,3,4,5,6,35]:self.sql('SET ROLE ground_reader; '+self.query(id))
        self.assertEqual(self.sql(self.query(6)).split('|')[-2:],['',''])
for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(GrafanaProfiles,name,None)
class PartitionedGrafanaProfiles(GrafanaProfiles):PARTITIONED=True
if __name__=='__main__':unittest.main()
