#!/usr/bin/env python3
import sqlite3, os, uuid, random
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw

DB = Path('/home/jfischer/claude/open-photo/op.db')
UPLOADS = Path('/home/jfischer/claude/open-photo/uploads')
UPLOADS.mkdir(exist_ok=True)

DIM = 512

CLUSTERS = [
    ('beach vacation',     (70,130,200), ['waves on sandy shore','sunset over ocean','kids in surf','beach umbrella','seagulls over water','sandcastle','snorkeling','palm trees','beach bonfire','colorful towels'], 2018),
    ('family dinner',      (210,120,60), ['holiday dinner table','grandmother serving turkey','birthday cake','gathered around table','passing dishes','dessert and coffee','wine glasses toast','kitchen chaos','kids table','board games'], 2019),
    ('mountain hiking',    (80,160,80),  ['pine forest trail','summit above clouds','mountain stream','rocky ridge','wildflowers on path','rest stop','panoramic vista','fog in valley','campsite','sunrise from peak'], 2015),
    ('city streets',       (160,80,160), ['busy intersection','street food cart','graffiti wall','taxi in traffic','outdoor cafe','night rain reflections','subway entrance','historic building','park bench','bicycle by lamppost'], 2017),
    ('childrens birthday', (230,200,50), ['blowing out candles','balloon decorations','kids in backyard','opening presents','tiger face paint','pin the tail','pinata candy','birthday crown','cake on face','party hats'], 2020),
    ('winter snow',        (180,200,230),['snowman in yard','sledding down hill','frozen lake','snowball fight','icicles on roof','cross country skiing','snow covered pines','footprints in snow','hot chocolate','kids in snow gear'], 2016),
    ('dogs and pets',      (200,150,90), ['retriever at park','puppy with toy','cat in sunbeam','dog catching frisbee','dogs on beach','pet portrait','kitten with yarn','dog swimming','hamster in wheel','dog on trail'], 2021),
    ('garden flowers',     (230,130,160),['rose garden blooming','bees on lavender','vegetable garden','sunflowers in light','herb garden pots','cherry blossoms','butterfly on flower','watering garden','flower market','autumn blooms'], 2014),
]

rng = np.random.default_rng(42)
centroids = []
for _ in CLUSTERS:
    c = rng.standard_normal(DIM).astype(np.float32); c /= np.linalg.norm(c); centroids.append(c)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('DELETE FROM media')
conn.execute('UPDATE media SET layout_x=NULL, layout_y=NULL WHERE 1=0')
conn.commit()

inserted = 0
for ci, (name, color, captions, year) in enumerate(CLUSTERS):
    cen = centroids[ci]
    for i, cap in enumerate(captions):
        mid = str(uuid.uuid4())
        img = Image.new('RGB', (256,256), color)
        ImageDraw.Draw(img).rectangle([8,8,247,247], outline=tuple(max(0,c-60) for c in color), width=2)
        fname = f'{mid[:8]}.jpg'; img.save(UPLOADS/fname, 'JPEG', quality=85)
        v = cen + rng.standard_normal(DIM).astype(np.float32)*0.2; v/=np.linalg.norm(v)
        taken = f'{year}:{random.randint(1,12):02d}:{random.randint(1,28):02d} 12:00:00'
        conn.execute('INSERT INTO media (id,media_type,original_filename,file_hash,label,caption,thumbnail_path,taken_at,clip_embedding,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (mid,'image',f'{name}_{i}.jpg',mid,cap,f'A photo of {cap} from the {name} collection.',fname,taken,v.tobytes(),'inbox',datetime.now().isoformat(),datetime.now().isoformat()))
        inserted += 1

conn.commit(); conn.close()
print(f'Seeded {inserted} photos across {len(CLUSTERS)} clusters')
