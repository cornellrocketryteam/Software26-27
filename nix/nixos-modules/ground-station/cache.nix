{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.cache;
  runtimeKey = cfg.signingKeyFile != null
    && lib.hasPrefix "/" cfg.signingKeyFile
    && !(lib.hasPrefix "/nix/store" cfg.signingKeyFile);
  provisioner = pkgs.callPackage ../../packages/crt/platform-signing/package.nix {
    nix = config.nix.package;
  };
  dependency = pkgs.runCommand "ground-cache-read-dependency-v1" { } ''
    mkdir -p "$out"
    printf 'signed-cache dependency v1\n' > "$out/payload"
  '';
  fixture = pkgs.runCommand "ground-cache-read-artifact-v1" { } ''
    mkdir -p "$out"
    printf 'signed-cache artifact v1\n' > "$out/payload"
    ln -s ${dependency}/payload "$out/dependency"
  '';
in
{
  options.groundStation.cache = {
    provisioning.enable = lib.mkEnableOption "fixed root-only station signing identity provisioning and read fixture";
    enable = lib.mkOption {
      type = lib.types.bool;
      default = cfg.signingKeyFile != null;
      defaultText = lib.literalExpression "config.groundStation.cache.signingKeyFile != null";
      description = "Signed read-only Harmonia cache, proxied at /cache/. No HTTP uploads; optional SSH ingestion is configured separately.";
    };
    signingKeyFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Absolute runtime secret path outside /nix/store. Provision out of band, owned by root with mode 0600 in a root-controlled directory, never as a Nix path literal. The Nix daemon and Harmonia use this key; clients must pin the corresponding public key. Existing store paths are not retroactively signed.";
    };
  };

  config = {
    assertions = [
      { assertion = cfg.provisioning.enable -> cfg.signingKeyFile == "/var/lib/ground-station/cache-signing/cache.sec";
        message = "station cache provisioning requires its fixed runtime signing-key path."; }
      { assertion = cfg.enable -> cfg.signingKeyFile != null; message = "ground-station cache signing key is required; unsigned serving is prohibited."; }
      { assertion = cfg.signingKeyFile != null -> runtimeKey; message = "ground-station cache signing key must be an absolute runtime path outside /nix/store."; }
      {
        assertion = config.services.harmonia.cache.enable -> (
          cfg.enable && runtimeKey
          && config.services.harmonia.cache.signKeyPaths == [ cfg.signingKeyFile ]
        );
        message = "ground-station Harmonia must use the configured runtime cache signing key; no unsigned fallback.";
      }
    ];
    environment.systemPackages = lib.optional cfg.provisioning.enable provisioner;
    environment.etc."ground-cache-read-fixture" = lib.mkIf cfg.provisioning.enable {
      text = "${fixture}\n";
    };
    system.build.groundCacheProvisioner = provisioner;
    # Harmonia signs HTTP narinfos, not the underlying store-path signatures
    # transferred over ssh-ng. Have the root Nix daemon sign newly built paths
    # even when HTTP serving is disabled. Provision the secret before building;
    # signing/transfer acceptance and explicitly signing old paths remain pending.
    nix.settings.secret-key-files = lib.mkIf runtimeKey [ cfg.signingKeyFile ];
    services.harmonia.cache = lib.mkIf cfg.enable {
      enable = true;
      signKeyPaths = lib.optional runtimeKey cfg.signingKeyFile;
      settings = {
        bind = "127.0.0.1:5000";
        workers = 2;
      };
    };
    systemd.services.harmonia = lib.mkIf cfg.enable {
      serviceConfig = {
        CPUQuota = "100%";
        MemoryMax = "512M";
        MemorySwapMax = 0;
      };
    };
  };
}
