# Shared operating-profile definitions

`hardware/operating-profiles.json` records agreed device ownership and sensor
intent separately from `hardware/profiles/*.json`, which define physical wiring.
The validator is `hardware/operating_profiles.py`. Firmware, MQTT/storage and
paired image builds now support operating intent. UI/Grafana/CSV variants and
physical acceptance remain pending; see the build-selector table below.

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

Normal Hybrid disables local SV2/SV3/SV4/MAV in its effective wiring; Hybrid-test
disables SV3/SV4. Saved base wiring is preserved. Existing deployed images do not
change until rebuilt and deployed; the generic debug target remains legacy.

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

## Effective wiring compiler

The compiler now accepts an opt-in operating selector, separately from the
existing physical-profile selector:

```sh
python3 fill-station/hardware/compiler.py --operating-profile hybrid --output /tmp/hybrid-effective
python3 fill-station/hardware/compiler.py --operating-profile hybrid-test --output /tmp/hybrid-test-effective
```

Run these from the repository root. They produce pinmux/runtime files plus
`operating-profile.json`, containing the validated operating definition and
separate SHA256 identities for the definition, base wiring and effective wiring.
These are configuration identities, not a complete firmware/release identity.
The runtime JSON also records `operating_profile`; consumers still need explicit
support for its sensor ownership/routing contract.

The compiler copies saved physical wiring, disables the definition's named local
devices and runs the existing hardware/pinmux validation. It preserves connectors,
GPIO polarity, ADC addresses and settings of retained devices. Hybrid retains
local IG1/IG2, ADC1/ADC2, SV1, QD/SV5 and BV; Hybrid-test additionally retains SV2
and MAV. Neither includes local SV3/SV4. Sensor channel ownership and calibration
status remain in the emitted operating definition, rather than being guessed
from enabled ADC hardware. Liquid's pending semantic mapping is rejected by this
new selector; existing `--profile liquid` builds remain available unchanged.

Normal Hybrid and Hybrid-test builds now invoke this operating selector for the
application and device tree. Runtime ownership/FSW gating and LC2 v2 wire/storage
support are implemented. Native image compilation, profile-specific consumers and
physical acceptance remain pending. Do not flash standalone generated compiler
files as a complete image.

Checks cover exact local roles/masks, retained connector equality, deterministic
hashes, untouched saved wiring, pending-Liquid rejection and conflicting selector
errors. Existing physical-profile, pinmux and PRU tests remain unchanged and pass.
Native Rust/image compilation and hardware acceptance of the new configuration
are still pending.

## Runtime routing support

`operating_profile` in generated hardware runtime JSON is now read by firmware.
Absent means legacy behavior; only `hybrid` and `hybrid-test` are recognized, both
requiring the Hybrid physical wiring family. Unknown names or mismatched families
fail initialization. The paired image configurations below supply this selector;
direct Cargo without the environment selector and generic debug retain legacy behavior.

Hybrid-test policy suppresses the FSW background task and closes its forwarding
receiver, so attempted remote forwards fail rather than queue for a future FSW
connection. MQTT ignores FSW readings and receive-age state in this mode. Local
ADC1 CH2/CH3 populate PT3/PT4; local SV2/MAV state populates their existing wire
fields. Those state values are driver/command state, not physical position proof.
Normal Hybrid leaves PT3/PT4 and those actuator fields owned by FSW.

A pure routing layer returns an optional scaled reading for each assigned pressure
and for LC1. Failed ADCs, missing scaling and nonfinite engineering values clear
validity rather than publish an apparently valid zero. Existing MQTT mask bits
0/1/2 remain PT1/PT2/LC1; opt-in test mode adds bits 3/4 for local PT3/PT4. Numeric
wire fields still use zero placeholders when invalid; consumers must honor masks.
Bus sample age remains separate from per-reading validity and can indicate an old
last successful sample.

LC2 on ADC2 CH2 is represented internally as optional raw counts/voltage only;
scaled input is deliberately discarded even if supplied. Failure/nonfinite voltage
makes it unavailable, and it is absent outside Hybrid-test. **LC2 now has MQTT protobuf/storage fields (source v2); CSV and named UI fields remain pending.** Generic ADC WebSocket responses
already contain the channel readings, but this is not a complete profile UI.
The remaining LC2 consumer integration must land before a combined candidate
is accepted for deployment. Neither new profile is physically accepted.

Host tests exercise both Hybrid and Liquid Cargo configurations, real generated
operating JSON into mock hardware, profile-family rejection, exact channel routing,
FSW policy and failed/nonfinite ADCs. No serial/GPIO/I2C hardware or Linux native
image was exercised. Physical FSW absence, local outputs/continuity, all sensor
channels and full end-to-end LC2 telemetry remain later acceptance gates.

LC2 wire/storage integration is now implemented: see [the v2 contract](../../docs/operations/lc2-telemetry.md). Paired selectors are available below; physical acceptance is still pending.

## Paired image selectors

The source build configurations now activate operating intent together:

| Target | Cargo wiring family | Operating intent |
| --- | --- | --- |
| fill-station | hybrid | hybrid (local SV1/QD/BV/igniters, FSW-owned SV2/MAV/PT3/PT4) |
| fill-station-hybrid-test | hybrid | hybrid-test (local SV1/SV2/QD/BV/MAV/igniters and all sensors) |
| fill-station-liquid | liquid | legacy Liquid wiring, unchanged |
| fill-station-debug | hybrid | legacy full Hybrid wiring, explicitly not the normal operating image |

Existing target names remain available, but **fill-station now disables local
SV2–SV4/MAV according to the agreed normal Hybrid definition**. Do not expect those
local connectors to actuate from that image. The separate Hybrid-test target
keeps local SV2/MAV and disables SV3/SV4. The generic debug target remains a wiring
bring-up tool and does not enforce these operating-device subsets.

MixOS `fillStation.operatingProfile` is threaded into the application, pinmux and
PRU packages. PRU core selection filters disabled devices before startup planning.
The Rust build script validates `FILL_STATION_OPERATING_PROFILE` against the Cargo
family and invokes the same compiler selector as pinmux/PRU. Pinmux packages ship
`profile.json` as the effective wiring rather than the unfiltered base; the
compiler also emits `effective-wiring.json` for inspection. Missing/empty runtime
build selector retains legacy behavior for direct Cargo and debug builds.

Once the station worker is available and inputs are prepared, the candidate OSPI
build command is:

```sh
./scripts/platform build fill-station --vehicle hybrid-test --artifact ospi --build-platform x86_64-linux --builder station
```

Add `--offline` only after preparing the full input closure. Use `--vehicle hybrid`
for normal Hybrid or `--vehicle liquid` for Liquid. Routine builds select OSPI;
SD/recovery artifacts remain explicit optional requests. The release manifest's
`profileSha256` remains the **base physical wiring** hash (Hybrid for Hybrid-test),
not an effective wiring hash. The full tracked source snapshot, target attribute,
derivation/output hashes and vehicle distinguish operating builds. Do not treat
the base profile hash alone as release identity.

These targets have been graph-evaluated on both builder architectures and the
operating selectors have passed native host Cargo tests. No full native ARM/FIT
build or deployment was performed in this block. Current Commanding/Grafana/CSV
still require their profile-specific controls, labels and LC2 support. Finish
those consumers and freeze one combined candidate before physical acceptance.
