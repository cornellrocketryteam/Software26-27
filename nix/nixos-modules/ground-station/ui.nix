{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.grafana;
  runtimeKey = cfg.secretKeyFile != null
    && lib.hasPrefix "/" cfg.secretKeyFile
    && !(lib.hasPrefix "/nix/store" cfg.secretKeyFile);
  landing = pkgs.writeTextDir "index.html" ''
    <!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Ground station — not provisioned</title>
    <body><h1>Ground station not provisioned</h1>
    <p>This offline foundation is running. Telemetry, database, broker,
    operator UI, map tiles and physical commanding are not ready.</p>
    <p>Fill-station connection: not configured. No commands are sent by this page.</p>
    <p>Container archives, immutable image pins, provisioning and kiosk setup
    require a reviewed deployment configuration. Do not use for operations.</p>
    <p>Host liveness: <a href="/healthz">/healthz</a>.
    Operational readiness: <a href="/readyz">/readyz</a> (unavailable).</p>
    </body></html>
  '';
in
{
  options.groundStation.grafana = {
    enable = lib.mkEnableOption "native Grafana foundation, separate from the pending pinned telemetry stack";
    secretKeyFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Runtime Grafana secret-key file outside /nix/store. No default administrative password or provisioned datasources.";
    };
    rootUrl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Reviewed external HTTP(S) URL ending in /grafana/, required for LAN access. Null uses the loopback HTTP endpoint.";
    };
  };

  config = {
    assertions = [
      {
        assertion = cfg.enable -> runtimeKey;
        message = "ground-station Grafana runtime secret must be provisioned as an absolute path outside /nix/store before enabling native Grafana.";
      }
      {
        assertion = cfg.enable -> (config.groundStation.network.lanInterfaces == [ ] || cfg.rootUrl != null);
        message = "ground-station LAN Grafana requires the reviewed external rootUrl, including port and /grafana/.";
      }
      {
        assertion = cfg.rootUrl != null -> (
          (lib.hasPrefix "http://" cfg.rootUrl || lib.hasPrefix "https://" cfg.rootUrl)
          && lib.hasSuffix "/grafana/" cfg.rootUrl
        );
        message = "ground-station Grafana rootUrl must be an HTTP(S) URL ending in /grafana/.";
      }
    ];

    services.nginx = {
      enable = true;
      recommendedProxySettings = true;
      virtualHosts.ground-station = {
        default = true;
        listen = [ {
          addr = if config.groundStation.network.lanInterfaces == [ ] then "127.0.0.1" else "0.0.0.0";
          port = config.groundStation.network.webPort;
        } ];
        root = landing;
        locations = {
          "/".tryFiles = "$uri $uri/ =404";
          "= /healthz".return = "200 'Ground station foundation running.\\n'";
          "= /readyz".return = "503 'Ground station not provisioned; telemetry and commanding are unavailable.\\n'";
          "/cache/" = lib.mkIf config.services.harmonia.cache.enable {
            proxyPass = "http://127.0.0.1:5000/";
          };
          "/grafana/" = lib.mkIf cfg.enable {
            proxyPass = "http://127.0.0.1:3000";
            proxyWebsockets = true;
          };
        };
      };
    };

    services.grafana = lib.mkIf cfg.enable {
      enable = true;
      openFirewall = false;
      settings = {
        server = {
          http_addr = "127.0.0.1";
          http_port = 3000;
          root_url = if cfg.rootUrl != null then cfg.rootUrl else "http://localhost:${toString config.groundStation.network.webPort}/grafana/";
          serve_from_sub_path = true;
        };
        security = {
          disable_initial_admin_creation = true;
          admin_password = "";
          secret_key = "$__file{/run/credentials/grafana.service/secret-key}";
        };
        "auth.anonymous" = { enabled = true; org_role = "Viewer"; };
        users.allow_sign_up = false;
        analytics = {
          reporting_enabled = false;
          check_for_updates = false;
          check_for_plugin_updates = false;
        };
      };
    };
    systemd.services.grafana = lib.mkIf (cfg.enable && runtimeKey) {
      serviceConfig.LoadCredential = [ "secret-key:${cfg.secretKeyFile}" ];
    };
    systemd.services.ground-grafana-ready = lib.mkIf cfg.enable {
      description = "Bounded native Grafana HTTP readiness check (not telemetry readiness)";
      wantedBy = [ "multi-user.target" ];
      requires = [ "grafana.service" ];
      after = [ "grafana.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = 60;
        DynamicUser = true;
        NoNewPrivileges = true;
        ExecStart = pkgs.writeShellScript "ground-grafana-ready" ''
          set -eu
          status=$(${pkgs.curl}/bin/curl --fail --silent --show-error \
            --retry 15 --retry-delay 2 --retry-connrefused --max-time 2 \
            --output /dev/null --write-out '%{http_code}' \
            http://127.0.0.1:3000/grafana/api/health)
          test "$status" = 200
        '';
      };
    };
  };
}
