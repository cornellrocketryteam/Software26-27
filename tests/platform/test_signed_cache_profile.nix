{ nixpkgs }:
let
  lib = import (nixpkgs + "/lib");
  evaluate = extra: (import (nixpkgs + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [ ../../nix/nixos-configurations/ground-station
      ../../nix/nixos-configurations/ground-station/vm.nix ] ++ extra;
  }).config;
  base = evaluate [ ];
  cache = evaluate [ ../../nix/nixos-configurations/ground-station/signed-cache.nix ];
  key = "/var/lib/ground-station/cache-signing/cache.sec";
  valid = c: lib.all (a: a.assertion) c.assertions;
  bad = evaluate [ { groundStation.cache = {
    provisioning.enable = true; signingKeyFile = "/var/lib/another.sec";
  }; } ];
in {
  defaultOff = !base.groundStation.cache.enable && !base.groundStation.cache.provisioning.enable;
  profileValid = valid cache;
  fieldMode = cache.groundStation.fieldMode;
  workerOff = !cache.groundStation.builder.enable && !cache.groundStation.builder.remote.enable
    && !cache.groundStation.builder.validated && !cache.groundStation.builder.validation.enable;
  noPrivilegedIngest = !cache.groundStation.cache.ingestion.enable
    && !(cache.users.users ? ground-cache) && !(cache.users.users ? ground-builder);
  runtimeKey = cache.groundStation.cache.signingKeyFile == key;
  daemonSigning = cache.nix.settings.secret-key-files == [ key ];
  credentialPlumbing = cache.systemd.services.harmonia.serviceConfig.LoadCredential == [ "sign-key-0:${key}" ]
    && cache.systemd.services.harmonia.environment.SIGN_KEY_PATHS == "%d/sign-key-0"
    && cache.systemd.services.harmonia.serviceConfig.DynamicUser;
  loopbackBackend = cache.services.harmonia.cache.settings.bind == "127.0.0.1:5000";
  readOnlyProxy = cache.services.nginx.virtualHosts.ground-station.locations."/cache/".proxyPass == "http://127.0.0.1:5000/";
  helperInstalled = builtins.elem cache.system.build.groundCacheProvisioner cache.environment.systemPackages;
  wrongPathRejected = !valid bad;
  limitsRemain = cache.systemd.services.harmonia.serviceConfig.MemoryMax == "512M"
    && cache.nix.settings.require-sigs && cache.nix.settings.max-jobs == 0;
}
