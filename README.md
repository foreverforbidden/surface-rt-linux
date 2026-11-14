# Surface RT on modern Linux

The Microsoft Surface RT (2012) has good hardware: a quad-core NVIDIA Tegra 3, 2 GB of RAM, a 1366×768 touchscreen and stereo speakers. Its software is dead. Windows RT gets no updates, and many Surface RT Linux installs still run a 5.17 development kernel from 2022.

This repository shows how one Surface RT runs Linux 7.2.13 on Raspberry Pi OS 11 (Raspbian bullseye) every day. It has the scripts, the boot files, the measurements and the problems we found, so you can do the same on your tablet without the guesswork.

You can use it in three ways:

- Upgrade an existing Surface RT Linux install to kernel 7.2.13 with a safe one-shot trial boot.
- Look up a fix: Wi-Fi that drops off the network, silent speakers, `SIGILL` in ffmpeg, video decode limits.
- Copy the touch dashboard as a starting point for a kiosk, a wall panel or a home display.

## What works on 7.2.13

Tested on one Surface RT (not the Surface 2) with the UEFI boot path.

| Part | Status | Notes |
|---|---|---|
| 4 CPU cores | Works | Started through the ACPI parking protocol |
| CPU frequency scaling | Works | 51 MHz to 1.4 GHz. New compared with 5.17 |
| L2 cache | Works | Through the secure monitor. New compared with 5.17 |
| Thermal zones | Works | Three zones. New compared with 5.17 |
| Battery and charger status | Works | |
| Wi-Fi (Marvell 88W8797, `mwifiex_sdio`) | Works | Read [docs/05-wifi.md](docs/05-wifi.md) first |
| Touchscreen | Works | Used by the dashboard every day |
| Backlight | Works | Needs a udev rule for non-root control |
| Speakers (WM8962) | Works | Needs a mixer route: [system/speaker-on.sh](system/speaker-on.sh) |
| Volume buttons | Works | `gpio-keys` input device |
| Hardware H.264 decode (`tegra-vde`) | Partly | CAVLC streams only. No CABAC, so not AirPlay |
| DRM overlay plane (`kmssink`) | Works | About 60 fps zero-copy video |
| `reboot` | Works | About 43 seconds back to SSH |
| CPU idle | Off | Boot with `cpuidle.off=1` |
| `poweroff` | Not tested | |
| Cameras, Bluetooth, HDMI, Type Cover | Not tested here | The kernel has patches for some of these |

The full list, with kernel arguments and expected warnings, is in [docs/04-hardware-status.md](docs/04-hardware-status.md).

## Start here

1. Your Surface RT must already boot Linux. The Open Surface RT project explains how to unlock Secure Boot and install a base system: [open-rt.gitbook.io](https://open-rt.gitbook.io/open-surfacert/get-started/linux). See [docs/01-start-here.md](docs/01-start-here.md).
2. Get the kernel. Download it from [Releases](https://github.com/foreverforbidden/surface-rt-linux/releases), or build it yourself in about 30 minutes: [docs/02-kernel-7.2.md](docs/02-kernel-7.2.md).
3. Install it next to your current kernel and do one trial boot. If the new kernel fails, the next boot is the old one: [docs/03-safe-boot.md](docs/03-safe-boot.md).

```bash
scripts/build-kernel.sh                         # or unpack a release into out/
scripts/install-kernel.sh --dry-run rt          # shows every change, changes nothing
scripts/install-kernel.sh rt                    # rt = ssh name of your tablet
ssh rt sudo reboot                              # be at the tablet for this one
scripts/make-default.sh rt                      # only after a good trial boot
```

## Documentation

| Page | Contents |
|---|---|
| [01 Start here](docs/01-start-here.md) | What you need before you begin |
| [02 Kernel 7.2](docs/02-kernel-7.2.md) | Where the kernel comes from, how to build it, our config changes |
| [03 Safe boot](docs/03-safe-boot.md) | One-shot trial boots and fallbacks in the UEFI shell |
| [04 Hardware status](docs/04-hardware-status.md) | What works, kernel arguments, harmless warnings |
| [05 Wi-Fi](docs/05-wifi.md) | Power save and TKIP problems that hide the tablet from the network |
| [06 Audio, input, display](docs/06-audio-input-display.md) | Speakers, volume buttons, backlight, touch |
| [07 Video and AirPlay](docs/07-video-airplay.md) | Software and hardware H.264, benchmarks, an AirPlay receiver |
| [08 Raspbian upkeep](docs/08-raspbian-upkeep.md) | Safe upgrades, package holds, Node.js, low memory |
| [09 Touch dashboard](docs/09-dashboard.md) | A GTK kiosk with a crash rescue screen |
| [Troubleshooting](docs/troubleshooting.md) | Symptom, cause, fix |

## Repository layout

```
docs/            the guides above
scripts/         build, install, make-default and rollback scripts (run on your PC)
kernel/overlay/  our config changes on top of linux-surface-rt
kernel/boot/     example UEFI shell boot scripts
system/          files that go to /etc on the tablet
video/           GStreamer 1.26 cross-build for hardware decode, UxPlay patch
bench/           raw benchmark results
dashboard/       the touch dashboard (Python, GTK 3)
```

## Credits

The kernel is [linux-surface-rt](https://github.com/nuno407/linux-surface-rt) by nuno407. It builds on the patches of [libre-tegra](https://codeberg.org/libre-tegra/linux), [grate-driver](https://github.com/grate-driver/linux) and the [Open Surface RT](https://open-rt.gitbook.io/open-surfacert/) community. The AirPlay receiver is [UxPlay](https://github.com/FDH2/UxPlay). [THIRD_PARTY.md](THIRD_PARTY.md) lists the licences.

This project is not affiliated with Microsoft or NVIDIA. Surface is a trademark of Microsoft Corporation. Tegra is a trademark of NVIDIA Corporation.

## Contributing

Reports from other tablets are the most useful thing you can add. If you try this on your Surface RT, open an issue with the hardware report template, even if everything worked. See [CONTRIBUTING.md](CONTRIBUTING.md).
