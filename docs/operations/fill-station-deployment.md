# Fill-station local boot and network updates

This is the current procedure. The [ground-platform architecture](../architecture/ground-platform.md)
and [roadmap](../superpowers/plans/2026-11-09-ground-platform.md) describe future
orchestration; `scripts/platform` does not exist yet. The board boots locally;
SSH is used for deployment, not network boot.

## Build one vehicle from the working checkout

Liquid:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage -o result-sd-liquid
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage -o result-ospi-liquid
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.dataCardImage -o result-data-liquid
```

For Hybrid, use `mixosConfigurations.fill-station` and corresponding `-hybrid`
output names. The current full build requires an ARM64 Linux worker; the Mac's
Linux VM is the established fallback. Ground-station cache/build selection is
future work. Finish local profile changes and include new files in the Git-backed
flake before building. Never change vehicle wiring just to make tests pass.

## SD provisioning and recovery

Back up logs and use the card-writing procedure in
[LINUX_IMAGE_BUILD_PROCESS.md](../../fill-station/docs/LINUX_IMAGE_BUILD_PROCESS.md).
The full SD image contains boot firmware plus ext4 DATA. The DATA-only image
contains ext4 state/log storage for OSPI operation; it cannot recover missing
bootloaders by itself. Keep a separate tested full SD for recovery.

Boot the fresh image, verify SSH without a manual chmod, `/` mode 0755, ext4
`/state`, log persistence, expected vehicle/profile and connected peripherals.
Retain serial access. The user reports SD, OSPI, and persistent SSH operation;
automatic rollback and power-cut recovery have not been demonstrated.

## Initial OSPI provisioning or reviewed bootloader change

With the board running Linux from a known-good SD and the bench made ready for
maintenance, check `flashcp` and `/proc/mtd`, then from the Mac:

```sh
tools/flash-ospi.sh fillstation all result-ospi-liquid
```

The `fillstation` SSH alias is local configuration; alternatively pass the verified
`root@BOARD_IP`. This writes bootloaders and FIT and prompts first. Keep power
stable. The script verifies copied checksums and flash read-back, but does not
verify the board's vehicle or safe actuator state; the operator must do that.
It currently preflights each file just before writing it, not the whole batch
before the first erase. Reboot is separate and requires a post-boot check.

## Ordinary OSPI update

First confirm the board is configured for OSPI boot and has only a DATA-only
card inserted, not a full SD firmware partition. Otherwise reboot can select
the older SD FIT and mask the update. Retain serial access.

Build the matching bundle above, record its revision and vehicle, prepare the
bench for maintenance, and upload only the FIT:

```sh
tools/flash-ospi.sh fillstation fit result-ospi-liquid
```

After successful verification, explicitly reboot from your operator terminal:

```sh
ssh fillstation reboot
```

Confirm `Booting FIT from OSPI...` in serial and verify the expected release,
application health, SSH and persistent state before declaring the update successful. No root filesystem installation is required while powered off: this
system runs from RAM after boot, allowing staged Linux/SSH updates to flash.
That does not make an interrupted erase/write atomic or automatically recoverable.

## Prove actual OSPI boot and recover

Use the board's documented OSPI boot-switch position, power-cycle, and use only
the DATA-only card. Keep the full recovery card aside. Expect the serial message
`Booting FIT from OSPI...` followed by successful Linux/application startup.

Current U-Boot tries an SD FIT first, then OSPI. A bootable SD can mask an OSPI
problem; OSPI failure does not trigger a second SD attempt. To recover, power off,
select SD boot, insert the known-good full SD, boot Linux, and reflash the verified
bundle. FIT-only corruption need not require rewriting working bootloaders.

The single FIT slot has no A/B rollback. Current FIT CRC32 detects corruption;
SHA256 transfer/read-back checks are not authenticated secure boot. Do not replace
this recovery procedure with proposed network boot until that path is implemented
and tested independently.
