#!/usr/bin/env python3
"""Synthetic, paced 30/60fps decode/convert benchmark; NOT end-to-end AirPlay latency.

Arguments: frame rates to run (e.g. `60`; default all) and `--profile NAME` (repeatable) to
replace each rate's profile list. Profiles `hw` (decode+convert) and `hw-decode` (decode only)
use the Tegra hardware decoder and re-execute this script under the private GStreamer build.

Run as a transient system unit with LD_HWCAP_MASK=0. JSON results go to stdout.
Fixtures are temporary and generated with the installed ffmpeg, without builds.
"""
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from airplay_settings import DECODERS, FRESH_FRAME_QUEUE, HW_PREFIX, hw_env

RATES = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
PROFILES = [sys.argv[i + 1] for i, arg in enumerate(sys.argv[:-1]) if arg == "--profile"]
if any(p.startswith("hw") for p in PROFILES) and HW_PREFIX not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.execve(sys.executable, [sys.executable, "-u"] + sys.argv, hw_env())

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)
# ffmpeg (fixture generation) must use the system libraries even under the hw environment.
ENV = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
ENV["LD_HWCAP_MASK"] = "0"


def benchmark(fixture, profile):
    if profile == "hw-decode":
        middle = DECODERS["hw"] + " ! " + FRESH_FRAME_QUEUE
    elif profile == "hw":
        middle = DECODERS["hw"] + " ! " + FRESH_FRAME_QUEUE + " ! videoconvert n-threads=2"
    elif profile == "original":
        middle = ("avdec_h264 thread-type=frame max-threads=4 ! queue max-size-buffers=3 ! "
                  "videoconvert n-threads=2 ! queue max-size-buffers=3")
    else:
        middle = DECODERS[profile] + " ! " + FRESH_FRAME_QUEUE + " ! videoconvert n-threads=2"
    pipeline = Gst.parse_launch(
        f'filesrc location="{fixture}" ! qtdemux ! h264parse ! '
        'video/x-h264,alignment=au ! identity name=pacer sync=true ! queue ! ' + middle +
        ('' if profile == "hw-decode" else ' ! videoscale ! video/x-raw,format=BGRx') +
        ' ! fakesink name=output sync=false')
    entered, delays, times, drift = {}, [], [], []
    first_pts = [None]

    def incoming(_pad, info):
        entered[info.get_buffer().pts] = time.monotonic()
        return Gst.PadProbeReturn.OK

    def outgoing(_pad, info):
        now = time.monotonic()
        start = entered.pop(info.get_buffer().pts, None)
        if start is not None:
            delays.append((now - start) * 1000)
        pts = info.get_buffer().pts
        if first_pts[0] is None:
            first_pts[0] = pts
        else:
            drift.append((now - times[0] - (pts - first_pts[0]) / Gst.SECOND) * 1000)
        times.append(now)
        return Gst.PadProbeReturn.OK

    pipeline.get_by_name("pacer").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, incoming)
    pipeline.get_by_name("output").get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, outgoing)
    wall, cpu = time.monotonic(), time.process_time()
    pipeline.set_state(Gst.State.PLAYING)
    try:
        message = pipeline.get_bus().timed_pop_filtered(
            30 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message is None:
            raise RuntimeError("pipeline timed out")
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            raise RuntimeError(f"{error}: {debug}")
        elapsed = time.monotonic() - wall
        ordered = sorted(delays)
        result = {"profile": profile, "frames": len(times),
                  "fps": round((len(times) - 1) / (times[-1] - times[0]), 2),
                  "median_ms": round(statistics.median(delays), 2),
                  "p95_ms": round(ordered[int((len(ordered) - 1) * .95)], 2),
                  "cpu_percent": round(100 * (time.process_time() - cpu) / elapsed, 1),
                  "schedule_drift_ms": round(drift[-1], 2),
                  "last_minus_first_ms": round(statistics.median(delays[-30:]) -
                                               statistics.median(delays[:30]), 2)}
        return result
    finally:
        pipeline.set_state(Gst.State.NULL)


MATRIX = {
    30: (("1366x768", "1280x720", "960x540"), ("original", "slice", "frame2")),
    60: (("1366x768", "1280x720", "960x540", "854x480", "640x360"), ("slice",)),
}


def main():
    rates = RATES or sorted(MATRIX)
    results = []
    with tempfile.TemporaryDirectory(prefix="airplay-bench-") as tmp:
        for rate in rates:
            resolutions, profiles = MATRIX[rate]
            profiles = PROFILES or profiles
            for resolution in resolutions:
                for slices in (1, 4):
                    fixture = Path(tmp) / f"{resolution}-{rate}-{slices}.mp4"
                    subprocess.run([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"testsrc2=size={resolution}:rate={rate}",
                        "-t", "4", "-an", "-c:v", "libx264", "-threads", "1",
                        "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "23",
                        "-x264-params", f"slices={slices}:keyint={rate}", str(fixture)],
                        env=ENV, check=True, timeout=180)
                    frame = subprocess.run([
                        "ffmpeg", "-v", "error", "-i", str(fixture), "-c:v", "copy",
                        "-frames:v", "1", "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"],
                        env=ENV, capture_output=True, check=True, timeout=15).stdout
                    actual_slices = sum(bool(nal) and (nal[0] & 31) in (1, 5)
                                        for nal in re.split(b"\x00\x00\x00?\x01", frame))
                    if actual_slices != slices:
                        raise RuntimeError(f"fixture has {actual_slices} slices, expected {slices}")
                    for profile in profiles:
                        result = dict(resolution=resolution, fps_target=rate, slices=slices,
                                      **benchmark(fixture, profile))
                        results.append(result)
                        print(json.dumps(result), flush=True)
    print(json.dumps({"kind": "synthetic_decode_convert_only", "results": results}), flush=True)


if __name__ == "__main__":
    main()
