# PRU servo PWM

PRU PWM extends the hardware profile workflow: select a direct PRU output for a
MAV or EREG PWM connection, validate/save, build the matching image, then deploy
and reboot. Saving does not change a running board.

Physical PRU connector pins 37, 38, 39 and 40 route to ICSSG0 PRU1 output bits
2, 3, 4 and 5. They are connector pin numbers, not Linux GPIO line numbers.
Each channel has an independent period and pulse width. A shared frequency is
not required. Existing profiles retain their wiring unless explicitly edited.

## Timing and device settings

The editor exposes `period_ns`, `min_pulse_us`, `max_pulse_us` and
`safe_pulse_us`. The servo envelope is 20–500 Hz (2–50 ms periods), with at
least 100 microseconds high and low time. Pulse bounds must fit that period.
PRU timing is rounded to the nearest microsecond; ordinary ePWM uses its Linux
driver's timing. Requested resolution is not a measured edge-accuracy guarantee.

MAV and EREG use the same PWM backend interface. MAV retains its open/close
behavior; EREG retains angle conversion. Pulse bounds must accommodate MAV's
commanded positions. Changing bounds does not recalibrate the physical actuator.
The EREG angle range still requires physical calibration.

## Ownership and failure behavior

The compiler resolves the selected pad to either ePWM or PRU. PRU pads use direct
output mux mode and are excluded from Linux GPIO idle hogs. A pad cannot also be
a valve GPIO, I2C signal or another device connection. Other firmware cannot own
the selected PRU resources concurrently. Only inventoried eligible routes are
offered; a PRU connector label alone does not establish PWM capability.

Firmware starts with outputs disabled. Host configuration establishes pulse
bounds and safe pulses before arming. Rust sends settings through RPMsg; Linux
does not generate individual pulse edges. Heartbeats run every 100 ms. Loss of
contact for 500 ms selects the configured safe pulses and requires rearming.
MAV defaults to its closed pulse; EREG defaults to its minimum pulse. Explicit
disable drives low. A reset or stopped processor cannot continue generating a
safe pulse: actuator behavior on signal loss must be checked separately.

## Acceptance before use

Use a dedicated profile with four initialized-only devices on pins 37–40;
unbound devices do not acquire WebSocket commands automatically. Scope all four
outputs at mixed 20, 50, 330 and 500 Hz and again at 330 Hz together. Verify pulse
updates, application termination/restart, firmware stop and board reboot under
Linux/network load. Target edge error is within plus or minus 2 microseconds,
with no missing or unintended pulses during normal operation. Hardware
acceptance is separate from compiler, scheduler and image-build tests.

For failures, first check the selected image/profile, generated pinmux report,
remoteproc firmware identity/state, RPMsg endpoint and startup logs. Do not
substitute remoteproc numbers from another board. A missing endpoint or rejected
configuration is an initialization error; it must not silently fall back to
Linux GPIO bit-banging.

High-frequency power control, complementary outputs and dead time are outside
this servo implementation. Dedicated ICSSG peripheral PWM is a different mux
route and is not selected by choosing a direct PRU GPO output.

## Build and test

Build the selected image normally after saving the profile:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage
python3 -m unittest discover -s tests -p 'test_hardware*.py'
python3 -m unittest discover -s tests -p 'test_pru*.py'
node --test tests/test_hardware_editor.mjs
make -C fill-station/pru test
```

Real-board-tree merge tests require the pinned Linux source and clang/dtc tools:

```sh
KERNEL_DTS_DIR=/path/to/linux python3 tests/test_pinmux_integration.py
```

The pinned TI compiler is a proprietary build dependency. The MixOS package set
allows only that named package; it is not installed on the board. Its old
32-bit installer requires a glibc compatibility setting, while its 64-bit tools
run through QEMU/proot on ARM64 Linux builders. The firmware package uses a
native build package set so the compiler's dependencies are not cross-compiled
for the board. Unchanged ePWM-only profiles do not pull in this toolchain.

Initial PRU edges are scheduled 500 microseconds after enabling/arming to leave
time for command handling. Repeated global ARM while outputs are enabled is
rejected. Timing deadline faults disable outputs and require reconfiguration;
heartbeat-loss faults continue configured safe pulses. A live scope check is
required to establish the usable channel/timing envelope, particularly near
simultaneous edges and during RPMsg traffic.

## Implementation verification

The implementation was checked with 24 Rust library tests for each of Liquid
and Hybrid, 53 hardware/editor tests (one environment-dependent test skipped),
19 pinmux tests, six merged-tree verifier tests, four boot-wrapper tests, two
editor JavaScript tests and the shared C scheduler tests. Five integration
tests merged overlays into the pinned Linux 7.2.15 board tree.

The ARM64 musl application and pinned TI compiler/PRU firmware packages built.
The unchanged Liquid SD image built. A separate temporary Liquid profile with
four EREGs on physical PRU37–40 at mixed periods built both SD and OSPI outputs
and passed FIT verification; its FIT was 14,250,636 bytes against a
58,458,112-byte slot.
These checks do not establish physical timing or live RPMsg behavior.
