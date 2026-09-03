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
];

export function SidePanel({ meta, seeds, settings, onSettings, onPick }) {
  const { depth, limit, includePeriod, showLabels, showRail } = settings;
  return (
    <aside className="side">
      <section>
        <h2>시작점</h2>
        <p className="hint">가장 많이 연결된 개체부터. 클릭하면 그 주변을 펼칩니다.</p>
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

      <section>
        <h2>범례</h2>
        <Legend nodeTypes={meta?.node_types} />
        <ul className="legend lines">
          {LINE_KINDS.map(({ dash, label }) => (
            <li key={label}>
              <svg width="26" height="10" aria-hidden="true">
                <line x1="1" y1="5" x2="25" y2="5" stroke="rgba(198,196,186,.6)"
                      strokeWidth="1.4" strokeDasharray={dash || undefined} />
              </svg>
              <span>{label}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>표시</h2>
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
        <label className="check">
          <input type="checkbox" checked={showLabels}
                 onChange={(e) => onSettings({ showLabels: e.target.checked })} />
          {' '}이름표 보이기
        </label>
        {/* 연표는 화면 폭을 250px 먹는다. 관계망만 크게 보고 싶을 때가 있다. */}
        <label className="check">
          <input type="checkbox" checked={showRail}
                 onChange={(e) => onSettings({ showRail: e.target.checked })} />
          {' '}왼쪽 연표 보이기
        </label>
        <p className="hint">노드 클릭 = 상세 + 주변 펼치기 · 드래그 = 고정 · 휠 = 확대</p>
      </section>
    </aside>
  );
}
