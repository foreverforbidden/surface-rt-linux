# Kernel 7.2.13

Mainline Linux has no device tree for the Surface RT. A current kernel needs Surface RT patches on top of a kernel.org release. Other people already carry those patches forward, so we build their tree and do not port anything ourselves.

## Where the kernel comes from

We use [nuno407/linux-surface-rt](https://github.com/nuno407/linux-surface-rt), pinned at commit `6468f0b`. It downloads the Linux 7.2.13 tarball from kernel.org, checks its sha256 and applies 45 patches:

- Seven patches come from [libre-tegra](https://codeberg.org/libre-tegra/linux), the community Tegra tree that postmarketOS packages. They add the device trees, CPU bring-up, L2 cache and Type Cover support.
- The others fix problems found on a real unit: reboot and power-off hangs, Wi-Fi scans with older firmware, CPU idle hangs, sound, cameras and Bluetooth wiring.
- Each patch lists its origin in the repository's `PROVENANCE.md`.

Before we used it, we read all boot-critical and shared-code patches in full and scanned the rest. We found no binaries and no changes outside the drivers that the patches name. The tarball's sha256 matched kernel.org's signed `sha256sums.asc`.

Two warnings: the repository has one author we do not know, and Linux 7.2 no longer gets upstream fixes.

### What the old 5.17 kernel had

Many Surface RT installs run the 5.17-rc3 kernel from the Open Surface RT `grate-linux` fork (February 2022). It adds these to the grate-driver Tegra patches:

| Patch | What it does | In mainline now |
|---|---|---|
| ACPI parking protocol for ARM32 | Starts CPU cores 2 to 4 when the tablet boots through UEFI | No |
| `tegra30-microsoft-surface-rt.dts` | Device tree for the board | No |
| `tegra30-microsoft-surface-rt-efi.dts` | Smaller device tree for UEFI boot | No |
| I2C address 0x00 exception | Lets the kernel see the Type/Touch Cover on its I2C bus | No |
| `surface-rt-ec.c` | Battery and charger driver | Yes |
| WM8962 sound machine driver | Sound card | No |
| HID Type Cover 2 quirk | Stops stray F23 key presses from the cover's trackpad | No |
| LVDS codec binding (`idt,v103`) | Display bridge | Yes |

The 7.2.13 tree has patches for the same hardware. Examples are the parking protocol (`0001`), the Type Cover quirk (`0004`), the device trees (`0006`) and WM8962 fixes (`0010`, `0042`). The patch list is in `surface-rt/patches/` of linux-surface-rt.

The new EFI device tree is not the cut-down one that 5.17 uses. It keeps the PMIC regulators, CPU voltage scaling, the L2 cache (through the secure monitor) and the thermal zones. It only drops LP2 idle. This is why CPU frequency scaling and temperatures work on 7.2. It also makes the first boot a bigger change, so do the trial boot in [03-safe-boot.md](03-safe-boot.md).

## Our config changes

The overlay in [kernel/overlay/surface-rt/rt.config](../kernel/overlay/surface-rt/rt.config) adds three changes for Raspberry Pi OS 11:

| Option | Why |
|---|---|
| `CONFIG_AUTOFS_FS=y` | systemd uses autofs for its automount units. |
| `CONFIG_HARDEN_BRANCH_PREDICTOR=y` | The 5.17 kernel had this Spectre v2 mitigation for the Cortex-A9. |
| `CONFIG_MODULE_COMPRESS` off | The `kmod` 28 in Raspberry Pi OS 11 has no zstd support (`kmod --version` shows `-ZSTD`). It cannot load `.ko.zst` modules, so the Wi-Fi module does not load and the tablet is off the network. |

If you skip the last change, the new kernel boots, but you cannot reach it over Wi-Fi.

The base config has everything that the tablet needs to boot without an initramfs. The EFI stub, ext4, SD/MMC, 4-CPU SMP and the framebuffer console are built in. Wi-Fi (`mwifiex_sdio`) is a module.

## Download a build

Each release has the files below and their checksums. Check them before you install:

```bash
shasum -a 256 -c SHA256SUMS
```

| File | Contents |
|---|---|
| `zImage` | The kernel, 7.4 MB |
| `tegra30-microsoft-surface-rt-efi.dtb` | Device tree for UEFI boot. This is the one you need |
| `tegra30-microsoft-surface-rt.dtb` | Device tree for other boot paths |
| `modules.tar.gz` | 567 modules, 39 MB unpacked, in `lib/modules/7.2.13-surface/` |
| `kernel.config`, `kernel.release` | The full config and the release string `7.2.13-surface` |
| `manifest.json`, `SHA256SUMS` | Sizes and sha256 of every file, and the source commit |

The release also has the source: the linux-surface-rt tree at the pinned commit, our overlay and the kernel.org tarball.

## Build it yourself

You need Docker and about 4 GB of disk. The build runs in a Debian container for your PC's own architecture, with a cross compiler. Nothing is emulated, so it also runs at full speed on an Apple Silicon Mac. A build takes about 30 minutes on a 4-core desktop.

On a Mac, start Colima first:

```bash
brew install colima docker
colima start --cpu 8 --memory 8 --disk 20
```

Then build:

```bash
scripts/build-kernel.sh            # artifacts in out/
```

The script clones linux-surface-rt, checks out the pinned commit and runs its `build.sh` with our overlay. It checks the checksums at the end. The kernel tree stays in the Docker volume `linux-surface-rt-src`, not on your disk.

The build is reproducible: the same commit and overlay in the same container image give the same bytes. A container image that you build on another day can have newer Debian packages, so your checksums can differ from the release.

To add your own config options, put them in `kernel/overlay/surface-rt/rt.config` and build again. The linux-surface-rt README explains overlays in its "Overlays" section.

## Next step

Install the kernel next to your old one and do a trial boot: [03-safe-boot.md](03-safe-boot.md).
