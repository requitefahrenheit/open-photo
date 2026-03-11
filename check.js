

// ─────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────
const API = '';  // same origin

// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────
let _currentView   = 'scatter';
let _searchMode    = 'semantic';
let _searchTimer   = null;
let _galleryOffset = 0;
let _galleryType   = 'all';
let _galleryYear   = '';
let _timelineYear  = null;
let _timelineMonth = null;
let _timelineYears = [];
let _currentMediaId = null;
let _currentClusterId = null;
let _nameDialogClusterId = null;
let _mapInstance   = null;
let _mapInitialized = false;

// ─────────────────────────────────────────────
// Utils
// ─────────────────────────────────────────────
const $  = id => document.getElementById(id);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html) e.innerHTML = html;
  return e;
};

async function api(path, opts={}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

function toast(msg, dur=2500) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), dur);
}

function thumbUrl(path) {
  if (!path) return '';
  return `${API}/uploads/${path}`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', { year:'numeric', month:'long', day:'numeric' });
  } catch { return iso.slice(0,10); }
}

function formatDateShort(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString('en-US', { month:'short', day:'numeric' });
  } catch { return iso.slice(5,10); }
}

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// ─────────────────────────────────────────────
// Navigation
// ─────────────────────────────────────────────
document.querySelectorAll('.nav-tab').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

function switchView(name) {
  _currentView = name;
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
  document.body.classList.toggle('immersive', name === 'scatter' || name === 'poincare');
  $('count-chips').style.display = (name === 'scatter' || name === 'poincare') ? '' : 'none';
  $('pd-force-wrap').style.display = (name === 'poincare') ? 'flex' : 'none';
  closeDetail();
  closePersonPanel();
  if (name === 'map' && !_mapInitialized) initMap();
  if (name === 'timeline' && _timelineYears.length) loadTimeline();
  if (name === 'gallery') loadGallery(true);
  if (name === 'scatter' && !_scatterLoaded) initScatter();
  if (name === 'poincare' && !_pdInitialized) initPoincareView();
}

// ─────────────────────────────────────────────
// Stats
// ─────────────────────────────────────────────
async function loadStats() {
  try {
    const s = await api('/api/stats');
    $('stats-text').textContent = `${s.total.toLocaleString()} photos`;
  } catch {}
}

// ─────────────────────────────────────────────
// People view
// ─────────────────────────────────────────────
async function loadPeople() {
  try {
    const data = await api('/api/people?limit=200');
    const grid = $('people-grid');
    grid.innerHTML = '';
    $('people-subtitle').textContent =
      `${data.total} people detected · ${data.people.filter(p=>p.person_name).length} named`;

    data.people.forEach(person => {
      const card = el('div', 'person-card');
      const name = person.person_name || person.anonymous_label;
      const isNamed = !!person.person_name;

      if (person.cover_thumb) {
        const img = el('img', 'face-img');
        img.src = thumbUrl(person.cover_thumb);
        img.alt = name;
        card.appendChild(img);
      } else {
        card.appendChild(el('div', 'face-placeholder', '👤'));
      }

      const info = el('div', 'person-card-info');
      info.innerHTML = `
        <div class="person-card-name ${isNamed ? '' : 'person-card-unnamed'}">${name}</div>
        <div class="person-card-count">${person.face_count.toLocaleString()} photos</div>
      `;
      card.appendChild(info);
      card.addEventListener('click', () => openPersonPanel(person));
      grid.appendChild(card);
    });
  } catch(e) {
    console.error(e);
  }
}

// ─────────────────────────────────────────────
// Person panel
// ─────────────────────────────────────────────
let _editingName = false;

async function openPersonPanel(person) {
  _currentClusterId = person.id;
  const panel = $('person-panel');
  panel.classList.add('open');

  $('person-face-big').src = person.cover_thumb ? thumbUrl(person.cover_thumb) : '';
  const nameDisplay = $('person-name-display');
  const nameInput   = $('person-name-input');
  nameDisplay.textContent = person.person_name || person.anonymous_label;
  nameInput.value = person.person_name || '';
  $('person-count').textContent = `${person.face_count.toLocaleString()} photos`;

  nameDisplay.style.display = '';
  nameInput.style.display = 'none';
  $('person-name-edit-btn').textContent = 'name';
  _editingName = false;

  const data = await api(`/api/people/${person.id}/photos?limit=200`);
  const grid = $('person-photos-grid');
  grid.innerHTML = '';

  data.photos.forEach(photo => {
    const item = el('div', 'gallery-item');
    const img = el('img');
    img.src = thumbUrl(photo.thumbnail_path);
    img.alt = photo.label;
    img.loading = 'lazy';
    item.appendChild(img);
    item.addEventListener('click', () => openDetail(photo.id));
    grid.appendChild(item);
  });
}

function closePersonPanel() {
  $('person-panel').classList.remove('open');
  _currentClusterId = null;
}

$('person-back').addEventListener('click', closePersonPanel);

$('person-name-edit-btn').addEventListener('click', async () => {
  const nameDisplay = $('person-name-display');
  const nameInput   = $('person-name-input');
  const btn = $('person-name-edit-btn');

  if (!_editingName) {
    nameDisplay.style.display = 'none';
    nameInput.style.display = '';
    nameInput.focus();
    btn.textContent = 'save';
    _editingName = true;
  } else {
    const newName = nameInput.value.trim();
    if (newName && _currentClusterId) {
      await api(`/api/people/${_currentClusterId}`, {
        method:'PATCH',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({person_name: newName})
      });
      nameDisplay.textContent = newName;
      toast(`Named "${newName}"`);
      loadPeople();
    }
    nameDisplay.style.display = '';
    nameInput.style.display = 'none';
    btn.textContent = 'name';
    _editingName = false;
  }
});

// ─────────────────────────────────────────────
// Gallery view
// ─────────────────────────────────────────────
async function loadGallery(reset=false) {
  if (reset) {
    _galleryOffset = 0;
    $('gallery-grid').innerHTML = '';
    $('gallery-load-more').style.display = 'none';
  }

  let url = `/api/timeline?limit=80&offset=${_galleryOffset}`;
  if (_galleryType !== 'all') url += `&media_type=${_galleryType}`;
  if (_galleryYear) url += `&from=${_galleryYear}-01-01&to=${_galleryYear}-12-31`;

  try {
    const data = await api(url);
    const grid = $('gallery-grid');

    data.items.forEach(item => {
      const div = el('div', 'gallery-item');
      const img = el('img');
      img.src = thumbUrl(item.thumbnail_path);
      img.alt = item.label;
      img.loading = 'lazy';
      div.appendChild(img);

      if (item.media_type === 'video') {
        div.appendChild(el('div', 'gallery-item-video-badge', '▶ video'));
      }

      const overlay = el('div', 'gallery-item-overlay');
      overlay.innerHTML = `
        <div class="gallery-item-date">${formatDateShort(item.taken_at)}</div>
        <div class="gallery-item-caption">${item.label || ''}</div>
      `;
      div.appendChild(overlay);
      div.addEventListener('click', () => openDetail(item.id));
      grid.appendChild(div);
    });

    _galleryOffset += data.items.length;
    const hasMore = _galleryOffset < data.total;
    $('gallery-load-more').style.display = hasMore ? 'block' : 'none';
  } catch(e) { console.error(e); }
}

document.querySelectorAll('.filter-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _galleryType = btn.dataset.type;
    loadGallery(true);
  });
});

$('year-select').addEventListener('change', e => {
  _galleryYear = e.target.value;
  loadGallery(true);
});

$('gallery-more-btn').addEventListener('click', () => loadGallery(false));

async function populateYearSelect() {
  try {
    const years = await api('/api/timeline/years');
    const sel = $('year-select');
    const uniqueYears = [...new Set(years.map(r => r.year))];
    uniqueYears.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y; opt.textContent = y;
      sel.appendChild(opt);
    });
    _timelineYears = years;
  } catch {}
}

// ─────────────────────────────────────────────
// Timeline view
// ─────────────────────────────────────────────
function buildTimelineScrubber() {
  const yearsEl  = $('timeline-years');
  yearsEl.innerHTML = '';

  const grouped = {};
  _timelineYears.forEach(r => {
    if (!grouped[r.year]) grouped[r.year] = {};
    grouped[r.year][r.month] = r.count;
  });

  const sortedYears = Object.keys(grouped).sort((a,b) => b-a);

  sortedYears.forEach((year, i) => {
    const total = Object.values(grouped[year]).reduce((a,b)=>a+b, 0);
    const block = el('div', 'year-block');
    block.innerHTML = `${year}<span class="year-count">${total.toLocaleString()}</span>`;
    if (i === 0) {
      block.classList.add('active');
      _timelineYear = year;
    }
    block.addEventListener('click', () => {
      document.querySelectorAll('.year-block').forEach(b => b.classList.remove('active'));
      block.classList.add('active');
      _timelineYear = year;
      _timelineMonth = null;
      buildMonthChips(grouped[year]);
      loadTimeline();
    });
    yearsEl.appendChild(block);
  });

  if (sortedYears[0]) buildMonthChips(grouped[sortedYears[0]]);
}

function buildMonthChips(monthData) {
  const el2 = $('timeline-months');
  el2.innerHTML = '';
  const allChip = el('button', 'month-chip active', 'all');
  allChip.addEventListener('click', () => {
    document.querySelectorAll('.month-chip').forEach(b => b.classList.remove('active'));
    allChip.classList.add('active');
    _timelineMonth = null;
    loadTimeline();
  });
  el2.appendChild(allChip);

  Object.keys(monthData).sort().forEach(m => {
    const chip = el('button', 'month-chip', MONTHS[parseInt(m)-1]);
    chip.addEventListener('click', () => {
      document.querySelectorAll('.month-chip').forEach(b => b.classList.remove('active'));
      chip.classList.add('active');
      _timelineMonth = m;
      loadTimeline();
    });
    el2.appendChild(chip);
  });
}

async function loadTimeline() {
  if (!_timelineYear) return;
  const content = $('timeline-content');
  content.innerHTML = '<div style="font-family:var(--mono);font-size:12px;color:var(--text-muted);padding:20px">loading...</div>';

  let from = `${_timelineYear}-01-01`;
  let to   = `${_timelineYear}-12-31`;
  if (_timelineMonth) {
    const m = _timelineMonth.padStart(2,'0');
    const lastDay = new Date(_timelineYear, parseInt(_timelineMonth), 0).getDate();
    from = `${_timelineYear}-${m}-01`;
    to   = `${_timelineYear}-${m}-${lastDay}`;
  }

  try {
    const data = await api(`/api/timeline?from=${from}&to=${to}&limit=500`);
    content.innerHTML = '';

    const byDay = {};
    data.items.forEach(item => {
      const day = item.taken_at ? item.taken_at.slice(0,10) : 'unknown';
      if (!byDay[day]) byDay[day] = [];
      byDay[day].push(item);
    });

    Object.keys(byDay).sort().reverse().forEach(day => {
      const group = el('div', 'timeline-day');
      const label = el('div', 'timeline-day-label', formatDate(day));
      const photos = el('div', 'timeline-day-photos');
      byDay[day].forEach(item => {
        const img = el('img', 'timeline-thumb');
        img.src = thumbUrl(item.thumbnail_path);
        img.alt = item.label;
        img.loading = 'lazy';
        img.addEventListener('click', () => openDetail(item.id));
        photos.appendChild(img);
      });
      group.appendChild(label);
      group.appendChild(photos);
      content.appendChild(group);
    });

    if (data.items.length === 0) {
      content.innerHTML = '<div style="font-family:var(--serif);font-size:16px;font-style:italic;color:var(--text-dim);padding:40px;text-align:center">nothing here</div>';
    }
  } catch(e) { console.error(e); }
}

// ─────────────────────────────────────────────
// Map view
// ─────────────────────────────────────────────
async function initMap() {
  _mapInitialized = true;
  const map = L.map('leaflet-map', {
    center:[20,0], zoom:2,
    attributionControl:false,
  });
  _mapInstance = map;

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom:19, attribution:'© OpenStreetMap'
  }).addTo(map);

  try {
    const data = await api('/api/map');
    if (!data.items.length) return;

    const markers = [];
    data.items.forEach(item => {
      if (!item.geo_lat || !item.geo_lon) return;
      const marker = L.circleMarker([item.geo_lat, item.geo_lon], {
        radius:6, fillColor:'#d4a853', fillOpacity:0.8,
        color:'#0c0b09', weight:1.5,
      }).addTo(map);
      marker.on('click', () => showMapPopup(item));
      markers.push(marker);
    });

    if (markers.length) {
      const group = L.featureGroup(markers);
      map.fitBounds(group.getBounds(), {padding:[40,40]});
    }
  } catch(e) { console.error(e); }
}

function showMapPopup(item) {
  const overlay = $('map-popup-overlay');
  $('map-popup-img').src = thumbUrl(item.thumbnail_path);
  $('map-popup-title').textContent = item.label || '';
  $('map-popup-info').textContent = [item.geo_name, formatDateShort(item.taken_at)].filter(Boolean).join(' · ');
  overlay.classList.add('visible');
  overlay.style.cursor = 'pointer';
  overlay.onclick = () => openDetail(item.id);
}

// ─────────────────────────────────────────────
// Detail panel
// ─────────────────────────────────────────────
async function openDetail(mediaId) {
  _currentMediaId = mediaId;
  const panel = $('detail-panel');
  panel.classList.add('open');

  $('detail-img').src = '';
  $('detail-caption').textContent = '';
  $('detail-meta').innerHTML = '';
  $('detail-faces-section').style.display = 'none';
  $('detail-similar-grid').innerHTML = '';

  try {
    const data = await api(`/api/media/${mediaId}`);

    $('detail-img').style.backgroundImage = `url(${thumbUrl(data.thumbnail_path)})`;
    $('detail-title').textContent = formatDateShort(data.taken_at) || data.label || 'photo';

    if (data.caption) {
      $('detail-caption').textContent = data.caption;
      $('detail-caption').style.display = '';
    } else {
      $('detail-caption').style.display = 'none';
    }

    const meta = [
      ['date',   formatDate(data.taken_at)],
      ['album',  data.album || '—'],
      ['camera', [data.camera_make, data.camera_model].filter(Boolean).join(' ') || '—'],
      ['size',   data.width ? `${data.width}×${data.height}` : '—'],
      ['location', data.geo_name || (data.geo_lat ? `${data.geo_lat.toFixed(3)}, ${data.geo_lon.toFixed(3)}` : '—')],
      ['type',   data.media_type || '—'],
    ];
    $('detail-meta').innerHTML = meta.map(([label,val]) => `
      <div class="meta-item">
        <div class="meta-label">${label}</div>
        <div class="meta-value">${val}</div>
      </div>
    `).join('');

    const faces = (data.faces || []).filter(f => !f.is_noise);
    if (faces.length) {
      $('detail-faces-section').style.display = '';
      const list = $('detail-faces-list');
      list.innerHTML = '';
      faces.forEach(face => {
        const chip = el('div', 'face-chip');
        chip.innerHTML = `
          <img class="face-chip-thumb" src="" alt="">
          <span class="${face.person_name ? 'face-chip-name' : 'face-chip-anon'}">
            ${face.person_name || face.anonymous_label || 'unknown'}
          </span>
        `;
        chip.addEventListener('click', () => {
          if (face.cluster_id) openNameDialog(face.cluster_id, face.person_name || face.anonymous_label);
        });
        list.appendChild(chip);
      });
    }

    loadSimilar(mediaId);
    $('detail-promote-btn').textContent = data.status === 'permanent' ? 'kept ✓' : 'keep';

  } catch(e) { console.error(e); }
}

async function loadSimilar(mediaId) {
  try {
    const data = await api(`/api/similar/${mediaId}?limit=8`);
    const grid = $('detail-similar-grid');
    grid.innerHTML = '';
    data.results.forEach(item => {
      const div = el('div', 'similar-thumb');
      if (item.thumbnail_path) div.style.backgroundImage = `url(${thumbUrl(item.thumbnail_path)})`;
      div.style.backgroundSize = 'cover';
      div.style.backgroundPosition = 'center';
      div.addEventListener('click', () => openDetail(item.id));
      grid.appendChild(div);
    });
  } catch {}
}

function closeDetail() {
  $('detail-panel').classList.remove('open');
  _currentMediaId = null;
}

$('detail-close-btn').addEventListener('click', closeDetail);

$('detail-promote-btn').addEventListener('click', async () => {
  if (!_currentMediaId) return;
  await api(`/api/media/${_currentMediaId}`, {
    method:'PATCH',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({status:'permanent'})
  });
  $('detail-promote-btn').textContent = 'kept ✓';
  toast('Photo kept');
});

$('detail-find-similar-btn').addEventListener('click', () => {
  if (!_currentMediaId) return;
  closeDetail();
  openSearchWith(_currentMediaId);
});

// ─────────────────────────────────────────────
// Search
// ─────────────────────────────────────────────
$('search-btn').addEventListener('click', openSearch);
$('search-close').addEventListener('click', closeSearch);

document.addEventListener('keydown', e => {
  if (e.key === '/' && !e.target.matches('input,textarea')) {
    e.preventDefault(); openSearch();
  }
  if (e.key === 'Escape') {
    closeSearch(); closeDetail(); closePersonPanel();
  }
});

document.querySelectorAll('.search-mode-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.search-mode-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _searchMode = btn.dataset.mode;
    const q = $('search-input').value.trim();
    if (q) doSearch(q);
  });
});

$('search-input').addEventListener('input', e => {
  clearTimeout(_searchTimer);
  const q = e.target.value.trim();
  if (!q) {
    $('search-empty').style.display = '';
    $('search-results-grid').style.display = 'none';
    return;
  }
  _searchTimer = setTimeout(() => doSearch(q), 400);
});

function openSearch() {
  $('search-overlay').classList.add('visible');
  setTimeout(() => $('search-input').focus(), 50);
}

function closeSearch() {
  $('search-overlay').classList.remove('visible');
  $('search-input').value = '';
  $('search-empty').style.display = '';
  $('search-results-grid').style.display = 'none';
}

async function openSearchWith(mediaId) {
  openSearch();
  $('search-input').value = 'similar to selected photo';
  try {
    const data = await api(`/api/similar/${mediaId}?limit=50`);
    renderSearchResults(data.results);
  } catch {}
}

async function doSearch(q) {
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&mode=${_searchMode}&limit=60`);
    renderSearchResults(data.results);
  } catch(e) { console.error(e); }
}

function renderSearchResults(results) {
  const grid = $('search-results-grid');
  $('search-empty').style.display = results.length ? 'none' : '';
  grid.style.display = results.length ? 'grid' : 'none';
  grid.innerHTML = '';

  results.forEach(item => {
    const div = el('div', 'search-result-item');
    div.innerHTML = `
      <img src="${thumbUrl(item.thumbnail_path)}" alt="${item.label || ''}" loading="lazy">
      ${item.score ? `<div class="search-result-score">${(item.score*100).toFixed(0)}%</div>` : ''}
      <div class="search-result-caption">${item.caption || item.label || ''}</div>
    `;
    div.addEventListener('click', () => {
      closeSearch();
      openDetail(item.id);
    });
    grid.appendChild(div);
  });
}

// ─────────────────────────────────────────────
// Name dialog
// ─────────────────────────────────────────────
function openNameDialog(clusterId, currentName) {
  _nameDialogClusterId = clusterId;
  $('name-dialog-input').value = currentName && !currentName.startsWith('Person ') ? currentName : '';
  $('name-dialog').classList.add('open');
  setTimeout(() => $('name-dialog-input').focus(), 50);
}

$('name-dialog-cancel').addEventListener('click', () => $('name-dialog').classList.remove('open'));
$('name-dialog-save').addEventListener('click', async () => {
  const name = $('name-dialog-input').value.trim();
  if (!name || !_nameDialogClusterId) return;
  await api(`/api/people/${_nameDialogClusterId}`, {
    method:'PATCH',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({person_name:name})
  });
  $('name-dialog').classList.remove('open');
  toast(`Named "${name}"`);
  loadPeople();
  if (_currentMediaId) openDetail(_currentMediaId);
});

$('name-dialog-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') $('name-dialog-save').click();
  if (e.key === 'Escape') $('name-dialog').classList.remove('open');
});

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────
async function init() {
  await loadStats();
  _initScatterChips(); // register chip handlers at startup, not inside scatter init
  $('loading').classList.add('hidden');
  switchView('poincare');
}

init();

// ══════════════════════════════════════════════
// SCATTER VIEW  (DOM-based — browser handles image loading)
// ══════════════════════════════════════════════
const SCATTER_TILE = 48;
let _scatterLoaded = false;
let _scatterNodes  = [];
// Split camera: input writes to target, rAF loop lerps cam toward it
let _scatterTarget = { x: 0, y: 0, k: 1 };   // what we want
let _scatterCam    = { x: 0, y: 0, k: 1 };   // what's rendered (lerps toward target)
let _scatterTx     = _scatterCam;             // alias for compat
let _scatterW = 0, _scatterH = 0;
let _scatterLimit  = 100;
let _scatterEventsInit = false;
let _scatterLoopRunning = false;
const CAM_LERP = 0.15;  // 0 = frozen, 1 = instant snap

async function initScatter(limit) {
  if (limit != null) _scatterLimit = limit;
  $('scatter-loading').style.display = 'flex';
  try {
    const [layoutData, photosData] = await Promise.all([
      api(`/api/embedding-layout?limit=${_scatterLimit}`), api('/api/photos')
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

    // Build DOM tiles as divs with background-image + staggered fade-in
    const field = $('scatter-field');
    field.innerHTML = '';
    _scatterNodes.forEach((node, i) => {
      const el = document.createElement('div');
      el.className = 'scatter-tile';
      if (node.thumb) el.style.backgroundImage = `url(${node.thumb})`;
      el.style.left = node.wx + 'px';
      el.style.top  = node.wy + 'px';
      el.dataset.id = node.id;
      el.dataset.caption = node.caption;
      el.dataset.date = node.date || '';
      field.appendChild(el);
      node.el = el;
      // Staggered fade-in
      setTimeout(() => el.classList.add('loaded'), 30 + i * 8);
    });

    // Measure container
    const container = $('view-scatter');
    _scatterW = container.clientWidth  || window.innerWidth;
    _scatterH = container.clientHeight || window.innerHeight;

    // Auto-fit (snap=true on first load so it doesn't animate from origin)
    _autoFitScatter(true);
    _applyScatterTransform();
    _startScatterLoop();
    if (!_scatterEventsInit) { _initScatterEvents(); _scatterEventsInit = true; }

  } catch(e) {
    $('scatter-loading').style.display = 'none';
    console.error('Scatter init failed:', e);
  }
}

function _initScatterChips() {
  document.querySelectorAll('.count-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const lim = parseInt(btn.dataset.limit);
      if (lim === _scatterLimit && _currentView !== 'poincare') return;
      _scatterLimit = lim;
      document.querySelectorAll('.count-chip').forEach(b => b.classList.toggle('active', b === btn));
      _pdEmbLayout = null;
      _pdSimCache = {};
      if (_currentView === 'poincare' && pdState.centerId) {
        const cid = pdState.centerId;
        (async () => {
          try {
            // Reload photos list so new limit nodes are in _pdNodeMap
            const data = await api('/api/photos');
            _pdPhotos = data.nodes;
            _pdPhotos.forEach(n => _pdNodeMap[n.id] = n);
            _pdEmbLayout = await api(`/api/embedding-layout?limit=${lim}`);
            await pdComputeLayout(cid);
            _pdSVGBuilt=false; if(_pdGL) _pdGL._svgBuilt=false;
            // Rebuild SVG immediately so nodes show before atlas loads
            renderPoincareGraph();
            // Load atlas in background, re-render when done
            const vn=[...pdState.positions.keys()].map(id=>_pdNodeMap[id]).filter(Boolean);
            pdGLLoadAtlas(vn).then(()=>{
              _pdSVGBuilt=false; if(_pdGL) _pdGL._svgBuilt=false;
              renderPoincareGraph();
            });
          } catch(e) { console.error('pd chip reload', e); }
        })();
      } else {
        // Reload scatter
        document.querySelectorAll('.scatter-tile').forEach(t => t.classList.remove('loaded'));
        setTimeout(() => {
          _scatterLoaded = false;
          _scatterLoopRunning = false;
          initScatter(lim);
        }, 300);
      }
    });
  });
}

function _applyScatterTransform() {
  const field = $('scatter-field');
  if (!field) return;
  field.style.transform = `translate(${_scatterCam.x}px, ${_scatterCam.y}px) scale(${_scatterCam.k})`;
}

// rAF loop: lerps camera toward target, applies transform
function _startScatterLoop() {
  if (_scatterLoopRunning) return;
  _scatterLoopRunning = true;
  function tick() {
    if (!_scatterLoaded) { _scatterLoopRunning = false; return; }
    // Lerp camera toward target
    const dx = _scatterTarget.x - _scatterCam.x;
    const dy = _scatterTarget.y - _scatterCam.y;
    const dk = _scatterTarget.k - _scatterCam.k;
    if (Math.abs(dx) > 0.1 || Math.abs(dy) > 0.1 || Math.abs(dk) > 0.0001) {
      _scatterCam.x += dx * CAM_LERP;
      _scatterCam.y += dy * CAM_LERP;
      _scatterCam.k += dk * CAM_LERP;
      _applyScatterTransform();
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function _autoFitScatter(snap) {
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
  _scatterTarget.k = k;
  _scatterTarget.x = cW / 2 - ((minX + maxX) / 2) * k;
  _scatterTarget.y = cH / 2 - ((minY + maxY) / 2) * k;
  if (snap) {
    _scatterCam.x = _scatterTarget.x;
    _scatterCam.y = _scatterTarget.y;
    _scatterCam.k = _scatterTarget.k;
  }
}

function _zoomScatterAt(sx, sy, factor) {
  const oldK = _scatterTarget.k;
  const newK = Math.max(0.02, Math.min(oldK * factor, 40));
  _scatterTarget.x = sx - (sx - _scatterTarget.x) * (newK / oldK);
  _scatterTarget.y = sy - (sy - _scatterTarget.y) * (newK / oldK);
  _scatterTarget.k = newK;
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
    _scatterTarget.x += e.clientX - lastX;
    _scatterTarget.y += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
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
      _scatterTarget.x += cx - lastX; _scatterTarget.y += cy - lastY;
      lastX = cx; lastY = cy;
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

  // Resize — re-fit with smooth glide (snap=false)
  window.addEventListener('resize', () => {
    if (_currentView !== 'scatter') return;
    _scatterW = container.clientWidth || window.innerWidth;
    _scatterH = container.clientHeight || window.innerHeight;
    _autoFitScatter(false);
  });
}
// ==============================================
// POINCARE DISK VIEW  (ported from OpenMind)
// ==============================================

// Complex arithmetic
function cMul(a,b){return[a[0]*b[0]-a[1]*b[1],a[0]*b[1]+a[1]*b[0]];}
function cDiv(a,b){const d=b[0]*b[0]+b[1]*b[1];return[(a[0]*b[0]+a[1]*b[1])/d,(a[1]*b[0]-a[0]*b[1])/d];}
function cSub(a,b){return[a[0]-b[0],a[1]-b[1]];}
function cConj(a){return[a[0],-a[1]];}
function cAbs(a){return Math.hypot(a[0],a[1]);}
function cScale(a,s){return[a[0]*s,a[1]*s];}
function mobiusTransform(z,a){
  return cDiv(cSub(z,a), cSub([1,0],cMul(cConj(a),z)));
}
function visualScale(z){const r2=z[0]*z[0]+z[1]*z[1];return Math.max(1-r2,0.01);}

const pdState = {
  centerId: null,
  positions: new Map(),
  screenPositions: new Map(),
  topSimilar: [],
  diskCx: 0, diskCy: 0, diskR: 0,
  animRAF: null,
  nodeEls: new Map()
};
const pdHistory   = [];
let _pdNodeMap    = {};
let _pdPhotos     = null;
let _pdEmbLayout  = null;
let _pdSimCache   = {};
let _pdInitialized = false;
let _pdSimPull = 0.3;
let _pdHoveredId = null;

// ── WebGL renderer ────────────────────────────────────────────────────────
const _PD_MIN_R=2,_PD_MAX_R=38;
let _pdGL=null;
let _pdSVGBuilt=false;
let _pdGLOK=false;
let _pdDragging=false;       // true while drag/momentum in flight
let _pdInstBuf=null;         // pre-allocated Float32Array, reused every GL frame
let _pdLastUniCx=-1,_pdLastUniCy=-1,_pdLastUniR=-1,_pdLastUniW=0,_pdLastUniH=0; // uniform cache

const _PD_VERT=`#version 300 es
precision highp float;
in vec2 a_corner;in vec2 a_pos;in float a_radius;in vec2 a_uv;in float a_root;
uniform vec2 u_ctr;uniform float u_dr;uniform vec2 u_res;uniform float u_sl;
out vec2 v_uv;out float v_vs;out float v_cd;out float v_root;
void main(){
  float r2=dot(a_pos,a_pos);v_vs=max(1.0-r2,0.0);v_cd=length(a_corner);v_root=a_root;
  vec2 sc=u_ctr+a_pos*u_dr+a_corner*a_radius;
  vec2 cl=sc/u_res*2.0-1.0;cl.y=-cl.y;
  gl_Position=vec4(cl,0.0,1.0);
  v_uv=a_uv+(a_corner*0.5+0.5)*u_sl;
}`;
const _PD_FRAG=`#version 300 es
precision mediump float;
uniform sampler2D u_tex;
in vec2 v_uv;in float v_vs;in float v_cd;in float v_root;
out vec4 fragColor;
void main(){
  if(v_vs<0.012||v_cd>1.0)discard;
  float aa=smoothstep(1.0,0.88,v_cd);
  if(v_root>0.5&&v_cd>0.80){fragColor=vec4(0.831,0.659,0.325,aa);return;}
  vec4 t=texture(u_tex,v_uv);fragColor=vec4(t.rgb,aa);
}`;

function initPdGL(){
  const cv=$('pd-gl-canvas');if(!cv)return false;
  const gl=cv.getContext('webgl2',{alpha:true,premultipliedAlpha:false,antialias:false});
  if(!gl){console.warn('WebGL2 unavailable');return false;}
  const sh=(t,s)=>{const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
    if(!gl.getShaderParameter(x,gl.COMPILE_STATUS)){console.error(gl.getShaderInfoLog(x));return null;}return x;};
  const vs=sh(gl.VERTEX_SHADER,_PD_VERT),fs=sh(gl.FRAGMENT_SHADER,_PD_FRAG);
  if(!vs||!fs)return false;
  const p=gl.createProgram();gl.attachShader(p,vs);gl.attachShader(p,fs);gl.linkProgram(p);
  if(!gl.getProgramParameter(p,gl.LINK_STATUS)){console.error(gl.getProgramInfoLog(p));return false;}
  const lc=gl.getAttribLocation(p,'a_corner'),lp=gl.getAttribLocation(p,'a_pos'),
    lr=gl.getAttribLocation(p,'a_radius'),lu=gl.getAttribLocation(p,'a_uv'),lt=gl.getAttribLocation(p,'a_root');
  const qb=gl.createBuffer(),ib=gl.createBuffer();
  // Build VAO with all attribute state baked in
  const vao=gl.createVertexArray();
  gl.bindVertexArray(vao);
  // Corner buffer (divisor 0 — one quad per instance)
  gl.bindBuffer(gl.ARRAY_BUFFER,qb);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,-1,1,1,-1,1]),gl.STATIC_DRAW);
  gl.enableVertexAttribArray(lc);gl.vertexAttribPointer(lc,2,gl.FLOAT,false,0,0);gl.vertexAttribDivisor(lc,0);
  // Instance buffer (divisor 1 — one entry per node)
  const BYTES=24;
  gl.bindBuffer(gl.ARRAY_BUFFER,ib);
  gl.enableVertexAttribArray(lp);gl.vertexAttribPointer(lp,2,gl.FLOAT,false,BYTES,0);gl.vertexAttribDivisor(lp,1);
  gl.enableVertexAttribArray(lr);gl.vertexAttribPointer(lr,1,gl.FLOAT,false,BYTES,8);gl.vertexAttribDivisor(lr,1);
  gl.enableVertexAttribArray(lu);gl.vertexAttribPointer(lu,2,gl.FLOAT,false,BYTES,12);gl.vertexAttribDivisor(lu,1);
  gl.enableVertexAttribArray(lt);gl.vertexAttribPointer(lt,1,gl.FLOAT,false,BYTES,20);gl.vertexAttribDivisor(lt,1);
  gl.bindVertexArray(null);
  _pdGL={gl,prog:p,vao,qb,ib,atlasTex:null,grid:1,atlasIdx:new Map(),sl:1,
    uc:gl.getUniformLocation(p,'u_ctr'),ud:gl.getUniformLocation(p,'u_dr'),
    ur:gl.getUniformLocation(p,'u_res'),us:gl.getUniformLocation(p,'u_sl'),ua:gl.getUniformLocation(p,'u_tex')};
  return true;
}

async function pdGLLoadAtlas(nodes){
  if(!_pdGL||!nodes||!nodes.length)return;
  const N=nodes.length,g=Math.ceil(Math.sqrt(N))||1,sz=g*64;
  const oc=document.createElement('canvas');oc.width=oc.height=sz;
  const ctx=oc.getContext('2d');ctx.fillStyle='#1c1a16';ctx.fillRect(0,0,sz,sz);
  const idx=new Map();
  // Skip atlas slots for nodes too small to show thumbnails
  const MIN_THUMB_R=10;
  nodes.forEach((n,i)=>idx.set(n.id,i));
  // Parallel with cap of 24 concurrent to avoid overwhelming mobile
  const SEM=24;
  let active=0,qi=0;
  await new Promise(done=>{
    function next(){
      while(active<SEM&&qi<N){
        const i=qi++;active++;
        const n=nodes[i];
        const finish=()=>{active--;if(qi<N)next();else if(active===0)done();};
        // Skip image load for nodes below minimum display size
        const sp=pdState.screenPositions.get(n.id);
        if(!n.thumbnail_path||(sp&&sp.r<MIN_THUMB_R)){finish();continue;}
        const img=new Image();img.crossOrigin='anonymous';
        img.onload=()=>{ctx.drawImage(img,(i%g)*64,Math.floor(i/g)*64,64,64);finish();};
        img.onerror=finish;img.src=thumbUrl(n.thumbnail_path);
      }
      if(qi>=N&&active===0)done();
    }
    next();
  });
  const{gl}=_pdGL;
  if(_pdGL.atlasTex)gl.deleteTexture(_pdGL.atlasTex);
  const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,oc);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  _pdGL.atlasTex=t;_pdGL.grid=g;_pdGL.atlasIdx=idx;_pdGL.sl=1/g;
  // Pre-allocate instance buffer sized for this atlas + 50% headroom, STREAM_DRAW
  const maxN=Math.ceil(N*1.5);
  if(!_pdInstBuf||_pdInstBuf.length<maxN*6)_pdInstBuf=new Float32Array(maxN*6);
  gl.bindBuffer(gl.ARRAY_BUFFER,_pdGL.ib);
  gl.bufferData(gl.ARRAY_BUFFER,_pdInstBuf.byteLength,gl.STREAM_DRAW); // pre-size on GPU
  gl.bindBuffer(gl.ARRAY_BUFFER,null);
  // Invalidate uniform cache so they're re-uploaded next draw
  _pdLastUniCx=_pdLastUniCy=_pdLastUniR=-1;_pdLastUniW=_pdLastUniH=0;
}

function _pdComputeScreenPos(positions,cx,cy,R){
  // Always compute screenPositions (used for hit testing)
  pdState.screenPositions.clear();
  for(const[id,pos]of positions){
    const vs=visualScale(pos);
    if(vs<0.005&&id!==pdState.centerId)continue;
    const isRoot=id===pdState.centerId;
    const nr=_PD_MIN_R+(_PD_MAX_R-_PD_MIN_R)*Math.pow(vs,1.8);
    pdState.screenPositions.set(id,{sx:cx+pos[0]*R,sy:cy+pos[1]*R,r:isRoot?Math.max(nr,Math.min(64,R*0.22)):nr,vs});
  }
}

function _pdSVGFallback(positions,cx,cy,R){
  // Build persistent SVG nodes, each positioned via transform="translate(sx,sy)"
  // so _pdUpdateSVGPositions() can animate them in-place without a full rebuild.
  const svg=$('pd-svg'); if(!svg)return;
  _pdEnsureSVGStructure(svg,0,0);
  const g=$('pd-nodes-svg');
  while(g.lastChild)g.removeChild(g.lastChild);
  const sorted=[...pdState.screenPositions.entries()].sort((a,b)=>a[1].vs-b[1].vs);
  const MIN_THUMB_R=10, RX=3;
  const ns='http://www.w3.org/2000/svg';
  for(const[id,sp]of sorted){
    const node=_pdNodeMap[id]; if(!node)continue;
    const isRoot=id===pdState.centerId;
    const r=sp.r, sz=r*2;
    const showThumb=r>=MIN_THUMB_R&&node.thumbnail_path;
    // Every node is a <g data-id transform=translate(sx,sy)>
    const el=document.createElementNS(ns,'g');
    el.classList.add('pd-node-g');
    el.dataset.id=id;
    el.style.transform=`translate(${sp.sx.toFixed(1)}px,${sp.sy.toFixed(1)}px)`;
    if(!showThumb){
      const c=document.createElementNS(ns,'rect');
      c.setAttribute('x',-r);c.setAttribute('y',-r);
      c.setAttribute('width',sz);c.setAttribute('height',sz);
      c.setAttribute('rx',RX);c.setAttribute('ry',RX);
      c.setAttribute('fill','none');
      c.setAttribute('stroke',isRoot?'var(--accent)':'rgba(255,255,255,0.25)');
      c.setAttribute('stroke-width',isRoot?'2':'0.8');
      el.appendChild(c);
    } else {
      const clipId='pdc-'+id;
      const defs=document.createElementNS(ns,'defs');
      const clip=document.createElementNS(ns,'clipPath');
      clip.setAttribute('id',clipId);
      const cr=document.createElementNS(ns,'rect');
      cr.setAttribute('x',-r);cr.setAttribute('y',-r);
      cr.setAttribute('width',sz);cr.setAttribute('height',sz);
      cr.setAttribute('rx',RX);cr.setAttribute('ry',RX);
      clip.appendChild(cr);defs.appendChild(clip);el.appendChild(defs);
      const bg=document.createElementNS(ns,'rect');
      bg.setAttribute('x',-r);bg.setAttribute('y',-r);
      bg.setAttribute('width',sz);bg.setAttribute('height',sz);
      bg.setAttribute('rx',RX);bg.setAttribute('ry',RX);
      bg.setAttribute('fill','#1c1a16');
      if(isRoot){bg.setAttribute('stroke','var(--accent)');bg.setAttribute('stroke-width','2.5');}
      else{bg.setAttribute('stroke','rgba(255,255,255,0.15)');bg.setAttribute('stroke-width','0.8');}
      el.appendChild(bg);
      const img=document.createElementNS(ns,'image');
      img.setAttribute('x',-r);img.setAttribute('y',-r);
      img.setAttribute('width',sz);img.setAttribute('height',sz);
      img.setAttribute('clip-path',`url(#${clipId})`);
      img.setAttribute('preserveAspectRatio','xMidYMid slice');
      img.setAttribute('href',thumbUrl(node.thumbnail_path));
      el.appendChild(img);
    }
    g.appendChild(el);
  }
}

// Fast in-place update — moves nodes by updating transform, resizes rects/images.
// Called every frame during drag and animation instead of full rebuild.
function _pdUpdateSVGPositions(positions,cx,cy,R,skipSizeAndSort){
  // skipSizeAndSort=true during drag: only move nodes, skip rect resizing and z-sort
  const g=$('pd-nodes-svg'); if(!g)return;
  const vsMap=skipSizeAndSort?null:new Map();
  for(const el of g.children){
    const id=el.dataset.id; if(!id)continue;
    const pos=positions.get(id);
    if(!pos){el.style.display='none';continue;}
    const vs=visualScale(pos);
    if(vs<0.005&&id!==pdState.centerId){el.style.display='none';continue;}
    el.style.display='';
    const isRoot=id===pdState.centerId;
    const nr=_PD_MIN_R+(_PD_MAX_R-_PD_MIN_R)*Math.pow(vs,1.8);
    const r=isRoot?Math.max(nr,Math.min(64,R*0.22)):nr;
    const sx=cx+pos[0]*R, sy=cy+pos[1]*R;
    // CSS transform instead of SVG attribute — composited, no layout recalc
    el.style.transform=`translate(${sx.toFixed(1)}px,${sy.toFixed(1)}px)`;
    pdState.screenPositions.set(id,{sx,sy,r,vs});
    if(!skipSizeAndSort){
      const sz=r*2;
      for(const rect of el.querySelectorAll('rect')){
        const isClip=rect.closest('clipPath')!==null;
        rect.setAttribute('x',-r);rect.setAttribute('y',-r);
        rect.setAttribute('width',sz);rect.setAttribute('height',sz);
        if(!isClip){
          if(isRoot){rect.setAttribute('stroke','var(--accent)');rect.setAttribute('stroke-width','2.5');}
          else{rect.setAttribute('stroke','rgba(255,255,255,0.15)');rect.setAttribute('stroke-width','0.8');}
        }
      }
      const img=el.querySelector('image');
      if(img){img.setAttribute('x',-r);img.setAttribute('y',-r);img.setAttribute('width',sz);img.setAttribute('height',sz);}
      vsMap.set(id,isRoot?2:vs);
    }
  }
  if(!skipSizeAndSort){
    // Z-sort: far first → near last = nearest painted on top
    const sorted=[...g.children].sort((a,b)=>(vsMap.get(a.dataset.id)||0)-(vsMap.get(b.dataset.id)||0));
    sorted.forEach(el=>g.appendChild(el));
  }
  // Edges
  const edgesG=$('pd-edges'); if(!edgesG)return;
  for(const path of edgesG.querySelectorAll('.pd-edge')){
    const p1=positions.get(path.dataset.source);
    const p2=positions.get(path.dataset.target);
    if(!p1||!p2)continue;
    const d=geodesicPath(p1,p2,cx,cy,R);
    if(d)path.setAttribute('d',d);
  }
}

// Lean GL-only draw: no SVG touched, pre-allocated buffer, cached uniforms
function _pdGLDrawOnly(positions,cx,cy,R,W,H){
  const g=_pdGL; if(!g||!g.atlasTex)return;
  const gl=g.gl,cv=gl.canvas,dpr=window.devicePixelRatio||1;
  const pw=W||cv.clientWidth||window.innerWidth;
  const ph=H||cv.clientHeight||window.innerHeight;
  const cw=Math.round(pw*dpr),ch=Math.round(ph*dpr);
  if(cv.width!==cw||cv.height!==ch){cv.width=cw;cv.height=ch;}
  gl.viewport(0,0,cw,ch);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  const sps=pdState.screenPositions;
  const maxN=sps.size; if(!maxN)return;
  if(!_pdInstBuf||_pdInstBuf.length<maxN*6)_pdInstBuf=new Float32Array(maxN*6);
  // Fill sorted by vs ascending (far→near = drawn last = on top)
  const tmp=[...sps.entries()];tmp.sort((a,b)=>a[1].vs-b[1].vs);
  let i=0;
  for(const[id,sp]of tmp){
    const pos=positions.get(id);if(!pos)continue;
    const slot=g.atlasIdx.get(id)??-1;const b=i*6;
    _pdInstBuf[b]=pos[0];_pdInstBuf[b+1]=pos[1];_pdInstBuf[b+2]=sp.r*dpr;
    _pdInstBuf[b+3]=slot>=0?(slot%g.grid)/g.grid:0;
    _pdInstBuf[b+4]=slot>=0?Math.floor(slot/g.grid)/g.grid:0;
    _pdInstBuf[b+5]=id===pdState.centerId?1:0;
    i++;
  }
  if(!i)return;
  gl.bindVertexArray(g.vao);
  gl.bindBuffer(gl.ARRAY_BUFFER,g.ib);
  gl.bufferSubData(gl.ARRAY_BUFFER,0,_pdInstBuf,0,i*6); // no realloc
  gl.bindBuffer(gl.ARRAY_BUFFER,null);
  gl.useProgram(g.prog);
  // Only re-upload uniforms that changed
  if(cx!==_pdLastUniCx||cy!==_pdLastUniCy){gl.uniform2f(g.uc,cx*dpr,cy*dpr);_pdLastUniCx=cx;_pdLastUniCy=cy;}
  if(R!==_pdLastUniR){gl.uniform1f(g.ud,R*dpr);_pdLastUniR=R;}
  if(cw!==_pdLastUniW||ch!==_pdLastUniH){gl.uniform2f(g.ur,cw,ch);_pdLastUniW=cw;_pdLastUniH=ch;}
  gl.uniform1f(g.us,g.sl);gl.uniform1i(g.ua,0);
  gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,g.atlasTex);
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  gl.drawArraysInstanced(gl.TRIANGLES,0,6,i);
  gl.bindVertexArray(null);
}

function pdGLRender(positions,cx,cy,R,W,H){
  _pdComputeScreenPos(positions,cx,cy,R);
  const glAvail=_pdGL&&_pdGL.atlasTex;
  if(!_pdSVGBuilt){
    try{
      _pdSVGFallback(positions,cx,cy,R);
    }catch(e){
      console.error('_pdSVGFallback error:',e);
    }
    _pdSVGBuilt=true;
    if(_pdGL) _pdGL._svgBuilt=true;
  } else {
    // Fast path: update node positions in-place (full update, not during drag)
    _pdUpdateSVGPositions(positions,cx,cy,R,false);
  }
  if(glAvail){
    const g=_pdGL,gl=g.gl,cv=gl.canvas;
    const dpr=window.devicePixelRatio||1;
    const pw=W||cv.clientWidth||window.innerWidth;
    const ph=H||cv.clientHeight||window.innerHeight;
    const cw=Math.round(pw*dpr),ch=Math.round(ph*dpr);
    if(cv.width!==cw||cv.height!==ch){cv.width=cw;cv.height=ch;}
    gl.viewport(0,0,cw,ch);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
    const entries=[];
    for(const[id,sp]of pdState.screenPositions){
      const pos=positions.get(id); if(!pos)continue;
      const isRoot=id===pdState.centerId;
      const slot=g.atlasIdx.get(id)??-1;
      const uu=slot>=0?(slot%g.grid)/g.grid:0;
      const uv=slot>=0?Math.floor(slot/g.grid)/g.grid:0;
      entries.push([pos[0],pos[1],sp.r*dpr,uu,uv,isRoot?1:0,sp.vs]);
    }
    entries.sort((a,b)=>a[6]-b[6]);
    const N=entries.length;
    if(N>0){
      const d=new Float32Array(N*6);
      for(let i=0;i<N;i++){const e=entries[i],b=i*6;
        d[b]=e[0];d[b+1]=e[1];d[b+2]=e[2];d[b+3]=e[3];d[b+4]=e[4];d[b+5]=e[5];}
      gl.bindVertexArray(g.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER,g.ib);
      gl.bufferData(gl.ARRAY_BUFFER,d,gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER,null);
      gl.useProgram(g.prog);
      gl.uniform2f(g.uc,cx*dpr,cy*dpr);gl.uniform1f(g.ud,R*dpr);
      gl.uniform2f(g.ur,cw,ch);gl.uniform1f(g.us,g.sl);gl.uniform1i(g.ua,0);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,g.atlasTex);
      gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
      gl.drawArraysInstanced(gl.TRIANGLES,0,6,N);
      gl.bindVertexArray(null);
    }
  }
}

function _pdHitTest(cx,cy){
  const rect=$('view-poincare').getBoundingClientRect();
  const px=cx-rect.left,py=cy-rect.top;
  let best=null,bestD=Infinity;
  for(const[id,sp]of pdState.screenPositions){
    // Square hit test: check if within the square bounds (not just circle)
    const dx=Math.abs(px-sp.sx),dy=Math.abs(py-sp.sy);
    const inSq=dx<=sp.r+8&&dy<=sp.r+8;
    const d=Math.hypot(dx,dy);
    if(inSq&&d<bestD){bestD=d;best=id;}
  }
  return best;
}
// ── end WebGL ────────────────────────────────────────────────────────────

async function initPoincareView() {
  $('pd-loading').style.display = 'flex';
  if(!_pdGL) initPdGL();
  if (!_pdPhotos) {
    const data = await api('/api/photos');
    _pdPhotos = data.nodes;
    for (const n of _pdPhotos) _pdNodeMap[n.id] = n;
  }
  if (!_pdEmbLayout) _pdEmbLayout = await api(`/api/embedding-layout?limit=${_scatterLimit}`);
  _pdInitialized = true;
  $('pd-loading').style.display = 'none'; // hide spinner before atlas load
  if (!pdState.centerId && _pdPhotos.length) {
    const pos = _pdEmbLayout.positions;
    let best = null, bestDist = Infinity;
    for (const [id, [x,y]] of Object.entries(pos)) {
      const d = (x-.5)*(x-.5)+(y-.5)*(y-.5);
      if (d < bestDist) { bestDist = d; best = id; }
    }
    if (best) await enterPoincareView(best);
    else $('pd-empty').style.display = 'flex';
  } else if (pdState.centerId) {
    renderPoincareGraph();
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    pdGLLoadAtlas(vn).then(()=>renderPoincareGraph());
  } else {
    $('pd-empty').style.display = 'flex';
  }
  $('pd-back').addEventListener('click', pdGoBack);
  $('pd-detail-close').addEventListener('click', hidePdDetail);
  $('pd-detail-full-btn').addEventListener('click', () => { if (pdState.centerId) openDetail(pdState.centerId); });
  window.addEventListener('resize', () => { if (_currentView === 'poincare') { _pdSVGBuilt=false; if(_pdGL) _pdGL._svgBuilt=false; requestAnimationFrame(renderPoincareGraph); } });
  _initPdDrag();
  _initPdEvents();
  const forceSlider = $('pd-force-slider');
  forceSlider.addEventListener('touchstart', e => e.stopPropagation(), { passive: true });
  forceSlider.addEventListener('touchmove', e => e.stopPropagation(), { passive: true });
  forceSlider.addEventListener('touchend', e => e.stopPropagation(), { passive: true });
  forceSlider.addEventListener('input', async e => {
    _pdSimPull = parseFloat(e.target.value);
    if (pdState.centerId) {
      await pdComputeLayout(pdState.centerId);
      const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
      await pdGLLoadAtlas(vn);
      renderPoincareGraph();
    }
  });
}



function _initPdDrag(){
  const container=$("view-poincare");
  const svg=$("pd-svg");
  let dragging=false,dragStartX=0,dragStartY=0,dragMoved=false;
  let velocityX=0,velocityY=0,lastMoveTime=0,momentumRAF=null;
  // rAF throttle: accumulate pending dx/dy, render once per frame
  let _pendingDx=0,_pendingDy=0,_rafPending=false;
  // Reusable Möbius vector — avoids allocating [x,y] each call
  const _mVec=[0,0];

  function _pdDragEnd(){
    if(!_pdDragging)return;
    _pdDragging=false;
    const{diskCx:cx,diskCy:cy,diskR:R}=pdState;
    _pdUpdateSVGPositions(pdState.positions,cx,cy,R,false);
    $('pd-nodes-svg').style.visibility='';
  }

  function _flushDrag(){
    _rafPending=false;
    if(!_pendingDx&&!_pendingDy)return;
    const dx=_pendingDx,dy=_pendingDy;
    _pendingDx=0;_pendingDy=0;
    if(pdState.animRAF)return;
    const{diskCx:cx,diskCy:cy,diskR:R,diskW:W,diskH:H}=pdState;
    if(!R)return;
    const scale=0.8/R;
    _mVec[0]=dx*scale;_mVec[1]=dy*scale;
    const aLen=Math.sqrt(_mVec[0]*_mVec[0]+_mVec[1]*_mVec[1]);
    if(aLen>0.9){_mVec[0]*=0.9/aLen;_mVec[1]*=0.9/aLen;}
    // Mutate positions in-place — no new Map, no new arrays
    for(const[id,pos]of pdState.positions){
      const p=mobiusTransform(pos,_mVec);
      pos[0]=p[0];pos[1]=p[1];
    }
    if(_pdGL&&_pdGL.atlasTex){
      if(!_pdDragging){_pdDragging=true;$('pd-nodes-svg').style.visibility='hidden';}
      _pdComputeScreenPos(pdState.positions,cx,cy,R);
      _pdGLDrawOnly(pdState.positions,cx,cy,R,W,H);
    } else {
      _pdUpdateSVGPositions(pdState.positions,cx,cy,R,true);
    }
  }

  function applyDragTransform(dx,dy){
    _pendingDx+=dx;_pendingDy+=dy;
    if(!_rafPending){_rafPending=true;requestAnimationFrame(_flushDrag);}
  }

  function startMomentum(){
    let mvx=velocityX,mvy=velocityY;
    if(Math.hypot(mvx,mvy)<1){_pdDragEnd();return;}
    function tick(){
      mvx*=.92;mvy*=.92;
      if(Math.hypot(mvx,mvy)<.5){momentumRAF=null;_pdDragEnd();return;}
      // Momentum runs its own rAF tick — call _flushDrag directly
      _pendingDx-=mvx;_pendingDy-=mvy;
      _flushDrag();
      momentumRAF=requestAnimationFrame(tick);
    }
    momentumRAF=requestAnimationFrame(tick);
  }
  function cancelMomentum(){
    if(momentumRAF){cancelAnimationFrame(momentumRAF);momentumRAF=null;_pdDragEnd();}
  }
  // Mouse drag — on container, track on window (same pattern as scatter)
  container.addEventListener("mousedown",e=>{
    if(_pdHitTest(e.clientX,e.clientY))return;
    cancelMomentum();dragging=true;dragMoved=false;
    dragStartX=e.clientX;dragStartY=e.clientY;
    velocityX=0;velocityY=0;lastMoveTime=performance.now();
    container.style.cursor="grabbing";e.preventDefault();
  });
  window.addEventListener("mousemove",e=>{
    if(!dragging)return;
    const dx=e.clientX-dragStartX,dy=e.clientY-dragStartY;
    if(Math.hypot(dx,dy)>3)dragMoved=true;if(!dragMoved)return;
    const now=performance.now(),dt=Math.max(now-lastMoveTime,1);
    velocityX=dx/dt*16;velocityY=dy/dt*16;lastMoveTime=now;
    applyDragTransform(-dx,-dy);dragStartX=e.clientX;dragStartY=e.clientY;
  });
  window.addEventListener("mouseup",()=>{
    if(dragging){dragging=false;container.style.cursor="";if(dragMoved)startMomentum();else _pdDragEnd();}
  });
  // Touch drag — on container, same pattern as scatter
  let touchId=null;
  container.addEventListener("touchstart",e=>{
    if(e.touches.length!==1)return;
    if(_pdHitTest(e.touches[0].clientX,e.touches[0].clientY))return;
    cancelMomentum();touchId=e.touches[0].identifier;
    dragStartX=e.touches[0].clientX;dragStartY=e.touches[0].clientY;
    dragMoved=false;velocityX=0;velocityY=0;lastMoveTime=performance.now();
  },{passive:true});
  container.addEventListener("touchmove",e=>{
    if(touchId===null)return;
    const touch=[...e.touches].find(t=>t.identifier===touchId);if(!touch)return;
    const dx=touch.clientX-dragStartX,dy=touch.clientY-dragStartY;
    if(!dragMoved&&Math.hypot(dx,dy)<8)return;
    dragMoved=true;e.preventDefault();
    const now=performance.now(),dt=Math.max(now-lastMoveTime,1);
    velocityX=dx/dt*16;velocityY=dy/dt*16;lastMoveTime=now;
    applyDragTransform(-dx,-dy);dragStartX=touch.clientX;dragStartY=touch.clientY;
  },{passive:false});
  container.addEventListener("touchend",e=>{
    if(touchId===null)return;
    const found=[...e.changedTouches].find(t=>t.identifier===touchId);
    if(found){touchId=null;if(dragMoved)startMomentum();else _pdDragEnd();}
  },{passive:true});
}

function _initPdEvents(){
  const container=$("view-poincare"),tip=$("pd-tooltip");
  function inPD(){ return _currentView==="poincare"; }
  container.addEventListener("mousemove",e=>{
    if(!inPD())return;
    const id=_pdHitTest(e.clientX,e.clientY);
    if(id===_pdHoveredId)return;
    _pdHoveredId=id;
    const svg=$("pd-svg"),ring=svg&&svg.querySelector("#pd-hover-ring");
    if(id&&id!==pdState.centerId){
      const sp=pdState.screenPositions.get(id);
      if(ring&&sp){ring.setAttribute("cx",sp.sx);ring.setAttribute("cy",sp.sy);ring.setAttribute("r",sp.r+3);ring.style.display="";}
    }else{if(ring)ring.style.display="none";}
  });
  container.addEventListener("mouseleave",()=>{
    _pdHoveredId=null;
    const ring=$("pd-svg")&&$("pd-svg").querySelector("#pd-hover-ring");
    if(ring)ring.style.display="none";
  });
  let _ct=null,_lid=null;
  window.addEventListener("click",e=>{
    if(!inPD())return;
    const id=_pdHitTest(e.clientX,e.clientY);if(!id)return;
    if(_lid===id&&_ct){clearTimeout(_ct);_ct=null;_lid=null;openDetail(id);}
    else{clearTimeout(_ct);_lid=id;
      _ct=setTimeout(()=>{_ct=null;_lid=null;
        if(id!==pdState.centerId)enterPoincareView(id);else renderPdDetail(id);
      },220);}
  });
  window.addEventListener("dblclick",e=>{if(inPD()&&!_pdHitTest(e.clientX,e.clientY))pdGoBack();});
  let _lt=null,_li=null,_ltid=null,_tsx=0,_tsy=0;
  window.addEventListener("touchstart",e=>{
    if(!inPD())return;
    const t=e.touches[0],id=_pdHitTest(t.clientX,t.clientY);if(!id)return;
    _li=id;_ltid=t.identifier;_tsx=t.clientX;_tsy=t.clientY;
    clearTimeout(_lt);
    _lt=setTimeout(()=>{_lt=null;if(_li)openDetail(_li);},500);
  },{passive:true});
  window.addEventListener("touchmove",e=>{
    if(!_ltid)return;
    const found=[...e.changedTouches].find(t=>t.identifier===_ltid);
    if(found&&Math.hypot(found.clientX-_tsx,found.clientY-_tsy)>8){clearTimeout(_lt);_lt=null;}
  },{passive:true});
  window.addEventListener("touchend",e=>{
    if(!inPD()||!_ltid)return;
    const found=[...e.changedTouches].find(t=>t.identifier===_ltid);if(!found)return;
    const fired=!_lt;clearTimeout(_lt);_lt=null;_ltid=null;
    const id=_li;_li=null;
    if(fired)return;
    if(id&&id!==pdState.centerId)enterPoincareView(id);else if(id)renderPdDetail(id);
  },{passive:false});
}


async function enterPoincareView(id) {
  if (_currentView !== 'poincare') switchView('poincare');
  const isNav = pdState.centerId && pdState.centerId !== id;
  if (isNav) {
    const prev = _pdNodeMap[pdState.centerId];
    if (prev) pdHistory.push({ id: pdState.centerId, label: prev.label || prev.taken_at || '' });
  } else if (!pdState.centerId) {
    pdHistory.length = 0;
  }
  pdState.centerId = id;
  _pdSVGBuilt=false; if(_pdGL) _pdGL._svgBuilt=false; // invalidate SVG cache for new center
  $('pd-empty').style.display = 'none';

  if (isNav && pdState.positions.size > 0) {
    const flyP = pdAnimateToNode(id);
    await pdComputeLayout(id);
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    const atlasP = pdGLLoadAtlas(vn);
    await flyP;
    await pdSettleIntoLayout();
    await atlasP; // may already be done; final re-render with textures
    renderPoincareGraph();
  } else {
    await pdComputeLayout(id);
    renderPoincareGraph(); // show disk immediately (no textures yet)
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    pdGLLoadAtlas(vn).then(()=>renderPoincareGraph()); // re-render with textures when ready
  }
  renderPdDetail(id);
  renderPdNav();
}

async function pdComputeLayout(rootId) {
  if (!_pdSimCache[rootId]) {
    try {
      const d = await api(`/api/media/${rootId}/similarities`);
      _pdSimCache[rootId] = d.similarities || [];
    } catch { _pdSimCache[rootId] = []; }
  }
  const simsData = _pdSimCache[rootId];
  const simMap = {};
  for (const s of simsData) simMap[s.id] = s.score;
  const pos = (_pdEmbLayout && _pdEmbLayout.positions) || {};
  const rootPCA = pos[rootId] || [0.5, 0.5];
  const positions = new Map();
  positions.set(rootId, [0, 0]);

  // Build candidate list — sorted by similarity desc so we take the most-similar nodes

  const PD_MAX_NODES = _scatterLimit;
  const allNodes = (_pdPhotos || []).filter(n => n.id !== rootId);
  allNodes.sort((a, b) => (simMap[b.id] || 0) - (simMap[a.id] || 0));

  // Step 1: collect similarity scores + PCA-derived raw angles
  const items = allNodes.slice(0, PD_MAX_NODES).map(n => {
    const sim = simMap[n.id] || 0;
    const pca = pos[n.id];
    let rawAngle;
    if (pca) {
      rawAngle = Math.atan2(pca[1] - rootPCA[1], pca[0] - rootPCA[0]);
    } else {
      rawAngle = Math.random() * 2 * Math.PI;
    }
    return { id: n.id, sim, rawAngle };
  });

  // Step 2: normalize sim scores [0,1] then apply power curve
  // r = pow(1 - normalized, simPull) — low simPull = gentle spread, high = tight cluster near center
  const simVals = items.map(it => it.sim);
  const minSim = Math.min(...simVals), maxSim = Math.max(...simVals);
  const simRange = Math.max(maxSim - minSim, 0.001);
  for (const it of items) {
    const normalized = (it.sim - minSim) / simRange; // 0=least similar, 1=most similar
    it.r = 0.08 + Math.pow(1 - normalized, _pdSimPull) * 0.82;
  }

  // Step 3: sort by PCA angle, redistribute evenly around circle (no bunching)
  items.sort((a, b) => a.rawAngle - b.rawAngle);
  items.forEach((it, i) => { it.diskAngle = (2 * Math.PI * i) / items.length; });

  for (const it of items) {
    positions.set(it.id, [Math.cos(it.diskAngle) * it.r, Math.sin(it.diskAngle) * it.r]);
  }
  pdState.topSimilar = simsData.slice(0, 5).map(s => s.id);
  pdState.positions  = positions;
}

function geodesicPath(p1, p2, cx, cy, R) {
  const dx = p2[0]-p1[0], dy = p2[1]-p1[1];
  const dist = Math.hypot(dx,dy);
  if (dist < 2) return '';
  if (Math.abs(p1[0]*p2[1]-p1[1]*p2[0]) < 0.02*R*R || dist < R*0.15)
    return `M${cx+p1[0]*R},${cy+p1[1]*R} L${cx+p2[0]*R},${cy+p2[1]*R}`;
  const r1sq=p1[0]*p1[0]+p1[1]*p1[1], r2sq=p2[0]*p2[0]+p2[1]*p2[1];
  if (r1sq<0.001||r2sq<0.001) return `M${cx+p1[0]*R},${cy+p1[1]*R} L${cx+p2[0]*R},${cy+p2[1]*R}`;
  const inv1=[p1[0]/r1sq,p1[1]/r1sq];
  const [ax,ay]=[p1[0],p1[1]], [bx,by]=[p2[0],p2[1]], [ex,ey]=inv1;
  const D=2*(ax*(by-ey)+bx*(ey-ay)+ex*(ay-by));
  if (Math.abs(D)<1e-10) return `M${cx+p1[0]*R},${cy+p1[1]*R} L${cx+p2[0]*R},${cy+p2[1]*R}`;
  const ux=((ax*ax+ay*ay)*(by-ey)+(bx*bx+by*by)*(ey-ay)+(ex*ex+ey*ey)*(ay-by))/D;
  const uy=((ax*ax+ay*ay)*(ex-bx)+(bx*bx+by*by)*(ax-ex)+(ex*ex+ey*ey)*(bx-ax))/D;
  const arcR=Math.hypot(ax-ux,ay-uy)*R;
  const sweep=((p1[0]-ux)*(p2[1]-uy)-(p1[1]-uy)*(p2[0]-ux))>0?1:0;
  return `M${cx+p1[0]*R},${cy+p1[1]*R} A${arcR},${arcR} 0 0 ${sweep} ${cx+p2[0]*R},${cy+p2[1]*R}`;
}

function _pdCanvasDims(){
  const svg=$('pd-svg');
  const W=(svg&&svg.clientWidth)||window.innerWidth;
  const H=(svg&&svg.clientHeight)||window.innerHeight;
  const detailEl=$('pd-detail');
  const detailH=(detailEl&&detailEl.classList.contains('open'))?(detailEl.offsetHeight||0):0;
  const visH=H-detailH;
  const R=Math.min(W,visH)*0.44,cx=W/2,cy=visH/2;
  return{W,H,R,cx,cy};
}

function _pdEnsureSVGStructure(svg,W,H){
  // One-time setup of persistent SVG groups — never wipe the whole SVG
  if(!svg.querySelector('#pd-bg')){
    const ns='http://www.w3.org/2000/svg';
    const bg=document.createElementNS(ns,'g');bg.id='pd-bg';svg.appendChild(bg);
    const ed=document.createElementNS(ns,'g');ed.id='pd-edges';svg.appendChild(ed);
    const nd=document.createElementNS(ns,'g');nd.id='pd-nodes-svg';svg.appendChild(nd);
  }
}

function renderPoincareGraph(){
  const svg=$('pd-svg');
  if(!svg||pdState.positions.size===0)return;
  const{W,H,R,cx,cy}=_pdCanvasDims();
  pdState.diskCx=cx;pdState.diskCy=cy;pdState.diskR=R;pdState.diskW=W;pdState.diskH=H;
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width',W);svg.setAttribute('height',H);
  _pdEnsureSVGStructure(svg,W,H);
  // Update background (boundary, glow, hover-ring) — never touches nodes
  const bg=$('pd-bg');
  bg.innerHTML=
    `<circle cx="${cx}" cy="${cy}" r="${R}" class="pd-boundary"/>` +
    `<circle cx="${cx}" cy="${cy}" r="${R*0.07}" class="pd-center-glow" stroke-width="2"/>` +
    `<circle id="pd-hover-ring" cx="0" cy="0" r="0" fill="none" stroke="var(--accent)" stroke-width="2" stroke-opacity="0.8" style="display:none"/>`;
  // Update edges
  const top5=new Set(pdState.topSimilar);
  let edgeHtml='';
  for(const tid of top5){
    const p1=pdState.positions.get(pdState.centerId),p2=pdState.positions.get(tid);
    if(!p1||!p2)continue;
    const path=geodesicPath(p1,p2,cx,cy,R);if(!path)continue;
    const op=Math.max(0.04,0.25*(1-cAbs(p2)*0.8)).toFixed(2);
    edgeHtml+=`<path d="${path}" class="pd-edge" data-source="${pdState.centerId}" data-target="${tid}" stroke="var(--accent)" stroke-opacity="${op}" stroke-width="1"/>`;
  }
  $('pd-edges').innerHTML=edgeHtml;
  // Render nodes (GL or SVG fallback) — nodes group is never wiped by this function
  pdGLRender(pdState.positions,cx,cy,R,W,H);
}



function pdAnimateToNode(targetId){
  return new Promise(resolve=>{
    const target=pdState.positions.get(targetId);
    if(!target||cAbs(target)<0.001){resolve();return;}
    // ensure dims are populated
    if(!pdState.diskR){const d=_pdCanvasDims();pdState.diskCx=d.cx;pdState.diskCy=d.cy;pdState.diskR=d.R;pdState.diskW=d.W;pdState.diskH=d.H;}
    const{diskCx:cx,diskCy:cy,diskR:R,diskW:W,diskH:H}=pdState;
    const atanhR=Math.atanh(Math.min(cAbs(target),0.999));
    const dur=500,t0=performance.now();
    const oldPos=new Map(pdState.positions);
    function frame(now){
      const t=Math.min((now-t0)/dur,1);
      const et=t<0.5?2*t*t:1-Math.pow(-2*t+2,2)/2;
      const r=Math.tanh(et*atanhR);
      const a=cScale(target,r/cAbs(target));
      const np=new Map();
      for(const[id,pos]of oldPos)np.set(id,mobiusTransform(pos,a));
      pdGLRender(np,cx,cy,R,W,H);
      if(t<1){pdState.animRAF=requestAnimationFrame(frame);}
      else{
        pdState.animRAF=null;
        pdState._mobiusEnd=new Map();
        for(const[id,pos]of oldPos)pdState._mobiusEnd.set(id,mobiusTransform(pos,target));
        resolve();
      }
    }
    if(pdState.animRAF)cancelAnimationFrame(pdState.animRAF);
    pdState.animRAF=requestAnimationFrame(frame);
  });
}

function pdSettleIntoLayout(){
  return new Promise(resolve=>{
    const mEnd=pdState._mobiusEnd;
    if(!mEnd||mEnd.size===0){renderPoincareGraph();resolve();return;}
    const{diskCx:cx,diskCy:cy,diskR:R,diskW:W,diskH:H}=pdState;
    const dur=350,s0=performance.now();
    function settle(now){
      const st=Math.min((now-s0)/dur,1);
      const se=st*st*(3-2*st);
      const blended=new Map();
      for(const[id,clean]of pdState.positions){
        const end=mEnd.get(id);
        if(end){blended.set(id,[end[0]+(clean[0]-end[0])*se,end[1]+(clean[1]-end[1])*se]);}
        else blended.set(id,clean);
      }
      pdGLRender(blended,cx,cy,R,W,H);
      if(st<1){pdState.animRAF=requestAnimationFrame(settle);}
      else{pdState.animRAF=null;pdState._mobiusEnd=null;renderPoincareGraph();resolve();}
    }
    pdState.animRAF=requestAnimationFrame(settle);
  });
}

function _pdRenderBlended(blended,cx,cy,R){pdGLRender(blended,cx,cy,R);}

function renderPdDetail(id){
  const node=_pdNodeMap[id]; if(!node) return;
  const img=$('pd-detail-img');
  img.style.backgroundImage=node.thumbnail_path?`url(${thumbUrl(node.thumbnail_path)})`:'';
  img.style.display=node.thumbnail_path?'':'none';
  $('pd-detail-date').textContent=(node.taken_at||'').slice(0,10);
  $('pd-detail-label').textContent=node.label||node.taken_at||'';
  $('pd-detail-caption').textContent=node.caption||'';
  $('pd-detail').classList.add('open');
}
function hidePdDetail(){ $('pd-detail').classList.remove('open'); requestAnimationFrame(() => renderPoincareGraph()); }

function renderPdNav(){
  $('pd-back').disabled=pdHistory.length===0;
  const recent=pdHistory.slice(-3);
  const crumbs=recent.map((h,i)=>{
    const idx=pdHistory.length-recent.length+i;
    return `<span class="pd-crumb" data-idx="${idx}" style="cursor:pointer;color:var(--accent)">${escHtml((h.label||'').slice(0,20))}</span>`;
  }).join(' \u203a ');
  const center=_pdNodeMap[pdState.centerId];
  $('pd-breadcrumb').innerHTML=crumbs+(crumbs?' \u203a ':'')+
    `<strong>${escHtml((center&&(center.label||center.taken_at)||'').slice(0,30))}</strong>`;
  $('pd-breadcrumb').querySelectorAll('.pd-crumb').forEach(el=>{
    el.addEventListener('click',()=>{
      const idx=parseInt(el.dataset.idx);
      const entry=pdHistory[idx];
      if(entry){pdHistory.splice(idx);enterPoincareView(entry.id);}
    });
  });
}

function pdGoBack(){
  if(!pdHistory.length) return;
  const prev=pdHistory.pop();
  pdState.centerId=null;
  enterPoincareView(prev.id);
}

function escHtml(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

