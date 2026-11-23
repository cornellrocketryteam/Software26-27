{ buildPackages, path, lib, profile ? "liquid", operatingProfile ? null }:
let
  native = import path { system = buildPackages.stdenv.buildPlatform.system; config.allowUnfreePredicate = p: lib.getName p == "ti-pru-cgt"; };
  compiler = native.callPackage ../ti-pru-cgt/package.nix { };
  pssp = native.fetchgit {
    url = "https://git.ti.com/git/pru-software-support-package/pru-software-support-package.git";
    rev = "28107daa1d184059f67676ba49d0fcaebb0f6a96";
    hash = "sha256-QeC8O9sbdboLFc/CBdieqJ6lMKXjnW6Ad98IZZ1Rmmo=";
  };
in
assert lib.assertMsg (operatingProfile == null || (profile == "hybrid" && builtins.elem operatingProfile [ "hybrid" "hybrid-test" ])) "operating selector requires Hybrid wiring";
assert lib.assertMsg (builtins.elem profile [ "liquid" "hybrid" ]) "PRU firmware requires a hardware profile";
native.stdenvNoCC.mkDerivation {
  pname = "fill-station-pru-${profile}";
  version = "1";
  src = ../../../../fill-station/pru;
  hardwareSource = ../../../../fill-station/hardware;
  nativeBuildInputs = [ native.gnumake native.python3 native.stdenv.cc native.removeReferencesTo ];
  buildPhase = ''
    runHook preBuild
    python3 "$hardwareSource/compiler.py" ${if operatingProfile == null then "--profile ${profile}" else "--operating-profile ${operatingProfile}"} --output generated
    for core in 0 1; do
      mask=$(python3 - "$core" <<'PY'
    import json,sys
    devices=json.load(open('generated/hardware-runtime.json'))['devices']
    bits=[d['pwm']['bit'] for d in devices if d.get('pwm',{}).get('backend')=='pru' and d['pwm']['core']==int(sys.argv[1])]
    print(sum(1 << bit for bit in bits))
    PY
      )
      make CORE=$core MASK=$mask BUILD=build/$core PRU_CGT=${compiler} PSSP=${pssp}
    done
    runHook postBuild
  '';
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    make test
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib/firmware $out/share/fill-station-pru
    cp build/0/fill-station-pru0_0-fw build/1/fill-station-pru0_1-fw $out/lib/firmware/
    cp build/0/firmware.map $out/share/fill-station-pru/pru0.map
    cp build/1/firmware.map $out/share/fill-station-pru/pru1.map
    cp generated/hardware-runtime.json $out/share/fill-station-pru/
    remove-references-to -t ${compiler} -t ${pssp} $out/lib/firmware/* $out/share/fill-station-pru/*.map
    runHook postInstall
  '';
  allowedReferences = [ ];
  meta.description = "AM64x ICSSG0 multi-channel PWM remoteproc firmware";
}
