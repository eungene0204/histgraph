// 개인 역사 — 세 열이 한 자 위에 서는지, 화면에 영어가 새지 않는지.
//
//   node web/tests/life.test.mjs
//
// 브라우저 없이 돈다. 배치(lifeLayout)와 그리기(renderLife)는 순수 함수다.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  normalize, removeNode, editNode, nodeYears, dateSaid, parseWhen, lifeLayout, renderLife, renderHead, personalMarks, historyMarks, stageBands,
  ladder,
  graphPayload, graphMeta, GRAPH_TYPE, GRAPH_TYPE_LABEL, edgeLabel, tidyEdges, deedOf, LIFE_EDGES, RELAX,
  splitStories, joinStories, appendDraft, nodeLabel, participantsFromStory, linkParticipants, saysDate,
  addedFocus, addedNames,
  linkPeople, kinIn, markYs,
  NODE_TYPE_KO, EDGE_TYPE_KO, IMPACT_KO, LIFE_STAGES, COLS, MILITARY,
} from '../src/lib/life.js';
import { searchNodes } from '../src/lib/life.js';
import { isTyping } from '../src/lib/keys.js';
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
  ok('양끝 없는 관계·모르는 관계는 버린다', !n.edges.some((e) => e.type === 'flew' || e.target === 'bad'));
  ok('버려서 섬이 된 사건은 주인공에게 잇는다', n.edges.length === 1 && n.edges[0].type === 'experienced'
    && n.edges[0].source === 'me' && n.edges[0].target === 'e1', JSON.stringify(n.edges));
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
  // '가능성'은 화살표를 긋지 않는다 (2026-09-08 "세월호 사건과 퍼듀대학교 졸업은 도대체 무슨 상관이지?")
  {
    const guess = normalize({ ...sample, historical_connections: [
      ...sample.historical_connections,
      { personal_event: 'ev_bankrupt', historical_event: '제2연평해전', year: 2002, node_id: 'x:guess', node_label: '제2연평해전',
        impact_type: 'possible', description: '영향을 미쳤을 수 있음', confidence: 0.4 },
    ] });
    const g = lifeLayout({ life: guess, context, bodyH: 700, today: 2026 });
    ok("'가능성' 연결은 역사 열에 서되 화살표가 없다",
      g.history.some((p) => p.m.id === 'x:guess' && p.m.linked) && !g.links.some((l) => l.from === 'x:guess'),
      String(g.links.length));
  }
  ok('그래프에 없는 사건도 세우되 표시한다', lay.history.some((p) => p.m.kind === 'extra' && p.m.label === '2002년 FIFA 월드컵'));
  ok('생년보다 앞선 사건(6·25)은 축이 아니라 머리에 선다', lay.before.some((m) => m.id === 'wd:Q8663' && m.links.length === 1) && !lay.history.some((p) => p.m.id === 'wd:Q8663'));
  ok('축은 생년 두 해 앞에서 연다', lay.from === 1983);
  // 인과
  ok('개인 사건의 인과가 선이 된다', lay.causal.length >= 8 && lay.causal.every((c) => !c.backwards), String(lay.causal.length));
  // 재위 띠·인생 단계
  ok('구간에 걸친 대통령만 선다', lay.reigns.length === 3);
  const st = stageBands(life, 2026);
  ok('인생 단계 띠가 이어진다', st.length >= 6 && st.every((b, i) => !i || st[i - 1].end === b.start) && st[st.length - 1].end === 2026, JSON.stringify(st));
  // 군복무 — 공익근무도 병역이다 (2026-09-08 사용자: "사실 공익근무는 군복무 기간이야.
  // 훈련소, 공익근무 역시 군복무로 인식할 수 있게 해줘"). 모델은 '사회생활'로 적어 온다.
  const army = normalize({
    nodes: [{ id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'col', type: 'PersonalEvent', name: '신구대학 입학', start_date: '2000', confidence: 1 },
      { id: 'a1', type: 'PersonalEvent', name: '30사단 훈련소 입소', start_date: '2002-03', confidence: 1 },
      { id: 'a2', type: 'PersonalEvent', name: '천호3동 사무소 공익요원 근무 시작', start_date: '2002-04', confidence: 1 },
      { id: 'a3', type: 'PersonalEvent', name: '소집해제', start_date: '2004', confidence: 1 },
      { id: 'mv', type: 'PersonalEvent', name: '미국으로 이주', start_date: '2006', confidence: 1 }],
    edges: [],
    timeline: [{ event_id: 'col', life_stage: '대학', year: 2000 },
      { event_id: 'a1', life_stage: '사회생활', year: 2002 },
      { event_id: 'a2', life_stage: '사회생활', year: 2002 },
      { event_id: 'a3', life_stage: '사회생활', year: 2004 },
      { event_id: 'mv', life_stage: '사회생활', year: 2006 }],
  });
  const as = Object.fromEntries(army.timeline.map((t) => [t.event_id, t.life_stage]));
  ok('훈련소·공익근무·소집해제는 군복무다', as.a1 === '군복무' && as.a2 === '군복무' && as.a3 === '군복무', JSON.stringify(as));
  ok('병역이 아닌 것은 그대로', as.col === '대학' && as.mv === '사회생활', JSON.stringify(as));
  // 단계는 뒤로 가지 않는다 (2026-09-09 실측: 공익 시절에 만난 사람의 항목이 '초등학교').
  // 서버가 세운 만남 사건은 단계를 안 달고 오고, 그 단계는 앞뒤가 같을 때만 잇는다.
  const stages = normalize({
    nodes: [{ id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'a2', type: 'PersonalEvent', name: '천호3동 사무소 공익요원 근무 시작', start_date: '2002-04', confidence: 1 },
      { id: 'gf', type: 'PersonalEvent', name: '정혜림을 만남', start_date: '2002', confidence: 0.9 },
      { id: 'a3', type: 'PersonalEvent', name: '소집해제', start_date: '2004', confidence: 1 },
      { id: 'mv', type: 'PersonalEvent', name: '미국으로 이주', start_date: '2006', confidence: 1 }],
    edges: [],
    timeline: [{ event_id: 'a2', life_stage: '군복무', year: 2002 },
      { event_id: 'gf', life_stage: '초등학교', year: 2002 },
      { event_id: 'a3', life_stage: '군복무', year: 2004 },
      { event_id: 'mv', life_stage: null, year: 2006 }],
  });
  const ss = Object.fromEntries(stages.timeline.map((t) => [t.event_id, t.life_stage]));
  // 같은 해의 앞 항목에서 잇는다 — 2000년 대학 입학 다음에 선 '최근호를 만남'은 '대학'.
  const sameYear = normalize({
    nodes: [{ id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'entry', type: 'PersonalEvent', name: '신구대학 입학', start_date: '2000', confidence: 1 },
      { id: 'met', type: 'PersonalEvent', name: '최근호를 만남', start_date: '2000', confidence: 0.9 },
      { id: 'army', type: 'PersonalEvent', name: '30사단 훈련소 입소', start_date: '2002', confidence: 1 }],
    edges: [],
    timeline: [{ event_id: 'entry', life_stage: '대학', year: 2000 },
      { event_id: 'met', life_stage: null, year: 2000 },
      { event_id: 'army', life_stage: '군복무', year: 2002 }],
  });
  ok('같은 해의 앞 항목에서 단계를 잇는다',
    sameYear.timeline.find((t) => t.event_id === 'met').life_stage === '대학',
    JSON.stringify(sameYear.timeline));
  ok('스무 살의 항목이 초등학교로 되돌아가지 않는다', ss.gf === '군복무', JSON.stringify(ss));
  ok('뒤가 없으면 빈 단계는 채우지 않는다', ss.mv === null, JSON.stringify(ss));
  ok("'공익생활'도 군복무로 읽는다", MILITARY.test('공익생활을 하던 시절'));

  // 더한 것으로 화면이 옮겨 간다 (2026-09-09 사용자: "모델이 해석을 끝냈으면 그래프와
  // 연표에 바로 적용되야 하는데"). 연표에 서는 것(해를 아는 사건)이 먼저, 이른 것부터.
  const madeDoc = { nodes: [
    { id: 'p', type: 'Person', name: '정혜림', year: 2002 },
    { id: 'e2', type: 'PersonalEvent', name: '제주도 혼자 여행', year: 2013 },
    { id: 'e1', type: 'PersonalEvent', name: '정혜림을 만남', year: 2002 },
    { id: 'x', type: 'PersonalEvent', name: '해를 모르는 일', year: null },
  ] };
  ok('더한 것 중 이른 사건으로 간다', addedFocus(madeDoc, ['e2', 'e1', 'p']) === 'e1');
  ok('사건이 없으면 사람이라도 고른다', addedFocus(madeDoc, ['p']) === 'p');
  ok('해를 모르는 것뿐이면 그것을 고른다', addedFocus(madeDoc, ['x']) === 'x');
  ok('더한 것이 없으면 움직이지 않는다', addedFocus(madeDoc, []) === null && addedFocus(madeDoc, undefined) === null);
  ok('무엇이 늘었는지 이름으로 적는다',
    JSON.stringify(addedNames(madeDoc, ['e2', 'e1', 'p'])) === JSON.stringify(['정혜림을 만남', '제주도 혼자 여행']));

  const ab = stageBands(army, 2026).map((b) => `${b.stage} ${b.start}~${b.end}`);
  ok('띠는 소집해제한 해에 닫는다 (2년 복무가 4년이 되지 않게)',
    ab.includes('군복무 2002~2004') && ab.includes('사회생활 2006~2026'), ab.join(' · '));

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
  // 섬 — '성내중학교 졸업'은 다른 사건하고만 이어져 있었다 (2026-09-08 사용자:
  // "'나'와의 연결이 없이 떨어진 그래프들이 보이는데 왜 따로 떼어둔거지?")
  ok('떨어진 사건은 주인공이 겪은 것으로 잇고 이름도 단다',
    mk.get('me>gr') === 'experienced' && mr.get('me>gr') === '졸업', mk.get('me>gr'));
  // 차례만 말하는 엣지는 세우지 않는다 (2026-09-08 사용자: "다음 이라는 메뉴는 뭐야?
  // 별 정보값이 없는데 그냥 삭제해") — 그 차례는 연표가 이미 연도로 그린다. 옮길 데가
  // 있는 것(주인공 → 자기 사건의 after)은 참여로 남으므로 버리는 것은 사건 → 사건뿐이다.
  ok('사건 → 사건의 before 는 세우지 않는다 (차례는 연표가 그린다)', !mk.has('gr>hs'));
  ok('사건 → 학교·전공의 studied_at 은 그 곳(at)으로 옮긴다', mk.get('hs>sch') === 'at' && mk.get('hs>major') === 'at');
  ok('사람 → 사건의 역할은 사건 이름의 술어 (이주·입학), 없으면 사건의 종류(실패); 옮긴 전공은 역할 "전공"',
    [mr.get('me>mv'), mr.get('me>hs'), mr.get('me>fail'), mr.get('hs>major')].join(',') === '이주,입학,실패,전공', [...mr].join(' '));
  const pay = graphPayload(messy, 'me');
  const lab = (a, b) => pay.edges.find((e) => e.s === a && e.t === b)?.label;
  ok('선 위의 말: 역할이 이기고 없으면 양끝 — 이주 · 실패 · 학교 · 전공 · 이주지 · 친구 · 같은 학교',
    [lab('me', 'mv'), lab('me', 'fail'), lab('hs', 'sch'), lab('hs', 'major'), lab('mv', 'usa'), lab('me', 'kim'), lab('kim', 'park')].join(',')
      === '이주,실패,학교,전공,이주지,친구,같은 학교',
    pay.edges.map((e) => `${e.s}>${e.t}:${e.label}`).join(' '));
  ok('사람 → 학교는 재학', lab('kim', 'sch') === '재학' && edgeLabel('studied_at', 'Person', 'School') === '재학');
  ok("화면에 '뒤'·'동안'·'다음'·'수학'·'앞'·'겪음'이 서지 않는다", !pay.edges.some((e) => ['뒤', '동안', '다음', '이전', '수학', '앞', '겪음'].includes(e.label)));
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

console.log("\n개인 역사 — 노드를 고르면 연표도 간다 (2026-09-09 \"한국사 처럼 자동으로 이동시켜줘\")");
{
  const life = normalize(sample);
  const lay = lifeLayout({ life, context, bodyH: 700, today: 2026 });
  // 사건은 제 자리 하나
  const bust = lay.personal.find((p) => p.m.id === 'ev_bankrupt');
  ok('고른 사건의 자리로 간다', JSON.stringify(markYs(lay, life, 'ev_bankrupt')) === JSON.stringify([bust.ty]));
  // 역사 열의 사건도 (그래프에서 눌러도, 연표에서 눌러도 같은 노드다)
  const imf = lay.history.find((p) => p.m.id === 'wd:Q625457');
  ok('역사 열의 사건도 찾는다', markYs(lay, life, 'wd:Q625457').includes(imf.ty));
  // 연표에 서지 않는 노드(인물)는 그와 이어진 사건들의 폭으로
  const person = life.nodes.find((n) => n.type === 'Person' && n.id !== life.subject?.id
    && life.edges.some((e) => e.source === n.id || e.target === n.id));
  const near = life.edges.filter((e) => e.source === person.id || e.target === person.id)
    .map((e) => (e.source === person.id ? e.target : e.source));
  const want = lay.personal.filter((p) => near.includes(p.m.id)).map((p) => p.ty);
  ok('연표에 없는 인물은 이어진 사건의 자리로', want.length > 0
    && JSON.stringify(markYs(lay, life, person.id).sort()) === JSON.stringify(want.sort()), person?.name);
  ok('아무 데도 안 걸리면 움직이지 않는다', markYs(lay, life, 'x:없는것').length === 0);
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

console.log('\n개인 역사 — 남의 생년은 짐작해 세우지 않는다');
{
  // 2026-09-08 사용자: "인물들의 출생연도 나이는 사용자가 입력하지 않은 이상 추측해서
  // 명시 하지마. 모르면 그냥 아예 명시를 하지마." 사람 노드의 year 는 생년이 아니라
  // 그 사람이 내 삶에 들어온 해(refine 이 '1학년 때 만난' 에서 센 것)다.
  ok('이야기가 말한 생년은 세운다', nodeYears({ type: 'FamilyMember', start_date: '1955', year: 1955 }) === '1955');
  ok('셈한 해뿐인 인물은 세우지 않는다', nodeYears({ type: 'Person', start_date: null, year: 1997 }) === '');
  ok('가족·조상·관계도 같다', ['FamilyMember', 'Ancestor', 'Relationship']
    .every((t) => nodeYears({ type: t, start_date: null, year: 1960 }) === ''));
  ok('책·영화의 해는 그대로', nodeYears({ type: 'Book', start_date: null, year: 1996 }) === '1996');
  // 원문을 모르는 자리(계정에만 있는 옛 그래프)에서는 미룬 날짜를 표식으로 읽는다
  ok('미룬 생년(confidence < 1)은 세우지 않는다',
    nodeYears({ type: 'Person', start_date: '1982-01-01', year: 1982, confidence: 0.9 }) === '');
  ok('말한 생년(confidence 1)은 세운다',
    nodeYears({ type: 'Person', start_date: '1982', year: 1982, confidence: 1 }) === '1982');
  // 연표에 서면 그 자리가 곧 생년이다 — 나이('0세')와 단계('출생')를 달고 선다
  const guessed = normalize({
    nodes: [
      { id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'f1', type: 'Person', name: '친구', start_date: null, confidence: 0.9 },
      { id: 'f2', type: 'FamilyMember', name: '딸', start_date: '2024', confidence: 1 },
    ],
    edges: [],
    timeline: [{ event_id: 'f1', life_stage: '출생', year: 1982 }, { event_id: 'f2', life_stage: '가족 형성', year: 2024 }],
  });
  const marks = personalMarks(guessed).map((m) => m.id);
  ok('이야기가 날짜를 말하지 않은 인물은 연표에 안 선다', !marks.includes('f1'), marks.join(','));
  ok('말한 인물은 그대로 선다', marks.includes('f2'), marks.join(','));
  // 주인공의 생일 — '출생' 사건이 든 날짜가 이긴다 (2026-09-08 사용자: "2월 27일에
  // 태어 났다고 했는데, 왜 헷갈리게 '1982-01-01 · 0세 · 출생' 이라고 써있지").
  const born = normalize({
    nodes: [
      { id: 'me', type: 'Person', name: '나', start_date: '1982-01-01', confidence: 1,
        description: '1982년 2월 27일 서울에서 태어난 사람.' },
      { id: 'b1', type: 'Time', name: '출생', start_date: '1982-02-27', confidence: 1 },
    ],
    edges: [{ source: 'me', target: 'b1', type: 'experienced', role: '출생', confidence: 1 }],
    timeline: [{ event_id: 'b1', life_stage: '출생', age: 0, date_text: '1982-02-27', year: 1982 },
      { event_id: 'me', life_stage: '출생', age: 0, year: 1982 }],
    subject: { id: 'me', name: '나' },
  });
  ok("모델이 적어 둔 1월 1일 대신 '출생' 사건의 날짜를 쓴다",
    born.nodes[0].start_date === '1982-02-27', born.nodes[0].start_date);
  ok('주인공은 연표의 항목이 아니다', born.timeline.map((t) => t.event_id).join(',') === 'b1',
    born.timeline.map((t) => t.event_id).join(','));
  ok('생년은 그대로', born.subject.birth_year === 1982, JSON.stringify(born.subject));
  ok('해가 다른 출생은 남의 것이라 가져오지 않는다', normalize({
    nodes: [{ id: 'me', type: 'Person', name: '나', start_date: '1982-01-01', confidence: 1 },
      { id: 'b1', type: 'Time', name: '출생', start_date: '1955-03-02', confidence: 1 }],
    edges: [], timeline: [],
  }).nodes[0].start_date === '1982-01-01');
  // 항목의 해와 노드의 날짜가 어긋나면 **달까지 아는 날짜**가 이긴다 (2026-09-08
  // 지적: "메탈리카 공연은 1998년 이었어" — 1998-04-24 공연이 항목에는 1997 ·
  // 만 15세로 적혀 와 1997 칸에 '4월'로 섰다).
  const off = normalize({
    nodes: [
      { id: 'me', type: 'Person', name: '나', start_date: '1982-02-27', confidence: 1 },
      { id: 'gig', type: 'PersonalEvent', name: '메탈리카 공연 관람', start_date: '1998-04-24', confidence: 1 },
      { id: 'grad', type: 'PersonalEvent', name: '중학교 졸업', start_date: '1997', confidence: 1 },
    ],
    edges: [],
    timeline: [{ event_id: 'gig', age: 15, year: 1997 }, { event_id: 'grad', age: 15, year: 1997 }],
    subject: { id: 'me', name: '나', birth_year: 1982 },
  });
  const gig = off.timeline.find((t) => t.event_id === 'gig');
  ok('달까지 아는 날짜가 항목의 해를 이긴다', gig.year === 1998, String(gig.year));
  ok('어림한 나이도 다시 센다', gig.age === 16, String(gig.age));
  ok('해까지만 아는 날짜는 항목의 해를 두고 본다',
    off.timeline.find((t) => t.event_id === 'grad').year === 1997);
  ok('연표의 그 줄도 1998 로 선다',
    personalMarks(off).find((m) => m.id === 'gig').year === 1998);
  ok('해가 없으면 빈 칸', nodeYears({ type: 'Book', year: null }) === '');
  ok('끝나는 해가 있으면 물결로', nodeYears({ type: 'Company', start_date: '2004', year: 2004, end_year: 2011 }) === '2004~2011');
  // 화면이 그 규칙을 쓰는지 — '사람 · 문화' 탭이 nodeYears 로 해를 세운다
  const view = readFileSync(here('../src/components/LifeView.jsx'), 'utf8');
  ok('사람 · 문화 탭이 이 규칙으로 해를 세운다', /nodeYears\(n\)/.test(view) && !/\{n\.year\}/.test(view));
}

console.log('\n개인 역사 — 학제의 차례는 이야기의 차례를 이긴다 (2026-09-08 "초등학교 졸업을 해야 중학교 입학을 하지")');
{
  ok('사다리 — 초등 입학 10 · 초등 졸업 12 · 중학 입학 20 · 대학 졸업 42',
    ladder({ type: 'PersonalEvent', name: '성일초등학교 입학' }) === 10
    && ladder({ type: 'PersonalEvent', name: '성내초등학교 졸업' }) === 12
    && ladder({ type: 'PersonalEvent', name: '성내중학교 입학' }) === 20
    && ladder({ type: 'PersonalEvent', name: '퍼듀대학교 졸업' }) === 42
    && ladder({ type: 'PersonalEvent', name: '대학원 입학' }) === 50);
  ok('학제와 무관한 사건·사람은 사다리에 없다',
    ladder({ type: 'PersonalEvent', name: '미국으로 이주' }) === null
    && ladder({ type: 'School', name: '성내중학교' }) === null);
  ok('이름이 층을 말하면 설명은 안 본다 (설명은 앞뒤를 같이 말한다)',
    ladder({ type: 'PersonalEvent', name: '성내중학교 입학', description: '성내초등학교를 졸업하고 성내중학교에 입학함' }) === 20);
  // 달을 모르는 같은 해 — 이야기가 중학교 입학을 먼저 말했어도 졸업이 먼저 선다
  const school = normalize({
    nodes: [
      { id: 'me', type: 'Person', name: '나', start_date: '1982', confidence: 1 },
      { id: 'ms_in', type: 'PersonalEvent', name: '성내중학교 입학', start_date: '1994', confidence: 1 },
      { id: 'es_out', type: 'PersonalEvent', name: '성내초등학교 졸업', start_date: '1994', confidence: 1 },
      { id: 'move', type: 'PersonalEvent', name: '이사', start_date: '1994', confidence: 1 },
    ],
    edges: [],
    timeline: [{ event_id: 'ms_in', life_stage: '중학교', year: 1994 },
      { event_id: 'move', life_stage: '어린 시절', year: 1994 },
      { event_id: 'es_out', life_stage: '초등학교', year: 1994 }],
    subject: { id: 'me', name: '나', birth_year: 1982 },
  });
  const order = personalMarks(school).map((m) => m.id);
  ok('같은 해면 초등 졸업이 중학 입학보다 먼저 선다', order.indexOf('es_out') < order.indexOf('ms_in'), order.join(','));
  ok('사다리에 없는 사건은 제자리에 남는다 (자리만 맞바꾼다)', order[1] === 'move', order.join(','));
  ok('연표의 차례도 같이 선다', school.timeline.map((t) => t.event_id).join(',') === 'es_out,move,ms_in',
    school.timeline.map((t) => t.event_id).join(','));
}

console.log('\n개인 역사 — 함께한 사람 (2026-09-08 "친구 김일권과 같이 갔다고 분명 말했는데")');
{
  const doc = () => ({
    nodes: [
      { id: 'me', type: 'Person', name: '나', start_date: '1982-02-27', confidence: 1 },
      { id: 'kim', type: 'Person', name: '김일권', confidence: 1 },
      { id: 'gig', type: 'PersonalEvent', name: '메탈리카 공연 관람', start_date: '1998-04-24',
        participants: ['me'], confidence: 1 },
      { id: 'ticket', type: 'Memory', name: '메탈리카 공연 티켓', start_date: '1998-04-24',
        participants: ['me'], confidence: 1 },
    ],
    edges: [{ source: 'me', target: 'gig', type: 'experienced', confidence: 1 }],
    timeline: [{ event_id: 'gig', year: 1998 }],
    subject: { id: 'me', name: '나', birth_year: 1982 },
    stories: [{ at: '', text: '1998년 4월 24일 메탈리카 공연을 친구 김일권과 함께 갔어. 티켓도 아직 가지고 있어.' }],
  });
  const life = normalize(doc());
  const gig = life.nodes.find((n) => n.id === 'gig');
  ok('이야기 한 문장이 사건과 사람을 함께 부르면 함께한 사람이다',
    gig.participants.includes('kim'), JSON.stringify(gig.participants));
  ok('그 사람은 사건에 이어진다 (역할 함께)',
    life.edges.some((e) => e.source === 'kim' && e.target === 'gig' && e.type === 'experienced' && e.role === '함께'),
    JSON.stringify(life.edges));
  ok('기억(티켓)은 날짜로 잡지 않는다',
    !life.nodes.find((n) => n.id === 'ticket').participants.includes('kim'));
  // 이름으로 적어 와도 같은 자리에 선다
  const named = doc();
  named.nodes[2].participants = ['나', '김일권', 'person_9'];
  const byName = normalize(named).nodes.find((n) => n.id === 'gig');
  ok('이름으로 적어 온 것도 노드 id 로 푼다',
    byName.participants.join(',') === 'me,kim', JSON.stringify(byName.participants));
  ok('못 푸는 식별자는 버린다', !byName.participants.includes('person_9'));
  // 근거가 없으면 잇지 않는다 — 해만 같은 문장은 그 해의 일을 여럿 담는다
  const loose = doc();
  loose.stories = [{ at: '', text: '1998년에 김일권과 자주 만났어. 메탈리카 공연도 갔어.' }];
  loose.nodes[2].participants = ['me'];
  loose.nodes[3].participants = ['me'];
  const far = normalize(loose).nodes.find((n) => n.id === 'gig');
  ok('해만 말한 문장으로는 잇지 않는다', !far.participants.includes('kim'), JSON.stringify(far.participants));
  ok('달까지 아는 날짜만 잰다', saysDate('1998년 4월 24일 공연', '1998-04-24')
    && saysDate('1998-04-24 공연', '1998-04-24') && !saysDate('1998년에 공연', '1998-04-24')
    && !saysDate('1998년 공연', '1998'));
  // 화면에 낼 수 있는 이름인가 — 아이디는 낼 수 없다
  const byId = new Map(life.nodes.map((n) => [n.id, n]));
  ok('아는 아이디는 이름으로', nodeLabel(byId, 'kim') === '김일권');
  ok('모르는 식별자는 빈 칸', nodeLabel(byId, 'person_1') === '' && nodeLabel(byId, null) === '');
  ok('그래프에 없어도 한글이면 그대로', nodeLabel(byId, '박정환') === '박정환');
  // 화면이 그 규칙을 쓰는가 — '함께' 줄은 이름으로 서고, 아무도 없으면 서지 않는다
  const view = readFileSync(here('../src/components/LifeView.jsx'), 'utf8');
  ok("'함께' 줄은 푼 이름으로 선다", /withWhom\.length > 0 && <><dt>함께<\/dt>/.test(view)
    && !/node\.participants\.join/.test(view), '아직 participants 를 그대로 적는다');
  // 같은 사람이 위(함께)와 아래(관련)에 두 번 서지 않는다 (2026-09-08 "왜 함께가
  // 두 번 들어가지 한 번만 보여줘"). 선이 그어진 사람은 '관련'이 맡는다.
  // 그래프에 있는 것은 어디서든 눌러서 옮겨간다 (2026-09-08 "node에 있으면 링크를 걸어 줘야지")
  ok("'관련'의 상대는 눌러서 옮겨간다",
    /byId\.has\(other\)\s*\n?\s*\? <button type="button" className="life-link" onClick=\{\(\) => onPick\(other\)\}/.test(view),
    '관련이 아직 이름만 적는다');
  ok('분석의 사건·사람도 같은 단추다', /const Link = \(\{ id \}\) => \(isEvent\(id\)/.test(view)
    && !/<b>\{nameOf\(p\.event\)\}<\/b>/.test(view));
  ok("'관련'에 선 사람은 '함께' 줄에 다시 적지 않는다",
    /const tied = new Set\(\[\.\.\.ins, \.\.\.outs\]/.test(view) && /!tied\.has\(pid\)/.test(view));
  ok('이름을 못 푸는 아이디를 적는 자리가 없다', !/\?\.name \|\| nid/.test(view));
  // linkParticipants 는 있는 선을 두 번 세우지 않는다
  const nodes = doc().nodes;
  const edges = [{ source: 'kim', target: 'gig', type: 'experienced', confidence: 1 }];
  nodes[2].participants = ['me', 'kim'];
  ok('이미 이어진 것은 다시 잇지 않는다', linkParticipants(nodes, edges, nodes[0]) === 0 && edges.length === 1);
  ok('이야기가 없으면 아무것도 안 한다', participantsFromStory(doc().nodes, '') === 0);
}

console.log('\n개인 역사 — 가족은 호칭으로 잇는다 (2026-09-08 "왜 엄마라고 분명히 말했고 … 엣지를 그리지 않았지?")');
{
  // 더한 토막의 모델 답이 person_mother → person_1 을 적었지만 주인공 노드가 새 답에
  // 없어 관문이 버렸고, 브라우저에 남은 그래프에는 어머니가 홀로 떴다. 화면은 이야기를
  // 읽어 잇는다 — 서버 없이도, 새로고침만으로.
  const doc = () => ({
    nodes: [
      { id: 'person_1', type: 'Person', name: '나', start_date: '1982-02-27', confidence: 1 },
      { id: 'kim', type: 'Person', name: '김일권', description: '고등학교 1학년 때 만난 친구', confidence: 1 },
      { id: 'gig', type: 'PersonalEvent', name: '메탈리카 공연 관람', start_date: '1998-04-24', confidence: 1 },
      { id: 'person_mother', type: 'Person', name: '백경순', start_date: '1953-07-09', confidence: 1 },
    ],
    edges: [{ source: 'person_1', target: 'gig', type: 'experienced', confidence: 1 },
      { source: 'kim', target: 'gig', type: 'experienced', confidence: 1 }],
    timeline: [{ event_id: 'gig', year: 1998 }],
    subject: { id: 'person_1', name: '나', birth_year: 1982 },
    stories: [{ at: '', text: '1998년 4월 24일 메탈리카 공연을 친구 김일권과 함께 갔어.' },
      { at: '', text: '우리 엄마는 1953년 7월 9일에 태어나셨어. 성함은 백경순이야.' }],
  });
  const life = normalize(doc());
  const mom = life.edges.find((e) => [e.source, e.target].includes('person_mother'));
  ok('엄마와 나 사이에 부모 관계가 선다 (부모 → 자녀)',
    mom && mom.type === 'parent_of' && mom.source === 'person_mother' && mom.target === 'person_1', JSON.stringify(life.edges));
  ok("호칭 '엄마'가 선의 이름이다", mom?.role === '엄마' && graphPayload(life).edges.find((e) => e.s === 'person_mother')?.label === '엄마');
  ok('본인이 말한 것이라 확신 1', mom?.confidence === 1);
  const momNode = life.nodes.find((n) => n.id === 'person_mother');
  ok('사용자가 말한 생일 1953-07-09 는 남는다', momNode.start_date === '1953-07-09' && momNode.year === 1953 && nodeYears(momNode) === '1953');
  ok('이미 이어진 사람(김일권)은 건드리지 않는다', life.edges.filter((e) => e.source === 'kim' || e.target === 'kim').length === 1);
  ok('두 번 다듬어도 그대로', normalize(life).edges.length === life.edges.length);
  // 호칭은 낱말이다 — 이름 안의 글자('나형철'의 '형')로는 잇지 않는다
  ok("'나형철'의 '형'은 호칭이 아니다", kinIn('이름은 나형철이고 지금까지 만나고 있어', ['나형철']) === null);
  ok("'우리형은' 은 형이다", kinIn('우리형은 1980년생이야')?.term === '형' && kinIn('동생 박준영과 갔어')?.kind === 'relative_of');
  const me = { id: 'me', type: 'Person', name: '나' };
  const two = () => [me, { id: 'k', type: 'Person', name: '김일권' }];
  let edges = [];
  linkPeople(two(), edges, me, '친구 김일권의 엄마는 선생님이셨어.');
  ok("남의 가족('김일권의 엄마')은 내 가족이 아니다 — 이름이 불렸으니 만난 사이", edges.length === 1 && edges[0].type === 'met' && edges[0].confidence === 0.8, JSON.stringify(edges));
  edges = [];
  linkPeople(two(), edges, me, '내 아들 김일권은 2010년에 태어났어.');
  ok('아들은 나 → 그 사람 (부모 → 자녀)', edges[0]?.type === 'parent_of' && edges[0].source === 'me' && edges[0].role === '아들', JSON.stringify(edges));
  edges = [{ source: 'k', target: 'me', type: 'parent_of', confidence: 1 }];
  ok('모델이 이미 이은 가족 관계에는 호칭만 단다', linkPeople(two(), edges, me, '우리 아버지는 김일권이야.') === 0 && edges.length === 1 && edges[0].role === '아버지');
  ok('이름이 이야기에 없으면 잇지 않는다', linkPeople(two(), [], me, '우리 엄마는 1953년에 태어나셨어.') === 0);
  ok('이야기가 없으면 아무것도 안 한다', linkPeople(two(), [], me, '') === 0);
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

console.log('\n개인 역사 — 노드를 고친다');
{
  // 상세 패널의 '편집' (2026-09-09 사용자: "'삭제' 옆에 '편집'버튼 … 표시된 모든
  // 정보를 사용자가 직접 편집 … 완료 버튼 누르면 그래프와 연표에 바로 반영").
  // 지우기와 같은 규칙이다 — 고치는 것은 날것의 문서라 브라우저·계정에 남는
  // 것도 같이 고쳐진다.
  const view = normalize(sample);

  // 날짜 — 서버가 풀어 둔 옛 해(year·precision)가 남으면 고쳐도 연표는 옛 칸에 선다
  const moved = normalize(editNode(sample, 'ev_worldcup', {
    name: '월드컵의 기억', start_date: '2003-06', timeline: { date_text: '2003년 6월', life_stage: '고등학교' },
  }));
  ok('날것을 건드리지 않는다', sample.nodes.find((n) => n.id === 'ev_worldcup').name === '2002년 월드컵의 기억');
  ok('이름이 바뀐다', moved.nodes.find((n) => n.id === 'ev_worldcup').name === '월드컵의 기억');
  ok('고친 날짜로 연표가 다시 선다', moved.timeline.find((t) => t.event_id === 'ev_worldcup').year === 2003);
  ok('나이도 다시 센다', moved.timeline.find((t) => t.event_id === 'ev_worldcup').age === 2003 - 1985);
  ok('연표 점이 그 해로 옮겨 간다', personalMarks(moved).find((m) => m.id === 'ev_worldcup')?.year === 2003);
  ok('안 건드린 것은 그대로', moved.nodes.find((n) => n.id === 'ev_worldcup').description
    === sample.nodes.find((n) => n.id === 'ev_worldcup').description);

  // 연표에서 내린다 — 앞뒤를 이어 붙이는 것은 지우기와 같다. 노드는 남는다.
  const off = normalize(editNode(sample, 'ev_worldcup', { start_date: '', timeline: null }));
  ok('날짜를 비우면 연표에서 내려간다', !off.timeline.some((t) => t.event_id === 'ev_worldcup')
    && !personalMarks(off).some((m) => m.id === 'ev_worldcup'));
  ok('내려도 노드는 그래프에 남는다', off.nodes.some((n) => n.id === 'ev_worldcup')
    && graphPayload(off).nodes.some((n) => n.id === 'ev_worldcup'));
  ok('연표의 앞뒤가 다시 이어진다',
    off.timeline.every((t) => t.previous_event !== 'ev_worldcup' && t.next_event !== 'ev_worldcup'));

  // 함께 — 폼에서 뺀 이름은 참여자에서도 빠진다. 관계로 이어진 사람은 '함께'에
  // 서지 않으므로(상세와 같은 규칙) 여기서 빠지지 않는다.
  const shop = normalize(editNode(sample, 'print_shop', { participants: ['아버지'], with_whom: [] }));
  ok('인쇄소에 아버지가 참여자로 있었다',
    (view.nodes.find((n) => n.id === 'print_shop').participants || []).length === 1);
  ok('폼에서 뺀 이름은 참여자에서도 빠진다',
    !(shop.nodes.find((n) => n.id === 'print_shop').participants || []).length);

  // 전환점
  const noTurn = normalize(editNode(sample, 'ev_fail', { turning: null }));
  ok('전환점에서 내린다', !noTurn.turning_points.some((t) => t.event === 'ev_fail'));
  ok('남의 전환점은 그대로', noTurn.turning_points.length === sample.turning_points.length - 1);
  const newTurn = normalize(editNode(sample, 'ev_ai', { turning: { turning_point_score: 99, reason: '요즘의 일' } }));
  const put = newTurn.turning_points.find((t) => t.event === 'ev_ai');
  ok('전환점으로 세운다', put?.reason === '요즘의 일');
  ok('점수는 1~10 안이다', put?.turning_point_score === 10);

  // 인물의 날짜 — 사람이 적은 것은 셈한 것이 아니다 (dateSaid)
  ok('셈한 날짜는 이름 옆에 안 선다', !dateSaid(view.nodes.find((n) => n.id === 'minjun')));
  const said = normalize(editNode(sample, 'minjun', { start_date: '1985-07' }));
  ok('사람이 적은 날짜는 선다', dateSaid(said.nodes.find((n) => n.id === 'minjun')));

  // 그 무렵의 한국사 · 만약 없었다면
  const links = view.historical_connections.filter((c) => c.personal_event === 'ev_bankrupt');
  const relink = normalize(editNode(sample, 'ev_bankrupt', { links: links.map((c) => ({ ...c, description: '고친 설명' })) }));
  ok('역사 연결의 설명을 고친다',
    relink.historical_connections.filter((c) => c.personal_event === 'ev_bankrupt').every((c) => c.description === '고친 설명'));
  const nolink = normalize(editNode(sample, 'ev_bankrupt', { links: [] }));
  ok('역사 연결을 뺀다', !nolink.historical_connections.some((c) => c.personal_event === 'ev_bankrupt'));
  ok('남의 역사 연결은 그대로', nolink.historical_connections.some((c) => c.personal_event === 'ev_move'));
  const cf = normalize(editNode(sample, 'ev_bankrupt', {
    counterfactual: [{ question: '부도가 없었다면?', answer: '대구에 남았을 것이다', possibilities: ['대구에 남았을 가능성', '  '] }] }));
  const one = cf.counterfactual_analysis.find((c) => c.event === 'ev_bankrupt');
  ok('만약 없었다면의 답을 고친다', one?.answer === '대구에 남았을 것이다');
  ok('빈 줄은 갈렸을 길이 되지 않는다', one?.possibilities.length === 1);

  // 화면 — 고치는 길이 지우는 길 옆에 서고, 완료가 그 자리에서 다시 그린다
  const src = readFileSync(here('../src/components/LifeView.jsx'), 'utf8');
  ok("상세 아래에 '편집' 이 '삭제' 옆에 선다", /삭제<\/button>[\s\S]{0,300}>편집<\/button>/.test(src));
  ok('완료를 누르면 날것을 고쳐 다시 받아들인다', /editNode\(raw, id, patch\)[\s\S]{0,600}adopt\(next, 'local'\)/.test(src));
  ok('고친 것은 계정에도 남는다', /const saveNode[\s\S]{0,900}keepInAccount\(next\)/.test(src));
  ok('다른 노드로 옮겨 가면 폼이 접힌다', /\[selected\]/.test(src) && /setEditing\(false\)/.test(src));
  ok('폼의 글자에 영어가 없다',
    (src.match(/<option key=\{s\} value=\{s\}>|>완료<|>취소<|>사람 더하기<|>전환점으로 세우기</g) || []).length >= 4);
  ok('관계는 편집 칸에 없다 (2026-09-09 사용자)', !/<h3>관계<\/h3>/.test(src) && !/관계 더하기/.test(src));
}

console.log('\n개인 역사 — 내가 적은 이야기');
{
  // 옛 문서에는 기록 열이 없다 — 서버에 남은 원문을 빈 줄로 가른다.
  // (server.LifeAnalysis._run 이 이어 붙일 때 넣는 그 빈 줄이다.)
  const raw = '잠실고딩학교 1학넌때 친구 김일권을 만났고\n\n\n잠실고등학교 1학년때 김일권을 만났고\n\n2002년 3월에 30사단 입대';
  const got = splitStories(raw);
  ok('원문을 적어 넣은 덩어리로 가른다', got.length === 3 && got[2].text === '2002년 3월에 30사단 입대');
  ok('적은 날을 모르면 지어내지 않는다', got.every((g) => g.at === ''));
  ok('빈 글은 덩어리가 되지 않는다', splitStories('\n\n   \n\n').length === 0);
  // 고쳐서 다시 읽을 때 서버가 받는 글 — 이어 붙인 꼴이 원문과 같다.
  ok('다시 한 편으로 이어 붙인다', joinStories(got) === '잠실고딩학교 1학넌때 친구 김일권을 만났고\n\n잠실고등학교 1학년때 김일권을 만났고\n\n2002년 3월에 30사단 입대');
  ok('지운 덩어리는 빠진다', joinStories(got.filter((g, i) => i !== 0)) === '잠실고등학교 1학년때 김일권을 만났고\n\n2002년 3월에 30사단 입대');
  ok('다 지우면 빈 글이다', joinStories([{ at: '', text: '  ' }]) === '');
  // 줄을 눌러 입력창으로 옮길 때 — 적다 만 글은 삼키지 않고 아래에 붙인다.
  ok('빈 입력창에는 그대로 들어간다', appendDraft('', '1993년 부터') === '1993년 부터');
  ok('적다 만 글 아래에 붙는다', appendDraft('쓰던 글', '옛 글') === '쓰던 글\n\n옛 글');
  // 이미 있는 글이어도 붙인다 — 눌렀는데 아무 일도 없으면 고장으로 보인다.
  ok('이미 있는 글이어도 붙인다', appendDraft('옛 글', '옛 글') === '옛 글\n\n옛 글');
  ok('빈 글은 붙이지 않는다', appendDraft('쓰던 글', '   ') === '쓰던 글');
}

console.log('\n개인 역사 — 오른쪽 상세는 접힌다');
{
  // 2026-09-08 사용자: "이 오른쪽 DRAWER를 다시 접을수 있게 버튼을 만들어서
  // 오른쪽으로 들어 갈 수 있게 해 줘". 접는 것보다 **되돌아가는 길**이 관문이다 —
  // 접고 나서 펼 손잡이가 없으면 화면을 잃는다.
  const view = readFileSync(here('../src/components/LifeView.jsx'), 'utf8');
  const css = readFileSync(here('../style.css'), 'utf8');
  ok('탭 줄에 접는 단추가 있다', /life-detail-fold/.test(view) && /setDetailOpen\(false\)/.test(view));
  ok('접은 뒤 펼 손잡이가 남는다',
    /!detailOpen && \(/.test(view) && /life-detail-peek[\s\S]{0,200}setDetailOpen\(true\)/.test(view),
    '접으면 되돌아갈 길이 없다');
  ok('노드를 고르면 저절로 펴진다', /const pick = useCallback\([\s\S]{0,160}setDetailOpen\(true\)/.test(view));
  ok('접힌 동안은 탭에 걸리지 않는다', /inert=\{!detailOpen\}/.test(view));
  ok('오른쪽으로 미끄러져 들어간다', /\.life-detail\.is-folded[^}]*translateX\(100%\)/.test(css));
  ok('되찾은 폭을 가운데가 쓴다', /\.life-detail\.is-folded[^}]*margin-right: calc\(-1 \* var\(--fold-w\)\)/.test(css));
  ok('손잡이 글자가 한국어다', /aria-label="상세 펼치기"/.test(view) && /<span>상세<\/span>/.test(view));
}

console.log('\n개인 역사 — 검색');
{
  // 2026-09-09 사용자: "내 역사 페이지에 노드를 검색 할수 있는 기능넣어줘.
  // 검색창은 오른쪽 상단에 만들고 숏컷으로 '/' 을 누르면".
  const life = { nodes: [
    { id: 'e1', type: 'PersonalEvent', name: '대학 입학', description: '서울에서 공부를 시작했다', year: 1998 },
    { id: 'e2', type: 'PersonalEvent', name: '첫 출근', description: '대학 동기가 소개한 회사', year: 2004 },
    { id: 'p1', type: 'FamilyMember', name: '대학 친구 민수', year: null },
    { id: 'l1', type: 'Residence', name: '봉천동', location: '서울', year: 1998 },
  ] };
  const names = (rows) => rows.map((r) => r.id).join(',');
  ok('이름에 걸린 것이 설명에 걸린 것보다 먼저다',
    names(searchNodes(life, '대학')) === 'e1,p1,e2',
    names(searchNodes(life, '대학')));
  ok('이름이 그대로 같으면 맨 위다', searchNodes(life, '첫 출근')[0].id === 'e2');
  ok('장소·종류로도 찾는다', names(searchNodes(life, '서울')) === 'l1,e1');
  // 위의 '대학' 이 같은 자리(이름 머리) 둘을 냈다 — 1998년 입학이 해 없는 민수보다 위다.
  ok('해로는 찾지 않는다 — 그건 연표가 하는 일이다', names(searchNodes(life, '1998')) === '');
  ok('빈 말은 아무것도 안 찾는다', searchNodes(life, '   ').length === 0);
  ok('없는 말은 없다고 한다', searchNodes(life, '없는낱말').length === 0);
  ok('줄에 색 견본과 한국어 종류가 붙는다', (() => {
    const r = searchNodes(life, '봉천동')[0];
    return r.type === 'place' && r.group === 'thing' && r.kind_label === '거주지';
  })());
  ok('세는 수를 넘기지 않는다', searchNodes(life, '대학', 2).length === 2);

  const box = readFileSync(here('../src/components/LifeSearch.jsx'), 'utf8');
  const view = readFileSync(here('../src/components/LifeView.jsx'), 'utf8');
  const css = readFileSync(here('../style.css'), 'utf8');
  ok('검색창이 머리 줄 오른쪽에 선다',
    /<div className="top-right">[\s\S]{0,240}<LifeSearch/.test(view) && /\.life-search[^}]*grid-column: auto/.test(css),
    '오른쪽 상단이 아니다');
  ok('목록이 오른쪽 가장자리에 맞춰 떨어진다', /\.life-search \.results[^}]*right: 0/.test(css));
  ok("'/' 가 검색창으로 데려간다", /ev\.key !== '\/'/.test(box) && /inputRef\.current\?\.focus\(\)/.test(box));
  ok("글 치는 중의 '/' 는 글자다", /isTyping\(document\.activeElement\)/.test(box), '이야기 상자에서 커서를 뺏는다');
  ok('입력기가 조립 중인 키는 넘긴다', /imeKey\(ev\)/.test(box));
  ok('고른 노드는 연표·그래프·상세가 함께 따라간다', /onPick=\{pick\}/.test(view));
  ok('노드가 없으면 검색창도 없다', /\{life && <LifeSearch/.test(view));
  ok('창의 글자가 한국어다', !/[A-Za-z]/.test((box.match(/placeholder="([^"]*)"/) || [,''])[1]));
}
ok("글 치는 중을 가른다 (isTyping)",
  isTyping({ tagName: 'TEXTAREA' }) && isTyping({ tagName: 'INPUT' })
  && isTyping({ tagName: 'DIV', isContentEditable: true })
  && !isTyping({ tagName: 'DIV' }) && !isTyping(null));

console.log('\n개인 역사 — 배포에도 싣는다');
{
  // 사용자 결정(2026-09-09): 배포한다. 2026-09-07 에 걸어 둔 `!VERCEL` 을 풀었다 —
  // 그때 막은 이유(이야기를 읽는 길이 로컬에만 있었다)가 없어졌다.
  delete process.env.VERCEL;
  const local = (await import('../vite.config.js?local')).default;
  process.env.VERCEL = '1';
  const vercel = (await import('../vite.config.js?vercel')).default;
  delete process.env.VERCEL;
  ok('로컬 빌드에 life.html 이 있다', !!local.build.rollupOptions.input.life && local.define['import.meta.env.VITE_LIFE'] === '"1"');
  ok('배포 빌드에도 life.html 이 있다', !!vercel.build.rollupOptions.input.life && vercel.define['import.meta.env.VITE_LIFE'] === '"1"');
}

console.log(`\n${'='.repeat(46)}\n통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
