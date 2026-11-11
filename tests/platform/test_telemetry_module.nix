# Pure contracts with deliberately synthetic pins and helper; no image fetches,
# secrets, containers or hardware are involved in this evaluation.
{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = modules: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/vm.nix
      ({ pkgs, ... }: {
        nixpkgs.hostPlatform = "x86_64-linux";
        nixpkgs.overlays = [ (_: prev: {
          crt = (prev.crt or { }) // {
            ground-telemetry = pkgs.writeShellScriptBin "ground-telemetry" "exit 0";
          };
        }) ];
      })
    ] ++ modules;
  }).config;
  base = evaluate [ ];
  names = [ "timescaledb" "emqx" "grafana" ];
  # These all-zero values are evaluation fixtures, never deployment pins.
  pins = lib.genAttrs names (name: {
    imageName = "fixture.invalid/${name}";
    imageDigest = "sha256:${lib.concatStrings (lib.replicate 64 "0")}";
    sha256 = lib.fakeHash;
  });
  settings.groundStation.telemetry = {
    enable = true;
    secretsFile = "/run/keys/telemetry.json";
    imagePins = pins;
  };
  enabled = evaluate [ settings ];
  override = extra: evaluate [ settings extra ];
  lan = override {
    groundStation.network.lanInterfaces = [ "inspected-ethernet" ];
    groundStation.grafana.rootUrl = "http://station.test:8080/grafana/";
  };
  public = override {
    groundStation.operatorUi.enable = true;
  };
  c = enabled.virtualisation.oci-containers.containers;
  services = enabled.systemd.services;
  failed = config: lib.filter (a: !a.assertion) config.assertions;
  hasFailure = needle: config: lib.any (a: lib.hasInfix needle a.message) (failed config);
  pinOverride = value: override { groundStation.telemetry.imagePins = lib.mkForce value; };
  serviceNames = [ "docker-ground-timescaledb" "docker-ground-emqx" "docker-ground-grafana"
    "ground-telemetry-prepare" "ground-telemetry-database" "ground-telemetry-broker"
    "ground-telemetry-grafana-ready" ];
  unitNames = map (name: "${name}.service") serviceNames;
  unit = name: services.${lib.removeSuffix ".service" name};
  # A Requires/After failure never executes the blocked service, so its own
  # Restart policy cannot recover it. Check the reverse activation edges used
  # by a fresh start transaction of each successfully retried prerequisite.
  requestedBy = upstream: downstream:
    builtins.elem upstream enabled.systemd.units.${downstream}.wantedBy
    || builtins.elem downstream (unit upstream).wants;
  ordering = lib.toposort (a: b:
    builtins.elem a (unit b).after || builtins.elem b (unit a).before) unitNames;
  checks = {
    defaultDisabled = !(base.groundStation.telemetry.enable or true)
      && base.virtualisation.oci-containers.containers == { }
      && !(base.systemd.services ? ground-telemetry-prepare);
    defaultRuntimeAndState = base.groundStation.telemetry.secretsFile == null
      && base.groundStation.telemetry.stateDirectory == "/var/lib/ground-station/telemetry"
      && base.groundStation.telemetry.imagePins == { };
    requiresAllThreePins = hasFailure "telemetry image pins" (pinOverride { })
      && hasFailure "telemetry image pins" (pinOverride (builtins.removeAttrs pins [ "emqx" ]))
      && hasFailure "telemetry image pins" (pinOverride (pins // { unexpected = pins.emqx; }));
    rejectsMalformedDigest = hasFailure "telemetry image pins" (pinOverride (pins // {
      emqx = pins.emqx // { imageDigest = "latest"; };
    }));
    rejectsMissingArchiveHash = hasFailure "telemetry image pins" (pinOverride (pins // {
      grafana = pins.grafana // { sha256 = ""; };
    }));
    rejectsUnsafeImageName = hasFailure "telemetry image pins" (pinOverride (pins // {
      emqx = pins.emqx // { imageName = "fixture.invalid/emqx; injected"; };
    }));
    requiresRuntimeSecret = lib.all (path: hasFailure "telemetry runtime credentials" (override {
      groundStation.telemetry.secretsFile = lib.mkForce path;
    })) [ null "relative.json" "/nix/store/secret.json" ];
    rejectsUnsafeState = lib.all (path: hasFailure "telemetry stateDirectory" (override {
      groundStation.telemetry.stateDirectory = path;
    })) [ "/" "relative" "/nix/store/telemetry" "/var/lib/../telemetry" "/var/lib/telemetry; injected" ];
    rejectsNativeGrafanaOverlap = hasFailure "telemetry requires native Grafana disabled" (override {
      groundStation.grafana = { enable = true; secretKeyFile = "/run/keys/native-grafana"; };
    });
    reviewedLanRootRequired = hasFailure "telemetry LAN Grafana" (override {
      groundStation.network.lanInterfaces = [ "inspected-ethernet" ];
    });
    realEnabledProfilesHaveNoFailures = failed enabled == [ ] && failed lan == [ ];
    exactlyThreeContainers = builtins.attrNames c == [ "ground-emqx" "ground-grafana" "ground-timescaledb" ];
    dockerBackend = enabled.virtualisation.oci-containers.backend == "docker"
      && enabled.virtualisation.docker.enable;
    archivesInClosure = lib.all (name: c."ground-${name}".imageFile != null) names;
    pinnedArchivePlatformAndTag = lib.all (name: let
      archive = enabled.system.build.groundTelemetryImages.${name};
    in archive.imageDigest == pins.${name}.imageDigest
      && lib.hasInfix "--override-os linux" archive.buildCommand
      && lib.hasInfix "--override-arch amd64" archive.buildCommand
      && c."ground-${name}".image == "${archive.imageName}:${archive.imageTag}"
      && lib.hasPrefix "crt-ground-${name}:sha256-" c."ground-${name}".image) names;
    neverPullOrPublish = lib.all (name: c."ground-${name}".pull == "never"
      && c."ground-${name}".ports == [ ]
      && builtins.elem "--network=host" c."ground-${name}".extraOptions) names;
    generatedCommandsForbidPulls = lib.all (name:
      lib.hasInfix "--pull never" services."docker-ground-${name}".script) names;
    noNetworkOnlineDependency = lib.all (name: let s = services.${name}; in
      !(builtins.elem "network-online.target" s.after)
      && !(builtins.elem "network-online.target" s.wants)
      && !(builtins.elem "network-online.target" s.requires)) (serviceNames ++ [ "docker" ]);
    boundedContainerAttempts = lib.all (name: services."docker-ground-${name}".serviceConfig.TimeoutStartSec == 300) names;
    recoveryRequestsDependenciesAgain = lib.all (name:
      builtins.elem "ground-telemetry-prepare.service" services."docker-ground-${name}".wantedBy) names
      && builtins.elem "ground-telemetry-database.service" services.docker-ground-grafana.wantedBy;
    prepareRecoveryRequestsContainers = lib.all (name:
      requestedBy "ground-telemetry-prepare.service" "docker-ground-${name}.service") names;
    databaseRecoveryRequestsConsumers = lib.all (name:
      requestedBy "ground-telemetry-database.service" name)
        [ "docker-ground-grafana.service" "ground-telemetry-broker.service" ];
    containerRecoveryRequestsProvisioning =
      requestedBy "docker-ground-timescaledb.service" "ground-telemetry-database.service"
      && requestedBy "docker-ground-emqx.service" "ground-telemetry-broker.service";
    noStartupOrderingCycle = !(ordering ? cycle);
    provisioningNeverWaitsForItsConsumers = lib.all (upstream:
      lib.all (downstream: !(requestedBy upstream downstream)
        || !(builtins.elem downstream (unit upstream).after)) unitNames) unitNames;
    recordingIndependentOfBrowser = lib.all (name: let s = services.${name}; in
      lib.all (dependency: !(builtins.elem dependency (s.requires ++ s.bindsTo ++ s.partOf)))
        [ "graphical.target" "display-manager.service" "ground-operator-ui.service" ]) serviceNames;
    containerFailuresKeepRetrying = lib.all (name: let s = services."docker-ground-${name}"; in
      s.serviceConfig.Restart == "on-failure"
      && (s.serviceConfig.RestartSec or 0) == 5
      && (s.unitConfig.StartLimitIntervalSec or null) == 0) names;
    boundedProvisioningAttempts = lib.all (name: let
      timeout = services.${name}.serviceConfig.TimeoutStartSec;
    in builtins.isInt timeout && timeout > 0 && timeout <= 300)
      [ "ground-telemetry-prepare" "ground-telemetry-database" "ground-telemetry-broker" "ground-telemetry-grafana-ready" ];
    actualGeneratedUnitsEvaluate = lib.all (name: let
      text = enabled.systemd.units."${name}.service".text;
    in lib.hasInfix "ExecStart=" text && !(lib.hasInfix "network-online.target" text)) serviceNames;
    completeProfileEvaluates = builtins.isString enabled.system.build.toplevel.drvPath;
    prepareBeforeAllContainers = lib.all (name: let s = services."docker-ground-${name}"; in
      builtins.elem "ground-telemetry-prepare.service" s.requires
      && builtins.elem "ground-telemetry-prepare.service" s.after) names;
    privateRootPreparation = services.ground-telemetry-prepare.serviceConfig.User == "root"
      && services.ground-telemetry-prepare.serviceConfig.UMask == "0077"
      && services.ground-telemetry-prepare.serviceConfig.RuntimeDirectory == "ground-telemetry"
      && services.ground-telemetry-prepare.serviceConfig.RuntimeDirectoryMode == "0700"
      && lib.hasInfix "prepare --secrets-file /run/keys/telemetry.json --output /run/ground-telemetry"
        services.ground-telemetry-prepare.serviceConfig.ExecStart;
    runtimeEnvFilesOnly = c.ground-timescaledb.environmentFiles == [ "/run/ground-telemetry/database.env" ]
      && c.ground-emqx.environmentFiles == [ "/run/ground-telemetry/emqx.env" ]
      && c.ground-grafana.environmentFiles == [ "/run/ground-telemetry/grafana.env" ]
      && !(c.ground-timescaledb.environment ? POSTGRES_PASSWORD)
      && !(c.ground-emqx.environment ? EMQX_NODE__COOKIE)
      && !(c.ground-grafana.environment ? GF_SECURITY_ADMIN_PASSWORD);
    postgresLoopbackAndIdentity = c.ground-timescaledb.environment == {
      POSTGRES_USER = "postgres"; POSTGRES_DB = "telemetry"; PGDATA = "/pgdata";
    } && builtins.elem "listen_addresses=127.0.0.1" c.ground-timescaledb.cmd
      && builtins.elem "/var/lib/ground-station/telemetry/db:/pgdata" c.ground-timescaledb.volumes;
    postgresUsesExplicitHba = c.ground-timescaledb.cmd == [
      "postgres" "-c" "listen_addresses=127.0.0.1" "-c" "port=5432"
      "-c" "hba_file=/etc/ground-telemetry/pg_hba.conf"
    ];
    postgresImmutableReadOnlyHba = let
      mounts = lib.filter (v: lib.hasInfix ":/etc/ground-telemetry/pg_hba.conf" v)
        c.ground-timescaledb.volumes;
    in builtins.length mounts == 1 && lib.all (v:
      lib.hasPrefix "/nix/store/" v
      && lib.hasSuffix "/share/ground-telemetry/database/pg_hba.conf:/etc/ground-telemetry/pg_hba.conf:ro" v) mounts;
    generatedDatabaseCommandUsesHba =
      lib.hasInfix "hba_file=/etc/ground-telemetry/pg_hba.conf" services.docker-ground-timescaledb.script
      && lib.hasInfix "/share/ground-telemetry/database/pg_hba.conf:/etc/ground-telemetry/pg_hba.conf:ro"
        services.docker-ground-timescaledb.script;
    emqxPrivateAdminAndStableNode = c.ground-emqx.environment.EMQX_NODE__NAME == "emqx@127.0.0.1"
      && c.ground-emqx.environment.EMQX_DASHBOARD__LISTENERS__HTTP__BIND == "127.0.0.1:18083"
      && c.ground-emqx.environment.EMQX_LISTENERS__TCP__DEFAULT__BIND == "127.0.0.1:1883";
    emqxDisablesUnconfiguredListeners = lib.all
      (kind: c.ground-emqx.environment."EMQX_LISTENERS__${kind}__DEFAULT__ENABLE" == "false")
      [ "SSL" "WS" "WSS" ];
    apiBootstrapRuntimeFile = c.ground-emqx.environment.EMQX_API_KEY__BOOTSTRAP_FILE == "/opt/emqx/etc/api-keys.bootstrap"
      && builtins.elem "/run/ground-telemetry/api-keys.bootstrap:/opt/emqx/etc/api-keys.bootstrap:ro" c.ground-emqx.volumes
      && c.ground-emqx.user == "1000:1000";
    persistenceDirectories = lib.all (rule: builtins.elem rule enabled.systemd.tmpfiles.rules) [
      "d /var/lib/ground-station/telemetry/db 0700 root root - -"
      "d /var/lib/ground-station/telemetry/emqx/data 0700 1000 1000 - -"
      "d /var/lib/ground-station/telemetry/emqx/log 0700 1000 1000 - -"
      "d /var/lib/ground-station/telemetry/grafana 0700 472 472 - -"
    ];
    mqttLanOnly = lan.virtualisation.oci-containers.containers.ground-emqx.environment.EMQX_LISTENERS__TCP__DEFAULT__BIND == "0.0.0.0:1883"
      && builtins.elem 1883 lan.networking.firewall.interfaces.inspected-ethernet.allowedTCPPorts
      && lan.networking.firewall.allowedTCPPorts == [ ]
      && enabled.networking.firewall.allowedTCPPorts == [ ];
    databaseMigrationPrerequisite = builtins.elem "docker-ground-timescaledb.service" services.ground-telemetry-database.requires
      && lib.hasInfix "database --docker /nix/store/" services.ground-telemetry-database.serviceConfig.ExecStart
      && lib.hasInfix "/bin/docker --assets /nix/store/" services.ground-telemetry-database.serviceConfig.ExecStart;
    brokerWaitsForMigratedDatabase = lib.all (name: builtins.elem name services.ground-telemetry-broker.requires
      && builtins.elem name services.ground-telemetry-broker.after)
        [ "ground-telemetry-database.service" "docker-ground-emqx.service" ]
      && lib.hasInfix "broker --secrets-file /run/keys/telemetry.json --assets /nix/store/"
        services.ground-telemetry-broker.serviceConfig.ExecStart
      && lib.hasInfix "--api-url http://127.0.0.1:18083/api/v5" services.ground-telemetry-broker.serviceConfig.ExecStart;
    grafanaAfterMigration = builtins.elem "ground-telemetry-database.service" services.docker-ground-grafana.requires
      && builtins.elem "ground-telemetry-database.service" services.docker-ground-grafana.after;
    retryableProvisioning = lib.all (name: services.${name}.serviceConfig.Restart == "on-failure"
      && services.${name}.serviceConfig.RestartSec == 5
      && services.${name}.unitConfig.StartLimitIntervalSec == 0)
        [ "ground-telemetry-prepare" "ground-telemetry-database" "ground-telemetry-broker" "ground-telemetry-grafana-ready" ];
    migrationTracksDatabaseRestarts = builtins.elem "docker-ground-timescaledb.service" services.ground-telemetry-database.partOf
      && builtins.elem "docker-ground-timescaledb.service" services.ground-telemetry-database.bindsTo;
    brokerTracksRestarts = builtins.elem "docker-ground-emqx.service" services.ground-telemetry-broker.partOf
      && builtins.elem "ground-telemetry-database.service" services.ground-telemetry-broker.partOf;
    brokerCannotStayActiveAcrossPrerequisiteLoss = lib.all (name:
      builtins.elem name services.ground-telemetry-broker.bindsTo)
        [ "docker-ground-emqx.service" "ground-telemetry-database.service" ];
    probeTracksGrafanaRestarts = builtins.elem "docker-ground-grafana.service" services.ground-telemetry-grafana-ready.partOf
      && builtins.elem "docker-ground-grafana.service" services.ground-telemetry-grafana-ready.bindsTo;
    recurringNonStickyProbe = !services.ground-telemetry-grafana-ready.serviceConfig.RemainAfterExit
      && enabled.systemd.timers.ground-telemetry-grafana-ready.timerConfig.OnUnitInactiveSec == "30s"
      && lib.hasInfix "wait --url http://127.0.0.1:3000/grafana/api/health" services.ground-telemetry-grafana-ready.serviceConfig.ExecStart;
    grafanaPrivateOfflineDefaults = c.ground-grafana.environment.GF_SERVER_HTTP_ADDR == "127.0.0.1"
      && c.ground-grafana.environment.GF_SERVER_ROOT_URL == "http://localhost:8080/grafana/"
      && c.ground-grafana.environment.GF_SECURITY_ALLOW_EMBEDDING == "true"
      && c.ground-grafana.environment.GF_DASHBOARDS_MIN_REFRESH_INTERVAL == "125ms"
      && c.ground-grafana.environment.GF_PLUGINS_PREINSTALL_DISABLED == "true"
      && c.ground-grafana.environment.GF_PLUGINS_PREINSTALL == ""
      && c.ground-grafana.environment.GF_PANELS_DISABLE_SANITIZE_HTML == "false";
    grafanaReviewedRoot = lan.virtualisation.oci-containers.containers.ground-grafana.environment.GF_SERVER_ROOT_URL
      == "http://station.test:8080/grafana/";
    localProvisioningMounts = lib.any (v: lib.hasSuffix "/share/ground-telemetry/grafana/provisioning:/etc/grafana/provisioning:ro" v) c.ground-grafana.volumes
      && lib.any (v: lib.hasSuffix "/share/ground-telemetry/grafana/dashboards:/var/lib/grafana/dashboards:ro" v) c.ground-grafana.volumes;
    publicGrafanaProxy = enabled.services.nginx.virtualHosts.ground-station.locations."/grafana/".proxyPass == "http://127.0.0.1:3000"
      && (builtins.fromJSON public.system.build.groundOperatorUiConfig.text).grafanaUrl == "/grafana/";
    noFullReadinessClaim = enabled.services.nginx.virtualHosts.ground-station.locations."= /readyz".return
      == base.services.nginx.virtualHosts.ground-station.locations."= /readyz".return
      && lib.hasPrefix "503 " enabled.services.nginx.virtualHosts.ground-station.locations."= /readyz".return;
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "Telemetry module contract failed: ${lib.concatStringsSep ", " (builtins.attrNames (lib.filterAttrs (_: v: !v) checks))}";
checks
