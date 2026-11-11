# Ground-station offline boot and recovery implementation plan

**Goal:** Exercise the actual NixOS telemetry units and packaged UI in an isolated
x86 guest, including degraded boot, automatic recovery and persisted telemetry.

**Architecture:** Extend the manual VM acceptance pattern with the real three
Linux/amd64 archives. The guest has no NIC, no physical-command listener and no
host service activation. A test-only unit generates random private credentials
after an explicit fixture-release marker; normal services retain their real
dependency/retry graph. Reuse the existing synthetic MQTT and API assertions.

**Tech stack:** Locked Nixpkgs runNixOSTest/QEMU, real Docker images, systemd,
Python standard library, existing telemetry helper and React package.

## Constraints

- Keep production architecture, image pins, credentials and hardware gates intact.
- Real service units and preload-only image behavior must be exercised.
- Do not replace EMQX or remove QUIC merely to get a green result. The all-amd64
  startup issue on Docker Desktop remains separate until this guest demonstrates
  otherwise; a VM result still does not prove physical UM560 compatibility.
- Generate fixture secrets on the guest's persistent disk; never print them or
  put values in Nix expressions, command arguments, artifacts or the store.
- Keep `/readyz` at 503; telemetry acceptance is not physical-command readiness.
- Do not add a slow image/VM build to automatic branch-push workflows.

## Tasks

- [x] Add `tests/platform/test_telemetry_vm.nix` using the actual profile,
  telemetry module, pinned archives and UI. First boot with credentials withheld;
  assert the local UI starts while dependent services stay unavailable.
- [x] Release the test credentials and wait for automatic retries to start the
  containers, database migration and broker provisioning. Do not manually start
  those production units to conceal a missing recovery edge.
- [x] Reuse `telemetry_stack_integration.py` synthetic publishing/inventory/Grafana
  checks through a guest-only adapter; prove seven correct NULL/zero fixture rows.
- [x] Restart/fail database, broker and Grafana units separately. Verify their
  automatic recovery and health, then prove fourteen rows without duplicates.
- [x] Cold-restart the guest with its existing disk, keeping all NICs absent;
  prove unattended startup, saved telemetry and stable credentials.
- [x] Observe meaningful failures before any production fix; add focused
  regression contracts, implement only the needed change and rerun acceptance.
- [x] Run relevant host/module checks, document exact evidence and remaining
  native/hardware gaps, and commit this increment locally.

Primary files: new `tests/platform/test_telemetry_vm.nix` and
`tests/platform/telemetry_vm_check.py`; only change
`nix/nixos-modules/ground-station/telemetry.nix` if the real guest exposes a bug,
with corresponding `tests/platform/test_telemetry_module.nix` regression checks.
Update `docs/operations/telemetry-stack.md` and the main implementation checklist
after observing the actual outcome.

## Findings during execution

The real guest reproduced a boot barrier with credentials withheld: nginx was
available, but `multi-user.target` still had a waiting start job after 120 more
seconds. Six telemetry units were ordered before that target; preparation retried
while five consumers waited. The fix moves telemetry into a nonordering background
target, removes implicit OCI multi-user activation, and preserves service/shutdown
dependencies. Three new module contracts failed before this change and passed
after it (59 total). Diagnostic reruns completed degraded boot and started
containers automatically after the fixture credentials were supplied. The final
direct-macOS run completed all acceptance cases below.

The reverse activation edges also cause immediate client-requested retries after
some preparation failures, bypassing the configured restart delay. That is distinct
from the boot barrier; do not claim a fixed retry cadence from configuration alone.

The full x86 guest starts the unmodified amd64 EMQX image successfully, unlike
the Docker Desktop/Rosetta attempt. It also automatically retries a deliberately
failed first migration. One later run lost the test transport without enough
diagnostics; a diagnostic rerun showed host available memory falling below
50 MiB and QEMU exiting on signal 9 at about 550 seconds. This strongly suggests
host memory pressure but did not identify the killer at that stage. Only the
fixture's guest RAM was reduced from 4 GiB to 3 GiB to leave host emulation
overhead on the 8 GiB builder; production services/images stayed unchanged and
post-failure counter collection was added.

The 3 GiB retry completed broker provisioning, then QEMU was killed at roughly
756 seconds. The same runner's `oom_kill` counter increased from zero to one,
confirming host OOM during this attempt. This is not a completed ingestion or
recovery test. The locked framework explicitly supports an aarch64-Darwin host
with an x86 guest. The runner was moved directly to the Mac to avoid the Linux
builder's 8 GiB host limit. Linux-only diagnostics are guarded on Darwin and
hardware acceleration remains optional; guest services and amd64 archives stay intact.

The direct macOS runner has completed degraded boot, automatic credential and
migration recovery, broker/Grafana inventory and seven correct synthetic rows.
Separate database, broker and Grafana SIGKILLs recovered automatically with fresh
container IDs and provisioning invocations where applicable. All saved rows
survived and a second batch produced fourteen correct rows without duplicates.
The populated-disk cold restart also passed: all NICs stayed absent, the boot ID
changed, credentials were byte-identical, all fourteen rows remained correct,
and a third batch produced 21 correct rows without duplicates. The held-out
Grafana timer was then enabled and its actual probe completed successfully.
`/readyz` stayed 503 and the command listener was absent. The test completed in
1,492 seconds with exit status zero; output:
`/nix/store/js5rm5j0zlr2vfdgz1n62psa6xnf962m-vm-test-run-ground-telemetry-offline-recovery`.
This proves emulated service behavior, not native hardware timing, abrupt machine
power-loss recovery or physical field acceptance.

Repeated broker reconciliation now compares owned public fields and skips
unchanged schema/action/rule writes. Masked connector passwords are still
reapplied. Schema compilation gets a bounded longer request budget within the
overall deadline. Two focused tests failed before the change; all 17 runtime
tests now pass on Darwin and x86 Linux. The host suite passes 110 tests with one
Linux-only skip; the telemetry/foundation contracts pass 59/121 checks.

Hardware handoff: the user identifies the existing mini PC as Linux with SSH user
`root`; the configured MQTT host is `192.168.1.206`. On 2026-11-10 the user clarified
that the PC is powered off. Treat `root@192.168.1.206` as the planned connection,
not a completed SSH/hardware test. Continue the isolated VM work independently.
