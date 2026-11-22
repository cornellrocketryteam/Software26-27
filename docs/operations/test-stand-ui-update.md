> The redesigned commanding page in this bundle was rejected. For the corrected PC UI and explicit WebSocket endpoint, use [the UI restoration update](commanding-ui-restore.md). The Hybrid solenoid-QD FIT remains current; do not reflash it solely for this PC correction.

# Solenoid QD and manual test-stand update

This supersedes the earlier two-control UI bundle. The setup is **SV1, BV and
QD on the SV5 connector**, with **PT1/PT2 on ADC1 CH0/CH1, 0–1500 PSI**.
There is no automated fill, pressure-driven sequence or timed vent. `/propulsion`
opens the same manual page as `/` and `/test-stand`; Recovery stays separate.

Kaleb's `QuickDisconnect = SolenoidValve` alias was already merged in `cc14688`.
Hybrid had still selected the stepper. The updated profile now creates a distinct
`quick_disconnect` device at SV5's existing GPIO1_48 control/GPIO1_46 sense pins.
Normally-closed/active-high release is enforced. The old stepper driver, motor
commands and active configuration are removed; role bits 0–10 stay unchanged,
QD uses SV5 bit 8, and former motor bit 11 is unused.

**Release QD** energizes the output. **Output off** de-energizes it; neither
command proves mechanical release or reconnection. Reports show command memory
and continuity, not position. No pulse timing or reconnect actuation is added.

## Incremental bundle prerequisites

The updated archive contains new recipes and sources for **both** the mini-PC
system and the **Hybrid OSPI image**. It is not a completed image or a fully
self-contained bootstrap. It reuses the cross-build and signed-cache inputs
already imported on this mini PC. Its import script verifies every required
old store path before allowing the build. If inputs were garbage-collected,
stop and restore the original cross-build/cache bundles; no WAN download is
silently attempted. See [original native inputs](native-cross-build-check.md).

Full Rust compilation remains pending: offline Cargo on the Mac lacked a cached
dependency. The native Hybrid build below is required before any board flashing.
Hardware/compiler/client tests, Rust syntax parsing, 30 UI tests, production
build/lint and both mocked browser suites passed. These do not prove actuation.

## Transfer from Mac

On the station LAN, from the repository:

```sh
scp result-ground-test-stand-files/ground-station-test-stand-inputs.tar \
  result-ground-test-stand-files/SHA256SUMS \
  ground-admin@192.168.1.206:~/
```

Use a fresh extraction directory so an earlier UI bundle cannot get mixed in.
On the mini PC, over SSH or its terminal, run each command only after success:

```sh
cd ~
sha256sum -c SHA256SUMS
mkdir ground-station-qd-update
tar -xf ground-station-test-stand-inputs.tar -C ground-station-qd-update
cd ground-station-qd-update
bash import-inputs.sh
bash build-hybrid.sh
bash build-ui.sh
```

Keep the SSH session connected during builds, or use the mini PC terminal.

The builds use the already accepted bounded local-store bootstrap: one job,
three cores, 6GiB and no swap. Normal/remote worker and upload accounts remain
disabled. The Hybrid build checks all four OSPI checksums and prints FIT size.
Nothing has been flashed, rebooted or activated by these commands.

## Apply the built Hybrid FIT

The updated PC UI uses the compatible SV5 command messages. However, retiring
the stepper from the **running board** requires the newly built Hybrid FIT,
not just a browser update. Use the already tested SSH/key and flash-script setup
from the earlier cross-build deployment:

```sh
bash ~/flash-ospi.sh root@192.168.1.106 fit "$PWD/result-ospi-hybrid-qd"
```

Stop on any checksum, capacity, SSH or read-back failure. This command updates
only FIT, not the bootloader or DATA card. After success, reboot the board:

```sh
ssh root@192.168.1.106 reboot
```

Confirm wired SSH and advancing telemetry return before proceeding. If the
flash script or established SSH authentication is unavailable, stop and report
that error rather than changing host-key policy or copying private keys.

## Test the PC generation

During maintenance with no active actuation:

```sh
bash test-ui.sh
```

It test-activates the PC generation, restarts greetd to reload the pages, checks
UI/Grafana health and signed cache reads. The display restarts; SSH remains
available. Ctrl+Alt+F2 opens a console and Ctrl+Alt+F1 returns to the display.
Signing keys, camera credentials and database state are preserved; no signing
key is generated or rotated. The PC boot default is unchanged.

Without actuating, verify SV1/BV/QD controls, initial locking, advancing PT1/PT2
PSI readings, fresh reports, cameras, dual/single monitor layouts and Station
views navigation. Disconnect/reconnect must relock and never replay a command.
Physical actuation is a separate operator test; do not click a release/open
confirmation merely to test rendering.

The existing MQTT schema covers SV1/BV/PT1/PT2. QD is read directly from SV5
WebSocket reports; no new QD history field was invented. Legacy integer
`qd_state` is always unknown and is never used as solenoid feedback. CSV records
the QD through existing SV5 columns; old motor columns are N/A.

## PC recovery

Reboot returns to the previous accepted cache generation. To restore it without
reboot, from this extracted update directory:

```sh
previous=$(cat previous-system)
sudo "$previous/bin/switch-to-configuration" test
```

Keep previous recovery images and both new result links/recipe roots until
acceptance. Report build and display/data results before retaining a new PC boot
default. No SD image is needed for this update. Details: [QD driver/protocol](../../fill-station/docs/QD_SOLENOID.md)
and [commanding UI](../../Ground_Station_UI/TEST_STAND.md).
