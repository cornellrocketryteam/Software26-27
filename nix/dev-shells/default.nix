inputs:
inputs.nixpkgs.lib.mapAttrs (
  _: pkgs:
  let
    # Python for fill-station's nanopb generator (build.rs)
    nanopbPython = pkgs.python3.withPackages (ps: [ ps.protobuf ]);
  in
  {
    default = pkgs.mkShell {
      packages = with pkgs; [
        (fenix.combine [
          fenix.stable.defaultToolchain
          fenix.targets.aarch64-unknown-linux-musl.stable.rust-std
        ])
        rust-analyzer

        # fill-station build.rs: nanopb generator (Python + protoc) and bindgen
        nanopbPython
        protobuf
        rustPlatform.bindgenHook
      ];

      NANOPB_DIR = "${pkgs.crt.nanopb-src}";
      # Full path: a bare `python3` lookup can start without this env's packages
      NANOPB_PYTHON = "${nanopbPython}/bin/python3";
    };
  }
) inputs.self.legacyPackages
