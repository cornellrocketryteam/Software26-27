{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  evaluate = extra: (import (flake.inputs.nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-modules/ground-station/network.nix
      ../../nix/nixos-modules/ground-station/time.nix extra ];
  }).config;
  base = evaluate {};
  enabled = evaluate {
    groundStation.network.lanInterfaces = [ "lan0" ];
    groundStation.timeServer.enable = true;
  };
  checks = {
    disabledByDefault = !base.groundStation.timeServer.enable;
    serverEnabled = enabled.services.chrony.enable;
    noAutomaticSteps = !enabled.services.chrony.makestep.enable
      && !enabled.services.chrony.initstepslew.enabled;
    offlineDefault = enabled.services.chrony.servers == [];
    restrictedClients = lib.hasInfix "allow 192.168.1.106/32" enabled.services.chrony.extraConfig;
    localReference = lib.hasInfix "local stratum 10" enabled.services.chrony.extraConfig;
    noRemoteManagement = lib.hasInfix "cmdport 0" enabled.services.chrony.extraConfig;
    scopedFirewall = builtins.elem 123 enabled.networking.firewall.interfaces.lan0.allowedUDPPorts
      && !(builtins.elem 123 enabled.networking.firewall.allowedUDPPorts);
    noOnlineWait = !(builtins.elem "network-online.target" enabled.systemd.services.chronyd.after);
    boardClients = lib.all (name:
      let c = flake.mixosConfigurations.${name}.config;
      in c.init.time-sync.action == "respawn"
        && lib.hasInfix "ntpd -n -p 192.168.1.206" c.init.time-sync.process
        && !(lib.hasInfix " -q" c.init.time-sync.process)
    ) [ "fill-station" "fill-station-liquid" "fill-station-debug" ];
  };
in assert lib.all (x: x) (builtins.attrValues checks); checks
