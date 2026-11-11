{ lib, stdenvNoCC, python3, makeWrapper }:
stdenvNoCC.mkDerivation {
  pname = "ground-telemetry";
  version = "1";
  src = lib.fileset.toSource {
    root = ../../../../ground-station;
    fileset = lib.fileset.unions (map (relative: ../../../../ground-station + "/${relative}") [
      "provisioning/runtime.py" "provisioning/roles.sql"
      "create-telemetry-table.sql" "emqx_action.sql" "emqx_rule.sql"
      "emqx_rule_fill_station.sql" "proto/telemetry.proto"
      "migrations/001-hardware-availability.sql" "grafana.json"
    ]);
  };
  nativeBuildInputs = [ python3 makeWrapper ];
  dontConfigure = true;
  dontBuild = true;
  doCheck = true;
  __darwinAllowLocalNetworking = true;
  checkPhase = ''
    runHook preCheck
    testRoot="$TMPDIR/ground-telemetry-check"
    mkdir -p "$testRoot/ground-station" "$testRoot/tests/platform"
    cp -R . "$testRoot/ground-station/"
    cp ${../../../../tests/platform/test_telemetry_runtime.py} "$testRoot/tests/platform/test_telemetry_runtime.py"
    python -m unittest discover -s "$testRoot/tests/platform" -p test_telemetry_runtime.py
    python provisioning/runtime.py --help >/dev/null
    python provisioning/runtime.py assets --source . --output assets
    test -s assets/grafana/provisioning/datasources/telemetry.yaml
    test -s assets/proto/telemetry.proto
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/libexec" "$out/bin" "$out/share"
    cp provisioning/runtime.py "$out/libexec/ground-telemetry.py"
    cp -R assets "$out/share/ground-telemetry"
    makeWrapper ${python3}/bin/python3 "$out/bin/ground-telemetry" \
      --add-flags "$out/libexec/ground-telemetry.py"
    runHook postInstall
  '';
  meta = {
    description = "Offline ground-station telemetry provisioning and public assets";
    platforms = lib.platforms.unix;
  };
}
