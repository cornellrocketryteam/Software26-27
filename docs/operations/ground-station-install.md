# UM560 offline foundation installation

This installs a fresh NixOS **foundation** on the UM560 XT. It includes Ethernet,
key-only SSH and the packaged operator UI. Production telemetry, cache, worker,
commanding and kiosk are still off/pending; `/readyz` returns 503. Installing this
image is not acceptance of the full field stack.

The owner accepted loss of the old Ubuntu/container data on November 12. Legacy
backup/restore is not required. The manual formatting steps below erase the chosen
SSD. Preparing/building the image does not change that SSD or any USB drive.

## Prepare while internet is available

On a Linux Nix builder, from a checkout containing this change:

```sh
nix build .#nixosConfigurations.ground-station-installer.config.system.build.isoImage -o result-ground-installer
sha256sum result-ground-installer/iso/*.iso
```

The ISO contains the complete prebuilt UM560 runtime closure. Installation does
not rebuild/evaluate the repository or download packages. It does not promise
arbitrary offline development builds; those require separately prepared inputs.
The media carries contributor **public** SSH keys, not private keys or passwords.

### Mac fallback: isolated Linux store

The current Mac's Determinate native builder fails on ncurses terminfo paths
because it shares a case-insensitive store. This is a documented
[builder limitation](https://docs.determinate.systems/troubleshooting/native-linux-builder/)
and matches [the upstream report](https://github.com/NixOS/nixpkgs/issues/550124).
Use a Linux worker or Docker volume, rather than editing case-hack paths in the
station configuration or reinstalling the host's Nix.

Start Docker Desktop, then run from the repository root:

```sh
mkdir -p result-ground-installer-files
docker run --rm --platform linux/amd64 \
  --volume crt-ground-nix:/nix \
  --volume "$PWD:/work:ro" \
  --volume "$PWD/result-ground-installer-files:/artifacts" \
  --workdir /work --entrypoint /bin/sh \
  nixos/nix@sha256:b49cb33f3a7e5cf3933ad8774529de0e3807ec5cf54987aa7ccdfb49f2fc55ed \
  -ec '
    git config --global --add safe.directory /work
    nix --extra-experimental-features "nix-command flakes" build \
      "git+file:///work#nixosConfigurations.ground-station-installer.config.system.build.isoImage" \
      --out-link /tmp/installer --print-build-logs \
      --option sandbox false --option filter-syscalls false \
      --option substituters https://cache.nixos.org
    cp /tmp/installer/iso/*.iso /artifacts/
    cd /artifacts
    sha256sum ./*.iso > SHA256SUMS
  '
```

The pinned bootstrap container reports Nix 2.35.6. Its Linux `/nix` volume persists
between builds and is separate from the Mac's store; the repository is read-only.
The syscall-filter option is needed for this emulated Docker build and changes no
host or installed-station setting. Preparation downloads from public Nix/GitHub
sources and needs internet initially; it does not use FlakeHub authentication.
This is the installer bootstrap fallback, not yet the platform CLI's automatic
remote-worker routing. Keep the volume until the artifact has been verified.

## Write and boot the installer USB

Use a USB drive large enough for the built ISO. In a disk-image writer such as
balenaEtcher, select this ISO, select the intended USB by size/model, and write it.
That erases the selected USB. Do not choose the internal SSD. The ISO supports
UEFI and USB boot; use the UM560 firmware boot menu to select the USB's UEFI entry.
Secure Boot is not configured by this foundation.

On the tested UM560, restart and tap **F7** repeatedly to select the Kingston
USB's **UEFI Partition 2** entry. Leave Secure Boot disabled for this unsigned
installer and foundation; an invalid-signature message means firmware rejected
that boot chain. Signing and key enrollment are not implemented here.

### Black screen after selecting NixOS

The tested USB required a one-boot console workaround. Stop the NixOS menu's
countdown with an arrow key, then select **Options → No modesetting**. Highlight
the NixOS entry inside it and press **e**. On the line starting `linux` or
`linuxefi`, remove `console=ttyS0,115200`, retaining `console=tty0` and `nomodeset`.
Press **Ctrl+X** to boot. This combination reached the live terminal on the real
UM560; it does not establish which parameter alone caused the black screen.

The current ISO includes the serial parameter for VM testing, so this workaround
is still needed on that hardware. It edits only the current USB boot; the
installed SSD system subsequently reached its console without that USB edit.

The live system logs in locally as `nixos`, with passwordless sudo. It has no SSH
server. Read the embedded instructions:

```sh
cat /etc/crt-um560-install.txt
lsblk -o NAME,SIZE,MODEL,TRAN,FSTYPE,LABEL,MOUNTPOINTS
ls -l /dev/disk/by-id/
test -d /sys/firmware/efi && echo 'Booted in UEFI mode'
```

Stop if the UEFI check fails. Identify the internal SSD's whole-disk `by-id` link;
it must not be the USB device or a `-partN` link. The recorded Ubuntu disk was
about 476.9 GiB, but verify the actual live listing rather than assuming its name.

## If macOS flashing fails

For this hybrid ISO, use a raw whole-device write rather than Disk Utility's
Restore operation. The [official NixOS macOS instructions](https://nixos.org/manual/nixos/stable/#sec-booting-from-usb)
use `diskutil` and `dd`. First identify the USB again; device numbers can change
when it is disconnected. Do not copy an earlier disk number blindly.

```sh
diskutil list external physical
```

After checking the target's capacity/model, replace **N** below with its current
whole-disk number. These commands erase the selected USB, not just one partition.
Run from the repository root; the image path must name the actual `.iso` file.

```sh
diskutil unmountDisk /dev/diskN
sudo dd if="$PWD/result-ground-installer-files/crt-ground-station-um560-installer.iso" of=/dev/rdiskN bs=4m
sync
diskutil eject /dev/diskN
```

Wait for `dd` to finish successfully before ejecting. On macOS, Control-T displays
progress while it runs. If macOS then says the disk is unreadable, do not initialize
or reformat it; the Linux installer partitions need not be mountable by macOS.
If Etcher fails, record its exact error and whether it occurs on source selection,
writing or verification; those are different failures. Do not assume rebuilding
or renaming a bootable ISO will fix an unexplained flashing-app error.

On November 12 this exact 1,560,281,088-byte ISO was rechecked: SHA-256 matched
`SHA256SUMS`; the GPT header and partition-array CRCs matched. `hdiutil imageinfo`
reported an internal error while parsing the hybrid ISO, but a separate QEMU UEFI
boot using the ISO as a read-only **USB mass-storage disk**, with no ISO attached
as CD media and no NIC, reached the live shell. `lsblk` identified the USB ISO9660
and EFI FAT partitions. The install helper correctly refused unprepared mounts.
Evidence: `/private/tmp/ground-installer-usb-check-20261112/console.log` and `PASS`.
This validates USB boot layout; physical flash-write success and the reported
Etcher failure remain unverified. No physical USB was written by the assistant.

## Prepare the selected SSD manually

Replace the placeholder with the actual whole-disk ID from the listing:

```sh
disk=/dev/disk/by-id/REPLACE_WITH_VERIFIED_INTERNAL_SSD_ID
lsblk -o NAME,SIZE,MODEL,TRAN,FSTYPE,LABEL,MOUNTPOINTS "$disk"
```

The following commands erase that disk. Run them only after verifying the printed
model/capacity and that none of its partitions are mounted. They create a 1 GiB
EFI partition and an ext4 root using the labels expected by the prebuilt system.

```sh
sudo parted --script "$disk" mklabel gpt \
  mkpart ESP fat32 1MiB 1025MiB set 1 esp on \
  mkpart root ext4 1025MiB 100%
sudo udevadm settle
sudo mkfs.fat -F 32 -n CRT-GS-EFI "${disk}-part1"
sudo mkfs.ext4 -L CRT-GS-ROOT "${disk}-part2"
sudo mount -t ext4 "${disk}-part2" /mnt
sudo mkdir -p /mnt/boot
sudo mount -t vfat "${disk}-part1" /mnt/boot
sudo crt-install-um560 --check
```

The helper checks mounts, labels and filesystem types. It does not identify the
physical SSD for you, format anything or install automatically. Avoid duplicate
labels on attached devices.

## Install and establish console access

```sh
sudo crt-install-um560 --install
```

This explicitly copies the embedded closure into `/mnt`, registers its system
profile and writes the UEFI bootloader/entry. The local copy accepts the ISO's
unsigned local build outputs; verify the ISO checksum before use. It disables
remote substitution/building and changes no installed signature-trust policy. It then prompts twice for a password for
`ground-admin`; this password stays on the installed host, outside Git/Nix store.
Root remains locked and SSH password login remains disabled. The account database
is mutable so this locally set console password survives boot; it is not embedded
in the ISO.

If password setup was interrupted after installation, finish it before rebooting:

```sh
sudo nixos-enter --root /mnt --command 'passwd ground-admin'
```

Unmount and reboot when both installation and password setup finish:

```sh
sudo umount -R /mnt
sudo reboot
```

Remove the USB when restarting. Log in on the PC as `ground-admin` using the local
password. Keep the USB for local recovery. This is an offline bootstrap, not an
automated destructive installer.

## First hardware checks

Run one check at a time and inspect its output:

```sh
findmnt /
findmnt /boot
ip -br address
systemctl is-active nginx sshd
curl --fail http://127.0.0.1:8080/healthz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/readyz
```

Expect `CRT-GS-ROOT`/ext4 and `CRT-GS-EFI`/vfat mounts, Ethernet `lan0`, active
nginx/sshd, successful liveness and readiness **503**.
Ethernet MAC `58:47:CA:7E:6E:15` is pinned; IPv4 comes from DHCP. Reserve
`192.168.1.206` at the router if that is the intended address; no static gateway
was invented. Without a DHCP server, local boot still works but LAN SSH needs a
prepared addressing plan.

From a laptop on that LAN, verify the new host-key fingerprint against the PC's
console before accepting it, then connect as `ground-admin` using a contributor
private key. Do not disable host-key checking. The old assumed `root` login is not
the new account policy. Open `http://<actual-address>:8080/` from the laptop.
A local graphical kiosk is not included yet.

## Confirmed physical foundation checks

The operator completed installation on the UM560's internal 476.9 GiB AirDisk
NVMe SSD and confirmed SSD boot without the installer USB, `ground-admin` console
login, active nginx and sshd, and the expected local `/healthz` response. Ethernet
`lan0` obtained `192.168.1.206/24`; SSH login and the UI at
`http://192.168.1.206:8080/` worked from the Mac on the same LAN.

These are operator-reported physical results. The physical `/readyz` check and a
separate power-cycle with LAN/WAN absent have not been reported. VM checks cover
offline installation and disk-only boot; the foundation and ISO built, 211
configuration contracts and five install-helper tests passed.

Production telemetry, kiosk, signed cache/build worker, commanding and Secure
Boot remain unconfigured or unaccepted. A successful foundation UI is not field
readiness; `/readyz` intentionally remains 503.
