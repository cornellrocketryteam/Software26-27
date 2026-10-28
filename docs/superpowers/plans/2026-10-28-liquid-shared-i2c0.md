# Liquid shared I2C0 implementation

Approved scope: disable Liquid QD, expose PRU6/8 as always-on shared I2C0, preserve Hybrid exactly, keep existing ADS1015 devices on I2C2, and add no new ADC type.

1. Capture Hybrid operational outputs; add failing compiler policy tests.
2. Add native board routes and Liquid-only required shared-bus policy, board address reservations, and profile-aware FIT checks.
3. Update the editor to show ownership even with no external devices and prevent removing/replacing the shared bus.
4. Verify compiler, real merged kernel DTBs, Rust Liquid/Hybrid, native overlay builds, and browser behavior. Update both permanent guides.

Tools: Git inspection, Python unittest, Cargo, Nix, clang/dtc/fdtoverlay/fdtget and CUA browser inspection. No delegation is needed for this bounded change. No flashing, actuation or commits. Preserve unrelated working-tree changes.

Physical prerequisite: isolate the former QD enable wire from PRU6 before powering the rebuilt Liquid configuration. Board PROC100A(002) uses the TPS6522053 PMIC; reserve 0x30 and EEPROM 0x51, plus 0x50 for expansion EEPROM use. Preserve base device-tree children; do not invent PMIC/regulator nodes.
