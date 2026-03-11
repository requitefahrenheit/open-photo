# Open Photo — System Specification v2.0

*Updated March 9, 2026*

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
- **Transfer** → sqlite3 .dump media | scp → do-import.sh on serve machine
- **op-server.py** → FastAPI, port 8260, serves API + static files from serve machine (736 lines)
- **op-viz.html** → single-file frontend, ~2,336 lines, served at /. No build step, no framework.
- **op.db** → SQLite WAL, single source of truth for media metadata + embeddings
- **uploads/** → thumbnail JPEGs, 512x512 max, served at /uploads/

### 2.3 Process Management

The server is kept alive by a cron watchdog that runs every minute:

```
* * * * * pgrep -f op-server.py > /dev/null \
  || (cd ~/claude/open-photo && PYTHONPATH="" python3 -u op-server.py >> server.log 2>&1 &)
```

**Important:** always start the server with `PYTHONPATH=""`. The default PYTHONPATH on c-jfischer3 points to a broken torchvision install that causes import failures even when torch is not used.

### 2.4 Version History

| Version | File | Description |
|---------|------|-------------|
| v1.0 | op-viz-v1.html, op-server-v1.py | First working version with DOM scatter + Poincaré |
| v2.5-inprogress | op-viz-v2.5-inprogress.html | Canvas-based scatter (broken thumbnails) |
| current | op-viz.html, op-server.py | DOM scatter + HTML Poincaré + smooth animation |

---

## 3. Data Model

*(Unchanged from v1.0 — see original spec for full schema)*

### 3.1 media table — 5,952 rows

Key columns: id (12-char hex), media_type, label, caption (GPT-4o), clip_embedding (512-dim ViT-B/32), thumbnail_path, taken_at, geo_lat/lon/name, album, layout_x/layout_y (PCA cache), temperature, visit_count.

### 3.2 faces / face_clusters — schema exists but not fully migrated

### 3.3 collections / collection_media — schema exists, no UI

---

## 4. Ingest Pipeline (GPU Machine)

*(Unchanged from v1.0)*

As of March 2026: ~5,952 photos/videos ingested, ~8,000 remaining (rclone died and needs restart).

---

## 5. Backend API (op-server.py)

### 5.1 Startup

- **CLIP model** — fails gracefully (libstdc++ mismatch on serve machine)
- **Embedding index** — 4,344 entries loaded into `_embeddings_cache` dict at startup (~15s)
- **PCA basis** — computed once from first 100 items, cached in `_pca_basis` global. Additional items projected onto the same basis vectors.
- **Temperature decay** — background task, hourly, multiplies temperature × 0.9

### 5.2 Layout / PCA

PCA is computed via numpy SVD. The basis vectors (mean + top-2 components) are computed from the first 100 items and cached. Subsequent requests with higher limits (300, 900, 2700) project onto the same basis — no re-SVD needed. Results are normalized to [0,1] with outlier clamping.

**The `?limit=` parameter** controls how many items are projected. This is used by the frontend's count chips.

### 5.3 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | / | Serve op-viz.html |
| GET | /uploads/{filename} | Serve thumbnail JPEG |
| GET | /api/stats | DB counts and per-year breakdown |
| GET | /api/layout?limit=100&recompute=false | PCA 2D positions. Recompute clears basis. |
| GET | /api/embedding-layout?limit=100 | PCA positions in {positions: {id: [x,y]}} shape |
| GET | /api/photos | All media as lightweight nodes |
| GET | /api/media/{id} | Full media record + faces. Side effect: boosts temperature |
| PATCH | /api/media/{id} | Update label, caption, or status |
| DELETE | /api/media/{id} | Delete media record |
| GET | /api/similar/{id}?limit=24 | Top-N cosine-similar photos |
| GET | /api/neighbors/{id} | Same as similar |
| GET | /api/media/{id}/similarities | Cosine similarity vs ALL others (used by Poincaré layout) |
| GET | /api/search?q=&mode=&limit= | Text search (semantic/fts/combined) |
| POST | /api/search-by-image | Multipart upload; cosine search (requires CLIP) |
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

~2,336 lines. No build step, no framework. Uses vanilla JS, CSS transforms for scatter, SVG for Poincaré geometry, HTML divs with `background-image` for all photo thumbnails. All state is in global JS variables.

### 6.2 Design System

| Token | Value | Notes |
|-------|-------|-------|
| --bg | #0c0b09 | Near-black warm dark |
| --bg2 | #141210 | Secondary |
| --bg3 | #1c1a16 | Surface (nav pills) |
| --border | #2e2b22 | Divider lines |
| --text | #e8e4dc | Primary text |
| --text-dim | #8a8275 | Dimmed text |
| --accent | #d4a853 | Amber — highlights |
| --font | DM Sans | Body |
| --serif | Playfair Display | Logo (italic) |
| --mono | JetBrains Mono | Nav tabs, timestamps |

### 6.3 Layout

- **Top bar** — fixed, gradient fadeout. Contains: logo, nav tabs (scatter/poincaré), search button, stats chip, count chips (100/300/900/2.7k)
- **Mobile** — top bar wraps to two rows. Search button and stats chip hidden. Views pushed down to `top:80px`.
- **Immersive mode** — on mobile, scatter + poincaré go `position:fixed; inset:0; z-index:50`

### 6.4 Count Chips

Four mutually exclusive buttons in the top bar: **100, 300, 900, 2.7k**. Default: 100. Controls:
- How many photos the `/api/embedding-layout?limit=N` endpoint returns for the scatter
- How many nodes the Poincaré disk considers (`PD_MAX_NODES = limit × 0.8`, capped at 200)
- Switching chips fades out existing tiles (300ms), reloads scatter, and resets the Poincaré similarity cache

### 6.5 Scatter View

**Architecture:** DOM-based. Photo thumbnails are `<div>` elements with `background-image` (NOT `<img>` tags, NOT canvas — see Section 8.1 for why). All tiles are children of `#scatter-field`, which is positioned with a single CSS `transform: translate() scale()`.

**Camera system:** Split into `_scatterTarget` (input writes) and `_scatterCam` (rendered). A `requestAnimationFrame` loop lerps cam toward target by 15% per frame (`CAM_LERP = 0.15`). This produces smooth, decelerating motion on all interactions.

**Auto-fit:** On load, computes bounding box of all node positions and sets target k/x/y to fit with 40px padding. First load snaps (no animation); resize triggers smooth glide.

**Hover:** CSS `transition: transform 0.18s ease` + `:hover { transform: scale(2.2); z-index:100 }`. Golden glow + shadow.

**Staggered entry:** Tiles start at `opacity:0`, then stagger-fade-in with `setTimeout(() => el.classList.add('loaded'), 30 + i * 8)`.

**Interactions:**
- Pan: mousedown/mousemove drag; 1-finger touch
- Zoom: wheel (desktop); 2-finger pinch (mobile) — zooms toward pointer/midpoint
- Tap tile: enter Poincaré view for that photo
- Hover (desktop): tooltip with date + caption

### 6.6 Poincaré Disk View

**Architecture:** Hybrid SVG + HTML. SVG renders the disk boundary circle, center glow, and geodesic arcs to top-5 neighbors. Photo thumbnails are HTML `<div>` elements with `background-image` in a sibling overlay div (`#pd-nodes-html`), using `transform: translate(-50%, -50%)` for centering.

**Layout algorithm:** When entering Poincaré for photo X:
1. Fetch `/api/media/{id}/similarities` — cosine scores for all photos
2. Sort by similarity desc, take top `PD_MAX_NODES`
3. Assign hyperbolic radius by rank: `r = 0.08 + rNorm * 0.82`
4. Assign angle by **golden angle** distribution: `angle = rank × 2.399963 radians`
5. Position: `[cos(a) * r, sin(a) * r]`

**Size falloff:** `nr = MIN_R + (MAX_R - MIN_R) × vs^1.8` where `vs = max(1 - r², 0.01)`. The exponent 1.8 makes outer nodes much smaller than inner. MIN_R=2, MAX_R=38. Root node gets a bonus: `min(64, R*0.22)`.

**Hover:** JS-driven grow. Hovered node expands to `max(naturalR, min(44, diskR×0.14))`, gets `pd-hovered` class for glow, and is `appendChild`'d to front of container. CSS transition on width/height (0.25s ease). On touch: grow on touchstart, shrink after 300ms delay on touchend.

**Navigation (Möbius fly-through):**
1. **Fly (500ms):** Hyperbolic interpolation via `atanh`/`tanh` with easeInOut timing. All node positions transformed per frame via Möbius transform. CSS transitions disabled.
2. **Recompute:** Fetch new similarity data, compute fresh golden-angle layout.
3. **Settle (400ms):** `renderPoincareGraph()` creates nodes at clean positions, then immediately moves them to Möbius end positions and smoothstep-lerps into clean layout.

**Möbius drag (swipe navigation):** Swiping on empty space applies a Möbius transform to all positions, panning through hyperbolic space. Momentum: velocity tracked per frame, decays 0.92× after release. Touch support with identifier tracking and 8px dead zone.

**Detail panel:** Slides up from bottom on root tap — thumbnail (background-image), filename, caption, "view full" button.

### 6.7 Other Views (hidden from nav)

Gallery, timeline, people, map views exist in the codebase but are hidden from the nav tabs. Map uses Leaflet.

---

## 7. Critical Implementation Details

### 7.1 Image Loading — Use background-image, Not <img> or new Image()

Mobile Safari has severe bugs with `new Image()` and `<img src>` when loading many images concurrently through Cloudflare tunnel:

| Method | Result on Mobile Safari |
|--------|------------------------|
| `new Image(); img.src = url` | All stuck at loading state forever |
| `img.crossOrigin = 'anonymous'` on same-origin | Makes it worse |
| `<img loading="lazy">` in CSS-transformed container | Never triggers |
| **`<div style="background-image:url(...)">`** | **Works** |

All thumbnail rendering in both scatter and Poincaré uses CSS `background-image` on `<div>` elements. The `<img>` tag is not used anywhere for thumbnails.

### 7.2 Camera Lerp System

Input events write to `_scatterTarget`. A continuous rAF loop lerps `_scatterCam` toward target:
```
cam.x += (target.x - cam.x) * 0.15
```
This produces smooth, decelerating motion. Same pattern as OpenMind's `cam += (targetCam - cam) * 0.1`.

### 7.3 Golden Angle Distribution

Poincaré nodes are distributed at `rank × 2.399963` radians (≈137.5°). This guarantees even coverage of the full 360° regardless of node count. Previous approach (sort by PCA angle, then evenly space) created C-arcs.

### 7.4 Transitions vs rAF Animations

CSS transitions on `.pd-html-node` (for hover grow) must be disabled during Möbius fly-through and drag, otherwise CSS and JS fight. Pattern: `node.style.transition = 'none'` before rAF loop, restore `''` after.

---

## 8. Known Issues & Constraints

### 8.1 Resolved (since v1.0)

- ~~Scatter thumbnails not loading~~ — Fixed by switching from canvas/Image() to DOM divs with background-image
- ~~Poincaré pile-up / C-arc~~ — Fixed by golden angle distribution
- ~~Scatter initial positioning~~ — Fixed by auto-fit with camera lerp
- ~~PCA limited to 100 items~~ — Fixed by caching basis vectors and projecting N items onto them

### 8.2 Active Infrastructure Constraints

- **CLIP broken on serve machine** — libstdc++ mismatch. Semantic text search and image search require GPU machine.
- **rclone stopped** — ~8,000 photos not yet transferred. Needs manual restart.
- **Face schema mismatch** — face_clusters on serve machine lacks columns the API expects.
- **WAL file size** — needs periodic `PRAGMA wal_checkpoint(TRUNCATE)`.

### 8.3 Data Gaps

| Metric | Count |
|--------|-------|
| Total media | 5,952 |
| With CLIP embedding | 4,344 (73%) |
| With thumbnail | 4,344 (73%) |
| With taken_at date | 588 (10%) |
| With GPS | 388 (7%) |
| With caption | 4,344 (73%) |

---

## 9. Roadmap

### 9.1 Near-term

- **Restart rclone** — finish Google Drive transfer; re-run ingest on remaining ~5k photos
- **Text search UI** — search bar in header; GPU sidecar or FTS fallback
- **Taken-at recovery** — parse Google Photos JSON sidecars for timestamps
- **Full data transfer** — complete ingest, transfer, recompute layout

### 9.2 Later

- **Face recognition** — migrate full face schema; enable People view
- **Collections UI** — create/manage named collections
- **iOS PWA** — manifest + service worker for home screen install
- **Video playback** — add `<video>` player in detail view
- **Performance at 2700+** — outline squares below 16px screen size; viewport culling

---

## 10. Developer Quick Reference

### 10.1 SSH Access

```bash
# Serve machine
ssh -p 4640 jfischer@ceto.languageweaver.com

# GPU machine (from serve machine)
ssh ec2-user@172.18.71.210
```

### 10.2 Server Management

```bash
# Start server
cd ~/claude/open-photo && PYTHONPATH="" python3 -u op-server.py >> server.log 2>&1 &

# Check status
pgrep -f op-server.py && curl -s http://localhost:8260/api/stats | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['total'],'photos')"

# Restart (kill, let cron restart within 60s)
pkill -f op-server.py

# Force restart of RWX dev server (if MCP tools stop working)
bash ~/claude/rwx/kick-off.sh
```

### 10.3 File Locations (serve machine)

| File | Path |
|------|------|
| Server | ~/claude/open-photo/op-server.py |
| Frontend | ~/claude/open-photo/op-viz.html |
| Database | ~/claude/open-photo/op.db |
| Thumbnails | ~/claude/open-photo/uploads/ |
| Server log | ~/claude/open-photo/server.log |
| v1 backup (server) | ~/claude/open-photo/op-server-v1.py |
| v1 backup (frontend) | ~/claude/open-photo/op-viz-v1.html |
| Animation skill | ~/claude/skills/smooth-web-animation/SKILL.md |

*— end of spec —*
