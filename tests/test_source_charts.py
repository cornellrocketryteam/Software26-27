"""Execute operating pressure source-time charts in disposable PostgreSQL."""
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

@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for disposable PostgreSQL')
class SourceCharts(base.SourceIngestionDatabase):
    def setUp(self):
        super().setUp()
        with tempfile.TemporaryDirectory() as directory:
            runtime.build_assets(base.GS,directory)
            root=Path(directory)/'grafana/dashboards'
            self.views={name:json.loads((root/name).read_text()) for name in ['dashboard.json','hybrid.json','hybrid-test.json']}
    def panel(self,name,id=2):return next(p for p in self.views[name]['panels'] if p['id']==id)
    def frame(self,**overrides):
        values=dict(source_metadata_version=3,operating_profile=2,load_cell_2_raw=0,load_cell_2_voltage=0,load_cell_2_valid="false")
        values.update(overrides);return self.insert(**values)
    def chart(self,selection='100:200',name='hybrid-test.json'):
        sql=self.panel(name)['targets'][0]['rawSql'].replace('${fill_session:sqlstring}',"'"+selection.replace("'","''")+"'")
        return re.sub(r'\$__timeFilter\(([^)]+)\)',r"\1 BETWEEN '2026-01-01' AND '2028-01-01'",sql)
    def test_source_order_is_independent_of_arrival_and_clock_generations_split(self):
        self.sql(self.frame(seq=9,pressure=90,unix=1800000000900,arrival='2026-11-22 UTC'))
        self.sql(self.frame(seq=2,pressure=20,unix=1800000000200,arrival='2026-11-24 UTC'))
        self.sql(self.frame(seq=10,pressure=100,unix=1800000000100,source_time_generation=2))
        rows=self.sql('SET ROLE ground_reader; '+self.chart()).splitlines()
        pt1=[row for row in rows if '|PT1 / clock ' in row]
        self.assertEqual([r.split('|')[1:] for r in pt1],[['PT1 / clock 2','100'],['PT1 / clock 1','20'],['PT1 / clock 1','90']])
    def test_same_timestamp_and_generation_uses_highest_sequence_once(self):
        self.sql(self.frame(seq=9,pressure=90))
        self.sql(self.frame(seq=2,pressure=20,arrival='2026-11-24 UTC'))
        rows=self.sql(self.chart()).splitlines()
        self.assertEqual(len(rows),4)
        self.assertEqual([r.split('|')[2] for r in rows if '|PT1 / clock 1|' in r],['90'])
        self.assertEqual(self.sql('SELECT count(*) FROM telemetry_data;'),'2')
    def test_missing_source_time_has_no_arrival_fallback_but_head_survives(self):
        self.sql(self.frame(valid='false',quality=0,unix=0,pressure=77))
        self.assertEqual(self.sql(self.chart()),'')
        sql=self.panel('hybrid-test.json',6)['targets'][0]['rawSql'].replace('${fill_session:sqlstring}',"'100:200'")
        self.assertEqual(self.sql(sql).split('|')[0],'77')
    def test_session_profile_and_unknown_selection_do_not_mix(self):
        self.sql(self.frame())
        self.sql(self.frame(hi=999,pressure=999))
        self.sql(self.frame(hi=888,operating_profile=1,pressure=888))
        for selection in ['none','legacy','888:200',"100:200' OR true --"]:
            self.assertEqual(self.sql(self.chart(selection)),'')
        self.assertIn('PT1 / clock 1',self.sql(self.chart('888:200','hybrid.json')))
    def test_default_chart_is_unchanged_and_operating_layout_preserved(self):
        default=self.panel('dashboard.json')['targets'][0]['rawSql']
        self.assertIn('$__timeFilter(time)',default)
        self.assertNotIn('clock ',default)
        for name in ['hybrid.json','hybrid-test.json']:
            panel=self.panel(name)
            self.assertEqual(panel['gridPos'],self.panel('dashboard.json')['gridPos'])
            self.assertEqual(panel['targets'][0]['format'],'time_series')
            self.assertFalse(panel['fieldConfig']['defaults']['custom']['spanNulls'])
    def test_invalid_pressure_is_null_and_time_filter_is_on_source_time(self):
        self.sql(self.frame(valid_readings_mask=0))
        self.assertIn('$__timeFilter(source_event_time)',self.panel('hybrid-test.json')['targets'][0]['rawSql'])
        self.assertTrue(all(row.endswith('|') for row in self.sql(self.chart()).splitlines()))
        self.sql(self.frame(seq=2,unix=1000))
        self.assertEqual(len(self.sql(self.chart()).splitlines()),4)
for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(SourceCharts,name,None)
class PartitionedSourceCharts(SourceCharts):PARTITIONED=True
if __name__=='__main__':unittest.main()
