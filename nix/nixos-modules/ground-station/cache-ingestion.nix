{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.cache.ingestion;
  account = "ground-cache";
  daemonStore = "unix:///nix/var/nix/daemon-socket/socket";
  validArchiveId = cfg.archiveId != null
    && builtins.match "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" cfg.archiveId != null;
  barePublicKey = key: builtins.match
    "(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) [A-Za-z0-9+/]+={0,3}( [^\r\n]*)?"
    key != null;
  receiver = pkgs.callPackage ../../packages/crt/platform-cache-receiver/package.nix {
    nix = config.nix.package;
  };
  sshWrapper = pkgs.writeShellApplication {
    name = "ground-cache-ssh";
    text = ''
      # SSH_ORIGINAL_COMMAND is compared as data, never split, interpolated as
      # shell code or evaluated. No command arguments supplied by the peer pass.
      cd /
      case "''${SSH_ORIGINAL_COMMAND-}" in
        'nix-daemon --stdio')
          # Locked nixpkgs' nix-ssh-serve.nix uses this ssh-ng command. Pin a
          # daemon-backed store: Nix delegates store/build operations to the
          # system daemon and its cgroup instead of a local SSH-session store.
          # Source: Nix 2.34.9 src/nix/unix/daemon.cc runDaemon(). Do not use
          # --store local, --force-trusted or --process-ops here.
          exec ${pkgs.coreutils}/bin/env -i \
            HOME=${lib.escapeShellArg cfg.stateDir} USER=${account} LOGNAME=${account} \
            PATH=${lib.makeBinPath [ config.nix.package ]} \
            NIX_REMOTE=${daemonStore} NIX_USER_CONF_FILES=/dev/null \
            ${config.nix.package}/bin/nix-daemon --stdio --store ${daemonStore}
          ;;
        'crt-platform-cache-receive-v1')
          exec ${pkgs.coreutils}/bin/env -i \
            HOME=${lib.escapeShellArg cfg.stateDir} USER=${account} LOGNAME=${account} \
            PATH=${lib.makeBinPath [ config.nix.package ]} \
            NIX_REMOTE=${daemonStore} NIX_USER_CONF_FILES=/dev/null \
            ${receiver}/bin/crt-platform-cache-receive-v1 \
              --state-dir ${lib.escapeShellArg cfg.stateDir} \
              --archive-id ${lib.escapeShellArg (if cfg.archiveId == null then "" else cfg.archiveId)}
          ;;
        *)
          echo 'ground-cache: command denied' >&2
          exit 126
          ;;
      esac
    '';
  };
in
{
  options.groundStation.cache.ingestion = {
    enable = lib.mkEnableOption "trusted SSH cache ingestion and durable release receipts";
    authorizedKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Explicit bare public keys for reviewed developers. No key options, newlines or inherited administrator keys.";
    };
    trustedDeveloperAccessReviewed = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Owner has reviewed that Nix trusted-user access is effectively administrative access. The forced command is an interface restriction, not a privilege boundary against trusted developers.";
    };
    archiveId = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Explicit stable nonsecret archive identity (1-128 letters, digits, dots, underscores or hyphens; starts with a letter or digit). Must match the pinned client configuration and durable archive.";
    };
    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/ground-cache-archive";
      readOnly = true;
      description = "Fixed account-owned archive, manifests, receipts and registered GC roots. No signing secrets belong here.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = cfg.trustedDeveloperAccessReviewed;
        message = "ground-station cache ingestion requires review of effectively administrative developer access."; }
      { assertion = cfg.authorizedKeys != [ ];
        message = "ground-station cache ingestion requires explicit nonempty public keys."; }
      { assertion = lib.all barePublicKey cfg.authorizedKeys;
        message = "ground-station cache ingestion accepts only bare single-line public keys without caller key options."; }
      { assertion = validArchiveId;
        message = "ground-station cache ingestion requires an explicit stable archive ID (1-128 safe characters, starting alphanumeric)."; }
      { assertion = config.groundStation.cache.enable && config.groundStation.cache.signingKeyFile != null;
        message = "ground-station cache ingestion requires an enabled signed cache and its runtime signing key."; }
    ];

    users.groups.${account} = { };
    users.users.${account} = {
      isSystemUser = true;
      group = account;
      description = "Reviewed trusted developer cache ingestion (administrative Nix access)";
      hashedPassword = "!";
      home = cfg.stateDir;
      createHome = false;
      shell = pkgs.bash;
      openssh.authorizedKeys.keys = map
        (key: ''restrict,command="${sshWrapper}/bin/ground-cache-ssh" ${key}'')
        cfg.authorizedKeys;
    };
    # Trusted users can always connect; leave allowed-users (default [ "*" ])
    # unchanged so enabling ingestion does not revoke other local access.
    nix.settings.trusted-users = [ account ];
    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0700 ${account} ${account} - -"
    ];
    # Account-level restrictions also cover accidentally added keys without
    # per-key restrictions. The existing root/password/LAN policy is unchanged.
    services.openssh.extraConfig = ''
      Match User ${account}
        ForceCommand ${sshWrapper}/bin/ground-cache-ssh
        AllowAgentForwarding no
        AllowTcpForwarding no
        AllowStreamLocalForwarding no
        PermitTTY no
        PermitTunnel no
        PermitUserRC no
        X11Forwarding no
      Match All
    '';
    # Inspection/build targets for acceptance tests; these do not install a
    # second daemon or imply that physical deployment has been validated.
    system.build.groundCacheSsh = sshWrapper;
    system.build.groundCacheReceiver = receiver;
  };
}
