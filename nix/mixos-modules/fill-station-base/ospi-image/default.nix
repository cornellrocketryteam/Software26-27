# Images for booting from the SK-AM64B's OSPI NOR flash (S28HS512T, 64 MiB).
#
# ospiImage: one file per flash partition (layout from k3-am642-sk.dts, ospi0),
# written from Linux with tools/flash-ospi.sh:
#   ospi.tiboot3 0x0       1 MiB    tiboot3.bin
#   ospi.tispl   0x100000  2 MiB    tispl.bin
#   ospi.u-boot  0x300000  4 MiB    u-boot.img
#   ospi.rootfs  0x800000  0x37c0000 fitImage.itb (booted by U-Boot's BOOTCOMMAND)
# ospi.env*, and ospi.phypattern at 0x3fc0000, are never written.
#
# dataCardImage: SD card with only the ext4 DATA partition for
# running from flash; state.init finds it by LABEL=DATA.
{ config, pkgs, ... }:
let
  inherit (pkgs.pkgsCross.armv7l-hf-multiplatform.crt) ti-uboot-r5;
  inherit (pkgs.pkgsCross.aarch64-multiplatform.crt) ti-uboot-a53;
  fitImage = "${config.system.build.fitImage}/fitImage.itb";
in
{
  system.build.ospiImage =
    pkgs.runCommand "fill-station-ospi"
      {
        allowedReferences = [ ];
      }
      ''
        mkdir -p $out
        cp ${ti-uboot-r5}/tiboot3-am64x_sr2-hs-fs-evm.bin $out/tiboot3.bin
        cp ${ti-uboot-a53}/tispl.bin $out/tispl.bin
        cp ${ti-uboot-a53}/u-boot.img $out/u-boot.img
        cp ${fitImage} $out/fitImage.itb

        # Each file must fit its partition
        check() {
          size=$(stat -c %s "$out/$1")
          echo "$1: $size bytes (partition $2: $3 bytes)"
          if [ "$size" -gt "$3" ]; then
            echo "$1 does not fit in $2" >&2
            exit 1
          fi
        }
        check tiboot3.bin ospi.tiboot3 ${toString (1024 * 1024)}
        check tispl.bin ospi.tispl ${toString (2 * 1024 * 1024)}
        check u-boot.img ospi.u-boot ${toString (4 * 1024 * 1024)}
        check fitImage.itb ospi.rootfs ${toString 58458112}

        # Partition each file goes to, for tools/flash-ospi.sh
        cat > $out/partitions <<EOF
        tiboot3.bin ospi.tiboot3
        tispl.bin ospi.tispl
        u-boot.img ospi.u-boot
        fitImage.itb ospi.rootfs
        EOF

        (cd $out && sha256sum tiboot3.bin tispl.bin u-boot.img fitImage.itb > SHA256SUMS)
      '';

  system.build.dataCardImage = pkgs.callPackage (
    {
      stdenvNoCC,
      e2fsprogs,
      libfaketime,
      util-linux,
    }:
    stdenvNoCC.mkDerivation {
      name = "fill-station-data-card.img";
      nativeBuildInputs = [
        e2fsprogs
        libfaketime
        util-linux
      ];
      buildCommand = ''
        mkdir -p $out
        img=$out/fill-station-data-card.img
        sizeMiB=256
        startMiB=1

        truncate -s $(((startMiB + sizeMiB) * 1024 * 1024)) $img
        sfdisk --no-reread --no-tell-kernel $img <<EOF
          label: dos
          start=''${startMiB}M, size=''${sizeMiB}M, type=83
        EOF

        truncate -s $((sizeMiB * 1024 * 1024)) data.img
        faketime "2000-01-01 00:00:00" mkfs.ext4 -F -L DATA \
          -U 2178694e-0000-4000-8000-000000000001 \
          -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=2178694e-0000-4000-8000-000000000001 data.img
        e2fsck -fn data.img
        dd conv=notrunc if=data.img of=$img bs=1M seek=$startMiB
      '';

      allowedReferences = [ ];
    }
  ) { };
}
