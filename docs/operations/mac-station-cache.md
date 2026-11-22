# Optional station cache on the Mac

The station's signed read cache, reboot recovery, outage recovery and Mac LAN
downloads are operator-confirmed. The real Liquid OSPI bundle passed all four
SHA256SUMS entries after its Mac download. Remote builds and uploads remain off.

## Install on this Mac

The local public cache identity is prepared outside Git in
`~/.config/cornell-rocketry/ground-station/client-cache.json`. It contains the
verified URL/public signing key and accepted OSPI verification path. It contains
no private key. Other developers must obtain and verify the public identity
through the already pinned station SSH connection before making their own file.
Do not copy the private station key.

From the repository on the Mac:

```sh
./scripts/configure-station-cache show
./scripts/configure-station-cache install
```

Installation needs the Mac administrator password. It adds one managed block to
`/etc/nix/nix.custom.conf`, backs up the prior file as a root-only timestamped
file, then restarts `systems.determinate.nix-daemon`. It does not edit
Determinate's generated `nix.conf`, remove existing caches/keys, expand
`trusted-users`, change FlakeHub login or start the Linux builder/Docker.
Run this between builds because restarting the daemon can interrupt a build.

The station gets cache priority 20 and one HTTP attempt. Nix signatures remain
required and its public key is added alongside official keys. Cache reads do not
upload outputs or permit station-side builds.

## Offline behavior and timeout scope

Connection establishment is limited to 3 seconds and a stalled transfer to
15 seconds. Nix exposes these two settings globally: they also affect official
HTTP caches, not only the station. They are per request, not an overall build
deadline. The station's retry-attempts setting is per cache. A live Nix test
against a deliberately stalled loopback cache verified the timeout mechanism;
the 2-second test timeout returned in about 2.07 seconds, with no LAN probe.

`fallback = true` permits local building when substitution fails. Existing other
caches remain available; a cache outage does not turn off signature checking.
Building without WAN still requires all needed sources/tools already present.
It does not manufacture missing inputs. The cache shares matching derivations;
x86 station tools and ARM Mac/Linux-builder tools can differ.

## Verify the installed configuration

Connect the Mac to the station LAN, then run:

```sh
./scripts/configure-station-cache verify
```

This checks system-configured public trust, creates an empty disposable store
and asks Nix to realize the accepted OSPI path using its configured substituters.
It supplies no per-command cache URL or public key. Builds are disabled with
zero jobs and no builders. All four OSPI checksums must pass; the disposable
store is removed afterwards. Existing copies in the normal Mac store cannot
make this test pass accidentally. Nothing is flashed or activated.

Configuration rendering, idempotence, backup/removal, unsafe-file rejection and
the verification command are covered by host tests. Real Nix parsed the candidate
settings and retained official caches/keys and root-only trusted users. Privileged
installation and the fresh-store LAN check still require the operator to run
the commands above; they have not been performed by the agent.

## Undo

```sh
./scripts/configure-station-cache remove
```

This removes only the owned block and restarts the Mac daemon. Prior custom
settings remain. Backups are root-only because an existing custom file could
contain other private settings; do not paste their contents into chat.

The cache URL and public identity are local workstation configuration. No secret
signing key or developer credential is added to this repository. FlakeHub source,
cache and CI retirement remains a later gate in the build/deployment rollout.

Sources: [Determinate custom configuration](https://docs.determinate.systems/determinate-nix/)
and [Nix HTTP cache settings](https://nix.dev/manual/nix/2.35/store/types/http-binary-cache-store.html).
