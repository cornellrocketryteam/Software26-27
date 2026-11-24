# Operating pressure charts and source time

The candidate changes only the pressure-history panel (2) in the separate Hybrid
and Hybrid-test views. Layouts, cameras, default FillOps, latest-value cards and
Commanding remain unchanged. Choose the actual publisher session explicitly as
before; the page does not automatically select a new boot.

## Time and ordering

The pressure chart filters and sorts on `source_event_time`, qualified by existing
ingestion from the board's UNIX milliseconds and time-quality flags. Delayed
packets plot at their source time, independently of their broker arrival. Records
without qualified time are omitted; no arrival-time fallback is mixed into the
series. Latest-value cards remain usable and sequence-based even when time is
unknown. A blank chart with populated cards can therefore mean missing source
time or an incorrect selected time range, not lost telemetry.

Clock corrections or synchronization loss/recovery change the publisher's clock
generation. Series names include that generation (`PT1 / clock 1`, etc.), so a
line does not connect across clock generations. Within a generation, identical
source timestamps use the highest sequence once. This is only chart reduction;
all received frames remain in database history. Invalid pressures stay null and
Grafana span-null bridging is disabled. Generations can overlap on the time axis;
that is not a new session or a deletion of earlier samples.

This is frame-assembly time, not individual ADC/FSW acquisition time. A board
synchronized to the offline ground station can agree with its LAN clock without
having correct external UTC. Existing sensor ages and clock-quality metadata
retain their separate meanings. No source-time error estimate or freshness alarm
is introduced. A stopped selected run can remain visible.

## Build and later acceptance

Only the PC's generated dashboard assets change; no firmware/protobuf/database
migration is added in this block. Existing combined producer/migration requirements
still apply. Default FillOps remains the arrival-time fallback for legacy and
unqualified sessions.

After deploying the combined PC candidate:

1. Verify local telemetry and the selected publisher ID; let LAN time settle.
2. Open each operating view, choose its matching session and a range containing
   the board's clock. Confirm pressure legend units, distinct clock-generation
   names, null gaps and normal refresh behavior in actual Grafana.
3. Use a disposable telemetry fixture to deliver a newer frame before an older
   frame; check the chart follows source time and latest cards retain the newer
   sequence. Check equal timestamps choose the higher sequence.
4. In that fixture, include a clock correction, an unknown-time frame and an
   invalid-pressure frame. Check separate series, omitted unknown time, null
   pressure and no switch to another session. Do not change live board clocks
   or send actuator commands for this check.
5. Check reader queries and actual Timescale plans/data volume on the PC.
   Arrival-time partitions are unchanged; source-time queries may span arrival
   partitions. This work does not claim bounded long-history query cost.

Host tests execute the generated queries in ordinary and time-partitioned
PostgreSQL with the reader role, including delayed delivery, clock changes,
timestamp ties, invalid values and session/profile isolation. Actual Grafana
rendering, real Timescale performance and hardware clock behavior remain pending.

The query uses Grafana's documented three-column `time`, `metric`, `value`
[PostgreSQL time-series format](https://grafana.com/docs/grafana/latest/datasources/postgres/query-editor/).
