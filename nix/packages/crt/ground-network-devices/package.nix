{ lib, stdenvNoCC, python3, makeWrapper }:
stdenvNoCC.mkDerivation {
  pname = "ground-network-devices";
  version = "1";
  src = lib.fileset.toSource {
    root = ../../../../ground-station/network-devices;
    fileset = lib.fileset.unions (map (name: ../../../../ground-station/network-devices + "/${name}") [
      "service.py" "shelly.py" "wan.py" "inspect_omada.py" "ecoflow_probe.py" "inventory.json"
    ]);
  };
  nativeBuildInputs = [ python3 makeWrapper ];
  dontConfigure = true;
  dontBuild = true;
  doCheck = true;
  __darwinAllowLocalNetworking = true;
  checkPhase = ''
    export PYTHONDONTWRITEBYTECODE=1
    testRoot="$TMPDIR/network-device-tests"
    mkdir -p "$testRoot/ground-station/network-devices" "$testRoot/tests/platform"
    cp *.py inventory.json "$testRoot/ground-station/network-devices/"
    cp ${../../../../tests/platform/test_network_devices.py} "$testRoot/tests/platform/"
    cp ${../../../../tests/platform/test_shelly.py} "$testRoot/tests/platform/"
    cp ${../../../../tests/platform/test_wan_monitor.py} "$testRoot/tests/platform/"
    cp ${../../../../tests/platform/test_ecoflow_probe.py} "$testRoot/tests/platform/"
    python -m unittest discover -s "$testRoot/tests/platform" -p test_ecoflow_probe.py
    python -m unittest discover -s "$testRoot/tests/platform" -p test_wan_monitor.py
    cp ${../../../../tests/platform/test_omada_inspection.py} "$testRoot/tests/platform/"
    python -m unittest discover -s "$testRoot/tests/platform" -p test_omada_inspection.py
    python -m unittest discover -s "$testRoot/tests/platform" -p test_network_devices.py
    python -m unittest discover -s "$testRoot/tests/platform" -p test_shelly.py
    python service.py --check-config
  '';
  installPhase = ''
    mkdir -p "$out/libexec/ground-network-devices" "$out/bin"
    cp *.py inventory.json "$out/libexec/ground-network-devices/"
    makeWrapper ${python3}/bin/python3 "$out/bin/crt-network-devices" \
      --add-flags "$out/libexec/ground-network-devices/service.py"
    makeWrapper ${python3}/bin/python3 "$out/bin/crt-inspect-omada" \
      --add-flags "$out/libexec/ground-network-devices/inspect_omada.py"
    makeWrapper ${python3}/bin/python3 "$out/bin/crt-probe-ecoflow" \
      --add-flags "$out/libexec/ground-network-devices/ecoflow_probe.py"
  '';
  meta = {
    description = "Local network-device status and explicit authenticated Shelly power API";
    platforms = lib.platforms.linux;
  };
}
