# Telemetry retry cadence implementation plan

**Goal:** Remove dependency-triggered immediate retry loops while retaining unattended telemetry recovery.

**Architecture:** Request dependent services only after a prerequisite successfully starts. Keep startup consumers' Requires/After/BindsTo/PartOf and the background boot target. Make the health probe observational with Requisite/After, without activating Grafana. Enqueue starts asynchronously so success hooks never wait for their own ordered consumers.

**Tech stack:** Locked NixOS/systemd, Nix module contracts, an isolated x86 QEMU guest on macOS.

## Constraints

- No physical host connection, deployment, credentials or production image changes.
- Keep `/readyz` at 503 and commanding disabled.
- A controlled service fixture proves scheduling only; rerun the real-image VM for ingestion and persistence.
- A newly successful prerequisite or explicit administrator start/restart request can override a pending automatic delay. Fix feedback under unchanged failures, not a global limit on all start requests.

## Task 1: Reproduce and fix the activation feedback

Files: `tests/platform/test_telemetry_retry_vm.nix`, `tests/platform/test_telemetry_module.nix`, `nix/nixos-modules/ground-station/telemetry.nix`.

- [x] Extend the existing telemetry VM with controlled failing preparation/migration/broker executables and inert container processes. Retain the production activation graph, record monotonic invocation times privately, and assert automatic attempts are at least 4.8 seconds apart. Exercise the normal probe during degraded boot, then withhold it during recovery.
- [x] Run the fixture on the existing module and observe a cadence assertion fail.
- [x] Replace prerequisite service `wantedBy` feedback with success-only, nonblocking activation, for example `ExecStartPost = [ "${pkgs.systemd}/bin/systemctl --no-block start docker-ground-timescaledb.service docker-ground-emqx.service docker-ground-grafana.service" ];`. Containers retain background-target membership.
- [x] Update module contracts to check success-only recovery paths and absence of reverse Wants cycles. Preserve dependency and shutdown ordering; make the recurring probe observational.
- [x] Prove controlled preparation, migration and broker failures retry with delay; release inputs using marker files only; prove all consumers recover. Kill each inert container process and verify real systemd restart/provisioning invocations.

## Task 2: Verify and document the actual stack

- [x] Run module contracts and host tests.
- [x] Rerun `tests/platform/test_telemetry_vm.nix` with the actual amd64 images: offline boot, credential release, migration failure, three container kills, cold restart and 21 correct rows.
- [x] Update the architecture/checklist/runbook with exact evidence and the scope of automatic versus explicit start requests. Commit locally after checks pass.

Run focused acceptance:

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = "aarch64-darwin"; }; in import ./tests/platform/test_telemetry_retry_vm.nix { inherit pkgs; }' -o /private/tmp/ground-telemetry-retry-vm --option timeout 1200 -L
```

Root-cause evidence from the preceding real-service VM: systemd logged scheduled restarts immediately on client requests while consumers pulled failed prerequisites back into new start transactions. `RestartSec=5` remained configured but did not govern those requests. The [systemd 262 service documentation](https://www.freedesktop.org/software/systemd/man/262/systemd.service.html) specifies that success hooks participate in startup ordering, so enqueueing with `--no-block` is required.

## Evidence during execution

The scheduling fixture failed on the original graph: successive preparation
invocations were about 0.8–1 second apart. Five updated module contracts also
failed before the production change. Afterward all 60 telemetry and 121
foundation contracts passed; the host suite passed 110 tests with one Linux-only
skip. The scheduling VM passed in 140 seconds. Preparation gaps were at least
5.85 seconds with the normal probe active; migration and broker gaps were at
least 5.93 and 5.95 seconds respectively. Inputs were released using marker files
only, with the probe withheld, and all consumers recovered. Killing each inert
container process produced the expected automatic restart and fresh provisioning
invocations. The probe timer had fired during degraded boot without executing
its service or activating Grafana; it executed after recovery. This proves the
service graph's scheduling behavior. Its output is
`/nix/store/ddmhn15d8d7yl047wrfm5m9qbxcssbmk-vm-test-run-ground-telemetry-retry-cadence`.

The unchanged real-image acceptance script also passed on the new module in
994 seconds, exit status zero. It covered missing-credential boot, automatic
credential recovery, deliberately failed migration, separate database/broker/
Grafana SIGKILLs, preserved fourteen rows and byte-identical telemetry credentials
after a populated-disk cold restart, and 21 correct rows after new ingestion.
The recurring Grafana probe completed; NICs remained absent, `/readyz` remained
503, and the command listener stayed absent. Output:
`/nix/store/bndmzk2bzi9avmfz597gjcyx8dg4sp55-vm-test-run-ground-telemetry-offline-recovery`.
These emulated timings are not a comparative performance benchmark. Native
hardware, abrupt power loss and physical field acceptance remain unverified.

The user chose to keep working without the mini PC on November 11. No hardware
connection or configuration change was attempted in this increment.
