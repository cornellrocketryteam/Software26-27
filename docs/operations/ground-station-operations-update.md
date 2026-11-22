# Apply the monitor and camera update offline

This updates the existing NixOS installation. Keep the SSD, current telemetry
data/secrets and boot setup in place. No installer USB or fresh OS installation
is needed. This revised update opens Grafana with telemetry and cameras on one monitor and
the commanding UI on the other. One monitor uses Grafana/Commanding tabs at
`/station/`. It supersedes the earlier telemetry/camera split archive.

## Transfer from the Mac on the station LAN

```sh
scp result-ground-operations-files/ground-station-operations-update.tar \
  result-ground-operations-files/SHA256SUMS \
  /Users/ronit/.config/cornell-rocketry/ground-station/camera-relay-credentials.json \
  ground-admin@192.168.1.206:~/
```

The private camera file is separate from the public system archive. Do not
replace `/var/lib/ground-station/telemetry-secrets.json` or rerun its initializer.

## Import on the mini PC

Run in the mini PC's console, or SSH when switching the laptop network will not
interrupt your session. Start in the directory containing the transferred files:

```sh
sha256sum -c SHA256SUMS
mkdir -p ground-station-operations-update
tar -xf ground-station-operations-update.tar -C ground-station-operations-update
cd ground-station-operations-update
system=$(cat system-path)
sudo nix --extra-experimental-features nix-command copy --offline --no-check-sigs \
  --from "file://$PWD/cache" "$system"
```

Stop if checksum or import fails. This is a command-scoped import of the prepared
developer bundle, not a global signature-policy change or a signed-cache rollout.

Install the private camera file from the home directory:

```sh
sudo install -d -m 0700 /var/lib/ground-station/cameras
sudo install -m 0600 ~/camera-relay-credentials.json \
  /var/lib/ground-station/cameras/credentials.json
rm ~/camera-relay-credentials.json
```

## Test the running system first

Attach the monitor(s), keyboard and mouse, then run:

```sh
sudo "$system/bin/switch-to-configuration" test
```

The local graphical session replaces tty1. **Ctrl+Alt+F2** opens another console;
log in there as `ground-admin` if you need to continue typing. SSH remains
available. From that console, check:

```sh
systemctl is-active greetd ground-station-cameras
curl --fail http://127.0.0.1:8080/grafana/api/health
```

Confirm the following before setting the boot default:

- Two monitors: Grafana with telemetry/cameras on one, commanding on the other.
- One monitor: both views accessible through tabs without reloading commanding.
- Advancing fill-station telemetry and the actual camera scenes, not just pages.
- Existing SSH and all telemetry services still work.
- Unplugging/reconnecting one display produces the single/dual layout again.

If outputs are reversed, see [output mapping and recovery](ground-station-display.md).
If the camera page opens but video fails, use [camera troubleshooting](ground-station-cameras.md).
Physical camera credentials/codecs and the UM560 display hardware still need
these checks even though synthetic playback and software contracts passed.

## Make the tested system persistent

From the same shell where `system` is set:

```sh
sudo nix-env --profile /nix/var/nix/profiles/system --set "$system" \
  --option substitute false --option substituters '' --option builders ''
sudo "$system/bin/switch-to-configuration" boot
sudo reboot
```

Verify local monitor startup, camera playback, telemetry and SSH again after
reboot, with WAN disconnected. The previous NixOS boot generation remains the
recovery route. The separate slim fill-station OSPI bundles are not installed by
this update; test them as a distinct board change.
