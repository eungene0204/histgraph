import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './lib/api.js';
import { GraphCanvas } from './components/GraphCanvas.jsx';
import { TimelinePanel } from './components/TimelinePanel.jsx';
import { SidePanel } from './components/SidePanel.jsx';
import { DetailPanel } from './components/DetailPanel.jsx';
import { Search } from './components/Search.jsx';
import { ThemeToggle } from './components/ThemeToggle.jsx';
import { AccountMenu } from './components/AccountMenu.jsx';
import { LoginModal } from './components/LoginModal.jsx';
import { auth } from './lib/auth.js';
import { readLife, ownerOf } from './lib/lifestore.js';
import { COPYRIGHT } from './lib/site.js';

// 시대 이름은 **서버가 준다** (`meta.era_label`). 여기 표를 두면 시대를
// 더할 때마다 두 곳을 고쳐야 하고, 빠뜨린 하나가 화면에 영어로 뜬다.

// 인과 도면 스위치. 2026-09-06 사용자: "인과관계 그래프를 지우진 말고 기능
// 꺼두자." 켜면 노드를 눌렀을 때 캔버스가 그 노드의 인과 도면이 된다
// (design.md §4 '인과 도면'). 꺼져 있으면 전처럼 그 노드의 주변 관계를 편다.
export const CAUSAL_DIAGRAM = false;

// 개인 역사 장이 이 빌드에 있는가 — vite.config.js. 서버 렌더 테스트(esbuild)
// 에는 import.meta.env 가 없으므로 없는 것으로 친다.
const LIFE_PAGE = Boolean(import.meta.env?.VITE_LIFE);
// 브라우저에 남은 내 역사는 **주인 표를 지나서만** 읽는다 (lib/lifestore.js).
// 여기서 재는 것은 '내 역사' 단추를 빛낼지 하나뿐이지만, 읽는 길이 둘이면
// 규칙도 둘이 된다 — 한 길로 모은다.

function hashId() {
  return location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [seeds, setSeeds] = useState([]);
  // Obsidian 그래프 설정과 같은 네 절 — 필터·묶음(범례)·표시·힘 (design.md §5).
  const [settings, setSettings] = useState({
    depth: 2, limit: 120, includePeriod: false, hiddenEdges: [],     // 필터
    showLabels: true, showRail: true, arrows: true,                  // 표시
    textFade: 0.3, nodeScale: 1, lineScale: 1,
    centerForce: 1, repelForce: 1, linkDistance: 1,                  // 힘
  });
  const [detail, setDetail] = useState(null);       // 상세 패널에 그릴 노드 (서버 응답)
  const [timeline, setTimeline] = useState(null);   // 연표 자료
  const [note, setNote] = useState(null);
  const [sideOpen, setSideOpen] = useState(false);
  const [ready, setReady] = useState(false);        // 그래프를 한 번이라도 그렸나
  // 자료 서버에 못 닿은 상태. 화면에는 '아직 아무것도 안 골랐다'와
  // 똑같이 비어 보이므로, 둘을 갈라 적으려고 따로 든다.
  const [offline, setOffline] = useState(false);

  // **상세 패널에서** 관계를 타고 들어간 자취. '←' 로 한 칸씩 되짚어
  // 올라간다. 그래프나 연표에서 고른 노드는 여기 쌓이지 않는다 — 그건
  // 이어서 파고든 걸음이 아니라 새로 시작한 걸음이다.
  const [trail, setTrail] = useState([]);

  // 내 역사로 들어가려면 로그인이 필요하다 — 누가 보고 있는지만 알면 된다.
  // (`null` = 아직 안 물어봤다. 그동안 눌러도 상자가 뜨는 쪽이 안전하다.)
  const [mine, setMine] = useState(null);
  const [askLogin, setAskLogin] = useState(false);
  // 내 역사가 비었는가. `null` = 아직 안 읽었다 — 그동안은 아무 표시도 안 한다.
  const [lifeEmpty, setLifeEmpty] = useState(null);

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
  // 도면에서 돌아올 때 되살릴 주변 관계 안내 칩
  const worldNoteRef = useRef(null);

  const showTimeline = useCallback(async (id) => {
    if (!settingsRef.current.showRail || timelineIdRef.current === id) return;
    timelineIdRef.current = id;
    const t = await api.timeline(id).catch(() => null);
    if (!t) return;
    // 그 사이에 다른 노드로 옮겼으면 늦게 온 답은 버린다
    if (timelineIdRef.current !== id) return;
    setTimeline(t.error ? null : t);
  }, []);

  // --- 그래프 적재 -----------------------------------------------------
  //
  const load = useCallback(async (id, { merge = false } = {}) => {
    const view = viewRef.current;
    if (!view) return;
    const data = await api.graph(id, settingsRef.current).catch(() => null);
    // 서버가 죽어 있으면 fetch 가 통째로 터진다. 잡지 않으면 약속이 조용히
    // 깨져 화면은 첫 빈 화면 그대로 서 있는다 — 그게 '그래프가 안 보인다'다.
    if (!data) { setOffline(true); setNote(null); return; }
    setOffline(false);
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
    const text = (
      <>
        {label} 주변 · 노드 {data.nodes.length} · 관계 {data.edges.length}
        {/* 잘릴 때 남는 것은 무게가 큰 이웃이다 (store._share_budget ·
            central.py). 설정 상자의 '시작점' 안내와 같은 말을 쓴다. */}
        {data.truncated && <> · <b>중심에 가까운 것만 표시</b></>}
      </>
    );
    worldNoteRef.current = text;
    setNote(text);
  }, [showTimeline]);

  // --- 인과 도면 -------------------------------------------------------
  //
  // **노드를 누르면 캔버스가 그 노드의 인과 도면이 된다** (2026-09-06 사용자:
  // "노드를 클릭하면 인과관계를 보여주는 그래프를", 그리고 이웃 위에 얹어
  // 보였더니 "너무 복잡하게 그려지고 있어서 아무런 정보값이 없어"). 원인은
  // 왼쪽 열, 결과는 오른쪽 열 (design.md §4 '인과 도면'). 인과가 없는
  // 노드(대부분의 인물)는 전처럼 그 노드의 주변 관계를 편다. 빈 곳을
  // 누르면 접어 둔 주변 관계 그래프로 돌아온다.
  const openCausal = useCallback(async (id) => {
    const view = viewRef.current;
    if (!view) return;
    if (!CAUSAL_DIAGRAM) { load(id, { merge: true }); return; }
    // 두 걸음만 편다 — 네 걸음(사슬 패널)을 도면에 다 세우면 심하전투의
    // 원인 31개가 한 화면에 겹친다. 더 앞은 도면 안의 노드를 눌러 이어 간다.
    const chain = await api.chain(id, 2).catch(() => null);
    if (chain && !chain.error && view.showCausal(chain)) {
      const v = view.causalView;
      const label = chain.nodes?.[id]?.label || id;
      setNote(<>{label}의 인과 · 원인 {v.causes} · 결과 {v.effects} · 노드를 누르면 그 노드의 인과로, 빈 곳을 누르면 주변 관계로</>);
      return;
    }
    load(id, { merge: true });
  }, [load]);

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
    viewRef.current?.exitCausal();   // Esc 는 도면도 접는다
    // 연표는 남긴다 — 상세를 닫아도 화면 한가운데 그 노드는 그대로 있고,
    // '언제 사람인가'는 관계 목록과 달리 계속 붙어 있어야 할 정보다.
  }, []);

  // 상세·연표에서 고른 노드 — 도면이 켜져 있으면 캔버스에서 누른 것과 같이
  // 인과 도면을 열고(안 서면 주변 관계), 꺼져 있으면 화면에 있는 노드면
  // 그리로 옮기고 없으면 그 주변을 새로 편다.
  const visit = useCallback((id, opts = {}) => {
    const view = viewRef.current;
    if (CAUSAL_DIAGRAM) openCausal(id);
    else if (view?.byId.has(id)) { view.select(id); view.focusOn(id); }
    else load(id, { merge: true });
    showDetail(id, opts);
  }, [load, openCausal, showDetail]);

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
      const m = await api.meta().catch(() => null);
      if (!alive) return;
      if (!m) { setOffline(true); return; }
      setMeta(m);
      const s = await api.seeds(12).catch(() => []);
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

  // 내 역사 장이 있는 빌드에서만 묻는다 (배포에는 그 장이 없다). 같은 걸음에
  // **적어 둔 것이 있는지**도 본다 — 없으면 아래 단추가 숨을 쉰다.
  //
  // **로그인 전에는 늘 부른다** (2026-09-09 사용자: "로그인 안 했을때도 똑같은
  // 효과를 줘"). 그 사람에게 내 역사는 아직 아무것도 아니고, 여기가 로그인을
  // 묻는 유일한 자리다 — 이 브라우저에 적어 둔 것이 남아 있어도 마찬가지다
  // (그것은 이 컴퓨터의 것이지 그 사람의 계정에 있는 것이 아니다). 대신 부르는
  // 말을 바꾼다 — 아래 title 이 '비었다' 대신 '로그인하면 적을 수 있다'로 선다.
  //
  // 로그인한 사람은 재는 자리가 둘이다 (LifeView 의 부팅과 같은 차례): 계정에
  // 올려 둔 문서가 먼저이고, 그것이 없으면 브라우저에만 남은 것이다 (부팅이
  // 그것을 찾으면 계정으로 옮긴다). 계정 쪽은 **서버가 한 줄로 답한다**
  // (`auth.me` 의 `life`) — 빛낼지 말지를 알자고 남의 역사를 통째로 내려받게
  // 하지 않는다.
  //
  // 다 읽기 전에는 `null` 이라 아무 표시도 안 한다 — '아직 모른다'를 '없다'로
  // 읽으면 적어 둔 사람의 머리 줄이 한 번 번쩍인다 (2026-09-09 사용자: 빈
  // 안내는 없다고 확인된 뒤에 세운다).
  useEffect(() => {
    if (!LIFE_PAGE) return undefined;
    let alive = true;
    (async () => {
      const me = await auth.me();
      if (!alive) return;
      setMine(me);
      if (!me.user) { setLifeEmpty(true); return; }
      if (me.life) { setLifeEmpty(false); return; }
      const kept = readLife(ownerOf(me));
      if (alive) setLifeEmpty(!kept?.nodes?.length);
    })();
    return () => { alive = false; };
  }, []);

  const era = meta?.era_label || '전체';
  const prev = trail[trail.length - 1] || null;

  return (
    <>
      <header className="top">
        <div className="brand">
          <span className="mark" />
          <h1>histgraph</h1>
          {/* 어디까지 파고 들어가도 한 번에 중심으로 돌아올 수 있어야 한다.
              주소에 남은 노드 때문에 새로고침해도 왕조로 안 돌아오기 때문이다. */}
          <button className="era" title="이 그래프의 중심으로"
                  onClick={() => meta?.root && load(meta.root)}>
            {era}
          </button>
          {/* 개인 역사 — 내 삶을 왕·대통령의 띠와 한국사 옆에 세우는 장 (life.html).

              **여기만 로그인을 묻는다** (2026-09-08 사용자: "내 역사는 개인별로
              다 다르니깐"). 그래프는 로그인 없이 다 보이고, 사람마다 다른 것
              하나만 막는다. 로그인 전이면 옮겨가지 않고 상자를 세운다 — 빈
              화면을 보여 준 뒤에 묻는 것보다 낫다. */}
          {LIFE_PAGE && (
            <a className={`era${lifeEmpty ? ' beckon' : ''}`} href="/life.html"
               title={!lifeEmpty ? '내 삶을 세상의 역사와 나란히 봅니다'
                      : mine?.user ? '아직 적은 내 역사가 없습니다 — 눌러서 시작합니다'
                                   : '로그인하면 내 역사를 적을 수 있습니다'}
               onClick={(e) => { if (!mine?.user) { e.preventDefault(); setAskLogin(true); } }}>
              내 역사
            </a>
          )}
        </div>

        {/* 검색으로 찾은 노드는 그래프만이 아니라 오른쪽 상세도 바로 연다 */}
        <Search nodeTypes={meta?.node_types} onPick={(id) => { load(id); showDetail(id); }} />
        {/* 머리 줄 오른쪽 끝. 계정이 바깥쪽(가장 끝)이고 화면 밝기가 안쪽이다 —
            누르는 빈도는 밝기가 높지만, 계정은 '지금 누구로 보고 있나'라서
            눈이 먼저 가는 자리에 둔다. 가입이 꺼져 있으면 계정은 서지 않는다. */}
        <div className="top-right">
          {/* 연표는 색을 문자열로 박아 두므로(SVG) 테마가 바뀌면 다시 그려 준다.
              캔버스는 매 프레임 그리니 스스로 따라온다. */}
          <ThemeToggle onChange={() => railRef.current?.layout({ keepView: true })} />
          <AccountMenu />
        </div>
      </header>

      {askLogin && (
        <LoginModal
          next="/life.html"
          ready={Boolean(mine?.enabled)}
          title="내 역사는 로그인이 필요합니다"
          onClose={() => setAskLogin(false)}
        />
      )}

      <div className="layout">
        <TimelinePanel railRef={railRef} data={timeline} onPick={visit} />

        {/* 그래프 설정은 캔버스 위 오른쪽 위에 뜬다 (Obsidian 의 graph-controls).
            사이드바가 아니라 캔버스의 일부라서 같은 틀에 담는다. */}
        <div className="stage-wrap">
        <GraphCanvas
          viewRef={viewRef}
          settings={settings}
          note={note}
          empty={!ready}
          offline={offline}
          // **클릭하면 그 사람의 세계가 열려야 한다.** 고르기만 하면 화면에는
          // 그 노드가 우연히 들고 온 엣지 한두 개만 남는다 — 조선 화면에서
          // 정종을 누르면 '한씨'와의 선 하나뿐이고, 아버지 태조도 형제인 태종도
          // 안 보인다. 실제로는 관계가 25건 있는데 화면이 못 보여준 것이다.
          onSelect={(node) => { showDetail(node.id); openCausal(node.id); }}
          // 더블클릭은 자리를 지킨 채 이웃만 얹는다 (지금 보던 배치를 잃지 않는다).
          // 도면에서는 도면을 접고 그 노드의 이웃을 편다.
          onExpand={(node) => { viewRef.current?.exitCausal(); load(node.id, { merge: true }); }}
          onCausalExit={() => setNote(worldNoteRef.current)}
        />
        <SidePanel
          open={sideOpen}
          onToggle={() => setSideOpen((v) => !v)}
          meta={meta}
          seeds={seeds}
          settings={settings}
          onSettings={changeSettings}
          onPick={(id) => load(id)}
        />
        </div>

        <DetailPanel
          node={detail}
          prev={prev}
          onClose={closeDetail}
          onBack={backDetail}
          onVisit={visit}
        />
      </div>

      {/* 광고를 실으려면 방침과 약관이 어느 화면에서든 한 번에 닿아야 한다.
          두 장은 리액트 바깥의 정적 문서라 자바스크립트 없이도 열린다
          (web/privacy.html · web/terms.html). 그래서 <a> 로 그냥 넘긴다. */}
      <footer className="foot">
        <span className="foot-copy">{COPYRIGHT}</span>
        <a href="/privacy.html">개인정보처리방침</a>
        <a href="/terms.html">이용약관</a>
      </footer>
    </>
  );
}
