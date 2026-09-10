// 3D 그래프 렌더러 (`3d-force-graph` · three.js).
//
// 2026-09-11 사용자 결정으로 2D 캔버스 렌더러를 걷어내고 **3D 하나만** 둔다
// ("3d-force-graph를 이용해서 우리 그래프를 3d로 만들어줘", 전환 단추 없음).
// 한국사 그래프와 내 역사 그래프가 같은 이 클래스를 쓰므로 한 곳을 고치면
// 둘 다 바뀐다.
//
// **뜻은 그대로 두고 표현만 3차원으로 옮겼다** (graph-drawer §3·§4·§5):
// 색상 = 타입 · 크기 = 차수 · 굵기 = 인과 · 링 = 상태 · 조명 = 가리킨 노드와
// 직접 이웃 · 화살촉 = 방향. 옮기면서 다시 정한 것은 셋뿐이고 셋 다 아래
// 주석과 graph-drawer §12 에 이유를 적었다: 확실성(파선 → **파선 무늬를 입힌
// 관**), 이름표를 언제 세우나(겹침을 화면 좌표에서 잰다 — 자는 3D 가 되었다),
// 되데우기(3D 엔진은 한 단계뿐).
//
// **엔진은 늦게 싣는다.** `3d-force-graph` 는 Node 에서 import 가 터지는데
// (window 가 없다) 배치 검증(layout.test.mjs)과 서버 렌더링 검증
// (render.test.mjs)이 이 파일을 Node 에서 그대로 읽는다. 그래서 자료·상태를
// 다루는 일은 전부 브라우저 없이 돌고, three 를 만지는 일만 `_attach` 뒤로
// 미룬다. 엔진이 오기 전에 들어온 setData·select·setDisplay 는 버려지지
// 않는다 — 상태는 이미 이 객체에 다 있고, 엔진이 오면 `_sync` 가 통째로
// 옮겨 싣는다.
import { isLight } from './theme.js';
import {
  buildForces, nodeRadius, DEFAULT_FORCES,
  ALPHA_DECAY, ALPHA_MIN, VELOCITY_DECAY,
} from './layout.js';

// style.css 의 --font-interface 와 같은 순서. 이름표(SpriteText)는 캔버스에
// 글자를 그려 텍스처로 만들므로 CSS 변수를 못 읽는다.
const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif';

// 모양은 하나(구)로 두고, 색이 타입을 말한다.
//
// 아홉 색을 한 화면에 쓰는 건 원래 실패한 배치였다(README 의 팔레트 표).
// 살려낸 방법은 **색상만으로 벌리지 않은 것**이다 — 밝기까지 층으로 갈라
// 두면 색을 잃은 눈에도 차이가 남는다. `python3 tools/check_palette.py` 가
// 이 파일의 값을 직접 읽어 잰다 (OKLab ΔE ×100, 최악 쌍):
//
//   정상 10.7 · 2형(deutan) 9.7 · 1형(protan) 7.3   — 눈금 5.0 을 넘긴다
//   (3형은 근사라 판정에서 뺀다. 검증기 주석에 이유를 적어 뒀다.)
//
// 색을 고치면 저 검증기를 다시 돌린다. 여기 적힌 숫자는 그때의 기록일 뿐
// 이고, 실제 값은 검증기가 말한다.
//
// 색은 2026-09-06 사용자가 준 여섯 색 팔레트(Coolors "skafold": 초록 004F2D
// · 남색 003049 · 빨강 D62828 · 주황 FB6C13 · 노랑 F9C80E · 크림 F5E0B7)다.
// 여섯으로 아홉 타입을 다 못 덮으므로 **색상은 팔레트에서만 가져오고 밝기로
// 갈랐다.** 빨강·주황·노랑·크림 넷은 원색 그대로. 남색과 초록은 바탕
// #1e1e1e 위에서 대비가 1.2·1.7 이라 작은 점이 보이지 않아 같은 색상으로
// 밝힌 값을 쓴다. **인물만 예외로 파랑** #3d84f5 다 — 팔레트를 씌운 뒤
// 사용자가 "인물 노드도 blue 로" 라고 했다 (2026-09-06). 연표의 왕·대통령
// 재위 띠(timeline.js REIGN_COLOR)와 같은 파랑.
//
// 3D 에서도 이 표가 그대로 선다. 구는 램버트 재질이라 빛을 받으면 위쪽이
// 밝고 아래쪽이 어두워지지만, 색상(hue)은 그대로라 타입은 갈린다.
export const TYPE_COLOR = {
  person: '#3d84f5',   // 파랑 — 팔레트 밖. 사용자 결정 (재위 띠와 같은 파랑)
  org: '#f5e0b7',      // 크림 (팔레트 원색) — 인물(파랑)과 밝기를 크게 벌렸다
  event: '#fb6c13',    // 주황 (팔레트 원색)
  place: '#2e9e5e',    // 초록 — 팔레트 004F2D 를 밝힘 (원색은 바탕 대비 1.7)
  heritage: '#f9c80e', // 노랑 (팔레트 원색) — 유물·문화재
  artwork: '#f2a0a0',  // 연빨강 — 팔레트 D62828 을 밝힘. 예술작품
  media: '#3a7ca5',    // 남색 — 팔레트 003049 를 밝힘 (원색은 바탕 대비 1.2). 영화·드라마
  period: '#2a5d78',   // 어두운 남색 — 뼈대라서 물러나 있어야 한다
  role: '#1e6b45',     // 어두운 초록 — 뼈대의 다른 한쪽
};

// 갈래 색. 타입을 모를 때 물러날 자리다.
export const GROUP_COLOR = {
  actor: '#3d84f5', // 인물·단체
  event: '#fb6c13', // 사건
  thing: '#2e9e5e', // 장소·유물·작품
  frame: '#2a5d78', // 시대·직위
};

// 라이트 테마의 노드 색. **색상은 그대로, 밝기만 뒤집었다** — 흰 바탕에서는
// 밝힌 값(크림·노랑·연빨강)이 사라지므로 팔레트 원색(빨강 D62828·남색
// 003049)이나 어둡게 누른 값으로 돌아가고, 뼈대(시대·직위)는 반대로 옅어져
// 물러난다. 인물 파랑과 사건 주황은 두 바탕에서 다 읽혀 그대로다.
export const TYPE_COLOR_LIGHT = {
  person: '#3d84f5',
  org: '#b08a45',      // 크림을 어둡게 누른 황갈색
  event: '#fb6c13',
  place: '#22854c',    // 초록 — 원색 004F2D 보다 한 단 밝다 (직위와 갈리게)
  heritage: '#c29500', // 노랑을 어둡게 — 흰 바탕의 F9C80E 는 대비 1.4, 이 값은 2.3
  artwork: '#d62828',  // 팔레트 원색 빨강
  media: '#003049',    // 팔레트 원색 남색
  period: '#7fa3bd',   // 옅은 남색 — 뼈대는 물러나되 보이기는 해야 한다 (2.6:1)
  role: '#6fae8e',     // 옅은 초록 (2.5:1)
};
export const GROUP_COLOR_LIGHT = {
  actor: '#3d84f5',
  event: '#fb6c13',
  thing: '#22854c',
  frame: '#7fa3bd',
};

// 노드 색은 타입이 정한다. 모르는 타입은 갈래로 물러난다. 테마는 물을 때마다
// 읽는다 — 단추를 누르면 `_repaint` 가 색을 다시 먹인다. 상세·연표의 색 점은
// React 가 다시 그릴 때 따라온다.
export function nodeColor(type, group) {
  const [T, G] = isLight() ? [TYPE_COLOR_LIGHT, GROUP_COLOR_LIGHT] : [TYPE_COLOR, GROUP_COLOR];
  return T[type] || G[group] || G.thing;
}

// **서로 같은 것을 뜻하는 관계.** 두 가지가 여기서 따라 나온다.
//   1. 화살촉을 붙이지 않는다. 화살촉은 '누가 누구에게'를 말하는 부호인데, 방향이
//      없는 자리에 붙이면 없는 방향을 지어낸다 — 신사임당 → 이원수와 이원수 →
//      신사임당은 같은 말이다.
//   2. 선은 한 줄이다. 두 방향이 다 오면 같은 자리에 두 번 겹쳐 그려진다 (실측
//      2026-09-08: 배우자 네 쌍이 여덟 줄이었다). 상세 패널은 이미 카드 한 장으로
//      접는다 (`relations.js SYMMETRIC`).
// 한국사는 `spouse_of`, 개인 역사는 만남·친구·동료·같은 학교·함께 나눔·겹침
// (`life.SYMMETRIC`). same_as 는 관계가 아니라 이음이라 예전부터 화살촉이 없다.
// **`relative_of` 는 뺐다** — 대칭이지만 선 이름이 도착 쪽을 부르는 말이라
// ('나 → 나형철 · 형' = 나형철이 나의 형) 화살촉이 그 말의 주어를 정한다.
// `related_to` 도 뺐다 — 라벨이 '다음'이면 앞뒤가 있다 (`LABEL_DIR_HEAD`).
export const MUTUAL = new Set(['same_as', 'spouse_of',
  'met', 'friend_of', 'partner_of', 'worked_with', 'schoolmate', 'shared_with', 'overlapped']);

// Obsidian 의 그래프 뷰를 따른다 (design.md §3). 바탕은 --background-primary,
// 선은 --graph-line (회색 한 가지), 가리킨 노드의 선과 테두리만 강조색.
// 두 벌이다 — CSS 변수를 three 가 못 읽으므로 style.css 의 값을 여기 옮겨 적었다.
const DARK = {
  surface: '#1e1e1e',                     // --background-primary
  edgeBase: '#4a4a4a',                    // --graph-line 보다 한 단 밝다
  edgeSoft: 'rgba(74,74,74,0.35)',        // 가리키는 동안 물러난 선
  edgeSame: '#3f3f3f',                    // 동일 실체 (same_as) — 관계가 아니라 이음이라 더 어둡다
  edgeLit: '#a8a8a8',                     // 가리킨 노드에 붙은 선 — 보라가 아니라 밝은 회색 (2026-09-05 사용자 결정)
  edgeLitSame: '#7a7a7a',                 // 가리킨 노드의 same_as 선
  // 인과 도면의 선 — 연표의 '원인'과 같은 파랑(--color-blue) 계열. 주변
  // 관계 그래프에서는 인과도 회색 한 가지다.
  causeLit: '#8cc4ea',
  accent: '#8a6cef',                      // --color-accent
  accentSoft: '#af9af4',                  // --color-accent-2
  text: '#dadada',                        // --text-normal
  textDim: '#9a9a9a',                     // --text-muted 무게 (스프라이트는 알파 대신 값으로 준다)
  ring: '#dadada',                        // 중심 노드의 테두리 (알파는 링 재질이 든다)
};
// 라이트. 처음 값(선 #c4c4c4·글자 62%)은 흰 바탕에서 안 보였다 (2026-09-06
// 지적). 선은 Radix gray 9 (#8d8d8d) 수준으로, 가리킨 선은 글자만큼 어둡게.
const LIGHT = {
  surface: '#ffffff',
  edgeBase: '#9a9a9a',                    // 흰 바탕 2.7:1 — 가는 선이 보이는 하한 근처
  edgeSoft: 'rgba(154,154,154,0.4)',
  edgeSame: '#b8b8b8',
  edgeLit: '#2e2e2e',                     // 가리킨 노드의 선 — 글자와 같은 무게
  edgeLitSame: '#6a6a6a',
  causeLit: '#2a6a9a',                    // --color-blue (라이트)
  accent: '#7a4be0',                      // hsl(258 80% 56%)
  accentSoft: '#9b76ea',                  // hsl(258 80% 68%)
  text: '#1f1f1f',
  textDim: '#5a5a5a',
  ring: '#1f1f1f',
};
function chrome() { return isLight() ? LIGHT : DARK; }

// --- 3D 로 옮기며 정한 치수 ---------------------------------------------
//
// 자는 **월드 단위**다. 노드 반지름이 4~17 이고 링크 거리가 112 라, 아래 값은
// 그 사이에서 골랐다 (2D 의 픽셀 값을 그대로 쓰면 3D 에서는 선이 통나무가 된다).
const DIM_ALPHA = 0.16;        // 조명 밖 (2D 의 globalAlpha 0.16 그대로)
const RING_GAP = 4.5;          // 상태 링이 노드 밖으로 나오는 만큼
const ARROW_LEN = 5.5;         // 화살촉 길이 — 라이브러리가 도착 노드 반지름을 빼고 세운다
// 선 굵기. 2D 의 1.1px 을 월드 굵기로 옮긴 것 — 선이 노드보다 굵어지면 안
// 되므로 가장 작은 노드(반지름 4)의 1/6 을 밑동으로 잡았다. `lit` 은 인과
// 도면의 선이고, 주변 관계 그래프에서 조명은 굵기가 아니라 밝기가 말한다.
const LINK_W = { base: 0.7, lit: 1.15, same: 0.5 };
const CAUSE_W = 0.8;           // 인과는 다른 관계보다 굵다 (2D 의 +1.2px)
// 파선의 마디 수. 2D 의 `5 4`(추출)와 `2 4`(동일 실체)를 마디 밀도로 옮겼다.
const DASH = { infer: 7, same: 16 };
// **이름표는 화면에서 늘 같은 크기다** — 2D 의 값 그대로(초점 12.5 · 나머지
// 11 · 둘째 이름 9.5px). 3D 의 스프라이트는 멀어지면 작아지는데, 그러면 노드
// 120개짜리 그래프가 화면에 꽉 찬 거리(≈1400)에서 글자가 5px 이 되어 아무도
// 못 읽는다 (실측 2026-09-11: 첫 화면에 이름이 하나도 없었다). 그래서 매번
// 카메라 거리에 맞춰 스프라이트를 다시 키운다 — 2D 가 `/k` 로 하던 일이다.
// 무엇을 세울지는 그 다음 문제이고, 그건 겹침이 정한다(`_placeLabels`).
const LABEL_PX = { strong: 12.5, normal: 11, alt: 9.5 };
// 글자를 구울 때의 높이. 화면 크기는 위에서 정하므로 이 값은 **텍스처의
// 해상도**일 뿐이다 (작으면 흐리고 크면 메모리를 먹는다).
const LABEL_BAKE = 12;
const FOCUS_DIST = 240;        // focusOn 이 노드에서 떨어져 서는 거리
const FIT_PAD = 90;            // 카메라 맞춤의 여백 (화면 가장자리에서)

// --- 인과 도면 ----------------------------------------------------------
//
// 노드를 누르면 캔버스가 **그 노드의 인과 도면**이 된다. 원인은 왼쪽 열,
// 결과는 오른쪽 열, 열 안은 연도순. 힘 배치는 멈춘다 — 3D 에서는 노드를
// 못박아(fx/fy/fz) 멈춘다.
//
// **3D 에서도 도면은 평면이다** (2026-09-11 에 정한 것, graph-drawer §12.23).
// 인과는 방향이 뜻이고 그 방향은 축 하나(왼쪽 → 오른쪽)로 읽혀야 한다. 깊이를
// 셋째 뜻으로 쓰면 '앞에 있는 것'이 무엇인지 새 규칙이 필요한데, 층 배치가
// 말하는 것은 걸음 수뿐이라 실을 뜻이 없다. 그래서 z = 0 평면에 세우고 카메라를
// 정면에 둔다 — 돌려보면 평면이라는 것이 보이고, 그것이 참이다.
// 지금은 꺼져 있다 (`App.jsx CAUSAL_DIAGRAM = false`, 2026-09-06 사용자 결정).
const COL = 230;   // 열(걸음) 간격
const ROW = 58;    // 한 열 안의 줄 간격
// 열 머리. 걸음이 멀수록 말이 흐려진다 — '원인의 원인의 원인'은 안 읽힌다.
const COL_CAPTION = {
  cause: ['원인', '원인의 원인', '더 앞선 원인'],
  effect: ['결과', '결과의 결과', '더 뒤의 결과'],
};

export class GraphView {
  constructor(container, opts = {}) {
    this.container = container;
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.center = null;
    this.hover = null;
    this.selected = null;
    this.onSelect = opts.onSelect || (() => {});
    this.onExpand = opts.onExpand || (() => {});
    this.onHover = opts.onHover || (() => {});
    this.onCausalExit = opts.onCausalExit || (() => {});
    this.showLabels = true;
    // Obsidian 그래프 설정의 '표시'·'필터'·'힘' 절 (design.md §4).
    // nodeScale·lineScale 은 배율, textFade 는 이름표가 사라지는 **거리** 문턱
    // (0 = 멀리서도 보임 · 1 = 가까이 가야 보임), arrows 는 화살촉 여부.
    this.display = { nodeScale: 1, lineScale: 1, textFade: 0.3, arrows: true };
    this.hiddenEdgeTypes = new Set();   // 필터로 끈 관계 종류
    this.forces = { ...DEFAULT_FORCES };
    // 인과 도면 상태 (showCausal). 도면 밖이면 null.
    this.causalView = null;
    this._saved = null;

    this.fg = null;          // 3d-force-graph 인스턴스 (늦게 실린다)
    this.three = null;
    this.SpriteText = null;
    this._objs = new Map();  // 노드 id → { group, ring, label, alt }
    this._mats = new Map();  // 파선 재질 캐시 (색 × 마디 수)
    this._texes = new Map(); // 파선 무늬 캐시
    this._shownLabels = new Set();
    this._captions = [];
    this._light = isLight();
    this._cooling = false;
    this._ticked = false;
    this._ticks = 0;
    this._fitDist = 900;   // 이름표 흐림의 자 (첫 맞춤이 실제 값으로 고친다)
    this._raf = 0;
    this._frames = 0;
    this._stopped = false;
    this.autoFit = true;

    this._boot();
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(container);
    }
  }

  // 엔진을 늦게 싣는다 (모듈 맨 위에서 부르면 Node 에서 터진다).
  async _boot() {
    let mods;
    try {
      mods = await Promise.all([
        import('3d-force-graph'), import('three'), import('three-spritetext'),
      ]);
    } catch {
      return;   // 브라우저가 아니다 — 자료 다루는 일은 그대로 돈다
    }
    if (this._stopped) return;
    this._attach(mods[0].default, mods[1], mods[2].default);
  }

  // 엔진이 왔다. **여기서 처음으로 three 를 만진다.** 검증은 가짜 엔진을
  // 넘겨 이 길을 그대로 밟는다 (layout.test.mjs).
  _attach(ForceGraph3D, three, SpriteText) {
    this.three = three;
    this.SpriteText = SpriteText;
    const c = chrome();
    const fg = new ForceGraph3D(this.container, { controlType: 'orbit' });
    this.fg = fg;
    fg.backgroundColor(c.surface)
      // 라이브러리의 안내 글(“Left-click: rotate…”)과 툴팁은 영어다. 끈다 —
      // 화면에 한글 아닌 글을 띄우지 않는다 (CLAUDE.md §1). 이름은 노드에
      // 붙은 이름표(SpriteText)가 한국어로 말한다.
      .showNavInfo(false)
      .nodeLabel(() => '')
      .linkLabel(() => '')
      // 반지름 = nodeRadius 그대로. 라이브러리는 `∛val × nodeRelSize` 를
      // 반지름으로 쓰므로 val 에 r³ 을 준다.
      .nodeRelSize(1)
      .nodeVal((n) => Math.max(n.r || 1, 0.5) ** 3)
      .nodeResolution(14)
      .nodeOpacity(1)
      .linkOpacity(1)
      .linkResolution(6)
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalArrowResolution(8)
      .nodeThreeObjectExtend(true)
      .d3AlphaDecay(ALPHA_DECAY)
      .d3VelocityDecay(VELOCITY_DECAY)
      .d3AlphaMin(ALPHA_MIN)
      // 멈추는 자리는 alphaMin 하나다. 틱·시간으로 자르면 큰 그래프가
      // 식기 전에 굳는다.
      .cooldownTicks(Infinity)
      .cooldownTime(Infinity)
      .enableNodeDrag(true)
      .onNodeClick((n) => this._click(n))
      .onNodeHover((n) => this._hover(n))
      .onBackgroundClick(() => this._clearSpot())
      // **드래그는 못박기다** (2D 와 같은 뜻). 라이브러리는 드래그가 끝나면
      // 못을 도로 뽑으므로 여기서 다시 박는다.
      .onNodeDragEnd((n) => { n.fx = n.x; n.fy = n.y; n.fz = n.z; })
      .onEngineTick(() => this._tick())
      .onEngineStop(() => this._engineStopped());

    this._accessors();
    this._applyForces();
    // 사용자가 화면을 돌리거나 확대하면 그때부터 카메라는 사용자 것이다.
    try { fg.controls().addEventListener('start', () => { this.autoFit = false; }); } catch { /* 조작기가 없는 엔진 */ }
    this._resize();
    if (this.nodes.length) this._sync({ reheat: true });
    if (typeof requestAnimationFrame !== 'undefined') {
      this._raf = requestAnimationFrame(() => this._frame());
    }
  }

  // React 가 언마운트할 때 부른다. 안 부르면 렌더 루프가 죽은 컨테이너를
  // 붙잡고 계속 돈다.
  destroy() {
    this._stopped = true;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._ro?.disconnect();
    // **그리기를 먼저 세우고 걷는다.** `_destructor()` 는 엔진의 상태를
    // 비우는데 라이브러리의 애니메이션 고리(requestAnimationFrame)는 그대로
    // 돌아서, 다음 프레임에 빈 상태를 짚고 터진다 (`layoutTick` 의
    // `state.layout`). 한 번 터지면 그 고리는 다음 프레임을 걸지 않는다 —
    // 개발 모드(StrictMode)가 캔버스를 떼었다 붙이는 자리에서 그것이
    // 화면을 통째로 비웠다 (실측 2026-09-11, /life.html).
    try { this.fg?.pauseAnimation?.(); } catch { /* 이미 멈췄다 */ }
    try { this.fg?._destructor(); } catch { /* 이미 걷혔다 */ }
    for (const m of this._mats.values()) m.dispose?.();
    for (const t of this._texes.values()) t.dispose?.();
    this._mats.clear();
    this._texes.clear();
    this._dropObjs();
    this.fg = null;
  }

  // 배치가 아직 도는가. 2D 의 `alpha` 자리다 — 3D 엔진은 alpha 를 밖으로
  // 내주지 않으므로 '식었나/도는가' 둘로만 답한다.
  get alpha() { return this._cooling ? 1 : 0; }

  // --- 자료 ---------------------------------------------------------
  //
  // merge=true 면 기존 배치를 유지한 채 새 노드만 얹는다. 펼치기를 할
  // 때마다 화면이 통째로 다시 튀면 사용자는 방금 보던 것을 잃는다.
  setData(payload, { merge = false } = {}) {
    // 도면 위에 이웃을 얹지 않는다 — 검색·펼치기는 주변 관계 그래프의 일이다.
    if (this.causalView) this.exitCausal({ restore: merge });
    if (!merge) {
      this.nodes = [];
      this.edges = [];
      this.byId = new Map();
      this._dropObjs();
    }

    const incoming = new Set();
    let placed = 0;
    for (const n of payload.nodes) {
      incoming.add(n.id);
      let node = this.byId.get(n.id);
      if (!node) {
        // **공 껍질 위에 고르게 놓는다.** 무작위로 뿌리면 노드 몇 개가 거의
        // 겹친 채 시작하고, 그 지점의 반발력이 폭발해 서로를 멀리 튕겨낸다.
        // 2D 의 황금각 나선을 3차원으로 옮긴 것 — 방위각은 황금각, 극각은
        // 황금비의 소수부를 걸어 층이 지지 않게 했다. 무작위가 아니므로 같은
        // 자료는 같은 그림이 된다 (graph-drawer §2 '결정성').
        const anchor = this.byId.get(payload.center);
        const i = placed++;
        const a = i * 2.399963;                       // 황금각
        const d = 40 + 26 * Math.sqrt(i);
        const cz = 1 - 2 * ((i * 0.618033988749895) % 1);
        const s = Math.sqrt(Math.max(0, 1 - cz * cz));
        node = {
          ...n,
          x: (anchor ? anchor.x : 0) + Math.cos(a) * s * d,
          y: (anchor ? anchor.y : 0) + Math.sin(a) * s * d,
          z: (anchor ? anchor.z : 0) + cz * d,
          vx: 0, vy: 0, vz: 0,
        };
        this.byId.set(n.id, node);
        this.nodes.push(node);
      } else {
        Object.assign(node, { degree: Math.max(node.degree, n.degree) });
      }
      node.r = nodeRadius(node) * this.display.nodeScale;
    }

    const seen = new Map(this.edges.map((e) => [edgeKey(e), e]));
    for (const e of payload.edges) {
      if (!this.byId.has(e.s) || !this.byId.has(e.t)) continue;
      const key = pairKey(e.s, e.t, e.type);
      const have = seen.get(key);
      if (have) {
        // 사슬이 주는 인과의 종류(배경·계기·영향)가 '원인'보다 구체적이다
        if (e.type === 'caused' && e.label && e.label !== '원인') have.label = e.label;
        continue;
      }
      const row = { ...e, kind: 'edge' };
      seen.set(key, row);
      this.edges.push(row);
    }
    for (const s of payload.same_as || []) {
      if (!this.byId.has(s.a) || !this.byId.has(s.b)) continue;
      const key = pairKey(s.a, s.b, 'same_as');
      if (seen.has(key)) continue;
      // seen 은 Map 이다. 여기서 .add 를 불러 same_as 가 하나라도 있는 화면은
      // setData 가 중간에 죽었다 — 노드는 이미 실렸는데 center·selected 가
      // 안 잡혀 검색한 노드에 조명이 안 들었다 (2026-09-06 지적: 명성황후).
      const row = { s: s.a, t: s.b, type: 'same_as', label: '동일 실체', conf: 1, kind: 'same_as' };
      seen.set(key, row);
      this.edges.push(row);
    }

    this.center = payload.center;
    const c = this.byId.get(payload.center);
    if (c && !merge) { c.x = 0; c.y = 0; c.z = 0; }
    this.adjacency = null;
    this._reach = null;
    this.autoFit = true;   // 사용자가 화면을 돌리기 전까지는 카메라가 따라간다
    this._fitted = false;
    this._sync({ reheat: true });
    return incoming;
  }

  // 인과 도면으로 들어간다. `/api/chain` 의 나무를 열로 세우고(causalLayout)
  // 주변 관계 그래프는 접어 둔다. 인과가 없으면 false — 부르는 쪽이 전처럼
  // 주변 관계를 편다.
  showCausal(chain) {
    const laid = causalLayout(chain, { col: COL, row: ROW });
    if (!laid) return false;
    if (!this.causalView) {
      this._saved = { nodes: this.nodes, edges: this.edges, byId: this.byId, center: this.center };
    }
    // 열 배치는 화면 좌표(아래로 +y)라 3D 로 뒤집어 세운다. 못을 박아 힘이
    // 못 건드리게 한다 — 2D 에서 시뮬레이션을 멈추던 자리다.
    this.nodes = laid.nodes.map((n) => ({
      ...n, y: -n.y, z: 0, fx: n.x, fy: -n.y, fz: 0, vx: 0, vy: 0, vz: 0,
    }));
    this.edges = laid.edges;
    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    this.center = chain.center;
    this.selected = chain.center;
    this.hover = null;
    this.causalView = { chain, center: chain.center, causes: laid.causes, effects: laid.effects,
                        depths: laid.depths, col: COL };
    this.adjacency = null;
    this._reach = null;
    this._dropObjs();
    this.autoFit = false;
    this._sync({ reheat: false });
    this._captionsFor(laid);
    this._faceCausal(laid);
    return true;
  }

  // 도면에서 주변 관계 그래프로. 접어 둔 노드·자리가 그대로 돌아온다
  // (restore=false 면 곧 setData 가 덮어쓰므로 상태만 접는다).
  exitCausal({ restore = true } = {}) {
    if (!this.causalView) return;
    const s = this._saved;
    this._saved = null;
    this.causalView = null;
    this.hover = null;
    this._captionsFor(null);
    if (restore && s) {
      this.nodes = s.nodes; this.edges = s.edges; this.byId = s.byId; this.center = s.center;
      this.selected = null;
      this.adjacency = null;
      this._reach = null;
      this._dropObjs();
      this.autoFit = true;
      this._fitted = false;
      this._sync({ reheat: false });
      this.onCausalExit();
    }
  }

  // 한 노드에서 인과 엣지를 따라 위(원인)·아래(결과)로 닿는 모든 것.
  // 도면에서 노드를 가리키면 그 노드를 지나는 경로만 밝힌다.
  causalReachOf(id) {
    if (this._reach?.id !== id) {
      this._reach = { id, ...causalReach(this.edges, id, (e) => this.edgeShown(e)) };
    }
    return this._reach;
  }

  // --- 설정 -------------------------------------------------------------
  setDisplay(patch) {
    const was = this.display;
    this.display = { ...was, ...patch };
    const sized = this.display.nodeScale !== was.nodeScale;
    if (sized && this.nodes.length && !this.causalView) {
      for (const n of this.nodes) n.r = nodeRadius(n) * this.display.nodeScale;
    }
    // 크기 배율이 바뀐 때만 무거운 길로 간다 — 나머지(화살촉·흐림 문턱)는
    // 조명과 같은 길이라 객체를 다시 만들지 않는다.
    if (sized || this.display.lineScale !== was.lineScale) this._resizeNodes();
    else this._relight();
  }

  setForces(patch) {
    this.forces = { ...this.forces, ...patch };
    this._applyForces();
    // **되데우기는 한 단계다** (3D 엔진은 alpha 를 직접 못 준다). 그래서
    // 데우는 계기를 줄였다 — 힘이 바뀔 때와 새 자료가 올 때뿐이고, 크기
    // 배율·창 크기·도면 복귀는 데우지 않는다 (자리는 그대로 두면 된다).
    if (this.nodes.length && !this.causalView) this._reheat();
  }

  // 관계 종류를 끄면 그 선은 안 그리고, 그래서 선이 하나도 안 남은 노드도
  // 안 그린다 — Obsidian 필터가 그래프에서 노드를 빼는 것과 같다.
  // 시뮬레이션에는 그대로 남아 있어 켜면 제자리로 돌아온다.
  setEdgeFilter(hidden) {
    this.hiddenEdgeTypes = new Set(hidden || []);
    this.adjacency = null;
    this._reach = null;
    if (this.hover && !this.nodeShown(this.hover)) this.hover = null;
    this._relight();
  }

  edgeShown(e) { return !this.hiddenEdgeTypes.has(e.type); }

  nodeShown(id) {
    if (!this.hiddenEdgeTypes.size || id === this.center) return true;
    return this.neighborsOf(id).size > 0;
  }

  neighborsOf(id) {
    if (!this.adjacency) {
      this.adjacency = new Map();
      for (const e of this.edges) {
        if (!this.edgeShown(e)) continue;
        if (!this.adjacency.has(e.s)) this.adjacency.set(e.s, new Set());
        if (!this.adjacency.has(e.t)) this.adjacency.set(e.t, new Set());
        this.adjacency.get(e.s).add(e.t);
        this.adjacency.get(e.t).add(e.s);
      }
    }
    return this.adjacency.get(id) || new Set();
  }

  // 프로그램에서 고르는 경로. **콜백을 부르지 않는다.**
  //
  // 부르면 무한히 돈다: 클릭 → onSelect → load() → select() → onSelect →
  // load() → … 한 번 클릭할 때마다 요청이 끝없이 이어지고, load 마다
  // setData 가 배치를 되데워 영영 식지 않는다.
  select(id) {
    const node = this.byId.get(id);
    if (!node) return;
    this.selected = node.id;
    this._relight();
  }

  // 노드가 화면 밖이면 사용자는 아무 일도 안 일어났다고 생각한다.
  // **맞춤이 아직 돌고 있으면 손대지 않는다** — 그때는 그래프 전체가 화면에
  // 들어오는 중이라 그 노드도 이미 보인다. 카메라를 둘이 서로 끌면 떨린다.
  focusOn(id) {
    const n = this.byId.get(id);
    if (!n || !this.fg) return;
    if (this.autoFit && this._cooling) return;
    const d = Math.hypot(n.x || 0, n.y || 0, n.z || 0) || 1;
    const k = 1 + FOCUS_DIST / d;
    this.autoFit = false;
    this.fg.cameraPosition({ x: (n.x || 0) * k, y: (n.y || 0) * k, z: (n.z || 0) * k }, n, 700);
  }

  // 노드가 지금 화면의 어디에 찍혀 있나 (컨테이너 안의 픽셀). 화면 코드는
  // 쓰지 않는다 — **CDP 검증이 노드를 누르는 자리**다. 3D 는 x·y 만으로는
  // 화면 자리를 알 수 없어(카메라가 정한다) 여기서 물어봐야 한다.
  // 카메라 뒤로 넘어간 노드는 null.
  screenAt(id) {
    const n = this.byId.get(id);
    if (!n || !this.fg) return null;
    const p = this.fg.graph2ScreenCoords(n.x || 0, n.y || 0, n.z || 0);
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return null;
    return { x: p.x, y: p.y };
  }

  // 그래프 전체가 화면에 들어오게 (설정·복귀에서 부른다)
  resetView() {
    this.autoFit = true;
    this._fit();
  }

  // --- 엔진에 싣기 ------------------------------------------------------
  _sync({ reheat = false } = {}) {
    const fg = this.fg;
    if (!fg) return;             // 아직 안 실렸다 — 실리면 _attach 가 통째로 싣는다
    // 링크의 양 끝은 늘 아이디로 넘긴다. 힘이 노드 객체로 바꿔 끼우므로
    // 두 번 실어도 흔들리지 않는다.
    for (const e of this.edges) { e.source = e.s; e.target = e.t; }
    // 자료가 바뀌면 라이브러리가 알아서 alpha 를 1 로 되돌린다. 그러니
    // '식는 중'이라고 적어 두어야 카메라가 배치를 따라간다.
    fg.graphData({ nodes: this.nodes, links: this.edges });
    this._cooling = true;
    this._ticks = 0;
    this._applyForces();
    if (reheat) this._reheat();
    this._relight();
  }

  // **되데우기는 한 단계뿐이다.** 2D 에서는 계기마다 alpha 를 달리 줬지만
  // (새 자료 1 · 크기 0.4 · 힘 0.6 · 도면 복귀 0.12), 3D 엔진은 alpha 를
  // 밖으로 내주지 않고 `d3ReheatSimulation`(=1) 하나만 연다. 그래서 **데우는
  // 계기를 줄였다** — 새 자료와 힘 설정 둘뿐이고, 노드 크기 배율·창 크기·
  // 조명은 데우지 않는다. 2D 에서 배치가 영영 안 식던 병이 창 크기에서
  // 왔던 것을 생각하면 계기가 적은 편이 낫다.
  //
  // **엔진이 한 번이라도 돌기 전에는 되데우지 않는다.** `d3ReheatSimulation`
  // 은 그 자리에서 `engineRunning = true` 로 세우는데(`resetCountdown`),
  // 배치(`state.layout`)는 자료 소화(digest)가 1ms 뒤에 만든다. 그 사이에
  // 프레임이 한 번 지나가면 라이브러리가 없는 배치를 짚어 터지고
  // (`layoutTick` 의 `state.layout.tick()`), **터진 고리는 다음 프레임을 걸지
  // 않아 화면이 통째로 죽는다.** 자료가 엔진보다 먼저 오는 화면(내 역사 —
  // `onReady` 가 만들자마자 `setData` 를 부른다)에서 늘 그랬다 (2026-09-11
  // 실측: `renderer.info.render.frame` 이 1 에서 멎었다).
  // 되데울 필요도 없다 — 자료를 실으면 라이브러리가 스스로 alpha 를 1 로
  // 되돌린다. 첫 틱을 본 뒤부터만 이 길을 쓴다.
  _reheat() {
    this._cooling = true;
    this._ticks = 0;
    if (this._ticked) this.fg?.d3ReheatSimulation();
  }

  // 라이브러리의 렌더 고리가 살아 있는가. 예외 하나에 고리가 통째로 멎고,
  // 그때 `animationFrameRequestId` 가 남아 있어 `resumeAnimation()` 만으로는
  // 못 되살린다 — 먼저 멈춘 것으로 표시해야(`pauseAnimation`) 새 고리를 건다.
  // 위의 관문이 원인을 막지만, 죽으면 화면이 통째로 비는 자리라 재서도 본다.
  _watchLoop() {
    const fg = this.fg;
    if (!fg || this._stopped) return;
    let n;
    try { n = fg.renderer?.().info?.render?.frame; } catch { return; }
    if (typeof n !== 'number') return;
    if (this._lastRenderFrame === n) {
      try { fg.pauseAnimation(); fg.resumeAnimation(); } catch { /* 걷힌 뒤 */ }
    }
    this._lastRenderFrame = n;
  }

  // 엔진이 멈췄다. **이미 식은 뒤에 오는 멈춤은 헛것이다** — 라이브러리는
  // 설정이 하나라도 바뀌면 시뮬레이션을 다시 켜고, 그 다음 프레임에 곧바로
  // 다시 멈춘다(alpha 가 이미 문턱 아래라서). 그때마다 카메라를 맞추면
  // 노드를 가리킬 때마다 화면이 튄다.
  _engineStopped() {
    if (!this._cooling) return;
    this._cooling = false;
    this._fit();
  }

  _applyForces() {
    const fg = this.fg;
    if (!fg) return;
    const F = buildForces({ center: this.center, forces: this.forces });
    // 라이브러리가 기본으로 다는 가운데 힘은 걷어낸다 — 우리는 중심 노드를
    // 더 세게 당기는 x·y·z 힘으로 같은 일을 한다.
    fg.d3Force('center', null);
    fg.d3Force('charge', F.charge);
    fg.d3Force('collide', F.collide);
    fg.d3Force('link', F.link);
    fg.d3Force('x', F.x);
    fg.d3Force('y', F.y);
    fg.d3Force('z', F.z);
  }

  // 무엇을 어떻게 그릴지 라이브러리에 건네는 함수들. **한 번만 건다** —
  // 이 중 `nodeThreeObject` 와 `linkWidth` 를 다시 걸면 라이브러리가 노드·선
  // 객체를 통째로 **다시 만든다**(three-forcegraph 의 `dataMapper.clear()`).
  // 조명은 초당 몇 번씩 바뀌므로 그 길로 가면 안 된다 — 그래서 조명이 만지는
  // 것(`_relight`)과 크기가 만지는 것(`_resizeNodes`)을 갈라 두었다.
  _accessors() {
    if (!this.fg) return;
    this.fg.nodeThreeObject((n) => this._nodeObject(n));
    this._resizeNodes();
  }

  // 노드 크기·선 굵기 배율이 바뀌었다. 객체를 다시 만드는 길이라 슬라이더가
  // 움직일 때만 지난다.
  _resizeNodes() {
    const fg = this.fg;
    if (!fg) return;
    fg.nodeVal((n) => Math.max(n.r || 1, 0.5) ** 3)
      .linkWidth((e) => this.edgeWidth(e));
    this._relight();
  }

  // 조명·색·화살촉. 가리킴·고름·필터·테마가 바뀔 때 부른다.
  _relight() {
    const fg = this.fg;
    if (!fg) return;
    fg.nodeColor((n) => this._nodeColor(n))
      .nodeVisibility((n) => this.nodeShown(n.id))
      .linkVisibility((e) => this.edgeShown(e))
      .linkColor((e) => this.edgeColor(e))
      .linkMaterial((e) => this._edgeMaterial(e))
      .linkDirectionalArrowLength((e) => this.arrowLength(e))
      .linkDirectionalArrowColor((e) => this.edgeColor(e));
    for (const n of this.nodes) {
      const obj = this._objs.get(n.id);
      if (obj) this._dressNode(n, obj);
    }
  }

  // 테마가 바뀌면 색을 다시 먹인다 (three 는 CSS 변수를 못 읽는다).
  _repaint() {
    this._light = isLight();
    const c = chrome();
    this.fg?.backgroundColor(c.surface);
    for (const m of this._mats.values()) m.dispose?.();
    this._mats.clear();
    for (const [id, obj] of this._objs) {
      const n = this.byId.get(id);
      if (!n) continue;
      obj.label.strokeColor = c.surface;
      obj.label.color = this._labelColor(n);
      if (obj.alt) { obj.alt.strokeColor = c.surface; obj.alt.color = c.textDim; }
    }
    this._relight();
  }

  // --- 부호 -------------------------------------------------------------
  //
  // 조명. 가리키는 동안은 hover 가, 손을 떼면 골라 둔 노드가 이어받는다 —
  // 빈 곳을 누르기 전까지 유지된다.
  _spot() {
    if (this.causalView) return this.hover;
    return this.hover ?? (this.byId.has(this.selected) ? this.selected : null);
  }

  _lit(id) {
    const spot = this._spot();
    if (!spot) return true;
    if (this.causalView) {
      const reach = this.causalReachOf(spot);
      return id === spot || reach.nodes.has(id);
    }
    return id === spot || this.neighborsOf(spot).has(id);
  }

  _nodeColor(n) {
    const base = nodeColor(n.type, n.group);
    return this._lit(n.id) ? base : withAlpha(base, DIM_ALPHA);
  }

  // 선은 회색뿐이다 — 인과도 여기서는 회색이다(인과는 굵기가 말한다).
  // 가리킨 노드에 붙은 선만 밝아지고 나머지는 물러난다. 강조색(보라)은
  // 노드의 상태 링에만 둔다 (2026-09-05 사용자 결정).
  edgeColor(e) {
    const c = chrome();
    if (this.causalView) {
      const spot = this._spot();
      const on = !spot || this.causalReachOf(spot).edges.has(edgeKey(e));
      return on ? c.causeLit : withAlpha(c.edgeLit, 0.18);
    }
    const spot = this._spot();
    const active = spot && (e.s === spot || e.t === spot);
    if (spot && !active) return c.edgeSoft;
    if (active) return e.kind === 'same_as' ? c.edgeLitSame : c.edgeLit;
    return e.kind === 'same_as' ? c.edgeSame : c.edgeBase;
  }

  // **3D 에서 굵기는 인과 하나만 진다.** 2D 에서는 가리킨 노드의 선도 굵어졌지만
  // (1.1 → 1.8px), 3D 에서 굵기를 바꾸면 라이브러리가 선 객체를 통째로 다시
  // 만들어야 하고 — 무엇보다 한 부호에 뜻이 둘이 된다 (§0.2). 조명은 밝기가
  // 말한다 (`edgeColor`). 굵기가 말하는 것은 인과뿐이다.
  edgeWidth(e) {
    let w = e.kind === 'same_as' ? LINK_W.same : this.causalView ? LINK_W.lit : LINK_W.base;
    // 인과(원인 → 결과)는 다른 관계보다 굵다. 이 그래프가 온톨로지인 이유가
    // 이 선이라, 참여·장소 선 사이에서 같은 굵기로 묻히면 안 된다.
    if (e.type === 'caused') w += CAUSE_W;
    // 0 이 되면 라이브러리가 관 대신 실(THREE.Line)로 그린다 — 그러면 굵기도
    // 파선 무늬도 못 싣는다.
    return Math.max(0.2, w * this.display.lineScale);
  }

  // 화살촉은 방향이 뜻인 관계에만. 라이브러리가 도착 노드의 반지름을 빼고
  // 세우므로 2D 의 `r + 3` 자리와 같다.
  arrowLength(e) {
    if (!this.display.arrows) return 0;
    if (e.kind === 'same_as' || MUTUAL.has(e.type)) return 0;
    const spot = this._spot();
    if (spot && !this.causalView && !(e.s === spot || e.t === spot)) return 0;
    return ARROW_LEN;
  }

  // **출처의 확실성은 파선이다 — 3D 에서는 파선 무늬를 입힌 관으로 그린다.**
  //
  // 2D 에서는 `setLineDash` 한 줄이었다. 3D 의 선은 원기둥이라 무늬를 못
  // 넣는다고 보고 다른 부호로 옮길 뻔했지만, 옮길 자리가 없었다 — 색상은
  // 타입이(노드), 굵기는 인과가, 투명도는 조명이 이미 쥐고 있다 (§0.2 한
  // 부호에 뜻 하나). 그래서 부호를 옮기지 않고 **무늬를 되찾았다**: 원기둥의
  // uv 는 길이 방향으로 0→1 이라, 줄무늬 알파맵을 길이 방향으로 되풀이하면
  // 관이 마디로 끊긴다. 굵기(인과)도 그대로 산다 — 인과 엣지 2,604건 중
  // 2,575건이 conf<1 이라(실측 2026-09-11), 파선이 굵기를 먹었으면 인과는
  // 화면에서 사실상 사라졌을 것이다.
  //
  // 마디 수는 링크 길이와 무관하게 일정하다(무늬는 관에 붙어 늘어난다) —
  // 마디의 '길이'가 아니라 '끊겨 있음'이 뜻이므로 그래도 읽힌다.
  _edgeMaterial(e) {
    const dashes = e.kind === 'same_as' ? DASH.same : (e.conf ?? 1) < 1 ? DASH.infer : 0;
    if (!dashes || !this.three) return null;   // 실선은 라이브러리 재질에 맡긴다
    return this._dashMaterial(this.edgeColor(e), dashes);
  }

  _dashMaterial(color, dashes) {
    const key = `${color}|${dashes}`;
    let m = this._mats.get(key);
    if (!m) {
      const T = this.three;
      const a = colorAlpha(color);
      m = new T.MeshLambertMaterial({
        color: new T.Color(colorSolid(color)),
        alphaMap: this._dashTexture(dashes),
        alphaTest: 0.4,
        transparent: true,
        opacity: a,
        depthWrite: a >= 1,
      });
      this._mats.set(key, m);
    }
    return m;
  }

  _dashTexture(dashes) {
    let tex = this._texes.get(dashes);
    if (!tex) {
      const T = this.three;
      const cv = document.createElement('canvas');
      cv.width = 4; cv.height = 32;
      const g = cv.getContext('2d');
      g.fillStyle = '#000'; g.fillRect(0, 0, 4, 32);
      g.fillStyle = '#fff'; g.fillRect(0, 0, 4, 19);   // 마디 6 : 빈 곳 4 (2D 의 `5 4`)
      tex = new T.CanvasTexture(cv);
      tex.wrapS = T.RepeatWrapping;
      tex.wrapT = T.RepeatWrapping;
      tex.repeat.set(1, dashes);
      this._texes.set(dashes, tex);
    }
    return tex;
  }

  // --- 노드에 붙는 것 (상태 링 · 이름표) ---------------------------------
  //
  // Obsidian 은 초점 노드를 강조색으로 **칠하지만** 우리 노드는 타입 색을
  // 지고 있으므로 **두른다.** 3D 의 고리(torus)는 옆에서 보면 사라지므로
  // 스프라이트로 두른다 — 스프라이트는 늘 카메라를 마주 보니 어느 각도에서
  // 봐도 2D 의 링과 같은 그림이다.
  _nodeObject(n) {
    if (!this.three || !this.SpriteText) return null;
    let obj = this._objs.get(n.id);
    if (!obj) {
      const T = this.three;
      const group = new T.Group();
      const ring = new T.Sprite(new T.SpriteMaterial({
        map: this._ringTexture(), transparent: true, depthWrite: false, depthTest: false,
      }));
      ring.visible = false;
      group.add(ring);
      const label = this._sprite(n.label || '', this._labelColor(n));
      group.add(label);
      let alt = null;
      const co = coName(n);
      if (co) { alt = this._sprite(co, chrome().textDim); group.add(alt); }
      // 글자 상자의 가로세로 비 — 화면 크기를 다시 먹일 때 이 비를 지킨다
      obj = { group, ring, label, alt,
              wide: label.scale.x / label.scale.y,
              wideAlt: alt ? alt.scale.x / alt.scale.y : 1 };
      this._objs.set(n.id, obj);
    }
    this._dressNode(n, obj);
    return obj.group;
  }

  // **글자는 빈 채로 세우고 마지막에 넣는다.** SpriteText 는 속성을 넣을
  // 때마다 캔버스에 글자를 다시 구워 텍스처를 만든다 — 글자를 먼저 주면
  // 노드마다 다섯 번씩 굽는다.
  _sprite(text, color) {
    const s = new this.SpriteText('', LABEL_BAKE, color);
    s.fontFace = FONT;
    s.fontWeight = '600';             // 3D 는 작게 보이는 자리가 많아 굵게 둔다
    s.strokeWidth = 1.4;              // 글자에 바탕색 외곽선 — 선 위에서도 읽힌다
    s.strokeColor = chrome().surface;
    s.padding = 0.4;                  // 외곽선이 상자 끝에서 잘리지 않게
    s.text = text;
    s.material.depthWrite = false;
    s.material.transparent = true;
    s.renderOrder = 20;
    return s;
  }

  _labelColor(n) {
    const c = chrome();
    return n.id === this._spot() || n.id === this.center || n.id === this.selected ? c.text : c.textDim;
  }

  // 상태 링과 이름표의 자리·색. 노드 크기가 바뀌면 같이 따라간다.
  _dressNode(n, obj) {
    const c = chrome();
    const r = n.r || 6;
    const state = n.id === this.selected ? 'selected'
      : n.id === this.center ? 'center'
        : n.id === this._spot() ? 'hover' : null;
    obj.ring.visible = Boolean(state) && this._lit(n.id);
    if (state) {
      const size = (r + RING_GAP) * 2;
      obj.ring.scale.set(size, size, 1);
      obj.ring.material.color.set(state === 'selected' ? c.accent : state === 'center' ? c.ring : c.accentSoft);
      obj.ring.material.opacity = state === 'center' ? 0.45 : 1;
    }
    // **값이 그대로면 건드리지 않는다.** SpriteText 는 색·크기를 넣을 때마다
    // 캔버스에 글자를 다시 그려 텍스처를 새로 만든다. 가리킬 때마다 노드 120개의
    // 텍스처를 다시 구우면 그때마다 프레임이 끊긴다.
    const color = this._labelColor(n);
    if (obj.label.color !== color) obj.label.color = color;
    // 이름표의 크기와 자리는 카메라가 정한다 (`_placeLabels`) — 화면에서 늘
    // 같은 크기여야 하므로 거리마다 다시 먹인다.
  }

  // 노드에 붙였던 스프라이트를 걷는다. 이름표는 노드마다 제 텍스처(글자를
  // 구운 캔버스)를 들고 있어 그냥 버리면 GPU 메모리에 쌓인다. 링의 무늬는
  // 모두가 나눠 쓰는 것이라 버리지 않는다.
  _dropObjs() {
    for (const o of this._objs.values()) {
      for (const s of [o.label, o.alt]) {
        if (!s) continue;
        s.parent?.remove?.(s);
        s.material?.map?.dispose?.();
        s.material?.dispose?.();
      }
      o.ring?.parent?.remove?.(o.ring);
      o.ring?.material?.dispose?.();
    }
    this._objs.clear();
    this._shownLabels = new Set();
  }

  _ringTexture() {
    let tex = this._texes.get('ring');
    if (!tex) {
      const T = this.three;
      const cv = document.createElement('canvas');
      cv.width = 96; cv.height = 96;
      const g = cv.getContext('2d');
      g.strokeStyle = '#fff';
      g.lineWidth = 7;
      g.beginPath();
      g.arc(48, 48, 42, 0, Math.PI * 2);
      g.stroke();
      tex = new T.CanvasTexture(cv);
      this._texes.set('ring', tex);
    }
    return tex;
  }

  // --- 프레임 -----------------------------------------------------------
  //
  // 렌더는 라이브러리가 한다. 우리 루프가 하는 일은 셋뿐이다 — 테마가
  // 바뀌었는지 보고, **이름표를 세울지 말지 재고**, 라이브러리의 렌더 고리가
  // 살아 있는지 본다.
  _frame() {
    if (this._stopped) return;
    this._frames++;
    if (isLight() !== this._light) this._repaint();
    // 3프레임에 한 번. 이름표 자리는 카메라가 움직여야 바뀌고, 매 프레임
    // 재도 눈에 보이는 차이가 없다.
    if (this._frames % 3 === 0) this._placeLabels();
    if (this._frames % 90 === 0) this._watchLoop();
    this._raf = requestAnimationFrame(() => this._frame());
  }

  _tick() {
    this._ticked = true;   // 배치가 섰다 — 이제부터 되데울 수 있다
    this._ticks++;
    // **식을 때까지 카메라가 따라간다.** 한 번만 맞추면 그 뒤로도 배치가
    // 계속 퍼져서 결국 화면 밖으로 나간다. 사용자가 화면을 돌리기 시작하면
    // 그때부터 손을 뗀다 (controls 의 'start').
    if (!this.autoFit) return;
    if (this._ticks === 20 || (this._ticks > 20 && this._ticks % 60 === 0)) this._fit();
  }

  // **노드 구름을 화면에 꽉 채운다** (2D 의 `fitView(70)` 자리).
  //
  // 라이브러리의 `zoomToFit` 은 쓰지 않는다. 그것은 (1) 노드의 **three 객체
  // 상자**를 재므로 우리가 노드에 붙인 이름표·상태 링까지 상자에 넣고,
  // (2) 상자의 가장 긴 변을 `atan` 으로 나눠 거리를 잡아 늘 멀찍이 선다.
  // 실측 2026-09-11: 반지름 650 짜리 구름에 카메라가 2308 에 서서 그래프가
  // 1084×737 화면의 가로 350px 만 썼다 (노드가 2~6px 이라 '크기 = 차수'가
  // 안 읽혔다).
  //
  // 그래서 직접 잰다. **노드의 자리와 반지름만** 세고(이름표는 상자를 불리지
  // 않는다), 지금 보고 있는 쪽을 지킨 채 거리만 고친다. 노드 하나가 화면
  // 안에 들려면 카메라에서 그 노드까지의 깊이 d 와 가로·세로 어긋남 u·v 에
  // 대해 `거리 ≥ d + u/tanH` 이고 `거리 ≥ d + v/tanV` 여야 한다 — 그중 가장
  // 먼 것이 답이다. 여백(FIT_PAD)은 시야각을 그만큼 좁혀서 넣는다.
  _fit(ms = null) {
    const fg = this.fg;
    if (!fg || !this.autoFit || !this.nodes.length || !this.three) return;
    let cam;
    try { cam = fg.camera(); } catch { return; }
    if (!cam) return;
    const shown = this.nodes.filter((n) => this.nodeShown(n.id) && Number.isFinite(n.x));
    if (!shown.length) return;
    const T = this.three;
    cam.updateMatrixWorld?.();
    const lo = [Infinity, Infinity, Infinity];
    const hi = [-Infinity, -Infinity, -Infinity];
    for (const n of shown) {
      const p = [n.x, n.y, n.z || 0];
      const r = n.r || 6;
      for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], p[i] - r); hi[i] = Math.max(hi[i], p[i] + r); }
    }
    const center = new T.Vector3((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
    const dir = new T.Vector3().subVectors(cam.position, center);
    if (!(dir.lengthSq() > 1e-6)) dir.set(0, 0, 1);
    dir.normalize();
    const right = new T.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).normalize();
    const up = new T.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).normalize();
    const W = this.container.clientWidth || 800;
    const H = this.container.clientHeight || 600;
    const tanV0 = Math.tan(((cam.fov || 50) * Math.PI) / 360);
    const tanV = tanV0 * Math.max(0.25, (H - FIT_PAD * 2) / H);
    const tanH = tanV0 * (W / H) * Math.max(0.25, (W - FIT_PAD * 2) / W);
    const rel = new T.Vector3();
    let dist = 120;
    for (const n of shown) {
      rel.set(n.x, n.y, n.z || 0).sub(center);
      const d = rel.dot(dir);
      const r = n.r || 6;
      dist = Math.max(dist,
        d + (Math.abs(rel.dot(right)) + r) / tanH,
        d + (Math.abs(rel.dot(up)) + r) / tanV);
    }

    // **그러고 한 번 더 다듬는다.** 위의 셈은 상자의 한가운데를 바라본다고
    // 보고 잰 것인데, 원근에서는 가까운 노드가 더 크게 벌어지므로 구름의
    // *그림자*는 한가운데에 오지 않는다 — 실측(120개 구름)에서 아래는 여백에
    // 딱 닿고 위는 73px 이 남아 세로를 87% 밖에 못 썼다. 그래서 실제로 찍어
    // 보고(깊이로 나눈 자리) 어긋난 만큼 바라보는 곳을 옮기고 거리를 곱한다.
    // 네 번이면 0.1% 안으로 붙는다.
    const target = center.clone();
    const cp = new T.Vector3();
    for (let pass = 0; pass < 4; pass++) {
      cp.copy(target).addScaledVector(dir, dist);
      let uLo = Infinity, uHi = -Infinity, vLo = Infinity, vHi = -Infinity;
      for (const n of shown) {
        rel.set(n.x, n.y, n.z || 0).sub(cp);
        const depth = -rel.dot(dir);
        if (!(depth > 1)) continue;             // 카메라 뒤이거나 코앞
        const rr = (n.r || 6) / depth;
        const u = rel.dot(right) / depth;
        const v = rel.dot(up) / depth;
        uLo = Math.min(uLo, u - rr); uHi = Math.max(uHi, u + rr);
        vLo = Math.min(vLo, v - rr); vHi = Math.max(vHi, v + rr);
      }
      if (!Number.isFinite(uLo) || !Number.isFinite(vLo)) break;
      target.addScaledVector(right, ((uLo + uHi) / 2) * dist)
            .addScaledVector(up, ((vLo + vHi) / 2) * dist);
      const need = Math.max((uHi - uLo) / 2 / tanH, (vHi - vLo) / 2 / tanV);
      if (Number.isFinite(need) && need > 0) dist = Math.max(60, dist * need);
    }

    this._fitDist = dist;
    fg.cameraPosition(
      { x: target.x + dir.x * dist, y: target.y + dir.y * dist, z: target.z + dir.z * dist },
      target,
      ms ?? (this._fitted ? 700 : 0),
    );
    this._fitted = true;
  }

  // **이름표는 자리가 있으면 붙이고 없으면 만다** (2D 와 같은 규칙, 자만
  // 3D 가 되었다). 노드를 화면 좌표로 옮겨 글자 상자가 겹치는지 실제로
  // 잰다 — '차수 6 이상만' 같은 기준은 화면 사정과 무관해서, 왕조를 중심에
  // 놓으면 왕후 수십 명이 이름 없는 파란 점이 된다.
  //
  // 3D 라서 더해진 것 셋:
  //   (1) **글자를 화면 크기에 맞춰 다시 키운다** — 스프라이트는 멀어지면
  //       작아지는데, 그래프가 화면에 꽉 찬 거리에서 5px 글자는 못 읽는다.
  //       2D 가 `/k` 로 하던 일이고, 그래서 상자도 그냥 픽셀로 잰다.
  //   (2) 카메라 뒤로 넘어간 노드는 아예 세지 않는다.
  //   (3) 멀어지면 흐려진다 — **거리**가 2D 의 배율 자리를 대신한다
  //       (`labelAlpha`, 자는 그 그래프가 화면에 꽉 차는 거리 `_fitDist`).
  _placeLabels() {
    const fg = this.fg;
    if (!fg || !this.three || !this._objs.size) return;
    let cam;
    try { cam = fg.camera(); } catch { return; }
    if (!cam) return;
    const W = this.container.clientWidth || 800;
    const H = this.container.clientHeight || 600;
    const fov = ((cam.fov || 50) * Math.PI) / 180;
    const perWorld = H / (2 * Math.tan(fov / 2));   // 거리 1 에서 1px 이 되는 월드 길이의 역수
    const V = (this._vec ||= new this.three.Vector3());
    const focus = this._spot() || this.selected;
    const rank = (n) => (n.id === focus ? 3 : n.id === this.center ? 2 : 0) + Math.min((n.degree || 0) / 40, 1);
    const shown = this._shownLabels;
    const next = new Set();
    const placed = [];
    const cands = this.nodes
      .filter((n) => this._objs.has(n.id) && this.nodeShown(n.id) && this._lit(n.id))
      .sort((a, b) => rank(b) - rank(a));

    for (const n of this.nodes) {
      const o = this._objs.get(n.id);
      if (o) { o.label.visible = false; if (o.alt) o.alt.visible = false; }
    }
    if (!this.showLabels) { this._shownLabels = next; return; }

    for (const n of cands) {
      const o = this._objs.get(n.id);
      const strong = n.id === focus || n.id === this.center;
      V.set(n.x || 0, n.y || 0, n.z || 0);
      const dist = V.distanceTo(cam.position);
      V.project(cam);
      if (V.z > 1) continue;                       // 카메라 뒤
      const k = perWorld / Math.max(dist, 1);      // 월드 → 화면 픽셀
      const sx = (V.x * 0.5 + 0.5) * W;
      const sy = (-V.y * 0.5 + 0.5) * H;
      const px = strong ? LABEL_PX.strong : LABEL_PX.normal;
      const altPx = o.alt ? LABEL_PX.alt : 0;
      const w = px * o.wide + 6;
      const h = px + altPx;
      const box = { x: sx - w / 2, y: sy + (n.r || 6) * k, w, h };
      // **지난 프레임에 떠 있던 이름은 조금 더 버틴다.** 겹침 판정은
      // 예/아니오라서, 노드가 1px 움직일 때마다 판정이 뒤집히면 이름이
      // 초당 몇 번씩 깜빡인다. 한 번 뜬 이름은 3px 더 겹쳐야 물러난다.
      const test = shown.has(n.id) ? inset(box, 3) : box;
      if (!strong && placed.some((p) => overlaps(p, test))) continue;
      placed.push(box);
      next.add(n.id);
      const a = strong ? 1 : labelAlpha(dist, this.display.textFade, this._fitDist);
      if (a <= 0) continue;
      // 화면에서 px 이 되도록 월드 크기를 다시 먹인다
      const size = px / k;
      o.label.scale.set(size * o.wide, size, 1);
      o.label.position.set(0, -((n.r || 6) + 4 / k + size / 2), 0);
      o.label.visible = true;
      o.label.material.opacity = a;
      if (o.alt) {
        const alt = altPx / k;
        o.alt.scale.set(alt * o.wideAlt, alt, 1);
        o.alt.position.set(0, o.label.position.y - size / 2 - alt * 0.6, 0);
        o.alt.visible = true;
        o.alt.material.opacity = a;
      }
    }
    this._shownLabels = next;
  }

  _resize() {
    const fg = this.fg;
    if (!fg) return;
    const w = this.container.clientWidth || 800;
    const h = this.container.clientHeight || 600;
    // **크기가 그대로면 아무것도 하지 않는다.** ResizeObserver 는 상세
    // 패널이 열리거나 소수점 반올림이 달라져도 불린다. 그리고 3D 에서는
    // 크기가 바뀌어도 배치를 데울 이유가 없다 — 끌어당기는 중심이 원점이라
    // 창과 무관하다 (2D 에서는 화면 가운데가 바뀌어 데워야 했고, 그게 배치가
    // 영영 안 식던 병의 자리였다).
    if (w === this._w && h === this._h) return;
    this._w = w;
    this._h = h;
    fg.width(w).height(h);
  }

  // --- 몸짓 -------------------------------------------------------------
  //
  // 한 번 누르기 = 고르기, 두 번 = 펼치기. 3D 라이브러리에는 더블클릭
  // 신호가 없어 같은 노드를 320ms 안에 두 번 누른 것으로 잰다. 첫 번째
  // 누름은 그대로 고르기라 반응이 늦지 않는다.
  _click(node) {
    const now = Date.now();
    if (this._lastClick && this._lastClick.id === node.id && now - this._lastClick.t < 320) {
      this._lastClick = null;
      this.onExpand(node);
      return;
    }
    this._lastClick = { id: node.id, t: now };
    this.selected = node.id;
    this._relight();
    this.onSelect(node);
  }

  _hover(node) {
    const id = node ? node.id : null;
    if (id === this.hover) return;
    this.hover = id;
    this._relight();
    this.onHover(node || null);
  }

  // 빈 곳을 누르면 조명이 꺼진다. 도면에서는 주변 관계 그래프로 돌아가는 몸짓이다.
  _clearSpot() {
    if (this.causalView) { this.exitCausal(); return; }
    this.selected = null;
    this._relight();
  }

  // --- 인과 도면의 살림 --------------------------------------------------
  //
  // 열 머리를 글자로 적는다 — 왼쪽이 원인, 오른쪽이 결과라는 것을 자리만으로
  // 말하지 않는다 (§0.4).
  _captionsFor(laid) {
    if (!this.fg || !this.three || !this.SpriteText) return;
    let scene;
    try { scene = this.fg.scene(); } catch { return; }
    for (const s of this._captions) scene.remove?.(s);
    this._captions = [];
    if (!laid) return;
    let top = 0;
    for (const n of laid.nodes) top = Math.max(top, -n.y);
    for (const d of laid.depths) {
      if (d === 0) continue;
      const side = d < 0 ? COL_CAPTION.cause : COL_CAPTION.effect;
      const s = this._sprite(side[Math.min(Math.abs(d) - 1, side.length - 1)], chrome().textDim);
      s.scale.multiplyScalar(2.2);        // 도면은 멀리서 보므로 열 머리는 크게
      s.position.set(d * COL, top + ROW, 0);
      this._captions.push(s);
      scene.add?.(s);
    }
  }

  // 도면은 평면이라 카메라를 정면에 세운다. 돌려볼 수는 있다.
  _faceCausal(laid) {
    if (!this.fg) return;
    let span = 200;
    for (const n of laid.nodes) span = Math.max(span, Math.abs(n.x) * 2, Math.abs(n.y) * 2);
    this.fg.cameraPosition({ x: 0, y: 0, z: span * 1.1 }, { x: 0, y: 0, z: 0 }, 700);
  }
}

// --- 도구 ---------------------------------------------------------------

// 또 하나의 이름(`names[1]`)은 **아랫줄에** 작게 쓴다. 옆에 이어 붙이면
// '기축옥사 · 정여립의 난' 이 한 줄로 길어져 이웃 이름표를 밀어낸다.
function coName(n) {
  return n.names && n.names.length > 1 ? n.names[1] : null;
}

function inset(b, m) {
  return { x: b.x + m, y: b.y + m, w: Math.max(b.w - m * 2, 1), h: Math.max(b.h - m * 2, 1) };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// `#rrggbb` → `rgba(r,g,b,a)`. three 는 rgba 문자열의 색을 읽고, 알파는
// 라이브러리가 `colorAlpha` 로 따로 읽어 재질의 투명도로 쓴다.
export function withAlpha(color, alpha) {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const v = parseInt(m[1], 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${alpha})`;
}

function colorAlpha(color) {
  const m = /rgba?\([^)]*,\s*([\d.]+)\s*\)/.exec(String(color));
  return m ? Number(m[1]) : 1;
}

// 알파를 뗀 색. three 의 Color 는 rgba 를 받으면 알파를 버리면서 콘솔에
// 경고를 찍는다 — 투명도는 재질이 따로 들므로 색만 준다.
function colorSolid(color) {
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/.exec(String(color));
  if (!m) return color;
  const h = (v) => Math.round(Number(v)).toString(16).padStart(2, '0');
  return `#${h(m[1])}${h(m[2])}${h(m[3])}`;
}

// **이름표는 멀어지면 흐려진다.** 2D 의 '텍스트 흐림 문턱'을 3D 로 옮긴 것
// (Obsidian 의 같은 손잡이). 2D 에서는 배율 k 가 자였고, 3D 에서는 카메라와
// 노드 사이의 거리가 그 자리다.
//
// **자는 그 그래프가 화면에 꽉 차는 거리(`fit`)다** — 절대 거리를 쓰면 안
// 된다. 그래프마다 크기가 다르고(노드 12개와 400개), 처음 열릴 때의 거리도
// 그만큼 다르다. 첫 판에 절대 거리(1000)를 걸었더니 노드 120개짜리 첫 화면이
// 2308 에서 열려 **이름표가 하나도 안 떴다** (2026-09-11 실측). 꽉 차는
// 거리를 1 로 놓으면 뜻이 그대로다: fade 0 이면 1.35배 물러나도 또렷하고,
// 기본 0.3 은 1.1배까지 또렷하다가 1.6배에서 사라지고, 1 이면 절반 거리까지
// 다가가야 뜬다. **첫 화면에는 늘 이름이 있다.**
export function labelAlpha(dist, fade, fit = 900) {
  const near = Math.max(1, fit) * (1.35 - fade * 0.85);
  const far = near * 1.45;
  return Math.max(0, Math.min(1, (far - dist) / (far - near)));
}

// 한 노드에서 `caused` 엣지를 따라 위(원인 쪽, 들어오는 선)·아래(결과 쪽,
// 나가는 선)로 닿는 노드와 그 선. 순환이 있어도 한 번씩만 밟는다. 인과
// 아닌 엣지와 필터로 끈 엣지는 건너뛴다.
export function causalReach(edges, id, shown = () => true) {
  const out = new Map();
  const into = new Map();
  for (const e of edges) {
    if (e.type !== 'caused' || !shown(e)) continue;
    if (!out.has(e.s)) out.set(e.s, []);
    if (!into.has(e.t)) into.set(e.t, []);
    out.get(e.s).push(e);
    into.get(e.t).push(e);
  }
  const nodes = new Set([id]);
  const keys = new Set();
  const walk = (adj, other) => {
    const stack = [id];
    const seen = new Set([id]);
    while (stack.length) {
      const n = stack.pop();
      for (const e of adj.get(n) || []) {
        keys.add(edgeKey(e));
        const m = other(e);
        if (seen.has(m)) continue;
        seen.add(m);
        nodes.add(m);
        stack.push(m);
      }
    }
  };
  walk(out, (e) => e.t);
  walk(into, (e) => e.s);
  return { nodes, edges: keys };
}

// 연도 한 줄. '1592-04-13' → '1592', '-0057-01-01' → '기원전 57'. 모르면 ''.
function yearOf(date) {
  if (!date) return '';
  const m = String(date).match(/^(-?)(\d{1,4})/);
  if (!m) return '';
  const y = parseInt(m[2], 10);
  return m[1] ? `기원전 ${y}` : String(y);
}

// `/api/chain` 의 나무를 열로 세운다. 가운데(0열)가 고른 노드, 왼쪽(-1, -2…)
// 이 원인, 오른쪽(+1, +2…)이 결과. 열은 수기야마(Sugiyama) 층 매기기의
// '가장 긴 경로'다 — 한 노드가 여러 가지에 나와도 한 번만 서고, 그 노드에서
// 고른 노드까지 가장 긴 길만큼 떨어진 열에 선다. 그래야 **모든 선이
// 왼쪽에서 오른쪽으로만** 간다 (가까운 열에 두면 후금 → 정묘호란이 같은
// 열 안에서 위아래로 서고, 방향이 사라진다). 열 안은 연도순(모르는 것은
// 뒤), 같은 해면 이름순. 인과가 없으면 null.
export function causalLayout(chain, { col = COL, row = ROW } = {}) {
  if (!chain || !(chain.causes?.length || chain.effects?.length)) return null;
  const side = new Map([[chain.center, 0]]);   // -1 원인 쪽 · +1 결과 쪽
  const edges = new Map();
  const walk = (items, parent, sign) => {
    const stack = (items || []).map((it) => [it, parent]);
    while (stack.length) {
      const [it, from] = stack.pop();
      if (!chain.nodes?.[it.id]) continue;
      if (!side.has(it.id)) side.set(it.id, sign);
      const [s, t] = sign < 0 ? [it.id, from] : [from, it.id];
      const key = `${s}|${t}|caused`;
      if (!edges.has(key)) {
        edges.set(key, { s, t, type: 'caused', kind: 'edge', label: it.kind || '원인',
                         how: it.how || '', conf: it.confidence ?? 1, sources: it.sources || [] });
      }
      for (const child of it.children || []) stack.push([child, it.id]);
    }
  };
  walk(chain.causes, chain.center, -1);
  walk(chain.effects, chain.center, +1);

  // 가장 긴 경로 층 매기기. 원인 쪽은 '이 노드가 부른 것' 중 가장 먼 열의
  // 한 칸 왼쪽, 결과 쪽은 '이 노드를 부른 것' 중 가장 먼 열의 한 칸 오른쪽.
  // 순환(두 사건이 서로를 불렀다고 적힌 경우)은 되돌아오는 선을 무시한다.
  const next = new Map();   // 원인 쪽: s → [t…]
  const prev = new Map();   // 결과 쪽: t → [s…]
  for (const e of edges.values()) {
    if (side.get(e.s) === -1 && side.get(e.t) !== 1) (next.get(e.s) || next.set(e.s, []).get(e.s)).push(e.t);
    if (side.get(e.t) === 1 && side.get(e.s) !== -1) (prev.get(e.t) || prev.set(e.t, []).get(e.t)).push(e.s);
  }
  const depthOf = new Map([[chain.center, 0]]);
  const onPath = new Set();
  const depth = (id, adj, sign) => {
    if (depthOf.has(id)) return depthOf.get(id);
    if (onPath.has(id)) return 0;          // 순환 — 이 선은 층에 안 들어간다
    onPath.add(id);
    let far = 0;
    for (const other of adj.get(id) || []) far = Math.max(far, Math.abs(depth(other, adj, sign)));
    onPath.delete(id);
    const d = sign * (far + 1);
    depthOf.set(id, d);
    return d;
  };
  for (const [id, s] of side) {
    if (s === -1) depth(id, next, -1);
    else if (s === 1) depth(id, prev, 1);
  }

  const columns = new Map();
  for (const [id, d] of depthOf) {
    if (!columns.has(d)) columns.set(d, []);
    columns.get(d).push(id);
  }
  const nodes = [];
  const info = (id) => chain.nodes?.[id] || { id, label: id, type: 'event' };
  for (const [d, ids] of columns) {
    ids.sort((p, q) => {
      const a = info(p).start || '', b = info(q).start || '';
      if (a && b && a !== b) return a < b ? -1 : 1;
      if (!!a !== !!b) return a ? -1 : 1;
      return (info(p).label || '').localeCompare(info(q).label || '', 'ko');
    });
    ids.forEach((id, i) => {
      const n = info(id);
      nodes.push({
        ...n,
        names: [n.label, yearOf(n.start)].filter(Boolean),
        degree: n.degree || 0,
        depth: d,
        x: d * col,
        y: (i - (ids.length - 1) / 2) * row,
        vx: 0, vy: 0,
        r: d === 0 ? 10 : 7,
      });
    });
  }
  const depths = [...columns.keys()].sort((a, b) => a - b);
  const count = (sign) => [...depthOf.values()].filter((d) => Math.sign(d) === sign).length;
  return { nodes, edges: [...edges.values()], depths, causes: count(-1), effects: count(1) };
}

// 서로 같은 것을 뜻하는 관계는 **방향을 키에서 뺀다** — 두 방향이 다 와도 선은 한 줄이다.
function edgeKey(e) {
  return pairKey(e.s, e.t, e.type);
}
function pairKey(s, t, type) {
  return MUTUAL.has(type) ? `${[s, t].sort().join('|')}|${type}` : `${s}|${t}|${type}`;
}
