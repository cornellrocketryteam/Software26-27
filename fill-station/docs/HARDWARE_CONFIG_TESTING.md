# How to test the hardware editor

Work through these sections in order. The first checks run on your computer. The last section checks the actual board.

**Do not treat laptop tests as proof that the physical wiring works.** The implementation passed software checks, but a complete image and physical board still need verification.

## 1. Start from the repository

```sh
cd /Users/ronit/Software26-27
```

Use your checkout's location if it is somewhere else. Check your working tree:

```sh
git status --short
```

Keep unrelated changes. You do not need to reset the repository to run these tests.

Before experimenting in the editor, back up both profiles:

```sh
hardware_test_backup=$(mktemp -d)
cp fill-station/hardware/profiles/liquid.json "$hardware_test_backup/liquid.json"
cp fill-station/hardware/profiles/hybrid.json "$hardware_test_backup/hybrid.json"
echo "$hardware_test_backup"
```

Keep this terminal open and keep the printed backup location. The backup contains the current profiles, including any work that has not been committed.

## 2. Run the automatic checks

### Configuration, saving, and telemetry contracts

```sh
python3 -m unittest discover -s tests -p 'test_hardware*.py'
python3 tests/test_pinmux.py
```

**Pass:** both commands finish with `OK`. These cover pin conflicts, device settings, disabled pins, I²C routing, protected pads, profile saving, stale-file protection, and telemetry contracts.

The database test is skipped unless PostgreSQL is provided. A skip does not mean that test passed. Section 6 explains how to run it.

The default-profile regression expects the original wiring: **24 active pads and 61 idle pads** in Hybrid. Liquid now expects **23 active pads and 63 idle pads**, QD disabled, I²C0 enabled on PRU6/8, and the original ADCs still on I²C2. If you intentionally change the default wiring later, that baseline needs review too.

### Rust application

On your development computer:

```sh
nix develop --command cargo test --manifest-path fill-station/Cargo.toml --features liquid
nix develop --command cargo test --manifest-path fill-station/Cargo.toml --features hybrid
nix develop --command cargo test --manifest-path fill-station/Cargo.toml --no-default-features
```

**Pass:** no failed tests. On macOS, hardware is mocked. The development configuration without either feature is empty.

Also check that choosing both versions is rejected:

```sh
nix develop --command cargo check --manifest-path fill-station/Cargo.toml --features liquid,hybrid
```

**Expected failure:** the error says Liquid and Hybrid hardware features are mutually exclusive. Do not count this deliberate rejection as a build defect.

### Ground-station interface

Use Node.js with built-in TypeScript support for the regression tests:

```sh
node --test Ground_Station_UI/tests/hardwareAvailability.test.mjs
npm run build --prefix Ground_Station_UI
```

**Pass:** all six availability tests pass, followed by a successful TypeScript/Vite build.

If frontend dependencies are missing, install them first. The existing lockfile was inconsistent with the Vite version range when this feature was implemented. This command allowed verification without rewriting that lockfile:

```sh
npm install --ignore-scripts --package-lock=false --no-audit --no-fund --prefix Ground_Station_UI
```

## 3. Try the editor

Launch it in a second terminal from the repository root:

```sh
nix run .#hardware-config -- --repo .
```

Use the editor only during these tests; it does not operate the live board.

| Test | What to do | Expected result |
|---|---|---|
| Profiles | Switch between Liquid and Hybrid. | Each profile loads independently. |
| Pin display | Select PRU pin 36 in the diagram. | It identifies the same pad as expansion pin 8. |
| Disable | Uncheck Enable device for `ig1`, then validate. | The profile is valid; its two pins return to idle. Liquid becomes 21 active / 65 idle; Hybrid becomes 22 active / 63 idle. |
| Persistence | Save, reload the page, and select the profile again if needed. | `ig1` remains disabled. Re-enable it, save, and reload to restore it. |
| Extra device | Add an ADS1015 on the existing bus with address `0x48` (72). | Validation rejects the address conflict. |
| Correct the conflict | Change the added ADC address to `0x4a` (74). | Validation succeeds; it is marked Initialized only. |
| Protected resources | Inspect locked header positions and connection choices. | Protected pads cannot be assigned. Already-used connections are identified or blocked. |
| Unsaved changes | Edit a device and switch profiles. | The editor asks before discarding the changes. |
| Discard | Discard an unsaved edit. | The saved profile returns. |

For a new-controller test, add an MCU I²C1 bus, select its SCL/SDA connections, and move one ADC to it. It should validate without a manual device-tree change. Do not deploy that test configuration unless the ADC is actually wired there.

### Check protection against overwriting someone else's changes

1. Open the editor URL in two tabs and load the same profile in both.
2. In tab A, rename an instance and save it.
3. In tab B, make a different edit and try to save.
4. Confirm that tab B reports the file changed on disk and refuses the save.

**Pass:** tab A's saved work remains intact.

### Restore your profiles

Close the test tabs first. In the original terminal, restore only the two files you backed up:

```sh
cp "$hardware_test_backup/liquid.json" fill-station/hardware/profiles/liquid.json
cp "$hardware_test_backup/hybrid.json" fill-station/hardware/profiles/hybrid.json
```

Do this only if nobody has made profile changes you want to keep since the backup. Do not restore the whole repository. Reopen the editor to confirm the intended settings before building.

## 4. Test unavailable hardware without connecting to hardware

Start the existing station UI development server:

```sh
npm run dev --prefix Ground_Station_UI -- --host 127.0.0.1
```

Open `/tests/hardware-availability.html` on the address Vite prints. For example, if it prints `http://127.0.0.1:5173`, open `http://127.0.0.1:5173/tests/hardware-availability.html`.

**Use this fixture page for these tests.** Its commands stay inside the page; it does not connect to the fill station.

1. Click **All devices**, then **Initiate**.
2. Click **Disable ball valve**.
3. Confirm that the fill stops and Initiate becomes disabled.
4. Confirm that **INITIATE SAFE PROCEDURE** and **INITIATE STOP FILL** remain usable.
5. Confirm that the local ball-valve control says Unavailable.
6. Set a nonzero FSW vent duration, confirm it, and check that the independent FSW vent is still available.

For reconnect behavior:

1. Reload the fixture for a fresh state.
2. Set and confirm a 10-second vent duration.
3. Click All devices, Initiate, then VENT.
4. While it says Venting, click Disconnect fixture and Reconnect fixture.
5. Click Count FSW closes.

**Pass:** the fill is cancelled and a close command is recorded after reconnect. In a fresh run, the count should be 1. Stop the development server with Ctrl-C when finished.

## 5. Check the generated pinmux and image builds

First, generate both configurations without building an image:

```sh
python3 fill-station/hardware/compiler.py --profile liquid --output /tmp/hardware-test-liquid
python3 fill-station/hardware/compiler.py --profile hybrid --output /tmp/hardware-test-hybrid
```

**Pass:** both commands succeed. Each output folder contains `pinmux-report.json`, `expectations.json`, and `hardware-runtime.json`, plus generated source files. Check the report against your intended wiring.

Build both overlays using a working Linux build environment:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.pinmuxOverlay --out-link result-pinmux-liquid
nix build .#mixosConfigurations.fill-station-hybrid.config.system.build.pinmuxOverlay --out-link result-pinmux-hybrid
```

Then build both complete FIT images:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.fitImage --out-link result-fit-liquid
nix build .#mixosConfigurations.fill-station-hybrid.config.system.build.fitImage --out-link result-fit-hybrid
```

**Pass:** each build finishes successfully. The FIT build includes checks on the overlay after it is merged into the board device tree. Always deploy the image matching the profile you edited.

On this Mac, the full-image attempt failed because Determinate's Native Linux Builder timed out while starting. If that happens, fix the builder or run the builds on a Linux build machine. Successful JSON generation alone is not a substitute for these builds.

### If you deploy using an SD card

A FIT image is a boot component, not the complete SD-card image. Build the complete card image for the version you will test:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage --out-link result-sd-liquid
nix build .#mixosConfigurations.fill-station-hybrid.config.system.build.sdImage --out-link result-sd-hybrid
```

Use `result-sd-liquid/fill-station.img` or `result-sd-hybrid/fill-station.img` with the **Flashing to SD Card** procedure in `fill-station/docs/LINUX_IMAGE_BUILD_PROCESS.md`. Substitute your selected result path for that guide's `result/fill-station.img`. Confirm the destination is the intended SD card before writing it; writing an image erases that destination. For OSPI deployment, use the team's approved OSPI procedure instead.

### Optional: run the standalone real-board device-tree tests

With the board kernel source and `clang`, `dtc`, `fdtoverlay`, `fdtget`, and `fdtput` available:

```sh
KERNEL_DTS_DIR=/path/to/linux-6.18 python3 tests/test_pinmux_integration.py
```

Replace the path with the actual source root containing `include/` and `arch/`. **Pass:** all four tests run and pass. A skipped suite means the kernel path was not supplied.

## 6. Check database and dashboard availability

To test the migration locally, point this command at a PostgreSQL installation's `bin` folder:

```sh
PG_BIN=/path/to/postgresql/bin python3 tests/test_hardware_telemetry.py
```

**Pass:** all four tests run and pass, including the database test. It creates a temporary database and checks repeated migration, missing devices, partial readings, valid zero values, and legacy messages. It does not use your production database.

Before deploying the updated application, follow the deployment order in `ground-station/README.md`: database migration, protobuf schema, both broker rules and their shared action, then Grafana and the application.

On the deployed test system, confirm:

- A missing device or invalid reading displays Unavailable rather than a valid zero or closed state.
- A real measured zero remains zero.
- A configured closed valve remains closed, rather than becoming unavailable.
- Losing ADC1 does not erase valid readings from ADC2.
- FSW's own valve and MAV displays are unaffected by disabled local devices.

## 7. Finish with a physical bench check

Use the team's established bench procedure with the intended wiring and with ignition/pressurized equipment isolated. Do not use Launch as a pinmux test.

1. Deploy a successfully built image for the selected profile and reboot.
2. Confirm Ethernet and USB still work and the application starts.
3. Compare the actual wiring with the saved profile and generated report.
4. Confirm each configured I²C adapter is present and each connected ADC produces plausible readings. The default ADC bus is `/dev/i2c-2`.
5. Verify GPIO inputs with controlled test signals and PWM with test equipment. Verify outputs with isolated test loads before reconnecting actuators.
6. With a deliberately disabled device in a separate bench image, confirm its dependent command reports unavailable and its released pins have the intended idle behavior.
7. Confirm an unavailable required GPIO or I²C adapter causes startup to fail. An ADC that can open its adapter but cannot read its sensor may instead show invalid readings.
8. Use the team's shutdown procedure to verify each enabled actuator reaches its intended safe state. Include any added instances.

Rebuild and restore the intended operating profile after bench experiments.

## Sign-off checklist

- [ ] Automatic tests pass; any skipped tests are identified.
- [ ] Editor validation, save/reload, and stale-save checks pass.
- [ ] Test profile edits are restored or intentionally kept and reviewed.
- [ ] Unavailable-device, safe/stop, and reconnect behavior passes in the fixture.
- [ ] Both profiles generate and the required image builds succeed.
- [ ] Broker/database/dashboard changes are deployed in the documented order.
- [ ] Physical wiring and shutdown behavior pass the bench check.

Record the Git revision, selected profile, board revision, test results, and any remaining failures before sign-off.

## Liquid shared-I²C0 checks

- In Liquid, select `main_i2c0`. Check PRU6=SCL, PRU8=SDA, board address reservations and the always-enabled notice. There must be no Remove bus or controller-switch control for this bus.
- QD starts disabled. Temporarily enable it without saving: validation must report the pin-6 conflict. Discard the draft.
- Disable both ADS1015 devices in a draft: I²C0 must still be enabled, while the unused I²C2 bus becomes disabled. Discard.
- Switch to Hybrid: QD is enabled and no I²C0 bus is offered.
- The merged-tree tests check I²C0 status per profile, stable alias 0, EEPROM address 0x51, original board I²C1 preservation, selected registers and pinctrl attachment.
- Before bench power, disconnect the old QD enable wire from PRU6. With external devices disconnected, boot a rebuilt Liquid image and inspect `/proc/device-tree` controller status, `/dev/i2c-0`, and pinctrl ownership. Do not use a broad I²C scan on a live PMIC bus. Test only the future ADC's known address with a model-appropriate read after its driver and electrical wiring are reviewed.
- No new ADC model is implemented by this change. Full image and physical bus validation remain separate from host tests.
