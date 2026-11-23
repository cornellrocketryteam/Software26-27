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

This is not firmware activation. Existing Cargo/Nix builds still invoke
`--profile`, and no deployable Hybrid-test target is exposed yet. The MQTT
publisher currently has hardcoded PT1/PT2/LC1 extraction and the application
starts FSW monitoring unconditionally. Next integration must consume the contract,
route local PT3/PT4, add raw/voltage LC2 with explicit validity, disable FSW on the
test stand, and carry matching metadata through codecs/storage/client consumers.
Only then pair the Cargo and Nix image/pinmux selectors and deploy a test image.
Do not flash these standalone generated files as a complete image.

Checks cover exact local roles/masks, retained connector equality, deterministic
hashes, untouched saved wiring, pending-Liquid rejection and conflicting selector
errors. Existing physical-profile, pinmux and PRU tests remain unchanged and pass.
Native Rust/image compilation and hardware acceptance of the new configuration
are still pending.
