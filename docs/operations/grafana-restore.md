# Restore the original Grafana panels

The original Fill Operations dashboard panels, layout, titles and queries are
restored. The working same-origin camera viewer and existing provisioning/access
fixes are retained. Commanding remains the accepted restored UI with its explicit
WebSocket endpoint; no firmware changes or board flashing are needed.

On the Mac, on the station LAN:

```sh
cd /Users/ronit/Software26-27
scp result-ground-grafana-restore-files/ground-station-grafana-restore-inputs.tar \
  result-ground-grafana-restore-files/SHA256SUMS ground-admin@192.168.1.206:~/
ssh ground-admin@192.168.1.206
```

On the mini PC, stop on any failure:

```sh
cd ~
sha256sum -c SHA256SUMS
mkdir ground-station-grafana-restore
tar -xf ground-station-grafana-restore-inputs.tar -C ground-station-grafana-restore
cd ground-station-grafana-restore
bash import-inputs.sh
bash build-ui.sh
bash test-ui.sh
```

Keep SSH open during the build. This incremental bundle reuses previously
imported offline inputs, checked by the import script. Test activation reloads
Grafana and the displays; the test script checks page health and signed cache
reads. Verify the original panels, cameras and still-connected Commanding.
This does not change the PC boot default. To restore the preceding generation:

```sh
previous=$(cat previous-system)
sudo "$previous/bin/switch-to-configuration" test
sudo systemctl restart greetd
```

Source JSON was compared against the original: every original panel and query
matches, except the preserved camera iframe. Native generation build and actual
display acceptance are operator-run, not claimed from local checks.
