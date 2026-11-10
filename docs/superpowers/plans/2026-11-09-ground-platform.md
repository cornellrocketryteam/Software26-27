# Ground-platform implementation plan and acceptance checklist

Status: implementation started; foundation committed on 2026-11-10.
Architecture and confirmed requirements:
[ground-platform.md](../../architecture/ground-platform.md).

**Goal:** Reproducible offline NixOS ground-station startup, LAN caching and
optional builds, deferred artifact publication, and straightforward local-boot
fill-station deployment with tested recovery. The operator UI also provides local
network/power controls and wireless-bridge health monitoring. Both the mini PC
and fill station use Ethernet for normal network access.

**Architecture:** Keep the fill station on MixOS with OSPI boot and ext4 DATA;
manage the x86-64 ground station with NixOS. Implement one build/release interface
over Nix, backed by a signed cache and durable laptop outbox.

**Tech stack:** Nix/NixOS/MixOS, systemd, pinned OCI images, Python command
listener, built React assets, Harmonia, SSH, QEMU/binfmt, existing FIT updater.

## Current evidence and next milestone

Baseline commit `1518d86` preserves the verified SSH fix, keys and offline dashboard
instructions. Foundation commit `0078f82` adds the NixOS targets, build/cache CLI,
experimental x86 build graph and packaged command listener. Other contributors'
changes remain in the branch; these commits do not imply hardware acceptance.

The initial 52 host tests passed for the CLI/outbox and listener parser. Nix evaluation checks the
NixOS configuration gates and both vehicles on both build platforms. Both x86
device-tree overlays and the macOS listener package built successfully. The VM
test exists but has not been built/run; the UM560 remains uninspected.

The receipt increment adds a bounded cache receiver, client acknowledgement state
and an opt-in forced-command SSH importer. It is disabled by default. The expanded
73-test host suite passed, covering malformed receipts, interrupted writes, concurrent/repeated sync, duplicate
IDs and modeled GC. A real local-Nix check rooted and verified the existing FIT,
preserved its manifest bytes and returned a stable receipt on retry. Station LAN,
signing/substitution, daemon containment and power-loss tests remain unchecked.
See [cache setup and acceptance](../../operations/build-cache.md).

The worker increment adds runtime health, strict client checks/worker-ID pinning,
a separate untrusted forced-command SSH account, serialized sessions and shared
daemon-side admission. Its endpoint stays disabled. Host tests cover field/disk/
busy/capability failures and session lifecycle. All 15 worker tests also passed
inside the existing ARM64 Linux builder, including parent-death cleanup. This is
process/policy evidence using modeled Nix, not full remote station acceptance.
See [worker setup and acceptance](../../operations/build-worker.md).

A real Liquid FIT build through `scripts/platform` completed using the Mac's
ARM64 Linux worker. Release `20261110T040717Z-c36b10ad543f467bb563a579b2901ebb`
contains an 18,727,192-byte FIT with SHA256
`9f105acda9180e87b8f6a706df4aa9d1a33d9b6dce815bb38cc490c7e4eae736`.
Its manifest records a development snapshot based on `1518d86`; it is rooted
locally and pending publication because no cache is configured. This release
has not been deployed or tested on the board. Its roots protect outputs, not a
complete offline rebuild input set.

Next milestone: inspect the powered-on UM560, back up the current data/services,
and supply actual hardware/boot configuration. Validate the cache/receipt setup
on that machine, complete remote output retention and validate the worker endpoint
before routine station builds. Preserve the current Compose deployment until the
NixOS service migration passes. Existing
button firmware is monitoring-only with the new listener; session-protocol
firmware and command mapping review remain required.

## Global constraints

- Preserve Hybrid/Liquid separation, current profiles, ext4 state, SSH keys,
  `/` permission fix, and local failsafes.
- No mandatory internet/ground-station dependency for fill-station startup.
- Ethernet is the normal network attachment for both machines; mini PC startup
  does not depend on Wi-Fi. Wired endpoints may still use an inter-site bridge hop.
- No automatic commanding, flashing, arming, release activation, or reboot as a
  side effect of building, caching, syncing, or service startup.
- No network-device power action on UI/service startup, reconnect or stale metrics.
  Missing device endpoints remain unconfigured; IP addresses are supplied later.
- Preserve unrelated local work. Historical plans are evidence, not current runbooks.
- Tests and hardware evidence have separate status; unchecked means unfinished.
- New commands/paths below are specified interfaces until their task is complete.

## Dependency order

Inventory → ground-station OS/service packaging → signed cache and offline
preparation using the validated Mac worker → durable sync/build interface →
deployment orchestration → CI cutover → field acceptance. The optional station
build-worker proof can run independently; keep it disabled until it passes.
Network boot is a separate optional final task.

## 0. Freeze and inventory the working baseline

- [x] Record a reviewed commit including the pending SSH root-mode fix, all three
  authorized keys, and offline dashboard documentation; do not lose these changes.
- [ ] Archive the working Liquid/Hybrid release manifests and recovery SD image.
  Capture user-reported SD/OSPI/persistence results with board/release identity.
- [ ] Obtain `lscpu`, memory, storage, NIC names, firmware/boot mode, display and
  USB serial identities from the UM560; record hardware configuration outside secrets.
- [ ] Inventory the Ethernet interface names/MACs on both machines and map their
  switch ports, LAN segments and any EAP215 bridge hop. User provides IPs later.
- [ ] Inventory existing broker/database/Grafana data, versions, schema/rules,
  camera/Home Assistant use, and installed command-button firmware.
- [ ] Restore a test database backup into an isolated instance; record pass/fail.
- [ ] Agree the LAN names, DHCP reservations, trusted developer accounts, and
  exact physical-command source identity. Keep private keys out of Git/Nix store.

Acceptance: a second contributor can recover the existing system using the archive;
the NixOS migration has a tested data-backup restore path.

## 1. Introduce the ground-station NixOS target

Planned files: `nix/flake-modules/nixos-configurations.nix`,
`nix/nixos-configurations/ground-station/default.nix`, its hardware module,
and `nix/nixos-modules/ground-station/{network,operator,storage}.nix`.
Keep existing MixOS configurations and attributes intact.

- [x] Add `nixosConfigurations.ground-station` for `x86_64-linux` using locked inputs.
- [ ] Configure disks/filesystems, persistent service directories, named users,
  SSH, LAN firewall rules, clock/RTC handling, and journal retention.
- [ ] Install from prepared local media; boot without WAN, without a laptop,
  and without the fill station. Record NixOS generation and hardware identity.
- [ ] Package the static operator UI and offline tile assets; start the kiosk
  without requiring public DNS, internet, or npm downloads.
- [ ] Test local-console recovery and selecting a previous NixOS generation.
- [ ] Verify unattended kiosk startup, field-mode suspend prevention, intended
  display behavior, and automatic recovery after AC power returns. Repeat with
  WAN and both peers absent; record any firmware setting required.

Planned raw build interface:

```sh
nix build .#nixosConfigurations.ground-station.config.system.build.toplevel
```

This attribute exists but rejects a physical system build until inspected hardware
and boot configuration are supplied. A separate `ground-station-vm` target exists
for virtual testing. Initial installation must first make a matching x86-64
builder available; the ARM64 Mac VM is not an x86 native builder.

## 1a. Move fill-station networking to Ethernet and configure wired mini PC access

Status: user-confirmed requirement; migration is not implemented. See the
[Ethernet architecture](../../architecture/ground-platform.md#ethernet-connections-for-the-fill-station-and-mini-pc).
The shared fill-station image currently starts Wi-Fi association and DHCP on
`wlan0`; the mini PC's actual wired interface is not inventoried yet.

- [ ] Verify the fill-station Ethernet driver/PHY, carrier and actual interface
  name on the board. Do not assume `eth0` or change vehicle wiring to test it.
- [ ] Configure Ethernet addressing/DHCP in the shared MixOS module for both
  Liquid and Hybrid, with bounded retries and visible link/address state.
- [ ] Configure the mini PC's inspected Ethernet interface, routing and LAN
  firewall/service scope in NixOS. Normal operation requires no Wi-Fi connection.
- [ ] Reserve wired addresses by Ethernet MAC and configure stable LAN names on
  the existing router/DHCP service; document recovery addressing. Do not invent
  IPs or deploy a competing DHCP server.
- [ ] Update SSH aliases/verified host identity records and application/broker/UI
  endpoints to the wired addresses or LAN names. Preserve persistent authorized
  keys, root-permission fix, ext4 state and Liquid/Hybrid profile separation.
- [ ] Establish SSH over Ethernet and verify telemetry/command connectivity
  before retiring fill-station `wpa_supplicant`/`wlan0` DHCP as normal startup.
  Retain serial recovery and document any optional manual Wi-Fi recovery policy.
- [ ] Test wired cold boot and connectivity on SD and OSPI, including persistent
  SSH and both relevant vehicle configurations. Keep boot media/recovery behavior
  unchanged; this task does not require U-Boot network boot.
- [ ] Test mini PC wired access to local devices, cache/build endpoints and the
  router/network when available. Confirm Wi-Fi is not needed for normal startup.
- [ ] Test unplug/replug and DHCP/peer absence: local boot completes, the UI
  reports disconnected/stale state, and wired connectivity recovers predictably.
- [ ] With WAN and Wi-Fi unavailable, verify local wired SSH, telemetry and UI
  paths; separately test the actual inter-site bridge path if present. Record
  which segment failed instead of treating Ethernet carrier as end-to-end health.

Acceptance: both machines use their wired interfaces for normal network traffic;
the fill station's Wi-Fi startup is no longer required, local SD/OSPI boot and SSH
persistence still work, and missing cables/peers cannot block independent startup.

## 2. Package and autostart the telemetry and command stack

Planned files: `nix/nixos-modules/ground-station/{telemetry,commanding,ui}.nix`,
packages under `nix/packages/crt/`, and versioned provisioning under
`ground-station/provisioning/`. Modify `ground-station/LaunchButton/pc_listener.py`
and `Ground_Station_UI/src/App.tsx` for explicit endpoint configuration.

- [ ] Pin container image digests, preload archives, and declare persistent volumes.
  Retain current EMQX/TimescaleDB/Grafana behavior during host migration.
- [ ] Provision the database and availability migration idempotently; preserve data.
- [ ] Provision broker protobuf schema, both topic rules, and shared SQL action.
- [ ] Provision Grafana datasource and dashboard; test NULL/unavailable vs zero.
- [ ] Replace hard-coded UI/listener/broker addresses with one deployment config.
- [x] Package Python listener dependencies in Nix; replace interactive serial
  selection with configured stable device identity and controlled retries.
- [ ] Add dependency/readiness checks and restart policies, visible service status,
  device permissions, and logs. Browser failure must not stop recording.
- [ ] Test startup/restart/unplug/replug with a simulator: no launch, arm, or wipe
  is emitted without a new valid physical input in the intended session.
- [ ] Power-cycle offline: UI, broker, database, Grafana, and listener recover
  without terminal commands. Missing peer is visible and does not block boot.
- [ ] Confirm map tiles work with WAN disconnected but LAN connected.
- [ ] Compare UI telemetry, command responses, persistence, and recovery to baseline.

Acceptance: documented cold boot to usable operator screen; expected services
healthy or explicitly degraded; no accidental command on service startup.

## 2a. Add network/power controls and bridge metrics to the operator UI

Status: new user-requested scope, planned only. Full behavior and vendor references
are in [the architecture](../../architecture/ground-platform.md#network-and-power-controls-in-the-operator-ui).
Missing IP addresses do not block design, adapter fixtures or UI work.

Inventory supplied by the user:

| Device family | Count | Requested integration |
| --- | --- | --- |
| Omada ES205GP, 5-port Gigabit Easy Managed PoE switch | Confirm later | PoE controls in the ground-station UI |
| Omada EAP215-Bridge KIT, 5 GHz AC867 wireless bridge | Confirm kits/endpoints later | Wireless-link metrics in the UI |
| Shelly Plug US Gen4 | Two | Individually named smart-plug controls and available metering |

Planned implementation locations: `Ground_Station_UI/src/` for the panel,
`ground-station/network-control/` for device adapters and a local backend,
`nix/nixos-modules/ground-station/network-control.nix` for supervision/secrets,
and `tests/platform/` for simulated device/command tests. These paths are planned
interfaces, not claims that the service or controls exist.

- [ ] Inventory each unit's exact model, hardware revision, firmware, MAC/device
  identity, management address and access mode. User will provide IPs later;
  record DHCP reservation/local DNS choices then, without hard-coded guesses.
- [ ] Record the number of switches and bridge pairs, both ends/roles of each
  bridge, existing Omada controller/adoption state and any Home Assistant use.
  Verify actual Ethernet/Wi-Fi management topology rather than assuming that
  all devices use Ethernet because their loads are physically wired.
- [ ] Map named switch ports and both Shelly plugs to loads. Identify power and
  management-path dependencies, especially bridge/uplink/ground-station power.
- [ ] Prove the ES205GP's supported local PoE read/write interface for the installed
  revision. Verify local controller compatibility/version and actual control
  endpoints; do not assume SNMP, an Open API or undocumented web writes work.
- [ ] Select the bridge metrics interface on the installed revision: supported
  local controller API or verified SNMP/MIBs. Capture redacted sample responses
  from both ends and identify exposed fields before defining capability flags.
- [ ] Validate Shelly local RPC, authentication and operating mode for both units.
  Inventory schedules/timers and power-restore behavior; choose the adapter without
  introducing cloud dependence or competing automatic controllers.
- [ ] Define one device inventory/configuration with stable IDs, labels, endpoint
  overrides, port/load mappings, supported capabilities and runtime secret refs.
  Device credentials stay out of Git, immutable Nix store and browser code.
- [ ] Implement a supervised local backend with allowlisted device actions,
  bounded polling/timeouts and independent per-device degraded state. If a local
  Omada controller is needed, pin/package its offline startup and persistent data.
- [ ] Add ES205GP UI port cards/table: observed PoE/link state, named load, explicit
  on/off and power-cycle buttons, and available per-port/total power readings.
  Keep PoE power, data-port disabling and whole-switch reboot distinct; expose
  only validated capabilities and avoid a blanket power-off action.
- [ ] Add two individually named Shelly UI controls with observed relay state and
  explicit on/off/cycle, plus available power/energy/voltage/current/fault readings.
- [ ] Add a bridge panel for both ends: link/peer state, RSSI, available SNR/noise,
  TX/RX negotiated rates, traffic rates, channel/width, uptime and disconnects.
  Missing fields show unavailable, not zero; include sample age and last contact.
- [ ] Add separately labeled, bounded LAN RTT/loss probes; keep RF statistics,
  negotiated rates and actual traffic distinct. Active throughput testing remains
  an explicit maintenance action and is not run during startup/normal monitoring.
- [ ] Store infrastructure time series separately and provision Grafana trends.
  Set polling/load budgets and test that monitoring does not degrade telemetry
  recording, operator UI latency or commanding.
- [ ] Require an explicit operator action and affected-load confirmation for
  disruptive writes. Verify a device-local restore timer or independent recovery
  before permitting a cycle that removes its own management link.
- [ ] Implement action IDs/duplicate suppression, bounded results and an audit
  trail with requested vs observed state. After timeout, read status and report
  uncertainty; do not blindly retry toggles/cycles or queue writes for reconnect.
- [ ] Simulator tests: missing config, unsupported capabilities, unavailable/stale
  metrics, partial failures, delayed/lost replies, duplicate clicks and reconnection.
  No power command may run during boot, page load or connection recovery.
- [ ] Bench tests on labeled noncritical loads: compare UI state/metrics to vendor
  management, on/off/cycle behavior, failure/read-back handling and local recovery.
  Keep autonomous PoE recovery/power automations unchanged during manual tests.
- [ ] Disconnect WAN and restart services: controls/metrics work over LAN, missing
  devices degrade visibly, and the rest of the station boots and records normally.

Acceptance: the operator can identify and control the intended PoE port/plug and
see actual bridge health without cloud access, invented metrics or replayed power
commands. Record firmware, controller/API version, port/load map and tested revision.

## 3. Prove the x86 PC can build the current ARM64 graph

Planned file: `nix/nixos-modules/ground-station/builder.nix`; tests under
`tests/platform/`. Current `fill-station-base/default.nix` remains ARM64-hosted.

- [ ] Enable and verify ARM64 Linux QEMU/binfmt; do not merely advertise support.
- [ ] Establish daemon-side SSH worker credentials and pinned host identity.
- [x] Implement the opt-in untrusted worker account, immutable policy, fixed health
  command and guarded daemon-backed stdio endpoint. Check policy/capacity again
  inside the actual pre-build hook; preserve default-off and field restrictions.
- [x] Exercise real lock/process/signal/parent-death behavior with modeled Nix on
  the Mac and its Linux builder. Actual station transport, trust and cgroups remain
  unvalidated; do not treat declaration or host tests as execution benchmarks.
- [ ] Build both vehicle binaries, kernel, bootloaders, overlays, FITs, and images
  on the UM560 worker; record emulation time, peak RAM, and image sizes.
- [ ] Boot one generated release on the board and compare peripheral behavior.
- [ ] Confirm Mac ARM64 Linux VM can build with station disabled/unreachable.
- [ ] Keep the user-accepted signed-in Determinate Mac builder as fallback and
  test offline restart/credential behavior. Replacing it with an account-independent
  VM is deferred, not required to remove FlakeHub Cache.
- [ ] Apply real worker CPU/memory isolation, not just Nix job/core hints. Set
  initial one-job concurrency and proposed 6 GiB/three-core ceiling; ensure the
  Nix daemon doing the work is inside that boundary. Keep heavy field builds
  disabled until the team sets numeric latency budgets and stress tests pass.
- [x] Evaluate a native x86-to-ARM cross-build configuration alongside the default
  ARM graph and make build-platform selection explicit. Both x86 overlays built.
- [ ] Validate complete images from both x86 vehicle graphs, including board tests.
- [ ] Benchmark identical source/lock/profile across station and laptop: clean
  compile with prepared dependencies, incremental app build, and cached build.
  Include queue/copy overhead, peak RAM and operator-service load. Do not guess
  the winner from CPU models. Select station-first only for proven faster jobs.
- [ ] Verify the chosen graph has a compatible laptop fallback; if cross-build
  fallback needs a distinct graph/platform, record it and validate both outputs.

Acceptance: real compatible worker, not an unsupported-system scheduling label.

## 4. Signed cache, archive, and offline preparation

Planned files: `nix/nixos-modules/ground-station/{cache,backup}.nix`,
`nix/client-config/` examples and `docs/operations/build-cache.md`.

- [ ] Serve Harmonia on LAN-only endpoints, with signature verification on clients.
  Evaluate nix-serve as the smaller alternative before finalizing the module.
- [ ] Install the cache signing secret on the station and public trust on clients;
  prove a valid object substitutes and an invalid signature is refused.
- [ ] Implement authenticated ingestion separate from HTTP read service; pin
  imported closure before acknowledging it. Test two authorized developers.
- [x] Implement the ingestion/receipt protocol and opt-in SSH account; verify
  original manifest bytes, registered output roots, closure content and matching
  acknowledgement. Exercise failure/retry on the host and the receiver with
  actual local Nix. Two-developer station/signing tests remain outstanding.
- [ ] Publish and fetch both ARM64 image artifacts and x86 station closures.
- [ ] Verify no FlakeHub credentials or endpoint is required on a clean client
  or worker. Inspect host-level substituters too, not just repository files.
- [ ] Define free-space guard, GC roots/retention, archive layout and independent
  DB/secret backups. Run GC and prove active/recovery releases remain usable.
- [ ] Add `prepare-offline`: retain flake inputs, source/dependency closures,
  required build platforms, OCI images, UI assets and map data.
- [ ] Test a declared prepared offline rebuild with WAN and station disconnected:
  it must succeed in an isolated test store containing required inputs/toolchains
  but no final target outputs, including after GC. Never delete the only recovery
  release to perform this test.
- [ ] Separately test an intentionally unprepared target: report exact missing
  inputs. A clear error does not count as successful prepared offline building.
- [ ] Export/import a `file://` cache from external storage as the temporary option.

Acceptance: substitution and offline recovery work without a public service;
cache outage cannot stop a booted field application.

## 5. One build command, durable retry, and traceable releases

Planned files: `scripts/platform`, `tools/platform/{build,cache,manifest}.py`,
`shared/schemas/release-manifest.schema.json`, tests under `tests/platform/`.
The CLI can be a thin Python implementation behind the shell entry point.

- [ ] Implement the interface in the architecture doc; add help and validation.
- [x] Implement `check`, `build`, `cache-sync` and local `status`, with help and
  validation. Deployment and `prepare-offline` remain separate unchecked work.
- [ ] Test host/vehicle/artifact selection and bounded cache/SSH probes before
  enabling an optional cache/worker. Implement `auto`, explicit local, explicit
  station, and offline modes with visible selection reasons.
- [ ] Test station-first `auto` when benchmarks justify it, laptop-first otherwise,
  and local-capability failure routing to the station before compilation starts.
  Exercise station unreachable/busy/full and local Linux builder unavailable.
- [ ] Test Determinate external-builder/SSH-worker priority explicitly. Implement
  bounded infrastructure-only failover, never blind retries of compiler failures.
- [ ] Record manifest before publication, including commit/dirty source snapshot,
  input/profile digests, platform, worker, artifacts, hashes, and tests.
- [x] Record source snapshot, commit/dirty state, lock/profile digests, platform,
  selected worker, artifact inventory and hashes before publication. Do not infer
  test outcomes; bootloader version/test evidence integration remains pending.
- [x] Persist outbox record and real GC roots transactionally; local build success
  must remain success if station upload fails.
- [ ] Make next build and `cache-sync` retry pending records idempotently. Test
  station absent, laptop restart, partial copy, concurrent sync and duplicate IDs.
- [x] Host-test pending-to-acknowledged transitions, receipt mismatch/disconnect,
  process restart, concurrent sync, conflicting IDs and interrupted local/remote
  acknowledgement persistence. Keep local release roots after acknowledgement.
- [ ] Simulate GC while an item is pending; verify its artifacts and needed
  prepared build inputs remain available.
- [ ] Remove pending pins only after validated remote receipt and retention roots.
  Distinguish cached, tested, and active releases in status output.
- [ ] Test offline builds on laptop, reconnection, station publication, and cache
  reuse by another developer without compiling again where outputs match.

Acceptance: one documented entry point; no hidden dependency on successful upload.

## 6. Deploy and recover without routine SD reflashing

Planned files: `tools/platform/deploy.py`, enhancements to `tools/flash-ospi.sh`,
`tests/platform/test_deploy.py`, and the deployment runbook.

- [ ] Separate `build`, `publish`, `deploy`, `reboot`, and `health-check` actions.
- [ ] Add machine/vehicle/release identity checks, pinned SSH host keys and a
  deployment lock. Do not silently inherit aliases disabling host verification.
- [ ] Preflight every requested partition/file/checksum/size and staging space
  before writing the first partition; reject incomplete bundles early.
- [ ] Define and test application safing and update quiescence with its owner.
  Network connectivity alone is not proof the system is ready to update.
- [ ] Default to FIT-only updates; require explicit bootloader provisioning mode.
- [ ] Stage over SSH, check SHA256, perform flashcp read-back verification, and
  reboot only as an explicit deployment step.
- [ ] Expose installed release identity on the board and verify it after reboot;
  check root mode, ext4 state, persistent SSH, application/broker connectivity.
- [ ] Archive previous FIT and tested recovery SD; rehearse manual SD boot and
  restoring the OSPI bundle. Do not claim automatic rollback for the single slot.
- [ ] In isolated maintenance testing, characterize upload interruption and
  simulated write failure. Actual power-cut flashing tests need a prepared
  recovery setup and owner-defined procedure, not a live operating system.
- [ ] Deploy a ground-station closure, test boot entry rollback and schema
  compatibility; verify cache data and telemetry survive OS generation changes.

Acceptance: ordinary update requires no SD removal; failed single-slot write has
a documented, demonstrated manual recovery route.

## 7. Retire expensive GitHub builds and align documentation

- [ ] After replacement build/cache/offline acceptance, remove or convert
  `.github/workflows/nix.yml` so branch pushes do not build/upload full images
  and do not authenticate to FlakeHub. Keep lightweight contract/host tests.
- [ ] Do not install a privileged public-PR GitHub runner on the operator station.
- [ ] Replace manual-default instructions once provisioning/deploy commands exist;
  retain explicitly labeled recovery procedures and historical evidence.
- [ ] Audit all docs for obsolete uEnv/ospiboot, FlakeHub-required, network-boot,
  automatic rollback, cryptographic FIT verification, and fresh-boot download claims.
- [ ] Have a second contributor execute the documented workflow from a clean
  prepared laptop without verbal instructions.

## 8. Optional network boot and A/B exploration

- [ ] Measure whether staged FIT-over-SSH iteration is insufficient first.
- [ ] If network boot is pursued, separately enable/test U-Boot Ethernet, image
  serving, bounded attempts, and local fallback with the server disconnected.
- [ ] If A/B is pursued, measure image headroom and design partition/state/boot
  acknowledgement together; require interrupted-update recovery tests.

These are not prerequisites for the agreed offline OSPI/network-update baseline.

## Final acceptance matrix

| Scenario | Required result | Evidence |
| --- | --- | --- |
| WAN absent, both machines cold boot | Local UI/services and fill-station application start | Boot logs + readiness timings |
| Both endpoint Wi-Fi connections unavailable | Normal wired SSH/data paths work | Ethernet interface/MAC + route/connectivity evidence |
| Ethernet cable/DHCP absent, then restored | Local boot completes; link/address/connectivity recovers visibly | Boot + unplug/replug log |
| Ground station powered off | Fill station boots locally; laptop prepared build works | Serial log + build manifest |
| Fill station absent | Ground station boots, records service health, displays disconnected | UI + service logs |
| Cache absent with online laptop | Build uses allowed alternatives; publication queues | Outbox + builder log |
| Cache and WAN absent with prepared laptop | Declared release rebuild succeeds without final outputs already present | Offline/GC test log |
| Deliberately unprepared offline target | Exact missing-input report; no long network waits | Negative test log |
| Reconnect after local build | Queue syncs once; second client substitutes | Transfer record + cache log |
| Heavy build while collecting telemetry | Measured accepted latency, or builds paused | Resource/latency trace |
| Listener restarts with held/noisy input | No spontaneous command or replay | Simulator transcript |
| PoE/Shelly UI start or reconnect | No power action; observed states/freshness shown | Adapter/UI test log |
| Requested port/plug action on a bench load | Correct named load changes; result read back or explicitly unknown | Port/load map + action record |
| Bridge degrades/disconnects | RF/traffic/probe metrics distinguished; stale/unavailable visible | Both-end comparison + time series |
| WAN absent with local devices reachable | Network/power panel works over LAN without cloud | Offline control/monitoring test |
| New FIT update | Correct vehicle/release boots and state persists | Manifest + post-boot checks |
| Broken FIT in isolated recovery test | Manual SD restoration succeeds | Recovery log |
| NixOS rollback after data migration | Compatible services/data or explicit restore path | Restore test |
| Station disk pressure/GC | Active release and DB retained; builds stop clearly | GC/free-space test |

Each acceptance row needs the tested revision, hardware, date, operator and
artifact references. A checked implementation task alone is not hardware signoff.
