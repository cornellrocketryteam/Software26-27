"""Generated read-only receiver measurement SQL, not actual throughput evidence."""
import importlib.util
import json
import os
import unittest
import test_source_ingestion as base
spec=importlib.util.spec_from_file_location('throughput',base.GS/'provisioning/throughput.py')
throughput=importlib.util.module_from_spec(spec);spec.loader.exec_module(throughput)

class ReportInputs(unittest.TestCase):
    def test_session_and_bounds(self):
        self.assertEqual(throughput.session_parts('ffffffffffffffff0000000000000001'),(18446744073709551615,1))
        for value in ['0'*32,'1:2',"x' OR true --",'f'*31,'g'*32]:
            with self.assertRaises(ValueError):throughput.session_parts(value)
        for args in [(0,10),(3601,10),(60,0),(60,51),(True,10)]:
            with self.assertRaises(ValueError):throughput.report_sql('0'*31+'1',*args)

@unittest.skipUnless(os.environ.get('PG_BIN'),'set PG_BIN for disposable PostgreSQL')
class ReceiverReport(base.SourceIngestionDatabase):
    def report(self,**kwargs):
        query=throughput.report_sql('000000000000006400000000000000c8',60,50,**kwargs)
        return json.loads(self.sql('SET ROLE ground_reader; '+query))
    def test_empty_window_does_not_choose_another_session(self):
        self.sql(self.insert(hi=999))
        report=self.report()
        self.assertEqual(report['storedFrames'],0)
        self.assertIsNone(report['firstSequence'])
        self.assertIsNone(report['latencyMs'])
    def test_rate_internal_gaps_and_duplicates(self):
        self.sql(self.insert(seq=1));self.sql(self.insert(seq=3));self.sql(self.insert(seq=3))
        report=self.report()
        self.assertEqual(report['storedFrames'],2)
        self.assertEqual(report['missingWithinObservedRange'],1)
        self.assertAlmostEqual(report['databaseReceiptHz'],2/60)
        self.assertEqual(report['lastSequence'],'3')
        self.assertFalse(report['clockAgreementAsserted'])
    def test_old_receipts_excluded_and_tied_order_is_not_invented(self):
        self.sql(self.insert(seq=9));self.sql(self.insert(seq=2));self.sql(self.insert(seq=1))
        self.sql("UPDATE telemetry_data SET received_at=clock_timestamp()-interval '2 minutes' WHERE publisher_sequence=1;")
        self.sql("UPDATE telemetry_data SET received_at=CURRENT_TIMESTAMP WHERE publisher_sequence IN (2,9);")
        report=self.report()
        self.assertEqual(report['storedFrames'],2)
        self.assertEqual(report['tiedReceiptFrames'],2)
        self.assertEqual(report['lowerSequenceAfterHigherTimestampGroups'],0)
    def test_latency_stays_unavailable_across_clock_generations_or_unknown_time(self):
        self.sql(self.insert(seq=1,source_time_generation=1))
        self.sql(self.insert(seq=2,source_time_generation=2))
        self.assertIsNone(self.report(clock_agreement_verified=True)['latencyMs'])
        self.sql('TRUNCATE telemetry_data,ground_telemetry_private.source_receipts;')
        self.sql(self.insert(valid='false',quality=0,unix=0))
        report=self.report(clock_agreement_verified=True)
        self.assertEqual(report['qualifiedTimeFrames'],0)
        self.assertIsNone(report['latencyMs'])
    def test_timestamp_group_regression_and_latency_opt_in(self):
        self.sql(self.insert(seq=9));self.sql(self.insert(seq=2))
        self.sql("UPDATE telemetry_data SET received_at=clock_timestamp()-interval '10 seconds' WHERE publisher_sequence=9;")
        report=self.report(clock_agreement_verified=True)
        self.assertEqual(report['lowerSequenceAfterHigherTimestampGroups'],1)
        self.assertEqual(report['latencyMs']['samples'],2)
        self.assertTrue(report['clockAgreementAsserted'])
        self.assertIsNone(self.report()['latencyMs'])
for name in vars(base.SourceIngestionDatabase):
    if name.startswith('test_'):setattr(ReceiverReport,name,None)
class PartitionedReceiverReport(ReceiverReport):PARTITIONED=True
if __name__=='__main__':unittest.main()
