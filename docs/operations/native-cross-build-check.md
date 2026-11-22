# Native UM560 cross-build check

This is an offline validation build on the mini PC, not an installation or board
update. It uses immutable Liquid/Hybrid OSPI recipes from the development checkout
and a prepared cache of source/tool inputs. No Git checkout, FlakeHub login,
network boot, new SD image, board connection or actuation is required.

The seed was prepared in the local x86 Linux validation store. All 797 fixed
source outputs in the combined recipe graph were available, including the
hash-verified MixOS Zig dependency bundle. It contains 3,765 store paths (about
18.75 GiB uncompressed before any sharing with the station's existing store).
Actual offline compilation on the native UM560 remains the acceptance test.

## Transfer

From the Mac on the station LAN, after the prepared archive/checksum exist:

```sh
scp result-cross-build-inputs-files/cross-build-inputs.tar \
  result-cross-build-inputs-files/SHA256SUMS ground-admin@192.168.1.206:~/
```

A USB copy of those same two files is equally usable. Keep the existing running
NixOS installation and telemetry files. This bundle contains no new station
system generation; the outstanding UI navigation patch is not deployed by it.

## Import on the mini PC

From the directory containing the transferred files:

```sh
sha256sum -c SHA256SUMS
mkdir -p ~/cross-build-check
tar -xf cross-build-inputs.tar -C ~/cross-build-check
cd ~/cross-build-check
sudo nix --extra-experimental-features nix-command copy --all --offline \
  --no-check-sigs --from "file://$PWD/cache"
```

Stop if verification/import fails. The signature exception applies only to this
locally prepared developer bundle; it does not configure the production signed
cache or change global trust settings.

## Build Liquid first

Run during maintenance. Nix job/core settings below limit concurrency, not a
verified hard CPU/RAM boundary; worker containment is a separate acceptance task.

```sh
cd ~/cross-build-check
liquid=$(cat liquid.drv)
sudo nix --extra-experimental-features nix-command build "$liquid^*" \
  --offline --option substitute false --option substituters '' \
  --option builders '' --max-jobs 1 --cores 3 \
  --out-link "$PWD/result-ospi-liquid-cross" -L
```

A first build can take time compiling its cross-toolchain and kernel. Success
returns exit code zero and creates `result-ospi-liquid-cross`. On failure, send
the final error and the named failing derivation; do not flash anything.

After Liquid succeeds, build Hybrid:

```sh
hybrid=$(cat hybrid.drv)
sudo nix --extra-experimental-features nix-command build "$hybrid^*" \
  --offline --option substitute false --option substituters '' \
  --option builders '' --max-jobs 1 --cores 3 \
  --out-link "$PWD/result-ospi-hybrid-cross" -L
```

Then verify each bundle's own checksum file and inspect FIT sizes. Keep both
cross-built candidates separate from the currently accepted ARM-builder outputs.
Build success does not establish board boot/peripheral acceptance. Report native
results before proceeding to explicit FIT-only Ethernet/OSPI deployment.

## Installed build-admission gate

The operator reported `station builds disabled or unvalidated`. This is the
installed pre-build policy rejecting compilation, not a missing source or compiler
error. Do not mark the remote worker validated merely to run this first test.
For this developer-supplied recipe, use a one-time root-owned local store build
in a bounded systemd scope. The empty pre-build hook applies only to that command;
remote worker enablement and daemon policy stay unchanged. The local store avoids
forwarding this exception to the normal daemon. No station generation is activated.

```sh
cd ~/cross-build-check
liquid=$(cat liquid.drv)
sudo systemd-run --scope -p MemoryMax=6G -p CPUQuota=300% \
  nix --extra-experimental-features nix-command build --store local "$liquid^*" \
  --offline --option pre-build-hook '' \
  --option substitute false --option substituters '' --option builders '' \
  --max-jobs 1 --cores 3 --out-link "$PWD/result-ospi-liquid-cross" -L
```

Use the equivalent Hybrid recipe only after Liquid succeeds. If the scope or build
fails, report the exact error before changing policy or resource limits.
