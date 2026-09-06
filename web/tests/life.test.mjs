// 개인 역사 — 세 열이 한 자 위에 서는지, 화면에 영어가 새지 않는지.
//
//   node web/tests/life.test.mjs
//
// 브라우저 없이 돈다. 배치(lifeLayout)와 그리기(renderLife)는 순수 함수다.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  normalize, parseWhen, lifeLayout, renderLife, renderHead, personalMarks, historyMarks, stageBands,
  NODE_TYPE_KO, EDGE_TYPE_KO, IMPACT_KO, LIFE_STAGES, COLS,
} from '../src/lib/life.js';

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
}

const sample = JSON.parse(readFileSync(here('../public/life-sample.json'), 'utf8'));
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

console.log('\n개인 역사 — 빈 자료');
{
  const life = normalize({ nodes: [{ id: 'me', type: 'Person', name: '나', confidence: 1 }], edges: [], timeline: [] });
  ok('해를 아는 사건이 없으면 배치가 없다', lifeLayout({ life, context: null }) === null);
  ok('연표가 비어도 표시 목록은 빈 배열', personalMarks(life).length === 0 && historyMarks(life, null).length === 0);
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
  ok('Vercel 빌드는 예시 자료를 뺀다', vercel.plugins.some((p) => p.name === 'strip-life'));
}

console.log(`\n${'='.repeat(46)}\n통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
