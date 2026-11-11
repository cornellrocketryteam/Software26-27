# Signed cache acceptance implementation plan

**Goal:** Verify the existing NixOS cache with real HTTP signing, isolated client stores, negative trust tests and retained artifacts during cache outage.

**Architecture:** Boot an isolated x86 guest using the actual ground-station profile, Harmonia and nginx `/cache/` proxy. Generate disposable keys privately on the guest disk. Import ordinary input-addressed fixture closures into fresh client stores; no WAN, FlakeHub, builds or production keys participate at runtime.

**Tech stack:** Locked NixOS/QEMU, Harmonia, Nix local stores, Python standard library.

## Constraints

- Physical PC inventory proceeds through user-run local commands; it is on a separate offline network. Do not attempt remote connections.
- No installation, disk changes, production keys, deployment or Git push.
- No global GC. Every collector invocation must explicitly target a disposable client store beneath `/var/lib/ground-cache-vm/clients`.
- Clear client signing secrets and inherited trust; retain `require-sigs=true`. Fixtures must not be content-addressed, since those have different trust semantics.
- Keep workers, telemetry and commanding disabled in this cache-specific fixture, and keep `/readyz` at 503.
- Existing administrator root access inside the guest does not count as SSH ingestion/two-developer acceptance.

## Task 1: Real cache trust and retention test

Files: create `tests/platform/test_cache_vm.nix` and `tests/platform/cache_vm_check.py`; modify production modules only for an observed failure, with focused regression coverage.

- [x] Reuse the existing VM runner's console normalization and no-NIC setup. Enable the production cache with a runtime key path; generate a persistent fixture key pair and an unrelated test key pair privately before Harmonia starts.
- [x] Prepare small ordinary derivation outputs with a dependency and an unretained control object. Assert HTTP metadata contains the expected signature and no content-addressing exemption.
- [x] Copy the signed closure through nginx into an empty local store with only the fixture public key trusted. Verify physical client contents and closure references.
- [x] Use separate empty client stores to reject an unrelated trusted key and a deliberately corrupted HTTP metadata signature. Require signature-specific errors, not transport failures; assert no fixture was accepted.
- [x] Register a retention root in the disposable positive client. Copy an unrooted control, collect only that store, and prove the retained closure survives while the control is removed.
- [x] Stop the cache socket/service and prove the existing client artifacts and local UI stay usable, while a fresh cache fetch fails. Restart the cache and prove a new client reuses the artifacts without compiling.
- [x] Cold-restart the guest, verify unchanged public trust and unattended cache startup, and fetch into another empty client using the original public key.
- [x] Run the explicit VM acceptance and appropriate module checks; record exact scope and any failures before making production fixes.

## Task 2: Documentation and local commit

- [x] Update `docs/operations/build-cache.md`, the main implementation checklist and architecture status with VM evidence separately from physical LAN, ingestion, backup and worker acceptance.
- [x] Verify whitespace, repository layout and document links; commit the tested increment locally.

Manual command:

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = "aarch64-darwin"; }; in import ./tests/platform/test_cache_vm.nix { inherit pkgs; }' -o /private/tmp/ground-cache-vm --option timeout 2400 -L
```

References: [Nix copy signature checks](https://nix.dev/manual/nix/2.28/command-ref/new-cli/nix3-copy.html), [local store root isolation](https://releases.nixos.org/nix/nix-2.30.5/manual/store/types/local-store.html), and the repository's locked Harmonia module and cache configuration. A passing VM does not establish the physical PC's network reachability, installed keys or production data retention.

## Observed evidence

The final exact test passed in 180 seconds with exit status zero. Output:
`/nix/store/mk7ffc94afxzbharjvchrh51nya6k5rx-vm-test-run-ground-signed-cache`.
All trust, isolated GC, outage/reconnection and cold-restart cases above passed;
both negative clients retained no fixture paths. The existing cache module
required no production changes. All 121 foundation and 60 telemetry module
contracts passed separately. The tampering fixture supports both HEAD and GET;
an initial missing-HEAD HTTP 501 failed the test rather than being misclassified
as successful signature rejection.

Physical handoff: the user confirmed the PC IP but reports a separate offline
network and unknown SSH setup. No remote connection was attempted. Local console
inventory starts with `cat /etc/os-release`; its output is still pending.
