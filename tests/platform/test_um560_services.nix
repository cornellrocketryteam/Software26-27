{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  profile = ../../nix/nixos-configurations/ground-station/services.nix;
  config = (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      { nixpkgs.hostPlatform = "x86_64-linux"; }
      ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/um560.nix
    ] ++ lib.optional (builtins.pathExists profile) profile;
  }).config;
  checks = {
    profileExists = builtins.pathExists profile;
    hardwareUnchanged = config.groundStation.hardwareConfigured
      && config.fileSystems."/".device == "/dev/disk/by-label/CRT-GS-ROOT"
      && config.groundStation.network.lanInterfaces == [ "lan0" ];
    telemetryEnabled = config.groundStation.telemetry.enable;
    privateRuntimeFile = config.groundStation.telemetry.secretsFile
      == "/var/lib/ground-station/telemetry-secrets.json";
    freshPersistentState = config.groundStation.telemetry.stateDirectory == "/var/lib/ground-station/telemetry";
    explicitPins = builtins.attrNames config.groundStation.telemetry.imagePins == [ "emqx" "grafana" "timescaledb" ];
    reviewedLanUrl = config.groundStation.grafana.rootUrl == "http://192.168.1.206:8080/grafana/";
    noNativeGrafana = !config.groundStation.grafana.enable;
    credentialTool = lib.any (p: (p.pname or p.name or "") == "ground-telemetry") config.environment.systemPackages;
    backgroundAutostart = config.systemd.targets.ground-telemetry.wantedBy == [ "multi-user.target" ]
      && !config.systemd.targets.ground-telemetry.unitConfig.DefaultDependencies;
    otherServicesRemainGated = !config.groundStation.cache.enable
      && !config.groundStation.builder.enable && !config.groundStation.commandListener.enable;
    notFieldReady = lib.hasPrefix "503 " config.services.nginx.virtualHosts.ground-station.locations."= /readyz".return;
    assertionsPass = lib.all (a: a.assertion) config.assertions;
  };
in
assert lib.assertMsg (builtins.pathExists profile) "UM560 services profile missing";
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "UM560 services contract failed: ${lib.concatStringsSep ", " (builtins.attrNames (lib.filterAttrs (_: v: !v) checks))}";
checks
