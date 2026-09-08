// 개인 역사 — 한 사람의 삶을 왕·대통령의 띠와 역사 연표 옆에 세운다.
//
// 세 열이 **자 하나**를 쓴다 (buildScale). 왼쪽은 왕·대통령의 재위 띠
// (시대 연표와 같은 reignBand), 가운데는 그 무렵 한국사의 큰 사건, 오른쪽은
// 이 사람의 사건이다. 같은 해는 세 열에서 같은 높이다 — 그래야 "IMF 때
// 아버지 인쇄소가 부도났다"가 선 하나로 읽힌다. 몰린 해는 시대 연표처럼
// 그 해를 늘린다. 어느 열이 더 몰렸든 그 열이 필요한 만큼 늘리고, 나머지
// 열은 같은 자를 따라간다.
//
// **모델의 영어 식별자는 화면에 내지 않는다** (CLAUDE.md §1). 타입·관계·
// 영향의 이름은 아래 표로 옮기고, 표에 없는 것은 테스트가 잡는다
// (life.test.mjs 가 지시문을 읽어 대조한다). 파이썬 `life.py` 와 같은 표다.
//
// DOM 없이 도는 부분(normalize · lifeLayout · renderLife 의 문자열)과
// 브라우저에 붙는 부분(LifeBoard)을 가른다 — 배치가 어긋나는지는 브라우저
// 없이 재야 한다.

import { buildScale, placeMarks, reignBand, causeWire, yearCells, CAUSE_WIRE, REIGN_COLOR } from './timeline.js';

export const NODE_TYPE_KO = {
  Person: '인물', FamilyMember: '가족', Ancestor: '조상', Relationship: '관계',
  Time: '때', LifeStage: '인생 단계', Period: '시기',
  PersonalEvent: '개인 사건', HistoricalEvent: '역사 사건', TurningPoint: '전환점',
  Crisis: '위기', Achievement: '성취', Failure: '실패', Decision: '결정',
  Location: '장소', BirthPlace: '출생지', Residence: '거주지', TravelLocation: '여행지',
  School: '학교', University: '대학', Company: '회사', Organization: '단체', Community: '공동체',
  Occupation: '직업', Project: '프로젝트', Business: '사업', Investment: '투자',
  Hobby: '취미', Skill: '기술',
  Book: '책', Movie: '영화', Music: '음악', Religion: '종교', Culture: '문화',
  Technology: '기술 환경', Comic: '만화', Game: '게임', Memory: '기억',
};
export const EDGE_TYPE_KO = {
  parent_of: '부모', child_of: '자녀', grandparent_of: '조부모', ancestor_of: '조상', relative_of: '친척',
  influenced: '영향을 줌', inspired: '영감을 줌', helped: '도움', mentored_by: '스승',
  worked_with: '함께 일함', met: '만남',
  // 아래 셋은 지시문에 없고 다듬기(tidyEdges · life.py tidy_edges)가 세운다 — 친구는
  // '만남'이 아니고, 주인공과 자기 사건은 '뒤'·'동안'이 아니다 (2026-09-08 사용자 지적).
  friend_of: '친구', experienced: '당사자', schoolmate: '같은 학교', at: '곳',
  caused: '원인', triggered: '촉발', led_to: '이어짐', changed: '바꿈', affected: '영향', resulted_in: '결과',
  before: '다음', after: '이전', during: '동안', overlapped: '겹침',
  born_in: '출생지', lived_in: '거주', moved_to: '이주', visited: '방문', grew_up_in: '성장지',
  studied_at: '재학', worked_at: '근무', member_of: '소속',
  changed_by: '바뀜', inspired_by: '영감을 받음',
  read: '읽음', changed_belief: '생각을 바꿈', recommended_by: '추천받음', shared_with: '함께 나눔',
  listened_to: '들음', associated_with: '연관', reminds_of: '떠올림',
  watched: '봄', changed_view: '관점을 바꿈', connected_to_event: '사건과 연결',
  shaped_interest: '관심을 만듦', created_memory: '기억을 남김',
  played: '함', learned: '배움', built_skill: '기술을 익힘',
  used: '사용', enabled: '가능하게 함', changed_life: '삶을 바꿈',
  remembered_by: '기억됨', connected_to: '연결', triggered_by: '촉발됨',
  shaped: '형성', connected: '연결',
};
// 원인 → 결과로 읽는 관계. 개인 연표에서 오른쪽 여백의 꺾인 선이 된다.
export const CAUSAL_EDGES = new Set(['caused', 'triggered', 'led_to', 'resulted_in']);
export const IMPACT_KO = { direct: '직접', indirect: '간접', possible: '가능성' };
export const LIFE_STAGES = ['출생', '어린 시절', '초등학교', '중학교', '고등학교', '대학', '군복무',
  '사회생활', '창업', '가족 형성', '현재'];
// 군복무로 읽는 말 (life.py MILITARY 와 같다). 현역만이 아니다 — 공익근무요원·
// 사회복무요원·상근예비역·방위병·의무경찰도 병역이고, 훈련소 입소부터 소집해제까지가
// 그 기간이다 (2026-09-08 사용자: "공익근무는 군복무 기간이야. 훈련소, 공익근무 역시
// 군복무로 인식할 수 있게 해줘"). 모델이 '사회생활'로 적어 와도 이 표가 이긴다.
export const MILITARY = /군복무|군 복무|병역|입대|입영|훈련소|신병교육|\d+\s*사단|공익근무|공익요원|사회복무요원|상근예비역|방위병|의무경찰|의경대|카투사|해병대|현역|전역|소집해제|(?<![가-힣])제대(?!로)/;
// 그 단계를 **끝내는** 사건 — 띠를 여기서 닫는다. 없으면 띠는 다음 단계가 시작할
// 때까지 이어져 2년 복무가 4년으로 칠해진다.
export const STAGE_END = { 군복무: /전역|소집해제|(?<![가-힣])제대(?!로)|만기/ };
// 연표에 점으로 찍는 타입. 사람·장소·책은 이어지는 것이라 점이 아니다.
export const EVENT_TYPES = new Set(['PersonalEvent', 'HistoricalEvent', 'TurningPoint', 'Crisis',
  'Achievement', 'Failure', 'Decision', 'Memory']);
// 사람 갈래 (life.py PERSON_TYPES 와 같다).
export const PERSON_TYPES = new Set(['Person', 'FamilyMember', 'Ancestor', 'Relationship']);
// 삶의 사다리 (life.py `ladder` 머리글과 같다). 학제는 정해져 있다 — 층(초1·중2·고3·
// 대4·대학원5)과 그 안의 자리(들어감 0·다님 1·나옴 2)를 한 줄로 세운다: 초등 입학 10 ·
// 초등 졸업 12 · 중학 입학 20 … 대학 졸업 42. 달을 모르는 두 사건의 차례는 모델에게
// 물을 것이 아니다 (2026-09-08 사용자: "초등학교 졸업을 해야 중학교 입학을 하지").
const LADDER_WORDS = [['대학원', 5], ['석사', 5], ['박사', 5], ['대학교', 4], ['대학', 4],
  ['전문대', 4], ['고등학교', 3], ['고교', 3], ['중학교', 2], ['초등학교', 1], ['국민학교', 1]];
const LADDER_IN = /입학|진학|편입|복학|전학|들어갔|들어감/;
const LADDER_OUT = /졸업|수료|자퇴|중퇴|퇴학|마쳤|마침/;

function rung(text) {
  for (const [word, level] of LADDER_WORDS) {
    if (text.includes(word)) {
      return level * 10 + (LADDER_OUT.test(text) ? 2 : LADDER_IN.test(text) ? 0 : 1);
    }
  }
  return null;
}

// 이름이 먼저다 — 설명은 앞뒤를 같이 말하곤 해서('초등학교를 졸업하고 중학교에 입학함')
// 자리를 뒤집는다. 이름이 층을 말하지 않을 때만 설명을 본다.
export function ladder(node) {
  if (!node || !EVENT_TYPES.has(node.type)) return null;
  return rung(String(node.name || '')) ?? rung(String(node.description || ''));
}

// 해가 같은 칸끼리 사다리 순으로 다시 세운다. **사다리에 없는 항목은 제자리에 둔다** —
// 자리만 맞바꾼다 (life.py order_by_ladder 와 같다). 목록은 이미 해 순이다.
export function orderByLadder(items, nodeOf, yearOf) {
  const rank = items.map((it) => ladder(nodeOf(it)));
  for (let i = 0; i < items.length;) {
    let j = i;
    while (j < items.length && yearOf(items[j]) === yearOf(items[i])) j += 1;
    if (yearOf(items[i]) != null) {
      const spots = [];
      for (let k = i; k < j; k += 1) if (rank[k] != null) spots.push(k);
      if (spots.length > 1) {
        const sorted = spots.map((k) => [items[k], rank[k]])
          .sort((a, b) => a[1] - b[1]).map(([it]) => it);
        spots.forEach((k, n) => { items[k] = sorted[n]; });
      }
    }
    i = j;
  }
  return items;
}

// 이름 옆에 세우는 해. **인물은 이야기가 말한 날짜가 있을 때만 세운다**
// (2026-09-08 사용자: "인물들의 출생연도 나이는 사용자가 입력하지 않은 이상 추측해서
// 명시 하지마. 모르면 그냥 아예 명시를 하지마"). 사람 노드의 `year` 는 생년이 아니라
// **그 사람이 내 삶에 들어온 해**다 — refine 이 '고등학교 1학년 때 만난' 에서 센 것이라
// 이름 옆에 숫자로 적으면 읽는 사람은 생년으로 읽는다. 책·영화의 해는 그대로 세운다.
// 이야기가 이 사람의 날짜를 **말했는가**. 인물이 아니면 늘 참이다.
// 서버는 원문에 대 보고 근거 없는 날짜를 비운다(life.gate_person_dates). 원문이
// 없는 자리(계정에만 있는 옛 그래프·다른 컴퓨터)에서는 화면이 한 가지를 더 본다 —
// **미룬 날짜(confidence < 1)는 세우지 않는다.** 지시문이 "셈한 해는 confidence 를
// 0.7~0.9 로 낮춘다"고 하므로 그 값이 곧 '이야기가 말한 것이 아니다' 라는 표식이다.
export function dateSaid(n) {
  if (!PERSON_TYPES.has(n.type)) return true;
  return !!n.start_date && (n.confidence == null || n.confidence >= 1);
}
// 주인공의 생일 — '출생' 사건이 든 날짜가 주인공 노드의 날짜를 이긴다
// (life.py birth_date_from_nodes 와 같은 규칙). 모델은 해만 알면 1월 1일을 적어 두고
// 화면은 그것을 생일로 읽는다 (2026-09-08 사용자: "2월 27일에 태어 났다고 했는데,
// 왜 헷갈리게 '1982-01-01 · 0세 · 출생' 이라고 써있지"). 서버를 안 거친 옛 그래프도
// 여기서 고쳐진다.
const WHEN_TYPES = new Set(['Time', 'PersonalEvent', 'LifeStage']);
const BIRTH_NODE = /^(출생|탄생|태어남)$/;
const BIRTH_FULL = /(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일[^.。]{0,25}?(태어|출생)/;
const BIRTH_YEAR = /(\d{4})\s*년[^.。]{0,25}?(태어|출생)/;
export function birthDate(me, nodes, edges) {
  if (!me) return null;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const said = [];
  const take = (w) => { if (typeof w === 'string' && parseWhen(w).year != null) said.push(w.trim()); };
  for (const e of edges || []) {
    if (!e || e.source !== me.id) continue;
    const t = byId.get(e.target);
    if (!t || !WHEN_TYPES.has(t.type)) continue;
    // born_in 은 다듬기 전의 이름이고, 다듬은 뒤에는 experienced 에 역할이 '출생'이다.
    if (e.type === 'born_in' || BIRTH_NODE.test(String(e.role || '').trim())
        || BIRTH_NODE.test(String(t.name || '').trim())) take(t.start_date);
  }
  for (const n of nodes) {
    if (WHEN_TYPES.has(n.type) && BIRTH_NODE.test(String(n.name || '').trim())) take(n.start_date);
  }
  const desc = String(me.description || '');
  const full = BIRTH_FULL.exec(desc);
  if (full) take(`${full[1]}-${String(+full[2]).padStart(2, '0')}-${String(+full[3]).padStart(2, '0')}`);
  else { const y = BIRTH_YEAR.exec(desc); if (y) take(y[1]); }
  const year = parseWhen(me.start_date).year;
  const fit = said.filter((w) => year == null || parseWhen(w).year === year);
  return fit.length ? fit.reduce((a, b) => (b.length > a.length ? b : a)) : null;
}
export function nodeYears(n) {
  if (n.year == null || !dateSaid(n)) return '';
  return `${n.year}${n.end_year != null ? `~${n.end_year}` : ''}`;
}

// --- 온톨로지: 관계마다 출발·도착 갈래 (life.py LIFE_EDGES 와 같은 표) ----------------
// 한국사 그래프의 ontology.EDGE_TYPES 와 같은 꼴 — [일반 이름, 출발 갈래, 도착 갈래].
// 갈래는 캔버스의 여덟 색(GRAPH_TYPE)이다. 어긋난 엣지는 버리지 않고 RELAX 가 뜻이
// 남는 타입으로 옮긴다 (untangle.RELAX). 서버 없이 브라우저에 남은 옛 그래프도 여기서 고쳐진다.
const P = ['person']; const E = ['event']; const O = ['org']; const L = ['place']; const T = ['period']; const R = ['role'];
const W = ['artwork', 'media'];
const ANY = ['person', 'event', 'org', 'place', 'artwork', 'media', 'period', 'role'];
export const LIFE_EDGES = {
  parent_of: ['부모', P, P], child_of: ['자녀', P, P], grandparent_of: ['조부모', P, P], ancestor_of: ['조상', P, P], relative_of: ['친척', P, P],
  friend_of: ['친구', P, P], met: ['만남', P, P], worked_with: ['함께 일함', P, P], schoolmate: ['같은 학교', P, P],
  mentored_by: ['스승', P, P], helped: ['도움', P, P],
  influenced: ['영향을 줌', [...P, ...E, ...W, ...O], [...P, ...E]], inspired: ['영감을 줌', [...P, ...E, ...W, ...O], [...P, ...E]],
  // 사건 참여 — 한국사의 participated_in. 사람 → 사건이고 역할(role)이 선의 이름이다.
  experienced: ['당사자', P, [...E, ...T]],   // 도착에 period: 모델이 '출생'을 Time 으로 세운다
  caused: ['원인', [...E, ...P, ...O, ...W], E], triggered: ['촉발', [...E, ...P, ...O, ...W], E],
  led_to: ['이어짐', E, E], resulted_in: ['결과', E, E],
  changed: ['바꿈', [...E, ...W, ...P], [...P, ...E, ...R]], affected: ['영향', [...E, ...W, ...P], [...P, ...E, ...R]],
  before: ['다음', [...E, ...T], [...E, ...T]], after: ['이전', [...E, ...T], [...E, ...T]],
  during: ['동안', E, [...E, ...T]], overlapped: ['겹침', [...E, ...T], [...E, ...T]],
  // 사건이 일어난 곳 — 한국사의 occurred_at
  at: ['곳', [...E, ...T], [...O, ...L, ...R]],
  born_in: ['출생지', [...P, ...E, ...T], L], lived_in: ['거주', [...P, ...E], L], moved_to: ['이주', [...P, ...E], L],
  visited: ['방문', [...P, ...E], L], grew_up_in: ['성장지', P, L],
  studied_at: ['재학', P, [...O, ...R]], worked_at: ['근무', P, [...O, ...R]], member_of: ['소속', P, O],
  read: ['읽음', P, W], watched: ['봄', P, W], listened_to: ['들음', P, W], played: ['함', P, W], used: ['사용', P, W],
  learned: ['배움', P, [...W, ...R]], built_skill: ['기술을 익힘', [...P, ...W, ...E], R],
  recommended_by: ['추천받음', [...P, ...W], P], shared_with: ['함께 나눔', [...P, ...W], P],
  changed_belief: ['생각을 바꿈', [...W, ...E, ...P], P], changed_view: ['관점을 바꿈', [...W, ...E, ...P], P],
  changed_life: ['삶을 바꿈', [...W, ...E, ...P, ...O], P], changed_by: ['바뀜', [...P, ...E], [...W, ...E, ...P]],
  inspired_by: ['영감을 받음', [...P, ...E, ...W], [...W, ...P, ...E]],
  shaped_interest: ['관심을 만듦', [...W, ...E, ...P], [...P, ...R]], shaped: ['형성', [...W, ...E, ...P, ...O], [...P, ...R]],
  enabled: ['가능하게 함', [...W, ...E, ...P, ...O], [...E, ...P, ...O]],
  created_memory: ['기억을 남김', [...W, ...E, ...P, ...L], [...E, ...P]], remembered_by: ['기억됨', ANY, P],
  reminds_of: ['떠올림', [...W, ...L, ...E], ANY], associated_with: ['연관', ANY, ANY],
  connected_to_event: ['사건과 연결', ANY, E], triggered_by: ['촉발됨', E, [...E, ...P, ...W, ...O]],
  connected_to: ['연결', ANY, ANY], connected: ['연결', ANY, ANY],
};
export const MAX_TARGETS = { born_in: 1 };
// 화면에 세우지 않는 관계 — life.py SEQUENCE_ONLY 와 같은 표. `before`('다음')·`after`
// ('이전')는 사건 사이의 **차례**만 말하는데 그 차례는 연표가 이미 연도로 그린다
// (2026-09-08 사용자: "다음 이라는 메뉴는 뭐야? 별 정보값이 없는데 그냥 삭제해").
// 모델이 답하는 것은 막지 않는다 — 주인공 → 자기 사건을 after 로 답하기도 하고 그것은
// 참여라 뜻이 있다. 버리는 자리는 RELAX **뒤** 한 곳이라 계정·브라우저에 남은 옛
// 그래프도 새로고침으로 여기서 사라진다.
export const SEQUENCE_ONLY = new Set(['before', 'after']);
const TIME_EDGES = ['before', 'after', 'during', 'overlapped'];
export const RELAX = new Map([
  ...TIME_EDGES.map((t) => [`${t}|person|event`, 'experienced']),
  ...TIME_EDGES.map((t) => [`${t}|event|person`, 'experienced']),
  ['born_in|person|period', 'experienced'],
  ...['studied_at', 'worked_at', 'member_of', 'during', 'lived_in'].flatMap((t) => [[`${t}|event|org`, 'at'], [`${t}|event|role`, 'at']]),
  ...['studied_at', 'worked_at', 'member_of'].flatMap((t) => [[`${t}|period|org`, 'at'], [`${t}|period|role`, 'at']]),
]);
const RELAX_ROLE = { 'studied_at|role': '전공', 'worked_at|role': '직업', 'born_in|period': '출생' };
const SYMMETRIC = new Set(['met', 'friend_of', 'worked_with', 'schoolmate', 'relative_of', 'shared_with', 'overlapped']);
const FRIEND = /친구|벗|단짝|절친|죽마고우/;
const COLLEAGUE = /동료|같이 일|함께 일|같은 회사|같은 팀/;
// 사건 이름 꼬리의 술어 — 당사자가 그 사건에서 한 일 (한국사의 역할 머리말 '주도'·'지휘' 자리)
const DEED = /(입학|졸업|수료|자퇴|휴학|복학|편입|전학|유학|이주|이사|이민|귀국|출국|귀화|창업|개업|폐업|입사|퇴사|이직|취업|취직|승진|발령|전근|파견|은퇴|입소|입대|전역|제대|소집해제|결혼|이혼|약혼|출생|출산|사망|합격|낙방|수상|당선|낙선|출마|입원|수술|데뷔|입양|이별|재회|시작|종료)\s*$/;
const EVENT_KIND_ROLE = { TurningPoint: '전환점', Crisis: '위기', Achievement: '성취', Failure: '실패', Decision: '결정', Memory: '기억' };
export const klass = (n) => (n ? GRAPH_TYPE[n.type] : undefined);
export function deedOf(event) {
  const name = String(event.name || '').trim();
  const m = DEED.exec(name);
  if (m && m[1] !== '시작' && m[1] !== '종료') return m[1];
  if (m) {
    const head = name.slice(0, m.index).split(/\s+/).filter(Boolean);
    if (head.length) return `${head[head.length - 1]} ${m[1]}`;
  }
  return EVENT_KIND_ROLE[event.type] || null;
}
export function fits(kind, s, t) {
  const spec = LIFE_EDGES[kind];
  return !!spec && spec[1].includes(klass(s)) && spec[2].includes(klass(t));
}

// 모델이 고른 타입을 온톨로지와 증거로 고친다 — 서버의 life.py tidy_edges 와 같은 다섯 규칙.
//   1. 출발·도착이 표에 어긋나면 RELAX 로 옮긴다 (없으면 그대로 두고 issues 에 센다)
//   2. met 인데 설명이 '친구'라 하면 friend_of, '동료'면 worked_with
//   3. 미룬(확신 < 1) worked_with 인데 둘 다 일한 곳이 없고 같은 학교면 schoolmate
//   4. 사람 → 사건은 역할을 단다 — 당사자는 사건의 술어(입학·졸업), 남은 '함께'
//   5. 옮길 데 없이 차례만 남은 것(SEQUENCE_ONLY)은 버린다 — 연표가 이미 그린다
//   6. 대칭 관계의 역방향 중복은 하나만
// 주인공과 떨어져 뜬 섬을 잇는다 (life.py link_orphans 와 같은 규칙). 모델은 한 번에
// 준 이야기 안에서는 주인공 → 사건을 잇지만, 더하기로 뒤에 붙인 토막에서는 사건끼리만
// 이어 놓는다 (2026-09-08 사용자: "'나'와의 연결이 없이 떨어진 그래프들이 보이는데 왜
// 따로 떼어둔거지?"). 남의 사건(이미 인물과 이어진 것)과 세계사 사건은 그대로 둔다.
// 온톨로지를 씌운 뒤에 잰다 — 계정·브라우저에 남은 옛 그래프도 여기서 이어진다.
export function linkOrphans(nodes, edges, me) {
  if (!me) return 0;
  const who = new Set(nodes.filter((n) => PERSON_TYPES.has(n.type)).map((n) => n.id));
  const touched = new Set();
  for (const e of edges) { touched.add(e.source); touched.add(e.target); }
  let made = 0;
  for (const n of nodes) {
    if (klass(n) !== 'event' || n.type === 'HistoricalEvent') continue;
    if (edges.some((e) => (who.has(e.source) && e.target === n.id) || (who.has(e.target) && e.source === n.id))) continue;
    edges.push({ source: me.id, target: n.id, type: 'experienced', description: null, confidence: 0.8 });
    made += 1;
  }
  for (const spot of nodes) {
    const name = String(spot.name || '').trim();
    if (!['place', 'org'].includes(klass(spot)) || touched.has(spot.id) || name.length < 2) continue;
    const ev = nodes.find((n) => ['event', 'period'].includes(klass(n)) && n.id !== spot.id
      && `${n.name || ''} ${n.description || ''}`.includes(name));
    if (ev) { edges.push({ source: ev.id, target: spot.id, type: 'at', description: null, confidence: 0.8 }); made += 1; }
  }
  return made;
}

// --- 가족은 이야기가 호칭으로 말한다 (life.py link_people 과 같은 규칙) --------------
// 2026-09-08 사용자: "왜 엄마라고 분명히 말했고 엄마는 매우 중요한 사람인데 그래프에서
// 나와 엄마 사이에 엣지를 그리지 않았지?" 가족 호칭은 모델에게 다시 물을 것이 아니다 —
// 이야기가 한 문장(또는 바로 앞 문장까지)에서 호칭과 이름을 함께 부르면 코드가 잇는다.
// 호칭이 선의 이름(역할)이다. 방향은 LIFE_EDGES 대로: in = 그 사람 → 나 (부모 → 자녀),
// out = 나 → 그 사람, sym = 대칭(relative_of — 형제·배우자·친척은 호칭을 역할로 단다).
const KIN_TERMS = {};
for (const t of ['증조할머니', '증조할아버지', '고조할머니', '고조할아버지', '증조부', '증조모', '고조부', '고조모']) KIN_TERMS[t] = ['ancestor_of', 'in'];
for (const t of ['외할머니', '외할아버지', '친할머니', '친할아버지', '할머니', '할아버지', '조모', '조부']) KIN_TERMS[t] = ['grandparent_of', 'in'];
for (const t of ['어머니', '어머님', '엄마', '모친', '아버지', '아버님', '아빠', '부친', '새어머니', '새아버지', '양어머니', '양아버지', '계모', '계부']) KIN_TERMS[t] = ['parent_of', 'in'];
for (const t of ['큰아들', '작은아들', '큰딸', '작은딸', '아들', '딸', '자식', '자녀']) KIN_TERMS[t] = ['parent_of', 'out'];
for (const t of ['외손자', '외손녀', '손자', '손녀']) KIN_TERMS[t] = ['grandparent_of', 'out'];
for (const t of ['남동생', '여동생', '형님', '누님', '쌍둥이', '형', '누나', '언니', '오빠', '동생',
  '아내', '남편', '부인', '집사람', '신랑', '배우자',
  '외삼촌', '삼촌', '이모부', '고모부', '외숙모', '이모', '고모', '숙부', '숙모', '백부', '백모',
  '큰아버지', '작은아버지', '큰어머니', '작은어머니', '사촌', '조카',
  '장인', '장모', '시아버지', '시어머니', '며느리', '사위', '처남', '처형', '처제',
  '매형', '매제', '형수', '제수', '올케', '시누이', '동서']) KIN_TERMS[t] = ['relative_of', 'sym'];
const KIN_ALT = Object.keys(KIN_TERMS).sort((a, b) => b.length - a.length).join('|');
// 호칭은 낱말이어야 한다 — 앞에 한글이 붙으면 다른 낱말이다 ('나형철'의 '형'). '우리형'은 받는다.
const KIN_TAIL = '(?=[은는이가을를과와의도만께랑한로들야]|\\s|[,.!?)]|$)';
const KIN = new RegExp(`(?:(?<![가-힣])|(?<=우리|내|저희|울))(${KIN_ALT})${KIN_TAIL}`);
const FAMILY_EDGES = new Set(['parent_of', 'child_of', 'grandparent_of', 'ancestor_of', 'relative_of']);
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// 문장 속 가족 호칭 하나 — {term, kind, dir}. names 는 그 문장의 사람 이름이라 먼저 가린다.
export function kinIn(sentence, names = []) {
  let masked = String(sentence || '');
  for (const nm of names) masked = masked.split(nm).join('○'.repeat(nm.length));
  const m = KIN.exec(masked);
  if (!m) return null;
  const [kind, dir] = KIN_TERMS[m[1]];
  return { term: m[1], kind, dir };
}
// '김일권의 엄마'·'김일권 엄마' — 남의 가족이지 내 가족이 아니다.
const kinOfOther = (sentence, name) => new RegExp(`${escapeRe(name)}\\s*(?:의|네)?\\s*(?:${KIN_ALT})${KIN_TAIL}`).test(sentence);

// 주인공과 떨어진 **사람**을 잇는다. 사람 섬은 남기지 않는다:
//   1. 호칭과 이름을 함께 부른 사람 → 가족 관계 (확신 1, 호칭이 역할). 나와 직접 이어져
//      있지 않은 사람만 — 모델이 가족 관계로 이었는데 역할이 비면 호칭만 단다.
//   2. 그러고도 주인공에게 닿지 않는 사람은 이야기가 이름을 부르면 met(0.8) —
//      설명이 '친구'라 하면 tidyEdges 가 friend_of 로 옮긴다.
export function linkPeople(nodes, edges, me, text) {
  const story = String(text || '').trim();
  if (!me || !story) return 0;
  const people = nodes.filter((n) => PERSON_TYPES.has(n.type) && n !== me && n.id !== me.id
    && String(n.name || '').trim().length >= 2);
  if (!people.length) return 0;
  const tied = edges.map((e) => [e.source, e.target]);
  const direct = new Set(tied.filter(([a, b]) => a === me.id || b === me.id).map(([a, b]) => (a === me.id ? b : a)));
  const unnamed = new Map();
  for (const e of edges) {
    if (FAMILY_EDGES.has(e.type) && !e.role && (e.source === me.id || e.target === me.id)) {
      const other = e.source === me.id ? e.target : e.source;
      if (!unnamed.has(other)) unnamed.set(other, e);
    }
  }
  let made = 0;
  for (const n of people) {
    if (direct.has(n.id) && !unnamed.has(n.id)) continue;
    const name = String(n.name).trim();
    let hit = null;
    for (const para of story.split('\n')) {
      const sents = para.split(/[.!?。]/).filter((s) => s.trim());
      for (let i = 0; i < sents.length && !hit; i += 1) {
        const s = sents[i];
        if (!s.includes(name) || kinOfOther(s, name)) continue;
        const names = people.map((p) => String(p.name).trim()).filter((nm) => s.includes(nm));
        hit = kinIn(s, names) || (i > 0 ? kinIn(sents[i - 1], names) : null);
      }
      if (hit) break;
    }
    if (!hit) continue;
    if (unnamed.has(n.id)) { unnamed.get(n.id).role = hit.term; continue; }
    const [src, dst] = hit.dir === 'in' ? [n.id, me.id] : [me.id, n.id];
    edges.push({ source: src, target: dst, type: hit.kind, role: hit.term, description: null, confidence: 1 });
    tied.push([src, dst]);
    direct.add(n.id);
    made += 1;
  }
  const reach = new Set([me.id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const [a, b] of tied) {
      if (reach.has(a) !== reach.has(b)) { reach.add(a); reach.add(b); grew = true; }
    }
  }
  for (const n of people) {
    if (reach.has(n.id) || !story.includes(String(n.name).trim())) continue;
    edges.push({ source: me.id, target: n.id, type: 'met', description: n.description ?? null, confidence: 0.8 });
    tied.push([me.id, n.id]);
    reach.add(n.id);
    made += 1;
  }
  return made;
}

// --- 함께한 사람 -------------------------------------------------------------
// 화면에 낼 수 있는 이름인가. 그래프에 있으면 그 노드의 이름이고, 없으면 **한글로
// 적힌 말일 때만** 그대로 쓴다 — 모델의 식별자(`person_1`)를 화면에 내지 않는다
// (2026-09-08 지적: "person_1이라고 변수 이름을 바로 노출 하면 안 돼", CLAUDE.md §1).
export const HANGUL = /[가-힣]/;
export function nodeLabel(byId, id) {
  const n = byId?.get?.(id);
  if (n?.name) return String(n.name);
  const s = String(id ?? '').trim();
  return HANGUL.test(s) ? s : '';
}

// 이야기 글 전부 (적은 차례대로). 근거를 원문에서 찾는 자리가 읽는다.
export function storyText(raw) {
  return (raw?.stories || []).map((r) => String(r?.text || '')).filter(Boolean).join('\n');
}

// 이야기가 **한 문장 안에서** 사건과 사람을 함께 부르면 그 사람도 그 자리에 있었다.
// 모델은 participants 에 주인공만 적어 놓기도 한다 (2026-09-08 지적: "친구 김일권과
// 같이 갔다고 분명 말했는데 '함께 person_1' 이라고 말하고 있어").
//
// 문장이 사건을 **이름으로 부르거나 달까지 아는 날짜로** 가리킬 때만 잰다 — 해만
// 말한 문장("1997년에 입학했고 김일권을 만났어")은 그 해의 일을 여럿 담으므로
// 누가 어디에 있었는지를 가르지 못한다. 근거가 원문에 있어야 한다는 규칙 그대로다.
export function participantsFromStory(nodes, text) {
  const story = String(text || '').trim();
  if (!story) return 0;
  const people = nodes.filter((n) => PERSON_TYPES.has(n.type) && String(n.name || '').trim().length >= 2);
  const events = nodes.filter((n) => EVENT_TYPES.has(n.type));
  if (!people.length || !events.length) return 0;
  let made = 0;
  for (const line of story.split(/[.!?。\n]+/)) {
    const said = people.filter((n) => line.includes(n.name));
    if (!said.length) continue;
    for (const ev of events) {
      const name = String(ev.name || '').trim();
      // 날짜로 가리키는 것은 **그 날 일어난 일**이다. 기억(Memory)은 물건이 그 날을
      // 가리킬 뿐이라 날짜로 잡지 않는다 — 공연에 함께 간 사람이 '공연 티켓'에도
      // 함께한 사람으로 서면 안 된다. 이름으로 부른 것은 그대로 잰다.
      const byDate = ev.type !== 'Memory' && saysDate(line, ev.start_date);
      if (!(name.length >= 2 && line.includes(name)) && !byDate) continue;
      const have = Array.isArray(ev.participants) ? ev.participants.map(String) : [];
      for (const n of said) {
        if (have.includes(n.id) || have.includes(n.name)) continue;
        have.push(n.id); made += 1;
      }
      ev.participants = have;
    }
  }
  return made;
}

// 문장이 이 날짜를 말하는가. **달까지 아는 날짜만** 잰다 ('1998' 은 너무 넓다).
// '1998-04-24' · '1998년 4월 24일' · '1998년 4월' 을 같은 것으로 읽는다.
export function saysDate(line, date) {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(String(date || ''));
  if (!m) return false;
  const [, y, mo, d] = m;
  const forms = [`${y}-${mo}${d ? `-${d}` : ''}`, `${+y}년 ${+mo}월${d ? ` ${+d}일` : ''}`, `${+y}년 ${+mo}월`];
  return forms.some((f) => line.includes(f));
}

// participants 를 사람 노드로 풀어 **하나의 꼴(노드 id)** 로 만들고 사건에 잇는다.
// 모델은 여기에 id 를 적기도 하고 이름을 적기도 한다. 못 푸는 식별자는 버린다 —
// 화면이 그것을 그대로 적을 자리가 없어야 한다. 이은 선의 역할은 tidyEdges 가
// '함께'로 단다 (주인공은 사건의 술어 — '입학'·'졸업').
export function linkParticipants(nodes, edges, me) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const byName = new Map();
  for (const n of nodes) if (PERSON_TYPES.has(n.type)) byName.set(norm(n.name), n);
  const tied = new Set(edges.map((e) => `${e.source}>${e.target}`));
  let made = 0;
  for (const ev of nodes) {
    if (!Array.isArray(ev.participants)) continue;
    const kept = [];
    for (const p of ev.participants) {
      const who = byId.get(String(p)) || byName.get(norm(p));
      const id = who ? who.id : (HANGUL.test(String(p)) ? String(p).trim() : '');
      if (!id || id === ev.id || kept.includes(id)) continue;
      kept.push(id);
      if (!who || who === me || !PERSON_TYPES.has(who.type) || !EVENT_TYPES.has(ev.type)) continue;
      if (tied.has(`${who.id}>${ev.id}`) || tied.has(`${ev.id}>${who.id}`)) continue;
      edges.push({ source: who.id, target: ev.id, type: 'experienced', description: null,
        confidence: ev.confidence ?? 1 });
      tied.add(`${who.id}>${ev.id}`);
      made += 1;
    }
    ev.participants = kept;
  }
  return made;
}

export function tidyEdges(nodes, edges, me, issues = []) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const schools = new Map();
  const works = new Map();
  const add = (m, k, v) => { if (!m.has(k)) m.set(k, new Set()); m.get(k).add(v); };
  for (const e of edges) {
    const s = byId.get(e.source); const t = byId.get(e.target);
    if (!s || !t || klass(s) !== 'person') continue;
    if (e.type === 'studied_at' && (t.type === 'School' || t.type === 'University')) add(schools, s.id, t.id);
    if (e.type === 'worked_at' || t.type === 'Company' || t.type === 'Business') add(works, s.id, t.id);
  }
  const out = [];
  const seen = new Set();
  const targets = new Map();
  for (const raw of edges) {
    const e = { ...raw };
    let s = byId.get(e.source); let t = byId.get(e.target);
    let kind = e.type;
    let role = e.role || null;
    if (s && t && LIFE_EDGES[kind]) {
      if (!fits(kind, s, t)) {
        const moved = RELAX.get(`${kind}|${klass(s)}|${klass(t)}`);
        if (moved === 'experienced' && klass(s) === 'event') { [e.source, e.target, s, t] = [t.id, s.id, t, s]; }
        if (moved) { role = role || RELAX_ROLE[`${kind}|${klass(t)}`] || null; kind = moved; }
        else issues.push(`${kind}: ${s.name}(${klass(s)}) → ${t.name}(${klass(t)}) — 표 밖`);
      }
      if (kind === 'met') {
        const text = [e.description, ...[s, t].filter((n) => n !== me).map((n) => n.description)].filter(Boolean).join(' ');
        if (FRIEND.test(text)) kind = 'friend_of';
        else if (COLLEAGUE.test(text)) kind = 'worked_with';
      }
      if (kind === 'worked_with' && (e.confidence ?? 1) < 1 && !works.has(s.id) && !works.has(t.id)
        && [...(schools.get(s.id) || [])].some((id) => schools.get(t.id)?.has(id))) kind = 'schoolmate';
      if (kind === 'experienced' && !role) role = (!me || s === me) ? deedOf(t) : '함께';
    }
    // 5. 차례만 남은 것은 버린다 — RELAX 가 옮길 데가 있었으면 이미 옮겼고(주인공 →
    //    자기 사건은 참여), 사건 → 사건으로 남았으면 연표가 이미 그리는 차례다.
    if (SEQUENCE_ONLY.has(kind)) continue;
    const key = SYMMETRIC.has(kind) ? `${[e.source, e.target].sort().join('|')}|${kind}` : `${e.source}>${e.target}|${kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (MAX_TARGETS[kind]) {
      const k = `${e.source}|${kind}`;
      add(targets, k, e.target);
      if (targets.get(k).size > MAX_TARGETS[kind]) issues.push(`${kind}: ${s?.name} 의 도착이 ${targets.get(k).size}개`);
    }
    e.type = kind;
    if (role) e.role = role; else delete e.role;
    out.push(e);
  }
  return out;
}

// 선 위에 적는 말. 역할이 있으면 그것이 타입 이름을 이긴다 (한국사의 LABEL_HEADS — '주도'가
// '참여'보다 정확하다). 없으면 양끝을 본다: 사건이 일어난 곳(at)은 도착이 학교면 '학교',
// 전공이면 '전공'이고, 사건 → 장소의 moved_to 는 '이주지'다. 그것도 없으면 타입의 일반 이름.
const AT_LABEL = { School: '학교', University: '학교', Company: '회사', Business: '회사', Organization: '단체', Community: '단체',
  Project: '프로젝트', Investment: '투자', Occupation: '직업', Skill: '기술', Hobby: '취미',
  Location: '장소', BirthPlace: '장소', Residence: '장소', TravelLocation: '장소' };
const EVENT_TO = { moved_to: '이주지', visited: '방문지', lived_in: '거주지', born_in: '출생지' };
export function edgeLabel(kind, srcType, dstType, role = null) {
  if (role) return role;
  if (kind === 'at') return AT_LABEL[dstType] || '곳';
  const sc = GRAPH_TYPE[srcType];
  if ((sc === 'event' || sc === 'period') && EVENT_TO[kind]) return EVENT_TO[kind];
  return LIFE_EDGES[kind]?.[0] || EDGE_TYPE_KO[kind] || kind;
}

// --- 그래프 --------------------------------------------------------------
// 개인 그래프는 역사 그래프와 **같은 캔버스**(graph-view.js GraphView)에 선다.
// 캔버스는 노드의 `type` 으로 색을 고르므로(TYPE_COLOR: person·org·event·
// place·artwork·media·period·role) 지시문의 타입을 그 여덟에 대응시킨다.
// 색이 곧 갈래다 — 가족도 친구도 파랑(인물), 책·영화·음악·게임은 연빨강
// (작품), 학교·회사는 크림(단체). 이름표에는 원래 타입(가족·책)이 남는다.
export const GRAPH_TYPE = {
  Person: 'person', FamilyMember: 'person', Ancestor: 'person', Relationship: 'person',
  Time: 'period', LifeStage: 'period', Period: 'period',
  PersonalEvent: 'event', HistoricalEvent: 'event', TurningPoint: 'event', Crisis: 'event',
  Achievement: 'event', Failure: 'event', Decision: 'event', Memory: 'event',
  Location: 'place', BirthPlace: 'place', Residence: 'place', TravelLocation: 'place',
  School: 'org', University: 'org', Company: 'org', Organization: 'org', Community: 'org',
  Business: 'org', Project: 'org', Investment: 'org',
  Occupation: 'role', Hobby: 'role', Skill: 'role',
  Book: 'artwork', Movie: 'artwork', Music: 'artwork', Comic: 'artwork', Game: 'artwork',
  Religion: 'media', Culture: 'media', Technology: 'media',
};
const GRAPH_GROUP = { person: 'actor', org: 'actor', event: 'event', place: 'thing', artwork: 'thing', media: 'thing', period: 'frame', role: 'frame' };
// 범례의 묶음 이름 — 캔버스 타입 하나에 지시문 타입 여럿이 든다.
export const GRAPH_TYPE_LABEL = {
  person: '인물·가족', org: '학교·회사·단체', event: '사건·기억', place: '장소',
  artwork: '책·영화·음악·게임', media: '기술·문화·종교', period: '시기', role: '직업·취미·기술',
};

// 캔버스가 받는 꼴 (server.graph 와 같다): {center, nodes:[{id,label,type,group,degree}],
// edges:[{s,t,type,label,conf}]}. 개인 그래프는 작아서(수십 노드) 통째로 준다 —
// 역사 그래프처럼 한 노드 주변만 잘라 줄 이유가 없다.
export function graphPayload(life, center = null) {
  const degree = new Map();
  for (const e of life.edges) {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }
  const nodes = life.nodes.map((n) => {
    const type = GRAPH_TYPE[n.type] || 'event';
    return { id: n.id, label: n.name, type, group: GRAPH_GROUP[type], degree: degree.get(n.id) || 0,
      kind: n.type, kind_label: NODE_TYPE_KO[n.type] };
  });
  const kindOf = new Map(life.nodes.map((n) => [n.id, n.type]));
  const edges = life.edges.map((e) => ({
    s: e.source, t: e.target, type: e.type, label: edgeLabel(e.type, kindOf.get(e.source), kindOf.get(e.target), e.role), conf: e.confidence ?? 1,
  }));
  return { center: center && nodes.some((n) => n.id === center) ? center : (life.subject?.id || nodes[0]?.id), nodes, edges };
}

// 설정 상자(SidePanel)가 읽는 메타 — 범례와 관계 종류 필터. 역사 그래프는
// 서버(/api/meta)가 주는 것을 개인 그래프는 자료에서 센다.
export function graphMeta(life) {
  const pay = graphPayload(life);
  const nodeTypes = {};
  for (const n of pay.nodes) {
    const t = (nodeTypes[n.type] ||= { label: GRAPH_TYPE_LABEL[n.type], group: n.group, count: 0 });
    t.count++;
  }
  const edgeTypes = {};
  for (const e of pay.edges) {
    const t = (edgeTypes[e.type] ||= { label: EDGE_TYPE_KO[e.type] || e.label, count: 0 });
    t.count++;
  }
  const seeds = [...pay.nodes].sort((a, b) => b.degree - a.degree).slice(0, 8);
  return { node_types: nodeTypes, edge_types: edgeTypes, seeds };
}

// --- 치수 ----------------------------------------------------------------
// 왼쪽 띠는 시대 연표와 같은 104px (timeline.js LANE_W). 가운데·오른쪽은
// 각각 연도 칸(38) + 축 + 라벨이다. 두 열 사이 홈(gutter)으로 역사 → 개인
// 연결선이 지난다 — 라벨 위를 지나면 글자를 가른다. 인생 단계 띠는 **맨
// 오른쪽**이다: 개인 열 왼쪽에 두면 연결선이 띠의 이름을 가로지른다
// (실측: '초등학교 1997~1998' 위로 IMF 선이 지났다).
//
// 너비는 **좁게** 잡는다 (2026-09-08 지적: "연표 폭을 줄여줘 너무 넓어").
// 세 열을 다 펴면 그만큼 가운데 그래프가 좁아지는데, 줄은 이름 한 줄이라
// 넘치면 말줄임으로 접히고 전체 이름은 title 에 남는다 — 넓게 잡을 값이
// 아니다. 왼쪽 띠만 시대 연표와 같은 104px 로 둔다 (막대 자리가 timeline.js
// 에 박혀 있다).
export const COLS = {
  lane: 104,      // 왕·대통령 띠
  history: 208,   // 역사 열
  gutter: 28,     // 연결선이 지나는 홈
  personal: 214,  // 개인 열 (오른쪽 24px 은 인과 선의 자리)
  stage: 78,      // 인생 단계 띠 (라벨은 .life-stage 가 54px 로 접는다)
};
// 연표 판의 너비 — 세 열과 세로 스크롤바. 화면(LifeView)이 왼쪽 칸을 이만큼 잡는다.
export function boardWidth() {
  return COLS.lane + COLS.history + COLS.gutter + COLS.personal + COLS.stage + 12;
}
const AXIS_X = 46;   // 열 안에서 세로축이 서는 자리 (timeline.js 와 같다)
const PAD_TOP = 18;
const PAD_BOTTOM = 64;
const ZOOM = 5;      // 일생 40년이면 시대 연표의 16배는 너무 길다
export const STAGE_COLOR = 'var(--interactive-accent)';

// --- 날짜 ----------------------------------------------------------------
// 파이썬 life.parse_when 과 같은 규칙. 화면에 붙여 넣은 날것의 JSON 도
// 같은 해로 풀려야 한다. 지어내지 않는다 — '20대 초반'은 생년 없이는 null.
const PART = { 초반: 1, 중반: 4, 후반: 7 };
export function parseWhen(text, birthYear = null) {
  const s = String(text ?? '').trim();
  if (!s) return { year: null, end: null, precision: '' };
  let m = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/.exec(s);
  if (m) return { year: +m[1], end: +m[1], precision: m[2] ? 'exact' : 'year' };
  m = /(\d{4})\s*년대\s*(초반|중반|후반)?/.exec(s);
  if (m) {
    const base = +m[1];
    const lo = base + (m[2] ? PART[m[2]] - 1 : 0);
    return { year: lo, end: m[2] ? lo + 3 : base + 9, precision: 'decade' };
  }
  m = /(\d{4})\s*년?/.exec(s);
  if (m) return { year: +m[1], end: +m[1], precision: 'year' };
  m = /(\d{1,2})\s*(?:대\s*(초반|중반|후반)?|살|세)/.exec(s);
  if (m) {
    if (birthYear == null) return { year: null, end: null, precision: 'age' };
    const n = +m[1];
    if (m[0].includes('대')) {
      const lo = birthYear + n + (m[2] ? PART[m[2]] - 1 : 0);
      return { year: lo, end: m[2] ? lo + 3 : birthYear + n + 9, precision: 'age' };
    }
    return { year: birthYear + n, end: birthYear + n, precision: 'age' };
  }
  // '고등학교 2학년'·'고2' — 학년은 해다. 생년에서 센다 (초1 = 생년+7, 중1 = +13,
  // 고1 = +16, 대1 = +19). 입학 해에서 세는 더 나은 길은 서버(life.school_year)에 있다.
  m = /(초등학교|국민학교|초등|중학교|고등학교|고교|대학교|대학)\s*(\d)\s*학년/.exec(s)
    || /(?<![가-힣\d])(초|중|고|대)\s?(\d)(?![\d학년-])/.exec(s);
  if (m) {
    if (birthYear == null) return { year: null, end: null, precision: 'age' };
    const level = m[1][0];
    const y = birthYear + SCHOOL_ENTRY_AGE[level] + (+m[2]) - 1;
    return { year: y, end: y, precision: 'age' };
  }
  return { year: null, end: null, precision: '' };
}
const SCHOOL_ENTRY_AGE = { '초': 7, '국': 7, '중': 13, '고': 16, '대': 19 };

// --- 정규화 ----------------------------------------------------------------
// 서버(`histgraph life`)를 거친 JSON 은 이미 이 꼴이다. 화면에 바로 붙여 넣은
// 모델 답은 여기서 같은 꼴이 된다: 모르는 타입·관계는 버리고, 날짜를 해로
// 풀고, 연표 항목이 해를 안 적었으면 노드의 해를 쓴다.
const SELF_NAMES = new Set(['사용자', '본인', '화자', '주인공', '나 (사용자)', '사용자 (나)', 'user', 'me', 'self']);

export function normalize(raw) {
  const out = { ...raw };
  const nodes = [];
  const seen = new Set();
  for (const n of raw.nodes || []) {
    if (!n || !n.id || !n.name || !NODE_TYPE_KO[n.type] || seen.has(n.id)) continue;
    seen.add(n.id);
    nodes.push({ ...n, confidence: clamp(+n.confidence || 1, 0, 1) });
  }
  const me = nodes.find((n) => n.type === 'Person') || null;
  // 지시문이 화자를 '사용자'라 부르니 모델도 그 이름을 적는다. 화면에서는 '나'다
  // (2026-09-08). 서버를 안 거친 자료(브라우저·계정에 남은 것)도 여기서 고쳐진다.
  if (me && SELF_NAMES.has(me.name.trim().toLowerCase())) me.name = '나';
  const said = birthDate(me, nodes, raw.edges || []);
  if (me && said && said !== me.start_date && said.length >= String(me.start_date || '').length) {
    const w = parseWhen(said);
    me.start_date = said; me.year = w.year; me.precision = w.precision;
  }
  const birth = me ? parseWhen(me.start_date).year : null;
  for (const n of nodes) {
    if (n.year !== undefined && n.precision !== undefined) continue;   // 서버가 이미 풀었다
    const w = parseWhen(n.start_date, birth);
    const e = parseWhen(n.end_date, birth).year;
    n.year = w.year;
    n.end_year = e ?? (w.end !== w.year ? w.end : null);
    n.precision = w.precision;
  }
  out.nodes = nodes;
  out.subject = raw.subject
    ? { ...raw.subject, name: (me && raw.subject.id === me.id) ? me.name : raw.subject.name,
      birth_year: raw.subject.birth_year ?? (raw.subject.id === me?.id ? birth : null) }
    : (me ? { id: me.id, name: me.name, birth_year: birth } : null);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const subj = out.subject ? byId.get(out.subject.id) || me : me;
  const kept = (raw.edges || []).filter((e) => e && EDGE_TYPE_KO[e.type] && byId.has(e.source) && byId.has(e.target));
  // 함께한 사람 — 이야기가 한 문장에서 같이 부른 사람을 찾아 넣고(참여), 그렇게 모인
  // participants 를 사람 노드로 풀어 사건에 잇는다. 온톨로지를 씌우기 전에 (새 선도
  // 같은 관문을 지난다).
  participantsFromStory(nodes, storyText(raw));
  linkParticipants(nodes, kept, subj);
  out.edges = tidyEdges(nodes, kept, subj);
  // 섬을 잇는다 — 온톨로지를 씌운 뒤에 (버려질 엣지를 이어진 것으로 세면 섬이 남는다).
  // 사건은 내가 겪은 것으로, 사람은 이야기의 호칭(엄마·형·아들)으로 — 브라우저에 남은
  // 옛 그래프도 새로고침으로 여기서 이어진다.
  if (linkOrphans(nodes, out.edges, subj) + linkPeople(nodes, out.edges, subj, storyText(raw))) {
    out.edges = tidyEdges(nodes, out.edges, subj);
  }
  const timeline = [];
  for (const t of raw.timeline || []) {
    if (!t || !byId.has(t.event_id)) continue;
    // 주인공은 연표의 항목이 아니라 연표 그 자체다 — 자기 노드가 0세 자리에 서면
    // '출생' 사건 옆에 같은 것이 하나 더 선다 (life.py refine 3 과 같다).
    if (me && t.event_id === me.id) continue;
    const node = byId.get(t.event_id);
    const item = { ...t };
    if (!LIFE_STAGES.includes(item.life_stage)) item.life_stage = null;
    // 훈련소 입소부터 소집해제까지는 병역이지 사회생활이 아니다 (life.py refine 3 과 같다)
    if (['event', 'period'].includes(klass(node))
      && MILITARY.test(`${node.name || ''} ${node.description || ''}`)) item.life_stage = '군복무';
    // 해의 출처 차례: 항목의 날짜 글 → 나이(생년을 알 때) → 노드의 날짜 (life.py 와 같다)
    if (item.year == null) item.year = parseWhen(item.date_text, birth).year;
    if (item.year == null && item.age != null && birth != null) item.year = birth + item.age;
    if (item.year == null) item.year = node.year;
    // **달까지 아는 날짜는 항목이 적어 온 해를 이긴다.** 모델은 항목의 `year` 를
    // 나이나 앞뒤 항목에서 어림해 적는다 — 1998년 4월 24일 메탈리카 공연이
    // 1997 로 적혀 와 1997 칸에 '4월'로 섰다 (2026-09-08 지적: "메탈리카 공연은
    // 1998년 이었어"). 어림한 나이도 함께 버리고 생년에서 다시 센다.
    const fine = monthYear(node.start_date);
    if (fine != null && fine !== item.year) { item.year = fine; item.age = null; }
    if (item.age == null && item.year != null && birth != null) item.age = item.year - birth;
    timeline.push(item);
  }
  timeline.sort((a, b) => (a.year == null) - (b.year == null) || (a.year || 0) - (b.year || 0));
  // 해가 같으면 학제가 차례다 — 초등 졸업이 중학 입학보다 먼저다 (`ladder` 머리글).
  out.timeline = orderByLadder(timeline, (t) => byId.get(t.event_id), (t) => t.year);
  out.historical_connections = (raw.historical_connections || []).filter(Boolean)
    .map((c) => ({ ...c, impact_type: IMPACT_KO[c.impact_type] ? c.impact_type : 'possible' }));
  let ranking = raw.influence_ranking || {};
  if (Array.isArray(ranking)) ranking = { items: ranking };
  else if (!Array.isArray(ranking.items)) {
    ranking = { items: Object.entries(ranking).filter(([, v]) => v && typeof v === 'object')
      .map(([k, v]) => ({ category: k, ...v })) };
  }
  out.influence_ranking = ranking;
  out.turning_points = raw.turning_points || [];
  out.impact_analysis = raw.impact_analysis || [];
  out.counterfactual_analysis = raw.counterfactual_analysis || [];
  out.life_patterns = raw.life_patterns || [];
  out.family_analysis = raw.family_analysis || { members: [] };
  out.follow_up_questions = (raw.follow_up_questions || []).slice(0, 5);
  return out;
}

// --- 지우기 ----------------------------------------------------------------
// 상세 패널의 '삭제' — 노드 하나와 그것을 가리키던 것을 함께 뺀다 (2026-09-08
// 사용자: "삭제 버튼을 누르면 해당 노드를 지워서 그래프와 연표에서 삭제").
//
// 고치는 것은 **날것의 문서**다. 화면이 쥔 것(normalize 를 지난 것)만 고치면
// 브라우저·계정에 남은 자료가 그대로라 새로고침에 되살아난다.
//
// **가리키던 것을 두고 가지 않는다.** 엣지는 normalize 가 알아서 버리지만
// (한쪽 끝이 없다), 분석 묶음('전환점'·'영향'·'만약 없었다면'·'가장 크게
// 영향을 준 것'·가족)은 이름만 들고 있어 그대로 두면 지운 사건이 그 자리에
// 유령으로 선다. 분석 쪽은 아이디 대신 **이름**을 적어 두기도 하므로(모델이
// 그렇게 답한다) 이름으로도 재되, 같은 이름의 노드가 또 남아 있으면 이름으로는
// 재지 않는다 — 이름만으로는 아무것도 단정하지 않는다.
export function removeNode(raw, id) {
  const doc = { ...raw };
  const node = (raw.nodes || []).find((n) => n && n.id === id) || null;
  doc.nodes = (raw.nodes || []).filter((n) => n && n.id !== id);
  const label = node && !doc.nodes.some((n) => norm(n.name) === norm(node.name)) ? norm(node.name) : '';
  const hit = (v) => v === id || (label !== '' && typeof v === 'string' && norm(v) === label);

  doc.edges = (raw.edges || []).filter((e) => e && e.source !== id && e.target !== id);
  // 연표에서 뺀 자리는 앞뒤를 이어 붙인다 — 사슬에 구멍을 내지 않는다.
  const gap = (raw.timeline || []).find((t) => t && t.event_id === id) || null;
  doc.timeline = (raw.timeline || []).filter((t) => t && t.event_id !== id).map((t) => (
    t.previous_event !== id && t.next_event !== id ? t : {
      ...t,
      previous_event: t.previous_event === id ? (gap?.previous_event ?? null) : t.previous_event,
      next_event: t.next_event === id ? (gap?.next_event ?? null) : t.next_event,
    }
  ));
  doc.historical_connections = (raw.historical_connections || []).filter((c) => c && c.personal_event !== id);
  for (const key of ['turning_points', 'impact_analysis', 'counterfactual_analysis']) {
    if (raw[key]) doc[key] = raw[key].filter((it) => !(it && hit(it.event)));
  }
  const ranking = raw.influence_ranking;
  const items = Array.isArray(ranking) ? ranking : (Array.isArray(ranking?.items) ? ranking.items : null);
  if (items) {
    const kept = items.filter((it) => !(it && hit(it.node)));
    doc.influence_ranking = Array.isArray(ranking) ? kept : { ...ranking, items: kept };
  }
  if (raw.family_analysis && Array.isArray(raw.family_analysis.members)) {
    doc.family_analysis = { ...raw.family_analysis, members: raw.family_analysis.members.filter((m) => m && m.node_id !== id) };
  }
  // 주인공을 지웠으면 자리를 비운다 — normalize 가 남은 인물에서 다시 고른다.
  if (raw.subject && raw.subject.id === id) doc.subject = null;
  return doc;
}

// --- 내가 적은 이야기 -------------------------------------------------------
// 그래프는 사람이 적은 글에서 나온다. 그래서 **그 글을 다시 볼 수 있어야
// 고칠 수 있다** (2026-09-08 사용자: "누르면 사용자가 입력한 사용자의 역사
// 히스토리를 보여줘. 그래서 잘못된 입력을 고칠 수 있게 해줘" — 실제로 옛
// 원문에는 '잠실고딩학교 1학넌때'가 남아 있고 다시 적은 문단이 그 옆에 있다).
//
// 문서는 `stories: [{at, text}]` 로 들고 다닌다 — 한 번 '입력' 이 한 줄이다.
// 그 열이 없는 옛 문서는 서버에 남은 원문(`/api/life/story`)을 **빈 줄로**
// 가른다. 이어 붙일 때 빈 줄을 넣었으므로 (server.LifeAnalysis._run) 그것이
// 덩어리의 경계다. 한 번에 여러 문단을 적었으면 더 잘게 갈리지만, 고치고
// 다시 읽을 때 같은 빈 줄로 이어 붙이므로 결과는 같다.
export function splitStories(text) {
  return String(text || '')
    .split(/\n\s*\n/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => ({ at: '', text: t }));
}

// 예전에 적은 글을 입력창으로 옮길 때 (2026-09-08 사용자: "예전 입력을
// 클릭하면 우리 인생 입력창에 자동으로 복사해줘"). **적다 만 글은 지우지
// 않는다** — 사람이 쓰던 것을 삼키면 안 되므로 빈 줄을 두고 아래에 붙인다.
//
// **이미 있는 글이어도 붙인다.** 전에는 같은 글이면 조용히 넘겼는데, 그러면
// 누른 줄이 이미 칸에 있을 때(모달의 맨 윗줄은 아랫줄들을 합친 글이다) 눌러도
// 아무 일이 없어 '복사가 안 된다'로 보였다. 두 번 붙은 것은 눈에 보이고 지울 수
// 있지만, 아무 일도 안 일어난 것은 고장으로만 보인다.
export function appendDraft(cur, text) {
  const a = String(cur || '').trim();
  const b = String(text || '').trim();
  if (!b) return a;
  if (!a) return b;
  return `${a}\n\n${b}`;
}

// 이야기 덩어리를 다시 한 편의 글로. 서버가 파일에 이어 두던 꼴 그대로다.
export function joinStories(stories) {
  return (stories || []).map((s) => String(s?.text || '').trim()).filter(Boolean).join('\n\n');
}

// --- 무엇이 서는가 ---------------------------------------------------------
// 개인 열: 연표 항목이 해를 아는 사건. 연표에 없는 사건 노드도 해를 알면
// 선다 — 모델이 연표를 빠뜨렸다고 사건이 없던 일이 되면 안 된다.
//
// **같은 해 안의 차례는 연표의 차례다.** 날짜 문자열로 세우면 '1998'(전학)이
// '1998-03'(이사)보다 앞에 서서 결과가 원인 위에 온다 — 시대 연표가 겪은
// 같은 함정이다 (CLAUDE.md §1-5). 연표 항목은 모델이 앞뒤(previous_event·
// next_event)를 잡아 준 차례이므로 해만 같으면 그 차례를 지킨다. **학제만 예외다** —
// 초등 졸업과 중학 입학처럼 뒤집힐 수 없는 차례는 이야기의 차례를 이긴다 (orderByLadder).
export function personalMarks(life) {
  const byId = new Map(life.nodes.map((n) => [n.id, n]));
  const marks = [];
  const seen = new Set();
  for (const t of life.timeline) {
    const n = byId.get(t.event_id);
    // 이야기가 날짜를 말하지 않은 인물은 연표에 세우지 않는다 — 연표 항목의 나이·단계가
    // 그 사람 이름 아래 '0세 · 출생'으로 서면 그것이 곧 생년이다 (2026-09-08 사용자).
    if (!n || t.year == null || !dateSaid(n)) continue;
    seen.add(n.id);
    marks.push(mark(n, t.year, t));
  }
  for (const n of life.nodes) {
    if (seen.has(n.id) || !EVENT_TYPES.has(n.type) || n.year == null) continue;
    marks.push(mark(n, n.year, null));
  }
  const ordered = marks.map((m, i) => [m, i])
    .sort((a, b) => a[0].year - b[0].year || a[1] - b[1]).map(([m]) => m);
  // 그러고도 해가 같으면 학제가 차례다 (`ladder` 머리글). 연표에 없던 사건도 여기서
  // 제자리를 찾는다 — 서버가 세운 차례(life.py refine 3)와 같은 규칙이다.
  return orderByLadder(ordered, (m) => byId.get(m.id), (m) => m.year);
}

function mark(n, year, t) {
  return {
    id: n.id, label: n.name, type: n.type, year,
    end: n.end_year ?? null,
    date: n.start_date || '',
    age: t?.age ?? null, stage: t?.life_stage ?? null,
    importance: n.importance_score ?? null,
    precision: n.precision || '',
    confidence: n.confidence,
  };
}

// 역사 열: 그래프의 큰 사건(context.anchors) + 모델이 이은 사건 중 그래프에
// 없는 것. 없는 것은 없는 대로 세우되 그렇다고 표시한다 (`kind: 'extra'`) —
// 모델이 부른 이름을 그래프의 사건인 척 세우지 않는다.
export function historyMarks(life, context) {
  const marks = (context?.anchors || []).map((a) => ({
    id: a.id, label: a.label, year: a.year, date: a.date || '', kind: 'anchor', linked: false,
  }));
  const byId = new Map(marks.map((m) => [m.id, m]));
  const byName = new Map(marks.map((m) => [`${norm(m.label)}@${m.year}`, m]));
  for (const c of life.historical_connections || []) {
    let m = c.node_id ? byId.get(c.node_id) : null;
    if (!m && c.year != null) m = byName.get(`${norm(c.historical_event)}@${c.year}`);
    if (!m && c.node_id) {
      // 그래프에는 있지만 이 구간의 뼈대에 안 든 사건 (6·25 처럼 생년보다 앞).
      m = { id: c.node_id, label: c.node_label || c.historical_event, year: c.year, date: '', kind: 'anchor', linked: false };
      if (m.year == null) continue;
      marks.push(m); byId.set(m.id, m);
    }
    if (!m) {
      if (c.year == null) continue;
      m = { id: `x:${norm(c.historical_event)}@${c.year}`, label: c.historical_event, year: c.year, date: '', kind: 'extra', linked: false };
      if (byId.has(m.id)) m = byId.get(m.id);
      else { marks.push(m); byId.set(m.id, m); }
    }
    m.linked = true;
    c._mark = m.id;
  }
  return marks.sort((a, b) => a.year - b.year || String(a.date).localeCompare(String(b.date)) || a.label.localeCompare(b.label, 'ko'));
}

// 인생 단계 띠 — 연표 항목의 단계가 바뀌는 자리에서 시작해 다음 단계 앞까지.
// 마지막 단계는 오늘까지. 항목이 단계를 안 적었으면 띠가 없다.
export function stageBands(life, toYear) {
  const byId = new Map(life.nodes.map((n) => [n.id, n]));
  const bands = [];
  for (const t of life.timeline) {
    if (!t.life_stage || t.year == null) continue;
    const last = bands[bands.length - 1];
    if (last && last.stage === t.life_stage) { last.last = t; continue; }
    if (last) last.end = t.year;
    bands.push({ stage: t.life_stage, start: t.year, end: null, last: t });
  }
  if (bands.length) bands[bands.length - 1].end = Math.max(toYear, bands[bands.length - 1].start);
  // 끝나는 사건이 있으면 거기서 닫는다 — 2004년에 소집해제하고 2006년에야 다음 일이
  // 있으면, 다음 단계까지 칠한 띠는 2년 복무를 4년으로 만든다 (2026-09-08 사용자).
  for (const b of bands) {
    const n = byId.get(b.last?.event_id);
    const rule = STAGE_END[b.stage];
    if (n && rule && rule.test(`${n.name || ''} ${n.description || ''}`) && b.last.year < b.end) b.end = b.last.year;
    delete b.last;
  }
  return bands;
}

// --- 배치 ------------------------------------------------------------------
// 세 열이 같은 자를 쓴다. 한 해의 높이는 두 열 중 더 몰린 쪽이 정한다 —
// 라벨은 제 해를 떠나지 않고, 다른 열은 그 해를 같은 높이로 지난다.
export function lifeLayout({ life, context, bodyH = 700, today = new Date().getFullYear() }) {
  const personal = personalMarks(life);
  const allHistory = historyMarks(life, context);
  // **축은 이 사람의 삶이다** — 생년(또는 첫 사건)에서 오늘까지. 태어나기
  // 전의 역사(할아버지가 참전한 6·25)를 축에 세우면 앞이 35년 비고 정작
  // 일생이 아래로 밀린다. 그 전의 일은 축 위 머리(`before`)에 따로 세운다.
  const years = personal.map((m) => m.year);
  const birth = life.subject?.birth_year;
  if (birth != null) years.push(birth);
  if (!years.length) return null;
  const from = Math.min(...years) - 2;
  const to = Math.max(...years, ...allHistory.map((m) => m.year), today) + 1;
  // 그 전의 뼈대는 세우지 않는다 — 6·25 의 전투 서른 개가 머리를 채우면 정작
  // 이 사람과 이어진 한 줄이 묻힌다. 이어진 것만 머리에 선다.
  const before = allHistory.filter((m) => m.year < from && m.linked);
  const history = allHistory.filter((m) => m.year >= from);

  // 해마다 두 열 중 큰 쪽만큼 가짜 표시를 세워 자를 잰다 (buildScale 은 year 만 본다)
  const count = new Map();
  const bump = (list) => {
    const c = new Map();
    for (const m of list) c.set(m.year, (c.get(m.year) || 0) + 1);
    for (const [y, n] of c) count.set(y, Math.max(count.get(y) || 0, n));
  };
  bump(personal); bump(history);
  const virtual = [];
  for (const [y, n] of count) for (let i = 0; i < n; i++) virtual.push({ year: y });
  const axis = buildScale(virtual, { from, to, base: (bodyH - PAD_TOP - PAD_BOTTOM) * ZOOM });
  const at = (y) => axis.pos[clamp(Math.round(y), from, to) - from];

  const placeP = placeMarks(personal, axis).map(({ m, y }) => ({ m, ty: y }));
  const placeH = placeMarks(history, axis).map(({ m, y }) => ({ m, ty: y }));
  const tyP = new Map(placeP.map((p) => [p.m.id, p.ty]));
  const tyH = new Map(placeH.map((p) => [p.m.id, p.ty]));

  // 역사 → 개인 연결선. 양끝이 다 서 있어야 긋는다.
  const links = [];
  const beforeIds = new Set(before.map((m) => m.id));
  for (const m of before) m.links = [];
  for (const c of life.historical_connections || []) {
    if (c._mark && beforeIds.has(c._mark)) {
      before.find((m) => m.id === c._mark).links.push(c);
      continue;
    }
    if (!c._mark || !tyH.has(c._mark) || !tyP.has(c.personal_event)) continue;
    // '가능성'은 화살표가 아니다 — 모델의 짐작("영향을 미쳤을 수 있음")을 선으로
    // 그으면 읽는 사람에게 인과가 된다 (2026-09-08 지적: 세월호 → 퍼듀 졸업).
    // 역사 열의 점과 툴팁에는 남는다.
    if (c.impact_type === 'possible') continue;
    links.push({ from: c._mark, to: c.personal_event, y1: tyH.get(c._mark), y2: tyP.get(c.personal_event), impact: c.impact_type });
  }
  // 개인 사건 사이의 인과. 원인이 결과보다 위에 있어야 한다 — 아래에 있으면
  // 날짜가 틀린 것이라 그리되 표시한다.
  const causal = [];
  for (const e of life.edges) {
    if (!CAUSAL_EDGES.has(e.type) || !tyP.has(e.source) || !tyP.has(e.target)) continue;
    causal.push({ from: e.source, to: e.target, y1: tyP.get(e.source), y2: tyP.get(e.target), type: e.type, backwards: tyP.get(e.source) > tyP.get(e.target) });
  }
  const reigns = (context?.reigns || []).filter((r) => r.start <= to && r.end >= from);
  const stages = stageBands(life, today).map((b) => ({ ...b, y1: at(b.start), y2: at(b.end) }));
  return { axis, from, to, at, personal: placeP, history: placeH, before, links, causal, reigns, stages, H: axis.H };
}

// --- 그리기 ------------------------------------------------------------------
// 열 셋이 한 캔버스(.life-canvas) 위에 절대 좌표로 선다. 선은 SVG 한 장.
export function renderLife(layout, { selected = null, subjectName = '나' } = {}) {
  const { lane, history: HW, gutter, stage: SW, personal: PW } = COLS;
  const xH = lane;                    // 역사 열 시작
  const xG = xH + HW;                 // 홈 시작
  const xP = xG + gutter;             // 개인 열 시작
  const xS = xP + PW;                 // 단계 띠 시작
  const W = xS + SW;
  const H = layout.H;
  const AXH = xH + AXIS_X;
  const AXP = xP + AXIS_X;
  const at = layout.at;

  // 왼쪽 띠 — 시대 연표와 같은 함수
  const band = reignBand(layout.reigns, at, {});

  // 인생 단계 띠 — 재위 띠와 같은 문법(막대 + 이름·연도), 강조색
  const stageSvg = layout.stages.map((s, i) => `
    <rect x="${xS + 6}" y="${s.y1.toFixed(1)}" width="6" height="${Math.max(s.y2 - s.y1, 2).toFixed(1)}" rx="3"
          fill="${STAGE_COLOR}" opacity="${i % 2 ? 0.45 : 0.75}"><title>${esc(s.stage)} ${s.start}~${s.end}</title></rect>`).join('');
  const stageItems = layout.stages.map((s) => `
    <div class="tl-reign life-stage" style="left:${xS + 18}px; top:${s.y1.toFixed(1)}px" title="${esc(s.stage)} · ${s.start}~${s.end}">
      <b>${esc(s.stage)}</b><i>${s.start}~${s.end === s.start ? '' : s.end}</i></div>`).join('');

  // 점과 구간
  const dots = [];
  for (const { m, ty } of layout.history) {
    dots.push(`<circle cx="${AXH}" cy="${ty.toFixed(1)}" r="${m.linked ? 3.4 : 2.6}"
      fill="${m.kind === 'extra' ? 'var(--surface-2)' : 'var(--text-faint)'}"
      stroke="${m.linked ? CAUSE_WIRE.color : 'none'}" stroke-width="1.4"/>`);
  }
  for (const { m, ty } of layout.personal) {
    const r = 2.4 + (m.importance ? m.importance / 4 : 1);
    const on = m.id === selected;
    if (m.end != null && m.end !== m.year) {
      dots.push(`<line x1="${AXP}" y1="${ty.toFixed(1)}" x2="${AXP}" y2="${at(m.end).toFixed(1)}"
        stroke="${REIGN_COLOR}" stroke-width="3" stroke-linecap="round" opacity=".5"/>`);
    }
    dots.push(`<circle cx="${AXP}" cy="${ty.toFixed(1)}" r="${r.toFixed(1)}" fill="${REIGN_COLOR}"
      opacity="${on ? 1 : 0.85}"${on ? ' stroke="var(--text-normal)" stroke-width="1.5"' : ''}/>`);
  }

  // 역사 → 개인 연결선. 역사 라벨 오른쪽 끝에서 홈을 건너 개인 열의 왼쪽
  // 가장자리까지 — 축까지 끌면 연도 칸의 숫자를 가른다. 같은 줄 높이라 눈이 잇는다.
  // 직접 영향은 실선, 간접·가능성은 점선 — 굵기가 아니라 선의 종류로 가른다.
  const linkSvg = layout.links.map((l) => {
    const x1 = xG - 6;
    const x2 = xP - 2;
    const cx = (x1 + x2) / 2;
    const dash = l.impact === 'direct' ? '' : ' stroke-dasharray="3 3"';
    return `<path d="M${x1} ${l.y1.toFixed(1)} C${cx} ${l.y1.toFixed(1)} ${cx} ${l.y2.toFixed(1)} ${x2} ${l.y2.toFixed(1)}"
      fill="none" stroke="${CAUSE_WIRE.color}" stroke-width="1.2" opacity=".85"${dash}/>
      <path d="M${x2 - 4} ${(l.y2 - 3).toFixed(1)} L${x2} ${l.y2.toFixed(1)} L${x2 - 4} ${(l.y2 + 3).toFixed(1)}"
      fill="none" stroke="${CAUSE_WIRE.color}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>`;
  }).join('');

  // 개인 사건의 인과 — 시대 연표와 같은 ㄷ 자 선, 개인 열의 오른쪽 여백을 탄다.
  // 겹치지 않게 선마다 4px 씩 안으로.
  const causalSvg = layout.causal.map((c, i) => causeWire(c.y1, c.y2, xS - (i % 5) * 4)).join('');

  const hCells = yearCells(layout.history.map((p) => p.m));
  const hItems = layout.history.map(({ m, ty }, i) => {
    const cell = hCells[i];
    const extra = m.kind === 'extra' ? '<span class="tl-rel">그래프에 없는 사건</span>' : '';
    const tag = m.kind === 'extra' ? 'span' : 'a';
    const href = m.kind === 'extra' ? '' : ` href="/#${encodeURIComponent(m.id)}"`;
    return `<${tag} class="tl-mark life-h${m.linked ? ' is-linked' : ''}"${href} data-id="${esc(m.id)}"
      style="left:${xH}px; width:${HW - 8}px; top:${ty.toFixed(1)}px" title="${esc(m.label)} · ${m.year}년">
      <span class="tl-y${cell.repeat ? ' rep' : ''}">${cell.text}</span><span class="tl-name">${esc(m.label)}</span>${extra}</${tag}>`;
  }).join('');

  // 연도 칸은 시대 연표와 같은 규칙이다 (yearCells) — 그 해의 첫 줄이 해를 적고
  // 뒤따르는 줄은 달을 적는다. 연도는 언제나 달보다 위에 선다 (2026-09-08 지적).
  const pCells = yearCells(layout.personal.map((p) => p.m));
  const pItems = layout.personal.map(({ m, ty }, i) => {
    const cell = pCells[i];
    // '세'는 만 나이다 (2026-09-08 사용자: "나이 앞에 '만'이라고 써줘") — 이야기가
    // 준 나이를 그대로 세는 것이라 한국 나이(세는 나이)로 헷갈릴 수 있다.
    const age = m.age != null ? `<span class="tl-rel">만 ${m.age}세</span>` : '';
    const rough = m.precision === 'decade' || m.precision === 'age' ? '<span class="tl-rel">어림</span>' : '';
    return `<button type="button" class="tl-mark life-p${m.id === selected ? ' k-self' : ''}" data-id="${esc(m.id)}"
      style="left:${xP}px; width:${PW - 28}px; top:${ty.toFixed(1)}px" title="${esc(m.label)} · ${m.year}년">
      <span class="tl-y${cell.repeat ? ' rep' : ''}">${cell.text}</span><span class="tl-name">${esc(m.label)}</span>${age}${rough}</button>`;
  }).join('');

  // 태어나기 전의 역사 — 축 위가 아니라 캔버스 머리에 한 줄씩. 무엇과 이어졌는지 함께 적는다.
  const byName = new Map();
  const before = (layout.before || []).map((m) => {
    const who = (m.links || []).map((c) => `${IMPACT_KO[c.impact_type]} · ${c.description}`).join(' / ');
    const tag = m.kind === 'extra' ? 'span' : 'a';
    const href = m.kind === 'extra' ? '' : ` href="/#${encodeURIComponent(m.id)}"`;
    return `<div class="life-before-row"><span class="tl-y">${m.year}</span><${tag} class="life-before-name"${href}>${esc(m.label)}</${tag}><span class="life-before-why">${esc(who)}</span></div>`;
  }).join('');
  // 캔버스 위에 따로 선다(흐름 배치) — 축 위에 얹으면 첫 해의 표시와 겹친다.
  const beforeBlock = before
    ? `<div class="life-before" style="margin-left:${xH}px; width:${HW + gutter + SW + PW - 16}px"><div class="life-before-head">태어나기 전</div>${before}</div>`
    : '';

  return `${beforeBlock}
    <div class="life-canvas" style="height:${H}px; width:${W}px">
      <svg class="tl-wires" width="${W}" height="${H}" aria-hidden="true">
        <line x1="${AXH}" y1="${PAD_TOP - 8}" x2="${AXH}" y2="${H - PAD_BOTTOM + 8}" stroke="var(--line)" stroke-width="1"/>
        <line x1="${AXP}" y1="${PAD_TOP - 8}" x2="${AXP}" y2="${H - PAD_BOTTOM + 8}" stroke="var(--line)" stroke-width="1"/>
        <g class="life-lane">${band.svg}</g>
        <g transform="translate(0,0)">${stageSvg}</g>
        ${linkSvg}${causalSvg}${dots.join('')}
      </svg>
      <div class="life-lane-items">${band.items}</div>
      ${stageItems}${hItems}${pItems}
    </div>`;
}

// 열 머리. 이름을 개인 열에 적는다 — "누구의 역사인가"가 열 이름이다.
export function renderHead(subjectName) {
  const { lane, history, gutter, stage, personal } = COLS;
  return `
    <div class="life-col-head" style="width:${lane}px">왕 · 대통령</div>
    <div class="life-col-head" style="width:${history}px">한국사</div>
    <div class="life-col-head" style="width:${gutter}px"></div>
    <div class="life-col-head" style="width:${personal + stage}px">${esc(subjectName)}의 역사</div>`;
}

// --- 브라우저 --------------------------------------------------------------
export class LifeBoard {
  constructor(root, { onPick } = {}) {
    this.root = root;
    this.head = root.querySelector('.life-head');
    this.body = root.querySelector('.life-body');
    this.onPick = onPick || (() => {});
    this.state = null;
    this.body.addEventListener('click', (ev) => {
      const el = ev.target.closest('.life-p[data-id]');
      if (el) this.onPick(el.dataset.id);
    });
    this._ro = new ResizeObserver(() => this.layout());
    this._ro.observe(this.body);
  }

  destroy() { this._ro?.disconnect(); }

  show({ life, context, selected = null }) {
    this.state = { life, context, selected };
    this.head.innerHTML = renderHead(life.subject?.name || '나');
    this.layout({ recenter: true });
  }

  select(id) {
    if (!this.state) return;
    this.state.selected = id;
    this.layout();
  }

  layout({ recenter = false } = {}) {
    if (!this.state) return;
    const { life, context, selected } = this.state;
    const lay = lifeLayout({ life, context, bodyH: this.body.clientHeight || 700 });
    if (!lay) {
      this.body.innerHTML = '<p class="tl-empty">해를 아는 사건이 없어 연표를 세울 수 없습니다.</p>';
      return;
    }
    this.layoutData = lay;
    const top = this.body.scrollTop;
    this.body.innerHTML = renderLife(lay, { selected, subjectName: life.subject?.name });
    if (recenter) {
      // 고른 사건이 있으면 그 자리를 한가운데로. 없으면 맨 위 — 축이 생년
      // 두 해 앞에서 열리므로 출생과 '태어나기 전' 머리가 첫 화면에 같이 든다.
      const target = selected ? lay.personal.find((p) => p.m.id === selected) : null;
      const off = this.body.querySelector('.life-canvas')?.offsetTop || 0;   // 머리(태어나기 전)만큼
      this.body.scrollTop = target ? Math.max(0, off + target.ty - this.body.clientHeight / 2) : 0;
    } else {
      this.body.scrollTop = top;
    }
  }
}

// --- 잔손 -------------------------------------------------------------------
// 달까지 아는 날짜의 해. 'YYYY-MM' 부터가 달을 아는 것이다 — 'YYYY' 는 해뿐이라
// 여기서는 없는 것으로 친다.
export function monthYear(date) {
  const m = /^(-?\d{1,4})-(\d{2})/.exec(String(date || ''));
  return m ? Number(m[1]) : null;
}

export function norm(s) {
  return String(s || '').replace(/[\s·.\-–—()（）]/g, '').toLowerCase();
}

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
