# Hybrid fill station that runs the E-REG bench sweep at boot (once) instead
# of the normal fill-station tasks. Bench use only, not for launch.
{
  imports = [ ../mixos-modules/fill-station-base ];

  fillStation.mode = "hybrid";
  fillStation.extraFeatures = [ "ereg-test" ];
}
