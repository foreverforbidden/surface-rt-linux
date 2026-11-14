# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A new kernel boots, but there is no Wi-Fi | Compressed modules (`.ko.zst`) and `kmod` without zstd | Build with module compression off. [02-kernel-7.2.md](02-kernel-7.2.md) |
| The trial kernel hangs at boot | Unknown | Hold the power button. The next boot is the old kernel. [03-safe-boot.md](03-safe-boot.md) |
| The tablet always boots the old kernel | `trynew.flag` is gone after a failed trial, or `startup.nsh` is the trial script | Check `/boot/startup.nsh`, then run `install-kernel.sh` again or `make-default.sh` |
| `install-kernel.sh` stops: "already exists" | A file it would write is on `/boot` or in `/lib/modules` | Pick new names with `NEW_IMAGE` and `NEW_DTB`, or remove the old trial files by hand |
| Other machines cannot reach the tablet's IPv4 address, SSH by name still works | Wi-Fi power save, or TKIP group cipher on the router | [05-wifi.md](05-wifi.md) |
| `arp -a` on another machine shows the tablet as `(incomplete)` | Broadcasts do not reach the tablet | [05-wifi.md](05-wifi.md) |
| `Illegal instruction` (SIGILL) in ffmpeg, GStreamer or UxPlay | Raspberry Pi OS libav built with `sdiv` | `LD_HWCAP_MASK=0`. [07-video-airplay.md](07-video-airplay.md) |
| `v4l2slh264dec`: `Failed to open decoder` | GStreamer 1.18 is too old for the kernel API | Use the GStreamer 1.26 build. [07-video-airplay.md](07-video-airplay.md) |
| `v4l2slh264dec`: `Failed to decode frame 1` | The stream uses CABAC | The VDE decodes CAVLC only. Use software decoding |
| AirPlay video falls behind more and more | The stream is too large for software decoding | Use `1280x720` at 30 fps or smaller. [07-video-airplay.md](07-video-airplay.md) |
| No sound from the speakers, but `aplay` exits with 0 | The WM8962 speaker path is off | `system/speaker-on.sh`. [06-audio-input-display.md](06-audio-input-display.md) |
| Writing to `/sys/class/backlight/*/brightness` fails | Only root can write it | Install `system/90-backlight.rules`, join the `video` group, reboot |
| The volume buttons do nothing in your program | No read access to the input device | Join the `input` group. [06-audio-input-display.md](06-audio-input-display.md) |
| An `apt upgrade` wants to install a Pi kernel | `raspberrypi-kernel` is not on hold | `sudo apt-mark hold raspberrypi-kernel raspberrypi-bootloader`. [08-raspbian-upkeep.md](08-raspbian-upkeep.md) |
| A build or `npm install` on the tablet dies with no error | The OOM killer, with only about 100 MB of swap | Build on your PC. [08-raspbian-upkeep.md](08-raspbian-upkeep.md) |
| Your SSH session closes when you run `pkill -f` | The pattern matched your own SSH command | Anchor it: `pkill -f '^python3 app.py'` |
| systemd at shutdown: `Failed to set timeout to 600s` | The PMIC watchdog maximum is 100 seconds | Harmless. [04-hardware-status.md](04-hardware-status.md) |
| `failed to register cpuidle driver` | Expected with `cpuidle.off=1` | Harmless |
| The fullscreen GTK window is cut off at the right edge | One page is wider than the screen | [09-dashboard.md](09-dashboard.md) |

If your problem is not here, open an issue. Include `uname -r`, the output of `dmesg --level=err,warn` and your `startup.nsh`.
