#!/usr/bin/env python3
"""Observe an existing receiver for five minutes without altering its pipeline.

Reports CPU/RSS, process continuity and new errors. Does not measure fps,
decoded-frame backlog, or screen-to-screen latency.
"""
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time


def state(pid):
    # comm is parenthesized and may contain spaces; fields after it start at 3.
    data = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"ticks": int(data[11]) + int(data[12]), "started": int(data[19]),
            "rss_kib": int(data[21]) * os.sysconf("SC_PAGE_SIZE") // 1024}


def main():
    found = subprocess.run(["pgrep", "-x", "uxplay"], capture_output=True, text=True, check=True)
    pids = found.stdout.split()
    if len(pids) != 1:
        raise RuntimeError(f"expected one receiver, found {len(pids)}")
    pid = int(pids[0])
    start = previous_time = time.monotonic()
    previous = state(pid)
    start_ticks = previous["started"]
    clock_ticks = os.sysconf("SC_CLK_TCK")
    samples, errors = [], []
    log = Path.home() / "app.log"
    offset = log.stat().st_size
    latest = log.read_text(errors="replace")[-65536:]
    resolutions = re.findall(r"width_source = ([0-9.]+) height_source = ([0-9.]+)", latest)
    resolution = resolutions[-1] if resolutions else None
    ended = "completed"
    for _ in range(30):
        time.sleep(10)
        now = time.monotonic()
        try:
            current = state(pid)
        except FileNotFoundError:
            ended = "receiver_exited"
            break
        if current["started"] != start_ticks:
            ended = "receiver_replaced"
            break
        sample = {"elapsed_s": round(now - start, 1), "rss_kib": current["rss_kib"],
                  "cpu_percent": round(100 * (current["ticks"] - previous["ticks"]) /
                                       clock_ticks / (now - previous_time), 1)}
        samples.append(sample)
        print(json.dumps(sample), flush=True)
        previous, previous_time = current, now
        with log.open() as stream:
            if log.stat().st_size < offset:
                offset = 0
            stream.seek(offset)
            new_lines = stream.read().splitlines()
            offset = stream.tell()
        errors.extend(line for line in new_lines if re.search(r"ERROR|error|touch controls failed", line))
    result = {"kind": "live_process_observation", "pid": pid, "outcome": ended,
              "observed_s": round(time.monotonic() - start, 1), "resolution": resolution,
              "samples": samples, "errors": errors}
    if samples:
        result.update(cpu_median_percent=statistics.median(s["cpu_percent"] for s in samples),
                      cpu_max_percent=max(s["cpu_percent"] for s in samples),
                      rss_min_kib=min(s["rss_kib"] for s in samples),
                      rss_max_kib=max(s["rss_kib"] for s in samples))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
