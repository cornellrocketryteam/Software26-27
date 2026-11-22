{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/um560.nix ] ++ extra;
  }).config;
  base = evaluate [ ];
  kiosk = evaluate [ { groundStation.kiosk.enable = true; } ];
  checks = {
    defaultOff = !base.groundStation.kiosk.enable && !base.services.greetd.enable;
    enabled = kiosk.services.greetd.enable && kiosk.programs.sway.enable;
    unprivileged = kiosk.services.greetd.settings.initial_session.user == "operator"
      && !(builtins.elem "wheel" kiosk.users.users.operator.extraGroups);
    localUrl = kiosk.groundStation.kiosk.path == "/station/";
    displayRoute = kiosk.services.nginx.virtualHosts.ground-station.locations ? "^~ /station/";
    graphicalBoot = kiosk.systemd.defaultUnit == "graphical.target";
    supervised = kiosk.systemd.services.greetd.serviceConfig.Restart == "always";
    recoverable = kiosk.services.getty.autologinUser == null;
    graphics = kiosk.hardware.graphics.enable;
    noInputRequired = lib.hasInfix "WLR_LIBINPUT_NO_DEVICES=1" kiosk.services.greetd.settings.initial_session.command;
    noWanDependency = !(builtins.elem "network-online.target" kiosk.systemd.services.greetd.after);
    assertions = lib.all (a: a.assertion) kiosk.assertions;
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "kiosk contract failed";
checks
