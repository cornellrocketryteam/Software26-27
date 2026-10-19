# Ground Station

This directory will contain the Ground Station UI and platform services.

Ground Station software covers operator presentation, recording, network-device control, and non-time-critical commands. Keep time-critical Fill Station behavior independent of the Ground Station.

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
