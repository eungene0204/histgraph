// 캔버스 렌더러.
//
// 배치는 d3-force 가 맡고(layout.js), 이 파일은 **그리기와 상호작용만**
// 한다. 색·노드·이름표·화살촉은 손대지 않았다 — 팔레트는 색약 검증기
// (tools/check_palette.py)가 이 파일의 값을 직접 읽어 잰다.
//
// React 가 감싸긴 하지만 이 클래스는 React 를 모른다. 캔버스는 매 프레임
// 60번 다시 그려지는 곳이라 가상 DOM 을 통과시킬 이유가 없다.
import { isLight } from './theme.js';
import { buildSimulation, retarget, nodeRadius, DEFAULT_FORCES } from './layout.js';

const TAU = Math.PI * 2;
// style.css 의 --font-interface 와 같은 순서. 캔버스는 CSS 변수를 못 읽는다.
const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif';

// **시뮬레이션은 화면 주사율과 무관하게 초당 60틱으로 돈다.** 힘 계수가
// 전부 "한 틱당"으로 잡혀 있어서, 프레임마다 한 번 돌리면 120Hz 화면
// (ProMotion)에서 같은 그래프에 힘이 두 배로 들어간다.
const TICK_MS = 1000 / 60;

// 모양은 하나(원)로 두고, 색이 타입을 말한다.
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
// #1e1e1e 위에서 대비가 1.2·1.7 이라 작은 원이 보이지 않아(그대로 둔 것을
// 그려 보고 확인했다) 같은 색상으로 밝힌 값을 쓴다. **인물만 예외로 파랑**
// #3d84f5 다 — 팔레트를 씌운 뒤 사용자가 "인물 노드도 blue 로" 라고 했다
// (2026-09-06). 연표의 왕·대통령 재위 띠(timeline.js REIGN_COLOR)와 같은 파랑.
// 팔레트의 빨강 D62828 은 원색으로는 남는 자리가 없고, 작품(연빨강)에 밝힌
// 값으로만 남는다.
//
// 갈래는 색상 계열로 남는다 — 인물·단체는 파랑·크림, 사건은 주황, 장소·
// 유물·작품은 초록~노랑~연빨강~남색, 시대·직위는 남색·초록을 어둡게 누른
// 것. 화면이 먼저 네 덩어리로 읽히고 그 안에서 타입이 갈린다. 뼈대(시대·
// 직위)는 어둡게 묶어 물러나 있게 했다.
//
// 5.5 는 "다르다"이지 "나란히 놓지 않아도 읽힌다"가 아니다. 그래서 **색만
// 으로 읽어야 하는 자리를 만들지 않는다**: 범례는 색 견본 옆에 타입 이름을
// 적고, 노드를 고르면 상세 패널이 타입을 글자로 말한다.
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

// 노드 색은 타입이 정한다. 모르는 타입은 갈래로 물러난다. 테마는 그릴 때마다
// 읽는다 — 캔버스는 매 프레임 다시 그리므로 단추를 누르면 다음 프레임부터
// 새 색이다. 상세·연표의 색 점은 React 가 다시 그릴 때 따라온다.
export function nodeColor(type, group) {
  const [T, G] = isLight() ? [TYPE_COLOR_LIGHT, GROUP_COLOR_LIGHT] : [TYPE_COLOR, GROUP_COLOR];
  return T[type] || G[group] || G.thing;
}

// **서로 같은 것을 뜻하는 관계.** 두 가지가 여기서 따라 나온다.
//   1. 화살촉을 붙이지 않는다. 화살촉은 '누가 누구에게'를 말하는 부호인데, 방향이
//      없는 자리에 붙이면 없는 방향을 지어낸다 — 신사임당 → 이원수와 이원수 →
//      신사임당은 같은 말이다.
//   2. 선은 한 줄이다. 두 방향이 다 오면 같은 자리에 두 번 겹쳐 그려진다 (실측
//      2026-09-08: 배우자 네 쌍이 여덟 줄이었다 — 가리켰을 때 이름이 두 번 뜨고,
//      파선은 위상이 겹쳐 실선처럼 진해진다). 상세 패널은 이미 카드 한 장으로
//      접는다 (`relations.js SYMMETRIC`) — 캔버스만 안 접고 있었다.
// 한국사는 `spouse_of`, 개인 역사는 만남·친구·동료·같은 학교·함께 나눔·겹침
// (`life.SYMMETRIC`). same_as 는 관계가 아니라 이음이라 예전부터 화살촉이 없다.
// **`relative_of` 는 뺐다** — 대칭이지만 선 이름이 도착 쪽을 부르는 말이라
// ('나 → 나형철 · 형' = 나형철이 나의 형) 화살촉이 그 말의 주어를 정한다.
// `related_to` 도 뺐다 — 라벨이 '다음'이면 앞뒤가 있다 (`LABEL_DIR_HEAD`).
export const MUTUAL = new Set(['same_as', 'spouse_of',
  'met', 'friend_of', 'worked_with', 'schoolmate', 'shared_with', 'overlapped']);

// Obsidian 의 그래프 뷰를 따른다 (design.md §3). 바탕은 --background-primary,
// 선은 --graph-line (회색 한 가지), 가리킨 노드의 선과 테두리만 강조색.
// 선에 타입 색을 입히던 것을 걷어냈다 — 색은 점에만 있고 선은 조용하다.
// 두 벌이다 — CSS 변수를 캔버스가 못 읽으므로 style.css 의 값을 여기 옮겨 적었다.
const DARK = {
  surface: '#1e1e1e',                     // --background-primary
  edgeBase: '#4a4a4a',                    // --graph-line 보다 한 단 밝다 (1px 선은 #3f3f3f 로는 안 보인다)
  edgeSoft: 'rgba(74,74,74,0.35)',        // 가리키는 동안 물러난 선
  edgeSame: '#3f3f3f',                    // 동일 실체 (same_as) — 관계가 아니라 이음이라 더 어둡다
  edgeLit: '#a8a8a8',                     // 가리킨 노드에 붙은 선 — 보라가 아니라 밝은 회색 (2026-09-05 사용자 결정)
  edgeLitSame: '#7a7a7a',                 // 가리킨 노드의 same_as 선
  // 인과 도면의 선 — 연표의 '원인'과 같은 파랑(--color-blue) 계열. 주변
  // 관계 그래프에서는 인과도 회색 한 가지다 (2026-09-06 사용자: "처음부터
  // 보여주지 말고(그럼 너무 복잡해 보임)").
  causeLit: '#8cc4ea',
  accent: '#8a6cef',                      // --color-accent
  accentSoft: '#af9af4',                  // --color-accent-2
  text: '#dadada',                        // --text-normal
  textDim: 'rgba(218,218,218,0.62)',      // --text-muted 와 같은 무게
  ring: 'rgba(218,218,218,0.45)',         // 중심 노드의 테두리
};
// 라이트. 처음 값(선 #c4c4c4·글자 62%)은 흰 바탕에서 안 보였다 (2026-09-06
// 지적). 선은 Radix gray 9 (#8d8d8d) 수준으로, 가리킨 선은 글자만큼 어둡게.
// 값의 근거는 style.css 의 [data-theme="light"] 주석.
const LIGHT = {
  surface: '#ffffff',
  edgeBase: '#9a9a9a',                    // 흰 바탕 2.7:1 — 1px 선이 보이는 하한 근처
  edgeSoft: 'rgba(154,154,154,0.4)',
  edgeSame: '#b8b8b8',
  edgeLit: '#2e2e2e',                     // 가리킨 노드의 선 — 글자와 같은 무게
  edgeLitSame: '#6a6a6a',
  causeLit: '#2a6a9a',                    // --color-blue (라이트)
  accent: '#7a4be0',                      // hsl(258 80% 56%)
  accentSoft: '#9b76ea',                  // hsl(258 80% 68%)
  text: '#1f1f1f',
  textDim: 'rgba(31,31,31,0.72)',         // ≈ #5a5a5a — 보조 글자와 같은 무게
  ring: 'rgba(31,31,31,0.5)',
};
function chrome() { return isLight() ? LIGHT : DARK; }

// --- 인과 도면 ----------------------------------------------------------
//
// 노드를 누르면 캔버스가 **그 노드의 인과 도면**이 된다. 원인은 왼쪽 열,
// 결과는 오른쪽 열, 열 안은 연도순. 힘 배치는 멈춘다.
//
// 처음엔 주변 관계(이웃 120)의 힘 배치 위에 파란 인과 선을 얹었다.
// 2026-09-06 사용자: "인과관계 그래프가 너무 복잡하게 그려지고 있어서,
// 아무런 정보값이 없어. 팔란티어나 다른 회사의 그래프 디자인을 검색해서
// 공부해서 수정해봐." 찾아본 셋이 같은 말을 했다 — 팔란티어 Vertex 는
// 그래프 배치에 '계층(좌→우)'을 따로 두고 뿌리 노드를 골라 엣지 방향대로
// 층을 세운다. Cambridge Intelligence(KeyLines)는 힘 배치가 전체 모양만
// 보여주므로 흐름이 있는 자료는 '순차 배치(sequential layout)'로 층을
// 나눈다. 사건 인과 시각화 논문들(VAC2·DOMINO 등)은 인과 나무를 시간축을
// 따라 원인 → 결과의 흐름도로 그리고, 고른 사건에서 출발해 그 사건으로
// 이어지는 경로만 점진적으로 펼친다. 셋의 공통: **인과는 방향이 뜻이므로
// 층으로 세우고, 그 밖의 관계는 그리지 않는다.**
const COL = 230;   // 열(걸음) 간격
const ROW = 58;    // 한 열 안의 줄 간격 — 이름 두 줄(이름·연도)보다 넉넉히
// 열 머리. 걸음이 멀수록 말이 흐려진다 — '원인의 원인의 원인'은 안 읽힌다.
const COL_CAPTION = {
  cause: ['원인', '원인의 원인', '더 앞선 원인'],
  effect: ['결과', '결과의 결과', '더 뒤의 결과'],
};

export class GraphView {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.center = null;
    this.hover = null;
    this.selected = null;
    this.tx = 0;
    this.ty = 0;
    this.k = 1;
    this.sim = null;
    this.onSelect = opts.onSelect || (() => {});
    this.onExpand = opts.onExpand || (() => {});
    this.onHover = opts.onHover || (() => {});
    this.showLabels = true;
    // Obsidian 그래프 설정의 '표시'·'필터'·'힘' 절 (design.md §4).
    // nodeScale·lineScale 은 배율, textFade 는 이름표가 사라지는 확대 문턱
    // (0 = 늘 보임 · 1 = 많이 확대해야 보임), arrows 는 화살촉 여부.
    this.display = { nodeScale: 1, lineScale: 1, textFade: 0.3, arrows: true };
    this.hiddenEdgeTypes = new Set();   // 필터로 끈 관계 종류
    // 인과 도면 상태 (showCausal). 도면 밖이면 null. 들어가며 접어 둔 주변
    // 관계 그래프는 _saved 에 있다가 exitCausal 로 그대로 돌아온다.
    this.causalView = null;
    this._saved = null;
    this.onCausalExit = opts.onCausalExit || (() => {});
    this.forces = { ...DEFAULT_FORCES };

    // **여기서 한 번 정해 둔다.** _resize 는 배킹 크기가 그대로면 일찍
    // 돌아가는데, StrictMode 가 같은 캔버스에 GraphView 를 다시 세우면
    // (개발 서버 5173) 크기가 이미 맞아 그 길로 빠진다. 그때 dpr 이 없으면
    // setTransform 에 NaN 이 들어가 **캔버스가 변환을 통째로 무시하고**
    // 1배로 그린다 — 화면의 왼쪽 위 1/4 에만 그려지고, 지우는 자리도 그
    // 1/4 뿐이라 나머지 3/4 에 지난 프레임이 겹겹이 쌓인다
    // (실측 2026-09-08: 개인 역사 그래프가 잔상으로 뒤덮였다).
    this.dpr = window.devicePixelRatio || 1;

    this._acc = 0;
    this._prev = 0;
    this._raf = 0;
    this._shownLabels = new Set();
    this._stopped = false;

    this._bindEvents();
    this._resize();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(canvas.parentElement);
    this._raf = requestAnimationFrame((t) => this._frame(t));
  }

  // React 가 언마운트할 때 부른다. 안 부르면 RAF 루프와 ResizeObserver 가
  // 죽은 캔버스를 붙잡고 계속 돈다.
  destroy() {
    this._stopped = true;
    cancelAnimationFrame(this._raf);
    this._ro?.disconnect();
    this.sim?.stop();
  }

  get alpha() { return this.sim ? this.sim.alpha() : 0; }

  // --- 데이터 ---------------------------------------------------------

  // merge=true 면 기존 배치를 유지한 채 새 노드만 얹는다. 펼치기를 할
  // 때마다 화면이 통째로 다시 튀면 사용자는 방금 보던 것을 잃는다.
  setData(payload, { merge = false } = {}) {
    // 도면 위에 이웃을 얹지 않는다 — 검색·펼치기는 주변 관계 그래프의 일이다.
    if (this.causalView) this.exitCausal({ restore: merge });
    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 600;
    if (!merge) {
      this.nodes = [];
      this.edges = [];
      this.byId = new Map();
    }

    const incoming = new Set();
    let placed = 0;
    for (const n of payload.nodes) {
      incoming.add(n.id);
      let node = this.byId.get(n.id);
      if (!node) {
        // **나선 위에 고르게 놓는다.** 무작위로 뿌리면 노드 몇 개가 거의
        // 겹친 채 시작하고, 그 지점의 반발력이 폭발해 서로를 화면 밖으로
        // 튕겨낸다. 한번 멀리 나간 노드는 alpha 가 식은 뒤라 돌아오지
        // 못하고 그 자리에 굳는다 (실측: 117개 중 예닐곱이 그렇게 됐다).
        const anchor = this.byId.get(payload.center);
        const i = placed++;
        const a = i * 2.399963;             // 황금각 — 뭉치지 않고 퍼진다
        const d = 40 + 26 * Math.sqrt(i);
        node = {
          ...n,
          x: (anchor ? anchor.x : w / 2) + Math.cos(a) * d,
          y: (anchor ? anchor.y : h / 2) + Math.sin(a) * d,
          vx: 0, vy: 0,
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
    if (c && !merge) {
      c.x = w / 2;
      c.y = h / 2;
    }
    this.adjacency = null;
    this._reach = null;
    this._rebuildSim(w, h);
    this.autoFit = true;   // 사용자가 화면을 움직이기 전까지는 카메라가 따라간다
    // 첫 맞춤은 즉시. 처음부터 서서히 따라가면 그래프가 화면 밖에서
    // 반 초 동안 날아 들어온다.
    this._fitted = false;
    if (!merge) this.resetView();
    return incoming;
  }

  // 인과 도면으로 들어간다. `/api/chain` 의 나무를 열로 세우고(causalLayout)
  // 주변 관계 그래프는 접어 둔다. 인과가 없으면 false — 부르는 쪽이 전처럼
  // 주변 관계를 편다.
  showCausal(chain) {
    if (!causalLayout(chain)) return false;
    if (!this.causalView) {
      this._saved = { nodes: this.nodes, edges: this.edges, byId: this.byId, center: this.center,
                      tx: this.tx, ty: this.ty, k: this.k };
    }
    this.sim?.stop();
    this.sim = null;
    this.causalView = { chain, center: chain.center, causes: 0, effects: 0, depths: [] };
    this.selected = chain.center;
    this.hover = null;
    this._layoutCausal();
    return true;
  }

  // 도면을 **화면 자로** 세운다. 이름표는 배율과 무관하게 11px 인데 줄 간격을
  // 배율로 줄이면(fitView) 글자가 겹친다. 그래서 열 간격은 화면 폭을 열 수로
  // 나눈 것(120~230), 줄 간격은 화면 높이를 가장 긴 열의 줄 수로 나눈
  // 것(40~58)으로 정하고 배율 1 로 둔다. 그래도 폭이 넘치면 그만큼만 줄이되
  // 줄 간격은 화면에서 40px 아래로 안 내려가게 미리 키운다. 캔버스 크기가
  // 바뀌면(상세 패널이 열리면 폭이 준다) 다시 잰다 (_resize).
  _layoutCausal() {
    const { chain } = this.causalView;
    const W = this.canvas.clientWidth || 800;
    const H = this.canvas.clientHeight || 600;
    const probe = causalLayout(chain);
    const perColumn = new Map();
    for (const n of probe.nodes) perColumn.set(n.depth, (perColumn.get(n.depth) || 0) + 1);
    const tallest = Math.max(...perColumn.values());
    const cols = Math.max(probe.depths.length - 1, 1);
    const col = Math.max(120, Math.min(COL, (W - 160) / cols));
    const k = Math.min(1, (W - 60) / (col * cols + 100));
    const row = Math.max(40, Math.min(ROW, (H - 170) / Math.max(tallest - 1, 1))) / k;
    const laid = causalLayout(chain, { col, row });
    this.nodes = laid.nodes;
    this.edges = laid.edges;
    this.byId = new Map(laid.nodes.map((n) => [n.id, n]));
    this.center = chain.center;
    Object.assign(this.causalView, { causes: laid.causes, effects: laid.effects, depths: laid.depths, col });
    this.adjacency = null;
    this._reach = null;
    this._shownLabels = new Set();
    this.autoFit = false;
    // 도면의 상자를 화면 한가운데에 (열 머리 자리만큼 아래로)
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of laid.nodes) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    }
    this.k = k;
    this.tx = W / 2 - ((minX + maxX) / 2) * k;
    this.ty = H / 2 - ((minY + maxY) / 2) * k + 14;
  }

  // 도면에서 주변 관계 그래프로. 접어 둔 노드·자리·카메라가 그대로 돌아온다
  // (restore=false 면 곧 setData 가 덮어쓰므로 상태만 접는다).
  exitCausal({ restore = true } = {}) {
    if (!this.causalView) return;
    const s = this._saved;
    this._saved = null;
    this.causalView = null;
    this.hover = null;
    if (restore && s) {
      this.nodes = s.nodes; this.edges = s.edges; this.byId = s.byId; this.center = s.center;
      this.tx = s.tx; this.ty = s.ty; this.k = s.k;
      this.selected = null;
      this.adjacency = null;
      this._reach = null;
      this._shownLabels = new Set();
      this._rebuildSim(this.canvas.clientWidth, this.canvas.clientHeight);
      this.sim.alpha(0.12);   // 자리는 그대로, 살짝만 데운다
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

  // d3 의 forceLink 는 링크 배열을 자기 것으로 삼아 source/target 을 노드
  // 객체로 바꿔 끼운다. 그리기는 여전히 e.s / e.t 를 쓰므로 서로 밟지 않는다.
  // --- 설정 -------------------------------------------------------------
  setDisplay(patch) {
    const before = this.display.nodeScale;
    this.display = { ...this.display, ...patch };
    if (this.display.nodeScale !== before && this.nodes.length && !this.causalView) {
      for (const n of this.nodes) n.r = nodeRadius(n) * this.display.nodeScale;
      // 겹침 방지 반지름이 바뀌었으니 배치를 다시 데운다 (자리는 지킨다)
      this._rebuildSim(this.canvas.clientWidth, this.canvas.clientHeight);
      this.sim.alpha(0.4);
    }
  }

  setForces(patch) {
    this.forces = { ...this.forces, ...patch };
    if (!this.nodes.length || this.causalView) return;
    this._rebuildSim(this.canvas.clientWidth, this.canvas.clientHeight);
    this.sim.alpha(0.6);
  }

  // 관계 종류를 끄면 그 선은 안 그리고, 그래서 선이 하나도 안 남은 노드도
  // 안 그린다 — Obsidian 필터가 그래프에서 노드를 빼는 것과 같다.
  // 시뮬레이션에는 그대로 남아 있어 켜면 제자리로 돌아온다.
  setEdgeFilter(hidden) {
    this.hiddenEdgeTypes = new Set(hidden || []);
    this.adjacency = null;
    this._reach = null;
    if (this.hover && !this.nodeShown(this.hover)) this.hover = null;
  }

  edgeShown(e) { return !this.hiddenEdgeTypes.has(e.type); }

  nodeShown(id) {
    if (!this.hiddenEdgeTypes.size || id === this.center) return true;
    return this.neighborsOf(id).size > 0;
  }

  _rebuildSim(w, h) {
    this.sim?.stop();
    for (const e of this.edges) {
      e.source = e.s;
      e.target = e.t;
    }
    this.sim = buildSimulation({
      nodes: this.nodes,
      edges: this.edges,
      center: this.center,
      width: w,
      height: h,
      forces: this.forces,
    });
    this.sim.alpha(1);
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

  // `ease` 를 주면 목표로 **서서히** 따라간다.
  //
  // 매 프레임 목표값을 그대로 대입하면 배치 전체가 떨린다. 카메라는 노드
  // 좌표의 최소/최대로 정해지는데, 경계값은 가장 흔들리는 통계라서 바깥
  // 노드 하나가 몇 픽셀 움직이면 배율과 이동량이 같이 흔들리고, 그러면
  // **가만히 있는 노드까지 화면에서 떨린다.**
  fitView(pad = 70, ease = 0) {
    if (!this.nodes.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      minX = Math.min(minX, n.x - n.r); maxX = Math.max(maxX, n.x + n.r);
      minY = Math.min(minY, n.y - n.r); maxY = Math.max(maxY, n.y + n.r);
    }
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const k = Math.min(1.35, Math.max(0.22,
      Math.min((w - pad * 2) / Math.max(maxX - minX, 1),
               (h - pad * 2) / Math.max(maxY - minY, 1))));
    const tx = w / 2 - ((minX + maxX) / 2) * k;
    const ty = h / 2 - ((minY + maxY) / 2) * k;

    if (ease <= 0) {           // 명시적 호출(버튼·첫 배치)은 즉시 맞춘다
      this.k = k; this.tx = tx; this.ty = ty;
      return;
    }
    // **목표가 코앞이면 손대지 않는다.** 배치가 거의 다 식어도 경계 노드
    // 하나가 1px 씩 움직이면 목표 배율과 이동량이 계속 조금씩 바뀌고,
    // 카메라가 그걸 8%씩 따라가면 가만히 있는 노드까지 같이 떤다.
    if (Math.abs(k - this.k) < 0.003
        && Math.abs(tx - this.tx) < 1.5
        && Math.abs(ty - this.ty) < 1.5) return;
    this.k += (k - this.k) * ease;
    this.tx += (tx - this.tx) * ease;
    this.ty += (ty - this.ty) * ease;
  }

  // --- 렌더 -----------------------------------------------------------
  _frame(now = 0) {
    if (this._stopped) return;
    // 지난 프레임 이후 흐른 시간만큼만 시뮬레이션을 돌린다. 탭이 뒤로
    // 갔다 오면 dt 가 수 초로 튀므로 위에서 잘라둔다 — 안 자르면 돌아온
    // 순간 수백 틱이 한 번에 돌아 배치가 폭발한다.
    const dt = this._prev ? Math.min(now - this._prev, 100) : TICK_MS;
    this._prev = now;
    this._acc += dt;
    // 0.9 여유를 둔다. 60Hz 화면에서 dt 가 16.6 과 16.7 을 오가면 어떤
    // 프레임은 0틱, 다음은 2틱이 되어 눈에 띄게 덜컹거린다.
    for (let i = 0; i < 3 && this._acc >= TICK_MS * 0.9; i++) {
      if (this.sim && this.sim.alpha() > 0.005) this.sim.tick();
      this._acc -= TICK_MS;
    }
    if (this._acc < 0) this._acc = 0;

    // **식을 때까지 카메라가 따라간다.** 한 번만 맞추면 그 뒤로도 배치가
    // 계속 퍼져서 결국 화면 밖으로 나간다. 사용자가 직접 움직이기
    // 시작하면 그때부터 손을 뗀다.
    if (this.autoFit && this.alpha > 0.02) {
      this.fitView(70, this._fitted ? 0.08 : 0);
      this._fitted = true;
    }

    this._draw();
    this._raf = requestAnimationFrame((t) => this._frame(t));
  }

  _draw() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(this.tx, this.ty);
    ctx.scale(this.k, this.k);

    if (this.causalView) {
      this._drawCausal(ctx);
      ctx.restore();
      return;
    }

    // 가리키는 동안은 hover 가, 마우스를 떼면 클릭해 둔 노드가 조명을
    // 이어받는다 — 빈 곳을 클릭하기 전까지 유지된다. 선택 노드가 화면에
    // 없으면(새 데이터 로드 뒤) 조명 없는 기본 화면으로 돌아간다.
    const spot = this.hover
      ?? (this.byId.has(this.selected) ? this.selected : null);
    const near = spot ? this.neighborsOf(spot) : null;
    const lit = (id) => !spot || id === spot || near.has(id);
    const focus = spot || this.selected;  // 라벨을 굵게 쓸 대상
    // 관계 이름은 가리켰을 때만. 늘 그리면 자녀가 12명인 세종 주위에
    // '자녀'가 12번 겹쳐 찍힌다.
    const showEdgeLabels = spot && near.size <= 16 && this.k > 0.5;

    // 엣지 먼저 — 노드가 그 위에 얹혀야 교점이 지저분해지지 않는다
    for (const e of this.edges) {
      const a = this.byId.get(e.s);
      const b = this.byId.get(e.t);
      if (!a || !b || !this.edgeShown(e)) continue;
      const active = spot && (e.s === spot || e.t === spot);
      // 선은 회색뿐이다 — 인과도 여기서는 회색이다(인과는 노드를 누르면
      // 도면으로 펼친다). 가리킨 노드에 붙은 선은 더 밝고 굵게 선다 —
      // 강조색(보라)은 노드 테두리에만 둔다. 무엇이 무엇에게 건 관계인지는
      // 화살촉이 말한다.
      ctx.globalAlpha = 1;
      if (spot && !active) {
        ctx.strokeStyle = chrome().edgeSoft;
        ctx.lineWidth = 1;
      } else if (active) {
        ctx.strokeStyle = e.kind === 'same_as' ? chrome().edgeLitSame : chrome().edgeLit;
        ctx.lineWidth = 1.8;
      } else {
        ctx.strokeStyle = e.kind === 'same_as' ? chrome().edgeSame : chrome().edgeBase;
        ctx.lineWidth = 1.1;
      }
      ctx.lineWidth *= this.display.lineScale;
      // 추출로 얻은 관계(신뢰도 < 1)는 점선. 구조화 소스가 준 사실과
      // 텍스트에서 추론한 사실을 화면에서 구분하지 않으면 둘 다 못 믿는다.
      ctx.setLineDash(e.kind === 'same_as' ? [2, 4] : e.conf < 1 ? [5, 4] : []);
      // 인과(원인 → 결과)는 다른 관계보다 굵다. 이 그래프가 온톨로지인
      // 이유가 이 선이라, 참여·장소 선 사이에서 같은 굵기로 묻히면 안 된다.
      if (e.type === 'caused') ctx.lineWidth += 1.2 * this.display.lineScale;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);

      if (this.display.arrows && e.kind !== 'same_as' && !MUTUAL.has(e.type) && (!spot || active)) {
        drawArrow(ctx, a, b, ctx.strokeStyle);
      }
      if (active && showEdgeLabels) {
        drawEdgeLabel(ctx, a, b, e.label, this.k);
      }
      ctx.globalAlpha = 1;
    }

    for (const node of this.nodes) {
      if (!this.nodeShown(node.id)) continue;
      drawNode(ctx, node, {
        dim: !lit(node.id),
        focused: node.id === focus,
        center: node.id === this.center,
        selected: node.id === this.selected,
      });
    }

    if (this.showLabels) {
      // **자리가 있으면 붙이고 없으면 만다.** '차수 6 이상만' 같은 기준은
      // 화면 사정과 무관해서, 왕조를 중심에 놓으면 왕후 수십 명이 이름
      // 없는 파란 점이 되고 만다. 실제로 겹치는지를 재서 정하면 확대할
      // 때마다 더 많은 이름이 저절로 드러난다.
      const placed = [];
      const shown = this._shownLabels;
      const next = new Set();
      const rank = (n) => (n.id === focus ? 3 : n.id === this.center ? 2 : 0) + Math.min(n.degree / 40, 1);
      const candidates = this.nodes
        .filter((n) => lit(n.id) && this.nodeShown(n.id))
        .sort((a, b) => rank(b) - rank(a));
      // 멀리서 보면 이름표가 흐려진다 — Obsidian 의 '텍스트 흐림 문턱'.
      // 중심과 초점의 이름은 늘 그린다.
      const fade = labelAlpha(this.k, this.display.textFade);

      for (const node of candidates) {
        const strong = node.id === focus || node.id === this.center;
        const box = labelBox(ctx, node, strong, this.k);
        // **지난 프레임에 떠 있던 이름은 조금 더 버틴다.** 겹침 판정은
        // 예/아니오라서, 노드가 1px 움직일 때마다 판정이 뒤집히면 이름이
        // 초당 몇 번씩 깜빡인다. 한 번 뜬 이름은 3px 더 겹쳐야 물러난다.
        const test = shown.has(node.id) ? inset(box, 3 / this.k) : box;
        // 중심과 가리킨 노드의 이름은 무슨 일이 있어도 그린다
        if (!strong && placed.some((p) => overlaps(p, test))) continue;
        placed.push(box);
        next.add(node.id);
        if (!strong && fade <= 0) continue;
        drawLabel(ctx, node, strong, this.k, strong ? 1 : fade);
      }
      this._shownLabels = next;
    }
    ctx.restore();
  }

  // 인과 도면 그리기. 열은 causalLayout 이 정했고 여기서는 선·점·이름·열
  // 머리만 그린다. 가리키는 노드가 있으면 그 노드를 지나는 경로만 밝다.
  _drawCausal(ctx) {
    const view = this.causalView;
    const spot = this.hover;
    const reach = spot ? this.causalReachOf(spot) : null;
    const lit = (id) => !spot || id === spot || reach.nodes.has(id);
    const litEdge = (e) => !spot || reach.edges.has(edgeKey(e));

    // 열 머리 — 도면의 맨 위에 흐리게. 왼쪽이 원인, 오른쪽이 결과라는 것을
    // 글자로 한 번 더 말한다 (색만으로 뜻을 나르지 않는다).
    let top = Infinity;
    for (const n of this.nodes) top = Math.min(top, n.y);
    ctx.font = `600 ${11 / this.k}px ${FONT}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = chrome().textDim;
    for (const d of view.depths) {
      if (d === 0) continue;
      const side = d < 0 ? COL_CAPTION.cause : COL_CAPTION.effect;
      ctx.fillText(side[Math.min(Math.abs(d) - 1, side.length - 1)], d * view.col, top - 26 / this.k);
    }

    // 선 — 열 사이를 잇는 곡선. 곧은 선은 열을 건너뛰는 선이 중간 열의
    // 점을 가로지르고, 곡선은 점 사이로 지나간다.
    for (const e of this.edges) {
      const a = this.byId.get(e.s);
      const b = this.byId.get(e.t);
      if (!a || !b) continue;
      const on = litEdge(e);
      ctx.globalAlpha = on ? 1 : 0.18;
      ctx.strokeStyle = on ? chrome().causeLit : chrome().edgeLit;
      ctx.lineWidth = (on ? 2 : 1) * this.display.lineScale;
      ctx.setLineDash(e.conf < 1 ? [5, 4] : []);
      const bend = Math.max(40, Math.abs(b.x - a.x) * 0.5);
      const c1 = { x: a.x + bend, y: a.y };
      const c2 = { x: b.x - bend, y: b.y };
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
      // 화살촉은 곡선의 끝 접선(c2 → b)을 따른다
      drawArrow(ctx, { x: c2.x, y: c2.y }, b, ctx.strokeStyle);
      // 종류(배경·계기·영향)는 선 한가운데. 곡선의 중점은 양 끝의 평균이다.
      // 선이 많으면 가리킨 경로에만 적는다 — 스물 넘는 글자가 열 사이에
      // 쌓이면 선끼리 갈리지 않는다.
      if (on && this.k > 0.35 && (spot || this.edges.length <= 24)) drawEdgeLabel(ctx, a, b, e.label, this.k, chrome().causeLit);
      ctx.globalAlpha = 1;
    }

    for (const node of this.nodes) {
      drawNode(ctx, node, {
        dim: !lit(node.id),
        focused: node.id === spot,
        center: node.id === view.center,
        selected: node.id === view.center,
      });
    }
    // 이름은 전부 쓴다 — 열 안 줄 간격(ROW)이 이름 두 줄보다 넓다.
    for (const node of this.nodes) {
      if (!lit(node.id)) continue;
      drawLabel(ctx, node, node.id === view.center || node.id === spot, this.k, 1);
    }
  }

  // --- 상호작용 -------------------------------------------------------
  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const pw = Math.round(w * dpr);
    const ph = Math.round(h * dpr);
    // 배율은 일찍 돌아가더라도 늘 최신으로 둔다 (그리는 쪽이 이걸 읽는다).
    this.dpr = dpr;
    // **크기가 그대로면 아무것도 하지 않는다.** ResizeObserver 는 상세
    // 패널이 열리거나 소수점 반올림이 달라져도 불린다. 그때마다 alpha 를
    // 되살리면 시뮬레이션이 영영 식지 않아 배치가 계속 떤다.
    if (pw === this.canvas.width && ph === this.canvas.height) return;
    this.canvas.width = pw;
    this.canvas.height = ph;
    if (this.causalView) { this._layoutCausal(); return; }
    if (this.sim) {
      retarget(this.sim, { center: this.center, width: w, height: h });
      this.sim.alpha(Math.max(this.sim.alpha(), 0.35));
    }
  }

  resetView() {
    this.tx = 0;
    this.ty = 0;
    this.k = 1;
  }

  toWorld(px, py) {
    return { x: (px - this.tx) / this.k, y: (py - this.ty) / this.k };
  }

  nodeAt(px, py) {
    const p = this.toWorld(px, py);
    let best = null;
    let bestD = Infinity;
    for (const n of this.nodes) {
      if (!this.nodeShown(n.id)) continue;
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d < n.r + 6 && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  _bindEvents() {
    const c = this.canvas;
    let dragNode = null;
    let panning = false;
    let last = null;
    let moved = false;

    c.addEventListener('pointerdown', (ev) => {
      c.setPointerCapture(ev.pointerId);
      last = { x: ev.offsetX, y: ev.offsetY };
      moved = false;
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      // d3 는 fx/fy 로 노드를 못박는다. 옛 `fixed` 플래그가 하던 일이다.
      if (hit) { dragNode = hit; hit.fx = hit.x; hit.fy = hit.y; } else { panning = true; }
      this.autoFit = false;
    });

    c.addEventListener('pointermove', (ev) => {
      if (dragNode) {
        const p = this.toWorld(ev.offsetX, ev.offsetY);
        dragNode.fx = p.x;
        dragNode.fy = p.y;
        // 도면에는 시뮬레이션이 없다 — 자리를 직접 옮긴다
        if (!this.sim) { dragNode.x = p.x; dragNode.y = p.y; }
        if (this.sim) this.sim.alpha(Math.max(this.sim.alpha(), 0.4));
        moved = true;
        return;
      }
      if (panning && last) {
        this.tx += ev.offsetX - last.x;
        this.ty += ev.offsetY - last.y;
        last = { x: ev.offsetX, y: ev.offsetY };
        moved = true;
        return;
      }
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      const id = hit ? hit.id : null;
      if (id !== this.hover) {
        this.hover = id;
        c.style.cursor = hit ? 'pointer' : 'default';
        this.onHover(hit || null, ev);
      }
    });

    const release = (ev) => {
      if (dragNode && !moved) {
        // 끌지 않고 눌렀다 뗀 것은 고르기다 — 못을 도로 뽑는다
        dragNode.fx = null;
        dragNode.fy = null;
        this._select(dragNode);
      }
      // 빈 곳 클릭(끌지 않은 팬)은 선택 해제 — 조명이 여기서 꺼진다.
      // 도면에서는 주변 관계 그래프로 돌아가는 몸짓이다.
      if (!dragNode && !moved) {
        if (this.causalView) this.exitCausal();
        else this.selected = null;
      }
      dragNode = null;
      panning = false;
      last = null;
      if (ev && ev.pointerId !== undefined) {
        try { c.releasePointerCapture(ev.pointerId); } catch { /* 이미 해제됨 */ }
      }
    };
    c.addEventListener('pointerup', release);
    c.addEventListener('pointercancel', release);

    c.addEventListener('dblclick', (ev) => {
      const hit = this.nodeAt(ev.offsetX, ev.offsetY);
      if (hit) this.onExpand(hit);
    });

    c.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      this.autoFit = false;
      const factor = Math.exp(-ev.deltaY * 0.0015);
      const k = Math.min(3.5, Math.max(0.25, this.k * factor));
      // 커서 아래 지점이 그대로 있도록 평행이동을 보정한다
      this.tx = ev.offsetX - ((ev.offsetX - this.tx) * k) / this.k;
      this.ty = ev.offsetY - ((ev.offsetY - this.ty) * k) / this.k;
      this.k = k;
    }, { passive: false });
  }

  _select(node) {
    this.selected = node.id;
    this.onSelect(node);
  }

  // 프로그램에서 고르는 경로. **콜백을 부르지 않는다.**
  //
  // 부르면 무한히 돈다: 클릭 → onSelect → load() → select() → onSelect →
  // load() → … 한 번 클릭할 때마다 요청이 끝없이 이어지고, load 마다
  // setData 가 alpha 를 1 로 되돌려 배치가 영영 식지 않는다. 상세 패널도
  // 매 바퀴 다시 그려져 여러 노드가 번갈아 나오는 것처럼 보인다.
  select(id) {
    const node = this.byId.get(id);
    if (node) this.selected = node.id;
  }

  // 노드가 화면 밖이면 사용자는 아무 일도 안 일어났다고 생각한다
  focusOn(id) {
    const node = this.byId.get(id);
    if (!node) return;
    this.tx = this.canvas.clientWidth / 2 - node.x * this.k;
    this.ty = this.canvas.clientHeight / 2 - node.y * this.k;
  }
}

// --- 그리기 도구 -------------------------------------------------------

function drawNode(ctx, n, { dim, focused, center, selected }) {
  const color = nodeColor(n.type, n.group);

  ctx.globalAlpha = dim ? 0.16 : 1;

  // 배경색 링 — 노드가 겹쳐도 서로 먹히지 않는다
  ctx.lineWidth = 2;
  ctx.strokeStyle = chrome().surface;
  ctx.beginPath();
  ctx.arc(n.x, n.y, n.r + 1, 0, TAU);
  ctx.stroke();

  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(n.x, n.y, n.r, 0, TAU);
  ctx.fill();

  // 고른 노드·중심·가리킨 노드의 테두리 — Obsidian 은 초점 노드를 강조색으로
  // 칠하지만 우리 노드는 타입 색을 지고 있으므로 테두리로 두른다.
  if (selected || center) {
    ctx.strokeStyle = selected ? chrome().accent : chrome().ring;
    ctx.lineWidth = selected ? 2 : 1.5;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r + 4.5, 0, TAU);
    ctx.stroke();
  } else if (focused) {
    ctx.strokeStyle = chrome().accentSoft;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r + 3.5, 0, TAU);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function labelFont(ctx, strong, k) {
  const size = strong ? 12.5 : 11;
  ctx.font = `${strong ? 600 : 400} ${size / k}px ${FONT}`;
  return size / k;
}

// 라벨이 차지할 자리 (월드 좌표). 좌우로 조금 여유를 둬서 글자끼리
// 스치듯 붙는 것도 겹침으로 본다.
// 또 하나의 이름(`names[1]`)은 **아랫줄에** 작게 쓴다. 옆에 이어 붙이면
// '기축옥사 · 정여립의 난' 이 한 줄로 길어져 이웃 라벨을 밀어낸다.
function coName(n) {
  return n.names && n.names.length > 1 ? n.names[1] : null;
}

function labelBox(ctx, n, strong, k) {
  const size = labelFont(ctx, strong, k);
  let w = ctx.measureText(n.label).width + 6 / k;
  let h = size * 1.25;
  const co = coName(n);
  if (co) {
    coFont(ctx, k);
    w = Math.max(w, ctx.measureText(co).width + 6 / k);
    h += size * 1.05;
    labelFont(ctx, strong, k);
  }
  const y = n.y + n.r + 4 / k;
  return { x: n.x - w / 2, y, w, h };
}

function coFont(ctx, k) {
  const size = 9.5;
  ctx.font = `400 ${size / k}px ${FONT}`;
  return size / k;
}

function inset(b, m) {
  return {
    x: b.x + m, y: b.y + m,
    w: Math.max(b.w - m * 2, 1), h: Math.max(b.h - m * 2, 1),
  };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// 이름표가 보이기 시작하는 배율. fade 0 이면 0.3 배에서, 1 이면 1.5 배에서
// 완전히 나타나고, 그보다 0.35 배 아래까지 서서히 흐려진다.
export function labelAlpha(k, fade) {
  const kMin = 0.3 + fade * 1.2;
  return Math.max(0, Math.min(1, (k - kMin) / 0.35 + 1));
}

function drawLabel(ctx, n, strong, k, alpha = 1) {
  ctx.globalAlpha = alpha;
  labelFont(ctx, strong, k);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const y = n.y + n.r + 4 / k;
  // 글자에 배경색 외곽선을 둘러 선 위에서도 읽히게 한다
  ctx.lineWidth = 3 / k;
  ctx.strokeStyle = chrome().surface;
  ctx.lineJoin = 'round';
  ctx.strokeText(n.label, n.x, y);
  ctx.fillStyle = strong ? chrome().text : chrome().textDim;
  ctx.fillText(n.label, n.x, y);

  const co = coName(n);
  if (co) {
    const size = labelFont(ctx, strong, k);
    const y2 = y + size * 1.1;
    coFont(ctx, k);
    ctx.strokeStyle = chrome().surface;
    ctx.strokeText(co, n.x, y2);
    ctx.fillStyle = chrome().textDim;
    ctx.fillText(co, n.x, y2);
  }
  ctx.globalAlpha = 1;
}

function drawEdgeLabel(ctx, a, b, text, k, color = chrome().textDim) {
  if (!text) return;
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  ctx.font = `${10.5 / k}px ${FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 3 / k;
  ctx.strokeStyle = chrome().surface;
  ctx.lineJoin = 'round';
  ctx.strokeText(text, mx, my);
  ctx.fillStyle = color;
  ctx.fillText(text, mx, my);
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

function drawArrow(ctx, a, b, color) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const d = Math.hypot(dx, dy) || 1;
  const ux = dx / d;
  const uy = dy / d;
  // 화살촉은 도착 노드 바로 앞에 — 방향이 없으면 '누가 누구에게'가 사라진다
  const tipX = b.x - ux * (b.r + 3);
  const tipY = b.y - uy * (b.r + 3);
  const size = 5;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  ctx.lineTo(tipX - ux * size + uy * size * 0.5, tipY - uy * size - ux * size * 0.5);
  ctx.lineTo(tipX - ux * size - uy * size * 0.5, tipY - uy * size + ux * size * 0.5);
  ctx.closePath();
  ctx.fill();
}

// 서로 같은 것을 뜻하는 관계는 **방향을 키에서 뺀다** — 두 방향이 다 와도 선은 한 줄이다.
function edgeKey(e) {
  return pairKey(e.s, e.t, e.type);
}
function pairKey(s, t, type) {
  return MUTUAL.has(type) ? `${[s, t].sort().join('|')}|${type}` : `${s}|${t}|${type}`;
}
