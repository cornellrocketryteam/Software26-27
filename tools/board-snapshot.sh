#!/usr/bin/env bash
# Read-only snapshot of what the running fill-station kernel actually found and
# bound: drivers, devices, USB, network, MTD. Take one before a kernel config
# change and one after, then diff them to catch a peripheral that silently
# disappeared.
#
# Usage: tools/board-snapshot.sh root@<board-ip> [label] [outdir]
#   e.g. tools/board-snapshot.sh root@192.168.1.50 baseline
#        tools/board-snapshot.sh root@192.168.1.50 pass1
#        diff board-snapshots/baseline.txt board-snapshots/pass1.txt
set -euo pipefail

target=${1:?usage: $0 root@<board-ip> [label] [outdir]}
label=${2:-$(date +%Y%m%d-%H%M%S)}
outdir=${3:-board-snapshots}
mkdir -p "$outdir"

# Runs under busybox sh on the board. Output avoids counters and timestamps so
# two snapshots diff cleanly.
ssh "$target" sh -s >"$outdir/$label.txt" <<'EOF'
section() { echo; echo "=== $1 ==="; }

section "kernel"
uname -r
cat /proc/cmdline

section "bound drivers (bus/driver device)"
for drv in /sys/bus/*/drivers/*; do
  bus=${drv#/sys/bus/}; bus=${bus%%/*}
  for dev in "$drv"/*; do
    [ -L "$dev" ] || continue
    case ${dev##*/} in module | bind | unbind | uevent | new_id | remove_id) continue ;; esac
    echo "$bus/${drv##*/} ${dev##*/}"
  done
done | sort

section "devices without a driver (platform bus)"
for dev in /sys/bus/platform/devices/*; do
  [ -e "$dev/driver" ] || echo "${dev##*/}"
done | sort

section "/dev"
ls /dev | sort

section "usb devices (id name)"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  echo "$(cat "$d/idVendor"):$(cat "$d/idProduct") $(cat "$d/product" 2>/dev/null)"
done | sort

section "network interfaces"
ls /sys/class/net | sort

section "mtd"
cat /proc/mtd 2>/dev/null || echo "(no /proc/mtd)"

section "mounts"
awk '{ print $2, $3 }' /proc/mounts | sort

section "interrupts (name only)"
awk 'NR > 1 { print $1, $(NF - 1), $NF }' /proc/interrupts

section "pwm / gpio / i2c"
ls /sys/class/pwm /sys/bus/gpio/devices /sys/class/i2c-dev 2>/dev/null
EOF

# dmesg goes in its own file with timestamps stripped; it's for reading, not
# for a clean diff
ssh "$target" dmesg | sed 's/^\[ *[0-9.]*\] //' >"$outdir/$label.dmesg.txt"

echo "Saved $outdir/$label.txt and $outdir/$label.dmesg.txt"
