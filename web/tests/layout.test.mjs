// 배치 검증 — 브라우저 없이 돈다 (d3-force-3d 는 DOM 을 쓰지 않는다).
//
//   node web/tests/layout.test.mjs
//
// 손으로 짠 시뮬레이션 → d3-force(2D) → d3-force-3d(3D) 로 두 번 옮기면서
// 잃기 쉬운 것들을 잡아둔다: 좌표가 NaN 이 되는 것, 식지 않는 것, 중심이
// 원점을 안 지키는 것, 노드가 겹쳐 버리는 것, 이어진 노드가 안 이어진
// 노드보다 멀어지는 것.
//
// **화면과 같은 힘을 잰다** — `layout.js buildForces` 가 만든 것을 3D 엔진에도
// 여기에도 그대로 꽂는다. 3D 엔진(`3d-force-graph`)은 Node 에서 import 가
// 터지지만 힘은 여기서 돈다.
import { buildSimulation, buildForces, nodeRadius } from '../src/lib/layout.js';
import { buildScale, placeMarks, sortMarks, seatCount, markName, yearCell, yearCells, isCause, causeWire, reignBand, dateRuler, CAUSE_WIRE, dateContains } from '../src/lib/timeline.js';
import { causalReach, causalLayout, GraphView, MUTUAL, labelAlpha, withAlpha } from '../src/lib/graph-view.js';

let pass = 0;
let fail = 0;

function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? `  — ${extra}` : ''}`); }
}

// 별 모양 + 곁가지. 중심 하나에 여럿이 붙고, 그 바깥에 안 붙은 무리가 있다.
function sampleGraph(n = 40) {
  const nodes = [];
  const edges = [];
  for (let i = 0; i < n; i++) {
    const node = {
      id: `n${i}`,
      label: `노드${i}`,
      type: i === 0 ? 'person' : 'event',
      group: i === 0 ? 'actor' : 'event',
      degree: i === 0 ? n : 2,
    };
    node.r = nodeRadius(node);
    // 화면과 같은 자리에 뿌린다 — 황금각 방위 + 황금비 극각의 공 껍질
    // (graph-view.js setData). 무작위가 아니라 같은 자료는 같은 그림이다.
    const a = i * 2.399963;
    const d = 40 + 26 * Math.sqrt(i);
    const cz = 1 - 2 * ((i * 0.618033988749895) % 1);
    const sn = Math.sqrt(Math.max(0, 1 - cz * cz));
    node.x = Math.cos(a) * sn * d;
    node.y = Math.sin(a) * sn * d;
    node.z = cz * d;
    node.vx = 0;
    node.vy = 0;
    node.vz = 0;
    nodes.push(node);
  }
  // 절반은 중심에 붙는다
  for (let i = 1; i < n / 2; i++) edges.push({ s: 'n0', t: `n${i}`, kind: 'edge' });
  // 나머지는 자기들끼리 사슬
  for (let i = Math.floor(n / 2); i < n - 1; i++) edges.push({ s: `n${i}`, t: `n${i + 1}`, kind: 'edge' });
  return { nodes, edges };
}

function run(sim, ticks = 400) {
  for (let i = 0; i < ticks; i++) sim.tick();
}

// 3차원 거리. 2D 의 Math.hypot(dx, dy) 자리다.
function dist3(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
}

console.log('\n배치 (d3-force-3d)');

// --- 좌표가 성하다 ------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  run(sim);
  const bad = nodes.filter((n) => !['x', 'y', 'z'].every((c) => Number.isFinite(n[c])));
  ok('400틱 뒤에도 세 축 좌표가 모두 유한하다', bad.length === 0, `${bad.length}개가 NaN/Infinity`);
  const flat = nodes.every((n) => Math.abs(n.z) < 1e-6);
  ok('그래프가 3차원으로 퍼진다 (한 평면에 눕지 않는다)', !flat);
}

// --- 식는다 -------------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  const a0 = sim.alpha();
  run(sim);
  const a1 = sim.alpha();
  ok('시뮬레이션이 식는다', a1 < a0 * 0.2, `${a0.toFixed(3)} → ${a1.toFixed(3)}`);

  // 식은 뒤에는 노드가 사실상 멈춰 있어야 한다 — 안 멈추면 화면이 떤다
  const before = nodes.map((n) => ({ x: n.x, y: n.y, z: n.z }));
  run(sim, 30);
  const moved = Math.max(...nodes.map((n, i) => dist3(n, before[i])));
  ok('식은 뒤 30틱에 거의 안 움직인다', moved < 1.0, `최대 ${moved.toFixed(2)}px`);
}

// --- 중심이 원점을 지킨다 -----------------------------------------------
// 2D 에서는 '화면 가운데(w/2, h/2) 120px 안'이었다. 3D 에서 화면 가운데는
// **원점**이다 — 카메라가 바라보는 자리라 창이 커져도 그대로다.
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  run(sim);
  const c = nodes[0];
  const off = Math.hypot(c.x, c.y, c.z);
  ok('중심 노드가 원점 근처에 남는다', off < 120, `${off.toFixed(0)} 벗어남`);
  // 그래프 전체의 무게중심도 원점 언저리에 있어야 카메라 맞춤이 헛돌지 않는다
  const mid = ['x', 'y', 'z'].map((k) => nodes.reduce((a, n) => a + n[k], 0) / nodes.length);
  ok('그래프가 원점 둘레에 머문다', Math.hypot(...mid) < 120, mid.map((v) => v.toFixed(0)).join(','));
}

// --- 겹치지 않는다 ------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  run(sim);
  let worst = Infinity;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const gap = dist3(nodes[i], nodes[j]) - nodes[i].r - nodes[j].r;
      worst = Math.min(worst, gap);
    }
  }
  ok('노드가 서로 파고들지 않는다', worst > -1, `가장 가까운 쌍이 ${worst.toFixed(1)}px`);
}

// --- 이어진 것이 더 가깝다 ----------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  run(sim);
  const linked = new Set(edges.map((e) => `${e.s}|${e.t}`));
  let near = 0; let nearN = 0; let far = 0; let farN = 0;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const d = dist3(nodes[i], nodes[j]);
      const isLinked = linked.has(`${nodes[i].id}|${nodes[j].id}`) || linked.has(`${nodes[j].id}|${nodes[i].id}`);
      if (isLinked) { near += d; nearN++; } else { far += d; farN++; }
    }
  }
  ok('이어진 쌍이 안 이어진 쌍보다 가깝다', near / nearN < far / farN,
     `이어짐 ${(near / nearN).toFixed(0)}px vs 아님 ${(far / farN).toFixed(0)}px`);
  ok('byId 로 찾은 노드가 시뮬레이션 노드와 같은 객체다', byId.get('n0') === nodes[0]);
}

// --- same_as 는 바짝 붙는다 ---------------------------------------------
{
  const nodes = ['a', 'b', 'c'].map((id, i) => {
    const n = { id, label: id, type: 'person', group: 'actor', degree: 1 };
    n.r = nodeRadius(n);
    n.x = i * 200; n.y = 0; n.z = 0; n.vx = 0; n.vy = 0; n.vz = 0;
    return n;
  });
  const edges = [
    { s: 'a', t: 'b', source: 'a', target: 'b', kind: 'same_as' },
    { s: 'b', t: 'c', source: 'b', target: 'c', kind: 'edge' },
  ];
  const sim = buildSimulation({ nodes, edges, center: 'a' });
  run(sim);
  const [a, b, c] = nodes;
  const same = dist3(a, b);
  const plain = dist3(b, c);
  ok('same_as 로 묶인 쌍이 보통 엣지보다 바짝 붙는다', same < plain, `${same.toFixed(0)} vs ${plain.toFixed(0)}`);
}

// --- 고정한 노드는 안 움직인다 (드래그) --------------------------------
{
  const { nodes, edges } = sampleGraph(20);
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0' });
  const pinned = nodes[5];
  pinned.fx = 700;
  pinned.fy = 100;
  pinned.fz = -50;
  run(sim, 200);
  ok('fx/fy/fz 로 못박은 노드는 그 자리에 있다 (드래그)',
     Math.abs(pinned.x - 700) < 0.001 && Math.abs(pinned.y - 100) < 0.001 && Math.abs(pinned.z + 50) < 0.001,
     `(${pinned.x.toFixed(1)}, ${pinned.y.toFixed(1)}, ${pinned.z.toFixed(1)})`);
}

// --- 3D 엔진에 꽂는 힘이 여기서 잰 그 힘이다 ----------------------------
// 화면(graph-view.js `_applyForces`)은 `buildForces` 가 만든 것을
// `fg.d3Force(이름, 힘)` 으로 꽂는다. 이름이 하나라도 빠지면 라이브러리
// 기본 힘이 남아 화면만 다른 배치가 된다.
{
  const F = buildForces({ center: 'n0' });
  ok('힘 한 벌이 여섯 자리를 다 채운다',
     ['charge', 'collide', 'link', 'x', 'y', 'z'].every((k) => typeof F[k] === 'function'),
     Object.keys(F).join(','));
  ok('중심 노드가 더 세게 끌린다',
     F.x.strength()({ id: 'n0' }) > F.x.strength()({ id: 'n9' }));
  ok('세 축의 끌림이 같다',
     F.x.strength()({ id: 'n9' }) === F.z.strength()({ id: 'n9' }));
}

// --- 반지름 ------------------------------------------------------------
{
  ok('뼈대(frame) 노드가 더 작다',
     nodeRadius({ group: 'frame', degree: 4 }) < nodeRadius({ group: 'actor', degree: 4 }));
  ok('차수가 커도 반지름은 묶여 있다', nodeRadius({ group: 'actor', degree: 100000 }) <= 17);
}

// --- 연표: 축과 라벨이 같은 자를 쓴다 -----------------------------------
//
// 임진왜란처럼 한 해에 사건이 수십이면 라벨을 겹칠 수 없다. 예전에는
// 라벨을 밀어냈고, 그러면 밀린 라벨만 제 해를 떠나 왼쪽 재위 띠와 갈라졌다
// (1597년 전투들이 효종 1649~1659 막대 옆에 섰다). 지금은 몰린 해가
// 늘어나므로 어긋남이 0 이어야 한다.
{
  const marks = [];
  for (let y = 1100; y < 1592; y += 6) marks.push({ year: y, label: `사건${y}`, date: `${y}-01-01` });
  for (let i = 0; i < 38; i++) marks.push({ year: 1592, label: `전투${i}`, date: `1592-${String(i % 12 + 1).padStart(2, '0')}-01` });
  for (let y = 1600; y <= 1980; y += 6) marks.push({ year: y, label: `사건${y}`, date: `${y}-01-01` });

  const from = 1097;
  const to = 1997;
  const scale = buildScale(sortMarks(marks), { from, to, base: (700 - 18 - 64) * 16 });
  const place = placeMarks(sortMarks(marks), scale);
  const yOf = (year) => scale.pos[year - from];

  // 재위 띠가 쓰는 자와 라벨이 쓰는 자가 같다: 라벨은 제 해의 칸 안에 선다.
  const stray = place.filter((p) => p.y < yOf(p.m.year) - 0.001 || p.y >= yOf(p.m.year + 1) - 0.001);
  ok('라벨은 언제나 제 해의 칸 안에 선다', stray.length === 0,
     stray.length ? `${stray[0].m.label} ${stray[0].m.year}년이 칸 밖` : '');

  // 몰린 해 앞뒤는 그대로다 — 1592년이 삼켜서는 안 된다.
  ok('몰린 해가 이웃한 해를 밀어내지 않는다',
     Math.abs(yOf(1591) - yOf(1590) - (yOf(1502) - yOf(1501))) < 0.001);

  const gaps = place.slice(1).map((p, i) => p.y - place[i].y);
  ok('라벨끼리 30px 아래로 붙지 않는다', Math.min(...gaps) >= 30 - 0.001,
     `최소 ${Math.min(...gaps).toFixed(1)}px`);

  ok('마지막 라벨이 연표 안에 있다', place[place.length - 1].y <= scale.H - 64 + 0.001);

  // 빈 구간은 비례를 지킨다 — 100년이 1년처럼 보이면 연표가 아니다.
  ok('사건 없는 100년이 사건 하나 있는 해보다 길다',
     yOf(1300) - yOf(1200) > yOf(1101) - yOf(1100));

  // 한 해가 늘어나면 그 안의 차례가 시간 순으로 읽힌다.
  const y92 = place.filter((p) => p.m.year === 1592);
  ok('같은 해는 날짜 순으로 선다',
     y92.every((p, i) => i === 0 || y92[i - 1].m.date <= p.m.date));
}

// 상한에 걸려도 라벨 자리는 줄지 않는다 — 깎이는 것은 빈 해의 몫이다.
{
  const marks = [];
  for (let y = -2333; y <= 1980; y += 2) marks.push({ year: y, label: `${y}`, date: '' });
  const scale = buildScale(sortMarks(marks), { from: -2336, to: 1983, base: (700 - 82) * 16 });
  const place = placeMarks(sortMarks(marks), scale);
  const gaps = place.slice(1).map((p, i) => p.y - place[i].y);
  ok('MAX_HEIGHT 에 걸려도 라벨은 겹치지 않는다', Math.min(...gaps) >= 30 - 0.001,
     `최소 ${Math.min(...gaps).toFixed(1)}px`);
  // 라벨 자리는 못 깎으므로 상한을 넘을 수는 있다. 깎이는 것은 빈 해의
  // 몫이고, 남은 높이가 라벨 자리(N x GAP)뿐이면 더 줄일 데가 없다.
  ok('빈 해의 몫이 0 까지 깎인다', scale.H <= marks.length * 30 + 82 + 0.5,
     `${scale.H.toFixed(0)}px, 라벨 자리만 ${marks.length * 30 + 82}px`);
}

// --- 띠의 칩: 왕과 대통령을 따로 센다 ------------------------------------
// 1948년 뒤에는 대통령이 같은 띠에 선다. 칩이 '왕 27' 로만 세면 대통령
// 14명이 왕으로 세어진다. 없는 쪽은 적지 않는다 — 조선 그래프에 '대통령 0'
// 이 뜨면 안 된다.
{
  const kings = Array.from({ length: 3 }, (_, i) => ({ id: `k${i}`, kind: 'monarch' }));
  const presidents = Array.from({ length: 2 }, (_, i) => ({ id: `p${i}`, kind: 'president' }));
  ok('왕만 있으면 왕만 센다', seatCount(kings) === '왕 3', seatCount(kings));
  ok('둘 다 있으면 따로 센다', seatCount([...kings, ...presidents]) === '왕 3 · 대통령 2',
     seatCount([...kings, ...presidents]));
  ok('대통령만 있으면 대통령만 센다', seatCount(presidents) === '대통령 2');
  // 종류를 안 적은 예전 데이터는 왕이다
  ok('종류가 없으면 왕으로 센다', seatCount([{ id: 'x' }]) === '왕 1');
}

// --- 인물은 생년 자리에 '탄생'을 달고 선다 ---------------------------------
// 이름만 찍으면 그 해에 무엇을 했다는 것처럼 읽힌다. 띠의 '사망'과 같은
// 꼴이다. 다만 날짜 없이 이어진 사건으로 자리만 가늠한 인물에게는 붙이지
// 않는다 — 그 해는 생년이 아니다.
{
  ok('생년에 선 인물은 탄생을 단다',
     markName({ label: '세종', type: 'person', group: 'actor', year: 1397, date: '1397-05-15' }) === '세종 탄생');
  ok('연도만 아는 생년도 탄생이다',
     markName({ label: '이순신', type: 'person', group: 'actor', year: 1545, date: '1545' }) === '이순신 탄생');
  ok('기원전 생년도 탄생이다',
     markName({ label: '주몽', type: 'person', group: 'actor', year: -58, date: '-0058-01-01' }) === '주몽 탄생');
  ok('자리만 가늠한 인물에는 붙이지 않는다',
     markName({ label: '서장옥', type: 'person', group: 'actor', year: 1894, date: '' }) === '서장옥');
  // 나라는 첫 해에 건국을 단다 — 서버가 나라라고 표식한 것만.
  ok('나라는 건국을 단다',
     markName({ label: '조선', type: 'org', group: 'actor', year: 1392, date: '1392-08-13', founded: true }) === '조선건국');
  ok('고른 나라 자신도 건국이다',
     markName({ label: '대한제국', type: 'org', group: 'actor', year: 1897, date: '1897-10-12', kind: 'self', founded: true }) === '대한제국건국');
  ok('표식 없는 단체에는 붙이지 않는다',
     markName({ label: '집현전', type: 'org', group: 'actor', year: 1420, date: '1420' }) === '집현전');
  ok('연도가 날짜와 다르면 붙이지 않는다',
     markName({ label: '서장옥', type: 'person', group: 'actor', year: 1894, date: '1900-01-01' }) === '서장옥');
  ok('사건에는 붙이지 않는다',
     markName({ label: '임진왜란', type: 'event', group: 'event', year: 1592, date: '1592-04-13' }) === '임진왜란');
}

// --- 연도 칸: 아는 해를 지우지 않는다 --------------------------------------
// 같은 해의 뒤따르는 줄에는 달을 적어 그 안의 차례를 설명한다. 달을 모르면
// 비우는 것이 아니라 해를 흐리게 되풀이한다 — 비우면 그 줄만 '연도 미상'
// 으로 읽힌다 (실측: 1380년의 진포 해전 다음에 선 황산대첩).
{
  const a = { year: 1380, date: '1380', label: '진포 해전' };
  const b = { year: 1380, date: '1380', label: '황산대첩' };
  ok('그 해의 첫 줄에는 해를 적는다',
     yearCell(a, null).text === '1380' && yearCell(a, null).repeat === false);
  ok('달을 모르는 뒷줄은 비우지 않고 해를 되풀이한다',
     yearCell(b, a).text === '1380' && yearCell(b, a).repeat === true);
  ok('달을 아는 뒷줄에는 달을 적는다',
     yearCell({ year: 1592, date: '1592-07-08' }, { year: 1592, date: '1592-04-13' }).text === '7월');
  ok('해가 바뀌면 다시 해를 적는다',
     yearCell({ year: 1381, date: '1381-03' }, a).text === '1381');
  ok('기원전은 접두어를 줄여 적는다',
     yearCell({ year: -57, date: '-0057' }, { year: -57, date: '-0057' }).text === '전57');
}

// --- 연도는 달보다 위에 선다 (2026-09-08 지적) ------------------------------
// '4월' 밑의 '1998' 은 해가 거기서 다시 시작하는 것처럼 읽힌다. 달을 적은
// 뒤의 줄은 해를 되풀이하지 않고 비운다 — 그 해의 첫 줄이 이미 해를 적었다.
{
  const cells = yearCells([
    { year: 1998, date: '1998-04-24', label: '공연' },
    { year: 1998, date: '1998-04-24', label: '티켓' },
    { year: 1998, date: '1998', label: '친구' },
    { year: 1999, date: '1999', label: '이사' },
  ]).map((c) => c.text);
  ok('첫 줄은 해, 다음은 달, 달 뒤의 모르는 줄은 빈다',
     cells.join('|') === '1998|4월||1999', cells.join('|'));
  const none = yearCells([
    { year: 1380, date: '1380', label: '진포 해전' },
    { year: 1380, date: '1380', label: '황산대첩' },
  ]).map((c) => c.text);
  ok('달이 하나도 없는 해는 그대로 해를 되풀이한다', none.join('|') === '1380|1380', none.join('|'));
  ok('해와 어긋나는 날짜의 달은 적지 않는다',
     yearCell({ year: 1997, date: '1998-04-24' }, { year: 1997, date: '1997' }).text === '1997');
}

// 원인은 결과보다 위에 선다. 결과의 거친 날짜(연도만)가 원인의 날짜를
// 품으면 원인 바로 뒤에 세운다 — 병자호란(12월 9일)이 공석신주사건(1636)
// 아래에 섰던 것 (2026-09-05 지적).
{
  const self = { id: 's', kind: 'self', year: 1636, date: '1636', label: '공석신주사건' };
  const cause = { id: 'c', kind: 'near', year: 1636, date: '1636-12-09', label: '병자호란', rel: { type: 'caused', dir: 'in' } };
  const other = { id: 'o', kind: 'anchor', year: 1636, date: '1636-03', label: '다른 일' };
  const order = sortMarks([self, other, cause]).map((m) => m.id);
  ok('연도만 아는 결과는 그 해의 원인 바로 뒤에 선다', order.join() === 'o,c,s', order.join());
  // 고른 노드가 원인이고 이웃이 거친 날짜의 결과일 때도 같다
  const self2 = { id: 's', kind: 'self', year: 1907, date: '1907-08-01', label: '군대해산' };
  const effect = { id: 'e', kind: 'near', year: 1907, date: '1907', label: '정미의병', rel: { type: 'caused', dir: 'out' } };
  const order2 = sortMarks([effect, self2]).map((m) => m.id);
  ok('연도만 아는 결과 이웃은 원인인 고른 노드 뒤에 선다', order2.join() === 's,e', order2.join());
  // 같은 날이면 원인이 먼저
  const same = { id: 'e', kind: 'near', year: 1907, date: '1907-08-01', label: '남대문 전투', rel: { type: 'caused', dir: 'out' } };
  ok('같은 날이면 원인이 먼저다', sortMarks([same, self2]).map((m) => m.id).join() === 's,e');
  // 인과가 아닌 이웃은 날짜 순 그대로
  const plain = { id: 'p', kind: 'near', year: 1636, date: '1636-12-09', label: '남한산성', rel: { type: 'took_place_in', dir: 'out' } };
  ok('인과가 아니면 거친 날짜는 여전히 앞이다', sortMarks([self, plain]).map((m) => m.id).join() === 's,p');
  ok('거친 날짜가 고운 날짜를 품는다', dateContains('1636', '1636-12-09') && dateContains('1920-10', '1920-10-21')
     && dateContains('1907-08-01', '1907-08-01') && !dateContains('1636-1', '1636-12-09') && !dateContains('1637', '1636-12'));
}

// 고른 노드가 끼지 않은 쌍도 원인이 먼저다. 서버가 마크들 사이의 인과를
// [원인 id, 결과 id] 로 보내 준다 (2026-09-08 지적: 한일병합과 무단통치는
// 같은 날 1910-08-29 이라 가나다로 갈렸고, 을사조약(1905-11-17)은 그
// 결과인 애국계몽운동(1905) 아래에 섰다).
{
  const self = { id: 's', kind: 'self', year: 1905, date: '1905-11-17', label: '고른 것' };
  const a = { id: 'a', kind: 'anchor', year: 1910, date: '1910-08-29', label: '한일병합' };
  const b = { id: 'b', kind: 'anchor', year: 1910, date: '1910-08-29', label: '무단통치' };
  const order = sortMarks([b, a, self], [['a', 'b']]).map((m) => m.id);
  ok('둘 다 뼈대여도 같은 날의 원인이 먼저다', order.join() === 's,a,b', order.join());
  ok('인과를 안 주면 날짜·가나다 순 그대로',
     sortMarks([b, a, self]).map((m) => m.id).join() === 's,b,a');

  const c = { id: 'c', kind: 'anchor', year: 1905, date: '1905-11-17', label: '을사조약' };
  const e = { id: 'e', kind: 'anchor', year: 1905, date: '1905', label: '애국계몽운동' };
  const f = { id: 'f', kind: 'anchor', year: 1905, date: '1905-01', label: '다른 일' };
  const o2 = sortMarks([e, f, c], [['c', 'e']]).map((m) => m.id);
  ok('연도만 아는 뼈대 결과도 원인 뒤에 선다', o2.join() === 'f,c,e', o2.join());

  // 날짜가 서로를 품지 않으면 날짜가 이긴다 — 화면이 자료의 날짜를 뒤집지
  // 않는다 (그것은 chronology 가 잡을 일이다).
  const late = { id: 'l', kind: 'anchor', year: 1636, date: '1636-12-09', label: '늦은 원인' };
  const early = { id: 'r', kind: 'anchor', year: 1636, date: '1636-03-01', label: '이른 결과' };
  ok('날짜가 서로를 안 품으면 날짜 순 그대로',
     sortMarks([late, early], [['l', 'r']]).map((m) => m.id).join() === 'r,l');

  // 순환 — 진주농민봉기와 임술민란은 서로를 원인으로 물고 둘 다 1862년이다.
  const p1 = { id: 'p', kind: 'anchor', year: 1862, date: '1862', label: '임술민란' };
  const p2 = { id: 'q', kind: 'anchor', year: 1862, date: '1862', label: '진주농민봉기' };
  const p3 = { id: 'z', kind: 'anchor', year: 1862, date: '1862', label: '평안 소요' };
  const cyc = sortMarks([p3, p2, p1], [['p', 'q'], ['q', 'p'], ['p', 'z']]).map((m) => m.id);
  ok('순환이 있어도 모든 마크가 한 번씩 선다', cyc.length === 3 && new Set(cyc).size === 3, cyc.join());
  ok('순환에서도 풀 수 있는 차례는 지킨다', cyc.indexOf('p') < cyc.indexOf('z'), cyc.join());
}

// 날짜를 모르는 마크는 '그 해 어딘가'이지 '그 해 첫날'이 아니다. 연표는
// 연도 노드에서 해만 빌려 세우고 date 가 빈 문자열이라, 그 해의 어떤
// 원인보다도 위에 섰다 (2026-09-08 지적: 함흥차사 아래에 그 원인인
// 왕자의 난(1398-08-26)이 섰다).
{
  const cause = { id: 'w', kind: 'anchor', year: 1398, date: '1398-08-26', label: '제1차 왕자의 난' };
  const nodate = { id: 'h', kind: 'anchor', year: 1398, date: '', label: '함흥차사' };
  const order = sortMarks([nodate, cause], [['w', 'h']]).map((m) => m.id);
  ok('날짜를 모르는 결과도 원인 뒤에 선다', order.join() === 'w,h', order.join());
  ok('빈 날짜는 무엇이든 품는다', dateContains('', '1398-08-26') && dateContains('', ''));
  ok('인과를 모르면 날짜 없는 것이 여전히 앞이다',
     sortMarks([nodate, cause]).map((m) => m.id).join() === 'h,w');
  // 둘 다 날짜가 없어도 인과는 안다 (송유진 -> 송유진의 난)
  const a0 = { id: 'a', kind: 'anchor', year: 1594, date: '', label: '송유진' };
  const b0 = { id: 'b', kind: 'anchor', year: 1594, date: '', label: '송유진의 난' };
  ok('둘 다 날짜가 없어도 원인이 먼저다',
     sortMarks([b0, a0], [['a', 'b']]).map((m) => m.id).join() === 'a,b');

  // 단체는 끝난 날이 아니라 **시작한 날**에 선다 — 창립이 곧 결과인 쌍
  // (3·1 운동 -> 북로군정서)도 같은 규칙으로 갈린다.
  const mv = { id: 'm', kind: 'anchor', year: 1919, date: '1919-03-01', label: '3·1 운동' };
  const org = { id: 'g', kind: 'era', year: 1919, date: '1919', label: '북로군정서' };
  ok('단체의 창립이 결과면 원인 아래에 선다',
     sortMarks([org, mv], [['m', 'g']]).map((m) => m.id).join() === 'm,g');
  // 결과의 날짜가 원인보다 분명히 앞서면 끌어내리지 않는다 (청나라 건국 4월)
  const war = { id: 'x', kind: 'anchor', year: 1636, date: '1636-12-09', label: '병자호란' };
  const qing = { id: 'y', kind: 'era', year: 1636, date: '1636-04-11', label: '청나라' };
  ok('원인보다 앞선 것이 분명한 날짜는 인과로 끌어내리지 않는다',
     sortMarks([qing, war], [['x', 'y']]).map((m) => m.id).join() === 'y,x');
}

// 원인은 caused 엣지의 들어오는 쪽이다. 결과(out)와 다른 관계는 잇지 않는다.
// 선은 원인 줄에서 오른쪽으로 나가 꺾여 고른 노드 줄로 돌아온다 — 세로
// 선은 캔버스 오른쪽 여백 안에 서고, 화살촉은 고른 노드 줄에 찍힌다.
{
  ok('caused 의 들어오는 쪽이 원인이다',
     isCause({ rel: { type: 'caused', dir: 'in' } }) === true);
  ok('결과(out)와 다른 관계는 원인이 아니다',
     isCause({ rel: { type: 'caused', dir: 'out' } }) === false
     && isCause({ rel: { type: 'part_of', dir: 'in' } }) === false
     && isCause({}) === false);
  const w = causeWire(100, 160, 252);
  const xR = 252 - CAUSE_WIRE.inset, xS = xR - CAUSE_WIRE.arm;
  ok('선은 원인 줄에서 나가 오른쪽 여백에서 꺾여 고른 노드 줄로 돌아온다',
     w.includes(`M${xS}.0 100.0 H${xR}.0 V160.0 H${xS}.0`));
  ok('화살촉은 고른 노드 줄에 찍힌다', w.includes(`L${xS}.0 160.0`));
  ok('선은 파랗다', w.includes(CAUSE_WIRE.color) && CAUSE_WIRE.color === '#4f93bf');
}

// --- 인과 사슬 조명 (graph-view.js causalReach) ------------------------------
// 2026-09-06 사용자: "노드를 클릭하면 인과관계를 보여주는 그래프를 인과관계
// 엣지를 연결해서 보여줘". 고른 노드에서 caused 엣지를 따라 위·아래로 닿는
// 것이 모두 밝아야 임진왜란 → 후금 → 정묘호란 → 병자호란이 한 조명에 선다.
{
  const c = (s, t) => ({ s, t, type: 'caused' });
  const edges = [
    c('임진왜란', '후금'), c('후금', '정묘호란'), c('정묘호란', '병자호란'), c('병자호란', '정축하성'),
    { s: '인조', t: '병자호란', type: 'participated_in' },   // 인과가 아니다
    c('갑', '을'), c('을', '갑'),                            // 순환
    c('병자호란', '숨김'),
  ];
  const r = causalReach(edges, '병자호란', (e) => e.t !== '숨김');
  ok('원인 쪽으로 세 걸음까지 닿는다', ['정묘호란', '후금', '임진왜란'].every((id) => r.nodes.has(id)), [...r.nodes].join(' '));
  ok('결과 쪽도 닿는다', r.nodes.has('정축하성'));
  ok('인과 아닌 엣지는 따라가지 않는다', !r.nodes.has('인조'));
  ok('필터로 끈 인과는 따라가지 않는다', !r.nodes.has('숨김'));
  ok('사슬 밖 인과는 밝히지 않는다', !r.nodes.has('갑') && !r.nodes.has('을'));
  ok('밝힐 선은 사슬 위의 인과 넷', r.edges.size === 4 && r.edges.has('후금|정묘호란|caused'), [...r.edges].join(' '));
  const loop = causalReach([c('갑', '을'), c('을', '갑')], '갑');
  ok('순환이 있어도 한 번씩만 밟는다', loop.nodes.size === 2 && loop.edges.size === 2);
}

// --- 인과 도면 배치 (graph-view.js causalLayout) -----------------------------
// 2026-09-06 사용자: 이웃 위에 얹은 인과는 "너무 복잡하게 그려지고 있어서
// 아무런 정보값이 없어". 팔란티어 Vertex 의 계층(좌→우)·KeyLines 의 순차
// 배치처럼 원인은 왼쪽 열, 결과는 오른쪽 열에 세운다.
{
  const it = (id, kind, children = []) => ({ id, kind, how: '', as: '', evidence: [], confidence: 0.8, sources: [], children });
  const chain = {
    center: 'BJ',
    causes: [ it('JMH', '배경', [ it('JIN', '배경', [ it('IMJIN', '배경') ]) ]), it('JIN', '원인') ],
    effects: [ it('JCH', '결과'), it('GB', '결과', [ it('X', '영향') ]) ],
    nodes: { BJ: { id: 'BJ', label: '병자호란', type: 'event', start: '1636-12-09' },
             JMH: { id: 'JMH', label: '정묘호란', type: 'event', start: '1627' },
             JIN: { id: 'JIN', label: '후금', type: 'org', start: '1616' },
             IMJIN: { id: 'IMJIN', label: '임진왜란', type: 'event', start: '1592' },
             JCH: { id: 'JCH', label: '정축하성', type: 'event', start: '1637' },
             GB: { id: 'GB', label: '강빈옥사', type: 'event', start: '1646' },
             X: { id: 'X', label: '무엇', type: 'event' } },
  };
  const L = causalLayout(chain);
  const at = (id) => L.nodes.find((n) => n.id === id);
  ok('고른 노드가 0열 한가운데', at('BJ').x === 0 && at('BJ').y === 0 && at('BJ').depth === 0);
  ok('원인은 왼쪽 열, 결과는 오른쪽 열', at('JMH').x < 0 && at('JCH').x > 0 && at('GB').x > 0);
  ok('걸음마다 한 열씩', at('IMJIN').x < at('JIN').x && at('JIN').x < at('JMH').x && at('X').x > at('GB').x);
  ok('두 가지에 나온 노드는 한 번만, 가장 긴 길만큼 왼쪽에', L.nodes.filter((n) => n.id === 'JIN').length === 1 && at('JIN').depth === -2, String(at('JIN').depth));
  ok('열 안은 연도순', at('JCH').y < at('GB').y);
  ok('엣지는 늘 원인 → 결과', L.edges.every((e) => at(e.s).x < at(e.t).x) && L.edges.some((e) => e.s === 'JIN' && e.t === 'BJ'), JSON.stringify(L.edges.map((e) => `${e.s}>${e.t}`)));
  ok('엣지에 종류가 실린다', L.edges.find((e) => e.s === 'JMH' && e.t === 'BJ').label === '배경');
  ok('이름 아래 연도가 선다', at('BJ').names[1] === '1636' && at('X').names.length === 1, JSON.stringify(at('BJ').names));
  ok('원인·결과 수를 센다', L.causes === 3 && L.effects === 3, `${L.causes} ${L.effects}`);
  ok('열 목록은 왼쪽부터', L.depths.join(',') === '-3,-2,-1,0,1,2');
  ok('기원전은 글자로', causalLayout({ center: 'a', causes: [it('b', '원인')], effects: [], nodes: { a: { id: 'a', label: '가', type: 'event', start: '-0057-01-01' }, b: { id: 'b', label: '나', type: 'event' } } }).nodes.find((n) => n.id === 'a').names[1] === '기원전 57');
  ok('인과가 없으면 도면도 없다', causalLayout({ center: 'a', causes: [], effects: [], nodes: {} }) === null);
}

// --- setData 는 same_as 가 있어도 끝까지 간다 ------------------------------
// 명성황후를 검색하면 노드는 120개 실렸는데 조명이 안 들었다 (2026-09-06).
// same_as 묶음을 넣는 줄이 Map 에 .add 를 불러 setData 가 중간에 죽었고,
// center·selected 가 안 잡혀 검색한 노드가 그냥 무리 속 점 하나였다.
// 브라우저 없이 세운다 — 3D 엔진은 Node 에서 안 실리지만(늦게 싣는다) 자료를
// 다루는 일은 그대로 돌아야 한다. 그것이 이 검사가 서 있는 자리다.
console.log('\nsetData 와 same_as');
{
  const noop = () => {};
  const ctx = new Proxy({}, { get: () => noop, set: () => true });
  const canvas = {
    getContext: () => ctx, clientWidth: 800, clientHeight: 600, width: 0, height: 0,
    style: {}, parentElement: {}, addEventListener: noop,
    setPointerCapture: noop, releasePointerCapture: noop,
  };
  const saved = { RO: globalThis.ResizeObserver, raf: globalThis.requestAnimationFrame,
                  caf: globalThis.cancelAnimationFrame, win: globalThis.window };
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = noop;
  globalThis.window = { devicePixelRatio: 1 };
  try {
    const view = new GraphView(canvas);
    const payload = {
      center: 'wd:MS',
      nodes: [
        { id: 'wd:MS', label: '명성황후', type: 'person', group: 'actor', degree: 3 },
        { id: 'wd:JOSEON', label: '조선', type: 'org', group: 'actor', degree: 9 },
        { id: 'kr:period:조선시대', label: '조선시대', type: 'period', group: 'frame', degree: 5 },
      ],
      edges: [{ s: 'wd:MS', t: 'wd:JOSEON', type: 'member_of', label: '소속', conf: 1 }],
      same_as: [{ a: 'wd:JOSEON', b: 'kr:period:조선시대' }],
    };
    let threw = null;
    try { view.setData(payload); } catch (e) { threw = e; }
    ok('same_as 가 있어도 setData 가 죽지 않는다', !threw, String(threw));
    ok('중심이 잡힌다', view.center === 'wd:MS', String(view.center));
    ok('same_as 가 한 줄로 실린다', view.edges.filter((e) => e.kind === 'same_as').length === 1);
    view.select('wd:MS');
    ok('검색한 노드가 고른 노드가 된다', view.selected === 'wd:MS');
    // 같은 자료를 얹어도(merge) same_as 가 두 번 실리지 않는다
    view.setData(payload, { merge: true });
    ok('얹어도 same_as 는 하나', view.edges.filter((e) => e.kind === 'same_as').length === 1);
    view.destroy();
  } finally {
    globalThis.ResizeObserver = saved.RO;
    globalThis.requestAnimationFrame = saved.raf;
    globalThis.cancelAnimationFrame = saved.caf;
    if (saved.win === undefined) delete globalThis.window; else globalThis.window = saved.win;
  }
}

// --- 엔진이 늦게 와도 실어 둔 자료를 잃지 않는다 --------------------------
//
// `3d-force-graph` 는 브라우저에서만 실린다(모듈 맨 위에서 부르면 Node 에서
// window 가 없다고 터진다). 그래서 GraphView 는 엔진을 **늦게** 싣고, 그
// 사이에 들어온 setData·select·setDisplay 는 이 객체 안에 그대로 쌓인다.
// 엔진이 오면(`_attach`) 통째로 옮겨 실어야 한다 — 안 그러면 App 이 만들자마자
// 부르는 setData 가 조용히 사라져 화면이 빈 채로 남는다.
//
// 여기서는 가짜 엔진을 넘겨 그 길을 그대로 밟는다. 부른 것을 다 적어 두므로
// **무엇을 어떻게 걸었는지**(힘 여섯 자리·한국어 이름표·안내 글 끄기)까지 잰다.
console.log('\n엔진 늦게 싣기');
{
  const calls = [];
  const fake = () => new Proxy(function () {}, {
    get: (_t, k) => (...args) => { calls.push([k, ...args]); return fake.self; },
    apply: () => fake.self,
  });
  fake.self = fake();
  class FakeEngine {
    constructor(el, opts) { calls.push(['new', el, opts]); return fake.self; }
  }
  const three = new Proxy({}, {
    get: (_t, k) => class { constructor(...a) { this.args = a; this.children = []; }
      add() {} set() {} copy() {} clone() { return this; }
      distanceTo() { return 300; } project() {} },
  });
  class FakeSprite { constructor(t, h, c) { this.text = t; this.textHeight = h; this.color = c;
    this.scale = { x: 40, y: h, set() {} }; this.position = { set() {} };
    this.material = { opacity: 1 }; } }

  const holder = { clientWidth: 800, clientHeight: 600 };
  const view = new GraphView(holder);
  // 엔진이 오기 **전에** 자료와 설정이 들어온다 (App.load 가 이 차례다)
  view.setData({ center: 'a', nodes: [
    { id: 'a', label: '세종', type: 'person', group: 'actor', degree: 3 },
    { id: 'b', label: '훈민정음', type: 'heritage', group: 'thing', degree: 1 }],
    edges: [{ s: 'a', t: 'b', type: 'created', label: '제작', conf: 1 }] });
  view.select('a');
  view.setDisplay({ nodeScale: 1.5 });
  ok('엔진 없이도 자료가 실린다', view.nodes.length === 2 && view.edges.length === 1);
  ok('엔진 없이도 고른 노드를 든다', view.selected === 'a');

  view._attach(FakeEngine, three, FakeSprite);
  const got = calls.find((c) => c[0] === 'graphData');
  ok('엔진이 오면 실어 둔 자료가 그대로 넘어간다',
     got && got[1].nodes.length === 2 && got[1].links.length === 1, JSON.stringify(got?.[1]?.nodes?.length));
  ok('링크의 양 끝은 아이디로 넘긴다 (힘이 노드로 바꿔 끼운다)',
     got && got[1].links[0].source === 'a' && got[1].links[0].target === 'b');
  const forces = calls.filter((c) => c[0] === 'd3Force').map((c) => c[1]);
  ok('힘 여섯 자리를 다 꽂는다',
     ['charge', 'collide', 'link', 'x', 'y', 'z'].every((k) => forces.includes(k)), forces.join(','));
  ok('라이브러리 기본 가운데 힘은 걷어낸다',
     calls.some((c) => c[0] === 'd3Force' && c[1] === 'center' && c[2] === null));
  // 라이브러리가 내는 안내 글과 툴팁은 영어다 (CLAUDE.md §1)
  ok('영어 안내 글을 끈다', calls.some((c) => c[0] === 'showNavInfo' && c[1] === false));
  const tip = calls.find((c) => c[0] === 'nodeLabel');
  ok('라이브러리 툴팁을 비운다', tip && tip[1]({ label: '세종', name: 'Sejong' }) === '');
  ok('컨테이너 크기를 엔진에 준다', calls.some((c) => c[0] === 'width' && c[1] === 800));

  // **엔진이 배치를 세우기 전에는 되데우지 않는다.**
  //
  // 2026-09-11 실측: `/life.html` 이 통째로 안 그려졌다
  // (`renderer.info.render.frame` 이 1 에서 멎음). `d3ReheatSimulation` 은 그
  // 자리에서 `engineRunning = true` 로 세우는데 배치(`state.layout`)는 자료
  // 소화가 1ms 뒤에 만든다 — 그 사이 프레임이 없는 배치를 짚어 터지고,
  // **터진 렌더 고리는 다음 프레임을 걸지 않는다.** 자료가 엔진보다 먼저 오는
  // 화면에서만 나던 병이라 검사에 그 차례가 없었다. 이제 있다.
  ok('배치가 서기 전에는 되데우지 않는다', !calls.some((c) => c[0] === 'd3ReheatSimulation'));
  view.setForces({ repel: 2 });
  ok('첫 틱 전에는 힘이 바뀌어도 안 데운다', !calls.some((c) => c[0] === 'd3ReheatSimulation'));
  // 엔진이 한 바퀴 돌았다고 알린다 (onEngineTick) — 이제 배치가 있다
  const onTick = calls.find((c) => c[0] === 'onEngineTick');
  ok('틱 신호를 받아 둔다', typeof onTick?.[1] === 'function');
  onTick[1]();
  view.setForces({ repel: 3 });
  ok('배치가 선 뒤에는 되데운다', calls.some((c) => c[0] === 'd3ReheatSimulation'));
  view.destroy();
  ok('걷을 때 그리기부터 세운다 (죽은 상태를 짚지 않게)',
     calls.findIndex((c) => c[0] === 'pauseAnimation') < calls.findIndex((c) => c[0] === '_destructor')
     || !calls.some((c) => c[0] === '_destructor'));
}

// --- 진짜 라이브러리가 우리가 부르는 이름을 다 갖고 있는가 ------------------
//
// 위의 가짜 엔진은 무엇이든 받아 주므로 이름을 틀려도 모른다. 그래서 여기서는
// **진짜 `3d-force-graph`** 를 세워 같은 길(`_attach`)을 밟는다. 캅슐(kapsule)은
// DOM 요소 없이 부르면 그리기를 시작하지 않고 메서드만 단 객체를 준다 — 그래서
// 브라우저 없이도 이름이 맞는지 잴 수 있다. 라이브러리를 올릴 때 이름이 바뀌면
// 여기서 먼저 걸린다 (화면에서는 "…is not a function" 으로 죽는다).
console.log('\n라이브러리 이름 맞추기');
{
  const saved = { doc: globalThis.document, win: globalThis.window };
  const el = () => ({ style: {}, dataset: {}, appendChild() {}, setAttribute() {}, addEventListener() {},
                      classList: { add() {}, remove() {} }, children: [], innerHTML: '' });
  globalThis.document = { createElement: el, createTextNode: (t) => ({ t }), head: el(), body: el(),
                          documentElement: el(), addEventListener() {}, querySelector: () => null };
  // 테마를 읽는 자리(theme.js)가 document.documentElement.dataset 를 본다
  globalThis.window = { addEventListener() {}, devicePixelRatio: 1, document: globalThis.document };
  try {
    const [fgMod, three, textMod] = await Promise.all([
      import('3d-force-graph'), import('three'), import('three-spritetext'),
    ]);
    // 요소를 안 넘기면 캅슐이 그리기를 시작하지 않는다 (메서드만 달린 객체)
    class Probe { constructor() { return fgMod.default(); } }
    const view = new GraphView({ clientWidth: 800, clientHeight: 600 });
    view.setData({ center: 'a',
      nodes: [{ id: 'a', label: '가', type: 'person', group: 'actor', degree: 1 },
        { id: 'b', label: '나', type: 'event', group: 'event', degree: 1 }],
      edges: [{ s: 'a', t: 'b', type: 'caused', label: '원인', conf: 0.8 }] });
    let threw = null;
    try {
      view._attach(Probe, three, textMod.default);
      view.screenAt('a');            // CDP 검증이 노드를 누르는 자리
      view.setDisplay({ nodeScale: 1.2 });
      view.setForces({ repel: 1.5 });
      view.setEdgeFilter(['caused']);
      view.select('a');
    } catch (e) { threw = e; }
    ok('진짜 라이브러리에 우리가 부르는 이름이 다 있다', !threw, String(threw && threw.message));
    view.destroy();
  } catch (e) {
    console.log('    (건너뛴 까닭: ' + e.message + ')');
    ok('3d-force-graph 를 Node 에서 못 세운다 (여기서는 건너뜀)', true, String(e.message));
  } finally {
    if (saved.doc === undefined) delete globalThis.document; else globalThis.document = saved.doc;
    if (saved.win === undefined) delete globalThis.window; else globalThis.window = saved.win;
  }
}

// --- 부호: 굵기 · 파선 · 화살촉 ---------------------------------------------
//
// 3D 로 옮기며 **뜻은 그대로 두고 표현만 옮겼다**. 여기서 재는 것은 그 뜻이다:
// 굵기는 인과만, 파선은 출처의 확실성만, 화살촉은 방향이 뜻인 관계에만.
console.log('\n부호 (굵기 · 파선 · 화살촉)');
{
  const view = new GraphView({ clientWidth: 800, clientHeight: 600 });
  view.setData({
    center: 'me',
    nodes: [{ id: 'me', label: '나', type: 'person', group: 'actor', degree: 3 },
      { id: 'kim', label: '김일권', type: 'person', group: 'actor', degree: 2 },
      { id: 'ev', label: '메탈리카 공연', type: 'event', group: 'event', degree: 1 }],
    // 친구는 두 방향이 다 왔다 — 선은 한 줄이어야 한다.
    edges: [{ s: 'me', t: 'ev', type: 'experienced', label: '관람', conf: 1 },
      { s: 'me', t: 'kim', type: 'friend_of', label: '친구', conf: 1 },
      { s: 'kim', t: 'me', type: 'friend_of', label: '친구', conf: 1 },
      { s: 'kim', t: 'ev', type: 'caused', label: '계기', conf: 0.8 }],
  });
  const at = (type) => view.edges.find((e) => e.type === type);
  ok('방향이 있는 선에만 화살촉이 선다',
     view.arrowLength(at('experienced')) > 0 && view.arrowLength(at('friend_of')) === 0);
  ok('화살촉을 끄면 다 사라진다',
     (view.setDisplay({ arrows: false }), view.arrowLength(at('experienced')) === 0));
  view.setDisplay({ arrows: true });
  // 두 방향이 다 와도 선은 한 줄이다 — 실측: 배우자 네 쌍이 여덟 줄로 겹쳐 있었다.
  ok('대칭 관계는 두 방향이 와도 선 한 줄', view.edges.filter((e) => e.type === 'friend_of').length === 1,
    String(view.edges.filter((e) => e.type === 'friend_of').length));
  ok('대칭 표에 개인 역사의 상호 관계가 다 들어 있다',
    ['met', 'friend_of', 'worked_with', 'schoolmate', 'shared_with', 'overlapped', 'spouse_of', 'same_as']
      .every((t) => MUTUAL.has(t)));
  // 대칭이지만 선 이름이 도착 쪽을 부르는 말이라('나 → 나형철 · 형') 방향에 뜻이 있다.
  // 라벨이 '다음'인 related_to 도 앞뒤가 있다 (LABEL_DIR_HEAD).
  ok('역할이 도착을 부르는 관계와 인과는 화살촉을 지킨다',
    !MUTUAL.has('relative_of') && !MUTUAL.has('related_to') && !MUTUAL.has('caused')
    && !MUTUAL.has('participated_in') && !MUTUAL.has('experienced'));

  // **굵기는 인과 하나만 진다.** 2D 에서는 가리킨 선도 굵어졌지만 3D 에서는
  // 조명이 밝기로 말한다 — 한 부호에 뜻 하나.
  ok('인과가 다른 관계보다 굵다', view.edgeWidth(at('caused')) > view.edgeWidth(at('experienced')));
  view.hover = 'me';
  ok('가리켜도 굵기는 그대로다', view.edgeWidth(at('experienced')) === view.edgeWidth(at('friend_of')));
  ok('가리키면 밝기가 갈린다',
     view.edgeColor(at('experienced')) !== view.edgeColor(at('caused')),
     `${view.edgeColor(at('experienced'))} vs ${view.edgeColor(at('caused'))}`);
  view.hover = null;
  ok('조명 밖 노드는 흐려진다 (색상은 그대로, 알파만)',
     withAlpha('#3d84f5', 0.16) === 'rgba(61,132,245,0.16)', withAlpha('#3d84f5', 0.16));
  // 선 굵기 배율은 굵기에 곱해진다 (설정의 '표시' 절)
  const w0 = view.edgeWidth(at('experienced'));
  view.setDisplay({ lineScale: 2 });
  ok('선 굵기 배율이 그대로 먹는다', Math.abs(view.edgeWidth(at('experienced')) - w0 * 2) < 1e-9);
  view.setDisplay({ lineScale: 1 });
  ok('굵기는 0 이 되지 않는다 (0 이면 관이 실이 되어 무늬를 못 싣는다)',
     (view.setDisplay({ lineScale: 0.01 }), view.edgeWidth(at('experienced')) > 0));
  view.setDisplay({ lineScale: 1 });
  view.destroy();
}

// --- 카메라가 노드 구름을 화면에 꽉 채운다 ---------------------------------
//
// 2026-09-11 실측: 반지름 650 짜리 구름에 카메라가 2308 에 서서 그래프가
// 1084×737 화면의 가로 350px 만 썼다 (노드가 2~6px 이라 '크기 = 차수'가 안
// 읽혔다). 라이브러리의 `zoomToFit` 은 노드에 붙인 이름표·링까지 상자에 넣고
// 상자의 긴 변을 `atan` 으로 나눠 늘 멀찍이 선다. 그래서 우리가 직접 잰다.
// 여기서는 **진짜 three 카메라**로 맞춘 뒤 노드를 화면에 찍어 본다.
console.log('\n카메라 맞춤 (노드 구름이 화면을 채운다)');
{
  const W = 1084;
  const H = 737;
  const PAD = 90;                       // graph-view.js FIT_PAD
  try {
    const three = await import('three');
    const cam = new three.PerspectiveCamera(50, W / H, 1, 20000);
    cam.position.set(0, 0, 1200);
    cam.lookAt(0, 0, 0);
    cam.updateMatrixWorld();
    let seen = null;
    let fg;
    const impl = {
      camera: () => cam,
      cameraPosition: (pos, look) => { seen = { pos, look }; return fg; },
    };
    fg = new Proxy(impl, { get: (t, k) => (k in t ? t[k] : () => fg) });
    class Probe { constructor() { return fg; } }
    // 글자를 굽는 일만 빼고 진짜 스프라이트다 (자리·크기·보임은 진짜로 잰다)
    class FakeSprite extends three.Sprite {
      constructor(t, h, c) {
        super();
        this.text = t; this.textHeight = h; this.color = c;
        this.scale.set(h * 3, h, 1);   // 가로세로 비 3:1 인 글자 상자
      }
    }
    // 상태 링은 진짜 three 스프라이트라 캔버스를 하나 굽는다
    const ctx2d = { fillRect() {}, beginPath() {}, arc() {}, stroke() {}, fillText() {},
                    measureText: () => ({ width: 10 }), translate() {}, save() {}, restore() {} };
    const savedDoc = globalThis.document;
    globalThis.document = {
      createElement: () => ({ width: 0, height: 0, getContext: () => ctx2d }),
      documentElement: { dataset: {} },   // theme.js 가 테마를 여기서 읽는다
    };
    const view = new GraphView({ clientWidth: W, clientHeight: H });
    // 실측과 같은 크기의 구름 — 원점 둘레 반지름 650
    const nodes = [];
    for (let i = 0; i < 120; i++) {
      nodes.push({ id: `n${i}`, label: `노드${i}`, type: 'event', group: 'event', degree: 2 });
    }
    view.setData({ center: 'n0', nodes, edges: [] });
    view._attach(Probe, three, FakeSprite);
    let k = 0;
    for (const n of view.nodes) {                 // 공 껍질 위에 고르게
      const a = k * 2.399963;
      const cz = 1 - 2 * ((k * 0.618033988749895) % 1);
      const sn = Math.sqrt(Math.max(0, 1 - cz * cz));
      n.x = Math.cos(a) * sn * 650; n.y = Math.sin(a) * sn * 650; n.z = cz * 650;
      k++;
    }
    view.autoFit = true;
    view._fit(0);
    ok('카메라를 옮긴다', Boolean(seen), String(seen));

    // 맞춘 자리에 카메라를 세우고 노드를 화면에 찍어 본다
    cam.position.set(seen.pos.x, seen.pos.y, seen.pos.z);
    cam.lookAt(seen.look.x, seen.look.y, seen.look.z);
    cam.updateMatrixWorld();
    const V = new three.Vector3();
    const perWorld = H / (2 * Math.tan((50 * Math.PI) / 360));
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const n of view.nodes) {
      V.set(n.x, n.y, n.z);
      const dist = V.distanceTo(cam.position);
      V.project(cam);
      const rpx = (n.r || 6) * perWorld / dist;
      const sx = (V.x * 0.5 + 0.5) * W;
      const sy = (-V.y * 0.5 + 0.5) * H;
      left = Math.min(left, sx - rpx); right = Math.max(right, sx + rpx);
      top = Math.min(top, sy - rpx); bottom = Math.max(bottom, sy + rpx);
    }
    ok('노드가 하나도 화면 밖으로 안 나간다',
       left > -0.5 && right < W + 0.5 && top > -0.5 && bottom < H + 0.5,
       `x[${left.toFixed(0)},${right.toFixed(0)}] y[${top.toFixed(0)},${bottom.toFixed(0)}]`);
    ok('여백 90px 을 지킨다',
       left > PAD - 2 && right < W - PAD + 2 && top > PAD - 2 && bottom < H - PAD + 2,
       `x[${left.toFixed(0)},${right.toFixed(0)}] y[${top.toFixed(0)},${bottom.toFixed(0)}]`);
    // 채운다: 어느 한 쪽은 여백 바로 안까지 닿아야 한다 (2308 짜리 병의 관문)
    const fill = Math.max((right - left) / (W - PAD * 2), (bottom - top) / (H - PAD * 2));
    ok('구름이 여백 안을 꽉 채운다', fill > 0.97, `${(fill * 100).toFixed(0)}%`);
    const used = (bottom - top) / H;
    ok('세로로도 화면의 3분의 2 넘게 쓴다', used > 0.66, `${(used * 100).toFixed(0)}%`);

    // --- 첫 화면에 이름표가 선다 -------------------------------------------
    //
    // 2026-09-11 실측: 열자마자 보이는 그래프에 **글자가 하나도 없었다**
    // (자리다툼은 106개가 이겼는데 거리 문턱에서 전부 0 이 됐다). 이름표가
    // 화면에서 늘 같은 크기가 되게 다시 키우고(2D 의 `/k`), 흐림의 자를 그
    // 그래프가 꽉 차는 거리로 바꿨다.
    for (const n of view.nodes) view._nodeObject(n);   // 라이브러리가 소화할 때 하는 일
    view._placeLabels();
    const lit = view.nodes.filter((n) => view._objs.get(n.id)?.label.visible);
    ok('첫 화면에 이름표가 여럿 선다', lit.length > 10, `${lit.length}개`);
    console.log(`    (노드 ${view.nodes.length} 중 이름표 ${lit.length} · 카메라 ${view._fitDist.toFixed(0)})`);
    ok('겹치는 만큼은 접는다 (전부 세우지 않는다)', lit.length < view.nodes.length,
       `${lit.length}/${view.nodes.length}`);
    const heights = lit.map((n) => {
      const V2 = new three.Vector3(n.x, n.y, n.z);
      const d = V2.distanceTo(cam.position);
      return view._objs.get(n.id).label.scale.y * perWorld / d;
    });
    const off = heights.filter((h) => Math.abs(h - 11) > 0.6 && Math.abs(h - 12.5) > 0.6);
    ok('이름표는 화면에서 늘 같은 크기다 (11px · 초점 12.5px)', off.length === 0,
       `어긋난 것 ${off.length}개 — ${heights.slice(0, 3).map((h) => h.toFixed(1)).join(', ')}`);
    view.destroy();
    if (savedDoc === undefined) delete globalThis.document; else globalThis.document = savedDoc;
  } catch (e) {
    ok('three 를 Node 에서 못 세운다 (여기서는 건너뜀)', false, String(e.message));
  }
}

// --- 이름표는 멀어지면 흐려진다 ---------------------------------------------
// 2D 의 '텍스트 흐림 문턱'을 3D 로 옮긴 것. 자가 배율에서 **카메라 거리**로
// 바뀌었을 뿐, 손잡이(textFade 0~1)의 뜻은 그대로다.
console.log('\n이름표 흐림 (거리)');
{
  // 자는 **그 그래프가 화면에 꽉 차는 거리**다 (절대 거리가 아니다). 그래프마다
  // 크기가 다르고 처음 열리는 거리도 그만큼 다르다 — 절대 거리(1000)를 걸었더니
  // 노드 120개짜리 첫 화면이 2308 에서 열려 이름표가 하나도 안 떴다 (2026-09-11).
  const fit = 1400;
  ok('꽉 찬 거리에서는 늘 또렷하다 (첫 화면)',
     labelAlpha(fit, 0.3, fit) === 1 && labelAlpha(fit, 0, fit) === 1);
  ok('그래프가 커도 첫 화면은 같다', labelAlpha(4000, 0.3, 4000) === 1);
  ok('물러나면 사라진다', labelAlpha(fit * 2, 0.3, fit) === 0);
  ok('그 사이는 서서히', labelAlpha(fit * 1.4, 0.3, fit) > 0 && labelAlpha(fit * 1.4, 0.3, fit) < 1);
  ok('문턱을 올리면 더 가까이 가야 보인다', labelAlpha(fit, 1, fit) < labelAlpha(fit, 0, fit));
  ok('문턱 1 은 절반 거리까지 다가가야 뜬다', labelAlpha(fit * 0.5, 1, fit) > 0);
  ok('문턱 0 은 물러나도 더 오래 버틴다', labelAlpha(fit * 1.4, 0, fit) > labelAlpha(fit * 1.4, 0.3, fit));
}

// --- 재위 띠는 취임한 날에 앉는다 -------------------------------------------
// "해당 대통령의 이름을 취임날에 맞춰서 위치 시켜 달라고" (2026-09-09).
{
  const from = 1960;
  const to = 1990;
  const marks = [];
  for (let y = from; y <= to; y += 1) marks.push({ year: y, label: `${y}`, date: `${y}-01-01` });
  const scale = buildScale(sortMarks(marks), { from, to, base: 4000 });
  // TimelineRail.yOf 와 같은 규칙 — 두 눈금 사이를 소수만큼 나눠 앉힌다.
  const at = (y) => {
    const v = Math.min(Math.max(y, from), to);
    const i = Math.floor(v);
    const a = scale.pos[i - from];
    const f = v - i;
    return (!f || i >= to) ? a : a + (scale.pos[i + 1 - from] - a) * f;
  };

  ok('정수를 주면 예전처럼 그 해의 첫날이다', at(1963) === scale.pos[3]);
  const twelfth = at(1963.96);
  ok('12월은 그 해 칸의 끝에 앉는다',
     twelfth > at(1963) && twelfth < at(1964)
     && twelfth - at(1963) > (at(1964) - at(1963)) * 0.9,
     `${twelfth.toFixed(1)} / ${at(1963).toFixed(1)}~${at(1964).toFixed(1)}`);

  // 박정희의 취임은 1963-12-17 이다. 해로만 앉히면 이름이 1963년 1월에 선다.
  // (그 해에 사건이 하나도 없을 때의 자리 — 소수로 나눈다.)
  const band = reignBand([{
    id: 'wd:Q14356', label: '박정희', position: '대한민국 대통령', kind: 'president',
    start: 1963, end: 1979, at_start: 1963.96, at_end: 1979.818,
    ongoing: false, death: 1979, at_death: 1979.818, birth: 1917,
  }], at, {});
  const top = Number(/top:([\d.]+)px/.exec(band.items)[1]);
  // 화면에 적히는 값은 소수 한 자리로 잘린다 (`toFixed(1)`).
  ok('대통령의 이름이 취임한 날에 선다', Math.abs(top - at(1963.96)) < 0.06,
     `${top.toFixed(1)} vs ${at(1963.96).toFixed(1)}`);
  ok('이름이 취임한 해의 1월에 서지 않는다', top - at(1963) > 1,
     `${(top - at(1963)).toFixed(1)}px`);
  const barY = Number(/tl-reign-bar[^>]*?y="([\d.]+)"/.exec(band.svg)[1]);
  ok('막대도 이름과 같은 날에서 시작한다', Math.abs(barY - top) < 0.06);

  // 날짜를 모르는 띠는 예전 그대로 — 해의 첫날이다.
  const plain = reignBand([{
    id: 'x', label: '아무개', position: '자리', kind: 'monarch',
    start: 1970, end: 1975, ongoing: false, death: null, birth: null,
  }], at, {});
  ok('해 안의 자리를 모르면 그 해의 첫날에 선다',
     Math.abs(Number(/top:([\d.]+)px/.exec(plain.items)[1]) - at(1970)) < 0.06);
}

// --- 사건이 선 해에서는 그 사건들 사이에 앉는다 (`dateRuler`) ------------------
// "이재명 대통령은 2025년 6월에 취임했어 그럼 2025년 6월 오른쪽에 이름을 둬야
// 하는거야" (2026-09-09). 몰린 해는 사건이 한 칸씩 서므로 (`placeMarks`), 해를
// 소수로 고르게 나누면 6월 취임이 4월 사건 옆에 선다.
{
  const from = 2020;
  const to = 2030;
  const marks = [
    { year: 2025, label: '폭설', date: '2025-01-27' },
    { year: 2025, label: '산불', date: '2025-03-22' },
    { year: 2025, label: '유심 해킹', date: '2025-04-18' },
    { year: 2025, label: '태안화력', date: '2025-06-02' },
    { year: 2025, label: '제21대 대통령 선거', date: '2025-06-03' },
    { year: 2025, label: '집중호우', date: '2025-07-16' },
    { year: 2025, label: 'APEC', date: '2025-10-31' },
  ];
  // 빈 해의 몫(rate)이 라벨 간격(GAP 30)보다 작아야 몰린 해가 사건 수만큼
  // 늘어난다 — 실제 연표가 그렇다 (1100년에 9,900px 이면 한 해 9px).
  const scale = buildScale(sortMarks(marks), { from, to, base: 100 });
  const place = placeMarks(sortMarks(marks), scale).map(({ m, y }) => ({ m, ty: y }));
  const yOf = (y) => {
    const v = Math.min(Math.max(y, from), to);
    const i = Math.floor(v);
    const a = scale.pos[i - from];
    const f = v - i;
    return (!f || i >= to) ? a : a + (scale.pos[i + 1 - from] - a) * f;
  };
  const at = dateRuler(place, yOf);
  const yAt = (label) => place.find((p) => p.m.label === label).ty;

  const inaug = at(2025, '2025-06-04');
  ok('취임일은 그 앞 사건과 뒷 사건 사이에 앉는다',
     inaug > yAt('제21대 대통령 선거') && inaug < yAt('집중호우'),
     `${inaug} / 선거 ${yAt('제21대 대통령 선거')} · 호우 ${yAt('집중호우')}`);
  ok('한 사건의 칸에 딱 맞추지 않는다 — 그 사건이 곧 취임인 것처럼 읽힌다',
     inaug !== yAt('집중호우') && inaug !== yAt('제21대 대통령 선거'));
  ok('해를 소수로 고르게 나눈 자리(4월 언저리)와는 다르다',
     Math.abs(inaug - yOf(2025.42)) > 30,
     `${inaug} vs ${yOf(2025.42)}`);
  ok('그 해의 첫 사건보다 앞선 날은 해의 첫 칸이다',
     at(2025, '2025-01-02') === yAt('폭설'));
  ok('그 해의 마지막 사건보다 뒤인 날은 그 아래 반 칸이다',
     at(2025, '2025-12-25') > yAt('APEC') && at(2025, '2025-12-25') < yOf(2026));
  ok('사건이 하나도 없는 해는 소수로 나눈 자리 그대로다',
     at(2023.5, '2023-07-01') === yOf(2023.5));
  ok('날짜를 안 주면 예전처럼 해의 자리다', at(2025) === yOf(2025));

  // 띠도 같은 자를 쓴다.
  const band = reignBand([{
    id: 'wd:Q12612463', label: '이재명', position: '대한민국 대통령', kind: 'president',
    start: 2025, end: 2026, at_start: 2025.42, start_date: '2025-06-04',
    ongoing: true, death: null, birth: 1964,
  }], at, {});
  const top = Number(/top:([\d.]+)px/.exec(band.items)[1]);
  ok('대통령의 이름이 그 해 6월 자리에 선다', Math.abs(top - inaug) < 0.06,
     `${top} vs ${inaug}`);
}

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
