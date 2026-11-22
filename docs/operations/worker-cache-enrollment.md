# Enroll the station build worker and publication account

This is the later hardware-session procedure. Source support is implemented;
actual account enrollment and end-to-end acceptance remain pending. No commands
in this guide have been executed against the mini PC for this checkpoint.

Use three distinct identities: developer-to-worker, developer-to-publication,
and the mini-PC-to-board deployment key. Existing contributor keys already grant
normal administrative login separately: Kaleb's key is present in the shared
`nix/mixos-modules/fill-station-base/authorized_keys`, which is also loaded for
`ground-admin`. No duplicate key entry is required. Live login with his private
key remains an operator check; worker/publication grants are explicit role lists.
The mini-PC-to-board identity is covered by
[board deployment SSH](ground-station-accepted-system.md). The public cache signing
identity is separate again; its secret stays root-owned on the mini PC.

## Prepare developer identities locally

On each developer's own computer, without sudo:

```sh
install -d -m 700 "$HOME/.ssh"
for role in worker publication; do
  key="$HOME/.ssh/crt-station-$role"
  if [ ! -e "$key" ] && [ ! -e "$key.pub" ]; then
    ssh-keygen -t ed25519 -N '' -C "crt-station-$role" -f "$key"
  fi
  ssh-keygen -l -f "$key.pub"
done
```

Inspect an existing partial pair rather than deleting/regenerating it. These are
noninteractive machine-role keys: the explicit no-agent connection mode cannot
prompt for a passphrase. Keep private files local with mode 0600; send only `.pub`
files for enrollment. Do not use a cache signing secret as an SSH identity.

Independently verify the mini PC's SSH host key and record a known-hosts file for
`192.168.1.206`. Do not accept a fresh keyscan as verification. Worker/publication
endpoints ignore ordinary SSH aliases/config; their explicit user/address, pin
and identity file are configured below.

## Prepare the one-time site module

After validating the real daemon containment using the
[maintenance validation procedure](build-daemon-validation.md), prepare a local
site directory containing `worker.pub`, `publication.pub` and this `site.nix`.
The public files must contain the exact intended developer keys. Multiple
reviewed developers may be added explicitly to the appropriate lists later.

```nix
{ lib, ... }:
{
  groundStation = {
    fieldMode = false;
    builder = {
      enable = true;
      validated = true; # Only after actual normal-daemon containment acceptance.
      remote = {
        enable = true;
        workerId = "crt-um560-worker-v1";
        authorizedKeys = [ (lib.removeSuffix "\n" (builtins.readFile ./worker.pub)) ];
      };
    };
    cache = {
      enable = true;
      signingKeyFile = "/var/lib/ground-station/cache-signing/cache.sec";
      ingestion = {
        enable = true;
        archiveId = "crt-um560-archive-v1";
        trustedDeveloperAccessReviewed = true;
        authorizedKeys = [ (lib.removeSuffix "\n" (builtins.readFile ./publication.pub)) ];
      };
    };
  };
}
```

The IDs above are proposed site values. Inspect any existing archive identity
before choosing its ID; do not rename an existing archive to match this example.
`ground-builder` stays an untrusted Nix peer. `ground-cache` is deliberately a
trusted developer importer with effectively administrative Nix access; enroll
only the intended publication keys. The public-only module never contains a
private key or changes the normal field-services profile by itself.

From this checkout, on a compatible prepared builder, the site generation can be
built separately from normal field operation:

```sh
export CRT_STATION_SITE="$HOME/station-site/site.nix"
nix build --impure --no-write-lock-file --no-update-lock-file \
  --out-link result-station-enrollment --expr '
    let f = builtins.getFlake (toString ./.);
        site = builtins.toPath (builtins.getEnv "CRT_STATION_SITE");
    in (f.nixosConfigurations.ground-station-um560-services.extendModules {
      modules = [ site ];
    }).config.system.build.toplevel'
```

This is one-time site enrollment, not the routine build command. It requires the
existing inputs/toolchain or their prepared offline transfer. A field station
with ordinary builds disabled cannot bootstrap this through its normal daemon;
prepare/transfer it through the accepted maintenance procedure first. Build does
not activate it. Test-activate the reviewed generation, keep the previous known-
good boot generation, and check services before making it persistent. No ARM
binfmt capability or global SSH builder is enabled by this native-x86 site module.

## Configure the developer CLI

Merge these sections into `STATE/config.json` (the exact default state path is in
[the CLI guide](../../tools/platform/README.md)). Replace paths and IDs with actual
accepted values. JSON paths are absolute: literal `$HOME`/`~` are not expanded.

```json
{
  "policy": { "preferStation": false },
  "station": {
    "store": "ssh-ng://ground-builder@192.168.1.206",
    "sshTarget": "ground-builder@192.168.1.206",
    "knownHosts": "/absolute/path/to/verified_station_known_hosts",
    "identityFile": "/absolute/path/to/.ssh/crt-station-worker",
    "workerId": "crt-um560-worker-v1",
    "platforms": ["x86_64-linux"],
    "validated": false,
    "minFreeBytes": 100000000000
  },
  "cache": {
    "store": "ssh-ng://ground-cache@192.168.1.206",
    "sshTarget": "ground-cache@192.168.1.206",
    "knownHosts": "/absolute/path/to/verified_station_known_hosts",
    "identityFile": "/absolute/path/to/.ssh/crt-station-publication",
    "receiptArchiveId": "crt-um560-archive-v1"
  }
}
```

`identityFile` pins a local private-key file, not its contents. For that endpoint
all health/RPC/store connections use it with agent use/forwarding disabled. The
file must be nonempty, regular, owned by the current user and have no group/other
permissions; symlinks and SSH path-expansion characters are refused. An invalid
configured identity fails before transport rather than falling back to an agent.
Omitting the setting preserves existing agent/default-key behavior.

Source reference: [Nix 2.34.9 SSH transport](https://github.com/NixOS/nix/blob/2.34.9/src/libstore/ssh.cc)
parses `NIX_SSHOPTS` as shell-split arguments. The host tests also exercise the
installed Nix binary against a capture-only SSH stub, including paths with spaces.
This checks argument forwarding, not remote authentication or a successful build.

## Integrated acceptance when back at the hardware

1. Close forwarded-agent sessions. From a fresh developer session, run
   `./scripts/platform check --station --build-platform x86_64-linux`. Confirm the
   worker ID, maintenance mode, free-space reserve and available platform. Client
   `validated:false` remains until the reviewed checks pass; the health command
   does not grant build permission or prove containment.
2. Confirm only the intended keys access each forced endpoint; an administrative
   shell, forwarding and cross-role key use must be denied. Check the normal
   daemon cgroup limits under real compiler load, not just the SSH launcher.
3. After those checks, explicitly set client `station.validated:true`. Run
   `./scripts/platform build fill-station --vehicle hybrid --builder station`.
   The default artifact is OSPI. Verify download signatures, local roots, archive
   receipt and matching source/profile/worker identities before deploying.
4. Exercise interrupted transfer/release acknowledgement, `transfer-resume`,
   station outage/local fallback, retained publication and later `cache-sync`.
   Use the dedicated worker key for build/import/retention and the publication
   key for archive copy/receipts throughout. Neither requires an agent.
5. Repeat the signed-cache read and explicit board FIT deployment/boot checks,
   observing camera/telemetry/operator-service continuity and preserving local
   offline boot. Only then consider station-first routing and boot persistence.

Pending transfer journals retain the original endpoint/key path. Do not remove
or rotate that identity until transfers finish, and do not edit journals to move
unfinished work to a different worker/archive. Missing credentials leave roots
and pending publication retained. HTTP cache reads are independent of both SSH
roles and continue to use signature verification.
