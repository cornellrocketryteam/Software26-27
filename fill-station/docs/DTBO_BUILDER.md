# Fill-station hardware configuration

Liquid and Hybrid each have one JSON hardware profile in `fill-station/hardware/profiles/`.
The selected application feature determines both the Rust hardware wiring and the Linux pinmux.
Saving a profile changes the next build; it never controls the board currently running.

## Open the editor

From the repository root:

```sh
nix run .#hardware-config -- --repo .
```

Python 3.10+ can run the same editor without Nix or a frontend installation:

```sh
python3 fill-station/hardware/server.py --repo .
```

The editor binds to loopback, opens a browser, and prints its URL. Use `--no-browser`
for a terminal-only launch, or `--port 8765` to choose a port. Stop it with Ctrl-C.
All assets are local; no TI installation, account, or network service is needed.

1. Choose Liquid or Hybrid.
2. Select an existing device, or add an instance of a supported type.
3. Assign its connections. Pin labels are physical connector positions, followed by GPIO/function and package ball.
4. For an ADC, select/create a shared I²C bus and choose an address from 0x48–0x4b.
5. Validate and save. Invalid profiles cannot be saved. Discard reloads the file.
6. Build the matching image through the normal Nix workflow, then deploy and reboot.

The editor asks before discarding unsaved work on a profile switch. If another editor
changes the file, saving is rejected; reload/discard and reapply the intended edits.

## Devices, roles, and disabling

Supported types are igniter, solenoid valve, ADS1015, MAV servo, ball valve, and QD stepper.
Existing devices have application roles (`ig1`, `sv1`, `adc1`, etc.). Their instance IDs
may change without changing the role. Roles determine which existing commands and
telemetry fields use a device. New instances are **initialized only**: they have no new
control commands or telemetry bindings. Every initialized actuator participates in
emergency shutdown. Driver timing, servo calibration and sensor scaling remain in Rust.

A solenoid's normally-open/normally-closed option describes valve behavior, not its
resistor pull configuration. Pin bias is a separate electrical setting.

Disabling/removing a device releases its pins for reassignment. Otherwise, unused
eligible header pins become GPIO inputs with pull-downs and input GPIO hogs. Dedicated
open-drain pads without internal pulls use no pull. **Idle input does not hold a
normally-open valve closed.** Disabled hardware is no longer controlled by the application;
use appropriate external circuitry or disconnect it where necessary.

Commands requiring a missing role return `device_unavailable` before any action.
Launch requires both igniters and will not forward its launch command if either is
missing. A configured device that fails initialization stops application startup.

## Board connections and protections

The board inventory is `fill-station/hardware/board-pins.json`, based on TI SPRUJ64
header tables and the AM64x ALV routing data. Connector sizes are PRU54, expansion40,
and MCU28. See [TI's SK-AM64B guide](https://www.ti.com/lit/ug/spruj64/spruj64.pdf).
Shared connector positions identify one SoC pad and cannot be allocated twice.

- Main I²C2 normally uses expansion3/5 (SDA/SCL), adapter `/dev/i2c-2`.
- Main I²C3 uses the existing ball-valve pads, adapter `/dev/i2c-3`; those must be released before using that bus.
- MCU I²C0 uses MCU21/24 (SDA/SCL), adapter `/dev/i2c-4`.
- MCU I²C1 uses MCU16/22 (SDA/SCL), adapter `/dev/i2c-5`.
- PRU6/8 are the shared board I²C0 pins. Liquid uses them as always-on I²C0 (`/dev/i2c-0`) with QD disabled; Hybrid keeps stepper enable on PRU6 and I²C0 disabled. They are not an extra free I²C controller.
- Native I²C cannot be assigned arbitrarily to PRU GPO pins. The editor offers actual mux routes only.
- Ethernet, board buses/control pins, boot resources and unlisted pads remain protected. USB host policy and GPIO1_1 test input remain board-owned.

Kernel support is assumed configured. SPI, PRU firmware, UARTs and new control protocols
are outside this editor. Coordinate Linux ownership before adding MCU/PRU firmware use.

## Builds and generated files

`fill-station/hardware/compiler.py` validates the JSON and produces pin groups, controller
attachments, idle hogs, runtime descriptors and expectations. Both Cargo's build script
and Nix use it. Generated files belong in build directories; do not edit them.

```sh
python3 fill-station/hardware/compiler.py --profile liquid --output /tmp/liquid-hardware
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.pinmuxOverlay
nix build .#mixosConfigurations.fill-station-hybrid.config.system.build.pinmuxOverlay
nix develop --command cargo test --manifest-path fill-station/Cargo.toml --features liquid
```

The normal image names remain `fill-station-liquid` and `fill-station-hybrid`, paired by
`fillStation.mode`. The plain image defaults to Hybrid. Cargo without either feature
uses the empty development configuration. Selecting both features is an error; `none`
has no boot-image pinmux profile.

Nix's overlay build uses build-platform tools, including during cross compilation.
The FIT merge verifier checks every generated register, controller attachment, idle hog
and I²C alias against the real merged board tree. The old static DTSI/wrapper are historical
references, not build inputs. SysConfig projects/import tools are retired.

## Availability and extending the catalog

Availability version1 uses device bits0–11: `ig1`, `ig2`, `adc1`, `adc2`, `sv1`, `sv2`,
`sv3`, `sv4`, `sv5`, `mav`, `ball_valve`, `qd_stepper`. Reading bits0–2 are PT1, PT2,
and load cell. Version0/missing metadata means legacy behavior. Added unbound instances
do not consume role bits or generate telemetry fields. CSV uses blanks for unavailable
readings. See `ground-station/README.md` for the database/broker migration order.

To add a device type: add catalog metadata in `catalog.json`, teach the compiler its
supported connection/settings rules, implement its Rust constructor and shutdown action,
and add compiler/runtime tests. Adding an application role also requires explicit command,
telemetry and consumer integration; the editor never infers arbitrary Rust code.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_hardware*.py'
python3 tests/test_pinmux.py
KERNEL_DTS_DIR=/path/to/linux-6.18 python3 tests/test_pinmux_integration.py
node --test Ground_Station_UI/tests/hardwareAvailability.test.mjs
```

Real-tree tests need clang, dtc, fdtoverlay, fdtget and fdtput. Downstream migration tests
can use an isolated PostgreSQL installation with `PG_BIN=/path/to/postgresql/bin`.
The fixture `hardware/fixtures/original-expectations.json` preserves the exact initial
register values: 24 active pads and 61 idle inputs in Hybrid. Liquid now has 23 active pads and 63 idle inputs, with native I²C0 and QD disabled.

For a no-network station UI regression fixture, run `npm run dev --prefix Ground_Station_UI -- --host 127.0.0.1`
and open `/tests/hardware-availability.html` on its printed URL. Commands stay inside
the fixture. Start a fill, disable the ball valve, and verify initiation is disabled
while safe/stop and independent FSW controls remain available. Timed vents must close
after the fixture disconnects and reconnects. This fixture never opens a hardware socket.
