// 개인 역사 — 한 사람의 삶을 왕·대통령의 띠와 역사 연표 옆에 세운다.
//
// 세 열이 **자 하나**를 쓴다 (buildScale). 왼쪽은 왕·대통령의 재위 띠
// (시대 연표와 같은 reignBand), 가운데는 그 무렵 한국사의 큰 사건, 오른쪽은
// 이 사람의 사건이다. 같은 해는 세 열에서 같은 높이다 — 그래야 "IMF 때
// 아버지 인쇄소가 부도났다"가 선 하나로 읽힌다. 몰린 해는 시대 연표처럼
// 그 해를 늘린다. 어느 열이 더 몰렸든 그 열이 필요한 만큼 늘리고, 나머지
// 열은 같은 자를 따라간다.
//
// **모델의 영어 식별자는 화면에 내지 않는다** (CLAUDE.md §1). 타입·관계·
// 영향의 이름은 아래 표로 옮기고, 표에 없는 것은 테스트가 잡는다
// (life.test.mjs 가 지시문을 읽어 대조한다). 파이썬 `life.py` 와 같은 표다.
//
// DOM 없이 도는 부분(normalize · lifeLayout · renderLife 의 문자열)과
// 브라우저에 붙는 부분(LifeBoard)을 가른다 — 배치가 어긋나는지는 브라우저
// 없이 재야 한다.

import { buildScale, placeMarks, reignBand, causeWire, CAUSE_WIRE, REIGN_COLOR } from './timeline.js';

export const NODE_TYPE_KO = {
  Person: '인물', FamilyMember: '가족', Ancestor: '조상', Relationship: '관계',
  Time: '때', LifeStage: '인생 단계', Period: '시기',
  PersonalEvent: '개인 사건', HistoricalEvent: '역사 사건', TurningPoint: '전환점',
  Crisis: '위기', Achievement: '성취', Failure: '실패', Decision: '결정',
  Location: '장소', BirthPlace: '출생지', Residence: '거주지', TravelLocation: '여행지',
  School: '학교', University: '대학', Company: '회사', Organization: '단체', Community: '공동체',
  Occupation: '직업', Project: '프로젝트', Business: '사업', Investment: '투자',
  Hobby: '취미', Skill: '기술',
  Book: '책', Movie: '영화', Music: '음악', Religion: '종교', Culture: '문화',
  Technology: '기술 환경', Comic: '만화', Game: '게임', Memory: '기억',
};
export const EDGE_TYPE_KO = {
  parent_of: '부모', child_of: '자녀', grandparent_of: '조부모', ancestor_of: '조상', relative_of: '친척',
  influenced: '영향을 줌', inspired: '영감을 줌', helped: '도움', mentored_by: '스승',
  worked_with: '함께 일함', met: '만남',
  caused: '원인', triggered: '촉발', led_to: '이어짐', changed: '바꿈', affected: '영향', resulted_in: '결과',
  before: '앞', after: '뒤', during: '동안', overlapped: '겹침',
  born_in: '출생지', lived_in: '거주', moved_to: '이주', visited: '방문', grew_up_in: '성장지',
  studied_at: '수학', worked_at: '근무', member_of: '소속',
  changed_by: '바뀜', inspired_by: '영감을 받음',
  read: '읽음', changed_belief: '생각을 바꿈', recommended_by: '추천받음', shared_with: '함께 나눔',
  listened_to: '들음', associated_with: '연관', reminds_of: '떠올림',
  watched: '봄', changed_view: '관점을 바꿈', connected_to_event: '사건과 연결',
  shaped_interest: '관심을 만듦', created_memory: '기억을 남김',
  played: '함', learned: '배움', built_skill: '기술을 익힘',
  used: '사용', enabled: '가능하게 함', changed_life: '삶을 바꿈',
  remembered_by: '기억됨', connected_to: '연결', triggered_by: '촉발됨',
  shaped: '형성', connected: '연결',
};
// 원인 → 결과로 읽는 관계. 개인 연표에서 오른쪽 여백의 꺾인 선이 된다.
export const CAUSAL_EDGES = new Set(['caused', 'triggered', 'led_to', 'resulted_in']);
export const IMPACT_KO = { direct: '직접', indirect: '간접', possible: '가능성' };
export const LIFE_STAGES = ['출생', '어린 시절', '초등학교', '중학교', '고등학교', '대학',
  '사회생활', '창업', '가족 형성', '현재'];
// 연표에 점으로 찍는 타입. 사람·장소·책은 이어지는 것이라 점이 아니다.
export const EVENT_TYPES = new Set(['PersonalEvent', 'HistoricalEvent', 'TurningPoint', 'Crisis',
  'Achievement', 'Failure', 'Decision', 'Memory']);

// --- 그래프 --------------------------------------------------------------
// 개인 그래프는 역사 그래프와 **같은 캔버스**(graph-view.js GraphView)에 선다.
// 캔버스는 노드의 `type` 으로 색을 고르므로(TYPE_COLOR: person·org·event·
// place·artwork·media·period·role) 지시문의 타입을 그 여덟에 대응시킨다.
// 색이 곧 갈래다 — 가족도 친구도 파랑(인물), 책·영화·음악·게임은 연빨강
// (작품), 학교·회사는 크림(단체). 이름표에는 원래 타입(가족·책)이 남는다.
export const GRAPH_TYPE = {
  Person: 'person', FamilyMember: 'person', Ancestor: 'person', Relationship: 'person',
  Time: 'period', LifeStage: 'period', Period: 'period',
  PersonalEvent: 'event', HistoricalEvent: 'event', TurningPoint: 'event', Crisis: 'event',
  Achievement: 'event', Failure: 'event', Decision: 'event', Memory: 'event',
  Location: 'place', BirthPlace: 'place', Residence: 'place', TravelLocation: 'place',
  School: 'org', University: 'org', Company: 'org', Organization: 'org', Community: 'org',
  Business: 'org', Project: 'org', Investment: 'org',
  Occupation: 'role', Hobby: 'role', Skill: 'role',
  Book: 'artwork', Movie: 'artwork', Music: 'artwork', Comic: 'artwork', Game: 'artwork',
  Religion: 'media', Culture: 'media', Technology: 'media',
};
const GRAPH_GROUP = { person: 'actor', org: 'actor', event: 'event', place: 'thing', artwork: 'thing', media: 'thing', period: 'frame', role: 'frame' };
// 범례의 묶음 이름 — 캔버스 타입 하나에 지시문 타입 여럿이 든다.
export const GRAPH_TYPE_LABEL = {
  person: '인물·가족', org: '학교·회사·단체', event: '사건·기억', place: '장소',
  artwork: '책·영화·음악·게임', media: '기술·문화·종교', period: '시기', role: '직업·취미·기술',
};

// 캔버스가 받는 꼴 (server.graph 와 같다): {center, nodes:[{id,label,type,group,degree}],
// edges:[{s,t,type,label,conf}]}. 개인 그래프는 작아서(수십 노드) 통째로 준다 —
// 역사 그래프처럼 한 노드 주변만 잘라 줄 이유가 없다.
export function graphPayload(life, center = null) {
  const degree = new Map();
  for (const e of life.edges) {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }
  const nodes = life.nodes.map((n) => {
    const type = GRAPH_TYPE[n.type] || 'event';
    return { id: n.id, label: n.name, type, group: GRAPH_GROUP[type], degree: degree.get(n.id) || 0,
      kind: n.type, kind_label: NODE_TYPE_KO[n.type] };
  });
  const edges = life.edges.map((e) => ({
    s: e.source, t: e.target, type: e.type, label: EDGE_TYPE_KO[e.type], conf: e.confidence ?? 1,
  }));
  return { center: center && nodes.some((n) => n.id === center) ? center : (life.subject?.id || nodes[0]?.id), nodes, edges };
}

// 설정 상자(SidePanel)가 읽는 메타 — 범례와 관계 종류 필터. 역사 그래프는
// 서버(/api/meta)가 주는 것을 개인 그래프는 자료에서 센다.
export function graphMeta(life) {
  const pay = graphPayload(life);
  const nodeTypes = {};
  for (const n of pay.nodes) {
    const t = (nodeTypes[n.type] ||= { label: GRAPH_TYPE_LABEL[n.type], group: n.group, count: 0 });
    t.count++;
  }
  const edgeTypes = {};
  for (const e of pay.edges) {
    const t = (edgeTypes[e.type] ||= { label: e.label, count: 0 });
    t.count++;
  }
  const seeds = [...pay.nodes].sort((a, b) => b.degree - a.degree).slice(0, 8);
  return { node_types: nodeTypes, edge_types: edgeTypes, seeds };
}

// --- 치수 ----------------------------------------------------------------
// 왼쪽 띠는 시대 연표와 같은 104px (timeline.js LANE_W). 가운데·오른쪽은
// 각각 연도 칸(38) + 축 + 라벨이다. 두 열 사이 홈(gutter)으로 역사 → 개인
// 연결선이 지난다 — 라벨 위를 지나면 글자를 가른다. 인생 단계 띠는 **맨
// 오른쪽**이다: 개인 열 왼쪽에 두면 연결선이 띠의 이름을 가로지른다
// (실측: '초등학교 1997~1998' 위로 IMF 선이 지났다).
export const COLS = {
  lane: 104,      // 왕·대통령 띠
  history: 300,   // 역사 열
  gutter: 44,     // 연결선이 지나는 홈
  personal: 320,  // 개인 열 (오른쪽 24px 은 인과 선의 자리)
  stage: 84,      // 인생 단계 띠
};
const AXIS_X = 46;   // 열 안에서 세로축이 서는 자리 (timeline.js 와 같다)
const PAD_TOP = 18;
const PAD_BOTTOM = 64;
const ZOOM = 5;      // 일생 40년이면 시대 연표의 16배는 너무 길다
export const STAGE_COLOR = 'var(--interactive-accent)';

// --- 날짜 ----------------------------------------------------------------
// 파이썬 life.parse_when 과 같은 규칙. 화면에 붙여 넣은 날것의 JSON 도
// 같은 해로 풀려야 한다. 지어내지 않는다 — '20대 초반'은 생년 없이는 null.
const PART = { 초반: 1, 중반: 4, 후반: 7 };
export function parseWhen(text, birthYear = null) {
  const s = String(text ?? '').trim();
  if (!s) return { year: null, end: null, precision: '' };
  let m = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/.exec(s);
  if (m) return { year: +m[1], end: +m[1], precision: m[2] ? 'exact' : 'year' };
  m = /(\d{4})\s*년대\s*(초반|중반|후반)?/.exec(s);
  if (m) {
    const base = +m[1];
    const lo = base + (m[2] ? PART[m[2]] - 1 : 0);
    return { year: lo, end: m[2] ? lo + 3 : base + 9, precision: 'decade' };
  }
  m = /(\d{4})\s*년?/.exec(s);
  if (m) return { year: +m[1], end: +m[1], precision: 'year' };
  m = /(\d{1,2})\s*(?:대\s*(초반|중반|후반)?|살|세)/.exec(s);
  if (m) {
    if (birthYear == null) return { year: null, end: null, precision: 'age' };
    const n = +m[1];
    if (m[0].includes('대')) {
      const lo = birthYear + n + (m[2] ? PART[m[2]] - 1 : 0);
      return { year: lo, end: m[2] ? lo + 3 : birthYear + n + 9, precision: 'age' };
    }
    return { year: birthYear + n, end: birthYear + n, precision: 'age' };
  }
  return { year: null, end: null, precision: '' };
}

// --- 정규화 ----------------------------------------------------------------
// 서버(`histgraph life`)를 거친 JSON 은 이미 이 꼴이다. 화면에 바로 붙여 넣은
// 모델 답은 여기서 같은 꼴이 된다: 모르는 타입·관계는 버리고, 날짜를 해로
// 풀고, 연표 항목이 해를 안 적었으면 노드의 해를 쓴다.
export function normalize(raw) {
  const out = { ...raw };
  const nodes = [];
  const seen = new Set();
  for (const n of raw.nodes || []) {
    if (!n || !n.id || !n.name || !NODE_TYPE_KO[n.type] || seen.has(n.id)) continue;
    seen.add(n.id);
    nodes.push({ ...n, confidence: clamp(+n.confidence || 1, 0, 1) });
  }
  const me = nodes.find((n) => n.type === 'Person') || null;
  const birth = me ? parseWhen(me.start_date).year : null;
  for (const n of nodes) {
    if (n.year !== undefined && n.precision !== undefined) continue;   // 서버가 이미 풀었다
    const w = parseWhen(n.start_date, birth);
    const e = parseWhen(n.end_date, birth).year;
    n.year = w.year;
    n.end_year = e ?? (w.end !== w.year ? w.end : null);
    n.precision = w.precision;
  }
  out.nodes = nodes;
  out.subject = raw.subject || (me ? { id: me.id, name: me.name, birth_year: birth } : null);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  out.edges = (raw.edges || []).filter((e) => e && EDGE_TYPE_KO[e.type] && byId.has(e.source) && byId.has(e.target));
  const timeline = [];
  for (const t of raw.timeline || []) {
    if (!t || !byId.has(t.event_id)) continue;
    const node = byId.get(t.event_id);
    const item = { ...t };
    if (!LIFE_STAGES.includes(item.life_stage)) item.life_stage = null;
    // 해의 출처 차례: 항목의 날짜 글 → 나이(생년을 알 때) → 노드의 날짜 (life.py 와 같다)
    if (item.year == null) item.year = parseWhen(item.date_text, birth).year;
    if (item.year == null && item.age != null && birth != null) item.year = birth + item.age;
    if (item.year == null) item.year = node.year;
    if (item.age == null && item.year != null && birth != null) item.age = item.year - birth;
    timeline.push(item);
  }
  timeline.sort((a, b) => (a.year == null) - (b.year == null) || (a.year || 0) - (b.year || 0));
  out.timeline = timeline;
  out.historical_connections = (raw.historical_connections || []).filter(Boolean)
    .map((c) => ({ ...c, impact_type: IMPACT_KO[c.impact_type] ? c.impact_type : 'possible' }));
  let ranking = raw.influence_ranking || {};
  if (Array.isArray(ranking)) ranking = { items: ranking };
  else if (!Array.isArray(ranking.items)) {
    ranking = { items: Object.entries(ranking).filter(([, v]) => v && typeof v === 'object')
      .map(([k, v]) => ({ category: k, ...v })) };
  }
  out.influence_ranking = ranking;
  out.turning_points = raw.turning_points || [];
  out.impact_analysis = raw.impact_analysis || [];
  out.counterfactual_analysis = raw.counterfactual_analysis || [];
  out.life_patterns = raw.life_patterns || [];
  out.family_analysis = raw.family_analysis || { members: [] };
  out.follow_up_questions = (raw.follow_up_questions || []).slice(0, 5);
  return out;
}

// --- 무엇이 서는가 ---------------------------------------------------------
// 개인 열: 연표 항목이 해를 아는 사건. 연표에 없는 사건 노드도 해를 알면
// 선다 — 모델이 연표를 빠뜨렸다고 사건이 없던 일이 되면 안 된다.
//
// **같은 해 안의 차례는 연표의 차례다.** 날짜 문자열로 세우면 '1998'(전학)이
// '1998-03'(이사)보다 앞에 서서 결과가 원인 위에 온다 — 시대 연표가 겪은
// 같은 함정이다 (CLAUDE.md §1-5). 연표 항목은 모델이 앞뒤(previous_event·
// next_event)를 잡아 준 차례이므로 해만 같으면 그 차례를 지킨다.
export function personalMarks(life) {
  const byId = new Map(life.nodes.map((n) => [n.id, n]));
  const marks = [];
  const seen = new Set();
  for (const t of life.timeline) {
    const n = byId.get(t.event_id);
    if (!n || t.year == null) continue;
    seen.add(n.id);
    marks.push(mark(n, t.year, t));
  }
  for (const n of life.nodes) {
    if (seen.has(n.id) || !EVENT_TYPES.has(n.type) || n.year == null) continue;
    marks.push(mark(n, n.year, null));
  }
  return marks.map((m, i) => [m, i]).sort((a, b) => a[0].year - b[0].year || a[1] - b[1]).map(([m]) => m);
}

function mark(n, year, t) {
  return {
    id: n.id, label: n.name, type: n.type, year,
    end: n.end_year ?? null,
    date: n.start_date || '',
    age: t?.age ?? null, stage: t?.life_stage ?? null,
    importance: n.importance_score ?? null,
    precision: n.precision || '',
    confidence: n.confidence,
  };
}

// 역사 열: 그래프의 큰 사건(context.anchors) + 모델이 이은 사건 중 그래프에
// 없는 것. 없는 것은 없는 대로 세우되 그렇다고 표시한다 (`kind: 'extra'`) —
// 모델이 부른 이름을 그래프의 사건인 척 세우지 않는다.
export function historyMarks(life, context) {
  const marks = (context?.anchors || []).map((a) => ({
    id: a.id, label: a.label, year: a.year, date: a.date || '', kind: 'anchor', linked: false,
  }));
  const byId = new Map(marks.map((m) => [m.id, m]));
  const byName = new Map(marks.map((m) => [`${norm(m.label)}@${m.year}`, m]));
  for (const c of life.historical_connections || []) {
    let m = c.node_id ? byId.get(c.node_id) : null;
    if (!m && c.year != null) m = byName.get(`${norm(c.historical_event)}@${c.year}`);
    if (!m && c.node_id) {
      // 그래프에는 있지만 이 구간의 뼈대에 안 든 사건 (6·25 처럼 생년보다 앞).
      m = { id: c.node_id, label: c.node_label || c.historical_event, year: c.year, date: '', kind: 'anchor', linked: false };
      if (m.year == null) continue;
      marks.push(m); byId.set(m.id, m);
    }
    if (!m) {
      if (c.year == null) continue;
      m = { id: `x:${norm(c.historical_event)}@${c.year}`, label: c.historical_event, year: c.year, date: '', kind: 'extra', linked: false };
      if (byId.has(m.id)) m = byId.get(m.id);
      else { marks.push(m); byId.set(m.id, m); }
    }
    m.linked = true;
    c._mark = m.id;
  }
  return marks.sort((a, b) => a.year - b.year || String(a.date).localeCompare(String(b.date)) || a.label.localeCompare(b.label, 'ko'));
}

// 인생 단계 띠 — 연표 항목의 단계가 바뀌는 자리에서 시작해 다음 단계 앞까지.
// 마지막 단계는 오늘까지. 항목이 단계를 안 적었으면 띠가 없다.
export function stageBands(life, toYear) {
  const bands = [];
  for (const t of life.timeline) {
    if (!t.life_stage || t.year == null) continue;
    const last = bands[bands.length - 1];
    if (last && last.stage === t.life_stage) continue;
    if (last) last.end = t.year;
    bands.push({ stage: t.life_stage, start: t.year, end: null });
  }
  if (bands.length) bands[bands.length - 1].end = Math.max(toYear, bands[bands.length - 1].start);
  return bands;
}

// --- 배치 ------------------------------------------------------------------
// 세 열이 같은 자를 쓴다. 한 해의 높이는 두 열 중 더 몰린 쪽이 정한다 —
// 라벨은 제 해를 떠나지 않고, 다른 열은 그 해를 같은 높이로 지난다.
export function lifeLayout({ life, context, bodyH = 700, today = new Date().getFullYear() }) {
  const personal = personalMarks(life);
  const allHistory = historyMarks(life, context);
  // **축은 이 사람의 삶이다** — 생년(또는 첫 사건)에서 오늘까지. 태어나기
  // 전의 역사(할아버지가 참전한 6·25)를 축에 세우면 앞이 35년 비고 정작
  // 일생이 아래로 밀린다. 그 전의 일은 축 위 머리(`before`)에 따로 세운다.
  const years = personal.map((m) => m.year);
  const birth = life.subject?.birth_year;
  if (birth != null) years.push(birth);
  if (!years.length) return null;
  const from = Math.min(...years) - 2;
  const to = Math.max(...years, ...allHistory.map((m) => m.year), today) + 1;
  // 그 전의 뼈대는 세우지 않는다 — 6·25 의 전투 서른 개가 머리를 채우면 정작
  // 이 사람과 이어진 한 줄이 묻힌다. 이어진 것만 머리에 선다.
  const before = allHistory.filter((m) => m.year < from && m.linked);
  const history = allHistory.filter((m) => m.year >= from);

  // 해마다 두 열 중 큰 쪽만큼 가짜 표시를 세워 자를 잰다 (buildScale 은 year 만 본다)
  const count = new Map();
  const bump = (list) => {
    const c = new Map();
    for (const m of list) c.set(m.year, (c.get(m.year) || 0) + 1);
    for (const [y, n] of c) count.set(y, Math.max(count.get(y) || 0, n));
  };
  bump(personal); bump(history);
  const virtual = [];
  for (const [y, n] of count) for (let i = 0; i < n; i++) virtual.push({ year: y });
  const axis = buildScale(virtual, { from, to, base: (bodyH - PAD_TOP - PAD_BOTTOM) * ZOOM });
  const at = (y) => axis.pos[clamp(Math.round(y), from, to) - from];

  const placeP = placeMarks(personal, axis).map(({ m, y }) => ({ m, ty: y }));
  const placeH = placeMarks(history, axis).map(({ m, y }) => ({ m, ty: y }));
  const tyP = new Map(placeP.map((p) => [p.m.id, p.ty]));
  const tyH = new Map(placeH.map((p) => [p.m.id, p.ty]));

  // 역사 → 개인 연결선. 양끝이 다 서 있어야 긋는다.
  const links = [];
  const beforeIds = new Set(before.map((m) => m.id));
  for (const m of before) m.links = [];
  for (const c of life.historical_connections || []) {
    if (c._mark && beforeIds.has(c._mark)) {
      before.find((m) => m.id === c._mark).links.push(c);
      continue;
    }
    if (!c._mark || !tyH.has(c._mark) || !tyP.has(c.personal_event)) continue;
    links.push({ from: c._mark, to: c.personal_event, y1: tyH.get(c._mark), y2: tyP.get(c.personal_event), impact: c.impact_type });
  }
  // 개인 사건 사이의 인과. 원인이 결과보다 위에 있어야 한다 — 아래에 있으면
  // 날짜가 틀린 것이라 그리되 표시한다.
  const causal = [];
  for (const e of life.edges) {
    if (!CAUSAL_EDGES.has(e.type) || !tyP.has(e.source) || !tyP.has(e.target)) continue;
    causal.push({ from: e.source, to: e.target, y1: tyP.get(e.source), y2: tyP.get(e.target), type: e.type, backwards: tyP.get(e.source) > tyP.get(e.target) });
  }
  const reigns = (context?.reigns || []).filter((r) => r.start <= to && r.end >= from);
  const stages = stageBands(life, today).map((b) => ({ ...b, y1: at(b.start), y2: at(b.end) }));
  return { axis, from, to, at, personal: placeP, history: placeH, before, links, causal, reigns, stages, H: axis.H };
}

// --- 그리기 ------------------------------------------------------------------
// 열 셋이 한 캔버스(.life-canvas) 위에 절대 좌표로 선다. 선은 SVG 한 장.
export function renderLife(layout, { selected = null, subjectName = '나' } = {}) {
  const { lane, history: HW, gutter, stage: SW, personal: PW } = COLS;
  const xH = lane;                    // 역사 열 시작
  const xG = xH + HW;                 // 홈 시작
  const xP = xG + gutter;             // 개인 열 시작
  const xS = xP + PW;                 // 단계 띠 시작
  const W = xS + SW;
  const H = layout.H;
  const AXH = xH + AXIS_X;
  const AXP = xP + AXIS_X;
  const at = layout.at;

  // 왼쪽 띠 — 시대 연표와 같은 함수
  const band = reignBand(layout.reigns, at, {});

  // 인생 단계 띠 — 재위 띠와 같은 문법(막대 + 이름·연도), 강조색
  const stageSvg = layout.stages.map((s, i) => `
    <rect x="${xS + 8}" y="${s.y1.toFixed(1)}" width="6" height="${Math.max(s.y2 - s.y1, 2).toFixed(1)}" rx="3"
          fill="${STAGE_COLOR}" opacity="${i % 2 ? 0.45 : 0.75}"><title>${esc(s.stage)} ${s.start}~${s.end}</title></rect>`).join('');
  const stageItems = layout.stages.map((s) => `
    <div class="tl-reign life-stage" style="left:${xS + 24}px; top:${s.y1.toFixed(1)}px" title="${esc(s.stage)} · ${s.start}~${s.end}">
      <b>${esc(s.stage)}</b><i>${s.start}~${s.end === s.start ? '' : s.end}</i></div>`).join('');

  // 점과 구간
  const dots = [];
  for (const { m, ty } of layout.history) {
    dots.push(`<circle cx="${AXH}" cy="${ty.toFixed(1)}" r="${m.linked ? 3.4 : 2.6}"
      fill="${m.kind === 'extra' ? 'var(--surface-2)' : 'var(--text-faint)'}"
      stroke="${m.linked ? CAUSE_WIRE.color : 'none'}" stroke-width="1.4"/>`);
  }
  for (const { m, ty } of layout.personal) {
    const r = 2.4 + (m.importance ? m.importance / 4 : 1);
    const on = m.id === selected;
    if (m.end != null && m.end !== m.year) {
      dots.push(`<line x1="${AXP}" y1="${ty.toFixed(1)}" x2="${AXP}" y2="${at(m.end).toFixed(1)}"
        stroke="${REIGN_COLOR}" stroke-width="3" stroke-linecap="round" opacity=".5"/>`);
    }
    dots.push(`<circle cx="${AXP}" cy="${ty.toFixed(1)}" r="${r.toFixed(1)}" fill="${REIGN_COLOR}"
      opacity="${on ? 1 : 0.85}"${on ? ' stroke="var(--text-normal)" stroke-width="1.5"' : ''}/>`);
  }

  // 역사 → 개인 연결선. 역사 라벨 오른쪽 끝에서 홈을 건너 개인 열의 왼쪽
  // 가장자리까지 — 축까지 끌면 연도 칸의 숫자를 가른다. 같은 줄 높이라 눈이 잇는다.
  // 직접 영향은 실선, 간접·가능성은 점선 — 굵기가 아니라 선의 종류로 가른다.
  const linkSvg = layout.links.map((l) => {
    const x1 = xG - 6;
    const x2 = xP - 2;
    const cx = (x1 + x2) / 2;
    const dash = l.impact === 'direct' ? '' : ' stroke-dasharray="3 3"';
    return `<path d="M${x1} ${l.y1.toFixed(1)} C${cx} ${l.y1.toFixed(1)} ${cx} ${l.y2.toFixed(1)} ${x2} ${l.y2.toFixed(1)}"
      fill="none" stroke="${CAUSE_WIRE.color}" stroke-width="1.2" opacity=".85"${dash}/>
      <path d="M${x2 - 4} ${(l.y2 - 3).toFixed(1)} L${x2} ${l.y2.toFixed(1)} L${x2 - 4} ${(l.y2 + 3).toFixed(1)}"
      fill="none" stroke="${CAUSE_WIRE.color}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>`;
  }).join('');

  // 개인 사건의 인과 — 시대 연표와 같은 ㄷ 자 선, 개인 열의 오른쪽 여백을 탄다.
  // 겹치지 않게 선마다 4px 씩 안으로.
  const causalSvg = layout.causal.map((c, i) => causeWire(c.y1, c.y2, xS - (i % 5) * 4)).join('');

  const hItems = layout.history.map(({ m, ty }, i) => {
    const cell = yearText(m, i ? layout.history[i - 1].m : null);
    const extra = m.kind === 'extra' ? '<span class="tl-rel">그래프에 없는 사건</span>' : '';
    const tag = m.kind === 'extra' ? 'span' : 'a';
    const href = m.kind === 'extra' ? '' : ` href="/#${encodeURIComponent(m.id)}"`;
    return `<${tag} class="tl-mark life-h${m.linked ? ' is-linked' : ''}"${href} data-id="${esc(m.id)}"
      style="left:${xH}px; width:${HW - 8}px; top:${ty.toFixed(1)}px" title="${esc(m.label)} · ${m.year}년">
      <span class="tl-y${cell.repeat ? ' rep' : ''}">${cell.text}</span><span class="tl-name">${esc(m.label)}</span>${extra}</${tag}>`;
  }).join('');

  const pItems = layout.personal.map(({ m, ty }, i) => {
    const cell = yearText(m, i ? layout.personal[i - 1].m : null);
    const age = m.age != null ? `<span class="tl-rel">${m.age}세</span>` : '';
    const rough = m.precision === 'decade' || m.precision === 'age' ? '<span class="tl-rel">어림</span>' : '';
    return `<button type="button" class="tl-mark life-p${m.id === selected ? ' k-self' : ''}" data-id="${esc(m.id)}"
      style="left:${xP}px; width:${PW - 28}px; top:${ty.toFixed(1)}px" title="${esc(m.label)} · ${m.year}년">
      <span class="tl-y${cell.repeat ? ' rep' : ''}">${cell.text}</span><span class="tl-name">${esc(m.label)}</span>${age}${rough}</button>`;
  }).join('');

  // 태어나기 전의 역사 — 축 위가 아니라 캔버스 머리에 한 줄씩. 무엇과 이어졌는지 함께 적는다.
  const byName = new Map();
  const before = (layout.before || []).map((m) => {
    const who = (m.links || []).map((c) => `${IMPACT_KO[c.impact_type]} · ${c.description}`).join(' / ');
    const tag = m.kind === 'extra' ? 'span' : 'a';
    const href = m.kind === 'extra' ? '' : ` href="/#${encodeURIComponent(m.id)}"`;
    return `<div class="life-before-row"><span class="tl-y">${m.year}</span><${tag} class="life-before-name"${href}>${esc(m.label)}</${tag}><span class="life-before-why">${esc(who)}</span></div>`;
  }).join('');
  // 캔버스 위에 따로 선다(흐름 배치) — 축 위에 얹으면 첫 해의 표시와 겹친다.
  const beforeBlock = before
    ? `<div class="life-before" style="margin-left:${xH}px; width:${HW + gutter + SW + PW - 16}px"><div class="life-before-head">태어나기 전</div>${before}</div>`
    : '';

  return `${beforeBlock}
    <div class="life-canvas" style="height:${H}px; width:${W}px">
      <svg class="tl-wires" width="${W}" height="${H}" aria-hidden="true">
        <line x1="${AXH}" y1="${PAD_TOP - 8}" x2="${AXH}" y2="${H - PAD_BOTTOM + 8}" stroke="var(--line)" stroke-width="1"/>
        <line x1="${AXP}" y1="${PAD_TOP - 8}" x2="${AXP}" y2="${H - PAD_BOTTOM + 8}" stroke="var(--line)" stroke-width="1"/>
        <g class="life-lane">${band.svg}</g>
        <g transform="translate(0,0)">${stageSvg}</g>
        ${linkSvg}${causalSvg}${dots.join('')}
      </svg>
      <div class="life-lane-items">${band.items}</div>
      ${stageItems}${hItems}${pItems}
    </div>`;
}

// 열 머리. 이름을 개인 열에 적는다 — "누구의 역사인가"가 열 이름이다.
export function renderHead(subjectName) {
  const { lane, history, gutter, stage, personal } = COLS;
  return `
    <div class="life-col-head" style="width:${lane}px">왕 · 대통령</div>
    <div class="life-col-head" style="width:${history}px">한국사</div>
    <div class="life-col-head" style="width:${gutter}px"></div>
    <div class="life-col-head" style="width:${personal + stage}px">${esc(subjectName)}의 역사</div>`;
}

// --- 브라우저 --------------------------------------------------------------
export class LifeBoard {
  constructor(root, { onPick } = {}) {
    this.root = root;
    this.head = root.querySelector('.life-head');
    this.body = root.querySelector('.life-body');
    this.onPick = onPick || (() => {});
    this.state = null;
    this.body.addEventListener('click', (ev) => {
      const el = ev.target.closest('.life-p[data-id]');
      if (el) this.onPick(el.dataset.id);
    });
    this._ro = new ResizeObserver(() => this.layout());
    this._ro.observe(this.body);
  }

  destroy() { this._ro?.disconnect(); }

  show({ life, context, selected = null }) {
    this.state = { life, context, selected };
    this.head.innerHTML = renderHead(life.subject?.name || '나');
    this.layout({ recenter: true });
  }

  select(id) {
    if (!this.state) return;
    this.state.selected = id;
    this.layout();
  }

  layout({ recenter = false } = {}) {
    if (!this.state) return;
    const { life, context, selected } = this.state;
    const lay = lifeLayout({ life, context, bodyH: this.body.clientHeight || 700 });
    if (!lay) {
      this.body.innerHTML = '<p class="tl-empty">해를 아는 사건이 없어 연표를 세울 수 없습니다.</p>';
      return;
    }
    this.layoutData = lay;
    const top = this.body.scrollTop;
    this.body.innerHTML = renderLife(lay, { selected, subjectName: life.subject?.name });
    if (recenter) {
      // 고른 사건이 있으면 그 자리를 한가운데로. 없으면 맨 위 — 축이 생년
      // 두 해 앞에서 열리므로 출생과 '태어나기 전' 머리가 첫 화면에 같이 든다.
      const target = selected ? lay.personal.find((p) => p.m.id === selected) : null;
      const off = this.body.querySelector('.life-canvas')?.offsetTop || 0;   // 머리(태어나기 전)만큼
      this.body.scrollTop = target ? Math.max(0, off + target.ty - this.body.clientHeight / 2) : 0;
    } else {
      this.body.scrollTop = top;
    }
  }
}

// --- 잔손 -------------------------------------------------------------------
function yearText(m, prev) {
  if (!prev || prev.year !== m.year) return { text: String(m.year), repeat: false };
  const mm = /^-?\d{1,4}-(\d{2})/.exec(String(m.date || ''));
  return mm ? { text: `${Number(mm[1])}월`, repeat: false } : { text: String(m.year), repeat: true };
}

export function norm(s) {
  return String(s || '').replace(/[\s·.\-–—()（）]/g, '').toLowerCase();
}

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
