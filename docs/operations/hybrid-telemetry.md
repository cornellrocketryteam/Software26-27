# Normal Hybrid telemetry identity and view

The candidate's normal Hybrid image now publishes source metadata version 2,
operating-profile code 1. Hybrid-test remains v2/code 2; current Liquid and generic
debug remain legacy v1/code 0. No new protobuf tags are introduced here. The
Commanding WebSocket report remains its separate version-1 report format.

Normal Hybrid gets a separate dashboard at:

`http://192.168.1.206:8080/grafana/d/fillops-hybrid/hybrid`

Use **Hybrid (with FSW)** on standard FillOps to open it. Standard FillOps remains
the default home/kiosk view and the full-flight/legacy fallback. The normal and
test views have separate session catalogs and row filters, and neither guesses
which boot is current. Use the publisher's startup session ID to select the run.

## Device interpretation

Normal Hybrid keeps local SV1, BV, QD, two igniters, PT1/PT2 and LC1. SV2, MAV and
PT3/PT4 stay FSW-owned over the umbilical; disabled local SV2/MAV connector bits
must not erase those remote values. The new normal view preserves the existing
fill-section positions and cameras. It has no LC2 card. The former RTD slot shows
FSW receive age at stored-frame assembly rather than introducing a sensor outside the agreed profile.
FSW flight mode is retained in the status card, alongside combined igniter intent.
Broader unit-1 flight panels remain in standard FillOps, not this scoped view.

A normal-Hybrid frame must carry LC2's absent placeholders (raw 0, voltage 0,
validity false). It cannot claim an LC2 measurement. When FSW receive-age validity
is false, ingestion makes PT3/PT4, RTD, remote SV2/MAV and FSW flight mode NULL.
No qualified receive age is not zero pressure, Startup mode, or a closed valve.
The age is captured at frame assembly, not continuously recomputed in Grafana.
A stopped publisher can leave its old age/value visible; it is not a freshness
alarm. Inspect the selected session and actual device connection. Other legacy FSW fields in raw records still need their qualification;
this change does not define validity for every flight-sensor field.

## Migration and compatibility

Migration 005 extends the supported v2 profile set to 1 and 2. It keeps the frozen
v1 and v2 field inventories/fingerprints intact, reuses the same receipt table and
never rewrites historical data or receipt keys. Existing v1 and v2/code2 receipts
still match after migration. Changing the profile under the same frame identity
is a conflicting payload, not an allowed reassignment.

Apply migrations 001–005 and reader grants before deploying the new normal Hybrid
producer. The runtime asset pack and provisioning order include 005. A database
with only migration 004 rejects v2/code1 frames. Do not replay older migrations
alone against a running new producer; use the ordered maintenance/provisioning
procedure. New normal publisher lifetimes use new sessions; older normal v1 data
remain accessible in standard FillOps and are not relabelled as v2/code1.

The test-stand path and its local mask interpretation remain unchanged. Liquid
is not assigned code 3 or a new dashboard: its semantic mappings are still pending.
The runtime profile is not physical wiring or release attestation. Per-igniter /
QD MQTT detail and freshness presentation still have separately recorded gaps.

## Later acceptance

After the combined candidate is built, provision the PC first, then deploy normal
Hybrid. Match its logged session ID to the normal view and verify local inputs /
commands independently from FSW-owned inputs / commands. Disconnect FSW only in
an approved setup: remote values should become unavailable, with local inputs
continuing. Reconnect, restart, signed-cache and OSPI recovery remain part of the
cumulative hardware session. Do not actuate merely to verify the dashboard.

Host checks cover ordinary/time-partitioned PostgreSQL, old fingerprint survival,
invalid LC2/profile claims, disjoint session choices and URL filtering, reader
queries, and the actual firmware mode identity helper. Existing test-stand /
standard dashboard and runtime checks also run. Real EMQX/Timescale, actual
Grafana rendering, native ARM images, FSW/ADC hardware and deployment are pending.
