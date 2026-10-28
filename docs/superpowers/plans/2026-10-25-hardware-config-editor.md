# Fill-station hardware configuration editor implementation plan

Approved scope: two complete JSON profiles drive a local browser editor, Rust wiring and Linux pinmux. This replaces the earlier SysConfig workflow. No live hardware control or GUI build button.

## Constraints

- Preserve initial Liquid/Hybrid wiring and exact register settings: 24 active and 61 idle pads.
- Support PRU54, expansion40 and MCU28 connectors; lock board-owned/boot/Ethernet resources.
- Disabled devices release pins to idle input/pull-down, with hardware-specific no-pull exceptions.
- Existing roles are optional; commands requiring missing roles reject before side effects.
- Added supported instances initialize and participate in shutdown, without new application bindings.
- Availability metadata is additive; legacy messages retain prior interpretation.
- Preserve unrelated local OSPI/bootloader/test-harness work. No commits, flash, or actuation.

## Work allocation and interfaces

Primary owns versioned JSON profiles/catalog/compiler, Nix integration, existing station UI and final integration.
Rust subagent owns generated hardware initialization, optional role registries, command preflight, shutdown and telemetry producers.
GUI subagent owns the loopback stdlib server, offline browser assets, physical header diagrams and server tests.
Review subagent owns independent review and a bounded downstream ingestion/migration task.

The compiler API is `load_profile(name)` and `compile_profile(profile)`, returning pins, overlay, report, expectations and runtime descriptors. Its CLI accepts `--profile liquid|hybrid|none --output DIR` and emits `hardware_config.rs` for Cargo plus device-tree and JSON artifacts. Runtime devices contain resolved GPIO chip/line, I²C adapter/address or PWM platform/channel; pin routing stays in the shared compiler.

The editor uses GET bootstrap/profile, POST validate and PUT profile with revision checking. Saves are atomic, token-protected and limited to two profile files.

## Implementation checklist

- [x] Check status and pull safely before implementation.
- [x] Capture existing register expectations and migrate the two profiles.
- [x] Write compiler tests, observe missing implementation failure, implement validation/generation.
- [x] Implement editor, request protections, stale-save handling and browser workflow.
- [x] Implement Rust typed registries, generated initialization, disabled-role command preflight and all-instance shutdown.
- [x] Add independent ADC validity, WS metadata, protobuf tags64–66 and CSV missing values.
- [x] Update existing ground-station controls, ingestion, database migration and affected dashboard displays.
- [x] Replace TI CLI build dependency with shared JSON compiler and add Nix editor app.
- [x] Replace CLI-dependent merged-DTB tests and update usage documentation.
- [x] Complete final integrated checks/review and record actual results separately.

Validation: both default profiles match the original register fixture; both native overlays build; real Linux 6.18 DTB merge tests pass; Liquid/Hybrid host Cargo tests and ARM64 musl checks pass; development-mode tests pass; conflicting features reject; editor HTTP and real-browser workflows pass; isolated PostgreSQL migration tests pass; Node availability regressions and TypeScript/Vite build pass. Full FIT derivations evaluate, but the complete image build failed while Determinate Native Linux Builder initialized (deadline elapsed). No image was linked or flashed and no physical actuation occurred. Ground-station npm lockfile was already inconsistent; verification used npm install --package-lock=false without modifying it.

## Tools and acceptance

Use Python unittest, Cargo host tests and ARM64 Linux checks, Nix overlay builds and image derivation evaluation, clang/dtc/fdtoverlay/fdtget/fdtput, Node availability tests, TypeScript/Vite build, isolated PostgreSQL migration tests and CUA browser testing. Validate both profile defaults, disabled pins, new MCU I²C, conflicts, all-instance shutdown, Launch rejection before forwarding, partial ADC data, legacy telemetry, stale saves and real merged-board register expectations. Full image build depends on an available Linux builder; physical validation remains separate.
