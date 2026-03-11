import sqlite3, struct

conn = sqlite3.connect('/home/jfischer/claude/open-photo/op_new.db')
conn.executescript(open('/home/jfischer/claude/open-photo/rebuild_db.py').read().split('EOF')[0])  # placeholder
