# Open Photo — Thread Orientation

*Read this first when starting a new thread in the Open Photo project.*

## What This Is

Open Photo is a self-hosted photo archive that displays ~6,000 photos from Google Photos in two zoomable views: a **PCA scatter map** and a **Poincaré hyperbolic disk**. It runs on a serve machine (c-jfischer3) as a FastAPI server + single-file HTML frontend, proxied via Cloudflare tunnel to https://openphoto.fahrenheitrequited.dev.

## How to Access the Code

All code lives on c-jfischer3 and is accessed via MCP dev tools (`dev:dev_read_file`, `dev:dev_patch_file`, `dev:dev_run`, etc.). The project files `open-photo-spec.docx` and `CLAUDE_open_mind_spec.pdf` in the Claude Project are READ-ONLY reference — the live code is on the server.

```
~/claude/open-photo/op-server.py     # FastAPI server (736 lines)
~/claude/open-photo/op-viz.html      # Frontend (2,336 lines)
~/claude/open-photo/op.db            # SQLite database
~/claude/open-photo/uploads/         # Thumbnail JPEGs
~/claude/open-photo/server.log       # Server logs
```

Updated spec: `~/claude/open-photo/open-photo-spec-v2.md`

## Architecture Summary

**Server:** FastAPI on port 8260. Loads 4,344 CLIP embeddings into memory at startup (~15s). Serves PCA layouts via `/api/embedding-layout?limit=N` where N = 100/300/900/2700. PCA basis computed once from first 100 items, all others projected onto it. Cosine similarity for Poincaré via `/api/media/{id}/similarities`.

**Frontend:** Single HTML file, no build step. Two views:

1. **Scatter** — DOM-based. `<div>` tiles with `background-image` inside a CSS-transformed container (`#scatter-field`). Camera lerp system: input writes to `_scatterTarget`, rAF loop lerps `_scatterCam` toward it at 0.15/frame. Hover: CSS scale(2.2) + glow. Count chips (100/300/900/2.7k) in top bar reload the scatter.

2. **Poincaré** — Hybrid SVG (boundary circle, geodesic edges) + HTML div overlay (photo nodes with background-image). Golden-angle distribution (rank × 2.399963 rad). Size falls off steeply: `vs^1.8`. Navigation via Möbius fly-through (500ms atanh/tanh interpolation + 400ms settle). Swipe on empty space = Möbius drag with momentum (0.92× decay).

## Critical Things That Will Bite You

### 1. Image loading on mobile Safari
`new Image()`, `<img src>`, and `<img loading="lazy">` inside CSS-transformed containers ALL fail silently on mobile Safari with many concurrent loads. The ONLY working approach is `<div style="background-image:url(...)">`. We spent 5 versions debugging this. Do not revert to canvas drawImage or img tags for thumbnails.

### 2. crossOrigin attribute
Never set `crossOrigin = 'anonymous'` on same-origin image loads. It breaks Safari's connection pooling.

### 3. CSS transitions vs rAF
Poincaré nodes have CSS `transition: width 0.25s ease` for hover. This MUST be disabled (`style.transition = 'none'`) during Möbius fly-through and drag animations, otherwise CSS and JavaScript fight each other. Re-enable after animation completes.

### 4. Server startup
Always use `PYTHONPATH=""` when starting the server. The default PYTHONPATH on c-jfischer3 imports a broken torchvision.

### 5. Killing the dev server
Never run `killall python3` — it kills the RWX MCP server too, cutting off your access. To restart op-server.py: `kill $(pgrep -f op-server.py)` specifically. If RWX dies, the user needs to SSH in and run `bash ~/claude/rwx/kick-off.sh`.

### 6. Cron watchdog
The server auto-restarts within 60s via cron. After killing, you can either wait or start manually.

## Related Projects

**OpenMind** (`~/openmind/om-viz.html`, ~11,000 lines) is the sister project — a knowledge graph visualizer. Its Poincaré disk, canvas rendering engine, hover animations, and Möbius navigation were the reference implementation for Open Photo. When studying how something should work in Open Photo, look at OpenMind first.

**Smooth Web Animation Skill** (`~/claude/skills/smooth-web-animation/SKILL.md`) captures all the animation patterns learned from both projects: camera lerp, background-image loading, golden angle distribution, touch handling, Möbius fly-through, hover grow, GPU compositing, staggered transitions.

## Current State (March 9, 2026)

**Working:**
- Scatter view with DOM tiles, smooth camera lerp, pinch-to-zoom, hover grow
- Poincaré disk with golden-angle distribution, Möbius fly-through navigation, Möbius drag/swipe with momentum, hover grow + z-order, detail panel
- Count chips (100/300/900/2700) controlling both views
- Mobile-optimized top bar layout
- Staggered fade-in/out transitions

**Not yet working / needs attention:**
- CLIP broken on serve machine (text search, image search disabled)
- ~8,000 photos still not transferred from Google Drive (rclone stopped)
- Face recognition pipeline not migrated
- Collections UI not built (schema exists)
- Video playback (only shows thumbnail)
- Performance at 2700 nodes could be improved (outline squares below 16px)
- Search UI not implemented
- 90% of photos lack taken_at dates (Google Photos JSON sidecars not parsed)

## How to Test Changes

1. Edit files on c-jfischer3 via `dev:dev_patch_file` or `dev:dev_write_file`
2. Kill server: `dev:dev_run` with `kill $(pgrep -f op-server.py)`
3. Wait ~60s for cron restart, or start manually
4. Verify: `curl -s http://localhost:8260/ | grep 'YOUR_CHANGE'`
5. Ask user to hard-refresh the page on their device

## API Quick Test

```bash
# Check server is up
curl -s http://localhost:8260/api/stats | python3 -c 'import sys,json; print(json.load(sys.stdin)["total"],"photos")'

# Check layout at different limits
for n in 100 300 900 2700; do
  echo -n "limit=$n: "
  curl -s "http://localhost:8260/api/embedding-layout?limit=$n" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["positions"]))'
done

# Check a thumbnail serves
curl -sI http://localhost:8260/uploads/thumb_$(sqlite3 ~/claude/open-photo/op.db "SELECT id FROM media WHERE thumbnail_path IS NOT NULL LIMIT 1").jpg
```
