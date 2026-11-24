"""Generate read-only SQL for one explicit telemetry session; never connects itself."""
import argparse
import re


def session_parts(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{32}',value) or int(value,16)==0:
        raise ValueError('Expected nonzero 32-hex publisher session ID')
    return int(value[:16],16),int(value[16:],16)


def report_sql(session,window_seconds=60,target_hz=10,*,clock_agreement_verified=False):
    hi,lo=session_parts(session)
    if type(window_seconds) is not int or not 1<=window_seconds<=3600:raise ValueError('Window must be 1..3600 seconds')
    if type(target_hz) is not int or not 1<=target_hz<=50:raise ValueError('Target rate must be 1..50 Hz')
    if type(clock_agreement_verified) is not bool:raise ValueError('Clock assertion must be boolean')
    # Only parsed integers, normalized hex and a literal boolean enter SQL.
    clock='true' if clock_agreement_verified else 'false'
    return f"""BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
WITH frames AS MATERIALIZED (
 SELECT publisher_sequence, received_at, source_time_generation, source_event_time
 FROM public.telemetry_data
 WHERE unit_id=0 AND source_identity_valid
   AND publisher_session_hi={hi} AND publisher_session_lo={lo}
   AND received_at >= CURRENT_TIMESTAMP - make_interval(secs => {window_seconds})
   AND received_at < CURRENT_TIMESTAMP
), groups AS (
 SELECT received_at, max(publisher_sequence) AS top_sequence, count(*) AS n
 FROM frames GROUP BY received_at
), ordering AS (
 SELECT *, max(top_sequence) OVER (ORDER BY received_at
   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_max
 FROM groups
), summary AS (
 SELECT count(*) AS n, min(publisher_sequence) AS first_seq,
   max(publisher_sequence) AS last_seq,
   count(DISTINCT publisher_sequence) AS distinct_sequences,
   min(received_at) AS first_receipt, max(received_at) AS last_receipt,
   count(DISTINCT source_time_generation) AS generations,
   count(*) FILTER (WHERE source_event_time IS NOT NULL) AS timed_frames
 FROM frames
), latency AS (
 SELECT count(*) AS n,
   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (received_at-source_event_time))*1000) AS p50,
   percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (received_at-source_event_time))*1000) AS p95,
   min(extract(epoch FROM (received_at-source_event_time))*1000) AS minimum,
   max(extract(epoch FROM (received_at-source_event_time))*1000) AS maximum
 FROM frames WHERE source_event_time IS NOT NULL
)
SELECT json_build_object(
 'schemaVersion',1,'session','{session.lower()}',
 'windowSeconds',{window_seconds},'targetHz',{target_hz},
 'windowStart',CURRENT_TIMESTAMP-make_interval(secs => {window_seconds}),
 'windowEnd',CURRENT_TIMESTAMP,'storedFrames',s.n,
 'databaseReceiptHz',s.n::numeric/{window_seconds},
 'firstSequence',s.first_seq::text,'lastSequence',s.last_seq::text,
 'missingWithinObservedRange',coalesce(s.last_seq-s.first_seq+1-s.distinct_sequences,0),
 'firstReceivedAt',s.first_receipt,'lastReceivedAt',s.last_receipt,
 'tiedReceiptFrames',(SELECT coalesce(sum(n) FILTER (WHERE n>1),0) FROM groups),
 'lowerSequenceAfterHigherTimestampGroups',
   (SELECT count(*) FROM frames f JOIN ordering o USING (received_at)
    WHERE f.publisher_sequence<o.previous_max),
 'clockGenerations',s.generations,'qualifiedTimeFrames',s.timed_frames,
 'clockAgreementAsserted',{clock},
 'latencyMs',CASE WHEN {clock} AND s.generations=1 AND l.n>0 THEN
   json_build_object('samples',l.n,'p50',l.p50,'p95',l.p95,'minimum',l.minimum,'maximum',l.maximum)
   ELSE NULL END,
 'scope','stored database receipts; internal gaps are not proven packet loss; timestamp order is not physical arrival order'
) FROM summary s CROSS JOIN latency l;
COMMIT;
"""


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True,help='exact 32-hex MQTT publisher session, not CSV session')
    parser.add_argument('--window-seconds',type=int,default=60)
    parser.add_argument('--target-hz',type=int,default=10,help='operator-recorded target, not auto-detected')
    parser.add_argument('--clock-agreement-verified',action='store_true',help='explicit operator assertion; enables qualified signed latency summaries')
    args=parser.parse_args(argv)
    try:query=report_sql(args.session,args.window_seconds,args.target_hz,clock_agreement_verified=args.clock_agreement_verified)
    except ValueError as error:parser.error(str(error))
    print(query,end='')
    return 0


if __name__=='__main__':raise SystemExit(main())
