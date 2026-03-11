#!/usr/bin/env python3
import re, sys

with open('/home/jfischer/claude/open-photo/op-viz.html', 'r') as f:
    src = f.read()

# ── 1. CSS: replace pd-nodes-html / pd-html-node block ──────────────────────
OLD_CSS = '''#pd-nodes-html { position:absolute; inset:0; pointer-events:none; }
.pd-html-node {
  position:absolute; border-radius:5px; background-color:#1c1a16;
  background-size:cover; background-position:center;
  pointer-events:all; cursor:pointer; transform:translate(-50%,-50%);
  transition: width 0.25s ease, height 0.25s ease, box-shadow 0.2s ease;
}
.pd-html-node.pd-root-node { box-shadow:0 0 0 2.5px var(--accent), 0 0 12px rgba(212,168,83,0.3); }
.pd-html-node.pd-hovered {
  z-index:50;
  box-shadow:0 0 16px rgba(212,168,83,0.5), 0 4px 20px rgba(0,0,0,0.7);
}
#pd-nodes-html.dragging .pd-html-node { transition: none !important; }'''

NEW_CSS = '#pd-gl-canvas { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }'

# ── 2. HTML: replace the div with canvas ────────────────────────────────────
OLD_HTML = '    <div id="pd-nodes-html"></div>'
NEW_HTML = '    <canvas id="pd-gl-canvas"></canvas>'

# ── 3. JS globals: inject GL code after _pdSimPull ──────────────────────────
OLD_GLOBALS = 'let _pdSimPull = 1.0;'

GL_CODE = '''let _pdSimPull = 1.0;
let _pdHoveredId = null;

// ── WebGL renderer ────────────────────────────────────────────
const _PD_MIN_R = 2, _PD_MAX_R = 38;
let _pdGL = null;

const _PD_VERT = `#version 300 es
precision highp float;
in vec2 a_corner;   // quad corner [-1,1]
in vec2 a_pos;      // disk position
in float a_radius;  // screen px radius
in vec2 a_uv;       // atlas tile origin
in float a_root;    // 1 = root node
uniform vec2 u_ctr; // disk center px
uniform float u_dr; // disk radius px
uniform vec2 u_res; // canvas size px
uniform float u_sl; // atlas slot size (1/grid)
out vec2 v_uv; out float v_vs; out float v_cd; out float v_root;
void main(){
  float r2=dot(a_pos,a_pos);
  v_vs=max(1.0-r2,0.0);
  v_cd=length(a_corner); // 0=center, 1=edge
  v_root=a_root;
  vec2 sc=u_ctr+a_pos*u_dr+a_corner*a_radius;
  vec2 cl=sc/u_res*2.0-1.0; cl.y=-cl.y;
  gl_Position=vec4(cl,0.0,1.0);
  v_uv=a_uv+(a_corner*0.5+0.5)*u_sl;
}`;

const _PD_FRAG = `#version 300 es
precision mediump float;
uniform sampler2D u_tex;
in vec2 v_uv; in float v_vs; in float v_cd; in float v_root;
out vec4 fragColor;
void main(){
  if(v_vs<0.012||v_cd>1.0)discard;
  float aa=smoothstep(1.0,0.88,v_cd);
  // root: amber ring
  if(v_root>0.5&&v_cd>0.80){fragColor=vec4(0.831,0.659,0.325,aa);return;}
  vec4 t=texture(u_tex,v_uv);
  fragColor=vec4(t.rgb,aa*t.a);
}`;

function initPdGL(){
  const cv=$('pd-gl-canvas'); if(!cv) return false;
  const gl=cv.getContext('webgl2',{alpha:true,premultipliedAlpha:false,antialias:false});
  if(!gl){console.warn('WebGL2 unavailable');return false;}
  const sh=(t,s)=>{
    const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
    if(!gl.getShaderParameter(x,gl.COMPILE_STATUS)){console.error(gl.getShaderInfoLog(x));return null;}
    return x;
  };
  const vs=sh(gl.VERTEX_SHADER,_PD_VERT),fs=sh(gl.FRAGMENT_SHADER,_PD_FRAG);
  if(!vs||!fs)return false;
  const p=gl.createProgram();gl.attachShader(p,vs);gl.attachShader(p,fs);gl.linkProgram(p);
  if(!gl.getProgramParameter(p,gl.LINK_STATUS)){console.error(gl.getProgramInfoLog(p));return false;}
  // quad corners buffer (shared, divisor=0)
  const qb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,qb);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,-1,1,1,-1,1]),gl.STATIC_DRAW);
  _pdGL={gl,prog:p,qb,ib:gl.createBuffer(),
    atlasTex:null,grid:1,atlasIdx:new Map(),sl:1,nodeCount:0,
    lc:gl.getAttribLocation(p,'a_corner'),
    lp:gl.getAttribLocation(p,'a_pos'),
    lr:gl.getAttribLocation(p,'a_radius'),
    lu:gl.getAttribLocation(p,'a_uv'),
    lt:gl.getAttribLocation(p,'a_root'),
    uc:gl.getUniformLocation(p,'u_ctr'),
    ud:gl.getUniformLocation(p,'u_dr'),
    ur:gl.getUniformLocation(p,'u_res'),
    us:gl.getUniformLocation(p,'u_sl'),
    ua:gl.getUniformLocation(p,'u_tex')
  };
  return true;
}

async function pdGLLoadAtlas(nodes){
  if(!_pdGL||!nodes||!nodes.length)return;
  const N=nodes.length,g=Math.ceil(Math.sqrt(N))||1,sz=g*64;
  const oc=document.createElement('canvas');oc.width=oc.height=sz;
  const ctx=oc.getContext('2d');ctx.fillStyle='#1c1a16';ctx.fillRect(0,0,sz,sz);
  const idx=new Map();
  await Promise.all(nodes.map((n,i)=>{
    idx.set(n.id,i);
    if(!n.thumbnail_path)return Promise.resolve();
    return new Promise(res=>{
      const img=new Image();
      img.crossOrigin='anonymous';
      img.onload=()=>{const x=(i%g)*64,y=Math.floor(i/g)*64;
        ctx.drawImage(img,x,y,64,64);res();};
      img.onerror=res;img.src=thumbUrl(n.thumbnail_path);
    });
  }));
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
}

function pdGLRender(positions,cx,cy,R){
  if(!_pdGL||!_pdGL.atlasTex)return;
  const g=_pdGL,gl=g.gl,cv=gl.canvas;
  const dpr=window.devicePixelRatio||1;
  const cw=Math.round(cv.clientWidth*dpr),ch=Math.round(cv.clientHeight*dpr);
  if(cv.width!==cw||cv.height!==ch){cv.width=cw;cv.height=ch;}
  gl.viewport(0,0,cw,ch);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  // build per-instance data: [px,py,radius,uu,uv,root] x6 floats = 24 bytes stride
  const entries=[];
  pdState.screenPositions.clear();
  for(const[id,pos]of positions){
    const vs=visualScale(pos);
    if(vs<0.005&&id!==pdState.centerId)continue;
    const isRoot=id===pdState.centerId;
    const nr_raw=_PD_MIN_R+(_PD_MAX_R-_PD_MIN_R)*Math.pow(vs,1.8);
    const nr=isRoot?Math.max(nr_raw,Math.min(64,R*0.22)):nr_raw;
    const slot=g.atlasIdx.get(id)??-1;
    const uu=slot>=0?(slot%g.grid)/g.grid:0;
    const uv=slot>=0?Math.floor(slot/g.grid)/g.grid:0;
    entries.push([pos[0],pos[1],nr*dpr,uu,uv,isRoot?1:0,vs,id]);
    pdState.screenPositions.set(id,{sx:cx+pos[0]*R,sy:cy+pos[1]*R,r:nr,vs});
  }
  // painter sort: far (low vs) first, close (high vs) last
  entries.sort((a,b)=>a[6]-b[6]);
  const N=entries.length;if(!N)return;
  const ST=6,d=new Float32Array(N*ST);
  for(let i=0;i<N;i++){const e=entries[i],b=i*ST;
    d[b]=e[0];d[b+1]=e[1];d[b+2]=e[2];d[b+3]=e[3];d[b+4]=e[4];d[b+5]=e[5];}
  gl.useProgram(g.prog);
  gl.uniform2f(g.uc,cx*dpr,cy*dpr);
  gl.uniform1f(g.ud,R*dpr);
  gl.uniform2f(g.ur,cw,ch);
  gl.uniform1f(g.us,g.sl);
  gl.uniform1i(g.ua,0);
  // corners (shared, divisor 0)
  gl.bindBuffer(gl.ARRAY_BUFFER,g.qb);
  gl.enableVertexAttribArray(g.lc);gl.vertexAttribPointer(g.lc,2,gl.FLOAT,false,0,0);
  gl.vertexAttribDivisor(g.lc,0);
  // instances
  gl.bindBuffer(gl.ARRAY_BUFFER,g.ib);gl.bufferData(gl.ARRAY_BUFFER,d,gl.DYNAMIC_DRAW);
  const BYTES=24; // 6 floats * 4
  gl.enableVertexAttribArray(g.lp);gl.vertexAttribPointer(g.lp,2,gl.FLOAT,false,BYTES,0);gl.vertexAttribDivisor(g.lp,1);
  gl.enableVertexAttribArray(g.lr);gl.vertexAttribPointer(g.lr,1,gl.FLOAT,false,BYTES,8);gl.vertexAttribDivisor(g.lr,1);
  gl.enableVertexAttribArray(g.lu);gl.vertexAttribPointer(g.lu,2,gl.FLOAT,false,BYTES,12);gl.vertexAttribDivisor(g.lu,1);
  gl.enableVertexAttribArray(g.lt);gl.vertexAttribPointer(g.lt,1,gl.FLOAT,false,BYTES,20);gl.vertexAttribDivisor(g.lt,1);
  gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,g.atlasTex);
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  gl.drawArraysInstanced(gl.TRIANGLES,0,6,N);
}

function _pdHitTest(cx,cy){
  const rect=$('view-poincare').getBoundingClientRect();
  const px=cx-rect.left,py=cy-rect.top;
  let best=null,bestD=Infinity;
  for(const[id,sp]of pdState.screenPositions){
    const d=Math.hypot(px-sp.sx,py-sp.sy);
    if(d<=sp.r+8&&d<bestD){bestD=d;best=id;}
  }
  return best;
}
// ── end WebGL ──────────────────────────────────────────'''

# ── 4. initPoincareView: add GL init + atlas load + _initPdEvents ─────────
OLD_INIT = '''  $('pd-back').addEventListener('click', pdGoBack);
  $('pd-detail-close').addEventListener('click', hidePdDetail);
  $('pd-detail-full-btn').addEventListener('click', () => { if (pdState.centerId) openDetail(pdState.centerId); });
  window.addEventListener('resize', () => { if (_currentView === 'poincare') requestAnimationFrame(renderPoincareGraph); });
  _initPdDrag();
  const forceSlider = $('pd-force-slider');'''

NEW_INIT = '''  $('pd-back').addEventListener('click', pdGoBack);
  $('pd-detail-close').addEventListener('click', hidePdDetail);
  $('pd-detail-full-btn').addEventListener('click', () => { if (pdState.centerId) openDetail(pdState.centerId); });
  window.addEventListener('resize', () => { if (_currentView === 'poincare') requestAnimationFrame(renderPoincareGraph); });
  _initPdDrag();
  _initPdEvents();
  const forceSlider = $('pd-force-slider');'''

OLD_INIT2 = '''  if (!_pdPhotos) {
    const data = await api('/api/photos');
    _pdPhotos = data.nodes;
    for (const n of _pdPhotos) _pdNodeMap[n.id] = n;
  }
  if (!_pdEmbLayout) _pdEmbLayout = await api(`/api/embedding-layout?limit=${_scatterLimit}`);
  $('pd-loading').style.display = 'none';
  _pdInitialized = true;
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
  } else {
    $('pd-empty').style.display = 'flex';
  }'''

NEW_INIT2 = '''  if(!_pdGL) initPdGL();
  if (!_pdPhotos) {
    const data = await api('/api/photos');
    _pdPhotos = data.nodes;
    for (const n of _pdPhotos) _pdNodeMap[n.id] = n;
  }
  if (!_pdEmbLayout) _pdEmbLayout = await api(`/api/embedding-layout?limit=${_scatterLimit}`);
  _pdInitialized = true;
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
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    await pdGLLoadAtlas(vn);
    renderPoincareGraph();
  } else {
    $('pd-empty').style.display = 'flex';
  }
  $('pd-loading').style.display = 'none';'''

# force slider: also reload atlas
OLD_FORCE = '''    if (pdState.centerId) {
      await pdComputeLayout(pdState.centerId);
      renderPoincareGraph();
    }'''
NEW_FORCE = '''    if (pdState.centerId) {
      await pdComputeLayout(pdState.centerId);
      const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
      await pdGLLoadAtlas(vn);
      renderPoincareGraph();
    }'''

# ── 5. enterPoincareView: parallel atlas load ─────────────────────────────
OLD_ENTER = '''  if (isNav && pdState.positions.size > 0) {
    // 1. Fly the clicked node to center via Möbius (600ms)
    await pdAnimateToNode(id);
    // 2. Compute fresh layout with new center
    await pdComputeLayout(id);
    // 3. Settle from Möbius end-state into clean layout (300ms)
    await pdSettleIntoLayout();
  } else {
    await pdComputeLayout(id);
    renderPoincareGraph();
  }'''

NEW_ENTER = '''  if (isNav && pdState.positions.size > 0) {
    const flyP = pdAnimateToNode(id);
    await pdComputeLayout(id);
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    const atlasP = pdGLLoadAtlas(vn);
    await flyP;
    await atlasP;
    await pdSettleIntoLayout();
  } else {
    await pdComputeLayout(id);
    const vn=[...pdState.positions.keys()].map(nid=>_pdNodeMap[nid]).filter(Boolean);
    await pdGLLoadAtlas(vn);
    renderPoincareGraph();
  }'''

# ── 6. _initPdDrag: remove nodesDiv refs, use _pdHitTest ─────────────────
OLD_DRAG = '''// Möbius drag navigation: swipe on empty space to pan through hyperbolic space
function _initPdDrag() {
  const container = $(\'view-poincare\');
  let dragging = false, dragStartX = 0, dragStartY = 0, dragMoved = false;
  let velocityX = 0, velocityY = 0, lastMoveTime = 0;
  let momentumRAF = null;

  const nodesDiv = $(\'pd-nodes-html\');
  function applyDragTransform(dx, dy) {
    if (pdState.animRAF) return;
    if (nodesDiv && !nodesDiv.classList.contains(\'dragging\')) nodesDiv.classList.add(\'dragging\');
    const { diskCx: cx, diskCy: cy, diskR: R } = pdState;
    const scale = 0.8 / R;
    const a = [dx * scale, dy * scale];
    const aLen = cAbs(a);
    if (aLen > 0.9) { a[0] *= 0.9 / aLen; a[1] *= 0.9 / aLen; }
    const newPositions = new Map();
    for (const [id, pos] of pdState.positions) newPositions.set(id, mobiusTransform(pos, a));
    pdState.positions = newPositions;
    // Fast path: update positions + sizes
    _pdRenderBlended(pdState.positions, cx, cy, R);
  }

  function startMomentum() {
    let mvx = velocityX, mvy = velocityY;
    if (Math.hypot(mvx, mvy) < 1) return;
    function tick() {
      mvx *= 0.92; mvy *= 0.92;
      if (Math.hypot(mvx, mvy) < 0.5) { momentumRAF = null; if (nodesDiv) nodesDiv.classList.remove(\'dragging\'); return; }
      applyDragTransform(-mvx, -mvy);
      momentumRAF = requestAnimationFrame(tick);
    }
    momentumRAF = requestAnimationFrame(tick);
  }
  function cancelMomentum() {
    if (momentumRAF) { cancelAnimationFrame(momentumRAF); momentumRAF = null; }
  }

  // Mouse drag on empty space
  container.addEventListener(\'mousedown\', e => {
    if (e.target.closest(\'.pd-html-node\')) return;
    cancelMomentum();
    dragging = true; dragMoved = false;
    dragStartX = e.clientX; dragStartY = e.clientY;
    velocityX = 0; velocityY = 0;
    lastMoveTime = performance.now();
    container.style.cursor = \'grabbing\';
    e.preventDefault();
  });
  window.addEventListener(\'mousemove\', e => {
    if (!dragging) return;
    const dx = e.clientX - dragStartX, dy = e.clientY - dragStartY;
    if (Math.hypot(dx, dy) > 3) dragMoved = true;
    if (!dragMoved) return;
    const now = performance.now();
    const dt = Math.max(now - lastMoveTime, 1);
    velocityX = dx / dt * 16; velocityY = dy / dt * 16;
    lastMoveTime = now;
    applyDragTransform(-dx, -dy);
    dragStartX = e.clientX; dragStartY = e.clientY;
  });
  window.addEventListener(\'mouseup\', () => {
    if (dragging) { dragging = false; container.style.cursor = \'\'; if (dragMoved) startMomentum(); else if (nodesDiv) nodesDiv.classList.remove(\'dragging\'); }
  });

  // Touch drag on empty space
  let touchId = null;
  container.addEventListener(\'touchstart\', e => {
    if (e.target.closest(\'.pd-html-node\')) return;
    if (e.touches.length !== 1) return;
    cancelMomentum();
    touchId = e.touches[0].identifier;
    dragStartX = e.touches[0].clientX; dragStartY = e.touches[0].clientY;
    dragMoved = false;
    velocityX = 0; velocityY = 0;
    lastMoveTime = performance.now();
  }, { passive: true });

  container.addEventListener(\'touchmove\', e => {
    if (touchId === null) return;
    const touch = [...e.touches].find(t => t.identifier === touchId);
    if (!touch) return;
    const dx = touch.clientX - dragStartX, dy = touch.clientY - dragStartY;
    if (!dragMoved && Math.hypot(dx, dy) < 8) return;
    dragMoved = true;
    e.preventDefault();
    const now = performance.now();
    const dt = Math.max(now - lastMoveTime, 1);
    velocityX = dx / dt * 16; velocityY = dy / dt * 16;
    lastMoveTime = now;
    applyDragTransform(-dx, -dy);
    dragStartX = touch.clientX; dragStartY = touch.clientY;
  }, { passive: false });

  container.addEventListener(\'touchend\', e => {
    if (touchId === null) return;
    const found = [...e.changedTouches].find(t => t.identifier === touchId);
    if (found) { touchId = null; if (dragMoved) startMomentum(); else if (nodesDiv) nodesDiv.classList.remove(\'dragging\'); }
  }, { passive: true });
}'''

NEW_DRAG_AND_EVENTS = '''
function _initPdDrag(){
  const container=$(\'view-poincare\');
  let dragging=false,dragStartX=0,dragStartY=0,dragMoved=false;
  let velocityX=0,velocityY=0,lastMoveTime=0,momentumRAF=null;
  function applyDragTransform(dx,dy){
    if(pdState.animRAF)return;
    const{diskCx:cx,diskCy:cy,diskR:R}=pdState;
    const scale=0.8/R;let a=[dx*scale,dy*scale];
    const aLen=cAbs(a);if(aLen>0.9){a[0]*=.9/aLen;a[1]*=.9/aLen;}
    const np=new Map();
    for(const[id,pos]of pdState.positions)np.set(id,mobiusTransform(pos,a));
    pdState.positions=np;
    pdGLRender(pdState.positions,cx,cy,R);
  }
  function startMomentum(){
    let mvx=velocityX,mvy=velocityY;
    if(Math.hypot(mvx,mvy)<1)return;
    function tick(){mvx*=.92;mvy*=.92;
      if(Math.hypot(mvx,mvy)<.5){momentumRAF=null;return;}
      applyDragTransform(-mvx,-mvy);momentumRAF=requestAnimationFrame(tick);}
    momentumRAF=requestAnimationFrame(tick);
  }
  function cancelMomentum(){if(momentumRAF){cancelAnimationFrame(momentumRAF);momentumRAF=null;}}
  container.addEventListener(\'mousedown\',e=>{
    if(_pdHitTest(e.clientX,e.clientY))return;
    cancelMomentum();dragging=true;dragMoved=false;
    dragStartX=e.clientX;dragStartY=e.clientY;
    velocityX=0;velocityY=0;lastMoveTime=performance.now();
    container.style.cursor=\'grabbing\';e.preventDefault();
  });
  window.addEventListener(\'mousemove\',e=>{
    if(!dragging)return;
    const dx=e.clientX-dragStartX,dy=e.clientY-dragStartY;
    if(Math.hypot(dx,dy)>3)dragMoved=true;if(!dragMoved)return;
    const now=performance.now(),dt=Math.max(now-lastMoveTime,1);
    velocityX=dx/dt*16;velocityY=dy/dt*16;lastMoveTime=now;
    applyDragTransform(-dx,-dy);dragStartX=e.clientX;dragStartY=e.clientY;
  });
  window.addEventListener(\'mouseup\',()=>{
    if(dragging){dragging=false;container.style.cursor=\'\';if(dragMoved)startMomentum();}
  });
  let touchId=null;
  container.addEventListener(\'touchstart\',e=>{
    if(e.touches.length!==1)return;
    if(_pdHitTest(e.touches[0].clientX,e.touches[0].clientY))return;
    cancelMomentum();touchId=e.touches[0].identifier;
    dragStartX=e.touches[0].clientX;dragStartY=e.touches[0].clientY;
    dragMoved=false;velocityX=0;velocityY=0;lastMoveTime=performance.now();
  },{passive:true});
  container.addEventListener(\'touchmove\',e=>{
    if(touchId===null)return;
    const touch=[...e.touches].find(t=>t.identifier===touchId);if(!touch)return;
    const dx=touch.clientX-dragStartX,dy=touch.clientY-dragStartY;
    if(!dragMoved&&Math.hypot(dx,dy)<8)return;
    dragMoved=true;e.preventDefault();
    const now=performance.now(),dt=Math.max(now-lastMoveTime,1);
    velocityX=dx/dt*16;velocityY=dy/dt*16;lastMoveTime=now;
    applyDragTransform(-dx,-dy);dragStartX=touch.clientX;dragStartY=touch.clientY;
  },{passive:false});
  container.addEventListener(\'touchend\',e=>{
    if(touchId===null)return;
    const found=[...e.changedTouches].find(t=>t.identifier===touchId);
    if(found){touchId=null;if(dragMoved)startMomentum();}
  },{passive:true});
}

function _initPdEvents(){
  const container=$(\'view-poincare\'),tip=$(\'pd-tooltip\');
  container.addEventListener(\'mousemove\',e=>{
    const id=_pdHitTest(e.clientX,e.clientY);
    if(tip.style.display===\'block\'){tip.style.left=(e.clientX+14)+\'px\';tip.style.top=(e.clientY-24)+\'px\';}
    if(id===_pdHoveredId)return;
    _pdHoveredId=id;
    const svg=$(\'pd-svg\'),ring=svg&&svg.querySelector(\'#pd-hover-ring\');
    if(id&&id!==pdState.centerId){
      const sp=pdState.screenPositions.get(id);
      if(ring&&sp){ring.setAttribute(\'cx\',sp.sx);ring.setAttribute(\'cy\',sp.sy);ring.setAttribute(\'r\',sp.r+3);ring.style.display=\'\';}
      const n=_pdNodeMap[id];
      if(n){tip.innerHTML=`<div style="color:var(--accent);font-size:10px;margin-bottom:3px">${(n.taken_at||\'\').slice(0,7)}</div><div>${escHtml((n.caption||n.label||\'\').slice(0,80))}</div>`;tip.style.display=\'block\';}
    }else{if(ring)ring.style.display=\'none\';tip.style.display=\'none\';}
  });
  container.addEventListener(\'mouseleave\',()=>{
    _pdHoveredId=null;
    const ring=$(\'pd-svg\')&&$(\'pd-svg\').querySelector(\'#pd-hover-ring\');
    if(ring)ring.style.display=\'none\';$(\'pd-tooltip\').style.display=\'none\';
  });
  let _ct=null,_lid=null;
  container.addEventListener(\'click\',e=>{
    const id=_pdHitTest(e.clientX,e.clientY);if(!id)return;
    if(_lid===id&&_ct){clearTimeout(_ct);_ct=null;_lid=null;openDetail(id);}
    else{clearTimeout(_ct);_lid=id;
      _ct=setTimeout(()=>{_ct=null;_lid=null;
        if(id!==pdState.centerId)enterPoincareView(id);else renderPdDetail(id);
      },220);}
  });
  container.addEventListener(\'dblclick\',e=>{if(!_pdHitTest(e.clientX,e.clientY))pdGoBack();});
  let _lt=null,_li=null,_ltid=null,_tsx=0,_tsy=0;
  container.addEventListener(\'touchstart\',e=>{
    const t=e.touches[0],id=_pdHitTest(t.clientX,t.clientY);if(!id)return;
    _li=id;_ltid=t.identifier;_tsx=t.clientX;_tsy=t.clientY;
    clearTimeout(_lt);
    _lt=setTimeout(()=>{_lt=null;if(_li)openDetail(_li);},500);
  },{passive:true});
  container.addEventListener(\'touchmove\',e=>{
    const found=[...e.changedTouches].find(t=>t.identifier===_ltid);
    if(found&&Math.hypot(found.clientX-_tsx,found.clientY-_tsy)>8){clearTimeout(_lt);_lt=null;}
  },{passive:true});
  container.addEventListener(\'touchend\',e=>{
    const found=[...e.changedTouches].find(t=>t.identifier===_ltid);if(!found)return;
    const fired=!_lt;clearTimeout(_lt);_lt=null;_ltid=null;
    const id=_li;_li=null;
    if(fired)return;
    if(id&&id!==pdState.centerId)enterPoincareView(id);else if(id)renderPdDetail(id);
  },{passive:false});
}'''

# ── 7. renderPoincareGraph: GL version ───────────────────────────────────
OLD_RPG_START = '''function renderPoincareGraph() {
  const svg = $(\'pd-svg\');
  const nodesDiv = $(\'pd-nodes-html\');
  if (!svg || !nodesDiv || pdState.positions.size === 0) return;'''

NEW_RPG = '''function renderPoincareGraph(){
  const svg=$(\'pd-svg\');
  if(!svg||pdState.positions.size===0)return;
  const W=svg.clientWidth||window.innerWidth,H=svg.clientHeight||window.innerHeight;
  const detailEl=$(\'pd-detail\');
  const detailH=(detailEl&&detailEl.classList.contains(\'open\'))?(detailEl.offsetHeight||0):0;
  const visH=H-detailH,R=Math.min(W,visH)*0.44,cx=W/2,cy=visH/2;
  pdState.diskCx=cx;pdState.diskCy=cy;pdState.diskR=R;
  svg.setAttribute(\'viewBox\',`0 0 ${W} ${H}`);svg.setAttribute(\'width\',W);svg.setAttribute(\'height\',H);
  const top5=new Set(pdState.topSimilar);
  let s=`<circle cx="${cx}" cy="${cy}" r="${R}" class="pd-boundary"/>`;
  s+=`<circle cx="${cx}" cy="${cy}" r="${R*0.07}" class="pd-center-glow" stroke-width="2"/>`;
  s+=`<circle id="pd-hover-ring" cx="0" cy="0" r="0" fill="none" stroke="var(--accent)" stroke-width="2" stroke-opacity="0.8" style="display:none"/>`;
  s+=\'<g id="pd-edges">\';
  for(const tid of top5){
    const p1=pdState.positions.get(pdState.centerId),p2=pdState.positions.get(tid);
    if(!p1||!p2)continue;
    const path=geodesicPath(p1,p2,cx,cy,R);if(!path)continue;
    const op=Math.max(0.04,0.25*(1-cAbs(p2)*0.8)).toFixed(2);
    s+=`<path d="${path}" class="pd-edge" stroke="var(--accent)" stroke-opacity="${op}" stroke-width="1"/>`;
  }
  s+=\'</g>\';
  svg.innerHTML=s;
  pdGLRender(pdState.positions,cx,cy,R);
}'''

# The old renderPoincareGraph body ends with _attachPdEvents(nodesDiv); \n}
OLD_RPG_END = '''  _attachPdEvents(nodesDiv);
}'''

# ── 8. Animation functions: replace DOM writes with GL calls ─────────────
OLD_ANIM = '''// Möbius fly-to: 600ms hyperbolic fly only. Settle is separate.
function pdAnimateToNode(targetId) {
  return new Promise(resolve => {
    const target = pdState.positions.get(targetId);
    if (!target || cAbs(target) < 0.001) { resolve(); return; }
    const { diskCx: cx, diskCy: cy, diskR: R } = pdState;
    const atanhR = Math.atanh(Math.min(cAbs(target), 0.999));
    const dur = 500, t0 = performance.now();
    const oldPos = new Map(pdState.positions);

    // Disable CSS transitions during rAF
    document.querySelectorAll(\'.pd-html-node\').forEach(n => n.style.transition = \'none\');

    function frame(now) {
      const t = Math.min((now - t0) / dur, 1);
      const et = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const r = Math.tanh(et * atanhR);
      const a = cScale(target, r / cAbs(target));
      _pdUpdatePositions(oldPos, a, cx, cy, R);
      if (t < 1) {
        pdState.animRAF = requestAnimationFrame(frame);
      } else {
        pdState.animRAF = null;
        // Store where each node ended up after full Möbius
        pdState._mobiusEnd = new Map();
        for (const [id, pos] of oldPos) pdState._mobiusEnd.set(id, mobiusTransform(pos, target));
        resolve();
      }
    }
    if (pdState.animRAF) cancelAnimationFrame(pdState.animRAF);
    pdState.animRAF = requestAnimationFrame(frame);
  });
}

// Settle: lerp from Möbius end positions into the freshly computed clean layout (400ms)
function pdSettleIntoLayout() {
  return new Promise(resolve => {
    const mEnd = pdState._mobiusEnd;
    if (!mEnd || mEnd.size === 0) { renderPoincareGraph(); resolve(); return; }
    const svg = $(\'pd-svg\');
    const W = svg.clientWidth || window.innerWidth, H = svg.clientHeight || window.innerHeight;
    const R = Math.min(W, H) * 0.44, cx = W / 2, cy = H / 2;
    pdState.diskCx = cx; pdState.diskCy = cy; pdState.diskR = R;

    // Rebuild DOM for new layout (but start at Möbius end positions)
    renderPoincareGraph();  // creates nodes at clean positions
    // Immediately move them to Möbius end positions
    document.querySelectorAll(\'.pd-html-node\').forEach(n => n.style.transition = \'none\');
    for (const [id, endPos] of mEnd) {
      const el = pdState.nodeEls.get(id);
      if (el) {
        el.style.left = (cx + endPos[0] * R) + \'px\';
        el.style.top = (cy + endPos[1] * R) + \'px\';
      }
    }

    // Now lerp from Möbius end to clean layout
    const dur = 400, s0 = performance.now();
    function settle(now) {
      const st = Math.min((now - s0) / dur, 1);
      const se = st * st * (3 - 2 * st); // smoothstep
      for (const [id, clean] of pdState.positions) {
        const end = mEnd.get(id);
        const el = pdState.nodeEls.get(id);
        if (!el) continue;
        if (end) {
          const bx = end[0] + (clean[0] - end[0]) * se;
          const by = end[1] + (clean[1] - end[1]) * se;
          el.style.left = (cx + bx * R) + \'px\';
          el.style.top = (cy + by * R) + \'px\';
        }
      }
      if (st < 1) {
        pdState.animRAF = requestAnimationFrame(settle);
      } else {
        pdState.animRAF = null;
        pdState._mobiusEnd = null;
        document.querySelectorAll(\'.pd-html-node\').forEach(n => n.style.transition = \'\');
        resolve();
      }
    }
    // Force layout before starting animation
    void document.body.offsetHeight;
    pdState.animRAF = requestAnimationFrame(settle);
  });
}

// Update HTML div positions during Möbius fly-through
function _pdUpdatePositions(positions, a, cx, cy, R) {
  const MIN_R = 2, MAX_R = 38;
  for (const [id, pos] of positions) {
    const np = mobiusTransform(pos, a);
    const vs = visualScale(np);
    const el = pdState.nodeEls.get(id); if (!el) continue;
    if (vs < 0.012 && id !== pdState.centerId) { el.style.display = \'none\'; continue; }
    el.style.display = \'\';
    const nr = Math.max(MIN_R, MIN_R + (MAX_R - MIN_R) * Math.pow(vs, 1.8));
    const isRoot = id === pdState.centerId, _cr = Math.min(90, R * 0.35);
    const finalR = isRoot ? Math.max(nr, _cr) : nr;
    el.style.left = (cx + np[0] * R).toFixed(1) + \'px\';
    el.style.top = (cy + np[1] * R).toFixed(1) + \'px\';
    el.style.width = (finalR * 2).toFixed(1) + \'px\';
    el.style.height = (finalR * 2).toFixed(1) + \'px\';
  }
}

// Update HTML div positions during settle lerp
function _pdRenderBlended(blended, cx, cy, R) {
  const MIN_R = 2, MAX_R = 38;
  for (const [id, pos] of blended) {
    const el = pdState.nodeEls.get(id); if (!el) continue;
    const vs = visualScale(pos);
    const nr = Math.max(MIN_R, MIN_R + (MAX_R - MIN_R) * Math.pow(vs, 1.8));
    const isRoot = id === pdState.centerId, _cr = Math.min(90, R * 0.35);
    const finalR = isRoot ? Math.max(nr, _cr) : nr;
    el.style.left = (cx + pos[0] * R).toFixed(1) + \'px\';
    el.style.top = (cy + pos[1] * R).toFixed(1) + \'px\';
    el.style.width = (finalR * 2).toFixed(1) + \'px\';
    el.style.height = (finalR * 2).toFixed(1) + \'px\';
    el.style.zIndex = Math.round(vs * 90);
    el.style.display = (vs < 0.012 && !isRoot) ? \'none\' : \'\';
  }
}'''

NEW_ANIM = '''function pdAnimateToNode(targetId){
  return new Promise(resolve=>{
    const target=pdState.positions.get(targetId);
    if(!target||cAbs(target)<0.001){resolve();return;}
    const{diskCx:cx,diskCy:cy,diskR:R}=pdState;
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
      pdGLRender(np,cx,cy,R);
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
    const{diskCx:cx,diskCy:cy,diskR:R}=pdState;
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
      pdGLRender(blended,cx,cy,R);
      if(st<1){pdState.animRAF=requestAnimationFrame(settle);}
      else{pdState.animRAF=null;pdState._mobiusEnd=null;renderPoincareGraph();resolve();}
    }
    pdState.animRAF=requestAnimationFrame(settle);
  });
}

function _pdRenderBlended(blended,cx,cy,R){pdGLRender(blended,cx,cy,R);}'''

# ── Apply all substitutions ───────────────────────────────────────────────
out = src

def sub(old, new, label):
    global out
    if old not in out:
        print(f"WARN: not found: {label}")
        return
    out = out.replace(old, new, 1)
    print(f"OK: {label}")

sub(OLD_CSS, NEW_CSS, 'CSS')
sub(OLD_HTML, NEW_HTML, 'HTML canvas')
sub(OLD_GLOBALS, GL_CODE, 'GL globals')
sub(OLD_INIT2, NEW_INIT2, 'initPoincareView body')
sub(OLD_INIT, NEW_INIT, 'initPoincareView drag/events')
sub(OLD_FORCE, NEW_FORCE, 'force slider atlas')
sub(OLD_ENTER, NEW_ENTER, 'enterPoincareView')

# Replace drag + add _initPdEvents (search for unique start of function)
old_drag_marker = "// M\u00f6bius drag navigation: swipe on empty space to pan through hyperbolic space"
if old_drag_marker in out:
    # find end of _initPdDrag closing brace
    start = out.index(old_drag_marker)
    # The function ends with the lone closing brace after touchend
    # Find 'async function enterPoincareView' which immediately follows
    end_marker = "\nasync function enterPoincareView"
    end = out.index(end_marker, start)
    out = out[:start] + NEW_DRAG_AND_EVENTS + "\n" + out[end:]
    print("OK: _initPdDrag + _initPdEvents")
else:
    print("WARN: _initPdDrag not found")

# renderPoincareGraph: find and replace from function def to _attachPdEvents(nodesDiv);\n}
rpg_start = "function renderPoincareGraph() {\n  const svg = $('pd-svg');\n  const nodesDiv = $('pd-nodes-html');"
rpg_end_marker = "  _attachPdEvents(nodesDiv);\n}"
if rpg_start in out and rpg_end_marker in out:
    s = out.index(rpg_start)
    e = out.index(rpg_end_marker, s) + len(rpg_end_marker)
    out = out[:s] + NEW_RPG + out[e:]
    print("OK: renderPoincareGraph")
else:
    print(f"WARN: renderPoincareGraph not found (rpg_start={rpg_start in out}, rpg_end={rpg_end_marker in out})")

# Now remove the stale let _pdHoveredId = null; and _attachPdEvents
stale = "let _pdHoveredId = null;\nfunction _attachPdEvents"
if stale in out:
    # remove from here to end of _attachPdEvents closing brace
    # which is followed by two newlines then pdAnimateToNode
    s = out.index(stale)
    end_marker2 = "\n\n// M\u00f6bius fly-to"
    if end_marker2 in out:
        e = out.index(end_marker2, s)
        out = out[:s] + out[e:]
        print("OK: removed _pdHoveredId + _attachPdEvents")
    else:
        print("WARN: _attachPdEvents end not found")
else:
    print("WARN: stale _pdHoveredId not found (may be already removed)")

# Animation functions
if OLD_ANIM in out:
    out = out.replace(OLD_ANIM, NEW_ANIM, 1)
    print("OK: animation functions")
else:
    print("WARN: animation functions not found")

with open('/home/jfischer/claude/open-photo/op-viz.html', 'w') as f:
    f.write(out)
print(f"Done. {len(out)} chars, {out.count(chr(10))+1} lines")
