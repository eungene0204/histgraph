import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ThemeToggle } from './ThemeToggle.jsx';
import { GraphCanvas } from './GraphCanvas.jsx';
import { SidePanel } from './SidePanel.jsx';
import { LifeBoard, normalize, graphPayload, graphMeta, boardWidth, NODE_TYPE_KO, EDGE_TYPE_KO, IMPACT_KO, CAUSAL_EDGES, EVENT_TYPES } from '../lib/life.js';

// 개인 역사 화면 (/life.html). 왼쪽 왕·대통령 띠 · 가운데 한국사 · 오른쪽
// 내 역사 — 세 열이 한 자 위에 선다 (lib/life.js). 오른쪽 끝 패널이 고른
// 사건의 상세와 분석(가족 뿌리·전환점·패턴·영향·가상 역사·물음)을 읽는다.
//
// 자료는 셋 중 하나에서 온다: (1) 로컬 서버가 저장한 것(/api/life —
// `histgraph life` 가 만든다), (2) 사람이 붙여 넣거나 올린 JSON (브라우저에
// 남긴다 — 배포된 화면에는 서버 저장이 없다), (3) 예시. 역사 쪽 자료
// (재위 띠·큰 사건)는 언제나 서버(/api/context)다.

const STORE_KEY = 'life-json';
const RAIL_KEY = 'life-rail';   // 연표를 접어 두었나 ('0' 이면 접힘)

// 개인 그래프의 선 범례. 역사 그래프의 '구조화 소스/산문 추출' 대신 —
// 실선은 본인이 말한 것, 점선은 말한 것에서 미룬 것(confidence < 1).
const LIFE_LINES = [
  { dash: null, label: '본인이 말한 것 (확실)' },
  { dash: '5 4', label: '말한 것에서 미룬 것' },
];

async function getJson(path) {
  const res = await fetch(path);
  if (!res.ok) return null;
  return res.json();
}

// 서버에 물을 구간 — 이 사람의 삶이다. 이어진 역사 사건이 그보다 앞서면
// (할아버지의 6·25) 그 사건은 연결 자체가 이름·해를 들고 있으니 따로 안 묻는다.
function yearsOf(life) {
  const ys = [];
  for (const t of life.timeline) if (t.year != null) ys.push(t.year);
  for (const n of life.nodes) if (n.year != null && EVENT_TYPES.has(n.type)) ys.push(n.year);
  if (life.subject?.birth_year != null) ys.push(life.subject.birth_year);
  if (!ys.length) return null;
  return [Math.min(...ys) - 2, Math.max(...ys, new Date().getFullYear()) + 1];
}

export default function LifeView() {
  const [life, setLife] = useState(null);
  const [context, setContext] = useState(null);
  const [source, setSource] = useState('');       // 'server' | 'local' | 'sample'
  // 주소의 #사건id 가 고른 사건이다 — 새로고침해도 자리를 잃지 않고 "이거 봐" 하고 줄 수 있다.
  const [selected, setSelected] = useState(() => (typeof location !== 'undefined' && location.hash ? decodeURIComponent(location.hash.slice(1)) : null));
  const [tab, setTab] = useState('event');
  const [pasting, setPasting] = useState(false);
  const [offline, setOffline] = useState(false);
  const rootRef = useRef(null);
  const boardRef = useRef(null);

  // --- 그래프 (역사 그래프와 같은 캔버스·설정 상자) ---------------------
  // **연표와 그래프는 동시에 보인다** (2026-09-07 사용자: "연표와 그래프를
  // 동시에 보여줘"). 역사 화면과 같은 배치 — 왼쪽 연표, 가운데 그래프, 오른쪽
  // 상세. 연표는 세 열이라 넓으니(boardWidth) 접을 수 있게만 한다.
  const [railOpen, setRailOpen] = useState(() => {
    try { return localStorage.getItem(RAIL_KEY) !== '0'; } catch { return true; }
  });
  const toggleRail = () => {
    setRailOpen((v) => {
      try { localStorage.setItem(RAIL_KEY, v ? '0' : '1'); } catch { /* 저장 못 해도 동작한다 */ }
      return !v;
    });
  };
  const [sideOpen, setSideOpen] = useState(false);
  const [settings, setSettings] = useState({
    depth: 2, limit: 120, includePeriod: false, hiddenEdges: [],
    showLabels: true, showRail: true, arrows: true,
    textFade: 0.3, nodeScale: 1, lineScale: 1,
    centerForce: 1, repelForce: 1, linkDistance: 1,
  });
  const viewRef = useRef(null);
  const meta = useMemo(() => (life ? graphMeta(life) : null), [life]);

  // 자료를 받아들이는 한 길. 날것이든 서버를 거친 것이든 normalize 를 지난다.
  const adopt = useCallback(async (raw, from) => {
    let norm;
    try { norm = normalize(raw); } catch { return false; }
    if (!norm.nodes.length) return false;
    setLife(norm);
    setSource(from);
    setSelected((cur) => (cur && norm.nodes.some((n) => n.id === cur) ? cur : null));
    if (from === 'local') {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(raw)); } catch { /* 저장 못 해도 본다 */ }
    }
    const span = yearsOf(norm);
    if (span) {
      const ctx = await getJson(`/api/context?from=${span[0]}&to=${span[1]}`).catch(() => null);
      setOffline(!ctx);
      setContext(ctx || { reigns: [], anchors: [] });
    } else {
      setContext({ reigns: [], anchors: [] });
    }
    return true;
  }, []);

  const loadSample = useCallback(async () => {
    const raw = await getJson('/life-sample.json').catch(() => null);
    if (raw) adopt(raw, 'sample');
  }, [adopt]);

  // 부팅: 서버 → 브라우저에 남긴 것 → 빈 화면
  useEffect(() => {
    let alive = true;
    (async () => {
      const server = await getJson('/api/life').catch(() => null);
      if (!alive) return;
      if (server && await adopt(server, 'server')) return;
      let kept = null;
      try { kept = JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch { /* 비었다 */ }
      if (kept && await adopt(kept, 'local')) return;
    })();
    return () => { alive = false; };
  }, [adopt]);

  // 판 — DOM 을 직접 그리는 쪽
  useEffect(() => {
    const board = new LifeBoard(rootRef.current, { onPick: (id) => { setSelected(id); setTab('event'); } });
    boardRef.current = board;
    return () => board.destroy();
  }, []);
  useEffect(() => {
    if (life && context) boardRef.current?.show({ life, context, selected });
  }, [life, context]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    boardRef.current?.select(selected);
    if (typeof history !== 'undefined') history.replaceState(null, '', selected ? `#${encodeURIComponent(selected)}` : location.pathname);
  }, [selected]);
  // 그래프는 통째로 싣는다 — 수십 노드라 자를 이유가 없다. 고른 노드가 중심.
  // 캔버스는 자료가 있을 때 붙어 있다(GraphCanvas 가 그때 마운트). 같은
  // 커밋에서 자식 효과가 먼저 돌아 viewRef 가 채워진 뒤 이 효과가 돈다.
  useEffect(() => {
    const gv = viewRef.current;
    if (!gv || !life) return;
    gv.setData(graphPayload(life, selected));
    if (selected) { gv.select(selected); gv.focusOn(selected); }
  }, [life]);   // eslint-disable-line react-hooks/exhaustive-deps
  // 연표에서 고르든 그래프에서 고르든 같은 노드다 — 그래프의 조명도 따라간다.
  useEffect(() => {
    const gv = viewRef.current;
    if (!gv || !selected || !gv.byId.has(selected)) return;
    gv.select(selected);
    gv.focusOn(selected);
  }, [selected]);
  // 연표를 접었다 펴면 캔버스 폭이 바뀐다 — GraphView 의 ResizeObserver 가 따라간다.

  const onFile = async (ev) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    try { await adopt(JSON.parse(await f.text()), 'local'); } catch { alert('JSON 을 읽지 못했습니다.'); }
    ev.target.value = '';
  };
  const onPaste = async (text) => {
    try {
      const ok = await adopt(JSON.parse(text), 'local');
      if (ok) setPasting(false);
      else alert('노드가 없는 JSON 입니다.');
    } catch { alert('JSON 이 아닙니다.'); }
  };
  const forget = () => {
    try { localStorage.removeItem(STORE_KEY); } catch { /* 없다 */ }
    setLife(null); setContext(null); setSource(''); setSelected(null);
  };

  const name = life?.subject?.name || '나';
  const sourceText = { server: '로컬 서버에 저장된 자료', local: '이 브라우저에 남긴 자료', sample: '예시 자료' }[source] || '';

  return (
    <>
      <header className="top life-top">
        <div className="brand">
          <span className="mark" />
          <h1>histgraph</h1>
          <a className="era" href="/">한국사 그래프</a>
          <span className="era life-here">내 역사</span>
        </div>
        <div className="life-tools">
          {life && (
            <button type="button" className="life-btn" onClick={toggleRail} aria-pressed={railOpen}
                    title="왼쪽 연표를 접거나 폅니다">{railOpen ? '연표 접기' : '연표 펴기'}</button>
          )}
          {life && <span className="life-source">{sourceText}</span>}
          <button type="button" className="life-btn" onClick={loadSample}>예시 보기</button>
          <label className="life-btn">JSON 파일 열기<input type="file" accept=".json,application/json" onChange={onFile} hidden /></label>
          <button type="button" className="life-btn" onClick={() => setPasting((v) => !v)} aria-pressed={pasting}>붙여 넣기</button>
          {life && source !== 'server' && <button type="button" className="life-btn" onClick={forget}>지우기</button>}
        </div>
        <ThemeToggle onChange={() => boardRef.current?.layout()} />
      </header>

      {pasting && <PasteBox onSubmit={onPaste} onClose={() => setPasting(false)} />}

      <div className="layout life-layout">
        {/* 연표 판은 늘 붙어 있다(LifeBoard 가 DOM 을 쥔다). 자료가 없으면 빈
            안내가 이 자리를 다 쓰고, 있으면 세 열 너비로 왼쪽에 선다 — 단 화면의
            45% 까지다. 1440px 에서 864px 를 다 주면 그래프 폭이 0 이 된다 (실측).
            좁으면 연표 안에서 가로로 훑는다. */}
        <section className="life-board" ref={rootRef} hidden={!!life && !railOpen}
                 style={life ? { width: `min(${boardWidth()}px, 45vw)` } : undefined}>
          <div className="life-head" />
          <div className="life-body">
            {!life && <Empty offline={offline} onSample={loadSample} />}
          </div>
        </section>
        {life && (
          <div className="stage-wrap">
            <GraphCanvas
              viewRef={viewRef}
              settings={settings}
              note={<>{name}의 관계망 · 노드 {life.nodes.length} · 관계 {life.edges.length}</>}
              empty={false}
              offline={false}
              onSelect={(node) => { setSelected(node.id); setTab('event'); }}
              onExpand={(node) => { setSelected(node.id); setTab('event'); }}
            />
            <SidePanel
              open={sideOpen}
              onToggle={() => setSideOpen((v) => !v)}
              meta={meta}
              seeds={meta.seeds}
              settings={settings}
              onSettings={(patch) => setSettings((prev) => ({ ...prev, ...patch }))}
              onPick={(id) => { setSelected(id); setTab('event'); }}
              lines={LIFE_LINES}
              whole
            />
          </div>
        )}
        {life && (
          <aside className="detail life-detail">
            <div className="life-tabs">
              <button type="button" className={tab === 'event' ? 'on' : ''} onClick={() => setTab('event')}>사건</button>
              <button type="button" className={tab === 'analysis' ? 'on' : ''} onClick={() => setTab('analysis')}>분석</button>
              <button type="button" className={tab === 'people' ? 'on' : ''} onClick={() => setTab('people')}>사람 · 문화</button>
            </div>
            {tab === 'event' && <EventDetail life={life} id={selected} onPick={setSelected} />}
            {tab === 'analysis' && <Analysis life={life} onPick={(id) => { setSelected(id); setTab('event'); }} />}
            {tab === 'people' && <Things life={life} />}
          </aside>
        )}
      </div>

      <footer className="foot">
        <span className="foot-copy">© 2026 histgraph</span>
        <a href="/privacy.html">개인정보처리방침</a>
        <a href="/terms.html">이용약관</a>
      </footer>
    </>
  );
}

function Empty({ offline, onSample }) {
  return (
    <div className="life-empty">
      <h2>내 삶을 한국사 옆에 세웁니다</h2>
      <p>왼쪽에 왕과 대통령의 재위, 가운데에 그 무렵의 큰 사건, 오른쪽에 내 사건이 같은 해에 같은 높이로 섭니다.</p>
      <ol>
        <li>자기 이야기를 글로 적습니다 — 태어난 해와 곳, 가족, 이사, 학교, 일, 만남, 잊히지 않는 책·영화·음악·게임.</li>
        <li>로컬에서 <code>uv run histgraph life 이야기.txt</code> 를 돌리면 이 화면이 그 결과를 바로 읽습니다.
          모델과 대화로 받은 JSON 이 있으면 위의 <b>붙여 넣기</b>로 넣습니다. 이 브라우저에만 남고 어디로도 보내지 않습니다.</li>
        <li>사건을 누르면 오른쪽에 원인과 결과, 그 해의 한국사, 전환점 점수가 나옵니다.</li>
      </ol>
      <button type="button" className="life-btn big" onClick={onSample}>예시로 먼저 보기</button>
      {offline && <p className="tl-hint">자료 서버에 닿지 못해 왕·대통령과 한국사 열이 비어 있습니다.</p>}
    </div>
  );
}

function PasteBox({ onSubmit, onClose }) {
  const [text, setText] = useState('');
  return (
    <div className="life-paste">
      <textarea value={text} onChange={(e) => setText(e.target.value)}
                placeholder='{"nodes": [...], "edges": [...], "timeline": [...], ...}' />
      <div className="life-paste-row">
        <span className="tl-hint">모델이 돌려준 JSON 그대로. 브라우저 밖으로 나가지 않습니다.</span>
        <button type="button" className="life-btn" onClick={onClose}>닫기</button>
        <button type="button" className="life-btn on" onClick={() => onSubmit(text)}>세우기</button>
      </div>
    </div>
  );
}

// --- 사건 상세 ------------------------------------------------------------
function EventDetail({ life, id, onPick }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  const node = id ? byId.get(id) : null;
  if (!node) {
    return <p className="life-hint">오른쪽 열의 사건을 누르면 여기에 원인·결과와 그 해의 한국사가 나옵니다.</p>;
  }
  const t = life.timeline.find((x) => x.event_id === id);
  const ins = life.edges.filter((e) => e.target === id);
  const outs = life.edges.filter((e) => e.source === id);
  const causes = ins.filter((e) => CAUSAL_EDGES.has(e.type));
  const effects = outs.filter((e) => CAUSAL_EDGES.has(e.type));
  const others = [...ins.filter((e) => !CAUSAL_EDGES.has(e.type)), ...outs.filter((e) => !CAUSAL_EDGES.has(e.type))];
  const links = life.historical_connections.filter((c) => c.personal_event === id);
  const turning = life.turning_points.find((p) => p.event === id);
  const cf = life.counterfactual_analysis.filter((c) => c.event === id);
  const when = [t?.date_text || node.start_date, t?.age != null ? `${t.age}세` : null, t?.life_stage].filter(Boolean).join(' · ');
  const nameOf = (nid) => byId.get(nid)?.name || nid;
  return (
    <div className="life-event">
      <span className="d-type">{NODE_TYPE_KO[node.type]}</span>
      <h2 className="d-title">{node.name}</h2>
      <div className="d-dates">{when}{node.location ? ` · ${node.location}` : ''}</div>
      {node.description && <p className="life-desc">{node.description}</p>}
      <dl className="life-facts">
        {node.importance_score != null && <><dt>중요도</dt><dd><Meter v={node.importance_score} /></dd></>}
        {turning && <><dt>전환점</dt><dd><Meter v={turning.turning_point_score} /> {turning.reason}</dd></>}
        {node.emotional_impact && <><dt>감정</dt><dd>{node.emotional_impact}</dd></>}
        {node.participants?.length > 0 && <><dt>함께</dt><dd>{node.participants.join(', ')}</dd></>}
        {node.confidence < 1 && <><dt>확실함</dt><dd>본인이 말한 것에서 미룬 것 ({Math.round(node.confidence * 100)}%)</dd></>}
      </dl>
      {causes.length > 0 && <Rel head="원인" items={causes} side="source" nameOf={nameOf} onPick={onPick} />}
      {effects.length > 0 && <Rel head="결과" items={effects} side="target" nameOf={nameOf} onPick={onPick} />}
      {links.length > 0 && (
        <section className="life-sec">
          <h3>그 무렵의 한국사</h3>
          <ul>
            {links.map((c, i) => (
              <li key={i}>
                <b>{c.node_id ? <a href={`/#${encodeURIComponent(c.node_id)}`}>{c.node_label || c.historical_event}</a> : c.historical_event}</b>
                <span className="tl-rel"> {IMPACT_KO[c.impact_type]}{c.year != null ? ` · ${c.year}` : ''}</span>
                <p>{c.description}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {others.length > 0 && (
        <section className="life-sec">
          <h3>관련</h3>
          <ul>{others.map((e, i) => (
            <li key={i}><span className="tl-rel">{EDGE_TYPE_KO[e.type]}</span> {e.source === id ? nameOf(e.target) : nameOf(e.source)}{e.description ? <p>{e.description}</p> : null}</li>
          ))}</ul>
        </section>
      )}
      {cf.length > 0 && (
        <section className="life-sec">
          <h3>만약 없었다면</h3>
          {cf.map((c, i) => (
            <div key={i}><p className="life-q">{c.question}</p><ul>{(c.possibilities || []).map((p, j) => <li key={j}>{p}</li>)}</ul></div>
          ))}
          <p className="tl-hint">가능성일 뿐 단정이 아닙니다.</p>
        </section>
      )}
    </div>
  );
}

// 원인·결과 묶음. 묶음 머리가 이미 방향을 말하므로 관계 이름('원인'·'이어짐')은
// 다시 달지 않는다 — '결과' 아래 '서울 이사 원인'이라 적히면 거꾸로 읽힌다.
function Rel({ head, items, side, nameOf, onPick }) {
  return (
    <section className="life-sec">
      <h3>{head} · {items.length}</h3>
      <ul>{items.map((e, i) => (
        <li key={i}>
          <button type="button" className="life-link" onClick={() => onPick(e[side])}>{nameOf(e[side])}</button>
          {e.confidence < 1 && <span className="tl-rel"> 미룬 것</span>}
          {e.description && <p>{e.description}</p>}
        </li>
      ))}</ul>
    </section>
  );
}

function Meter({ v }) {
  return <span className="life-meter" title={`${v} / 10`}><i><span style={{ width: `${v * 10}%` }} /></i><b>{v}</b></span>;
}

// --- 분석 -----------------------------------------------------------------
function Analysis({ life, onPick }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  const nameOf = (nid) => byId.get(nid)?.name || nid;
  const fam = life.family_analysis || {};
  const isEvent = (nid) => byId.has(nid);
  return (
    <div className="life-analysis">
      <section className="life-sec">
        <h3>어떤 흐름에서 태어났나</h3>
        {fam.origin && <p>{fam.origin}</p>}
        {fam.historical_flow && <p>{fam.historical_flow}</p>}
        {fam.members?.length > 0 && <ul>{fam.members.map((m, i) => <li key={i}><b>{m.relation}</b> {nameOf(m.node_id)} — {m.description}</li>)}</ul>}
        {fam.values && <p className="life-q">{fam.values}</p>}
      </section>
      {life.turning_points.length > 0 && (
        <section className="life-sec">
          <h3>전환점</h3>
          <ul>{[...life.turning_points].sort((a, b) => b.turning_point_score - a.turning_point_score).map((p, i) => (
            <li key={i}>
              {isEvent(p.event) ? <button type="button" className="life-link" onClick={() => onPick(p.event)}>{nameOf(p.event)}</button> : <b>{p.event}</b>}
              {' '}<Meter v={p.turning_point_score} /><p>{p.reason}</p>
            </li>
          ))}</ul>
        </section>
      )}
      {life.impact_analysis.length > 0 && (
        <section className="life-sec">
          <h3>역사가 준 영향</h3>
          <ul>{[...life.impact_analysis].sort((a, b) => b.strength - a.strength).map((p, i) => (
            <li key={i}><b>{p.event}</b> <span className="tl-rel">{IMPACT_KO[p.impact_type]}</span> <Meter v={p.strength} /><p>{p.description}</p></li>
          ))}</ul>
        </section>
      )}
      {life.life_patterns.length > 0 && (
        <section className="life-sec">
          <h3>되풀이되는 것</h3>
          <ul>{life.life_patterns.map((p, i) => (
            <li key={i}>{p.kind && <span className="tl-rel">{p.kind} </span>}<b>{p.pattern}</b>
              {p.evidence?.length > 0 && <ul className="life-sub">{p.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul>}</li>
          ))}</ul>
        </section>
      )}
      {life.influence_ranking?.items?.length > 0 && (
        <section className="life-sec">
          <h3>가장 크게 영향을 준 것</h3>
          <ul>{[...life.influence_ranking.items].sort((a, b) => b.influence_score - a.influence_score).map((p, i) => (
            <li key={i}><span className="tl-rel">{p.category} </span>
              {isEvent(p.node) ? <button type="button" className="life-link" onClick={() => onPick(p.node)}>{nameOf(p.node)}</button> : <b>{p.node}</b>}
              {' '}<Meter v={p.influence_score} /><p>{p.reason}</p></li>
          ))}</ul>
        </section>
      )}
      {life.counterfactual_analysis.length > 0 && (
        <section className="life-sec">
          <h3>만약 없었다면</h3>
          {life.counterfactual_analysis.map((c, i) => (
            <div key={i}><p className="life-q">{c.question}</p><ul>{(c.possibilities || []).map((p, j) => <li key={j}>{p}</li>)}</ul></div>
          ))}
          <p className="tl-hint">가능성일 뿐 단정이 아닙니다.</p>
        </section>
      )}
      {life.follow_up_questions.length > 0 && (
        <section className="life-sec">
          <h3>더 말해 주면 좋은 것</h3>
          <ul>{life.follow_up_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </section>
      )}
    </div>
  );
}

// --- 사람 · 장소 · 문화 ----------------------------------------------------
// 연표에 점으로 못 서는 것들 — 사람·장소·조직·책·영화·음악·게임·기술.
function Things({ life }) {
  const groups = new Map();
  for (const n of life.nodes) {
    if (n.type === 'Person' && n.id === life.subject?.id) continue;
    if (['PersonalEvent', 'TurningPoint', 'Crisis', 'Achievement', 'Failure', 'Decision', 'Memory', 'HistoricalEvent'].includes(n.type)) continue;
    const key = NODE_TYPE_KO[n.type];
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(n);
  }
  return (
    <div className="life-analysis">
      {[...groups].map(([head, items]) => (
        <section className="life-sec" key={head}>
          <h3>{head} · {items.length}</h3>
          <ul>{items.map((n) => (
            <li key={n.id}><b>{n.name}</b>
              {n.author && <span className="tl-rel"> {n.author}</span>}
              {(n.year != null) && <span className="tl-rel"> {n.year}{n.end_year != null ? `~${n.end_year}` : ''}</span>}
              {n.description && <p>{n.description}</p>}
              {n.influence && <p className="life-q">{n.influence}</p>}
            </li>
          ))}</ul>
        </section>
      ))}
    </div>
  );
}
