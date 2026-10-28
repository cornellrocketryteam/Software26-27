{
  description = "Cornell Rocketry Nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-25.11";
    mixos = {
      url = "github:jmbaur/mixos";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    fenix = {
      url = "github:nix-community/fenix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs: {
    apps = inputs.nixpkgs.lib.mapAttrs (_: pkgs: {
      hardware-config = {
        type = "app";
        program = "${pkgs.writeShellScriptBin "hardware-config" ''
          exec ${pkgs.python3}/bin/python3 ${./fill-station/hardware}/server.py "$@"
        ''}/bin/hardware-config";
      };
    }) inputs.self.legacyPackages;
    devShells = import ./nix/dev-shells inputs;
    formatter = import ./nix/formatter inputs;
    legacyPackages = import ./nix/legacy-packages inputs;
    mixosConfigurations = import ./nix/mixos-configurations inputs;
    overlays = import ./nix/overlays inputs;
  };
}
