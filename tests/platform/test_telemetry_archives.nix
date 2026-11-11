# Explicit/manual archive acceptance using disposable test versions, never a
# production image choice. Return the actual module's three archive derivations.
{ nixpkgs }:
let
  evaluated = import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/vm.nix
      {
        groundStation.telemetry = {
          enable = true;
          secretsFile = "/run/keys/isolated-fixture.json";
          imagePins = builtins.fromJSON (builtins.readFile ./telemetry_nix_pins.json);
        };
      }
    ];
  };
in evaluated.config.system.build.groundTelemetryImages
