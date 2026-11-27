{ nixpkgs }:
let
  pkgs = import nixpkgs { system = "x86_64-linux"; };
  lib = pkgs.lib;
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-modules/ground-station/ecoflow.nix
      { nixpkgs.pkgs = pkgs; system.stateVersion = "26.11";
        fileSystems."/" = { device = "/dev/fixture"; fsType = "ext4"; };
        boot.loader.grub.enable = false;
      } extra ];
  }).config;
  base = evaluate {};
  enabled = evaluate { groundStation.ecoflow = { enable = true; serial = "FIXTURE123"; region = "us"; credentialsFile = "/var/lib/ground-station/ecoflow.json"; }; };
  invalid = evaluate { groundStation.ecoflow.enable = true; };
  unsafe = evaluate { groundStation.ecoflow = { enable = true; serial = "ABC"; region = "eu"; credentialsFile = "/nix/store/secret"; }; };
  service = enabled.systemd.services.ground-ecoflow;
  checks = {
    disabledNoService = !(base.systemd.services ? ground-ecoflow);
    disabledExplicitResponse = lib.hasInfix "disabled" base.services.nginx.virtualHosts.ground-station.locations."/ecoflow-api/".extraConfig;
    separateCredential = service.serviceConfig.LoadCredential == [ "ecoflow:/var/lib/ground-station/ecoflow.json" ];
    hardened = service.serviceConfig.DynamicUser && service.serviceConfig.NoNewPrivileges;
    boundedResources = service.serviceConfig.MemoryMax == "128M" && service.serviceConfig.TasksMax == 32;
    noOnlineBootDependency = !(builtins.elem "network-online.target" (service.after ++ service.wants));
    explicitRegion = lib.hasInfix "--region us" service.serviceConfig.ExecStart;
    incompleteRefused = !(lib.all (a: a.assertion) invalid.assertions);
    storeSecretRefused = !(lib.all (a: a.assertion) unsafe.assertions);
    configuredValid = lib.all (a: a.assertion) enabled.assertions;
  };
in assert lib.assertMsg (lib.all (x: x) (builtins.attrValues checks)) "EcoFlow module contracts failed"; checks
