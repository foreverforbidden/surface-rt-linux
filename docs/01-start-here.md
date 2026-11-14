# Start here

This repository starts where the Open Surface RT guides end. Your tablet must already boot Linux from its UEFI firmware.

## Get Linux on the tablet first

A stock Surface RT only starts code that Microsoft signed. The Open Surface RT project documents how to disable Secure Boot and install Linux:

- [Get started: Secure Boot](https://open-rt.gitbook.io/open-surfacert/get-started/secure-boot)
- [Yahallo: disable Secure Boot](https://open-rt.gitbook.io/open-surfacert/common/boot-sequence/uefi/secure-boot/disable-secureboot)
- [Get started: Linux](https://open-rt.gitbook.io/open-surfacert/get-started/linux)
- [Raspberry Pi OS on the Surface RT](https://open-rt.gitbook.io/open-surfacert/surface-rt/linux/root-filesystem/distros/raspberry-pi-os)
- [UEFI boot](https://open-rt.gitbook.io/open-surfacert/surface-rt/linux/booting/uefi-boot)

Our tablet used the Raspberry Pi OS 11 (bullseye, armhf) image from those guides, with the 5.17 development kernel from the `grate-linux` fork. It booted through `startup.nsh` in the UEFI shell. The scripts here expect that setup.

The community is on [Discord](https://discord.gg/VW75GmWa95).

## What you need

On the tablet:

- Linux that boots through the UEFI shell and `/boot/startup.nsh`, with `/boot` the vfat boot partition.
- Wi-Fi and an SSH server.
- A user with passwordless `sudo`. The scripts run every command over SSH and cannot answer prompts.
- About 9 MB free on `/boot` and 40 MB free on `/`.

On your PC:

- macOS or Linux with Docker, if you want to build the kernel. On a Mac, [Colima](https://github.com/abiosoft/colima) works: `brew install colima docker`.
- An SSH key for the tablet. A `~/.ssh/config` entry makes the commands shorter:

```
Host rt
    HostName surface.local
    User pi
```

The examples in these docs use `rt` as the tablet's SSH name. Replace it with yours.

## Recovery before you start

You need a way back if a boot fails. Make sure that you can do each of these before you change a kernel:

1. Attach a keyboard. Press Esc during boot to get the UEFI shell.
2. In the shell, type `fs0:` and then the name of a boot script, for example `startup-old.nsh`.
3. Hold the power button until the tablet turns off.

[docs/03-safe-boot.md](03-safe-boot.md) explains how the scripts use these.

## Things that are different on this tablet

- It is 32-bit ARM (armv7l, Cortex-A9). Check that a package has an armhf build before you choose it.
- It has 2 GB of RAM and about 100 MB of swap. Large compiles and big `npm install` runs get OOM-killed instead of slowing down. Build on your PC and copy the result.
- The CPU has no `sdiv` instruction. Some Raspberry Pi OS libraries use it. See [docs/07-video-airplay.md](07-video-airplay.md).
- Raspberry Pi OS thinks it runs on a Pi. Hold its kernel packages, or an upgrade writes Pi kernels to `/boot`. See [docs/08-raspbian-upkeep.md](08-raspbian-upkeep.md).
