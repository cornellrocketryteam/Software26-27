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
  ingestionSettings = {
    groundStation.cache = {
      signingKeyFile = "/run/keys/cache-signing-key";
      ingestion = {
        enable = true;
        authorizedKeys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureOnlyNotADeploymentKey archive-test" ];
        trustedDeveloperAccessReviewed = true;
        archiveId = "test-station-archive-v1";
      };
    };
  };
  ingestion = evaluateVM [ ingestionSettings ];
  missingIngestionReview = evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.trustedDeveloperAccessReviewed = lib.mkForce false;
  } ];
  missingIngestionKeys = evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.authorizedKeys = lib.mkForce [ ];
  } ];
  invalidIngestionKey = evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.authorizedKeys = lib.mkForce [ "restrict,command=\"false\" ssh-ed25519 AAAA" ];
  } ];
  # RFC 8032 test-vector public key; fixture only, never a deployment key.
  ingestionTestKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdamAGCsQq31Uv+08lkBzoO4XLz2qYjJa8CGmj3B1Ea";
  ingestionWithKey = key: evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.authorizedKeys = lib.mkForce [ key ];
  } ];
  carriageReturnIngestionKey = ingestionWithKey "${ingestionTestKey} runner\rannotation";
  newlineIngestionKey = ingestionWithKey "${ingestionTestKey} runner\n${ingestionTestKey} injected";
  crlfIngestionKey = ingestionWithKey "${ingestionTestKey} runner\r\n${ingestionTestKey} injected";
  trailingNewlineIngestionKey = ingestionWithKey "${ingestionTestKey} runner\n";
  # Ordinary r/n letters and literal backslash-r/backslash-n are legal comment
  # text; the regex must reject control characters rather than those letters.
  validIngestionComment = "runner ronit normal literal\\r\\n";
  commentedIngestionKey = ingestionWithKey "${ingestionTestKey} ${validIngestionComment}";
  missingArchiveId = evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.archiveId = lib.mkForce null;
  } ];
  invalidArchiveId = evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.archiveId = lib.mkForce "../not-an-archive";
  } ];
  ingestionWithArchiveId = archiveId: evaluateVM [ ingestionSettings {
    groundStation.cache.ingestion.archiveId = lib.mkForce archiveId;
  } ];
  carriageReturnArchiveId = ingestionWithArchiveId "test-station\rarchive";
  newlineArchiveId = ingestionWithArchiveId "test-station\narchive";
  trailingNewlineArchiveId = ingestionWithArchiveId "test-station-archive-v1\n";
  injectedArchiveId = ingestionWithArchiveId "test-station; echo injected";
  newlineInjectedArchiveId = ingestionWithArchiveId "test-station\n$(echo injected)";
  unsignedIngestion = evaluateVM [ ingestionSettings {
    groundStation.cache.enable = lib.mkForce false;
  } ];
  ingestionSsh = ingestion.system.build.groundCacheSsh.text;
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
  remoteSettings = {
    groundStation = {
      fieldMode = false;
      cache = {
        enable = false;
        signingKeyFile = "/run/keys/cache-signing-key";
      };
      builder = {
        enable = true;
        validated = true;
        remote = {
          enable = true;
          authorizedKeys = [ ingestionTestKey ];
          workerId = "test-worker-v1";
        };
      };
    };
  };
  remote = evaluateVM [ remoteSettings ];
  remoteOverride = override: evaluateVM [ remoteSettings override ];
  remoteNoKeys = remoteOverride { groundStation.builder.remote.authorizedKeys = lib.mkForce [ ]; };
  remoteBadKey = key: remoteOverride { groundStation.builder.remote.authorizedKeys = lib.mkForce [ key ]; };
  remoteNoIdentity = remoteOverride { groundStation.builder.remote.workerId = lib.mkForce null; };
  remoteBadIdentity = id: remoteOverride { groundStation.builder.remote.workerId = lib.mkForce id; };
  remoteNoBuilder = remoteOverride { groundStation.builder.enable = lib.mkForce false; };
  remoteUnvalidated = remoteOverride { groundStation.builder.validated = lib.mkForce false; };
  remoteUnsigned = remoteOverride { groundStation.cache.signingKeyFile = lib.mkForce null; };
  remoteField = remoteOverride { groundStation.fieldMode = lib.mkForce true; };
  remoteSsh = remote.system.build.groundWorkerSsh.text;
  remoteTimeout = value: builtins.tryEval (builtins.deepSeq
    (remoteOverride { groundStation.builder.remote.sessionTimeoutSeconds = lib.mkForce value; })
      .groundStation.builder.remote.sessionTimeoutSeconds true);
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
  operatorSettings = {
    groundStation.operatorUi = {
      enable = true;
      package = (import nixpkgs { system = "x86_64-linux"; }).writeTextDir "index.html" "fixture UI";
    };
  };
  operator = evaluateVM [ operatorSettings ];
  operatorOverride = extra: evaluateVM [ operatorSettings extra ];
  operatorLocations = operator.services.nginx.virtualHosts.ground-station.locations;
  operatorConfig = builtins.fromJSON operator.system.build.groundOperatorUiConfig.text;
  operatorGrafana = evaluateVM [ operatorSettings {
    groundStation.grafana = {
      enable = true;
      secretKeyFile = "/run/keys/grafana-secret-key";
    };
    groundStation.operatorUi = {
      fillStationWebSocketUrl = "wss://fill.test/socket";
      tilesDirectory = "/var/lib/ground-station/tiles";
    };
    groundStation.cache.signingKeyFile = "/run/keys/cache-signing-key";
  } ];
  configuredOperator = builtins.fromJSON operatorGrafana.system.build.groundOperatorUiConfig.text;
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
    operatorUiOffByDefault = !(base.groundStation.operatorUi.enable or true)
      && !(base.system.build ? groundOperatorUiConfig);
    operatorUiDefaultsToLockedPackage = base.groundStation.operatorUi.package.pname == "ground-operator-ui"
      && base.groundStation.operatorUi.package.npmBuildScript == "build"
      && base.groundStation.operatorUi.package.npmDepsHash == "sha256-ZrG5fJ2GSmAXYCy3QbzSIy0+w7jB9+zD8Bdh6HVwLg8=";
    operatorUiRunsPublicConfigTests = (base.groundStation.operatorUi.package.doCheck or false)
      && lib.hasInfix "npm test" base.groundStation.operatorUi.package.checkPhase;
    operatorUiSourceExcludesGeneratedTrees = let
      source = base.groundStation.operatorUi.package.src;
      accepts = name: type: source.filter "${toString source.origSrc}/${name}" type;
    in !(accepts "node_modules" "directory") && !(accepts "dist" "directory")
      && !(accepts ".git" "directory") && !(accepts "nested/node_modules" "directory")
      && accepts "package-lock.json" "regular" && accepts "src" "directory" && accepts "public" "directory";
    operatorUiSafeConfig = operatorConfig == {
      schemaVersion = 1;
      fillStationWebSocketUrl = null;
      grafanaUrl = null;
      fieldMode = true;
      map = { tileUrl = "/tiles/{z}/{x}/{y}.png"; tilesConfigured = false; };
    };
    operatorUiRootAndSpa = toString operator.services.nginx.virtualHosts.ground-station.root
      == toString operator.groundStation.operatorUi.package
      && operatorLocations."/".tryFiles == "$uri $uri/ /index.html";
    operatorUiMissingAssets404 = operatorLocations."^~ /assets/".tryFiles == "$uri =404";
    operatorUiMissingTiles404 = operatorLocations."^~ /tiles/".return == "404";
    operatorUiExactUncachedConfig = toString operatorLocations."= /station-config.json".alias
      == toString operator.system.build.groundOperatorUiConfig
      && lib.hasInfix "no-store" operatorLocations."= /station-config.json".extraConfig;
    operatorUiLivenessSeparate = operatorLocations."= /ui-healthz".tryFiles == "/index.html =503"
      && operatorLocations."= /readyz".return == base.services.nginx.virtualHosts.ground-station.locations."= /readyz".return
      && operatorLocations."= /healthz".return == base.services.nginx.virtualHosts.ground-station.locations."= /healthz".return;
    operatorUiConfiguredEndpoints = configuredOperator.fillStationWebSocketUrl == "wss://fill.test/socket"
      && configuredOperator.grafanaUrl == "/grafana/"
      && configuredOperator.map.tilesConfigured
      && operatorGrafana.services.nginx.virtualHosts.ground-station.locations."^~ /tiles/".alias
        == "/var/lib/ground-station/tiles/";
    operatorUiPreservesProxies = operatorGrafana.services.nginx.virtualHosts.ground-station.locations."/grafana/".proxyPass
      == "http://127.0.0.1:3000"
      && operatorGrafana.services.nginx.virtualHosts.ground-station.locations."/cache/".proxyPass
        == "http://127.0.0.1:5000/";
    operatorUiRejectsBadWs = lib.all (url: hasFailure "operator UI WebSocket URL" (operatorOverride {
      groundStation.operatorUi.fillStationWebSocketUrl = url;
    })) [ "http://fill.test" "ws://user:secret@fill.test/" "ws://fill.test\n" "ws:///socket" ];
    operatorUiRejectsWsFragments = lib.all (url: hasFailure "operator UI WebSocket URL" (operatorOverride {
      groundStation.operatorUi.fillStationWebSocketUrl = url;
    })) [ "ws://fill.test/socket#fragment" "ws://fill.test/socket#" ];
    operatorUiRejectsBadGrafana = lib.all (url: hasFailure "operator UI Grafana URL" (operatorOverride {
      groundStation.operatorUi.grafanaUrl = url;
    })) [ "javascript:alert(1)" "https://user:secret@station.test/grafana/" "//station.test/grafana/" ];
    operatorUiRejectsRemoteFieldTiles = lib.all (url: hasFailure "operator UI tile URL" (operatorOverride {
      groundStation.operatorUi.tileUrl = url;
    })) [ "https://tiles.test/{z}/{x}/{y}.png" "//tiles.test/{z}/{x}/{y}.png" "/tiles/../{z}/{x}/{y}.png" "/tiles/{z}/{x}/{y}.png?remote=1" "/tiles/{x}/{y}.png" "/\\tiles/{z}/{x}/{y}.png" ];
    operatorUiNonFieldRemoteTiles = !hasFailure "operator UI tile URL" (operatorOverride {
      groundStation.fieldMode = false;
      groundStation.operatorUi.tileUrl = "https://tiles.test/{z}/{x}/{y}.png";
    });
    operatorUiExplicitRemoteTilesConfigured = (builtins.fromJSON (operatorOverride {
      groundStation.fieldMode = false;
      groundStation.operatorUi = {
        tileUrl = "https://tiles.test/{z}/{x}/{y}.png";
        tilesDirectory = null;
      };
    }).system.build.groundOperatorUiConfig.text).map.tilesConfigured;
    operatorUiRejectsRelativeDirectory = hasFailure "operator UI tilesDirectory" (operatorOverride {
      groundStation.operatorUi.tilesDirectory = "relative/tiles";
    });
    operatorUiRejectsDirectoryInjection = lib.all (path: hasFailure "operator UI tilesDirectory" (operatorOverride {
      groundStation.operatorUi.tilesDirectory = path;
    })) [ "/tiles/../private" "/tiles; autoindex on;" "/tiles\nmalicious" "/tiles$remote_addr" ];
    operatorUiUsesHostFieldMode = !(builtins.fromJSON (operatorOverride {
      groundStation.fieldMode = false;
    }).system.build.groundOperatorUiConfig.text).fieldMode;
    operatorUiProfilesEvaluate = failed operator == [ ] && failed operatorGrafana == [ ];
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
    remoteAdmissionOffByDefault = !(base.groundStation.builder.remote.enable or true)
      && !(base.users.users ? ground-builder);
    remoteOptionsDefault = base.groundStation.builder.remote.authorizedKeys == [ ]
      && base.groundStation.builder.remote.workerId == null
      && base.groundStation.builder.remote.sessionTimeoutSeconds == 14400;
    remoteRequiresValidatedBuilder = hasFailure "remote builder requires an enabled validated builder" remoteNoBuilder
      && hasFailure "remote builder requires an enabled validated builder" remoteUnvalidated;
    remoteRequiresKeys = hasFailure "remote builder requires explicit nonempty public keys" remoteNoKeys;
    remoteRequiresOutputSigning = hasFailure "remote builder requires a daemon runtime signing key" remoteUnsigned;
    remoteSigningIndependentOfHttp = !remote.services.harmonia.cache.enable
      && remote.nix.settings.secret-key-files == [ "/run/keys/cache-signing-key" ]
      && remote.nix.settings.require-sigs;
    remoteRejectsKeyOptionsAndControls = lib.all
      (key: hasFailure "remote builder accepts only bare single-line public keys" (remoteBadKey key))
      [ "restrict ${ingestionTestKey}" "${ingestionTestKey}\n" "${ingestionTestKey} a\rb" "${ingestionTestKey} a\nb" ];
    remoteAllowsKeyComments = failed (remoteBadKey "${ingestionTestKey} runner ronit literal\\r\\n") == [ ];
    remoteRequiresWorkerId = hasFailure "remote builder requires an explicit stable worker ID" remoteNoIdentity
      && lib.all (id: hasFailure "remote builder requires an explicit stable worker ID" (remoteBadIdentity id))
        [ "../worker" "worker\n" "worker; injected" ];
    remoteSessionTimeoutBounded = !(remoteTimeout 0).success && !(remoteTimeout 86401).success
      && (remoteTimeout 1).success && (remoteTimeout 86400).success;
    remoteAccountUntrusted = remote.users.users.ground-builder.isSystemUser
      && remote.users.users.ground-builder.hashedPassword == "!"
      && remote.users.users.ground-builder.extraGroups == [ ]
      && remote.nix.settings.trusted-users == base.nix.settings.trusted-users
      && remote.nix.settings.allowed-users == base.nix.settings.allowed-users;
    remoteLockRootControlled = builtins.elem
      "d /run/ground-station-builder 0750 root ground-builder - -" remote.systemd.tmpfiles.rules
      && builtins.elem "f /run/ground-station-builder/session.lock 0660 root ground-builder - -"
        remote.systemd.tmpfiles.rules;
    remoteForcedKey = lib.all (key: lib.hasPrefix "restrict,command=\"/nix/store/" key
      && lib.hasInfix "/bin/ground-builder-ssh\" ssh-ed25519 " key)
        remote.users.users.ground-builder.openssh.authorizedKeys.keys;
    remoteForcedAccountCommand = lib.hasInfix "Match User ground-builder" remote.services.openssh.extraConfig
      && lib.hasInfix "ForceCommand /nix/store/" remote.services.openssh.extraConfig
      && lib.hasInfix "AllowStreamLocalForwarding no" remote.services.openssh.extraConfig
      && lib.hasInfix "PermitUserRC no" remote.services.openssh.extraConfig;
    remoteExactCommands = lib.hasInfix "case \"\${SSH_ORIGINAL_COMMAND-}\" in" remoteSsh
      && lib.hasInfix "'crt-platform-builder-health-v1')" remoteSsh
      && lib.hasInfix "'nix-daemon --stdio')" remoteSsh
      && lib.hasInfix "command denied" remoteSsh && lib.hasInfix "exit 126" remoteSsh
      && !(lib.hasInfix "eval " remoteSsh);
    remoteFixedHelperArguments = lib.hasInfix "--policy /nix/store/" remoteSsh
      && lib.hasInfix "--lock /run/ground-station-builder/session.lock" remoteSsh
      && lib.hasInfix "--field-marker /run/ground-station/field-mode" remoteSsh
      && lib.hasInfix "--store-path /nix/store" remoteSsh
      && lib.hasInfix "--binfmt-root /proc/sys/fs/binfmt_misc" remoteSsh
      && lib.hasInfix "--daemon-program /nix/store/" remoteSsh
      && lib.hasInfix " health" remoteSsh && lib.hasInfix " guard" remoteSsh;
    remoteCleanDaemonEnvironment = lib.hasInfix "/bin/env -i" remoteSsh
      && lib.hasInfix "NIX_REMOTE=unix:///nix/var/nix/daemon-socket/socket" remoteSsh
      && lib.hasInfix "NIX_USER_CONF_FILES=/dev/null" remoteSsh
      && !(lib.hasInfix "--force-trusted" remoteSsh) && !(lib.hasInfix "--process-ops" remoteSsh);
    sharedBuildAdmission = lib.hasInfix "crt-platform-worker-v1" remote.system.build.groundWorkerAdmission.text
      && lib.hasInfix " admit" remote.system.build.groundWorkerAdmission.text
      && !(lib.hasInfix " guard\n" remote.system.build.groundWorkerAdmission.text)
      && !(lib.hasInfix " health\n" remote.system.build.groundWorkerAdmission.text);
    workerHelperIsolated = lib.hasInfix "/bin/python -I" remote.system.build.groundWorkerHelper.text
      && lib.hasInfix "tools.platform.worker" remote.system.build.groundWorkerHelper.text;
    remotePreservesFieldAndContainment = remoteField.nix.settings.max-jobs == 0
      && remoteField.boot.binfmt.emulatedSystems == [ ]
      && remote.systemd.services.nix-daemon.serviceConfig.MemoryMax == "6G"
      && remote.systemd.services.nix-daemon.serviceConfig.CPUQuota == "300%"
      && !remote.nix.sshServe.enable && !remote.groundStation.cache.ingestion.enable;
    remoteValidProfileEvaluates = failed remote == [ ] && builtins.isString remote.system.build.toplevel.drvPath;
    validatedWorker = worker.nix.settings.max-jobs == 1
      && builtins.elem "aarch64-linux" worker.boot.binfmt.emulatedSystems;
    armBinfmtMatchesRuntimeProbe = worker.boot.binfmt.registrations.aarch64-linux.fixBinary
      && !worker.boot.binfmt.registrations.aarch64-linux.wrapInterpreterInShell
      && worker.boot.binfmt.registrations.aarch64-linux.preserveArgvZero
      && lib.any (lib.hasPrefix "L+ /run/binfmt/aarch64-linux ") worker.systemd.tmpfiles.rules;
    fieldInhibitsWorker = field.nix.settings.max-jobs == 0
      && field.boot.binfmt.emulatedSystems == [ ];
    validationGate = hasFailure "builder validation" unvalidated
      && hasFailure "aarch64 validation" unvalidated;
    daemonMemoryBound = worker.systemd.services.nix-daemon.serviceConfig.MemoryMax == "6G";
    daemonCpuBound = worker.systemd.services.nix-daemon.serviceConfig.CPUQuota == "300%";
    buildAdmissionHook = builtins.isString base.nix.settings.pre-build-hook;
    cacheOffWithoutKey = !base.services.harmonia.cache.enable;
    cacheIngestionOffByDefault = !(base.groundStation.cache.ingestion.enable or true)
      && !(base.users.users ? ground-cache)
      && base.groundStation.cache.ingestion.authorizedKeys == [ ]
      && !base.groundStation.cache.ingestion.trustedDeveloperAccessReviewed
      && base.groundStation.cache.ingestion.archiveId == null
      && !(builtins.elem "ground-cache" base.nix.settings.trusted-users);
    cacheIngestionRequiresReview = hasFailure "administrative developer access" missingIngestionReview;
    cacheIngestionRequiresKeys = hasFailure "explicit nonempty public keys" missingIngestionKeys;
    cacheIngestionRejectsKeyOptions = hasFailure "bare single-line public keys" invalidIngestionKey;
    cacheIngestionRejectsKeyCR = hasFailure "bare single-line public keys" carriageReturnIngestionKey;
    cacheIngestionRejectsKeyLF = hasFailure "bare single-line public keys" newlineIngestionKey;
    cacheIngestionRejectsKeyCRLF = hasFailure "bare single-line public keys" crlfIngestionKey;
    cacheIngestionRejectsKeyTrailingLF = hasFailure "bare single-line public keys" trailingNewlineIngestionKey;
    cacheIngestionAllowsCommentLettersAndLiteralEscapes = failed commentedIngestionKey == [ ]
      && lib.any (lib.hasSuffix "${ingestionTestKey} ${validIngestionComment}")
        commentedIngestionKey.users.users.ground-cache.openssh.authorizedKeys.keys;
    cacheIngestionRequiresArchiveId = hasFailure "explicit stable archive ID" missingArchiveId
      && hasFailure "explicit stable archive ID" invalidArchiveId;
    cacheIngestionRejectsArchiveCR = hasFailure "explicit stable archive ID" carriageReturnArchiveId;
    cacheIngestionRejectsArchiveLF = hasFailure "explicit stable archive ID" newlineArchiveId;
    cacheIngestionRejectsArchiveTrailingLF = hasFailure "explicit stable archive ID" trailingNewlineArchiveId;
    cacheIngestionRejectsArchiveInjection = hasFailure "explicit stable archive ID" injectedArchiveId
      && hasFailure "explicit stable archive ID" newlineInjectedArchiveId;
    cacheIngestionRequiresSignedCache = hasFailure "enabled signed cache" unsignedIngestion;
    cacheIngestionFixedState = ingestion.groundStation.cache.ingestion.stateDir == "/var/lib/ground-cache-archive";
    cacheIngestionTrustedAccount = builtins.elem "ground-cache" ingestion.nix.settings.trusted-users
      && ingestion.nix.settings.allowed-users == base.nix.settings.allowed-users;
    cacheIngestionAccountLocked = ingestion.users.users.ground-cache.isSystemUser
      && ingestion.users.users.ground-cache.hashedPassword == "!"
      && ingestion.users.users.ground-cache.extraGroups == [ ];
    cacheIngestionArchiveOwnership = builtins.elem
      "d /var/lib/ground-cache-archive 0700 ground-cache ground-cache - -"
      ingestion.systemd.tmpfiles.rules;
    cacheIngestionForcedKeys = lib.all
      (key: lib.hasPrefix "restrict,command=\"/nix/store/" key
        && lib.hasInfix "/bin/ground-cache-ssh\" ssh-ed25519 " key)
      ingestion.users.users.ground-cache.openssh.authorizedKeys.keys;
    cacheIngestionForcedAccountCommand = lib.hasInfix "Match User ground-cache" ingestion.services.openssh.extraConfig
      && lib.hasInfix "ForceCommand /nix/store/" ingestion.services.openssh.extraConfig
      && lib.hasInfix "AllowTcpForwarding no" ingestion.services.openssh.extraConfig
      && lib.hasInfix "PermitTTY no" ingestion.services.openssh.extraConfig;
    cacheIngestionExactCommands = lib.hasInfix "case \"\${SSH_ORIGINAL_COMMAND-}\" in" ingestionSsh
      && lib.hasInfix "'nix-daemon --stdio')" ingestionSsh
      && lib.hasInfix "'crt-platform-cache-receive-v1')" ingestionSsh
      && lib.hasInfix "command denied" ingestionSsh
      && lib.hasInfix "exit 126" ingestionSsh
      && !(lib.hasInfix "eval " ingestionSsh);
    cacheIngestionPinsDaemon = lib.hasInfix "nix-daemon --stdio --store unix:///nix/var/nix/daemon-socket/socket" ingestionSsh
      && lib.hasInfix "NIX_REMOTE=unix:///nix/var/nix/daemon-socket/socket" ingestionSsh
      && lib.hasInfix "NIX_USER_CONF_FILES=/dev/null" ingestionSsh
      && lib.hasInfix "/bin/env -i" ingestionSsh;
    cacheIngestionPinsReceiverIdentity = lib.hasInfix "--state-dir /var/lib/ground-cache-archive" ingestionSsh
      && lib.hasInfix "--archive-id test-station-archive-v1" ingestionSsh;
    cacheIngestionPreservesFieldPolicy = ingestion.groundStation.fieldMode
      && ingestion.nix.settings.max-jobs == 0
      && ingestion.systemd.services.nix-daemon.serviceConfig.MemoryMax == "6G"
      && !ingestion.nix.sshServe.enable
      && ingestion.services.openssh.settings.PermitRootLogin == "no"
      && !ingestion.services.openssh.settings.PasswordAuthentication
      && (builtins.head ingestion.services.openssh.listenAddresses).addr == "127.0.0.1";
    cacheIngestionDoesNotExposeSecret = !(lib.hasInfix "/run/keys/cache-signing-key"
      (lib.concatStringsSep "\n" ingestion.users.users.ground-cache.openssh.authorizedKeys.keys));
    cacheIngestionEnabledAssertionsPass = failed ingestion == [ ];
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
