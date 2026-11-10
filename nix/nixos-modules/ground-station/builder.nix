{ config, lib, pkgs, ... }:
let
  cfg = config.groundStation.builder;
  allowed = cfg.enable && cfg.validated && !config.groundStation.fieldMode;
  admission = pkgs.writeShellScript "ground-build-admission" ''
    set -eu
    ${lib.optionalString (!allowed) ''
      echo "Ground-station builds inhibited: field mode or unvalidated/disabled worker." >&2
      exit 1
    ''}
    if test -e /run/ground-station/field-mode; then
      echo "Ground-station builds inhibited by runtime field-mode marker." >&2
      exit 1
    fi
    read -r blocks blocksize < <(${pkgs.coreutils}/bin/stat -f --format='%a %S' /nix/store)
    if (( blocks * blocksize < ${toString cfg.minimumFreeBytes} )); then
      echo "Ground-station builds inhibited: Nix-store filesystem below free-space reserve." >&2
      exit 1
    fi
  '';
in
{
  options.groundStation.builder = {
    enable = lib.mkEnableOption "local station builds (no SSH worker endpoint is provisioned)";
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
  };

  config = {
    assertions = [
      { assertion = cfg.enable -> cfg.validated; message = "ground-station builder validation is required before enabling station builds."; }
      { assertion = cfg.aarch64.enable -> (cfg.enable && cfg.aarch64.validated); message = "ground-station aarch64 validation and an enabled validated builder are required before advertising ARM execution."; }
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
    # Limit the daemon doing the work, not an SSH launcher. No sshServe/direct
    # stdio daemon is enabled: that would need its own validated containment.
    systemd.services.nix-daemon.serviceConfig = {
      CPUQuota = "300%";
      MemoryHigh = "5G";
      MemoryMax = "6G";
      MemorySwapMax = 0;
      TasksMax = 512;
      Nice = 10;
      IOWeight = 10;
    };
  };
}
