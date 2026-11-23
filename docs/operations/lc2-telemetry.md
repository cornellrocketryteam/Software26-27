# Hybrid-test LC2 telemetry

The candidate now carries ADC2 CH2 as raw counts and voltage, with explicit
validity. It does not apply LC1 calibration, calculate force or infer engineering
units. This is implemented and host-tested; paired image targets are now available.
Profile-aware CSV is implemented; UI/Grafana views remain separate work.

## Wire and storage contract

Both protobuf copies append the following tags; existing tags are unchanged:

| Tag | Field | Meaning |
| --- | --- | --- |
| 82 | load_cell_2_raw (sint32) | Signed ADC counts, constrained to int16 at ingestion |
| 83 | load_cell_2_voltage (double) | Finite voltage, no force calibration |
| 84 | load_cell_2_valid (bool) | Successful ADC2 reading with finite voltage |
| 85 | operating_profile (uint32) | 0 unspecified; 2 Hybrid-test currently supported with v2 |

The opt-in Hybrid-test runtime publishes source_metadata_version=2 and profile
code 2. Other current runtime configurations remain version 1/profile code 0.
Codes 1/3 are reserved for later Hybrid/Liquid identification; do not infer they
are implemented. The code is an operating-mode label, not a wiring/release hash.
Invalid/unavailable LC2 uses zero wire placeholders and validity false. It shares
ADC2's existing sample age; it is not a separately timed channel acquisition.

Migration 004 adds nullable raw/voltage columns, validity default false and profile
code default 0. It does not backfill historical LC2 or modify existing receipts.
Version 1 retains its exact frozen fingerprint. Version 2 includes the four new
fields, so a changed LC2 reading under the same session/sequence is rejected.
Version transitions must use the normal new publisher session on restart; old
identities are never rekeyed. Legacy/v1/unsupported source claims cannot assert
LC2 validity. Consumers should require valid source identity, metadata version 2,
profile code 2 and load_cell_2_valid before displaying LC2 as a measurement.

Version 2 requires availability_version 1/profile 2, finite voltage and int16 raw
counts, including finite placeholders when unavailable. Malformed supported
frames fail SQLSTATE 22023 before receipt insertion. Invalid local PT3/PT4 become
NULL using mask bits 3/4, and unavailable local SV2/MAV become NULL using configured
bits 5/9. Version 1 FSW-owned values retain their prior interpretation. Driver
state is still not a physical valve position measurement.

## Deployment and later checks

Provision PC schema/migrations 001–004, EMQX schema/rule/action and reader grants
before enabling a v2 producer. An older v1-only stack does not provide LC2 integrity
or display support. Runtime asset packaging includes 004 before role grants and
broker reconciliation. Existing selected-session views/functions include the new
columns; the accepted dashboard still has no dedicated LC2 panel.

After the complete Hybrid-test candidate is ready, verify all of these together:

1. Real EMQX accepts the updated protobuf descriptor, including signed sint32 raw
   counts; confirm raw/voltage/validity/profile code in PostgreSQL.
2. ADC2 CH2 responds independently from CH1, and changing CH2 does not change LC1's
   calibration or mapping. Record reference readings before accepting measurements.
3. Failed/disconnected ADC2 clears validity; zero volts with validity true remains
   distinguishable from an unavailable channel. Confirm sample age semantics.
4. Replay duplicates only in an isolated telemetry fixture: exact v2 retries
   suppress, changed LC2 conflicts reject, and a migrated v1 receipt still matches.
5. Confirm reader-role access, session-selected queries, real Timescale operation,
   reboot/offline recovery and profile-specific CSV recordings and later UI representations.

Host checks use disposable PostgreSQL 17 ordinary/time-partitioned tables, the
actual generated SQL action, real nanopb C round trips, and Hybrid/Liquid Rust
suites. They do not prove live EMQX descriptor deployment, Timescale extension
behavior, native ARM compilation or physical ADC operation. No hardware was used.
