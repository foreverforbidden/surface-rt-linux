# Licences

Everything in this repository is under the MIT licence ([LICENSE](LICENSE)), except:

| Path | Licence | Why |
|---|---|---|
| `kernel/overlay/` | GPL-2.0 | Configuration for the Linux kernel |
| `video/uxplay-1.73.7-render-rect.patch` | GPL-3.0 | A change to UxPlay |
| `dashboard/src/assets/world-land.json` | Public domain | Made from Natural Earth `ne_110m_land` with `dashboard/tools/make-world-map.py` |

## Software we build on

| Project | Licence | Used for |
|---|---|---|
| [Linux](https://kernel.org) | GPL-2.0 | The kernel |
| [linux-surface-rt](https://github.com/nuno407/linux-surface-rt) | GPL-2.0 | Surface RT patches and build scripts, commit `6468f0b` |
| [libre-tegra](https://codeberg.org/libre-tegra/linux) | GPL-2.0 | Patches that linux-surface-rt carries |
| [UxPlay](https://github.com/FDH2/UxPlay) | GPL-3.0 | AirPlay receiver, v1.73.7 |
| [GStreamer](https://gstreamer.freedesktop.org) | LGPL-2.1 | Video pipelines, 1.18.4 (system) and 1.26.11 (`video/`) |
| [Natural Earth](https://www.naturalearthdata.com) | Public domain | World map outlines |
| [Inter](https://rsms.me/inter/) | OFL-1.1 | Dashboard font, installed from Debian (`fonts-inter`) |

## Kernel release binaries

Each kernel release comes with its complete corresponding source, as the GPL requires: the linux-surface-rt tree at the commit in `manifest.json`, the overlay from this repository and the kernel.org tarball whose sha256 is in `manifest.json`.
