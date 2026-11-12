# Packaged by installer.nix with @system@ replaced by the embedded system closure.
set -euo pipefail

case "${1:-}" in
  '')
    cat <<'EOF'
UM560 offline foundation installer. No disks are partitioned or formatted here.
Read /etc/crt-um560-install.txt, prepare and mount the intended filesystems, then:
  sudo crt-install-um560 --check
  sudo crt-install-um560 --install
The install writes the mounted target and UEFI boot entry, then asks you to set
an offline console password for ground-admin. SSH remains key-only.
EOF
    exit 0
    ;;
  --check|--install) ;;
  *) echo 'Usage: crt-install-um560 [--check|--install]' >&2; exit 2 ;;
esac
if [ "$#" -ne 1 ]; then
  echo 'Specify exactly one action.' >&2
  exit 2
fi
if [ "$(id -u)" != 0 ]; then
  echo 'Run as root using sudo.' >&2
  exit 1
fi

check_mount() {
  local path="$1" label="$2" fs_type="$3"
  if ! mountpoint --quiet "$path" \
    || [ "$(findmnt --noheadings --output LABEL --mountpoint "$path")" != "$label" ] \
    || [ "$(findmnt --noheadings --output FSTYPE --mountpoint "$path")" != "$fs_type" ]; then
    echo "Refusing installation: $path must be a mounted $fs_type filesystem labeled $label." >&2
    exit 1
  fi
}
check_mount /mnt CRT-GS-ROOT ext4
check_mount /mnt/boot CRT-GS-EFI vfat
printf '%s\n' 'Expected root and EFI filesystems are mounted.'
if [ "$1" = --check ]; then
  exit 0
fi

# Populate the new store explicitly before disabling all substitution. This is a
# local copy from the checksum-verified ISO, including its unsigned local builds;
# no signature policy is changed on the installed machine.
nix --extra-experimental-features nix-command copy --offline --no-check-sigs \
  --to 'local?root=/mnt' @system@
# --system avoids evaluation/building. No remote substituters or builders are used.
nixos-install --root /mnt --system @system@ --no-channel-copy --no-root-passwd \
  --option substitute false --option substituters '' --option builders ''
printf '%s\n' 'Set a local console password for ground-admin. SSH password login stays disabled.'
nixos-enter --root /mnt --command 'passwd ground-admin'
printf '%s\n' 'Installed. Reboot and remove the installer USB. Sign in locally as ground-admin.'
