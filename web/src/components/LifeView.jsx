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
// `histgraph life` 가 만든다), (2) **이 화면에 이야기를 적어 로컬 모델에게
// 물은 것**(POST /api/life/analyze — 몇 분 걸리므로 띄워 두고 /api/life/job
// 으로 물어본다), (3) 예시. 역사 쪽 자료(재위 띠·큰 사건)는 언제나
// 서버(/api/context)다.
//
// **머리에는 '내 역사 입력하기' 하나만 둔다** (2026-09-08 사용자: "'JSON 파일
// 열기', '붙여넣기', '연표접기' 버튼 모두 삭제해줘"). 붙여 넣기·파일 열기는
// 사람이 모델과 따로 대화해 받은 JSON 을 넣던 길이고, 이제 화면이 직접
// 물어본다. 연표는 늘 펴 둔다.

const STORE_KEY = 'life-json';  // 옛 화면이 브라우저에 남긴 자료 (지금도 읽는다)
const STORY_KEY = 'life-story'; // 적다 만 이야기 (분석은 몇 분이라 새로고침해도 글은 남긴다)

// 입력 상자의 보기글. 무엇을 적어야 하는지는 설명보다 예가 빠르다 —
// **해와 곳, 가족, 이사, 학교, 일, 만남, 그때의 마음.** 지어낸 사람이다.
const STORY_EXAMPLE = `나는 1982년 서울에서 태어나 2살 무렵부터 강동구 성내동에서 10년 정도 살았다. 아버지는 작은 인쇄소를 하셨고 어머니는 시장에서 옷 가게를 했다.
1989년에 성내국민학교에 들어갔고, 1995년 아버지 일 때문에 분당으로 이사하면서 전학을 갔다. 친구를 다 잃은 기분이었던 게 아직도 기억난다.
1997년 겨울 외환위기로 인쇄소가 문을 닫았다. 그때부터 어머니가 식당 일을 나갔고, 나는 처음으로 돈이 무엇인지 알았다.
2001년에 대학에 들어가 컴퓨터를 전공했다. 2003년에 읽은 책 한 권이 진로를 바꿨고, 2008년 첫 직장에 들어갔다. 2014년에 지금의 아내를 만났다.`;

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

// 이야기를 로컬 서버에 보낸다. 서버가 없는 자리(배포·정적 파일)에서는
// fetch 자체가 실패하므로 상태 0 으로 돌려주고 화면이 그렇게 말한다.
async function postJson(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let payload = null;
    try { payload = await res.json(); } catch { /* 본문이 없을 수 있다 */ }
    return { ok: res.ok, status: res.status, payload };
  } catch {
    return { ok: false, status: 0, payload: null };
  }
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
  // 자료가 어디서 왔는지는 **화면에 적지 않는다** (2026-09-08 사용자: "'로컬
  // 서버에 저장된 자료' 문구도 삭제해"). 서버가 쥔 자료는 화면이 지울 수 없으니
  // '지우기' 를 낼지 정하는 데만 쓴다.
  const [source, setSource] = useState('');       // 'server' | 'local' | 'sample'
  // 주소의 #사건id 가 고른 사건이다 — 새로고침해도 자리를 잃지 않고 "이거 봐" 하고 줄 수 있다.
  const [selected, setSelected] = useState(() => (typeof location !== 'undefined' && location.hash ? decodeURIComponent(location.hash.slice(1)) : null));
  const [tab, setTab] = useState('event');
  const [writing, setWriting] = useState(false);   // 이야기 상자를 폈나
  const [job, setJob] = useState(null);   // 분석 상태 (running·done·error)
  // 이야기를 읽는 모델이 이 컴퓨터에 있는가. 서버가 `/api/life/job` 에 적어
  // 준다 — 밖의 무료 모델로 읽으면 글이 이 컴퓨터를 나가므로 **그렇게 적는다.**
  const [local, setLocal] = useState(true);
  const [offline, setOffline] = useState(false);
  const rootRef = useRef(null);
  const boardRef = useRef(null);

  // --- 그래프 (역사 그래프와 같은 캔버스·설정 상자) ---------------------
  // **연표와 그래프는 동시에 보인다** (2026-09-07 사용자: "연표와 그래프를
  // 동시에 보여줘"). 역사 화면과 같은 배치 — 왼쪽 연표, 가운데 그래프, 오른쪽
  // 상세. 연표는 접지 않는다 (2026-09-08 — 세 열을 좁게 잡아 접을 이유가 없어졌다).
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

  // --- 이야기 → 개인 그래프 (로컬 서버의 모델) --------------------------
  // 모델은 몇 분을 돈다. 답을 기다리는 요청 하나에 매달면 브라우저가 먼저
  // 끊으므로, 서버는 띄우기만 하고(POST /api/life/analyze) 여기서 2초마다
  // 물어본다. 새로고침해도 돌던 것을 다시 붙잡는다 (부팅 효과).
  const pollRef = useRef(null);
  const watchJob = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const st = await getJson('/api/life/job').catch(() => null);
      if (!st) return;   // 한 번 못 물었다고 그만두지 않는다
      setJob(st);
      if (st.state === 'running') return;
      clearInterval(pollRef.current);
      pollRef.current = null;
      if (st.state === 'done' && st.payload) await adopt(st.payload, 'server');
    }, 2000);
  }, [adopt]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const onStory = useCallback(async (text, name) => {
    const r = await postJson('/api/life/analyze', { text, name });
    if (r.ok || r.status === 409) {   // 409 는 이미 돌고 있다는 뜻이라 같이 지켜본다
      setJob({ state: 'running', step: '모델에게 묻는 중', elapsed: 0 });
      watchJob();
      return;
    }
    // 화면 글자에 영어를 두지 않는다 (CLAUDE.md §1) — 명령 이름도 적지 않는다.
    setJob({ state: 'error', error: r.payload?.error
      || '로컬 서버에 닿지 못했습니다. 이 컴퓨터에서 띄운 화면에서만 분석할 수 있습니다.' });
  }, [watchJob]);

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
    // 창을 닫았다 다시 열어도 돌던 분석은 서버에서 계속 돈다.
    (async () => {
      const st = await getJson('/api/life/job').catch(() => null);
      if (!alive || !st) return;
      setLocal(st.backend !== 'openrouter' && st.backend !== 'anthropic');
      if (st.state !== 'running') return;
      setJob(st); setWriting(true); watchJob();
    })();
    return () => { alive = false; };
  }, [adopt, watchJob]);

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
  // 캔버스는 자료가 있을 때 붙어 있다(GraphCanvas 가 그때 마운트). 자료가
  // 바뀔 때(효과)와 **캔버스가 새로 만들어질 때**(onReady) 둘 다 싣는다 —
  // 개발 모드의 StrictMode 가 캔버스를 한 번 떼었다 다시 붙이므로, 효과
  // 한 번으로는 떼어진 첫 캔버스에만 실리고 화면의 캔버스는 빈 채였다.
  const lifeRef = useRef(null);
  lifeRef.current = life;
  const selectedRef = useRef(null);
  selectedRef.current = selected;
  const loadGraph = useCallback((gv) => {
    const cur = lifeRef.current;
    if (!gv || !cur) return;
    gv.setData(graphPayload(cur, selectedRef.current));
    if (selectedRef.current) { gv.select(selectedRef.current); gv.focusOn(selectedRef.current); }
  }, []);
  useEffect(() => { loadGraph(viewRef.current); }, [life, loadGraph]);
  // 연표에서 고르든 그래프에서 고르든 같은 노드다 — 그래프의 조명도 따라간다.
  useEffect(() => {
    const gv = viewRef.current;
    if (!gv || !selected || !gv.byId.has(selected)) return;
    gv.select(selected);
    gv.focusOn(selected);
  }, [selected]);

  const forget = () => {
    try { localStorage.removeItem(STORE_KEY); } catch { /* 없다 */ }
    setLife(null); setContext(null); setSource(''); setSelected(null);
  };

  const name = life?.subject?.name || '나';

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
          {/* 상자를 닫아도 분석은 계속 돈다 — 단추가 그것을 말한다. */}
          <button type="button" className="life-btn" onClick={() => setWriting((v) => !v)} aria-pressed={writing}>
            {job?.state === 'running' ? `내 역사 읽는 중 · ${job.elapsed ?? 0}초` : '내 역사 입력하기'}
          </button>
          {life && source !== 'server' && <button type="button" className="life-btn" onClick={forget}>지우기</button>}
        </div>
        <ThemeToggle onChange={() => boardRef.current?.layout()} />
      </header>

      {writing && <StoryBox job={job} local={local} onSubmit={onStory} onClose={() => setWriting(false)} />}

      <div className="layout life-layout">
        {/* 연표 판은 늘 붙어 있다(LifeBoard 가 DOM 을 쥔다). 자료가 없으면 빈
            안내가 이 자리를 다 쓰고, 있으면 세 열 너비로 왼쪽에 선다 — 단 화면의
            45% 까지다. 1440px 에서 864px 를 다 주면 그래프 폭이 0 이 된다 (실측).
            좁으면 연표 안에서 가로로 훑는다. */}
        <section className="life-board" ref={rootRef}
                 style={life ? { width: `min(${boardWidth()}px, 45vw)` } : undefined}>
          <div className="life-head" />
          <div className="life-body">
            {!life && <Empty offline={offline} local={local} onSample={loadSample} onWrite={() => setWriting(true)} />}
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
              onReady={loadGraph}
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

function Empty({ offline, local, onSample, onWrite }) {
  return (
    <div className="life-empty">
      <h2>내 삶을 한국사 옆에 세웁니다</h2>
      <p>왼쪽에 왕과 대통령의 재위, 가운데에 그 무렵의 큰 사건, 오른쪽에 내 사건이 같은 해에 같은 높이로 섭니다.</p>
      <ol>
        <li><b>내 역사 입력하기</b>를 눌러 자기 이야기를 적습니다 — 태어난 해와 곳, 가족, 이사, 학교, 일, 만남,
          잊히지 않는 책·영화·음악·게임.</li>
        <li>{local
          ? '이 컴퓨터의 모델이 그 글을 읽어 사건과 인과로 옮깁니다. 몇 분 걸립니다. 글도 결과도 이 컴퓨터 밖으로 나가지 않습니다.'
          : '모델이 그 글을 읽어 사건과 인과로 옮깁니다. 1~2분 걸립니다. 읽는 모델이 인터넷 너머에 있어 글이 그리로 갑니다 — 결과는 이 컴퓨터에 남습니다.'}</li>
        <li>사건을 누르면 오른쪽에 원인과 결과, 그 해의 한국사, 전환점 점수가 나옵니다.</li>
      </ol>
      <div className="life-empty-row">
        <button type="button" className="life-btn big on" onClick={onWrite}>내 역사 입력하기</button>
        <button type="button" className="life-btn big" onClick={onSample}>예시로 먼저 보기</button>
      </div>
      {offline && <p className="tl-hint">자료 서버에 닿지 못해 왕·대통령과 한국사 열이 비어 있습니다.</p>}
    </div>
  );
}

// 이야기를 적는 상자. 보기글(placeholder)이 무엇을 적을지 대신 말한다 —
// 빈 칸에 '자유롭게 적으세요' 라고 쓰면 아무도 첫 줄을 못 적는다.
// 적다 만 글은 브라우저에 남긴다. 분석이 몇 분이라 그동안 창을 닫는다.
function StoryBox({ job, local, onSubmit, onClose }) {
  const [text, setText] = useState(() => {
    try { return localStorage.getItem(STORY_KEY) || ''; } catch { return ''; }
  });
  const running = job?.state === 'running';
  const change = (v) => {
    setText(v);
    try { localStorage.setItem(STORY_KEY, v); } catch { /* 저장 못 해도 적을 수 있다 */ }
  };
  return (
    <div className="life-paste life-story">
      <textarea value={text} onChange={(e) => change(e.target.value)} disabled={running}
                placeholder={STORY_EXAMPLE} spellCheck={false} />
      <div className="life-paste-row">
        {running ? (
          <span className="tl-hint">{job.step || '읽는 중'} · {job.elapsed ?? 0}초 — 몇 분 걸립니다. 창을 닫아도 계속 돕니다.</span>
        ) : job?.state === 'error' ? (
          <span className="tl-hint life-warn">{job.error}</span>
        ) : (
          <span className="tl-hint">{local
            ? '이 컴퓨터의 모델이 읽습니다. 글은 어디로도 보내지 않습니다.'
            : '인터넷 너머의 모델이 읽습니다. 적은 글이 그 모델로 갑니다.'}</span>
        )}
        <button type="button" className="life-btn" onClick={onClose}>닫기</button>
        <button type="button" className="life-btn on" disabled={running || text.trim().length < 40}
                onClick={() => onSubmit(text, '나')}>{running ? '읽는 중' : '세우기'}</button>
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
