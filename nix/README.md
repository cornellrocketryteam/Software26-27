# Nix infrastructure

This directory contains the development environments, fill-station kernel and
firmware packages, and MixOS image builds.

For the intended x86-64 NixOS ground station, signed LAN cache, optional ARM64
build worker, durable offline publication queue and reduced GitHub CI, see the
[ground-platform architecture](../docs/architecture/ground-platform.md) and
[checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md).
They are planned work: the current configuration still uses an ARM64 Linux
build host, and `.github/workflows/nix.yml` still builds through FlakeHub on
branch pushes until the replacement workflow is implemented and tested.

Normal fill-station operation should use local OSPI boot with network-delivered
updates and SD recovery. Existing commands are in the
[deployment runbook](../docs/operations/fill-station-deployment.md). No actual
network boot or automatic A/B rollback is currently implemented.

- [Editing the Linux kernel config](linux-kernel.md): use `nix develop` on Linux
  or inside the Darwin Linux builder VM on macOS.
