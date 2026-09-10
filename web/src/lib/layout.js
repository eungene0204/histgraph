// 힘기반 배치 — d3-force-3d 로 돌린다.
//
// 손으로 짠 O(n²) 시뮬레이션 → d3-force(2D) → d3-force-3d(3D) 로 두 번
// 옮겨 왔다. 계수는 처음 것을 그대로 들고 왔다. 옛 주석에 근거가 남아 있던
// 것은 여기에도 옮겨 적었다.
//
// **차원만 늘었고 뜻은 그대로다.** 반발·링크 거리·겹침 방지는 3차원 거리로
// 재고, 화면 가운데로 끌던 힘은 **원점**(0,0,0)으로 끈다 — 3D 에서는 카메라가
// 바라보는 자리가 원점이라 그것이 곧 '화면 가운데'다. 그래서 2D 의
// `retarget`(창 크기가 바뀌면 끌어당기는 중심도 옮긴다)은 없어졌다. 창이
// 커져도 원점은 원점이다.
//
// 이 파일은 **브라우저를 모른다.** `3d-force-graph` 는 Node 에서 import 가
// 터지지만 d3-force-3d 는 돌아가므로, 배치 검증(layout.test.mjs)이 여기서
// 만든 것과 **같은 힘**을 Node 에서 직접 돌려 불변식을 잰다.
import {
  forceSimulation, forceManyBody, forceLink, forceCollide, forceX, forceY, forceZ,
} from 'd3-force-3d';

// 반발이 용수철보다 약하면 그래프가 가운데로 뭉쳐 라벨이 전부 겹친다.
// 큰 노드일수록 더 넓은 자리를 요구한다 — 옛 계수의 (a.r+b.r)*120 자리다.
export const REPEL_BASE = 300;
export const REPEL_PER_RADIUS = 24;

// 800 밖은 서로 밀 이유가 없다 (옛 코드의 d2 > 640000 컷과 같은 뜻).
export const REPEL_MAX_DIST = 800;

// 같은 실체(same_as)는 붙여 놓는다 — 한 개체가 둘로 보이면 안 된다.
export const SAME_AS_DISTANCE = 34;
export const SAME_AS_STRENGTH = 0.35;
export const LINK_BASE_DISTANCE = 112;
export const LINK_STRENGTH = 0.12;

// 중심 노드는 원점을 지킨다 — 무엇을 보고 있는지 잃지 않게.
export const CENTER_PULL = 0.06;
export const NODE_PULL = 0.016;

// 옛 코드는 매 틱 vx *= 0.82 였다. d3 의 velocityDecay 는 "깎아내는 비율"
// 이라 1 - 0.82 로 준다.
export const VELOCITY_DECAY = 0.18;

// 옛 코드는 alpha *= 0.985. d3 는 alpha += (target - alpha) * decay 라
// 같은 감쇠가 되려면 0.015 다.
export const ALPHA_DECAY = 0.015;

// **엔진이 스스로 멈추는 자리.** 2D 에서는 우리가 틱을 돌리며 alpha 0.005
// 아래를 안 돌렸다. 3D 엔진(3d-force-graph)은 자기 루프로 도므로 같은 값을
// alphaMin 으로 준다 — 안 주면 식은 뒤에도 영원히 틱이 돈다.
export const ALPHA_MIN = 0.005;

// 노드 반지름 — 배치와 그리기가 같은 값을 봐야 겹침 판정이 맞는다.
// **크기는 차수다** (graph-drawer §4). 뼈대(frame)는 밑동이 작다 — 물러나
// 있어야 하는 것들이다.
export function nodeRadius(n) {
  const base = n.group === 'frame' ? 4 : 6;
  return base + Math.min(11, Math.sqrt(n.degree || 0) * 1.7);
}

// `forces` 는 Obsidian 그래프 설정의 '힘' 절이 주는 배율이다 — 중심 힘·
// 반발 힘·링크 거리. 1 이 위의 기본 계수 그대로다. 계수 자체를 바꾸지
// 않고 곱만 하므로 배치 검증(layout.test.mjs)은 배율 1 로 그대로 돈다.
export const DEFAULT_FORCES = { center: 1, repel: 1, link: 1 };

// 링크 하나의 자연 길이·강도. **same_as 는 다른 자를 쓴다** — 관계가 아니라
// 이음이라 바짝 붙어야 한다. 2D 에서는 힘을 둘로 나눠 걸었지만(forceLink 두
// 개), 3D 엔진은 링크 힘을 하나만 들고 우리가 준 링크 배열을 통째로 그 힘에
// 밀어 넣으므로 **하나의 힘 안에서 링크마다 갈라 잰다.**
export function linkDistance(e, f = DEFAULT_FORCES) {
  if (e.kind === 'same_as') return SAME_AS_DISTANCE;
  return LINK_BASE_DISTANCE * f.link + (e.source?.r || 0) + (e.target?.r || 0);
}
export function linkStrength(e) {
  return e.kind === 'same_as' ? SAME_AS_STRENGTH : LINK_STRENGTH;
}

// 힘 한 벌. 3D 엔진에는 `fg.d3Force(이름, 힘)` 으로 꽂고, 검증에는
// `buildSimulation` 이 같은 것을 시뮬레이션에 건다. **한 곳에서만 만든다** —
// 두 벌이 되면 화면과 검증이 다른 배치를 재게 된다.
export function buildForces({ center, forces = DEFAULT_FORCES } = {}) {
  const f = { ...DEFAULT_FORCES, ...forces };
  const pull = (n) => (n.id === center ? CENTER_PULL : NODE_PULL) * f.center;
  return {
    charge: forceManyBody()
      .strength((n) => -(REPEL_BASE + (n.r || 0) * REPEL_PER_RADIUS) * f.repel)
      .distanceMax(REPEL_MAX_DIST),
    // 겹침 방지. 옛 MIN_REPEL_DIST 가 하던 일을 대신한다.
    collide: forceCollide().radius((n) => (n.r || 0) + 6).strength(0.7),
    link: forceLink()
      .id((n) => n.id)
      .distance((e) => linkDistance(e, f))
      .strength(linkStrength),
    x: forceX(0).strength(pull),
    y: forceY(0).strength(pull),
    z: forceZ(0).strength(pull),
  };
}

// 배치 하나를 만든다. **시작 상태로 멈춰서 돌려준다** — 틱은 부르는 쪽이
// 돌린다. 화면에서는 3D 엔진이 자기 루프로 돌리고, 검증에서는 테스트가
// 돌린다.
export function buildSimulation({ nodes, edges, center, forces = DEFAULT_FORCES }) {
  const F = buildForces({ center, forces });
  F.link.links(edges);
  const sim = forceSimulation(nodes, 3)
    .velocityDecay(VELOCITY_DECAY)
    .alphaDecay(ALPHA_DECAY)
    .alphaMin(ALPHA_MIN)
    .force('charge', F.charge)
    .force('collide', F.collide)
    .force('link', F.link)
    .force('x', F.x)
    .force('y', F.y)
    .force('z', F.z);
  sim.forces = { ...DEFAULT_FORCES, ...forces };
  sim.stop();
  return sim;
}
