{
  description = "Cornell Rocketry Nix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    import-tree.url = "github:denful/import-tree";
    treefmt-nix.url = "github:numtide/treefmt-nix";

    mixos.url = "github:jmbaur/mixos";
    mixos.inputs.nixpkgs.follows = "nixpkgs";
  };

  # Every .nix file under nix/flake-modules is a flake-parts module; paths containing `/_` are skipped
  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } (inputs.import-tree ./nix/flake-modules);
}
