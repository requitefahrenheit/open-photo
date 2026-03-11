# Open Photo — Session Notes (v4 / v4.1x)

## v4 — Stable baseline (op-viz-v4.html, 2546 lines)

### Bugs fixed
- Count chips not working in Poincaré: moved _initScatterChips() to init() at page load
- Marooned nodes: set display:none for nodes not in current layout
- Z-ordering: re-sort #pd-nodes-svg children by vs after each update; root gets vs=2
- Floating tooltip text: removed from Poincaré mousemove
- SVG blocking touches: pointer-events:none on SVG; drag on container div

### Key architecture
- background-image on <div>, never <img>/new Image() — Mobile Safari + Cloudflare bug
- Drag: touchstart {passive:true}, touchmove {passive:false} on container div
- Poincaré drag: new Map() + mobiusTransform() per frame; full SVG update each frame
- Golden angle: rank × 2.399963 rad for node placement
- Kill: pkill -f op-server.py — never killall python3
- Start: PYTHONPATH="" python3 -u op-server.py

## v4.1x — Experimental perf (op-viz-v4.1x.html, 2640 lines)

Not confirmed to improve real-world smoothness. Changes:
- el.style.transform instead of setAttribute('transform') — compositor path
- skipSizeAndSort=true during drag — skip rect resize + z-sort
- _pdGLDrawOnly: hide SVG, GL-only render during drag when atlas loaded
- _pdInstBuf: pre-allocated Float32Array, reused via bufferSubData + STREAM_DRAW
- Cached uniforms: gl.uniform* only when cx/cy/R/W/H change
- rAF throttle: touchmove accumulates _pendingDx/Dy, one _flushDrag per frame
- In-place mutation: pos[0]=p[0]; pos[1]=p[1]; — no new Map() per frame

Revert to v4:
  cp ~/claude/open-photo/op-viz-v4.html ~/claude/open-photo/op-viz.html
  pkill -f op-server.py

## Spec
~/claude/open-photo/open-photo-spec-v3.md
