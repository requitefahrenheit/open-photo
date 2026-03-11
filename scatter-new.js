// ══════════════════════════════════════════════
// SCATTER VIEW  (DOM-based — browser handles image loading)
// ══════════════════════════════════════════════
const SCATTER_TILE = 48;   // tile size in world-space px
let _scatterLoaded = false;
let _scatterNodes  = [];   // [{id, wx, wy, thumb, caption, date}]
let _scatterTx     = { x: 0, y: 0, k: 1 };
let _scatterW = 0, _scatterH = 0;

async function initScatter() {
  $('scatter-loading').style.display = 'flex';
  try {
    const [layoutData, photosData] = await Promise.all([
      api('/api/embedding-layout'), api('/api/photos')
    ]);
    const nodeMap = {};
    for (const n of photosData.nodes) nodeMap[n.id] = n;
    const pos = layoutData.positions;
    const WORLD = 1000;
    _scatterNodes = Object.entries(pos).map(([id,[nx,ny]]) => {
      const n = nodeMap[id] || {};
      return {
        id,
        wx: nx * WORLD,
        wy: ny * WORLD,
        caption: (n.caption || n.label || '').slice(0, 80),
        date: (n.taken_at || '').slice(0, 7),
        thumb: n.thumbnail_path ? thumbUrl(n.thumbnail_path) : null,
      };
    });
    _scatterLoaded = true;
    $('scatter-loading').style.display = 'none';

    // Build DOM tiles
    const field = $('scatter-field');
    field.innerHTML = '';
    for (const node of _scatterNodes) {
      const el = document.createElement('img');
      el.className = 'scatter-tile';
      el.loading = 'lazy';
      el.draggable = false;
      el.alt = '';
      if (node.thumb) el.src = node.thumb;
      el.style.left = node.wx + 'px';
      el.style.top  = node.wy + 'px';
      el.dataset.id = node.id;
      el.dataset.caption = node.caption;
      el.dataset.date = node.date || '';
      field.appendChild(el);
      node.el = el;
    }

    // Measure container
    const container = $('view-scatter');
    _scatterW = container.clientWidth  || window.innerWidth;
    _scatterH = container.clientHeight || window.innerHeight;

    // Auto-fit
    _autoFitScatter();
    _applyScatterTransform();
    _initScatterEvents();

    // Debug
    const dbg = $('scatter-debug');
    if (dbg) dbg.textContent = `v3.0 | ${_scatterNodes.length} tiles, DOM-based`;
  } catch(e) {
    $('scatter-loading').style.display = 'none';
    console.error('Scatter init failed:', e);
  }
}

function _applyScatterTransform() {
  const field = $('scatter-field');
  field.style.transform = `translate(${_scatterTx.x}px, ${_scatterTx.y}px) scale(${_scatterTx.k})`;
}

function _autoFitScatter() {
  if (!_scatterNodes || _scatterNodes.length === 0) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of _scatterNodes) {
    if (n.wx < minX) minX = n.wx;
    if (n.wx > maxX) maxX = n.wx;
    if (n.wy < minY) minY = n.wy;
    if (n.wy > maxY) maxY = n.wy;
  }
  if (!isFinite(minX)) return;
  const dataW = (maxX - minX) + SCATTER_TILE * 2;
  const dataH = (maxY - minY) + SCATTER_TILE * 2;
  if (dataW <= 0 || dataH <= 0) return;
  const pad = 40;
  const cW = _scatterW || window.innerWidth;
  const cH = _scatterH || window.innerHeight;
  const k = Math.min((cW - pad * 2) / dataW, (cH - pad * 2) / dataH, 10);
  _scatterTx.k = k;
  _scatterTx.x = cW / 2 - ((minX + maxX) / 2) * k;
  _scatterTx.y = cH / 2 - ((minY + maxY) / 2) * k;
}

function _zoomScatterAt(sx, sy, factor) {
  const oldK = _scatterTx.k;
  const newK = Math.max(0.02, Math.min(oldK * factor, 40));
  _scatterTx.x = sx - (sx - _scatterTx.x) * (newK / oldK);
  _scatterTx.y = sy - (sy - _scatterTx.y) * (newK / oldK);
  _scatterTx.k = newK;
  _applyScatterTransform();
}

function _initScatterEvents() {
  const container = $('view-scatter');
  const tip = $('scatter-tooltip');
  let dragging = false, lastX = 0, lastY = 0;
  let pinching = false, lastPinchDist = 0;

  // Desktop: wheel zoom
  container.addEventListener('wheel', e => {
    e.preventDefault();
    const r = container.getBoundingClientRect();
    _zoomScatterAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.1 : 1/1.1);
  }, { passive: false });

  // Desktop: mouse drag
  container.addEventListener('mousedown', e => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    container.classList.add('dragging');
  });
  window.addEventListener('mousemove', e => {
    if (!dragging) return;
    _scatterTx.x += e.clientX - lastX;
    _scatterTx.y += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    _applyScatterTransform();
  });
  window.addEventListener('mouseup', () => { dragging = false; container.classList.remove('dragging'); });

  // Touch: pan + pinch-to-zoom
  container.addEventListener('touchstart', e => {
    if (e.touches.length === 1) {
      dragging = true; pinching = false;
      lastX = e.touches[0].clientX; lastY = e.touches[0].clientY;
    } else if (e.touches.length === 2) {
      e.preventDefault(); dragging = false; pinching = true;
      const t0 = e.touches[0], t1 = e.touches[1];
      lastPinchDist = Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
    }
  }, { passive: false });

  container.addEventListener('touchmove', e => {
    if (e.touches.length === 1 && dragging && !pinching) {
      const cx = e.touches[0].clientX, cy = e.touches[0].clientY;
      _scatterTx.x += cx - lastX; _scatterTx.y += cy - lastY;
      lastX = cx; lastY = cy;
      _applyScatterTransform();
    } else if (e.touches.length === 2) {
      e.preventDefault();
      pinching = true; dragging = false;
      const t0 = e.touches[0], t1 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
      if (lastPinchDist > 0 && dist > 0) {
        const r = container.getBoundingClientRect();
        const midX = (t0.clientX + t1.clientX) / 2 - r.left;
        const midY = (t0.clientY + t1.clientY) / 2 - r.top;
        _zoomScatterAt(midX, midY, dist / lastPinchDist);
      }
      lastPinchDist = dist;
    }
  }, { passive: false });

  container.addEventListener('touchend', e => {
    if (e.touches.length < 2) { pinching = false; lastPinchDist = 0; }
    if (e.touches.length === 0) dragging = false;
    if (e.touches.length === 1) {
      dragging = true; lastX = e.touches[0].clientX; lastY = e.touches[0].clientY;
    }
  });

  // Tap tiles to enter Poincaré
  container.addEventListener('click', e => {
    const tile = e.target.closest('.scatter-tile');
    if (tile && tile.dataset.id) {
      enterPoincareView(tile.dataset.id);
    }
  });

  // Hover tooltip (desktop)
  container.addEventListener('mouseover', e => {
    const tile = e.target.closest('.scatter-tile');
    if (tile) {
      tip.innerHTML = `<div style="color:var(--accent);font-size:10px;margin-bottom:3px">${tile.dataset.date||''}</div><div>${escHtml(tile.dataset.caption||'')}</div>`;
      tip.style.display = 'block';
    }
  });
  container.addEventListener('mousemove', e => {
    if (tip.style.display === 'block') {
      tip.style.left = (e.clientX + 14) + 'px';
      tip.style.top = (e.clientY - 24) + 'px';
    }
  });
  container.addEventListener('mouseout', e => {
    if (e.target.closest('.scatter-tile')) tip.style.display = 'none';
  });

  // Resize
  window.addEventListener('resize', () => {
    if (_currentView !== 'scatter') return;
    _scatterW = container.clientWidth || window.innerWidth;
    _scatterH = container.clientHeight || window.innerHeight;
    _autoFitScatter();
    _applyScatterTransform();
  });
}
