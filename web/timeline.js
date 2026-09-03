// 연표 — 고른 노드가 몇 년쯤의 일이고, 무엇 뒤 무엇 앞인지.
//
// **절대 연도는 위치를 말해주지 못한다.** '1504년'을 들어도 그게 조선의
// 어디쯤인지 아는 사람은 드물다. 사람이 실제로 쓰는 좌표는 아는 사건과의
// 앞뒤다 — "무오사화 다음, 중종반정 직전". 그래서 이 막대는 고른 노드
// 하나만 찍지 않고 그 무렵의 큰 사건과 연도를 아는 이웃을 함께 세운다.
//
// **자리는 연도에 비례한다.** 목록으로 늘어놓으면 1400년과 1401년 사이가
// 1400년과 1500년 사이와 똑같이 벌어져, 연표라고 부를 수 없게 된다.
// 다만 라벨은 겹치면 못 읽으므로 밀어서 떨어뜨리고, 실제 자리와 밀린
// 자리는 가는 실선으로 이어 둔다 — 어긋난 만큼이 눈에 보여야 속지 않는다.
// 그 선에 노드 색을 쓰지 않는 이유는 관계선으로 읽히기 때문이다 (실측:
// 1398년에 나란히 선 '왕자의 난'과 '제1차 왕자의 난'이 이어진 것으로
// 보였는데, 그때 그래프에는 둘 사이에 엣지가 하나도 없었다).
//
// **줌은 자리가 아니라 밀도를 바꾼다.** 지도가 멀리서는 큰 도시만, 가까이
// 가면 동네까지 보여주듯이, 연표도 멀리서는 큰 사건만 세우고 가까이 갈수록
// 더 많은 사건을 세운다. 무엇이 '큰' 사건인지는 그래프가 정한다 — 많이
// 연결된 사건이 먼저 자리를 얻고, 겹치는 자리에 오는 작은 사건은 다음
// 단계에서야 나타난다. 마지막 단계는 전부 세운다.

import { nodeColor, TYPE_COLOR } from '/graph.js';

// **왼쪽에는 왕의 재위 띠가 선다.** 조선의 시간을 사람은 절대 연도가
// 아니라 임금으로 읽는다 — '1456년'보다 '세조 때'가 먼저 온다. 재위는
// 구간이므로 점이 아니라 막대로 긋고, 사망은 재위의 끝이 아니라서
// (태조는 1398년에 물러나 1408년에 죽었다) 따로 찍어 점선으로 잇는다.
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
const DOT_X = 58;     // 라벨이 시작하는 자리
const PAD_TOP = 18;   // 첫 표시가 머리에 붙지 않게
// 아래는 넉넉히 둔다. 마지막 사건이 축 끝에 딱 붙으면 스크롤을 끝까지
// 내려도 패널 바닥과 '더 있다'는 그림자(28px)에 눌려 반쯤 지워진다.
const PAD_BOTTOM = 64;
const GAP = 30;       // 라벨 두 줄이 서로를 가리지 않는 최소 간격

// 줌 단계. 0단계는 시대 전체가 한 화면에 들어오는 눈금이고, 한 단계마다
// 눈금이 두 배가 된다. 조선(567년)은 패널 높이 760px 에서 1.3 → 2.7 → 5.4
// → 11 → 21px/년. 마지막 단계는 밀도 상한을 풀고 전부 세운다.
const MAX_LEVEL = 4;
// 안전판. 시대를 나누지 않은 전체 그래프는 기원전까지 걸쳐 있어 마지막
// 단계에서 끝없이 길어진다.
const MAX_HEIGHT = 40000;

export class TimelineRail {
  constructor(root, { onPick } = {}) {
    this.root = root;
    this.onPick = onPick || (() => {});
    this.data = null;
    this.body = root.querySelector('.tl-body');
    this.head = root.querySelector('.tl-head');
    // 새로고침해도 들여다보던 배율을 지킨다. 못 읽으면 0단계.
    this.level = 0;
    this.lane = 0;
    // 재위 띠는 기본으로 켠다. 끈 사람은 그 선택을 기억한다.
    this.showReigns = true;
    try {
      this.level = clamp(+localStorage.getItem('tl-zoom') || 0, 0, MAX_LEVEL);
      this.showReigns = localStorage.getItem('tl-reigns') !== '0';
    } catch { /* 비공개 창 등 */ }
    this.focusPy = 0;
    // 지금 배치의 축 — 연도 <-> 픽셀 환산에 쓴다
    this.axis = { from: 0, to: 1, H: 1 };

    // 재위 막대와 띠 라벨도 노드다 — 누르면 그 임금으로 옮긴다.
    this.body.addEventListener('click', (ev) => {
      const el = ev.target.closest('.tl-mark[data-id], .tl-reign[data-id], .tl-reign-bar[data-id]');
      if (el) this.onPick(el.dataset.id);
    });
    // 연표가 화면보다 길어졌으니 훑다 보면 고른 자리를 잃는다. 머리의
    // 연도를 누르면 그 자리로 돌아온다 (머리는 스크롤을 타지 않는다).
    this.head.addEventListener('click', (ev) => {
      if (ev.target.closest('.tl-when')) this.recenter();
      const z = ev.target.closest('.tl-zoom button');
      if (z) this.zoom(+z.dataset.dir);
      if (ev.target.closest('.tl-kings')) this.toggleReigns();
    });

    this.body.addEventListener('scroll', () => this.syncMap(), { passive: true });

    // ⌘/Ctrl+휠, 트랙패드 핀치는 줌. 그냥 휠은 스크롤이어야 한다 — 연표를
    // 훑는 몸짓이 그것이라, 줌으로 가로채면 위아래로 못 움직인다.
    let wheelAcc = 0;
    this.body.addEventListener('wheel', (ev) => {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      ev.preventDefault();
      wheelAcc += ev.deltaY;
      // 핀치는 한 번에 몇 픽셀씩 잘게 온다. 모아서 한 단계씩 넘긴다.
      if (Math.abs(wheelAcc) < 40) return;
      const dir = wheelAcc < 0 ? 1 : -1;
      wheelAcc = 0;
      const rect = this.body.getBoundingClientRect();
      this.zoom(dir, ev.clientY - rect.top);
    }, { passive: false });

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
    new ResizeObserver(() => this.layout({ keepView: true })).observe(this.body);
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
        <div class="tl-zoom" role="group" aria-label="연표 줌">
          <button data-dir="-1" title="줌아웃 — 큰 사건만 (⌘+휠)">−</button>
          <span class="tl-level" aria-live="polite"></span>
          <button data-dir="1" title="줌인 — 더 많은 사건 (⌘+휠)">+</button>
        </div>
      </div>
      <button class="tl-when" title="고른 자리로 돌아가기">${esc(when)}${via}</button>
      <div class="tl-count"></div>
      ${kings ? `<button class="tl-kings" aria-pressed="${this.showReigns}"
            title="왼쪽에 왕의 재위 기간을 막대로 세웁니다">왕 ${kings}</button>` : ''}
      <div class="tl-map" hidden title="누르거나 끌어서 연표를 옮깁니다">
        <span>${d.axis.from}</span>
        <div class="tl-map-bar"><i class="tl-map-view"></i><b class="tl-map-here" hidden></b></div>
        <span>${d.axis.to}</span>
      </div>
      ${hint ? `<p class="tl-hint">${esc(hint)}</p>` : ''}`;
  }

  // --- 줌 --------------------------------------------------------------
  // anchorY: 패널 안에서 제자리를 지킬 픽셀 위치. 휠은 커서 아래를, 버튼은
  // 고른 노드(화면 안에 있으면)를 고정한다 — 들여다보던 해가 달아나면 줌이
  // 아니라 점프다.
  zoom(dir, anchorY = null) {
    const next = clamp(this.level + dir, 0, MAX_LEVEL);
    if (next === this.level) return;
    const b = this.body;
    if (anchorY === null) {
      // 버튼 줌: 고른 노드가 화면 안에 있으면 그 노드를, 아니면 가운데를 지킨다
      const selfY = this.focusPy - b.scrollTop;
      anchorY = selfY >= 0 && selfY <= b.clientHeight ? selfY : b.clientHeight / 2;
    }
    const year = this.yearAt(b.scrollTop + anchorY);
    this.level = next;
    try { localStorage.setItem('tl-zoom', String(next)); } catch { /* 저장 못 해도 동작한다 */ }
    this.layout();
    b.scrollTop = this.yOf(year) - anchorY;
    this.syncMap();
  }

  // 재위 띠를 켜고 끈다. 패널이 그만큼 넓어졌다 좁아진다.
  toggleReigns() {
    this.showReigns = !this.showReigns;
    try { localStorage.setItem('tl-reigns', this.showReigns ? '1' : '0'); } catch { /* 저장 못 해도 동작한다 */ }
    this.renderHead();
    this.layout({ keepView: true });
  }

  yOf(year) {
    const { from, to, H } = this.axis;
    return PAD_TOP + (clamp(year, from, to) - from) / Math.max(to - from, 1) * (H - PAD_TOP - PAD_BOTTOM);
  }

  yearAt(y) {
    const { from, to, H } = this.axis;
    return from + (y - PAD_TOP) / Math.max(H - PAD_TOP - PAD_BOTTOM, 1) * (to - from);
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
    // 창 크기가 바뀌어 다시 그리는 경우엔 보던 해를 지킨다
    const viewYear = keepView ? this.yearAt(this.body.scrollTop + this.body.clientHeight / 2) : null;

    // 재위 띠가 왼쪽 칸을 먹고, 축과 라벨은 그만큼 오른쪽으로 밀린다.
    const reigns = (d.reigns || []);
    const lane = this.lane = this.showReigns && reigns.length ? LANE_W : 0;
    this.root.style.width = `${PANEL_W + lane}px`;
    const AX = lane + AXIS_X;
    const DX = lane + DOT_X;

    const { from, to } = d.axis;
    const span = Math.max(to - from, 1);
    const bodyH = this.body.clientHeight || 600;
    // 0단계 = 시대 전체가 한 화면. 단계마다 두 배.
    const fit = (bodyH - PAD_TOP - PAD_BOTTOM) / span;
    const scale = fit * 2 ** this.level;
    const full = this.level === MAX_LEVEL;   // 마지막 단계는 전부 세운다
    let H = Math.min(MAX_HEIGHT, span * scale + PAD_TOP + PAD_BOTTOM);
    // 전부 세울 때는 라벨이 다 들어갈 만큼은 늘린다. 안 그러면 밀어낼
    // 자리가 없어 끝에서 겹친다.
    if (full) H = Math.max(H, marks.length * GAP + PAD_TOP + PAD_BOTTOM);
    this.axis = { from, to, H };
    const at = (year) => this.yOf(year);

    // --- 이 단계에서 누가 서는가 ---------------------------------------
    // 고른 노드·왕조·이웃은 늘 선다 — 그 노드의 이야기이지 배경이 아니다.
    // 뼈대(큰 사건)는 많이 연결된 것부터 자리를 잡고, 이미 선 것과 겹치면
    // 이 단계에서는 물러난다. 눈금이 두 배가 되면 겹치던 자리가 벌어져
    // 다음 사건이 들어온다.
    const always = marks.filter((m) => m.kind !== 'anchor');
    const bones = marks.filter((m) => m.kind === 'anchor')
      .sort((a, b) => (b.degree || 0) - (a.degree || 0) || a.year - b.year);
    const taken = always.map((m) => at(m.year));
    const visible = [...always];
    let hidden = 0;
    for (const m of bones) {
      const ty = at(m.year);
      if (!full && taken.some((y) => Math.abs(y - ty) < GAP)) { hidden++; continue; }
      taken.push(ty);
      visible.push(m);
    }
    visible.sort((a, b) => a.year - b.year || a.label.localeCompare(b.label, 'ko'));

    // 실제 자리(ty)를 잡고, 겹치면 아래로 민다. 끝에서 넘치면 위로 되민다.
    const place = visible.map((m) => ({ m, ty: at(m.year), py: 0 }));
    let prev = -Infinity;
    for (const p of place) p.py = prev = Math.max(p.ty, prev + GAP);
    let next = H - PAD_BOTTOM + GAP;
    for (let i = place.length - 1; i >= 0; i--) {
      place[i].py = next = Math.max(PAD_TOP, Math.min(place[i].py, next - GAP));
    }

    const wires = place.map(({ m, ty, py }) => {
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
      // 라벨이 제 해에서 밀렸을 때만 잇는다. **관계선처럼 보이면 안 된다** —
      // 실측: 1398년에 '왕자의 난'과 '제1차 왕자의 난'이 함께 서서 한 줄이
      // 밀렸는데, 노드 색으로 그은 선이라 둘이 이어진 것으로 읽혔다
      // (그때 그래프에는 둘 사이에 엣지가 하나도 없었다). 갈리는 것은 색이다 —
      // 회색 실선은 글자를 제자리에 데려다 놓는 안내선이지 관계가 아니다.
      const off = Math.abs(py - ty) > 1.5
        ? `<path d="M${AX} ${ty} C${AX + 7} ${ty}, ${DX - 9} ${py}, ${DX - 2} ${py}"
                 fill="none" stroke="var(--text-3)" stroke-width="1" opacity=".45"/>`
        : '';
      return `${bar}${off}
        <circle cx="${AX}" cy="${ty}" r="${m.kind === 'self' ? 4 : 2.6}" fill="${c}"/>`;
    }).join('');

    const items = place.map(({ m, py }) => `
      <button class="tl-mark k-${m.kind}" data-id="${esc(m.id)}" style="top:${py.toFixed(1)}px"
              title="${esc(m.label)}">
        <span class="tl-y">${esc(shortYear(m.year))}</span>
        <span class="tl-name">${esc(m.label)}</span>
        ${m.rel ? `<span class="tl-rel">${esc(relHead(m.rel))}</span>` : ''}
      </button>`).join('');

    const band = lane
      ? this.reignBand(reigns, at, { id: d.id, year: d.year })
      : { svg: '', items: '', named: 0 };

    this.body.innerHTML = `
      <div class="tl-canvas" style="height:${H}px; --lane:${lane}px">
        <svg class="tl-wires" width="100%" height="${H}" aria-hidden="true">
          <line x1="${AX}" y1="${PAD_TOP - 8}" x2="${AX}" y2="${H - PAD_BOTTOM + 8}"
                stroke="var(--line)" stroke-width="1"/>
          ${band.svg}
          ${wires}
        </svg>
        ${band.items}
        ${items}
      </div>`;

    // 몇 개가 물러나 있는지 늘 말한다. 안 보이는 사건이 없는 셈이 되면
    // 안 되므로, 숫자로라도 '더 있다'를 남긴다.
    const shown = visible.filter((m) => m.kind === 'anchor').length;
    const count = this.head.querySelector('.tl-count');
    if (count) {
      count.innerHTML = `큰 사건 <b>${shown}</b> / ${bones.length}`
        + (hidden ? ` <span class="tl-more">· 더 보려면 +</span>` : '');
    }
    const chip = this.head.querySelector('.tl-kings');
    if (chip) {
      const all = reigns.length;
      chip.textContent = !lane || band.named >= all ? `왕 ${all}` : `왕 ${band.named}/${all}`;
      chip.title = !lane
        ? '왼쪽에 왕의 재위 기간을 막대로 세웁니다'
        : band.named >= all
        ? '막대가 재위, 동그라미가 몰년입니다'
        : `이름을 세울 자리가 모자란 임금 ${all - band.named}명은 막대만 있습니다`
          + ' — 줌인하거나 막대에 마우스를 올리면 이름이 나옵니다';
    }
    const lvl = this.head.querySelector('.tl-level');
    if (lvl) {
      lvl.textContent = full ? '전부' : `${this.level + 1}/${MAX_LEVEL + 1}`;
      lvl.title = full ? '연대를 아는 사건을 다 세웠습니다' : `줌 ${this.level + 1}단계`;
    }
    for (const b of this.head.querySelectorAll('.tl-zoom button')) {
      b.disabled = (+b.dataset.dir < 0 && this.level === 0)
                || (+b.dataset.dir > 0 && this.level === MAX_LEVEL);
    }

    const self_ = place.find((p) => p.m.kind === 'self');
    const focus = self_ || place.find((p) => p.m.kind === 'near')
      || place[Math.floor(place.length / 2)];
    this.focusPy = focus.py;
    // 훑기 막대의 표식은 **밀리기 전 제자리**를 쓴다. 라벨이 밀린 자리를
    // 찍으면 막대가 축과 다른 해를 가리킨다.
    this.hereFrac = self_ ? self_.ty / H : null;
    this.hereEndFrac = self_ && self_.m.end != null && self_.m.end !== self_.m.year
      ? at(self_.m.end) / H : null;
    if (recenter) this.recenter();
    else if (viewYear !== null) this.body.scrollTop = this.yOf(viewYear) - this.body.clientHeight / 2;
    this.syncMap();
  }

  // --- 왼쪽 칸: 왕의 재위 띠 ------------------------------------------
  // 막대 = 재위, 동그라미 = 사망. 둘을 한 점으로 합치지 않는 이유는
  // 물러나서도 산 임금이 여럿이기 때문이다 (태조 1398 퇴위 · 1408 사망,
  // 고종 1907 퇴위 · 1919 사망). 재위 중에 죽은 임금은 막대 끝과 동그라미가
  // 같은 자리에 겹치고, 그때 몰년은 막대 라벨의 뒷 숫자가 곧 몰년이다.
  reignBand(reigns, at, self = {}) {
    const c = TYPE_COLOR.person;
    const svg = [];
    const labels = [];       // {y, prio, html}
    // **고른 노드가 누구 때의 일인지 띠에서 바로 보이게 한다.** 연표가
    // 답해야 할 물음이 그것이다 — 갑자사화(1504)를 고르면 연산군의 막대가
    // 밝아진다. 고른 노드가 임금 자신이면 그 임금이 밝아진다.
    const now = (r) => self.id === r.id
      || (self.year != null && self.year >= r.start && self.year <= r.end);
    for (const [i, r] of reigns.entries()) {
      const y1 = at(r.start);
      const y2 = Math.max(at(r.end), y1 + 2);
      const dy = r.death != null ? at(r.death) : null;
      const tip = `${r.label} · ${r.position} 재위 ${yr(r.start)}~${yr(r.end)}`
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
                 title="${esc(tip)}"><b>${esc(shortName(r.label))}</b><i>${shortYear(r.start)}~${shortYear(r.end)}</i></button>`,
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

  recenter() {
    this.body.scrollTo({ top: this.focusPy - this.body.clientHeight / 2, behavior: 'smooth' });
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

// 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다 —
// 'A child_of B' 에서 들어오는 쪽 상대는 자녀다. app.js 의 상세 패널과
// 같은 규칙을 쓴다.
const DIR_HEAD = {
  child_of: { out: '부모', in: '자녀' },
  part_of: { out: '상위', in: '하위' },
};

function relHead(rel) {
  return DIR_HEAD[rel.type]?.[rel.dir] || rel.label;
}

// 띠 칸은 좁다. 왕조 접두어는 띠 전체가 같은 왕조라 떼어도 헷갈리지
// 않는다 ('조선 세종' -> '세종'). 도구말에는 온 이름이 남는다.
const DYNASTY_HEAD = /^(고구려|백제|신라|가야|발해|후백제|태봉|고려|조선|대한제국|대한민국)\s+/;

function shortName(label) {
  return String(label || '').replace(DYNASTY_HEAD, '');
}

function yr(y) {
  return y < 0 ? `기원전 ${-y}년` : `${y}년`;
}

// 축 옆 칸은 좁다. 기원전은 접두어를 줄여 쓴다.
function shortYear(y) {
  return y < 0 ? `전${-y}` : String(y);
}

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
