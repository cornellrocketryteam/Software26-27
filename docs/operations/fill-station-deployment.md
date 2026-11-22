# Fill-station local boot and network updates

This is the current procedure. The [ground-platform architecture](../architecture/ground-platform.md)
and [roadmap](../superpowers/plans/2026-11-09-ground-platform.md) describe future
deployment orchestration. The [build CLI](../../tools/platform/README.md) now
handles builds and the local publication queue; deployment still uses the
procedure below. The board boots locally; SSH is used for deployment, not network
boot.

New images use wired DHCP on `eth0`, with no automatic Wi-Fi association. Follow
the [Ethernet setup and test guide](../../fill-station/docs/ETHERNET_SETUP.md)
when moving an older image to the `192.168.1.x` LAN. Reserve the intended `.106`
address only after observing the board's Ethernet MAC.

## Build one vehicle from the working checkout

The unified build command records a frozen tracked source snapshot, manifest and
GC roots. Include new intended source files in Git before building:

```sh
./scripts/platform check
./scripts/platform build fill-station --vehicle liquid --artifact ospi --builder local
./scripts/platform status
```

Find the artifact links under `outputs/platform/RELEASE_ID/`. The default is
`ospi`; the existing boot switches and DATA card are already configured, so normal
updates do not rebuild SD or DATA images. Explicit `--artifact release` produces
all three only when provisioning/recovery media are needed. Use `--artifact fit` for
a FIT-only build. `status` reports pending publication, not board test results.
No station is needed for local builds; absent cache configuration leaves artifacts
locally rooted and pending. Prepared offline input retention is not implemented.

The raw attributes below also remain supported. Unlike the CLI, they do not create
its manifest or publication record.

Liquid:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage -o result-ospi-liquid
```

For Hybrid, use `mixosConfigurations.fill-station` and corresponding `-hybrid`
output names. The current full build requires an ARM64 Linux worker; the Mac's
Linux VM is the established fallback. Optional station routing exists in the CLI,
but no station worker has been provisioned or validated. The experimental x86
graph has component-build evidence only. Finish local profile changes and include
new files in the Git-backed flake before building. Never change vehicle wiring
just to make tests pass.

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

## Deployment SSH diagnostic correction

`tools/flash-ospi.sh` now uses strict host checking, noninteractive key authentication
and a five-second connection timeout for each SSH connection. An authenticated
remote shell explicitly reports missing flashcp; rejected keys, host-key failures
and transport errors no longer produce the misleading missing-flashcp message.
Deployments never reboot implicitly. A configured SSH host alias can select the
station's dedicated deployment IdentityFile; existing explicit user@IP targets
remain supported. The diagnostic correction has fake-endpoint regression checks;
actual station key enrollment is still a separate hardware step.

## Unified explicit deployment CLI (source candidate)

The source CLI now supports `deploy --manifest "$manifest" --target fillstation-deploy`.
`$manifest` must be the exact manifest path returned by the selected normal build;
do not automatically choose the newest output. First run the same command with
`--dry-run` to inspect profile, target and FIT identity. It requires a complete
OSPI artifact. FIT-only/SD-only manifests and inconsistent, empty or symlinked
bundle payloads are rejected. The actual command stages verified bytes before SSH
so later source-directory changes cannot alter the transmitted image.

The installed `crt-platform` packages its own flash script and dependencies; it
does not execute a similarly named script from the caller's working directory.
The dedicated station identity/host pinning still requires hardware enrollment.
Configure the named SSH alias using the accepted-system guide; explicit user@host
targets also work with the caller's established key and strictly checked host.
No private key is copied/generated by the deployment CLI.

Deployment writes FIT only. Its state directory contains per-release attempts
and logs under `deployments/`; `status` lists them. Build/cache publication
manifests remain immutable. Successful flash read-back records `flash-verified`
with `runtimeAcceptance: pending` and `rebootRequested: false`. Reboot explicitly
with SSH when ready and verify returning telemetry before claiming runtime
acceptance. Bootloader changes still use the separate deliberate low-level flow.

A nonzero result or interruption records failed/unconfirmed state, does not retry
and does not reboot. Local locks serialize this CLI state, not every possible
updater on the network; use one maintenance updater for the board. Remote
partition names/capacities are strictly parsed before staging. There is no global
write timeout that kills a possibly active flash erase/write.

Tests use the real flash script with fake SSH and cover checksum/mapping rejection,
malformed remote metadata, source mutation after staging, authentication failure,
interrupted write, FIT-only/no-reboot behavior and installed-layout execution.
Actual native packaging, key enrollment and board update/boot remain pending.
