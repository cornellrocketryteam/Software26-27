# Fill-station networking

The current images use **Ethernet**, not automatic Wi-Fi. See
[Ethernet setup and testing](ETHERNET_SETUP.md) for cabling, DHCP, SSH and MQTT.

The former `CornellRocketry-Fill` Wi-Fi configuration is no longer packaged or
started. The board still has Wi-Fi hardware, but this image does not provide a
supported automatic Wi-Fi fallback. An older flashed image will retain its old
Wi-Fi behavior until its FIT or full SD image is updated.
