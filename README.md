# Cornell Rocketry Software 2026–2027

This repository is the shared home for flight, pad, ground, and supporting software for the 2026–2027 program.

Flight software remains one shared Hybrid/Liquid codebase. Vehicle-specific behavior is selected through reviewed build-time configuration; neither configuration may silently inherit a safety or actuator change intended only for the other vehicle.

## Project map

| Directory | Purpose |
| --- | --- |
| `fsw/` | Shared Hybrid/Liquid flight software |
| `fill-station/` | Pad-side Fill Station software |
| `ground-station/` | Ground Station UI and platform software |
| `shared/proto/` | Versioned Ground Station/Fill Station contracts |
| `airbrakes/` | Air-brake controller and simulation |
| `rats/` | Radio Antenna Tracking System |
| `blims/` | BLiMS software |
| `payload/` | Payload integration software |
| `nix/` | Reproducible development and deployment infrastructure |
| `docs/` | Architecture, interfaces, and operational-readiness records |

## Start here

Read [system boundaries](docs/architecture/system-boundaries.md), then the README for the subsystem you are changing.

Run the repository check before opening a pull request:

```sh
sh tests/test_repository_layout.sh
```

## Operational boundary

Code in this repository is not approved for operational use merely because it builds or merges. Follow the evidence and signoff requirements in [development readiness](docs/operations/development-readiness.md).
