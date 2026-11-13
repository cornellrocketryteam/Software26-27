# Offline UM560 services update

The working `ground-station-um560` target stays a UI/SSH foundation. The separate
`ground-station-um560-services` target adds TimescaleDB, EMQX and Grafana, with
prepared local image archives and private runtime credentials. It does not enable
kiosk, commanding, cache or build-worker admission. `/readyz` remains 503.

## Pinned compatibility baseline

The deployment pins are in
[`telemetry-images.json`](../../nix/nixos-configurations/ground-station/telemetry-images.json).
They identify Linux/amd64 manifests and verified Nix archive hashes:

| Service | Baseline |
| --- | --- |
| TimescaleDB | 2.24.0, PostgreSQL 17.7 |
| EMQX | 6.0.0 (`e6.0.0` in the status API), included single-node Community license |
| Grafana | 12.3.1, `grafana/grafana` OSS image |

These match the legacy application's versions; they are not a claim to be the
latest releases. Upgrades require a compatibility review and explicit digest changes. EMQX 5.8 disposable Enterprise test images are not used
by this deployment. EMQX documents its single-node production grant in the
[licensing FAQ](https://www.emqx.com/en/content/license-faq); the tested 6.0 image
reported `type=community` and `expiry=false`, without an external trial key.

The profile uses the confirmed Ethernet MAC and
`http://192.168.1.206:8080/grafana/`. Reserve this address on the router, or change
`services.nix` and rebuild for the actual address before deployment. The database
and management ports stay loopback-only; MQTT port 1883 is scoped to `lan0`.

## Prepare the complete update while online

On a Linux Nix build host, from the repository:

```sh
nix build .#nixosConfigurations.ground-station-um560-services.config.system.build.toplevel -o result-ground-services
mkdir -p result-ground-telemetry-files/bundle/cache
readlink -f result-ground-services > result-ground-telemetry-files/bundle/system-path
nix copy --to "file://$PWD/result-ground-telemetry-files/bundle/cache" "$(cat result-ground-telemetry-files/bundle/system-path)"
cp docs/operations/ground-station-update.md result-ground-telemetry-files/bundle/README.md
tar -C result-ground-telemetry-files/bundle -cf result-ground-telemetry-files/ground-station-telemetry-update.tar .
(cd result-ground-telemetry-files && sha256sum ground-station-telemetry-update.tar > SHA256SUMS)
```

The complete runtime closure includes the three OCI archives. This prepares an
update without field downloads or compilation; it does not prepare arbitrary
offline source rebuilds. No real credentials are generated during the build.

On the Apple-silicon Mac with the case-insensitive Nix-store limitation, use the
same pinned Docker bootstrap as the [installer guide](ground-station-install.md).
From a regular checkout, with Docker Desktop running:

```sh
mkdir -p result-ground-telemetry-files
docker run --rm --platform linux/amd64 \
  --volume crt-ground-nix:/nix \
  --volume "$PWD:/work:ro" \
  --volume "$PWD/result-ground-telemetry-files:/artifacts" \
  --workdir /work --entrypoint /bin/sh \
  nixos/nix@sha256:b49cb33f3a7e5cf3933ad8774529de0e3807ec5cf54987aa7ccdfb49f2fc55ed \
  -ec '
    git config --global --add safe.directory /work
    nix --extra-experimental-features "nix-command flakes" build \
      "git+file:///work#nixosConfigurations.ground-station-um560-services.config.system.build.toplevel" \
      --out-link /tmp/services --print-build-logs \
      --option sandbox false --option filter-syscalls false \
      --option substituters https://cache.nixos.org
    mkdir -p /tmp/update/cache
    readlink -f /tmp/services > /tmp/update/system-path
    nix --extra-experimental-features nix-command copy \
      --to file:///tmp/update/cache "$(cat /tmp/update/system-path)"
    cp /work/docs/operations/ground-station-update.md /tmp/update/README.md
    tar -C /tmp/update -cf /artifacts/ground-station-telemetry-update.tar .
    cd /artifacts
    sha256sum ground-station-telemetry-update.tar > SHA256SUMS
  '
```

Keep the Linux volume for subsequent builds. The Docker fallback does not use
FlakeHub login, and changes no host Nix settings. The emitted archive is for the
x86 UM560, not an ARM station.

## Transfer without reflashing the SSD

The mini PC does not need to be reinstalled. When the laptop and station are on
the same LAN, copy the prepared archive and checksum file:

```sh
scp result-ground-telemetry-files/ground-station-telemetry-update.tar \
  result-ground-telemetry-files/SHA256SUMS ground-admin@192.168.1.206:~/
```

A separate USB data drive is an alternative. Keep the installer USB available
for recovery. This guide assumes the operator runs commands on the station; it
does not automatically connect to, reboot or activate any physical machine.

On the mini PC, from the directory containing the transferred files:

```sh
sha256sum -c SHA256SUMS
mkdir -p ground-station-update
tar -xf ground-station-telemetry-update.tar -C ground-station-update
cd ground-station-update
system=$(cat system-path)
sudo nix --extra-experimental-features nix-command copy --offline --no-check-sigs \
  --from "file://$PWD/cache" "$system"
```

Stop on any checksum/import error. The local import accepts unsigned developer
outputs from this explicitly trusted, checksum-verified bundle; it does not alter
global signature trust or the future signed-cache policy. NAR hashes still verify
the imported content.

## Initialize private credentials once

Before first activation:

```sh
sudo "$system/sw/bin/ground-telemetry" init-secrets \
  --secrets-file /var/lib/ground-station/telemetry-secrets.json
```

This generates independent random values in a root-owned mode-0600 file. It
refuses an existing file, symlink destination or unsafe parent directory and
prints no values. It is not a rotation command: on later updates, keep the valid
existing file and skip initialization. The foundation already creates the parent
directory. The passwords and broker cookie never enter the Nix store or bundle.

## Test before changing the boot default

```sh
sudo "$system/bin/switch-to-configuration" test
```

This changes the running system but leaves the current boot profile pointing at
the working foundation. Keep your console/SSH connection available. The first
start loads local images and initializes fresh service data in
`/var/lib/ground-station/telemetry`; it may take several minutes. Missing private
credentials cause bounded background retries rather than holding up UI/SSH boot.

Check one command at a time, allowing startup to finish:

```sh
systemctl is-active ground-telemetry-prepare ground-telemetry-database ground-telemetry-broker
systemctl is-active docker-ground-timescaledb docker-ground-emqx docker-ground-grafana
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/grafana/api/health
```

From the laptop, open `http://192.168.1.206:8080/grafana/` and the UI at port
8080. Grafana permits anonymous Viewer access; it queries with a dedicated
read-only database role. Real fill-station telemetry is a separate check from
container health and should be verified before treating ingestion as accepted.
Readiness 503 is still expected while commanding/field acceptance is incomplete.

If the test fails, do not commit the new boot profile. Rebooting returns to the
previous foundation. Runtime service data is separate from the NixOS generation;
changing a generation does not undo database writes or schema changes.

## Make the tested generation persistent

Only after the checks succeed:

```sh
sudo nix-env --profile /nix/var/nix/profiles/system --set "$system" \
  --option substitute false --option substituters '' --option builders ''
sudo "$system/bin/switch-to-configuration" boot
sudo reboot
```

Then check SSH/UI, the three services and Grafana again with WAN absent. The
previous foundation generation remains available in the UEFI boot menu. New
credentials and service state persist across reboots; operational backup and
retention remain separate work.

## Repeat the deployment-image VM test

The older default VM test still uses disposable EMQX 5.8 fixtures. To exercise
these exact deployment pins on the current host (with a suitable Linux builder
for guest derivations):

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = builtins.currentSystem; }; in import ./tests/platform/test_telemetry_vm.nix { inherit pkgs; imagePinsFile = ./nix/nixos-configurations/ground-station/telemetry-images.json; expectedEmqxVersion = "e6.0.0"; }' -L
```

This test uses a full x86 guest with no network adapter, private fixture credentials
and synthetic packets. The native-ARM broker Docker test is useful for API
compatibility, but does not replace this check of the amd64 image and NixOS units.
No test contacts the physical mini PC or fill-station hardware.

Validated for this pinned baseline: 224 configuration contracts, 23 runtime tests
(including credential initialization), mixed-platform API/ingestion/restart
acceptance, and the full x86 NixOS VM test. The x86 guest passed missing-credential
recovery, a forced initial migration failure, three container SIGKILL recoveries,
a NIC-free cold reboot with unchanged credentials and persisted rows, and a final
batch ending with 21 correct rows without duplicates. The Grafana probe also ran
successfully; no command listener was enabled. This is VM/software evidence, not
physical mini-PC telemetry acceptance.
