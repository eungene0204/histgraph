// 힘기반 배치 — d3-force 로 돌린다.
//
// 손으로 짠 O(n²) 시뮬레이션이 있던 자리다. 옮긴 이유는 성능이 아니라
// **진동을 계속 손으로 막고 있었기 때문**이다. 1/d² 반발력은 근거리에서
// 강성이 폭발해서, 감쇠 0.82 의 준음함수 오일러가 견디는 한계(≈3.6)를
// 큰 노드 두 개가 18px 안에서 넘겼다. 그걸 MIN_REPEL_DIST 로 잘라 막고
// 있었는데, 같은 문제를 d3 는 forceCollide 로 푼다 — 겹치지 않게 밀되
// 1/d² 을 쓰지 않으니 애초에 강성이 터지지 않는다.
//
// 아래 값들은 옛 계수를 옮겨 온 것이다. 옛 주석에 근거가 남아 있던 것은
// 여기에도 옮겨 적었다.
import {
  forceSimulation, forceManyBody, forceLink, forceCollide, forceX, forceY,
} from 'd3-force';

// 반발이 용수철보다 약하면 그래프가 가운데로 뭉쳐 라벨이 전부 겹친다.
// 큰 노드일수록 더 넓은 자리를 요구한다 — 옛 계수의 (a.r+b.r)*120 자리다.
export const REPEL_BASE = 300;
export const REPEL_PER_RADIUS = 24;

// 800px 밖은 서로 밀 이유가 없다 (옛 코드의 d2 > 640000 컷과 같은 뜻).
export const REPEL_MAX_DIST = 800;

// 같은 실체(same_as)는 붙여 놓는다 — 한 개체가 둘로 보이면 안 된다.
export const SAME_AS_DISTANCE = 34;
export const SAME_AS_STRENGTH = 0.35;
export const LINK_BASE_DISTANCE = 112;
export const LINK_STRENGTH = 0.12;

// 중심 노드는 화면 가운데를 지킨다 — 무엇을 보고 있는지 잃지 않게.
export const CENTER_PULL = 0.06;
export const NODE_PULL = 0.016;

// 옛 코드는 매 틱 vx *= 0.82 였다. d3 의 velocityDecay 는 "깎아내는 비율"
// 이라 1 - 0.82 로 준다.
export const VELOCITY_DECAY = 0.18;

// 옛 코드는 alpha *= 0.985. d3 는 alpha += (target - alpha) * decay 라
// 같은 감쇠가 되려면 0.015 다.
export const ALPHA_DECAY = 0.015;

// 노드 반지름 — 배치와 그리기가 같은 값을 봐야 겹침 판정이 맞는다.
export function nodeRadius(n) {
  const base = n.group === 'frame' ? 4 : 6;
  return base + Math.min(11, Math.sqrt(n.degree || 0) * 1.7);
}

// 배치 하나를 만든다. **시작 상태로 멈춰서 돌려준다** — 틱은 부르는 쪽이
// 돌린다. d3 가 자기 타이머로 돌게 두면 화면 주사율을 따라가는데, 힘
// 계수가 전부 "한 틱당"으로 잡혀 있어서 120Hz 화면에서는 같은 그래프에
// 힘이 두 배로 들어간다. 초당 60틱을 지키는 건 호출부의 일이다.
export function buildSimulation({ nodes, edges, center, width, height }) {
  const cx = width / 2;
  const cy = height / 2;

  const links = edges.filter((e) => e.kind !== 'same_as');
  const sameAs = edges.filter((e) => e.kind === 'same_as');

  const sim = forceSimulation(nodes)
    .velocityDecay(VELOCITY_DECAY)
    .alphaDecay(ALPHA_DECAY)
    .force('charge', forceManyBody()
      .strength((n) => -(REPEL_BASE + (n.r || 0) * REPEL_PER_RADIUS))
      .distanceMax(REPEL_MAX_DIST))
    // 겹침 방지. 옛 MIN_REPEL_DIST 가 하던 일을 대신한다.
    .force('collide', forceCollide().radius((n) => (n.r || 0) + 6).strength(0.7))
    .force('link', forceLink(links)
      .id((n) => n.id)
      .distance((e) => LINK_BASE_DISTANCE + (e.source.r || 0) + (e.target.r || 0))
      .strength(LINK_STRENGTH))
    .force('same', forceLink(sameAs)
      .id((n) => n.id)
      .distance(SAME_AS_DISTANCE)
      .strength(SAME_AS_STRENGTH))
    .force('x', forceX(cx).strength((n) => (n.id === center ? CENTER_PULL : NODE_PULL)))
    .force('y', forceY(cy).strength((n) => (n.id === center ? CENTER_PULL : NODE_PULL)));

  sim.stop();
  return sim;
}

// 화면 크기가 바뀌면 끌어당기는 중심도 따라가야 한다.
export function retarget(sim, { center, width, height }) {
  const fx = sim.force('x');
  const fy = sim.force('y');
  if (fx) fx.x(width / 2).strength((n) => (n.id === center ? CENTER_PULL : NODE_PULL));
  if (fy) fy.y(height / 2).strength((n) => (n.id === center ? CENTER_PULL : NODE_PULL));
}
