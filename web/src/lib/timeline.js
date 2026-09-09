// 연표 — 고른 노드가 몇 년쯤의 일이고, 무엇 뒤 무엇 앞인지.
//
// **절대 연도는 위치를 말해주지 못한다.** '1504년'을 들어도 그게 조선의
// 어디쯤인지 아는 사람은 드물다. 사람이 실제로 쓰는 좌표는 아는 사건과의
// 앞뒤다 — "무오사화 다음, 중종반정 직전". 그래서 이 막대는 고른 노드
// 하나만 찍지 않고 그 무렵의 큰 사건과 연도를 아는 이웃을 함께 세운다.
//
// **자리는 연도에 비례한다.** 목록으로 늘어놓으면 1400년과 1401년 사이가
// 1400년과 1500년 사이와 똑같이 벌어져, 연표라고 부를 수 없게 된다.
//
// **몰린 해는 라벨이 아니라 자가 양보한다.** 라벨은 겹치면 못 읽으니 한
// 해에 사건이 수십이면 어딘가는 물러나야 한다. 예전에는 라벨을 밀어냈는데,
// 그러면 밀린 라벨만 제 해를 떠나고 왼쪽 재위 띠는 제 해에 남아 둘이
// 갈라진다 (실측: 임진왜란 한 해에 사건이 38건이라 1594~1597년 전투들이
// 1700px — 그 눈금으로 73년치 — 아래로 밀려, 효종(1649~1659)의 막대 옆에
// 섰다). 그래서 미는 대신 **그 해를 늘린다**: 1592년이 1140px 를 차지하고,
// 재위 띠도 같은 자를 쓰니 선조의 막대가 그 1140px 를 함께 지난다.
// 밀어낼 것이 없으므로 축과 라벨의 어긋남은 0 이다 (buildScale).
//
// **눈금은 하나다 — 가장 촘촘한 자리에 고정한다.** 줌은 걷어냈고, 남긴
// 쪽은 '전부 세우는' 눈금이다. 연대를 아는 사건은 하나도 물러나지 않는다
// — 무엇이 빠졌는지 세어 보게 만드느니 다 세우고 스크롤하게 둔다.
// 대신 연표는 화면보다 길어지므로, 훑기 막대와 '고른 자리로 돌아가기'가
// 길을 잃지 않게 받쳐 준다.

import { nodeColor } from './graph-view.js';

// **왼쪽에는 왕의 재위 띠가 선다.** 조선의 시간을 사람은 절대 연도가
// 아니라 임금으로 읽는다 — '1456년'보다 '세조 때'가 먼저 온다. 재위는
// 구간이므로 점이 아니라 막대로 긋고, 사망은 재위의 끝이 아니라서
// (태조는 1398년에 물러나 1408년에 죽었다) 따로 찍어 점선으로 잇는다.
//
// **대통령도 같은 띠, 같은 모양이다.** 1948년 뒤의 시간은 '박정희 때'로
// 읽힌다 — 왕이 하던 일을 대통령이 이어받았다. 서버가 자리의 종류(kind)를
// 주고, 여기서는 말만 가른다: 재위/재임. 재임 중인 사람은 끝 해 대신
// '~' 만 적는다 (ongoing).
const LANE_W = 104;   // 재위 띠 칸의 너비 (끄면 0)
const BAR_X = 11;     // 재위 막대가 서는 자리 (칸 안에서)
const BAR_W = 6;
// 몰년 표식은 막대 옆으로 비켜 세운다. 같은 x 에 찍으면 다음 임금의
// 막대가 그 위를 덮어 '물러난 뒤 산 기간'이 통째로 안 보인다.
const DEATH_X = 19;
// 띠 라벨은 이름과 연도 두 줄이라 26px 를 먹는다. 이보다 가까우면
// 글자가 서로를 덮어 둘 다 못 읽는다 (실측: 13px 로 두었더니 문종 위에
// 예종이, 광해군 위에 인조가 얹혔다).
const LANE_GAP = 26;
const PANEL_W = 252;  // 띠를 뺀 연표 패널의 너비 (style.css 와 같은 값)

const AXIS_X = 46;    // 세로축이 서는 자리 (왼쪽은 연도 칸) — 띠 너비만큼 밀린다
const PAD_TOP = 18;   // 첫 표시가 머리에 붙지 않게
// 아래는 넉넉히 둔다. 마지막 사건이 축 끝에 딱 붙으면 스크롤을 끝까지
// 내려도 패널 바닥과 '더 있다'는 그림자(28px)에 눌려 반쯤 지워진다.
const PAD_BOTTOM = 64;
const GAP = 30;       // 라벨 한 줄이 먹는 높이 — 몰린 해는 이만큼씩 늘어난다

// 눈금. 시대 전체가 한 화면에 들어오는 배율의 16배다 — 줌이 있던 시절의
// 마지막 단계와 같은 촘촘함이고, 조선(567년)이면 패널 760px 기준 약 19px/년.
const ZOOM = 16;
// 안전판. 시대를 나누지 않은 전체 그래프는 기원전까지 걸쳐 있어 이 눈금에서
// 끝없이 길어진다.
const MAX_HEIGHT = 40000;

// 눈금 — 해를 픽셀로 옮기는 자. **띠도 라벨도 이 자 하나만 쓴다.**
//
// 한 해에 내주는 높이는 `max(rate, 그 해의 라벨 수 x GAP)` 이다. 사건이
// 없는 해는 rate 만큼(조선~근현대 900년이면 11px 남짓) 비례해서 지나가고,
// 몰린 해만 라벨이 다 설 만큼 늘어난다. 그래서 100년이 1년처럼 보이는 일도
// 없고, 라벨이 제 해를 떠나는 일도 없다.
//
// DOM 을 안 쓰는 순수 함수다 — 축과 라벨이 어긋나는지는 브라우저 없이
// 재야 한다 (tests/layout.test.mjs).
export function buildScale(marks, { from, to, base }) {
  const span = Math.max(to - from, 1);
  // 그 해가 라벨에 내줘야 할 높이. 라벨은 이 안에서만 선다.
  const need = new Float64Array(span + 1);
  for (const m of marks) need[clamp(m.year, from, to) - from] += GAP;

  const total = (rate) => {
    let sum = PAD_TOP + PAD_BOTTOM;
    for (let i = 0; i < span; i++) sum += Math.max(rate, need[i]);
    return sum;
  };
  // 늘리다 보면 끝없이 길어질 수 있다 (기원전까지 걸친 전체 그래프).
  // 라벨 자리는 줄일 수 없으니 **빈 해의 몫**만 깎아 상한에 맞춘다.
  let rate = base / span;
  if (total(rate) > MAX_HEIGHT) {
    let lo = 0;
    let hi = rate;
    for (let k = 0; k < 40; k++) {
      const mid = (lo + hi) / 2;
      if (total(mid) > MAX_HEIGHT) hi = mid;
      else lo = mid;
    }
    rate = lo;
  }

  const pos = new Float64Array(span + 1);
  pos[0] = PAD_TOP;
  for (let i = 0; i < span; i++) pos[i + 1] = pos[i] + Math.max(rate, need[i]);
  return { from, to, H: pos[span] + PAD_BOTTOM, pos };
}

// 라벨 자리. marks 는 sortMarks 로 세운 차례여야 한다 — 같은 해는 그
// 차례대로 GAP 씩 내려 선다. 그 해에 내준 높이가 곧 라벨 수 x GAP 이라
// 다음 해를 침범하지 않는다.
export function placeMarks(marks, { from, to, pos }) {
  let year = null;
  let nth = 0;
  return marks.map((m) => {
    const y = clamp(m.year, from, to);
    if (y !== year) { year = y; nth = 0; }
    return { m, y: pos[y - from] + nth++ * GAP };
  });
}

// 한 해가 늘어나면 그 안의 **차례가 곧 시간 순으로 읽힌다.** 그러니 같은
// 해는 가나다가 아니라 날짜로 세운다 (실측: 1592년 38건이 가나다순이라
// 부산진 전투(5월)가 한산도 대첩(7월)보다 아래에 섰다). 날짜를 모르는
// 것은 앞에 둔다 — 위키데이터는 연도만 아는 날을 1월 1일로 적어 보내므로
// 달을 따로 적어 주지는 않는다. 다만 그 해에 제 원인이 함께 서 있으면
// 원인 뒤로 물러난다 (아래 `dateContains`).
//
// **원인은 결과보다 위에 선다.** 날짜만으로는 그 차례가 안 나온다. 같은
// 날인 인과가 있고(한일병합·무단통치 1910-08-29, 3·1독립선언서·3·1운동
// 1919-03-01), 결과의 날짜가 본래 거칠어서 원인의 날짜를 품기도 한다
// (을사조약 1905-11-17 → 애국계몽운동 1905). 거친 날짜는 '그 해 어딘가'
// 이지 1월 1일이 아니므로, **결과의 날짜가 원인의 날짜를 품으면 결과를
// 원인 뒤에 세운다.** 날짜가 서로를 품지 않으면(원인 12월, 결과 3월)
// 날짜가 이긴다 — 그것은 자료의 날짜가 틀린 것이라 `chronology` 가 잡을
// 일이지 화면이 지어낼 일이 아니다 (병자호란 1636-12-09 옆의 청나라
// 1636년 자리는 건국(4월)이지 그 결과가 아니다).
//
// 품는 쪽에는 **날짜를 모르는 마크**와 **단체의 창립**이 함께 걸린다.
// 앞은 해만 빌려 선 것이라 '그 해 어딘가'이고(왕자의 난 1398-08-26 →
// 함흥차사), 뒤는 연표가 단체를 끝난 날이 아니라 **시작한 날**에 세우기
// 때문이다 (3·1 운동 1919-03-01 → 북로군정서 1919, 5·16 군사정변
// 1961-05-16 → 국가재건최고회의 1961).
//
// 인과는 두 곳에서 온다: 서버가 보내는 마크 사이의 인과(`causes`,
// [원인 id, 결과 id])와 고른 노드에 달린 `rel`. 전에는 뒤엣것뿐이라
// **둘 다 뼈대인 쌍은 인과를 아예 몰랐다** (2026-09-08 지적).
export function sortMarks(marks, causes) {
  const cmp = plainOrder(marks);
  const rel = causeEdges(marks, causes);
  const years = new Map();
  for (const m of marks) {
    if (!years.has(m.year)) years.set(m.year, []);
    years.get(m.year).push(m);
  }
  const out = [];
  for (const y of [...years.keys()].sort((a, b) => a - b)) {
    out.push(...orderYear(years.get(y), rel, cmp));
  }
  return out;
}

// 인과가 없을 때의 차례 — 날짜, 같으면 가나다, 그래도 같으면 들어온 순
// (같은 자료면 같은 그림이어야 한다).
function plainOrder(marks) {
  const at = new Map(marks.map((m, i) => [m, i]));
  return (a, b) => {
    const da = String(a.date || '');
    const db = String(b.date || '');
    if (da !== db) return da < db ? -1 : 1;
    return String(a.label || '').localeCompare(String(b.label || ''), 'ko')
      || at.get(a) - at.get(b);
  };
}

// 거친 날짜가 고운 날짜를 품는가 — '1636' ⊇ '1636-12-09', '1920-10' ⊇
// '1920-10-21'. 같은 날도 품는다.
//
// **날짜를 모르면('') 무엇이든 품는다.** 연표는 날짜가 없는 마크도 연도
// 노드에서 해를 빌려 세우는데(`time:1398`), 그 자리는 '그 해 어딘가'이지
// '그 해 첫날'이 아니다 — 거친 연도가 1월 1일이 아닌 것과 같은 이치다.
export function dateContains(coarse, fine) {
  const c = String(coarse || '');
  const f = String(fine || '');
  if (!c) return true;
  return f.startsWith(c) && (f.length === c.length || f[c.length] === '-');
}

// 같은 해에 함께 선 마크들 사이의 [원인, 결과] 짝. 결과의 날짜가 원인의
// 날짜를 품는 것만 남긴다 (위 설명).
function causeEdges(marks, causes) {
  const byId = new Map(marks.map((m) => [m.id, m]));
  const pairs = [];
  const add = (c, e) => {
    if (!c || !e || c === e || c.year !== e.year) return;
    if (!dateContains(e.date, c.date)) return;
    pairs.push([c, e]);
  };
  for (const [src, dst] of causes || []) add(byId.get(src), byId.get(dst));
  // 고른 노드에 달린 관계도 같은 인과다. 서버가 `causes` 를 안 보내던
  // 때의 자료와 개인 연표에서도 이 길로 선다.
  const self = marks.find((m) => m.kind === 'self');
  if (self) {
    for (const m of marks) {
      if (m === self || m.rel?.type !== 'caused') continue;
      if (m.rel.dir === 'in') add(m, self);
      else if (m.rel.dir === 'out') add(self, m);
    }
  }
  return pairs;
}

// 한 해 안의 차례 — 날짜 순을 지키되 원인을 결과보다 위에 세운다.
// 위상 정렬(칸)로 세우고, 세울 수 있는 것 중 날짜가 앞선 것을 고른다.
// **순환이 있어도 멈추지 않는다** — 진주농민봉기와 임술민란은 서로를
// 원인으로 물고 둘 다 1862년이다. 아무도 앞설 수 없으면 남은 것 중
// 날짜·가나다가 앞선 것을 세우고 마저 푼다.
function orderYear(group, rel, cmp) {
  const inYear = new Set(group);
  const edges = rel.filter(([c, e]) => inYear.has(c) && inYear.has(e));
  if (!edges.length) return [...group].sort(cmp);
  const waiting = new Map(group.map((m) => [m, 0]));
  const next = new Map(group.map((m) => [m, []]));
  for (const [c, e] of edges) {
    next.get(c).push(e);
    waiting.set(e, waiting.get(e) + 1);
  }
  const left = new Set(group);
  const out = [];
  while (left.size) {
    let pick = null;
    for (const m of left) {
      if (waiting.get(m) === 0 && (pick === null || cmp(m, pick) < 0)) pick = m;
    }
    if (pick === null) {
      for (const m of left) if (pick === null || cmp(m, pick) < 0) pick = m;
    }
    out.push(pick);
    left.delete(pick);
    for (const e of next.get(pick)) waiting.set(e, waiting.get(e) - 1);
  }
  return out;
}

export class TimelineRail {
  constructor(root, { onPick } = {}) {
    this.root = root;
    this.onPick = onPick || (() => {});
    this.data = null;
    this.body = root.querySelector('.tl-body');
    this.head = root.querySelector('.tl-head');
    this.lane = 0;
    // 재위 띠는 기본으로 켠다. 끈 사람은 그 선택을 기억한다.
    this.showReigns = true;
    try {
      this.showReigns = localStorage.getItem('tl-reigns') !== '0';
    } catch { /* 비공개 창 등 */ }
    this.focusPy = 0;
    // 고른 자리로 가는 중인가. show() 가 켜고, 도착하거나 사람이 훑으면 꺼진다.
    this.seeking = false;
    // 지금 배치의 축 — 연도 <-> 픽셀 환산에 쓴다 (pos: 해마다의 y)
    this.axis = { from: 0, to: 1, H: 1, pos: new Float64Array([0, 1]) };

    // 재위 막대와 띠 라벨도 노드다 — 누르면 그 임금으로 옮긴다.
    this.body.addEventListener('click', (ev) => {
      const el = ev.target.closest('.tl-mark[data-id], .tl-reign[data-id], .tl-reign-bar[data-id]');
      if (el) this.onPick(el.dataset.id);
    });
    // 연표가 화면보다 길어졌으니 훑다 보면 고른 자리를 잃는다. 머리의
    // 연도를 누르면 그 자리로 돌아온다 (머리는 스크롤을 타지 않는다).
    this.head.addEventListener('click', (ev) => {
      if (ev.target.closest('.tl-when')) this.recenter();
      if (ev.target.closest('.tl-kings')) this.toggleReigns();
    });

    this.body.addEventListener('scroll', () => this.syncMap(), { passive: true });
    // 사람이 직접 훑기 시작하면 '고른 자리로 가는 중'은 끝난 것이다.
    for (const ev of ['wheel', 'pointerdown', 'touchstart']) {
      this.body.addEventListener(ev, () => { this.seeking = false; }, { passive: true });
    }

    // 훑기 막대를 누르거나 끌면 그 해로 옮긴다.
    this.head.addEventListener('pointerdown', (ev) => {
      const bar = ev.target.closest('.tl-map-bar');
      if (!bar) return;
      ev.preventDefault();
      const to = (e) => {
        const r = bar.getBoundingClientRect();
        const f = clamp((e.clientX - r.left) / r.width, 0, 1);
        this.body.scrollTop = f * this.body.scrollHeight - this.body.clientHeight / 2;
      };
      const stop = () => {
        window.removeEventListener('pointermove', to);
        window.removeEventListener('pointerup', stop);
      };
      window.addEventListener('pointermove', to);
      window.addEventListener('pointerup', stop);
      to(ev);
    });

    // 패널 폭·높이가 바뀌면 비례 배치를 다시 잡는다. 0단계 눈금은 패널
    // 높이에서 나오므로 창을 줄이면 눈금도 따라 줄어야 한다.
    this._ro = new ResizeObserver(() => this.layout({ keepView: true }));
    this._ro.observe(this.body);
  }

  // React 가 언마운트할 때 부른다 — 안 부르면 죽은 노드를 붙잡고 관찰을 이어간다.
  destroy() {
    this._ro?.disconnect();
  }

  hide() {
    this.root.hidden = true;
    this.data = null;
  }

  show(data) {
    this.data = data;
    this.root.hidden = false;
    this.renderHead();
    // 새 노드를 고른 것이니 고른 자리로 스크롤을 옮긴다. 줌 단계는 지킨다 —
    // 가까이 들여다보던 사람이 다른 노드를 눌렀다고 멀어지면 안 된다.
    this.layout({ recenter: true });
  }

  // --- 머리: 몇 년인가 --------------------------------------------------
  renderHead() {
    const d = this.data;
    const kings = (d.reigns || []).length;
    const chipText = seatCount(d.reigns || []);
    const when = d.year === null ? '연도 미상'
      : d.end !== null && d.end !== d.year ? `${yr(d.year)} ~ ${yr(d.end)}`
      : yr(d.year);
    // 노드가 스스로 적고 있는 날짜인지, 시대 노드에 붙어 있어 알게 된
    // 것인지 구분해서 말한다. 둘을 같은 얼굴로 내놓으면 안 된다.
    const via = d.year_source === 'edge'
      ? '<span class="tl-via" title="이 노드에는 날짜가 없고, 이어진 연도 노드에서 가져왔습니다">연결된 연도</span>'
      : '';

    // 자리를 무엇에 기대어 잡았는지 밝힌다. 연도를 모르는 개체를 아무
    // 말 없이 축 위에 세우면, 화면이 모르는 것을 아는 척한 것이 된다.
    const hint = {
      near: '연도가 적혀 있지 않아, 이어진 사건으로 자리만 가늠했습니다.',
      era: '연도를 알 수 없습니다. 시대의 큰 사건만 세웁니다.',
    }[d.basis];

    this.head.innerHTML = `
      <div class="tl-top">
        <div class="tl-kicker">연표</div>
      </div>
      <button class="tl-when" title="고른 자리로 돌아가기">${esc(when)}${via}</button>
      <div class="tl-count"></div>
      ${kings ? `<button class="tl-kings" aria-pressed="${this.showReigns}"
            title="${esc(seatHint(d.reigns))}">${esc(chipText)}</button>` : ''}
      <div class="tl-map" hidden title="누르거나 끌어서 연표를 옮깁니다">
        <span>${d.axis.from}</span>
        <div class="tl-map-bar"><i class="tl-map-view"></i><b class="tl-map-here" hidden></b></div>
        <span>${d.axis.to}</span>
      </div>
      ${hint ? `<p class="tl-hint">${esc(hint)}</p>` : ''}`;
  }

  // 재위 띠를 켜고 끈다. 패널이 그만큼 넓어졌다 좁아진다.
  toggleReigns() {
    this.showReigns = !this.showReigns;
    try { localStorage.setItem('tl-reigns', this.showReigns ? '1' : '0'); } catch { /* 저장 못 해도 동작한다 */ }
    this.renderHead();
    this.layout({ keepView: true });
  }

  // 해 -> 픽셀. 재위 띠도 사건 점도 이걸 쓴다 (buildScale 주석 참고).
  //
  // **소수를 받는다.** 자의 눈금은 한 해지만 재위 띠는 날짜를 안다 —
  // 1963.96 은 박정희가 취임한 1963-12-17 이다. 두 눈금 사이를 그만큼
  // 나눠 앉히지 않으면 12월에 취임한 사람의 이름이 그 해 1월에 선다
  // (2026-09-09 지적). 정수를 주면 예전과 똑같이 그 해의 첫날이다.
  yOf(year) {
    const { from, to, pos } = this.axis;
    const y = clamp(year, from, to);
    const i = Math.floor(y);
    const a = pos[i - from];
    const f = y - i;
    if (!f || i >= to) return a;
    return a + (pos[i + 1 - from] - a) * f;
  }

  // 픽셀 -> 해. 눈금이 고르지 않으니 나누기가 아니라 표를 되짚는다.
  yearAt(y) {
    const { from, to, pos } = this.axis;
    let lo = 0;
    let hi = to - from;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (pos[mid] <= y) lo = mid;
      else hi = mid - 1;
    }
    return from + lo;
  }

  // --- 몸통: 비례 배치 --------------------------------------------------
  layout({ recenter = false, keepView = false } = {}) {
    const d = this.data;
    if (!d) return;
    const marks = d.marks;
    if (!marks.length) {
      this.body.innerHTML = '<p class="tl-empty">연도를 아는 이웃이 없어 자리를 잡을 수 없습니다.</p>';
      return;
    }
    // 창 크기가 바뀌어 다시 그리는 경우엔 보던 해를 지킨다.
    //
    // **단, 고른 자리로 가는 중이면 그리로 마저 간다.** 새 노드의 머리글이
    // 이전과 다르면 (연도 미상 힌트가 생기거나 '연결된 연도' 줄이 사라지면)
    // 몸통 높이가 몇 px 바뀌고, 그 순간 ResizeObserver 가 이 길로 들어온다.
    // 그때 '보던 해'는 아직 옛 노드의 자리라, 지키면 방금 시작한 스크롤을
    // 도로 끊는 셈이 된다 (실측: 갑자사화에서 한양을 검색하면 연표가 1504년에
    // 그대로 서 있었다. 그래프에서 누를 때는 비슷한 노드끼리 오가 머리글이
    // 안 바뀌니 드러나지 않았을 뿐이다).
    const seeking = this.seeking;
    const viewYear = keepView && !seeking
      ? this.yearAt(this.body.scrollTop + this.body.clientHeight / 2) : null;

    // 재위 띠가 왼쪽 칸을 먹고, 축과 라벨은 그만큼 오른쪽으로 밀린다.
    const reigns = (d.reigns || []);
    const lane = this.lane = this.showReigns && reigns.length ? LANE_W : 0;
    this.root.style.width = `${PANEL_W + lane}px`;
    const AX = lane + AXIS_X;

    const { from, to } = d.axis;
    const bodyH = this.body.clientHeight || 600;

    // --- 누가 서는가 ---------------------------------------------------
    // 전부 선다. 고른 노드도 왕조도 이웃도 배경이 된 큰 사건도 가리지
    // 않는다 — 몰린 해는 그 해가 늘어나 자리를 내주므로 다툴 일이 없다.
    const visible = sortMarks(marks, d.causes);

    // 시대 전체가 한 화면에 드는 높이의 ZOOM 배가 '빈 해'의 몫이다.
    this.axis = buildScale(visible, { from, to, base: (bodyH - PAD_TOP - PAD_BOTTOM) * ZOOM });
    const H = this.axis.H;
    const at = (year) => this.yOf(year);
    const place = placeMarks(visible, this.axis).map(({ m, y }) => ({ m, ty: y }));

    const wires = place.map(({ m, ty }) => {
      const c = nodeColor(m.type, m.group);
      // 구간 막대는 고른 노드와 왕조에만 그린다. 이웃까지 그리면 축
      // 위에서 서로 겹쳐 한 덩어리가 되고, 정작 점이 어디에 찍혔는지
      // 안 보인다.
      //
      // 왕조(kind 'era')는 500년을 가로지르므로 축 **옆에** 비켜 세운다.
      // 축 위에 겹쳐 그리면 그 위의 사건 점들을 다 덮는다.
      const hasSpan = m.end != null && m.end !== m.year;
      const bar = m.kind === 'self' && hasSpan
        ? `<line x1="${AX}" y1="${ty}" x2="${AX}" y2="${at(m.end)}"
                 stroke="${c}" stroke-width="4" stroke-linecap="round" opacity=".85"/>`
        : m.kind === 'era' && hasSpan
        ? `<line x1="${AX - 6}" y1="${ty}" x2="${AX - 6}" y2="${at(m.end)}"
                 stroke="${c}" stroke-width="2" stroke-linecap="round" opacity=".5"/>`
        : '';
      // 밀린 자리와 제자리를 잇던 안내선은 걷어냈다 — 이제 라벨이 제 해를
      // 떠나지 않으므로 이을 것이 없다.
      return `${bar}
        <circle cx="${AX}" cy="${ty}" r="${m.kind === 'self' ? 4 : 2.6}" fill="${c}"/>`;
    }).join('');

    // 원인은 오른쪽 여백에서 꺾인 선으로 고른 노드와 잇는다 (2026-09-05
    // 사용자 요청). 축 위에 그리면 점·막대와 겹치고, 라벨 사이를 지나면
    // 글자를 가른다 — 오른쪽 가장자리는 늘 비어 있다.
    const W = this.body.clientWidth || (PANEL_W + lane);
    const self_ = place.find((p) => p.m.kind === 'self');
    const causeWires = self_
      ? place.filter((p) => isCause(p.m)).map((p) => causeWire(p.ty, self_.ty, W)).join('')
      : '';

    const cells = yearCells(place.map((p) => p.m));
    const items = place.map(({ m, ty }, i) => {
      const cell = cells[i];
      return `
      <button class="tl-mark k-${m.kind}" data-id="${esc(m.id)}" style="top:${ty.toFixed(1)}px"
              title="${esc(markName(m))} · ${esc(whenText(m))}">
        <span class="tl-y${cell.repeat ? ' rep' : ''}">${esc(cell.text)}</span>
        <span class="tl-name">${esc(markName(m))}</span>
        ${m.rel ? `<span class="tl-rel${isCause(m) ? ' is-cause' : ''}">${esc(relHead(m.rel))}</span>` : ''}
      </button>`;
    }).join('');

    const band = lane
      ? reignBand(reigns, at, { id: d.id, year: d.year })
      : { svg: '', items: '', named: 0 };

    this.body.innerHTML = `
      <div class="tl-canvas${causeWires ? ' has-cause' : ''}" style="height:${H}px; --lane:${lane}px">
        <svg class="tl-wires" width="100%" height="${H}" aria-hidden="true">
          <line x1="${AX}" y1="${PAD_TOP - 8}" x2="${AX}" y2="${H - PAD_BOTTOM + 8}"
                stroke="var(--line)" stroke-width="1"/>
          ${band.svg}
          ${wires}
          ${causeWires}
        </svg>
        ${band.items}
        ${items}
      </div>`;

    // 몇 개가 서 있는지 적는다. 물러난 것이 없으므로 분모는 없다 —
    // 'N / N' 은 늘 같은 두 수를 나란히 보여줄 뿐이다.
    const shown = visible.filter((m) => m.kind === 'anchor').length;
    const count = this.head.querySelector('.tl-count');
    if (count) count.innerHTML = `큰 사건 <b>${shown}</b>`;
    const chip = this.head.querySelector('.tl-kings');
    if (chip) {
      const all = reigns.length;
      chip.textContent = !lane || band.named >= all
        ? seatCount(reigns) : `${seatCount(reigns)} (이름 ${band.named}/${all})`;
      chip.title = !lane
        ? seatHint(reigns)
        : band.named >= all
        ? '막대가 재위·재임, 동그라미가 몰년입니다'
        : `이름을 세울 자리가 모자란 ${all - band.named}명은 막대만 있습니다`
          + ' — 막대에 마우스를 올리면 이름이 나옵니다';
    }
    const focus = self_ || place.find((p) => p.m.kind === 'near')
      || place[Math.floor(place.length / 2)];
    this.focusPy = focus.ty;
    this.hereFrac = self_ ? self_.ty / H : null;
    this.hereEndFrac = self_ && self_.m.end != null && self_.m.end !== self_.m.year
      ? at(self_.m.end) / H : null;
    if (recenter || seeking) this.recenter();
    else if (viewYear !== null) this.body.scrollTop = this.yOf(viewYear) - this.body.clientHeight / 2;
    this.syncMap();
  }

  recenter() {
    const top = Math.max(0, Math.min(
      this.focusPy - this.body.clientHeight / 2,
      this.body.scrollHeight - this.body.clientHeight));
    this.seeking = true;
    this.body.scrollTo({ top, behavior: 'smooth' });
    // 도착하면 '가는 중'을 내린다. 그 뒤로는 창 크기가 바뀌어도 보던 해를 지킨다.
    // 가는 도중 다시 부르면 이전 목적지의 감시는 걷는다 — 남겨 두면 지나가는
    // 길에 옛 자리를 스치는 순간 '도착'으로 잘못 읽는다.
    if (this._arrive) this.body.removeEventListener('scroll', this._arrive);
    const arrived = () => {
      if (Math.abs(this.body.scrollTop - top) > 1) return;
      this.seeking = false;
      this.body.removeEventListener('scroll', arrived);
      if (this._arrive === arrived) this._arrive = null;
    };
    this._arrive = arrived;
    this.body.addEventListener('scroll', arrived, { passive: true });
    arrived();
  }

  // 지금 보이는 구간이 연표 어디쯤인지. 스크롤이 없으면 막대도 없다.
  syncMap() {
    const map = this.head.querySelector('.tl-map');
    if (!map) return;
    const b = this.body;
    map.hidden = b.scrollHeight - b.clientHeight <= 4;
    if (map.hidden) return;
    const pct = (v) => (v * 100).toFixed(2) + '%';
    const view = map.querySelector('.tl-map-view');
    view.style.left = pct(b.scrollTop / b.scrollHeight);
    view.style.width = pct(b.clientHeight / b.scrollHeight);
    const here = map.querySelector('.tl-map-here');
    here.hidden = this.hereFrac === null;
    if (!here.hidden) {
      here.style.left = pct(this.hereFrac);
      here.style.width = pct(Math.max((this.hereEndFrac ?? this.hereFrac) - this.hereFrac, 0));
    }
  }
}

// --- 왼쪽 칸: 왕의 재위 띠 ------------------------------------------
// 막대 = 재위, 동그라미 = 사망. 둘을 한 점으로 합치지 않는 이유는
// 물러나서도 산 임금이 여럿이기 때문이다 (태조 1398 퇴위 · 1408 사망,
// 고종 1907 퇴위 · 1919 사망). 재위 중에 죽은 임금은 막대 끝과 동그라미가
// 같은 자리에 겹치고, 그때 몰년은 막대 라벨의 뒷 숫자가 곧 몰년이다.
//
// 시대 연표(TimelineRail)와 개인 연표(life.js)가 같은 띠를 세운다 — 왕·
// 대통령의 자는 어느 연표에서든 같은 얼굴이어야 한다. `at` 은 해 → y.
export function reignBand(reigns, at, self = {}) {
  const c = REIGN_COLOR;
  const svg = [];
  const labels = [];       // {y, prio, html}
  // **고른 노드가 누구 때의 일인지 띠에서 바로 보이게 한다.** 연표가
  // 답해야 할 물음이 그것이다 — 갑자사화(1504)를 고르면 연산군의 막대가
  // 밝아진다. 고른 노드가 임금 자신이면 그 임금이 밝아진다.
  const now = (r) => self.id === r.id
    || (self.year != null && self.year >= r.start && self.year <= r.end);
  for (const [i, r] of reigns.entries()) {
    // **띠는 취임한 날에서 시작한다.** 해만 쓰면 12월에 취임한 대통령의
    // 막대와 이름이 그 해 1월에 선다 (박정희 1963-12-17 · 최규하
    // 1979-12-21 · 전두환 1980-09-01). 서버가 해 안의 자리를 소수로 준다
    // (`server._year_at`); 없는 것은 해의 첫날이다.
    const y1 = at(r.at_start ?? r.start);
    const y2 = Math.max(at(r.at_end ?? r.end), y1 + 2);
    const dy = r.death != null ? at(r.at_death ?? r.death) : null;
    const tip = `${r.label} · ${r.position} ${seatWord(r)} ${yr(r.start)}~`
      + (r.ongoing ? '' : yr(r.end))
      + (r.death != null ? ` · ${yr(r.death)} 사망` : '');
    // 이웃한 재위는 끝과 시작이 맞닿는다. 한 칸씩 걸러 진하게 칠해야
    // 어디서 갈리는지 보인다.
    const on = now(r);
    svg.push(`<rect class="tl-reign-bar${on ? ' k-on' : ''}" data-id="${esc(r.id)}"
        x="${BAR_X - BAR_W / 2}" y="${y1.toFixed(1)}" width="${BAR_W}"
        height="${(y2 - y1).toFixed(1)}" rx="${BAR_W / 2}" fill="${c}"
        opacity="${on ? 1 : i % 2 ? 0.5 : 0.78}"><title>${esc(tip)}</title></rect>`);
    if (dy != null && dy - y2 > 2) {
      // 물러난 뒤 산 기간. 막대에서 비스듬히 빠져나와 몰년에 닿는다.
      svg.push(`<path d="M${BAR_X} ${y2.toFixed(1)} L${DEATH_X} ${dy.toFixed(1)}"
          fill="none" stroke="${c}" stroke-width="1" stroke-dasharray="2 3" opacity=".6"/>`);
    }
    if (dy != null) {
      svg.push(`<circle cx="${DEATH_X}" cy="${dy.toFixed(1)}" r="2.8"
          fill="var(--surface-2)" stroke="${c}" stroke-width="1.4"><title>${esc(tip)}</title></circle>`);
    }
    labels.push({
      y: y1, prio: 0,
      html: `<button class="tl-reign${on ? ' k-on' : ''}" data-id="${esc(r.id)}" style="top:${y1.toFixed(1)}px"
               title="${esc(tip)}"><b>${esc(shortName(r.label))}</b><i>${shortYear(r.start)}~${r.ongoing ? '' : shortYear(r.end)}</i></button>`,
    });
    // 퇴위 뒤에도 산 임금만 몰년을 따로 적는다. 재위 중에 죽었으면
    // 위 막대 라벨의 뒷 숫자가 이미 몰년이라 두 번 적는 셈이 된다.
    //
    // **이름을 반드시 함께 적는다.** 물러난 임금의 몰년은 이미 다음
    // 임금의 재위 안이라, 연도만 적으면 그 자리의 막대 주인이 죽은
    // 것으로 읽힌다 (태조의 1408년 몰이 태종 재위 한가운데에 선다).
    if (r.death != null && r.death > r.end) {
      labels.push({
        y: dy, prio: 1,
        html: `<button class="tl-reign k-death" data-id="${esc(r.id)}" style="top:${dy.toFixed(1)}px"
                 title="${esc(tip)}"><i>${esc(shortName(r.label))} ${shortYear(r.death)} 사망</i></button>`,
      });
    }
  }
  // 라벨은 겹치면 못 읽는다. 재위 라벨이 몰년 라벨보다 먼저 자리를
  // 얻고, 자리가 없으면 물러난다 — 막대와 동그라미는 그대로 남으므로
  // 마우스를 올리면 언제나 이름과 연도를 말해 준다.
  const taken = [];
  const kept = labels
    .slice()
    .sort((a, b) => a.prio - b.prio || a.y - b.y)
    .filter((l) => {
      if (taken.some((y) => Math.abs(y - l.y) < LANE_GAP)) return false;
      taken.push(l.y);
      return true;
    })
    .sort((a, b) => a.y - b.y);
  return {
    svg: svg.join(''),
    items: kept.map((l) => l.html).join(''),
    // 이름을 못 세운 임금이 몇인지 알려야 한다. 막대는 다 서 있지만
    // 라벨이 없으면 화면에서는 없는 왕이나 마찬가지다.
    named: kept.filter((l) => l.prio === 0).length,
  };
}

// 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다 —
// 'A child_of B' 에서 들어오는 쪽 상대는 자녀다. app.js 의 상세 패널과
// 같은 규칙을 쓴다.
const DIR_HEAD = {
  child_of: { out: '부모', in: '자녀' },
  part_of: { out: '상위', in: '하위' },
  // 서버는 인과의 이름을 '원인'으로만 준다. 나가는 쪽 상대는 이 노드가
  // 부른 **결과**다 — 위화도 회군 옆에 과전법이 '원인'으로 서 있었다.
  caused: { out: '결과', in: '원인' },
};

// 라벨이 타입 이름보다 정확하면 서버가 `specific` 을 달아 보낸다
// ('피해'·'다음 일'). 그때는 방향으로 다시 부르지 않는다 — 이름이 이미
// 방향을 말한다. 2026-09-07 전수 조사: 연표의 딱지가 전부 '관련'이었다.
function relHead(rel) {
  if (rel.specific) return rel.label;
  return DIR_HEAD[rel.type]?.[rel.dir] || rel.label;
}

// 이 표시가 고른 노드의 **원인**인가. caused 엣지는 원인 → 결과이므로
// 들어오는(in) 쪽 상대가 원인이다. 결과(out)는 잇지 않는다 — 사용자가
// 부른 것은 원인뿐이고, 양쪽을 다 그리면 선이 어느 쪽으로 읽히는지 흐려진다.
export function isCause(m) {
  return m.rel?.type === 'caused' && m.rel?.dir === 'in';
}

// 원인 줄에서 오른쪽으로 나가 꺾여 내려오고(올라가고), 고른 노드의 줄로
// 되돌아오는 ㄷ 자 선. 끝에 작은 화살촉이 고른 노드를 가리킨다 —
// 원인이 결과로 흐른다는 방향은 색만으로는 안 읽힌다.
//   yFrom: 원인 줄의 y · yTo: 고른 노드 줄의 y · W: 연표 캔버스 너비
export const CAUSE_WIRE = { arm: 12, inset: 12, color: '#4f93bf' };   // --color-blue
// 왕·대통령의 재위 띠는 파랑이다 (2026-09-06 사용자 결정: 노드 팔레트가
// 빨강 계열로 바뀐 뒤에도 "전처럼 blue 를 유지"). 노드 색과 잇지 않는다 —
// 인물 노드가 빨강이 됐을 때 띠까지 따라가서 지적받았다.
export const REIGN_COLOR = '#3d84f5';
export function causeWire(yFrom, yTo, W) {
  const { arm, inset, color } = CAUSE_WIRE;
  const xR = W - inset;          // 세로 선 — 스크롤바와 그림자 안쪽
  const xS = xR - arm;           // 가로 팔이 시작하는 자리 (라벨 오른쪽 끝 + 2px)
  const f = (v) => Number(v).toFixed(1);
  return `<path d="M${f(xS)} ${f(yFrom)} H${f(xR)} V${f(yTo)} H${f(xS)}"
                fill="none" stroke="${color}" stroke-width="1.2"
                stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>
          <path d="M${f(xS + 4)} ${f(yTo - 3)} L${f(xS)} ${f(yTo)} L${f(xS + 4)} ${f(yTo + 3)}"
                fill="none" stroke="${color}" stroke-width="1.2"
                stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>`;
}

// 띠 칸은 좁다. 왕조 접두어는 띠 전체가 같은 왕조라 떼어도 헷갈리지
// 않는다 ('조선 세종' -> '세종'). 도구말에는 온 이름이 남는다.
const DYNASTY_HEAD = /^(고구려|백제|신라|가야|발해|후백제|태봉|고려|조선|대한제국|대한민국)\s+/;

function shortName(label) {
  return String(label || '').replace(DYNASTY_HEAD, '');
}

// 인물은 생년 자리에 선다. 이름만 적으면 그 해에 무엇을 했다는 것처럼
// 읽힌다 — 띠의 '사망'과 같은 꼴로 '탄생'을 붙인다. 붙이는 조건은
// **그 해가 정말 생년일 때**뿐이다: 날짜가 없어 이어진 사건으로 자리만
// 가늠한 인물(basis 'near')이나 시대 노드에서 연도를 받은 인물에게
// '탄생'을 적으면 모르는 것을 아는 척한 것이 된다.
//
// **나라는 첫 해에 '건국'을 단다.** '조선'이 1392년에 홀로 서 있으면 그 해에
// 조선이 무엇을 했다는 말인지 알 수 없다 — 그 해는 조선이 선 해다. 어느
// 나라가 건국인지는 서버가 정한다 (`founded`, 시대 묶음의 정체 노드 중
// 나라인 것). 일제강점기는 나라가 아니라 받지 않는다.
export function markName(m) {
  const label = String(m.label || '');
  if (m.founded) return `${label}건국`;   // 띄지 않는다 — '조선건국' (사용자 표기)
  if (m.type !== 'person') return label;
  const own = /^(-?\d{1,4})/.exec(String(m.date || ''));
  if (!own || Number(own[1]) !== m.year) return label;
  return `${label} 탄생`;
}

// 연도 칸에 무엇을 적는가. **그 해의 첫 줄**에는 해를 적고, 뒤따르는
// 줄에는 달을 적는다 — 늘어난 해에서 같은 숫자를 서른여덟 번 되풀이해
// 봐야 읽을 것이 없고, 달은 그 안의 차례를 실제로 설명한다.
//
// **달을 모르면 해를 다시 적되 흐리게 둔다.** 예전에는 비웠는데, 그러면
// 한 해에 둘만 서고 그 둘 다 날짜가 없을 때 뒤에 선 쪽만 연도 칸이 통째로
// 비어 '연도를 모르는 사건'으로 읽힌다 (실측: 1380년에 진포 해전과
// 황산대첩이 나란히 섰고, 가나다순으로 뒤인 황산대첩에 연도가 없었다).
// 모르는 것은 달이지 해가 아니다 — 아는 것을 지워 모르는 척할 이유는 없다.
//
// **다만 연도는 달보다 위에 선다** (2026-09-08 지적: "연도가 항상 달보다
// 위에 올라가야해"). '4월' 밑의 '1998' 은 해가 거기서 다시 시작하는 것처럼
// 읽힌다. 그래서 그 해에 달을 이미 적었으면(`monthShown`) 뒤따르는 줄은
// 해를 되풀이하지 않고 비운다 — 위의 실측과 어긋나지 않는다. 거기서 빈
// 것은 **달이 하나도 없던 해**의 줄이었고, 여기서 비는 것은 달을 적은
// 줄 바로 아래라 해가 눈에 남아 있다.
//
// 달은 **그 줄의 해와 같은 날짜**일 때만 적는다. 해와 날짜가 어긋난 자료
// (모델이 1998-04-24 사건을 1997 로 적어 온 것)가 1997 칸에 '4월'을
// 세우면 읽는 사람은 1997년 4월로 읽는다.
export function yearCell(m, prev, monthShown = false) {
  if (!prev || prev.year !== m.year) return { text: shortYear(m.year), repeat: false, month: false };
  const month = monthOf(m.date, m.year);
  if (month) return { text: month, repeat: false, month: true };
  return { text: monthShown ? '' : shortYear(m.year), repeat: true, month: false };
}

// 줄줄이 이어 적을 때의 연도 칸. 한 해 안에서 달을 적었는지를 들고 간다.
export function yearCells(marks) {
  let monthShown = false;
  return marks.map((m, i) => {
    const prev = i ? marks[i - 1] : null;
    if (!prev || prev.year !== m.year) monthShown = false;
    const cell = yearCell(m, prev, monthShown);
    if (cell.month) monthShown = true;
    return cell;
  });
}

// 왕은 재위하고 대통령은 재임한다. 서버가 자리의 종류를 준다.
function seatWord(r) {
  return r.kind === 'president' ? '재임' : '재위';
}

// 칩의 글자 — '왕 27' 또는 '왕 29 · 대통령 14'. 없는 쪽은 적지 않는다.
export function seatCount(reigns) {
  const kings = reigns.filter((r) => r.kind !== 'president').length;
  const presidents = reigns.length - kings;
  const parts = [];
  if (kings) parts.push(`왕 ${kings}`);
  if (presidents) parts.push(`대통령 ${presidents}`);
  return parts.join(' · ');
}

function seatHint(reigns) {
  const hasP = (reigns || []).some((r) => r.kind === 'president');
  const hasK = (reigns || []).some((r) => r.kind !== 'president');
  const who = hasP && hasK ? '왕의 재위와 대통령의 재임' : hasP ? '대통령의 재임' : '왕의 재위';
  return `왼쪽에 ${who} 기간을 막대로 세웁니다`;
}

function yr(y) {
  return y < 0 ? `기원전 ${-y}년` : `${y}년`;
}

// 축 옆 칸은 좁다. 기원전은 접두어를 줄여 쓴다.
function shortYear(y) {
  return y < 0 ? `전${-y}` : String(y);
}

// 부분 날짜에서 달만. '1592-04-15' -> '4월', '1592' -> '' (달을 모른다).
// 기원전은 앞에 부호가 붙어 한 칸 밀린다 ('-0400-04').
function monthOf(date, year = null) {
  const m = /^(-?\d{1,4})-(\d{2})/.exec(String(date || ''));
  if (!m || (year != null && Number(m[1]) !== year)) return '';
  return `${Number(m[2])}월`;
}

// 도구말에 적는 날. 아는 만큼만 적는다 — 날을 모르면 달까지, 달도 모르면
// 해까지다. 없는 자리를 1월 1일로 채워 말하지 않는다.
function whenText(m) {
  const d = /^(-?\d{1,4})-(\d{2})(?:-(\d{2}))?/.exec(String(m.date || ''));
  const head = yr(m.year);
  if (!d) return head;
  return d[3] ? `${head} ${Number(d[2])}월 ${Number(d[3])}일`
    : `${head} ${Number(d[2])}월`;
}

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
