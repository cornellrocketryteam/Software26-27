# Cornell Rocketry Software 2026–2027

This repository is the shared home for flight, pad, ground, and supporting software for the 2026–2027 program.

Flight software remains one shared Hybrid/Liquid codebase. Vehicle-specific behavior is selected through reviewed build-time configuration; neither configuration may silently inherit a safety or actuator change intended only for the other vehicle.

## Hybrid and Liquid development rule

This requirement applies to **both Flight Software and Fill Station software**:

- Hybrid and Liquid must be able to evolve in the same repository without accidentally using the other vehicle's hardware, commands, sensors, sequencing, or safety behavior.
- The two systems may solve that separation differently. FSW will normally use compile-time vehicle configuration; Fill Station may use a separate service, device, or deployment configuration when that better matches its Linux and pad hardware.
- A change is complete only when its owner records which vehicle(s) it affects, keeps the other vehicle's build or deployment valid, and adds the appropriate variant-specific test or validation evidence.
- Do not create permanent `hybrid` and `liquid` branches. Keep shared behavior together and make vehicle differences explicit in code and configuration.

See the [documentation index](docs/README.md) for the contributor starting point and the documentation for each subsystem.

## Project map

| Directory | Purpose |
| --- | --- |
| `fsw/` | Shared Hybrid/Liquid flight software |
| `fill-station/` | Pad-side Fill Station software |
| `ground-station/` | Ground Station UI and platform software |
| `shared/proto/` | Versioned Ground Station/Fill Station contracts |
| `airbrakes/` | Air-brake controller and simulation |
| `rats/` | Rotational Antenna Tracking System |
| `blims/` | BLiMS software |
| `payload/` | Payload integration software |
| `nix/` | Reproducible development and deployment infrastructure |
| `docs/` | Architecture, interfaces, and operational-readiness records |

## Start here

Read the README for the subsystem you are changing, then check the current project scope in Confluence.

Run the repository check before opening a pull request:

```sh
sh tests/test_repository_layout.sh
```

## Operational boundary

Code in this repository is not approved for operational use merely because it builds or merges. Follow the evidence and signoff requirements in [development readiness](docs/operations/development-readiness.md).
