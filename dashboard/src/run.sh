#!/bin/sh
# Keeps the dashboard running: restarts it if it exits or crashes.
# After 3 quick crashes in a row it shows the rescue screen (rescue.py) instead;
# leaving that screen tries the dashboard again.
cd "$(dirname "$0")" || exit 1
DASHBOARD=${DASHBOARD:-dashboard.py}  # override only for testing the rescue path
QUICK=30        # seconds: a crash sooner than this counts as "quick"
MAX_CRASHES=3

crashes=0
while true; do
  start=$(date +%s)
  python3 "$DASHBOARD"
  code=$?
  elapsed=$(( $(date +%s) - start ))
  # 143 = SIGTERM (pkill on a redeploy): not a crash.
  if [ "$code" -ne 0 ] && [ "$code" -ne 143 ] && [ "$elapsed" -lt "$QUICK" ]; then
    crashes=$((crashes + 1))
    echo "[run.sh] dashboard exited with $code after ${elapsed}s (quick crash $crashes/$MAX_CRASHES)"
  else
    crashes=0
  fi
  if [ "$crashes" -ge "$MAX_CRASHES" ]; then
    echo "[run.sh] opening the rescue screen"
    python3 rescue.py
    crashes=0
  fi
  sleep 2
done
