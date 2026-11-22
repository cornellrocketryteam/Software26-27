{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.cameras;
  assets = ../../.. + "/ground-station/cameras";
  helper = pkgs.writeShellScriptBin "ground-camera-credentials" ''
    exec ${pkgs.python3}/bin/python3 ${assets}/credentials.py "$@"
  '';
  privatePath = cfg.credentialsFile != null
    && lib.hasPrefix "/" cfg.credentialsFile
    && !(lib.hasPrefix "/nix/store" cfg.credentialsFile)
    && builtins.match "/[A-Za-z0-9_./-]+" cfg.credentialsFile != null
    && lib.all (part: part != "." && part != "..") (lib.splitString "/" cfg.credentialsFile);
  readOnly = ''
    if ($request_method !~ ^(GET|HEAD)$) { return 405; }
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
  '';
  streamLocations = lib.genAttrs [ "fillcam0" "fillcam1" "fillcam2" ] (name: {
    # Avoid duplicate Host headers from the parent's recommended proxy include.
    recommendedProxySettings = false;
    proxyPass = "http://127.0.0.1:${toString cfg.apiPort}/api/stream.mp4?src=${name}&video&audio=none";
    extraConfig = readOnly + ''
      # Clear caller arguments before nginx constructs the fixed upstream URI.
      set $args "";
      proxy_pass_request_body off;
      proxy_pass_request_headers off;
      proxy_set_header Host "127.0.0.1";
      proxy_set_header User-Agent "ground-station-camera";
      proxy_set_header Content-Length "";
      proxy_buffering off;
      proxy_cache off;
      proxy_connect_timeout 2s;
      proxy_read_timeout 15s;
      proxy_intercept_errors on;
      error_page 301 302 303 307 308 400 401 403 404 500 502 503 504 =502 /cameras/unavailable.txt;
      proxy_hide_header Location;
    '';
  });
in
{
  options.groundStation.cameras = {
    enable = lib.mkEnableOption "private native camera relay and standalone viewer (no physical acceptance implied)";
    credentialsFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Absolute private runtime JSON file outside the Nix store; see ground-station-cameras.md. Never use a Nix path literal or builtins.readFile.";
    };
    apiPort = lib.mkOption {
      type = lib.types.port;
      default = 1984;
      description = "Loopback-only relay HTTP port; never opened in the firewall.";
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.go2rtc;
      description = "Native package from locked Nixpkgs. Must remain version 1.9.15.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = privatePath; message = "Camera credentialsFile must be an absolute private runtime path outside /nix/store, without traversal."; }
      { assertion = cfg.package.version == "1.9.15"; message = "Camera relay requires locked Nixpkgs go2rtc 1.9.15; revalidate transport before upgrading."; }
      { assertion = cfg.apiPort >= 1024; message = "Camera API must use an unprivileged loopback port."; }
    ];
    environment.systemPackages = [ helper ];
    systemd.services.ground-station-cameras = {
      description = "Private camera RTSP to HTTP relay (camera availability is not boot readiness)";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      startLimitIntervalSec = 0;
      serviceConfig = {
        Type = "simple";
        DynamicUser = true;
        RuntimeDirectory = "ground-station-cameras";
        RuntimeDirectoryMode = "0700";
        UMask = "0077";
        LoadCredential = lib.optional privatePath "cameras.json:${cfg.credentialsFile}";
        ExecStartPre = pkgs.writeShellScript "render-camera-config" ''
          set -eu
          rm -f /run/ground-station-cameras/go2rtc.yaml
          ${helper}/bin/ground-camera-credentials render \
            --credentials "$CREDENTIALS_DIRECTORY/cameras.json" \
            --output /run/ground-station-cameras/go2rtc.yaml --port ${toString cfg.apiPort}
        '';
        ExecStart = "${lib.getExe cfg.package} -config /run/ground-station-cameras/go2rtc.yaml";
        Restart = "always";
        RestartSec = "5s";
        TimeoutStartSec = "15s";
        # Producer errors can contain RTSP userinfo. Never journal relay output.
        StandardOutput = "null";
        StandardError = "null";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        CapabilityBoundingSet = "";
      };
    };
    services.nginx.enable = true;
    services.nginx.virtualHosts.ground-station.locations = {
      "= /cameras".return = "302 /cameras/";
      "= /cameras/" = { root = assets; tryFiles = "/index.html =404"; extraConfig = readOnly + "default_type text/html;"; };
      "= /cameras/viewer.js" = { alias = "${assets}/viewer.js"; extraConfig = readOnly + "default_type application/javascript;"; };
      "= /cameras/unavailable.txt" = {
        extraConfig = "internal; default_type text/plain;";
        return = "502 'Camera unavailable. Retry shortly.\\n'";
      };
      "^~ /cameras/".return = "404";
    } // lib.mapAttrs' (name: value: lib.nameValuePair "= /cameras/${name}/stream.mp4" value) streamLocations;
  };
}
