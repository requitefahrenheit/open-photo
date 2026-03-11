#!/bin/bash
# sync-from-gpu.sh — Pull op.db and uploads from GPU machine after ingest
set -e
GPU=ec2-user@172.18.71.210
LOCAL_DB=~/claude/open-photo/op.db
LOCAL_UPLOADS=~/claude/open-photo/uploads/

echo "=== $(date) Syncing DB ==="
rsync -avz --progress $GPU:~/op.db $LOCAL_DB

echo "=== $(date) Syncing uploads ==="
rsync -avz --progress $GPU:~/uploads/ $LOCAL_UPLOADS

echo "=== $(date) Restarting op-server ==="
pkill -f op-server.py || true

echo "=== $(date) Done. Cron will restart server within 60s ==="
