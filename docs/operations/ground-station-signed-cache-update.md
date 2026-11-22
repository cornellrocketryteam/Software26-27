# Signed cache read rollout

The operator confirmed the maintenance generation's native build, real-daemon
probe, display/navigation checks and persistence across reboot on November 20.
That establishes the fixed daemon smoke check, not remote-worker acceptance.

This next generation adds a read-only signed cache. Field mode is enabled;
ordinary builds, remote builds and the privileged upload account stay disabled.
It keeps the accepted telemetry, cameras and local displays. The LAN endpoint is
`http://192.168.1.206:8080/cache/`; Harmonia binds only to `127.0.0.1:5000`.

## Transfer and build

On the Mac, from the repository while connected to the station LAN:

```sh
scp result-ground-cache-files/ground-station-signed-cache-inputs.tar \
  result-ground-cache-files/SHA256SUMS \
  ground-admin@192.168.1.206:~/
```

On the mini PC, run these one at a time, stopping on any failure:

```sh
cd ~
sha256sum -c SHA256SUMS
mkdir ground-station-signed-cache
tar -xf ground-station-signed-cache-inputs.tar -C ground-station-signed-cache
cd ground-station-signed-cache
bash import-inputs.sh
bash build-cache.sh
bash test-cache.sh
```

This is a frozen input bundle, not a prebuilt closure. The UM560 builds the
remaining configuration/helpers natively with one job, three cores, 6GiB memory
and no swap. Large dependencies and source downloads are bundled. No WAN is
required and Docker/emulation on the Mac is unnecessary. The local-store
admission exception is command-scoped; the normal daemon remains gated.

The archive has no Apple extended metadata. Niceness is applied to the caller
with `nice -n 10`, not an unsupported scope `Nice=` property.

## What the test does

Before activation, `test-cache.sh` runs the new generation's fixed root-only
`crt-provision-cache-key` helper. It generates `crt-ground-station-1` on the PC
in `/var/lib/ground-station/cache-signing`. The directory is mode 0700 and the
secret `cache.sec` is mode 0600. Existing keys are checked and preserved;
mismatches fail instead of rotating the signing identity. A missing public file
can be derived from an existing valid secret. Do not delete a key to retry.

The private key never enters the bundle, Git, a Nix expression or the Mac.
Only `cache-public-identity.json` is printed/saved. Harmonia uses systemd
`LoadCredential`, keeping the original secret inaccessible to its dynamic user.
The daemon is configured to sign future builds with the same key. This does not
retroactively sign the earlier maintenance-built OSPI paths for SSH export.

The script test-activates the generation, starts the cache socket and runs
`crt-check-cache-reads`. It uses three new disposable local stores with builds
disabled, signatures required and explicit client trust. It verifies a complete
artifact/dependency download with the station key, and requires unrelated-key
and corrupted-signature downloads to fail specifically because of signatures.
Content-addressed fixtures are rejected because they would not prove signature
enforcement. No global trust settings or host GC state are changed.

Success saves `cache-read-validation.json` and `cache-fixture-path`. Keep those
and `cache-public-identity.json`. Check existing SSH, advancing telemetry,
cameras and both display layouts. Use Ctrl+Alt+F1 to return to the display or
`sudo systemctl restart greetd` if needed.

## Recovery and remaining acceptance

The test does not change the boot default. Reboot returns to the accepted
maintenance generation, or restore it immediately from the bundle directory:

```sh
previous=$(cat previous-system)
sudo "$previous/bin/switch-to-configuration" test
```

Do not set the cache generation as the boot default yet. First report the check
output. Next, copy only the public identity and fixture information through the
already verified SSH connection, test a no-compilation LAN fetch on the Mac,
and add the public key alongside existing official trust. Prove cache outage and
reboot recovery, then deliberately sign/export selected existing OSPI closures.
These are pending physical checks, separate from local source tests.

An unavailable cache must not interrupt telemetry or local operation. No upload
account, worker validation flag or remote execution is enabled by these scripts.

## Operator acceptance recorded November 20

The cache generation was built, activated and made persistent. Station-local
fresh-store checks passed with correct public trust and rejected unrelated and
corrupted signatures. The Mac fetched the fixture and dependency over the LAN
with command-scoped trust and verified both payloads. After reboot the same
public identity passed all checks again. During a deliberate stop of both
Harmonia units, telemetry, cameras and UI remained working; restarting the cache
restored all three signature checks. These are operator-reported physical results;
no tool connection to the LAN was used.

The earlier test-only boot guidance above describes initial installation. The
operator has since made this tested cache generation the boot default. Keep its
previous accepted generation available for recovery. Persistent Mac trust/cache
configuration, real OSPI retrieval and underlying store-path signing for SSH
export are still pending. No worker/upload account is enabled.
