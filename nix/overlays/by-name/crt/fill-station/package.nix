{
  lib,
  rustPlatform,
  buildPackages,
  crt-software-root,
  nanopb-src,
  # Also build the ADC CLI tools from src/bin/ (adc_monitor, adc_test, ...).
  # Off by default to keep the production image small.
  withHelpers ? false,
  # Build mode: "none", "liquid", or "hybrid"
  mode ? "none",
}:
rustPlatform.buildRustPackage (finalAttrs: {
  pname = "fill-station";
  version = "0.1.0";

  src = crt-software-root + /fill-station;
  cargoLock.lockFile = finalAttrs.src + /Cargo.lock;

  # Only build the main binary unless the helpers are wanted
  cargoBuildFlags = lib.optionals (!withHelpers) [
    "--bin"
    "fill-station"
  ] ++ lib.optionals (mode != "none") [
    "--features"
    mode
  ];

  # build.rs generates the telemetry protobuf code with nanopb (Python + protoc,
  # both run on the build machine) and binds it with bindgen (needs libclang).
  nativeBuildInputs = [
    (buildPackages.python3.withPackages (ps: [ ps.protobuf ]))
    buildPackages.protobuf
    rustPlatform.bindgenHook
  ];
  env = {
    NANOPB_DIR = "${nanopb-src}";
    NANOPB_PYTHON = "${buildPackages.python3.withPackages (ps: [ ps.protobuf ])}/bin/python3";
  };

  # Skip tests (since we don't have any)
  doCheck = false;

  # Install all binaries from src/bin/, not just the main one
  postInstall = lib.optionalString withHelpers ''
    # The main binary is already installed, now add the others
    for bin in target/*/release/*; do
      if [ -f "$bin" ] && [ -x "$bin" ]; then
        basename=$(basename "$bin")
        # Skip .d files, libraries, and the main fill-station binary (already installed)
        if [[ "$basename" != *.d ]] && [[ "$basename" != lib* ]] && [[ "$basename" != "fill-station" ]]; then
          install -Dm755 "$bin" "$out/bin/$basename"
        fi
      fi
    done
  '';

  meta = {
    description = "Fill Station Binary and Utilities";
    mainProgram = "fill-station";
    # platforms = lib.platforms.linux;
  };
})
