# Commanding operating profiles

The React page now follows the connected board's reported operating profile.
Existing buttons, confirmation dialogs, fonts and general layout remain. No fill
automation is added. This is source/host/browser tested, not deployed or physically
accepted. A separate [Hybrid-test Grafana view](grafana-profiles.md) is now generated; other mode separation remains pending.

## Identity and compatibility

New firmware sends `operating_profile` on connection and answers
`{"command":"get_operating_profile"}`:

```json
{"type":"operating_profile","profile_version":1,"profile":"hybrid-test","fsw_enabled":false}
```

Supported labels are hybrid, hybrid-test and legacy (the current Liquid/debug
behavior). FSW policy must agree with the label. Unsupported versions, malformed
or missing reports leave the UI in unknown mode and block its actuation sends.
An older server with no report needs updating before the new UI can command it;
the UI does not guess a mode from an ADC count or availability mask. Older clients
can ignore this additive report. Board identity is a runtime operating label,
not proof of physical wiring, release hash or valve position.

Reconnect clears the profile. Changing profile/connection disables interaction
and dismisses the pending key confirmation; delayed sends are bound to their
original socket and profile. Normal manual confirmation/launch lock behavior
remains. Read-only Recovery map functions remain available while unidentified,
but its forwarding commands are gated. Hardware masks still independently disable
missing local devices.

## Hybrid-test behavior

SV2 open/close uses local `actuate_valve` on SV2. MAV uses local `mav_open` and
`mav_close` without a timed sequence. Local state is queried at startup, after
commands and by periodic polling. SV1/BV/QD and combined igniter/Launch controls
retain their existing manual paths. State labels are cached driver/command
readback; they do not prove physical position or freshness.

The added readings line shows local PT3/PT4 on ADC1 CH2/CH3 and LC2 raw counts /
voltage on ADC2 CH2. LC1 retains its existing calibration with no newly inferred
engineering unit. LC2 never displays inherited scaled/force values. Failed ADCs,
missing or nonfinite data display Unavailable; zero remains a measurement.

FSW-only key, maintenance controls, rocket-state display and Recovery navigation
are hidden. Direct Recovery navigation reports that this mode has no FSW. No FSW
stream is started and delayed/direct UI forwarding commands are rejected by the
profile policy. Firmware separately disables its FSW receiver/task for test mode.

## Normal Hybrid and legacy

Normal Hybrid keeps SV2/MAV on the FSW command paths and gets their state and
PT3/PT4 from FSW telemetry. Local-only availability text explicitly refers to
local devices, so disabled local SV2 does not imply the remote SV2 is absent.
Legacy keeps the original control routing; it is not a newly specified Liquid
hardware mapping. Custom Liquid views still need its agreed semantic mapping.

## Later acceptance

Deploy matched firmware and UI together after the combined candidate is ready.
Check the displayed profile, mode-specific readings, hardware masks, disconnect /
reconnect, explicit re-enabling and cancelled confirmations before actuation.
For test mode confirm local SV2/MAV command/readback with an approved hardware
setup and no FSW. Verify physical outputs separately from cached UI state. Normal
Hybrid still needs FSW-path checks. The host browser tests use fake sockets and
never contact a board, camera, switch or power device.

Checks include policy/operating-definition agreement, local and remote routing,
strict report parsing, raw LC2, TypeScript production build, actual rendered
Hybrid-test/Hybrid/unknown pages, local SV2/MAV open and close, and prior startup /
manual SV1/BV/QD/cancel/reconnect browser regressions.
