{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.commandListener;
  haveDevice = cfg.device != null || cfg.serialNumber != null;
  args = [ "--uri" cfg.uri ]
    ++ lib.optionals (cfg.device != null) [ "--device" cfg.device ]
    ++ lib.optionals (cfg.serialNumber != null) [ "--serial-number" cfg.serialNumber ]
    ++ lib.concatMap (command: [ "--allow-command" command ]) cfg.authorizedCommands;
in
{
  options.groundStation.commandListener = {
    enable = lib.mkEnableOption "physical-button listener (monitoring only unless commands are explicitly authorized)";
    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "crt" "ground-command-listener" ] null pkgs;
      description = "Packaged ground-command-listener executable, provided by the repository package overlay.";
    };
    uri = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Explicit ws:// or wss:// fill-station endpoint; no guessed LAN address.";
    };
    device = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Inspected /dev/serial/by-id/ path; never a guessed ttyUSB/ttyACM index.";
    };
    serialNumber = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Inspected LaunchButton serial number; listener also validates VID/PID/product.";
    };
    authorizedCommands = lib.mkOption {
      type = lib.types.listOf (lib.types.enum [ "launch" "fsw_key_arm" "fsw_wipe_fram_reboot" ]);
      default = [ ];
      description = "Explicit --allow-command allowlist. Empty monitors only. Firmware PIN3 disarm/<X>/FRAM-wipe mismatch requires owner review.";
    };
    commandPolicyReviewed = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Owner reviewed physical button mappings and command authorization, including <X> FRAM wipe; not implied by connection readiness.";
    };
    sessionProtocolValidated = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Nonce/sequence firmware protocol has been implemented and tested. Legacy Pico messages remain monitoring-only.";
    };
  };

  config = {
    assertions = lib.optionals cfg.enable [
      { assertion = cfg.uri != null && (lib.hasPrefix "ws://" cfg.uri || lib.hasPrefix "wss://" cfg.uri); message = "ground-station listener requires an explicit WebSocket endpoint."; }
      { assertion = haveDevice; message = "ground-station listener requires an inspected stable device path or serial number."; }
      { assertion = cfg.device == null || lib.hasPrefix "/dev/serial/by-id/" cfg.device; message = "ground-station listener device must be a stable /dev/serial/by-id/ path."; }
      { assertion = cfg.package != null; message = "ground-station listener requires the repository ground-command-listener package overlay."; }
      { assertion = cfg.authorizedCommands == [ ] || cfg.commandPolicyReviewed; message = "ground-station listener command policy requires owner review before authorizing any physical command."; }
      { assertion = cfg.authorizedCommands == [ ] || cfg.sessionProtocolValidated; message = "ground-station listener requires validated session-protocol firmware; legacy queued messages cannot authorize commanding."; }
    ];
    users.groups.ground-command = lib.mkIf cfg.enable { };
    users.users.ground-command = lib.mkIf cfg.enable {
      isSystemUser = true;
      group = "ground-command";
      extraGroups = [ "dialout" ];
    };
    systemd.services.ground-command-listener = lib.mkIf (cfg.enable && cfg.package != null && cfg.uri != null && haveDevice) {
      description = "Physical-button listener; explicit command allowlist, empty means monitor only";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs ([ (lib.getExe' cfg.package "ground-command-listener") ] ++ args);
        User = "ground-command";
        Group = "ground-command";
        Restart = "on-failure";
        RestartSec = 3;
        TimeoutStopSec = 10;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        MemoryMax = "256M";
        CPUQuota = "50%";
      };
    };
  };
}
