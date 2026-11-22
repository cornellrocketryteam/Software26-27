{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/vm.nix ] ++ extra;
  }).config;
  base = evaluate [ ];
  validation = evaluate [ {
    groundStation.fieldMode = false;
    groundStation.builder.validation.enable = true;
  } ];
  field = evaluate [ { groundStation.builder.validation.enable = true; } ];
  enabled = evaluate [ {
    groundStation.fieldMode = false;
    groundStation.builder = { validation.enable = true; enable = true; validated = true; };
  } ];
  valid = c: lib.all (a: a.assertion) c.assertions;
  settings = builtins.fromJSON (builtins.unsafeDiscardStringContext validation.system.build.groundWorkerValidationSettings.text);
  checks = {
    defaultOff = !base.groundStation.builder.validation.enable;
    maintenanceValid = valid validation;
    fieldRejected = !valid field;
    normalBuilderRejected = !valid enabled;
    noWorkerEnabled = !validation.groundStation.builder.enable && !validation.groundStation.builder.validated
      && !validation.groundStation.builder.remote.enable && !(validation.users.users ? ground-builder);
    globalGatePreserved = validation.nix.settings.max-jobs == 0
      && validation.nix.settings.pre-build-hook == toString validation.system.build.groundWorkerAdmission;
    untrustedUnchanged = validation.nix.settings.trusted-users == base.nix.settings.trusted-users;
    resourceLimitsPreserved = validation.systemd.services.nix-daemon.serviceConfig.MemoryMax == "6G"
      && validation.systemd.services.nix-daemon.serviceConfig.CPUQuota == "300%";
    helperInstalled = lib.any (p: p.name == "crt-validate-build-daemon") validation.environment.systemPackages;
    fixedRecipe = settings.enabled && !settings.fieldMode
      && lib.hasSuffix ".drv" settings.fixtureDrv
      && validation.system.build.groundWorkerValidationFixture.allowSubstitutes == false;
    noOutputAtActivation = let
      context = builtins.getContext validation.system.build.groundWorkerValidationSettings.text;
      entry = context.${builtins.unsafeDiscardStringContext validation.system.build.groundWorkerValidationFixture.drvPath};
    in (entry.path or false) && !(entry.allOutputs or false);
    assertions = valid base;
  };
in
assert lib.assertMsg (lib.all (v: v) (builtins.attrValues checks))
  "daemon validation module contract failed";
checks
