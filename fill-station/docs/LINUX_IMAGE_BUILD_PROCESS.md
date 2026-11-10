# Linux Image Build Process

This guide describes the current TI SK-AM64B MixOS image build. The intended
NixOS ground-station/cache/build architecture is in
[ground-platform.md](../../docs/architecture/ground-platform.md), with a
[phased checklist](../../docs/superpowers/plans/2026-11-09-ground-platform.md).
Those services and the proposed `scripts/platform` interface are not implemented
by documenting them. Current deployment is in the
[SD/OSPI runbook](../../docs/operations/fill-station-deployment.md).

## Inputs and build platform

The repository's `flake.lock` pins Nixpkgs, MixOS, and flake tooling. Source packages
live under `nix/packages/crt`; shared image modules under
`nix/mixos-modules/fill-station-base`; machine selections under
`nix/mixos-configurations/*.nix`. `nix/flake-modules` exports those configurations.

The current fill-station module selects an `aarch64-linux` build platform and an
`aarch64-unknown-linux-musl` target, tuned for Cortex-A53. On an Apple-silicon Mac,
use the configured ARM64 Linux VM/builder. An x86 Linux machine is not automatically
compatible: the ground-station roadmap first proves ARM64 emulation, with native
x86 cross-builds considered separately. Kernel editing is described in
[nix/linux-kernel.md](../../nix/linux-kernel.md).

The current GitHub image workflow still uses FlakeHub until replaced. This is a
migration dependency, not the desired permanent architecture. Host-level Nix
cache settings also matter; changing repository inputs alone does not remove
FlakeHub from an installed daemon's substituters.

## Build commands

Liquid full SD:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage -o result-sd-liquid
```

Hybrid full SD (the default configuration):

```sh
nix build .#mixosConfigurations.fill-station.config.system.build.sdImage -o result-sd-hybrid
```

For the smaller build components and flash bundle, for example Liquid:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.pinmuxOverlay -o result-pinmux-liquid
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.fitImage -o result-fit-liquid
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage -o result-ospi-liquid
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.dataCardImage -o result-data-liquid
```

The debug configuration is `fill-station-debug` (Hybrid). There is no separate
ADS7128 diagnostic machine; add selectable devices in the hardware editor and
build the matching normal vehicle. Saving does not deploy it or add telemetry
roles to unbound devices.

A `result-*` entry is normally a symlink into the Nix store. It names that build's
output, not necessarily the current source. New Git-backed flake files must be
tracked to enter the build. Record source/profile identity before deployment.

## Build stages and key files

| Stage | Current source | Result |
| --- | --- | --- |
| R5 bootloader | `nix/packages/crt/ti-uboot-r5` | Board/security-specific `tiboot3.bin` |
| A53 bootloader | `nix/packages/crt/ti-uboot-a53` | `tispl.bin`, `u-boot.img`, compiled boot policy |
| Trusted firmware | `ti-arm-trusted-firmware`, `ti-optee`, `ti-linux-firmware` packages | Boot dependencies |
| Kernel | `fill-station-linux/package.nix` and `kernel.config` | Kernel, DTBs, modules |
| Hardware config | `fill-station/hardware/compiler.py` and selected profile | Matching runtime configuration and DT overlay |
| Application | `fill-station/package.nix` and `fill-station/build.rs` | Vehicle-selected Rust binary and generated nanopb bindings |
| Runtime | `fill-station-base/default.nix` and MixOS | Immutable userspace/initrd plus persistent-state setup |
| FIT | `fill-station-base/fit/` | `fitImage.itb` containing kernel, merged DTB and initrd |
| SD | `fill-station-base/sd-image/` | Full card image |
| OSPI/DATA | `fill-station-base/ospi-image/` | Flash bundle and DATA-only card image |

The FIT build applies the generated pinmux overlay to the kernel's SK DTB,
checks controller/pin expectations, adds boot arguments, compresses the kernel
with LZMA, and packages it with the initrd. It rejects a FIT larger than the
58,458,112-byte OSPI slot. Overlay-only success does not validate the complete
FIT build, a board boot, or physical pin behavior.

The current FIT uses CRC32 integrity checks, not authenticated signatures. Do not
infer secure boot from the FIT format or confuse Nix-cache signing with bootloader
verification. SHA256 transport checks and flash read-back also do not authenticate
a signer to the bootloader.

## Runtime and persistent storage

Linux starts from the FIT/initrd and creates a tmpfs runtime root, with packaged
userspace supplied by MixOS. The shared SSH startup corrects `/` to mode 0755
before Dropbear runs: mode 1777 was confirmed to cause parent-directory rejection
of valid public keys. Password login remains disabled; authorized keys are
versioned under `fill-station-base/authorized_keys`.

The SD partition labeled DATA is ext4 and mounted at `/state`. MixOS uses it for
persistent `/etc` overlay directories and `/var`, `/root`, `/home` state. FAT32
cannot serve as this OverlayFS backing filesystem. Existing FAT32 DATA cards
must be backed up and replaced; there is no automatic formatting/migration at boot.
CSV logs are under `/var/log/fill-station`. SSH host keys are intended to persist.
Inspect Dropbear logs in `/var/log/messages`; `logread` requires a shared-memory
buffer that this configuration does not enable.

The full SD image has a 2 MiB initial gap, a 128 MiB FAT firmware partition and
1 GiB ext4 DATA. Firmware contains `tiboot3.bin`, `tispl.bin`, `u-boot.img` and
`fitImage.itb`. The DATA-only image is a separate 256 MiB ext4 DATA partition
plus partition-table gap; it does not contain recovery bootloaders.

## Actual U-Boot boot policy

Boot policy is compiled in `nix/packages/crt/ti-uboot-a53/package.nix`; the image
no longer supplies the formerly documented `uEnv.txt`. Nor does this version
provide the old custom `boot_device`/`ospiboot` interface.

The ROM's boot-mode switches select the initial boot source. The boot stages are
ROM → R5 SPL (`tiboot3`) → A53 SPL (`tispl`, trusted firmware/OP-TEE) → main U-Boot.
Main U-Boot then tries:

1. Load `fitImage.itb` from MMC device 1, partition 1, and boot it.
2. If that returns/fails, probe OSPI, read the FIT header from offset `0x800000`,
   validate its size against `0x37c0000`, read that FIT, and boot it.

The built U-Boot inspected during integration uses `addr_fit=0x90000000`; the
kernel FIT load/entry address is separately `0x82000000`. Use the actual built
bootloader environment when debugging; these are different purposes.

A bootable SD can hide an OSPI problem. There is no SD retry after the OSPI attempt
and no A/B boot-success/rollback mechanism. Current U-Boot networking is disabled;
Linux SSH updates work without network boot.

## Flashing to SD Card

Back up logs first. Identify the destination card and confirm it is not a system
or data disk. Write the complete matching `fill-station.img` using a raw-image
writer such as the existing team SD-writing workflow, then eject it cleanly.
The image replaces the card partition table and DATA contents; do not copy the
image file into a mounted FAT filesystem. This document deliberately does not
supply a guessed `/dev/diskN` destructive command.

For SD testing use a full SD image and the board's documented SD boot-switch
position. For OSPI testing, first provision flash from a known-good running image,
then power off, choose the documented OSPI switch position, and insert a DATA-only
card. Preserve the full SD card as manual recovery media.

## OSPI update and recovery

Follow [fill-station-deployment.md](../../docs/operations/fill-station-deployment.md).
Use `tools/flash-ospi.sh TARGET all BUNDLE` for first provisioning/reviewed bootloader
changes, and `fit` for routine application/kernel/FIT updates. The script checks
SHA256 before writing and uses flashcp read-back comparison. It does not safe the
application, verify the vehicle, perform an atomic update, or reboot automatically.
Current per-file preflight does not guarantee later bundle files are valid before
the first write; stronger all-files preflight is planned.

Running from RAM permits updating flash while Linux is running. An interrupted
write can still leave OSPI unbootable. Manual recovery is power-off → SD boot with
the known-good full image → Linux → reflash the reviewed bundle. Never promise
power-loss tolerance or automatic SD fallback on the basis of the current script.

## Verification and troubleshooting

- Build both vehicle variants when changing shared configuration; use the
  [hardware testing guide](HARDWARE_CONFIG_TESTING.md) for profile/pinmux checks.
- Capture serial output at 115200 8N1. Record source revision, vehicle, profile,
  image identity, actual boot source, kernel version and connected hardware.
- After a fresh boot, verify root mode, ext4 `/state`, SSH keys, reboot persistence,
  application health and expected peripherals. SD and OSPI are separate tests.
- For a FIT failure, inspect serial and `mkimage -l fitImage.itb`, MMC partition,
  compiled boot command, OSPI offset/size and image integrity. There is no image
  `uEnv.txt` to edit in the current implementation.
- For SSH key rejection, see [troubleshooting](TROUBLESHOOTING.md). Do not erase
  authorized keys or weaken password/host-key checks to hide a permissions error.
- Missing cache/worker is a build-infrastructure issue, not proof of bad hardware;
  offline builds need prepared inputs and a compatible Linux worker.

## References

- [U-Boot FIT documentation](https://docs.u-boot.org/en/latest/usage/fit/index.html)
- [Nix distributed builds](https://nix.dev/tutorials/nixos/distributed-builds-setup.html)
- [Nix binary caches](https://nix.dev/tutorials/nixos/binary-cache-setup.html)
- [Ground-platform architecture](../../docs/architecture/ground-platform.md)
