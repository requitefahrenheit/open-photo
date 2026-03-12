#!/usr/bin/env python3
"""
op-ingest.py — Open Photo bulk ingest pipeline

Patches applied vs original:
  1. HEIC support via pillow-heif (register_heif_opener)
  2. Sidecar matching handles truncated Google Takeout filenames
  3. Caption requests parallelized with ThreadPoolExecutor (CAPTION_WORKERS=8)
"""

import argparse
import base64
import hashlib
import httpx
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from threading import Lock

import numpy as np
from PIL import Image, ExifTags
from tqdm import tqdm

# HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIC_SUPPORTED = True
except ImportError:
    _HEIC_SUPPORTED = False

PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.tiff', '.tif', '.bmp', '.gif'}
VIDEO_EXTS  = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.wmv'}
THUMB_SIZE  = 512
CLIP_BATCH  = 64
FACE_CONF   = 0.85
CLUSTER_MIN = 3
CLUSTER_EPS = 0.4
COSINE_LINK = 0.45
TOP_K_LINKS = 5
CAPTION_WORKERS = 8

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY, media_type TEXT NOT NULL, original_path TEXT,
    original_filename TEXT, file_hash TEXT UNIQUE NOT NULL, label TEXT,
    caption TEXT, ocr_text TEXT, clip_embedding BLOB, thumbnail_path TEXT,
    taken_at TEXT, geo_lat REAL, geo_lon REAL, geo_name TEXT, album TEXT,
    people_tags TEXT, description_src TEXT, camera_make TEXT, camera_model TEXT,
    width INTEGER, height INTEGER, duration_s REAL,
    status TEXT DEFAULT 'inbox', temperature REAL DEFAULT 1.5,
    visit_count INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS faces (
    id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    bbox_x INTEGER, bbox_y INTEGER, bbox_w INTEGER, bbox_h INTEGER,
    confidence REAL, embedding BLOB, cluster_id TEXT REFERENCES face_clusters(id),
    is_noise INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS face_clusters (
    id TEXT PRIMARY KEY, anonymous_label TEXT, person_name TEXT,
    cover_face_id TEXT, face_count INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    weight REAL, label TEXT DEFAULT 'similar', auto_created INTEGER DEFAULT 1,
    UNIQUE(source_id, target_id)
);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
    color TEXT DEFAULT '#6ee7b7', created_at TEXT
);
CREATE TABLE IF NOT EXISTS collection_media (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, media_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    id UNINDEXED, label, caption, ocr_text, album, people_tags, geo_name, description_src,
    content=media, content_rowid=rowid
);
CREATE INDEX IF NOT EXISTS idx_media_taken  ON media(taken_at);
CREATE INDEX IF NOT EXISTS idx_media_album  ON media(album);
CREATE INDEX IF NOT EXISTS idx_media_hash   ON media(file_hash);
CREATE INDEX IF NOT EXISTS idx_faces_media  ON faces(media_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
"""

def init_db(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def new_id(): return uuid.uuid4().hex[:12]
def now_iso(): return datetime.now(timezone.utc).isoformat()


def find_sidecar(media_path):
    """
    Find Google Takeout sidecar JSON for a media file.

    Google Takeout uses several naming schemes:
      1. photo.jpg.supplemental-metadata.json          (standard)
      2. photo.jpg.json                                (short form)
      3. photo.supplemental-metadata.json              (extension stripped)
      4. Truncated: when the base name is long, Google truncates it to ~46 chars
         before appending the suffix, e.g.:
           RequiteFahrenheit_sultry_ravishing_stunning_eu(8).json
         These standalone .json files sit next to the image with no image extension
         in the sidecar name.
      5. Dedup suffix: photo(1).jpg has photo(1).jpg.supplemental-metadata.json
         OR photo.jpg.supplemental-metadata(1).json
    """
    name = media_path.name
    stem = media_path.stem
    suffix = media_path.suffix
    parent = media_path.parent

    candidates = [
        # Standard
        parent / (name + '.supplemental-metadata.json'),
        parent / (name + '.json'),
        # Extension stripped
        parent / (stem + '.supplemental-metadata.json'),
        parent / (stem + '.json'),
        # Truncated stem (46 chars) + original suffix + .supplemental-metadata.json
        parent / (stem[:46] + suffix + '.supplemental-metadata.json'),
        parent / (stem[:46] + '.supplemental-metadata.json'),
    ]

    for c in candidates:
        if c.exists():
            return c

    # Fuzzy fallback: find any .json in same dir whose stem starts with
    # the first 20 chars of our stem (catches heavy truncation)
    prefix = stem[:20].lower()
    try:
        for f in parent.iterdir():
            if f.suffix == '.json' and f.stem.lower().startswith(prefix):
                return f
    except Exception:
        pass

    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''): h.update(chunk)
    return h.hexdigest()

def discover(takeout_path, conn, dry_run):
    known_hashes = set(r[0] for r in conn.execute('SELECT file_hash FROM media'))
    items = []
    skipped = 0
    heic_skipped = 0
    all_files = list(takeout_path.rglob('*'))
    media_files = [f for f in all_files if f.is_file() and f.suffix.lower() in PHOTO_EXTS | VIDEO_EXTS]

    # Warn if HEIC present but unsupported
    heic_count = sum(1 for f in media_files if f.suffix.lower() == '.heic')
    if heic_count and not _HEIC_SUPPORTED:
        print(f"  ⚠️  {heic_count:,} HEIC files found but pillow-heif not installed — they will be skipped")
        print(f"     Install with: pip install pillow-heif")

    print(f"\n📁 Discovery: found {len(media_files):,} media files")
    for path in tqdm(media_files, desc='Hashing', unit='file'):
        if path.suffix.lower() == '.heic' and not _HEIC_SUPPORTED:
            heic_skipped += 1
            continue
        try:
            h = sha256(path)
            if h in known_hashes:
                skipped += 1
                continue
            sidecar = find_sidecar(path)
            items.append((path, sidecar, h))
            known_hashes.add(h)
        except Exception as e:
            print(f"  ⚠️  {path.name}: {e}")
    print(f"  ✓ {len(items):,} new items, {skipped:,} already in DB"
          + (f", {heic_skipped:,} HEIC skipped (no pillow-heif)" if heic_skipped else ""))
    if dry_run:
        print("\n  [dry-run] Stopping here.")
        sys.exit(0)
    return items

def parse_sidecar(sidecar_path):
    if not sidecar_path: return {}
    try:
        with open(sidecar_path) as f: data = json.load(f)
        result = {}
        ts = data.get('photoTakenTime') or data.get('creationTime')
        if ts and ts.get('timestamp'):
            try:
                result['taken_at'] = datetime.fromtimestamp(int(ts['timestamp']), tz=timezone.utc).isoformat()
            except: pass
        geo = data.get('geoData') or data.get('geoDataExif')
        if geo and geo.get('latitude') and geo.get('latitude') != 0.0:
            result['geo_lat'] = geo['latitude']
            result['geo_lon'] = geo['longitude']
        people = [p['name'] for p in data.get('people', []) if p.get('name')]
        if people: result['people_tags'] = json.dumps(people)
        if data.get('description'): result['description_src'] = data['description']
        return result
    except: return {}

def parse_exif(path):
    result = {}
    try:
        img = Image.open(path)
        result['width'], result['height'] = img.size
        exif_data = img._getexif()
        if not exif_data: return result
        exif = {ExifTags.TAGS.get(k, k): v for k, v in exif_data.items()}
        for key in ('DateTimeOriginal', 'DateTimeDigitized', 'DateTime'):
            if key in exif:
                try:
                    dt = datetime.strptime(str(exif[key]), '%Y:%m:%d %H:%M:%S')
                    result['taken_at'] = dt.replace(tzinfo=timezone.utc).isoformat()
                    break
                except: pass
        gps_info = exif.get('GPSInfo')
        if gps_info:
            try:
                def to_degrees(vals):
                    d, m, s = vals
                    return float(d) + float(m)/60 + float(s)/3600
                lat = to_degrees(gps_info.get(2, [0,0,0]))
                lon = to_degrees(gps_info.get(4, [0,0,0]))
                if gps_info.get(1) == 'S': lat = -lat
                if gps_info.get(3) == 'W': lon = -lon
                if lat != 0 and lon != 0:
                    result['geo_lat'] = lat
                    result['geo_lon'] = lon
            except: pass
        if 'Make' in exif: result['camera_make'] = str(exif['Make']).strip('\x00')
        if 'Model' in exif: result['camera_model'] = str(exif['Model']).strip('\x00')
    except: pass
    return result

def extract_metadata(path, sidecar, file_hash):
    is_video = path.suffix.lower() in VIDEO_EXTS
    meta = {
        'id': new_id(), 'media_type': 'video' if is_video else 'photo',
        'original_path': str(path), 'original_filename': path.name,
        'file_hash': file_hash, 'label': path.stem,
        'album': path.parent.name, 'created_at': now_iso(), 'updated_at': now_iso(),
    }
    meta.update(parse_sidecar(sidecar))
    if not is_video:
        for k, v in parse_exif(path).items():
            if k not in meta or not meta.get(k): meta[k] = v
    if is_video:
        try:
            import subprocess
            r = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(path)],
                capture_output=True, text=True, timeout=30)
            info = json.loads(r.stdout)
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    meta['width'] = stream.get('width')
                    meta['height'] = stream.get('height')
                    meta['duration_s'] = float(stream.get('duration', 0) or 0)
                    break
        except: pass
    return meta

def make_thumbnail(path, uploads_dir, media_id, is_video):
    thumb_name = f"thumb_{media_id}.jpg"
    thumb_path = uploads_dir / thumb_name
    if thumb_path.exists(): return thumb_name
    try:
        if is_video:
            import subprocess
            r = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                capture_output=True, text=True, timeout=30)
            duration = float(r.stdout.strip() or 0)
            seek = max(0, duration * 0.1)
            subprocess.run(['ffmpeg', '-ss', str(seek), '-i', str(path),
                '-vframes', '1', '-q:v', '3', str(thumb_path), '-y'],
                capture_output=True, timeout=60)
        else:
            img = Image.open(path).convert('RGB')
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            img.save(thumb_path, 'JPEG', quality=85)
        return thumb_name if thumb_path.exists() else None
    except Exception as e:
        print(f"  ⚠️  Thumbnail failed for {path.name}: {e}")
        return None

def load_clip():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
    model.eval()
    try:
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model = model.to(device)
    except ImportError:
        device = 'cpu'
    print(f"  CLIP loaded on {device}")
    return model, preprocess, device

def clip_embed_batch(paths, model, preprocess, device):
    import torch
    results = [None] * len(paths)
    valid_indices = []
    tensors = []
    for i, path in enumerate(paths):
        try:
            img = Image.open(path).convert('RGB')
            tensors.append(preprocess(img))
            valid_indices.append(i)
        except: pass
    if not tensors: return results
    try:
        batch = torch.stack(tensors).to(device)
        with torch.no_grad():
            embeddings = model.encode_image(batch)
            embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
            embeddings = embeddings.cpu().float().numpy()
        for idx, emb in zip(valid_indices, embeddings):
            results[idx] = emb
    except Exception as e:
        print(f"  ⚠️  CLIP batch failed: {e}")
    return results


CAPTION_PROMPT = (
    "You are describing a personal photo for a private memory archive. "
    "Write 4-6 vivid sentences covering: the people present (approximate ages, expressions, relationships if apparent), "
    "what is happening and the mood or energy of the moment, "
    "the setting (specific location type, indoor/outdoor, recognizable places or landmarks), "
    "the era or decade this appears to be from (clothing, technology, decor), "
    "lighting and time of day, any visible text, signs, or objects of note. "
    "Write as if helping someone remember this moment years later. "
    "Be specific and concrete. Do not start with 'This photo', 'The image', or 'In this photo'."
)

# Thread-local http clients for parallel captioning
_caption_lock = Lock()

def _make_http_client():
    return httpx.Client(timeout=60)


def get_caption(path, openai_key, client=None):
    if not openai_key: return None
    if client is None:
        client = _make_http_client()
    try:
        with open(path, 'rb') as f: img_b64 = base64.b64encode(f.read()).decode()
        ext = path.suffix.lower()
        media_type = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png',
                      '.webp':'image/webp','.gif':'image/gif',
                      '.heic':'image/heic'}.get(ext, 'image/jpeg')
        resp = client.post('https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {openai_key}', 'Content-Type': 'application/json'},
            json={'model': 'gpt-4o', 'max_tokens': 600, 'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:{media_type};base64,{img_b64}', 'detail': 'low'}},
                {'type': 'text', 'text': CAPTION_PROMPT},
            ]}]})
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return None


def get_captions_parallel(paths_and_ids, openai_key, workers=CAPTION_WORKERS):
    """
    Fetch captions for a batch of (path, media_id) tuples in parallel.
    Returns dict: {media_id: caption_or_None}
    """
    results = {}
    if not openai_key or not paths_and_ids:
        return {mid: None for _, mid in paths_and_ids}

    def _fetch(item):
        path, media_id = item
        client = _make_http_client()
        caption = get_caption(path, openai_key, client)
        return media_id, caption

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch, item): item for item in paths_and_ids}
        for future in as_completed(futures):
            try:
                media_id, caption = future.result()
                results[media_id] = caption
            except Exception:
                _, media_id = futures[future]
                results[media_id] = None
    return results


def load_face_models():
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name='buffalo_sc', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(640, 640))
        print("  InsightFace (buffalo_sc) loaded")
        return app
    except Exception as e:
        print(f"  ⚠️  InsightFace failed: {e}")
        return None

def detect_faces(path, face_app, media_id):
    if face_app is None: return []
    try:
        import cv2
        img = cv2.imread(str(path))
        if img is None: return []
        faces = face_app.get(img)
        results = []
        for face in faces:
            if face.det_score < FACE_CONF: continue
            bbox = face.bbox.astype(int)
            x, y, x2, y2 = bbox
            results.append({'id': new_id(), 'media_id': media_id,
                'bbox_x': int(x), 'bbox_y': int(y), 'bbox_w': int(x2-x), 'bbox_h': int(y2-y),
                'confidence': float(face.det_score),
                'embedding': face.embedding.astype(np.float32).tobytes(),
                'cluster_id': None, 'is_noise': 0})
        return results
    except: return []

def insert_batch(conn, records, faces_batch):
    media_rows = []
    face_rows = []
    for rec, faces in zip(records, faces_batch):
        media_rows.append((
            rec.get('id'), rec.get('media_type'), rec.get('original_path'),
            rec.get('original_filename'), rec.get('file_hash'),
            rec.get('label'), rec.get('caption'), rec.get('ocr_text'),
            rec.get('clip_embedding'), rec.get('thumbnail_path'),
            rec.get('taken_at'), rec.get('geo_lat'), rec.get('geo_lon'),
            rec.get('geo_name'), rec.get('album'), rec.get('people_tags'),
            rec.get('description_src'), rec.get('camera_make'), rec.get('camera_model'),
            rec.get('width'), rec.get('height'), rec.get('duration_s'),
            'inbox', 1.5, 0, rec.get('created_at'), rec.get('updated_at'),
        ))
        for face in faces:
            face_rows.append((face['id'], face['media_id'], face['bbox_x'], face['bbox_y'],
                face['bbox_w'], face['bbox_h'], face['confidence'],
                face['embedding'], face['cluster_id'], face['is_noise']))
    conn.executemany("""INSERT OR IGNORE INTO media
        (id,media_type,original_path,original_filename,file_hash,label,caption,ocr_text,
         clip_embedding,thumbnail_path,taken_at,geo_lat,geo_lon,geo_name,album,people_tags,
         description_src,camera_make,camera_model,width,height,duration_s,
         status,temperature,visit_count,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", media_rows)
    if face_rows:
        conn.executemany("""INSERT OR IGNORE INTO faces
            (id,media_id,bbox_x,bbox_y,bbox_w,bbox_h,confidence,embedding,cluster_id,is_noise)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", face_rows)
    conn.commit()

def build_auto_links(conn):
    print("\n🔗 Building CLIP similarity edges...")
    rows = conn.execute('SELECT id, clip_embedding FROM media WHERE clip_embedding IS NOT NULL').fetchall()
    if len(rows) < 2:
        print("  Not enough embedded media to link.")
        return
    ids = [r[0] for r in rows]
    embs = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / np.maximum(norms, 1e-8)
    batch = 500
    edges = []
    for i in tqdm(range(0, len(ids), batch), desc='Linking', unit='batch'):
        chunk = embs[i:i+batch]
        sims = chunk @ embs.T
        for j, row in enumerate(sims):
            global_i = i + j
            row[global_i] = -1
            top_k = np.argpartition(row, -TOP_K_LINKS)[-TOP_K_LINKS:]
            for k in top_k:
                if row[k] >= COSINE_LINK:
                    src, tgt = ids[global_i], ids[k]
                    if src < tgt:
                        edges.append((new_id(), src, tgt, float(row[k]), 'similar', 1))
    conn.executemany("INSERT OR IGNORE INTO edges (id,source_id,target_id,weight,label,auto_created) VALUES (?,?,?,?,?,?)", edges)
    albums = conn.execute('SELECT album, GROUP_CONCAT(id) FROM media WHERE album IS NOT NULL GROUP BY album').fetchall()
    album_edges = []
    for album, ids_str in albums:
        album_ids = ids_str.split(',')
        if len(album_ids) > 50: continue
        for a in album_ids:
            for b in album_ids:
                if a < b:
                    album_edges.append((new_id(), a, b, 0.6, 'same_album', 1))
    conn.executemany("INSERT OR IGNORE INTO edges (id,source_id,target_id,weight,label,auto_created) VALUES (?,?,?,?,?,?)", album_edges)
    conn.commit()
    edge_count = conn.execute('SELECT COUNT(*) FROM edges').fetchone()[0]
    print(f"  ✓ {edge_count:,} total edges")

def cluster_faces(conn):
    print("\n👥 Clustering faces with HDBSCAN...")
    rows = conn.execute('SELECT id, media_id, embedding FROM faces WHERE embedding IS NOT NULL').fetchall()
    if not rows:
        print("  No faces to cluster.")
        return
    face_ids = [r[0] for r in rows]
    media_ids = [r[1] for r in rows]
    embeddings = np.array([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-8)
    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(min_cluster_size=CLUSTER_MIN,
            cluster_selection_epsilon=CLUSTER_EPS, metric='euclidean',
            cluster_selection_method='eom')
        labels = clusterer.fit_predict(embeddings)
    except ImportError:
        print("  ⚠️  hdbscan not installed")
        return
    unique_labels = set(labels)
    noise_count = sum(1 for l in labels if l == -1)
    cluster_count = len(unique_labels) - (1 if -1 in unique_labels else 0)
    print(f"  Found {cluster_count:,} clusters, {noise_count:,} noise faces")
    cluster_map = {}
    for label in sorted(unique_labels):
        if label == -1: continue
        cluster_id = new_id()
        cluster_map[label] = cluster_id
        face_count = sum(1 for l in labels if l == label)
        conn.execute("INSERT OR IGNORE INTO face_clusters (id,anonymous_label,face_count,created_at) VALUES (?,?,?,?)",
            (cluster_id, f"Person {label+1}", face_count, now_iso()))
    conn.commit()
    updates = []
    for face_id, label in zip(face_ids, labels):
        if label == -1: updates.append((None, 1, face_id))
        else: updates.append((cluster_map[label], 0, face_id))
    conn.executemany('UPDATE faces SET cluster_id=?, is_noise=? WHERE id=?', updates)
    for label, cluster_id in cluster_map.items():
        indices = [i for i, l in enumerate(labels) if l == label]
        best = max(indices, key=lambda i: conn.execute('SELECT confidence FROM faces WHERE id=?', (face_ids[i],)).fetchone()[0])
        conn.execute('UPDATE face_clusters SET cover_face_id=? WHERE id=?', (face_ids[best], cluster_id))
    person_edges = []
    for label, cluster_id in cluster_map.items():
        indices = [i for i, l in enumerate(labels) if l == label]
        mids = list(set(media_ids[i] for i in indices))
        if len(mids) < 2: continue
        for a in range(len(mids)):
            for b in range(a+1, min(a+20, len(mids))):
                person_edges.append((new_id(), mids[a], mids[b], 0.7, 'same_person', 1))
    conn.executemany("INSERT OR IGNORE INTO edges (id,source_id,target_id,weight,label,auto_created) VALUES (?,?,?,?,?,?)", person_edges)
    conn.commit()
    print(f"  ✓ Clustering complete. {cluster_count:,} clusters.")

def rebuild_fts(conn):
    print("\n📝 Rebuilding FTS index...")
    conn.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild')")
    conn.commit()
    print("  ✓ FTS index ready")

def main():
    parser = argparse.ArgumentParser(description='Open Photo ingest pipeline')
    parser.add_argument('--takeout', type=Path)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--uploads', type=Path)
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--incremental', action='store_true')
    parser.add_argument('--cluster-only', action='store_true')
    parser.add_argument('--openai-key', type=str, default=os.environ.get('OPENAI_API_KEY'))
    parser.add_argument('--no-captions', action='store_true')
    parser.add_argument('--no-faces', action='store_true')
    parser.add_argument('--caption-workers', type=int, default=CAPTION_WORKERS,
                        help=f'Parallel caption threads (default: {CAPTION_WORKERS})')
    args = parser.parse_args()

    if not _HEIC_SUPPORTED:
        print("  ⚠️  pillow-heif not installed. HEIC files will be skipped.")
        print("     pip install pillow-heif")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(str(args.db))

    if args.cluster_only:
        cluster_faces(conn)
        return

    if not args.takeout or not args.uploads:
        parser.error("--takeout and --uploads required unless --cluster-only")

    args.uploads.mkdir(parents=True, exist_ok=True)

    print("\n🔧 Loading models...")
    clip_model, clip_preprocess, clip_device = load_clip()
    face_app = None if args.no_faces else load_face_models()
    openai_key = None if args.no_captions else args.openai_key
    if not args.no_captions and not openai_key:
        print("  ⚠️  No OpenAI API key — captions disabled.")
        openai_key = None

    items = discover(args.takeout, conn, args.dry_run)

    print(f"\n🚀 Processing {len(items):,} items...")
    if openai_key:
        print(f"   Captions: {args.caption_workers} parallel workers")
    batch_size = args.batch_size
    record_buf = []
    faces_buf = []
    start = time.time()

    for idx, (path, sidecar, file_hash) in enumerate(tqdm(items, desc='Ingesting', unit='file')):
        try:
            is_video = path.suffix.lower() in VIDEO_EXTS
            meta = extract_metadata(path, sidecar, file_hash)
            thumb = make_thumbnail(path, args.uploads, meta['id'], is_video)
            meta['thumbnail_path'] = thumb
            meta['_path'] = path
            meta['_is_video'] = is_video
            faces = []
            if not is_video and face_app:
                faces = detect_faces(path, face_app, meta['id'])
            record_buf.append(meta)
            faces_buf.append(faces)

            if len(record_buf) >= batch_size or idx == len(items) - 1:
                paths_batch = [r.pop('_path') for r in record_buf]
                is_video_batch = [r.pop('_is_video') for r in record_buf]

                # CLIP embeddings
                photo_indices = [i for i, v in enumerate(is_video_batch) if not v]
                photo_paths = [paths_batch[i] for i in photo_indices]
                embs = clip_embed_batch(photo_paths, clip_model, clip_preprocess, clip_device)
                for list_idx, rec_idx in enumerate(photo_indices):
                    if embs[list_idx] is not None:
                        record_buf[rec_idx]['clip_embedding'] = embs[list_idx].tobytes()

                # Captions — parallel
                if openai_key:
                    caption_inputs = [
                        (paths_batch[i], record_buf[i]['id'])
                        for i in photo_indices
                    ]
                    caption_results = get_captions_parallel(
                        caption_inputs, openai_key, workers=args.caption_workers
                    )
                    for rec in record_buf:
                        if rec['id'] in caption_results:
                            rec['caption'] = caption_results[rec['id']]

                insert_batch(conn, record_buf, faces_buf)
                record_buf = []
                faces_buf = []
        except Exception as e:
            tqdm.write(f"  ⚠️  {path.name}: {e}")
            continue

    elapsed = time.time() - start
    total = conn.execute('SELECT COUNT(*) FROM media').fetchone()[0]
    print(f"\n✅ Ingested {len(items):,} items in {elapsed/60:.1f} min. DB total: {total:,}")

    build_auto_links(conn)
    if face_app: cluster_faces(conn)
    rebuild_fts(conn)

    print(f"\n🎉 Done! DB: {args.db}")
    print(f"   Next: scp {args.db} + uploads/ to c-jfischer3:~/claude/open-photo/")

if __name__ == '__main__':
    main()
