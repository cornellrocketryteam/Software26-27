# Ground Station

This directory contains the current telemetry stack (`compose.yml`), database
schema/migrations, Grafana dashboard, and physical-command listener. The React
operator application is in `../Ground_Station_UI`; the Python bench dashboard
is in `../fill-station/client`.

The intended NixOS service startup, LAN cache/build worker, offline fallback,
and local-boot deployment architecture is described in
[ground-platform.md](../docs/architecture/ground-platform.md). Work against its
[implementation and acceptance checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md).
The [NixOS foundation](../nix/nixos-configurations/ground-station/README.md) and
[build/cache CLI](../tools/platform/README.md) are implemented. They are not a
deployed operational stack. The Compose stack and manual provisioning below
remain current until their replacement passes. The updated
[physical-command listener](LaunchButton/README.md) is monitoring-only with
existing firmware; review its compatibility gate before changing its deployment.

The React UI now has a [static package and optional local startup integration](../docs/operations/operator-ui.md),
with explicit runtime endpoints and disconnected defaults. Broker/database/Grafana
provisioning and kiosk startup are still pending; a served UI is not complete
station readiness.

Ground Station software covers operator presentation, recording, network-device control, and non-time-critical commands. Keep time-critical Fill Station behavior independent of the Ground Station.

The mini PC will use Ethernet for normal network access; the fill station will
also migrate to Ethernet. Interface/address inventory and the fill-station
configuration change remain planned work. An EAP215 wireless bridge may still
connect the LAN segments. Follow the
[wired-network checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md#1a-move-fill-station-networking-to-ethernet-and-configure-wired-mini-pc-access).

Planned operator features now include Omada ES205GP PoE-port controls,
EAP215-Bridge KIT wireless-link metrics and two Shelly Plug US Gen4 controls.
These are not implemented or connected; IPs, firmware/API compatibility and
port/load mapping are pending. Follow the
[network/power checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md#2a-add-networkpower-controls-and-bridge-metrics-to-the-operator-ui).

## EMQX telemetry rules

Telemetry is written to TimescaleDB by two rules that share one action (`emqx_action.sql`). The topic prefix says which format the payload uses:

| Rule | Topic | Payload format |
|------|-------|----------------|
| `emqx_rule.sql` | `rats/raw/+` | JSON (RATS units) |
| `emqx_rule_fill_station.sql` | `rats/pb/0` | Protobuf, `TelemetryPayload` from `proto/telemetry.proto` (nanopb on the Fill Station) |

### One-time setup in the EMQX dashboard (http://<server>:18083)

1. **Integration → Schema Registry → Create**: name `telemetry`, type `Protobuf`, and paste the contents of `proto/telemetry.proto` as the schema.
2. **Integration → Rules → Create**: paste `emqx_rule_fill_station.sql` and add the same TimescaleDB action the JSON rule uses.
3. Optional, for reading Fill Station data in an MQTT client: add a second action to the Fill Station rule, **Republish**, with topic `rats/decoded/0` and payload `${.}`. This republishes every decoded message as JSON.

`proto/telemetry.proto` must stay identical to `fill-station/proto/telemetry.proto`. After changing the schema, update the Schema Registry entry too.

## Hardware availability deployment

Apply these changes before publishing the updated fill-station firmware. No database
or broker is changed by building the repository.

1. For a new database, run `create-telemetry-table.sql` first. For both new and
   existing databases, apply `migrations/001-hardware-availability.sql` using
   `psql -v ON_ERROR_STOP=1 -f ground-station/migrations/001-hardware-availability.sql`
   with your normal database connection options. The migration is transactional
   and may be applied repeatedly; it preserves existing telemetry.
2. Replace the EMQX Schema Registry `telemetry` schema with
   `ground-station/proto/telemetry.proto`.
3. Update **both** rules from `emqx_rule.sql` and `emqx_rule_fill_station.sql`,
   then update their shared TimescaleDB action from `emqx_action.sql`. Both rules
   provide zero for absent availability fields so legacy JSON/protobuf publishers
   continue to work with the shared action.
4. Import the updated `grafana.json`. Fill-station gauges/stats use the latest
   sample, including NULL, rather than retaining an older valid measurement.
   Pressure traces leave gaps for unavailable samples.
5. Deploy the fill-station application using the matching Liquid/Hybrid profile.

Availability is additive protobuf metadata: tags 64 `availability_version`,
65 `configured_devices_mask`, and 66 `valid_readings_mask`. Version **0** means
legacy interpretation; version **1** applies only to unit ID **0**. Other units
and unknown versions retain their existing behavior.

Device bits 0–11 are `ig1`, `ig2`, `adc1`, `adc2`, `sv1`, `sv2`, `sv3`, `sv4`,
`sv5`, `mav`, `ball_valve`, `qd_stepper`. Reading bits 0–2 are PT1, PT2, and load
cell. Added unbound device instances do not acquire application telemetry bits.
For version 1 fill-station records, the database trigger converts invalid sensor
values and absent actuator states to SQL NULL. Ignition is available when at least
one igniter is configured. A valid measured zero or a configured closed valve stays
zero/false. Flight-software fields, including its MAV and SV2, are unaffected.

Run `python3 tests/test_hardware_telemetry.py` for wire/configuration contracts.
Set `PG_BIN` to a PostgreSQL binary directory to also exercise the migration twice,
INSERT/UPDATE normalization, partial availability, valid zeros, legacy records,
and non-fill units in a temporary database using Unix sockets. This test never
connects to an existing database.
