# Runs actual generated nginx routes, not a hand-maintained proxy facsimile.
{ pkgs }:
let
  evaluated = (import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [ ../../nix/nixos-modules/ground-station/cameras.nix {
      nixpkgs.pkgs = pkgs;
      system.stateVersion = "26.05";
      groundStation.cameras = {
        enable = true;
        credentialsFile = "/private/fixture.json";
      };
      services.nginx = {
        recommendedProxySettings = true;
        logError = "stderr";
        commonHttpConfig = "access_log off;";
        virtualHosts.ground-station = {
          listen = [ { addr = "127.0.0.1"; port = 18080; } ];
          locations."= /healthz".return = "200 'dashboard alive'";
        };
      };
    } ];
  }).config;
in
pkgs.runCommand "ground-camera-serving-tests" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nginx ];
  NGINX_CONFIG = evaluated.environment.etc."nginx/nginx.conf".source;
} ''
  export PYTHONDONTWRITEBYTECODE=1
  python ${./test_cameras_serving.py}
  touch "$out"
''
