# Open Photo — System Specification v4.0

*Updated March 2026 · covers frontend v7 (current live), infrastructure as of March 10 2026*

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
- **op-server.py** → FastAPI, port 8260, serves API + static files from serve machine
- **op-viz.html** → single-file frontend, ~3,211 lines (v7 current), served at /
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
| v4 | op-viz-v4.html | 2,546 | Stable baseline — tooltip removed, all bugs fixed |
| v4.1x | op-viz-v4.1x.html | 2,640 | Experimental render optimizations |
| v5 | — | ~2,800 | NSFW filter, people filter, face sidebar, similar panel |
| v6 | — | ~3,000 | Scatter/Poincaré chip filtering, stagger perf, dual-handle time scrubber |
| **v7** | **op-viz.html** | **3,211** | **Current live — time scrubber drag handles, filter unification** |

**Stable backup:** `op-viz-v4.html` is the last known-good pre-filter version. To revert: `cp op-viz-v4.html op-viz.html && pkill -f op-server.py`.

---

## 3. Data Model

### 3.1 media table — 9,710 rows (as of March 2026)

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
| is_nsfw | INTEGER | 1 if flagged by caption heuristics, else 0 |
| has_faces | INTEGER | 1 if in a face cluster, else 0 |

**`is_nsfw` flagging:** caption keyword heuristics applied at ingest. Keywords include: refusal phrases ("I'm sorry"), lingerie, fishnet, nude, naked, topless, underwear, provocatively, erotic, sexually, bikini, explicit content, revealing outfit, corset, garter, stockings. `bra` excluded (too broad). ~397 photos flagged as of March 2026. This is a heuristic — a proper vision classifier should replace it at next full re-ingest.

### 3.2 faces / face_clusters

- 669 faces, 28 clusters, 0 named (as of March 2026)
- Face sidebar shows clusters with valid thumbnails; clusters with no on-disk thumbnail are hidden
- `cover_thumb` falls back to any face in cluster with thumbnail present on disk; `None` if none found
- Face embeddings exist but are not used for similarity (all similarity is CLIP-based)

### 3.3 collections / collection_media

Schema exists, no UI yet.

### 3.4 FTS index

FTS5 virtual table `media_fts` on (id, label, caption, ocr_text, geo_name). Built on import from GPU machine. **Note:** the FTS5 table uses `WITHOUT ROWID` syntax that requires SQLite ≥ 3.37. The system Python sqlite3 on c-jfischer3 may fail to open the DB directly — use the server API or the agent conda env instead.

---

## 4. Ingest Pipeline (GPU Machine)

### 4.1 Source data

```bash
nohup rclone copy "gdrive:Google Photos" /home/ec2-user/open-photo/ \
  --progress --transfers=8 --checkers=16 >> ~/rclone.log 2>&1 &
disown
```

As of March 2026: ~9,710 photos/videos on serve machine. rclone stopped before completing full Takeout; Google Takeout export kicked off March 10 2026 (email delivery pending).

### 4.2 CLIP embedding

- **Model:** ViT-B/32 via open_clip, pretrained="openai"
- **Device:** CUDA on g5.16xlarge (A10G GPU)
- **Output:** 512-dim float32 vector, L2-normalized, stored as raw bytes in clip_embedding
- **Thumbnail:** 512×512 JPEG, quality=85, stored in uploads/
- **Caption:** GPT-4o Vision, stored in caption column
- **Embedding index:** 7,015 entries loaded at server startup

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

### 4.4 Post-import steps

After any new import:
1. Run `is_nsfw` flagging script (caption keyword scan)
2. Run `has_faces` backfill (join media → faces → face_clusters)
3. Recompute PCA layout: `GET /api/layout?recompute=true`
4. Checkpoint WAL: `sqlite3 op.db "PRAGMA wal_checkpoint(TRUNCATE)"`

---

## 5. Backend API (op-server.py)

### 5.1 Startup

- **CLIP model** — fails gracefully (libstdc++ mismatch on serve machine)
- **Embedding index** — 7,015 entries loaded into `_embeddings_cache` at startup
- **PCA basis** — computed once from first 100 items, cached. Additional items projected onto same basis vectors.
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
| GET | /api/photos | All media as lightweight nodes (includes is_nsfw, has_faces) |
| GET | /api/media/{id} | Full record + faces. Boosts temperature. |
| PATCH | /api/media/{id} | Update label, caption, or status |
| DELETE | /api/media/{id} | Delete record |
| GET | /api/similar/{id}?limit=24 | Top-N cosine-similar photos (filters no-thumbnail results) |
| GET | /api/media/{id}/similarities | Cosine similarity vs ALL (used by Poincaré layout) |
| GET | /api/search?q=&mode=&limit= | Text search (semantic/fts/combined) |
| POST | /api/upload | Ingest new photo |
| GET | /api/timeline | Paginated chronological list |
| GET | /api/timeline/years | Monthly counts |
| GET | /api/map | All geotagged media |
| GET | /api/clusters?n=12 | Agglomerative clustering |
| GET | /api/people | Face clusters (cover_thumb fallback; hides clusters with no thumbnail on disk) |
| GET | /api/albums | Album list with counts |
| GET | /api/collections | User collections |

---

## 6. Frontend (op-viz.html)

### 6.1 Overview

No build step, no framework. Vanilla JS, CSS for scatter, SVG for Poincaré geometry. All state in global JS variables. Two primary views (scatter, poincaré); gallery/timeline/people/map exist but are hidden from nav.

### 6.2 Design System

| Token | Value | Notes |
|-------|-------|-------|
| --bg | #0c0b09 | Near-black warm dark |
| --bg2 | #141210 | Secondary |
| --bg3 | #1c1a16 | Surface (nav pills) |
| --border | #2e2b22 | Divider lines |
| --text | #e8e4dc | Primary text |
| --text-dim | #8a8275 | Dimmed text |
| --accent | #d4a853 | Amber — highlights, root node border, handle color |
| --font | DM Sans | Body |
| --serif | Playfair Display | Logo (italic) |
| --mono | JetBrains Mono | Nav tabs, timestamps |

### 6.3 Layout

- **Top bar** — 56px fixed, gradient fadeout. Contains: logo, nav tabs (scatter/poincaré), search button, stats chip, count chips
- **Mobile** — top bar wraps to two rows; views pushed to `top:80px`; search + stats hidden
- **Views** — `#views` is `position:fixed; inset:0; top:56px`. Views are `.view` divs toggled with `.active` class.
- **`#view-poincare`** and **`#view-scatter`** are `position:absolute; inset:0` within `#views`.

### 6.4 Count Chips

Five mutually exclusive buttons in the top bar: **100, 300, 900, 2.7k, max**. Default: 100.

- Initialized at page load in `init()` via `_initScatterChips()` — not lazily inside scatter init. Critical: chips must work from Poincaré view even if scatter has never loaded.
- Controls `/api/embedding-layout?limit=N` for scatter tile count
- Controls `PD_MAX_NODES` in Poincaré
- Switching chips: resets Poincaré similarity cache (`_pdSimCache = {}`), reloads scatter or Poincaré depending on current view

### 6.5 People/NSFW Filter Chips

Three mutually exclusive chips: **all / safe / people**. State stored in `_scatterPeopleFilter`.

| Value | Behavior |
|-------|----------|
| `"all"` | Show everything including NSFW |
| `"safe"` | Hide photos where `is_nsfw === true` |
| `"people"` | Show only `has_faces === true && is_nsfw !== true` |

- Applied in scatter via `_renderScatterTiles()` — filters the in-memory `_scatterNodes` array, no re-fetch
- Applied in Poincaré via `pdComputeLayout()` — filters `allNodes` before layout
- Applied to jump pool and demo pool via `_filteredPool()` helper
- Chip click in Poincaré calls `pdComputeLayout(pdState.centerId).then(() => renderPoincareGraph())`

### 6.6 Scatter View

**Architecture:** DOM-based. Photo thumbnails are `<div class="scatter-tile">` elements with `background-image` (NOT `<img>`, NOT canvas). All tiles are children of `#scatter-field`, positioned with a single CSS `transform: translate() scale()`.

**Initialization split:**
- `initScatter()` — fetches `/api/photos`, builds `_scatterNodes` array, calls `_renderScatterTiles()`. Runs once.
- `_renderScatterTiles()` — filters nodes by `_scatterPeopleFilter`, creates/updates DOM elements. Called on filter chip changes without re-fetching.

**Camera system:** `_scatterTarget` (input writes) and `_scatterCam` (rendered). Continuous rAF loop lerps cam toward target at 15% per frame (`CAM_LERP = 0.15`). Smooth decelerating motion on all interactions.

**Auto-fit:** On load, computes bounding box of all node positions, sets target k/x/y to fit with 40px padding.

**Stagger entry:** `setTimeout(() => el.classList.add('loaded'), 30 + Math.min(i * 2, 800))` ms — capped at 830ms max delay (previously `i * 8` caused 40s delays at 5,000 nodes).

**Interactions:**
- Pan: mousedown/mousemove drag; 1-finger touch
- Zoom: wheel (desktop); 2-finger pinch — zooms toward pointer/midpoint
- Tap tile: enter Poincaré for that photo

### 6.7 Time Scrubber

Dual-handle range control for filtering by year. State: `_timeStart`, `_timeEnd` (defaults 2003–2026).

**HTML structure:**
```html
<div id="time-scrubber">           <!-- position:relative, user-select:none -->
  <div id="time-track">            <!-- horizontal bar, 8px inset on each side -->
  <div id="time-fill">             <!-- amber fill between handles -->
  <div id="time-handle-start">     <!-- draggable left handle (amber square, border-radius:3px) -->
  <div id="time-handle-end">       <!-- draggable right handle -->
  <div id="time-label-start">      <!-- year label below left handle -->
  <div id="time-label-end">        <!-- year label below right handle -->
</div>
```

**Position math:** `pad = 8px`. `usable = scrubber.offsetWidth - 16`. Handle pixel position = `pad + ((yr - TIME_MIN) / (TIME_MAX - TIME_MIN)) * usable`.

**Drag:** `_initTimeDrag(handle, isStart)`. On `mousedown`/`touchstart`, attaches document-level `mousemove`/`touchmove`. Clamps year to `[TIME_MIN, TIME_MAX]`, enforces minimum gap of 1 year between handles. Calls `_updateTimeScrubber()` + `_applyTimeFilter()` on each move.

**Filter behavior:**
- Scatter: nodes with `yr < _timeStart || yr > _timeEnd` get `opacity:0.05` and `pointer-events:none`
- Photos with no `taken_at` date (`yr === 0`) are not hidden
- Poincaré: triggers `renderPoincareGraph()` if active

### 6.8 Face Sidebar

Fixed left panel (`#face-sidebar`), hidden by default. Opened via people icon in top bar.

- Loads from `/api/people?limit=200`
- Clusters with no `cover_thumb` (no thumbnail on disk) are skipped entirely
- Avatar shape: sharp squares (`border-radius:4px`), not circles
- Face bbox cap: `faceSize = Math.min(Math.max(bw, bh), 300)` — prevents pathologically large bboxes from making background-size tiny
- Clicking a person: calls `enterPoincareView(person.cover_id)` to jump to their most recent photo

### 6.9 Detail Panel & Similar Photos

Slides up from bottom on root node tap in Poincaré, or on scatter tile tap.

- Thumbnail via `background-image` (not `<img>`)
- Similar photos grid: fetches `/api/similar/{id}?limit=12`, filters out items with no `thumbnail_path`
- Clicking similar thumb: calls `openDetail(item.id)` — updates panel in-place with new photo + new similar grid
- Clicking main thumbnail: navigates to Poincaré. Fixed race condition: `const id = _currentMediaId; closeDetail(); enterPoincareView(id)` — captures id before closeDetail nulls it

### 6.10 Poincaré Disk View

#### Layout algorithm

When entering Poincaré for photo X:
1. Fetch `/api/media/{id}/similarities` — cosine scores for all photos
2. Filter by `_scatterPeopleFilter` (all/safe/people)
3. Sort descending, take top `PD_MAX_NODES` (= `_scatterLimit`, capped at 200)
4. Assign hyperbolic radius by rank: `r = 0.08 + (rank/(N-1)) * 0.64` → range [0.08, 0.72]
5. Assign angle: `angle = rank × 2.399963 radians` (golden angle ≈137.5°)
6. Position: `[cos(a) * r, sin(a) * r]` in Poincaré disk coordinates

#### Size and visual scale

`vs = max(1 - (x²+y²), 0.01)` — approaches 1 at center, 0 at boundary.
`nr = MIN_R + (MAX_R - MIN_R) × vs^1.8` — MIN_R=2, MAX_R=38.
Root node gets `max(nr, min(64, R×0.22))`. Nodes with `vs < 0.005` are hidden.

#### Navigation (Möbius fly-through)

1. **Fly (500ms):** Hyperbolic interpolation via `atanh`/`tanh` with easeInOut. CSS transitions disabled during flight.
2. **Recompute:** Fetch new similarity data, apply filter, compute fresh layout.
3. **Settle (400ms):** Nodes created at clean positions, Möbius-moved to end-of-flight positions, then smoothstep-lerped back.

#### Möbius drag

- Events on `#view-poincare` container (not SVG — SVG has `pointer-events:none`)
- 8px dead zone before drag activates
- Momentum: velocity tracked per frame, decays 0.92× per rAF tick after release
- In-place position mutation (no Map/array allocation per frame)

#### Rendering (SVG + optional WebGL2)

SVG layer: disk boundary, glow, geodesic arcs, node `<g>` elements. CSS `transform` (not SVG `transform` attribute) for position — avoids SVG reflow.

WebGL2 layer (optional): instanced quads, atlas texture, single draw call. Falls back to SVG-only if unavailable. During drag: SVG nodes hidden, GL renders only, SVG rebuilt on drag end.

---

## 7. Critical Implementation Notes

### Image loading — always background-image

Mobile Safari + Cloudflare silently breaks `new Image()`, `<img src>`, and `crossOrigin='anonymous'` on same-origin loads when loading many images concurrently.

| Method | Result on Mobile Safari |
|--------|------------------------|
| `new Image(); img.src = url` | Stuck loading forever |
| `img.crossOrigin = 'anonymous'` on same-origin | Makes it worse |
| `<img loading="lazy">` in CSS-transformed container | Never triggers |
| **`<div style="background-image:url(...)">`** | **Works** |

All thumbnail rendering uses CSS `background-image` on `<div>`. SVG `<image>` elements also load correctly.

### CSS transitions vs rAF

Disable CSS transitions on animated elements during rAF loops. Re-enable after. They fight each other and cause jerky motion. Applied in Poincaré fly-through and drag.

### Touch events on SVG

`#pd-svg` has `pointer-events:none` on itself and all children. All drag and tap handling is on `#view-poincare` (the container). Essential for iOS Safari — SVG touch handlers without passive mode delay or swallow top-bar chip button touches.

### Process management

Never `killall python3` — kills rwx-server too. Kill by name: `pkill -f op-server.py`. Never `pkill -f cloudflared` — kills all tunneled services.

---

## 8. Known Issues & Status

### 8.1 Resolved (as of v7)

- ~~Scatter thumbnails not loading~~ — background-image fix
- ~~Poincaré pile-up / C-arc~~ — golden angle distribution
- ~~Count chips not working in Poincaré~~ — `_initScatterChips()` moved to `init()`
- ~~Marooned nodes~~ — `display:none` for nodes not in layout
- ~~Floating tooltip~~ — removed in v4
- ~~Z-ordering~~ — sorted by `vs`
- ~~Face sidebar blank avatars~~ — server-side fallback + client-side skip on null cover_thumb
- ~~Similar panel navigation~~ — race condition fixed, clicking similar updates panel in-place
- ~~Scatter stagger delay~~ — delay capped at 830ms regardless of node count
- ~~Filter chips not affecting Poincaré layout~~ — `_scatterPeopleFilter` applied in `pdComputeLayout()`
- ~~Time scrubber single-thumb (couldn't set range)~~ — replaced with dual drag handles

### 8.2 Active Infrastructure Constraints

- **CLIP broken on serve machine** — libstdc++ mismatch. Semantic text search and `/api/similar` use precomputed index only; new photo ingest requires GPU machine.
- **rclone incomplete** — Google Takeout export in progress (kicked off March 10 2026). Remaining photos not yet ingested.
- **System sqlite3 incompatible** — FTS5 `WITHOUT ROWID` syntax requires newer SQLite than system python3 has. Use server API or conda `agent` env for DB access.
- **WAL file** — run `PRAGMA wal_checkpoint(TRUNCATE)` periodically.

### 8.3 Data State (March 2026)

| Metric | Count |
|--------|-------|
| Total media | 9,710 |
| With CLIP embedding | 7,015 (72%) |
| With thumbnail | ~7,015 (72%) |
| With taken_at date | ~10% (est.) |
| With GPS | 457 (5%) |
| With caption | 7,015 (72%) |
| NSFW flagged | ~397 (4%) |
| Face clusters | 28 |
| Named clusters | 0 |

---

## 9. Roadmap

### 9.1 Near-term

- **Complete Takeout ingest** — receive email, download, run rclone/ingest on remaining photos; re-run NSFW flagging and `has_faces` backfill
- **GPU SSH fix** — restore access to 172.18.71.210 for re-ingest pipeline
- **Text search UI** — search bar in header; FTS fallback on serve machine while CLIP is broken
- **Taken-at recovery** — parse Google Photos JSON sidecars for timestamps; ~90% of photos lack dates
- **Face naming** — UI exists in people sidebar (currently unused); 0 of 28 clusters named

### 9.2 Later

- **NSFW vision classifier** — replace caption heuristics with a proper image classifier at re-ingest time
- **Collections UI** — create/manage named collections (schema exists, no UI)
- **iOS PWA** — manifest + service worker for home screen install
- **Video playback** — `<video>` player in detail view (currently shows thumbnail only)
- **UMAP vs PCA** — evaluate UMAP for scatter layout at full corpus size; PCA at 9k+ may lose nuance
- **Search result navigation** — enter Poincaré from search results

---

## 10. Developer Quick Reference

### 10.1 SSH Access

```bash
# Serve machine
ssh -p 4640 jfischer@ceto.languageweaver.com

# GPU machine (from serve machine or VPN)
ssh ec2-user@172.18.71.210
```

### 10.2 Server Management

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

### 10.3 Database

```bash
# Quick stats (use server API — system sqlite3 may fail on FTS5)
curl -s http://localhost:8260/api/stats

# Checkpoint WAL (use conda agent env)
/home/jfischer/miniconda3/envs/agent/bin/python3 -c \
  "import sqlite3; sqlite3.connect('op.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"

# Clear layout cache
curl "https://openphoto.fahrenheitrequited.dev/api/layout?recompute=true"
```

### 10.4 Deploy Frontend

```bash
# Edit on server via dev tools, then:
pkill -f op-server.py   # cron restarts within 60s
# Hard-refresh browser (Cmd+Shift+R)
```

### 10.5 File Locations (serve machine)

| File | Path |
|------|------|
| Server | ~/claude/open-photo/op-server.py |
| Frontend | ~/claude/open-photo/op-viz.html |
| Database | ~/claude/open-photo/op.db |
| Thumbnails | ~/claude/open-photo/uploads/ |
| Import script | ~/claude/open-photo/do-import.sh |
| Server log | ~/claude/open-photo/server.log |
| Stable backup | ~/claude/open-photo/op-viz-v4.html |
| Spec (this file) | ~/claude/open-photo/open-photo-spec-v4.md |

### 10.6 File Locations (GPU machine)

| File | Path |
|------|------|
| Photos | /home/ec2-user/open-photo/ |
| Database | /home/ec2-user/op.db |
| Conda env | openphoto (Python 3.10) |
| rclone log | /home/ec2-user/rclone.log |

*— end of spec —*
