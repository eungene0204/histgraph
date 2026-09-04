import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api.js';
import { nodeColor } from '../lib/graph-view.js';
import { chainRows, chainName, pathSteps } from '../lib/relations.js';
import { Glyph } from './Glyph.jsx';

// 인과 사슬. "이 일은 무엇이 불렀고 무엇을 불렀나"를 원인 → 결과 엣지만
// 따라가 나무로 세운다. 관계 목록이 한 걸음이라면 여기는 여러 걸음이다 —
// 임진왜란 상세에서 병자호란까지가 한눈에 보여야 한다.
//
// 그리는 부분(ChainTree·PathView)은 자료를 받아 그리기만 한다. 서버에
// 묻는 것은 ChainPanel 하나다 — 그래야 브라우저 없이 그려서 잴 수 있다.

const KIND_ARROW = { in: '←', out: '→' };

function Row({ row, nodes, dir, onVisit }) {
  const n = nodes?.[row.id] || {};
  return (
    <div className="chain-row" style={{ marginLeft: row.depth * 14 }}>
      <span className="chain-arrow" aria-hidden="true">{KIND_ARROW[dir]}</span>
      <button className="chain-node" onClick={() => onVisit(row.id, { nest: true })}>
        <span className="rel-dot" style={{ background: nodeColor(n.type, n.group) }} />
        <span className="chain-name">{chainName(row, nodes)}</span>
      </button>
      <span className="chain-kind">{row.kind}</span>
      {(row.as || row.how) && (
        <span className="chain-how">
          {row.as && row.as !== chainName(row, nodes) && <b>{row.as}</b>}
          {row.as && row.how && ' · '}
          {row.how}
        </span>
      )}
    </div>
  );
}

// 원인 나무와 결과 나무. 둘 다 비어 있으면 아무것도 그리지 않는다 —
// "인과 없음"이라고 적어 봐야 아직 안 물어본 것인지 정말 없는 것인지 모른다.
export function ChainTree({ data, onVisit }) {
  if (!data) return null;
  const causes = chainRows(data.causes);
  const effects = chainRows(data.effects);
  if (!causes.length && !effects.length) return null;
  return (
    <div className="chain">
      {causes.length > 0 && (
        <>
          <div className="chain-head">이 일을 부른 것 · {causes.length}</div>
          {causes.map((r, i) => <Row key={`c-${r.id}-${i}`} row={r} nodes={data.nodes} dir="in" onVisit={onVisit} />)}
        </>
      )}
      {effects.length > 0 && (
        <>
          <div className="chain-head">이 일이 부른 것 · {effects.length}</div>
          {effects.map((r, i) => <Row key={`e-${r.id}-${i}`} row={r} nodes={data.nodes} dir="out" onVisit={onVisit} />)}
        </>
      )}
    </div>
  );
}

// 두 노드 사이의 경로. 걸음마다 종류와 '어떻게'를 적는다.
export function PathView({ data, onVisit }) {
  if (!data) return null;
  if (!data.found) return <p className="hint">인과 엣지로는 이어지지 않습니다.</p>;
  return (
    <div className="path">
      {data.reversed && <p className="hint">앞으로는 닿지 않고, 반대 방향으로 이어집니다.</p>}
      {data.paths.map((p, pi) => {
        const steps = pathSteps(p, data.nodes);
        return (
          <ol className="path-steps" key={pi}>
            {steps.map((s, i) => (
              <li key={`${s.id}-${i}`}>
                {i > 0 && (
                  <div className="path-edge">
                    <span className="chain-kind">{s.kind}</span>
                    {s.how && <span className="chain-how">{s.how}</span>}
                  </div>
                )}
                <button className="chain-node" onClick={() => onVisit(s.id, { nest: true })}>
                  <Glyph type={s.type} group={s.group} size={10} />
                  <span className="chain-name">{s.label}</span>
                  {s.year && <span className="chain-year">{s.year}</span>}
                </button>
              </li>
            ))}
          </ol>
        );
      })}
    </div>
  );
}

const DEBOUNCE_MS = 140;

// 두 사건 사이의 길 찾기. "…까지 이어졌는지 찾기"를 눌러야 열린다 — 나무가
// 못 보여주는 것(깊이 4 너머, 또는 '이어지지 않는다'는 답)을 묻는 자리다.
// 상대를 고르면 경로를 걸음마다 '어떻게'와 함께 그린다.
function PathFinder({ from, onVisit }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [rows, setRows] = useState(null);
  const [target, setTarget] = useState(null);
  const [result, setResult] = useState(null);
  const seqRef = useRef(0);

  useEffect(() => { setOpen(false); setQ(''); setRows(null); setTarget(null); setResult(null); }, [from.id]);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setRows(null); return; }
    let alive = true;
    const seq = seqRef.current;
    const timer = setTimeout(async () => {
      const found = await api.search(term, 8);
      if (!alive || seq !== seqRef.current) return;
      setRows(found.filter((r) => r.id !== from.id));
    }, DEBOUNCE_MS);
    return () => { alive = false; clearTimeout(timer); };
  }, [q, from.id]);

  const pick = async (r) => {
    seqRef.current += 1;
    setRows(null);
    setQ('');
    setTarget(r);
    setResult(null);
    setResult(await api.path(from.id, r.id));
  };

  if (!open) {
    return <button className="d-more" onClick={() => setOpen(true)}>다른 사건까지 이어졌는지 찾기</button>;
  }
  return (
    <div className="pathfinder">
      <p className="hint">인과 엣지를 따라 {from.label}에서 그 사건까지 가는 길을 찾습니다.</p>
      <input
        type="search"
        placeholder="사건 이름"
        autoComplete="off"
        spellCheck="false"
        autoFocus
        value={q}
        onChange={(ev) => setQ(ev.target.value)}
        onKeyDown={(ev) => {
          if (ev.key === 'Escape') { setOpen(false); return; }
          if (ev.key === 'Enter' && rows?.length) { ev.preventDefault(); pick(rows[0]); }
        }}
      />
      {rows && (
        <ul className="results pathfinder-results">
          {rows.length === 0
            ? <li className="empty-row">일치하는 개체가 없습니다</li>
            : rows.map((r) => (
              <li key={r.id} onClick={() => pick(r)}>
                <Glyph type={r.type} group={r.group} size={11} />
                <span>{(r.names || [r.label]).join(' · ')}</span>
              </li>
            ))}
        </ul>
      )}
      {target && (
        <>
          <div className="path-title">{from.label} → … → {target.label}</div>
          {result ? <PathView data={result} onVisit={onVisit} /> : <p className="hint">찾는 중…</p>}
        </>
      )}
    </div>
  );
}

export function ChainPanel({ node, onVisit }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    if (!node?.id) return undefined;
    api.chain(node.id).then((got) => { if (alive && !got.error) setData(got); });
    return () => { alive = false; };
  }, [node?.id]);

  // 인과 엣지가 하나도 없으면 아무것도 세우지 않는다 — 갈 길이 없는데
  // 이름을 치라고 할 이유가 없다. 나무 아래에는 길 찾기 하나만 둔다.
  // 먼 끝을 칩으로 다시 세우는 것은 나무의 되풀이였다 (2026-09-04 지적).
  if (!node || !data || !(data.causes?.length || data.effects?.length)) return null;
  return (
    <>
      <div className="d-section-title">인과 사슬</div>
      <ChainTree data={data} onVisit={onVisit} />
      <PathFinder from={node} onVisit={onVisit} />
    </>
  );
}
