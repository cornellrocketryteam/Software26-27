# Shared operating-profile definitions

`hardware/operating-profiles.json` records agreed device ownership and sensor
intent separately from `hardware/profiles/*.json`, which define physical wiring.
The validator is `hardware/operating_profiles.py`. This is a definition-only
foundation: firmware, MQTT, build targets, UI and Grafana do not consume it yet.
It does not create a selectable hybrid-test image or alter the existing profiles.

## Intended device mapping

| Device | hybrid | hybrid-test |
| --- | --- | --- |
| SV1 | Local SV1 | Local SV1 |
| SV2 | FSW over umbilical | Local SV2 connector |
| PT1/PT2 | Local ADC1 CH0/CH1, 0–1500 PSI | Same |
| PT3/PT4 | FSW over umbilical | Local ADC1 CH2/CH3, 0–1500 PSI |
| LC1 | Local ADC2 CH1; retain existing calibration | Same |
| LC2 | Absent | Local ADC2 CH2; raw/voltage only |
| Ball valve | Local existing connection | Same |
| QD | Local SV5 solenoid | Same |
| Igniters 1/2 | Local existing connections | Same |
| MAV | FSW over umbilical | Existing local MAV PWM |
| FSW dependency | Yes | None |

Normal Hybrid intends local SV2/SV3/SV4/MAV to be disabled; hybrid-test intends
local SV3/SV4 to be disabled. These lists are **not yet applied to the saved
wiring profiles or runtime command paths**. The current Hybrid image still has
the earlier local capabilities. Profile-aware runtime integration is a later step.

QD energized means disconnect; de-energizing does not reconnect it. Its declared
feedback is output intent/continuity, not mechanical position. No pulse or
actuation sequence is introduced. Igniter continuity is not proof of ignition.
Existing scaled sensor coefficients are referenced, not copied or recalibrated.
LC1's engineering unit is left unknown in this contract until confirmed; its
existing firmware coefficients are unchanged. LC2 has no borrowed calibration,
engineering unit or force value. Raw/voltage must remain visibly distinct.

Liquid retains its current physical wiring. Its devices are explicitly unmapped
in the semantic contract: no sensor channels, new control meanings or FSW policy
are guessed. This does not disable the existing Liquid firmware. Its future
profile-specific UI must wait for reviewed bindings/capabilities.

## Validate and inspect without building

From the repository root:

```sh
python3 fill-station/hardware/operating_profiles.py
python3 fill-station/hardware/operating_profiles.py --profile hybrid-test
python3 -m unittest discover -s tests -p test_operating_profiles.py
```

The CLI emits JSON and performs no network/device access or file writes. It
rejects duplicate JSON fields/IDs, wrong families, missing/disabled local device
references, duplicate ADC inputs, FSW dependencies on the standalone profile,
contradictory uncalibrated readings and unsupported QD/feedback claims. It is not
an authorization check and cannot be used to enable an actuator.

`definitionSha256` hashes canonical semantic JSON; `hardwareProfileSha256`
separately identifies canonical physical wiring JSON. Neither includes firmware,
calibration implementation, source/lock files or FSW firmware. Later release and
runtime identity must include those too. A matching definition hash is not proof
that a connected board is running the intended image or has the intended wiring.

## Remaining integration

Source-time/session/sequence telemetry and backward-compatible ingestion are next.
Then add the first-class hybrid-test build target, configure actual local/FSW
ownership and ADC semantics, disable FSW startup for standalone operation, and bind
minimal profile-specific Commanding/Grafana views. No automatic fill or replacement
UI design is planned. Physical channel/calibration/commanding acceptance remains
separate from the host tests of these definitions.
