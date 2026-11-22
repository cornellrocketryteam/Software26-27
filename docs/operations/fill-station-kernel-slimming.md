# Fill-station kernel slimming: first increment

This increment disables only the Wi-Fi kernel stack, after the user's confirmation
of Ethernet `eth0`, OSPI, SSH, telemetry and reboot. It is not deployed or boot-tested.
Greybus, WWAN and USB serial OPTION remain enabled. The saved config is shared by
Liquid and Hybrid. No SD image is built by the commands below.

## Configuration resolution

Pinned source: Linux 7.2.15,
`/nix/store/r3smdaqjcsmjvh5smsg2iqq7c7cawzjf-linux-7.2.15.tar.xz`.
A temporary derivation inherited the actual fill-station kernel's source, patches,
ARM64 musl compiler and make flags and ran on the existing Determinate Linux builder.
It replaced the source-output unpack hooks with normal build-directory unpacking.
The original config passed `olddefconfig` without changes. Then:

```sh
scripts/config --file "$buildRoot/.config" --disable WIRELESS --disable WLAN
make "${makeFlags[@]}" olddefconfig
```

The resulting complete `.config` was saved back to
`nix/packages/crt/fill-station-linux/kernel.config`. Running `olddefconfig` again
produced an identical file. See `nix/linux-kernel.md` for the normal Linux editor
workflow; a remote builder does not make `nix develop` a Linux shell on macOS.

## Exact effective symbol changes

Kconfig omits hidden children of disabled menus rather than writing every child
as `# CONFIG_... is not set`. Entries that were already disabled and disappeared
from the file are not behavior changes. For the two scalar MAC80211 settings,
"disabled / omitted" means the setting no longer exists in the active Wi-Fi stack.

| Symbol | Before | After |
| --- | --- | --- |
| `CONFIG_CFG80211` | `m` | disabled / omitted |
| `CONFIG_CFG80211_CRDA_SUPPORT` | `y` | disabled / omitted |
| `CONFIG_CFG80211_DEFAULT_PS` | `y` | disabled / omitted |
| `CONFIG_CFG80211_REQUIRE_SIGNED_REGDB` | `y` | disabled / omitted |
| `CONFIG_CFG80211_USE_KERNEL_REGDB_KEYS` | `y` | disabled / omitted |
| `CONFIG_CRYPTO_LIB_ARC4` | `m` | disabled / omitted |
| `CONFIG_MAC80211` | `m` | disabled / omitted |
| `CONFIG_MAC80211_HAS_RC` | `y` | disabled / omitted |
| `CONFIG_MAC80211_LEDS` | `y` | disabled / omitted |
| `CONFIG_MAC80211_RC_DEFAULT` | `"minstrel_ht"` | disabled / omitted |
| `CONFIG_MAC80211_RC_DEFAULT_MINSTREL` | `y` | disabled / omitted |
| `CONFIG_MAC80211_RC_MINSTREL` | `y` | disabled / omitted |
| `CONFIG_MAC80211_STA_HASH_MAX_SIZE` | `0` | disabled / omitted |
| `CONFIG_SYSTEM_DATA_VERIFICATION` | `y` | disabled / omitted |
| `CONFIG_WIRELESS` | `y` | disabled / omitted |
| `CONFIG_WL18XX` | `m` | disabled / omitted |
| `CONFIG_WLAN` | `y` | disabled / omitted |
| `CONFIG_WLAN_VENDOR_TI` | `y` | disabled / omitted |
| `CONFIG_WLCORE` | `m` | disabled / omitted |
| `CONFIG_WLCORE_SDIO` | `m` | disabled / omitted |

`CRYPTO_LIB_ARC4` is selected by MAC80211; `SYSTEM_DATA_VERIFICATION` is selected by
signed cfg80211 regulatory-database support. Their removal is Kconfig's dependency
resolution, not a separate trimming decision. No other effective symbol changed.

## Retention and test evidence

`tests/platform/test_kernel_policy.py` checks the saved config and accepts
`KERNEL_POLICY_CONFIG=/path/to/resolved.config` to check another resolved config.
It locks Wi-Fi off and retains PRU remoteproc, PRUSS/INTC, RPMsg including
`RPMSG_VIRTIO`, virtio/mailbox/SCI dependencies, USB ACM and the USB host stack,
CPSW/MDIO/PHY/DMA, ext4/EROFS/overlay, OSPI/SD, I2C/GPIO/PWM. Greybus and cellular
options are explicitly retained for this increment.

```sh
python3 -m unittest tests.platform.test_kernel_policy -v
```

Evidence from 2026-11-17:

- Before changing the config: four test methods ran; retention passed and Wi-Fi
  failed on eight enabled symbols, as intended.
- After resolution: all four methods passed against both the saved config and the
  independently retained first resolved config.
- Fourteen temporary mutations disabling PRU_REMOTEPROC, TI_PRUSS, TI_PRUSS_INTC,
  RPMSG_VIRTIO, USB_ACM, TI_K3_AM65_CPSW_NUSS, EXT4_FS, EROFS_FS, OVERLAY_FS,
  MMC_SDHCI_AM654, SPI_CADENCE_QUADSPI, I2C_OMAP, GPIO_CDEV and PWM_TIEHRPWM were
  each rejected by the policy tests.
- `test_pru_pwm.nix` and `test_fill_station_ethernet.nix` evaluated successfully
  for their configured variants. This is evaluation evidence, not runtime evidence.

## FIT build status and size baseline

The latest working Liquid baseline was verified locally as **13,537,128 bytes**:
`/nix/store/1d7gkj9131267pcjp9phlrs0x0c9r13b-fill-station-ospi/fitImage.itb`.
`result-ospi-liquid` was left pointing to that output.

Both direct builds below were attempted and **failed before kernel compilation**:

```sh
/nix/var/nix/profiles/default/bin/nix build \
  .#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage \
  --out-link /private/tmp/fill-kernel-trim/ospi-liquid -L
/nix/var/nix/profiles/default/bin/nix build \
  .#mixosConfigurations.fill-station.config.system.build.ospiImage \
  --out-link /private/tmp/fill-kernel-trim/ospi-hybrid -L
```

The existing builder reported source-unpack `Permission denied` errors, beginning
with `arch/arm64/tools/syscall_64.tbl` and
`arch/powerpc/configs/kvm_guest.config`; further symlink entries also failed.
The failed shared kernel derivation was
`/nix/store/2q0pha58iyri98ahc6m3d7hf4ba0gz8q-linux-aarch64-unknown-linux-musl-7.2.15.drv`.
This does not establish a Kconfig or compiler failure. A temporary override that
explicitly set kernel output paths reproduced the unpack failure and was not saved
in the repository. The Kconfig-only helper initially also failed (`xalloc.h` not
found when its source landed under `/lib/modules`); unpacking it in the normal
build directory allowed successful Kconfig resolution. Further investigation isolated the host-backed store behavior: all 62 denied
archive members were symlinks. A direct `ln -s` probe succeeded. Tracing GNU tar
1.35 on one exact member showed its mode-000 placeholder creation failing:

```text
openat(AT_FDCWD, "linux-7.2.15/arch/arm64/tools/syscall_64.tbl",
       O_WRONLY|O_CREAT|O_EXCL, 000) = -1 EACCES (Permission denied)
```

This narrows the failure to tar's placeholder operation on the host-backed store;
it is not a general inability to create symlinks. No global daemon or builder
settings were changed.

Those initial attempts produced no FIT. The successful isolated-store retry and
measured compressed FIT sizes are recorded below; uncompressed module totals
are not used as a savings estimate.
On a successful retry, record both FIT sizes, compare Liquid with the baseline,
and retain the FIT builder's pinmux checks and 58,458,112-byte OSPI slot check.
Shared-worktree changes may also affect a historical FIT comparison; attributing
all byte differences solely to Wi-Fi requires a matched baseline build.

Local investigation artifacts (temporary, not durable project outputs):
`/private/tmp/fill-kernel-trim/resolve.nix`, `resolved/`, `resolve.log`,
`build-liquid.log`, `build-hybrid.log`, `build-workaround.nix` and
`workaround-liquid.log`. No hardware was contacted, flashed or rebooted; no
commits or pushes were made. Board acceptance of this trimmed kernel remains
outstanding after successful builds.

## Isolated Linux-store retry

The retry subsequently completed both OSPI bundles and passed their partition,
pinmux and SHA256 checks. Liquid FIT: **12,949,352 bytes**, versus the unchanged
userspace baseline of 13,537,128 bytes: **587,776 bytes (4.34%) smaller**. Hybrid
FIT: **12,952,704 bytes**. No SD image was built. The derivation comparison recorded
only kernel/module/initrd/FIT changes; the Liquid application derivation was
unchanged from the working baseline.

The checked portable bundles are rooted on the workstation as
`result-ospi-liquid-slim` and `result-ospi-hybrid-slim`. Their content-addressed
local store copies have the same verified files as the original Linux-built
derivation outputs; they were added locally after the host daemon correctly
refused unsigned derivation-output import. No host signature policy was changed.
`result-ospi-liquid` remains the previous hardware-accepted image. Do not call the
trimmed kernel hardware-accepted until its boot, Ethernet, SSH, telemetry and
required peripheral checks pass on the board.

The exact original Liquid and Hybrid OSPI derivations were transferred to Docker,
so the retry uses their original source snapshots and kernel package definition,
not the temporary override. The container uses native ARM64 Linux, image
`nixos/nix:latest` (Nix 2.35.6; image digest
`sha256:b49cb33f3a7e5cf3933ad8774529de0e3807ec5cf54987aa7ccdfb49f2fc55ed`),
container `crt-kernel-trim-20261117`, and ext4 named volume
`crt-kernel-trim-nix-20261117` at `/nix`. The investigation directory is mounted
at `/work`. Other containers and volumes are preserved.

The available host dependency closure was exported into the local file cache
`/private/tmp/fill-kernel-trim/transfer-cache` and imported into the isolated store.
This avoids moving FlakeHub credentials; Docker's direct FlakeHub requests returned
401. The retry passed source unpacking and reported `No change to .config`, then
started kernel compilation. Its log is `docker-build-seeded.log` in the temporary
investigation directory. The container was capped at two CPUs while the parent
ran the station VM checks.

Exact retry command inside the container:

```sh
nix --extra-experimental-features 'nix-command flakes' build \
  '/nix/store/h6yzy4f0nhygx77ldxzjxhay6j9b03si-fill-station-ospi.drv^*' \
  '/nix/store/gmvlki9bf8wgdpylazr5q5a1s5wzgfnw-fill-station-ospi.drv^*' \
  --no-link --cores 2 --max-jobs 1 \
  --option substituters 'file:///work/transfer-cache https://cache.nixos.org' \
  --option require-sigs false -L
```

The signature exception is for locally exported trusted build inputs in this
isolated container. It does not change host daemon settings.
