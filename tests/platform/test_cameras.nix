{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = enabled: file: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-modules/ground-station/cameras.nix {
      groundStation.cameras = { enable = enabled; credentialsFile = file; };
      system.stateVersion = "26.05";
      fileSystems."/" = { device = "none"; fsType = "tmpfs"; };
      boot.loader.grub.enable = false;
    } ];
  }).config;
  off = evaluate false null;
  on = evaluate true "/var/lib/ground-station/cameras/credentials.json";
  bad = evaluate true "/nix/store/secret.json";
  service = on.systemd.services.ground-station-cameras;
  locations = on.services.nginx.virtualHosts.ground-station.locations;
  checks = {
    defaultOff = !off.groundStation.cameras.enable && !(off.systemd.services ? ground-station-cameras);
    pinned = on.groundStation.cameras.package.version == "1.9.15";
    supervised = service.serviceConfig.Restart == "always" && service.startLimitIntervalSec == 0;
    privateCredential = service.serviceConfig.LoadCredential == [ "cameras.json:/var/lib/ground-station/cameras/credentials.json" ];
    noWanDependency = !(builtins.elem "network-online.target" service.after);
    noBootPrerequisite = service.requiredBy == [ ];
    quiet = service.serviceConfig.StandardOutput == "null" && service.serviceConfig.StandardError == "null";
    noStoreSecrets = !(lib.all (a: a.assertion) bad.assertions);
    valid = lib.all (a: a.assertion) on.assertions;
    endpoints = lib.all (name:
      locations."= /cameras/${name}/stream.mp4".proxyPass == "http://127.0.0.1:1984/api/stream.mp4?src=${name}&video&audio=none"
      && lib.hasInfix "if ($request_method !~ ^(GET|HEAD)$)" locations."= /cameras/${name}/stream.mp4".extraConfig
    ) [ "fillcam0" "fillcam1" "fillcam2" ];
    denyUnknown = locations."^~ /cameras/".return == "404";
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks)) "camera contract failed";
checks
