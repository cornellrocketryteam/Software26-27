{ lib, buildNpmPackage }:
buildNpmPackage {
  pname = "ground-operator-ui";
  version = "0.0.0";

  # Never import a workstation's dependencies, generated assets or Git data.
  src = lib.cleanSourceWith {
    src = ../../../../Ground_Station_UI;
    filter = path: type:
      !(builtins.elem (baseNameOf path) [ "node_modules" "dist" ".git" ]);
  };

  # Verified from this repository's package-lock.json using fetchNpmDeps.
  npmDepsHash = "sha256-ZrG5fJ2GSmAXYCy3QbzSIy0+w7jB9+zD8Bdh6HVwLg8=";
  npmBuildScript = "build"; # package.json: tsc -b && vite build
  npmInstallFlags = [ "--ignore-scripts" ];
  npmRebuildFlags = [ "--ignore-scripts" ];

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    npm test
    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -R dist/. "$out/"
    test -s "$out/index.html"
    test -s "$out/station-config.json"
    runHook postInstall
  '';

  meta = {
    description = "Bundled Cornell Rocketry ground-station operator UI";
    platforms = lib.platforms.unix;
  };
}
