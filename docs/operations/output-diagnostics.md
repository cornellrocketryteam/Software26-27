# Output and continuity diagnostics

Hybrid and Hybrid-test emit source metadata version 3, profiles 1 and 2.
Protobuf tags 86–89 describe IG1, 90–93 IG2, and 94–97 QD. Each group contains
output intent, continuity, output validity and continuity validity. QD's output
is `qd_release_energized`: energizing requests disconnect; OFF does not reconnect.

IG output is the driver's cached command state. QD output is its solenoid driver
state. Continuity is a fallible GPIO observation. A missing device or failed read
has validity false, not a measured false. None of these proves physical ignition,
mechanical release, or safe actuation. Reading telemetry does not actuate outputs.

Migration 006 accepts v3 only for supported profiles. Diagnostic validity also
requires unit 0 and the corresponding configured output bit: IG1 bit 0, IG2 bit 1,
QD/SV5 bit 8. Old v1/v2 fingerprint inventories and stored receipts remain intact;
v3 adds the twelve diagnostics to its fingerprint. Old data has no invented
valid diagnostics. Liquid/debug remain legacy and do not emit v3 claims.

Provision migrations 001–006, protobuf/rules and dashboard assets on the PC before
updating the board. Operating dashboards retain their layout and append these
readouts to existing status cards. The original default dashboard is unchanged.
CSV schema 3 preserves all preceding columns and appends matching observations.

Software checks cover mock firmware, real protobuf encoding, PostgreSQL receipt
compatibility/qualification and generated Grafana SQL. Native ARM builds, real
broker/Timescale/Grafana, GPIO polarity, physical continuity and fixture commands
remain untested. Follow [the combined handoff](combined-return-handoff.md).
