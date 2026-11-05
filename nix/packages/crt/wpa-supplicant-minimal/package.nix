{ wpa_supplicant }:
# D-Bus support alone drags dbus -> systemd-minimal, libx11, libxcb, audit
# into the image (~30 MB uncompressed). We only drive it via the config file.
wpa_supplicant.override {
  dbusSupport = false;
  withPcsclite = false;
  withReadline = false;
}
