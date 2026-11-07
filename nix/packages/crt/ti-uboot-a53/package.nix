{
  lib,
  ti-optee,
  ti-arm-trusted-firmware,
  ti-linux-firmware,
  buildUBoot,
  buildPackages,
}:
let
  # && stops each chain at the first failure.
  sdBootCommand = lib.concatStringsSep " && " [
    "load mmc 1:1 \${addr_fit} fitImage.itb"
    "bootm \${addr_fit}"
  ];
  # ospi.rootfs partition (see ospi-image)
  ospiFitOffset = "0x800000";
  ospiFitMax = "0x37c0000";
  ospiBootCommand = lib.concatStringsSep " && " [
    "sf probe"
    "sf read \${addr_fit} ${ospiFitOffset} 0x40"
    "fdt addr -q \${addr_fit}"
    "fdt header get fitsize totalsize"
    "itest \${fitsize} -le ${ospiFitMax}"
    "sf read \${addr_fit} ${ospiFitOffset} \${fitsize}"
    "bootm \${addr_fit}"
  ];
  # bootm only returns on failure, so ; falls through to OSPI.
  bootCommand = lib.concatStringsSep "; " [
    "echo Booting FIT from SD..."
    sdBootCommand
    "echo Booting FIT from OSPI..."
    ospiBootCommand
  ];
in
buildUBoot {
  defconfig = "am64x_evm_a53_defconfig";
  extraConfig = ''
    CONFIG_BOOTCOMMAND="${bootCommand}"
    CONFIG_BOOTDELAY=1
    CONFIG_NO_NET=y
    # Sets MAC addresses; won't link without net
    # CONFIG_BOARD_LATE_INIT is not set
    # CONFIG_EFI_LOADER is not set
    # CONFIG_USB is not set
    # CONFIG_CMD_UBI is not set
  '';

  extraMeta.platforms = [ "aarch64-linux" ];

  filesToInstall = [
    "tispl.bin" # For HS-FS and HS-SE
    "u-boot.img" # For HS-FS and HS-SE
    "tispl.bin_unsigned" # For GP
    "u-boot.img_unsigned" # For GP
  ];
  outputChecks.out.allowedReferences = [ "out" ];

  extraMakeFlags = [
    "BINMAN_INDIRS=${ti-linux-firmware}"
    "TEE=${ti-optee}/tee-raw.bin"
    "BL31=${ti-arm-trusted-firmware}/bl31.bin"
  ];

  # Add library path for libfdt so that it does not look in /usr for libfdt
  preBuild = ''
    export DYLD_LIBRARY_PATH="${buildPackages.dtc}/lib:$DYLD_LIBRARY_PATH"
  '';
}
