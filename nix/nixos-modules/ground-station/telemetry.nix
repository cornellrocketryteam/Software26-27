{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.telemetry;
  names = [ "timescaledb" "emqx" "grafana" ];
  runtimePath = path: path != null && path != "/"
    && builtins.match "/[A-Za-z0-9_./-]+" path != null
    && !(lib.hasPrefix "/nix/store" path)
    && lib.all (part: part != "." && part != "..") (lib.splitString "/" path);
  validPin = pin:
    builtins.match "[a-z0-9][a-z0-9./:_-]*" pin.imageName != null
    && builtins.match "sha256:[a-f0-9]{64}" pin.imageDigest != null
    && builtins.match "(sha256-[A-Za-z0-9+/]{43}=|[a-f0-9]{64}|[0-9abcdfghijklmnpqrsvwxyz]{52})" pin.sha256 != null;
  validPins = builtins.attrNames cfg.imagePins == lib.sort builtins.lessThan names
    && lib.all (name: validPin cfg.imagePins.${name}) names;
  rootUrl = config.groundStation.grafana.rootUrl;
  validRootUrl = rootUrl == null || (
    builtins.match "https?://[^/@?#[:space:][:cntrl:]\\\\]+/[^[:space:][:cntrl:]\\\\]*" rootUrl != null
    && lib.hasSuffix "/grafana/" rootUrl
  );
  active = cfg.enable && validPins && runtimePath cfg.secretsFile && runtimePath cfg.stateDirectory;
  helper = pkgs.crt.ground-telemetry or (pkgs.callPackage ../../packages/crt/ground-telemetry/package.nix { });
  executable = "${helper}/bin/ground-telemetry";
  assets = "${helper}/share/ground-telemetry";
  archives = lib.genAttrs names (name: let pin = cfg.imagePins.${name}; in pkgs.dockerTools.pullImage {
    inherit (pin) imageName imageDigest sha256;
    os = "linux";
    arch = "amd64";
    finalImageName = "crt-ground-${name}";
    finalImageTag = "sha256-${lib.removePrefix "sha256:" pin.imageDigest}";
  });
  container = name: {
    image = "${archives.${name}.imageName}:${archives.${name}.imageTag}";
    imageFile = archives.${name};
    pull = "never";
    extraOptions = [ "--network=host" ];
    environmentFiles = [ "/run/ground-telemetry/${{
      timescaledb = "database"; emqx = "emqx"; grafana = "grafana";
    }.${name}}.env" ];
  };
  retry = {
    unitConfig.StartLimitIntervalSec = 0;
    serviceConfig = {
      Type = "oneshot";
      User = "root";
      UMask = "0077";
      Restart = "on-failure";
      RestartSec = 5;
      TimeoutStartSec = 180;
      NoNewPrivileges = true;
    };
  };
  dbUnit = "docker-ground-timescaledb.service";
  emqxUnit = "docker-ground-emqx.service";
  migrationUnit = "ground-telemetry-database.service";
  grafanaUnit = "docker-ground-grafana.service";
  containerUnit = {
    # A failed Requires/After start does not run the container's Restart policy.
    # Re-request it in each prepare start transaction, including automatic
    # retries. Wants does not add ordering: prepare must never wait on these.
    wantedBy = [ "ground-telemetry-prepare.service" ];
    requires = [ "ground-telemetry-prepare.service" ];
    after = [ "ground-telemetry-prepare.service" ];
    unitConfig.StartLimitIntervalSec = 0;
    serviceConfig = {
      # Loading the prepared archive is bounded; no registry fallback exists.
      TimeoutStartSec = lib.mkForce 300;
      RestartSec = 5;
    };
  };
in
{
  options.groundStation.telemetry = {
    enable = lib.mkEnableOption "offline pinned telemetry containers and bounded local provisioning";
    secretsFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Private runtime credentials JSON outside /nix/store. Provision it independently; no secret contents enter the Nix evaluation.";
    };
    stateDirectory = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/ground-station/telemetry";
      description = "Separate persistent telemetry state, with safe absolute path components. Never point this at existing Compose volumes without inventory, backups and migration acceptance.";
    };
    imagePins = lib.mkOption {
      default = { };
      type = lib.types.attrsOf (lib.types.submodule {
        options = lib.genAttrs [ "imageName" "imageDigest" "sha256" ] (name: lib.mkOption {
          type = lib.types.str;
          default = "";
          description = {
            imageName = "Inventoried registry repository name.";
            imageDigest = "Immutable sha256 registry digest.";
            sha256 = "Verified dockerTools.pullImage archive hash for the exact Linux/amd64 local name/tag.";
          }.${name};
        });
      });
      description = "Exactly timescaledb, emqx and grafana pins. No default images, mutable tags or guessed archive hashes.";
    };
  };

  config = lib.mkMerge [
    {
      assertions = [
        { assertion = cfg.enable -> validPins;
          message = "ground-station telemetry image pins require exactly timescaledb, emqx and grafana with valid repository, sha256 digest and verified archive hash."; }
        { assertion = cfg.enable -> runtimePath cfg.secretsFile;
          message = "ground-station telemetry runtime credentials require an absolute private path outside /nix/store without traversal or control characters."; }
        { assertion = cfg.enable -> runtimePath cfg.stateDirectory;
          message = "ground-station telemetry stateDirectory must be a safe absolute persistent path outside /nix/store, without traversal or configuration characters."; }
        { assertion = cfg.enable -> !config.groundStation.grafana.enable;
          message = "ground-station telemetry requires native Grafana disabled to avoid port and provisioning conflicts."; }
        { assertion = cfg.enable -> validRootUrl;
          message = "ground-station telemetry Grafana rootUrl must be reviewed HTTP(S), without embedded credentials, and end in /grafana/."; }
        { assertion = cfg.enable -> (config.groundStation.network.lanInterfaces == [ ] || rootUrl != null);
          message = "ground-station telemetry LAN Grafana requires the reviewed external groundStation.grafana.rootUrl, including port and /grafana/."; }
      ];
    }
    (lib.mkIf active {
      system.build.groundTelemetryImages = archives;
      systemd.tmpfiles.rules = [
        "d ${cfg.stateDirectory} 0750 root root - -"
        "d ${cfg.stateDirectory}/db 0700 root root - -"
        "d ${cfg.stateDirectory}/emqx 0750 root root - -"
        "d ${cfg.stateDirectory}/emqx/data 0700 1000 1000 - -"
        "d ${cfg.stateDirectory}/emqx/log 0700 1000 1000 - -"
        "d ${cfg.stateDirectory}/grafana 0700 472 472 - -"
      ];
      networking.firewall.interfaces = lib.genAttrs config.groundStation.network.lanInterfaces (_: {
        allowedTCPPorts = [ 1883 ];
      });
      virtualisation.oci-containers = {
        backend = "docker";
        containers = {
          ground-timescaledb = container "timescaledb" // {
            environment = { POSTGRES_USER = "postgres"; POSTGRES_DB = "telemetry"; PGDATA = "/pgdata"; };
            cmd = [
              "postgres" "-c" "listen_addresses=127.0.0.1" "-c" "port=5432"
              "-c" "hba_file=/etc/ground-telemetry/pg_hba.conf"
            ];
            volumes = [
              "${cfg.stateDirectory}/db:/pgdata"
              # Override image/PGDATA authentication defaults on every start.
              "${assets}/database/pg_hba.conf:/etc/ground-telemetry/pg_hba.conf:ro"
            ];
          };
          ground-emqx = container "emqx" // {
            user = "1000:1000";
            environment = {
              EMQX_NODE__NAME = "emqx@127.0.0.1";
              EMQX_DASHBOARD__LISTENERS__HTTP__BIND = "127.0.0.1:18083";
              EMQX_DASHBOARD__LISTENERS__HTTPS__BIND = "0";
              EMQX_LISTENERS__TCP__DEFAULT__BIND = if config.groundStation.network.lanInterfaces == [ ]
                then "127.0.0.1:1883" else "0.0.0.0:1883";
              EMQX_LISTENERS__SSL__DEFAULT__ENABLE = "false";
              EMQX_LISTENERS__WS__DEFAULT__ENABLE = "false";
              EMQX_LISTENERS__WSS__DEFAULT__ENABLE = "false";
              # EMQX 5.8 management auth reads [api_key, bootstrap_file]:
              # https://github.com/emqx/emqx/blob/v5.8.8/apps/emqx_management/src/emqx_mgmt_auth.erl
              EMQX_API_KEY__BOOTSTRAP_FILE = "/opt/emqx/etc/api-keys.bootstrap";
            };
            volumes = [
              "${cfg.stateDirectory}/emqx/data:/opt/emqx/data"
              "${cfg.stateDirectory}/emqx/log:/opt/emqx/log"
              "/run/ground-telemetry/api-keys.bootstrap:/opt/emqx/etc/api-keys.bootstrap:ro"
            ];
          };
          ground-grafana = container "grafana" // {
            user = "472:472";
            environment = {
              GF_SERVER_HTTP_ADDR = "127.0.0.1";
              GF_SERVER_HTTP_PORT = "3000";
              GF_SERVER_ROOT_URL = if rootUrl == null then "http://localhost:${toString config.groundStation.network.webPort}/grafana/" else rootUrl;
              GF_SERVER_SERVE_FROM_SUB_PATH = "true";
              GF_SECURITY_ALLOW_EMBEDDING = "true";
              GF_SECURITY_DISABLE_GRAVATAR = "true";
              GF_AUTH_ANONYMOUS_ENABLED = "true";
              GF_AUTH_ANONYMOUS_ORG_ROLE = "Viewer";
              GF_USERS_ALLOW_SIGN_UP = "false";
              GF_DASHBOARDS_MIN_REFRESH_INTERVAL = "125ms";
              GF_PLUGINS_PREINSTALL_DISABLED = "true";
              GF_PLUGINS_PREINSTALL = "";
              GF_INSTALL_PLUGINS = "";
              GF_ANALYTICS_REPORTING_ENABLED = "false";
              GF_ANALYTICS_CHECK_FOR_UPDATES = "false";
              GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES = "false";
              # The legacy camera text panel must not execute arbitrary HTML.
              GF_PANELS_DISABLE_SANITIZE_HTML = "false";
            };
            volumes = [
              "${cfg.stateDirectory}/grafana:/var/lib/grafana"
              "${assets}/grafana/provisioning:/etc/grafana/provisioning:ro"
              "${assets}/grafana/dashboards:/var/lib/grafana/dashboards:ro"
            ];
          };
        };
      };

      systemd.services = lib.genAttrs (map (name: "docker-ground-${name}") names) (_: containerUnit) // {
        docker-ground-grafana = lib.recursiveUpdate containerUnit {
          # Migration can fail before Grafana ever executes. A migration retry
          # must request Grafana again as well as broker reconciliation.
          wantedBy = [ "ground-telemetry-prepare.service" migrationUnit ];
          requires = [ "ground-telemetry-prepare.service" migrationUnit ];
          after = [ "ground-telemetry-prepare.service" migrationUnit ];
        };
        ground-telemetry-prepare = lib.recursiveUpdate retry {
          wantedBy = [ "multi-user.target" ];
          serviceConfig = {
            RemainAfterExit = true;
            RuntimeDirectory = "ground-telemetry";
            RuntimeDirectoryMode = "0700";
            RuntimeDirectoryPreserve = "yes";
            TimeoutStartSec = 30;
            ExecStart = "${executable} prepare --secrets-file ${cfg.secretsFile} --output /run/ground-telemetry";
          };
        };
        ground-telemetry-database = lib.recursiveUpdate retry {
          wantedBy = [ "multi-user.target" dbUnit ];
          requires = [ "ground-telemetry-prepare.service" dbUnit ];
          after = [ "ground-telemetry-prepare.service" dbUnit ];
          bindsTo = [ dbUnit ];
          partOf = [ dbUnit ];
          serviceConfig = {
            RemainAfterExit = true;
            TimeoutStartSec = 240;
            ExecStart = "${executable} database --docker ${config.virtualisation.docker.package}/bin/docker --assets ${assets}";
          };
        };
        ground-telemetry-broker = lib.recursiveUpdate retry {
          wantedBy = [ "multi-user.target" emqxUnit migrationUnit ];
          requires = [ "ground-telemetry-prepare.service" migrationUnit emqxUnit ];
          after = [ "ground-telemetry-prepare.service" migrationUnit emqxUnit ];
          bindsTo = [ migrationUnit emqxUnit ];
          partOf = [ migrationUnit emqxUnit ];
          serviceConfig = {
            RemainAfterExit = true;
            ExecStart = "${executable} broker --secrets-file ${cfg.secretsFile} --assets ${assets} --api-url http://127.0.0.1:18083/api/v5";
          };
        };
        ground-telemetry-grafana-ready = lib.recursiveUpdate retry {
          requires = [ grafanaUnit ];
          after = [ grafanaUnit ];
          bindsTo = [ grafanaUnit ];
          partOf = [ grafanaUnit ];
          serviceConfig = {
            RemainAfterExit = false;
            TimeoutStartSec = 75;
            ExecStart = "${executable} wait --url http://127.0.0.1:3000/grafana/api/health";
          };
        };
      };
      systemd.timers.ground-telemetry-grafana-ready = {
        description = "Recurring local Grafana HTTP probe; not full station readiness";
        wantedBy = [ "timers.target" ];
        timerConfig = { OnBootSec = "20s"; OnUnitInactiveSec = "30s"; };
      };
    })
  ];
}
