import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ThemeToggle } from './ThemeToggle.jsx';
import { auth } from '../lib/auth.js';
import { LoginModal } from './LoginModal.jsx';
import { GraphCanvas } from './GraphCanvas.jsx';
import { SidePanel } from './SidePanel.jsx';
import { LifeBoard, normalize, removeNode, graphPayload, graphMeta, boardWidth, edgeLabel, NODE_TYPE_KO, IMPACT_KO, CAUSAL_EDGES, EVENT_TYPES } from '../lib/life.js';

// 개인 역사 화면 (/life.html). 왼쪽 왕·대통령 띠 · 가운데 한국사 · 오른쪽
// 내 역사 — 세 열이 한 자 위에 선다 (lib/life.js). 오른쪽 끝 패널이 고른
// 사건의 상세와 분석(가족 뿌리·전환점·패턴·영향·가상 역사·물음)을 읽는다.
//
// 자료는 둘 중 하나에서 온다: (1) **이 화면에 이야기를 적어 모델에게 물은
// 것**(POST /api/life/analyze — 몇 분 걸리므로 띄워 두고 /api/life/job 으로
// 물어본다), (2) 로그인한 사람이 계정에 올려 둔 것. 역사 쪽 자료(재위 띠·큰
// 사건)는 언제나 서버(/api/context)다.
//
// **기본으로 보여 주던 자료는 없다** (2026-09-08 사용자: "디폴트로 넣었던 내
// 역사 데이터는 지워. 사용자가 로그인 해서 직접 입력 할거야"). 서버가 폴더의
// 개인 파일을 골라 주던 길(/api/life)과 지어낸 예시('예시로 먼저 보기')를 뺐다.
// 빈 화면에서 시작해 자기 이야기를 적는다.
//
// **머리에는 '내 역사 입력하기' 하나만 둔다** (2026-09-08 사용자: "'JSON 파일
// 열기', '붙여넣기', '연표접기' 버튼 모두 삭제해줘"). 붙여 넣기·파일 열기는
// 사람이 모델과 따로 대화해 받은 JSON 을 넣던 길이고, 이제 화면이 직접
// 물어본다. 연표는 늘 펴 둔다.

const STORE_KEY = 'life-json';  // 옛 화면이 브라우저에 남긴 자료 (지금도 읽는다)
const STORY_KEY = 'life-story'; // 적다 만 이야기 (분석은 몇 분이라 새로고침해도 글은 남긴다)

// 입력 상자의 보기글. 무엇을 적어야 하는지는 설명보다 예가 빠르다 —
// **해와 곳, 가족, 이사, 학교, 일, 만남, 그때의 마음.** 지어낸 사람이다.
// 앞에 '예:' 를 달고 색을 더 흐리게 두어 **예문이지 내 글이 아니라는 것**이
// 보이게 한다 (2026-09-08 사용자). 지명은 실제 있는 곳이되, 학교·회사·가게
// 이름은 **이 세상에 없는 것**이다 — 실재하는 곳의 이름을 남의 삶에 붙이지 않는다.
// (처음 지은 다섯 중 셋이 검색하니 실재하는 회사·사진관이었다. 지금 것은 검색해 없는 것을 확인했다.)
const STORY_EXAMPLE = `예: 나는 1979년 전북 익산에서 태어났다. 아버지는 익산역 근처에서 '노을결사진관'이라는 작은 사진관을 하셨고, 어머니는 집에서 한복 삯바느질을 하셨다. 외할머니는 김제에서 벼농사를 지으셨는데, 방학마다 거기서 지냈다.
1986년 익산의 '샛별뫼초등학교'에 들어갔다. 1991년 아버지가 사진관을 접고 인천 부평으로 올라오면서 전학을 갔다. 말투 때문에 놀림을 받았던 것이 아직 기억난다.
1997년 겨울 외환위기 때 아버지가 다니던 '온새미전자'가 문을 닫았고, 그 뒤로 어머니가 부평시장에서 반찬 가게를 시작했다. 나는 그해 처음으로 아르바이트를 했다.
1998년 '바람결대학교' 기계공학과에 들어갔다. 2002년 월드컵 때 광장에서 만난 선배 덕에 2004년 '별무리정밀'에 첫 직장을 얻었고, 2011년 지금의 남편을 만났다. 2020년 코로나 때 회사가 재택으로 바뀌면서 부평을 떠나 강원 원주로 이사했다.`;

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
  // 서버에 저장된 자료' 문구도 삭제해"). '계정에서 지우기' 를 낼지 정하는 데만 쓴다.
  const [source, setSource] = useState('');       // 'local' | 'account'
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

  // --- 내 계정에 두기 -----------------------------------------------------
  // 로그인한 사람의 분석 결과는 **끝나는 대로 계정에 올라간다** (2026-09-08 사용자:
  // "사용자가 로그인 해서 직접 입력 할거야" — 그리고 실측: 09-07 에 계정에 올린 옛
  // 그래프가 부팅 때 먼저 읽혀, 뒤에 분석해 브라우저에만 남은 새 그래프(친구 셋)를
  // 가렸다. "새로고침 해도 친구들이 안 보이는데?"). 부팅이 계정을 먼저 읽으므로
  // 계정이 늘 최신이어야 한다. 로그인이 안 된 자리(로컬)는 전처럼 브라우저에만.
  // 단추 '내 계정에 저장' 은 남긴다 — 브라우저에만 있는 것을 올리는 길.
  const rawRef = useRef(null);          // adopt 를 지나간 날것 — 그대로 올린다
  const [account, setAccount] = useState({ enabled: false, user: null });
  const accountRef = useRef(account);
  accountRef.current = account;
  // 방금 한 일을 한국어로 적는 팝업. **잠깐 보이고 사라진다** (2026-09-08 사용자:
  // "저장후 잠깐 보여주고 사라져야 해. 팝업 띄워서 저장 했다고 알려줘") — 된 것은
  // 2.5초, 안 된 것은 읽을 시간을 더 준다. '올리는 중' 은 결과가 올 때까지.
  const [kept, setKept] = useState('');
  const keptTimer = useRef(null);
  const toast = useCallback((msg, ms = 2500) => {
    if (keptTimer.current) clearTimeout(keptTimer.current);
    setKept(msg);
    keptTimer.current = ms ? setTimeout(() => setKept(''), ms) : null;
  }, []);
  useEffect(() => () => { if (keptTimer.current) clearTimeout(keptTimer.current); }, []);

  useEffect(() => { auth.me().then(setAccount); }, []);

  const saveToAccount = useCallback(async () => {
    if (!rawRef.current) return;
    toast('올리는 중입니다…', 0);
    try {
      await auth.life.save(rawRef.current);
      toast('내 계정에 저장했습니다');
    } catch (err) {
      toast(err.message, 6000);
    }
  }, [toast]);

  const dropFromAccount = useCallback(async () => {
    toast('지우는 중입니다…', 0);
    try {
      await auth.life.remove();
      toast('내 계정에서 지웠습니다');
    } catch (err) {
      toast(err.message, 6000);
    }
  }, [toast]);

  // 자료를 받아들이는 한 길. 날것이든 서버를 거친 것이든 normalize 를 지난다.
  const adopt = useCallback(async (raw, from) => {
    let norm;
    try { norm = normalize(raw); } catch { return false; }
    if (!norm.nodes.length) return false;
    setLife(norm);
    setSource(from);
    setSelected((cur) => (cur && norm.nodes.some((n) => n.id === cur) ? cur : null));
    rawRef.current = raw;
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
      // 브라우저에 남긴다 — 서버는 더 이상 저장된 파일을 화면에 주지 않으므로
      // 새로고침 뒤에도 보이려면 여기 있어야 한다. 로그인해 두었으면 계정에도.
      if (st.state === 'done' && st.payload) {
        await adopt(st.payload, 'local');
        if (accountRef.current.user) {
          try {
            await auth.life.save(st.payload);
            setSource('account');
            toast('내 계정에 저장했습니다');
          } catch (err) {
            toast(err.message, 6000);
          }
        }
      }
    }, 2000);
  }, [adopt, toast]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // 화면이 이미 그래프를 쥐고 있으면 **그것을 같이 보내 거기에 더한다** (서버의
  // life.merge). 지우고 새로 만들지 않는다 (2026-09-08 사용자).
  const onStory = useCallback(async (text, name) => {
    const r = await postJson('/api/life/analyze', { text, name, base: rawRef.current || undefined });
    if (r.ok || r.status === 409) {   // 409 는 이미 돌고 있다는 뜻이라 같이 지켜본다
      setJob({ state: 'running', step: '모델에게 묻는 중', elapsed: 0 });
      watchJob();
      return;
    }
    // 화면 글자에 영어를 두지 않는다 (CLAUDE.md §1) — 명령 이름도 적지 않는다.
    setJob({ state: 'error', error: r.payload?.error
      || '로컬 서버에 닿지 못했습니다. 이 컴퓨터에서 띄운 화면에서만 분석할 수 있습니다.' });
  }, [watchJob]);

  // 부팅: 계정에 올려 둔 것 → 이 브라우저에 남긴 것 → 빈 화면.
  // 서버 폴더의 파일은 읽지 않는다 — 누구의 것인지 모르는 자료가 기본으로
  // 서면 안 된다.
  useEffect(() => {
    let alive = true;
    (async () => {
      // 로그인해 두었고 계정에 올려 둔 것이 있으면 그것을 읽는다. 없으면
      // 조용히 지나간다 — 로그인이 아직 열리지 않은 자리에서는 조건이 아니다.
      // 옛 자료는 서버에게 다듬어 달라고 한다 (POST /api/life/refine — 모델 없이
      // 규칙만: 생년·학년의 해·만난 곳과의 연결). 규칙이 늘면 옛 그래프도 따라온다.
      // 서버가 없는 자리에서는 그대로 쓴다.
      const refined = async (doc) => {
        const r = await postJson('/api/life/refine', doc);
        return r.ok && r.payload?.nodes ? r.payload : doc;
      };
      const mine = await auth.me().then((s) => (s.user ? auth.life.load() : null)).catch(() => null);
      if (!alive) return;
      if (mine?.doc && await adopt(await refined(mine.doc), 'account')) return;
      let kept = null;
      try { kept = JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch { /* 비었다 */ }
      if (kept && await adopt(await refined(kept), 'local')) return;
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

  // --- 노드 하나를 지운다 --------------------------------------------------
  // 상세 패널 아래의 '삭제' (2026-09-08 사용자: "'지우기' 버튼을 지우고 …
  // 섹션 하단에 '삭제' 버튼을 만들어서 … 해당 노드를 지워서 그래프와 연표에서
  // 삭제"). 머리 줄에 있던 '지우기'(통째로 버리기)를 뺀 자리다 — 틀린 것 하나를
  // 지우려고 삶 전체를 다시 넣게 하지 않는다.
  //
  // 지우는 것은 **날것의 문서**이고(lib/life.js removeNode), 지운 자리는 브라우저와
  // — 로그인했으면 — 계정에도 남는다. 계정을 안 고치면 부팅이 계정을 먼저 읽으므로
  // 새로고침에 지운 노드가 되살아난다 (09-07 에 겪은 그 순서다).
  const dropNode = useCallback(async (id) => {
    const raw = rawRef.current;
    if (!id || !raw) return;
    const gone = lifeRef.current?.nodes.find((n) => n.id === id)?.name || '';
    const next = removeNode(raw, id);
    setSelected(null);
    if (!(next.nodes || []).length) {   // 마지막 하나를 지웠다 — 빈 화면으로 돌아간다
      forget();
      rawRef.current = null;
      if (accountRef.current.user) { try { await auth.life.remove(); } catch { /* 계정에 없을 수 있다 */ } }
      toast('마지막 노드를 지웠습니다 · 빈 화면으로 돌아갑니다');
      return;
    }
    await adopt(next, 'local');
    toast(gone ? `지웠습니다 · ${gone}` : '지웠습니다');
    if (accountRef.current.user) {
      try { await auth.life.save(next); setSource('account'); } catch (err) { toast(err.message, 6000); }
    }
  }, [adopt, toast]);   // eslint-disable-line react-hooks/exhaustive-deps

  const name = life?.subject?.name || '나';

  // **주소로 곧장 들어와도 같은 문을 지난다.** 머리 줄의 '내 역사'만 막으면
  // /life.html 을 치는 것으로 그냥 넘어간다 (2026-09-08 사용자: "로그인을 하게
  // 강제해"). 자료를 그리기 전에 세우므로 남의 연표가 뒷배경으로 비치지 않는다.
  //
  // **로그인이 아직 열리지 않았으면(`enabled:false`) 막지 않는다.** 지금이
  // 그 상태다 — 여기서 막으면 이 컴퓨터에서 내 역사를 아예 못 쓴다. 설정 넷이
  // 들어오는 순간부터 문이 닫힌다.
  if (account.enabled && !account.user) {
    return (
      <>
        <header className="top life-top">
          <div className="brand">
            <span className="mark" />
            <h1>histgraph</h1>
            <a className="era" href="/">한국사 그래프</a>
            <span className="era life-here">내 역사</span>
          </div>
        </header>
        <LoginModal
          next="/life.html"
          dismissible={false}
          title="내 역사는 로그인이 필요합니다"
          why="내 역사는 사람마다 다릅니다. 누구의 연표인지 알아야 다음에 다시 열어 드릴 수 있어서, 이 장에서만 로그인을 여쭙니다. 그래프를 보고 검색하는 데에는 로그인이 필요하지 않습니다."
        />
      </>
    );
  }

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
          {/* 계정에 두는 것은 **누를 때만** 일어난다 (위 saveToAccount 머리글). */}
          {account.user && life && (
            <button type="button" className="life-btn" onClick={saveToAccount}
                    title="이 개인 역사를 내 계정에 저장합니다">내 계정에 저장</button>
          )}
          {account.user && source === 'account' && (
            <button type="button" className="life-btn" onClick={dropFromAccount}
                    title="계정에 올려 둔 개인 역사를 지웁니다">계정에서 지우기</button>
          )}
        </div>
        <ThemeToggle onChange={() => boardRef.current?.layout()} />
      </header>
      {kept && <div className="life-toast" role="status" aria-live="polite">{kept}</div>}

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
            {!life && <Empty offline={offline} local={local} onWrite={() => setWriting(true)} />}
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
            {tab === 'event' && <EventDetail life={life} id={selected} onPick={setSelected} onDrop={dropNode} />}
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

function Empty({ offline, local, onWrite }) {
  return (
    <div className="life-empty">
      <h2>내 삶을 한국사 옆에 세웁니다</h2>
      <ol>
        <li><b>내 역사 입력하기</b>를 눌러 자기 이야기를 적습니다 — 태어난 해와 곳, 가족, 이사, 학교, 일, 만남,
          잊히지 않는 책·영화·음악·게임.</li>
        <li>{local
          ? '이 컴퓨터의 모델이 그 글을 읽어 사건과 인과로 옮깁니다. 몇 분 걸립니다. 글도 결과도 이 컴퓨터 밖으로 나가지 않습니다.'
          : '모델이 그 글을 읽어 사건과 인과로 옮깁니다. 1~2분 걸립니다.'}</li>
        <li>사건을 누르면 오른쪽에 원인과 결과, 그 해의 한국사, 전환점 점수가 나옵니다.</li>
      </ol>
      <div className="life-empty-row">
        <button type="button" className="life-btn big on" onClick={onWrite}>내 역사 입력하기</button>
      </div>
      {offline && <p className="tl-hint">자료 서버에 닿지 못해 왕·대통령과 한국사 열이 비어 있습니다.</p>}
    </div>
  );
}

// 진행 띠. 모델이 언제 답할지는 아무도 모르므로 **단계가 자리를, 지난 시간이
// 그 안의 길이를** 정한다 (2026-09-08 사용자: "진행 상황을 텍스트로 알려주고
// progress bar 같은걸 보여줘"). 가장 긴 단계(모델이 읽는 중)는 기대 시간에
// 가까워질수록 천천히 차서 끝에 닿지 않는다 — 100% 는 서버가 끝났다고 할 때만.
const STEP_SPAN = {
  '모델을 올리는 중': [0, 12], '모델에게 묻는 중': [0, 8],
  '이야기를 읽는 중': [8, 86], '답을 검증하는 중': [86, 92],
  '한국사 사건에 잇는 중': [92, 96], '저장하는 중': [96, 99],
};
// 기대 시간(초). 밖의 무료 모델은 1~2분, 로컬 MLX 는 모델을 올리는 데만 몇 분.
const EXPECT_SEC = { openrouter: 90, anthropic: 60, mlx: 360 };
function progressOf(job, local) {
  if (!job) return 0;
  if (job.state === 'done') return 100;
  if (job.state !== 'running') return 0;
  const [lo, hi] = STEP_SPAN[job.step] || [8, 86];
  const expect = EXPECT_SEC[job.backend] || (local ? 360 : 90);
  const t = job.elapsed ?? 0;
  // 지수로 차오른다 — 기대 시간에 약 63%, 두 배에 86%. 끝에는 안 닿는다.
  return Math.round(lo + (hi - lo) * (1 - Math.exp(-t / expect)));
}

// 이야기를 적는 상자. 보기글(placeholder)이 무엇을 적을지 대신 말한다 —
// 빈 칸에 '자유롭게 적으세요' 라고 쓰면 아무도 첫 줄을 못 적는다.
// 적다 만 글은 브라우저에 남긴다. 분석이 몇 분이라 그동안 창을 닫는다.
function StoryBox({ job, local, onSubmit, onClose }) {
  const [text, setText] = useState(() => {
    try { return localStorage.getItem(STORY_KEY) || ''; } catch { return ''; }
  });
  const running = job?.state === 'running';
  // 다 되면 칸을 비운다 — 다음에 적는 것은 **더하는** 이야기라 옛 글이 남아 있으면
  // 같은 것을 두 번 보내게 된다. 원문은 서버가 파일에 이어 둔다.
  useEffect(() => {
    if (job?.state !== 'done') return;
    setText('');
    try { localStorage.removeItem(STORY_KEY); } catch { /* 없다 */ }
  }, [job?.state]);
  const change = (v) => {
    setText(v);
    try { localStorage.setItem(STORY_KEY, v); } catch { /* 저장 못 해도 적을 수 있다 */ }
  };
  const done = job?.state === 'done';
  const pct = progressOf(job, local);
  const made = done && job.payload ? job.payload : null;
  return (
    <div className="life-paste life-story">
      <textarea value={text} onChange={(e) => change(e.target.value)} disabled={running}
                placeholder={STORY_EXAMPLE} spellCheck={false} />
      {(running || done) && (
        <div className="life-progress-row" role="status" aria-live="polite">
          <div className="life-progress" aria-hidden="true"><i style={{ width: `${pct}%` }} /></div>
          <span className="tl-hint">
            {running
              ? `${job.step || '읽는 중'} · ${job.elapsed ?? 0}초 · ${pct}%`
              : job.added
                ? `있는 역사에 더했습니다 · 새 사건과 사람 ${job.added.nodes} · 새 관계 ${job.added.edges}${job.took != null ? ` · ${job.took}초 걸렸습니다` : ''}`
                : made
                  ? `다 만들었습니다 · 사건과 사람 ${made.nodes?.length ?? 0} · 관계 ${made.edges?.length ?? 0}${job.took != null ? ` · ${job.took}초 걸렸습니다` : ''}`
                  : '다 만들었습니다'}
          </span>
        </div>
      )}
      <div className="life-paste-row">
        {running ? (
          <span className="tl-hint">창을 닫아도 계속 돕니다.</span>
        ) : job?.state === 'error' ? (
          <span className="tl-hint life-warn">{job.error}</span>
        ) : (
          /* 밖의 모델일 때는 아무 말도 안 한다 (2026-09-08 사용자). 빈 칸은
             단추를 오른쪽에 붙여 두는 자리다. */
          <span className="tl-hint">{local ? '이 컴퓨터의 모델이 읽습니다. 글은 어디로도 보내지 않습니다.' : ''}</span>
        )}
        <button type="button" className="life-btn" onClick={onClose}>닫기</button>
        {/* 글이 한 자라도 있으면 누를 수 있다. 전에는 40자 미만이면 말없이 잠겨
            있어 "입력해도 버튼이 활성화가 안 돼"(2026-09-08) — 문턱은 두지 않는다. */}
        <button type="button" className="life-btn go" disabled={running || !text.trim()}
                onClick={() => onSubmit(text, '나')}>{running ? '읽는 중' : '입력'}</button>
      </div>
    </div>
  );
}

// --- 사건 상세 ------------------------------------------------------------
function EventDetail({ life, id, onPick, onDrop }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  // 지우기 전에 한 번 묻는다 — 되돌리는 길이 없다. 브라우저가 띄우는 상자는
  // 단추 글자가 우리 것이 아니므로(화면에 영어) 패널 안에서 묻는다.
  const [ask, setAsk] = useState(false);
  useEffect(() => { setAsk(false); }, [id]);
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
            <li key={i}><span className="tl-rel">{edgeLabel(e.type, byId.get(e.source)?.type, byId.get(e.target)?.type, e.role)}</span> {e.source === id ? nameOf(e.target) : nameOf(e.source)}{e.description ? <p>{e.description}</p> : null}</li>
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
      {/* 상세의 맨 아래 — 이 노드를 지운다. 함께 사라지는 것(관계·연표 자리)을
          먼저 세어 보여 준다. 지운 뒤에는 되돌릴 길이 없으므로 두 번 누르게 한다. */}
      {onDrop && (
        <div className="life-del">
          {ask ? (
            <>
              <span className="tl-hint">
                {`정말 지울까요? 관계 ${ins.length + outs.length}건이 함께 사라집니다`}{t ? ' · 연표에서도 내려갑니다' : ''}
              </span>
              <button type="button" className="life-btn" onClick={() => setAsk(false)}>그만두기</button>
              <button type="button" className="life-btn danger" onClick={() => { setAsk(false); onDrop(id); }}>지웁니다</button>
            </>
          ) : (
            <button type="button" className="life-btn danger" onClick={() => setAsk(true)}>삭제</button>
          )}
        </div>
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
