# Hybrid-test Grafana view

The candidate provisions a separate **FillOps - Hybrid-test** dashboard:

`http://192.168.1.206:8080/grafana/d/fillops-hybrid-test/hybrid-test`

The standard dashboard remains at its existing URL and remains the default home /
kiosk view. Use its **Hybrid-test (local only)** link to open the new view. A
**Standard FillOps** link returns to the original. Nothing switches the dashboard
or selected boot automatically. No deployment has occurred in this block.

## What changes

The Hybrid-test view keeps the existing fill-section panel positions and camera
viewer. It removes flight/FSW panels and empty avionics/debug rows. PT1–PT4 and
SV1/SV2/BV/MAV use local test-stand telemetry. The former RTD card becomes LC2 raw
counts and voltage, with separate display units. LC1 keeps its existing scaling
but drops the unconfirmed pounds label and mass thresholds. No new force
calibration or mass unit is introduced.

The Pad Safety card shows individual IG1/IG2 output intent and continuity. The
valve card includes QD release output and continuity. Validity-qualified v3
readings distinguish false from unavailable; older v2 sessions have unavailable
new diagnostics. Output intent does not prove ignition or mechanical QD release,
and output OFF does not reconnect the QD. See [diagnostics](output-diagnostics.md).

The operating pressure chart uses qualified board frame-assembly time, ordered
by source timestamp. Clock generations become separate `PTn / clock N` series;
missing time produces no plotted point. Equal timestamps in one generation use
the highest source sequence once, while all frames remain stored. Invalid pressure
stays null and line bridging over nulls is disabled. See [source-time charts](source-time-charts.md).

Latest pressure, actuator and load-cell cards still use source sequence within
the selected session. Invalid LC2 does not recover an older valid value; zero
with validity true remains a measurement. The view is historical context, not
a freshness alarm: a stopped selected session can keep its last values visible.

## Choosing the session

The initial value is **Select a Hybrid-test session**, with no fill readings.
Reload after a new publisher starts to refresh the choices. Only known-valid
source versions 2 or 3 / operating-profile code 2 session heads appear in the catalog.
Every panel also enforces that profile/version on its rows. Legacy-only choices,
unknown IDs and non-test session IDs never fall back to other telemetry.

The publisher now logs its exact 32-character hexadecimal session ID with
`MQTT publisher session` on its first assembled frame. Match that ID against the
catalog label. On the board, the startup line is visible in the serial console
and in `/tmp/fill-station/logs/tracing.log.*` while retained. If multiple publisher
lifetimes are present, capture the current startup rather than guessing from
file timestamp/arrival recency. A publisher restart produces a new ID; an MQTT
reconnect alone retains it. The CSV logger has its own ID and must not be used
as the MQTT session identity.

## Scope and pending views

The raw exported dashboard is unchanged. Generated standard FillOps gains only
its navigation link in this block; its existing session queries/layout remain.
A separate normal-Hybrid view is now generated with v2/v3 profile1 filtering; see
[normal Hybrid identity](hybrid-telemetry.md). Legacy normal-Hybrid v1 data remain
in standard FillOps. Liquid still needs semantic sensor/device mapping before its
custom view can be defined. The Commanding UI already follows the board's reported mode.

## Later acceptance

1. Build/deploy the combined ground-station candidate, with migrations 001–006,
   matching protobuf descriptor/rules and both provisioned dashboard files.
2. Build/deploy the matched Hybrid-test board candidate. Capture its publisher
   session line, confirm Commanding reports Hybrid-test, reload the Grafana view
   and choose that exact session.
3. Confirm the camera viewer and layout in Chrome, all four local pressures,
   local actuator states, LC1 and LC2 counts/voltage against reference readings.
4. In an approved fixture, verify ADC2 loss makes LC2 unavailable and measured
   zero remains zero. Check invalid local PT masks and selected-session restart /
   reconnect behavior without replaying actuation commands.
5. Check both dashboard links, missing-camera placeholder and actual Grafana
   units/rendering. Verify real Timescale query plans at the expected data volume.

Host acceptance covers generated JSON, preserved fill positions, both camera
configurations, reader-role SQL, catalog/profile isolation, delayed packets,
invalid latest values, and ordinary/time-partitioned PostgreSQL. Native Grafana
rendering, real Timescale extension behavior, broker/hardware and deployment remain
pending; no Docker or live services were started for this change.

The display uses Grafana's documented [field overrides](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-overrides/)
and [custom unit formatting](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-standard-options/).
