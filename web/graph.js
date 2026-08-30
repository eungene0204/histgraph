// 힘기반 배치 + 캔버스 렌더러.
//
// 라이브러리를 쓰지 않는다 — 수집 파이프라인이 표준 라이브러리만 쓰듯,
// 화면도 브라우저가 이미 가진 것만 쓴다.
//
// 노드 200개 수준에서는 O(n²) 반발력으로 충분하다 (틱당 4만 회). 그보다
// 커지면 화면에서 읽히지 않으므로 서버가 먼저 잘라서 보낸다.

const TAU = Math.PI * 2;

// 한 틱에 노드가 움직일 수 있는 최대 거리(px)
const MAX_STEP = 34;

// 색은 큰 갈래만 말한다. 세부 타입은 모양이 말한다 — 9색을 한 화면에
// 쓰면 색약에서 구분이 무너진다(검증 실측: 8색 전체 조합 최악 ΔE 1.6).
export const GROUP_COLOR = {
  actor: '#3987e5', // 인물·단체
  event: '#d95926', // 사건
  thing: '#199e70', // 장소·유물·작품
  frame: '#8b8b84', // 시대·직위 — 뼈대라서 물러나 있어야 한다
};

// 타입별 글리프. 색 하나에 여러 타입이 얹히므로 모양이 실제 구분자다.
export const TYPE_SHAPE = {
  person: 'circle',
  org: 'hexagon',
  event: 'diamond',
  place: 'square',
  heritage: 'triangle',
  artwork: 'triangle',
  media: 'square',
  period: 'ring',
  role: 'pill',
};

const SURFACE = '#141413';
const EDGE_BASE = 'rgba(198,196,186,0.30)';
const EDGE_SOFT = 'rgba(198,196,186,0.16)';
const TEXT = '#f0efec';
const TEXT_DIM = 'rgba(240,239,236,0.55)';

export class GraphView {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.center = null;
    this.hover = null;
    this.selected = null;
    this.tx = 0;
    this.ty = 0;
    this.k = 1;
    this.alpha = 0;
    this.onSelect = opts.onSelect || (() => {});
    this.onExpand = opts.onExpand || (() => {});
    this.onHover = opts.onHover || (() => {});
    this.showLabels = true;

    this._bindEvents();
    this._resize();
    new ResizeObserver(() => this._resize()).observe(canvas.parentElement);
    requestAnimationFrame(() => this._frame());
  }

  // --- 데이터 ---------------------------------------------------------

  // merge=true 면 기존 배치를 유지한 채 새 노드만 얹는다. 펼치기를 할
  // 때마다 화면이 통째로 다시 튀면 사용자는 방금 보던 것을 잃는다.
  setData(payload, { merge = false } = {}) {
    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 600;
    if (!merge) {
      this.nodes = [];
      this.edges = [];
      this.byId = new Map();
    }

    const incoming = new Set();
    let placed = 0;
    for (const n of payload.nodes) {
      incoming.add(n.id);
      let node = this.byId.get(n.id);
      if (!node) {
        // **나선 위에 고르게 놓는다.** 무작위로 뿌리면 노드 몇 개가 거의
        // 겹친 채 시작하고, 그 지점의 반발력이 폭발해 서로를 화면 밖으로
        // 튕겨낸다. 한번 멀리 나간 노드는 alpha 가 식은 뒤라 돌아오지
        // 못하고 그 자리에 굳는다 (실측: 117개 중 예닐곱이 그렇게 됐다).
        const anchor = this.byId.get(payload.center);
        const i = placed++;
        const a = i * 2.399963;             // 황금각 — 뭉치지 않고 퍼진다
        const d = 40 + 26 * Math.sqrt(i);
        node = {
          ...n,
          x: (anchor ? anchor.x : w / 2) + Math.cos(a) * d,
          y: (anchor ? anchor.y : h / 2) + Math.sin(a) * d,
          vx: 0, vy: 0, fixed: false,
        };
        this.byId.set(n.id, node);
        this.nodes.push(node);
      } else {
        Object.assign(node, { degree: Math.max(node.degree, n.degree) });
      }
      node.r = nodeRadius(node);
    }

    const seen = new Set(this.edges.map(edgeKey));
    for (const e of payload.edges) {
      if (!this.byId.has(e.s) || !this.byId.has(e.t)) continue;
      const key = `${e.s}|${e.t}|${e.type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      this.edges.push({ ...e, kind: 'edge' });
    }
    for (const s of payload.same_as || []) {
      if (!this.byId.has(s.a) || !this.byId.has(s.b)) continue;
      const key = `${s.a}|${s.b}|same_as`;
      if (seen.has(key)) continue;
      seen.add(key);
      this.edges.push({ s: s.a, t: s.b, type: 'same_as', label: '동일 실체', conf: 1, kind: 'same_as' });
    }

    this.center = payload.center;
    const c = this.byId.get(payload.center);
    if (c && !merge) {
      c.x = w / 2;
      c.y = h / 2;
    }
    this.adjacency = null;
    this.alpha = 1;
    this.autoFit = true;   // 사용자가 화면을 움직이기 전까지는 카메라가 따라간다
    if (!merge) this.resetView();
    return incoming;
  }

  neighborsOf(id) {
    if (!this.adjacency) {
      this.adjacency = new Map();
      for (const e of this.edges) {
        if (!this.adjacency.has(e.s)) this.adjacency.set(e.s, new Set());
        if (!this.adjacency.has(e.t)) this.adjacency.set(e.t, new Set());
        this.adjacency.get(e.s).add(e.t);
        this.adjacency.get(e.t).add(e.s);
      }
    }
    return this.adjacency.get(id) || new Set();
  }

  // --- 시뮬레이션 -----------------------------------------------------
  _tick() {
    const nodes = this.nodes;
    const n = nodes.length;
    if (!n || this.alpha < 0.005) return;

    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 600;
    const cx = w / 2;
    const cy = h / 2;

    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 === 0) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        if (d2 > 640000) continue; // 800px 밖은 서로 밀 이유가 없다
        const d = Math.sqrt(d2);
        // 반발이 용수철보다 약하면 그래프가 가운데로 뭉쳐 라벨이 전부
        // 겹친다. 거리 100px 에서 용수철과 비슷한 크기가 되도록 잡았다.
        // 큰 노드일수록 더 넓은 자리를 요구한다.
        const force = (5200 + (a.r + b.r) * 120) / d2;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }

    for (const e of this.edges) {
      const a = this.byId.get(e.s);
      const b = this.byId.get(e.t);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      // 같은 실체(same_as)는 붙여 놓는다 — 한 개체가 둘로 보이면 안 된다
      const rest = e.kind === 'same_as' ? 34 : 112 + a.r + b.r;
      const k = e.kind === 'same_as' ? 0.06 : 0.02;
      const f = (d - rest) * k;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    for (const node of nodes) {
      if (node.fixed) { node.vx = 0; node.vy = 0; continue; }
      // 중심 노드는 화면 가운데를 지킨다 — 무엇을 보고 있는지 잃지 않게
      const pull = node.id === this.center ? 0.06 : 0.016;
      node.vx += (cx - node.x) * pull;
      node.vy += (cy - node.y) * pull;
      node.vx *= 0.82;
      node.vy *= 0.82;
      // 한 틱에 움직일 수 있는 거리를 묶어둔다. 이게 없으면 초반 한 번의
      // 큰 힘으로 노드가 수천 px 밖으로 나가고, 돌아오는 속도는 alpha 에
      // 비례해 줄어들어 영영 못 돌아온다.
      const step = Math.min(MAX_STEP, Math.hypot(node.vx, node.vy) * this.alpha);
      const v = Math.hypot(node.vx, node.vy) || 1;
      node.x += (node.vx / v) * step;
      node.y += (node.vy / v) * step;
    }

    this.alpha *= 0.985;

    // **식을 때까지 카메라가 따라간다.** 한 번만 맞추면 그 뒤로도 배치가
    // 계속 퍼져서 결국 화면 밖으로 나간다 (실측: 노드 117개에서 6초에
    // 화면의 16%를 채우던 그래프가 20초에는 1%만 남았다). 사용자가
    // 직접 움직이기 시작하면 그때부터 손을 뗀다.
    if (this.autoFit && this.alpha > 0.02) this.fitView();
  }

  fitView(pad = 70) {
    if (!this.nodes.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      minX = Math.min(minX, n.x - n.r); maxX = Math.max(maxX, n.x + n.r);
      minY = Math.min(minY, n.y - n.r); maxY = Math.max(maxY, n.y + n.r);
    }
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const k = Math.min(1.35, Math.max(0.22,
      Math.min((w - pad * 2) / Math.max(maxX - minX, 1),
               (h - pad * 2) / Math.max(maxY - minY, 1))));
    this.k = k;
    this.tx = w / 2 - ((minX + maxX) / 2) * k;
    this.ty = h / 2 - ((minY + maxY) / 2) * k;
  }

  // --- 렌더 -----------------------------------------------------------
  _frame() {
    this._tick();
    this._draw();
    requestAnimationFrame(() => this._frame());
  }

  _draw() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(this.tx, this.ty);
    ctx.scale(this.k, this.k);

    // **어둡게 하는 것은 가리킬 때뿐이다.** 선택만으로 나머지를 죽이면,
    // 중심을 열어둔 기본 화면에서 이웃끼리의 관계가 가장 흐린 선이 된다 —
    // 정작 "서로 어떻게 얽혀 있나"가 안 보인다.
    const spot = this.hover;
    const near = spot ? this.neighborsOf(spot) : null;
    const lit = (id) => !spot || id === spot || near.has(id);
    const focus = spot || this.selected;  // 라벨을 굵게 쓸 대상
    // 관계 이름은 가리켰을 때만. 늘 그리면 자녀가 12명인 세종 주위에
    // '자녀'가 12번 겹쳐 찍힌다.
    const showEdgeLabels = spot && near.size <= 16 && this.k > 0.5;

    // 엣지 먼저 — 노드가 그 위에 얹혀야 교점이 지저분해지지 않는다
    for (const e of this.edges) {
      const a = this.byId.get(e.s);
      const b = this.byId.get(e.t);
      if (!a || !b) continue;
      const active = spot && (e.s === spot || e.t === spot);
      // 선은 출발 노드의 갈래 색을 입는다 — 사람이 건 관계인지 사건이
      // 건 관계인지가 한눈에 갈린다.
      const color = e.kind === 'same_as'
        ? EDGE_BASE
        : (GROUP_COLOR[a.group] || EDGE_BASE);
      if (spot && !active) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = EDGE_SOFT;
        ctx.lineWidth = 1;
      } else {
        ctx.globalAlpha = active ? 1 : 0.6;
        ctx.strokeStyle = color;
        ctx.lineWidth = active ? 1.9 : 1.3;
      }
      // 추출로 얻은 관계(신뢰도 < 1)는 점선. 구조화 소스가 준 사실과
      // 텍스트에서 추론한 사실을 화면에서 구분하지 않으면 둘 다 못 믿는다.
      ctx.setLineDash(e.kind === 'same_as' ? [2, 4] : e.conf < 1 ? [5, 4] : []);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);

      if (e.kind !== 'same_as' && (!spot || active)) {
        drawArrow(ctx, a, b, ctx.strokeStyle);
      }
      if (active && showEdgeLabels) {
        drawEdgeLabel(ctx, a, b, e.label, this.k);
      }
      ctx.globalAlpha = 1;
    }

    for (const node of this.nodes) {
      drawNode(ctx, node, {
        dim: !lit(node.id),
        focused: node.id === focus,
        center: node.id === this.center,
        selected: node.id === this.selected,
      });
    }

    if (this.showLabels) {
      // **자리가 있으면 붙이고 없으면 만다.** '차수 6 이상만' 같은 기준은
      // 화면 사정과 무관해서, 왕조를 중심에 놓으면 왕후 수십 명이 이름
      // 없는 파란 점이 되고 만다. 실제로 겹치는지를 재서 정하면 확대할
      // 때마다 더 많은 이름이 저절로 드러난다.
      const placed = [];
      const rank = (n) => (n.id === focus ? 3 : n.id === this.center ? 2 : 0) + Math.min(n.degree / 40, 1);
      const candidates = this.nodes
        .filter((n) => lit(n.id))
        .sort((a, b) => rank(b) - rank(a));

      for (const node of candidates) {
        const strong = node.id === focus || node.id === this.center;
        const box = labelBox(ctx, node, strong, this.k);
        // 중심과 가리킨 노드의 이름은 무슨 일이 있어도 그린다
        if (!strong && placed.some((p) => overlaps(p, box))) continue;
        placed.push(box);
        drawLabel(ctx, node, strong, this.k);
      }
    }
    ctx.restore();
  }

  // --- 상호작용 -------------------------------------------------------
  _resize() {
    this.dpr = window.devicePixelRatio || 1;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    this.canvas.width = w * this.dpr;
    this.canvas.height = h * this.dpr;
    this.alpha = Math.max(this.alpha, 0.35);
  }

  resetView() {
    this.tx = 0;
    this.ty = 0;
    this.k = 1;
  }

  toWorld(px, py) {
    return { x: (px - this.tx) / this.k, y: (py - this.ty) / this.k };
  }

  nodeAt(px, py) {
    const p = this.toWorld(px, py);
    let best = null;
    let bestD = Infinity;
    for (const n of this.nodes) {
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d < n.r + 6 && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  _bindEvents() {
    const c = this.canvas;
    let dragNode = null;
    let panning = false;
    let last = null;
    let moved = false;

    c.addEventListener('pointerdown', (ev) => {
      c.setPointerCapture(ev.pointerId);
      last = { x: ev.offsetX, y: ev.offsetY };
      moved = false;
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      if (hit) { dragNode = hit; hit.fixed = true; } else { panning = true; }
      this.autoFit = false;
    });

    c.addEventListener('pointermove', (ev) => {
      if (dragNode) {
        const p = this.toWorld(ev.offsetX, ev.offsetY);
        dragNode.x = p.x;
        dragNode.y = p.y;
        this.alpha = Math.max(this.alpha, 0.4);
        moved = true;
        return;
      }
      if (panning && last) {
        this.tx += ev.offsetX - last.x;
        this.ty += ev.offsetY - last.y;
        last = { x: ev.offsetX, y: ev.offsetY };
        moved = true;
        return;
      }
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      const id = hit ? hit.id : null;
      if (id !== this.hover) {
        this.hover = id;
        c.style.cursor = hit ? 'pointer' : 'default';
        this.onHover(hit || null, ev);
      }
    });

    const release = (ev) => {
      if (dragNode && !moved) this._select(dragNode);
      dragNode = null;
      panning = false;
      last = null;
      if (ev && ev.pointerId !== undefined) {
        try { c.releasePointerCapture(ev.pointerId); } catch { /* 이미 해제됨 */ }
      }
    };
    c.addEventListener('pointerup', release);
    c.addEventListener('pointercancel', release);

    c.addEventListener('dblclick', (ev) => {
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      if (hit) this.onExpand(hit);
    });

    c.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      this.autoFit = false;
      const factor = Math.exp(-ev.deltaY * 0.0015);
      const k = Math.min(3.5, Math.max(0.25, this.k * factor));
      // 커서 아래 지점이 그대로 있도록 평행이동을 보정한다
      this.tx = ev.offsetX - ((ev.offsetX - this.tx) * k) / this.k;
      this.ty = ev.offsetY - ((ev.offsetY - this.ty) * k) / this.k;
      this.k = k;
    }, { passive: false });
  }

  _select(node) {
    this.selected = node.id;
    this.onSelect(node);
  }

  select(id) {
    const node = this.byId.get(id);
    if (node) this._select(node);
  }

  // 노드가 화면 밖이면 사용자는 아무 일도 안 일어났다고 생각한다
  focusOn(id) {
    const node = this.byId.get(id);
    if (!node) return;
    this.tx = this.canvas.clientWidth / 2 - node.x * this.k;
    this.ty = this.canvas.clientHeight / 2 - node.y * this.k;
  }
}

// --- 그리기 도구 -------------------------------------------------------

function nodeRadius(n) {
  const base = n.group === 'frame' ? 4 : 6;
  return base + Math.min(11, Math.sqrt(n.degree || 0) * 1.7);
}

function shapePath(ctx, shape, x, y, r) {
  ctx.beginPath();
  switch (shape) {
    case 'square':
      ctx.rect(x - r * 0.88, y - r * 0.88, r * 1.76, r * 1.76);
      break;
    case 'diamond':
      ctx.moveTo(x, y - r * 1.25);
      ctx.lineTo(x + r * 1.25, y);
      ctx.lineTo(x, y + r * 1.25);
      ctx.lineTo(x - r * 1.25, y);
      ctx.closePath();
      break;
    case 'triangle':
      ctx.moveTo(x, y - r * 1.2);
      ctx.lineTo(x + r * 1.1, y + r * 0.85);
      ctx.lineTo(x - r * 1.1, y + r * 0.85);
      ctx.closePath();
      break;
    case 'hexagon':
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * TAU - Math.PI / 2;
        const px = x + Math.cos(a) * r * 1.12;
        const py = y + Math.sin(a) * r * 1.12;
        i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      }
      ctx.closePath();
      break;
    case 'pill':
      roundRect(ctx, x - r * 1.3, y - r * 0.66, r * 2.6, r * 1.32, r * 0.66);
      break;
    default:
      ctx.arc(x, y, r, 0, TAU);
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawNode(ctx, n, { dim, focused, center, selected }) {
  const color = GROUP_COLOR[n.group] || GROUP_COLOR.thing;
  const shape = TYPE_SHAPE[n.type] || 'circle';

  ctx.globalAlpha = dim ? 0.22 : 1;

  // 배경색 링 — 노드가 겹쳐도 서로 먹히지 않는다
  ctx.lineWidth = 2;
  ctx.strokeStyle = SURFACE;
  shapePath(ctx, shape, n.x, n.y, n.r + 1);
  ctx.stroke();

  if (shape === 'ring') {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, TAU);
    ctx.stroke();
  } else {
    ctx.fillStyle = color;
    shapePath(ctx, shape, n.x, n.y, n.r);
    ctx.fill();
  }

  if (selected || center) {
    ctx.strokeStyle = selected ? TEXT : 'rgba(240,239,236,0.5)';
    ctx.lineWidth = selected ? 2 : 1.5;
    shapePath(ctx, shape, n.x, n.y, n.r + 4.5);
    ctx.stroke();
  } else if (focused) {
    ctx.strokeStyle = 'rgba(240,239,236,0.35)';
    ctx.lineWidth = 1.5;
    shapePath(ctx, shape, n.x, n.y, n.r + 3.5);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function labelFont(ctx, strong, k) {
  const size = strong ? 13 : 11.5;
  ctx.font = `${strong ? 600 : 400} ${size / k}px "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif`;
  return size / k;
}

// 라벨이 차지할 자리 (월드 좌표). 좌우로 조금 여유를 둬서 글자끼리
// 스치듯 붙는 것도 겹침으로 본다.
function labelBox(ctx, n, strong, k) {
  const size = labelFont(ctx, strong, k);
  const w = ctx.measureText(n.label).width + 6 / k;
  const y = n.y + n.r + 4 / k;
  return { x: n.x - w / 2, y, w, h: size * 1.25 };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function drawLabel(ctx, n, strong, k) {
  labelFont(ctx, strong, k);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const y = n.y + n.r + 4 / k;
  // 글자에 배경색 외곽선을 둘러 선 위에서도 읽히게 한다
  ctx.lineWidth = 3 / k;
  ctx.strokeStyle = SURFACE;
  ctx.lineJoin = 'round';
  ctx.strokeText(n.label, n.x, y);
  ctx.fillStyle = strong ? TEXT : TEXT_DIM;
  ctx.fillText(n.label, n.x, y);
}

function drawEdgeLabel(ctx, a, b, text, k) {
  if (!text) return;
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  ctx.font = `${10.5 / k}px "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 3 / k;
  ctx.strokeStyle = SURFACE;
  ctx.lineJoin = 'round';
  ctx.strokeText(text, mx, my);
  ctx.fillStyle = TEXT_DIM;
  ctx.fillText(text, mx, my);
}

function drawArrow(ctx, a, b, color) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const d = Math.hypot(dx, dy) || 1;
  const ux = dx / d;
  const uy = dy / d;
  // 화살촉은 도착 노드 바로 앞에 — 방향이 없으면 '누가 누구에게'가 사라진다
  const tipX = b.x - ux * (b.r + 3);
  const tipY = b.y - uy * (b.r + 3);
  const size = 5;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  ctx.lineTo(tipX - ux * size + uy * size * 0.5, tipY - uy * size - ux * size * 0.5);
  ctx.lineTo(tipX - ux * size - uy * size * 0.5, tipY - uy * size + ux * size * 0.5);
  ctx.closePath();
  ctx.fill();
}

function edgeKey(e) {
  return `${e.s}|${e.t}|${e.type}`;
}
