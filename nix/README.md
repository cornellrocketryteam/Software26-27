# Nix infrastructure

This directory contains the development environments, fill-station kernel and
firmware packages, and MixOS image builds.

For the intended x86-64 NixOS ground station, signed LAN cache, optional ARM64
build worker, durable offline publication queue and reduced GitHub CI, see the
[ground-platform architecture](../docs/architecture/ground-platform.md) and
[checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md).
The [NixOS foundation](nixos-configurations/ground-station/README.md) and
[build/cache CLI](../tools/platform/README.md) now exist. Full station services,
live signed-cache/receipt deployment and hardware acceptance remain pending. The default
fill-station graph still uses an ARM64 Linux build host; explicit experimental
x86 cross-build graphs have overlay-build evidence, not complete image validation.
`.github/workflows/nix.yml` still builds through FlakeHub on branch pushes until
the replacement workflow is implemented and tested.

Normal fill-station operation should use local OSPI boot with network-delivered
updates and SD recovery. Existing commands are in the
[deployment runbook](../docs/operations/fill-station-deployment.md). No actual
network boot or automatic A/B rollback is currently implemented.

- [Editing the Linux kernel config](linux-kernel.md): use `nix develop` on Linux
  or inside the Darwin Linux builder VM on macOS.
