{ runCommand, ti-linux-firmware }:
runCommand "wl18xx-firmware"
  {
    allowedReferences = [ ];
  }
  ''
    mkdir -p $out/lib/firmware/ti-connectivity
    cp ${ti-linux-firmware}/ti-connectivity/wl18xx-fw-4.bin $out/lib/firmware/ti-connectivity/
  ''
