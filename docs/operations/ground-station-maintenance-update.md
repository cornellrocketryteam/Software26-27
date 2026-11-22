# Offline maintenance update

This prepares the station for daemon validation. It does not enable the signed
cache or remote worker. The bundle contains frozen build inputs, not a completed
system closure; the UM560 performs the remaining native assembly. No Docker or
Linux emulation is required on the Mac.

## Transfer

From the repository on the Mac, while connected to the station LAN:

```sh
scp result-ground-maintenance-files/ground-station-maintenance-inputs.tar \
  result-ground-maintenance-files/SHA256SUMS \
  ground-admin@192.168.1.206:~/
```

Use a USB drive instead if needed. Both files must reach the same directory.
Do not transfer or replace any camera/telemetry credentials for this update.

## Build and test on the mini PC

In the mini PC terminal:

```sh
cd ~
sha256sum -c SHA256SUMS
mkdir ground-station-maintenance
tar -xf ground-station-maintenance-inputs.tar -C ground-station-maintenance
cd ground-station-maintenance
bash import-inputs.sh
bash build-maintenance.sh
bash test-maintenance.sh
```

Run each command only after the previous command succeeds. Use a fresh extraction
directory. The import verifies every file and roots the frozen recipe. The native
build uses the previously accepted local-store bootstrap in a bounded scope:
one job, three cores, 6GiB memory and no swap. The exception does not change the
normal daemon's admission policy. No WAN access is required.

The test script activates the generation temporarily, then runs the fixed probe
against the real Nix daemon. It saves `daemon-validation.json`. The boot default
is unchanged. Activation may restart affected services and the graphical session;
use SSH or Ctrl+Alt+F2 and log in as `ground-admin` to continue.

Send the probe output, or the last error if any step fails. A passing probe must
report `rebuilt: true` and `workerValidationChanged: false`. It proves a fixed
unprivileged recipe ran inside the daemon's bounded cgroup; it does not certify
the complete remote worker or signed cache.

Check SSH, advancing telemetry, live cameras, dual-monitor startup and single
monitor tabs. Select **Station views** from Commanding, then return to Commanding
to verify the navigation correction. Valve actuation remains deferred.

## Recovery and persistence

Reboot restores the prior boot configuration after a test-only activation.
To restore the previous running configuration without reboot:

```sh
previous=$(cat previous-system)
sudo "$previous/bin/switch-to-configuration" test
```

After the probe and operator checks pass, the bundle's `README.md` contains the
commands to retain the maintenance generation across reboot. Field mode is off
in that generation; restore the normal services/field-mode profile before field
operation. Normal and remote builds remain disabled throughout this step.

The bundle records the exact derivation, expected system path, dirty checkout
inventory and input verification. The source/profile evaluations and host tests
have passed; native build and physical acceptance remain pending until run here.
Keep the bundle, result link and recipe root until the rollout is accepted.

## November 20 compatibility correction

The first archive included Apple provenance metadata. GNU tar reports unknown
extended-header warnings while ignoring that metadata; archive checksums and
`CONTENTS.sha256` still check the actual files.

The first build script also incorrectly supplied `Nice=10` as a scope property.
For an already extracted original bundle, preserve its checksummed script and
create a corrected copy in the same directory:

```sh
sed 's/-p Nice=10 //g' build-maintenance.sh > build-maintenance-fixed.sh
bash build-maintenance-fixed.sh
```

All CPU, memory, swap and task bounds remain. After success, run
`bash test-maintenance.sh`. Newly prepared bundles apply niceness to the caller
with `nice -n 10`, retain the scope resource limits, and omit Apple metadata.
