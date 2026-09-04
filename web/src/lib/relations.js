// 관계를 사람이 읽는 말로 바꾸는 자리. DOM 을 모른다 — 그래서 따로 잰다
// (web/tests/relations.test.mjs).

// 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다.
// child_of 는 'A → B = A가 B의 자녀' — 나가는 상대는 부모, 들어오는
// 상대가 자녀다. 방향별 이름이 있는 타입만 바꿔 부른다.
export const DIR_HEAD = {
  child_of: { out: '부모', in: '자녀' },
  part_of: { out: '상위', in: '하위' },
  // 인과는 언제나 원인 → 결과다. 나가는 상대는 이 노드가 부른 결과,
  // 들어오는 상대는 이 노드를 부른 원인이다.
  caused: { out: '결과', in: '원인' },
};

// 인과의 종류(`causes.KINDS`)별 문장. 엣지 라벨이 종류다.
export const KIND_SENTENCE = {
  '원인': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 원인이 되었다`,
  '배경': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 배경이 되었다`,
  '계기': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 계기가 되었다`,
  '영향': (a, b) => `${a}${pt(a, '은', '는')} ${b}에 영향을 주었다`,
};

// 시대(from_period)와 시점(dated_to)은 둘 다 '언제'를 가리킨다. 따로 세우면
// 한 해가 양쪽에 한 번씩 나온다 — 황진이의 1506년이 그랬다. 한 묶음으로 받는다.
export const TIME_TYPES = new Set(['from_period', 'dated_to']);

// 방향이 뜻을 갖지 않는 관계. A의 배우자가 B면 B의 배우자도 A다.
export const SYMMETRIC = new Set(['spouse_of', 'related_to']);

// 'time:1506' 은 해, 'kr:period:조선시대' 는 이름뿐인 시대다. 해를 먼저 오름차순으로,
// 이름 붙은 시대는 뒤에 묶어 둔다.
export function byYear(a, b) {
  const year = (r) => { const m = /^time:(-?\d+)/.exec(r.other.id); return m ? +m[1] : null; };
  const [ya, yb] = [year(a), year(b)];
  if (ya === null || yb === null) {
    if (ya === yb) return a.other.label.localeCompare(b.other.label, 'ko');
    return ya === null ? 1 : -1;
  }
  return ya - yb;
}

// 받침이 있으면 앞말, 없으면 뒷말. '황진이는' / '김시민은'.
export function pt(word, withBatchim, without) {
  const code = String(word).trim().slice(-1).charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return without;   // 한글이 아니면 받침 없는 쪽으로
  return code % 28 ? withBatchim : without;
}

// 사건에서 맡은 역할. `roles` 가 말뭉치의 근거로 적은 것(주도·가담·대항·
// 피해·표적·수습·언급)과, 인포박스 칸 이름(지휘관·주요 인물·교전·가해)이다.
// 역할이 있으면 '참여했다'로 뭉개지 않는다 — 12.3 내란의 '주요인물2' 는
// 계엄을 막은 쪽이고, 체포 명단에 오른 사람을 참여자라 부르면 거짓이다.
export const ROLE_SENTENCE = {
  '주도': (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 주도했다`,
  '가담': (a, b) => `${a}${pt(a, '은', '는')} ${b}에 가담했다`,
  '대항': (a, b) => `${a}${pt(a, '은', '는')} ${b}에 맞섰다`,
  '피해': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 피해자다`,
  '표적': (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 표적이 되었다`,
  '수습': (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 수사·재판했다`,
  '언급': (a, b) => `${a}${pt(a, '은', '는')} ${b} 기록에 이름이 나온다`,
  '근거 없음': (a, b) => `${a}${pt(a, '과', '와')} ${b}${pt(b, '은', '는')} 관련이 있다고 하나 근거를 찾지 못했다`,
  '지휘관': (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 지휘했다`,
  '주요 인물': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 주요 인물이다`,
  '교전': (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 싸웠다`,
  '가해': (a, b) => `${a}${pt(a, '은', '는')} ${b}의 가해자다`,
};

// 엣지 방향 그대로 주어와 목적어를 놓는다. src -> dst 순서다.
export const SENTENCE = {
  participated_in: (a, b, o = {}) => (ROLE_SENTENCE[o.label]
    ? ROLE_SENTENCE[o.label](a, b)
    : `${a}${pt(a, '은', '는')} ${b}에 참여했다`),
  occurred_at: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 일어났다`,
  occurred_during: (a, b) => `${a}${pt(a, '은', '는')} ${b}에 일어났다`,
  born_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 태어났다`,
  died_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에서 죽었다`,
  created: (a, b) => `${a}${pt(a, '이', '가')} ${b}${pt(b, '을', '를')} 만들었다`,
  located_in: (a, b) => `${a}${pt(a, '은', '는')} ${b}에 있다`,
  depicts: (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 다룬다`,
  spouse_of: (a, b) => `${a}${pt(a, '과', '와')} ${b}${pt(b, '은', '는')} 부부다`,
  member_of: (a, b) => `${a}${pt(a, '은', '는')} ${b} 소속이다`,
  held_position: (a, b) => `${a}${pt(a, '은', '는')} ${b}${pt(b, '을', '를')} 지냈다`,
  part_of: (a, b) => `${a}${pt(a, '은', '는')} ${b}의 일부다`,
  caused: (a, b, o = {}) => (KIND_SENTENCE[o.label] || KIND_SENTENCE['원인'])(a, b),
  // 전후(P155/P156)는 앞선 사건에서, 인과(P828/P1542)는 원인에서 담는다.
  // 방향이 하나로 모여 있어 '다음'·'원인'이 적힌 엣지는 어느 쪽에서 읽어도
  // 뒤집히지 않는다.
  related_to: (a, b, o) => (o.label === '다음'
    ? `${a} 다음에 ${b}${pt(b, '이', '가')} 일어났다`
    : o.label === '원인'
    ? `${a}${pt(a, '은', '는')} ${b}의 원인이 되었다`
    : ROLE_SENTENCE[o.label]
    ? ROLE_SENTENCE[o.label](a, b)
    : `${a}${pt(a, '과', '와')} ${b}${pt(b, '은', '는')} 관련이 있다`),
  // 엣지에 '아버지'·'어머니'가 적혀 있으면 그대로 부른다 (실측 479건)
  child_of: (a, b, o) => {
    const role = o.label === '어머니' ? '어머니' : o.label === '아버지' ? '아버지' : '부모';
    return `${a}의 ${role}는 ${b}${pt(b, '이다', '다')}`;
  },
  // 인물은 연도와 같은 실체가 아니다 — '출생'·'사망'이 적힌 엣지만 그렇게 읽는다
  dated_to: (a, b, o) => (o.label === '출생' ? `${a}${pt(a, '은', '는')} ${b}에 태어났다`
                        : o.label === '사망' ? `${a}${pt(a, '은', '는')} ${b}에 죽었다`
                        : `${a}의 연표에 ${b}${pt(b, '이', '가')} 있다`),
  // 주어가 무엇이냐에 따라 시대를 부르는 말이 다르다 — 사람은 '사람이다',
  // 사건은 '일이다', 유물·작품은 '것이다'. ('진산사건은 1791년 것이다'가 나왔다)
  from_period: (a, b, o) => {
    if (o.label === '출생' || o.label === '사망') return SENTENCE.dated_to(a, b, o);
    if (o.srcType === 'person') return `${a}${pt(a, '은', '는')} ${b} 사람이다`;
    if (o.srcType === 'event') return `${a}${pt(a, '은', '는')} ${b}에 일어난 일이다`;
    return `${a}${pt(a, '은', '는')} ${b}의 것이다`;
  },
};

// 지금 보는 노드(self)와 상대 사이의 관계 하나를 문장으로 만든다.
export function sentence(r, self) {
  const me = { label: self.label, type: self.type };
  // 인과의 상대가 서술구('후금의 파약 행위')로 적혀 있었으면 그 구로 부른다 —
  // '후금은 병자호란의 원인이 되었다'보다 '후금의 파약 행위는…'이 참에 가깝다.
  const other = r.type === 'caused' && r.as ? { ...r.other, label: r.as } : r.other;
  const [src, dst] = r.dir === 'out' ? [me, other] : [other, me];
  const make = SENTENCE[r.type];
  return make
    ? make(src.label, dst.label, { label: r.edge_label, srcType: src.type })
    : `${src.label} → ${dst.label} · ${r.label}`;
}

export function mergeEvidence(card, r) {
  card.evidence = [...new Set([...card.evidence, ...(r.evidence || [])])];
  // 시대 엣지에 접힌 '출생'·'사망'까지 챙겨야 "1506년에 태어났다"를 말할 수 있다
  if (!card.edge_label && r.edge_label) card.edge_label = r.edge_label;
}

export function relHead(r) {
  if (TIME_TYPES.has(r.type)) return r.dir === 'out' ? '시기' : '이 시기의 개체';
  return DIR_HEAD[r.type]?.[r.dir] || r.label;
}

// 관계 목록을 화면에 세울 묶음으로 정리한다.
//
// 종류·방향별로 묶는다. 방향까지 키에 넣어야 부모와 자식이 한 덩어리로
// 뒤섞이는 일이 없다. 한 묶음 안에서 같은 상대는 카드 하나다 — 황진이의
// 1506년에는 시대·시점 엣지가 둘 다 걸려 있어 같은 해가 두 번 나왔다.
//
// 반환: { groups: [{ head, rels, shared }], count }
export function groupRelations(relations) {
  const groups = new Map();

  const add = (r) => {
    const head = relHead(r);
    if (!groups.has(head)) groups.set(head, new Map());
    // 배우자·관련은 방향에 뜻이 없다. 방향까지 키에 넣으면 양쪽에 다 적힌
    // 엣지가 카드 두 장이 된다 — 신사임당의 배우자 이원수가 두 번 나왔다
    // (실측: 조선 그래프에서 배우자 206건, 관련 44건).
    const key = `${r.other.id}\u0000${SYMMETRIC.has(r.type) ? '' : r.dir}`;
    const seen = groups.get(head).get(key);
    if (seen) { mergeEvidence(seen, r); return seen; }
    const card = { ...r, evidence: [...new Set(r.evidence || [])] };
    groups.get(head).set(key, card);
    return card;
  };

  // 구체 관계를 먼저 세운다. 그러면 '관련'은 이미 자리 잡은 카드로 접힌다.
  const cardOf = new Map();   // 상대 id -> 그 상대와의 구체 관계 카드 (첫 장)
  for (const r of relations) {
    if (r.type === 'related_to') continue;
    const card = add(r);
    if (!cardOf.has(r.other.id)) cardOf.set(r.other.id, card);
  }
  // 구체 관계가 있는 상대에게 붙은 '관련'은 아무 말도 더하지 않는다 — 정약용
  // 상세에 정약전이 부모로 한 번, 관련으로 또 한 번 나왔다(실측 192건).
  // 카드는 접고 근거 구절만 구체 카드로 옮긴다. '관련'은 방향에 뜻이 없어
  // 상대만 같으면 같은 사실로 본다.
  for (const r of relations) {
    if (r.type !== 'related_to') continue;
    const card = cardOf.get(r.other.id);
    if (card) mergeEvidence(card, r);
    else add(r);
  }

  const out = [...groups.entries()].map(([head, bucket]) => {
    const rels = [...bucket.values()];
    // 시대와 시점을 한 묶음으로 받으면 해가 뒤죽박죽 들어온다 — 연도순으로 세운다.
    if (TIME_TYPES.has(rels[0].type)) rels.sort(byYear);
    // 열거문("시조 작품으로는 A, B, C 등이 있다") 하나가 관계 여럿을 낳는다.
    // 카드마다 같은 문장을 찍으면 다른 작품인데 내용이 같아 보인다 —
    // 여럿이 공유하는 근거는 묶음 머리에 한 번만 둔다.
    const shared = new Set();
    const seen = new Set();
    for (const r of rels) {
      for (const ev of new Set(r.evidence || [])) {
        if (seen.has(ev)) shared.add(ev); else seen.add(ev);
      }
    }
    return { head, rels, shared: [...shared] };
  });

  return { groups: out, count: out.reduce((n, g) => n + g.rels.length, 0) };
}

// 지금 묶음들 중 특정 상대(prev)와의 카드만 골라낸다. 타고 들어온 관계를
// 상세 머리에 한 줄로 적기 위한 것 — 아래 목록과 다른 말을 하면 안 되므로
// 합쳐진 카드에서 그대로 가져온다.
export function cardsFor(groups, otherId) {
  return groups.flatMap((g) => g.rels).filter((c) => c.other.id === otherId);
}

// 빈 설명의 이유는 노드가 어디서 왔는지에 달려 있다. 뭉뚱그려
// '자료 없음'이라고 적으면, 더 받아오면 채워지는 노드와 애초에 채울
// 것이 없는 노드가 같은 말을 하게 된다.
export function whyEmpty(d) {
  if (d.source === 'timeline') return '연표의 해를 세우는 노드입니다.';
  if (d.source === 'extract') return '산문에서 이름만 추출된 노드라 원문이 없습니다.';
  if (d.source === 'khs') return '국가유산청 자료에 해설문이 없습니다.';
  // 한 줄 설명이 영어로 와서 비운 경우. 원문이 남아 있다는 사실만
  // 말하고 영어 자체는 내보내지 않는다.
  if (d.desc_dropped) return '한국어로 옮길 수 있는 설명이 아직 없습니다.';
  if (d.no_kowiki) return '한국어 위키백과에 문서가 없습니다.';
  return '아직 서사를 받아오지 않았습니다.';
}

export function fmtDate(v) {
  if (!v) return '';
  const m = String(v).match(/^(-?)(\d{1,4})/);
  if (!m) return '';
  const y = +m[2];
  return m[1] ? `기원전 ${y}년` : `${y}년`;
}

// 접힌 높이(168px)를 넘길 만큼 길 때만 '전문 보기'를 낸다. 세 줄짜리 글에
// 단추가 붙어 있으면 눌러도 아무 일이 없다.
export const LONG_DESC = 220;

// --- 인과 사슬 ---------------------------------------------------------------
// 서버(`/api/chain`)가 준 나무를 화면에 세울 줄로 편다. 깊이가 들여쓰기다.
// 원인 쪽은 이 노드를 부른 것들이라 '←', 결과 쪽은 '→' 로 읽는다.
export function chainRows(items, depth = 0, out = []) {
  for (const it of items || []) {
    out.push({ id: it.id, depth, kind: it.kind, how: it.how || '', as: it.as || '',
               evidence: it.evidence || [], sources: it.sources || [] });
    chainRows(it.children, depth + 1, out);
  }
  return out;
}

// 나무의 노드 이름. 서술구가 있으면 '후금 (후금의 파약 행위)' 가 아니라
// 서술구를 앞세운다 — 이름은 단추가, 구는 글이 말한다.
export function chainName(row, nodes) {
  const n = nodes?.[row.id];
  return n ? n.label : row.id;
}

// `/api/path` 의 경로 하나를 걸음으로. 첫 걸음에는 엣지가 없다.
export function pathSteps(path, nodes) {
  return (path || []).map((step) => ({
    id: step.id,
    label: nodes?.[step.id]?.label || step.id,
    type: nodes?.[step.id]?.type,
    group: nodes?.[step.id]?.group,
    year: fmtDate(nodes?.[step.id]?.start),
    kind: step.edge?.kind || '',
    how: step.edge?.how || '',
    evidence: step.edge?.evidence || [],
  }));
}

// 경로를 한 줄 글로. "임진왜란 → (배경) 후금 → (계기) 정묘호란"
export function pathSentence(steps) {
  return steps.map((s, i) => (i === 0 ? s.label : `→ (${s.kind}) ${s.label}`)).join(' ');
}
