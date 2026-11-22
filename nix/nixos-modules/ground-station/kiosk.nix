{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.kiosk;
  cameras = config.groundStation.cameras.enable or false;
  layoutConfig = pkgs.writeText "ground-display.json" (builtins.toJSON {
    inherit cameras;
    port = config.groundStation.network.webPort;
    browser = "${cfg.browserPackage}/bin/chromium";
    swaymsg = "${config.programs.sway.package}/bin/swaymsg";
    inherit (cfg) telemetryOutput commandingOutput;
    overviewPath = cfg.path;
  });
  display = pkgs.linkFarm "ground-station-display" [
    { name = "index.html"; path = ../../../ground-station/display/index.html; }
    { name = "tabs.js"; path = ../../../ground-station/display/tabs.js; }
  ];
  launcher = pkgs.writeShellScript "ground-station-kiosk" ''
    # Wait briefly for bundled assets; never wait for WAN, cameras or the board.
    for attempt in $(${pkgs.coreutils}/bin/seq 1 30); do
      ${pkgs.curl}/bin/curl --fail --silent --max-time 1 \
        http://127.0.0.1:${toString config.groundStation.network.webPort}/ui-healthz >/dev/null && break
      ${pkgs.coreutils}/bin/sleep 1
    done
    child=
    trap 'test -z "$child" || kill "$child" 2>/dev/null || true; exit 0' TERM INT
    while true; do
      ${pkgs.python3}/bin/python3 ${../../../ground-station/display/layout.py} ${layoutConfig} &
      child=$!
      wait "$child" || true
      child=
      ${pkgs.coreutils}/bin/sleep 3
    done
  '';
  swayConfig = pkgs.writeText "ground-station-sway.conf" ''
    include /etc/sway/config.d/*
    xwayland disable
    output * bg #111820 solid_color
    seat * hide_cursor 5000
    focus_follows_mouse no
    default_border none
    exec ${launcher}
  '';
  session = "${pkgs.coreutils}/bin/env WLR_LIBINPUT_NO_DEVICES=1 ${config.programs.sway.package}/bin/sway --config ${swayConfig}";
in
{
  options.groundStation.kiosk = {
    enable = lib.mkEnableOption "automatic local operator dashboard on the attached display";
    path = lib.mkOption {
      type = lib.types.strMatching "/[A-Za-z0-9_./-]*";
      default = "/station/";
      description = "Local dashboard path opened at boot. Never an external URL.";
    };
    browserPackage = lib.mkOption {
      type = lib.types.package;
      default = pkgs.chromium;
      description = "Packaged Chromium browser; no browser download occurs at boot.";
    };
    telemetryOutput = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[A-Za-z0-9_.-]+");
      default = null;
      description = "Optional inspected Sway output name for telemetry; null selects the first connected output.";
    };
    commandingOutput = lib.mkOption {
      type = lib.types.nullOr (lib.types.strMatching "[A-Za-z0-9_.-]+");
      default = null;
      description = "Optional inspected output name for commanding; null selects another connected output.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [ {
      assertion = config.groundStation.operatorUi.enable
        && !(lib.hasInfix "//" cfg.path)
        && lib.all (p: p != "." && p != "..") (lib.splitString "/" cfg.path);
      message = "ground-station kiosk requires the bundled operator UI and a local path without traversal.";
    } ];
    hardware.graphics.enable = true;
    programs.sway = {
      enable = true;
      wrapperFeatures.gtk = false;
      extraPackages = [ ];
    };
    services.greetd = {
      enable = true;
      restart = true;
      settings = {
        initial_session = { command = session; user = "operator"; };
        default_session = { command = session; user = "operator"; };
      };
    };
    systemd.defaultUnit = "graphical.target";
    services.nginx.virtualHosts.ground-station.locations = {
      "= /station".return = "302 /station/";
      "^~ /station/" = { alias = "${display}/"; index = "index.html"; };
    };
    system.build.groundStationDisplay = display;
    system.build.groundStationSwayConfig = swayConfig;
    systemd.services.greetd = {
      wants = [ "nginx.service" ];
      after = [ "nginx.service" ];
      serviceConfig = { Restart = lib.mkForce "always"; RestartSec = 3; };
      unitConfig.StartLimitIntervalSec = 0;
    };
  };
}
