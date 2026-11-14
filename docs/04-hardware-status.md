# Hardware status on 7.2.13-surface

All results are from one Surface RT that boots through UEFI, with Raspberry Pi OS 11. If your results are different, please open an issue with the hardware report template.

## Summary

| Part | Status | Where to look |
|---|---|---|
| CPU cores | 4 online | `nproc` |
| CPU frequency scaling | 51 MHz to 1.4 GHz | `/sys/devices/system/cpu/cpu0/cpufreq/` |
| L2 cache | On | Through the secure monitor. Not on 5.17 |
| Thermal zones | 3 | `/sys/class/thermal/thermal_zone*` |
| Battery and charger | Status reported | `/sys/class/power_supply/` |
| RAM | 1.9 GiB usable | `free -h` |
| Wi-Fi | Works, same address as on 5.17 | `mlan0`, module `mwifiex_sdio`. See [05-wifi.md](05-wifi.md) |
| Touchscreen | Works | Daily use with the dashboard |
| Backlight | Works | `/sys/class/backlight/`. See [06-audio-input-display.md](06-audio-input-display.md) |
| Speakers | Work after a mixer change | WM8962. See [06-audio-input-display.md](06-audio-input-display.md) |
| Volume buttons | Work | `/dev/input/by-path/platform-gpio-keys-event` |
| H.264 hardware decoder | CAVLC only | `tegra-vde`. See [07-video-airplay.md](07-video-airplay.md) |
| DRM overlay plane | Works | `kmssink driver-name=tegra` |
| `reboot` | Works | About 43 seconds until SSH answers again |
| CPU idle | Disabled | `cpuidle.off=1` |
| PMIC watchdog | Present, not armed | See below |
| `poweroff` | Not tested | |
| Cameras, Bluetooth, HDMI, Type Cover, microphones | Not tested by us | The kernel has patches for them |

After two trial boots there were no failed systemd units and no kernel warnings or oopses.

## Kernel arguments

```
root=PARTUUID=<your root partition> rootwait console=tty0 cpuidle.off=1 panic=10
```

| Argument | Why |
|---|---|
| `root=PARTUUID=...` | Finds the root partition by its ID, not by the MMC device number |
| `rootwait` | Waits for the MMC device, because there is no initramfs |
| `console=tty0` | Kernel messages on the screen |
| `cpuidle.off=1` | Keeps CPU idle off. We kept the setting from 5.17 and did not test 7.2 without it |
| `panic=10` | Reboots 10 seconds after a panic, so a trial boot falls back by itself |

## Messages that are normal

| Message | Why it is harmless |
|---|---|
| `failed to register cpuidle driver` | Expected with `cpuidle.off=1` |
| `Failed to set timeout to 600s: Invalid argument` (systemd, at shutdown) | systemd asks the TPS65911 PMIC watchdog for 600 seconds. Its maximum is 100 seconds. The watchdog was not left armed: the tablet stayed up for more than 5 minutes after the reboot |

## Compared with 5.17

The 7.2.13 kernel adds CPU frequency scaling, the L2 cache, three thermal zones and battery and charger status. These come from the full EFI device tree. See [02-kernel-7.2.md](02-kernel-7.2.md).

## Not tested yet

- `poweroff` from 7.2.13.
- The one-shot `oldkernel.flag` boot back to 5.17 (the `reboot` fallback during the trial worked).
- Suspend.
- The cameras, Bluetooth, HDMI out, the Type Cover and the microphones.

Reports for any of these are welcome.
