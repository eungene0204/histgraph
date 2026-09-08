// 개인 역사 — 세 열이 한 자 위에 서는지, 화면에 영어가 새지 않는지.
//
//   node web/tests/life.test.mjs
//
// 브라우저 없이 돈다. 배치(lifeLayout)와 그리기(renderLife)는 순수 함수다.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  normalize, removeNode, parseWhen, lifeLayout, renderLife, renderHead, personalMarks, historyMarks, stageBands,
  graphPayload, graphMeta, GRAPH_TYPE, GRAPH_TYPE_LABEL, edgeLabel, tidyEdges, deedOf, LIFE_EDGES, RELAX,
  NODE_TYPE_KO, EDGE_TYPE_KO, IMPACT_KO, LIFE_STAGES, COLS,
} from '../src/lib/life.js';
import { TYPE_COLOR, GraphView } from '../src/lib/graph-view.js';

let pass = 0;
let fail = 0;
function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? `  — ${extra}` : ''}`); }
}
const here = (p) => fileURLToPath(new URL(p, import.meta.url));

console.log('\n개인 역사 — 이름표');
{
  // 지시문이 부르는 식별자는 전부 한국어 이름이 있어야 한다 — 없으면 화면에 영어가 뜬다.
  const prompt = readFileSync(here('../../src/histgraph/life_prompt.md'), 'utf8');
  // 노드 타입: '# Node 타입' 절의 한 낱말 줄 + 확장 절의 `type:"X"` 와 '## 이름(X)' 머리.
  const nodeTypes = new Set();
  const core = prompt.slice(prompt.indexOf('# Node 타입'), prompt.indexOf('# Person Node 구조'));
  for (const line of core.split('\n')) if (/^[A-Z][a-z][A-Za-z]+$/.test(line.trim())) nodeTypes.add(line.trim());
  for (const m of prompt.matchAll(/type:"([A-Za-z]+)"/g)) nodeTypes.add(m[1]);
  for (const m of prompt.matchAll(/^## [^(\n]+\(([A-Z][A-Za-z]+)\)/gm)) nodeTypes.add(m[1]);
  // 관계: 한 낱말(밑줄 이어진) 줄 가운데 칸 이름이 아닌 것
  const edgeTypes = new Set();
  const FIELDS = new Set(['id', 'type', 'name', 'title', 'description', 'age', 'year', 'previous_event', 'next_event', 'confidence', 'event', 'category', 'node', 'strength', 'reason', 'direct', 'indirect', 'possible', 'score', 'author', 'period', 'influence', 'artist', 'creator', 'significance_score', 'emotional_connection', 'read_period', 'emotional_strength', 'associated_nodes', 'impact_type', 'turning_point_score', 'importance_score', 'emotional_impact', 'start_date', 'end_date', 'location', 'participants', 'birth_date', 'birth_place', 'occupation']);
  for (const raw of prompt.split('\n')) {
    const line = raw.trim();
    if (/^[a-z]+(_[a-z]+)*$/.test(line) && !FIELDS.has(line)) edgeTypes.add(line);
  }
  const missingN = [...nodeTypes].filter((t) => !NODE_TYPE_KO[t]);
  const missingE = [...edgeTypes].filter((t) => !EDGE_TYPE_KO[t]);
  ok(`지시문의 노드 타입 ${nodeTypes.size}개에 전부 한국어 이름이 있다`, nodeTypes.size > 30 && !missingN.length, missingN.join(', '));
  ok(`지시문의 관계 ${edgeTypes.size}개에 전부 한국어 이름이 있다`, edgeTypes.size > 40 && !missingE.length, missingE.join(', '));
  const hangul = (s) => /[가-힣]/.test(s);
  ok('이름표는 전부 한글', [...Object.values(NODE_TYPE_KO), ...Object.values(EDGE_TYPE_KO), ...Object.values(IMPACT_KO), ...LIFE_STAGES].every(hangul));
}

console.log('\n개인 역사 — 날짜');
{
  ok('ISO 날짜', parseWhen('1997-12-03').year === 1997 && parseWhen('1997-12-03').precision === 'exact');
  ok("'2000년대 초반' 은 2000~2003", JSON.stringify(parseWhen('2000년대 초반')) === JSON.stringify({ year: 2000, end: 2003, precision: 'decade' }));
  ok("'20대 초반' 은 생년 없이는 모른다", parseWhen('20대 초반').year === null);
  ok("'20대 초반' + 생년 1985 = 2005~2008", parseWhen('20대 초반', 1985).year === 2005 && parseWhen('20대 초반', 1985).end === 2008);
  ok("'7살' + 생년 1985 = 1992", parseWhen('7살', 1985).year === 1992);
  ok('빈 값은 모른다', parseWhen(null).precision === '');
  ok("'고등학교 2학년' + 생년 1981 = 1998 (어림)", parseWhen('고등학교 2학년', 1981).year === 1998 && parseWhen('고등학교 2학년', 1981).precision === 'age');
  ok("'중1' + 생년 1981 = 1994", parseWhen('중1 때', 1981).year === 1994);
  ok("학년은 생년 없이는 모른다", parseWhen('고등학교 1학년').year === null);
}

// 지어낸 인물의 그래프 — 시험용 붙박이일 뿐 화면에는 안 나간다 (2026-09-08 에
// '예시로 먼저 보기' 와 서버의 기본 자료를 뺐다).
const sample = JSON.parse(readFileSync(here('fixtures/life.json'), 'utf8'));
const context = {
  reigns: [
    { id: 'p1', label: '김영삼', position: '대통령', kind: 'president', start: 1993, end: 1998, death: 2015, ongoing: false },
    { id: 'p2', label: '김대중', position: '대통령', kind: 'president', start: 1998, end: 2003, death: 2009, ongoing: false },
    { id: 'p3', label: '문재인', position: '대통령', kind: 'president', start: 2017, end: 2022, death: null, ongoing: false },
  ],
  anchors: [
    { id: 'wd:Q625457', label: '대한민국의 IMF 구제금융 요청', year: 1997, date: '1997-12-03', kind: 'anchor' },
    { id: 'wd:Q83872398', label: '대한민국의 코로나19 범유행', year: 2020, date: '2020-01-20', kind: 'anchor' },
    { id: 'wd:Q1', label: '2008년 대한민국 촛불 시위', year: 2008, date: '2008-05', kind: 'anchor' },
    { id: 'wd:Q2', label: '세월호 침몰 사고', year: 2014, date: '2014-04-16', kind: 'anchor' },
  ],
};

console.log('\n개인 역사 — 정규화');
{
  const life = normalize(sample);
  ok('주인공과 생년', life.subject?.birth_year === 1985, JSON.stringify(life.subject));
  ok('연표가 해 순', life.timeline.every((t, i) => !i || life.timeline[i - 1].year <= t.year));
  // 날것(서버를 안 거친) JSON 도 같은 꼴이 된다
  const raw = { nodes: [
    { id: 'me', type: 'Person', name: '나', start_date: '1990', confidence: 1 },
    { id: 'e1', type: 'PersonalEvent', name: '입학', start_date: '20대 초반', confidence: 1 },
    { id: 'bad', type: 'Alien', name: '외계', confidence: 1 },
  ], edges: [{ source: 'me', target: 'bad', type: 'met', confidence: 1 }, { source: 'me', target: 'e1', type: 'flew', confidence: 1 }],
  timeline: [{ event_id: 'e1', life_stage: '대학' }] };
  const n = normalize(raw);
  ok('모르는 타입의 노드는 버린다', n.nodes.length === 2);
  const who = normalize({ nodes: [{ id: 'p1', type: 'Person', name: '사용자', confidence: 1 }], edges: [], timeline: [],
    subject: { id: 'p1', name: '사용자', birth_year: null } });
  ok("주인공을 '사용자'라 적어 와도 화면에서는 '나'", who.nodes[0].name === '나' && who.subject.name === '나', JSON.stringify(who.subject));
  ok('양끝 없는 관계·모르는 관계는 버린다', n.edges.length === 0);
  ok("'20대 초반' 이 생년으로 풀린다 (1990 → 2010)", n.nodes[1].year === 2010 && n.nodes[1].precision === 'age');
  ok('연표 항목이 노드의 해와 나이를 받는다', n.timeline[0].year === 2010 && n.timeline[0].age === 20);
}

console.log('\n개인 역사 — 세 열이 한 자');
{
  const life = normalize(sample);
  const lay = lifeLayout({ life, context, bodyH: 700, today: 2026 });
  ok('배치가 선다', !!lay && lay.personal.length >= 18 && lay.history.length >= 4, `${lay?.personal.length} / ${lay?.history.length}`);
  // 같은 해는 두 열에서 같은 높이 — IMF(1997) 와 인쇄소 부도(1997)
  const imf = lay.history.find((p) => p.m.id === 'wd:Q625457');
  const bust = lay.personal.find((p) => p.m.id === 'ev_bankrupt');
  ok('같은 해는 같은 높이 (1997)', imf && bust && Math.abs(imf.ty - bust.ty) < 0.01, `${imf?.ty} vs ${bust?.ty}`);
  // 해 순서는 픽셀 순서다 — 열마다
  const mono = (list) => list.every((p, i) => !i || list[i - 1].ty <= p.ty);
  ok('개인 열이 위에서 아래로 해 순', mono(lay.personal));
  ok('역사 열이 위에서 아래로 해 순', mono(lay.history));
  // 몰린 해(1998 에 셋)는 겹치지 않는다
  const ys = lay.personal.filter((p) => p.m.year === 1998).map((p) => p.ty).sort((a, b) => a - b);
  ok('한 해에 셋이면 30px 씩 내려 선다', ys.length === 3 && ys[1] - ys[0] >= 30 && ys[2] - ys[1] >= 30, ys.join(','));
  // 역사 → 개인 연결선
  ok('역사 연결이 선이 된다 (IMF → 부도, IMF → 이사, 코로나 → 재택)', lay.links.length >= 3, String(lay.links.length));
  ok('그래프에 없는 사건도 세우되 표시한다', lay.history.some((p) => p.m.kind === 'extra' && p.m.label === '2002년 FIFA 월드컵'));
  ok('생년보다 앞선 사건(6·25)은 축이 아니라 머리에 선다', lay.before.some((m) => m.id === 'wd:Q8663' && m.links.length === 1) && !lay.history.some((p) => p.m.id === 'wd:Q8663'));
  ok('축은 생년 두 해 앞에서 연다', lay.from === 1983);
  // 인과
  ok('개인 사건의 인과가 선이 된다', lay.causal.length >= 8 && lay.causal.every((c) => !c.backwards), String(lay.causal.length));
  // 재위 띠·인생 단계
  ok('구간에 걸친 대통령만 선다', lay.reigns.length === 3);
  const st = stageBands(life, 2026);
  ok('인생 단계 띠가 이어진다', st.length >= 6 && st.every((b, i) => !i || st[i - 1].end === b.start) && st[st.length - 1].end === 2026, JSON.stringify(st));

  // 그리기
  const html = renderLife(lay, { selected: 'ev_fail', subjectName: '나' }) + renderHead('나');
  ok("태어나기 전의 역사가 머리에 이유와 함께", html.includes('태어나기 전') && html.includes('6.25 전쟁') && html.includes('간접 · 할아버지'));
  ok('세 열 머리', html.includes('왕 · 대통령') && html.includes('한국사') && html.includes('나의 역사'));
  ok('고른 사건이 굵다', html.includes('life-p k-self'));
  ok('역사 사건은 그래프로 가는 링크', html.includes('href="/#wd%3AQ625457"'));
  ok('대통령 띠가 시대 연표와 같은 문법', html.includes('tl-reign-bar') && html.includes('김대중'));
  // 화면 글자에 영어가 새지 않는다 — 기준은 시대 연표와 같다: **한 덩어리에 한글이
  // 한 자도 없으면** 걸린다. 자료의 고유명(IMF 구제금융·AI 도구)은 한글과 함께 있다.
  const chunks = html.replace(/<svg[\s\S]*?<\/svg>/g, '').split(/<[^>]+>/).map((c) => c.replace(/&[a-z]+;/g, ' ').trim())
    .filter((c) => /[A-Za-z]{2,}/.test(c) && !/[가-힣]/.test(c));
  ok('화면 글자 덩어리마다 한글이 있다', chunks.length === 0, chunks.join(' | '));
  ok('원인이 결과보다 위에 선다 (이사 → 전학, 같은 해)', lay.personal.findIndex((p) => p.m.id === 'ev_move') < lay.personal.findIndex((p) => p.m.id === 'ev_transfer'));
  ok('열 너비의 합이 캔버스 너비', html.includes(`width:${COLS.lane + COLS.history + COLS.gutter + COLS.stage + COLS.personal}px`));
}

console.log('\n개인 역사 — 관계의 이름 (2026-09-08 "친구들은 만남이 아니라 친구 · 뒤·동안은 도대체 뭐야")');
{
  // 서버(life.py tidy_edges)와 같은 네 규칙 — 서버 없이 브라우저에 남은 옛 그래프도 여기서 고쳐진다.
  const messy = normalize({
    nodes: [{ id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'mv', type: 'PersonalEvent', name: '미국으로 이주', start_date: '2005', confidence: 1 },
      { id: 'hs', type: 'PersonalEvent', name: '잠실고등학교 입학', start_date: '1997', confidence: 1 },
      { id: 'gr', type: 'PersonalEvent', name: '성내중학교 졸업', start_date: '1997', confidence: 1 },
      { id: 'fail', type: 'Failure', name: '첫 창업 실패', start_date: '2010', confidence: 1 },
      { id: 'sch', type: 'School', name: '잠실고등학교', confidence: 1 },
      { id: 'major', type: 'Occupation', name: '수학 전공', confidence: 1 },
      { id: 'usa', type: 'Location', name: '미국', confidence: 1 },
      { id: 'kim', type: 'Person', name: '김일권', confidence: 1, description: '잠실고등학교 1학년 때 만난 친구' },
      { id: 'park', type: 'Person', name: '박준영', confidence: 1, description: '잠실고등학교 2학년 때 만난 친구' },
      { id: 'na', type: 'Person', name: '나형철', confidence: 1 },
      { id: 'lee', type: 'Person', name: '이대표', confidence: 1, description: '첫 회사 동료' }],
    edges: [{ source: 'me', target: 'mv', type: 'after', confidence: 1 },
      { source: 'hs', target: 'me', type: 'during', confidence: 1 },
      { source: 'me', target: 'fail', type: 'after', confidence: 1 },
      { source: 'gr', target: 'hs', type: 'before', confidence: 1 },
      { source: 'hs', target: 'sch', type: 'studied_at', confidence: 1 },
      { source: 'hs', target: 'major', type: 'studied_at', confidence: 1 },
      { source: 'mv', target: 'usa', type: 'moved_to', confidence: 1 },
      { source: 'kim', target: 'sch', type: 'studied_at', confidence: 0.8 },
      { source: 'park', target: 'sch', type: 'studied_at', confidence: 0.8 },
      { source: 'me', target: 'kim', type: 'met', confidence: 0.8 },
      { source: 'me', target: 'park', type: 'met', confidence: 0.8 },
      { source: 'me', target: 'lee', type: 'met', confidence: 0.8 },
      { source: 'kim', target: 'park', type: 'worked_with', confidence: 0.5 },
      { source: 'me', target: 'na', type: 'met', confidence: 0.9 },
      { source: 'na', target: 'me', type: 'met', confidence: 0.9 }],
    timeline: [], historical_connections: [],
  });
  const mk = new Map(messy.edges.map((e) => [`${e.source}>${e.target}`, e.type]));
  const mr = new Map(messy.edges.map((e) => [`${e.source}>${e.target}`, e.role || null]));
  ok('주인공 → 자기 사건의 시간 관계는 참여(experienced) — 뒤·동안이 아니다', mk.get('me>mv') === 'experienced' && mk.get('me>hs') === 'experienced' && !mk.has('hs>me'));
  ok('친구라 적힌 만남은 friend_of · 동료는 worked_with · 말 없으면 met', mk.get('me>kim') === 'friend_of' && mk.get('me>lee') === 'worked_with' && mk.get('me>na') === 'met');
  ok('일한 곳 없이 미룬 함께 일함은 같은 학교면 schoolmate', mk.get('kim>park') === 'schoolmate');
  ok('양방향 met 은 하나만', !mk.has('na>me') && messy.edges.length === 14);
  ok('사건 → 사건의 before 는 그대로', mk.get('gr>hs') === 'before');
  ok('사건 → 학교·전공의 studied_at 은 그 곳(at)으로 옮긴다', mk.get('hs>sch') === 'at' && mk.get('hs>major') === 'at');
  ok('사람 → 사건의 역할은 사건 이름의 술어 (이주·입학), 없으면 사건의 종류(실패); 옮긴 전공은 역할 "전공"',
    [mr.get('me>mv'), mr.get('me>hs'), mr.get('me>fail'), mr.get('hs>major')].join(',') === '이주,입학,실패,전공', [...mr].join(' '));
  const pay = graphPayload(messy, 'me');
  const lab = (a, b) => pay.edges.find((e) => e.s === a && e.t === b)?.label;
  ok('선 위의 말: 역할이 이기고 없으면 양끝 — 이주 · 실패 · 학교 · 전공 · 이주지 · 다음 · 친구 · 같은 학교',
    [lab('me', 'mv'), lab('me', 'fail'), lab('hs', 'sch'), lab('hs', 'major'), lab('mv', 'usa'), lab('gr', 'hs'), lab('me', 'kim'), lab('kim', 'park')].join(',')
      === '이주,실패,학교,전공,이주지,다음,친구,같은 학교',
    pay.edges.map((e) => `${e.s}>${e.t}:${e.label}`).join(' '));
  ok('사람 → 학교는 재학', lab('kim', 'sch') === '재학' && edgeLabel('studied_at', 'Person', 'School') === '재학');
  ok("화면에 '뒤'·'동안'·'수학'·'앞'·'겪음'이 서지 않는다", !pay.edges.some((e) => ['뒤', '동안', '수학', '앞', '겪음'].includes(e.label)));
  const meta = graphMeta(messy);
  ok('관계 종류 필터는 타입의 일반 이름 (당사자 · 재학 · 친구 · 곳)', meta.edge_types.experienced.label === '당사자' && meta.edge_types.studied_at.label === '재학' && meta.edge_types.friend_of.label === '친구' && meta.edge_types.at.label === '곳');
  ok('두 번 다듬어도 그대로', tidyEdges(messy.nodes, messy.edges, messy.nodes[0]).length === messy.edges.length);
  ok("술어 읽기: '스타트업 경력 시작' → '경력 시작' · '30사단 훈련소 입소' → '입소' · 술어 없으면 null",
    deedOf({ name: '스타트업 경력 시작', type: 'PersonalEvent' }) === '경력 시작' && deedOf({ name: '30사단 훈련소 입소', type: 'PersonalEvent' }) === '입소' && deedOf({ name: '아버지 인쇄소 부도', type: 'PersonalEvent' }) === null);
  // 온톨로지 관문
  ok('이름표와 온톨로지의 관계가 같고 일반 이름이 같다', Object.keys(EDGE_TYPE_KO).length === Object.keys(LIFE_EDGES).length
    && Object.entries(LIFE_EDGES).every(([k, v]) => EDGE_TYPE_KO[k] === v[0]), Object.entries(LIFE_EDGES).filter(([k, v]) => EDGE_TYPE_KO[k] !== v[0]).map(([k]) => k).join(','));
  const relaxBad = [...RELAX].filter(([key, moved]) => {
    const [kind, sc, dc] = key.split('|');
    const spec = LIFE_EDGES[moved]; if (!spec || !LIFE_EDGES[kind]) return true;
    const [a, b] = (moved === 'experienced' && sc === 'event') ? [dc, sc] : [sc, dc];
    return !spec[1].includes(a) || !spec[2].includes(b) || (LIFE_EDGES[kind][1].includes(sc) && LIFE_EDGES[kind][2].includes(dc));
  });
  ok('RELAX 의 결과는 전부 온톨로지에 맞고, 이미 맞는 짝은 옮기지 않는다', relaxBad.length === 0, relaxBad.map(([k]) => k).join(','));
  const issues = [];
  const kept = tidyEdges([{ id: 'a', type: 'Book', name: '책' }, { id: 'b', type: 'School', name: '학교' }], [{ source: 'a', target: 'b', type: 'parent_of', confidence: 1 }], null, issues);
  ok('표 밖 엣지는 버리지 않고 센다', kept.length === 1 && issues.length === 1);
}

console.log('\n개인 역사 — 빈 자료');
{
  const life = normalize({ nodes: [{ id: 'me', type: 'Person', name: '나', confidence: 1 }], edges: [], timeline: [] });
  ok('해를 아는 사건이 없으면 배치가 없다', lifeLayout({ life, context: null }) === null);
  ok('연표가 비어도 표시 목록은 빈 배열', personalMarks(life).length === 0 && historyMarks(life, null).length === 0);
}

console.log('\n개인 역사 — 그래프 (역사 그래프와 같은 캔버스)');
{
  ok('지시문의 노드 타입 전부가 캔버스 색 타입에 대응된다', Object.keys(NODE_TYPE_KO).every((t) => TYPE_COLOR[GRAPH_TYPE[t]]),
    Object.keys(NODE_TYPE_KO).filter((t) => !TYPE_COLOR[GRAPH_TYPE[t]]).join(','));
  ok('캔버스 타입마다 범례 이름이 한글', Object.values(GRAPH_TYPE).every((t) => /[가-힣]/.test(GRAPH_TYPE_LABEL[t] || '')));
  const life = normalize(sample);
  const pay = graphPayload(life, 'ev_fail');
  ok('노드·관계가 다 실린다', pay.nodes.length === life.nodes.length && pay.edges.length === life.edges.length);
  ok('고른 노드가 중심, 없으면 주인공', pay.center === 'ev_fail' && graphPayload(life, '없음').center === 'me');
  ok('차수를 센다 (주인공이 가장 많다)', pay.nodes.find((n) => n.id === 'me').degree >= 10);
  ok('관계 이름표가 한글', pay.edges.every((e) => /[가-힣]/.test(e.label)));
  ok('미룬 관계는 conf < 1', pay.edges.some((e) => e.conf < 1) && pay.edges.every((e) => e.conf <= 1));
  const meta = graphMeta(life);
  ok('범례가 캔버스 타입으로 세어진다', meta.node_types.person.count >= 4 && meta.node_types.artwork.count === 4 && meta.node_types.person.label === '인물·가족');
  ok('관계 종류 필터가 한글 이름으로', Object.values(meta.edge_types).every((t) => /[가-힣]/.test(t.label)) && meta.edge_types.caused.count === 3);
  ok('시작점은 차수 순', meta.seeds[0].id === 'me' && meta.seeds.length === 8);
  // 캔버스가 실제로 받는다 (DOM 없이 — layout.test 와 같은 흉내)
  const canvas = { clientWidth: 800, clientHeight: 600, getContext: () => null, addEventListener() {}, style: {} };
  let gv = null;
  try { gv = new GraphView(canvas, {}); } catch { gv = null; }
  if (gv) {
    gv.setData(pay);
    ok('GraphView 가 개인 그래프를 싣는다', gv.nodes.length === pay.nodes.length && gv.edges.length === pay.edges.length && gv.center === 'ev_fail');
  } else {
    ok('GraphView 는 브라우저가 필요하다 (여기서는 건너뜀)', true);
  }
}

console.log('\n개인 역사 — 노드를 지운다');
{
  // 상세 패널의 '삭제'. 지우는 것은 날것의 문서라 브라우저·계정에 남는 것도
  // 같이 지워진다 — 화면이 쥔 것만 고치면 새로고침에 되살아난다.
  const before = normalize(sample);
  const cut = removeNode(sample, 'ev_fail');
  const after = normalize(cut);
  ok('날것을 건드리지 않는다', sample.nodes.some((n) => n.id === 'ev_fail') && sample.nodes.length === before.nodes.length);
  ok('노드가 빠진다', !after.nodes.some((n) => n.id === 'ev_fail'));
  ok('그 노드의 관계가 함께 빠진다', before.edges.length > after.edges.length
    && !after.edges.some((e) => e.source === 'ev_fail' || e.target === 'ev_fail'));
  ok('연표에서 내려간다', before.timeline.some((t) => t.event_id === 'ev_fail')
    && !after.timeline.some((t) => t.event_id === 'ev_fail')
    && !personalMarks(after).some((m) => m.id === 'ev_fail'));
  ok('그래프에서도 내려간다', !graphPayload(after).nodes.some((n) => n.id === 'ev_fail'));
  ok('연표의 앞뒤가 다시 이어진다', after.timeline.every((t) => t.previous_event !== 'ev_fail' && t.next_event !== 'ev_fail'));
  ok('분석 묶음에 유령이 안 남는다',
    !after.turning_points.some((t) => t.event === 'ev_fail')
    && !after.counterfactual_analysis.some((c) => c.event === 'ev_fail')
    && !after.influence_ranking.items.some((it) => it.node === 'ev_fail'));
  // 가족·역사 연결도 같은 규칙 — 지운 사람이 '가족 뿌리'에 남으면 이름만 뜬다
  const noDad = normalize(removeNode(sample, 'father'));
  ok('가족 분석에서도 빠진다', !noDad.family_analysis.members.some((m) => m.node_id === 'father'));
  const noBust = normalize(removeNode(sample, 'ev_bankrupt'));
  ok('그 사건의 역사 연결이 빠진다', !noBust.historical_connections.some((c) => c.personal_event === 'ev_bankrupt'));
  // 같은 이름의 노드가 또 있으면 이름으로는 재지 않는다 — 이름만으로는 단정하지 않는다
  const twins = { nodes: [
    { id: 'a', type: 'PersonalEvent', name: '이사', start_date: '1998', confidence: 1 },
    { id: 'b', type: 'PersonalEvent', name: '이사', start_date: '2005', confidence: 1 },
  ], edges: [], timeline: [], turning_points: [{ event: '이사', turning_point_score: 7, reason: '두 번째 이사' }] };
  ok('이름이 겹치면 이름으로 지우지 않는다', removeNode(twins, 'a').turning_points.length === 1);
  ok('이름 하나뿐이면 이름으로 적힌 것도 지운다', removeNode(removeNode(twins, 'a'), 'b').turning_points.length === 0);
}

console.log('\n개인 역사 — 아직 배포하지 않는다');
{
  // 사용자 결정(2026-09-07): 로컬에서만 개발·테스트한다. Vercel 빌드에는 장이 없어야 한다.
  delete process.env.VERCEL;
  const local = (await import('../vite.config.js?local')).default;
  process.env.VERCEL = '1';
  const vercel = (await import('../vite.config.js?vercel')).default;
  delete process.env.VERCEL;
  ok('로컬 빌드에는 life.html 이 있다', !!local.build.rollupOptions.input.life && local.define['import.meta.env.VITE_LIFE'] === '"1"');
  ok('Vercel 빌드에는 life.html 이 없다', !vercel.build.rollupOptions.input.life && vercel.define['import.meta.env.VITE_LIFE'] === '""');
}

console.log(`\n${'='.repeat(46)}\n통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
