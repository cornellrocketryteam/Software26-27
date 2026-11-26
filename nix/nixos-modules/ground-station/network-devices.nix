{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.networkDevices;
  package = pkgs.callPackage ../../packages/crt/ground-network-devices/package.nix { };
  wanConfig = pkgs.writeText "ground-wan-probes.json" (builtins.toJSON {
    inherit (cfg.wan) targets intervalSeconds;
    timeoutSeconds = cfg.wan.timeoutMilliseconds / 1000.0;
  });
  runtimeFile = path: path != null && lib.hasPrefix "/" path
    && !(lib.hasPrefix "/nix/store" path)
    && builtins.match "/[A-Za-z0-9_./-]+" path != null
    && lib.all (part: part != "." && part != "..") (lib.splitString "/" path);
in
{
  options.groundStation.networkDevices = {
    enable = lib.mkEnableOption "local network-device API (no automatic power actions)";
    inventoryFile = lib.mkOption {
      type = lib.types.path;
      default = ../../../ground-station/network-devices/inventory.json;
      description = "Public device inventory. Default Omada adapters and unaddressed plugs remain inactive.";
    };
    credentialsFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Private runtime JSON with devices credentials and optional operatorToken. Null disables API power writes.";
    };
    port = lib.mkOption { type = lib.types.port; default = 8767; };
    allowedNetworks = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "192.168.1.0/24" ];
      description = "Device networks permitted by the service's systemd IP access policy, in addition to loopback.";
    };
    wan = {
      enable = lib.mkEnableOption "optional background external TCP reachability probes";
      intervalSeconds = lib.mkOption { type = lib.types.ints.between 5 300; default = 10; };
      timeoutMilliseconds = lib.mkOption { type = lib.types.ints.between 100 3000; default = 1000; };
      targets = lib.mkOption {
        default = [ ];
        description = "One to three explicit public IPv4 TCP targets; no default external traffic. Runtime validates public unicast addresses.";
        type = lib.types.listOf (lib.types.submodule {
          options = {
            label = lib.mkOption { type = lib.types.str; };
            address = lib.mkOption { type = lib.types.strMatching "[0-9]{1,3}(\\.[0-9]{1,3}){3}"; };
            port = lib.mkOption { type = lib.types.ints.between 1 65535; default = 443; };
          };
        });
      };
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [ {
      assertion = cfg.credentialsFile == null || runtimeFile cfg.credentialsFile;
      message = "Network device credentials must be an absolute runtime path outside the Nix store.";
    } {
      assertion = !cfg.wan.enable || (builtins.length cfg.wan.targets >= 1 && builtins.length cfg.wan.targets <= 3);
      message = "WAN probes require one to three explicit targets.";
    } ];
    systemd.services.ground-network-devices = {
      description = "Ground station local network-device API";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs ([ "${package}/bin/crt-network-devices"
          "--inventory" "${cfg.inventoryFile}" "--port" (toString cfg.port) ]
          ++ lib.optionals (cfg.credentialsFile != null) [ "--credentials-file" "%d/devices" ]
          ++ lib.optionals cfg.wan.enable [ "--wan-config" wanConfig ]);
        LoadCredential = lib.optional (cfg.credentialsFile != null) "devices:${cfg.credentialsFile}";
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
        IPAddressDeny = "any";
        IPAddressAllow = [ "localhost" ] ++ cfg.allowedNetworks
          ++ lib.optionals cfg.wan.enable (map (target: "${target.address}/32") cfg.wan.targets);
        MemoryMax = "128M";
        TasksMax = 32;
        CPUQuota = "20%";
        Restart = "on-failure";
        RestartSec = 3;
        TimeoutStopSec = if cfg.wan.enable then 15 else 5;
        UMask = "0077";
      };
    };
    services.nginx.virtualHosts.ground-station.locations."/network-api/" = {
      proxyPass = "http://127.0.0.1:${toString cfg.port}/";
      extraConfig = "client_max_body_size 4k;";
    };
  };
}
