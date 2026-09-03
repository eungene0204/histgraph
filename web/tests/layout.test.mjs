// 배치 검증 — 브라우저 없이 돈다 (d3-force 는 DOM 을 쓰지 않는다).
//
//   node web/tests/layout.test.mjs
//
// 손으로 짠 시뮬레이션을 들어내면서 잃기 쉬운 것들을 잡아둔다: 좌표가
// NaN 이 되는 것, 식지 않는 것, 중심이 가운데를 안 지키는 것, 노드가
// 겹쳐 버리는 것, 이어진 노드가 안 이어진 노드보다 멀어지는 것.
import { buildSimulation, nodeRadius, retarget } from '../src/lib/layout.js';

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

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
