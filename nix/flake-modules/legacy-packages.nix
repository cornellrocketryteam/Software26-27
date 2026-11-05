{ inputs, self, ... }:
{
  systems = [
    "aarch64-darwin"
    "aarch64-linux"
    "x86_64-linux"
  ];

  perSystem =
    { system, pkgs, ... }:
    {
      # Every perSystem module's `pkgs` includes our overlays
      _module.args.pkgs = import inputs.nixpkgs {
        inherit system;
        overlays = [
          inputs.mixos.overlays.default
          self.overlays.default
        ];
      };

      legacyPackages = pkgs;
    };
}
