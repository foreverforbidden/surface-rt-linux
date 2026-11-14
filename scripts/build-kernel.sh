#!/bin/sh
# Build the Surface RT kernel with this repo's overlay, on a Mac or Linux PC with Docker.
# Usage: scripts/build-kernel.sh [OUT_DIR]        (default: out/)
# On a Mac, start Colima first: colima start --cpu 8 --memory 8 --disk 20
set -eu

REPO_URL=https://github.com/nuno407/linux-surface-rt.git
PIN=6468f0b907c50c071fba54232191e149ff70529a   # reviewed commit: Linux 7.2.13, 45 patches

TOP=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-$TOP/out}
SRC=$TOP/build/linux-surface-rt

command -v docker >/dev/null || { echo "docker not found (on a Mac: brew install colima docker)" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker is not running (on a Mac: colima start)" >&2; exit 1; }

if [ ! -d "$SRC/.git" ]; then
	mkdir -p "$TOP/build"
	git clone "$REPO_URL" "$SRC"
fi
git -C "$SRC" fetch -q origin "$PIN" 2>/dev/null || true
git -C "$SRC" checkout -q "$PIN"
[ "$(git -C "$SRC" rev-parse HEAD)" = "$PIN" ] || { echo "could not check out $PIN" >&2; exit 1; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
cd "$SRC"
OVERLAY="$TOP/kernel/overlay" ./build.sh surface-rt "$OUT"

echo
echo "Artifacts in $OUT:"
ls -l "$OUT"
(cd "$OUT" && shasum -a 256 -c SHA256SUMS)
