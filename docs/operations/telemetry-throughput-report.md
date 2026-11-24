# Receiver-side throughput report

`crt-telemetry-throughput` generates read-only SQL for one explicitly selected
MQTT publisher session. It does not connect to any service, read credentials,
change settings, choose the newest session or command hardware. Run the SQL on
the PC's telemetry database to measure actual **stored database receipts**.

## Later mini-PC command

After deploying the updated PC candidate, capture the exact 32-hex session from
the board's `MQTT publisher session` startup line (not the CSV session). Replace
the example placeholder below. For the unchanged 10 Hz baseline:

```sh
session=REPLACE_WITH_32_HEX_PUBLISHER_SESSION
crt-telemetry-throughput --session "$session" --window-seconds 60 --target-hz 10 > "$HOME/throughput.sql"
sudo docker exec -i ground-timescaledb psql -X -qAt -U postgres -d telemetry -v ON_ERROR_STOP=1 < "$HOME/throughput.sql" > "$HOME/throughput.json"
cat "$HOME/throughput.json"
```

Run each command only after the previous one succeeds. Invalid input exits before
producing a query. The generated SQL starts a READ ONLY transaction and sets a
15-second statement timeout; it does not migrate, delete or modify data. The
example uses the container's existing local admin connection to avoid exporting
passwords; the query is also tested with `ground_reader` SELECT privileges.
From a source checkout, replace the generator command with
`python3 ground-station/provisioning/throughput.py`.

Window is 1–3600 trailing seconds on the database clock, ending at transaction
start. Target is an operator-supplied integer 1–50 Hz, not auto-detected from
firmware. Wait for a full stable window at each rate. Use a new report for each
stage and retain its board publisher summaries, session, artifact and configuration.
No database/report polling service is started by this command.

## Interpret the JSON

- `storedFrames` and `databaseReceiptHz`: distinct stored frames received during
  that exact trailing window, divided by the full window duration. This includes
  idle time, disconnects or partial startup windows. It is not broker reception
  rate, frame assembly rate or successful delivery of every queued frame.
- `firstSequence`/`lastSequence`: strings preserve full uint64 precision.
  `missingWithinObservedRange` counts sequence numbers absent between those
  bounds **within this window**. Delayed frames, window boundaries, encoding/
  queue failures and transport loss can all contribute. It is not proven packet
  loss and says nothing about sequences outside the observed bounds.
- `lowerSequenceAfterHigherTimestampGroups`: frames whose sequence is lower than
  a sequence at an earlier database `received_at` timestamp in this window.
  `tiedReceiptFrames` counts frames in timestamp groups with more than one member;
  ordering within those groups is not invented. Receipt clock corrections can
  also distort timestamp order, so this is not a physical arrival ordinal.
- `clockGenerations`/`qualifiedTimeFrames`: source-clock context for this window.
  `latencyMs` is null by default; no timing claim is inferred from synchronization.

Duplicate retries suppressed by ingestion are not visible as new stored frames.
This report cannot count rejected duplicates, conflicting payloads, broker drops
or subscriber-only traffic. It cannot distinguish wire loss from local publish
failures by itself. Compare board logs, broker counters and this report before
choosing a sustainable rate. An empty chosen session/window reports zero frames;
it does not prove the board is down or select another boot.

## Optional latency assertion

Only when independently satisfied that board and receiver clocks agree over the
measurement window, add `--clock-agreement-verified` to the generator command.
This is an explicit **operator assertion**, not a check performed by the tool.
Latency stays null if the window crosses source clock generations or has no
qualified source timestamps. Otherwise it reports sample count, p50/p95 and signed
minimum/maximum of database receipt minus board frame-assembly time. Missing-time
frames are excluded from those latency samples. Negative values are retained as
clock/order diagnostics rather than clamped to zero. These statistics include
queueing/ingestion and are not radio-only latency or individual sensor sample age.
Offline LAN clock agreement does not establish absolute UTC. Receiver clock steps
are not automatically detected; avoid those windows.

## Limits and pending acceptance

The trailing filter uses `received_at`, while existing Timescale partitions use
broker arrival `time`. No index/migration is added and long histories can require
more work. The statement timeout bounds execution, not a guarantee that every
large deployment finishes within it. Check real Timescale query plans and expected
data volume before relying on repeated reports. Shorten windows only if that
still answers the test; do not disable containment/timeouts to hide a problem.

Host tests execute actual generated SQL in ordinary/time-partitioned PostgreSQL,
under the reader role: empty/wrong sessions, gaps, duplicate suppression, trailing
window, tied/out-of-order receipt timestamps, optional latency and clock changes.
Actual container execution, sustained 50 Hz ingestion, native package deployment
and real clock agreement remain pending. Use this alongside the
[publisher/staged rate guide](telemetry-rate-testing.md).
