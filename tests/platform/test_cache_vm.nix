# Manual signing/retention acceptance; no physical configuration or global GC.
{ pkgs }:
(import ./test_operator_ui_vm.nix { inherit pkgs; }).extend {
  modules = [ ({ lib, ... }: {
    name = lib.mkForce "ground-signed-cache";
    requiredFeatures.apple-virt = false;
    nodes.station = { config, lib, pkgs, ... }:
    let
      dependency = pkgs.runCommand "ground-cache-vm-dependency" { } ''
        mkdir -p "$out"
        printf 'dependency\n' > "$out/payload"
      '';
      artifact = pkgs.runCommand "ground-cache-vm-artifact" { } ''
        mkdir -p "$out"
        printf 'artifact\n' > "$out/payload"
        ln -s ${dependency}/payload "$out/dependency"
      '';
      control = pkgs.runCommand "ground-cache-vm-control" { } ''
        mkdir -p "$out"
        printf 'unretained\n' > "$out/payload"
      '';
      check = pkgs.writeShellScriptBin "ground-cache-vm-check" ''
        export PATH=${lib.makeBinPath [ config.nix.package pkgs.coreutils ]}:"$PATH"
        exec ${pkgs.python3}/bin/python3 ${./cache_vm_check.py} "$@"
      '';
    in {
      virtualisation.memorySize = lib.mkForce 1536;
      groundStation.cache.signingKeyFile = "/var/lib/ground-cache-vm/cache.sec";
      environment.systemPackages = [ pkgs.python3 check ];
      environment.etc."ground-cache-vm.json".text = builtins.toJSON {
        inherit dependency artifact control;
      };
      systemd.tmpfiles.rules = [ "d /var/lib/ground-cache-vm 0700 root root - -" ];
      systemd.services.ground-cache-vm-key = {
        wantedBy = [ "multi-user.target" ];
        before = [ "harmonia.service" "nix-daemon.service" ];
        environment.NIX_REMOTE = "local";
        serviceConfig = { Type = "oneshot"; RemainAfterExit = true; UMask = "0077"; };
        script = ''
          for name in cache unrelated; do
            if ! test -e /var/lib/ground-cache-vm/$name.sec; then
              ${config.nix.package}/bin/nix-store --generate-binary-cache-key \
                "$name-vm.test" /var/lib/ground-cache-vm/$name.sec /var/lib/ground-cache-vm/$name.pub
            fi
            test -s /var/lib/ground-cache-vm/$name.pub
            chmod 0600 /var/lib/ground-cache-vm/$name.sec
          done
        '';
      };
      systemd.services.harmonia = {
        requires = [ "ground-cache-vm-key.service" ];
        after = [ "ground-cache-vm-key.service" ];
      };
      systemd.services.nix-daemon = {
        requires = [ "ground-cache-vm-key.service" ];
        after = [ "ground-cache-vm-key.service" ];
      };
      systemd.services.ground-cache-vm-corrupt-signature = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig = {
          ExecStart = "${check}/bin/ground-cache-vm-check proxy";
          Restart = "on-failure";
          UMask = "0077";
        };
      };
    };
    testScript = lib.mkForce ''
      start_all()
      station.wait_for_unit("multi-user.target", timeout=600)
      station.wait_for_unit("nginx", timeout=120)
      station.wait_for_unit("ground-cache-vm-key", timeout=120)
      station.wait_for_unit("ground-cache-vm-corrupt-signature", timeout=120)
      station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
      station.wait_until_succeeds("curl --fail http://127.0.0.1:8080/cache/nix-cache-info", timeout=120)
      station.wait_for_unit("harmonia", timeout=120)
      print(station.succeed("ground-cache-vm-check verify"))
      station.succeed("cp /var/lib/ground-cache-vm/cache.pub /var/lib/ground-cache-vm/before.pub")
      station.succeed("systemctl stop harmonia.socket harmonia.service")
      print(station.succeed("ground-cache-vm-check outage"))
      station.succeed("curl --fail http://127.0.0.1:8080/ui-healthz | grep 'id=\"root\"'")
      station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")
      station.succeed("systemctl start harmonia.socket")
      station.wait_until_succeeds("curl --fail http://127.0.0.1:8080/cache/nix-cache-info", timeout=120)
      print(station.succeed("ground-cache-vm-check restore"))
      station.shutdown()
      station.start()
      station.wait_for_unit("multi-user.target", timeout=600)
      station.wait_until_succeeds("curl --fail http://127.0.0.1:8080/cache/nix-cache-info", timeout=120)
      station.succeed("cmp -s /var/lib/ground-cache-vm/cache.pub /var/lib/ground-cache-vm/before.pub")
      print(station.succeed("ground-cache-vm-check afterboot"))
      station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
      station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")
      station.fail("test -e /etc/systemd/system/ground-command-listener.service")
      station.fail("systemctl is-active docker.service")
    '';
  }) ];
}
