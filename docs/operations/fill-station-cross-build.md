# Build the fill station on the ground station

## Agreed direction

Use the existing Nix cross-compilation pattern on the UM560. The build machine is
`x86_64-linux`; the fill-station target remains `aarch64-unknown-linux-musl` with
`gcc.cpu = "cortex-a53"`. Native x86 Linux tools produce ARM board software. Normal
station builds should not require emulating an entire ARM Linux build machine.
The ground station's own NixOS system is still built natively for x86-64.

The implementation already exists in
`nix/mixos-modules/fill-station-base/default.nix`:

```nix
nixpkgs.pkgs = import inputs.nixpkgs {
  localSystem = config.fillStation.buildSystem;
  crossSystem = {
    config = "aarch64-unknown-linux-musl";
    gcc.cpu = "cortex-a53";
  };
  config.allowUnfreePredicate = package: lib.getName package == "ti-pru-cgt";
  overlays = [
    inputs.self.overlays.default
    inputs.mixos.overlays.default
  ];
};
```

`nix/flake-modules/mixos-configurations.nix` supplies separate build graphs:

| Use | Build system | Flake output |
| --- | --- | --- |
| UM560, intended normal station route | x86_64-linux | `mixosBuildConfigurations."x86_64-linux"` |
| Existing Mac Linux-builder fallback | aarch64-linux | `mixosConfigurations` |

Both retain the same board target and vehicle configuration. Keep the tested
ARM64 default; select the x86 graph explicitly rather than replacing the default
for everyone's laptop.

## Prove the station route before making it preferred

On the UM560 with the checkout and required dependencies prepared:

```sh
./scripts/platform build fill-station --vehicle liquid --artifact ospi \
  --build-platform x86_64-linux --builder local
./scripts/platform build fill-station --vehicle hybrid --artifact ospi \
  --build-platform x86_64-linux --builder local
```

These are validation commands, not a claim that complete x86 images are already
accepted. Both x86 overlays have component build evidence; full applications,
PRU firmware/toolchain, kernel, bootloaders and FIT/OSPI bundles still require
complete builds and board checks. Review any dependency that tries to execute an
ARM target binary during its build. Fix its build/host separation first; retain
ARM QEMU/binfmt as an explicitly tested exception or alternate graph, not a
mandatory prerequisite for native x86 cross-building.

After validating station transport, signing and resource controls, the Mac can
request the same route using `--builder station --build-platform x86_64-linux`.
Station remote building remains disabled until that acceptance is complete.

## Cache, fallback and deployment implications

- The station cache can retain closures from both graphs. Different build systems
  can produce different derivation/store paths, so do not assume the laptop ARM
  graph and station x86 graph share every cache result or produce identical bytes.
  Record the selected graph in manifests and compare functional board behavior.
- Preserve the working Mac/Determinate ARM64 Linux builder as fallback. Offline
  builds require all needed source/toolchain inputs to have been prepared; a
  binary cache cannot supply artifacts it has never received.
- Select station-first only after measuring matching source/lock/profile builds,
  transfer time, memory use and impact on telemetry. Otherwise retain laptop-first
  routing and explicit station selection.
- A build does not deploy. Routine releases are OSPI-only; retain the DATA/recovery
  SD and its working boot switches. Stage and verify a FIT over Ethernet/SSH,
  flash/read back with the existing updater, explicitly reboot, then verify SSH,
  advancing telemetry and persistent state. Bootloader/full-flash and recovery
  operations remain separate choices.

## Next implementation increment

After the Grafana/commanding display increment, continue with the
[build/deployment checklist](../superpowers/plans/2026-11-18-build-deployment.md).

## Validation progress — November 18

The first complete Liquid graph audit counted 1,861 x86 Linux derivations and
155 built-in fetch operations, with no ARM execution platform. Complete Liquid
and Hybrid OSPI builds are in progress in an isolated x86 Linux store on the
Mac; this is graph/build validation, not a native UM560 speed benchmark.

The current hardware profiles select no PRU PWM channels, so those OSPI graphs
do not exercise the optional PRU toolchain. A separate Liquid PRU build first
failed because PRoot/QEMU could not resolve the TI installer's 32-bit loader.
Direct QEMU with the pinned loader succeeded. The x86 package now uses that
path without PRoot and compiled both PRU core images with passing scheduler
tests; the existing ARM-hosted PRoot path is retained. The narrow vendor-tool
emulator exception does not require an ARM build VM. Hybrid PRU firmware also compiled and passed scheduler tests. All four output
ELFs identify as 32-bit TI Programmable Realtime Unit executables.

The CLI now accepts `build ground-station --profile um560-services`, selects the
installed services system, and records its exact attribute in the release
manifest. Foundation remains the default for compatibility. It never activates
the system or issues hardware commands.

The first full OSPI attempt stopped in the MixOS Zig dependency fetch stage with
`rosetta error: bss_size overflow` (exit 133). The pinned dependency bundle was
then recovered from the existing ARM build store and verified against the same
`sha256-E0J8FsSmUDD6oc/1A7OUXd6nZMbLqi+zKMwbDdDHqBM=` hash before importing
its exact fixed-output path. The full build resumed without a source override.
This is legitimate sharing of a fixed source input between build systems, not
proof that architecture-dependent compiler outputs share paths. Native mini-PC
execution and performance acceptance remain separate.

For the first native UM560 acceptance build, use the
[prepared offline recipe/input bundle](native-cross-build-check.md). It avoids
requiring a Git checkout, Python CLI installation or network input resolution on
the isolated mini PC. The repository CLI remains the ongoing interface once the
station source/tools are provisioned.

## Native Liquid build: operator-confirmed November 19

The UM560 completed the offline Liquid cross-build with the one-time local
maintenance command, one Nix job, three cores/300% CPU and a 6 GiB memory cap.
The result symlink resolved to a fill-station OSPI store output, and all four
SHA256SUMS entries passed. The operator reported the build exceeded one hour;
exact elapsed time was not measured. Hybrid build and physical cross-built
image boot/peripheral acceptance remain pending. No flashing was reported.

## Native Hybrid build: operator-confirmed November 19

The UM560 also completed the offline Hybrid cross-build using the same bounded
local maintenance route. All four bundle checksum entries passed. The operator
reported that it built very quickly after Liquid, consistent with reuse of shared
dependencies; no numeric timing or station-versus-laptop benchmark was recorded.
Both native OSPI build/checksum checks are now accepted. Cross-built board boot,
FIT sizes, signed cache/remote worker acceptance and deployment orchestration
remain separate outstanding checks. Actuation stays deferred to the UI rework.

## Native FIT sizes: operator-reported November 19

- Liquid: **12,844,276 bytes**.
- Hybrid: **12,844,700 bytes**.
- Combined `wc` total: **25,688,976 bytes** (not an individual image).

Liquid is 692,852 bytes (5.12%) smaller than the
13,537,128-byte working pre-trim baseline. This is a measured image comparison
across the current cross-build/profile state, not attribution of all savings to
Wi-Fi removal. Both FITs remain below the 58,458,112-byte OSPI FIT slot. Board
boot acceptance remains pending; no new flash was reported.

## Integrated Liquid deployment: operator-confirmed November 19

The mini-PC-built Liquid FIT was deployed using the FIT-only updater and the
operator reported that the complete integrated test passed: fill-station reboot,
wired SSH/telemetry return, mini-PC reboot, automatic two-screen startup and
single-screen tab fallback. Camera playback works in the mini PC's Grafana.
No actuation acceptance is implied; it remains deferred to the UI rework. Hybrid
has build/checksum acceptance, not physical boot acceptance.

A separate LAN-client issue remains open: Grafana telemetry loads from the Mac,
but camera playback fails there while working on the mini PC. Browser and direct
`/cameras/` behavior are being checked. The current relay exposes fragmented MP4
for Chromium; Safari/HLS compatibility was explicitly not implemented. The
viewer and Grafana embed use same-origin `/cameras/` paths, not localhost camera
URLs, so no hard-coded client-host address error was found in that path.
