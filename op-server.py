#!/usr/bin/env python3
"""
op-server.py — Open Photo API server
Run on c-jfischer3 after scp'ing op.db + uploads/ from GPU machine.
"""

import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PORT        = int(os.environ.get('OPENPHOTO_PORT', 8260))
DB_PATH     = os.environ.get('OPENPHOTO_DB',      os.path.expanduser('~/claude/open-photo/op.db'))
UPLOADS_DIR = os.environ.get('OPENPHOTO_UPLOADS', os.path.expanduser('~/claude/open-photo/uploads'))
VIZ_PATH    = os.path.join(os.path.dirname(__file__), 'op-viz.html')

CLIP_MODEL_NAME = 'ViT-B-32'
CLIP_PRETRAINED = 'openai'
THUMB_SIZE      = 512
COSINE_LINK     = 0.45
TOP_K_SEARCH    = 50

app = FastAPI(title='Open Photo', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

db_lock = threading.Lock()
_conn = None

def get_db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute('PRAGMA journal_mode=WAL')
        _conn.execute('PRAGMA foreign_keys=ON')
    return _conn

def new_id(): return uuid.uuid4().hex[:12]
def now_iso(): return datetime.now(timezone.utc).isoformat()

def row_to_dict(row):
    if row is None: return None
    d = dict(row)
    for field in ('people_tags',):
        if d.get(field) and isinstance(d[field], str):
            try: d[field] = json.loads(d[field])
            except: pass
    d.pop('clip_embedding', None)
    return d

_clip_model = None
_clip_preprocess = None
_clip_device = 'cpu'
_embeddings_cache = {}

def load_clip():
    global _clip_model, _clip_preprocess, _clip_device
    try:
        import open_clip, torch
        model, _, preprocess = open_clip.create_model_and_transforms(CLIP_MODEL_NAME, pretrained=CLIP_PRETRAINED)
        model.eval()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model = model.to(device)
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_device = device
        print(f'  CLIP loaded on {device}')
    except Exception as e:
        print(f'  CLIP load failed: {e}')

def load_embeddings_index():
    global _embeddings_cache
    with db_lock:
        conn = get_db()
        rows = conn.execute('SELECT id, clip_embedding FROM media WHERE clip_embedding IS NOT NULL').fetchall()
    # Store normalized vectors for fast cosine similarity
    _embeddings_cache = {}
    for r in rows:
        v = np.frombuffer(r['clip_embedding'], dtype=np.float32).copy()
        n = np.linalg.norm(v)
        if n > 0: v /= n
        _embeddings_cache[r['id']] = v
    print(f'  Embedding index: {len(_embeddings_cache):,} items')

_st_model = None

def load_st_model():
    global _st_model
    try:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer('all-MiniLM-L6-v2')
        print('  SentenceTransformer loaded (text search enabled)')
    except Exception as e:
        print(f'  SentenceTransformer load failed: {e}')

def embed_text(text):
    if _clip_model is None and _st_model is None: return None
    # Prefer CLIP for text (same space as image embeddings)
    if _clip_model is not None:
        try:
            import open_clip, torch
            tokens = open_clip.tokenize([text]).to(_clip_device)
            with torch.no_grad():
                emb = _clip_model.encode_text(tokens)
                emb = emb / emb.norm(dim=-1, keepdim=True)
            return emb.cpu().float().numpy()[0]
        except: pass
    # Fallback: use caption FTS via returning None (handled in search endpoint)
    return None

def embed_image_bytes(data):
    if _clip_model is None: return None
    try:
        import torch
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data)).convert('RGB')
        tensor = _clip_preprocess(img).unsqueeze(0).to(_clip_device)
        with torch.no_grad():
            emb = _clip_model.encode_image(tensor)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().float().numpy()[0]
    except: return None

def cosine_search(query_emb, limit=TOP_K_SEARCH):
    if not _embeddings_cache: return []
    ids  = list(_embeddings_cache.keys())
    embs = np.array(list(_embeddings_cache.values()))
    query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-8)
    sims = embs @ query_emb
    top_k = min(limit, len(ids))
    indices = np.argpartition(sims, -top_k)[-top_k:]
    indices = indices[np.argsort(sims[indices])[::-1]]
    return [(ids[i], float(sims[i])) for i in indices]

@app.on_event('startup')
async def startup():
    import asyncio
    Path(UPLOADS_DIR).mkdir(parents=True, exist_ok=True)
    get_db()
    await asyncio.to_thread(load_clip)
    await asyncio.to_thread(load_embeddings_index)
    await asyncio.to_thread(load_st_model)
    asyncio.create_task(temperature_decay_loop())
    print(f'  Open Photo running on port {PORT}')

async def temperature_decay_loop():
    import asyncio
    while True:
        await asyncio.sleep(3600)
        try:
            with db_lock:
                conn = get_db()
                conn.execute("UPDATE media SET temperature = MAX(0.1, temperature * 0.9) WHERE status != 'permanent'")
                conn.commit()
        except: pass

@app.get('/')
def serve_frontend():
    return FileResponse(VIZ_PATH, headers={'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache'})

app.mount('/uploads', StaticFiles(directory=UPLOADS_DIR), name='uploads')

def _safe_count(c, q):
    try: return c.execute(q).fetchone()[0]
    except: return 0

@app.get('/api/stats')
def get_stats():
    with db_lock:
        conn = get_db()
        total    = _safe_count(conn, 'SELECT COUNT(*) FROM media')
        photos   = _safe_count(conn, "SELECT COUNT(*) FROM media WHERE media_type='image'")
        videos   = _safe_count(conn, "SELECT COUNT(*) FROM media WHERE media_type='video'")
        faces    = _safe_count(conn, 'SELECT COUNT(*) FROM faces')
        clusters = _safe_count(conn, 'SELECT COUNT(*) FROM face_clusters')
        inbox    = _safe_count(conn, "SELECT COUNT(*) FROM media WHERE status='inbox'")
        with_gps = _safe_count(conn, 'SELECT COUNT(*) FROM media WHERE geo_lat IS NOT NULL')
        captioned= _safe_count(conn, 'SELECT COUNT(*) FROM media WHERE caption IS NOT NULL')
        try:
            by_year = conn.execute("""
                SELECT SUBSTR(taken_at, 1, 4) as year, COUNT(*) as count
                FROM media WHERE taken_at IS NOT NULL
                GROUP BY year ORDER BY year DESC
            """).fetchall()
        except: by_year = []
    return {
        'total': total, 'photos': photos, 'videos': videos,
        'faces': faces, 'clusters': clusters, 'named_clusters': 0,
        'edges': 0, 'inbox': inbox, 'with_gps': with_gps,
        'captioned': captioned, 'by_year': [dict(r) for r in by_year],
        'embedding_index': len(_embeddings_cache),
    }



# PCA basis vectors — computed once from first 100, reused for projecting more items
_pca_basis = None      # (mean, Vt2, proj_min, proj_range)
_pca_basis_3d = None   # (mean, Vt3, proj_min, proj_range)

def compute_layout_3d(limit=100):
    """PCA 3D layout via SVD — pure numpy. Same as compute_layout but returns x,y,z."""
    global _pca_basis_3d
    import numpy as np

    with db_lock:
        conn = get_db()
        rows = conn.execute(
            'SELECT id, clip_embedding, thumbnail_path, taken_at, caption, label, media_type '
            'FROM media WHERE clip_embedding IS NOT NULL LIMIT ?', (limit,)
        ).fetchall()

    if len(rows) < 3:
        return []

    embs = np.array([np.frombuffer(r['clip_embedding'], dtype=np.float32) for r in rows])

    if _pca_basis_3d is None:
        basis_n = min(100, len(embs))
        mean = embs[:basis_n].mean(axis=0)
        centered = embs[:basis_n] - mean
        U, S, Vt = np.linalg.svd(centered, full_matrices=False)
        basis_proj = centered @ Vt[:3].T
        pmin = basis_proj.min(axis=0)
        prange = basis_proj.max(axis=0) - pmin + 1e-8
        _pca_basis_3d = (mean, Vt[:3], pmin, prange)

    mean, Vt3, pmin, prange = _pca_basis_3d

    proj = (embs - mean) @ Vt3.T
    proj = (proj - pmin) / prange
    proj = np.clip(proj, -0.1, 1.1)

    return [{
        'id': rows[i]['id'],
        'x': round(float(proj[i, 0]), 4),
        'y': round(float(proj[i, 1]), 4),
        'z': round(float(proj[i, 2]), 4),
        'thumbnail_path': rows[i]['thumbnail_path'],
        'taken_at': rows[i]['taken_at'],
        'caption': (rows[i]['caption'] or '')[:80],
        'label': rows[i]['label'],
        'media_type': rows[i]['media_type'],
    } for i in range(len(rows))]


def compute_layout(limit=100):
    """PCA 2D layout via SVD — pure numpy.
       Computes PCA basis from first 100 items, then projects up to `limit` items onto it."""
    global _pca_basis
    import numpy as np

    with db_lock:
        conn = get_db()
        rows = conn.execute(
            'SELECT id, clip_embedding, thumbnail_path, taken_at, caption, label, media_type '
            'FROM media WHERE clip_embedding IS NOT NULL LIMIT ?', (limit,)
        ).fetchall()

    if len(rows) < 2:
        return []

    embs = np.array([np.frombuffer(r['clip_embedding'], dtype=np.float32) for r in rows])

    # Compute PCA basis from first min(100, N) items (fast SVD)
    if _pca_basis is None:
        basis_n = min(100, len(embs))
        mean = embs[:basis_n].mean(axis=0)
        centered = embs[:basis_n] - mean
        U, S, Vt = np.linalg.svd(centered, full_matrices=False)
        # Project basis items to get normalization range
        basis_proj = centered @ Vt[:2].T
        pmin = basis_proj.min(axis=0)
        prange = basis_proj.max(axis=0) - pmin + 1e-8
        _pca_basis = (mean, Vt[:2], pmin, prange)

    mean, Vt2, pmin, prange = _pca_basis

    # Project all items onto the PCA basis
    proj = (embs - mean) @ Vt2.T
    proj = (proj - pmin) / prange  # normalize to ~[0,1]
    # Clamp outliers
    proj = np.clip(proj, -0.1, 1.1)

    return [{
        'id': rows[i]['id'],
        'x': round(float(proj[i, 0]), 4),
        'y': round(float(proj[i, 1]), 4),
        'thumbnail_path': rows[i]['thumbnail_path'],
        'taken_at': rows[i]['taken_at'],
        'caption': (rows[i]['caption'] or '')[:80],
        'label': rows[i]['label'],
        'media_type': rows[i]['media_type'],
    } for i in range(len(rows))]


@app.get('/api/layout')
async def get_layout(recompute: bool = Query(False), limit: int = Query(100)):
    """PCA 2D projection of CLIP embeddings."""
    global _pca_basis
    if recompute:
        _pca_basis = None
    limit = min(max(limit, 10), 5000)
    result = await asyncio.to_thread(compute_layout, limit)
    return {'nodes': result, 'count': len(result)}


@app.get('/api/clusters')
async def get_clusters(n: int = Query(12), min_size: int = Query(3)):
    """Cluster all photos by CLIP embedding similarity. Returns n clusters with members."""
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.preprocessing import normalize

    with db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, clip_embedding, thumbnail_path, taken_at, caption, label FROM media WHERE clip_embedding IS NOT NULL"
        ).fetchall()

    if len(rows) < 4:
        return {'clusters': [], 'count': 0}

    ids = [r['id'] for r in rows]
    thumbs = {r['id']: r['thumbnail_path'] for r in rows}
    captions = {r['id']: r['caption'] for r in rows}
    labels = {r['id']: r['label'] for r in rows}
    dates = {r['id']: r['taken_at'] for r in rows}

    # Load embeddings
    embs = np.array([np.frombuffer(r['clip_embedding'], dtype=np.float32) for r in rows])
    embs = normalize(embs)  # L2-normalize for cosine distance

    # Clamp n to reasonable range
    k = max(2, min(n, len(rows) // min_size))

    # Ward linkage on L2-normalized vectors = balanced cosine clusters
    clustering = AgglomerativeClustering(n_clusters=k, metric='euclidean', linkage='ward')
    cluster_labels = clustering.fit_predict(embs)

    # Group by cluster
    from collections import defaultdict
    groups = defaultdict(list)
    for i, cid in enumerate(cluster_labels):
        groups[int(cid)].append(ids[i])

    # For each cluster, find the medoid (most central photo)
    clusters_out = []
    for cid, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(members) < 1:
            continue
        member_idxs = [ids.index(m) for m in members]
        cluster_embs = embs[member_idxs]
        centroid = cluster_embs.mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        sims = cluster_embs @ centroid
        medoid_local = int(np.argmax(sims))
        medoid_id = members[medoid_local]

        # Auto-label the cluster from captions
        sample_caps = [captions.get(m, '') or labels.get(m, '') for m in members[:5]]
        sample_caps = [c for c in sample_caps if c]

        clusters_out.append({
            'cluster_id': cid,
            'size': len(members),
            'medoid_id': medoid_id,
            'medoid_thumb': thumbs.get(medoid_id),
            'members': members,
            'sample_captions': sample_caps[:3],
            'date_range': {
                'min': min((dates.get(m) or '' for m in members if dates.get(m)), default=''),
                'max': max((dates.get(m) or '' for m in members if dates.get(m)), default=''),
            }
        })

    return {'clusters': clusters_out, 'count': len(clusters_out)}


@app.get('/api/embedding-layout')
async def embedding_layout(limit: int = Query(100)):
    """PCA 2D positions keyed by id. ?limit=100|300|900|2700"""
    limit = min(max(limit, 10), 5000)
    result = await asyncio.to_thread(compute_layout, limit)
    positions = {n['id']: [n['x'], n['y']] for n in result}
    return {'positions': positions}


@app.get('/api/embedding-layout-3d')
async def embedding_layout_3d(limit: int = Query(100)):
    """PCA 3D positions keyed by id. ?limit=100|300|900|2700"""
    limit = min(max(limit, 10), 5000)
    result = await asyncio.to_thread(compute_layout_3d, limit)
    positions = {n['id']: [n['x'], n['y'], n['z']] for n in result}
    return {'positions': positions}


@app.get('/api/photos')
async def get_photos():
    """All photos as lightweight node list for Poincare disk."""
    with db_lock:
        conn = get_db()
        rows = conn.execute(
            'SELECT m.id, m.label, m.caption, m.thumbnail_path, m.taken_at, m.media_type, m.geo_name, '
            'EXISTS(SELECT 1 FROM faces f WHERE f.media_id=m.id) as has_faces, '
            'm.is_nsfw '
            'FROM media m ORDER BY m.taken_at DESC'
        ).fetchall()
    return {'nodes': [{
        'id': r['id'],
        'label': r['label'] or '',
        'caption': (r['caption'] or '')[:120],
        'thumbnail_path': r['thumbnail_path'],
        'taken_at': r['taken_at'],
        'media_type': r['media_type'],
        'geo_name': r['geo_name'],
        'has_faces': bool(r['has_faces']),
        'is_nsfw': bool(r['is_nsfw']),
    } for r in rows]}


@app.get('/api/media/{media_id}/similarities')
async def media_similarities(media_id: str, limit: int = Query(20)):
    """Cosine similarity of one photo against all others — for Poincare orbit layout."""
    import numpy as np
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT clip_embedding FROM media WHERE id=?', (media_id,)).fetchone()
    if not row or not row['clip_embedding']:
        return {'similarities': []}
    q = np.frombuffer(row['clip_embedding'], dtype=np.float32)
    qn = q / (np.linalg.norm(q) + 1e-8)

    # Use in-memory cache for speed
    scored = []
    for mid, emb in _embeddings_cache.items():
        if mid == media_id: continue
        sim = float(qn @ emb)
        if sim > 0.1:
            scored.append({'id': mid, 'score': round(sim, 4)})
    scored.sort(key=lambda x: -x['score'])
    return {'similarities': scored[:limit]}


@app.get('/api/search')
async def search(
    q: str = Query(...),
    mode: str = Query('semantic'),
    limit: int = Query(50),
    year: Optional[str] = None,
    album: Optional[str] = None,
    media_type: Optional[str] = None,
    has_gps: Optional[bool] = None,
    person: Optional[str] = None,
):
    import asyncio
    results = []
    if mode in ('semantic', 'combined'):
        query_emb = await asyncio.to_thread(embed_text, q)
        if query_emb is not None:
            matches = cosine_search(query_emb, limit=limit * 2)
            results = [{'id': mid, 'score': score, 'source': 'semantic'} for mid, score in matches if score > 0.2]
    # Fallback: if semantic returned nothing (CLIP unavailable), use FTS
    if mode == 'semantic' and not results:
        mode = 'fts'
    if mode in ('fts', 'combined'):
        with db_lock:
            conn = get_db()
            safe_q = ' '.join(f'"{w}"' for w in q.split() if w)
            fts_rows = conn.execute("""
                SELECT m.id, bm25(media_fts) as score FROM media_fts
                JOIN media m ON media_fts.id = m.id WHERE media_fts MATCH ? LIMIT ?
            """, (safe_q, limit)).fetchall()
        seen = {r['id'] for r in results}
        for row in fts_rows:
            if row['id'] not in seen:
                results.append({'id': row['id'], 'score': float(row['score']), 'source': 'fts'})
    if not results: return {'results': [], 'query': q, 'count': 0}
    ids = [r['id'] for r in results[:limit]]
    score_map = {r['id']: r['score'] for r in results}
    with db_lock:
        conn = get_db()
        placeholders = ','.join('?' * len(ids))
        rows = conn.execute(f"""
            SELECT id, media_type, label, caption, thumbnail_path, taken_at,
                   geo_lat, geo_lon, geo_name, album, people_tags, width, height,
                   duration_s, status, temperature
            FROM media WHERE id IN ({placeholders})
        """, ids).fetchall()
    records = [row_to_dict(r) for r in rows]
    for rec in records: rec['score'] = score_map.get(rec['id'], 0)
    if year: records = [r for r in records if r.get('taken_at', '').startswith(year)]
    if album: records = [r for r in records if r.get('album') == album]
    if media_type: records = [r for r in records if r.get('media_type') == media_type]
    if has_gps is True: records = [r for r in records if r.get('geo_lat') is not None]
    records.sort(key=lambda r: r['score'], reverse=True)
    return {'results': records[:limit], 'query': q, 'count': len(records)}

@app.get('/api/media/{media_id}')
def get_media(media_id: str):
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
        if not row: raise HTTPException(404, 'Not found')
        conn.execute("UPDATE media SET visit_count = visit_count + 1, temperature = MIN(2.0, temperature + 0.3) WHERE id=?", (media_id,))
        conn.commit()
        faces = conn.execute("""
            SELECT f.id, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h, f.confidence,
                   f.is_noise, fc.id as cluster_id, fc.anonymous_label, fc.person_name
            FROM faces f LEFT JOIN face_clusters fc ON f.cluster_id = fc.id
            WHERE f.media_id=?
        """, (media_id,)).fetchall()
        connected = []  # no edges in open-photo; use similarity API instead
    rec = row_to_dict(row)
    rec['faces'] = [dict(f) for f in faces]
    rec['connected'] = [dict(c) for c in connected]
    return rec

class MediaUpdate(BaseModel):
    label: Optional[str] = None
    caption: Optional[str] = None
    status: Optional[str] = None

@app.patch('/api/media/{media_id}')
def update_media(media_id: str, body: MediaUpdate):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates: raise HTTPException(400, 'Nothing to update')
    updates['updated_at'] = now_iso()
    with db_lock:
        conn = get_db()
        sets = ', '.join(f'{k}=?' for k in updates)
        conn.execute(f'UPDATE media SET {sets} WHERE id=?', (*updates.values(), media_id))
        conn.commit()
    return {'status': 'updated'}

@app.delete('/api/media/{media_id}')
def delete_media(media_id: str):
    with db_lock:
        conn = get_db()
        conn.execute('DELETE FROM media WHERE id=?', (media_id,))
        conn.commit()
    _embeddings_cache.pop(media_id, None)
    return {'status': 'deleted'}

@app.get('/api/similar/{media_id}')
def get_similar(media_id: str, limit: int = 24):
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT clip_embedding FROM media WHERE id=?', (media_id,)).fetchone()
    if not row or not row['clip_embedding']: raise HTTPException(404, 'No embedding')
    query_emb = np.frombuffer(row['clip_embedding'], dtype=np.float32)
    matches = cosine_search(query_emb, limit=limit + 1)
    matches = [(mid, score) for mid, score in matches if mid != media_id][:limit]
    ids = [m[0] for m in matches]
    score_map = {m[0]: m[1] for m in matches}
    with db_lock:
        conn = get_db()
        placeholders = ','.join('?' * len(ids))
        rows = conn.execute(f"SELECT id, label, thumbnail_path, taken_at, media_type FROM media WHERE id IN ({placeholders})", ids).fetchall()
    records = [row_to_dict(r) for r in rows if r['thumbnail_path']]
    for rec in records: rec['score'] = score_map.get(rec['id'], 0)
    records.sort(key=lambda r: r['score'], reverse=True)
    return {'results': records, 'count': len(records)}

@app.get('/api/neighbors/{media_id}')
def get_neighbors(media_id: str, limit: int = 12):
    """Return top-N neighbor IDs + scores for building k-NN graph in Poincare view."""
    with db_lock:
        conn = get_db()
        row = conn.execute('SELECT clip_embedding FROM media WHERE id=?', (media_id,)).fetchone()
    if not row or not row['clip_embedding']: raise HTTPException(404, 'No embedding')
    query_emb = np.frombuffer(row['clip_embedding'], dtype=np.float32)
    matches = cosine_search(query_emb, limit=limit + 1)
    matches = [(mid, float(score)) for mid, score in matches if mid != media_id][:limit]
    return {'id': media_id, 'similarities': [{'id': mid, 'score': score} for mid, score in matches]}


@app.get('/api/timeline')
def get_timeline(
    from_date: Optional[str] = Query(None, alias='from'),
    to_date: Optional[str] = Query(None, alias='to'),
    limit: int = Query(200),
    offset: int = Query(0),
):
    with db_lock:
        conn = get_db()
        conditions = ['taken_at IS NOT NULL']
        params = []
        if from_date: conditions.append('taken_at >= ?'); params.append(from_date)
        if to_date: conditions.append('taken_at <= ?'); params.append(to_date)
        where = ' AND '.join(conditions)
        total = conn.execute(f'SELECT COUNT(*) FROM media WHERE {where}', params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT id, media_type, label, thumbnail_path, taken_at,
                   geo_lat, geo_lon, album, width, height, duration_s
            FROM media WHERE {where} ORDER BY taken_at DESC LIMIT ? OFFSET ?
        """, [*params, limit, offset]).fetchall()
    return {'items': [row_to_dict(r) for r in rows], 'total': total, 'limit': limit, 'offset': offset}

@app.get('/api/timeline/years')
def get_timeline_years():
    with db_lock:
        conn = get_db()
        rows = conn.execute("""
            SELECT SUBSTR(taken_at,1,4) as year, SUBSTR(taken_at,6,2) as month, COUNT(*) as count
            FROM media WHERE taken_at IS NOT NULL
            GROUP BY year, month ORDER BY year DESC, month DESC
        """).fetchall()
    return [dict(r) for r in rows]

@app.get('/api/map')
def get_map():
    with db_lock:
        conn = get_db()
        rows = conn.execute("""
            SELECT id, thumbnail_path, geo_lat, geo_lon, geo_name, taken_at, label, media_type
            FROM media WHERE geo_lat IS NOT NULL AND geo_lon IS NOT NULL
        """).fetchall()
    return {'items': [dict(r) for r in rows], 'count': len(rows)}

@app.get('/api/people')
def get_people(limit: int = 100, offset: int = 0):
    with db_lock:
        conn = get_db()
        total = conn.execute('SELECT COUNT(*) FROM face_clusters').fetchone()[0]
        rows = conn.execute("""
            SELECT fc.id, fc.anonymous_label, fc.person_name, fc.face_count,
                   fc.cover_face_id, fc.created_at,
                   f.media_id as cover_media_id, m.thumbnail_path as cover_thumb,
                   f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                   m.width as orig_w, m.height as orig_h
            FROM face_clusters fc
            LEFT JOIN faces f ON fc.cover_face_id = f.id
            LEFT JOIN media m ON f.media_id = m.id
            ORDER BY fc.face_count DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
    import os
    thumb_dir = os.path.join(os.path.dirname(DB_PATH), 'uploads')
    result = []
    for r in rows:
        d = dict(r)
        # If cover thumb missing from disk, find another face in this cluster with a present thumb
        thumb = d.get('cover_thumb')
        if not thumb or not os.path.exists(os.path.join(thumb_dir, thumb)):
            fallback = conn.execute("""
                SELECT m.thumbnail_path, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                       m.width as orig_w, m.height as orig_h
                FROM faces f JOIN media m ON f.media_id = m.id
                WHERE f.cluster_id=? AND m.thumbnail_path IS NOT NULL
                ORDER BY m.taken_at DESC LIMIT 20
            """, (d['id'],)).fetchall()
            found = False
            for fb in fallback:
                if os.path.exists(os.path.join(thumb_dir, fb['thumbnail_path'])):
                    d['cover_thumb'] = fb['thumbnail_path']
                    d['bbox_x'] = fb['bbox_x']; d['bbox_y'] = fb['bbox_y']
                    d['bbox_w'] = fb['bbox_w']; d['bbox_h'] = fb['bbox_h']
                    d['orig_w'] = fb['orig_w']; d['orig_h'] = fb['orig_h']
                    found = True
                    break
            if not found:
                d['cover_thumb'] = None  # frontend will skip
        result.append(d)
    return {'people': result, 'total': total}

@app.get('/api/people/{cluster_id}/photos')
def get_person_photos(cluster_id: str, limit: int = 100, offset: int = 0):
    with db_lock:
        conn = get_db()
        cluster = conn.execute('SELECT * FROM face_clusters WHERE id=?', (cluster_id,)).fetchone()
        if not cluster: raise HTTPException(404, 'Person not found')
        total = conn.execute('SELECT COUNT(DISTINCT media_id) FROM faces WHERE cluster_id=?', (cluster_id,)).fetchone()[0]
        rows = conn.execute("""
            SELECT DISTINCT m.id, m.label, m.thumbnail_path, m.taken_at, m.media_type, m.album, m.geo_name
            FROM faces f JOIN media m ON f.media_id = m.id
            WHERE f.cluster_id=? ORDER BY m.taken_at DESC LIMIT ? OFFSET ?
        """, (cluster_id, limit, offset)).fetchall()
    return {'cluster': dict(cluster), 'photos': [dict(r) for r in rows], 'total': total}

class PersonUpdate(BaseModel):
    person_name: Optional[str] = None

@app.patch('/api/people/{cluster_id}')
def update_person(cluster_id: str, body: PersonUpdate):
    with db_lock:
        conn = get_db()
        conn.execute('UPDATE face_clusters SET person_name=? WHERE id=?', (body.person_name, cluster_id))
        conn.commit()
    return {'status': 'updated'}

@app.get('/api/albums')
def get_albums():
    with db_lock:
        conn = get_db()
        rows = conn.execute("""
            SELECT album, COUNT(*) as count, MIN(taken_at) as earliest, MAX(taken_at) as latest
            FROM media WHERE album IS NOT NULL GROUP BY album ORDER BY count DESC
        """).fetchall()
    return [dict(r) for r in rows]

@app.get('/api/albums/{album_name}')
def get_album_photos(album_name: str, limit: int = 200, offset: int = 0):
    with db_lock:
        conn = get_db()
        total = conn.execute('SELECT COUNT(*) FROM media WHERE album=?', (album_name,)).fetchone()[0]
        rows = conn.execute("""
            SELECT id, label, thumbnail_path, taken_at, media_type, width, height
            FROM media WHERE album=? ORDER BY taken_at DESC LIMIT ? OFFSET ?
        """, (album_name, limit, offset)).fetchall()
    return {'album': album_name, 'photos': [dict(r) for r in rows], 'total': total}

@app.post('/api/upload')
async def upload_media(file: UploadFile = File(...)):
    import asyncio
    from PIL import Image
    import io, hashlib
    data = await file.read()
    ext = Path(file.filename).suffix.lower()
    is_video = ext in {'.mp4', '.mov', '.avi', '.mkv', '.m4v'}
    media_id = new_id()
    file_hash = hashlib.sha256(data).hexdigest()
    with db_lock:
        conn = get_db()
        existing = conn.execute('SELECT id FROM media WHERE file_hash=?', (file_hash,)).fetchone()
        if existing: return {'status': 'duplicate', 'id': existing['id']}
    thumb_name = f'thumb_{media_id}.jpg'
    thumb_path = Path(UPLOADS_DIR) / thumb_name
    if not is_video:
        img = Image.open(io.BytesIO(data)).convert('RGB')
        w, h = img.size
        img.thumbnail((THUMB_SIZE, THUMB_SIZE))
        img.save(thumb_path, 'JPEG', quality=85)
    else:
        w, h = None, None
    emb = await asyncio.to_thread(embed_image_bytes, data)
    rec = {
        'id': media_id, 'media_type': 'video' if is_video else 'photo',
        'original_filename': file.filename, 'file_hash': file_hash,
        'label': Path(file.filename).stem, 'thumbnail_path': thumb_name,
        'width': w, 'height': h,
        'clip_embedding': emb.tobytes() if emb is not None else None,
        'status': 'inbox', 'temperature': 1.5,
        'created_at': now_iso(), 'updated_at': now_iso(),
    }
    with db_lock:
        conn = get_db()
        conn.execute("""INSERT INTO media (id,media_type,original_filename,file_hash,
            label,thumbnail_path,width,height,clip_embedding,status,temperature,visit_count,created_at,updated_at)
            VALUES (:id,:media_type,:original_filename,:file_hash,:label,:thumbnail_path,
            :width,:height,:clip_embedding,:status,:temperature,0,:created_at,:updated_at)""", rec)
        conn.commit()
    if emb is not None: _embeddings_cache[media_id] = emb
    return {'status': 'created', 'id': media_id, 'thumbnail': thumb_name}

@app.get('/api/collections')
def get_collections():
    with db_lock:
        conn = get_db()
        rows = conn.execute("""
            SELECT c.id, c.name, c.description, c.color, c.created_at, COUNT(cm.media_id) as count
            FROM collections c LEFT JOIN collection_media cm ON c.id = cm.collection_id
            GROUP BY c.id ORDER BY c.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]

class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = '#6ee7b7'

@app.post('/api/collections')
def create_collection(body: CollectionCreate):
    cid = new_id()
    with db_lock:
        conn = get_db()
        conn.execute('INSERT INTO collections (id,name,description,color,created_at) VALUES (?,?,?,?,?)',
            (cid, body.name, body.description, body.color, now_iso()))
        conn.commit()
    return {'id': cid, 'name': body.name}

@app.post('/api/collections/{collection_id}/media')
def add_to_collection(collection_id: str, body: dict):
    node_ids = body.get('media_ids', [])
    with db_lock:
        conn = get_db()
        conn.executemany('INSERT OR IGNORE INTO collection_media (collection_id, media_id) VALUES (?,?)',
            [(collection_id, mid) for mid in node_ids])
        conn.commit()
    return {'status': 'added', 'count': len(node_ids)}

@app.post('/api/search-by-image')
async def search_by_image(file: UploadFile = File(...)):
    import asyncio
    data = await file.read()
    emb = await asyncio.to_thread(embed_image_bytes, data)
    if emb is None: raise HTTPException(500, 'Could not embed image')
    matches = cosine_search(emb, limit=50)
    ids = [m[0] for m in matches]
    score_map = {m[0]: m[1] for m in matches}
    with db_lock:
        conn = get_db()
        placeholders = ','.join('?' * len(ids))
        rows = conn.execute(f"SELECT id, label, thumbnail_path, taken_at, media_type FROM media WHERE id IN ({placeholders})", ids).fetchall()
    records = [row_to_dict(r) for r in rows]
    for rec in records: rec['score'] = score_map.get(rec['id'], 0)
    records.sort(key=lambda r: r['score'], reverse=True)
    return {'results': records}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('op-server:app', host='0.0.0.0', port=PORT, reload=False)
