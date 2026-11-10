{ ... }:
{
  users.users = {
    root.hashedPassword = "!";
    ground-admin = {
      isNormalUser = true;
      description = "Ground station administrator (existing contributor public keys)";
      extraGroups = [ "wheel" ];
      hashedPassword = "!";
      openssh.authorizedKeys.keyFiles = [ ../../mixos-modules/fill-station-base/authorized_keys ];
    };
    operator = {
      isNormalUser = true;
      description = "Unprivileged operator; kiosk integration pending";
      hashedPassword = "!";
    };
  };
  # Key-only ground-admin is privileged; the operator is not a sudoer.
  security.sudo.wheelNeedsPassword = false;
}
