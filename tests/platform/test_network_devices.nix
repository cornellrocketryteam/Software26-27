{ pkgs }:
let
  lib = pkgs.lib;
  evaluate = extra: (import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/um560.nix
      { nixpkgs.pkgs = pkgs; } extra ];
  }).config;
  disabled = evaluate { };
  enabled = evaluate { groundStation.networkDevices.enable = true; };
  secured = evaluate {
    groundStation.networkDevices = {
      enable = true;
      credentialsFile = "/var/lib/ground-station/network-devices/credentials.json";
    };
  };
  invalid = evaluate { groundStation.networkDevices = { enable = true; credentialsFile = "/nix/store/secret.json"; }; };
  service = enabled.systemd.services.ground-network-devices.serviceConfig;
in
assert !(disabled.systemd.services ? ground-network-devices);
assert !(disabled.services.nginx.virtualHosts.ground-station.locations ? "/network-api/");
assert lib.all (item: item.assertion) enabled.assertions;
assert service.DynamicUser && service.PrivateDevices && service.ProtectHome;
assert service.LoadCredential == [ ];
assert !(lib.hasInfix "--credentials-file" service.ExecStart);
assert secured.systemd.services.ground-network-devices.serviceConfig.LoadCredential == [ "devices:/var/lib/ground-station/network-devices/credentials.json" ];
assert !(lib.all (item: item.assertion) invalid.assertions);
assert !(builtins.elem 8767 enabled.networking.firewall.allowedTCPPorts);
assert enabled.services.nginx.virtualHosts.ground-station.locations."/network-api/".proxyPass == "http://127.0.0.1:8767/";
assert builtins.pathExists enabled.groundStation.networkDevices.inventoryFile;
{
  disabledByDefault = true;
  privateCredentials = true;
  noPublicBackendPort = true;
  sandboxed = true;
  package = (pkgs.callPackage ../../nix/packages/crt/ground-network-devices/package.nix { }).drvPath;
}
