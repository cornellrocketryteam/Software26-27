# Fill-station hardware editor: complete usage guide

This guide explains what the editor does, how to use it, and where its limits are. For step-by-step checks and expected test results, use the [testing guide](HARDWARE_CONFIG_TESTING.md).

## Contents

1. [What this tool does](#1-what-this-tool-does)
2. [What it does not do](#2-what-it-does-not-do)
3. [Open and close the editor](#3-open-and-close-the-editor)
4. [Understand the screen](#4-understand-the-screen)
5. [Choose Liquid or Hybrid](#5-choose-liquid-or-hybrid)
6. [Edit an existing device](#6-edit-an-existing-device)
7. [Add a supported device](#7-add-a-supported-device)
8. [Set up I²C devices and buses](#8-set-up-i2c-devices-and-buses)
9. [Choose GPIO and PWM connections](#9-choose-gpio-and-pwm-connections)
10. [Understand the electrical settings](#10-understand-the-electrical-settings)
11. [Disable, re-enable, or remove a device](#11-disable-re-enable-or-remove-a-device)
12. [Validate, save, discard, and recover changes](#12-validate-save-discard-and-recover-changes)
13. [Build and use the saved configuration](#13-build-and-use-the-saved-configuration)
14. [What changes in the running application](#14-what-changes-in-the-running-application)
15. [Files and command-line use](#15-files-and-command-line-use)
16. [Mistakes to avoid](#16-mistakes-to-avoid)
17. [Common problems](#17-common-problems)
18. [FAQs](#18-faqs)

## 1. What this tool does

The editor lets you choose which supported devices the fill station uses and which TI SK-AM64B pins they connect to.

**Pinmux** means choosing a pin's function. For example, a pin may be available as a general input/output, an I²C connection, or a PWM output.

You edit one of two configurations: **Liquid** or **Hybrid**. Each is saved as a JSON file. JSON is a text format that holds the device list and its settings.

When you build the selected version, that same file controls:

- Which supported devices the Rust application creates at startup.
- Which physical pads those devices use.
- Which supported I²C and PWM controllers Linux enables.
- Which unused header pins receive the default idle settings.

This keeps the application wiring and Linux pin setup together. You do not need to edit a separate device-tree overlay or a TI SysConfig project for these supported changes.

**Saving updates a file on your computer. The board changes only after you build, deploy, and boot the matching new image.**

## 2. What it does not do

| The editor can… | It does not… |
|---|---|
| Add instances of the supported device types. | Create a driver for an arbitrary new sensor or actuator. |
| Set up the supported pin connections and controllers. | Enable missing kernel drivers or repair a kernel configuration. |
| Check the saved configuration for known conflicts. | Detect your actual wiring, probe the board, or prove a circuit is electrically correct. |
| Initialize an added device through its existing Rust driver. | Automatically create commands, telemetry fields, or station controls for that device. |
| Save a configuration for a later build. | Change live pins, actuate hardware, flash the board, or build an image from the browser. |
| Manage the supported GPIO, I²C, and PWM routes. | Configure SPI, UART, arbitrary peripheral types, or PRU/MCU firmware. |

This is a repository tool for the SK-AM64B fill station. It is not a replacement for the full TI SysConfig tool across every TI board or peripheral.

## 3. Open and close the editor

Open a terminal in the repository root. In this checkout that is:

```sh
cd /Users/ronit/Software26-27
```

Use your own checkout's path if it is elsewhere. Launch the editor:

```sh
nix run .#hardware-config -- --repo .
```

The terminal prints a local address and normally opens it in your browser. If the browser does not open, copy the printed address into it. The port may change each time you launch.

You can also run the editor using Python 3.10 or later, without Nix:

```sh
python3 fill-station/hardware/server.py --repo .
```

The editor itself needs no frontend package installation, TI installation, or account. Its pages and assets are local. Nix may need network access to obtain its dependencies the first time.

### Useful launch options

To print the address without opening a browser:

```sh
python3 fill-station/hardware/server.py --repo . --no-browser
```

To choose a fixed port:

```sh
python3 fill-station/hardware/server.py --repo . --port 8765
```

If that port is occupied, choose another one or leave out `--port` so the editor finds a free port. The same options can follow `--repo .` in the Nix command.

### Close it

Save or discard your work, then press **Ctrl-C** in the terminal running the editor. Closing a browser tab alone does not stop the server. Closing the editor has no effect on the running board.

The server accepts connections from your own computer. Do not expose it as a public website or try to use its local address from another computer.

## 4. Understand the screen

The layout may stack vertically in a narrow browser window. Scroll to reach the device settings and header diagrams.

| Part of the screen | What it means |
|---|---|
| Application selector | Chooses the Liquid or Hybrid file you are editing. |
| Devices | The device instances in that profile. Select one to edit it. |
| I²C buses | Shared bus definitions. Several ADCs can use one bus. |
| Device settings | The selected device's ID, enabled state, connections, and supported options. |
| Application bound | This instance has an existing role in the Rust application. |
| Initialized only | This instance has no application command or telemetry role. |
| Board connections | Physical pin diagrams for the PRU, 40-pin expansion, and MCU headers. |
| Configuration check | Shows whether the current draft passes validation and reports assigned/idle pad counts. |
| Validate | Checks the draft without saving it. |
| Save profile | Writes a valid, changed profile to disk. |
| Discard changes | Reloads the selected profile from disk. |

### Read pin labels correctly

A choice such as `EXPANSION:18 · GPIO0_39 · N16` gives you three different references:

- `EXPANSION:18`: physical pin 18 on the expansion connector. Use this to locate the connection on the board.
- `GPIO0_39`: the SoC signal name.
- `N16`: the chip's package ball, mainly useful when checking a schematic.

These are not Raspberry Pi BCM pin numbers. Also, the `0` in `GPIO0_39` is not a promise that Linux calls its device `gpiochip0`.

### Shared positions and locked pins

Two header positions can be connected to the same SoC pad. For example, **PRU:36 and EXPANSION:8** refer to one pad. Selecting either in the diagram shows the shared positions. They cannot be assigned to two different uses.

The header diagrams have 54 PRU positions, 40 expansion positions, and 28 MCU positions. Locked or unlisted positions are not available for assignment. They can include power, ground, board controls, and protected peripherals; “Locked” is not a complete description of their electrical purpose.

Some existing connections appear as **Board pad**, rather than a header position. Do not assume those pads are exposed on a spare header.

## 5. Choose Liquid or Hybrid

Each version has its own complete file:

| Version | Saved file |
|---|---|
| Liquid | `fill-station/hardware/profiles/liquid.json` |
| Hybrid | `fill-station/hardware/profiles/hybrid.json` |

Changing Liquid does not change Hybrid. Hybrid preserves the original wiring. Liquid disables QD and enables shared I²C0 on PRU pins 6/8; the existing ADCs stay on I²C2. The profiles can otherwise be changed independently.

The application build chooses the matching file automatically. There is no separate image pinmux choice to keep in sync.

**Selecting Hybrid in the editor does not select Hybrid for your next terminal build.** The selector chooses the file you edit. The build command chooses which version you build.

Only these two editable profiles are supported. The plain `fill-station` image defaults to Hybrid. A Cargo build with neither vehicle feature uses an empty development configuration; it is not a third editable hardware profile. Selecting both vehicle features is an error.

## 6. Edit an existing device

1. Choose the correct profile.
2. Select the device in the Devices list.
3. Check its application role before changing anything.
4. Choose each required connection. The editor shows supported routes and identifies connections already in use.
5. Change only the device options or electrical settings that your wiring requires.
6. Move out of a text field after editing so the change is applied to the draft.
7. Click Validate, resolve any errors, and save.

For a pin move, update the physical wiring to match before booting an image that uses the new assignment. Validation cannot check that you moved the wire.

### Instance ID versus application role

An **instance ID** names a particular configured device. An **application role** tells the Rust program which existing job that device performs.

For example, an instance may be named `fill_valve` while keeping the role `sv1`. Existing SV1 commands still use that role. Renaming the instance does not rename the command or create a different control.

Use IDs that start with a lowercase letter and contain only lowercase letters, digits, and underscores, up to 48 characters. Choose a unique ID. The compiler also rejects duplicate device IDs and duplicate application roles.

The existing application roles are:

| Roles | Device type |
|---|---|
| `ig1`, `ig2` | Igniters |
| `adc1`, `adc2` | ADS1015 ADCs |
| `sv1` through `sv5` | Solenoid valves |
| `mav` | MAV servo |
| `ball_valve` | Ball valve |
| `qd_stepper` | QD stepper |

The GUI displays existing roles but does not provide a role reassignment control.

### Liquid shared I²C0: PRU pins 6 and 8

Liquid has a required bus named `main_i2c0`. PRU pin 6 is its clock (SCL) and PRU pin 8 is its data line (SDA). The same physical lines appear at expansion pins 28 and 27. The bus remains enabled even when no external devices use it. It cannot be removed or changed to another controller in the editor.

Liquid's QD stepper is disabled. Its old enable connection uses PRU pin 6, so trying to enable QD with that wiring produces a pin conflict. Its unused step/direction pins become idle inputs. **Disconnect or isolate the old QD enable wire from pin 6 before powering this configuration.** A software setting cannot disconnect a physical wire. Hybrid keeps the original enabled QD and disabled main I²C0 configuration.

The PROC100A(002) board shares I²C0 with onboard devices. The compiler reserves `0x30` for the PMIC, `0x51` for the board EEPROM, and `0x50` for expansion EEPROM use. It preserves the base board's EEPROM node. External devices must use compatible 3.3 V I²C electrical levels, suitable pull-ups and unused addresses. Dedicated SCL/SDA pads use no internal pull; do not assume a GUI bias setting replaces external pull-ups.

The existing `adc1` and `adc2` stay on I²C2 at `0x48` and `0x49`. No new ADC has been added. Future ADC models need a catalog definition and a Rust driver before they can be added as working instances. Do not select ADS1015 for a different ADC model. Bus access will be `/dev/i2c-0` after building, deploying and booting the matching Liquid image. Saving in the editor alone does not enable hardware.

Board references: [TI SK-AM64B guide, I²C section](https://www.ti.com/lit/ug/spruj64/spruj64.pdf), [TPS6522053 register reference](https://www.ti.com/lit/ug/slvucj3/slvucj3.pdf).

## 7. Add a supported device

Click **+ Add** under Devices, choose a supported type, and enter an instance ID. Fill in every required connection before saving.

| Supported type | What you configure |
|---|---|
| Igniter | Continuity input and firing signal output. |
| Solenoid valve | Control output, sense input, and normally-open/normally-closed behavior. |
| ADS1015 ADC | Shared I²C bus and one of the supported addresses. |
| MAV servo | A supported PWM output. |
| Ball valve | `on_off` and `signal` outputs. |
| QD stepper | `step`, `direction`, and `enable` outputs. |

### What happens to an added instance

A new instance is marked **Initialized only**. When the application from the matching new image starts, it creates that instance through the device type's driver. Added actuators also participate in emergency shutdown.

Initialization can request GPIOs and set the driver's startup output state. For example, the normally-open solenoid driver requests a HIGH control output to hold the valve closed. The MAV driver sets its closed-position pulse and enables PWM. **Initialized only does not mean electrically inactive.** Connect added actuators only when their driver's startup behavior is appropriate for your setup.

A new instance does not automatically get a valve command, sensor channel mapping, telemetry field, or station button. That work requires a Rust application change and any needed consumer changes.

Naming a new instance `sv1` does not give it the `sv1` role. Its role remains unbound unless a developer explicitly assigns an existing role or adds application support.

### Adding a type that is not listed

The editor cannot create a new type from an arbitrary Rust file or detect devices mentioned in Rust source. A developer must add its catalog definition, configuration checks, Rust driver/initialization support, shutdown behavior, and tests. Commands and telemetry need explicit integration too.

## 8. Set up I2C devices and buses

I²C uses two signals:

- **SCL**: the clock.
- **SDA**: the data line.

Several devices can share those same two lines. Each enabled device on that bus must have a different address.

### Add another ADC on an existing bus

1. Add an ADS1015 device.
2. Choose the existing bus in its I²C bus setting.
3. Choose its address: `0x48`, `0x49`, `0x4a`, or `0x4b`.
4. Make sure the ADC's physical address wiring matches that choice.
5. Validate and save.

The initial ADCs use `0x48` and `0x49` on Main I²C2. A third ADC on that same bus needs another address, such as `0x4a`. The same address can be used on a different bus.

Changing the address in the editor does not change a chip's address wiring. Also, changing an ADC's role or wiring does not change the application's sensor scaling or channel assignments.

### Add a new bus

1. Click **+ Add** under I²C buses.
2. Choose a controller and enter a bus ID.
3. Choose its valid SCL and SDA connections.
4. Select that bus in the ADC's settings.
5. Validate and save.

The build enables the supported controller and attaches its pin group automatically when an enabled ADC uses that bus. There is one shared bus definition per controller.

Except for Liquid’s required shared I²C0, a bus definition with no enabled ADC using it does not keep that controller active or reserve its pins. It still needs valid SCL/SDA settings to pass validation. Disabling the last ADC on an optional bus releases its pins too; Liquid I²C0 stays active.

If you change a bus's controller, the editor clears the old SCL/SDA choices. Select the new pair before saving. If you rename a bus in the GUI, it updates device references to that bus. Removing a bus while an ADC still refers to it makes the profile invalid, including references from disabled ADC entries.

### Available controller routes

| Controller | Common/default route | Linux adapter |
|---|---|---|
| Main I²C2 | Expansion pin 3 = SDA; pin 5 = SCL. Alternate routes are available where the inventory allows them. | `/dev/i2c-2` |
| Main I²C3 | The pads currently used by the existing ball valve; not a spare PRU header pair. | `/dev/i2c-3` |
| Main I²C0 (Liquid only) | PRU pin 6 = SCL; pin 8 = SDA. Also expansion 28/27. | `/dev/i2c-0` |
| MCU I²C0 | MCU pin 21 = SDA; pin 24 = SCL. | `/dev/i2c-4` |
| MCU I²C1 | MCU pin 16 = SDA; pin 22 = SCL. | `/dev/i2c-5` |

A new route may require releasing a device that already uses those pads. For example, you cannot keep the existing ball-valve wiring and also use the same pads for Main I²C3.

PRU pins 6 and 8 are shared board I²C0 signals. Liquid enables this shared bus and disables QD. Hybrid keeps pin 6 as QD enable and leaves main I²C0 disabled. Board I²C1 remains protected in both profiles. You cannot turn arbitrary PRU GPIO pins into native I²C pins.

The current generated buses use **400 kHz**. The GUI does not offer a bus-speed control. Check that your devices, wiring, voltage levels, and external pull-up resistors suit the bus. An internal pin pull-up is not a replacement for checking the I²C circuit.

## 9. Choose GPIO and PWM connections

### GPIO

GPIO is a general digital input or output. The device type determines each connection's direction: for example, igniter continuity is an input and its firing signal is an output. You do not select arbitrary input/output direction separately in the GUI.

A device's GPIO connections can use supported available pads across the managed headers. The compiler resolves the Linux GPIO device and line for Rust.

There is no generic “free GPIO” device type in the current catalog. If an application needs a new kind of GPIO use, add the appropriate driver/application support rather than pretending it is a different component.

### PWM

PWM is the repeating output used by the supported MAV servo driver. Choose one of the supported PWM routes offered for that device.

The compiler maps the choice to its Linux PWM controller and channel. It rejects allocating the same PWM output twice, including through different pads.

The editor does not change servo pulse widths, calibration, PWM frequency, or timed motion logic. Those settings stay in the Rust driver. It is not a general-purpose PWM waveform editor.

### Board ownership

The tool protects board functions such as Ethernet, boot resources, board buses, and control pins. It also retains fixed USB host setup and the existing GPIO1_1 test input. You cannot reassign these through ordinary device entries.

“PRU header” and “MCU header” describe connectors. Selecting their pins here gives Linux ownership through this workflow; it does not configure a PRU or MCU firmware program to use them.

## 10. Understand the electrical settings

| Setting | Plain meaning | How to use it |
|---|---|---|
| Pull-down | A weak internal connection toward a low level when nothing stronger drives the signal. | Use only where the circuit calls for it. It is not a power supply or an actuator-off command. |
| Pull-up | A weak internal connection toward a high level. | Check the circuit requirements; it is not a promise that the external device is powered or safe. |
| No pull | No internal pull-up or pull-down is requested. | Appropriate where the circuit supplies its own bias or the pad has no internal pull support. |
| Schmitt input | An input setting that helps the receiver handle slow or noisy transitions. | Keep the existing/default setting unless you have a circuit-specific reason to change it. It does not replace proper signal conditioning. |

Some dedicated open-drain pads do not have internal pulls. The GUI restricts them to No pull, and validation rejects incompatible settings.

The tool does not configure voltage conversion, output current capability for an external load, or external resistors. Check the board and device electrical requirements before wiring.

### Solenoid behavior is a different setting

**Normally closed** and **normally open** describe the valve's mechanical state without actuation. They tell the driver how to interpret its control output. They are separate from pin pull-up/pull-down settings.

Use the option that matches the actual valve. A normally-open valve may need an asserted output to stay closed; simply disabling its device is not a way to hold it closed.

## 11. Disable, re-enable, or remove a device

### Disable temporarily

Uncheck **Enable device**. The entry and its settings remain in the profile, so you can enable it again later.

After the next build and boot:

- The Rust application does not initialize that instance.
- Its connections can be used by another enabled device.
- Otherwise, unused eligible header pads return to the default idle policy.
- Existing commands that require its missing role report that it is unavailable.

Disabled entries still need valid names, settings, connection choices, and bus references. Disabled does not mean the compiler ignores malformed entries. They do not claim active pin resources or active I²C addresses.

### Re-enable

Check Enable device again and validate. If another device now owns its old pins or I²C address, resolve that conflict first.

### Remove permanently

Select Remove device and confirm. This deletes the entry from the draft. Saving makes the deletion part of that profile.

Prefer disabling an application-bound device if you expect to bring it back. Removing it also removes its role assignment. Adding a new device with the old name does not restore that role automatically; restore the original entry from a backup or ask a developer to restore the existing role correctly.

### What idle means

Unused eligible header pins normally become GPIO inputs with pull-downs. Dedicated pads without internal pulls use no pull. Linux requests the idle GPIOs as inputs, so they are held for the idle policy until a later configuration assigns them.

This policy covers the eligible managed header pads, not every unassigned pin on the chip. Board-owned resources keep their board policy.

**Disabling does not cut power, disconnect a wire, or guarantee a safe physical position. An idle input does not hold a normally-open valve closed.** Use the appropriate external circuit or disconnect the device where necessary.

## 12. Validate, save, discard, and recover changes

### Validation

The editor checks changes as you work. Validate also runs the check explicitly. Builds use the same shared configuration checks.

Checks include supported device types, valid settings and routes, required connections, protected pads, duplicate pad use, complete I²C pairs, duplicate enabled addresses on a bus, duplicate PWM outputs, and valid application roles.

A Valid result means the configuration passes these software rules. It does not prove that the wire is on the right pin, a sensor responds, an output is safe, or the finished image has booted successfully.

The assigned/idle counts describe physical pads, not device counts or the total number of connector positions.

### Saving

Save profile is enabled when there are unsaved changes and the draft is valid. It writes only the selected Liquid or Hybrid JSON file. It does not save both profiles, commit to Git, build, deploy, or contact the board.

A saved draft is written as a complete replacement file. If the file has changed since you loaded it, the editor blocks the save rather than overwriting it with your older copy.

### Discarding and switching profiles

Discard changes reloads the selected profile from disk. It does not restore a previously saved version or undo a Git commit. If there are unsaved edits, the editor asks before discarding them.

Switching profiles also asks before discarding unsaved work. Save before refreshing or closing the tab. The editor requests a browser warning for unsaved changes, but it does not store a recoverable browser draft. If you leave and discard the edits, they are lost. A fresh page load starts with Liquid, so check the selector after refreshing.

### Recovering work

Before major changes, save a backup or make a reviewed Git commit. Keep both JSON files in version control.

If a stale-file warning appears, record any draft changes you want to keep, then discard/reload and reapply them to the current file. There is no automatic merge, named-snapshot system, or general Undo button.

After a saved mistake, restore the affected profile from a known backup or Git history. Check for other people's work before replacing it. Do not reset the whole repository to undo one profile edit.

## 13. Build and use the saved configuration

The normal sequence is:

**Edit → Validate → Save → Test → Build the matching version → Deploy → Reboot → Verify.**

For a complete SD-card image, choose one version:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage --out-link result-sd-liquid
```

or:

```sh
nix build .#mixosConfigurations.fill-station-hybrid.config.system.build.sdImage --out-link result-sd-hybrid
```

The card image is `result-sd-liquid/fill-station.img` or `result-sd-hybrid/fill-station.img`.

For the card-writing procedure, see **Flashing to SD Card** in `fill-station/docs/LINUX_IMAGE_BUILD_PROCESS.md`. Use the selected result path instead of that document's generic `result/fill-station.img`. Writing an image erases the destination, so confirm it is the intended SD card. For OSPI, use the team's approved OSPI deployment procedure.

The separate `fitImage` build target produces a boot component, not a complete SD-card image. Overlay-only and FIT-only checks are covered in the testing guide.

Use a working Linux build environment or Linux builder for the image. Launching the editor and validating JSON can work even when that builder is unavailable.

### What gets generated

The build creates Linux pin groups/controller setup and Rust device descriptions from the selected JSON. The FIT build also verifies the expected pin values and attachments after merging the overlay into the real board device tree.

Generated files belong in build output folders. Edit the JSON profiles, not the generated files or the old static pinmux reference files.

### Deployment includes the telemetry consumers

For the first deployment of this feature, update the database migration, protobuf schema, broker rules/action, and Grafana configuration before the updated application. Follow **Hardware availability deployment** in `ground-station/README.md`.

Saving or building a profile does not perform those service updates. The consumer changes are needed to show missing devices and invalid readings properly. They do not need to be reapplied simply because you make another ordinary pin edit after that deployment is complete.

## 14. What changes in the running application

### Missing devices and startup errors

An explicitly disabled or removed device is allowed. Commands needing its application role return `device_unavailable` before their action runs.

Launch requires both igniters. If either is missing, it rejects before starting ignition or forwarding its launch command. The separate FSW-only controls are not made unavailable simply because a local device is disabled.

If an enabled device fails during initialization, application startup fails. The program does not silently treat it as disabled. Some faults appear later: for example, an ADC may open an I²C adapter successfully but then fail to read its sensor. Those readings are invalid rather than usable zero measurements.

### Readings, displays, and logs

Availability information tells the station which existing roles are configured and which sensor readings are valid. ADC1 and ADC2 have separate reading validity, so one failing does not automatically erase the other's valid data.

With the updated consumers:

- A missing device or invalid reading displays as unavailable.
- CSV leaves unavailable values blank and includes availability information.
- The database stores unavailable affected values as missing values, so dashboards can show gaps or Unavailable.
- Valid zero measurements and configured closed states remain valid zero/false values.

Older messages without the metadata retain their legacy interpretation. Added unbound instances do not acquire new telemetry fields automatically.

Actuator status is generally the last commanded state; it is not proof of the device's actual physical position.

### Shutdown and interrupted fill operations

Every initialized actuator instance is included in the application's best-effort emergency shutdown. That includes added instances without application roles. A driver failure can still prevent a physical safe state; the editor does not verify actuator movement or guarantee shutdown timing.

The station UI blocks dependent controls when required local devices are unavailable. Safe/stop controls remain usable, and the independent FSW vent remains available. Interrupted timed fill vents retain the need to close after reconnect. Use the isolated fixture in the testing guide to check this behavior without operating hardware.

## 15. Files and command-line use

All paths below are relative to the repository root.

| File or folder | Purpose |
|---|---|
| `fill-station/hardware/profiles/liquid.json` | Complete Liquid configuration. |
| `fill-station/hardware/profiles/hybrid.json` | Complete Hybrid configuration. |
| `fill-station/hardware/board-pins.json` | Supported pads, functions, header positions, and idle policy. |
| `fill-station/hardware/catalog.json` | Supported device types and their editable settings/connections. |
| `fill-station/hardware/compiler.py` | Shared validation and generation used by GUI and builds. |
| `fill-station/hardware/server.py` | Local editor server. |

The two profile files use schema version 1. They contain device entries and shared I²C bus entries. You can edit them by hand if you preserve the format, then run validation. Unknown fields or unsupported values are rejected; do not invent settings and expect the build to use them.

For example, this is one added ADC entry inside a profile's device list, not a complete profile:

```json
{
  "id": "spare_adc",
  "type": "ads1015",
  "role": null,
  "enabled": true,
  "connections": {},
  "settings": {},
  "bus": "main_i2c2",
  "address": 74
}
```

Here, 74 means address `0x4a`, `main_i2c2` must be an existing bus ID in the profile, and `role: null` means Initialized only. A matching physical ADC is still required for useful operation.

To validate and generate review files without building an image:

```sh
python3 fill-station/hardware/compiler.py --profile liquid --output /tmp/liquid-hardware
```

Use `--profile hybrid` for Hybrid. Useful outputs include:

| Output | What to inspect |
|---|---|
| `pinmux-report.json` | Assigned pads, header positions, and idle pads. |
| `hardware-runtime.json` | Enabled Rust device descriptions, including resolved GPIO/I²C/PWM connections. |
| `expectations.json` | The values and attachments checked against the merged board tree. |

Other outputs are generated Rust and device-tree sources. Generating them does not install or activate them.

The GUI is limited to the two normal profile files. It does not offer arbitrary import/export destinations, a YAML format, or a way to add more vehicle profiles. Keep the profiles as regular files; the server rejects symlinked profile storage.

## 16. Mistakes to avoid

| Avoid this | Do this instead |
|---|---|
| Saving and assuming the running board changed. | Build, deploy, reboot, and verify the matching version. |
| Editing Liquid but building Hybrid. | Check both the GUI selector and terminal build command. |
| Moving a pin in software while leaving the wire on its old position. | Keep the configuration, wiring, and deployed image together. |
| Giving two devices the same pad through different headers. | Treat shared header positions as one physical resource. |
| Reusing an enabled I²C address on the same bus. | Choose a free address and match the device's hardware address wiring. |
| Adding an instance and expecting a new command or sensor display. | Add the required application/telemetry code separately. |
| Deleting an existing role-bound device when you only need it temporarily absent. | Disable it so its role assignment is easy to restore. |
| Treating disabled or Initialized only as electrically safe/off. | Check startup states, idle behavior, and the external circuit. |
| Renaming a device to impersonate another application role. | Keep the role and ID distinction clear; ask a developer for role changes. |
| Editing generated Rust or device-tree output. | Edit the profile and regenerate through the normal build. |
| Bypassing a conflict by editing the board inventory. | Resolve the actual resource conflict; inventory changes require hardware review. |
| Using a real ignition or pressurized setup to explore the GUI. | Use laptop tests and the team's isolated bench procedure first. |

## 17. Common problems

| Problem | What to check or do |
|---|---|
| The browser does not open. | Open the URL printed in the terminal. Confirm the server is still running. |
| The port is already in use. | Leave out `--port`, or choose a different port. |
| The editor cannot find the profiles. | Start in the repository root or give `--repo` the correct checkout path. Both JSON files must exist. |
| The server refuses a request or says its token is missing. | Open/reload the page from the current server's printed local URL. Do not reuse an old tab after restarting the server. |
| Save profile is disabled. | There may be no changes, validation may still be running, or the draft may have an error. Read Configuration check. |
| A text edit seems not to apply. | Move focus out of the text field, then validate. |
| Validation shows missing connections. | Complete every required device port or I²C SCL/SDA pair. Disabling does not excuse malformed entries. |
| A pin is blocked or unavailable. | Check its current owner, shared positions, and whether it is board-owned. Release the existing assignment if appropriate. |
| An I²C controller is listed but seems unused. | It is activated only when an enabled ADC uses that bus. |
| Validation reports an address conflict. | Two enabled ADCs on the same bus have the same address. Change the address or bus to match the actual wiring. |
| Save says the file changed on disk. | Preserve any draft notes you need, discard/reload, and reapply them. There is no automatic merge. |
| A manually edited JSON file will not load. | Fix its format or restore that profile from a known backup. The GUI does not repair corrupt files. |
| The build rejects an application role. | The role must be one of the existing roles, match the device type, and be assigned only once. |
| The image build cannot start its Linux builder. | Fix the builder or build on a working Linux machine. A valid profile alone is not a completed image. |
| The board still behaves like the old configuration. | Confirm you saved, built the correct version, deployed the resulting image, and rebooted from it. |
| An added ADC has no new readings in the station UI. | New instances are Initialized only. Its sampling, scaling, and telemetry need application support. |

## 18. FAQs

### Does this use TI SysConfig behind the scenes?

No. The active workflow uses the repository's JSON files and shared compiler. The board routing inventory was built from TI information, but saving or building these configurations does not need the TI GUI or CLI.

### Do I need the board connected to use the editor?

No. It edits local files and does not discover the board. A connected board also does not make validation a hardware test.

### Can I use this instead of looking at the schematic?

No. The inventory limits choices to known routes, but you still need to confirm connector orientation, board revision, voltage levels, external circuitry, and actual wiring. Locked/unlisted positions are not described electrically by the GUI.

### Can I use the PRU header for ordinary GPIO?

Yes, where the inventory offers those routes. The connector name does not require PRU firmware. Board-owned signals remain protected, and PRU pins 6/8 are not another free I²C bus.

### Can I put I²C on any two GPIO pins?

No. This tool selects native hardware I²C routes. It does not implement a software I²C bus on arbitrary GPIOs.

### Can two devices share pins?

Two ADCs on one shared I²C bus intentionally share SCL and SDA. They need different addresses on that bus. Separate GPIO uses cannot share a physical pad, and one PWM output cannot be allocated twice.

### Can I change frequency, sensor scaling, stepper motion, or servo calibration here?

No. The current GUI changes wiring and the listed device settings. Those operating details stay in Rust; the generated I²C clock is currently fixed at 400 kHz.

### Does adding a device make it part of Launch or the fill sequence?

No. Existing application roles determine what those flows use. Added unbound instances get initialization and actuator shutdown handling, not new sequence behavior.

### Why do controls still say unavailable after I delete and recreate `sv1`?

The new entry has no role. Reusing the ID does not restore the deleted role assignment. Restore the original entry from a backup or ask a developer to restore the existing role correctly. Use Disable next time if you want to keep that assignment.

### If I disable a device, can I reuse its old pins?

Yes. Active resource conflicts from that disabled instance are released. Keep its entry valid, and resolve conflicts before re-enabling it later. If you disable the last ADC using an optional bus, its pins are released too. Liquid’s shared I²C0 remains active.

### Is an idle pin the same as a powered-off device?

No. The device can remain powered and wired. An input with a pull-down is just a pin setting. It is not an actuator shutdown command and does not hold a normally-open valve closed.

### Does emergency shutdown cover newly added actuators?

Yes, initialized instances are included even without application roles. Shutdown is still best effort and depends on drivers, wiring, power, and the physical device. Test it on the bench.

### What if an enabled device is missing?

If initialization fails, startup fails. If the device initializes but later reads fail, the related data is invalid. The application does not automatically rewrite the profile or disable the device for you.

### Can I edit JSON while the GUI is open?

Yes, but that creates a possible stale-file conflict. The GUI will refuse to save an older copy over your changed file. Reload it before continuing. Prefer one editor at a time for ordinary work.

### Does Save commit my changes or update both vehicle versions?

No. It writes only the selected JSON file. Review and commit changes through the normal Git workflow. Repeat the intended edit in the other profile only if it should change too.

### Can I save several named configurations for one version?

The GUI has one active Liquid file and one active Hybrid file. Use Git history or explicit backups for earlier revisions. There is no named-profile library or snapshot picker.

### Can I hot-swap between Liquid and Hybrid on the running board?

No. The selected build includes one configuration. Changing the GUI selector does not switch the running application; build and deploy the other version.

### Why does Nix warn about uncommitted changes?

The checkout has local edits. Saving a profile does not commit it. Review the intended changes before a shared/release build; do not reset unrelated work just to remove the warning. New source files also need to be tracked so Git-backed Nix flakes can include them.

### What should I check before using a changed configuration?

Run the [testing guide](HARDWARE_CONFIG_TESTING.md), review the saved profile and generated report, complete the matching image build, and verify the wiring and shutdown behavior on the bench. Saving successfully is only one step.

### Where are the deeper technical details?

In the repository:

- `fill-station/docs/DTBO_BUILDER.md`: generation, builds, and pin policy.
- `fill-station/docs/PRU_HEADER.md`: header routing and board restrictions.
- `ground-station/README.md`: database, broker, and dashboard rollout.
- `fill-station/docs/LINUX_IMAGE_BUILD_PROCESS.md`: image and SD-card writing procedure.
- `fill-station/docs/WEBSOCKET_API.md`: existing application commands; consult current Rust code for the added availability responses.
