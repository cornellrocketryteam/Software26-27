{ nixpkgs }:
let
  pkgs = import nixpkgs { system = "x86_64-linux"; };
  lib = pkgs.lib;
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-modules/ground-station/network-devices.nix
      { nixpkgs.pkgs = pkgs; groundStation.networkDevices.enable = true;
        system.stateVersion = "26.11";
        fileSystems."/" = { device = "/dev/fixture"; fsType = "ext4"; };
        boot.loader.grub.enable = false;
      } extra ];
  }).config;
  base = evaluate {};
  enabled = evaluate { groundStation.networkDevices.wan = {
    enable = true;
    targets = [{ label = "Fixture"; address = "1.1.1.1"; port = 443; }];
  }; };
  invalid = evaluate { groundStation.networkDevices.wan.enable = true; };
  service = enabled.systemd.services.ground-network-devices;
  checks = {
    disabledWithoutTargets = !base.groundStation.networkDevices.wan.enable
      && !(lib.hasInfix "--wan-config" base.systemd.services.ground-network-devices.serviceConfig.ExecStart);
    explicitTargetsOnly = builtins.elem "1.1.1.1/32" service.serviceConfig.IPAddressAllow
      && !(builtins.elem "0.0.0.0/0" service.serviceConfig.IPAddressAllow);
    noRawSocketPrivilege = !(service.serviceConfig ? AmbientCapabilities);
    noOnlineBootDependency = !(builtins.elem "network-online.target" (service.after ++ service.wants));
    boundedShutdown = service.serviceConfig.TimeoutStopSec == 15;
    passesAssertions = lib.all (a: a.assertion) enabled.assertions;
    emptyTargetRefused = !(lib.all (a: a.assertion) invalid.assertions);
  };
in assert lib.assertMsg (lib.all (value: value) (builtins.attrValues checks))
  ("WAN contracts failed: " + lib.concatStringsSep ", " (builtins.filter (name: !checks.${name}) (builtins.attrNames checks))
    + "; " + lib.concatStringsSep "; " (map (a: a.message) (builtins.filter (a: !a.assertion) enabled.assertions))); checks
