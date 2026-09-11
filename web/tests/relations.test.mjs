// 관계 → 사람이 읽는 말. 브라우저 없이 돈다.
//
//   node web/tests/relations.test.mjs
//
// 여기 걸린 것들은 대부분 화면에서 실제로 났던 오류다. 옮기면서 방어가
// 같이 따라왔는지를 잰다.
import {
  pt, sentence, groupRelations, relHead, byYear, cardsFor,
  whyEmpty, fmtDate, chainRows, chainGuides, pathSteps, pathSentence,
} from '../src/lib/relations.js';
import { imeKey, moveCursor } from '../src/lib/keys.js';

let pass = 0;
let fail = 0;

function eq(name, got, want) {
  if (got === want) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}\n      나온 것: ${got}\n      바란 것: ${want}`); }
}
function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? `  — ${extra}` : ''}`); }
}

const rel = (o) => ({ evidence: [], ...o });
const other = (id, label, type = 'person', group = 'actor') => ({ id, label, type, group });

console.log('\n조사 (받침)');
eq('받침 있는 이름은 앞말', pt('김시민', '은', '는'), '은');
eq('받침 없는 이름은 뒷말', pt('황진이', '은', '는'), '는');
eq('한글이 아니면 받침 없는 쪽', pt('Sejong', '은', '는'), '는');
eq('숫자로 끝나도 받침 없는 쪽', pt('1506', '은', '는'), '는');

console.log('\n문장');
{
  const self = { label: '이순신', type: 'person' };
  eq('나가는 방향은 내가 주어',
     sentence(rel({ type: 'participated_in', dir: 'out', other: other('e1', '임진왜란', 'event', 'event') }), self),
     '이순신은 임진왜란에 참여했다');
  eq('들어오는 방향은 상대가 주어',
     sentence(rel({ type: 'created', dir: 'in', other: other('a1', '난중일기', 'artwork', 'thing') }), self),
     '난중일기가 이순신을 만들었다');
  // child_of 는 'A → B = A가 B의 자녀'
  eq('부모는 엣지 라벨을 따른다',
     sentence(rel({ type: 'child_of', dir: 'out', edge_label: '아버지', other: other('p1', '이정') }), self),
     '이순신의 아버지는 이정이다');
  eq('라벨이 없으면 부모로 부른다',
     sentence(rel({ type: 'child_of', dir: 'out', other: other('p1', '이정') }), self),
     '이순신의 부모는 이정이다');
  // 진산사건이 '1791년 것이다'로 나왔던 자리
  eq('사건의 시대는 “일이다”',
     sentence(rel({ type: 'from_period', dir: 'out', other: other('t1', '1791년', 'period', 'frame') }),
              { label: '진산사건', type: 'event' }),
     '진산사건은 1791년에 일어난 일이다');
  eq('사람의 시대는 “사람이다”',
     sentence(rel({ type: 'from_period', dir: 'out', other: other('t1', '조선', 'period', 'frame') }), self),
     '이순신은 조선 사람이다');
  eq('유물의 시대는 “것이다”',
     sentence(rel({ type: 'from_period', dir: 'out', other: other('t1', '조선', 'period', 'frame') }),
              { label: '측우기', type: 'heritage' }),
     '측우기는 조선의 것이다');
  eq('출생이 적힌 시대 엣지는 태어난 것으로 읽는다',
     sentence(rel({ type: 'from_period', dir: 'out', edge_label: '출생', other: other('t1', '1545년', 'period', 'frame') }), self),
     '이순신은 1545년에 태어났다');
  eq('모르는 타입은 화살표로 물러난다',
     sentence(rel({ type: 'unknown_type', dir: 'out', label: '무언가', other: other('x', '무엇') }), self),
     '이순신 → 무엇 · 무언가');
}

console.log('\n묶음 머리');
eq('나가는 child_of 는 부모', relHead(rel({ type: 'child_of', dir: 'out' })), '부모');
eq('들어오는 child_of 는 자녀', relHead(rel({ type: 'child_of', dir: 'in' })), '자녀');
eq('시대는 한 묶음', relHead(rel({ type: 'from_period', dir: 'out' })), '시기');
eq('시점도 같은 묶음', relHead(rel({ type: 'dated_to', dir: 'out' })), '시기');

console.log('\n카드 합치기');
{
  // 신사임당의 배우자 이원수가 두 번 나왔던 자리 — 방향이 뜻 없는 관계
  const { groups, count } = groupRelations([
    rel({ type: 'spouse_of', dir: 'out', label: '배우자', other: other('p1', '이원수') }),
    rel({ type: 'spouse_of', dir: 'in', label: '배우자', other: other('p1', '이원수') }),
  ]);
  eq('배우자는 양쪽에 적혀 있어도 카드 하나', count, 1);
  eq('묶음도 하나', groups.length, 1);
}
{
  // 부모와 자녀는 섞이면 안 된다
  const { groups } = groupRelations([
    rel({ type: 'child_of', dir: 'out', label: '자녀', other: other('p1', '아버지쪽') }),
    rel({ type: 'child_of', dir: 'in', label: '자녀', other: other('p2', '아들쪽') }),
  ]);
  const heads = groups.map((g) => g.head).sort();
  ok('부모와 자녀가 다른 묶음이다', heads.length === 2 && heads.includes('부모') && heads.includes('자녀'), heads.join(','));
}
{
  // 정약용 상세에 정약전이 부모로 한 번, 관련으로 또 한 번 나왔던 자리
  const { groups, count } = groupRelations([
    rel({ type: 'child_of', dir: 'in', label: '자녀', other: other('p1', '정약전'), evidence: ['형이다'] }),
    rel({ type: 'related_to', dir: 'out', label: '관련', other: other('p1', '정약전'), evidence: ['같이 유배됐다'] }),
  ]);
  eq('구체 관계가 있으면 “관련”은 접힌다', count, 1);
  const card = groups[0].rels[0];
  ok('접으면서 근거는 구체 카드로 옮겨온다',
     card.evidence.includes('형이다') && card.evidence.includes('같이 유배됐다'),
     JSON.stringify(card.evidence));
}
{
  // 구체 관계가 없는 '관련'은 남아야 한다
  const { count } = groupRelations([
    rel({ type: 'related_to', dir: 'out', label: '관련', other: other('p9', '아무개') }),
  ]);
  eq('구체 관계가 없으면 “관련”이 그대로 남는다', count, 1);
}
{
  // 황진이의 1506년 — 시대·시점 엣지가 둘 다 걸려 같은 해가 두 번 나왔다
  const { groups, count } = groupRelations([
    rel({ type: 'from_period', dir: 'out', label: '시대', other: other('time:1506', '1506년', 'period', 'frame') }),
    rel({ type: 'dated_to', dir: 'out', label: '시점', edge_label: '출생', other: other('time:1506', '1506년', 'period', 'frame') }),
  ]);
  eq('같은 해가 두 번 나오지 않는다', count, 1);
  eq('접힌 쪽의 “출생”을 챙겨 온다', groups[0].rels[0].edge_label, '출생');
}

console.log('\n연도순');
{
  const { groups } = groupRelations([
    rel({ type: 'dated_to', dir: 'out', label: '시점', other: other('kr:period:조선시대', '조선시대', 'period', 'frame') }),
    rel({ type: 'dated_to', dir: 'out', label: '시점', other: other('time:1592', '1592년', 'period', 'frame') }),
    rel({ type: 'dated_to', dir: 'out', label: '시점', other: other('time:1545', '1545년', 'period', 'frame') }),
  ]);
  const labels = groups[0].rels.map((r) => r.other.label);
  eq('해가 먼저, 오름차순으로', labels.join(' '), '1545년 1592년 조선시대');
}
{
  // 기원전을 문자열로 비교하면 뒤집힌다
  const a = { other: { id: 'time:-57', label: '기원전 57년' } };
  const b = { other: { id: 'time:668', label: '668년' } };
  ok('기원전이 먼저 온다', byYear(a, b) < 0);
}

console.log('\n공유 근거');
{
  // 열거문 하나가 관계 여럿을 낳는다 — 같은 문장을 카드마다 찍으면 안 된다
  const shared = '시조 작품으로는 청산리 벽계수야, 동짓달 기나긴 밤이 있다';
  const { groups } = groupRelations([
    rel({ type: 'created', dir: 'out', label: '만듦', other: other('a1', '청산리 벽계수야', 'artwork', 'thing'), evidence: [shared, '이것만의 근거'] }),
    rel({ type: 'created', dir: 'out', label: '만듦', other: other('a2', '동짓달 기나긴 밤', 'artwork', 'thing'), evidence: [shared] }),
  ]);
  const g = groups[0];
  ok('여럿이 나눠 쓰는 근거는 묶음 머리로 올라간다', g.shared.includes(shared), JSON.stringify(g.shared));
  ok('한 장만 가진 근거는 안 올라간다', !g.shared.includes('이것만의 근거'));
}

console.log('\n타고 들어온 관계');
{
  const { groups } = groupRelations([
    rel({ type: 'child_of', dir: 'out', label: '자녀', other: other('p1', '이정') }),
    rel({ type: 'participated_in', dir: 'out', label: '참여', other: other('e1', '임진왜란', 'event', 'event') }),
  ]);
  eq('상대 id 로 카드를 찾는다', cardsFor(groups, 'p1').length, 1);
  eq('없는 상대는 빈 목록', cardsFor(groups, 'nope').length, 0);
}

console.log('\n빈 설명의 이유');
eq('연표 노드', whyEmpty({ source: 'timeline' }), '연표의 해를 세우는 노드입니다.');
eq('추출 고아', whyEmpty({ source: 'extract' }), '산문에서 이름만 추출된 노드라 원문이 없습니다.');
eq('영어라 비운 것', whyEmpty({ desc_dropped: true }), '한국어로 옮길 수 있는 설명이 아직 없습니다.');
eq('한국어 문서가 없는 것', whyEmpty({ no_kowiki: true }), '한국어 위키백과에 문서가 없습니다.');
eq('아직 안 받아온 것', whyEmpty({}), '아직 서사를 받아오지 않았습니다.');
ok('이유는 늘 한국어다', !/[A-Za-z]/.test(
  [whyEmpty({ source: 'timeline' }), whyEmpty({ source: 'khs' }), whyEmpty({})].join('')));

console.log('\n날짜');
eq('연도', fmtDate('1592-01-01'), '1592년');
// 날짜 칸은 XSD 셈법이라 한 해 어긋난다 — '-0057' 은 기원전 58년이다.
eq('기원전', fmtDate('-0057-01-01'), '기원전 58년');
eq('빈 값', fmtDate(null), '');
eq('날짜가 아니면 빈 값', fmtDate('알 수 없음'), '');

console.log('\n역할 — 참여로 뭉개지 않는다');
{
  const me = { id: 'p', label: '이재명', type: 'person' };
  const ev = other('e', '12.3 내란', 'event', 'event');
  const r = (label, type = 'participated_in') => rel({ type, dir: 'out', other: ev, edge_label: label });
  eq('역할이 없으면 참여했다', sentence(r(null), me), '이재명은 12.3 내란에 참여했다');
  eq('인포박스 주요 인물은 주요 인물이다', sentence(r('주요 인물'), me), '이재명은 12.3 내란의 주요 인물이다');
  eq('대항은 맞섰다', sentence(r('대항'), me), '이재명은 12.3 내란에 맞섰다');
  eq('표적은 관련 엣지로 온다', sentence(r('표적', 'related_to'), me), '이재명은 12.3 내란에서 표적이 되었다');
  eq('피해자', sentence(r('피해', 'related_to'), me), '이재명은 12.3 내란의 피해자다');
  eq('근거 없음은 그렇다고 말한다', sentence(r('근거 없음', 'related_to'), me),
     '이재명과 12.3 내란은 관련이 있다고 하나 근거를 찾지 못했다');
  eq('원인·다음은 그대로', sentence(rel({ type: 'related_to', dir: 'out', other: ev, edge_label: '원인' }), me),
     '이재명은 12.3 내란의 원인이 되었다');
}

// 2026-09-05 지적: "정도전은 제1차 왕자의 난을 지휘했다" — 인포박스 지휘관1
// 뒤의 † 를 버려서 그 난에 죽은 사람이 지휘자가 됐다. 표(`data/roles.tsv`)가
// 피해로 판정하고, 표식(props.fate)이 결말을 말한다.
console.log('\n역할 — 표식과 편 이름');
{
  const jd = { id: 'p', label: '정도전', type: 'person' };
  const coup = other('e', '제1차 왕자의 난', 'event', 'event');
  const r = (label, extra = {}, type = 'participated_in') => rel({ type, dir: 'out', other: coup, edge_label: label, ...extra });
  eq('피해 + 사망은 살해되었다', sentence(r('피해', { fate: '사망' }, 'related_to'), jd), '정도전은 제1차 왕자의 난에서 살해되었다');
  eq('피해 + 처형', sentence(r('피해', { fate: '처형' }, 'related_to'), jd), '정도전은 제1차 왕자의 난에서 처형되었다');
  eq('피해 + 귀양', sentence(r('피해', { fate: '귀양' }, 'related_to'), jd), '정도전은 제1차 왕자의 난에서 귀양 갔다');
  eq('표식이 없으면 피해자다', sentence(r('피해', {}, 'related_to'), jd), '정도전은 제1차 왕자의 난의 피해자다');
  eq('주도 + 사망', sentence(r('주도', { fate: '사망' }), jd), '정도전은 제1차 왕자의 난을 주도했고 죽었다');
  eq('가담 + 처형', sentence(r('가담', { fate: '처형' }), jd), '정도전은 제1차 왕자의 난에 가담했고 처형되었다');
  eq('대항 + 피살', sentence(r('대항', { fate: '피살' }), jd), '정도전은 제1차 왕자의 난에 맞섰고 살해되었다');
  eq('모르는 표식은 무시', sentence(r('주도', { fate: '실종' }), jd), '정도전은 제1차 왕자의 난을 주도했다');

  const lee = { id: 'p2', label: '이순신', type: 'person' };
  const sea = other('e2', '옥포 해전', 'event', 'event');
  const c = (extra = {}) => rel({ type: 'participated_in', dir: 'out', other: sea, edge_label: '지휘관', ...extra });
  eq('지휘관은 편을 말한다', sentence(c({ side_name: '조선' }), lee), '이순신은 옥포 해전에서 조선 측을 지휘했다');
  eq('편 이름이 없으면 예전대로', sentence(c(), lee), '이순신은 옥포 해전을 지휘했다');
  eq('지휘관 + 사망은 전사', sentence(c({ side_name: '조선', fate: '사망' }), lee), '이순신은 옥포 해전에서 조선 측을 지휘하다 전사했다');
  eq('지휘관 + 처형', sentence(c({ side_name: '야인여진', fate: '처형' }), lee), '이순신은 옥포 해전에서 야인여진 측을 지휘하다 처형되었다');
  // 상대 쪽에서 보아도(사건 → 인물) 같은 문장이다
  const fromEvent = rel({ type: 'participated_in', dir: 'in', other: { id: 'p', label: '정도전', type: 'person', group: 'actor' },
                          edge_label: '피해', fate: '사망' });
  eq('사건 쪽에서 봐도 같다', sentence(fromEvent, { id: 'e', label: '제1차 왕자의 난', type: 'event' }), '정도전은 제1차 왕자의 난에서 살해되었다');
  // 2026-09-07 지적: 피해로 옮긴 정도전이 사건 상세의 '관련' 더미에 묻혀 사라진 것처럼 보였다
  eq('피해는 관련이 아니라 피해 묶음이다', relHead(fromEvent), '피해');
  eq('주도도 묶음 이름이다', relHead(rel({ type: 'participated_in', dir: 'in', other: jd, edge_label: '주도', label: '참여' })), '주도');
  eq('언급은 관련에 남는다', relHead(rel({ type: 'related_to', dir: 'in', other: jd, edge_label: '언급', label: '관련' })), '관련');
  const g = groupRelations([
    rel({ type: 'related_to', dir: 'in', other: { ...jd, group: 'actor' }, edge_label: '피해', label: '관련' }),
    rel({ type: 'related_to', dir: 'in', other: other('p9', '아무개'), edge_label: null, label: '관련' }),
  ]);
  eq('피해와 관련은 다른 묶음', g.groups.map((x) => x.head).join(','), '피해,관련');
}

// 2026-09-07 전수 조사: 라벨이 뜻을 말하는데 '관련' 한 더미에 묻힌 것들과,
// 문장 규칙이 아예 없어 "A → B · 배경" 화살표로 서던 타입 셋.
console.log('\n라벨이 타입보다 정확한 관계');
{
  const me = { id: 'a', label: '임진왜란', type: 'event' };
  const nxt = other('b', '정유재란', 'event', 'event');
  const seq = (dir) => rel({ type: 'related_to', dir, other: nxt, edge_label: '다음', label: '관련' });
  eq('다음 일은 관련이 아니다', relHead(seq('out')), '다음 일');
  eq('들어오는 쪽은 앞선 일', relHead(seq('in')), '앞선 일');
  eq('다음 문장', sentence(seq('out'), me), '임진왜란 다음에 정유재란이 일어났다');

  const rec = { id: 'r', label: '현화사를 창건하다', type: 'event' };
  const her = other('h', '현화사', 'heritage', 'thing');
  const art = rel({ type: 'related_to', dir: 'out', other: her, edge_label: '이 기사의 대상', label: '관련' });
  eq('기사의 대상', relHead(art), '이 기록이 다루는 것');
  eq('기사 문장', sentence(art, rec), '현화사를 창건하다는 현화사를 다룬 기록이다');

  const fr = { id: 'f', label: '프랑스', type: 'org' };
  const eu = other('e', '유럽 연합', 'org', 'org');
  const rel1 = rel({ type: 'related_to', dir: 'out', other: eu, edge_label: '소속', label: '관련' });
  eq('완화된 소속은 소속이다', relHead(rel1), '소속');
  eq('소속 문장', sentence(rel1, fr), '프랑스는 유럽 연합 소속이다');

  const drama = { id: 'd', label: '불멸의 이순신', type: 'media' };
  eq('원작', sentence(rel({ type: 'adapted_from', dir: 'out', other: other('n', '칼의 노래', 'artwork', 'thing') }), drama),
     '불멸의 이순신은 칼의 노래를 원작으로 한다');
  eq('배경', sentence(rel({ type: 'set_in', dir: 'out', other: other('j', '조선', 'org', 'org') }), drama),
     '불멸의 이순신의 배경은 조선이다');
  eq('주제', sentence(rel({ type: 'about', dir: 'out', other: other('c', '제도', 'concept', 'thing') }), drama),
     '불멸의 이순신은 제도를 주제로 한다');
}

// --- 씨족의 파 (`clans.py`) -------------------------------------------------
// 파는 새 타입도 새 색도 아니다 — org 안의 갈래이고, 가르는 것은 글자다
// (graph-drawer.md §12.21). 그 글자가 여기서 나온다.
console.log('\n씨족의 파');
{
  const pa = other('ex:org:덕천군파', '덕천군파', 'org', 'frame');
  const root = other('ex:org:전주 이씨', '전주 이씨', 'org', 'frame');
  const founder = other('wd:Q12592850', '덕천군', 'person', 'actor');

  // 타입 제한을 걷었다 — 이기는 것은 타입이 아니라 표에 적힌 라벨이다
  const jopa = rel({ type: 'member_of', dir: 'out', other: pa, edge_label: '파조', label: '소속' });
  eq('파조는 소속이 아니다', relHead(jopa), '파조');
  eq('파조 문장', sentence(jopa, { label: '덕천군', type: 'person' }), '덕천군은 덕천군파의 파조다');
  eq('파 쪽에서 봐도 같은 문장',
     sentence(rel({ type: 'member_of', dir: 'in', other: founder, edge_label: '파조', label: '소속' }),
              { label: '덕천군파', type: 'org' }),
     '덕천군은 덕천군파의 파조다');
  eq('라벨 없는 소속은 그대로',
     sentence(rel({ type: 'member_of', dir: 'out', other: root, label: '소속' }), { label: '이방원', type: 'person' }),
     '이방원은 전주 이씨 소속이다');

  const bun = (dir, o) => rel({ type: 'part_of', dir, other: o, edge_label: '분파', label: '상위' });
  eq('나가는 쪽은 속한 문중', relHead(bun('out', root)), '속한 문중');
  eq('들어오는 쪽은 갈라진 파', relHead(bun('in', pa)), '갈라진 파');
  eq('분파 문장', sentence(bun('out', root), { label: '덕천군파', type: 'org' }),
     '덕천군파는 전주 이씨에서 갈라져 나온 파다');
  eq('본관 쪽에서 봐도 같은 문장', sentence(bun('in', pa), { label: '전주 이씨', type: 'org' }),
     '덕천군파는 전주 이씨에서 갈라져 나온 파다');
  // 라벨이 없는 part_of 는 예전 그대로여야 한다 (전수 조사로 넓힌 자리라)
  eq('라벨 없는 상위는 그대로', relHead(rel({ type: 'part_of', dir: 'out', other: root, label: '상위' })), '상위');
  eq('일부다 문장도 그대로',
     sentence(rel({ type: 'part_of', dir: 'out', other: root, label: '상위' }), { label: '아무개', type: 'org' }),
     '아무개는 전주 이씨의 일부다');
  // 파는 상세에서 '관련' 더미에 묻히지 않는다 — 묶음이 따로 선다
  const gp = groupRelations([jopa, bun('out', root)]);
  eq('파의 묶음 둘', gp.groups.map((x) => x.head).join(','), '파조,속한 문중');

  // 본관 → 그 지명. 씨족 나무가 그래프에 닿는 자리다 (`clans.py`).
  const jeonju = other('wd:Q42140', '전주시', 'place', 'thing');
  const bon = (dir, o) => rel({ type: 'related_to', dir, other: o, edge_label: '본관', label: '관련' });
  eq('본관 지명', relHead(bon('out', jeonju)), '본관 지명');
  eq('지명 쪽에서는 씨족 목록', relHead(bon('in', root)), '이곳을 본관으로 하는 씨족');
  eq('본관 문장', sentence(bon('out', jeonju), { label: '전주 이씨', type: 'org' }),
     '전주 이씨의 본관은 전주시다');
}

// 작품을 만든 방식 (`creators.ROLES` — 그림·글씨·저술·편찬·제작·발원).
// 라벨을 버리고 타입 이름으로만 읽으면 "정선이 인왕제색도를 만들었다"가 된다.
console.log('\n작품을 만든 사람');
{
  const made = (dir, o, label) => rel({ type: 'created', dir, other: o, edge_label: label, label: '제작' });
  const inwang = other('khs:INWANG', '인왕제색도', 'artwork', 'thing');
  const sehando = other('khs:SEHANDO', '세한도', 'artwork', 'thing');
  const uigam = other('khs:UIGAM', '동의보감', 'heritage', 'thing');
  const jeongun = other('khs:JEONGUN', '동국정운', 'heritage', 'thing');
  const jagyeongnu = other('khs:JAGYEONGNU', '자격루', 'heritage', 'thing');
  const bulhwa = other('khs:HOEAM', '회암사명 약사여래삼존도', 'heritage', 'thing');

  eq('그린 것', sentence(made('out', inwang, '그림'), { label: '정선', type: 'person' }),
     '정선이 인왕제색도를 그렸다');
  eq('글씨를 쓴 것', sentence(made('out', sehando, '글씨'), { label: '김정희', type: 'person' }),
     '김정희가 세한도의 글씨를 썼다');
  eq('지은 것', sentence(made('out', uigam, '저술'), { label: '허준', type: 'person' }),
     '허준이 동의보감을 지었다');
  eq('엮은 것', sentence(made('out', jeongun, '편찬'), { label: '신숙주', type: 'person' }),
     '신숙주가 동국정운을 엮었다');
  eq('만든 것', sentence(made('out', jagyeongnu, '제작'), { label: '장영실', type: 'person' }),
     '장영실이 자격루를 만들었다');
  eq('만들게 한 것', sentence(made('out', bulhwa, '발원'), { label: '문정왕후', type: 'person' }),
     '문정왕후가 회암사명 약사여래삼존도를 만들게 했다');
  // 작품 쪽에서 읽어도 만든 사람이 주어다
  eq('작품 쪽에서 봐도 같은 문장',
     sentence(made('in', other('wd:JEONGSEON', '정선'), '그림'), { label: '인왕제색도', type: 'artwork' }),
     '정선이 인왕제색도를 그렸다');
  // 산문 추출이 낸 옛 엣지에는 라벨이 없다
  eq('라벨이 없으면 만들었다', sentence(made('out', inwang, null), { label: '정선', type: 'person' }),
     '정선이 인왕제색도를 만들었다');

  // 묶음 머리 — 사람 쪽은 만든 것들의 목록, 작품 쪽은 만든 사람이다
  eq('사람 쪽 머리', relHead(made('out', inwang, '그림')), '그린 것');
  eq('작품 쪽 머리', relHead(made('in', other('wd:JEONGSEON', '정선'), '그림')), '그린 사람');
  eq('발원도 갈라 부른다', relHead(made('in', other('wd:MUNJEONG', '문정왕후'), '발원')), '만들게 한 사람');
  eq('라벨 없는 제작은 타입 이름 그대로', relHead(made('out', inwang, null)), '제작');
  // 김정희의 상세에서 '제작' 한 더미로 뭉치지 않는다
  const gc = groupRelations([made('out', sehando, '글씨'), made('out', uigam, '저술'),
                             made('out', jagyeongnu, '제작')]);
  eq('만든 방식마다 묶음이 선다', gc.groups.map((x) => x.head).join(','), '글씨를 쓴 것,지은 것,만든 것');
}

// --- 인과 -----------------------------------------------------------------
// "온톨로지 그래프이므로 인과관계를 보여줘야 한다 — 임진왜란 → 명의 쇠퇴 →
// 여진족의 성장 → 병자호란" (2026-09-04). 엣지는 원인 → 결과, 라벨이 종류다.
console.log('\n인과');
{
  const imjin = { label: '임진왜란', type: 'event' };
  const jin = other('wd:JIN', '후금', 'org', 'actor');
  const bj = other('wd:BJ', '병자호란', 'event', 'event');
  eq('나가는 인과는 이 노드가 원인', sentence(rel({ type: 'caused', dir: 'out', other: jin, edge_label: '배경' }), imjin),
     '임진왜란은 후금의 배경이 되었다');
  eq('들어오는 인과는 상대가 원인', sentence(rel({ type: 'caused', dir: 'in', other: jin, edge_label: '계기' }), { label: '정묘호란', type: 'event' }),
     '후금은 정묘호란의 계기가 되었다');
  eq('종류가 영향이면 영향을 주었다', sentence(rel({ type: 'caused', dir: 'out', other: jin, edge_label: '영향' }), imjin),
     '임진왜란은 후금에 영향을 주었다');
  eq('종류를 모르면 원인', sentence(rel({ type: 'caused', dir: 'out', other: bj }), imjin), '임진왜란은 병자호란의 원인이 되었다');
  eq('서술구가 있으면 그 구로 부른다',
     sentence(rel({ type: 'caused', dir: 'in', other: jin, edge_label: '원인', as: '후금의 파약 행위' }), { label: '병자호란', type: 'event' }),
     '후금의 파약 행위는 병자호란의 원인이 되었다');
  eq('원인 묶음 머리', relHead({ type: 'caused', dir: 'in', label: '원인' }), '원인');
  eq('결과 묶음 머리', relHead({ type: 'caused', dir: 'out', label: '원인' }), '결과');
  const tree = { center: 'wd:BJ',
    causes: [{ id: 'wd:JIN', kind: '배경', how: '형제 관계를 요구했다', as: '', evidence: [],
               children: [{ id: 'wd:IMJIN', kind: '배경', how: '명의 쇠퇴', as: '', evidence: [], children: [] }] }],
    effects: [],
    nodes: { 'wd:BJ': { label: '병자호란' }, 'wd:JIN': { label: '후금' }, 'wd:IMJIN': { label: '임진왜란', start: '1592' } } };
  const rows = chainRows(tree.causes);
  ok('나무를 줄로 펴면 깊이가 들여쓰기다', rows.length === 2 && rows[0].depth === 0 && rows[1].depth === 1 && rows[1].id === 'wd:IMJIN', JSON.stringify(rows));
  // 안내선: 형제가 아래에 더 있는 단만 세로선이 이어진다
  const forest = chainRows([
    { id: 'a', kind: '원인', children: [{ id: 'a1', kind: '배경', children: [] }, { id: 'a2', kind: '배경', children: [] }] },
    { id: 'b', kind: '원인', children: [] },
  ]);
  const guides = chainGuides(forest);
  ok('첫 줄은 아래에 형제(b)가 있어 세로선이 이어진다', guides[0].lines[0] === true && guides[0].last === false, JSON.stringify(guides));
  ok('a1 은 0단 선이 지나가고 1단에도 형제(a2)가 남았다', guides[1].lines[0] === true && guides[1].lines[1] === true && guides[1].last === false, JSON.stringify(guides[1]));
  ok('a2 는 그 단의 마지막이라 1단 선이 끊긴다', guides[2].lines[0] === true && guides[2].lines[1] === false && guides[2].last === true, JSON.stringify(guides[2]));
  ok('b 는 뿌리 단의 마지막이다', guides[3].lines[0] === false && guides[3].last === true, JSON.stringify(guides[3]));
  ok('자식이 있는 줄(a)만 점 아래로 줄기를 내린다', guides[0].stem === true && guides[1].stem === false && guides[2].stem === false && guides[3].stem === false, JSON.stringify(guides.map((g) => g.stem)));
  const steps = pathSteps([{ id: 'wd:IMJIN', edge: null }, { id: 'wd:JIN', edge: { kind: '배경', how: '명의 쇠퇴' } }, { id: 'wd:BJ', edge: { kind: '원인', how: '' } }], tree.nodes);
  eq('경로를 글로 읽는다', pathSentence(steps), '임진왜란 → (배경) 후금 → (원인) 병자호란');
  eq('걸음에 연도가 붙는다', steps[0].year, '1592년');
}

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);

console.log('\n검색 목록 키보드');
eq('아무것도 안 고른 채 ↓ 는 맨 위', moveCursor(-1, 'ArrowDown', 4), 0);
eq('아무것도 안 고른 채 ↑ 는 맨 아래', moveCursor(-1, 'ArrowUp', 4), 3);
eq('↓ 는 한 칸', moveCursor(0, 'ArrowDown', 4), 1);
eq('맨 아래서 ↓ 는 맨 위로 돈다', moveCursor(3, 'ArrowDown', 4), 0);
eq('맨 위서 ↑ 는 맨 아래로 돈다', moveCursor(0, 'ArrowUp', 4), 3);
eq('목록이 비면 -1', moveCursor(2, 'ArrowDown', 0), -1);
ok('한글 조립 중의 키는 입력기 것', imeKey({ key: 'ArrowDown', isComposing: true }) && imeKey({ key: 'Process', keyCode: 229 }));
ok('조립이 끝난 키는 우리 것', !imeKey({ key: 'ArrowDown', isComposing: false, keyCode: 40 }));
