{
  perSystem =
    { pkgs, ... }:
    {
      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          cargo
          rustc
          clippy
          rustfmt
          rust-analyzer

          # fill-station build.rs: protoc for the nanopb generator, libclang for bindgen
          protobuf
          rustPlatform.bindgenHook
        ];

        env = {
          # Same nanopb source and generator Python as the Nix build
          inherit (pkgs.crt.fill-station.drvAttrs) NANOPB_DIR NANOPB_PYTHON;
          # std sources for rust-analyzer
          RUST_SRC_PATH = "${pkgs.rustPlatform.rustLibSrc}";
        };
      };
    };
}
