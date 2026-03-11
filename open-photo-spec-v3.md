# Open Photo — System Specification v3.0

*Updated March 2026 · covers v4 (stable) and v4.1x (experimental)*

---

## 1. Overview

Open Photo is a private, self-hosted photo and video memory archive. It ingests a lifetime of media from Google Photos, embeds each item semantically using OpenAI's CLIP model, and exposes two primary exploration interfaces: a zoomable semantic scatter map and a Poincaré hyperbolic disk navigator. The system is designed for a single user and prioritizes visual exploration over cataloguing.

The guiding philosophy is that photos should be experienced spatially by meaning, not filed chronologically. Two images taken years apart that share visual similarity appear near each other in the scatter view. Navigating in Poincaré space feels like moving through associative memory — the center photo is what you're thinking about; the orbit is everything related.

---

## 2. System Architecture

### 2.1 Machines

| Role | Description |
|------|-------------|
| GPU machine (AWS) | g5.16xlarge · ec2-user@172.18.71.210 · runs CLIP ingest pipeline, stores source photos |
| Serve machine | c-jfischer3 · jfischer@ceto.languageweaver.com:4640 · runs FastAPI server on port 8260 |
| Public URL | https://openphoto.fahrenheitrequited.dev (proxied to :8260 via Cloudflare tunnel) |

### 2.2 Component Map

- **Google Photos** → rclone → /home/ec2-user/open-photo/ (source files on GPU machine)
- **Ingest pipeline** → runs on GPU machine in conda env "openphoto", writes op.db + thumbnails
- **Transfer** → `sqlite3 .dump media | scp` → do-import.sh on serve machine
- **op-server.py** → FastAPI, port 8260, serves API + static files from serve machine (736 lines)
- **op-viz.html** → single-file frontend, ~2,546 lines (v4) / ~2,640 lines (v4.1x), served at /
- **op.db** → SQLite WAL, single source of truth for media metadata + embeddings
- **uploads/** → thumbnail JPEGs, 512×512 max, served at /uploads/

### 2.3 Process Management

The server is kept alive by a cron watchdog that runs every minute:

```
* * * * * pgrep -f op-server.py > /dev/null \
  || (cd ~/claude/open-photo && PYTHONPATH="" python3 -u op-server.py >> server.log 2>&1 &)
```

**Important:** always start the server with `PYTHONPATH=""`. The default PYTHONPATH on c-jfischer3 points to a broken torchvision install that causes import failures even when torch is not used.

**Restart safely:** `pkill -f op-server.py` then let cron bring it back within 60s. Never `killall python3`.

### 2.4 Version History

| Version | File | Lines | Description |
|---------|------|-------|-------------|
| v1 | op-viz-v1.html | 2,036 | First working version, DOM scatter + SVG Poincaré |
| v2 | op-viz-v2.html | ~2,300 | Canvas scatter attempt (broken thumbnails) |
| v3 | op-viz-v3.html | ~2,400 | DOM scatter refactor, Poincaré SVG squares |
| v3.1 | op-viz-v3.1.html | ~2,400 | Drag events moved to container (fixed chip blocking) |
| v3.3 | op-viz-v3.3.html | ~2,500 | Chip init fix + z-sort by proximity + marooned node fix |
| **v4** | **op-viz-v4.html** | **2,546** | **Stable baseline — tooltip removed, all bugs fixed** |
| v4.1x | op-viz-v4.1x.html | 2,640 | Experimental render optimizations (see §6.8) |
| current | op-viz.html | 2,640 | Same as v4.1x (may revert to v4) |

---

## 3. Data Model

### 3.1 media table — 5,952 rows

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | 12-char hex UUID |
| media_type | TEXT | "image" or "video" |
| original_filename | TEXT | Filename from Google Photos export |
| file_hash | TEXT UNIQUE | SHA-256, prevents duplicate ingest |
| label | TEXT | Short human-readable name |
| caption | TEXT | GPT-4o Vision auto-generated description |
| ocr_text | TEXT | OCR text from image |
| clip_embedding | BLOB | 512-dim float32 ViT-B/32, L2-normalized, raw bytes |
| thumbnail_path | TEXT | Filename in uploads/ |
| taken_at | TEXT | ISO-8601 from EXIF/metadata |
| geo_lat / geo_lon | REAL | GPS coordinates |
| geo_name | TEXT | Reverse-geocoded place name |
| album | TEXT | Source Google Photos album |
| people_tags | TEXT | JSON array of person names |
| layout_x / layout_y | REAL | PCA coordinate [0,1], cached |
| temperature | REAL | Recency score, decays 10%/hr, +0.3 on view |
| visit_count | INTEGER | Times detail view opened |
| status | TEXT | "inbox" \| "reviewed" \| "permanent" |

### 3.2 faces / face_clusters

Schema exists on both machines but face_clusters on the serve machine lacks `face_count`, `cover_face_id`, and `anonymous_label` columns that the API expects. People view will error until migrated.

### 3.3 collections / collection_media

Schema exists, no UI yet.

### 3.4 FTS index

FTS5 virtual table `media_fts` on (id, label, caption, ocr_text, geo_name). Built on import from GPU machine. Never transfer via WAL — always use `.dump` approach.

---

## 4. Ingest Pipeline (GPU Machine)

### 4.1 Source data

```bash
nohup rclone copy "gdrive:Google Photos" /home/ec2-user/open-photo/ \
  --progress --transfers=8 --checkers=16 >> ~/rclone.log 2>&1 &
disown
```

As of March 2026: ~5,952 photos/videos ingested, ~8,000 remaining (rclone died, needs restart).

### 4.2 CLIP embedding

- **Model:** ViT-B/32 via open_clip, pretrained="openai"
- **Device:** CUDA on g5.16xlarge (A10G GPU)
- **Output:** 512-dim float32 vector, L2-normalized, stored as raw bytes in clip_embedding
- **Thumbnail:** 512×512 JPEG, quality=85, stored in uploads/
- **Caption:** GPT-4o Vision, stored in caption column

### 4.3 Transfer to serve machine

Never scp the live op.db — WAL state causes corruption. Use the dump approach:

```bash
# On GPU machine:
sqlite3 /home/ec2-user/op.db ".dump media" > /tmp/op-media.sql
tar czf /tmp/uploads.tar.gz -C /home/ec2-user uploads/
scp -P 4640 /tmp/op-media.sql jfischer@ceto.languageweaver.com:~/claude/open-photo/
scp -P 4640 /tmp/uploads.tar.gz jfischer@ceto.languageweaver.com:~/claude/open-photo/

# On serve machine:
bash ~/claude/open-photo/do-import.sh

# After import — recompute PCA layout:
curl https://openphoto.fahrenheitrequited.dev/api/layout?recompute=true
```

`do-import.sh`: pauses cron, kills server, drops media table, imports SQL, restores cron, restarts server.

---

## 5. Backend API (op-server.py)

### 5.1 Startup

- **CLIP model** — fails gracefully (libstdc++ mismatch on serve machine)
- **Embedding index** — 4,344 entries loaded into `_embeddings_cache` at startup (~15s)
- **PCA basis** — computed once from first 100 items, cached in `_pca_basis`. Additional items projected onto same basis vectors.
- **Temperature decay** — background asyncio task, hourly, multiplies temperature × 0.9

### 5.2 Layout / PCA

PCA computed via numpy SVD. Basis vectors (mean + top-2 components) computed from first 100 items and cached. Subsequent requests with higher limits project onto the same basis — no re-SVD. Results normalized to [0,1] with outlier clamping.

`?limit=N` controls how many items are projected. Used by the frontend's count chips.

### 5.3 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | / | Serve op-viz.html |
| GET | /uploads/{filename} | Serve thumbnail JPEG |
| GET | /api/stats | DB counts and per-year breakdown |
| GET | /api/layout?limit=100&recompute=false | PCA 2D positions |
| GET | /api/embedding-layout?limit=100 | PCA positions as {positions: {id: [x,y]}} |
| GET | /api/photos | All media as lightweight nodes |
| GET | /api/media/{id} | Full record + faces. Boosts temperature. |
| PATCH | /api/media/{id} | Update label, caption, or status |
| DELETE | /api/media/{id} | Delete record |
| GET | /api/similar/{id}?limit=24 | Top-N cosine-similar photos |
| GET | /api/media/{id}/similarities | Cosine similarity vs ALL (used by Poincaré layout) |
| GET | /api/search?q=&mode=&limit= | Text search (semantic/fts/combined) |
| POST | /api/upload | Ingest new photo |
| GET | /api/timeline | Paginated chronological list |
| GET | /api/timeline/years | Monthly counts |
| GET | /api/map | All geotagged media |
| GET | /api/clusters?n=12 | Agglomerative clustering |
| GET | /api/people | Face clusters |
| GET | /api/albums | Album list with counts |
| GET | /api/collections | User collections |

---

## 6. Frontend (op-viz.html)

### 6.1 Overview

No build step, no framework. Vanilla JS, CSS for scatter, SVG for Poincaré geometry. All state in global JS variables. Two primary views (scatter, poincaré); gallery/timeline/people/map exist but hidden from nav.

### 6.2 Design System

| Token | Value | Notes |
|-------|-------|-------|
| --bg | #0c0b09 | Near-black warm dark |
| --bg2 | #141210 | Secondary |
| --bg3 | #1c1a16 | Surface (nav pills) |
| --border | #2e2b22 | Divider lines |
| --text | #e8e4dc | Primary text |
| --text-dim | #8a8275 | Dimmed text |
| --accent | #d4a853 | Amber — highlights, root node border |
| --font | DM Sans | Body |
| --serif | Playfair Display | Logo (italic) |
| --mono | JetBrains Mono | Nav tabs, timestamps |

### 6.3 Layout

- **Top bar** — 56px fixed, gradient fadeout. Contains: logo, nav tabs (scatter/poincaré), search button, stats chip, count chips
- **Mobile** — top bar wraps to two rows; views pushed to `top:80px`; search + stats hidden
- **Views** — `#views` is `position:fixed; inset:0; top:56px`. Views are `.view` divs toggled with `.active` class.
- **`#view-poincare`** and **`#view-scatter`** are `position:absolute; inset:0` within `#views`. They do not cover the top bar.

### 6.4 Count Chips

Five mutually exclusive buttons in the top bar: **100, 300, 900, 2.7k, max**. Default: 100.

- Initialized at page load in `init()` via `_initScatterChips()` — **not** lazily inside scatter init. This is critical: the chips must work from Poincaré view even if scatter has never loaded.
- Controls `/api/embedding-layout?limit=N` for scatter tile count
- Controls `PD_MAX_NODES` in Poincaré
- Switching chips: resets Poincaré similarity cache (`_pdSimCache = {}`), reloads scatter or reloads Poincaré depending on current view

### 6.5 Scatter View

**Architecture:** DOM-based. Photo thumbnails are `<div class="scatter-tile">` elements with `background-image` (NOT `<img>`, NOT canvas). All tiles are children of `#scatter-field`, positioned with a single CSS `transform: translate() scale()`.

**Camera system:** `_scatterTarget` (input writes) and `_scatterCam` (rendered). A continuous rAF loop lerps cam toward target at 15% per frame (`CAM_LERP = 0.15`). Smooth decelerating motion on all interactions.

**Auto-fit:** On load, computes bounding box of all node positions, sets target k/x/y to fit with 40px padding. First load snaps; resize triggers smooth glide.

**Hover:** CSS `transition: transform 0.18s ease` + `:hover { transform: scale(2.2) }`. Golden glow + shadow.

**Staggered entry:** Tiles start at `opacity:0`, stagger-fade-in via `setTimeout(() => el.classList.add('loaded'), 30 + i * 8)`.

**Interactions:**
- Pan: mousedown/mousemove drag; 1-finger touch
- Zoom: wheel (desktop); 2-finger pinch — zooms toward pointer/midpoint
- Tap tile: enter Poincaré for that photo
- Hover (desktop): tooltip with date + caption

### 6.6 Poincaré Disk View — v4 Architecture

This section describes **v4 (op-viz-v4.html, 2,546 lines)**, the current stable baseline.

#### Rendering pipeline

Hybrid: an SVG layer renders the disk boundary, center glow, geodesic arcs, and all node thumbnails. A WebGL2 canvas overlay (when available) renders nodes as instanced quads using an atlas texture.

**SVG layer (`#pd-svg`):**
- `pointer-events:none` on SVG and all children — no touch/click interception
- Disk background, glow, and edges are in `#pd-bg` and `#pd-edges` groups
- Node `<g>` elements live in `#pd-nodes-svg`. Each `<g>` has:
  - `data-id` attribute for hit testing and DOM lookup
  - `transform="translate(sx,sy)"` SVG attribute for position
  - A `<clipPath>` + `<rect>` for rounded-square clipping
  - A `<image>` for the thumbnail
  - An outer `<rect>` for the border

**WebGL2 layer (`#pd-gl-canvas`, optional):**
- Instanced rendering: one quad per node, atlas texture (64×64 per slot)
- Vertex shader computes screen position from Poincaré coordinates + uniforms
- Fragment shader: rounded square via `v_cd = length(a_corner)`, `smoothstep` AA, amber border on root
- `drawArraysInstanced(TRIANGLES, 0, 6, N)` — single draw call
- Falls back gracefully if WebGL2 unavailable (SVG only)

#### Layout algorithm

When entering Poincaré for photo X:
1. Fetch `/api/media/{id}/similarities` — cosine scores for all photos
2. Sort descending, take top `PD_MAX_NODES` (= `_scatterLimit`, capped at 200)
3. Assign hyperbolic radius by rank: `r = 0.08 + (rank/(N-1)) * 0.64` → range [0.08, 0.72]
4. Assign angle from golden angle distribution: `angle = rank × 2.399963 radians` (≈137.5°)
5. Position: `[cos(a) * r, sin(a) * r]` in Poincaré disk coordinates [-1,1]

#### Size and visual scale

`vs = max(1 - (x²+y²), 0.01)` — approaches 1 at center, 0 at boundary.
`nr = MIN_R + (MAX_R - MIN_R) × vs^1.8` — MIN_R=2, MAX_R=38.
Root node gets `max(nr, min(64, R×0.22))`.
Nodes with `vs < 0.005` are hidden.

#### Z-ordering

Nodes closest to center (highest `vs`) are painted on top. Implemented by re-sorting `#pd-nodes-svg` children via `appendChild` after every position update. Root node gets `vs=2` to ensure it's always topmost. In v4, z-sort runs on every position update including during drag.

#### Navigation (Möbius fly-through)

1. **Fly (500ms):** Hyperbolic interpolation via `atanh`/`tanh` with easeInOut. All positions Möbius-transformed per rAF frame. CSS transitions disabled during flight.
2. **Recompute:** Fetch new similarity data, compute fresh layout.
3. **Settle (400ms):** Nodes created at clean positions, then `_pdSVGBuilt=false` forces rebuild, Möbius-moved to end-of-flight positions, then smoothstep-lerped back to clean layout.

#### Möbius drag

Drag events on `#view-poincare` (the container div, not the SVG):
- `touchstart` / `touchmove` / `touchend` with `{passive:true}` / `{passive:false}` / `{passive:true}`
- `mousedown` on container, `mousemove` / `mouseup` on `window`
- On each drag frame: creates a new `Map`, applies `mobiusTransform()` to all 40 positions (new `[x,y]` array per node), then calls `_pdUpdateSVGPositions()` (full: positions + rect sizes + z-sort)
- Momentum: velocity tracked per frame, decays 0.92× per rAF tick after release
- 8px dead zone before drag activates

#### `_pdUpdateSVGPositions` (v4 — full update every call)

For each node `<g>` element:
- `el.setAttribute('transform', 'translate(sx,sy)')` — SVG attribute
- Updates `rect x/y/width/height` for each rect child
- Updates `image x/y/width/height`
- Updates `pdState.screenPositions` cache
- Hides nodes not in current layout (`display:none`)

Then z-sorts all children via `appendChild` loop.
Then updates edge `<path d>` attributes.

#### Hit testing

`_pdHitTest(cx, cy)`: iterates `pdState.screenPositions`, finds node where `|dx| < r+8 && |dy| < r+8` (square bounds). Returns id of best match.

#### Detail panel

Slides up from bottom on root node tap — thumbnail (background-image), filename, caption, "view full" button.

#### Hover ring

Desktop only: a `#pd-hover-ring` SVG circle element tracks the hovered node. No tooltip text (removed in v4).

### 6.7 Critical Implementation Notes

#### Image loading — use background-image, NOT `<img>` or `new Image()`

Mobile Safari has severe bugs with `new Image()` and `<img src>` when loading many images concurrently through Cloudflare tunnel:

| Method | Result on Mobile Safari |
|--------|------------------------|
| `new Image(); img.src = url` | All stuck at loading forever |
| `img.crossOrigin = 'anonymous'` on same-origin | Makes it worse |
| `<img loading="lazy">` in CSS-transformed container | Never triggers |
| **`<div style="background-image:url(...)">`** | **Works** |

All thumbnail rendering in scatter and Poincaré uses CSS `background-image` on `<div>` elements. The `<image>` inside SVG `<g>` nodes also loads correctly.

#### Touch events on SVG

The `#pd-svg` element has `pointer-events:none` on itself and all children. All drag and tap handling is on `#view-poincare` (the container). This is essential: SVG `touchstart` handlers without passive mode delay or swallow touch events in iOS Safari, breaking the top-bar chip buttons.

#### Chip initialization

`_initScatterChips()` is called in `init()` at page load — before any view is shown. It must not be deferred to scatter init, because chips need to work when starting directly in Poincaré view.

#### Golden angle distribution

Poincaré nodes distributed at `rank × 2.399963` radians (≈137.5°). Guarantees even 360° coverage regardless of node count. Previous approach (sort by PCA angle, then evenly space) created C-arcs.

---

## 6.8 v4.1x Experimental Render Optimizations

v4.1x (op-viz-v4.1x.html, 2,640 lines) adds rendering optimizations on top of v4. **Not yet confirmed to improve smoothness in practice.** The current live `op-viz.html` is v4.1x. To revert to v4: `cp op-viz-v4.html op-viz.html` and restart.

### Changes from v4

#### CSS transform instead of SVG attribute

`el.style.transform = 'translate(Xpx,Ypx)'` instead of `el.setAttribute('transform', 'translate(X,Y)')`.

Rationale: CSS transforms on SVG elements go through the compositor and do not trigger SVG layout recalculation. SVG `transform` attribute changes force a full SVG reflow.

Affects: `_pdSVGFallback` (initial build) and `_pdUpdateSVGPositions` (updates).

#### `skipSizeAndSort` flag on `_pdUpdateSVGPositions`

New parameter: `_pdUpdateSVGPositions(positions, cx, cy, R, skipSizeAndSort)`.

When `skipSizeAndSort=true` (used during drag): only moves nodes (sets `style.transform`). Skips:
- Rect width/height/x/y attribute updates
- Image width/height/x/y attribute updates
- Z-sort (`appendChild` loop)

Z-sort and size updates only happen on drag end (full sync) and on non-drag renders.

#### `_pdGLDrawOnly` — lean GL render path during drag

New function. When WebGL atlas is loaded, drag frames:
1. Set `#pd-nodes-svg { visibility: hidden }` — zero DOM mutations during drag
2. Call `_pdComputeScreenPos()` to update hit-test cache
3. Call `_pdGLDrawOnly()` instead of `pdGLRender()`

`_pdGLDrawOnly` skips the SVG build/update entirely and goes straight to GL. On drag end, `_pdDragEnd()` calls full `_pdUpdateSVGPositions(..., false)` and restores SVG visibility.

#### Pre-allocated instance buffer

`_pdInstBuf`: a `Float32Array` allocated once at atlas load time (sized for N×1.5 nodes). Reused every GL frame via `gl.bufferSubData(gl.ARRAY_BUFFER, 0, _pdInstBuf, 0, i*6)` — no heap allocation per frame.

Buffer pre-sized with `gl.bufferData(..., STREAM_DRAW)` at atlas load. `STREAM_DRAW` is the correct hint for data updated every frame (vs `DYNAMIC_DRAW` for occasional updates).

#### Cached uniforms

Globals `_pdLastUniCx/Cy/R/W/H` track the last-uploaded uniform values. `gl.uniform*` calls only fire when values change. During drag, `cx/cy/R` are constant, so uniforms are uploaded zero times per drag frame.

#### rAF-throttled drag with accumulated delta

Previously: `touchmove` → `applyDragTransform()` → render immediately. On a 120Hz iPhone, touchmove fires at 120Hz but the screen refreshes at 60Hz — double work per visible frame.

Now: `touchmove` accumulates delta into `_pendingDx/_pendingDy` and schedules one `requestAnimationFrame(_flushDrag)`. Multiple touchmove events between frames are coalesced. `_flushDrag` runs once per frame.

#### In-place position mutation

Previously: `const np = new Map(); for(...) np.set(id, mobiusTransform(pos, a)); pdState.positions = np;`

Now: `for(const [id,pos] of pdState.positions) { const p=mobiusTransform(pos,_mVec); pos[0]=p[0]; pos[1]=p[1]; }`

Eliminates one `Map` allocation and 40 `[x,y]` array allocations per drag frame. Reduces GC pressure that can cause frame-rate stutters.

`_mVec = [0,0]`: reusable Möbius parameter vector, allocated once.

### Revert instructions

```bash
cp ~/claude/open-photo/op-viz-v4.html ~/claude/open-photo/op-viz.html
pkill -f op-server.py  # cron restarts within 60s
```

---

## 7. Known Issues & Constraints

### 7.1 Resolved

- ~~Scatter thumbnails not loading~~ — Fixed by switching from canvas/Image() to DOM divs with background-image
- ~~Poincaré pile-up / C-arc~~ — Fixed by golden angle distribution
- ~~Scatter initial positioning~~ — Fixed by auto-fit with camera lerp
- ~~PCA limited to 100 items~~ — Fixed by caching basis vectors and projecting N items onto them
- ~~Count chips not working in Poincaré~~ — Fixed by moving `_initScatterChips()` to `init()`
- ~~Marooned nodes~~ — Fixed by hiding nodes not in current layout (`display:none`)
- ~~Floating tooltip text in Poincaré~~ — Removed in v4
- ~~Z-ordering (nearest node buried under far nodes)~~ — Fixed by sorting on `vs` in v4

### 7.2 Active Infrastructure Constraints

- **CLIP broken on serve machine** — libstdc++ mismatch. Semantic text search and image search require GPU machine.
- **rclone stopped** — ~8,000 photos not yet transferred. Needs manual restart on GPU machine.
- **Face schema mismatch** — face_clusters on serve machine lacks columns the API expects. People view errors.
- **WAL file** — run `PRAGMA wal_checkpoint(TRUNCATE)` periodically.

### 7.3 Data Gaps

| Metric | Count |
|--------|-------|
| Total media | 5,952 |
| With CLIP embedding | 4,344 (73%) |
| With thumbnail | 4,344 (73%) |
| With taken_at date | 588 (10%) |
| With GPS | 388 (7%) |
| With caption | 4,344 (73%) |

Low taken_at coverage: most photos lack EXIF data and Google Photos JSON sidecar extraction was incomplete.

---

## 8. Roadmap

### 8.1 Near-term

- **Restart rclone** — finish Google Drive transfer; re-run ingest on remaining ~5k photos
- **Assess v4.1x** — determine if render optimizations provide real-world improvement; keep or revert
- **Text search UI** — search bar in header; GPU sidecar or FTS fallback on serve machine
- **Taken-at recovery** — parse Google Photos JSON sidecars for timestamps

### 8.2 Later

- **Face recognition** — migrate full face schema from GPU machine; run clustering; enable People view
- **Collections UI** — create/manage named collections (schema exists, no UI)
- **iOS PWA** — manifest + service worker for home screen install
- **Video playback** — `<video>` player in detail view (currently shows thumbnail only)
- **Full data transfer** — complete ingest, recompute layout, reconsider UMAP vs PCA

---

## 9. Developer Quick Reference

### 9.1 SSH Access

```bash
# Serve machine
ssh -p 4640 jfischer@ceto.languageweaver.com

# GPU machine (from serve machine or VPN)
ssh ec2-user@172.18.71.210
```

### 9.2 Server Management

```bash
# Start server
cd ~/claude/open-photo && PYTHONPATH="" python3 -u op-server.py >> server.log 2>&1 &

# Check status
pgrep -f op-server.py && curl -s http://localhost:8260/api/stats | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['total'],'photos')"

# Restart (let cron handle it)
pkill -f op-server.py

# Tail logs
tail -f ~/claude/open-photo/server.log
```

### 9.3 Database

```bash
# Quick stats
sqlite3 ~/claude/open-photo/op.db \
  "SELECT COUNT(*), COUNT(clip_embedding), COUNT(taken_at) FROM media"

# Checkpoint WAL
sqlite3 ~/claude/open-photo/op.db "PRAGMA wal_checkpoint(TRUNCATE)"

# Clear layout cache
sqlite3 ~/claude/open-photo/op.db "UPDATE media SET layout_x=NULL, layout_y=NULL"
curl "https://openphoto.fahrenheitrequited.dev/api/layout?recompute=true"
```

### 9.4 File Locations (serve machine)

| File | Path |
|------|------|
| Server | ~/claude/open-photo/op-server.py |
| Frontend | ~/claude/open-photo/op-viz.html |
| Database | ~/claude/open-photo/op.db |
| Thumbnails | ~/claude/open-photo/uploads/ |
| Import script | ~/claude/open-photo/do-import.sh |
| Server log | ~/claude/open-photo/server.log |
| Stable backup | ~/claude/open-photo/op-viz-v4.html |
| Experimental backup | ~/claude/open-photo/op-viz-v4.1x.html |

### 9.5 File Locations (GPU machine)

| File | Path |
|------|------|
| Photos | /home/ec2-user/open-photo/ |
| Database | /home/ec2-user/op.db |
| Conda env | openphoto (Python 3.10) |
| rclone log | /home/ec2-user/rclone.log |

*— end of spec —*
