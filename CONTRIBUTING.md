# Contributing

Create focused pull requests with a linked issue, meeting decision, or design-review context. Run `sh tests/test_repository_layout.sh` before requesting review.

For Hybrid/Liquid work, label the change `Hybrid`, `Liquid`, or `both` in the pull request description. This applies to both FSW and Fill Station software. The two systems may use different separation mechanisms, but the pull request must identify the boundary and include validation for every affected variant.
## Branch workflow

`main` is the integration branch. Do not develop directly on `main` or push directly to it. Every person or project group works on a short-lived branch and opens a pull request when ready.

Use names that identify the system and purpose, for example:

```text
fsw/liquid-ereg-control
fsw/hybrid-fram-repair
fill/liquid-local-fill
ground/device-controls-ui
docs/interface-governance
```

The branch name describes the work, not the vehicle. Do not create permanent `hybrid` or `liquid` branches. Use one branch for one coherent change; share a branch only when a group is implementing one tightly coupled change.

### Start work

Always begin from the latest `main`:

```bash
git switch main
git pull --ff-only origin main
git switch -c fsw/liquid-ereg-control
```

### Before opening a pull request

Run the repository check, formatting check, and status check:

```bash
sh tests/test_repository_layout.sh
git diff --check
git status --short
```

For FSW or Fill Station changes, also run every affected Hybrid and Liquid build or deployment validation. If one variant is unavailable, record why and the follow-up validation in the pull request.

Update your branch before final review:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

Use `--force-with-lease` only when rebasing your own branch. Never force-push `main`.

### Pull-request checklist

Include the system changed, responsible reviewer, `Hybrid`, `Liquid`, or `both`, the behavior or interface changed, validation run, known limitations, and follow-up work. Do not merge a change that only compiles when operational-readiness evidence is still missing.

### Review and merge

The responsible subsystem owner reviews behavior and interfaces. The software lead or repository maintainer merges after required reviews and the `repository-contract` check pass. Resolve comments in the branch, rerun checks, and wait for new CI results. Prefer squash merge for a focused change, then delete the branch and start the next change from updated `main`.

### Changes affecting multiple systems

Document the dependency and use one coordinated pull request or merge changes in a safe order with a temporary compatibility path. Do not merge a producer contract change while its consumers are known to be broken.


## Changes to interfaces

For a command, telemetry, schema, hardware boundary, or configuration contract change:

1. Identify the owner of every affected system.
2. Update the interface documentation and compatibility note in the same pull request.
3. Add or update a fixture or automated test.
4. Obtain review from each affected system owner.

## Flight and operations changes

Changes that affect FSW, Fill Station control, operational procedures, or ground-command behavior require review from the responsible system owner. A merge does not approve use at a test or launch; record the required evidence under `docs/operations/`.
