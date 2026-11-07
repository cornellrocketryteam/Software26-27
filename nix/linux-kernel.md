# Editing the fill-station Linux config

The SK-AM64B uses an ARM64 kernel. Its saved config is
[`packages/crt/fill-station-linux/kernel.config`](packages/crt/fill-station-linux/kernel.config).
Run the editor on Linux: either a Linux computer or the Darwin Linux builder VM
on your Mac. A remote builder does not make `nix develop` run inside the VM.

## macOS: enter the builder VM

With nixpkgs' Darwin Linux builder running and its `linux-builder` SSH alias
configured, run these commands **from your Mac's repo root**. They copy the
working tree, including uncommitted changes to tracked files:

```sh
sudo -v
git ls-files -z |
  COPYFILE_DISABLE=1 tar --exclude=.git --exclude=target --exclude=node_modules \
    -czf - --null -T - |
  sudo ssh linux-builder \
    'mkdir -p ~/Software26-27 && tar -xzf - -C ~/Software26-27'

sudo ssh -t linux-builder
cd ~/Software26-27
```

The default alias uses port 31022 and user `builder`. `sudo` is needed when the
SSH key at `/etc/nix/builder_ed25519` is root-readable only.

## Linux: open the development shell

On a Linux computer, install Nix and open your checkout. On macOS, run this
**inside the VM**. Start from the repo root in either case.

This uses the repo's pinned kernel and an ARM64 musl toolchain, with native build
tools for your Linux host (ARM64 or x86-64):

```sh
nix --extra-experimental-features 'nix-command flakes' develop --impure --expr '
  let
    f = builtins.getFlake (toString ./.);
    p = import f.inputs.nixpkgs {
      localSystem = builtins.currentSystem;
      crossSystem = {
        config = "aarch64-unknown-linux-musl";
        gcc.cpu = "cortex-a53";
      };
      overlays = [ f.overlays.default f.inputs.mixos.overlays.default ];
    };
  in p.crt.fill-station-linux.overrideAttrs (old: {
    nativeBuildInputs = (old.nativeBuildInputs or [])
      ++ [ p.buildPackages.pkg-config p.buildPackages.ncurses ];
  })
'
```

## Unpack and edit

Inside that shell, unpack the selected source into a writable directory and apply
the package's source patches. Copy the repo's `kernel.config` to `build/.config`,
run `olddefconfig` to resolve it for this kernel version, then open `menuconfig`:

```sh
repoRoot=$PWD
kernelWork=$(mktemp -d /tmp/fill-station-kernel.XXXXXX)
tar -xf "$src" --strip-components=1 -C "$kernelWork"
cd "$kernelWork"
patchPhase

mkdir build
export buildRoot="$PWD/build"
cp "$repoRoot/nix/packages/crt/fill-station-linux/kernel.config" "$buildRoot/.config"
make "${makeFlags[@]}" O="$buildRoot" olddefconfig

export TERM=xterm-256color
make "${makeFlags[@]}" O="$buildRoot" menuconfig
```

In the editor, `/` searches, `Y` builds in, `M` creates a module, and `N` disables.
Choose **Save**, accept `.config`, then **Exit**. Saving already resolves the
config; you do not need to run `olddefconfig` again.

## Save back and build

After saving and exiting the editor, copy the edited `.config` back to the repo.
There are no config fragments to merge; `kernel.config` is the complete saved
configuration used by the build. Still in the Linux shell:

```sh
cp "$buildRoot/.config" "$repoRoot/nix/packages/crt/fill-station-linux/kernel.config"
```

If using the VM, run this **on your Mac, from the repo root**, to retrieve it:

```sh
sudo scp \
  linux-builder:Software26-27/nix/packages/crt/fill-station-linux/kernel.config \
  nix/packages/crt/fill-station-linux/kernel.config
```

From your main checkout, review and build. Full image builds currently require
ARM64 Linux locally or as a configured remote builder, including on x86-64 hosts:

```sh
git diff -- nix/packages/crt/fill-station-linux/kernel.config
nix --extra-experimental-features 'nix-command flakes' build \
  .#mixosConfigurations.fill-station.config.system.build.fitImage
```

The result is `result/fitImage.itb`. Use `system.build.sdImage` instead for a full
SD image. The kernel config is shared by the hybrid and liquid configurations;
test boot and required peripherals on the board before deploying it.
