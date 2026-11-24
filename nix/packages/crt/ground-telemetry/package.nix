{ lib, stdenvNoCC, python3, makeWrapper, cameraViewer ? false }:
stdenvNoCC.mkDerivation {
  pname = "ground-telemetry";
  version = "1";
  src = lib.fileset.toSource {
    root = ../../../../ground-station;
    fileset = lib.fileset.unions (map (relative: ../../../../ground-station + "/${relative}") [
      "provisioning/runtime.py" "provisioning/throughput.py" "provisioning/roles.sql"
      "create-telemetry-table.sql" "emqx_action.sql" "emqx_rule.sql"
      "emqx_rule_fill_station.sql" "proto/telemetry.proto"
      "migrations/001-hardware-availability.sql" "migrations/002-source-metadata.sql" "migrations/003-session-queries.sql" "migrations/004-lc2-telemetry.sql" "migrations/005-operating-profile-identity.sql" "migrations/006-output-diagnostics.sql" "grafana.json"
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
    python provisioning/throughput.py --help >/dev/null
    python provisioning/throughput.py --session 00000000000000000000000000000001 > report.sql
    grep -q 'BEGIN READ ONLY' report.sql
    python provisioning/runtime.py assets --source . --output assets ${lib.optionalString cameraViewer "--cameras"}
    test -s assets/grafana/provisioning/datasources/telemetry.yaml
    test -s assets/proto/telemetry.proto
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/libexec" "$out/bin" "$out/share"
    cp provisioning/runtime.py "$out/libexec/ground-telemetry.py"
    cp provisioning/throughput.py "$out/libexec/ground-telemetry-throughput.py"
    cp -R assets "$out/share/ground-telemetry"
    makeWrapper ${python3}/bin/python3 "$out/bin/ground-telemetry" \
      --add-flags "$out/libexec/ground-telemetry.py"
    makeWrapper ${python3}/bin/python3 "$out/bin/crt-telemetry-throughput" \
      --add-flags "$out/libexec/ground-telemetry-throughput.py"
    runHook postInstall
  '';
  meta = {
    description = "Offline ground-station telemetry provisioning and public assets";
    platforms = lib.platforms.unix;
  };
}
