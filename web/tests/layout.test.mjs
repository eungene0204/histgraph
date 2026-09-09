// 배치 검증 — 브라우저 없이 돈다 (d3-force 는 DOM 을 쓰지 않는다).
//
//   node web/tests/layout.test.mjs
//
// 손으로 짠 시뮬레이션을 들어내면서 잃기 쉬운 것들을 잡아둔다: 좌표가
// NaN 이 되는 것, 식지 않는 것, 중심이 가운데를 안 지키는 것, 노드가
// 겹쳐 버리는 것, 이어진 노드가 안 이어진 노드보다 멀어지는 것.
import { buildSimulation, nodeRadius, retarget } from '../src/lib/layout.js';
import { buildScale, placeMarks, sortMarks, seatCount, markName, yearCell, yearCells, isCause, causeWire, reignBand, dateRuler, CAUSE_WIRE, dateContains } from '../src/lib/timeline.js';
import { causalReach, causalLayout, GraphView, MUTUAL } from '../src/lib/graph-view.js';

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
// 캔버스 없이 세우기 위해 브라우저 것들을 흉내낸다 — 그리기는 안 돈다.
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

// --- 같은 캔버스에 다시 세워도 배율이 산다 --------------------------------
// 2026-09-08: 개인 역사 그래프가 잔상으로 뒤덮였다. StrictMode 가 같은
// 캔버스에 GraphView 를 다시 세우면 배킹 크기가 이미 맞아 _resize 가 일찍
// 돌아갔고, 그때 dpr 이 없어 setTransform 에 NaN 이 들어갔다 — 캔버스는
// 변환을 통째로 무시하므로 1배로 그리고, 지우는 자리도 왼쪽 위 1/4 뿐이라
// 나머지에 지난 프레임이 쌓인다.
console.log('\n배율(dpr)');
{
  const noop = () => {};
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_t, k) => (...args) => { calls.push([k, ...args]); },
    set: () => true,
  });
  const canvas = {
    getContext: () => ctx, clientWidth: 800, clientHeight: 600,
    // 이미 2배로 잡혀 있는 캔버스 — 두 번째 GraphView 가 물려받는 자리다.
    width: 1600, height: 1200,
    style: {}, parentElement: {}, addEventListener: noop,
    setPointerCapture: noop, releasePointerCapture: noop,
  };
  const saved = { RO: globalThis.ResizeObserver, raf: globalThis.requestAnimationFrame,
                  caf: globalThis.cancelAnimationFrame, win: globalThis.window };
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = noop;
  globalThis.window = { devicePixelRatio: 2 };
  try {
    const view = new GraphView(canvas);
    ok('크기가 그대로여도 배율을 든다', view.dpr === 2, String(view.dpr));
    calls.length = 0;
    view._draw();
    const t = calls.find((c) => c[0] === 'setTransform');
    ok('변환에 NaN 이 안 간다', t && t.slice(1).every(Number.isFinite), JSON.stringify(t));
    ok('변환이 배율 그대로', t && t[1] === 2 && t[4] === 2, JSON.stringify(t));
    const clear = calls.find((c) => c[0] === 'clearRect');
    ok('지우는 자리가 캔버스 전체', clear && clear[3] * view.dpr >= canvas.width && clear[4] * view.dpr >= canvas.height, JSON.stringify(clear));
    view.destroy();
  } finally {
    globalThis.ResizeObserver = saved.RO;
    globalThis.requestAnimationFrame = saved.raf;
    globalThis.cancelAnimationFrame = saved.caf;
    if (saved.win === undefined) delete globalThis.window; else globalThis.window = saved.win;
  }
}

// --- 대칭 관계에는 화살촉이 없다 -------------------------------------------
// 화살촉은 '누가 누구에게'를 말하는 부호다. 서로 같은 것을 뜻하는 관계(배우자,
// 개인 역사의 친구·같은 학교)에 붙이면 없는 방향을 지어낸다. `closePath` 를 부르는
// 곳은 drawArrow 하나뿐이라 그 횟수가 곧 그려진 화살촉 수다.
console.log('\n화살촉 (대칭 관계)');
{
  const noop = () => {};
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_t, k) => (...args) => {
      calls.push([k, ...args]);
      return k === 'measureText' ? { width: String(args[0] ?? '').length * 7 } : undefined;
    },
    set: () => true,
  });
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
    view.setData({
      center: 'me',
      nodes: [{ id: 'me', label: '나', type: 'person', group: 'actor', degree: 3 },
        { id: 'kim', label: '김일권', type: 'person', group: 'actor', degree: 2 },
        { id: 'ev', label: '메탈리카 공연', type: 'event', group: 'event', degree: 1 }],
      // 친구는 두 방향이 다 왔다 — 선은 한 줄이어야 한다.
      edges: [{ s: 'me', t: 'ev', type: 'experienced', label: '관람', conf: 1 },
        { s: 'me', t: 'kim', type: 'friend_of', label: '친구', conf: 1 },
        { s: 'kim', t: 'me', type: 'friend_of', label: '친구', conf: 1 },
        { s: 'kim', t: 'ev', type: 'experienced', label: '함께', conf: 0.8 }],
    });
    calls.length = 0;
    view._draw();
    const heads = calls.filter((c) => c[0] === 'closePath').length;
    ok('방향이 있는 선에만 화살촉이 선다 (친구 빼고 둘)', heads === 2, `화살촉 ${heads}`);
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
    view.destroy();
  } finally {
    globalThis.ResizeObserver = saved.RO;
    globalThis.requestAnimationFrame = saved.raf;
    globalThis.cancelAnimationFrame = saved.caf;
    if (saved.win === undefined) delete globalThis.window; else globalThis.window = saved.win;
  }
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
