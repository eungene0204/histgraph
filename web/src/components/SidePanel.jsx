import { Fragment } from 'react';
import { Glyph } from './Glyph.jsx';

// 색만으로 읽히지 않게 타입 이름을 늘 옆에 붙이고, 갈래별로 묶어 색상
// 계열이 눈에 잡히게 둔다.
const GROUP_LABEL = { actor: '인물·단체', event: '사건', thing: '장소·유물', frame: '시대·직위' };

function Legend({ nodeTypes }) {
  const groups = {};
  for (const [key, info] of Object.entries(nodeTypes || {})) {
    if (!info.count) continue;
    (groups[info.group] ||= []).push([key, info]);
  }
  // 묶음 머리와 항목이 **같은 층에** 있어야 한다 — CSS 가 `.legend li` 와
  // `.legend li.legend-group:first-child` 로 잡고 있어서, 중간에 <ul> 을
  // 하나 끼우면 여백과 첫 줄 처리가 어긋난다.
  return (
    <ul className="legend">
      {Object.entries(groups).map(([group, entries]) => (
        <Fragment key={group}>
          <li className="legend-group">{GROUP_LABEL[group]}</li>
          {entries.sort((a, b) => b[1].count - a[1].count).map(([key, info]) => (
            <li key={key} style={{ paddingLeft: 14 }}>
              <Glyph type={key} group={group} />
              <span>{info.label}</span>
              <span className="count">{info.count.toLocaleString()}</span>
            </li>
          ))}
        </Fragment>
      ))}
    </ul>
  );
}

const LINE_KINDS = [
  { dash: null, label: '구조화 소스 (확실)' },
  { dash: '5 4', label: '산문에서 추출 (근거 있음)' },
  { dash: '2 4', label: '동일 실체 (same_as)' },
  // 인과 도면(App.jsx CAUSAL_DIAGRAM)을 켜면 이 줄을 도면의 파랑 #4f93bf 으로.
  { dash: null, width: 2.8, label: '인과 (원인 → 결과)' },
];

// 조절 단추 아이콘 (lucide sliders-horizontal). Obsidian 의 그래프 설정이
// 접혀 있을 때 남는 단추와 같은 자리, 같은 뜻이다.
function SlidersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="21" x2="14" y1="4" y2="4" /><line x1="10" x2="3" y1="4" y2="4" />
      <line x1="21" x2="12" y1="12" y2="12" /><line x1="8" x2="3" y1="12" y2="12" />
      <line x1="21" x2="16" y1="20" y2="20" /><line x1="12" x2="3" y1="20" y2="20" />
      <line x1="14" x2="14" y1="2" y2="6" /><line x1="8" x2="8" y1="10" y2="14" />
      <line x1="16" x2="16" y1="18" y2="22" />
    </svg>
  );
}

// 설정 줄 하나 — Obsidian 의 setting-item. 슬라이더는 값을 옆에 적는다
// (Obsidian 은 툴팁으로 보여 주지만, 늘 보이는 편이 되돌리기 쉽다).
function Slider({ label, value, min, max, step, onChange, fmt = (v) => v.toFixed(1) }) {
  return (
    <label className="slider">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(+e.target.value)} />
      <i>{fmt(value)}</i>
    </label>
  );
}

// 그래프 설정 상자. 캔버스 왼쪽 위에 뜨고, 기본은 접혀서 단추만 남는다.
// 절은 Obsidian 그래프 설정과 같은 순서 — 필터·묶음(범례)·표시·힘 — 에
// 우리 것(시작점)을 앞에 하나 더 두었다. 절마다 <details> 라 따로 접힌다.
//
// 관계 종류 필터는 obsidian-better-graph-view 플러그인의 `edge:` 연산자를
// 옮긴 것이다 — Obsidian 그래프에 없어서 그 플러그인이 덧붙인 것이
// "관계 종류로 선을 거르기"였다. 우리 그래프는 관계에 종류가 있으니
// 검색 연산자 대신 체크 목록으로 둔다.
// `lines` 로 선 범례를 바꿔 줄 수 있고, `whole` 이면 그래프를 통째로 그리는 화면
// (개인 역사)이라 펼침 깊이·최대 노드·연도 포함·연표 스위치를 감춘다.
export function SidePanel({ open, onToggle, meta, seeds, settings, onSettings, onPick, lines = LINE_KINDS, whole = false }) {
  const {
    depth, limit, includePeriod, hiddenEdges = [],
    showLabels, showRail, arrows = true, textFade = 0.3, nodeScale = 1, lineScale = 1,
    centerForce = 1, repelForce = 1, linkDistance = 1,
  } = settings;
  const edgeTypes = Object.entries(meta?.edge_types || {})
    .filter(([, v]) => v.count > 0)
    .sort((a, b) => b[1].count - a[1].count);
  const toggleEdge = (key, on) => onSettings({
    hiddenEdges: on ? hiddenEdges.filter((k) => k !== key) : [...new Set([...hiddenEdges, key])],
  });
  return (
    <>
      <button
        className="clickable-icon graph-controls-toggle"
        aria-label="그래프 설정 열기"
        aria-expanded={open}
        title="시작점·필터·범례·표시·힘"
        onClick={onToggle}
      >
        <SlidersIcon />
      </button>
      <aside className="graph-controls" hidden={!open}>
        <button className="clickable-icon gc-close" aria-label="그래프 설정 닫기" onClick={onToggle}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>

        <details open>
          <summary>시작점</summary>
          <section>
            {/* 차례는 **무게**다 (central.py · life.js nodeWeight — 타입 가중
                PageRank). 연결 개수로 세우면 문서가 긴 쪽이 먼저 선다. 오른쪽
                수는 여전히 연결 개수라, 차례와 다를 수 있다고 적어 둔다. */}
            <p className="hint">{whole ? '이 그래프의 중심부터 (오른쪽 수는 연결 개수). 클릭하면 그리로 옮깁니다.' : '이 그래프의 중심부터 (오른쪽 수는 연결 개수). 클릭하면 그 주변을 펼칩니다.'}</p>
            <ul className="seeds">
              {seeds.map((s) => (
                <li key={s.id} onClick={() => onPick(s.id)}>
                  <Glyph type={s.type} group={s.group} size={11} />
                  <span>{s.label}</span>
                  <span className="meta">{s.degree}</span>
                </li>
              ))}
            </ul>
          </section>
        </details>

        <details>
          <summary>필터</summary>
          <section>
            {!whole && (<>
            <label className="row"><span>펼침 깊이</span>
              <select value={depth} onChange={(e) => onSettings({ depth: +e.target.value })}>
                <option value="1">1단계</option>
                <option value="2">2단계</option>
              </select>
            </label>
            <label className="row"><span>최대 노드</span>
              <select value={limit} onChange={(e) => onSettings({ limit: +e.target.value })}>
                <option value="60">60</option>
                <option value="120">120</option>
                <option value="220">220</option>
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={includePeriod}
                     onChange={(e) => onSettings({ includePeriod: e.target.checked })} />
              {' '}연도·시대 노드 포함
            </label>
            </>)}
            {edgeTypes.length > 0 && (
              <>
                <p className="gc-sub">관계 종류</p>
                <ul className="edge-filter">
                  {edgeTypes.map(([key, info]) => (
                    <li key={key}>
                      <label className="check">
                        <input type="checkbox" checked={!hiddenEdges.includes(key)}
                               onChange={(e) => toggleEdge(key, e.target.checked)} />
                        {' '}{info.label}
                        <span className="meta">{info.count.toLocaleString()}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </details>

        <details open>
          <summary>범례</summary>
          <section>
            <Legend nodeTypes={meta?.node_types} />
            <ul className="legend lines">
              {lines.map(({ dash, width, color, label }) => (
                <li key={label}>
                  <svg width="26" height="10" aria-hidden="true">
                    <line x1="1" y1="5" x2="25" y2="5" stroke={color || 'currentColor'}
                          strokeWidth={width || 1.4} strokeDasharray={dash || undefined} />
                  </svg>
                  <span>{label}</span>
                </li>
              ))}
            </ul>
          </section>
        </details>

        <details open>
          <summary>표시</summary>
          <section>
            <label className="check">
              <input type="checkbox" checked={arrows}
                     onChange={(e) => onSettings({ arrows: e.target.checked })} />
              {' '}화살촉
            </label>
            <label className="check">
              <input type="checkbox" checked={showLabels}
                     onChange={(e) => onSettings({ showLabels: e.target.checked })} />
              {' '}이름표 보이기
            </label>
            {/* 연표는 화면 폭을 250px 먹는다. 관계망만 크게 보고 싶을 때가 있다. */}
            {!whole && (
            <label className="check">
              <input type="checkbox" checked={showRail}
                     onChange={(e) => onSettings({ showRail: e.target.checked })} />
              {' '}왼쪽 연표 보이기
            </label>)}
            <Slider label="이름표 흐림 문턱" value={textFade} min={0} max={1} step={0.05}
                    onChange={(v) => onSettings({ textFade: v })} />
            <Slider label="노드 크기" value={nodeScale} min={0.5} max={2} step={0.1}
                    onChange={(v) => onSettings({ nodeScale: v })} />
            <Slider label="선 굵기" value={lineScale} min={0.5} max={3} step={0.1}
                    onChange={(v) => onSettings({ lineScale: v })} />
            <p className="hint">{whole ? '노드 클릭 = 상세 · 드래그 = 고정 · 휠 = 확대' : '노드 클릭 = 상세 + 주변 펼치기 · 드래그 = 고정 · 휠 = 확대'}</p>
          </section>
        </details>

        <details>
          <summary>힘</summary>
          <section>
            <Slider label="중심 힘" value={centerForce} min={0} max={2} step={0.1}
                    onChange={(v) => onSettings({ centerForce: v })} />
            <Slider label="반발 힘" value={repelForce} min={0.2} max={3} step={0.1}
                    onChange={(v) => onSettings({ repelForce: v })} />
            <Slider label="링크 거리" value={linkDistance} min={0.4} max={2.5} step={0.1}
                    onChange={(v) => onSettings({ linkDistance: v })} />
          </section>
        </details>
      </aside>
    </>
  );
}
