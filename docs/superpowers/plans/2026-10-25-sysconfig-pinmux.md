> Superseded by `2026-10-25-hardware-config-editor.md`. Historical design only.

# Liquid / Hybrid SysConfig Pinmux Implementation Plan

> Execution: implement inline in this session; no separate agents or commits are needed.

**Goal:** Use two GUI-editable SysConfig projects as the build inputs for Liquid and Hybrid Linux pinmux.

**Architecture:** A pinned TI CLI generates Linux DTSI from the selected project. A strict translator validates the assignments against a board header inventory, assigns idle states to unclaimed eligible pads, and generates controller enablement and pinctrl attachments. Existing board USB setup stays separate. Nix merges the overlay into the existing FIT image.

**Tech Stack:** TI SysConfig 1.28.1+4785, Python standard library, Nix, clang, dtc/libfdt.

## Global Constraints

- Preserve existing user changes and the existing fill station GPIO, I2C2, PWM and USB assignments.
- Two complete projects: liquid.syscfg and hybrid.syscfg, selected with fillStation.mode.
- No SPI support. Support GPIO, main/MCU I2C, main ePWM and the existing USB VBUS selection.
- Only eligible signal pads on the PRU, expansion and MCU headers may get idle states. Preserve Ethernet, reset, board-ID and other protected signals.
- Default unused eligible pads to input pull-down, except dedicated open-drain I2C pads that have no hardware internal pulls.
- Build checks are separate from hardware validation. Do not flash or actuate hardware.

## Tasks

- [x] Write failing translator tests: default idle state; main and MCU I2C; pinctrl attachment; reject protected pins, duplicate pads, unsupported SPI, incomplete buses, unknown syntax/flags and incorrect mux assignments.
- [x] Build a board inventory from TI AM64x ALV device data and the SK-AM64B header tables, including shared-header references and protected pad exclusions.
- [x] Implement the translator and run the tests until they pass. Validate complete I2C pairs and preserve generated electrical settings.
- [x] Create identical Liquid/Hybrid projects from existing assignments. Run the real TI CLI and compare the generated assignments to the previous DTSI, including pulls and input enables.
- [x] Package the pinned portable CLI with Node in Nix, using a verified one-time import from the installed official TI distribution if necessary. No host absolute paths enter the image build.
- [x] Select profiles through fillStation.mode, expose a pinmux-only build, compile both overlays, merge with the base board DTB and check register values and controller status.
- [x] Document GUI opening/saving, tool bootstrap, build selection, idle-state exceptions, protected pads, runtime device numbering and application mapping responsibilities.
- [x] Check Nix evaluation/builds and the final diff. Report environmental limits and any hardware checks that remain.

## File responsibilities

- `nix/overlays/by-name/crt/fillstation-dtbo/profiles/{liquid,hybrid}.syscfg`: complete editable projects.
- `nix/overlays/by-name/crt/fillstation-dtbo/board-pins.json`: header policy and legal GPIO/I2C/PWM mappings.
- `nix/overlays/by-name/crt/fillstation-dtbo/generate.py`: pure DTSI validation and overlay generation, with JSON audit report.
- `nix/overlays/by-name/crt/fillstation-dtbo/package.nix`: run CLI, translator, tests and dtc.
- `nix/overlays/by-name/crt/ti-sysconfig-cli/package.nix`: pinned build-time tool only.
- `tools/import-sysconfig.py`: deterministic tool import; no proprietary tool files committed.
- `tests/test_pinmux.py`: behavior tests; integration tests compile real CLI output.
- `nix/mixos-configurations/fill-station/fit/default.nix`: pair application mode and pinmux profile.
- `nix/mixos-configurations/fill-station/fit/build-fit-image.nix`: validate generated device-tree expectations after merging.
- `fill-station/docs/DTBO_BUILDER.md`: user workflow and limitations.

## Validation completed

- Pulled `kaleb_branch` with `git pull --ff-only`; already up to date.
- Preserved the pre-existing OSPI/bootloader changes and untracked test harness.
- Imported the existing official SysConfig 1.28.1+4785 portable CLI assets into the local Nix store.
- Native Darwin Nix overlay builds passed for Liquid and Hybrid, including generator tests.
- All 24 Python tests passed, including real TI CLI generation, merge with the exact Linux 6.18 SK-AM64B DTS, automatic MCU I2C enablement, and rejection of a corrupted merged pad value.
- Both reports contain 24 active assignments and 61 idle inputs. Legacy mux, input-enable, bias and drive fields match; the new TI template emits its read-only Schmitt-enable default.
- Liquid and Hybrid full image derivations evaluate with matching application/pinmux modes.
- Scoped diff whitespace checks and the existing repository-layout check passed. Pre-existing bootloader patch whitespace was left untouched.
- No full Linux image build, board flash or electrical/actuator testing was performed. Native GUI automation timed out, so GUI appearance remains unverified; saved files were validated using TI's CLI.
- New files are intent-to-add so Git-backed Nix flakes include them; contents are not staged and no commit was made.
