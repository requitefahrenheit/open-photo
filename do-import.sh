#!/bin/bash
set -e
LOG=/home/jfischer/claude/open-photo/import.log
exec >> $LOG 2>&1
echo "[$(date)] Starting import"

# Pause cron watchdog
crontab -l > /tmp/crontab.bak
crontab -l | grep -v op-server | crontab -
echo "[$(date)] Cron paused"

# Kill server
pkill -f op-server.py || true
sleep 4
echo "[$(date)] Server stopped"

cd /home/jfischer/claude/open-photo

# Drop table so dump's CREATE TABLE takes effect with correct schema
sqlite3 op.db 'DROP TABLE IF EXISTS media'
echo "[$(date)] Table dropped"

# Import
sqlite3 op.db < op-media.sql
echo "[$(date)] Import done"
sqlite3 op.db 'PRAGMA integrity_check; SELECT COUNT(*), COUNT(clip_embedding), COUNT(thumbnail_path) FROM media;'

# Restore cron
crontab /tmp/crontab.bak
echo "[$(date)] Cron restored"

# Restart server
PYTHONPATH='' /home/jfischer/miniconda3/envs/agent/bin/python3 -u op-server.py >> server.log 2>&1 &
echo "[$(date)] Server restarted PID $!"
