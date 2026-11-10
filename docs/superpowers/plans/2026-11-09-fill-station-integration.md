# Fill-station integration implementation plan

**Goal:** Combine Max's Nix branch, Kaleb's existing fill-station changes, and the local ADS7128 diagnostic into buildable Hybrid and Liquid images for bench testing.

**Architecture:** Fast-forward `kaleb_branch` to `origin/ml/nix-improvements`, retaining its shared fill-station base and upstream U-Boot configuration. Restore the local diagnostic as an opt-in Liquid machine using the same binary; normal images retain normal startup.

**Tech stack:** Nix/MixOS, Rust, Python hardware-profile checks.

## Constraints

- Do not merge `ereg`, `fsw`, or `main`, push, flash hardware, or actuate devices.
- Preserve original local changes in `/private/tmp/software26-integration-backup` and a Git stash.
- Retain Max's SD-first/OSPI-fallback boot flow and disabled U-Boot networking.
- Treat builds as build evidence; physical boot and peripheral tests remain with the user.

## Tasks

- [x] Back up local files, stash, and fast-forward to Max's eight commits.
- [x] Restore local changes and resolve the already-fixed DTBO verifier filename conflict in `nix/packages/crt/fillstation-dtbo/package.nix`.
- [x] Recover the early ADS7128 command and test its address validation before implementation; helper owns only `fill-station/src/ads7128_bench.rs` and minimal `main.rs` wiring.
- [x] Replace the obsolete empty directory-based machine with `nix/mixos-configurations/fill-station-liquid-ads7128-test.nix`, selecting Liquid and overriding only its init process.
- [x] Evaluate normal Hybrid, Liquid, and the diagnostic machine. Verify the diagnostic bypasses normal actuation startup.
- [x] Verify the documented VFAT/OverlayFS incompatibility against pinned MixOS `src/init.zig:611-618`; reproduce the failed filesystem assertion, then set state and both DATA image builders to ext4. The assertion passes after the fix; images run `e2fsck -fn` during construction.
- [x] Run hardware/profile tests and build normal/diagnostic SD images with the merged configuration where available.
- [x] Update diagnostic instructions for Max's layout and boot commands; report artifact paths and remaining board checks.

## Validation result

- Standalone ADC Rust tests: 5 passed. Hardware/configuration/server/telemetry tests: 34 run, 1 PostgreSQL-dependent test skipped; pinmux tests: 19 passed. Repository layout, scoped Rust formatting, shell syntax, and diff checks passed.
- Full cross builds passed for Hybrid, Liquid, and ADC-only Liquid SD images, both normal OSPI bundles, and the DATA-only card. No hardware was flashed or actuated.
- Inspected all three SD images and the DATA-only image: Linux partition type, ext4 superblock, and DATA label match the runtime state setting.
- Hybrid FIT: 18,731,812 bytes; Liquid FIT: 18,731,028 bytes. Both FIT headers match their file sizes and fit the 58,458,112-byte OSPI slot.
- Built U-Boot contains `addr_fit=0x90000000` and the expected SD-first, OSPI-fallback boot command.
- Test outputs: `result-sd-hybrid-integrated`, `result-sd-liquid-integrated`, `result-sd-ads7128-integrated`, `result-ospi-hybrid-integrated`, `result-ospi-liquid-integrated`, `result-data-integrated`.
- Fresh SD images are required: old FAT32 DATA cards are incompatible with the ext4 state mount. Physical boot, GPIO chip numbering, peripherals, persistence, and OSPI boot remain board checks.
