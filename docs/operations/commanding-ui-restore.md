# Restore the original commanding UI

This ground-station-only correction restores the original React/TypeScript
landing/propulsion/recovery layout, manual card controls and on-rocket section.
Automated fill and its coupled timed-vent components remain removed. QD retains
the current solenoid release/output-off behavior on SV5. The already flashed
Hybrid image does not need to be reflashed for this correction.

The UM560 services profile previously left the browser WebSocket endpoint null.
It now explicitly sets `ws://192.168.1.106:9000`. Confirm the live discrepancy with:

```sh
curl --fail --silent http://127.0.0.1:8080/station-config.json
```

If the old generation already serves a non-null address, keep that output and
inspect the browser WebSocket error; this configuration omission alone does not
establish the live failure. MQTT/Grafana and commanding are separate connections.

## Transfer and build

On the Mac, connected to the station LAN:

```sh
cd /Users/ronit/Software26-27
scp result-ground-ui-restore-files/ground-station-ui-restore-inputs.tar \
  result-ground-ui-restore-files/SHA256SUMS ground-admin@192.168.1.206:~/
ssh ground-admin@192.168.1.206
```

On the mini PC, use a fresh directory and stop on any error:

```sh
cd ~
sha256sum -c SHA256SUMS
mkdir ground-station-ui-restore
tar -xf ground-station-ui-restore-inputs.tar -C ground-station-ui-restore
cd ground-station-ui-restore
bash import-inputs.sh
bash build-ui.sh
bash test-ui.sh
```

Keep SSH connected during the build, or use the PC console. This incremental
archive needs the previously imported cross-build/cache inputs; import verifies
required paths and fails if they are absent. No WAN, Docker, board write or
private-key transfer is performed. The normal remote worker remains disabled.

Test activation reloads the displays. Check the served station-config JSON,
then open Propulsion and confirm the banner says connected. The normal landing
page and Recovery navigation are restored. Enable Button Interaction State before
manual commanding. Verify PT1/PT2 and SV1/BV/QD on a prepared bench; on-rocket
controls remain available but require the actual rocket for feedback. RELEASE
energizes QD and OFF does not reconnect it. Verify confirmation cancellation,
reconnect relocking and no automatic command replay.

The test script checks page health and signed cache reads, not physical commands
or browser WebSocket success. Those require the operator check above. No boot
default is changed. Recovery from this directory:

```sh
previous=$(cat previous-system)
sudo "$previous/bin/switch-to-configuration" test
sudo systemctl restart greetd
```

Production TypeScript build, 18 unit/contract tests and both mocked browser
suites passed locally. Native NixOS generation build and live connectivity remain
pending. No physical actuation was performed during software verification.
