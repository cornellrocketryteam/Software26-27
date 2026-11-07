args@{
  linuxManualConfig,
  linux_7_2,
  ...
}:
linuxManualConfig {
  inherit (linux_7_2) src version;
  configfile = ./kernel.config;
  # Keep callPackage from injecting the unrelated pkgs.kernelPatches set.
  kernelPatches = args.kernelPatches or [ ];
}
