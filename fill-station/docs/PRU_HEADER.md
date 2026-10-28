# PRU, expansion and MCU header pins

Pinmux and Rust wiring come from the two JSON profiles. Start with [the hardware editor workflow](DTBO_BUILDER.md).

- Profiles: `fill-station/hardware/profiles/{liquid,hybrid}.json`
- Header/ball/function inventory: `fill-station/hardware/board-pins.json`

The inventory uses physical, connector-local pin numbers (`PRU:15`,
`EXPANSION:3`, `MCU:21`), not Raspberry Pi BCM numbers. Its routing source is
TI SPRUJ64 tables 4-20 through 4-22 and SysConfig AM64x ALV data. Confirm the
board schematic/revision before wiring. Unlisted pads and special board-control
signals are protected; the inventory is not a license to claim every SoC ball.

## PRU header

PRG0_PRU0_GPO0–19 and PRG0_PRU1_GPO0–17 can be ordinary GPIOs. The default
profiles retain the existing test input on pad 0x164 (GPIO1_1) and idle the
other available signals as input pull-downs. PRG0_MDIO0 signals on this header
are also inventoried. PRG0_PRU1_GPO18/19 are Ethernet MDIO signals and remain
protected, as do PRG1 Ethernet pads.

The dedicated I2C pins 6/8 are main I2C0 SCL/SDA, shared with the board and
40-pin connector. Liquid uses these as an always-enabled shared I2C0 bus; QD is disabled.
Hybrid retains QD stepper ENA on pin 6 and keeps I2C0 disabled.
Disconnect the former QD enable wire from pin 6 before using Liquid I2C0. Native I2C cannot be arbitrarily
assigned to the other PRU GPO pads. Use TI's actual alternate-function choices.

## Expansion and MCU headers

The 40-pin connector exposes I2C2 on pins 3/5 (SDA/SCL), already used by the
sense board. Several pads named SPI are configured as GPIO for existing
components. SPI protocol support is outside this change.

The MCU connector exposes MCU I2C0 on pins 21/24 (SDA/SCL) and MCU I2C1 on
pins 16/22. The translator enables the selected MCU controller automatically
when its full valid SCL/SDA pair is assigned. Linux owns these signals in this
workflow; coordinate any future R5/M4 firmware use.

For unused pins, assigning a device connection in the editor releases its
idle input hog after rebuilding and rebooting. The ordinary Rust/libgpiod
request sets active GPIO direction and value. See the main workflow for idle
exceptions, fixed I2C adapter numbers, application mappings and build checks.
