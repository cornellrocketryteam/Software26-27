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
| Three operating-profile definitions | New shared definitions/validator implemented and host-tested | Runtime/build/telemetry/UI consumption; current hardware profiles unchanged |
| MQTT source timestamps, ordering and deduplication | Producer metadata plus SQL storage/deduplication and explicit session query interface implemented and host/PostgreSQL-tested; arrival partition retained | Timescale/EMQX acceptance, physical LAN clock validation, operator selection/browser acceptance and source-time chart integration |
| hybrid-test image with LC2 | Intended local/FSW/channel mapping defined; no image target yet | Standalone firmware, raw/voltage LC2, OSPI build and hardware acceptance |
| Hybrid/Liquid/test UI and Grafana variants | Planned; accepted layout is retained | Shared-contract bindings, profile identity/mismatch handling and views |
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
