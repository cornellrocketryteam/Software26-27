{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.ecoflow;
  package = pkgs.callPackage ../../packages/crt/ground-network-devices/package.nix { };
  runtimeFile = path: path != null && lib.hasPrefix "/" path
    && !(lib.hasPrefix "/nix/store" path)
    && builtins.match "/[A-Za-z0-9_./-]+" path != null
    && lib.all (part: part != "." && part != "..") (lib.splitString "/" path);
  disabled = builtins.toJSON {
    enabled = false; state = "disabled"; readOnly = true; deviceSampleTimeKnown = false;
    ageSeconds = null; batteryPercent = null; inputWatts = null; outputWatts = null;
  };
in {
  options.groundStation.ecoflow = {
    enable = lib.mkEnableOption "isolated read-only EcoFlow developer-cloud monitoring";
    region = lib.mkOption { type = lib.types.nullOr (lib.types.enum [ "us" "eu" ]); default = null; };
    serial = lib.mkOption { type = lib.types.strMatching "[A-Za-z0-9]{0,64}"; default = ""; };
    credentialsFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str; default = null;
      description = "Owner-only runtime JSON with developer accessKey and secretKey, outside the Nix store.";
    };
    intervalSeconds = lib.mkOption { type = lib.types.ints.between 30 300; default = 30; };
    port = lib.mkOption { type = lib.types.port; default = 8768; };
  };
  config = lib.mkMerge [ {
    services.nginx.virtualHosts.ground-station.locations."/ecoflow-api/" =
      if cfg.enable then {
        proxyPass = "http://127.0.0.1:${toString cfg.port}/";
        extraConfig = "limit_except GET { deny all; }";
      } else {
        extraConfig = ''
          default_type application/json;
          add_header Cache-Control no-store always;
          return 200 '${disabled}';
        '';
      };
  } (lib.mkIf cfg.enable {
    assertions = [ {
      assertion = cfg.region != null && cfg.serial != "" && runtimeFile cfg.credentialsFile;
      message = "EcoFlow monitoring needs explicit account region, serial and runtime credential path outside the store.";
    } ];
    systemd.services.ground-ecoflow = {
      description = "Optional read-only EcoFlow cloud collector";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [ "${package}/bin/crt-monitor-ecoflow"
          "--region" (if cfg.region == null then "us" else cfg.region)
          "--serial" cfg.serial "--credentials-file" "%d/ecoflow"
          "--interval" (toString cfg.intervalSeconds) "--port" (toString cfg.port) ];
        LoadCredential = lib.optional (cfg.credentialsFile != null) "ecoflow:${cfg.credentialsFile}";
        DynamicUser = true;
        NoNewPrivileges = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        # Cloud host IPs vary; this separate service needs DNS and outbound HTTPS.
        # The LAN-only network-device service retains its existing IP restrictions.
        MemoryMax = "128M";
        TasksMax = 32;
        CPUQuota = "10%";
        Restart = "on-failure";
        RestartSec = 10;
        TimeoutStopSec = 5;
        KillMode = "control-group";
        UMask = "0077";
      };
    };
  }) ];
}
