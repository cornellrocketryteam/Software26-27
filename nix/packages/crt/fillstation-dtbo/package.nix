{
  buildPackages,
  lib,
  profile ? "hybrid",
}:
let
  inherit (buildPackages)
    stdenvNoCC
    dtc
    python3
    ;
  # We only preprocess DTS with -nostdinc. A target-aware compiler wrapper
  # unnecessarily pulls target libc/GCC into a native device-tree build.
  clang = buildPackages.llvmPackages.clang-unwrapped;
in
assert lib.assertMsg (builtins.elem profile [
  "liquid"
  "hybrid"
]) "fillstation-dtbo requires profile liquid or hybrid (paired with fillStation.mode)";
stdenvNoCC.mkDerivation {
  name = "fillstation-${profile}-pinmux-overlay";
  src = ../../../../fill-station/hardware;
  nativeBuildInputs = [
    dtc
    clang
    python3
  ];
  buildPhase = ''
    runHook preBuild
    python3 compiler.py --profile ${profile} --output generated
    cp ${./src/k3.h} generated/k3.h
    clang -E -P -undef -nostdinc -x assembler-with-cpp -I generated \
      generated/k3-am64-fillstation-pinmux-overlay.dts -o overlay.pp.dts
    dtc -@ -I dts -O dtb -o k3-am64-fillstation-pinmux-overlay.dtbo overlay.pp.dts
    fdtget -p k3-am64-fillstation-pinmux-overlay.dtbo /__symbols__ >/dev/null
    fdtget -p k3-am64-fillstation-pinmux-overlay.dtbo /__fixups__ >/dev/null
    runHook postBuild
  '';
  doCheck = true;
  checkPhase = ''
    HARDWARE_SOURCE="$PWD" python3 ${../../../../tests/test_hardware_config.py}
    PINMUX_SOURCE="$PWD" python3 ${../../../../tests/test_pinmux.py}
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p $out
    cp k3-am64-fillstation-pinmux-overlay.dtbo generated/* $out/
    cp profiles/${profile}.json $out/profile.json
    cp board-pins.json $out/board-pins.json
    # Use the filename expected by the FIT builder, without the store hash.
    cp ${./verify-merged.py} $out/verify-merged.py
    printf '%s\n' '${profile}' > $out/profile
    runHook postInstall
  '';

  allowedReferences = [ ];
}
