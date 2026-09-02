// 화면 조립 — 검색·시작점·상세 패널을 그래프 뷰에 붙인다.
import { GraphView, GROUP_COLOR, TYPE_SHAPE } from '/graph.js';

const $ = (id) => document.getElementById(id);
const api = (path) => fetch(path).then((r) => r.json());

const state = { meta: null, depth: 2, limit: 120, includePeriod: false, current: null };

const view = new GraphView($('canvas'), {
  // **클릭하면 그 사람의 세계가 열려야 한다.** 고르기만 하면 화면에는
  // 그 노드가 우연히 들고 온 엣지 한두 개만 남는다 — 조선 화면에서
  // 정종을 누르면 '한씨'와의 선 하나뿐이고, 아버지 태조도 형제인 태종도
  // 안 보인다. 실제로는 관계가 25건 있는데 화면이 못 보여준 것이다.
  onSelect: (node) => { showDetail(node.id); load(node.id, { merge: true }); },
  // 더블클릭은 자리를 지킨 채 이웃만 얹는다 (지금 보던 배치를 잃지 않는다)
  onExpand: (node) => load(node.id, { merge: true }),
});

// --- 부팅 --------------------------------------------------------------
(async function boot() {
  state.meta = await api('/api/meta');
  $('go-root').textContent = ERA_LABEL[state.meta.era] || state.meta.era || '전체';
  document.title = `histgraph — ${$('go-root').textContent}`;
  // 어디까지 파고 들어가도 한 번에 중심으로 돌아올 수 있어야 한다.
  // 주소에 남은 노드 때문에 새로고침해도 왕조로 안 돌아오기 때문이다.
  $('go-root').onclick = () => { if (state.meta.root) load(state.meta.root); };
  $('counts').textContent =
    `노드 ${state.meta.nodes_total.toLocaleString()} · 엣지 ${state.meta.edges_total.toLocaleString()}`;
  renderLegend();
  const seeds = await api('/api/seeds?limit=12');
  renderSeeds(seeds);

  // 주소에 지금 보는 노드를 남긴다 — 새로고침해도 자리를 잃지 않고,
  // 남에게 "이거 봐" 하고 링크를 줄 수 있다.
  // 주소가 비어 있으면 왕조에서 시작한다. 조선 그래프의 중심은 조선이다 —
  // 차수 1위 노드로 열면 그때그때 병자호란이 중심인 화면이 된다.
  const start = hashId() || state.meta.root || seeds[0]?.id;
  if (start) load(start);
})();

function hashId() {
  return location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
}

window.addEventListener('hashchange', () => {
  const id = hashId();
  if (id && id !== state.current) load(id);
});

const ERA_LABEL = { joseon: '조선', goryeo: '고려', silla: '신라', goguryeo: '고구려', baekje: '백제' };

// --- 사이드 패널 --------------------------------------------------------
// 기본은 접힘. 캔버스 크기는 graph.js 의 ResizeObserver 가 따라온다.
$('menu-toggle').onclick = () => {
  const open = document.querySelector('.layout').classList.toggle('side-open');
  $('menu-toggle').setAttribute('aria-expanded', String(open));
  $('menu-toggle').setAttribute('aria-label', open ? '패널 닫기' : '패널 열기');
};

// --- 범례 --------------------------------------------------------------
// 색은 갈래, 모양은 타입. 둘 다 범례에 있어야 색만으로 읽지 않게 된다.
const GROUP_LABEL = { actor: '인물·단체', event: '사건', thing: '장소·유물', frame: '시대·직위' };

function renderLegend() {
  const types = state.meta.node_types;
  const groups = {};
  for (const [key, info] of Object.entries(types)) {
    if (!info.count) continue;
    (groups[info.group] ||= []).push([key, info]);
  }
  const li = [];
  for (const [group, entries] of Object.entries(groups)) {
    li.push(`<li style="margin-top:6px"><span style="color:${GROUP_COLOR[group]};font-weight:600">■</span>
             <span style="color:var(--text-2)">${GROUP_LABEL[group]}</span></li>`);
    for (const [key, info] of entries.sort((a, b) => b[1].count - a[1].count)) {
      li.push(`<li style="padding-left:14px">${glyph(key, group)}
               <span>${info.label}</span><span class="count">${info.count.toLocaleString()}</span></li>`);
    }
  }
  $('legend').innerHTML = li.join('');
}

function glyph(type, group, size = 13) {
  const c = GROUP_COLOR[group];
  const s = TYPE_SHAPE[type] || 'circle';
  const h = size / 2;
  const shapes = {
    circle: `<circle cx="${h}" cy="${h}" r="${h - 2}" fill="${c}"/>`,
    square: `<rect x="2" y="2" width="${size - 4}" height="${size - 4}" fill="${c}"/>`,
    diamond: `<path d="M${h} 1 L${size - 1} ${h} L${h} ${size - 1} L1 ${h}Z" fill="${c}"/>`,
    triangle: `<path d="M${h} 1.5 L${size - 1} ${size - 2} L1 ${size - 2}Z" fill="${c}"/>`,
    hexagon: `<path d="M${h} 1 L${size - 1.5} ${h * 0.55} L${size - 1.5} ${h * 1.45} L${h} ${size - 1} L1.5 ${h * 1.45} L1.5 ${h * 0.55}Z" fill="${c}"/>`,
    ring: `<circle cx="${h}" cy="${h}" r="${h - 2.5}" fill="none" stroke="${c}" stroke-width="1.6"/>`,
    pill: `<rect x="1" y="${h - 3}" width="${size - 2}" height="6" rx="3" fill="${c}"/>`,
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="flex:none">${shapes[s] || shapes.circle}</svg>`;
}

// --- 시작점 ------------------------------------------------------------
function renderSeeds(seeds) {
  $('seeds').innerHTML = seeds
    .map((s) => `<li data-id="${esc(s.id)}">${glyph(s.type, s.group, 11)}
        <span>${esc(s.label)}</span><span class="meta">${s.degree}</span></li>`)
    .join('');
  $('seeds').onclick = (ev) => {
    const li = ev.target.closest('li[data-id]');
    if (li) load(li.dataset.id);
  };
}

// --- 검색 --------------------------------------------------------------
let searchTimer = null;
let cursor = -1;

$('q').addEventListener('input', (ev) => {
  clearTimeout(searchTimer);
  const q = ev.target.value.trim();
  if (!q) { hideResults(); return; }
  searchTimer = setTimeout(async () => {
    const rows = await api(`/api/search?q=${encodeURIComponent(q)}&limit=25`);
    cursor = -1;
    if (!rows.length) {
      $('results').innerHTML = '<li class="empty-row" style="color:var(--text-3);cursor:default">일치하는 개체가 없습니다</li>';
    } else {
      $('results').innerHTML = rows
        .map((r) => `<li data-id="${esc(r.id)}">${glyph(r.type, r.group, 11)}
            <span>${esc(r.label)}</span>
            <span class="meta">${state.meta.node_types[r.type].label} · ${r.degree}</span></li>`)
        .join('');
    }
    $('results').hidden = false;
  }, 140);
});

$('q').addEventListener('keydown', (ev) => {
  const items = [...$('results').querySelectorAll('li[data-id]')];
  if (ev.key === 'Escape') { hideResults(); $('q').blur(); return; }
  if (!items.length) return;
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    ev.preventDefault();
    cursor = (cursor + (ev.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
    items.forEach((li, i) => li.setAttribute('aria-selected', i === cursor));
    items[cursor].scrollIntoView({ block: 'nearest' });
  } else if (ev.key === 'Enter') {
    load(items[Math.max(cursor, 0)].dataset.id);
    hideResults();
  }
});

$('results').onclick = (ev) => {
  const li = ev.target.closest('li[data-id]');
  if (li) { load(li.dataset.id); hideResults(); }
};

document.addEventListener('click', (ev) => {
  if (!ev.target.closest('.search')) hideResults();
});

document.addEventListener('keydown', (ev) => {
  if (ev.key === '/' && document.activeElement !== $('q')) { ev.preventDefault(); $('q').focus(); }
  if (ev.key === 'Escape') closeDetail();
});

function hideResults() { $('results').hidden = true; cursor = -1; }

// --- 표시 옵션 ---------------------------------------------------------
$('depth').onchange = (ev) => { state.depth = +ev.target.value; reload(); };
$('limit').onchange = (ev) => { state.limit = +ev.target.value; reload(); };
$('show-period').onchange = (ev) => { state.includePeriod = ev.target.checked; reload(); };
$('show-labels').onchange = (ev) => { view.showLabels = ev.target.checked; };

function reload() { if (state.current) load(state.current); }

// --- 그래프 적재 -------------------------------------------------------
async function load(id, { merge = false } = {}) {
  const exclude = state.includePeriod ? '' : 'period';
  const url = `/api/graph?id=${encodeURIComponent(id)}&depth=${state.depth}`
            + `&limit=${state.limit}&exclude=${exclude}`;
  const data = await api(url);
  if (data.missing || !data.nodes.length) {
    note(`‘${id}’ 주변에 그릴 관계가 없습니다.`);
    return;
  }
  state.current = id;
  if (!merge) location.hash = encodeURIComponent(id);
  $('empty').hidden = true;
  view.setData(data, { merge });
  view.select(id);
  view.focusOn(id);

  const label = data.nodes.find((n) => n.id === id)?.label || id;
  note(`${esc(label)} 주변 · 노드 ${data.nodes.length} · 관계 ${data.edges.length}`
     + (data.truncated ? ' · <b>차수 상위만 표시</b>' : ''));
}

function note(html) {
  $('note').innerHTML = html;
  $('note').hidden = false;
}

// --- 상세 패널 ---------------------------------------------------------
async function showDetail(id) {
  const d = await api(`/api/node/${encodeURIComponent(id)}`);
  if (d.error) return;

  const dates = [fmtDate(d.start), fmtDate(d.end)].filter(Boolean).join(' ~ ');
  // 관계는 종류·방향별로 묶는다. 방향까지 키에 넣어야 부모와 자식이
  // 한 덩어리로 뒤섞이는 일이 없다.
  const groups = new Map();
  for (const r of d.relations) {
    if (!groups.has(relHead(r))) groups.set(relHead(r), []);
    groups.get(relHead(r)).push(r);
  }

  const relHtml = [...groups.entries()].map(([head, rels]) => {
    // 열거문("시조 작품으로는 A, B, C 등이 있다") 하나가 관계 여럿을 낳는다.
    // 카드마다 같은 문장을 찍으면 다른 작품인데 내용이 같아 보인다 —
    // 여럿이 공유하는 근거는 묶음 머리에 한 번만 둔다.
    const shared = new Set();
    const seen = new Set();
    for (const r of rels) {
      for (const ev of new Set(r.evidence || [])) {
        if (seen.has(ev)) shared.add(ev); else seen.add(ev);
      }
    }
    return `
    <div class="rel-group">
      <div class="rel-head">${esc(head)} · ${rels.length}</div>
      ${[...shared].map((ev) => `<div class="rel-ev shared">“${esc(ev)}”</div>`).join('')}
      ${rels.map((r) => {
        const own = (r.evidence || []).filter((ev) => !shared.has(ev));
        return `
        <button class="rel" data-id="${esc(r.other.id)}">
          <span class="rel-line">
            <span class="rel-dot" style="background:${GROUP_COLOR[r.other.group]}"></span>
            <span class="rel-name">${esc(r.other.label)}</span>
            ${r.dir === 'in' ? '<span class="rel-dir">←</span>' : ''}
          </span>
          ${own.map((ev) => `<div class="rel-ev">“${esc(ev)}”</div>`).join('')}
        </button>`;
      }).join('')}
    </div>`;
  }).join('');

  $('detail-body').innerHTML = `
    <span class="d-type">${glyph(d.type, d.group, 11)} ${esc(d.type_label)}</span>
    <h2 class="d-title">${esc(d.label)}</h2>
    ${dates ? `<div class="d-dates">${esc(dates)}</div>` : ''}
    ${d.description ? `<div class="d-desc" id="desc">${esc(d.description)}</div>
       <button class="d-more" id="more">전문 보기</button>` : ''}
    ${d.aliases.length ? `<div class="d-section-title">다른 이름</div>
      <div class="d-aliases">${d.aliases.map((a) => `<span>${esc(a)}</span>`).join('')}</div>` : ''}
    <div class="d-section-title">관계 ${d.relations.length}</div>
    ${relHtml || '<p class="hint">연결된 관계가 없습니다.</p>'}
  `;
  $('detail').hidden = false;

  const more = $('more');
  if (more) more.onclick = () => {
    $('desc').classList.toggle('open');
    more.textContent = $('desc').classList.contains('open') ? '접기' : '전문 보기';
  };
  $('detail-body').querySelectorAll('.rel').forEach((btn) => {
    // 상세에서 고른 상대가 화면에 없을 수 있다 — 그때는 그 노드로 옮겨간다
    btn.onclick = () => (view.byId.has(btn.dataset.id)
      ? (view.select(btn.dataset.id), view.focusOn(btn.dataset.id), showDetail(btn.dataset.id))
      : load(btn.dataset.id));
  });
}

$('detail-close').onclick = closeDetail;
function closeDetail() { $('detail').hidden = true; }

// 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다.
// child_of 는 'A → B = A가 B의 자녀' — 나가는 상대는 부모, 들어오는
// 상대가 자녀다. 방향별 이름이 있는 타입만 바꿔 부른다.
const DIR_HEAD = {
  child_of: { out: '부모', in: '자녀' },
  part_of: { out: '상위', in: '하위' },
};

function relHead(r) {
  return DIR_HEAD[r.type]?.[r.dir] || r.label;
}

// --- 잡동사니 ----------------------------------------------------------
function fmtDate(v) {
  if (!v) return '';
  const m = String(v).match(/^(-?)(\d{1,4})/);
  if (!m) return '';
  const y = +m[2];
  return m[1] ? `기원전 ${y}년` : `${y}년`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
