# Retain the accepted ground-station system

Commanding, recovery and restored Grafana are operator-accepted. The final PC boot
default is not yet verified. The operator is away from the PC; hardware steps below
are queued for a single integrated test when access returns. No PC changes or key
enrollment have been performed remotely.

## 1. Confirm and retain the exact running generation

On the mini PC, inspect:

```sh
readlink -f /run/current-system
readlink -f ~/ground-station-grafana-restore/result-test-stand
readlink -f /nix/var/nix/profiles/system
```

The first two must match. If they do not, stop rather than retaining an untested
system. Then use this guarded block:

```sh
accepted=$(readlink -f /run/current-system)
expected=$(readlink -f "$HOME/ground-station-grafana-restore/result-test-stand")
if [ -n "$accepted" ] && [ "$accepted" = "$expected" ]; then
  mkdir -p "$HOME/.local/state/cornell-rocketry"
  readlink -f /nix/var/nix/profiles/system > "$HOME/.local/state/cornell-rocketry/previous-boot-system"
  sudo nix-env --profile /nix/var/nix/profiles/system --set "$accepted" &&
    sudo "$accepted/bin/switch-to-configuration" boot
else
  echo 'System mismatch; no boot default changed'
fi
```

Do not run a broad generation cleanup. Reboot explicitly when ready and verify
the same current-system path, automatic displays, camera playback, fresh telemetry,
connected Commanding and signed-cache identity/reads with WAN absent. Retain one
previous known-good boot generation and recovery board media.

## 2. Dedicated board deployment identity (queued, not enrolled)

The source CLI now prepares this locally. First place the independently verified
board ED25519 public host key in `~/fill-station-host.pub` (one plain
`ssh-ed25519 AAAA...` line). Verify its fingerprint against serial-console or
another already trusted source; a fresh unverified `ssh-keyscan` is insufficient.
Then, as `ground-admin` on the mini PC, run:

```sh
crt-platform deploy-ssh-init --host-key "$HOME/fill-station-host.pub" --dry-run
crt-platform deploy-ssh-init --host-key "$HOME/fill-station-host.pub"
```

From a source checkout, replace `crt-platform` with `./scripts/platform`.
This generates/reuses `~/.ssh/fill-station-deploy_ed25519`, prints only its public
key, and configures `fillstation-deploy` with a dedicated host-key file. No board
connection, enrollment, flash or reboot occurs. It preserves other SSH settings,
disables agent use/forwarding for this alias, and refuses an unmanaged alias,
symlinked configuration or changed existing host pin. Inspect conflicts manually;
do not delete identities or host pins just to bypass an error. Run without sudo.

Include the returned `publicKey` alongside existing contributor keys in
`nix/mixos-modules/fill-station-base/authorized_keys`. The private key stays on
the PC. Build/review the enrollment FIT, then perform one update using existing
Mac recovery/forwarded access. After explicit board reboot, test independently:

```sh
ssh -o IdentityAgent=none fillstation-deploy true
```

Subsequent explicit deployments can use:

```sh
crt-platform deploy --manifest "$manifest" --target fillstation-deploy --dry-run
crt-platform deploy --manifest "$manifest" --target fillstation-deploy
```

Set `$manifest` to the exact verified platform-build manifest; this does not apply
to older raw OSPI archives. Reboot remains an explicit separate operator action.

Acceptance requires a fresh PC session without a forwarded agent, then a board
reboot and another successful connection. The existing Mac recovery key remains
valid. This runbook is not evidence that the key has already been generated or
enrolled. The final integrated test will cover deployment once the software
pieces are ready.

## Cleanup status

On November 21, the Mac's superseded test-stand and UI-restoration transfer tar
files were removed only after every cached file was verified identical in the
retained accepted Grafana restoration bundle. About 182 MB was reclaimed. Original
cross-build/cache/maintenance input archives, recovery files, the Nix store and
registered roots were left intact. See `reports/ground-station-cleanup-2026-11-21.json`.
PC cleanup and store GC remain pending persistence and retention acceptance.
