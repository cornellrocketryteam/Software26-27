# Read-only signed cache. Neither SSH ingestion nor remote building is enabled.
{ ... }:
{
  groundStation.cache = {
    enable = true;
    signingKeyFile = "/var/lib/ground-station/cache-signing/cache.sec";
    provisioning.enable = true;
  };
}
