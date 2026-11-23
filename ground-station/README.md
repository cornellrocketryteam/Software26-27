# Ground Station

This directory contains the telemetry schema/migrations, Grafana dashboard,
legacy Compose/camera-relay configuration and physical-command listener. The React
operator application is in `../Ground_Station_UI`; the Python bench dashboard
is in `../fill-station/client`.

Start with the [network and device reference](../docs/operations/ground-station-network.md)
for current device addresses, usernames, the corrected credential-reference
location, the full port map and the optional Starlink topology.

The UM560 now runs the [NixOS foundation](../nix/nixos-configurations/ground-station/README.md).
The operator confirmed SSD boot, console/SSH access, wired `lan0`, and the static
operator UI. The separate [services update](../docs/operations/ground-station-update.md)
has been test-activated on the PC: telemetry provisioners/containers are active and
Grafana storage health/browser access passed. Persistence of that services boot
generation has not yet been reported, and physical SK-AM64B ingestion is untested
while the board is off. Full field readiness is not established by UI/health alone.

The [telemetry module](../docs/operations/telemetry-stack.md) prepares pinned local
images and provisions the database, broker and dashboard. The camera relay is
not deployed by that profile; its packaged camera panel remains unconfigured.
FillOps can currently be opened directly at
`http://192.168.1.206:8080/grafana/d/adrc2lg/fillops`. The default-home fix is tested
in code for the next update. Kiosk and signed cache/build-worker admission remain
separate work. The [build/cache CLI](../tools/platform/README.md) is available,
with its admission/acceptance gates still applying.

The PC's normal network connection is Ethernet. The SK-AM64B cable terminates at
fill switch 2 port 1, with reported address `.106`; its interface/traffic still
need verification after power-on. The EAP215 pair carries the inter-site wireless
bridge. Three ES205GP switch addresses and port assignments are now recorded;
PoE controls and bridge metrics still need supported local API/firmware validation.
Two Shelly Plug US Gen4 addresses and load mappings remain to be supplied.

The [physical-command listener](LaunchButton/README.md) remains monitoring-only
with existing firmware. Keep time-critical fill-station behavior independent of
the Ground Station. For the wider intended architecture and remaining work, see
[ground-platform.md](../docs/architecture/ground-platform.md) and its
[checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md).

The manual instructions below are for legacy Compose/manual deployments. The
NixOS services profile performs its managed provisioning automatically; do not
recreate its owned rules/dashboard manually.

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
   followed by `psql -v ON_ERROR_STOP=1 -f ground-station/migrations/002-source-metadata.sql`.
   Apply both before the new action/role grants; the NixOS provisioner handles this
   order automatically. See [source ingestion](../docs/operations/telemetry-source-ingestion.md)
   for receipt retention, time provenance and rollout limits. Supply your normal
   database connection options. Both migrations are transactional/repeatable and
   preserve existing telemetry.
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
