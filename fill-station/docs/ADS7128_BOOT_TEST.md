# ADS7128 serial boot test

This configuration uses the integrated Nix layout under
`nix/mixos-configurations/fill-station-liquid-ads7128-test.nix` and the same
Liquid executable as the normal image. The diagnostic exits into an ADC-only
path before normal logging, hardware setup, MQTT, or actuator initialization.

Build the dedicated Liquid bench image from the repository root:

```sh
nix build .#mixosConfigurations.fill-station-liquid-ads7128-test.config.system.build.sdImage --out-link result-sd-ads7128-test
```

Boot that SD image with the serial terminal open at **115200 baud, 8N1**.
The test replaces the normal fill-station process in this image, so normal
actuator initialization, commands and telemetry are unavailable. Use the usual
Liquid image to return to normal operation.

With power off, connect SCL to PRU pin 6, SDA to PRU pin 8 and connect a common
ground. Disconnect the former QD enable wire from pin 6. Verify the breakout's
power requirements and I²C levels before connecting it to the board.

The preset reads one chip at 7-bit address `0x10` on `/dev/i2c-0`. TI lists
that address for unpopulated ADDR resistors and shows it in the BP-ADS7128
evaluation board guide. A different breakout or strap can select another
address. The preset does not scan the bus.

Example output (illustrative raw counts):

```text
ADS7128 0x10: CH0=0 CH1=2048 CH2=0 CH3=0 CH4=0 CH5=0 CH6=0 CH7=0
```

Expect one line per second, with all eight channels. The values are raw counts,
not volts. Test channel selection by applying two different known voltages
within the ADC's input range to two channels. Floating inputs need not read zero.
A probe error means no scan will start; check the address, wiring, power and bus.
BusyBox init restarts the diagnostic after it exits, so a probe failure can repeat.
A channel read error prints `ERROR` for that channel. The diagnostic uses the
existing driver and assumes the ADC starts in its default analog/manual mode.

On a rebuilt normal Liquid image, the same diagnostic is also available
as `/bin/fill-station --ads7128-test 0x10` from a serial shell. Prefer the
dedicated bench image when you want the normal fill-station process stopped.

## Testing the combined normal image

For the normal Liquid system, build:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.sdImage --out-link result-sd-liquid
```

The default `fill-station` configuration builds Hybrid. Both normal images
include the manual `--ads7128-test` command, but do not run it at startup.
Do not run the manual command concurrently with the normal process on the
same I2C bus; use the dedicated diagnostic image for ADC-only testing.

Max's integrated U-Boot tries `fitImage.itb` from SD first, then OSPI. It no
longer provides our earlier `boot_device` variable or `ospiboot` command.
For the first board check, boot the new SD image and capture the serial boot
log; verify the SD boot message, Linux startup, DATA state mount, SSH, and
the expected vehicle's peripherals. CSV logs now live under
`/var/log/fill-station`, persisted through the DATA partition.
DATA is now ext4 to support MixOS's persistent `/etc` overlay. Use a newly
built SD image (back up old logs first); an old FAT32 DATA card will not work
with the new state mount. The boot firmware partition remains FAT.

OSPI bundles are still available as `system.build.ospiImage` and the existing
`tools/flash-ospi.sh` supports them. With this SD-first boot order, a bootable
SD firmware partition can mask OSPI testing; the DATA-only card output is
`system.build.dataCardImage`. A new bootloader must be installed to test the
new boot flow. Building a bundle does not flash it or validate physical boot.
U-Boot networking is disabled in this configuration; network boot is not
part of this integration.
