// 배치 검증 — 브라우저 없이 돈다 (d3-force 는 DOM 을 쓰지 않는다).
//
//   node web/tests/layout.test.mjs
//
// 손으로 짠 시뮬레이션을 들어내면서 잃기 쉬운 것들을 잡아둔다: 좌표가
// NaN 이 되는 것, 식지 않는 것, 중심이 가운데를 안 지키는 것, 노드가
// 겹쳐 버리는 것, 이어진 노드가 안 이어진 노드보다 멀어지는 것.
import { buildSimulation, nodeRadius, retarget } from '../src/lib/layout.js';
import { buildScale, placeMarks, sortMarks, seatCount, markName, yearCell } from '../src/lib/timeline.js';

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
    // 옛 코드와 같은 황금각 나선으로 뿌린다
    const a = i * 2.399963;
    const d = 40 + 26 * Math.sqrt(i);
    node.x = 400 + Math.cos(a) * d;
    node.y = 300 + Math.sin(a) * d;
    node.vx = 0;
    node.vy = 0;
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

console.log('\n배치 (d3-force)');

// --- 좌표가 성하다 ------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  run(sim);
  const bad = nodes.filter((n) => !Number.isFinite(n.x) || !Number.isFinite(n.y));
  ok('400틱 뒤에도 좌표가 유한하다', bad.length === 0, `${bad.length}개가 NaN/Infinity`);
}

// --- 식는다 -------------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  const a0 = sim.alpha();
  run(sim);
  const a1 = sim.alpha();
  ok('시뮬레이션이 식는다', a1 < a0 * 0.2, `${a0.toFixed(3)} → ${a1.toFixed(3)}`);

  // 식은 뒤에는 노드가 사실상 멈춰 있어야 한다 — 안 멈추면 화면이 떤다
  const before = nodes.map((n) => ({ x: n.x, y: n.y }));
  run(sim, 30);
  const moved = Math.max(...nodes.map((n, i) => Math.hypot(n.x - before[i].x, n.y - before[i].y)));
  ok('식은 뒤 30틱에 거의 안 움직인다', moved < 1.0, `최대 ${moved.toFixed(2)}px`);
}

// --- 중심이 가운데를 지킨다 ---------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  run(sim);
  const c = nodes[0];
  const off = Math.hypot(c.x - 400, c.y - 300);
  ok('중심 노드가 화면 가운데 근처에 남는다', off < 120, `${off.toFixed(0)}px 벗어남`);
}

// --- 겹치지 않는다 ------------------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  run(sim);
  let worst = Infinity;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const gap = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y) - nodes[i].r - nodes[j].r;
      worst = Math.min(worst, gap);
    }
  }
  ok('노드가 서로 파고들지 않는다', worst > -1, `가장 가까운 쌍이 ${worst.toFixed(1)}px`);
}

// --- 이어진 것이 더 가깝다 ----------------------------------------------
{
  const { nodes, edges } = sampleGraph();
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  run(sim);
  const linked = new Set(edges.map((e) => `${e.s}|${e.t}`));
  let near = 0; let nearN = 0; let far = 0; let farN = 0;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
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
    n.x = 400 + i * 200; n.y = 300; n.vx = 0; n.vy = 0;
    return n;
  });
  const edges = [
    { s: 'a', t: 'b', source: 'a', target: 'b', kind: 'same_as' },
    { s: 'b', t: 'c', source: 'b', target: 'c', kind: 'edge' },
  ];
  const sim = buildSimulation({ nodes, edges, center: 'a', width: 800, height: 600 });
  run(sim);
  const [a, b, c] = nodes;
  const same = Math.hypot(a.x - b.x, a.y - b.y);
  const plain = Math.hypot(b.x - c.x, b.y - c.y);
  ok('same_as 로 묶인 쌍이 보통 엣지보다 바짝 붙는다', same < plain, `${same.toFixed(0)}px vs ${plain.toFixed(0)}px`);
}

// --- 고정한 노드는 안 움직인다 (드래그) --------------------------------
{
  const { nodes, edges } = sampleGraph(20);
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  const pinned = nodes[5];
  pinned.fx = 700;
  pinned.fy = 100;
  run(sim, 200);
  ok('fx/fy 로 고정한 노드는 그 자리에 있다',
     Math.abs(pinned.x - 700) < 0.001 && Math.abs(pinned.y - 100) < 0.001,
     `(${pinned.x.toFixed(1)}, ${pinned.y.toFixed(1)})`);
}

// --- 창 크기가 바뀌면 중심도 옮겨간다 -----------------------------------
{
  const { nodes, edges } = sampleGraph(20);
  const sim = buildSimulation({ nodes, edges: edges.map((e) => ({ ...e, source: e.s, target: e.t })), center: 'n0', width: 800, height: 600 });
  run(sim);
  retarget(sim, { center: 'n0', width: 1600, height: 600 });
  sim.alpha(1);
  run(sim, 400);
  const off = Math.abs(nodes[0].x - 800);
  ok('retarget 뒤 중심이 새 가운데를 따라간다', off < 150, `x=${nodes[0].x.toFixed(0)}, 목표 800`);
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

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
