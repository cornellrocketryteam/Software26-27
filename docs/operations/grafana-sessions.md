# Selecting fill telemetry in Grafana

The candidate adds one **Fill session** dropdown above the existing dashboard.
Panel positions/types, cameras and flight panels retain their accepted layout.
Only fill panels 2, 3, 4, 5, 6 and 35 receive session-filtered queries during asset
provisioning; the original dashboard export remains the reference layout.
Commanding is a separate WebSocket path and is not changed by this selection.

On first load the selection is **Select a fill session**: fill panels show no data
until an operator selects a session. **Legacy only (arrival order)** shows only
metadata-version-0 fill data. Modern sessions are listed by full hexadecimal
publisher identity and stored last sequence. The option value is two exact decimal
uint64 strings, never a JavaScript number. The catalog refreshes on dashboard
load; reload the page after a new board publisher starts to obtain new choices.
Verify the selected identity against the board's run before interpreting data.
Bookmark a chosen run using Grafana's normal `var-fill_session` URL parameter.
The page's initial unqualified URL does not automatically choose the latest boot.

Latest-value panels use the greatest sequence within the selected session, so a
late earlier packet does not replace a newer reading. Legacy latest values use
arrival order. Unknown/malformed selections produce no rows and never fall back
to another boot. In the standard/default FillOps view, charts still use broker arrival time and the normal time range;
this does not yet put samples on a source-event-time axis or reorder plotted
samples by acquisition time. Mixed clock generations and timestamp uncertainty
therefore remain visible in the database rather than being implicitly resolved.

Selection is historical context, not liveness: an old selected session may keep
its last stat values on screen. Panel descriptions document this limit. A board
restart does not switch the dashboard; choose the new session explicitly. No
freshness alarm or automatic active-session detection is implemented here.

## Acceptance when hardware is available

1. Deploy the combined PC candidate with migrations 001–003 before its generated
   dashboard. Keep the board producer deployment and its session verification as
   separate recorded steps.
2. Open Grafana in Chrome. Confirm the initial prompt and unchanged camera/flight
   panel layout. Choose Legacy only if testing a pre-metadata board image.
3. With the new producer, reload and choose its full identity. Check all six fill
   panels, the saved URL and time-range changes; no selection should mix boots.
4. Restart the publisher/board, reload, and select the new identity. Confirm the
   previous selection remains historical rather than silently changing sessions.
5. In an isolated replay fixture, deliver a lower sequence after a higher one.
   Latest-value panels must retain the higher sequence; charts remain explicitly
   arrival-based. Do not replay commands or actuate hardware for this check.
6. Verify real query latency with the expected Timescale data volume. Host tests
   cover correctness, not production query plans, browser interpolation or UI
   behavior. Retention/performance work remains pending.

Tests execute the generated panel SQL against ordinary and time-partitioned
PostgreSQL with a model of Grafana SQL-string interpolation. They cover delayed
frames, multiple sessions, legacy isolation, invalid and quote-containing URL
values, maximum uint64 IDs and layout preservation. No live Grafana browser or
Timescale extension was run during development.

The variable uses Grafana's documented [PostgreSQL key/value query variables](https://grafana.com/docs/grafana/latest/datasources/postgres/template-variables/)
and [SQL-string formatting](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/variable-syntax/).


A separately filtered Hybrid-test view is now generated; standard FillOps remains
the default. Match the publisher's startup session log to the dropdown. See
[profile-specific Grafana](grafana-profiles.md) for scope and later acceptance.


The separate Hybrid and Hybrid-test pressure charts now use qualified source
frame-assembly time with separate clock-generation series. Default FillOps and
legacy charts retain arrival time. See [source-time chart policy](source-time-charts.md).
