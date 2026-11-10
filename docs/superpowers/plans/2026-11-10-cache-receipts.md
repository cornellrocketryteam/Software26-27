# Durable cache receipts implementation plan

**Goal:** Turn a copied release into an acknowledged archived release without
losing local outputs on failed, partial or repeated publication.

**Architecture:** Keep `nix copy` as transport. Send the exact manifest bytes to
one fixed receiver command over the same pinned SSH endpoint. The receiver
validates identity and paths, verifies the imported closure, registers GC roots,
and persists an immutable receipt before replying. The client validates the
receipt against its configured archive identity and records acknowledgement.
Retain local release roots after acknowledgement; automatic pruning is out of scope.

**Tech stack:** Existing Python stdlib CLI/state primitives, Nix CLI/store,
OpenSSH forced commands, opt-in NixOS configuration and unittest fixtures.

Status: implemented and reviewed; live station acceptance remains outstanding.

## Constraints and protocol

- No deployment, reboot, automatic GC or field build enablement.
- Use protocol 1; receiver SSH command is exactly `crt-platform-cache-receive-v1`.
- Request is one bounded JSON object: `protocol`, `releaseId`, `manifestSha256`,
  `manifestBase64`, `storePaths`. Hash the original decoded bytes, not reserialized JSON.
- Receipt binds `protocol`, `releaseId`, `manifestSha256`, sorted `storePaths`,
  `archiveId`, `roots`, and `retained: true`. Roots are server paths associated
  with each requested store path. Client pins `cache.receiptArchiveId` explicitly.
- Validate release IDs and Nix top-level store paths before filesystem changes.
  Bound manifest/request sizes and reject malformed or conflicting records.
- Crash/retry with the same manifest repairs missing roots and completes the
  archive. Reusing an ID with other content fails. No reply before durable writes.
- A failed receipt exchange leaves the record pending. One atomic record change
  persists acknowledgement; recovery recognizes it without deleting release roots.
- Ingestion is disabled by default. Enabling a daemon-trusted SSH importer grants
  administrative Nix capabilities and requires explicit review and public keys.
  Keep signing secrets runtime-only and unavailable to the importing account.

## Tasks

1. [x] Add failing receiver tests for exact-byte identity, invalid paths/digests,
   duplicate IDs, failed verification/root registration, replay and interruption.
   Implement `tools/platform/receipts.py` and `tools/platform/receiver.py`.
   Receiver CLI accepts `--state-dir` and `--archive-id`; only stdin carries requests.
2. [x] Add failing client tests for matching and forged receipts, transport failure,
   duplicate sync, concurrent sync and acknowledgement recovery. Extend bounded
   subprocess input support, `cache.py`, configuration and local status.
3. [x] Package `crt-platform-cache-receive-v1`; add an opt-in NixOS ingestion module
   with reviewed trusted-developer access, fixed SSH commands and explicit keys.
   Extend Nix configuration contracts, retaining field/build/cache defaults.
4. [x] Run host integration tests with fake Nix/store/SSH, Nix evaluation and a
   packaged receiver check. Review the protocol and failure paths independently.
5. [x] Update the CLI guide, foundation guide and main acceptance checklist with
   current behavior and remaining live signing, LAN, restart/GC acceptance.
   Save a local commit after checks pass.

Review fixes include repeating file/directory durability barriers when a prior
attempt stopped after rename, rejecting derivation and absent-output requests
before realization, and preserving a new local build's success when an unrelated
old queue entry is corrupt. Fault tests reproduce those conditions. The packaged
receiver also completed a real local-Nix exchange against the existing FIT.
All 73 host tests, NixOS module contracts, repository layout and documentation-link
checks passed. The receiver package built and its exported flake attribute evaluated.

Host tests establish implementation behavior, not a deployed station, trusted
cache substitution or recovery from actual power loss. Those remain live tests.
