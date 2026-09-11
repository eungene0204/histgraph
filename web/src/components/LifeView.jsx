import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ThemeToggle } from './ThemeToggle.jsx';
import { LifeSearch } from './LifeSearch.jsx';
import { auth, csrf } from '../lib/auth.js';
import { COPYRIGHT } from '../lib/site.js';
import { LoginModal } from './LoginModal.jsx';
import { GraphCanvas } from './GraphCanvas.jsx';
import { SidePanel } from './SidePanel.jsx';
import { DetailPanel } from './DetailPanel.jsx';
import { api } from '../lib/api.js';
import { readLife, writeLife, forgetLife, readSide, writeSide, ownerOf, localAfterAccount, STORE_KEY, NEXT_KEY, FAIL_KEY } from '../lib/lifestore.js';
import { LifeBoard, normalize, removeNode, editNode, nodeYears, dateSaid, graphPayload, graphMeta, boardWidth, edgeLabel, splitStories, appendDraft, nodeLabel, missingYears, addedFocus, addedNames, NODE_TYPE_KO, IMPACT_KO, LIFE_STAGES, CAUSAL_EDGES, EVENT_TYPES } from '../lib/life.js';

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
// 열기', '붙여넣기', '연표접기' 버튼 모두 삭제해줘" · 같은 날 "'내 계정에 저장',
// '계정에서 지우기' 버튼을 지워조"). 붙여 넣기·파일 열기는 사람이 모델과 따로
// 대화해 받은 JSON 을 넣던 길이고, 이제 화면이 직접 물어본다. 계정에 두는
// 것은 사람이 청하지 않아도 저절로 일어난다. 연표는 늘 펴 둔다.

// 오늘 — 이야기를 적어 넣은 날. 이 컴퓨터의 달력으로 잰다 (세계표준시로 재면
// 저녁에 적은 것이 내일이 된다).
function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// 브라우저에 남기는 자리 셋(`STORE_KEY` 문서 · `NEXT_KEY` 보낸 이야기 ·
// `FAIL_KEY` 모델이 못 읽은 글)은 `lib/lifestore.js` 가 들고 있다. **여기서
// localStorage 를 직접 부르지 않는다** — 거기에 '누구의 것인가'를 재는 규칙이
// 붙어 있고, 그것을 지나지 않는 길이 하나라도 있으면 한 컴퓨터를 나눠 쓰는
// 사람에게 앞사람의 삶이 선다 (2026-09-11 점검, lifestore 머리글).

// 입력 상자의 보기글. 무엇을 적어야 하는지는 설명보다 예가 빠르다 —
// **해와 곳, 가족, 이사, 학교, 일, 만남, 그때의 마음.** 지어낸 사람들이다.
// 앞에 '예:' 를 달고 색을 더 흐리게 두어 **예문이지 내 글이 아니라는 것**이
// 보이게 한다 (2026-09-08 사용자).
//
// **여럿을 두고 상자를 열 때마다 하나를 뽑는다** (2026-09-09 사용자: "연령,
// 성별, 직종을 다르게 해서 여러개 만들어서 랜덤으로 보여주게 해줘"). 예가
// 하나뿐이면 그 한 사람의 삶이 '이렇게 적어야 하는 것'처럼 읽힌다 — 1979년생
// 공대 나온 사람의 연표가 보기글이면 1955년생 농사꾼은 자기 이야기가 여기
// 들어갈 자리가 아니라고 여긴다. 그래서 세대(1950~2000년대생)·성별·직종
// (농사·건설·봉제·미용·기계·요리·간호·개발)을 갈라 여섯을 둔다.
//
// 지명은 실제 있는 곳이되, 학교·회사·가게 이름은 **이 세상에 없는 것**이다 —
// 실재하는 곳의 이름을 남의 삶에 붙이지 않는다. (처음 지은 다섯 중 셋이
// 검색하니 실재하는 회사·사진관이었고, 이번에 지은 '푸른소반'도 홍대의 실재
// 식당이라 물렀다. 지금 것은 하나씩 검색해 없는 것을 확인했다.)
const STORY_EXAMPLES = [
  `예: 나는 1955년 전남 보성에서 태어났다. 아버지는 논 서 마지기를 부치셨고 어머니는 장날마다 나물을 내다 파셨다. 1963년 '두메실국민학교'에 들어갔는데 십 리 길을 걸어 다녔다.
1974년 서울로 올라와 영등포의 '너럭건재'에서 미장일을 배웠다. 1977년 사우디로 나가 삼 년을 일했고, 돌아와 그 돈으로 봉천동에 방 두 칸을 얻었다.
1981년 고향 사람 소개로 아내를 만나 이듬해 큰딸을 낳았다. 1997년 외환위기 때는 현장이 끊겨 반년을 놀았다. 2015년 보성으로 내려와 지금은 매실 농사를 짓는다.`,

  `예: 나는 1968년 대구 서구에서 태어났다. 삼 남매의 맏이라 1984년 '해뜨미여자상업고등학교'를 다니면서 밤에는 '바람실섬유' 봉제 공장에 나갔다.
1988년 올림픽 때 우리 집에 처음 텔레비전이 들어왔다. 1991년 결혼해 안산으로 옮겼고 1993년 아들을 낳았다.
1996년 미용 자격증을 따서 원곡동에 '노루목머리방'을 열었다. 2003년 남편이 아파 가게를 두 해 접었던 것이 제일 힘들었다. 2020년 코로나 때 손님이 끊겼지만 지금도 그 자리에 있다.`,

  `예: 나는 1979년 전북 익산에서 태어났다. 아버지는 익산역 근처에서 '노을결사진관'이라는 작은 사진관을 하셨고, 어머니는 집에서 한복 삯바느질을 하셨다. 외할머니는 김제에서 벼농사를 지으셨는데, 방학마다 거기서 지냈다.
1986년 익산의 '샛별뫼초등학교'에 들어갔다. 1991년 아버지가 사진관을 접고 인천 부평으로 올라오면서 전학을 갔다. 말투 때문에 놀림을 받았던 것이 아직 기억난다.
1997년 겨울 외환위기 때 아버지가 다니던 '온새미전자'가 문을 닫았고, 그 뒤로 어머니가 부평시장에서 반찬 가게를 시작했다. 나는 그해 처음으로 아르바이트를 했다.
1998년 '바람결대학교' 기계공학과에 들어갔다. 2002년 월드컵 때 광장에서 만난 선배 덕에 2004년 '별무리정밀'에 첫 직장을 얻었고, 2011년 지금의 남편을 만났다. 2020년 코로나 때 회사가 재택으로 바뀌면서 부평을 떠나 강원 원주로 이사했다.`,

  `예: 나는 1988년 부산 사하구에서 태어났다. 아버지는 자갈치에서 배를 타셨고 어머니는 감천동에서 분식집을 하셨다.
2004년 '바다마루정보고등학교'에 들어갔지만 요리가 하고 싶어 2007년 서울로 올라왔다. 2009년부터 2011년까지 강원 화천에서 군 생활을 했고, 제대하고 신사동 '들메밥상' 주방에 막내로 들어갔다.
2016년 경주 지진이 나던 날 밤에 그릇을 다 쓸어 담았던 게 기억난다. 2018년 아내를 만나 2021년 제주로 내려와 애월에 '돌각담식탁'이라는 작은 가게를 열었다.`,

  `예: 나는 1996년 충북 청주에서 태어났다. 부모님이 두 분 다 교사라 어릴 때부터 이사가 잦았고, 방학이면 외가가 있는 단양에서 지냈다.
2012년 '별뜨락고등학교'에 들어갔고 2015년 '숲마루보건대학교' 간호학과에 진학했다. 2019년부터 서울 은평구의 병원에서 일했다.
2020년 코로나 병동에 배치되어 여름 내내 집에 못 들어간 적도 있다. 2022년 동아리에서 만난 사람과 결혼했고 2024년 딸을 낳았다. 지금은 야간 근무를 줄이고 방문 간호를 배우는 중이다.`,

  `예: 나는 2001년 인천 남동구에서 태어났다. 아버지는 남동공단에서 도금 일을 하셨고 어머니는 마트 계산대에 서셨다.
2017년 '솔미재고등학교'에 들어가 게임을 만들고 싶어 컴퓨터 동아리에 들었다. 2020년 대학 1학년은 내내 화상 수업이라 같은 과 친구를 한 명도 못 만났다.
2021년부터 2022년까지 군에서 통신병으로 복무했고, 제대하고는 학비를 벌려고 새벽에 배달을 뛰었다. 2024년 판교의 작은 회사 '모래별소프트'에 들어가 지금은 앱을 만든다.`,
];

// 상자를 열 때마다 하나를 뽑는다. 자리를 기억하지 않는 것은 일부러다 —
// 같은 사람이 다시 열면 다른 삶이 서는 편이 '아무거나 적어도 된다'는 말을
// 대신한다.
function anExample() {
  return STORY_EXAMPLES[Math.floor(Math.random() * STORY_EXAMPLES.length)];
}

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

// 이야기를 서버에 보낸다. 서버가 없는 자리(정적 파일)에서는 fetch 자체가
// 실패하므로 상태 0 으로 돌려주고 화면이 그렇게 말한다.
//
// **표와 쿠키를 함께 싣는다.** 배포에서는 이 길이 로그인한 사람의 것만 받고
// (`api/index.py _life_gate`), 표가 없는 요청은 남의 사이트가 이 브라우저로
// 모델을 부르는 길이 되므로 서버가 막는다 (`auth.check_write`).
async function postJson(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Histgraph-CSRF': csrf() },
      credentials: 'same-origin',
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
  // 계정에 올려 둔 것을 다 읽기 전에는 '비었다'고 그리지 않는다 (2026-09-09
  // 사용자: "메세지 화면이 한 번 보이고 그 다음에 그래프가 보여"). 계정을 읽는
  // 데 왕복이 셋이라(`/api/me` → `/api/my/life` → `/api/life/refine`) 그동안
  // `life` 가 null 인데, 그것을 없는 것으로 읽으면 있는 사람에게도 '내 역사를
  // 기록하세요'가 한 번 번쩍인다. **없다고 확인되기 전까지는 아무 말도 안 한다.**
  const [booting, setBooting] = useState(true);
  const [context, setContext] = useState(null);
  // 자료가 어디서 왔는지는 **화면에 적지 않는다** (2026-09-08 사용자: "'로컬
  // 서버에 저장된 자료' 문구도 삭제해"). 어디서 왔든 하는 일이 같아졌으므로
  // (계정에 두는 것이 자동이다 — 아래 keepInAccount) 상태로도 들고 있지 않는다.
  // 주소의 #사건id 가 고른 사건이다 — 새로고침해도 자리를 잃지 않고 "이거 봐" 하고 줄 수 있다.
  const [selected, setSelected] = useState(() => (typeof location !== 'undefined' && location.hash ? decodeURIComponent(location.hash.slice(1)) : null));
  const [tab, setTab] = useState('event');
  // 오른쪽 상세를 폈나 (2026-09-08 사용자: "이 오른쪽 DRAWER를 다시 접을수 있게
  // 버튼을 만들어서 오른쪽으로 들어 갈 수 있게 해 줘"). 접으면 드로어가 오른쪽
  // 으로 미끄러져 들어가고 그 폭(348px)을 가운데 그래프가 되찾는다.
  //
  // **브라우저에 남기지 않는다** — 노드를 고르면 저절로 펴지므로(아래 pick)
  // 접힌 채로 저장해 두면 다음에 열 때만 한 번 어긋나 보인다. 접은 것은
  // '지금 넓게 보고 싶다'는 그때의 뜻이지 이 사람의 설정이 아니다.
  const [detailOpen, setDetailOpen] = useState(true);
  // --- 한국사를 이 화면에서 본다 ------------------------------------------
  // 2026-09-10 사용자: "내 역사에서 한국사 사건을 연표에서 클릭하면 한국사
  // 페이지로 이동하는데 그러지 말고 한국사 그래프와 노드 정보를 그 페이지에서
  // 바로 보여줘 이동하지 말고". 가운데 캔버스가 그 사건의 주변 관계가 되고
  // (`/api/graph` — 한국사 화면과 **같은 자료·같은 규칙**), 오른쪽은 한국사
  // 상세(DetailPanel)가 그대로 선다. 설명·출처 한 줄·인과 사슬·관계 목록이
  // 두 화면에서 같은 글이어야 하므로 여기에 다시 그리지 않고 그 부품을 부른다.
  //
  // 왼쪽 내 연표는 그대로 있다 — 화면을 떠나지 않는 것이 이 일의 전부다.
  const [world, setWorld] = useState(null);        // 한국사 노드 상세 (서버 응답)
  const [worldNote, setWorldNote] = useState(null);
  const [worldTrail, setWorldTrail] = useState([]);   // 관계를 타고 들어간 자취
  const [worldSide, setWorldSide] = useState(null);   // 한국사 그래프의 범례·시작점
  const worldIdRef = useRef(null);   // 지금 보고 있는 한국사 노드 (콜백이 읽는다)
  const worldAtRef = useRef(null);   // { id, label } — 자취에 쌓을 것
  // 한국사에서 나온다 — 내 그래프로 되돌리는 것은 아래 효과가 맡는다(`world`).
  const leaveWorld = useCallback(() => {
    worldIdRef.current = null;
    worldAtRef.current = null;
    setWorld(null); setWorldNote(null); setWorldTrail([]);
  }, []);
  // 노드를 고르는 것은 "이것을 보겠다"는 뜻이라, 접혀 있으면 편다 — 접어 둔 채로
  // 두면 연표·그래프를 눌러도 아무 일이 없는 화면이 된다.
  // 내 사건을 고르면 한국사에서 나온다 — 한 캔버스가 둘을 같이 그릴 수는 없다.
  const pick = useCallback((id, to = 'event') => {
    leaveWorld();
    setSelected(id); setTab(to); setDetailOpen(true);
  }, [leaveWorld]);
  // 상세를 폼으로 펴 두었나 (아래 EventEdit). 다른 노드로 옮겨 가면 접는다 —
  // 고치던 칸이 남의 노드 위에 서면 안 된다.
  const [editing, setEditing] = useState(false);
  const [writing, setWriting] = useState(false);   // 이야기 상자를 폈나
  const [logOpen, setLogOpen] = useState(false);   // '내가 적은 이야기' 를 폈나
  // 사람이 한 번씩 적어 넣은 이야기 덩어리 — 문서가 `stories` 로 들고 다닌다.
  const [stories, setStories] = useState([]);
  const storiesRef = useRef(stories);
  storiesRef.current = stories;
  const [job, setJob] = useState(null);   // 분석 상태 (running·done·error)
  // 이야기를 읽는 모델이 이 컴퓨터에 있는가. 서버가 `/api/life/job` 에 적어
  // 준다 — 밖의 무료 모델로 읽으면 글이 이 컴퓨터를 나가므로 **그렇게 적는다.**
  const [local, setLocal] = useState(true);
  // 답이 한 번에 오는가(배포) 띄워 두고 물어 가는가(로컬 서버). 같은 자리에
  // 서버가 적어 준다 — **창을 닫아도 되는지**가 그것으로 갈린다.
  const [blocking, setBlocking] = useState(false);
  const blockingRef = useRef(false);
  const backendRef = useRef('');
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
  // 콜백 안에서 늘 최신 설정을 보게 하는 거울 (한국사 그래프를 부를 때 쓴다).
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const meta = useMemo(() => (life ? graphMeta(life) : null), [life]);

  // --- 내 계정에 두기 -----------------------------------------------------
  // **누르는 단추가 없다** (2026-09-08 사용자: "'내 계정에 저장', '계정에서
  // 지우기' 버튼을 지워조. 저장 버튼을 누르지 않아도 사용자가 '입력' 버턴을
  // 누르면 자동으로 저장해줘"). 그래서 자료가 바뀌는 자리마다 이 한 길을
  // 지난다 — '입력' 을 누를 때 · 분석이 끝났을 때 · 노드를 지웠을 때 · 부팅이
  // 브라우저에만 있는 것을 찾았을 때. 부팅이 계정을 먼저 읽으므로 계정이 늘
  // 최신이어야 한다 (실측: 09-07 에 계정에 올린 옛 그래프가 뒤에 분석해
  // 브라우저에만 남은 새 그래프를 가렸다 — "새로고침 해도 친구들이 안 보이는데?").
  // 로그인이 안 된 자리는 전처럼 브라우저에만 남는다.
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

  // 지금 화면을 보는 사람의 **주인 표**. 브라우저에 남기는 것마다 여기에
  // 적힌 표가 함께 간다 (lifestore). 비어 있는 동안(신원을 아직 모르는 동안)
  // 에는 **브라우저에서 아무것도 읽지 않는다** — 모르는 채로 재면 자기 자료를
  // 남의 것으로 알고 지운다.
  const ownerRef = useRef('');
  useEffect(() => {
    auth.me().then((me) => { ownerRef.current = ownerOf(me); setAccount(me); });
  }, []);

  // 로그인이 안 된 자리에서는 아무 일도 안 한다. 말(`msg`)을 주면 된 뒤에
  // 팝업으로 알리고, 안 주면 조용히 올린다 (부팅·'입력' 처럼 사람이 저장을
  // 청한 것이 아닌 자리). 안 된 것은 늘 말한다 — 계정에 없는 채로 두면
  // 다른 컴퓨터에서 못 본다.
  // 분석이 끝났을 때 문서에 실을 이야기 기록. '입력' 을 누를 때 여기에 적어
  // 두었다가 결과가 오면 그 문서에 넣는다. 브라우저에도 한 벌 두는 것은 분석이
  // 도는 몇 분 사이에 새로고침을 해도 방금 적은 문단을 잃지 않기 위해서다.
  const nextRef = useRef(null);
  const rememberStories = useCallback((list) => {
    nextRef.current = list;
    writeSide(NEXT_KEY, JSON.stringify(list), ownerRef.current);
  }, []);
  const takeStories = useCallback(() => {
    let list = nextRef.current;
    if (!list) {
      try { list = JSON.parse(readSide(NEXT_KEY, ownerRef.current) || 'null'); } catch { list = null; }
    }
    nextRef.current = null;
    writeSide(NEXT_KEY, '', ownerRef.current);
    return Array.isArray(list) && list.length ? list : null;
  }, []);

  const keepInAccount = useCallback(async (doc, msg) => {
    if (!doc || !accountRef.current.user) return;
    try {
      await auth.life.save(doc);
      if (msg) toast(msg);
    } catch (err) {
      toast(err.message, 6000);
    }
  }, [toast]);

  // --- 입력창에 글을 놓는다 ------------------------------------------------
  // 칸에 선 글. **브라우저에 남기지 않는다** (2026-09-10 사용자: "지금 내 역사
  // 입력창에 입력을 하면 마지막 입력이 남아서 보이고 있어. 사용자가 입력창을 다시
  // 열면 그냥 placeholder만 보여줘"). 전에는 적는 대로 브라우저에 남겨 두어,
  // 상자를 닫거나 새로고침한 뒤에 다시 열면 지난번 글이 서 있었다 — 그 글이 보낸
  // 것인지 아닌지는 화면 어디에도 없다. **칸에 선 글은 '지금 쓰고 있는 글' 하나만
  // 뜻한다**: 상자를 닫으면 걷고, 새로 열면 보기글뿐이다.
  //
  // 상자가 다시 세워지는 동안(key={draftStamp}) 글을 나르는 것이 이 칸이라, 적는
  // 대로 여기에 담아 둔다. **상태가 아니라 ref 다** — 글자마다 화면 전체를 다시
  // 그릴 이유가 없다.
  const draftRef = useRef('');
  const [draftStamp, setDraftStamp] = useState(0);
  // 입력창에 글을 놓고 상자를 새로 세운다. 모달에서 옛 글을 옮겨 올 때와,
  // 못 보낸 글을 사람이 '되돌리기' 로 부를 때 같은 길을 쓴다.
  const putDraft = useCallback((text) => {
    draftRef.current = appendDraft(draftRef.current, text);
    setDraftStamp((n) => n + 1);
    setWriting(true);
  }, []);
  const closeWriting = useCallback(() => {
    setWriting(false);
    draftRef.current = '';
  }, []);
  const sentRef = useRef('');
  // 모델이 지금 읽고 있는 글. **칸이 이것을 보여 준다** (2026-09-09 사용자:
  // "분석하는 동안 입력창에는 예문을 보여주지말고 사용자가 입력한 내용을
  // 보여줘") — 보낸 뒤 칸이 비면 보기글이 서서, 몇 분을 기다리는 사람이
  // 자기가 무엇을 보냈는지 화면 어디에서도 못 본다. 끝나면 비운다.
  const [sent, setSent] = useState('');

  // --- 못 보낸 글 ----------------------------------------------------------
  // 보낸 글은 칸에서 지운다. 모델이 답을 못 주면 **칸에 도로 넣지 않고** 여기에
  // 둔다 — 상자가 오류 옆에 '적은 글 되돌리기' 를 세우고, 누르면 그때 칸으로
  // 간다. 답이 온 자리에서는 비운다 (그 글은 이미 기록에 들었다).
  // **첫 그림에서 읽지 않는다.** 이 자리에 남은 글이 누구 것인지는 `/api/me`
  // 를 받은 뒤에야 알 수 있다 (부팅이 읽어 넣는다).
  const [failed, setFailed] = useState('');
  const keepFailed = useCallback((text) => {
    setFailed(text || '');
    writeSide(FAIL_KEY, text || '', ownerRef.current);
  }, []);

  // 자료를 받아들이는 한 길. 날것이든 서버를 거친 것이든 normalize 를 지난다.
  // `focus` 는 **이번에 새로 생긴 것**이다 (life.addedFocus) — 그리로 옮겨 간다.
  const adopt = useCallback(async (raw, from, focus = null) => {
    let norm;
    try { norm = normalize(raw); } catch { return false; }
    if (!norm.nodes.length) return false;
    setLife(norm);
    const goes = focus && norm.nodes.some((n) => n.id === focus) ? focus : null;
    setSelected((cur) => goes || (cur && norm.nodes.some((n) => n.id === cur) ? cur : null));
    setStories(Array.isArray(raw.stories) ? raw.stories : []);
    rawRef.current = raw;
    if (from === 'local') writeLife(raw, ownerRef.current);
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

  // --- 이야기 → 개인 그래프 --------------------------------------------
  // **답이 오는 길이 둘이다.** 로컬 서버는 띄우기만 하고(202) 여기서 2초마다
  // 물어본다 — MLX 는 몇 분이라 요청 하나에 매달면 브라우저가 먼저 끊는다.
  // 배포(서버리스)는 그 길이 아예 없어서(다음 요청까지 사는 스레드가 없다)
  // 답이 POST 하나에 실려 온다. 가르는 것은 **몸**이다 — `state` 가 `done`·
  // `error` 면 다 온 것이고, 아니면 물어본다 (`server.life_post`).

  // 끝난 상태 하나를 받아 화면과 저장을 마무리한다. 두 길이 여기서 만난다.
  const finish = useCallback(async (st) => {
    setJob(st);
    // 모델이 답을 못 준 글은 잃지 않는다 — 칸이 아니라 '되돌리기' 에 둔다.
    if (st.state === 'error' && sentRef.current) { keepFailed(sentRef.current); sentRef.current = ''; }
    if (st.state !== 'running') setSent('');   // 끝났으면 칸은 다시 사람의 것이다
    // 브라우저에 남긴다 — 서버는 더 이상 저장된 파일을 화면에 주지 않으므로
    // 새로고침 뒤에도 보이려면 여기 있어야 한다. 로그인해 두었으면 계정에도.
    if (st.state === 'done' && st.payload) {
      // 방금 읽은 이야기를 문서에 실어 둔다 — 그래야 다음에 열어 고칠 수 있다.
      const said = takeStories();
      sentRef.current = '';
      keepFailed('');
      const doc = said ? { ...st.payload, stories: said } : st.payload;
      // **다 만들었으면 그것을 보여 준다.** 연표가 서 있던 자리에 그대로 있으면
      // 사람 눈에는 아무 일도 안 일어난 것이다 (2026-09-09 사용자: "모델이 해석을
      // 끝냈으면 그래프와 연표에 바로 적용되야 하는데 그게 안 되고 있는거 같어").
      // 고른 노드는 연표를 그 자리로 미끄러뜨리고(LifeBoard.select) 그래프도
      // 거기로 옮긴다(gv.focusOn). 첫 그래프(더한 것이 아닌 때)는 옮기지 않는다 —
      // 전부가 새 것이라 고를 하나가 없다.
      // 옮겨 갈 자리는 **연표에 새로 선 것**이 먼저다 — 옛 노드가 이제야 해를 얻어
      // 줄에 서는 일도 있어서(life.merge `timeline_ids`), 새 노드만 보면 연표가
      // 늘었는데도 화면이 안 움직인다.
      await adopt(doc, 'local', st.added
        ? addedFocus(doc, [...(st.added.timeline_ids || []), ...(st.added.ids || [])]) : null);
      await keepInAccount(doc, '내 계정에 저장했습니다');
    }
  }, [adopt, keepInAccount, takeStories, keepFailed]);

  // 새로고침해도 돌던 것을 다시 붙잡는다 (부팅 효과). 로컬 서버에만 있는 길이다.
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
      await finish(st);
    }, 2000);
  }, [finish]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // 답이 한 번에 오는 자리에서는 **서버가 초를 세어 주지 않는다.** 진행 띠가
  // 멈춰 있으면 멎은 화면이므로 여기서 센다 (progressOf 가 elapsed 를 읽는다).
  const tickRef = useRef(null);
  const stopTick = useCallback(() => { clearInterval(tickRef.current); tickRef.current = null; }, []);
  const startTick = useCallback(() => {
    const from = Date.now();
    stopTick();
    tickRef.current = setInterval(() => {
      setJob((j) => (j?.state === 'running'
        ? { ...j, elapsed: Math.round((Date.now() - from) / 1000) } : j));
    }, 1000);
  }, [stopTick]);
  useEffect(() => stopTick, [stopTick]);

  // 화면이 이미 그래프를 쥐고 있으면 **그것을 같이 보내 거기에 더한다** (서버의
  // life.merge). 지우고 새로 만들지 않는다 (2026-09-08 사용자).
  const onStory = useCallback(async (text, name) => {
    sentRef.current = text;
    setSent(text);
    // 누르자마자 지금 화면에 있는 것을 계정에 둔다. 분석은 몇 분을 도는데
    // 그 사이에 창을 닫아도 여태 만든 것은 남아 있어야 한다.
    keepInAccount(rawRef.current);
    // 답을 기다리는 동안 띠가 선다. 한 번에 오는 자리에서는 단계가 안 오므로
    // 실제로 하고 있는 일('이야기를 읽는 중')을 미리 적는다 — 8%에 멈춘 띠를
    // 90초 동안 보여 주지 않는다.
    setJob({ state: 'running', elapsed: 0, backend: backendRef.current,
             step: blockingRef.current ? '이야기를 읽는 중' : '모델에게 묻는 중' });
    startTick();
    const r = await postJson('/api/life/analyze', { text, name, base: rawRef.current || undefined });
    const st = r.payload;
    stopTick();
    if (st && (st.state === 'done' || st.state === 'error')) {   // 배포 — 다 돌고 왔다
      if (st.state === 'done') rememberStories([...storiesRef.current, { at: today(), text: text.trim() }]);
      await finish(st);
      return;
    }
    if (r.ok || r.status === 409) {   // 409 는 이미 돌고 있다는 뜻이라 같이 지켜본다
      rememberStories([...storiesRef.current, { at: today(), text: text.trim() }]);
      watchJob();
      return;
    }
    // 화면 글자에 영어를 두지 않는다 (CLAUDE.md §1) — 명령 이름도 적지 않는다.
    setJob({ state: 'error', error: r.payload?.error
      || '자료 서버에 닿지 못했습니다. 잠시 뒤에 다시 해 주세요.' });
    keepFailed(text);          // 못 보낸 글은 '되돌리기' 에 둔다
    sentRef.current = '';
    setSent('');
  }, [watchJob, finish, keepInAccount, rememberStories, keepFailed, startTick, stopTick]);

  // 못 보낸 글을 사람이 부를 때. 칸으로 옮기고 '되돌리기' 는 걷는다.
  const restoreFailed = useCallback(() => {
    if (!failed) return;
    putDraft(failed);
    keepFailed('');
  }, [failed, putDraft, keepFailed]);

  // 예전에 적은 글을 입력창으로 옮긴다 (2026-09-08 사용자: "예전 입력을 클릭하면
  // 우리 인생 입력창에 자동으로 복사해줘"). 상자는 놓아 준 글을 읽고 서므로
  // (`draftRef`) 거기에 적고 상자를 새로 세운다. 적다 만 글은 아래에
  // 붙인다 — 쓰던 것을 삼키지 않는다 (`life.js appendDraft`).
  const pickStory = useCallback((text) => {
    putDraft(text);
    setLogOpen(false);
    // **팝업을 띄우지 않는다** (2026-09-08 사용자: "이 알림을 보여주지마. 필요
    // 없는 거야"). 상자가 열리며 그 글이 거기 서는 것이 이미 답이다 — 한 일이
    // 눈앞에 보이는데 글로 또 말하는 것은 군더더기다.
  }, [putDraft]);

  // --- 기록에서 한 줄 지운다 ----------------------------------------------
  // **그래프는 건드리지 않는다.** 지우는 것은 '내가 적은 글' 목록이고, 거기서
  // 나온 노드는 그대로 선다 (2026-09-08 사용자: 남은 글로 처음부터 다시 짓던
  // '고쳐서 다시 읽기' 를 뺐다 — 그래프를 버리고 몇 분을 기다리는 길이었다).
  // 노드가 틀렸으면 상세 패널의 '삭제' 가, 글이 틀렸으면 그 줄을 입력창으로
  // 옮겨 고쳐 넣는 길이 있다.
  //
  // 지운 자리는 브라우저와 계정에 바로 남긴다 — 안 그러면 새로고침에 되살아난다.
  const dropStory = useCallback(async (i) => {
    const list = storiesRef.current.filter((_, k) => k !== i);
    setStories(list);
    if (!rawRef.current) return;
    const doc = { ...rawRef.current, stories: list };
    rawRef.current = doc;
    writeLife(doc, ownerRef.current);
    await keepInAccount(doc);
  }, [keepInAccount]);

  // 부팅: 계정에 올려 둔 것 → 이 브라우저에 남긴 것 → 빈 화면.
  // 서버 폴더의 파일은 읽지 않는다 — 누구의 것인지 모르는 자료가 기본으로
  // 서면 안 된다.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // 로그인해 두었고 계정에 올려 둔 것이 있으면 그것을 읽는다. 없으면
        // 조용히 지나간다 — 로그인이 아직 열리지 않은 자리에서는 조건이 아니다.
        // 옛 자료는 서버에게 다듬어 달라고 한다 (POST /api/life/refine — 모델 없이
        // 규칙만: 생년·학년의 해·만난 곳과의 연결). 규칙이 늘면 옛 그래프도 따라온다.
        // 서버가 없는 자리에서는 그대로 쓴다.
        const refined = async (doc) => {
          const r = await postJson('/api/life/refine', doc);
          return r.ok && r.payload?.nodes ? r.payload : doc;
        };
        // 계정을 못 읽은 것(네트워크)과 계정이 빈 것을 가른다 — 못 읽었는데
        // 브라우저의 옛 자료를 올리면 계정에 있던 새 것을 덮는다.
        const me = await auth.me();
        // **여기서 주인이 정해진다.** 이 줄보다 앞에서 브라우저를 읽는 길은
        // 없어야 한다 — 신원을 모르는 채로 재면 남의 것과 내 것을 못 가른다.
        ownerRef.current = ownerOf(me);
        let mine = null, read = false;
        if (me.user) {
          try { mine = await auth.life.load(); read = true; } catch { /* 못 읽었다 */ }
        }
        if (!alive) return;
        // 못 보낸 글도 주인이 같을 때만 되살린다.
        const back = readSide(FAIL_KEY, ownerRef.current);
        if (back) setFailed(back);
        if (mine?.doc && await adopt(await refined(mine.doc), 'account')) return;
        // 브라우저에 남은 것은 **주인이 맞을 때만** 온다. 남의 것이면 그 자리에서
        // 지운다. **계정에서 지운 것도 여기서 걸린다** — 내 표가 찍힌 사본인데
        // 계정에 없으면 지운 것이므로 되살리지 않는다 (lifestore 머리글).
        const kept = localAfterAccount({
          owner: ownerRef.current, accountRead: read, accountHasDoc: !!mine?.doc,
        });
        if (kept && await adopt(await refined(kept), 'local')) {
          // 브라우저에만 있던 것을 계정으로 옮기는 길. 단추가 하던 일이다.
          if (me.user && read) await keepInAccount(rawRef.current);
          return;
        }
      } finally {
        // 읽어 봤다는 것 자체를 남긴다 — 있든 없든, 중간에 터졌든.
        // 여기서 안 내리면 자료가 없는 사람의 화면이 영영 빈 채로 멈춘다.
        if (alive) setBooting(false);
      }
    })();
    // 창을 닫았다 다시 열어도 돌던 분석은 서버에서 계속 돈다.
    (async () => {
      // 신원부터 (auth.me 는 화면 전체가 한 번만 묻고 나눠 쓴다). 서버도
      // **자기가 띄운 분석만** 알려 준다 — 남의 것은 없는 것으로 온다
      // (server.LifeAnalysis.status).
      ownerRef.current = ownerOf(await auth.me());
      const st = await getJson('/api/life/job').catch(() => null);
      if (!alive || !st) return;
      setLocal(st.backend !== 'openrouter' && st.backend !== 'anthropic');
      backendRef.current = st.backend || '';
      blockingRef.current = !!st.blocking;
      setBlocking(!!st.blocking);
      if (st.state !== 'running') return;
      // 새로고침해도 읽히고 있는 글을 칸에 되돌린다 — 보낼 때 기록으로
      // 남겨 둔 마지막 문단이 그것이다 (rememberStories).
      let last = '';
      try {
        const list = JSON.parse(readSide(NEXT_KEY, ownerRef.current) || 'null');
        if (Array.isArray(list) && list.length) last = list[list.length - 1]?.text || '';
      } catch { /* 없으면 칸은 빈 채로 돈다 */ }
      setJob(st); setSent(last); setWriting(true); watchJob();
    })();
    return () => { alive = false; };
  }, [adopt, watchJob, keepInAccount]);

  // 이야기 기록이 없는 옛 문서(이 열이 생기기 전에 만든 것)를 위해, 이 컴퓨터에
  // 남은 원문을 한 번 묻는다 (`/api/life/story` → data/life/나.txt). 빈 줄로 갈라
  // 덩어리를 세운다. 다른 컴퓨터·배포에서는 빈 글이 와 아무 일도 없다.
  const askedRef = useRef(false);
  useEffect(() => {
    if (!life || stories.length || askedRef.current) return;
    askedRef.current = true;
    (async () => {
      const r = await getJson('/api/life/story').catch(() => null);
      const list = splitStories(r?.text || '');
      if (!list.length) return;
      setStories(list);
      if (!rawRef.current) return;
      rawRef.current.stories = list;
      // **찾자마자 계정에 올린다.** 다음 저장까지 미루면, 그 사이에 아무것도
      // 안 한 사람의 계정에는 이야기가 없다 — 다른 컴퓨터에서 열면 빈 목록이다.
      // 브라우저에도 같이 남긴다 (부팅이 계정 다음으로 읽는 자리).
      writeLife(rawRef.current, ownerRef.current);
      await keepInAccount(rawRef.current);
    })();
  }, [life, stories.length, keepInAccount]);

  // 판 — DOM 을 직접 그리는 쪽
  useEffect(() => {
    const board = new LifeBoard(rootRef.current, {
      onPick: (id) => pick(id),
      onHistory: (id) => openWorldRef.current?.(id),
    });
    boardRef.current = board;
    return () => board.destroy();
  }, [pick]);
  useEffect(() => {
    if (life && context) boardRef.current?.show({ life, context, selected });
  }, [life, context]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    boardRef.current?.select(selected);
    setEditing(false);
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
  const openWorldRef = useRef(null);
  const loadGraph = useCallback((gv) => {
    // 한국사를 보는 중이면 캔버스에 실을 것은 그 그래프다 — 캔버스가 다시
    // 만들어졌을 때(StrictMode·테마) 내 그래프로 되돌아가 버리지 않게.
    if (worldIdRef.current) { openWorldRef.current?.(worldIdRef.current, { back: true }); return; }
    const cur = lifeRef.current;
    if (!gv || !cur) return;
    gv.setData(graphPayload(cur, selectedRef.current));
    if (selectedRef.current) { gv.select(selectedRef.current); gv.focusOn(selectedRef.current); }
  }, []);
  // 한국사에서 나오면 내 그래프가 그 자리에 다시 선다 (world → null).
  useEffect(() => {
    if (world) return;
    loadGraph(viewRef.current);
    boardRef.current?.select(selectedRef.current);
  }, [world, life, loadGraph]);
  // 연표에서 고르든 그래프에서 고르든 같은 노드다 — 그래프의 조명도 따라간다.
  useEffect(() => {
    const gv = viewRef.current;
    if (worldIdRef.current || !gv || !selected || !gv.byId.has(selected)) return;
    gv.select(selected);
    gv.focusOn(selected);
  }, [selected]);

  // 한국사 노드 하나를 캔버스와 오른쪽에 세운다. 그래프와 상세를 같이 묻는다 —
  // 둘 중 하나만 오면 화면이 반쪽이 된다.
  //
  // `nest` 를 준 걸음만 자취에 쌓인다 (한국사 화면의 규칙과 같다): 상세의 관계
  // 목록에서 고른 것은 지금 노드가 데리고 있는 것이라 그 밑으로 들어가고,
  // 연표·캔버스에서 고른 것은 새로 시작한 걸음이다.
  const openWorld = useCallback(async (id, { back = false, nest = false, merge = false } = {}) => {
    if (!id) return;
    worldIdRef.current = id;
    setEditing(false);
    setDetailOpen(true);
    if (!back) {
      const cur = worldAtRef.current;
      if (!nest) setWorldTrail([]);
      else if (cur && cur.id !== id) setWorldTrail((t) => [...t, cur].slice(-50));
    }
    const [data, node] = await Promise.all([
      api.graph(id, settingsRef.current).catch(() => null),
      api.node(id).catch(() => null),
    ]);
    if (worldIdRef.current !== id) return;   // 그새 다른 것을 골랐다 — 늦게 온 답은 버린다
    if (!node || node.error) {
      leaveWorld();
      toast('그 사건의 한국사 자료를 불러오지 못했습니다');
      return;
    }
    worldAtRef.current = { id, label: node.label };
    setWorld(node);
    boardRef.current?.select(id);   // 연표에서도 그 줄이 켜져 있어야 한다
    const gv = viewRef.current;
    if (gv && data && data.nodes?.length) {
      gv.setData(data, { merge });
      gv.select(id);
      gv.focusOn(id);
      setWorldNote(
        <>
          {node.label} 주변 · 노드 {data.nodes.length} · 관계 {data.edges.length}
          {data.truncated && <> · <b>중심에 가까운 것만 표시</b></>}
        </>,
      );
    } else {
      setWorldNote(<>{node.label} 주변에 그릴 관계가 없습니다</>);
    }
  }, [leaveWorld, toast]);
  openWorldRef.current = openWorld;
  // 한국사 상세에서 '←' — 타고 들어온 자리로 되짚어 올라간다.
  const backWorld = useCallback(() => {
    const prev = worldTrail[worldTrail.length - 1];
    if (!prev) return;
    setWorldTrail((t) => t.slice(0, -1));
    openWorld(prev.id, { back: true });
  }, [worldTrail, openWorld]);
  // 한국사 그래프의 범례·시작점은 한 번만 묻는다 (내 그래프의 것과 다른 자료다).
  useEffect(() => {
    if (!world || worldSide) return;
    let alive = true;
    (async () => {
      const m = await api.meta().catch(() => null);
      const seeds = await api.seeds(12).catch(() => []);
      if (alive && m) setWorldSide({ ...m, seeds });
    })();
    return () => { alive = false; };
  }, [world, worldSide]);

  const forget = () => {
    forgetLife();          // 문서·이야기 기록·못 보낸 글·주인 표까지 한 번에
    setLife(null); setContext(null); setSelected(null); setStories([]); setFailed('');
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
    await keepInAccount(next);
  }, [adopt, toast, keepInAccount]);   // eslint-disable-line react-hooks/exhaustive-deps

  // --- 노드 하나를 고친다 --------------------------------------------------
  // 상세의 '편집' → 폼의 '완료' (2026-09-09 사용자: "완료 버튼 누르면 그래프와
  // 연표에 바로 반영해주고"). 지우기와 같은 길이다 — **날것의 문서**를 고쳐
  // (life.editNode) 다시 받아들이면(adopt) 화면·연표·그래프가 그 자리에서 다시
  // 서고, 브라우저와 계정에도 같이 남는다.
  //
  // **못 세운 관계는 세어서 말한다.** 노드 타입을 바꾸면 그 노드에 놓여 있던
  // 관계가 온톨로지에 어긋나 다듬기에서 빠질 수 있다 (tidyEdges) — 아무 말 없이
  // 사라지면 '완료를 눌렀는데 안 됐다'로 보인다.
  const saveNode = useCallback(async (patch) => {
    const raw = rawRef.current;
    const id = selectedRef.current;
    if (!id || !raw) return;
    const next = editNode(raw, id, patch);
    setEditing(false);
    let lost = 0;
    try {
      const drawn = normalize(next).edges.filter((e) => e.source === id || e.target === id).length;
      lost = Math.max(0, (patch.edges || []).length - drawn);
    } catch { /* 세지 못해도 고친 것은 들어간다 */ }
    if (!(await adopt(next, 'local'))) { toast('고친 것을 받아들이지 못했습니다'); return; }
    toast(lost ? `고쳤습니다 · 관계 ${lost}건은 두 끝에 맞지 않아 서지 못했습니다` : '고쳤습니다');
    await keepInAccount(next);
  }, [adopt, toast, keepInAccount]);

  // 이야기가 해를 적었는데 그 해에 아무것도 서 있지 않은 문장들. 지어내지 않고
  // **세어서 보여만 준다** — 사람이 눌러 다시 넣으면 모델이 그때 읽는다
  // (2026-09-11 물음: "년도를 정확하게 말했는데 왜 그래프에서 빠진거지?").
  const missing = useMemo(() => missingYears(life, stories), [life, stories]);

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
            <a className="era" href="/">한국사</a>
            <span className="era life-here">내 역사</span>
          </div>
        </header>
        <LoginModal
          next="/life.html"
          dismissible={false}
          title="내 역사는 로그인이 필요합니다"
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
          <a className="era" href="/">한국사</a>
          <span className="era life-here">내 역사</span>
        </div>
        <div className="life-tools">
          {/* 상자를 닫아도 분석은 계속 돈다 — 단추가 그것을 말한다. */}
          <button type="button" className="life-btn" aria-pressed={writing}
                  onClick={() => { if (writing) closeWriting(); else setWriting(true); setLogOpen(false); }}>
            {job?.state === 'running' ? `내 역사 읽는 중 · ${job.elapsed ?? 0}초` : '내 역사 입력하기'}
          </button>
          {/* 내가 적은 이야기 — 그래프의 원본이다. 아이콘 하나로 펴고 접는다
              (2026-09-08 사용자: "'내 역사 입력하기' 오른쪽에 아이콘 하나 만들어서
              누르면 사용자가 입력한 사용자의 역사 히스토리를 보여줘").
              **입력 상자는 건드리지 않는다** — 모달을 덮는 것은 상자를 닫는 것이
              아니다. 닫아 버리면 적다 만 글이 걷혀(closeWriting) 옛 글을 골라 와도
              쓰던 것이 사라진다 (2026-09-08 "쓰던 것을 삼키지 않는다"). */}
          {life && (
            <button type="button" className="clickable-icon life-log-btn" aria-pressed={logOpen}
                    onClick={() => setLogOpen((v) => !v)} aria-label="내가 적은 이야기"
                    title="내가 적은 이야기 — 잘못 적은 것을 고칩니다">
              <StoryLogIcon />
            </button>
          )}
          {/* 계정에 두는 단추는 없다 — 저절로 올라간다 (위 keepInAccount 머리글). */}
        </div>
        {/* 머리 줄 오른쪽 끝 — 검색이 안쪽, 화면 밝기가 바깥쪽이다. 한국사
            장은 검색이 가운데지만 여기 가운데 칸은 '내 역사 입력하기'가 쓴다.
            노드가 있을 때만 선다 — 빈 화면에서는 찾을 것이 없다. */}
        <div className="top-right">
          {life && <LifeSearch nodes={life.nodes} onPick={pick} />}
          <ThemeToggle onChange={() => boardRef.current?.layout()} />
        </div>
      </header>
      {kept && <div className="life-toast" role="status" aria-live="polite">{kept}</div>}

      {writing && <StoryBox key={draftStamp} job={job} local={local} blocking={blocking} onSubmit={onStory}
                            sent={sent} failed={failed} onRestore={restoreFailed}
                            draft={draftRef.current} onDraft={(v) => { draftRef.current = v; }}
                            onClose={closeWriting} />}
      {logOpen && <StoryLog stories={stories} running={job?.state === 'running'}
                            missing={missing}
                            onPick={pickStory} onDrop={dropStory}
                            onClose={() => setLogOpen(false)} />}

      <div className="layout life-layout">
        {/* 연표 판은 늘 붙어 있다(LifeBoard 가 DOM 을 쥔다). 자료가 없으면 빈
            안내가 이 자리를 다 쓰고, 있으면 세 열 너비로 왼쪽에 선다 — 단 화면의
            45% 까지다. 1440px 에서 864px 를 다 주면 그래프 폭이 0 이 된다 (실측).
            좁으면 연표 안에서 가로로 훑는다. */}
        <section className="life-board" ref={rootRef}
                 style={life ? { width: `min(${boardWidth()}px, 45vw)` } : undefined}>
          <div className="life-head" />
          {/* **이 두 칸에는 React 가 자식을 두지 않는다.** `LifeBoard` 가
              `.life-head`·`.life-body` 를 `innerHTML` 로 통째로 다시 쓴다 —
              React 가 그린 것을 같이 지우고, 그 뒤 React 가 자기 것을 거두려다
              `removeChild` 로 터진다 (화면이 통째로 하얘진다). 그래서 사람이
              읽는 안내는 **판 위에 얹는다**. */}
          <div className="life-body" />
          {(booting || !life) && (
            <div className="life-over">
              {booting ? (
                <div className="life-booting" role="status" aria-live="polite">
                  <span className="life-spinner" aria-hidden="true" />
                  <p>내 역사를 불러오는 중입니다…</p>
                </div>
              ) : (
                <Empty offline={offline} onWrite={() => setWriting(true)} />
              )}
            </div>
          )}
        </section>
        {life && (
          <div className="stage-wrap">
            {/* 한 캔버스가 둘을 그린다 — 내 관계망이거나, 고른 한국사 사건의
                주변 관계이거나. 안내 줄이 지금 무엇을 보고 있는지 말하고, 그
                줄에서 내 역사로 돌아온다. */}
            <GraphCanvas
              viewRef={viewRef}
              settings={settings}
              note={world
                ? <>{worldNote} · <button type="button" className="stage-back" onClick={leaveWorld}>내 역사로 돌아가기</button></>
                : <>{name}의 관계망 · 노드 {life.nodes.length} · 관계 {life.edges.length}</>}
              empty={false}
              offline={false}
              onSelect={(node) => (worldIdRef.current ? openWorld(node.id) : pick(node.id))}
              onExpand={(node) => (worldIdRef.current ? openWorld(node.id, { merge: true }) : pick(node.id))}
              onReady={loadGraph}
            />
            {/* 범례와 시작점도 지금 캔버스에 선 그래프의 것이어야 한다 — 한국사를
                보는데 내 그래프의 타입 수가 적혀 있으면 그 수는 거짓말이다. */}
            <SidePanel
              open={sideOpen}
              onToggle={() => setSideOpen((v) => !v)}
              meta={world ? worldSide : meta}
              seeds={world ? (worldSide?.seeds || []) : meta.seeds}
              settings={settings}
              onSettings={(patch) => {
                setSettings((prev) => {
                  const next = { ...prev, ...patch };
                  settingsRef.current = next;
                  return next;
                });
                // 펼침 깊이·최대 노드는 서버에 다시 물어야 바뀐다 (한국사 그래프).
                if (worldIdRef.current && ('depth' in patch || 'limit' in patch || 'includePeriod' in patch)) {
                  openWorld(worldIdRef.current, { back: true });
                }
              }}
              onPick={(id) => (worldIdRef.current ? openWorld(id) : pick(id))}
              lines={world ? undefined : LIFE_LINES}
              whole={!world}
            />
          </div>
        )}
        {/* 한국사 사건을 고르면 그 자리에 **한국사 상세**가 선다 — 같은 노드를
            두 화면에서 다르게 적지 않으려고 한국사 장의 부품을 그대로 부른다
            (설명·출처 한 줄·인과 사슬·관계). 닫으면 내 사건 상세로 돌아온다. */}
        {life && world && (
          <DetailPanel
            node={world}
            prev={worldTrail[worldTrail.length - 1] || null}
            onClose={leaveWorld}
            onBack={backWorld}
            onVisit={(id, opts) => openWorld(id, opts)}
          />
        )}
        {/* 접혀도 DOM 에서 빼지 않는다 — 빼면 미끄러질 것이 없어 그냥 사라진다.
            대신 화면 밖에 있는 동안은 탭에 걸리지 않게 inert 로 재운다. */}
        {life && !world && (
          <aside className={`detail life-detail${detailOpen ? '' : ' is-folded'}`}
                 inert={!detailOpen} aria-hidden={!detailOpen}>
            <div className="life-tabs">
              <button type="button" className={tab === 'event' ? 'on' : ''} onClick={() => setTab('event')}>사건</button>
              <button type="button" className={tab === 'analysis' ? 'on' : ''} onClick={() => setTab('analysis')}>분석</button>
              <button type="button" className={tab === 'people' ? 'on' : ''} onClick={() => setTab('people')}>사람 · 문화</button>
              {/* 탭 줄 끝의 접기 — 화살표가 어느 쪽으로 들어가는지 말하고, 글은
                  aria·title 로만 둔다 (탭 세 칸의 너비를 뺏지 않는다). */}
              <button type="button" className="clickable-icon life-detail-fold" onClick={() => setDetailOpen(false)}
                      aria-label="상세 접기" title="상세 접기 — 오른쪽으로 밀어 넣습니다">
                <ChevronIcon to="right" />
              </button>
            </div>
            {tab === 'event' && (editing && selected && life.nodes.some((n) => n.id === selected)
              ? <EventEdit key={selected} life={life} id={selected} onDone={saveNode} onCancel={() => setEditing(false)} />
              : <EventDetail life={life} id={selected} onPick={pick} onHistory={openWorld}
                             onDrop={dropNode} onEdit={() => setEditing(true)} />)}
            {tab === 'analysis' && <Analysis life={life} onPick={(id) => pick(id)} />}
            {tab === 'people' && <Things life={life} />}
          </aside>
        )}
        {/* 접은 뒤에도 되돌아갈 손잡이가 오른쪽 가장자리에 남는다 — 접고 나서 펼
            길이 없으면 안 된다. 화살표만 두지 않고 '상세'라고 적는다 (부호 하나로만
            말하지 않는다). */}
        {life && !world && !detailOpen && (
          <button type="button" className="life-detail-peek" onClick={() => setDetailOpen(true)}
                  aria-label="상세 펼치기" title="상세 펼치기">
            <ChevronIcon to="left" />
            <span>상세</span>
          </button>
        )}
      </div>

      <footer className="foot">
        <span className="foot-copy">{COPYRIGHT}</span>
        <a href="/privacy.html">개인정보처리방침</a>
        <a href="/terms.html">이용약관</a>
      </footer>
    </>
  );
}

function Empty({ offline, onWrite }) {
  return (
    <div className="life-empty">
      <h2>내 삶을 세상의 역사와 나란히 봅니다</h2>
      <p><b>‘내 역사 입력하기’</b>를 눌러 당신의 역사를 기록하세요. 태어난 순간부터 가족, 학교, 일,
        소중한 만남, 그리고 기억에 남는 책·영화·음악·작품까지.</p>
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
// **새로 서는 상자는 늘 빈 칸이다** — 놓아 준 글(`draft`)이 있을 때만 그 글이 선다
// (기록에서 옮겨 온 것·못 보내 되돌린 것). 2026-09-10 사용자.
function StoryBox({ job, local, blocking, sent, failed, draft, onDraft, onRestore, onSubmit, onClose }) {
  const [text, setText] = useState(draft || '');
  const running = job?.state === 'running';
  // 칸을 비우는 것은 **보낼 때**다. 전에는 '분석이 끝났으면' 비웠는데, 그 효과가
  // **세워질 때마다** 돌았다 — 모달에서 예전 글을 눌러 옮기면 상자가 새로 서고
  // (key={draftStamp}) 그 자리에서 방금 옮긴 글이 지워졌다 (2026-09-08 사용자:
  // "입력을 클릭해도 입력창에 복사가 안 되는 경우가 있어"). 한 번 분석을 끝낸
  // 뒤에만 그랬으므로 '경우가 있어' 였다. 보낸 글은 못 보내면 화면이 되돌린다
  // (LifeView restoreDraft).
  const change = (v) => {
    setText(v);
    onDraft(v);   // 상자가 다시 서도 쓰던 글은 이어진다 (LifeView draftRef)
  };
  // 옮겨 온 글은 **끝에 커서를 두고** 보여 준다 — 긴 글이면 어디에 붙었는지
  // 안 보이면 옮겨진 줄 모른다.
  // 보기글은 **세울 때 한 번** 뽑는다. 글자마다 다시 뽑으면 안 적힌 칸의
  // 보기글이 눈앞에서 바뀐다.
  const [example] = useState(anExample);
  const areaRef = useRef(null);
  useEffect(() => {
    const el = areaRef.current;
    if (!el || el.disabled) return;
    el.focus();
    el.selectionStart = el.selectionEnd = el.value.length;
    el.scrollTop = el.scrollHeight;
  }, []);
  // 누르는 순간 칸을 비운다 (2026-09-09 사용자: "'입력' 버튼을 누르면 해당 내용은
  // 입력창에서 삭제 해줘"). 못 보낸 글은 화면이 들고 있다가 아래 '되돌리기' 로
  // 내어 주므로, 비워도 잃지 않는다.
  const send = () => {
    onSubmit(text, '나');
    setText('');
    onDraft('');
  };
  const done = job?.state === 'done';
  const pct = progressOf(job, local);
  const made = done && job.payload ? job.payload : null;
  // 무엇이 늘었는지 **이름으로** 적는다 — 수만 적으면 '적용이 됐나'를 화면에서
  // 확인할 수 없다 (2026-09-09 사용자).
  const madeNames = made && job.added ? addedNames(made, job.added.ids) : [];
  return (
    <div className="life-paste life-story">
      {/* 도는 동안은 **보낸 글**이 선다 (2026-09-09 사용자). 칸이 비어 보기글이
          서면, 몇 분을 기다리는 사람이 자기가 무엇을 보냈는지 못 본다. 그동안
          칸은 잠겨 있으므로 값만 갈아 끼우면 된다 — 고치는 것은 끝난 뒤다. */}
      <textarea ref={areaRef} value={running && sent ? sent : text} onChange={(e) => change(e.target.value)}
                disabled={running} placeholder={example} spellCheck={false} />
      {(running || done) && (
        <div className="life-progress-row" role="status" aria-live="polite">
          <div className="life-progress" aria-hidden="true"><i style={{ width: `${pct}%` }} /></div>
          <span className="tl-hint">
            {running
              ? `${job.step || '읽는 중'} · ${job.elapsed ?? 0}초 · ${pct}%`
              : job.added
                ? `있는 역사에 더했습니다 · ${madeNames.length
                    ? madeNames.join(' · ') + (job.added.nodes > madeNames.length ? ` 외 ${job.added.nodes - madeNames.length}` : '')
                    : `새 사건과 사람 ${job.added.nodes} · 새 관계 ${job.added.edges}`}${job.took != null ? ` · ${job.took}초 걸렸습니다` : ''}`
                : made
                  ? `다 만들었습니다 · 사건과 사람 ${made.nodes?.length ?? 0} · 관계 ${made.edges?.length ?? 0}${job.took != null ? ` · ${job.took}초 걸렸습니다` : ''}`
                  : '다 만들었습니다'}
          </span>
        </div>
      )}
      <div className="life-paste-row">
        {running ? (
          /* 로컬 서버는 띄워 두고 도므로 창을 닫아도 된다. 배포는 이 요청이
             모델을 붙들고 있어서 창을 닫으면 답이 오다 만다 — 그대로 적는다. */
          <span className="tl-hint">{blocking
            ? '이 창을 열어 둔 채로 기다려 주세요.'
            : '창을 닫아도 계속 돕니다.'}</span>
        ) : job?.state === 'error' ? (
          <span className="tl-hint life-warn">{job.error}</span>
        ) : (
          /* 밖의 모델일 때는 아무 말도 안 한다 (2026-09-08 사용자). 빈 칸은
             단추를 오른쪽에 붙여 두는 자리다. */
          <span className="tl-hint">{local ? '이 컴퓨터의 모델이 읽습니다. 글은 어디로도 보내지 않습니다.' : ''}</span>
        )}
        {/* 못 보낸 글이 있으면 그 글을 칸으로 부르는 단추. 있을 때만 선다. */}
        {failed && !running && (
          <button type="button" className="life-btn" onClick={onRestore}>적은 글 되돌리기</button>
        )}
        <button type="button" className="life-btn" onClick={onClose}>닫기</button>
        {/* 글이 한 자라도 있으면 누를 수 있다. 전에는 40자 미만이면 말없이 잠겨
            있어 "입력해도 버튼이 활성화가 안 돼"(2026-09-08) — 문턱은 두지 않는다. */}
        <button type="button" className="life-btn go" disabled={running || !text.trim()}
                onClick={send}>{running ? '읽는 중' : '입력'}</button>
      </div>
    </div>
  );
}

// --- 내가 적은 이야기 (모달) ----------------------------------------------
// 그래프는 사람이 적은 글에서 나온다. 그 글을 다시 볼 수 있어야 고칠 수 있다
// (2026-09-08 사용자: "잘못된 입력을 고칠 수 있게 해줘" — 실제로 원문에
// '잠실고딩학교 1학넌때'가 남아 있고 다시 적은 문단이 그 옆에 있었다).
//
// **머리 아래로 펴지는 상자가 아니라 모달이다** (같은 날: "히스토리 아이콘 누르면
// 히스토리 내역을 모달창으로 보여주고"). 여기서 하는 일은 둘뿐이다:
//
//  - **줄을 누르면 입력창으로 옮긴다** ("예전 입력을 클릭하면 우리 인생 입력창에
//    자동으로 복사해줘"). 거기서 고쳐 '입력' 하면 있는 그래프에 더해진다.
//  - **삭제는 그 줄을 기록에서 뺀다.** 그래프는 그대로다 — 남은 글로 처음부터
//    다시 짓던 '고쳐서 다시 읽기' 는 뺐다 (2026-09-08 사용자).
//
// 새로 적은 것이 맨 위다. 자리만 뒤집고 **글의 차례는 그대로 둔다** — 뒤에 적은
// 문단이 앞의 것을 고치는 말이라 이어 붙일 때 뒤집으면 뜻이 달라진다.
// 설명 문단은 두지 않는다 (2026-09-08 사용자: "이 문장을 삭제해줘") — 무엇을 하는
// 자리인지는 눌러 보면 알고, 단추의 title 로만 남긴다.
export function StoryLog({ stories, running, missing = [], onPick, onDrop, onClose }) {
  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onClose]);
  // 날을 아는 것이 하나도 없으면 그 칸을 세우지 않는다 — 빈 칸만 남기면 글이
  // 까닭 없이 오른쪽으로 밀린다. 하나라도 알면 줄을 맞추려고 다 세운다.
  const anyWhen = stories.some((r) => whenText(r.at));
  return (
    <div className="scrim" role="presentation"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className="life-log-box" role="dialog" aria-modal="true" aria-label="내가 적은 이야기">
        <h2>내가 적은 이야기</h2>
        {/* 이야기가 말했는데 연표에 없는 해. **지운 것이 아니라 안 읽힌 것이다**
            (life.js missingYears 머리글) — 누르면 그 문장이 입력창으로 가고,
            다시 넣으면 모델이 그때 읽는다. */}
        {missing.length > 0 && (
          <div className="life-log-miss">
            <p className="tl-hint">이야기가 말했는데 연표에 없는 해입니다. 누르면 그 문장이 입력창으로 갑니다.</p>
            <ul className="life-miss-list">
              {missing.map((m) => (
                <li key={m.year}>
                  <button type="button" className="life-miss-item" onClick={() => onPick?.(m.text)}
                          title="이 문장을 입력창으로 옮깁니다">
                    <span className="life-miss-year">{m.year}</span>
                    <span className="life-log-text">{m.text}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {stories.length === 0 && (
          <p className="tl-hint">아직 적은 이야기가 없습니다. ‘내 역사 입력하기’ 로 적으면 여기에 남습니다.</p>
        )}
        <ul className="life-log-list">
          {stories.map((r, i) => ({ r, i })).reverse().map(({ r, i }) => (
            <li key={i}>
              <button type="button" className="life-log-item" onClick={() => onPick?.(r.text)}
                      title="이 글을 입력창으로 옮깁니다">
                {anyWhen && <span className="life-log-when">{whenText(r.at)}</span>}
                <span className="life-log-text">{r.text}</span>
              </button>
              <button type="button" className="life-btn danger" disabled={running}
                      onClick={() => onDrop?.(i)}
                      title="이 글을 기록에서 지웁니다 (그래프는 그대로)">삭제</button>
            </li>
          ))}
        </ul>
        <div className="life-log-foot">
          <span className="tl-hint">{running ? '지금 읽는 중입니다. 끝나면 지울 수 있습니다.' : ''}</span>
          <button type="button" className="life-btn" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}

// 적은 날. 이 열이 생기기 전에 적은 것은 날을 모르는데, **모른다고 적지도
// 않는다** (2026-09-08 사용자: "'적은 날을 모릅니다' 문장을 삭제해"). 빈 칸을
// 그대로 두어 글 칸의 왼쪽 줄만 맞춘다.
function whenText(at) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(at || ''));
  return m ? `${m[1]}년 ${+m[2]}월 ${+m[3]}일` : '';
}

// lucide 의 chevron-left / chevron-right — 드로어가 어느 쪽으로 미끄러지는지.
function ChevronIcon({ to }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={to === 'left' ? 'm15 18-6-6 6-6' : 'm9 18 6-6-6-6'} />
    </svg>
  );
}

// lucide 의 scroll-text — 사람이 적은 글 뭉치.
function StoryLogIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 12h-5M15 8h-5M19 17V5a2 2 0 0 0-2-2H4" />
      <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" />
    </svg>
  );
}

// --- 사건 상세 ------------------------------------------------------------
function EventDetail({ life, id, onPick, onHistory, onDrop, onEdit }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  // 지우기 전에 한 번 묻는다 — 되돌리는 길이 없다. 브라우저가 띄우는 상자는
  // 단추 글자가 우리 것이 아니므로(화면에 영어) 패널 안에서 묻는다.
  const [ask, setAsk] = useState(false);
  useEffect(() => { setAsk(false); }, [id]);
  const node = id ? byId.get(id) : null;
  if (!node) {
    return <p className="life-hint">오른쪽 열의 사건을 누르면 여기에 원인·결과와 그 해의 한국사가 나옵니다.</p>;
  }
  // 인물의 연표 항목은 이야기가 그 사람의 날짜를 말했을 때만 읽는다 (lib/life.js dateSaid).
  const t = dateSaid(node) ? life.timeline.find((x) => x.event_id === id) : null;
  const ins = life.edges.filter((e) => e.target === id);
  const outs = life.edges.filter((e) => e.source === id);
  const causes = ins.filter((e) => CAUSAL_EDGES.has(e.type));
  const effects = outs.filter((e) => CAUSAL_EDGES.has(e.type));
  const others = [...ins.filter((e) => !CAUSAL_EDGES.has(e.type)), ...outs.filter((e) => !CAUSAL_EDGES.has(e.type))];
  const links = life.historical_connections.filter((c) => c.personal_event === id);
  const turning = life.turning_points.find((p) => p.event === id);
  const cf = life.counterfactual_analysis.filter((c) => c.event === id);
  // 날짜 줄도 같은 규칙이다 — 이야기가 말하지 않은 인물의 생년은 적지 않는다.
  // '세'는 만 나이다 (2026-09-08 사용자: "나이 앞에 '만'이라고 써줘").
  // **끝을 아는 일은 한 점이 아니라 기간이다.** 편집 칸이 '끝'을 받으므로 여기서
  // 안 그리면 고쳐도 화면이 그대로다 — '완료를 눌렀는데 안 바뀐다'로 보인다.
  // 날짜 글이 이미 기간을 말하고 있으면(물결) 덧붙이지 않는다.
  const from = t?.date_text || (dateSaid(node) ? node.start_date : null);
  // 끝이 시작과 같은 날이면 기간이 아니다 — 모델이 하루짜리 일에도 끝을 적어 둔다.
  const till = from && node.end_date && node.end_date !== node.start_date
    && dateSaid(node) && !String(from).includes('~') ? node.end_date : null;
  // 시절은 **이 일이 무엇이었나**를 먼저 적는다 (2026-09-10 사용자, 공익 시절에 만난
  // 사람의 상세가 '군복무'로 선 것을 보고: "오해하기 쉬운거야 타임라인은 그냥 군복무라고
  // 써도 되지만 노드엔 연애라고 표시해줘"). 연표의 띠는 그대로 그 시절(군복무)이다.
  const when = [till ? `${from} ~ ${till}` : from,
    t?.age != null ? `만 ${t.age}세` : null, t?.node_stage || t?.life_stage].filter(Boolean).join(' · ');
  // 이름을 모르는 아이디는 화면에 내지 않는다 (lib/life.js nodeLabel) — 모델의
  // 식별자가 그대로 서는 자리가 없어야 한다 (2026-09-08 지적).
  const nameOf = (nid) => nodeLabel(byId, nid);
  // '함께' 는 나 말고 이 일에 같이 있던 사람이다. 아이디로 적혀 오므로 이름으로 풀고,
  // 주인공과 못 푸는 식별자를 뺀다. 남는 사람이 없으면 **줄 자체를 세우지 않는다**
  // (2026-09-08 지적: "함께한 사람이 없으면 그냐야 '함께'라는 섹션 자체를 보여주면 안돼").
  //
  // **'관련'에 이미 선 사람은 여기 다시 적지 않는다** (2026-09-08 지적: "왜 함께가
  // 두 번 들어가지 한 번만 보여줘"). 함께한 사람은 사건에 이어지므로(experienced ·
  // 역할 '함께') 대개 아래 '관련'에 선다 — 그 줄이 눌러서 옮겨가는 자리이고 역할이
  // 머리글이다. 여기 남는 것은 **그래프에 노드가 없어 선을 못 그은 이름**뿐이다.
  const tied = new Set([...ins, ...outs].map((e) => (e.source === id ? e.target : e.source)));
  const withWhom = [...new Set(node.participants || [])]
    .filter((pid) => pid !== life.subject?.id && !tied.has(pid))
    .map((pid) => ({ id: byId.has(pid) ? pid : null, name: nameOf(pid) }))
    .filter((w) => w.name);
  return (
    <div className="life-event">
      <span className="d-type">{NODE_TYPE_KO[node.type]}</span>
      <h2 className="d-title">{node.name}</h2>
      <div className="d-dates">{when}{node.location ? ` · ${node.location}` : ''}</div>
      {node.description && <p className="life-desc">{node.description}</p>}
      <dl className="life-facts">
        {/* 중요도(importance_score)는 그리지 않는다 (2026-09-09 사용자 결정). 모델이
            '1 = 거의 영향 없음, 10 = 인생을 바꾼 사건' 두 줄만 보고 매긴 값이라 재는
            식이 없고, 짐작을 눈금으로 그리면 측정처럼 보인다. 수집은 그대로 두고
            화면에서만 뺀다. 연표 점의 크기도 같은 이유로 중요도를 말하지 않는다.
            **전환점 점수(turning_point_score)도 같은 날 내렸다** — 영향 순위에
            이어 사용자가 "'전환점' 점수 그래프도 삭제해". 전환점인지 아닌지는
            서 있는 것으로 말하고, 왜인지는 그 옆의 글이 말한다. */}
        {turning && <><dt>전환점</dt><dd>{turning.reason}</dd></>}
        {/* 감정(emotional_impact)은 그리지 않는다 (2026-09-09 사용자: "노드의 '감정'
            메뉴도 삭제해 필요 없어"). 모델이 사건마다 '불안'·'설렘' 한 낱말을
            붙여 온 것이라 이야기가 그렇게 말했다는 근거가 없고, 한 낱말로는
            읽는 사람에게 아무것도 더 말하지 않는다. 수집은 그대로 두고 화면에서만
            뺀다 — 중요도·영향 순위·전환점 점수를 내린 자리와 같다. */}
        {withWhom.length > 0 && <><dt>함께</dt><dd>{withWhom.map((w, i) => (
          <span key={`${w.id || ''}${w.name}`}>{i ? ', ' : ''}{w.id
            ? <button type="button" className="life-link" onClick={() => onPick(w.id)}>{w.name}</button>
            : w.name}</span>))}</dd></>}
        {/* 확신도 백분율(`확실함 … 90%`)도 그리지 않는다 (2026-09-09 사용자 결정).
            모델이 붙인 값이고 코드가 만드는 엣지는 죄다 0.8 상수라 90% 는 잰 값이
            아니라 적어 둔 값이다 — 짐작한 양을 눈금으로 그리지 않는다.
            다만 '본인이 말한 것인가, 미룬 것인가'는 확인되는 이진 사실이라
            관계 목록의 '미룬 것' 딱지와 그래프의 점선(LIFE_LINES)은 남는다. */}
      </dl>
      {causes.length > 0 && <Rel head="원인" items={causes} side="source" nameOf={nameOf} onPick={onPick} />}
      {effects.length > 0 && <Rel head="결과" items={effects} side="target" nameOf={nameOf} onPick={onPick} />}
      {links.length > 0 && (
        <section className="life-sec">
          <h3>그 무렵의 한국사</h3>
          <ul>
            {links.map((c, i) => (
              <li key={i}>
                {/* 한국사 사건은 연표에서와 같이 **이 화면에서** 펴진다
                    (2026-09-10 사용자). 링크는 남겨 cmd·ctrl 로 새 탭에 여는
                    길을 두되, 그냥 누르면 옮겨가지 않는다. */}
                <b>{c.node_id
                  ? <a href={`/#${encodeURIComponent(c.node_id)}`}
                       onClick={(ev) => {
                         if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
                         ev.preventDefault();
                         onHistory?.(c.node_id);
                       }}>{c.node_label || c.historical_event}</a>
                  : c.historical_event}</b>
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
          {/* 상대는 눌러서 옮겨가는 자리다 — 원인·결과(Rel)와 같은 단추다
              (2026-09-08 지적: "함께에 있는 사람이 node에 있으면 링크를 걸어 줘야지").
              그래프에 없는 것은 이름만 적는다. */}
          <ul>{others.map((e, i) => {
            const other = e.source === id ? e.target : e.source;
            return (
              <li key={i}><span className="tl-rel">{edgeLabel(e.type, byId.get(e.source)?.type, byId.get(e.target)?.type, e.role)}</span>{' '}
                {byId.has(other)
                  ? <button type="button" className="life-link" onClick={() => onPick(other)}>{nameOf(other)}</button>
                  : nameOf(other)}
                {e.description ? <p>{e.description}</p> : null}</li>
            );
          })}</ul>
        </section>
      )}
      {cf.length > 0 && <Counterfactual items={cf} />}
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
            <>
              <button type="button" className="life-btn danger" onClick={() => setAsk(true)}>삭제</button>
              {/* 고치는 길이 지우는 길 옆에 선다 (2026-09-09 사용자: "'삭제' 옆에
                  '편집'버튼을 만들어줘"). 틀린 것을 지우기 전에 고쳐 보게 한다. */}
              {onEdit && <button type="button" className="life-btn" onClick={() => onEdit(id)}>편집</button>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// --- 사건 고치기 ------------------------------------------------------------
// 상세에 선 것을 그 차례 그대로 칸으로 편다 (2026-09-09 사용자: "'삭제' 옆에
// '편집'버튼을 만들어줘 … 그 노드에 표시된 모든 정보를 사용자가 직접 편집 할
// 수있게 해줘(연도, 관계 등등). 완료 버튼 누르면 그래프와 연표에 바로 반영").
// 읽던 자리에서 고치므로 칸의 차례는 상세의 차례와 같다 — 이름·날짜·설명,
// 연표, 전환점, 함께, 그 무렵의 한국사, 만약 없었다면. 화면이 안 그리는
// 것은 칸으로도 두지 않는다 — 감정·1~10 점수가 그렇다.
//
// **관계는 여기서 고치지 않는다** (2026-09-09 사용자: "편집 메뉴에서 관계를
// 빼라고"). 관계는 이야기가 짓는 것이고, 화면에 선 선 가운데는 문서에 없는 것도
// 있다 — 섬 잇기·참여자 풀기·가족 호칭을 코드가 그때그때 긋는다. 그 선을 칸으로
// 내밀면 사람이 고른 것과 코드가 그은 것이 한 자리에서 섞인다. 노드가 틀렸으면
// '삭제'가, 이야기가 틀렸으면 그 글을 고쳐 다시 넣는 길이 있다.
//
// **모델의 영어 식별자는 여기서도 안 보인다** (CLAUDE.md §1). 타입·관계·영향은
// 한국어 이름으로 고르고, 상대 노드는 이름으로 고른다.
function EventEdit({ life, id, onDone, onCancel }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  const node = byId.get(id) || null;
  const item = life.timeline.find((x) => x.event_id === id) || null;
  const turn = life.turning_points.find((p) => p.event === id) || null;
  const [f, setF] = useState(() => {
    const n = node || {};
    // 관계로 이미 이어진 사람은 '함께'가 아니라 '관계'에서 고친다 (상세와 같은 규칙).
    const tied = new Set(life.edges.filter((e) => e.source === id || e.target === id)
      .map((e) => (e.source === id ? e.target : e.source)));
    return {
      type: n.type || 'PersonalEvent',
      name: n.name || '',
      start_date: n.start_date || '',
      end_date: n.end_date || '',
      location: n.location || '',
      description: n.description || '',
      date_text: item?.date_text || '',
      life_stage: item?.life_stage || '',
      turning: turn ? { score: turn.turning_point_score ?? 5, reason: turn.reason || '' } : null,
      participants: [...new Set(n.participants || [])],
      withWhom: [...new Set(n.participants || [])]
        .filter((p) => p !== life.subject?.id && !tied.has(p))
        .map((p) => ({ value: p, was: nodeLabel(byId, p), name: nodeLabel(byId, p) }))
        .filter((w) => w.was),
      links: life.historical_connections.filter((c) => c.personal_event === id).map((c) => ({ ...c })),
      cf: life.counterfactual_analysis.filter((c) => c.event === id)
        .map((c) => ({ ...c, possibilities: (c.possibilities || []).join('\n') })),
    };
  });
  const set = (patch) => setF((cur) => ({ ...cur, ...patch }));
  const setAt = (key, i, patch) => setF((cur) => ({ ...cur, [key]: cur[key].map((row, k) => (k === i ? { ...row, ...patch } : row)) }));
  const dropAt = (key, i) => setF((cur) => ({ ...cur, [key]: cur[key].filter((_, k) => k !== i) }));
  if (!node) return null;

  const submit = (ev) => {
    ev.preventDefault();
    onDone({
      type: f.type, name: f.name, start_date: f.start_date, end_date: f.end_date,
      location: f.location, description: f.description,
      // 날짜가 셋 다 비면 연표 항목을 내린다 — 해를 모르는 항목은 아무 자리도 못 잡는다.
      timeline: (f.date_text.trim() || f.life_stage || f.start_date.trim())
        ? { date_text: f.date_text, life_stage: f.life_stage || null } : null,
      turning: f.turning ? { turning_point_score: f.turning.score, reason: f.turning.reason } : null,
      participants: f.participants,
      with_whom: f.withWhom.map((w) => (w.name.trim() === w.was ? w.value : w.name.trim())).filter(Boolean),
      links: f.links,
      counterfactual: f.cf.map((c) => ({ ...c, possibilities: String(c.possibilities || '').split('\n') })),
    });
  };

  return (
    <form className="life-edit" onSubmit={submit}>
      <label className="life-field"><span>종류</span>
        <select value={f.type} onChange={(e) => set({ type: e.target.value })}>
          {Object.entries(NODE_TYPE_KO).map(([k, ko]) => <option key={k} value={k}>{ko}</option>)}
        </select>
      </label>
      <label className="life-field"><span>이름</span>
        <input value={f.name} onChange={(e) => set({ name: e.target.value })} required />
      </label>
      <label className="life-field"><span>시작</span>
        {/* 날짜를 고쳤는데 아래 '날짜 글'이 옛 날짜를 말하고 있으면 같이 비운다 —
            연표가 2003년 칸에 세우면서 '2002년 6월'이라 적으면 그 줄이 거짓말을
            한다. 사람이 손댄 날짜 글은 건드리지 않는다. */}
        <input value={f.start_date} placeholder="1998-04-24 · 1998-04 · 1998"
               onChange={(e) => set({ start_date: e.target.value,
                 ...(f.date_text === (item?.date_text || '') ? { date_text: '' } : {}) })} />
      </label>
      <label className="life-field"><span>끝</span>
        <input value={f.end_date} onChange={(e) => set({ end_date: e.target.value })} placeholder="비워 두면 없음" />
      </label>
      <label className="life-field"><span>장소</span>
        <input value={f.location} onChange={(e) => set({ location: e.target.value })} />
      </label>
      <label className="life-field"><span>설명</span>
        <textarea value={f.description} onChange={(e) => set({ description: e.target.value })} rows={4} />
      </label>

      {/* 연표 — **세울지 말지를 묻는 칸은 두지 않는다.** 연표는 해를 아는 사건을
          세우고(personalMarks) 그 규칙에 문턱을 놓지 않는다 (CLAUDE.md §1-3).
          여기서 고치는 것은 그 자리에 적히는 말(날짜 글·시절)이고, 내리는 길은
          날짜를 비우는 것이다 — 아래 한 줄이 그렇게 말한다.
          나이는 칸으로 두지 않는다 — 생년과 해에서 세는 값이라 손으로 적으면 둘이
          어긋난다 (2026-09-09 기준: 짐작한 값을 눈금으로 세우지 않는다). */}
      {(item || EVENT_TYPES.has(f.type)) && (
        <section className="life-sec">
          <h3>연표</h3>
          <label className="life-field"><span>날짜 글</span>
            <input value={f.date_text} onChange={(e) => set({ date_text: e.target.value })}
                   placeholder="1998년 봄 · 비우면 위 날짜를 씁니다" />
          </label>
          <label className="life-field"><span>시절</span>
            <select value={f.life_stage} onChange={(e) => set({ life_stage: e.target.value })}>
              <option value="">저절로</option>
              {LIFE_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <p className="tl-hint">연표는 해를 아는 사건을 세웁니다. 날짜와 날짜 글을 다 비우면 내려갑니다.</p>
        </section>
      )}

      <section className="life-sec">
        <h3>전환점</h3>
        {/* 1~10 점수는 칸으로도 두지 않는다 (2026-09-09 사용자 결정 셋: 중요도·영향
            순위·전환점 점수) — 화면이 안 그리는 값을 고치라고 내밀면 그 눈금이
            칸으로 되돌아온다. 적어 둔 값은 그대로 들고 있다가 도로 넣는다. */}
        {f.turning ? (
          <>
            <label className="life-field"><span>까닭</span>
              <input value={f.turning.reason} onChange={(e) => set({ turning: { ...f.turning, reason: e.target.value } })} />
            </label>
            <button type="button" className="life-btn" onClick={() => set({ turning: null })}>전환점에서 내리기</button>
          </>
        ) : (
          <button type="button" className="life-btn" onClick={() => set({ turning: { score: 7, reason: '' } })}>전환점으로 세우기</button>
        )}
      </section>

      <section className="life-sec">
        <h3>함께</h3>
        {f.withWhom.map((w, i) => (
          <div className="life-row" key={i}>
            <input value={w.name} onChange={(e) => setAt('withWhom', i, { name: e.target.value })} />
            <button type="button" className="life-btn danger" onClick={() => dropAt('withWhom', i)}>빼기</button>
          </div>
        ))}
        <button type="button" className="life-btn"
                onClick={() => setF((cur) => ({ ...cur, withWhom: [...cur.withWhom, { value: '', was: '', name: '' }] }))}>
          사람 더하기
        </button>
      </section>


      {f.links.length > 0 && (
        <section className="life-sec">
          <h3>그 무렵의 한국사</h3>
          {f.links.map((c, i) => (
            <div className="life-rel-edit" key={i}>
              <div className="life-row">
                <input value={c.node_label || c.historical_event || ''}
                       onChange={(e) => setAt('links', i, { historical_event: e.target.value, node_label: e.target.value })} />
                <select value={c.impact_type} onChange={(e) => setAt('links', i, { impact_type: e.target.value })}>
                  {Object.entries(IMPACT_KO).map(([k, ko]) => <option key={k} value={k}>{ko}</option>)}
                </select>
                <input className="life-year" value={c.year ?? ''} onChange={(e) => setAt('links', i, { year: e.target.value })} placeholder="해" />
                <button type="button" className="life-btn danger" onClick={() => dropAt('links', i)}>빼기</button>
              </div>
              <textarea value={c.description || ''} onChange={(e) => setAt('links', i, { description: e.target.value })} rows={2} />
            </div>
          ))}
        </section>
      )}

      {f.cf.length > 0 && (
        <section className="life-sec">
          <h3>만약 없었다면</h3>
          {f.cf.map((c, i) => (
            <div className="life-rel-edit" key={i}>
              <div className="life-row">
                <input value={c.question || ''} onChange={(e) => setAt('cf', i, { question: e.target.value })} placeholder="물음" />
                <button type="button" className="life-btn danger" onClick={() => dropAt('cf', i)}>빼기</button>
              </div>
              <textarea value={c.answer || ''} onChange={(e) => setAt('cf', i, { answer: e.target.value })} rows={3} placeholder="답" />
              <textarea value={c.possibilities} onChange={(e) => setAt('cf', i, { possibilities: e.target.value })}
                        rows={2} placeholder="갈렸을 길 — 한 줄에 하나" />
            </div>
          ))}
        </section>
      )}

      {/* 단추는 아래에 붙어 따라온다 — 칸이 길어 스크롤 끝까지 내려가야 고친 것을
          거둘 수 있으면 안 된다. */}
      <div className="life-edit-foot">
        <button type="submit" className="life-btn go">완료</button>
        <button type="button" className="life-btn" onClick={onCancel}>취소</button>
      </div>
    </form>
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

// --- 만약 없었다면 ---------------------------------------------------------
// 물음을 누르면 답이 펴진다 (2026-09-09 사용자: "질문만 있고 답변이 없어.
// 질문을 클릭하면 답을 볼수 있게"). 전에는 물음 아래에 갈렸을 길만 서 있었는데
// ('한국에서 대학을 계속 다녔을 가능성') 그것은 구절이라 **답으로 읽히지
// 않는다** — 같은 크기의 줄이 넷 서 있으면 물음도 목록의 한 줄로 보인다.
//
// 그래서 두 켜로 나눈다. 문단(`answer`)이 그 물음에 대한 답이고, 그 아래
// 짧은 구절(`possibilities`)이 갈렸을 길이다. **접어 둔 채로 연다** — 물음이
// 여럿이라 다 펴 두면 목록이 아니라 글이 되고, 읽는 사람은 어떤 물음이
// 있는지부터 훑는다.
//
// 답이 없는 옛 문서(지시문이 `answer` 를 요구하기 전에 만든 것)는 구절만
// 펴고, 답이 아직 없다고 한국어로 적는다 — 빈 자리를 지어내지 않는다.
export function Counterfactual({ items }) {
  const [open, setOpen] = useState(() => new Set());
  const toggle = (i) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(i)) next.delete(i); else next.add(i);
    return next;
  });
  return (
    <section className="life-sec">
      <h3>만약 없었다면</h3>
      {items.map((c, i) => {
        const on = open.has(i);
        const ways = c.possibilities || [];
        return (
          <div className={`life-cf${on ? ' on' : ''}`} key={i}>
            <button type="button" aria-expanded={on} onClick={() => toggle(i)}>
              <span className="life-cf-caret" aria-hidden="true">▸</span>
              <span>{c.question}</span>
            </button>
            {on && (
              <div className="life-cf-a">
                {c.answer
                  ? <p>{c.answer}</p>
                  : <p className="life-hint">이 물음에는 아직 답이 적히지 않았습니다. 갈렸을 길만 아래에 있습니다.</p>}
                {ways.length > 0 && <ul className="life-sub">{ways.map((p, j) => <li key={j}>{p}</li>)}</ul>}
              </div>
            )}
          </div>
        );
      })}
      <p className="tl-hint">가능성일 뿐 단정이 아닙니다.</p>
    </section>
  );
}

// --- 분석 -----------------------------------------------------------------
function Analysis({ life, onPick }) {
  const byId = useMemo(() => new Map(life.nodes.map((n) => [n.id, n])), [life]);
  // 그래프에 없는 것을 모델이 아이디로 부르기도 한다 — 이름으로 못 풀면 그 줄을
  // 세우지 않는다 (nodeLabel). 화면에 `person_1` 이 서는 자리를 없앤다.
  const nameOf = (nid) => nodeLabel(byId, nid);
  const fam = life.family_analysis || {};
  const isEvent = (nid) => byId.has(nid);
  // 그래프에 있는 것은 어디서든 눌러서 옮겨간다 (2026-09-08 지적: "node에 있으면
  // 링크를 걸어 줘야지"). 없는 것은 이름만 적는다.
  const Link = ({ id }) => (isEvent(id)
    ? <button type="button" className="life-link" onClick={() => onPick(id)}>{nameOf(id)}</button>
    : <b>{nameOf(id)}</b>);
  return (
    <div className="life-analysis">
      <section className="life-sec">
        <h3>어떤 흐름에서 태어났나</h3>
        {fam.origin && <p>{fam.origin}</p>}
        {fam.historical_flow && <p>{fam.historical_flow}</p>}
        {fam.members?.length > 0 && <ul>{fam.members.map((m, i) => <li key={i}><b>{m.relation}</b> <Link id={m.node_id} /> — {m.description}</li>)}</ul>}
        {fam.values && <p className="life-q">{fam.values}</p>}
      </section>
      {/* 전환점 점수(turning_point_score)의 눈금도 세우지 않는다 (2026-09-09 사용자:
          "'전환점' 점수 그래프도 삭제해" — 중요도·영향 순위에 이어 셋째다). 같은
          1~10 모델 점수라 재는 식이 없는데 막대는 잰 값처럼 읽힌다. **차례는 남긴다**
          — 영향 순위와 같은 자리다. 값은 수집에 그대로 둔다. */}
      {life.turning_points.length > 0 && (
        <section className="life-sec">
          <h3>전환점</h3>
          <ul>{[...life.turning_points].sort((a, b) => b.turning_point_score - a.turning_point_score).map((p, i) => (
            <li key={i}>
              <Link id={p.event} /><p>{p.reason}</p>
            </li>
          ))}</ul>
        </section>
      )}
      {life.impact_analysis.length > 0 && (
        <section className="life-sec">
          <h3>역사가 준 영향</h3>
          <ul>{[...life.impact_analysis].sort((a, b) => b.strength - a.strength).map((p, i) => (
            <li key={i}><Link id={p.event} /> <span className="tl-rel">{IMPACT_KO[p.impact_type]}</span> <Meter v={p.strength} /><p>{p.description}</p></li>
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
          {/* 영향 점수(influence_score)의 눈금은 세우지 않는다 (2026-09-09 사용자:
              "'가장 크게 영향을 준 것' 메뉴에서 점수 그래프를 삭제해"). 중요도와 같은
              1~10 모델 점수라 재는 식이 없고, 막대는 잰 값처럼 읽힌다
              (graph-drawer §12.19). 다만 **차례는 남긴다** — 이 묶음이 말하는 것이
              순위 자체이고, 차례는 화면에 세우는 수가 아니다. 값은 수집에 그대로 둔다. */}
          <ul>{[...life.influence_ranking.items].sort((a, b) => b.influence_score - a.influence_score).map((p, i) => (
            <li key={i}><span className="tl-rel">{p.category} </span>
              <Link id={p.node} /><p>{p.reason}</p></li>
          ))}</ul>
        </section>
      )}
      {life.counterfactual_analysis.length > 0 && <Counterfactual items={life.counterfactual_analysis} />}
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
              {nodeYears(n) && <span className="tl-rel"> {nodeYears(n)}</span>}
              {n.description && <p>{n.description}</p>}
              {n.influence && <p className="life-q">{n.influence}</p>}
            </li>
          ))}</ul>
        </section>
      ))}
    </div>
  );
}
