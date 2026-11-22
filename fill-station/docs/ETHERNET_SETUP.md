# SK-AM64B Ethernet setup and testing

Liquid, Hybrid and debug images now request DHCP on `eth0`. BusyBox init raises
the interface and supervises foreground `udhcpc`, which renews the lease and
keeps trying if the cable/router is unavailable. Interface discovery retries
without blocking the serial shell or application. Wi-Fi association and embedded
Wi-Fi credentials have been removed. This changes Linux networking, not U-Boot
or network boot. The existing SSH keys and persistent state policy are unchanged.

## Cabling and address

Connect the board's CPSW Ethernet port to **fill-side switch 2, port 1**. Power
the board normally; do not assume the Ethernet cable powers it. The intended
board address is **192.168.1.106**, and MQTT uses the ground station at
**192.168.1.206:1883**. The router supplies DHCP: reserve `.106` using the board's
actual Ethernet MAC after reading it from the serial console. The image does not
force a static address or guess a MAC, gateway or DNS server. The first lease
may therefore be a different address.

The ground station must be running and the wireless bridge must connect the two
sides of the LAN. Internet/Starlink is not required. See the complete
[network and switch port map](../../docs/operations/ground-station-network.md).

## Build and deploy

Before flashing, the existing image can provide the missing hardware inventory.
Boot it normally, attach the intended Ethernet cable, and run `ip link` in its
serial console. Record both `eth0`/`eth1` entries, their `link/ether` MACs and which
one shows `LOWER_UP`. The current build runs DHCP on **one selected port**, `eth0`;
it does not request independent leases on both ports. If the connected socket is
`eth1`, change the interface option and rebuild before deploying.

From the repository root, with the established ARM64 Linux builder available:

```sh
nix build .#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage -o result-ospi-liquid
```

Use `mixosConfigurations.fill-station` for Hybrid, matching the actual hardware.
This build includes the working checkout's hardware edits and current PRU backend
support. Routine updates build only OSPI; existing boot switches and the DATA
card remain configured. Build an SD image explicitly only for recovery or new
provisioning. Flash a separate test/recovery card using
the [SD/OSPI deployment runbook](../../docs/operations/fill-station-deployment.md).
A full SD image overwrites that card's state and logs. Keep existing recovery
media until the wired image has passed testing.

For an existing OSPI installation, the same runtime change is in the FIT. Boot
the existing image, update the FIT using its currently working connection, then
reboot and find the wired address. No bootloader rewrite is needed solely for
this networking change. Follow the runbook and keep serial access throughout:

```sh
tools/flash-ospi.sh root@CURRENT_BOARD_IP fit result-ospi-liquid
```

Do not use `.106` in that command until it actually reaches the running board.
Alternatively, boot the new full SD first, verify Ethernet, and flash OSPI from
that known-good system. Test OSPI separately with a DATA-only card so an SD FIT
does not mask the flash contents.

## First physical test: serial console

Start with one command:

```sh
ip link
```

Find `eth0` and record its `link/ether` MAC. With the cable attached, look for
`LOWER_UP`. If the wired port appears under a different name, do not guess a
static IP or start a second DHCP client: inspect the interfaces/driver logs and
set `fillStation.ethernetInterface` to that observed `ethN` name before rebuilding.
`eth0` is the configured default; its mapping still needs the physical check.

Then inspect the lease and route:

```sh
ip -4 addr show dev eth0
ip route
```

Expect a `192.168.1.x/24` lease; after the router reservation takes effect, expect
`.106`. Verify ground-station reachability:

```sh
ping -c 3 192.168.1.206
```

From a laptop on the same LAN, using the actual lease address:

```sh
ssh root@192.168.1.106
```

SSH remains public-key only. Inspect `/var/log/messages` for DHCP/Dropbear
failures. A persistent `/etc` overlay can retain an old Wi-Fi configuration file,
but the new init configuration does not launch Wi-Fi. Do not delete the DATA
partition or regenerate SSH host keys to troubleshoot networking.

## Acceptance checklist

- [ ] Record the actual wired interface, MAC and DHCP lease; reserve `.106`.
- [ ] Ping the ground station and log in over wired SSH.
- [ ] Confirm fresh telemetry from this board reaches MQTT, the database and
  FillOps; seeing the dashboard alone does not prove ingestion.
- [ ] Unplug/replug Ethernet and confirm connectivity/telemetry recover.
- [ ] Reboot and confirm wired networking and SSH return without manual commands.
- [ ] Repeat the boot/network checks from OSPI and record the actual boot source.

Source configuration checks and successful image builds cannot prove the physical
link, switch configuration, board MAC or telemetry delivery.

## Checks completed before the hardware test

On November 13, 2026, Liquid SD and OSPI builds and a Hybrid FIT build passed.
Both FITs passed merged pinmux verification and the OSPI slot-size check. Inspection
of their embedded device trees confirmed the CPSW controller and both Ethernet
ports enabled. The built init table selects wired DHCP without a Wi-Fi process;
configuration checks passed for Liquid, Hybrid and debug profiles. A shell-level
check exercised retrying interface discovery before starting foreground DHCP.
Physical networking, DHCP leases and MQTT ingestion remain pending.
