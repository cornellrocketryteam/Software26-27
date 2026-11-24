# CSV logging

The fill-station logger records snapshots at a target rate of 100 Hz. A CSV row is
not necessarily a newly acquired ADC sample: acquisition rates differ, and slow
I/O or hardware reads can reduce the logging rate. Sensor ages identify repeated
or stale cached samples independently from validity.

## Files and storage

Files are created under `/var/log/fill-station` on Linux and `logs/` on other
hosts. Names are `fill_station_log_<epoch-seconds>.csv`, with `_1`, `_2`, etc. on
collisions. Atomic create-new prevents overwriting an existing log. A clock before
1970 uses filename timestamp 0 and does not prevent logging; do not use the
filename as proof of valid UTC. Existing files are never migrated or appended to.

The logger attempts a file sync every 1,000 rows, roughly ten seconds at its target
rate. This reduces buffered-data exposure but does not guarantee survival of a
power cut. The pinned MixOS init bind-mounts `/state/var` onto `/var` before
application startup, separately from the `/etc` overlay. The logger verifies a
writable ext4 `/state` and same-device `/var` bind and checks its directory is on
that filesystem. If verification fails, CSV logging stops without a volatile
fallback; commanding and MQTT remain independent. Actual board reboot retention
still needs acceptance.

## Capacity and stopping

The logger preserves every recording and never prunes automatically. It reserves
32 MiB of available DATA space and 128 available inodes, and caps each recording
at 128 MiB including its header. The shipped DATA-card image is 256 MiB; recordings
are not unlimited. These are fixed firmware policy constants in `csv_storage.rs`,
not runtime environment settings. Normal host/mock runs keep the file cap but do
not claim DATA verification or real disk-reserve checks.

Space/mount checks run at startup and every 100 rows (about one second at target
rate), off the async executor. Every write debits the last measured headroom.
Other processes can consume disk between checks, so this is a recording budget,
not a filesystem quota or guarantee against unrelated writers. Low space/inodes,
mount/probe failure or the file limit stop only the CSV task with an error in the
application tracing log; no UI recording alarm is implemented. Capacity stops
attempt a final sync. Existing periodic sync errors are reported, not proof of
power-loss durability. Directory/file/header/row write errors also stop logging.

There is no automatic file rotation, restart or deletion at the limit. Before a
long run, measure actual bytes per second and ensure its recording fits both the
per-file cap and available capacity. Export and verify logs, then remove only
explicitly selected old recordings and restart the application during an approved
maintenance window to resume. Restart affects commanding connections; never do
this during active operation just to free log space. Resizing/reformatting DATA
is not part of routine FIT deployment.

## Compatibility and schema 3

The complete legacy and schema-2 headers stay at the beginning in the same order.
Output diagnostic fields are appended, with `CSV_Schema_Version=3`. Read columns by header name and allow
additional columns; consumers requiring an exact old column count need updating.
Old files remain readable with their old headers and have no fabricated new data.

Legacy columns still include loop/ADC timestamp, igniter state, SV1–SV5 output and
continuity, local MAV state/pulse width, all ADC raw/scaled channels, FSW fields,
deprecated QD motor fields, and availability masks. `QD_Enabled`/`QD_Direction`
remain `N/A`; solenoid QD release intent/continuity use SV5. Energizing requests
disconnect, while switching off does not reconnect or prove physical position.
Missing local hardware/readings are empty, invalid scaled values are empty, and
unavailable FSW fields are `N/A`. False and measured zero remain real values.

`Timestamp_ms` is the legacy ADC snapshot timestamp, not row assembly time. Raw
ADC fields describe physical channels; an enabled ADC can read spare channels
that are not assigned operating sensors. Legacy local actuator columns are not
relabelled as remote FSW states. `FSW_Timestamp` retains the FSW gps_time field,
not a new UNIX timestamp or a guaranteed FSW uptime.

## Profile-aware readings

| Columns | Meaning |
| --- | --- |
| Operating_Profile | hybrid, hybrid-test or legacy (including current Liquid/debug) |
| FSW_Enabled | Selected policy, not connection status |
| PT1_PSI…PT4_PSI and PT1_Valid…PT4_Valid | Assigned pressure and finite/available status |
| LC1_Scaled, LC1_Valid | Existing LC1 calibration, engineering unit still unconfirmed |
| LC2_Raw, LC2_Voltage, LC2_Valid | ADC2 CH2 in Hybrid-test only; no force calibration |
| SV2_Profile_Open, MAV_Profile_Open | Selected owner's driver/command state |
| BV_Commanded_Open | Last-commanded ball-valve state when configured |

Hybrid-test uses local ADC1 CH0–CH3 for PT1–PT4, ADC2 CH1 for LC1 and CH2 for LC2.
It uses local SV2/MAV, and never logs stale FSW values even if an old shared
snapshot says connected. Normal Hybrid obtains PT3/PT4 and SV2/MAV from connected
FSW. Disconnected remote values are empty and pressure validity false. Local
pressure validity requires a successful ADC snapshot and finite scaled data;
LC2 validity requires successful ADC2 and finite voltage. LC2 never uses a scaled
value even if one is present. Valid zero voltage differs from unavailable LC2.
The original mask retains PT1/PT2/LC1 bits 0/1/2; test mode adds local PT3/PT4
bits 3/4. Availability does not establish absolute sensor accuracy or freshness.

## CSV time and identity

The new `CSV_Session_Hi`/`CSV_Session_Lo`, `CSV_Sequence` and `CSV_Monotonic_ms`
identify and order logger snapshots. The random session belongs to this logger,
not the MQTT publisher: never join CSV and MQTT by matching sequence/session.
`Loop` equals this CSV sequence and starts at 1. Import uint64 identities and
sequence as exact integers or text, not floating point (including spreadsheet
imports). No attempt is made to combine successive files into one ordered boot.

`CSV_Unix_ms`, `CSV_Unix_Valid`, `CSV_Time_Quality` and `CSV_Time_Generation`
use the existing source-clock rules. Unknown time uses UNIX 0 with validity false.
Kernel-synchronized quality does not prove accurate UTC or a fresh upstream; LAN
reference uncertainty remains. Clock discontinuities increment the time generation
without resetting sequence. The logger stops rather than reuse identity on entropy,
sequence or time-generation failure.

ADC1/ADC2 `Sample_Age_ms` and `Sample_Age_Valid`, plus FSW `Receive_Age_ms` and
`Receive_Age_Valid`, describe last successful local scans/FSW receipt at row
assembly. Unknown age is empty/false, and fresh zero is 0/true. These are not
simultaneous channel acquisition times or FSW sensor timestamps.

## Acceptance

Host tests exercise the actual row formatter, column alignment and unchanged
legacy header prefix, profile routing, unavailable/nonfinite/zero/false values,
CSV-specific time metadata, and real temporary-file creation without overwrites.
The logger task itself has not been run on the board in this block.

After deploying the combined candidate, collect a short log without actuation.
Parse it with a CSV reader, verify row/header counts and mode, compare the named
channels with ADC and telemetry readings, then disconnect/reconnect FSW/ADC in an
approved hardware setup. Confirm invalid values and sample ages. Verify the real
log mount, free space and power/reboot retention separately before trusting field
recordings. Test near-limit behavior only on a disposable fixture filesystem, never by filling production DATA.

## Output diagnostics

Schema 3 appends IG1 and IG2 `Output_Active`, `Continuity`, `Output_Valid` and
`Continuity_Valid` fields, followed by QD `Release_Energized`, `Continuity`,
`Output_Valid` and `Continuity_Valid` (all prefixed with `IG1_`, `IG2_`, or `QD_`).
Missing observations are empty with validity false. Known false remains false
with validity true. Driver intent and continuity do not establish physical
ignition or release. Existing SV5/QD legacy columns remain in place.
