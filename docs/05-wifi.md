# Wi-Fi

The Surface RT has a Marvell 88W8797 on SDIO. Linux drives it with `mwifiex_sdio`, and the interface is `mlan0`. It connects without problems, but other machines on the network can lose the tablet. We found two causes.

## The symptom

- From the tablet, everything works: updates, ping, DNS.
- From another machine, the tablet's IPv4 address stops answering at random times. Its `.local` name stops working too.
- SSH by name often still works. It goes over IPv6 link-local, which does not need ARP.
- On the other machine, `arp -a` shows the tablet as `(incomplete)`. When the tablet sends a packet to that machine first, the address works again for a while.

## Cause 1: power save drops ARP broadcasts

With power save on, the chip drops ARP broadcasts. Other machines ask "who has this address?" and get no answer.

Turn power save off:

```bash
sudo iw dev mlan0 set power_save off
iw dev mlan0 get power_save
```

The driver turns power save on again each time the link comes up, so a command at boot is not enough. [system/dhcpcd.exit-hook](../system/dhcpcd.exit-hook) runs on every dhcpcd event for `mlan0` and turns it off again:

```bash
sudo install -m 644 system/dhcpcd.exit-hook /etc/dhcpcd.exit-hook
```

We tested it with `wpa_cli reassociate`: power save stayed off after the reconnect.

## Cause 2: the router uses TKIP for group traffic

Power save off was not enough on our network. `tcpdump` on the tablet showed only the tablet's own packets: no incoming broadcast or multicast at all. The other machines' ARP requests never arrived. The driver's `rx_dropped` counter did not go up, so the frames were lost before the driver, probably in the firmware.

The router used mixed WPA/WPA2 mode. In that mode, unicast traffic uses CCMP (AES), but group traffic (broadcast and multicast) uses TKIP. The mwifiex firmware probably cannot decrypt TKIP group frames. Unicast still works, which explains why the address answers again after the tablet sends a packet first.

The likely fix is on the router: set Wi-Fi security to WPA2 with AES (CCMP) only, not "WPA/WPA2" or "TKIP+AES". If this fixes your tablet, please say so in an issue, so that we can remove the "probably".

To check your network from the tablet:

```bash
sudo wpa_cli status | grep -E 'pairwise_cipher|group_cipher'
```

If `group_cipher=TKIP`, change the router.

## How to diagnose it

Install the tools (both have armhf packages):

```bash
sudo apt-get -y install tcpdump iputils-arping
```

1. On the tablet, watch for broadcasts from other machines:

   ```bash
   sudo tcpdump -ni mlan0 'arp or broadcast or multicast'
   ```

2. On another machine, ping the tablet's IPv4 address.
3. If the tablet sees no ARP requests while the other machine shows `(incomplete)`, the broadcasts do not arrive. Check power save first, then the group cipher.

The dashboard's tap-to-fix panel ([09-dashboard.md](09-dashboard.md)) checks power save and the Wi-Fi state with one tap.

## Other notes

- linux-surface-rt has a patch for Wi-Fi scans with firmware older than 14.68 (`0025-wifi-mwifiex-use-the-legacy-scan-with-pre-14.68-firm.patch`).
- With compressed kernel modules and the `kmod` of Raspberry Pi OS 11, the Wi-Fi module does not load at all. Our kernel overlay turns module compression off. See [02-kernel-7.2.md](02-kernel-7.2.md).
