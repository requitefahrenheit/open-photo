#!/bin/bash
# Watchdog for op-server.py — restarts on crash, logs to watchdog.log
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/watchdog.log"
PYTHON=/home/jfischer/miniconda3/envs/agent/bin/python3
PORT=8260

echo "[$(date)] Watchdog started" >> "$LOG"

while true; do
  # Check if already running
  if pgrep -f op-server.py > /dev/null; then
    sleep 15
    continue
  fi

  echo "[$(date)] op-server.py not running — starting" >> "$LOG"
  cd "$SCRIPT_DIR"
  PYTHONPATH='' $PYTHON -u op-server.py >> server.log 2>&1 &
  sleep 5

  # Verify it actually came up
  if curl -sf http://localhost:$PORT/ > /dev/null 2>&1; then
    echo "[$(date)] Server up on :$PORT" >> "$LOG"
  else
    echo "[$(date)] WARNING: server may not have started — check server.log" >> "$LOG"
  fi
done
