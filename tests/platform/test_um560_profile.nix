# Hardware intent and deployment boundaries; does not inspect or write a disk.
{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  profile = ../../nix/nixos-configurations/ground-station/um560.nix;
  evaluate = modules: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      { nixpkgs.hostPlatform = "x86_64-linux"; }
      ../../nix/nixos-configurations/ground-station
    ] ++ modules;
  }).config;
  base = evaluate [ ];
  host = evaluate (lib.optional (builtins.pathExists profile) profile);
  get = path: fallback: lib.attrByPath path fallback host;
  failed = c: lib.filter (a: !a.assertion) c.assertions;
  checks = {
    profileExists = builtins.pathExists profile;
    physicalX86 = host.nixpkgs.hostPlatform.system == "x86_64-linux"
      && !host.groundStation.virtualMachine;
    hardwareDeclared = host.groundStation.hardwareConfigured;
    genericTargetStillGated = !base.groundStation.hardwareConfigured
      && lib.any (a: lib.hasInfix "hardware installation prerequisite" a.message) (failed base);
    plannedRootLabel = get [ "fileSystems" "/" "device" ] null == "/dev/disk/by-label/CRT-GS-ROOT"
      && get [ "fileSystems" "/" "fsType" ] null == "ext4";
    plannedEfiLabel = get [ "fileSystems" "/boot" "device" ] null == "/dev/disk/by-label/CRT-GS-EFI"
      && get [ "fileSystems" "/boot" "fsType" ] null == "vfat";
    uefiBoot = host.boot.loader.systemd-boot.enable && host.boot.loader.efi.canTouchEfiVariables;
    nvmeInitrd = builtins.elem "nvme" host.boot.initrd.availableKernelModules;
    amdFirmware = host.hardware.cpu.amd.updateMicrocode && host.hardware.enableRedistributableFirmware;
    macBoundInterface = get [ "systemd" "network" "links" "10-ground-lan" "matchConfig" "MACAddress" ] null
      == "58:47:ca:7e:6e:15"
      && get [ "systemd" "network" "links" "10-ground-lan" "linkConfig" "Name" ] null == "lan0";
    wiredDhcp = host.networking.useNetworkd && !host.networking.useDHCP
      && get [ "systemd" "network" "networks" "20-ground-lan" "matchConfig" "Name" ] null == "lan0"
      && get [ "systemd" "network" "networks" "20-ground-lan" "networkConfig" "DHCP" ] null == "ipv4";
    noWifiDependency = !host.networking.wireless.enable && !host.networking.networkmanager.enable;
    nonblockingNetwork = !host.systemd.network.wait-online.enable
      && get [ "systemd" "network" "networks" "20-ground-lan" "linkConfig" "RequiredForOnline" ] null == "no";
    lanScope = host.groundStation.network.lanInterfaces == [ "lan0" ]
      && get [ "networking" "firewall" "interfaces" "lan0" "allowedTCPPorts" ] [ ] == [ 22 8080 ];
    fieldFoundation = host.groundStation.fieldMode && host.groundStation.operatorUi.enable
      && !host.groundStation.telemetry.enable && !host.groundStation.cache.enable
      && !host.groundStation.cache.ingestion.enable && !host.groundStation.builder.enable
      && !host.groundStation.commandListener.enable;
    keyOnlyAdministration = host.users.users.root.hashedPassword == "!"
      && host.services.openssh.settings.PermitRootLogin == "no"
      && host.users.users.ground-admin.openssh.authorizedKeys.keyFiles != [ ];
    notOperationalReadiness = lib.hasPrefix "503 "
      host.services.nginx.virtualHosts.ground-station.locations."= /readyz".return;
    profileAssertionsPass = failed host == [ ];
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "UM560 profile contract failed: ${lib.concatStringsSep ", " (builtins.attrNames (lib.filterAttrs (_: v: !v) checks))}";
checks
