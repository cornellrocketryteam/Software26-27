# Combined return-to-hardware acceptance

This is the accumulating checklist for when the operator regains PC/board access.
It distinguishes software checks already completed from physical tests still
pending. The final combined update bundle and exact activation commands will be
frozen after integration; the older Grafana-restoration archive does not contain
the newly added CLI/network API. Do not reflash merely to test a source-only change.

## Software completed and checked

- Restored Commanding/Grafana were previously accepted by the operator, including
  actual commanding/recovery. Their layout is preserved in the current work.
- Flash script separates SSH/authentication failure from genuinely missing flashcp;
  bounded strict SSH and fake transfer/read-back tests passed.
- Worker/graph-pair routing, pre-build fallback and explicit platform constraints
  passed host integration tests. Compilation failure does not trigger another
  machine's compilation.
- Pending remote transfers no longer block new local builds during station outage.
  Journals/roots stay retained. Explicit `transfer-resume` and read-only status/
  dry-run are implemented; recovery creates no new release.
- Cache outbox/receipt and retention suites pass with fake stores/transports.
- Network-device registry, two-second status cache and authenticated explicit
  Shelly writes are implemented. Default candidate has no write token; Omada
  adapters and unaddressed plugs remain inactive. Host/local-HTTP and Nix contracts
  pass. No real device has been contacted by these checks.
- Manual OSPI-only CI candidate is prepared; no FlakeHub cache action or automatic
  branch-push SD builds. YAML/shell/layout checks pass; GitHub has not run it.

## One integrated maintenance session, in order

1. **Identify the baseline.** Record current/boot system paths, available disk,
   current board FIT identity and station signing public identity. Preserve one
   previous known-good boot/recovery release. Do not delete bootstrap inputs yet.
2. **Apply the frozen candidate in test mode.** Build/import with prepared inputs,
   then test-activate. Check normal SSH, displays, camera playback, fresh telemetry,
   connected Commanding and monitor fallback. No new UI design is being tested.
3. **Check the read-only network service.** After that candidate is installed:

   ```sh
   systemctl is-active ground-network-devices
   curl --fail --silent http://127.0.0.1:8080/network-api/v1/devices
   ```

   Expect seven inventory entries, Omada `inspection_pending`, plugs
   `not_configured`, and `powerWritesConfigured:false`. Verify backend port 8767
   is not directly available over LAN and existing pages remain healthy. An
   unauthenticated POST must return 403 without any device action. Do not expect
   live bridge metrics before management-interface inspection. Open the new read-only
   Network page from the station selector; verify seven cards, wiring, unknown
   versus off/zero readings and normal navigation back to Propulsion/Recovery.
4. **Enroll independent deployment SSH.** Generate the dedicated PC key and supply
   its public half for the board image. Pin verified host identity, update the FIT
   once with the reviewed enrollment image, then connect from a fresh PC session
   without a forwarded agent and after board reboot. Keep Mac recovery access.
5. **Validate the normal worker in maintenance mode.** Use the prepared validation/
   worker configurations and explicit site keys; inspect actual compiler cgroups,
   memory/task limits, free-space rejection and cleanup. Observe telemetry/cameras
   during a bounded build. Client host tests are not a substitute for this check.
6. **Exercise real publication/build/fallback.** Use a real OSPI build, signed
   publication and fresh-store Mac fetch; verify receipt/roots. Interrupt a
   transfer, inspect `scripts/platform status` and `transfer-resume --dry-run`, then
   recover with `transfer-resume` without creating another release. With station
   unavailable, verify a local build succeeds and retains pending publication.
   Reconnect and `cache-sync` without rebuilding. Record measured timings.
7. **Inspect existing Omada devices read-only.** Addresses/port wiring are already
   known. Collect hardware/firmware revisions, standalone/controller mode and
   supported local interfaces. Confirm actual PoE delivery separately from link
   connectivity, especially SK-AM64B and bridge power. Then test reviewed camera
   power controls one at a time once their adapter is implemented; do not cut an
   infrastructure uplink to test a button.
8. **Shelly enrollment, when available.** Supply each plug's address/MAC, firmware,
   component identity, authentication setting and connected load. Keep entries
   disabled until then. Test status, authorized on/off/read-back and unknown-outcome
   behavior against a suitable connected load. Missing plugs do not block the rest.
9. **Retain the accepted candidate as boot default.** Follow the guarded accepted-
   system procedure for the exact tested generation. Cold-boot PC and board without
   WAN; repeat operator/cache/network-service smoke checks. Mark runtime results
   separately from source and mocked-test results.
10. **Finish cleanup.** Remove only superseded transfer/extraction artifacts after
    checking retained release/input roots. Store GC and bootstrap-root retirement
    wait for actual offline-build/publication retention acceptance. Preserve DATA,
    telemetry history, camera credentials and private signing/SSH keys.

## Remaining software before final handoff

- Finish normal-worker/publication enrollment configuration and unified deployment
  interface; freeze the combined candidate and source/lock/manifest identities.
- The separate read-only Network page is implemented and host-tested. Verify it
  on the PC, then add reviewed power controls and actual Omada adapters after
  firmware/interface inspection. Recorded wiring is not live metrics.
- Complete reviewed archive/disk retention policy and benchmark-guided routing.
- Decide/verify CI cutover before pushing; a source edit has not changed GitHub.
- The new source-time telemetry/hybrid-test/profile-view programme is separately
  queued in `2026-11-21-telemetry-time-and-vehicle-profiles.md`; those firmware/schema
  features are not implemented by this checkpoint. Extend this acceptance sheet
  when that candidate actually includes them.

Any failure gets investigated at its first failing boundary. No need to repeat all
previous tests after an unrelated fix; repeat checks covering the changed behavior
and the final reboot/operation smoke test.

## November 22 software checkpoint

Read-only Network page and selector navigation are implemented. Twenty UI tests,
production build, targeted lint, isolated-source build and three mocked browser
suites passed. No network power writes, operator-screen redesign or deployment
occurred. Details: [Network page guide](network-device-ui.md).

## Explicit deployment CLI checkpoint

The source candidate now includes `scripts/platform deploy` (or installed
`crt-platform deploy`) with mandatory `--manifest` and `--target`. It is separate
from build/cache/transfer recovery. Once a normal accepted build returns its
manifest, use that exact path as `$manifest`:

```sh
crt-platform deploy --manifest "$manifest" --target fillstation-deploy --dry-run
crt-platform deploy --manifest "$manifest" --target fillstation-deploy
crt-platform status
```

Verify the dry-run's selected profile/target and FIT hash before the actual command.
The dedicated SSH alias/key and host pin must already be enrolled. Older raw
bootstrap/GitHub artifacts without a platform release manifest remain inputs to
the low-level flash script, not automatically fabricated release manifests.

After success, expect a separate `flash-verified` attempt, `rebootRequested:false`
and runtime acceptance pending. Confirm the build/publication manifest is unchanged.
Reboot explicitly only after the flash succeeds; verify SSH, fresh telemetry and
normal operator pages return. Do not mistake flash read-back for a successful boot.

The CLI was tested with real script/fake SSH for no-network dry-run, source hashes,
reviewed partition mapping, empty/corrupt payload rejection, independent staged
bytes, authentication failure, interrupted write without retry and installed-layout
execution outside a checkout. The script also rejects malformed MTD/capacity data.
Fifteen focused deployment/script tests and the full 136-test host workflow suite
passed. Actual native packaging/SSH enrollment/OSPI flash/boot remain pending.


## Queued optional WAN and power-station acceptance

Starlink health and EcoFlow RIVER 2 Pro monitoring/control are planned, not part
of the implemented candidate. See the November 22 optional Starlink/EcoFlow
addition in [the completion plan](../superpowers/plans/2026-11-20-ground-station-completion.md).
Later record terminal/model/firmware, EcoFlow API support and output-to-load
mapping. Compare readings with vendor displays, test WAN-loss/recovery without
interrupting local operations, and test any approved power-group controls on a
noncritical load first. Individual EcoFlow socket control/metering is unconfirmed. Research now supports
a local Starlink gRPC/MQTT path and an EcoFlow developer-cloud AC/DC-bank path;
both remain queued. EcoFlow powers physical electronics only, not either computer
or the network. Verify account/serial enrollment and actual returned fields before
enabling its adapter; see the completion plan research decision.


## Independent deployment SSH helper checkpoint

`deploy-ssh-init` now prepares a local deployment key/alias and supplied verified
host pin without contacting the board. Real local keygen and OpenSSH config-parser
tests cover repeat setup, preservation, no-agent settings, changed-pin rejection,
invalid keys and symlink refusal. Actual station key generation, public-key image
enrollment, independent SSH after reboot and board deployment are still pending.
Follow [the exact enrollment procedure](ground-station-accepted-system.md).


## Per-role worker/publication identity follow-up

Use [the enrollment runbook](worker-cache-enrollment.md) to prepare separate
worker/publication keys and a public-only site module. Client identity paths now
reach direct SSH and Nix store transport without an agent; invalid configured
paths fail before transport. A 125-test focused regression run and fixture site
module evaluation passed. Actual enrollment, authentication and remote build/
publication acceptance still require the mini PC. Kaleb already appears in the
shared normal-login authorized-keys file used by both systems; verify his login
later rather than adding another copy or granting extra roles implicitly.


## November 23 producer metadata follow-up

The MQTT producer now includes metadata version 1, random per-publisher session,
sequence, frame time/quality/generation and separate ADC/FSW receive ages. Host
Cargo and actual codec checks pass; native ARM/Linux and physical checks remain
pending. SQL/UI still use the earlier arrival-time behavior. Complete compatible
ingestion/LAN time work before claiming packet ordering or accurate UNIX time.
Later verify new session on restart, stable session across MQTT reconnect,
unknown clock/age flags and stale cached samples without modifying the production
clock. See [the producer guide](../../fill-station/docs/TELEMETRY_SOURCE_TIME.md).


## Compatible source ingestion follow-up

The candidate now includes migration 002 and metadata-aware rules/action, private
receipt deduplication, qualified event-time provenance and per-session sequence
heads. Database/role migrations precede broker reconciliation. Host checks include
actual PostgreSQL 17 ordinary/partitioned tables, concurrent retry/rollback and
role permissions. Later verify real Timescale/EMQX, exact uint64 text binding,
old-producer compatibility and one-frame action batching before producer rollout.
No migration or query change has been applied to the mini PC. Existing Grafana
queries remain arrival-based; active session selection and LAN time are pending.
Use [the ingestion guide](telemetry-source-ingestion.md) with the final combined
candidate, not an older transfer bundle or guessed source-session identity.


## LAN time candidate — November 23

Chrony LAN reference and supervised board BusyBox client are implemented; ten
pure Nix contracts pass. No clock was changed or daemon started in development.
Native daemon/image build, measured convergence, offline reboot and reconnect
remain pending. See [LAN time acceptance](lan-time.md). Local reference is not
verified UTC; source session/sequence remains the ordering authority. Existing
Grafana queries remain arrival-based.


## Session query interface — November 23

Migration 003 adds a read-only session catalog, validated selected-session head
and bounded sequence history. Host PostgreSQL ordinary/partitioned checks pass;
asset provisioning includes the migration before reader grants. Later confirm
Timescale/real provisioning and explicit session choice against interleaved
reboot sessions. Existing UI/Grafana consumers still need integration; this does
not activate automatic session selection. See the
[query interface](telemetry-source-ingestion.md#explicit-session-query-interface-migration-003).


## Grafana session selection — November 23

Generated dashboard now adds an explicit Fill session dropdown and filters six
fill queries; latest modern values use sequence, legacy uses arrival. Original
layout/cameras/flight queries and Commanding are retained. Initial selection is
a prompt with no fill data, never an automatic boot guess. Charts still use
arrival time. Host generated-SQL and partition tests pass; real Grafana browser,
Timescale query performance and deployment remain pending. Follow
[Grafana session acceptance](grafana-sessions.md); selected historical values are
not a freshness indication.


## Operating-profile compiler — November 23

Opt-in effective Hybrid/Hybrid-test compiler implemented and host-tested. It
filters local devices before existing pinmux/runtime validation, preserves retained
connectors, and emits definition/base/effective wiring identities. Existing image
builds are unchanged. No Hybrid-test image or second-load-cell telemetry is ready
yet: runtime sensor routing, FSW gating, protocol/client/storage additions and
paired build selectors precede physical deployment. See
[operating-profile compiler](../../fill-station/docs/OPERATING_PROFILES.md#effective-wiring-compiler).


## Operating runtime — November 23

Runtime now reads an optional operating selector, rejects unknown/mismatched
families and routes test-stand PT3/PT4/SV2/MAV locally. Hybrid-test skips FSW
monitoring/forwarding and suppresses FSW MQTT data/age. Internal LC2 raw/voltage
validity is separate from LC1 scaling; LC2 wire/storage/client fields are still
pending, so no new image selector is enabled. Existing builds stay legacy. Host
Cargo Hybrid/Liquid and generated-config mock initialization checks pass; actual
Linux/serial/ADC/actuator and end-to-end LC2 acceptance remain pending. See
[the runtime guide](../../fill-station/docs/OPERATING_PROFILES.md#runtime-routing-support).


## LC2 versioned telemetry — November 23

Opt-in Hybrid-test now publishes source metadata v2 with LC2 raw/voltage/validity
and profile code2. Migration004/rule/action persist it with v2 duplicate integrity
while retaining v1 fingerprints. Local test-stand PT3/PT4/SV2/MAV placeholders
normalize to unavailable using their masks. Existing images stay v1; no new image
selector is enabled. Host PG/codec/Cargo checks pass; EMQX/Timescale/native ARM,
real ADC, UI/CSV and deployment remain pending. Follow
[LC2 acceptance](lc2-telemetry.md) before enabling a combined producer candidate.


## Paired operating builds — November 23

Normal Hybrid now selects agreed operating intent; new fill-station-hybrid-test
target pairs Hybrid wiring with local test-stand intent. App/pinmux/PRU selectors
and disabled-device core selection are threaded together on ARM/x86 graphs.
Liquid and generic debug stay legacy. CLI accepts hybrid-test and hashes Hybrid
base wiring in its manifest; effective identity remains in full source/output.
Host checks pass; native FIT/OSPI build, profile UI/CSV and full hardware deployment
remain pending. See [paired selectors](../../fill-station/docs/OPERATING_PROFILES.md#paired-image-selectors).


## Profile-aware CSV — November 23

CSV keeps the legacy header prefix and appends schema2 profile-aware PT1–PT4,
LC1/LC2, validity, owner-correct states and BV command memory, plus independent
CSV session/time metadata and sample ages. Test mode excludes FSW snapshots and
never scales LC2, including the legacy channel column. Atomic new files avoid
overwrite; invalid pre-epoch time does not prevent recording. Host formatter and
real temporary-file tests pass in Hybrid-test/Liquid suites. Later verify the
actual board log mount/free space, sustained rate, channel/validity values,
FSW disconnects and reboot retention. Periodic sync does not prove persistence.
UI/Grafana variants remain next. See [CSV logging](../../fill-station/docs/CSV_LOGGING.md).


## Profile-aware Commanding — November 23

Board reports versioned operating policy; React keeps its existing look and routes
SV2/MAV locally in Hybrid-test, with local PT3/PT4/LC2raw+voltage and no FSW-only
controls. Normal Hybrid retains remote FSW controls. Unknown profile blocks sends,
reconnect/mode changes disable interaction and delayed sends stay socket/mode bound.
Read-only Recovery map remains usable; forwarding is guarded. Host policy/build,
firmware and three production-preview mock-browser suites pass. No deployment or
physical output validation; old boards need the new report before this UI can
command them. Grafana variants remain next. See [guide](commanding-profiles.md).


## Hybrid-test Grafana — November 23

Separate fillops-hybrid-test view generated from accepted fill layout, no FSW
panels, profile2/v2-only explicit sessions, both local load cells and no guessed
LC1 mass units/LC2 force units. Standard dashboard/default kiosk remain; links
connect views. Latest LC1/LC2 use sequence and invalid LC2 stays unavailable.
Publisher startup now logs the exact MQTT session ID for manual matching.
Host JSON/SQL/runtime/Cargo checks pass; actual Grafana rendering, Timescale
performance and combined deployment remain pending. Normal Hybrid/Liquid source
profile separation is still pending. See [acceptance](grafana-profiles.md).


## Normal Hybrid identity/view — November 23

Normal Hybrid now uses v2/profile1, test remains v2/profile2, legacy Liquid/debug
v1/0. Migration005 extends supported modes while preserving old hashes, rejects
LC2 claims in normal Hybrid and qualifies visible remote fields with FSW age
validity; local connector masks do not erase remote SV2/MAV. Separate fillops-hybrid
view/camera/session filters are generated, default FillOps retained. Provision
001–005 before producer update. Host PG/runtime/Cargo checks pass; live stack,
images and physical mixed local/FSW acceptance remain pending. See
[normal Hybrid acceptance](hybrid-telemetry.md).


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


## Omada read-only inspection — November 24

Candidate package adds `crt-inspect-omada`, a manual fixed-inventory plan/probe
command for the three switches and two bridges. Bounded root HTTP/HTTPS checks
return reachability/status and unverified TLS fingerprints only; no login,
redirect following, polling adapter or power control. Host fixture tests pass.
Later run it on the mini PC and collect installed model/revision/firmware,
standalone/controller mode and available metric labels from existing management
UIs. All Omada adapters remain disabled. See [inspection steps](omada-inspection.md).


## Operating pressure source-time charts — November 24

Hybrid/Hybrid-test pressure histories now use qualified source frame-assembly
time, split clock generations into separate series and select the greatest
sequence for equal timestamps within a generation. Unknown source time is omitted;
latest cards remain sequence-based. Original/default FillOps remains arrival-based.
Generated SQL host checks cover ordinary/time-partitioned PostgreSQL; Grafana
rendering, hardware LAN clock and real Timescale query costs remain pending.
See [source-time chart acceptance](source-time-charts.md).


## Telemetry throughput target: 50 Hz — November 24

- [ ] Measure the current fill-station-to-ground-station telemetry baseline, then
  tune toward **50 Hz (one frame every 20 ms)**. This is a proposed target, not
  a confirmed sustainable rate; firmware timing is unchanged by this checklist.
- [ ] Distinguish publish attempts, broker receipt rate and database ingestion
  rate from ADC acquisition rate and Grafana refresh. Repeated cached samples
  are not new sensor measurements; inspect sample ages and validity.
- [ ] Compare baseline with staged increases through 50 Hz using source session /
  sequence counters: sustained delivered frames per second, gaps, duplicates,
  out-of-order delivery, reconnects, queue growth and end-to-end latency/jitter.
  Report latency only with qualified clock agreement, or use a clock-independent
  measurement; LAN synchronization alone does not establish external UTC.
- [ ] Check board CPU/RAM, GPIO/ADC read contention, network utilization, broker
  and database CPU/RAM, storage growth and Grafana query/refresh performance.
  Run long enough to detect accumulating backlog; receipt deduplication must hold.
- [ ] Verify manual commanding response, reconnect/recovery, cameras, local
  displays and CSV recording remain responsive under the higher rate. Use
  approved test loads; increasing telemetry must not auto-actuate hardware.
- [ ] Test the full Ethernet/wireless-bridge path and an interrupted/recovered
  connection. Retain the known-good rate as a rollback setting. If 50 Hz causes
  issues, diagnose the bottleneck and record the stable rate before making it
  the default. Hardware acceptance and acceptable latency/load bounds remain
  to be established with the actual equipment.


## Telemetry-rate test preparation — November 24

Candidate adds `fillStation.telemetryRateHz` (1–50, default 10), explicit init
environment and ten-second local publisher accounting. Summaries distinguish
local queue acceptance, rejection, encoding failures and work overruns; no broker
or delivery success is inferred. Existing QoS, queue size, ADC/CSV/UI behavior and
10 Hz default remain. Host/Nix checks pass; native images and staged 10/20/25/50 Hz
end-to-end load/latency/commanding/recovery acceptance remain pending. See
[rate configuration and testing](telemetry-rate-testing.md).


## Receiver throughput report — November 24

Candidate `crt-telemetry-throughput` generates bounded READ ONLY SQL for an explicit
publisher session/window: stored receipt rate, internal sequence gaps, receipt
timestamp-order regressions/ties and optional operator-qualified signed latency.
No automatic clock or loss claims; duplicate rejections/broker rates need separate
evidence. Disposable ordinary/partitioned PostgreSQL reader-role checks pass;
actual Timescale plans, container command and sustained 50 Hz remain pending.
See [receiver report](telemetry-throughput-report.md).


## Offline static-input audit — November 24

Candidate `platform offline-audit --drv ...` inspects local daemon metadata and
registration for full static source/derivation/fixed-output inputs. Missing and
unverifiable states stay separate; unknown/dynamic metadata cannot pass. It never
builds, fetches, creates GC roots or marks an offline build validated. Fixture
and inert real-derivation checks pass; actual combined PC/board graphs, retained
input preparation and network-isolated native builds remain pending. See
[offline audit](offline-input-audit.md).


## Explicit offline input pins — November 24

Candidate `offline-pin` requires a fresh passing static audit, registers one
metadata-only local GC root and verifies required closure references before a
receipt. No realization/fetch/admission change; dry-run audits without writing.
Local status exposes recorded/partial state; eight-pin capacity never evicts.
Fixture and real metadata-only checks pass, but mini-PC reboot/persistence,
concurrent GC, full graph and network-isolated builds remain pending. Explicit `offline-unpin` releases one managed root/partial attempt without store
deletion or GC, preserving archived records. See [input pins](offline-input-pins.md).


## Manual Shelly UI controls — November 24

Existing Network cards gain explicit on/off confirmation, memory-only operator
token and relay readback handling. Backend independently requires per-plug write
opt-in plus an assigned load. Fresh status and exact load/address are rechecked;
pre-write polls cannot overwrite post-request state, unknown outcomes lock with
no automatic retry. Both shipped unknown-address plugs remain disabled. Host and
mocked browser checks pass; actual mapping, firmware, authorization enrollment,
PC deployment and physical relay/load acceptance remain pending. Omada remains
inspection-pending. See [Shelly controls](shelly-controls.md).


## Cache-only input preparation — November 24

Candidate `offline-prepare` copies only missing static roots from an explicit
HTTP(S) cache/public key under Nix signature policy, re-audits and optionally
registers metadata-only input pins. No compilation, raw source fetch, fallback
cache, global trust or admission change. Incomplete copies cannot claim prepared
or pin success. Host/injected checks pass; actual imports/signature rejection,
interrupted transfers, full graphs and isolated builds remain pending. Full
source fetching/evaluation input retention and portable prepared-set transfer
are still separate work. See [cache preparation](offline-cache-preparation.md).


## Locked flake evaluation sources — November 24

Candidate `flake-inputs` computes/checks version7 immutable GitHub locked source
paths without fetching/evaluating a flake, and optionally retains a complete
present set through metadata-only pins with lock-digest evidence. Unknown types,
missing sources and failed registration never claim coverage. Current Mac audit
found seven of nine sources missing; a two-present-source pin/release fixture
passed. Full mini-PC source preparation, reboot/offline evaluation and normal
contained builds remain pending. See [locked sources](locked-flake-sources.md).


## Optional WAN TCP observations — November 26

Candidate adds explicit-target background TCP monitoring and an independent cached
WAN card on Network devices. No target/default public traffic, raw-socket privilege
or online boot dependency. Recent failures and successful connection timing are
not packet loss or Starlink terminal/radio health. Host/Nix/mock-browser checks
pass; actual mini-PC routes, IP policy, WAN interruption/recovery and terminal
integration remain pending. Local telemetry/control is not gated by WAN status.
See [WAN probe scope and acceptance](wan-probes.md).
