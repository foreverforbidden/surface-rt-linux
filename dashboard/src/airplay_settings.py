"""AirPlay command settings shared with the diagnostic tools."""

import os

DECODERS = {
    "slice": "avdec_h264 thread-type=slice max-threads=4",
    "frame2": "avdec_h264 thread-type=frame max-threads=2",
    # Tegra 3 hardware decoder (tegra-vde, /dev/media1). Needs the private GStreamer in HW_PREFIX.
    "hw": "v4l2slh264dec",
}
FRESH_FRAME_QUEUE = "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream"

# Private GStreamer 1.26 build (third_party/gst-hw); the system 1.18 cannot drive tegra-vde.
HW_PREFIX = os.environ.get("GST_HW_PREFIX", "/opt/gst-hw")


def hw_env(base=None):
    """Environment that makes a GStreamer program use HW_PREFIX instead of the system 1.18."""
    env = dict(os.environ if base is None else base)
    lib = HW_PREFIX + "/lib"
    env["LD_LIBRARY_PATH"] = ":".join(filter(None, [lib, env.get("LD_LIBRARY_PATH")]))
    env["GST_PLUGIN_SYSTEM_PATH"] = lib + "/gstreamer-1.0"
    env["GST_PLUGIN_SCANNER"] = HW_PREFIX + "/libexec/gstreamer-1.0/gst-plugin-scanner"
    env["GST_REGISTRY"] = os.path.expanduser("~/.cache/gstreamer-1.0/registry-gst-hw.bin")
    env.pop("GST_PLUGIN_PATH", None)
    return env


HW_UXPLAY = HW_PREFIX + "/bin/uxplay"  # UxPlay with the SIGUSR1/2 render-rectangle patch
SYSTEM_UXPLAY = "/usr/local/bin/uxplay"
# Hardware frames go straight to a Tegra DRM overlay plane above X (no CPU conversion or copy).
# skip-vsync: Tegra latches plane updates at vblank anyway; waiting again halves the rate to 30.
HW_SINK = "kmssink driver-name=tegra skip-vsync=true"


def decoder_name(config):
    decoder = config.get("decoder", "slice")
    if decoder not in ("slice", "hw"):
        raise ValueError('airplay.decoder must be "slice" or "hw"')
    return decoder


def receiver_executable(config):
    return HW_UXPLAY if decoder_name(config) == "hw" else SYSTEM_UXPLAY


def receiver_env(config, base=None, controls_rect=None):
    """Environment for uxplay. With the hw decoder, SIGUSR1 moves the video to controls_rect
    (x, y, w, h) so the control bar shows; SIGUSR2 restores the full display."""
    env = dict(os.environ if base is None else base)
    # Raspberry Pi OS's /lib/.../neon/vfp/ libavcodec uses sdiv, which the Cortex-A9 lacks.
    env["LD_HWCAP_MASK"] = "0"
    if decoder_name(config) == "hw":
        env = hw_env(env)
        env["UXPLAY_SKIP_PLUGIN_CHECK"] = "1"  # patched uxplay: audio-only plugins aren't built
        if controls_rect:
            env["UXPLAY_RECT_SIGUSR1"] = ",".join(str(int(v)) for v in controls_rect)
        env.pop("UXPLAY_RECT_SIGUSR2", None)
    return env


def receiver_args(executable, config):
    resolution = str(config.get("resolution", "1366x768"))
    import re
    if not re.fullmatch(r"[1-9][0-9]{1,3}x[1-9][0-9]{1,3}", resolution):
        raise ValueError("airplay.resolution must be WIDTHxHEIGHT")
    fps = config.get("fps", 30)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        raise ValueError("airplay.fps must be an integer from 1 to 60")
    extra = config.get("args", [])
    if not isinstance(extra, list) or not all(isinstance(arg, str) for arg in extra):
        raise ValueError("airplay.args must be a list of strings")
    args = [executable, "-n", str(config.get("name", "Surface RT")), "-nh", "-a"]
    if decoder_name(config) == "hw":
        # No -fs: with kmssink UxPlay would add force-modesetting, taking the whole CRTC from X
        # (and the control bar with it). No leaky queue: it stalls the decoder's dmabuf pool.
        args += ["-s", resolution, "-fps", str(fps), "-d", "1",
                 "-vd", DECODERS["hw"], "-vc", "identity", "-vs", HW_SINK]
    else:
        args += ["-fs", "-s", resolution, "-fps", str(fps), "-d", "1",
                 "-vd", DECODERS["slice"] + " ! " + FRESH_FRAME_QUEUE,
                 "-vc", "videoconvert n-threads=2", "-vs", "ximagesink"]
    return args + ["-vsync", "no", "-srgb", "no"] + extra
