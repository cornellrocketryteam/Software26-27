# Legacy Ubuntu mini-PC inventory

This is a **historical Ubuntu snapshot**, recorded 2026-11-12 from user-run
commands and photos collected starting November 11. The owner subsequently
installed the NixOS foundation and test-activated the telemetry services. The
Ubuntu account, mount usage, absent SSH server and old container state below are
not current NixOS settings. The assistant did not connect to or install the PC.

Use the [current network/device reference](ground-station-network.md) and
[services update guide](ground-station-update.md) for present addresses, wiring,
credential lookup and the reported physical service checks. The remaining
historical entries are preserved for context.

## Hardware and operating system

| Item | Observed/reported value |
| --- | --- |
| Model | User identifies MINISFORUM UM560 XT |
| OS | Ubuntu 24.04.4 LTS, Noble Numbat |
| CPU | AMD Ryzen 5 5600H with Radeon Graphics, x86_64, 6 cores / 12 logical CPUs |
| OS-visible memory | `free -h`: 13 GiB total, approximately 11 GiB available at collection |
| Swap | 4 GiB total, none used at collection |
| Disk | `nvme0n1`, 476.9 GiB (nominal 512 GB class) |
| EFI partition | `nvme0n1p1`, about 1 GiB, FAT, mounted at `/boot/efi` |
| Root partition | `nvme0n1p2`, 475.9 GiB partition, ext4 mounted at `/` |
| Root filesystem usage | `df -h`: 468 GiB filesystem, 27 GiB used, 418 GiB available, 6% used |
| Boot mode | UEFI, supported by the photo showing mounted `efivarfs` |
| Ethernet | `eno1`, UP, `192.168.1.206/24` |
| Ethernet MAC | `58:47:CA:7E:6E:15`; initial missing sysfs path was a typing error, subsequently resolved |
| Local console account | `crt`, hostname `crt`, visible in supplied terminal photos |
| SSH | `ssh.service` absent; `dpkg -l openssh-server` reported `un ... <none>` (server package not installed) |

The earlier proposed `root@192.168.1.206` SSH login is not verified. No SSH server
installation or account change has been performed. RAM reservation details,
filesystem UUIDs, NIC driver/firmware, USB serial identities and display behavior
remain uninspected. Do not turn disk names into destructive install commands.

## Running legacy services

The user reports all seven containers were up for about 17 minutes, corresponding
to the last PC power-on. This records observed automatic startup, not continued
operational relevance of every legacy integration. The repository's
[`compose.yml`](../../ground-station/compose.yml) supplies the core baseline and
`unless-stopped` restart policies; Matter's separate setup is not established by
that file. Exact image IDs and repository digests remain pending.

| Service | Reported image | Installed/runtime detail |
| --- | --- | --- |
| EMQX | `emqx/emqx:latest` | `emqx ctl status`: version **6.0.0**, node **`emqx@172.18.0.5`** |
| TimescaleDB | `timescale/timescaledb` (reported tag transcription `latest-p917`; repo uses `latest-pg17`; exact image identity pending) | PostgreSQL **17.7**, TimescaleDB extension **2.24.0** |
| Grafana | `grafana/grafana-oss:latest` | **12.3.1**, commit `0d1a5b4420a5e4579b91c239ecb240ea2b247fba` |
| Portainer | `portainer/portainer-ce:latest` | Optional legacy administration UI; migration need not established |
| go2rtc | `alexxit/go2rtc` | Camera integration relevance/version pending |
| Home Assistant | `homeassistant/home-assistant:stable` | Integration relevance/version pending |
| Matter server | `ghcr.io/home-assistant-libs/python-matter-server:stable` | Integration relevance/version pending |

PostgreSQL lists only `postgres`, `template0` and `template1`. The TimescaleDB
extension and the visible **`telemetry_data` table are in `postgres`**. A database
named `telemetry` does not exist on this host. Table presence is confirmed; row
count, detailed schema and restore compatibility have not yet been checked.

## Fresh-install decision (November 12)

The owner explicitly accepts loss of the old Ubuntu installation and container
data. Legacy backups, mount auditing, exports and restore tests are **not install
prerequisites**. Nothing has been erased or installed on the PC by the assistant.

- Reuse the repository's EMQX/TimescaleDB/Grafana schema, rules and dashboard,
  initializing fresh state. The new database may use the default `telemetry` name;
  no mapping from the old `postgres` database is required.
- Legacy versions above are reference only. Select immutable production images
  with validated APIs, PostgreSQL/Timescale compatibility and EMQX edition/license
  capabilities. Disposable VM fixtures are not production defaults.
- Ancillary services are opt-in according to current use, rather than carrying
  over all seven containers. Old broker node identity need not be preserved.
- User-reported mounts included EMQX and Grafana under `/home/crt/data`, and both
  a Docker volume and `/home/crt/data/timescaledb` for TimescaleDB. The transcript
  contains spelling/case uncertainty; these are not verified copy/reuse paths.
  Resolving them is unnecessary for the accepted fresh-install path.
- Future operational database/secret/cache retention and fill-station recovery
  releases remain separate requirements; this waiver concerns legacy PC state.

The new `ground-station-um560` foundation declares planned labels `CRT-GS-ROOT`
and `CRT-GS-EFI`, UEFI boot and MAC-bound Ethernet named `lan0` using IPv4 DHCP.
These labels describe new filesystems, not the current Ubuntu partition labels.
Building this target does not format disks or create installation media.

The separate [offline installer](ground-station-install.md) embeds this foundation
and provides console access/recovery. Next: physical boot and Ethernet/display
acceptance, production service image pins and credentials. Full operational
acceptance remains pending. No further legacy-data inventory is needed.
