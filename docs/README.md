# Software documentation index

This page is the starting point for software documentation in the repository.

## For a new contributor

1. Read the root [README](../README.md) for the project map and operational boundary.
2. Read [CONTRIBUTING](../CONTRIBUTING.md) for branches, pull requests, reviews, and testing.
3. Read [system boundaries](architecture/system-boundaries.md) before choosing where code belongs.
4. Open the README for the subsystem you are joining.
5. Check current scope, owners, and dates in the [Confluence Software 2026–2027 page](https://confluence.cornell.edu/spaces/crt/pages/763265299/Software+2026-2027).

## Repository documents

| Document | Use it for |
| --- | --- |
| [System boundaries](architecture/system-boundaries.md) | Which system owns a behavior and where responsibilities stop |
| [Interface governance](interfaces/README.md) | Protocols, schemas, compatibility, and interface-change evidence |
| [Development readiness](operations/development-readiness.md) | Evidence and signoff required before operational use |
| [FSW](../fsw/README.md) | Shared Hybrid/Liquid flight-software home |
| [Fill Station](../fill-station/README.md) | Pad-side fill, vent, purge, and safing software |
| [Ground Station](../ground-station/README.md) | Operator UI and ground-platform software |
| [Air-brakes](../airbrakes/README.md) | Air-brake controller and simulation |
| [RATS](../rats/README.md) | Radio Antenna Tracking System software |
| [BLiMS](../blims/README.md) | BLiMS software and integration assets |
| [Payload](../payload/README.md) | Payload-to-FSW integration requirements |
| [Nix infrastructure](../nix/README.md) | Reproducible development and deployment configuration |

## Where information belongs

- **Confluence** records team scope, project owners, milestones, design-review material, and evolving planning decisions.
- **This repository** records implementation, versioned interfaces, contribution rules, test evidence, and operational-readiness records tied to a revision.
- When a code or interface decision changes planned scope, update both locations and link the decision from the pull request.
