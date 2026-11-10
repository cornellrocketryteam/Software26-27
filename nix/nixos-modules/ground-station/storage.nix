{ ... }:
{
  services.journald.settings.Journal = {
    Storage = "persistent";
    SystemMaxUse = "512M";
    SystemKeepFree = "2G";
    MaxRetentionSec = "14day";
  };
  systemd.tmpfiles.rules = [
    "d /var/lib/ground-station 0750 root root - -"
    "d /var/lib/ground-station/releases 0750 root root - -"
    "d /var/lib/ground-station/pending 0700 root root - -"
    "d /var/lib/ground-station/backups 0700 root root - -"
    "d /nix/var/nix/gcroots/ground-station 0750 root root - -"
    "d /run/ground-station 0755 root root - -"
  ];
  # Release GC roots, data-consistent backups and retention policy are separate
  # work. No collector can silently delete offline/recovery inputs in this phase.
  nix.gc.automatic = false;
  nix.optimise.automatic = false;
  nix.settings = {
    keep-derivations = true;
    keep-outputs = true;
  };
}
