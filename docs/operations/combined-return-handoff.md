# Combined return-to-hardware handoff

This is one ordered handoff for the source candidate, not evidence of deployment.
The accompanying Git bundle contains source/history and this guide. It contains
**no Linux images, complete offline input closure, runtime credentials or private
keys**. Native build inputs must already be present on the mini PC or prepared
while internet is available. No new SD image is needed for the configured OSPI
board. Keep the working recovery SD and old accepted PC generation.

The first integrated target is Hybrid-test: SV1/SV2, PT1–PT4, LC1/LC2, BV, solenoid
QD and two igniters, all local. Normal Hybrid uses its separate target and FSW
ownership; test it afterwards. Liquid stays on its current mapping.

## 1. Transfer and verify source — Mac / USB

Copy the complete `return-handoff-<revision>` directory to the PC as
`~/return-handoff`. On the **mini PC**, logged in as `ground-admin`:

```sh
cd ~/return-handoff
sha256sum -c SHA256SUMS
git clone --branch kaleb_branch source.bundle "$HOME/ground-platform-return"
cd "$HOME/ground-platform-return"
test "$(git rev-parse HEAD)" = "$(cat "$HOME/return-handoff/SOURCE_REVISION")"
git status --short
```

Use a new checkout directory. Stop at any failed command. The tree should be
clean before enrollment. The bundle avoids Apple tar metadata and preserves the
exact Git revision. Do not use older maintenance/Grafana archives for this update.

## 2. Baseline and SSH — mini PC, then trusted Mac/serial

First check that the current PC still has working displays, cameras, telemetry
and SSH. Record and retain the current system before changing it:

```sh
readlink -f /run/current-system
readlink -f /nix/var/nix/profiles/system
nix-store --add-root "$PWD/accepted-pc-root" --indirect --realise "$(readlink -f /run/current-system)"
sudo test -s /var/lib/ground-station/cache-signing/cache.sec
sudo cat /var/lib/ground-station/cache-signing/cache.pub
sudo crt-check-cache-reads
```

Retain the printed public identity and probe output. Do not regenerate a missing
signing identity or reinitialize camera/database secrets. This handoff targets the
previously accepted cache-only site: if you have since enabled custom worker or
publication modules, preserve those site modules in the build target below rather
than replacing them with the stock cache profile.

Prepare the independently verified board ED25519 **public** host key as
`~/fill-station-host.pub`; match the live board against the trusted Mac/serial
fingerprint. Never copy its private host key. Then on the PC:

```sh
./scripts/platform deploy-ssh-init --host-key "$HOME/fill-station-host.pub" --dry-run
./scripts/platform deploy-ssh-init --host-key "$HOME/fill-station-host.pub"
```

Append only the generated PC public key to the board-only source file:

```sh
key=$(cat "$HOME/.ssh/fill-station-deploy_ed25519.pub")
file=nix/mixos-modules/fill-station-base/deployment_authorized_keys
grep -Fqx -- "$key" "$file" || printf '%s\n' "$key" >> "$file"
git diff -- "$file" > "$HOME/return-handoff/deployment-public-key.patch"
```

This intentional public-key patch makes the checkout dirty; retain it beside the
revision record. Do not add the deployment key to `authorized_keys`: that is the
shared contributor/admin file. Private keys remain on their originating machine.
The new key is not enrolled in the currently running board yet. The first FIT
update uses existing trusted Mac access; subsequent ones can use the PC alone.
If initialization reports an alias/key/pin conflict, inspect it rather than
replacing identities or disabling host checking.

## 3. Build on the mini PC — no activation yet

Keep compilation in an intentional maintenance window, separate from actuation.
Normal worker admission may still be disabled: that is a separate acceptance gate.
First evaluate the exact recipes without compilation:

```sh
pc_drv=$(nix --extra-experimental-features 'nix-command flakes' eval --offline --raw '.#nixosConfigurations.ground-station-um560-cache.config.system.build.toplevel.drvPath')
board_drv=$(nix --extra-experimental-features 'nix-command flakes' eval --offline --raw '.#mixosBuildConfigurations.x86_64-linux.fill-station-hybrid-test.config.system.build.ospiImage.drvPath')
printf '%s\n' "$pc_drv" "$board_drv" > "$HOME/return-handoff/recipes.txt"
```

Both variables must be nonempty `/nix/store/*.drv` paths. If offline inputs are
missing, stop and prepare them while online/on an admitted builder. The source
bundle alone cannot repair missing dependencies. Do not mark the worker validated
or remove daemon admission controls to make a command pass.

For this one-time update, the following is the previously used administrative
**local-store bootstrap**, scoped to these recipes, one job/three cores/6 GiB.
It does not use or enable the normal daemon/remote worker. It clears the hook only
for the explicit local-store invocation, not globally:

```sh
sudo -H systemd-run --scope -p MemoryMax=6G -p MemorySwapMax=0 -p CPUQuota=300% \
  "$(command -v nix)" --extra-experimental-features nix-command build --store local "$pc_drv^*" \
  --offline --option pre-build-hook '' --option substitute false --option substituters '' \
  --option builders '' --max-jobs 1 --cores 3 --out-link "$PWD/result-pc" -L

sudo -H systemd-run --scope -p MemoryMax=6G -p MemorySwapMax=0 -p CPUQuota=300% \
  "$(command -v nix)" --extra-experimental-features nix-command build --store local "$board_drv^*" \
  --offline --option pre-build-hook '' --option substitute false --option substituters '' \
  --option builders '' --max-jobs 1 --cores 3 --out-link "$PWD/result-board" -L

(cd result-board && sha256sum -c SHA256SUMS)
readlink -f result-pc
readlink -f result-board
```

Run each command only after the previous succeeds. This bootstrap produces raw
OSPI files, **not** a platform release manifest or worker/cache publication receipt.
If the normal worker is already admitted, the alternative normal path is
`./scripts/platform build fill-station --vehicle hybrid-test --artifact ospi --build-platform x86_64-linux --builder station`.
Use its real returned manifest for CLI deployment; never invent one for raw files.

## 4. Test-activate the PC first — mini PC

```sh
sudo ./result-pc/bin/switch-to-configuration test
systemctl --failed
systemctl is-active docker-ground-timescaledb docker-ground-emqx docker-ground-grafana
systemctl status ground-telemetry-database --no-pager
sudo crt-check-cache-reads
```

Wait for database/broker reconciliation to succeed. This installs migrations
001–006 and the descriptor/rules before the new producer. If migration or broker
setup fails, stop before flashing. Existing data and signing/camera/database
credentials remain; this is not a reinstall. The activation can restart services
and displays. Use SSH or Ctrl+Alt+F2 to continue; `sudo systemctl start greetd` brings
the operator session up if it is inactive. Retain the old boot default for now.

## 5. First board update — trusted Mac, then mini PC

Copy the complete six-file `result-board` directory to the Mac, for example:

```sh
scp -r ground-admin@192.168.1.206:~/ground-platform-return/result-board ./candidate-ospi
(cd candidate-ospi && shasum -a 256 -c SHA256SUMS)
bash tools/flash-ospi.sh root@192.168.1.106 fit ./candidate-ospi
```

Run the last command from the trusted matching source checkout on the Mac. Use
FIT-only, not `all`; do not alter boot switches, DATA, bootloader/environment or SD
layout. The flash script checks transfer and read-back. Reboot explicitly when
the fixture is ready, using serial or the existing trusted Mac SSH connection.
Then test on the PC, without a forwarded agent:

```sh
ssh -o IdentityAgent=none fillstation-deploy true
```

Repeat after another board reboot. If the new key is absent/rejected, inspect
`/etc/dropbear/authorized_keys` via trusted access: an old DATA overlay may mask
updated lower-layer keys. Preserve existing contributor keys and host pins; do
not erase DATA or copy a private key as a workaround.

## 6. One integrated functional test

- Confirm Ethernet `.106` reaches the PC, Commanding reports `hybrid-test`, and
  telemetry advances. Check the publisher's logged session ID and choose it in
  **Hybrid-test (local only)** from standard Grafana. Both dashboards stay explicit
  about session choice; CSV has a different logger session.
- Check PT1–PT4, LC1, LC2 raw/voltage and validity. Verify IG1/IG2 output intent and
  continuity independently, plus QD release intent/continuity. Unavailable must
  differ from a valid false/zero; none of these prove ignition or mechanical QD
  position. Check a fresh CSV header/row count and schema 3.
- With the operator's test loads/plumbing made ready, test manual SV1/SV2, BV,
  MAV and QD through the unchanged confirmations. Use safe electrical fixtures
  for igniter output/continuity checks. No script in this handoff auto-actuates.
- Check no FSW controls/streams are present in Hybrid-test. Later repeat normal
  Hybrid with its own image/view and actual FSW; disconnect should make remote
  data unavailable while local data continues.
- Reboot both systems, check persistent SSH, live telemetry/video, two monitors
  and one-monitor fallback. With WAN absent, test local operation and LAN time;
  LAN clock agreement is not externally verified UTC.
- Verify the actual CSV mount/free space/retention before relying on recordings.
  The pinned MixOS init binds `/state/var` onto `/var`; the new logger checks that
  mapping and stops rather than silently recording to tmpfs. Verify a short CSV
  remains after reboot. DATA needs 32 MiB/128 inodes in reserve and each recording
  stops at 128 MiB; there is no automatic pruning/rotation or UI recording alarm.
  See [recording limits](../../fill-station/docs/CSV_LOGGING.md). Test low-space
  behavior only on a disposable fixture, never by filling the production card.

Keep this read-only signed-cache check for the newly built artifact, if desired:
on the PC sign that exact output recursively with the existing root-owned key,
then fetch through `/cache/` on the Mac with require-sigs and the already verified
public key, and check SHA256SUMS as in [cache acceptance](mac-station-cache.md).
That proves signed reading of this output, not the normal publication/worker path.

## 7. Commit the tested PC generation to boot, then cleanup

Only after the integrated checks pass:

```sh
candidate=$(readlink -f result-pc)
sudo nix-env --profile /nix/var/nix/profiles/system --set "$candidate"
sudo "$candidate/bin/switch-to-configuration" boot
```

Reboot explicitly and verify the same current-system path and displays. Preserve
one known-good PC generation, board recovery SD/FIT, source bundle, public-key
patch and checksums. No broad generation/cache/data cleanup until this is accepted.
If PC test activation fails, test-switch back with
`sudo ./accepted-pc-root/bin/switch-to-configuration test`.
Board FIT rollback requires a separately verified known-good image and trusted
access/recovery; it is not automatic A/B rollback.

The independent remaining gates are real worker/publication-account enrollment,
normal daemon containment/admission, interrupted-transfer/GC/outage acceptance
and network-device integrations. See [worker enrollment](worker-cache-enrollment.md)
and the cumulative [return checklist](ground-station-return-testing.md). This
handoff does not silently enable worker/admin roles or mark those gates passed.
