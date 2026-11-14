# Video and AirPlay

## SIGILL in ffmpeg and GStreamer

Programs that use libavcodec (ffmpeg, GStreamer's `avdec_h264`) can die with `SIGILL` (illegal instruction) on Raspberry Pi OS.

Raspberry Pi OS ships extra copies of the libav libraries in `/lib/arm-linux-gnueabihf/neon/vfp/`. They are the Raspberry Pi (`rpt`) builds, and they use the `sdiv` instruction. The Cortex-A9 in the Tegra 3 does not have `sdiv`. The dynamic loader picks the `neon/vfp` copies because the CPU reports NEON and VFP.

Set `LD_HWCAP_MASK=0`. The loader then ignores the hardware-capability directories and uses the normal libraries:

```bash
LD_HWCAP_MASK=0 ffmpeg -version
```

Set it for every program that uses libavcodec. The dashboard sets it when it starts the AirPlay receiver.

## Software H.264 decoding

These are synthetic decode-and-convert tests on the tablet with GStreamer 1.18.4 and `avdec_h264`. Each fixture has 120 frames. The ranges cover a one-slice and a four-slice fixture. "Delay" is the median time from decode to converted frame. "Drift" is how far the output falls behind the media timeline over the clip.

At 30 fps:

| Stream and decoder | Delivered fps | Median delay | Drift over clip |
|---|---:|---:|---:|
| 1366×768, frame threads (4), first setup | 25.1 to 25.2 | 545 to 590 ms | +756 to +768 ms |
| 1280×720, frame threads (4), first setup | 28.1 to 30.1 | 151 to 416 ms | −18 to +263 ms |
| 1280×720, slice threads (4), 1-frame queue | 29.7 to 30.2 | 51 to 56 ms | −21 to +2 ms |
| 1280×720, frame threads (2), 1-frame queue | 29.9 to 30.0 | 83 ms | −17 to −5 ms |
| 960×540, slice threads (4), 1-frame queue | 30.1 to 30.2 | 26 to 29 ms | −25 to −19 ms |

At 60 fps (slice threads, 120 to 240 frames):

| Stream | Delivered fps | Median delay | Drift over clip |
|---|---:|---:|---:|
| 1280×720 | 24.9 to 30.5 | 573 to 927 ms | +917 to +1656 ms |
| 960×540 | 46.5 to 47.7 | 575 to 706 ms | +1024 to +1159 ms |
| 854×480 | 55.3 to 59.1 | 81 to 245 ms | +58 to +339 ms |
| 640×360 | 60.3 | 13 to 14 ms | −20 to −17 ms |

What this shows:

- Software decoding tops out near 26 to 28 megapixels per second.
- 720p at 30 fps works with slice threading and a leaky one-frame queue after the decoder.
- 720p at 60 fps is not possible in software. Only 640×360 keeps up at 60 fps.
- A small negative drift is a start and finish timing effect. It does not mean negative latency.

These fixtures came from x264 `ultrafast`, which uses CAVLC entropy coding. Real streams usually use CABAC, which costs more to decode. With CABAC (`veryfast`, High profile, full-motion test pattern), software 720p30 to `ximagesink` gave about 22 fps at about 233% CPU. Software decode to `kmssink` on the overlay plane rendered 296 of 300 frames at about 148% CPU. These two numbers are rough, single measurements.

The raw results are in [bench/airplay-benchmark-results.json](../bench/airplay-benchmark-results.json). The benchmark script is [dashboard/src/diagnostics/airplay_benchmark.py](../dashboard/src/diagnostics/airplay_benchmark.py). It makes its own test clips with the installed ffmpeg.

## Hardware H.264 decoding (tegra-vde)

The Tegra 3 has a hardware video decoder, driven by the kernel's `tegra-vde` driver as a V4L2 stateless decoder.

### GStreamer 1.18 cannot use it

The `v4l2slh264dec` in GStreamer 1.18 (Raspberry Pi OS 11) fails with `Failed to open decoder`. It is older than the stable kernel H.264 stateless API. Also, `tegra-vde` gives planar YM12/YM21 frames, and the 1.18 element only offers NV12/YUY2.

### GStreamer 1.26 can

[video/](../video/) cross-builds a small GStreamer 1.26.11 on your PC with the V4L2 stateless decoders and `kmssink`. It uses a Debian 11 container with the armhf cross compiler, which has the same glibc (2.31) and glib (2.66) as Raspberry Pi OS 11. Nothing is compiled on the tablet.

```bash
cd video
./build.sh                                   # installs into out/opt/gst-hw
rsync -a out/opt/gst-hw/ rt:/tmp/gst-hw/ && ssh rt 'sudo rm -rf /opt/gst-hw && sudo mv /tmp/gst-hw /opt/gst-hw'
```

The prefix is part of the build. Install it at the same path, or build with `PREFIX=/your/path ./build.sh`.

Run it with its own libraries and plugins, not the system 1.18:

```bash
P=/opt/gst-hw
export LD_LIBRARY_PATH=$P/lib
export GST_PLUGIN_SYSTEM_PATH=$P/lib/gstreamer-1.0
export GST_PLUGIN_SCANNER=$P/libexec/gstreamer-1.0/gst-plugin-scanner
export GST_REGISTRY=$HOME/.cache/gstreamer-1.0/registry-gst-hw.bin
$P/bin/gst-launch-1.0 filesrc location=clip.mp4 ! qtdemux ! h264parse ! v4l2slh264dec \
    ! kmssink driver-name=tegra skip-vsync=true
```

Results:

- 720p60 decodes at about 110 fps unpaced.
- Paced at 60 fps, it uses about 24% CPU.
- `kmssink` sends the frames zero-copy to a Tegra DRM overlay plane at about 60 fps.

### The limit: no CABAC

The VDE has no CABAC decoder. `tegra-vde` returns `-EOPNOTSUPP` for any picture parameter set with `entropy_coding_mode_flag` set (see `drivers/media/platform/nvidia/tegra-vde/h264.c`). The same 1280×720 clip decodes in hardware as CAVLC and fails as CABAC.

Most encoders use CABAC for Main and High profile. So the hardware decoder only helps when you control the encoder, for example with x264 `--no-cabac` or the Baseline profile. macOS screen mirroring sends CABAC, so AirPlay cannot use it.

## AirPlay mirroring receiver

[UxPlay](https://github.com/FDH2/UxPlay) 1.73.7 turns the tablet into an AirPlay mirroring screen for a Mac or iPhone. We run it with audio off.

### Build it on the tablet

UxPlay is small enough to build on the tablet. Install the build tools and the `-dev` packages from the "Debian-based systems" section of the [UxPlay README](https://github.com/FDH2/UxPlay#debian-based-systems), then:

```bash
git clone --branch v1.73.7 --depth 1 https://github.com/FDH2/UxPlay.git
cd UxPlay && mkdir build && cd build
cmake -DNO_MARCH_NATIVE=ON .. && make -j2 && sudo make install
```

We built with `-DNO_MARCH_NATIVE=ON`. `make -j2` keeps the memory use low enough for the small swap.

### Settings that work

This is the command that the dashboard runs ([dashboard/src/airplay_settings.py](../dashboard/src/airplay_settings.py)):

```bash
LD_HWCAP_MASK=0 uxplay -n "Surface RT" -nh -a -fs -s 1280x720 -fps 30 -d 1 \
    -vd "avdec_h264 thread-type=slice max-threads=4 ! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream" \
    -vc "videoconvert n-threads=2" -vs ximagesink -vsync no -srgb no
```

- `-a` turns audio off.
- `-s 1280x720 -fps 30` asks the sender for 720p at 30 fps. Our Mac negotiated 1280×720 (look for `width_source` in UxPlay's log).
- The decoder uses slice threading with up to four workers. A leaky queue after it keeps at most one decoded frame. Old decoded frames can be dropped, but compressed data is never dropped.
- Conversion uses two threads, and `ximagesink` with `-vsync no` shows each frame at once.

Our first setup used frame threading with four workers and three-frame queues. Compared with it, scrolling and window movement felt noticeably more responsive with these settings. UxPlay used about 1.8 to 1.9 cores (181% to 193% CPU) and 55.8 to 57.3 MiB RSS in a 60-second live session. We did not measure screen-to-screen latency with a camera, and we did not run a 5-minute stability test.

For more CPU headroom, use `960x540`. For sharper text, use `1366x768`, but it fell behind under motion in the benchmark. For 60 fps, only `640x360` keeps up.

To measure latency yourself, open [dashboard/src/diagnostics/latency.html](../dashboard/src/diagnostics/latency.html) on the sender and mirror it. Film both screens together and compare the clocks.

### Our UxPlay patch

[video/uxplay-1.73.7-render-rect.patch](../video/uxplay-1.73.7-render-rect.patch) adds two small features:

- `SIGUSR1` and `SIGUSR2` move or resize the video inside the display, from the variables `UXPLAY_RECT_SIGUSR1` and `UXPLAY_RECT_SIGUSR2` (`x,y,w,h`). If the variable is not set, the video fills the display. The dashboard uses this to uncover its control bar when the video is on a `kmssink` overlay plane.
- `UXPLAY_SKIP_PLUGIN_CHECK=1` skips the startup plugin check. The small GStreamer 1.26 build has no libav or playback plugins, and with audio off UxPlay does not need them.

Apply it before you build:

```bash
cd UxPlay && patch -p1 < /path/to/uxplay-1.73.7-render-rect.patch
```

You only need the patch for the hardware-decoder path. Because of the CABAC limit, the dashboard uses software decoding (`"decoder": "slice"`).
