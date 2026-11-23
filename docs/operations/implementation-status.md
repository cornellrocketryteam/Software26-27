# Ground/fill-station implementation checkpoint — November 22, 2026

This checkpoint publishes accumulated source changes. It is not a new deployed
system, a frozen offline transfer bundle, or acceptance of the final combined
candidate. Keep the currently operating systems until the maintenance checks are
ready. No hardware was contacted or actuated during this checkpoint.

## Included implementation

- Ethernet-first fill-station configuration and Wi-Fi kernel removal; existing
  Liquid/Hybrid OSPI outputs and native x86 cross-build path remain available.
- Solenoid QD on SV5 replaces the retired stepper implementation. Energizing
  requests disconnect; output off does not prove reconnection. Existing role bits
  retain their identities. No automatic QD pulse/retry is added.
- Original React/TypeScript commanding layout with automated fill/timed vent
  removed, retained on-rocket controls and explicit WebSocket configuration.
- Grafana/camera relay and directly attached display session: Grafana plus cameras
  on one monitor, Commanding on the other; single-monitor tab fallback.
- Read-only Network page and backend inventory. Omada adapters remain inspection
  pending; two unaddressed Shelly entries stay disabled. Shelly backend commands
  require explicit private configuration and authorization; no power buttons are
  exposed by the new page.
- Build/worker graph selection, retained-transfer recovery, signed-cache read and
  publication/retention tooling, installed CLI and daemon-validation profiles.
- Manifest-verified explicit FIT deployment with durable attempt records. A
  successful flash is not a claim of runtime acceptance. No automatic reboot.
- `deploy-ssh-init`: locally prepares/reuses the PC deployment key and configures
  a no-agent alias with an independently supplied verified board host pin. It
  neither contacts nor enrolls the board. See the [SSH runbook](ground-station-accepted-system.md).
- GitHub image workflow is manual OSPI-only, with Hybrid/Liquid selection;
  automatic image builds and its FlakeHub cache action are removed. Other
  repository contract workflows are unchanged.

## Checks run for this checkpoint

- Platform Python host suite: 265 tests run, 264 passed, one skipped because the
  worker parent-death syscall test requires Linux.
- Fill-station hardware configuration and solenoid-QD host suites: 43 passed.
- UI: 20 tests passed; TypeScript and Vite production build passed.
- Mocked browser checks: Network inventory/error recovery/read-only behavior,
  restored manual commanding/reconnect, and production startup/recovery passed.
  Browser/device HTTP and command sockets were mocked; these do not actuate hardware.
- Nix module contracts passed for cameras, kiosk, signed cache, daemon validation
  and network service. Ethernet and both execution-platform build graphs evaluated;
  the services candidate passed configuration assertions. CLI, worker-admission and
  generated-Nginx test recipes evaluated. Evaluation is not a package/VM build.
- SSH helper: six tests use actual local OpenSSH keygen/config parsing. They check
  repeat setup, identity/host pinning, no-agent configuration, conflict rejection,
  invalid host keys and symlink refusal.
- Workflow YAML parse, shell syntax, Python compile and Git whitespace checks passed.

The Nginx serving test is invoked by `tests/platform/test_cameras_serving.nix` and
requires its generated `NGINX_CONFIG`; direct unittest discovery cannot supply
that environment. Its recipe evaluated, but the generated-Nginx integration test
was not executed in this checkpoint. No heavy Docker/Linux build was started.

## Still requiring acceptance

- Native Linux package/system build and VM/integration tests for the latest combined
  source, including generated Nginx and compiler cgroup/worker behavior.
- Exact current PC generation and boot-default persistence, then cold boot and
  physical dual/single-monitor checks with fresh telemetry/video/commanding.
  Earlier operator-reported commanding/recovery/display acceptance applies to the
  earlier deployed system, not proof that every newly committed change is deployed.
- Generate the station-owned key, enroll its public half in the reviewed board
  image, verify host identity and connect from a fresh session without forwarding
  a Mac agent, including after board reboot.
- Real remote worker/account admission, signed publication/receipt, interrupted
  transfer recovery, offline fallback and cache retention/cleanup on the mini PC.
- Latest board FIT update, explicit reboot and connected hardware checks. QD state
  remains output intent/continuity, not mechanical position.
- Omada firmware/API inspection and actual switch/bridge telemetry/control;
  Shelly addresses, load mapping, firmware and real relay/read-back acceptance.
- The revised manual GitHub image workflow has not yet run on GitHub.
- Safari camera playback remains unsupported by the current MP4 viewer path;
  Chrome playback was previously accepted.

MQTT source timestamps, the new hybrid-test profile/profile-specific views,
Starlink monitoring and EcoFlow integration remain planned only. They are not
included in this software checkpoint. EcoFlow's intended controlled loads are
physical electronics only, not the computers or network.

Planning documents, research notes, local test reports, build artifacts and private
credentials are excluded from this publication. Operational runbooks accompany
source; no commit/push activates or reflashes either device.


## Follow-up: explicit worker/publication SSH identities

Optional `station.identityFile` and `cache.identityFile` now select separate local
private keys for direct SSH and Nix transport, with agent use/forwarding disabled.
Missing/unsafe configured keys fail before transport; omitted settings preserve
agent/default-key compatibility. No remote account, validation flag, signing
trust, global SSH setting or actual private key was changed.

Validation: 125 focused endpoint/routing/worker/publication/retention/packaging/
deployment-SSH tests passed. The endpoint tests include actual local OpenSSH
configuration inspection and the installed Nix client invoking a capture-only
SSH stub, including paths containing spaces. No network socket is opened by that
stub, and a deliberately failed protocol handshake is expected. The documented
site module was evaluated with public fixture keys: assertions passed, worker
untrusted/importer trusted roles were retained, native-only execution was kept,
and the daemon retained its 300% CPU / 6 GiB memory limits. Nothing was activated.

Kaleb's existing public key is already present in the shared fill-station file
loaded by `ground-admin`; no duplicate was added. Actual private-key login on the
PC/board, role enrollment, remote Nix builds and cache receipts remain pending.
See [the enrollment runbook](worker-cache-enrollment.md).


## Follow-up: operating-profile definition foundation

Added the versioned shared JSON definitions and strict loader/validator for Hybrid,
hybrid-test and explicitly unmapped Liquid. This records desired owners, ADC
inputs, feedback limits, raw/voltage-only LC2 and separate semantic/wiring digests.
It does not modify saved wiring, add a build target, change runtime commands,
stamp MQTT, migrate SQL or change UI/Grafana. Eleven profile tests and 43 existing
hardware/QD tests passed (54 total). No native build/deployment was performed.
The next work is source-time telemetry and compatible ingestion, followed by actual
profile runtime/build integration. See [feature status](feature-status.md) and
[profile guide](../../fill-station/docs/OPERATING_PROFILES.md).


## November 23: producer source-time metadata

Appended protobuf fields 67–81 and integrated fresh publisher-session identity,
non-wrapping sequence, qualified UNIX/session-monotonic assembly time, clock
generation and independent ADC/FSW receive ages in the actual MQTT producer. ADC
capture instants follow successful scans; missing/old values do not acquire new
capture timestamps. No time setting, NTP service, SQL ingestion/deduplication,
WebSocket/CSV metadata or Grafana change is included.

Both Hybrid/debug-json and Liquid/debug-json host Cargo suites passed: 64 test/
doc-test executions per configuration. Five schema/regenerated nanopb-C/Python
codec checks passed, including exact unsigned 64-bit values and old/new wire
compatibility. Existing profile/hardware/telemetry host checks passed; the optional
PostgreSQL trigger test was skipped because PG_BIN is not configured. Cargo.lock
was unchanged. Small host tooling/dependencies were fetched to run host checks;
no Docker or Linux image build was started.

The Linux-only read-only adjtimex path, ARM image build/boot, real MQTT transport,
time synchronization and consumer/database handling remain pending. The new SQL
schema decoder source is compatible, but existing action/query logic still ignores
source metadata and uses arrival time. Out-of-order database handling is not fixed
by this checkpoint alone. See [source-time guide](../../fill-station/docs/TELEMETRY_SOURCE_TIME.md).


## November 23: compatible source ingestion and query heads

Added migration 002, immutable/runtime packaging, both EMQX rule mappings and the
shared action. Store unsigned source fields exactly, retain arrival partition/time
and server receipt time, derive nullable qualified source time/provenance and
use a private ordinary-table receipt key for atomic duplicate suppression. Known
v1 identity/payload conflicts fail without overwrite. Frozen fingerprint fields
survive later columns; one-frame action transactions isolate conflicts. New
views expose per-session maximum-sequence heads and provenance-bearing history.
Existing Grafana queries and physical clocks are unchanged.

34 source-ingestion checks passed on actual disposable PostgreSQL 17.11, including
real time partitions, races, rollback, privilege boundaries, prepared TEXT/NUMERIC
parameters, malformed/old/new cases and unsigned precision. Four existing
availability/PostgreSQL checks and 24 runtime/provisioning checks passed. Actual
Nix-filtered assets were tested in isolation. The package recipe evaluated; its
native build was not attempted after dry-run showed a cold dependency graph.
PostgreSQL binaries were fetched from the official cache; no Docker/system image
build or operational database access occurred.

Actual Timescale/EMQX integration and deployment remain pending. The current PC
still runs its earlier candidate; active-session selection, LAN synchronization
and Grafana/WS/CSV integration remain further work. See [source ingestion](telemetry-source-ingestion.md).
