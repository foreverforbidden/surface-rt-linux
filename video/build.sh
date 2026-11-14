#!/bin/sh
# Cross-build GStreamer with hardware H.264 decode for the Surface RT, on the Mac (Colima running).
# Output: out$PREFIX (default out/opt/gst-hw)  ->  copy to the same path on the tablet
set -eu
cd "$(dirname "$0")"
docker build -t gst-hw-build .
docker run --rm -e PREFIX="${PREFIX:-/opt/gst-hw}" -v "$PWD":/work gst-hw-build sh /work/inner.sh
