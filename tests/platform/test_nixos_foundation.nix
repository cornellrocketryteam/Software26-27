# Lightweight module-contract evaluation; no VM boot, downloads or builds.
# nix-instantiate --eval --strict --json tests/platform/test_nixos_foundation.nix \
#   --arg nixpkgs /path/to/locked/nixpkgs
{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      { nixpkgs.hostPlatform = "x86_64-linux"; }
      ../../nix/nixos-configurations/ground-station
    ] ++ extra;
  }).config;
  evaluateVM = extra: evaluate ([ ../../nix/nixos-configurations/ground-station/vm.nix ] ++ extra);
  base = evaluate [ ];
  vm = evaluate [ ../../nix/nixos-configurations/ground-station/vm.nix ];
  signed = evaluateVM [ {
    groundStation.cache.signingKeyFile = "/run/keys/cache-signing-key";
  } ];
  signingOnly = evaluateVM [ {
    groundStation.cache = {
      enable = false;
      signingKeyFile = "/run/keys/cache-signing-key";
    };
  } ];
  unsigned = evaluate [ { groundStation.cache.enable = true; } ];
  storeKey = evaluate [ {
    groundStation.cache.signingKeyFile = "/nix/store/not-a-runtime-secret";
  } ];
  worker = evaluateVM [ {
    groundStation = {
      fieldMode = false;
      builder = {
        enable = true;
        validated = true;
        aarch64 = { enable = true; validated = true; };
      };
    };
  } ];
  field = evaluate [ {
    groundStation.builder = {
      enable = true;
      validated = true;
      aarch64 = { enable = true; validated = true; };
    };
  } ];
  unvalidated = evaluate [ {
    groundStation.builder.enable = true;
    groundStation.builder.aarch64.enable = true;
  } ];
  lan = evaluate [ { groundStation.network.lanInterfaces = [ "test-lan" ]; } ];
  grafana = evaluateVM [ {
    groundStation.grafana = {
      enable = true;
      secretKeyFile = "/run/keys/grafana-secret-key";
      rootUrl = "http://station.test:8080/grafana/";
    };
  } ];
  missingGrafanaKey = evaluate [ { groundStation.grafana.enable = true; } ];
  hardwareClaimOnly = evaluate [ { groundStation.hardwareConfigured = true; } ];
  listenerModule = {
    groundStation.commandListener = {
      enable = true;
      # Pure evaluation uses the real package, without building its Python env.
      package = (import nixpkgs { system = "x86_64-linux"; }).callPackage
        ../../nix/packages/crt/ground-command-listener/package.nix { };
      uri = "ws://localhost:8081";
      # Synthetic fixture identity, never deployment hardware evidence.
      device = "/dev/serial/by-id/test-fixture-only";
    };
  };
  monitor = evaluateVM [ listenerModule ];
  unauthorized = evaluate [ listenerModule {
    groundStation.commandListener.authorizedCommands = [ "launch" ];
  } ];
  reviewed = evaluateVM [ listenerModule {
    groundStation.commandListener = {
      authorizedCommands = [ "launch" ];
      commandPolicyReviewed = true;
      sessionProtocolValidated = true;
    };
  } ];
  legacyReviewed = evaluateVM [ listenerModule {
    groundStation.commandListener = {
      authorizedCommands = [ "launch" ];
      commandPolicyReviewed = true;
    };
  } ];
  failed = c: map (a: a.message) (lib.filter (a: !a.assertion) c.assertions);
  hasFailure = needle: c: lib.any (lib.hasInfix needle) (failed c);
  checks = {
    x86Host = base.nixpkgs.hostPlatform.system == "x86_64-linux";
    physicalInstallGated = hasFailure "hardware installation prerequisite" base;
    hardwareFlagAloneInsufficient = hasFailure "hardware installation prerequisite" hardwareClaimOnly;
    noInventedRootDisk = !(base.fileSystems ? "/");
    vmHasNoPhysicalGate = !(hasFailure "hardware installation prerequisite" vm);
    vmEvaluates = builtins.isString vm.system.build.toplevel.drvPath;
    fieldModeByDefault = base.groundStation.fieldMode;
    heavyBuildsDisabled = base.nix.settings.max-jobs == 0;
    noUnvalidatedArm = base.boot.binfmt.emulatedSystems == [ ];
    noRemoteWorker = !base.nix.sshServe.enable;
    validatedWorker = worker.nix.settings.max-jobs == 1
      && builtins.elem "aarch64-linux" worker.boot.binfmt.emulatedSystems;
    fieldInhibitsWorker = field.nix.settings.max-jobs == 0
      && field.boot.binfmt.emulatedSystems == [ ];
    validationGate = hasFailure "builder validation" unvalidated
      && hasFailure "aarch64 validation" unvalidated;
    daemonMemoryBound = worker.systemd.services.nix-daemon.serviceConfig.MemoryMax == "6G";
    daemonCpuBound = worker.systemd.services.nix-daemon.serviceConfig.CPUQuota == "300%";
    buildAdmissionHook = builtins.isString base.nix.settings.pre-build-hook;
    cacheOffWithoutKey = !base.services.harmonia.cache.enable;
    cacheSignedWithRuntimeKey = signed.services.harmonia.cache.enable
      && signed.services.harmonia.cache.signKeyPaths == [ "/run/keys/cache-signing-key" ];
    daemonSignsWithSameRuntimeKey = (signed.nix.settings.secret-key-files or [ ])
      == signed.services.harmonia.cache.signKeyPaths;
    daemonSigningIndependentOfHttp = !signingOnly.services.harmonia.cache.enable
      && (signingOnly.nix.settings.secret-key-files or [ ]) == [ "/run/keys/cache-signing-key" ];
    noDaemonKeyWithoutSecret = (base.nix.settings.secret-key-files or [ ]) == [ ];
    signedProfileRequiresSignatures = signed.nix.settings.require-sigs;
    unsignedRejected = hasFailure "cache signing key" unsigned;
    storeSecretRejected = hasFailure "outside /nix/store" storeKey;
    cacheLoopbackOnly = signed.services.harmonia.cache.settings.bind == "127.0.0.1:5000";
    signaturesRequired = base.nix.settings.require-sigs;
    gcNotAutomatic = !base.nix.gc.automatic && !base.services.harmonia.gc.automatic;
    passwordAuthOff = !base.services.openssh.settings.PasswordAuthentication
      && !base.services.openssh.settings.KbdInteractiveAuthentication;
    rootSshOff = base.services.openssh.settings.PermitRootLogin == "no";
    adminReusesPublicKeys = base.users.users.ground-admin.openssh.authorizedKeys.keyFiles
      == [ ../../nix/mixos-modules/fill-station-base/authorized_keys ];
    operatorUnprivileged = !(builtins.elem "wheel" base.users.users.operator.extraGroups);
    noGlobalFirewallOpenings = base.networking.firewall.allowedTCPPorts == [ ];
    lanPortsScoped = lan.networking.firewall.interfaces.test-lan.allowedTCPPorts == [ 22 8080 ];
    sshLoopbackByDefault = (builtins.head base.services.openssh.listenAddresses).addr == "127.0.0.1";
    webLoopbackByDefault = (builtins.head base.services.nginx.virtualHosts.ground-station.listen).addr == "127.0.0.1";
    notOperational = base.services.nginx.virtualHosts.ground-station.locations."= /readyz".return
      == "503 'Ground station not provisioned; telemetry and commanding are unavailable.\\n'";
    grafanaOffWithoutProvisioning = !base.services.grafana.enable;
    grafanaKeyRequired = hasFailure "Grafana runtime secret" missingGrafanaKey;
    grafanaLocal = grafana.services.grafana.settings.server.http_addr == "127.0.0.1";
    grafanaNoDefaultAdmin = grafana.services.grafana.settings.security.disable_initial_admin_creation;
    grafanaHealthProbe = grafana.systemd.services.ground-grafana-ready.requires == [ "grafana.service" ];
    grafanaProxyUrl = grafana.services.grafana.settings.server.root_url == "http://station.test:8080/grafana/";
    enabledProfilesHaveNoFailedAssertions = lib.all (c: failed c == [ ]) [ signed worker grafana monitor reviewed ];
    listenerDisabled = !base.groundStation.commandListener.enable
      && !(base.systemd.services ? ground-command-listener);
    monitoringHasNoCommands = !(lib.hasInfix "--allow-command" monitor.systemd.services.ground-command-listener.serviceConfig.ExecStart);
    commandPolicyGate = hasFailure "command policy requires owner review" unauthorized;
    sessionProtocolGate = hasFailure "validated session-protocol firmware" legacyReviewed;
    explicitAllowlist = lib.hasInfix "--allow-command launch" reviewed.systemd.services.ground-command-listener.serviceConfig.ExecStart
      && !(lib.hasInfix "fsw_wipe_fram_reboot" reviewed.systemd.services.ground-command-listener.serviceConfig.ExecStart);
    listenerNotRoot = monitor.systemd.services.ground-command-listener.serviceConfig.User == "ground-command";
    noUnpinnedContainers = base.virtualisation.oci-containers.containers == { };
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "NixOS foundation contract failed: ${lib.concatStringsSep ", " (builtins.attrNames (lib.filterAttrs (_: v: !v) checks))}";
checks
