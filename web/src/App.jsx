import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './lib/api.js';
import { GraphCanvas } from './components/GraphCanvas.jsx';
import { TimelinePanel } from './components/TimelinePanel.jsx';
import { SidePanel } from './components/SidePanel.jsx';
import { DetailPanel } from './components/DetailPanel.jsx';
import { Search } from './components/Search.jsx';

// 시대 이름은 **서버가 준다** (`meta.era_label`). 여기 표를 두면 시대를
// 더할 때마다 두 곳을 고쳐야 하고, 빠뜨린 하나가 화면에 영어로 뜬다.

function hashId() {
  return location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [seeds, setSeeds] = useState([]);
  const [settings, setSettings] = useState({
    depth: 2, limit: 120, includePeriod: false, showLabels: true, showRail: true,
  });
  const [detail, setDetail] = useState(null);       // 상세 패널에 그릴 노드 (서버 응답)
  const [timeline, setTimeline] = useState(null);   // 연표 자료
  const [note, setNote] = useState(null);
  const [sideOpen, setSideOpen] = useState(false);
  const [ready, setReady] = useState(false);        // 그래프를 한 번이라도 그렸나

  // **상세 패널에서** 관계를 타고 들어간 자취. '←' 로 한 칸씩 되짚어
  // 올라간다. 그래프나 연표에서 고른 노드는 여기 쌓이지 않는다 — 그건
  // 이어서 파고든 걸음이 아니라 새로 시작한 걸음이다.
  const [trail, setTrail] = useState([]);

  const viewRef = useRef(null);
  const railRef = useRef(null);
  // 콜백 안에서 늘 최신 값을 보게 하는 거울. 이걸 안 두면 GraphView 에
  // 넘긴 콜백이 부팅 당시의 설정을 영영 들고 있는다.
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const currentRef = useRef(null);      // 지금 그래프의 중심
  const detailRef = useRef(null);       // 지금 상세의 { id, label }
  const timelineIdRef = useRef(null);

  // --- 연표 ------------------------------------------------------------
  // 연표의 주인공은 **지금 보고 있는 노드**다. 검색으로 옮겨가든 캔버스에서
  // 누르든 상세를 타고 들어가든, 화면 한가운데가 바뀌면 연표도 따라간다.
  const showTimeline = useCallback(async (id) => {
    if (!settingsRef.current.showRail || timelineIdRef.current === id) return;
    timelineIdRef.current = id;
    const t = await api.timeline(id);
    // 그 사이에 다른 노드로 옮겼으면 늦게 온 답은 버린다
    if (timelineIdRef.current !== id) return;
    setTimeline(t.error ? null : t);
  }, []);

  // --- 그래프 적재 -----------------------------------------------------
  const load = useCallback(async (id, { merge = false } = {}) => {
    const view = viewRef.current;
    if (!view) return;
    const data = await api.graph(id, settingsRef.current);
    if (data.missing || !data.nodes.length) {
      setNote(<>‘{id}’ 주변에 그릴 관계가 없습니다.</>);
      return;
    }
    currentRef.current = id;
    showTimeline(id);
    if (!merge) location.hash = encodeURIComponent(id);
    setReady(true);
    view.setData(data, { merge });
    view.select(id);
    view.focusOn(id);

    const label = data.nodes.find((n) => n.id === id)?.label || id;
    setNote(
      <>
        {label} 주변 · 노드 {data.nodes.length} · 관계 {data.edges.length}
        {data.truncated && <> · <b>차수 상위만 표시</b></>}
      </>,
    );
  }, [showTimeline]);

  // --- 상세 패널 -------------------------------------------------------
  //
  // `nest` 를 준 걸음만 자취에 쌓인다.
  //
  // **그래프나 연표에서 고른 노드는 그 자체가 뿌리다.** 캔버스에서 아무
  // 노드나 누를 때마다 직전 노드가 상위로 붙으면, 서로 아무 관계도 없는
  // 두 노드가 부모-자식처럼 보인다 — 조선 화면에서 세종을 보다 저쪽 끝
  // 황진이를 누르면 '← 세종' 이 머리에 붙는 식이다. 그건 계보가 아니라
  // 그저 내가 방금 눌렀던 것일 뿐이다.
  //
  // 자취가 뜻을 갖는 곳은 오른쪽 패널뿐이다. 거기서 고른 사건·장소·날짜는
  // **지금 보는 노드가 데리고 있는 것**이라, 그 노드 밑으로 들어가는 게 맞다.
  const showDetail = useCallback(async (id, { back = false, nest = false } = {}) => {
    // ('←' 로 온 걸음은 쌓지도 지우지도 않는다 — 그러면 두 노드 사이를
    // 영영 못 벗어나거나, 한 칸 올라간 순간 나머지 자취를 잃는다)
    if (!back) {
      const cur = detailRef.current;
      if (!nest) setTrail([]);
      else if (cur && cur.id !== id) setTrail((t) => [...t, cur].slice(-50));
    }
    const d = await api.node(id);
    if (d.error) return;
    detailRef.current = { id, label: d.label };
    setDetail(d);
    showTimeline(id);   // 상세로 옮겨가면 연표의 주인공도 함께 옮긴다
  }, [showTimeline]);

  const closeDetail = useCallback(() => {
    setDetail(null);
    setTrail([]);
    detailRef.current = null;
    // 연표는 남긴다 — 상세를 닫아도 화면 한가운데 그 노드는 그대로 있고,
    // '언제 사람인가'는 관계 목록과 달리 계속 붙어 있어야 할 정보다.
  }, []);

  // 화면에 있는 노드면 그리로 옮기고, 없으면 그 주변을 새로 편다.
  const visit = useCallback((id, opts = {}) => {
    const view = viewRef.current;
    if (view?.byId.has(id)) { view.select(id); view.focusOn(id); }
    else load(id, { merge: true });
    showDetail(id, opts);
  }, [load, showDetail]);

  // 되짚어 올라가기 — 그래프에도 그 노드가 다시 보여야 '돌아왔다'가 된다.
  const backDetail = useCallback(() => {
    const prev = trail[trail.length - 1];
    if (!prev) return;
    setTrail((t) => t.slice(0, -1));
    visit(prev.id, { back: true });
  }, [trail, visit]);

  // --- 부팅 ------------------------------------------------------------
  useEffect(() => {
    let alive = true;
    (async () => {
      const m = await api.meta();
      if (!alive) return;
      setMeta(m);
      document.title = `histgraph — ${m.era_label || '전체'}`;
      const s = await api.seeds(12);
      if (!alive) return;
      setSeeds(s);
      // 주소가 비어 있으면 왕조에서 시작한다. 조선 그래프의 중심은 조선이다 —
      // 차수 1위 노드로 열면 그때그때 병자호란이 중심인 화면이 된다.
      const start = hashId() || m.root || s[0]?.id;
      if (start) load(start);
    })();
    return () => { alive = false; };
  }, [load]);

  // 주소에 지금 보는 노드를 남긴다 — 새로고침해도 자리를 잃지 않고,
  // 남에게 "이거 봐" 하고 링크를 줄 수 있다.
  useEffect(() => {
    const onHash = () => {
      const id = hashId();
      if (id && id !== currentRef.current) load(id);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [load]);

  // --- 단축키 ----------------------------------------------------------
  useEffect(() => {
    const onKey = (ev) => {
      // Esc 는 패널을 닫는다 — 깊이 들어갔다고 한 칸씩만 나가야 하면 답답하다
      if (ev.key === 'Escape') closeDetail();
      // 브라우저의 뒤로가기 몸짓은 상세 안에서 상위로 올라가는 뜻으로 받는다
      if (ev.key === 'ArrowLeft' && (ev.altKey || ev.metaKey) && trail.length) {
        ev.preventDefault();
        backDetail();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [closeDetail, backDetail, trail.length]);

  // --- 표시 설정 -------------------------------------------------------
  const changeSettings = useCallback((patch) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      settingsRef.current = next;
      // 그래프를 다시 받아야 하는 것들
      if (('depth' in patch || 'limit' in patch || 'includePeriod' in patch) && currentRef.current) {
        load(currentRef.current);
      }
      // 연표는 화면 폭을 250px 먹는다. 껐다 켜면 지금 노드로 다시 세운다.
      if ('showRail' in patch) {
        timelineIdRef.current = null;
        if (!patch.showRail) setTimeline(null);
        else if (currentRef.current) showTimeline(currentRef.current);
      }
      return next;
    });
  }, [load, showTimeline]);

  const era = meta?.era_label || '전체';
  const prev = trail[trail.length - 1] || null;

  return (
    <>
      <header className="top">
        <div className="brand">
          <button
            className="menu-toggle"
            aria-label={sideOpen ? '패널 닫기' : '패널 열기'}
            aria-expanded={sideOpen}
            title="시작점·범례·표시 설정"
            onClick={() => setSideOpen((v) => !v)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <span className="mark" />
          <h1>histgraph</h1>
          {/* 어디까지 파고 들어가도 한 번에 중심으로 돌아올 수 있어야 한다.
              주소에 남은 노드 때문에 새로고침해도 왕조로 안 돌아오기 때문이다. */}
          <button className="era" title="이 그래프의 중심으로"
                  onClick={() => meta?.root && load(meta.root)}>
            {era}
          </button>
        </div>

        {/* 검색으로 찾은 노드는 그래프만이 아니라 오른쪽 상세도 바로 연다 */}
        <Search nodeTypes={meta?.node_types} onPick={(id) => { load(id); showDetail(id); }} />

        <div className="counts">
          {meta && `노드 ${meta.nodes_total.toLocaleString()} · 엣지 ${meta.edges_total.toLocaleString()}`}
        </div>
      </header>

      <div className={`layout${sideOpen ? ' side-open' : ''}`}>
        <SidePanel
          meta={meta}
          seeds={seeds}
          settings={settings}
          onSettings={changeSettings}
          onPick={(id) => load(id)}
        />

        <TimelinePanel railRef={railRef} data={timeline} onPick={visit} />

        <GraphCanvas
          viewRef={viewRef}
          showLabels={settings.showLabels}
          note={note}
          empty={!ready}
          // **클릭하면 그 사람의 세계가 열려야 한다.** 고르기만 하면 화면에는
          // 그 노드가 우연히 들고 온 엣지 한두 개만 남는다 — 조선 화면에서
          // 정종을 누르면 '한씨'와의 선 하나뿐이고, 아버지 태조도 형제인 태종도
          // 안 보인다. 실제로는 관계가 25건 있는데 화면이 못 보여준 것이다.
          onSelect={(node) => { showDetail(node.id); load(node.id, { merge: true }); }}
          // 더블클릭은 자리를 지킨 채 이웃만 얹는다 (지금 보던 배치를 잃지 않는다)
          onExpand={(node) => load(node.id, { merge: true })}
        />

        <DetailPanel
          node={detail}
          prev={prev}
          onClose={closeDetail}
          onBack={backDetail}
          onVisit={visit}
        />
      </div>
    </>
  );
}
