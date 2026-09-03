// 화면 조립 — 검색·시작점·상세 패널을 그래프 뷰에 붙인다.
import { GraphView, GROUP_COLOR, TYPE_SHAPE } from '/graph.js';
import { TimelineRail } from '/timeline.js';

const $ = (id) => document.getElementById(id);
const api = (path) => fetch(path).then((r) => r.json());

const state = { meta: null, depth: 2, limit: 120, includePeriod: false,
                current: null, detail: null, timeline: null, rail: true };

// 상세에서 관계를 타고 들어간 자취. '←' 로 한 칸씩 되짚어 올라간다.
const trail = [];

// 왼쪽 연표. 그래프는 무엇이 무엇과 이어져 있는지만 말하고 언제인지는
// 말하지 않는다 — 고른 노드를 시간 위에 얹어 주는 것이 이 막대의 일이다.
const rail = new TimelineRail($('timeline'), { onPick: (id) => visit(id) });

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
  // Esc 는 패널을 닫는다 — 깊이 들어갔다고 한 칸씩만 나가야 하면 답답하다
  if (ev.key === 'Escape') closeDetail();
  // 브라우저의 뒤로가기 몸짓은 상세 안에서 상위로 올라가는 뜻으로 받는다
  if (ev.key === 'ArrowLeft' && (ev.altKey || ev.metaKey) && trail.length) {
    ev.preventDefault();
    backDetail();
  }
});

function hideResults() { $('results').hidden = true; cursor = -1; }

// --- 표시 옵션 ---------------------------------------------------------
$('depth').onchange = (ev) => { state.depth = +ev.target.value; reload(); };
$('limit').onchange = (ev) => { state.limit = +ev.target.value; reload(); };
$('show-period').onchange = (ev) => { state.includePeriod = ev.target.checked; reload(); };
$('show-labels').onchange = (ev) => { view.showLabels = ev.target.checked; };
// 연표는 화면 폭을 250px 먹는다. 관계망만 크게 보고 싶을 때가 있다.
$('show-timeline').onchange = (ev) => {
  state.rail = ev.target.checked;
  state.timeline = null;
  if (!state.rail) rail.hide();
  else if (state.current) showTimeline(state.current);
};

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
  showTimeline(id);
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
// 빈 설명의 이유는 노드가 어디서 왔는지에 달려 있다. 뭉뚱그려
// '자료 없음'이라고 적으면, 더 받아오면 채워지는 노드와 애초에 채울
// 것이 없는 노드가 같은 말을 하게 된다.
function whyEmpty(d) {
  if (d.source === 'timeline') return '연표의 해를 세우는 노드입니다.';
  if (d.source === 'extract') return '산문에서 이름만 추출된 노드라 원문이 없습니다.';
  if (d.source === 'khs') return '국가유산청 자료에 해설문이 없습니다.';
  // 한 줄 설명이 영어로 와서 비운 경우. 원문이 남아 있다는 사실만
  // 말하고 영어 자체는 내보내지 않는다.
  if (d.desc_dropped) return '한국어로 옮길 수 있는 설명이 아직 없습니다.';
  if (d.no_kowiki) return '한국어 위키백과에 문서가 없습니다.';
  return '아직 서사를 받아오지 않았습니다.';
}

// 설명칸. 비어 있을 때 아무것도 그리지 않으면 "이 노드는 원래 설명이
// 없는 것"처럼 보인다. 왜 비었는지를 대신 적는다.
//
// **어느 자료에서 왔는지는 적지 않는다.** 'Wikidata 한 줄 설명' 같은
// 딱지는 읽는 사람이 묻지 않은 것을 답하면서 정작 궁금한 것(이 사람이
// 누구인가)은 밀어낸다. 수집 경로는 화면이 아니라 props 에 남는다.
function descHtml(d) {
  if (!d.description) {
    return `<p class="d-nodesc">설명 없음 — ${esc(whyEmpty(d))}</p>`;
  }
  // 접힌 높이(168px)를 넘길 만큼 길 때만 단추를 낸다. 세 줄짜리 글에
  // '전문 보기'가 붙어 있으면 눌러도 아무 일이 없다.
  const long = d.description.length > 220;
  // 넘겨주기를 따라온 글은 이 노드를 설명하는 글이 아닐 수 있다
  // ('판의금부사' → '의금부'). 읽는 사람이 알고 읽어야 한다.
  const via = d.desc_via
    ? `<p class="d-desc-src">‘${esc(d.desc_via)}’ 문서에서 넘겨받은 글입니다</p>`
    : '';
  return `<div class="d-desc${long ? '' : ' open'}" id="desc">${esc(d.description)}</div>
          ${via}
          ${long ? '<button class="d-more" id="more">전문 보기</button>' : ''}`;
}

async function showDetail(id, { back = false } = {}) {
  // 새로 들어가는 길이면 지금 보던 곳을 되돌아갈 자리에 쌓는다.
  // ('←' 로 온 걸음은 쌓지 않는다 — 그러면 두 노드 사이를 영영 못 벗어난다)
  if (!back && state.detail && state.detail.id !== id) {
    trail.push(state.detail);
    if (trail.length > 50) trail.shift();
  }
  const d = await api(`/api/node/${encodeURIComponent(id)}`);
  if (d.error) return;
  state.detail = { id, label: d.label };
  showTimeline(id);   // 상세로 옮겨가면 연표의 주인공도 함께 옮긴다

  const dates = [fmtDate(d.start), fmtDate(d.end)].filter(Boolean).join(' ~ ');
  // 관계는 종류·방향별로 묶는다. 방향까지 키에 넣어야 부모와 자식이
  // 한 덩어리로 뒤섞이는 일이 없다.
  const groups = new Map();

  // 한 묶음 안에서 같은 상대는 카드 하나다. 황진이의 1506년에는 시대·시점
  // 엣지가 둘 다 걸려 있어 같은 해가 두 번 나왔다 — 근거만 합쳐 하나로 둔다.
  const add = (r) => {
    const head = relHead(r);
    if (!groups.has(head)) groups.set(head, new Map());
    // 배우자·관련은 방향에 뜻이 없다. 방향까지 키에 넣으면 양쪽에 다 적힌
    // 엣지가 카드 두 장이 된다 — 신사임당의 배우자 이원수가 두 번 나왔다
    // (실측: 조선 그래프에서 배우자 206건, 관련 44건).
    const key = `${r.other.id}\u0000${SYMMETRIC.has(r.type) ? '' : r.dir}`;
    const seen = groups.get(head).get(key);
    if (seen) { mergeEvidence(seen, r); return seen; }
    const card = { ...r, evidence: [...new Set(r.evidence || [])] };
    groups.get(head).set(key, card);
    return card;
  };

  // 구체 관계를 먼저 세운다. 그러면 '관련'은 이미 자리 잡은 카드로 접힌다.
  const cardOf = new Map();   // 상대 id -> 그 상대와의 구체 관계 카드 (첫 장)
  for (const r of d.relations) {
    if (r.type === 'related_to') continue;
    const card = add(r);
    if (!cardOf.has(r.other.id)) cardOf.set(r.other.id, card);
  }
  // 구체 관계가 있는 상대에게 붙은 '관련'은 아무 말도 더하지 않는다 — 정약용
  // 상세에 정약전이 부모로 한 번, 관련으로 또 한 번 나왔다(실측 192건).
  // 카드는 접고 근거 구절만 구체 카드로 옮긴다. '관련'은 방향에 뜻이 없어
  // 상대만 같으면 같은 사실로 본다.
  for (const r of d.relations) {
    if (r.type !== 'related_to') continue;
    const card = cardOf.get(r.other.id);
    if (card) mergeEvidence(card, r);
    else add(r);
  }
  const relCount = [...groups.values()].reduce((n, bucket) => n + bucket.size, 0);

  const relHtml = [...groups.entries()].map(([head, bucket]) => {
    const rels = [...bucket.values()];
    // 시대와 시점을 한 묶음으로 받으면 해가 뒤죽박죽 들어온다 — 연도순으로 세운다.
    if (TIME_TYPES.has(rels[0].type)) rels.sort(byYear);
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
          </span>
          ${own.map((ev) => `<div class="rel-ev">“${esc(ev)}”</div>`).join('')}
        </button>`;
      }).join('')}
    </div>`;
  }).join('');

  const prev = trail[trail.length - 1];
  // 타고 들어온 관계를 맨 위에 한 줄로 적는다. 조선시대 중기에는 개체가 37개
  // 달려 있어, 방금 누른 황진이가 목록 어디에 있는지 다시 찾아야 했다.
  // 합쳐진 카드에서 가져온다 — 아래 목록과 다른 말을 하면 안 된다.
  const via = prev
    ? [...groups.values()].flatMap((bucket) => [...bucket.values()])
        .filter((c) => c.other.id === prev.id)
    : [];
  const viaHtml = via.length ? `
    <div class="d-via">
      ${via.map((r) => `
        <div class="d-via-line">
          <span class="rel-dot" style="background:${GROUP_COLOR[r.other.group]}"></span>
          <span>${esc(sentence(r, d))}</span>
        </div>
        ${[...new Set(r.evidence || [])].map((ev) => `<div class="rel-ev">“${esc(ev)}”</div>`).join('')}
      `).join('')}
    </div>` : '';

  $('detail-body').innerHTML = `
    ${prev ? `<button class="d-back" id="detail-back" title="${esc(prev.label)}(으)로 돌아가기">
       <span aria-hidden="true">←</span> ${esc(prev.label)}</button>` : ''}
    ${viaHtml}
    <span class="d-type">${glyph(d.type, d.group, 11)} ${esc(d.type_label)}</span>
    <h2 class="d-title">${esc(d.label)}</h2>
    ${dates ? `<div class="d-dates">${esc(dates)}</div>` : ''}
    ${descHtml(d)}
    ${d.aliases.length ? `<div class="d-section-title">다른 이름</div>
      <div class="d-aliases">${d.aliases.map((a) => `<span>${esc(a)}</span>`).join('')}</div>` : ''}
    <div class="d-section-title">관계 ${relCount}</div>
    ${relHtml || '<p class="hint">연결된 관계가 없습니다.</p>'}
  `;
  $('detail').hidden = false;
  $('detail').scrollTop = 0;   // 옮겨간 곳은 머리부터 읽는다

  const backBtn = $('detail-back');
  if (backBtn) backBtn.onclick = backDetail;

  const more = $('more');
  if (more) more.onclick = () => {
    $('desc').classList.toggle('open');
    more.textContent = $('desc').classList.contains('open') ? '접기' : '전문 보기';
  };
  $('detail-body').querySelectorAll('.rel').forEach((btn) => {
    // 상세에서 고른 상대가 화면에 없을 수 있다 — 그때는 그 노드로 옮겨간다
    btn.onclick = () => visit(btn.dataset.id);
  });
}

$('detail-close').onclick = closeDetail;
function closeDetail() {
  $('detail').hidden = true;
  trail.length = 0;
  state.detail = null;
  // 연표는 남긴다 — 상세를 닫아도 화면 한가운데 그 노드는 그대로 있고,
  // '언제 사람인가'는 관계 목록과 달리 계속 붙어 있어야 할 정보다.
}

// 연표의 주인공은 **지금 보고 있는 노드**다. 검색으로 옮겨가든 캔버스에서
// 누르든 상세를 타고 들어가든, 화면 한가운데가 바뀌면 연표도 따라간다.
async function showTimeline(id) {
  if (!state.rail || state.timeline === id) return;
  state.timeline = id;
  const t = await api(`/api/timeline?id=${encodeURIComponent(id)}`);
  // 그 사이에 다른 노드로 옮겼으면 늦게 온 답은 버린다
  if (state.timeline !== id) return;
  if (t.error) { rail.hide(); return; }
  rail.show(t);
}

// 되짚어 올라가기 — 그래프에도 그 노드가 다시 보여야 '돌아왔다'가 된다.
function backDetail() {
  const prev = trail.pop();
  if (prev) visit(prev.id, { back: true });
}

// 화면에 있는 노드면 그리로 옮기고, 없으면 그 주변을 새로 편다.
function visit(id, opts = {}) {
  if (view.byId.has(id)) { view.select(id); view.focusOn(id); }
  else load(id, { merge: true });
  showDetail(id, opts);
}

// 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다.
// child_of 는 'A → B = A가 B의 자녀' — 나가는 상대는 부모, 들어오는
// 상대가 자녀다. 방향별 이름이 있는 타입만 바꿔 부른다.
const DIR_HEAD = {
  child_of: { out: '부모', in: '자녀' },
  part_of: { out: '상위', in: '하위' },
};

// 시대(from_period)와 시점(dated_to)은 둘 다 '언제'를 가리킨다. 따로 세우면
// 한 해가 양쪽에 한 번씩 나온다 — 황진이의 1506년이 그랬다. 한 묶음으로 받는다.
const TIME_TYPES = new Set(['from_period', 'dated_to']);

// 방향이 뜻을 갖지 않는 관계. A의 배우자가 B면 B의 배우자도 A다.
const SYMMETRIC = new Set(['spouse_of', 'related_to']);

// 'time:1506' 은 해, 'kr:period:조선시대' 는 이름뿐인 시대다. 해를 먼저 오름차순으로,
// 이름 붙은 시대는 뒤에 묶어 둔다.
function byYear(a, b) {
  const year = (r) => { const m = /^time:(-?\d+)/.exec(r.other.id); return m ? +m[1] : null; };
  const [ya, yb] = [year(a), year(b)];
  if (ya === null || yb === null) {
    if (ya === yb) return a.other.label.localeCompare(b.other.label, 'ko');
    return ya === null ? 1 : -1;
  }
  return ya - yb;
}

// --- 관계를 문장으로 --------------------------------------------------
// 받침이 있으면 앞말, 없으면 뒷말. '황진이는' / '김시민은'.
function pt(word, withBatchim, without) {
  const code = String(word).trim().slice(-1).charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return without;   // 한글이 아니면 받침 없는 쪽으로
  return code % 28 ? withBatchim : without;
}

// 엣지 방향 그대로 주어와 목적어를 놓는다. src -> dst 순서다.
const SENTENCE = {
  participated_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에 참여했다`,
  occurred_at: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 일어났다`,
  occurred_during: (a, b) => `${a}${pt(a, '은', '는')} ${b}에 일어났다`,
  born_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 태어났다`,
  died_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 죽었다`,
  created: (a, b) => `${a}${pt(a, '이', '가')} ${b}${pt(b, '을', '를')} 만들었다`,
  located_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에 있다`,
  depicts: (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 다룬다`,
  spouse_of: (a, b) => `${a}${pt(a, '과', '와')} ${b}${pt(b, '은', '는')} 부부다`,
  member_of: (a, b) => `${a}${pt(a, '은', '는')} ${b} 소속이다`,
  held_position: (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 지냈다`,
  part_of: (a, b) => `${a}${pt(a, '은', '는')} ${b}의 일부다`,
  // 전후(P155/P156)는 앞선 사건에서, 인과(P828/P1542)는 원인에서 담는다.
  // 방향이 하나로 모여 있어 '다음'·'원인'이 적힌 엣지는 어느 쪽에서 읽어도
  // 뒤집히지 않는다.
  related_to: (a, b, o) => (o.label === '다음'
    ? `${a} 다음에 ${b}${pt(b, '이', '가')} 일어났다`
    : o.label === '원인'
    ? `${a}${pt(a, '은', '는')} ${b}의 원인이 되었다`
    : `${a}${pt(a, '과', '와')} ${b}${pt(b, '은', '는')} 관련이 있다`),
  // 엣지에 '아버지'·'어머니'가 적혀 있으면 그대로 부른다 (실측 479건)
  child_of: (a, b, o) => {
    const role = o.label === '어머니' ? '어머니' : o.label === '아버지' ? '아버지' : '부모';
    return `${a}의 ${role}는 ${b}${pt(b, '이다', '다')}`;
  },
  // 인물은 연도와 같은 실체가 아니다 — '출생'·'사망'이 적힌 엣지만 그렇게 읽는다
  dated_to: (a, b, o) => (o.label === '출생' ? `${a}${pt(a, '은', '는')} ${b}에 태어났다`
                        : o.label === '사망' ? `${a}${pt(a, '은', '는')} ${b}에 죽었다`
                        : `${a}의 연표에 ${b}${pt(b, '이', '가')} 있다`),
  // 주어가 무엇이냐에 따라 시대를 부르는 말이 다르다 — 사람은 '사람이다',
  // 사건은 '일이다', 유물·작품은 '것이다'. ('진산사건은 1791년 것이다'가 나왔다)
  from_period: (a, b, o) => {
    if (o.label === '출생' || o.label === '사망') return SENTENCE.dated_to(a, b, o);
    if (o.srcType === 'person') return `${a}${pt(a, '은', '는')} ${b} 사람이다`;
    if (o.srcType === 'event') return `${a}${pt(a, '은', '는')} ${b}에 일어난 일이다`;
    return `${a}${pt(a, '은', '는')} ${b}의 것이다`;
  },
};

// 지금 보는 노드(self)와 상대 사이의 관계 하나를 문장으로 만든다.
function sentence(r, self) {
  const me = { label: self.label, type: self.type };
  const [src, dst] = r.dir === 'out' ? [me, r.other] : [r.other, me];
  const make = SENTENCE[r.type];
  return make
    ? make(src.label, dst.label, { label: r.edge_label, srcType: src.type })
    : `${src.label} → ${dst.label} · ${r.label}`;
}

function mergeEvidence(card, r) {
  card.evidence = [...new Set([...card.evidence, ...(r.evidence || [])])];
  // 시대 엣지에 접힌 '출생'·'사망'까지 챙겨야 "1506년에 태어났다"를 말할 수 있다
  if (!card.edge_label && r.edge_label) card.edge_label = r.edge_label;
}

function relHead(r) {
  if (TIME_TYPES.has(r.type)) return r.dir === 'out' ? '시기' : '이 시기의 개체';
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
