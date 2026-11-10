{ inputs, self, lib, ... }:
let
  station = extraModules: inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = [
      # Repository packages only; the MixOS overlay is not needed by NixOS.
      {
        nixpkgs.hostPlatform = "x86_64-linux";
        nixpkgs.overlays = [ self.overlays.default ];
      }
      ../nixos-configurations/ground-station
    ] ++ extraModules;
  };
in
{
  flake = {
    nixosModules.ground-station = ../nixos-modules/ground-station;
    nixosConfigurations = {
      ground-station = station [ ];
      ground-station-vm = station [ ../nixos-configurations/ground-station/vm.nix ];
    };
  };

  perSystem = { system, pkgs, ... }: {
    checks = lib.optionalAttrs (system == "x86_64-linux") {
      ground-station-vm = import ../../tests/platform/test_nixos_vm.nix { inherit pkgs; };
    };
  };
}
