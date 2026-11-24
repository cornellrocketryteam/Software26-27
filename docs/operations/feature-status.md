# Ground/fill-station feature status — November 23, 2026

This separates earlier operator acceptance from current implementation. The latest
combined source has not been deployed during the hardware-access gap. Earlier
successful tests do not prove every newly committed change is running on the PC.

| Feature | Current state | Still needed |
| --- | --- | --- |
| NixOS mini PC, wired LAN and local service startup | Earlier operator-confirmed installation/operation | Verify latest accepted generation is the persistent boot default |
| Board Ethernet at .106, local OSPI boot, telemetry and reboot recovery | Earlier operator-confirmed | Rebuild/deploy and repeat smoke test for the final combined candidate |
| Original manual Commanding/Recovery UI, automated fill removed | Earlier operator-confirmed commanding/recovery; source retained | Latest combined candidate and profile-aware variants |
| Grafana telemetry/cameras, dual monitors, one-monitor fallback | Earlier operator-confirmed; current source checked with mocks | Latest physical activation/reboot; Safari playback still unsupported |
| Solenoid QD on SV5 | Driver/protocol/profile/client changes implemented and host-tested | Separate physical release/continuity acceptance; off is not reconnection |
| ADS7128 selectable device, existing PRU PWM support | Existing source available; preserved by current work | Device-specific physical validation as used; not newly validated here |
| Ethernet image slimming | Wi-Fi stack removed in source; saved kernel configuration checked | Latest complete FIT build/boot/size comparison |
| Native x86-to-ARM OSPI builds | Earlier operator reported successful Liquid/Hybrid builds; current graphs evaluate | Latest complete release through the normal worker path |
| Signed cache reads | Earlier real trusted/invalid-signature and Mac OSPI fetch checks passed | Optional normal-client installation/verification and final persistence |
| Build routing, publication, receipts, retention and outage recovery | CLI/backend source and host tests implemented | Real normal-daemon worker, archive enrollment, interrupted transfer/GC/outage acceptance |
| Independent SSH | Shared contributor keys configured, including Kaleb; local board-key setup and per-role worker/publication identities implemented | PC-owned deployment-key enrollment, real role authentication and reboot checks |
| Explicit FIT deployment CLI | Manifest/hash/partition checks and attempt records implemented; fake-transport tests pass | Real manifest-based deployment through enrolled PC identity |
| Reduced GitHub image CI / FlakeHub dependencies | Repo inputs use GitHub pins; image workflow is manual OSPI-only with no FlakeHub cache action | Run revised workflow; verify offline input preparation and local tool dependencies |
| Cleanup | Some superseded local artifacts removed; no broad data/store purge | Final PC cleanup/GC only after persistence and retained-release acceptance |
| Network page and inventory | Read-only UI/backend implemented and host/browser-tested | Deploy latest PC candidate |
| Omada switches / wireless bridges | IPs/wiring recorded; no real management adapter yet | Firmware/API inspection, metrics, then reviewed camera-port power controls |
| Shelly plugs | Local RPC backend implemented/tested; two entries intentionally disabled | Addresses, identities/load mapping and real on/off/read-back acceptance |
| Three operating-profile definitions | Definitions, opt-in compiler and runtime sensor/FSW policy implemented and host-tested | Native build and physical acceptance; Liquid mapping; saved base wiring retained |
| MQTT source timestamps, ordering and deduplication | Producer metadata plus SQL storage/deduplication and explicit session query interface implemented and host/PostgreSQL-tested; arrival partition retained | Timescale/EMQX acceptance, physical LAN clock validation, operator selection/browser acceptance and source-time chart integration |
| hybrid-test image with LC2 | Paired image target, firmware routing, LC2 raw/voltage, CSV and profile-aware UI/Grafana implemented and host-tested | Native OSPI builds and combined hardware acceptance |
| Hybrid/Liquid/test UI and Grafana variants | Commanding runtime-profile routing and views implemented/tested with original styling; legacy Liquid retained | Normal Hybrid and Hybrid-test Grafana implemented/SQL tested; Liquid mapping and real combined deployment remain |
| Starlink health | Local integration path researched | Terminal identification, adapter, actual route/metrics and outage tests |
| EcoFlow RIVER 2 Pro | Cloud integration path researched; physical electronics only | Account/device/API enrollment, AC/DC-bank adapter and read-back tests; individual socket control/metering unproven |

The [implementation checkpoint](implementation-status.md) records check scope and
remaining native/VM/hardware validation. The [combined return checklist](ground-station-return-testing.md)
collects the later hardware session. The [profile definition guide](../../fill-station/docs/OPERATING_PROFILES.md)
explains the new foundation and its explicit limits. Planning/research remain local.

LAN time is now implemented and module-tested; native/image/physical acceptance
is pending. See [LAN time](lan-time.md). No latest candidate has been deployed.

Generated Grafana now has explicit session selection and sequence-based latest
fill values; deployment/browser acceptance is pending. See [session guide](grafana-sessions.md).

LC2 v2 MQTT/storage support is implemented and host-tested; native/image activation, live broker/ADC, profile UI and physical CSV acceptance remain pending. See [LC2](lc2-telemetry.md).

Paired Hybrid/Hybrid-test image selectors and CLI routing now exist and are graph/host tested; full images, consumer variants and physical acceptance remain pending. Liquid remains on its current wiring.

Profile-aware CSV schema3 now records named sensors/validity, LC2 raw/voltage, owner-correct actuator state and independent CSV time identity. Host formatter/file checks pass; board mount/retention/performance and physical recordings remain pending.


## Output diagnostics and combined handoff — November 23

Hybrid/Hybrid-test now emit v3 IG1/IG2/QD output intent and continuity with
independent validity. Migration 006, operating Grafana cards and CSV schema 3
carry them through without changing default FillOps or Commanding layouts.
Board deployment public keys now have a separate board-only file; contributor
PC access stays separate. No real key was enrolled and no hardware deployed.
See [diagnostics](output-diagnostics.md) and the ordered
[combined build/deploy/test handoff](combined-return-handoff.md).
Hardware, native image builds, offline input availability, actual SSH enrollment,
and worker/publication admission remain acceptance gates, not assumed passes.


## Persistent CSV capacity guard — November 23

Pinned MixOS already binds DATA `/state/var` onto `/var` before application init;
the earlier persistence uncertainty is resolved at source level. CSV now verifies
that writable mapping and periodically checks space/inodes off the executor.
It reserves 32 MiB/128 inodes, debits each write, and stops the CSV task at
128 MiB per recording or capacity/probe failure. No automatic pruning, rotation,
actuation, or UI recording alarm was added. Other processes can still use disk.
Commanding/MQTT continue independently. Native Linux probes, actual reboot
retention, sustained performance and disposable-fixture limit acceptance remain
pending. See [CSV storage policy](../../fill-station/docs/CSV_LOGGING.md).
