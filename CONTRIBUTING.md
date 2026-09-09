# Contributing

Create focused pull requests with a linked issue, meeting decision, or design-review context. Run `sh tests/test_repository_layout.sh` before requesting review.

## Changes to interfaces

For a command, telemetry, schema, hardware boundary, or configuration contract change:

1. Identify the owner of every affected system.
2. Update the interface documentation and compatibility note in the same pull request.
3. Add or update a fixture or automated test.
4. Obtain review from each affected system owner.

## Flight and operations changes

Changes that affect FSW, Fill Station control, operational procedures, or ground-command behavior require review from the responsible system owner. A merge does not approve use at a test or launch; record the required evidence under `docs/operations/`.
