# Telemetry rate preparation and later acceptance

The candidate makes MQTT rate configurable from 1 through 50 Hz, with **10 Hz
unchanged as the default**. No physical throughput result or sustainable 50 Hz
claim is established. The rate controls frame assembly/publish attempts, not ADC
sampling, FSW acquisition, CSV rate, broker delivery, database ingestion or Grafana
refresh. Increasing it can repeat cached sensor readings; inspect sample ages.

## Configuration

In the selected board Nix configuration, set for example:

```nix
fillStation.telemetryRateHz = 50;
```

For Hybrid-test that file is `nix/mixos-configurations/fill-station-hybrid-test.nix`.
Other profiles have their own file in the same directory. Leave the option absent
for the 10 Hz default. Record the configuration change with each test artifact;
rebuild the usual OSPI FIT and deploy through the accepted procedure. No SD/DATA
reformat or new boot switches are needed. Change rates only in an approved
maintenance window, then confirm the startup log reports the intended value.

Init supplies `FILL_STATION_MQTT_HZ` explicitly to the supervised application.
The binary accepts that environment setting for direct non-init test launches,
but exporting it in a serial/SSH shell does not change the running service or
its init environment. Do not start a second application instance to test a rate:
that can contend for GPIO, duplicate MQTT client identity and affect commands.
Invalid environment values warn and fall back to 10 Hz. Nix rejects rates outside
1–50 before producing the configured startup command. Periods use nanoseconds
so rates such as 30 Hz do not truncate to a whole-millisecond interval.

## Local publisher measurements

Every approximately ten seconds the application emits `MQTT publisher window`
in its existing tracing log (normally `/tmp/fill-station/logs/tracing.log.*`):

- `target_hz`, elapsed `window_ms`, `attempts` and `last_sequence`.
- `queued`, `rejected`, `encoding_failed` and `queued_hz`.
- `work_overruns` (assembly/encoding/local publish work at least one period) and
  `max_work_us`. These are work timings, not scheduler jitter or network latency.

Queued means accepted into the bounded local MQTT request queue. With existing
QoS 0 it is **not a broker acknowledgement or proof of delivered frames**.
Connection loss, process restart or broker/DB errors can lose queued messages.
Rejected frames consume source sequences and are not replayed. Encoding failures
are counted separately. Window counters reset after each summary; source session
and sequence retain their existing semantics. There is no automatic rate change,
QoS change, catch-up burst, queue enlargement or receiver-side retry in this work.

The optional debug-JSON feature produces a second publish and can compete for the
same queue. Counters describe only the protobuf stream, while work timing includes
the debug path when compiled. Compare like builds when assessing performance.

## Hardware session: baseline then staged rates

1. Retain a known-good 10 Hz FIT. Collect baseline publisher summaries and actual
   broker/ingest counts for an identified source session. Note any preexisting
   loss/load, sensor ages and recording/storage conditions.
2. Test 20, 25, then 50 Hz as separately identified candidates. Measure sustained
   receiver throughput, sequence gaps, duplicate suppression, out-of-order
   delivery and backlog growth. Capture both board and PC load/storage growth.
   A ten-second local queued-rate summary alone is insufficient acceptance.
3. Measure latency/jitter only with qualified clock agreement or an independent
   clock-safe measurement. Kernel/LAN synchronization does not establish UTC.
   Test long enough to reveal growing queues and slower database queries.
4. Check manual commanding response with approved loads, cameras, displays,
   CSV performance and LAN-time behavior. Test the actual Ethernet/bridge path
   and an interrupted/recovered connection, without replaying actuation commands.
5. Record acceptable latency/load limits, observed stable rate and failure modes.
   If any regression appears, restore the known-good FIT/rate and diagnose before
   choosing a new default. Nothing in source currently enables 50 Hz by default.

Host tests cover parsing/range limits, 20 ms at 50 Hz, fractional-millisecond
periods, queue/error accounting, work overruns and actual Nix startup commands for
10/50 Hz. Host tests do not establish scheduler performance, delivery, Linux GPIO
contention, native image build success or actual 50 Hz capacity.


For the receiver side, use the explicit-session
[database throughput report](telemetry-throughput-report.md). It complements local
queue measurements without inferring delivery or packet-loss causes.
