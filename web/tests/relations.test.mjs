// 관계 → 사람이 읽는 말. 브라우저 없이 돈다.
//
//   node web/tests/relations.test.mjs
//
// 여기 걸린 것들은 대부분 화면에서 실제로 났던 오류다. 옮기면서 방어가
// 같이 따라왔는지를 잰다.
import {
  pt, sentence, groupRelations, relHead, byYear, cardsFor,
  whyEmpty, fmtDate, chainRows, pathSteps, pathSentence, farEnds,
} from '../src/lib/relations.js';

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
eq('기원전', fmtDate('-0057-01-01'), '기원전 57년');
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
  const steps = pathSteps([{ id: 'wd:IMJIN', edge: null }, { id: 'wd:JIN', edge: { kind: '배경', how: '명의 쇠퇴' } }, { id: 'wd:BJ', edge: { kind: '원인', how: '' } }], tree.nodes);
  eq('경로를 글로 읽는다', pathSentence(steps), '임진왜란 → (배경) 후금 → (원인) 병자호란');
  eq('걸음에 연도가 붙는다', steps[0].year, '1592년');
  const ends = farEnds(tree);
  ok('먼 끝은 두 걸음 이상 떨어진 잎만', ends.length === 1 && ends[0].id === 'wd:IMJIN' && ends[0].side === 'cause' && ends[0].depth === 1, JSON.stringify(ends));
  ok('한 걸음짜리만 있으면 먼 끝이 없다', farEnds({ causes: [{ id: 'a', children: [] }], effects: [] }).length === 0);
}

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
