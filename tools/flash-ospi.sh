#!/usr/bin/env bash
# Write the fill-station image to the SK-AM64B's OSPI flash over SSH.
#
# Usage: tools/flash-ospi.sh <ssh-target> [fit|all] [image-dir]
#   fit  (default) write only the FIT (ospi.rootfs): the normal update
#   all  also write tiboot3/tispl/u-boot: first-time setup or a bootloader change
#   image-dir defaults to ./result-ospi, from:
#     nix build .#mixosConfigurations.fill-station.config.system.build.ospiImage -o result-ospi
#
# Works whether the board is running from SD or from flash: Linux runs from RAM,
# so rewriting the flash underneath it is safe. A FIT cut off mid-write fails
# U-Boot's checksum and the board falls back to the SD card. Partitions are found
# by name in /proc/mtd; ospi.env* and ospi.phypattern are never written.
set -euo pipefail

target=${1:?usage: $0 <ssh-target> [fit|all] [image-dir]}
mode=${2:-fit}
dir=${3:-result-ospi}

case $mode in
  fit) files=(fitImage.itb) ;;
  all) files=(tiboot3.bin tispl.bin u-boot.img fitImage.itb) ;;
  *) echo "mode must be fit or all" >&2; exit 1 ;;
esac

[[ -f $dir/partitions && -f $dir/SHA256SUMS ]] || {
  echo "$dir doesn't look like an ospiImage build (no partitions/SHA256SUMS)" >&2
  exit 1
}

# Check the local files against the build's checksums
if command -v sha256sum >/dev/null; then sum() { sha256sum "$@"; }; else sum() { shasum -a 256 "$@"; }; fi
(cd "$dir" && sum -c SHA256SUMS --quiet) || { echo "local files don't match SHA256SUMS" >&2; exit 1; }

ssh "$target" 'command -v flashcp >/dev/null' || {
  echo "flashcp isn't on the board; boot an image built with the busybox flashcp override first" >&2
  exit 1
}

if [[ $mode == all ]]; then
  echo "Writing the bootloaders too. If power is lost during this, the board won't boot"
  echo "from flash until it's booted from SD (SW3 = 01000011) and flashed again."
  read -r -p "Continue? [y/N] " answer
  [[ $answer == [yY]* ]] || exit 1
fi

for f in "${files[@]}"; do
  part=$(awk -v f="$f" '$1 == f { print $2 }' "$dir/partitions")
  case $part in
    ospi.tiboot3 | ospi.tispl | ospi.u-boot | ospi.rootfs) ;;
    *) echo "refusing to write $f to partition '$part'" >&2; exit 1 ;;
  esac
  expected=$(awk -v f="$f" '$2 == f { print $1 }' "$dir/SHA256SUMS")

  mtd=$(ssh "$target" "grep '\"$part\"' /proc/mtd | cut -d: -f1")
  [[ $mtd == mtd[0-9]* ]] || { echo "partition $part not found in /proc/mtd" >&2; exit 1; }
  partsize=$(ssh "$target" "cat /sys/class/mtd/$mtd/size")
  size=$(wc -c < "$dir/$f" | tr -d ' ')
  if (( size > partsize )); then
    echo "$f ($size bytes) is larger than $part ($partsize bytes)" >&2
    exit 1
  fi

  echo "== $f -> $part (/dev/$mtd): $size of $partsize bytes"
  ssh "$target" "cat > /tmp/flash-$f" < "$dir/$f"
  got=$(ssh "$target" "sha256sum /tmp/flash-$f | cut -d' ' -f1")
  [[ $got == "$expected" ]] || { echo "checksum mismatch after copying $f to the board" >&2; exit 1; }
  # flashcp erases, writes, then reads back and compares
  ssh "$target" "flashcp -v /tmp/flash-$f /dev/$mtd && rm /tmp/flash-$f"
done

echo
echo "Flash updated and verified. Reboot to run it: ssh $target reboot"
