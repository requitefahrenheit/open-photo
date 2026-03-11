# Open Photo QA Report
*Generated: 2026-03-11*
*Target: op-viz.html v6.7 (3211 lines) against localhost:8260*

## Summary

**28 tests: 21 PASS, 5 FAIL, 2 SKIP**

Top priority fixes:
1. **[CRITICAL]** Atlas eviction stale-fetch race — closure can overwrite reused slot with wrong image (lines 2279–2293)
2. **[HIGH]** `_filteredPool()` includes no-thumbnail/no-embedding nodes — Jump/Demo can navigate to empty Poincaré disk ~28% of the time (line 2498)
3. **[HIGH]** `/api/similar/{id}` returns HTTP 404 for no-embedding nodes — inconsistent with `/api/media/{id}/similarities` which returns 200 + empty array
4. **[MEDIUM]** Stats chip not updated when filter/count chips change while in Poincaré view (line 994)
5. **[MEDIUM]** 7 of 12 thumbnails returned by `/api/similar` for tested node don't exist on disk

---

## Area 1: API Contract Verification

Endpoints tested live against `localhost:8260`. Sample ID: `ea573a1ac37b`.

### 1a. /api/photos [PASS]

```
Status: 200
Keys per node: [caption, geo_name, has_faces, id, is_nsfw, label, media_type, taken_at, thumbnail_path]
Total: 9710 nodes, 7015 with thumbnail_path, 517 with has_faces, 397 is_nsfw, 0 no-date
Field types: is_nsfw=bool, has_faces=bool
```

Frontend expects `data.nodes[]` with `id`, `thumbnail_path`, `taken_at`, `has_faces`, `is_nsfw` — all present and correct types. Spot-checked `thumb_ea573a1ac37b.jpg` → exists on disk.

### 1b. /api/stats [PASS]

```
Keys: total, photos, videos, faces, clusters, by_year, embedding_index, ...
total: 9710, embedding_index: 7015
```

Frontend at line 994: `s.total.toLocaleString()` — field present and numeric.

### 1c. /api/people?limit=200 [PASS]

```
Shape: {people: [...], total: N}
Total: 28 clusters, 5 with null cover_thumb, 0 named
```

Frontend skips null `cover_thumb` at line 2688. All expected keys present.

### 1d. /api/embedding-layout?limit=N [PASS]

```
Shape: {positions: {id: [x, y]}}
limit=100 -> 100 positions
```

Frontend at lines 2473/2964 expects `positions` object with id→[x,y]. Correct.

### 1e. /api/media/{id}/similarities [PASS]

```
Shape: {similarities: [{id, score}]}
ea573a1ac37b: 20 results
b916d41e0300 (no embedding): {similarities: []} — 200 OK, empty array
```

Frontend at line 2958: `d.similarities || []` handles empty correctly.

### 1f. /api/similar/{id}?limit=N [FAIL]

```
ea573a1ac37b: 200 OK, {count: 12, results: [{id, label, thumbnail_path, taken_at, media_type, score}]}
b916d41e0300 (no embedding): HTTP 404, body: {"detail": "No embedding"}
```

**Bug (server-side)**: Returns 404 for no-embedding nodes. Inconsistent with `/api/media/{id}/similarities` which returns 200 + empty array. Frontend handles via try/catch at lines 1412–1427 (no crash), but similar grid stays empty with no feedback.

**Data integrity issue**: 7 of 12 thumbnails returned for `ea573a1ac37b` don't exist on disk:
```
MISSING: thumb_e2d9be6c9a11.jpg  thumb_7691e67c15b2.jpg  thumb_1c5af13c30f2.jpg
         thumb_9af7f8fd4254.jpg  thumb_cdfd342f00fa.jpg  thumb_81c16ee6d7d8.jpg
         thumb_e75b00db8c9f.jpg
```

Main `/api/photos` thumbnails all exist. Missing files are from the embedding index referencing records whose thumbnails were never generated.

### 1g. Thumbnail file existence for /api/photos [PASS]

50 sampled nodes from `/api/photos` with `thumbnail_path` — all exist on disk.

---

## Area 2: Filter Logic Analysis

### 2a. _scatterPeopleFilter='safe' — NSFW gate [PASS]

**Scatter** line 1700: `if (_scatterPeopleFilter === 'safe') return !node.is_nsfw;`
**Poincaré** line 2975: `if (_scatterPeopleFilter === 'safe' && n.is_nsfw) return false;`

Uses `===` for string comparison. `is_nsfw` always boolean from API. Scatter nodes normalized at line 1681: `is_nsfw: n.is_nsfw || false`. All views consistent.

### 2b. _scatterPeopleFilter='people' — faces AND not NSFW [PASS]

**Scatter** line 1701: `return node.has_faces && !node.is_nsfw;`
**Poincaré** line 2976: `if (_scatterPeopleFilter === 'people' && (!n.has_faces || n.is_nsfw)) return false;`

De Morgan equivalents. Requires BOTH `has_faces` truthy AND `is_nsfw` falsy. Consistent across all three filter sites (scatter, Poincaré layout, `_filteredPool`).

### 2c. pdComputeLayout filter — centerId handling [PASS]

Lines 2967–2978: Center node unconditionally placed at `[0,0]` (line 2967: `positions.set(rootId, [0, 0])`) before any filtering. People/safe filters only apply to surrounding nodes in `allNodes`.

If center is NSFW and filter is 'safe', center still renders — correct (user navigated to it explicitly). If similarity fetch fails, catch at line 2959 sets cache to `[]`, resulting in only the center node — graceful degradation.

### 2d. _filteredPool() for Jump/Demo [FAIL]

Lines 2498–2506:
```js
function _filteredPool() {
    if (!_pdPhotos || !_pdPhotos.length) return [];
    return _pdPhotos.filter(n => {
        if (n.id === pdState.centerId) return false;
        if (_scatterPeopleFilter === 'safe' && n.is_nsfw) return false;
        if (_scatterPeopleFilter === 'people' && (!n.has_faces || n.is_nsfw)) return false;
        return true;
    });
}
```

**Bug**: Does NOT filter by `n.thumbnail_path` or embedding presence. `_pdPhotos` contains all 9,710 nodes; 2,695 lack `thumbnail_path` and CLIP embedding (`embedding_index=7015` matches `with_thumb=7015`). Jump/Demo selects these ~28% of the time, resulting in:

1. `enterPoincareView(pick.id)` → `pdComputeLayout(id)`
2. `/api/media/{id}/similarities` returns `{similarities: []}` (verified with `b916d41e0300`)
3. Only root at `[0,0]` in positions, no thumbnail → dark gray placeholder
4. User sees single gray square in empty Poincaré disk

**Fix**: Add `if (!n.thumbnail_path) return false;` after line 2501. Optionally also filter by `_pdEmbLayout?.positions?.[n.id]`.

### 2e. Time scrubber yr=0 (no taken_at) [PASS]

Lines 2629–2631:
```js
const yr = node.date ? parseInt(node.date.slice(0,4)) : 0;
const hide = yr && (yr < _timeStart || yr > _timeEnd);
```

When `yr=0`: `hide = 0 && (...)` → `false` (short-circuit). Nodes with no date NOT hidden. Correct. Note: all 9,710 nodes have `taken_at` in current dataset, but code handles absence correctly by inspection.

### 2f. Count chip resets _pdSimCache [PASS]

Lines 1750–1751: `_pdEmbLayout = null; _pdSimCache = {};` Both caches cleared. Lines 1757–1763 re-fetch photos, embedding layout with new limit, and call `pdComputeLayout(cid)` which re-fetches similarities. Correct full reload.

---

## Area 3: Black Square Root Cause Analysis

### 3a. Race window identification [PASS — race exists but correctly guarded]

The atlas pipeline per node:

**Phase 1 — Slot assignment** (synchronous, line 2279):
`_atlasAssignSlot(n.id)` → `_atlasNodeSlot.set(id, slot)` (line 2206)

**Phase 2 — Async fetch** (lines 2282–2301):
```js
fetch(thumbUrl(n.thumbnail_path))
  .then(r => r.blob())
  .then(b => createImageBitmap(b, {...}))
  .then(bmp => {
      _atlasCtxs[layer].drawImage(bmp, sx, sy, _ATLAS_TILE, _ATLAS_TILE);
      bmp.close();
      _atlasLoaded.add(n.id);        // only set AFTER drawImage
      if(_pdGL && _pdGL.atlasTex){
          gl.texSubImage3D(...);      // per-tile GPU upload
      }
  })
```

**Phase 3 — Batch upload** (line 2308): `_atlasUploadToGL()` after ALL fetches complete.

**Race window**: Between Phase 1 and Phase 2 completing, `rAF` can fire. At line 2397–2398:
```js
const slot = g.atlasIdx.get(id) ?? -1;
const hasTexF = (hasTex && slot >= 0 && _atlasLoaded.has(id)) ? 4 : 0;
```

During race: `slot >= 0` (assigned) but `_atlasLoaded.has(id) = false` → `hasTexF = 0`. The triple-gate correctly prevents texture sampling. Shader's else-branch handles the node (see 3c).

### 3b. Per-tile vs batch upload paths [PASS]

**First navigation** (`_pdGL.atlasTex` is null):
- Per-tile upload checks `if(_pdGL && _pdGL.atlasTex)` → false. Skipped.
- Batch upload at line 2308 creates texture and uploads all layers.
- Before batch: `hasTex = !!g.atlasTex` → false → root gets gray placeholder, others discard.
- After batch: all loaded nodes appear simultaneously.

**Subsequent navigations** (`_pdGL.atlasTex` exists):
- Per-tile upload at lines 2286–2293 executes synchronously in same microtask:
  1. `drawImage(bmp, ...)` — synchronous canvas op
  2. `_atlasLoaded.add(n.id)` — synchronous Set op
  3. `texSubImage3D(...)` — synchronous GL call
- JS single-threaded: no rAF can fire between these. `_atlasLoaded` flag and GPU data update atomically from renderer's perspective.

### 3c. Fragment shader hasTex=false behavior [PASS]

Lines 2074–2082 (fragment shader):
```glsl
if(hasTex){
    vec4 t = texture(u_tex, v_uv);
    fragColor = vec4(t.rgb, aa);
} else {
    if(isRoot || isHovered){
        float h = 1.0 - cd;
        fragColor = vec4(vec3(0.15+h*0.05), aa);  // dark gray: ~rgb(38-51)
    } else {
        discard;  // invisible
    }
}
```

When `hasTex=false`:
- **Root/hovered nodes**: Dark gray gradient `rgb(0.15–0.20)` with alpha 1.0. On `#0c0b09` (`rgb(0.047)`) background appears as visible dark rectangle. This IS the "black square" users report — an intentional placeholder, visible for 1–2 frames on fast network, longer on slow.
- **All other nodes**: `discard` — completely invisible. Nodes pop in as textures arrive.

### 3d. Atlas eviction — stale fetch closure race [FAIL]

Lines 2173–2195: `_atlasEvictSlot()` correctly clears both `_atlasNodeSlot.delete(evictedId)` and `_atlasLoaded.delete(evictedId)` at line 2192. After eviction, the evicted node renders with `slot=-1` → `hasTexF=0` → discard. Correct so far.

**However**, there is a race with in-flight fetch closures. The sequence:

1. **Navigation N1**: `pdGLLoadAtlas` assigns slot S to node A. Closure captures `[sx,sy,layer]` from slot S (lines 2280–2281). Fetch starts (line 2282).
2. **Navigation N2** (before A's fetch completes): `pdGLLoadAtlas` calls `_atlasEvictSlot()` which evicts slot S from node A (`_atlasNodeSlot.delete(A)`, `_atlasLoaded.delete(A)`), then `_atlasAssignSlot(B)` gives slot S to node B.
3. Node B's fetch completes first, draws B's image to slot S correctly.
4. Node A's stale fetch completes. Closure still holds `[sx,sy,layer]` pointing to slot S:
   - **Line 2286**: `_atlasCtxs[layer].drawImage(bmp, sx, sy, ...)` — **overwrites B's canvas data with A's image**
   - **Line 2286**: `_atlasLoaded.add(A.id)` — pollutes `_atlasLoaded` with evicted node A's id
   - **Lines 2288–2292**: `texSubImage3D` writes A's image to GPU at slot S — **overwrites B's texture**
5. **Result**: Node B now displays node A's thumbnail until B is re-fetched or B's slot is evicted.

**Conditions**: Requires two navigations in quick succession where the second evicts a slot whose fetch from the first is still in flight. More likely with slow network. SEM=24 means up to 24 parallel fetches, widening the window.

**Fix**: Guard the fetch completion callback. Before drawing at line 2285, check that the node still owns its slot:
```js
.then(bmp => {
    if (_atlasNodeSlot.get(n.id) !== slot) { bmp.close(); finish(); return; }
    _atlasCtxs[layer].drawImage(bmp, sx, sy, _ATLAS_TILE, _ATLAS_TILE);
    bmp.close();
    _atlasLoaded.add(n.id);
    // ... per-tile upload unchanged
})
```

### 3e. Atlas on navigation [PASS — by design]

Atlas is **supplemented**, not cleared. Lines 2256–2263 show existing nodes are "touched" (LRU age updated) while only missing nodes are fetched. This is correct: shared nodes between navigation centers retain their textures.

During fly animation (line 3145: `pdAnimateToNode`), animation uses snapshot `oldPos = new Map(pdState.positions)` (captured before layout change). Concurrently, `pdGLLoadAtlas` may evict old nodes' slots — those nodes become invisible (discarded by shader), causing a minor "blink out" during fast navigation. Cosmetic, not a data bug.

### Black Square Summary

| Scenario | Visual effect | Bug? |
|---|---|---|
| Root placeholder during atlas load | Dark gray square ~rgb(38-51), 1-2 frames | No — intentional placeholder |
| Non-root before texture loads | Invisible (discard) — pop in when ready | No — by design |
| Evicted node stale fetch overwrites reused slot | **Wrong image** in reused slot | **YES — see 3d** |
| Navigation: concurrent eviction during fly | Node blinks out (discard) | No — cosmetic |
| Fetch failure | `#1c1a16` fill, `_atlasLoaded` NOT set | No — safe |
| Atlas init fill | `#1c1a16` matches surface | No — never sampled |

---

## Area 4: Navigation Pathway Analysis

### 4a. Scatter tile tap → enterPoincareView(id) [PASS]

Lines 1904–1910: Click handler calls `enterPoincareView(tile.dataset.id)`.
Line 2913: `pdState.centerId = id` set BEFORE `pdComputeLayout` and `renderPoincareGraph`. `_currentMediaId` is the detail panel's state, not used by Poincaré rendering. No null centerId risk.

### 4b. Poincaré node tap → fly to new center [PASS]

Lines 2917–2926 (isNav branch):
```js
const flyP = pdAnimateToNode(id);        // starts 500ms fly (captures oldPos snapshot)
await pdComputeLayout(id);               // replaces pdState.positions (awaited!)
const atlasP = pdGLLoadAtlas(vn);        // starts fetching thumbnails
await flyP;                               // waits for fly
await pdSettleIntoLayout();               // 350ms blend old→new
await atlasP;                             // waits for atlas
renderPoincareGraph();                    // final render
```

`pdAnimateToNode` captures `oldPos = new Map(pdState.positions)` BEFORE layout change. Fly uses `oldPos`. `pdComputeLayout` fully awaited before settle. Settle blends `_mobiusEnd` (Möbius-transformed old positions) → new positions. No position/node mismatch possible.

### 4c. Detail → click similar → openDetail(newId) [PASS]

Line 1423: `div.addEventListener('click', () => openDetail(item.id))` — NOT `enterPoincareView`. Grid cleared at line 1416 (`grid.innerHTML = ''`), rebuilt by `loadSimilar(mediaId)` at line 1406. Each `item` in `forEach` is block-scoped — no stale closure risk.

### 4d. Detail thumbnail → enterPoincareView [PASS]

Lines 1436–1441:
```js
$('detail-img-wrap').addEventListener('click', () => {
    if (!_currentMediaId) return;
    const id = _currentMediaId;   // capture BEFORE closeDetail
    closeDetail();                 // sets _currentMediaId = null (line 1431)
    enterPoincareView(id);         // uses captured id
});
```

Race condition fix in place. `const id` captures value before `closeDetail()` nullifies `_currentMediaId`.

### 4e. Demo mode timing [PASS]

Lines 2518–2524: `await enterPoincareView(pick.id)` awaits full animation (500ms fly + 350ms settle + atlas load). Then 1500ms pause via `setTimeout`. Demo stops on mousedown/touchstart (lines 2543–2544). Note: settle duration is 350ms (line 3149: `const dur=350`), not 400ms.

### 4f. Jump — no guard against no-embedding photos [FAIL]

Lines 2508–2512: `_filteredPool()` does NOT exclude nodes without `thumbnail_path` or embeddings. 2,695/9,710 nodes lack both. ~28% chance per jump of selecting an unembedded node → solitary center in empty Poincaré disk.

For no-embedding nodes: `/api/media/{id}/similarities` returns `{similarities: []}` (verified), `simMap` is empty, `allNodes` is empty, result is root-only disk with dark gray placeholder.

**Fix**: Add `if (!n.thumbnail_path) return false;` to `_filteredPool()`.

---

## Area 5: Edge Cases and Defensive Coding

### 5a. Empty filter result [PASS]

**Scatter**: Empty `filteredNodes` → `field.innerHTML = ''` clears field. `_autoFitScatter(true)` at line 1728 operates on `_scatterNodes` (unfiltered) — camera fits to all layout positions even when none are visible. This is acceptable: layout positions don't change with people filter, camera stays in a reasonable viewport.

**Poincaré**: Empty `allNodes` → only root at `[0,0]`. `actualMax` / `actualMin` get safe defaults at lines 2986–2987 (`scores.length ? ... : 1.0/0.1`). Renders lone root node.

### 5b. No-thumbnail node exclusion [PASS]

Five exclusion points, all consistent:
1. Scatter init (line 1672): `if (!n.thumbnail_path) return null;` + `.filter(Boolean)` at line 1683
2. Poincaré layout (line 2974): `!n.thumbnail_path` → excluded from allNodes
3. Atlas loading (line 2252): `.filter(n=>n.thumbnail_path)`
4. Similar grid (line 1418): `if (!item.thumbnail_path) return;`
5. Server-side `/api/similar`: pre-filtered to only records with `thumbnail_path`

Exception: `_filteredPool()` does not filter — see 2d FAIL.

### 5c. Poincaré with single node (N=1) [PASS]

No `rank/(N-1)` pattern exists. Layout uses similarity scores directly. Line 3002: `const SIM_RANGE = Math.max(0.001, SIM_MAX - SIM_MIN);`

When N=1: `SIM_MAX === SIM_MIN`, so `SIM_RANGE = Math.max(0.001, 0) = 0.001`. Division `(it.sim - SIM_MIN) / SIM_RANGE = 0 / 0.001 = 0`. No division by zero. When N=0: loop doesn't execute.

### 5d. Time scrubber at boundaries [PASS]

Lines 2646–2649:
```js
if (isStart) {
    _timeStart = Math.min(yr, _timeEnd - 1);
} else {
    _timeEnd = Math.max(yr, _timeStart + 1);
}
```

Enforces minimum 1-year gap. Boundary clamping correct via Math.min/Math.max. Full range (2003–2026) shows all nodes including dateless ones (yr=0 guard at line 2630).

### 5e. Face sidebar with 0 valid clusters [PASS]

Line 2686: `list.innerHTML = ''` clears stale DOM before loop. Line 2688: `if (!person.cover_thumb) return;` skips all. Empty sidebar — no crash, no stale DOM. Minor UX gap: no "no people found" message.

### 5f. Stats chip after filter changes [FAIL]

**Scatter view**: Lines 1704–1711 inside `_renderScatterTiles()` DO update the stats chip:
```js
if (_scatterPeopleFilter === 'all') {
    statsEl.textContent = `${_scatterNodes.length.toLocaleString()} photos`;
} else {
    statsEl.textContent = `${filteredNodes.length.toLocaleString()} of ${_scatterNodes.length.toLocaleString()}`;
}
```
This correctly shows filtered counts when in scatter view.

**Poincaré view**: People filter handler (line 1738–1739) calls `pdComputeLayout` + `renderPoincareGraph` but does NOT update stats chip. Count chip handler in Poincaré mode (lines 1752–1769) also does not update stats chip.

**Bug**: Stats chip shows stale count when filter/count chips change while in Poincaré view. Returns to correct value when switching back to scatter.

**Fix**: Add stats-text update in the Poincaré filter/count chip handlers.

---

## Area 6: Mobile / Touch Path Audit

### 6a. Time scrubber touch [PASS]

Lines 2661–2667: `e.stopPropagation()` prevents pan activation. `touchmove` with `{ passive: false }` allows `e2.preventDefault()`. Uses `e2.touches[0].clientX`. Listeners cleaned up on `touchend`.

### 6b. View transition touch cleanup [PASS]

No explicit handler cleanup in `switchView()`, but effectively safe:
- Container handlers on hidden views (`display:none`) don't receive touch events
- Window-level Poincaré handlers guarded by `inPD()` check (line 2839: `_currentView === 'poincare'`)

### 6c. Pinch-to-zoom in scatter [PASS]

Lines 1864–1902: Midpoint `(t0+t1)/2 - r.left` correct. Strict `=== 2` checks block 3+ fingers. `lastPinchDist > 0 && dist > 0` guard prevents division by zero. `touchend` resets state.

### 6d. Poincaré touch tap disambiguation [SKIP]

Lines 2871–2898: Distance threshold + 350ms double-tap window. Sound by code inspection; cannot verify timing without browser.

### 6e. Slider touch isolation [SKIP]

Lines 2546–2548: All sliders have `e.stopPropagation()` on touch events. Cannot verify without browser.

---

## Supplemental: pdAnimateBack is dead code

Line 3110: `function pdAnimateBack(prevCenterId, oldPositions)` is defined but **never called**. `pdGoBack()` at line 3200 calls `enterPoincareView(prev.id, { isBack: true })` which uses `pdAnimateToNode`, not `pdAnimateBack`. 34 lines of unused code (3110–3143).

Note: `cNeg` IS correctly defined at line 1957: `function cNeg(a){return[-a[0],-a[1]];}`. The function works; `pdAnimateBack` is simply never invoked.

---

## Prioritized Fix List

### 1. [CRITICAL] Atlas eviction stale-fetch race — wrong-image squares
**Lines**: 2279–2293 (fetch closure captures slot coordinates), 2173–2195 (eviction)
**Root cause**: When a node's atlas slot is evicted while its thumbnail fetch is in flight, the fetch completion callback still writes to the old slot coordinates (captured in closure), overwriting the new occupant's texture and polluting `_atlasLoaded`.
**Impact**: Wrong thumbnail displayed for a node. Requires two navigations in quick succession. More likely under slow network with SEM=24 parallel fetches.
**Fix**: At line 2285 (inside `.then(bmp => {...})`), add a guard:
```js
if (_atlasNodeSlot.get(n.id) !== slot) { bmp.close(); finish(); return; }
```

### 2. [HIGH] `_filteredPool()` missing `thumbnail_path` / embedding guard
**Lines**: 2498–2506
**Root cause**: Pool includes all 9,710 nodes; 2,695 lack thumbnails/embeddings.
**Impact**: Jump/Demo selects no-thumbnail node ~28% of time → empty Poincaré disk with lone gray placeholder.
**Fix**: Add `if (!n.thumbnail_path) return false;` after line 2501. Optionally also check `_pdEmbLayout?.positions?.[n.id]`.

### 3. [HIGH] `/api/similar/{id}` returns 404 for no-embedding nodes
**Endpoint**: Server-side (op-server.py)
**Root cause**: Returns HTTP 404 `{"detail": "No embedding"}` instead of 200 with empty results.
**Impact**: Inconsistent API contract with `/api/media/{id}/similarities` (which returns 200 + empty array). Frontend handles via try/catch — no crash, but no user feedback.
**Fix** (server): Return `{count: 0, results: []}` with 200 status.

### 4. [MEDIUM] Stats chip stale in Poincaré view
**Lines**: 994, 1704–1711, 1738–1739, 1752–1769
**Root cause**: Stats chip updated by `_renderScatterTiles()` (scatter only). People/count filter changes in Poincaré view do not update it.
**Impact**: Shows stale count while in Poincaré. Corrects when returning to scatter.
**Fix**: Add stats-text update in Poincaré filter/count chip handlers.

### 5. [MEDIUM] Missing thumbnail files for /api/similar results
**Server**: Data integrity
**Root cause**: Embedding index references 7/12 records (for tested node) whose thumbnails don't exist on disk.
**Impact**: Broken images in atlas, empty slots in similar grid (frontend skips them gracefully at line 1418).
**Fix** (server): Regenerate thumbnails for embedded records, or prune stale index entries.

### 6. [LOW] Demo mode infinite retry on empty pool
**Line**: 2521
**Root cause**: When `_filteredPool()` returns empty, demo retries every 500ms indefinitely.
**Impact**: Silent busy loop wasting CPU. User can manually click "stop".
**Fix**: Auto-stop after ~10 retries, optionally show toast.

### 7. [LOW] pdAnimateBack is dead code (34 lines)
**Lines**: 3110–3143
**Impact**: Unused code from incomplete refactoring.
**Fix**: Delete, or wire into `pdGoBack` if reverse animation is desired.
