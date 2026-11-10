# Software documentation index

This page is the starting point for software documentation in the repository.

## For a new contributor

1. Read the root [README](../README.md) for the project map and operational boundary.
2. Read [CONTRIBUTING](../CONTRIBUTING.md) for branches, pull requests, reviews, and testing.
3. Open the README for the subsystem you are joining.
4. Check current scope, owners, and dates in the [Confluence Software 2026–2027 page](https://confluence.cornell.edu/spaces/crt/pages/763265299/Software+2026-2027).

## Repository documents

| Document | Use it for |
| --- | --- |
| [Ground-platform architecture](architecture/ground-platform.md) | Approved NixOS startup, cache/build/offline workflow, and implementation boundaries |
| [Ground-platform checklist](superpowers/plans/2026-11-09-ground-platform.md) | Implementation order and measurable acceptance criteria |
| [Build/cache CLI](../tools/platform/README.md) | Current commands, routing, source snapshots, release retention and pending publication |
| [Ground-station NixOS foundation](../nix/nixos-configurations/ground-station/README.md) | Existing targets, configuration gates, and pending hardware/service work |
| [Fill-station deployment](operations/fill-station-deployment.md) | Current SD/OSPI build, network update, and manual recovery procedure |
| [Development readiness](operations/development-readiness.md) | Evidence and signoff required before operational use |
| [FSW](../fsw/README.md) | Shared Hybrid/Liquid flight-software home |
| [Fill Station](../fill-station/README.md) | Pad-side fill, vent, purge, and safing software |
| [Ground Station](../ground-station/README.md) | Operator UI and ground-platform software |
| [Air-brakes](../airbrakes/README.md) | Air-brake controller and simulation |
| [RATS](../rats/README.md) | Radio Antenna Tracking System software |
| [BLiMS](../blims/README.md) | BLiMS software and integration assets |
| [Payload](../payload/README.md) | Payload-to-FSW integration requirements |
| [Nix infrastructure](../nix/README.md) | Reproducible development and deployment configuration |
| [Linux kernel configuration](../nix/linux-kernel.md) | Edit the fill-station kernel using Linux or the Darwin Linux builder VM |

## Where information belongs

- **Confluence** records team scope, project owners, milestones, design-review material, and evolving planning decisions.
- **This repository** records implementation, contribution rules, test evidence, and operational-readiness records tied to a revision.
- When a code or interface decision changes planned scope, update both locations and link the decision from the pull request.
