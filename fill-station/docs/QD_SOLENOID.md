# Solenoid quick disconnect

Hybrid uses a distinct selectable `quick_disconnect` device (`id: qd`) on the existing SV5 connector. It reuses Kaleb’s `QuickDisconnect = SolenoidValve` driver alias.

| Property | Configuration |
| --- | --- |
| Application role | `sv5`, availability bit 8 |
| Control | GPIO1_48, pad `main:0x0220` |
| Continuity | GPIO1_46, pad `main:0x0218` |
| Polarity | Fixed normally closed / active-high release |
| Initial and shutdown output | De-energized |

The normal device-tree builder exposes this kind with `control`/`sense` ports. It may bind `sv5` or be an unbound extra; it cannot claim another application role. Both the compiler and runtime reject reversed QD polarity. Hybrid replaces its former ordinary SV5 entry and removes the motor entry. Liquid’s existing profile and solenoid QDs remain unchanged. Role bits 0–10 never move; former motor bit 11 is reserved and unassigned.

## Commands and feedback

The following are protocol examples, not an automated sequence:

```json
{"command":"actuate_valve","valve":"SV5","open":true}
{"command":"actuate_valve","valve":"SV5","open":false}
{"command":"get_valve_state","valve":"SV5"}
```

`true` energizes and **releases/disconnects**. `false` removes drive; it does **not** prove that the mechanism is attached again. `valve_state.open` is driver command memory. The separate `continuity` input is not a physical engagement or position sensor. The station UI labels these requests QD release/output-off and continues using SV5 on the wire.

The former motor move/retract/extend/state-query API is removed. There is no motor, step count, preset movement, or separate retract timer. Startup and emergency shutdown de-energize QD with the other configured solenoid outputs; no new QD sequence is introduced.

## Logging and compatibility

- WebSocket and CSV expose QD through existing SV5 command/continuity fields.
- Legacy CSV motor columns `QD_Enabled` / `QD_Direction` remain `N/A`, preserving column positions without querying a removed driver.
- The existing protobuf numeric `qd_state` field number 62 is unchanged but deprecated zero/unknown. Existing database availability normalization may render it NULL because bit 11 is not configured. It is never repurposed as this solenoid’s state.
- QD has no dedicated historical MQTT/Grafana field in this bounded change. Primary telemetry panels remain the existing local SV1/BV/PT1/PT2; use WebSocket command/continuity for QD. No schema or database migration is needed.
- A new Hybrid firmware build is required to install the typed QD runtime/profile and remove old motor support. The SV5 protocol and connector pin assignments remain compatible.

## Local checks and hardware handoff

Python compiler/hardware/client tests run without hardware. The mock accepts generic SV5 requests and rejects the retired motor API. Native Rust tests are present, but the current offline checkout lacks cached `aho-corasick v1.1.5`, so they could not compile here. No dependency download, cross-image build, Docker, deployment, or live actuation was performed.

After a reviewed native build, verify role bit 8 and the cleared motor bit, the exact GPIO connector, energize-to-release direction, output-off behavior and continuity on the actual mechanism. Software command memory and mocks do not validate physical engagement.
