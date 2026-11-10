{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.builder;
  allowed = cfg.enable && cfg.validated && !config.groundStation.fieldMode;
  account = "ground-builder";
  daemonStore = "unix:///nix/var/nix/daemon-socket/socket";
  worker = pkgs.callPackage ../../packages/crt/platform-worker/package.nix {
    nix = config.nix.package;
  };
  validWorkerId = cfg.remote.workerId != null
    && builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.remote.workerId != null;
  barePublicKey = key: builtins.match
    "(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) [A-Za-z0-9+/]+={0,3}( [^\r\n]*)?"
    key != null;
  policy = pkgs.writeText "ground-builder-policy.json" (builtins.toJSON {
    protocol = 1;
    enabled = cfg.enable;
    validated = cfg.validated;
    remoteEnabled = cfg.remote.enable;
    fieldMode = config.groundStation.fieldMode;
    minimumFreeBytes = cfg.minimumFreeBytes;
    platforms = [ "x86_64-linux" ]
      ++ lib.optional (allowed && cfg.aarch64.enable && cfg.aarch64.validated) "aarch64-linux";
    workerId = cfg.remote.workerId;
    sessionTimeoutSeconds = cfg.remote.sessionTimeoutSeconds;
  });
  arguments = lib.escapeShellArgs [
    "--policy" (toString policy)
    "--lock" "/run/ground-station-builder/session.lock"
    "--field-marker" "/run/ground-station/field-mode"
    "--store-path" "/nix/store"
    "--binfmt-root" "/proc/sys/fs/binfmt_misc"
    "--daemon-program" "${config.nix.package}/bin/nix-daemon"
  ];
  admission = pkgs.writeShellScript "ground-build-admission" ''
    # Called by the daemon: admit never probes that daemon or takes the remote
    # session lock. Those operations here would deadlock a guarded build.
    exec ${worker}/bin/crt-platform-worker-v1 ${arguments} admit
  '';
  sshWrapper = pkgs.writeShellApplication {
    name = "ground-builder-ssh";
    text = ''
      cd /
      # Compare peer data exactly; never interpret a shell command or arguments.
      case "''${SSH_ORIGINAL_COMMAND-}" in
        'crt-platform-builder-health-v1')
          exec ${pkgs.coreutils}/bin/env -i \
            HOME=/var/empty USER=${account} LOGNAME=${account} \
            PATH=${lib.makeBinPath [ config.nix.package ]} \
            NIX_REMOTE=${daemonStore} NIX_USER_CONF_FILES=/dev/null \
            ${worker}/bin/crt-platform-worker-v1 ${arguments} health
          ;;
        'nix-daemon --stdio')
          # The helper holds the remote lock for this entire daemon-backed
          # stdio child. The system daemon authenticates ground-builder as an
          # untrusted Unix peer; no local store or force-trusted bypass.
          exec ${pkgs.coreutils}/bin/env -i \
            HOME=/var/empty USER=${account} LOGNAME=${account} \
            PATH=${lib.makeBinPath [ config.nix.package ]} \
            NIX_REMOTE=${daemonStore} NIX_USER_CONF_FILES=/dev/null \
            ${worker}/bin/crt-platform-worker-v1 ${arguments} guard
          ;;
        *)
          echo 'ground-builder: command denied' >&2
          exit 126
          ;;
      esac
    '';
  };
in
{
  options.groundStation.builder = {
    enable = lib.mkEnableOption "local station builds";
    validated = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Owner has validated the worker and daemon cgroup containment on this machine.";
    };
    aarch64.enable = lib.mkEnableOption "aarch64-linux QEMU/binfmt worker capability";
    aarch64.validated = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Both vehicle graphs have been validated on the actual emulated worker; not ARM KVM.";
    };
    minimumFreeBytes = lib.mkOption {
      type = lib.types.ints.positive;
      default = 100000000000;
      description = "Free-space reserve checked before every new derivation build; does not evict telemetry or releases.";
    };
    remote = {
      enable = lib.mkEnableOption "untrusted guarded SSH builder admission";
      authorizedKeys = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Explicit bare single-line public keys; administrator and cache ingestion keys are not inherited.";
      };
      workerId = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Stable nonsecret worker identity: 1-128 letters, digits, dots, underscores or hyphens, starting alphanumeric.";
      };
      sessionTimeoutSeconds = lib.mkOption {
        type = lib.types.ints.between 1 86400;
        default = 14400;
        description = "Maximum guarded SSH stdio session lifetime; not a per-derivation timeout.";
      };
    };
  };

  config = {
    assertions = [
      { assertion = cfg.enable -> cfg.validated; message = "ground-station builder validation is required before enabling station builds."; }
      { assertion = cfg.aarch64.enable -> (cfg.enable && cfg.aarch64.validated); message = "ground-station aarch64 validation and an enabled validated builder are required before advertising ARM execution."; }
      { assertion = cfg.remote.enable -> (cfg.enable && cfg.validated); message = "ground-station remote builder requires an enabled validated builder."; }
      { assertion = cfg.remote.enable -> cfg.remote.authorizedKeys != [ ]; message = "ground-station remote builder requires explicit nonempty public keys."; }
      { assertion = cfg.remote.enable -> lib.all barePublicKey cfg.remote.authorizedKeys; message = "ground-station remote builder accepts only bare single-line public keys without caller key options."; }
      { assertion = cfg.remote.enable -> validWorkerId; message = "ground-station remote builder requires an explicit stable worker ID (1-128 safe characters, starting alphanumeric)."; }
      # The daemon signs newly produced input-addressed outputs; SSH clients
      # still require signatures and must pin this key's public half. HTTP
      # serving is independent. Pre-existing outputs may need signing first.
      { assertion = cfg.remote.enable -> config.groundStation.cache.signingKeyFile != null; message = "ground-station remote builder requires a daemon runtime signing key for signature-checked output downloads; HTTP caching may remain disabled."; }
    ];
    boot.binfmt = {
      emulatedSystems = lib.optional (allowed && cfg.aarch64.enable && cfg.aarch64.validated) "aarch64-linux";
      preferStaticEmulators = true;
    };
    nix = {
      distributedBuilds = false;
      settings = {
        experimental-features = [ "nix-command" "flakes" ];
        sandbox = true;
        require-sigs = true;
        max-jobs = lib.mkForce (if allowed then 1 else 0);
        cores = 3;
        pre-build-hook = toString admission;
        # Keep build children within the daemon's resource-control boundary.
        # Validate on hardware before enabling builds; root can bypass policy.
        use-cgroups = false;
      };
    };
    # Limit the system daemon doing the work, not only the SSH launcher.
    systemd.services.nix-daemon.serviceConfig = {
      CPUQuota = "300%";
      MemoryHigh = "5G";
      MemoryMax = "6G";
      MemorySwapMax = 0;
      TasksMax = 512;
      Nice = 10;
      IOWeight = 10;
    };
    users.groups.${account} = lib.mkIf cfg.remote.enable { };
    users.users.${account} = lib.mkIf cfg.remote.enable {
      isSystemUser = true;
      group = account;
      description = "Untrusted guarded ground-station builder";
      hashedPassword = "!";
      home = "/var/empty";
      createHome = false;
      shell = pkgs.bash;
      openssh.authorizedKeys.keys = map
        (key: ''restrict,command="${sshWrapper}/bin/ground-builder-ssh" ${key}'')
        cfg.remote.authorizedKeys;
    };
    # Never add the worker to trusted-users, wheel, sudo or the cache group.
    # Group write is on the pre-created lock inode only: the account cannot
    # unlink/replace that inode because its parent directory is root-controlled.
    systemd.tmpfiles.rules = lib.mkIf cfg.remote.enable [
      "d /run/ground-station-builder 0750 root ${account} - -"
      "f /run/ground-station-builder/session.lock 0660 root ${account} - -"
    ];
    services.openssh.extraConfig = lib.mkIf cfg.remote.enable ''
      Match User ${account}
        ForceCommand ${sshWrapper}/bin/ground-builder-ssh
        AllowAgentForwarding no
        AllowTcpForwarding no
        AllowStreamLocalForwarding no
        PermitTTY no
        PermitTunnel no
        PermitUserRC no
        X11Forwarding no
      Match All
    '';
    system.build = {
      groundWorkerHelper = worker;
      groundWorkerAdmission = admission;
      groundWorkerSsh = sshWrapper;
    };
  };
}
