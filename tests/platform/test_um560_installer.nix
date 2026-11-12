# Evaluate media policy without building a production system or touching disks.
{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  pkgs = import nixpkgs { system = "x86_64-linux"; };
  profile = ../../nix/nixos-configurations/ground-station/installer.nix;
  fixture = pkgs.runCommand "fixture-um560-system" { } "mkdir $out";
  config = (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    specialArgs.groundStationSystem = fixture;
    modules = [
      { nixpkgs.hostPlatform = "x86_64-linux"; }
    ] ++ lib.optional (builtins.pathExists profile) profile;
  }).config;
  checks = {
    profileExists = builtins.pathExists profile;
    x86Media = config.nixpkgs.hostPlatform.system == "x86_64-linux";
    uefiUsbMedia = config.isoImage.makeEfiBootable && config.isoImage.makeUsbBootable;
    embedsTarget = builtins.elem fixture config.isoImage.storeContents;
    explicitImageName = config.image.baseName == "crt-ground-station-um560-installer";
    localConsole = config.services.getty.autologinUser == "nixos"
      && !config.security.sudo.wheelNeedsPassword;
    noRemoteLogin = !config.services.openssh.enable;
    noChannelNeeded = !config.system.installer.channel.enable;
    noTimedInstall = !(config.systemd.services ? ground-install);
    helperAvailable = lib.any (p: (p.pname or p.name or "") == "crt-install-um560")
      config.environment.systemPackages;
    offlineInstructions = lib.hasInfix "crt-install-um560 --check"
      config.environment.etc."crt-um560-install.txt".text;
    assertionsPass = lib.all (a: a.assertion) config.assertions;
  };
in
assert lib.assertMsg (builtins.pathExists profile) "UM560 installer profile missing";
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "Installer contract failed: ${lib.concatStringsSep ", " (builtins.attrNames (lib.filterAttrs (_: v: !v) checks))}";
checks
