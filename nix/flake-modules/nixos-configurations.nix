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
      ground-station-um560 = station [ ../nixos-configurations/ground-station/um560.nix ];
      ground-station-installer = inputs.nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        specialArgs.groundStationSystem = self.nixosConfigurations.ground-station-um560.config.system.build.toplevel;
        modules = [
          { nixpkgs.hostPlatform = "x86_64-linux"; }
          ../nixos-configurations/ground-station/installer.nix
        ];
      };
      ground-station-vm = station [ ../nixos-configurations/ground-station/vm.nix ];
    };
  };

  perSystem = { system, pkgs, ... }: {
    checks = lib.optionalAttrs (system == "x86_64-linux") {
      ground-station-vm = import ../../tests/platform/test_nixos_vm.nix { inherit pkgs; };
    } // lib.optionalAttrs (builtins.elem system [ "aarch64-linux" "x86_64-linux" ]) {
      ground-worker-admission = import ../../tests/platform/test_worker_linux.nix { inherit pkgs; };
    };
  };
}
