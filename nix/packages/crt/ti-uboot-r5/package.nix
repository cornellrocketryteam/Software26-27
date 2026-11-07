{
  ti-linux-firmware,
  buildUBoot,
  buildPackages,
  python3Packages,
}:
(buildUBoot {
  defconfig = "am64x_evm_r5_defconfig";
  # Only the R5 SPL ships (tiboot3), so only SPL options matter.
  extraConfig = ''
    # SK's LPDDR4 setup even if the board-ID EEPROM read fails
    CONFIG_DEFAULT_DEVICE_TREE="k3-am642-r5-sk"
    CONFIG_NO_NET=y
    # CONFIG_USB is not set
  '';
  extraMeta.platforms = [ "armv7l-linux" ];

  filesToInstall = [
    "tiboot3-am64x-gp-evm.bin"
    "tiboot3-am64x_sr2-hs-fs-evm.bin"
    "tiboot3-am64x_sr2-hs-evm.bin"
  ];
  outputChecks.out.allowedReferences = [ "out" ];

  extraMakeFlags = [
    "BINMAN_INDIRS=${ti-linux-firmware}"
  ];

  # Add library path for libfdt so that it does not look in /usr for libfdt
  preBuild = ''
    export DYLD_LIBRARY_PATH="${buildPackages.dtc}/lib:$DYLD_LIBRARY_PATH"
  '';
}).overrideAttrs
  (oldAttrs: {
    nativeBuildInputs = oldAttrs.nativeBuildInputs ++ [
      # These Python packages are required by a ti-linux-firmware script
      python3Packages.pyyaml
      python3Packages.yamllint
      python3Packages.jsonschema
    ];
  })
