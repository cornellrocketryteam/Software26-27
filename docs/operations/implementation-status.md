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
