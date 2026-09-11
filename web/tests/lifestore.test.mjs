// 내 역사가 브라우저에 남는 자리 — **누구의 것인가**를 재는 규칙.
//
//   node web/tests/lifestore.test.mjs
//
// 여기서 재는 것은 틀리면 **남의 삶이 남에게 보이는** 자리다 (2026-09-11 점검:
// 갑이 로그아웃해도 `life-json` 이 남아, 을이 로그인하면 갑의 연표가 서고
// 그것이 을의 계정으로 저장까지 됐다). 브라우저 없이 돈다 — localStorage 는
// 흉내 낸 상자를 넣어 준다.
import { readLife, writeLife, forgetLife, readSide, writeSide, ownerOf, markedOwner, localAfterAccount, STORE_KEY, OWNER_KEY, NEXT_KEY, FAIL_KEY } from '../src/lib/lifestore.js';

let pass = 0;
let fail = 0;
function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? `  — ${extra}` : ''}`); }
}

// 흉내 낸 localStorage. 진짜와 같은 것 셋만 낸다.
function fakeBox(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    get size() { return map.size; },
    keys: () => [...map.keys()],
  };
}

const 갑 = 'owner-gap-tag';
const 을 = 'owner-eul-tag';
const doc = (name) => ({ subject: { name }, nodes: [{ id: 'me', name }] });

console.log('\n내 역사 — 브라우저에 남은 것의 주인');
{
  // 1) 주인 표는 로그인한 사람에게만 있다.
  ok('로그인한 사람의 표를 꺼낸다', ownerOf({ user: { 이름: '갑' }, owner: 갑 }) === 갑);
  ok('로그인하지 않으면 빈 표', ownerOf({ enabled: true, user: null, owner: 갑 }) === '');
  ok('신원을 못 받았으면 빈 표', ownerOf(null) === '');

  // 2) 내 것은 읽는다.
  const mine = fakeBox();
  writeLife(doc('갑'), 갑, mine);
  ok('남긴 자료에 주인이 함께 적힌다', markedOwner(mine) === 갑);
  ok('주인이 같으면 읽는다', readLife(갑, mine)?.subject.name === '갑');

  // 3) **남의 것은 읽지 않고 지운다.** 이 줄이 이 파일의 이유다.
  const shared = fakeBox();
  writeLife(doc('갑'), 갑, shared);
  writeSide(NEXT_KEY, '["갑이 적은 이야기"]', 갑, shared);
  writeSide(FAIL_KEY, '갑이 보냈다 실패한 글', 갑, shared);
  ok('다음 사람에게는 아무것도 주지 않는다', readLife(을, shared) === null);
  ok('그 자리에서 지운다 (다음에 열어도 없다)',
     shared.getItem(STORE_KEY) === null && shared.getItem(OWNER_KEY) === null,
     shared.keys().join(','));
  ok('곁에 둔 이야기·못 보낸 글도 함께 지운다',
     shared.getItem(NEXT_KEY) === null && shared.getItem(FAIL_KEY) === null,
     shared.keys().join(','));

  // 4) 로그아웃한 뒤(= 아무도 아닌 사람)에도 같다. 로그아웃이 지우는 것에
  //    기대지 않는다 — 창을 닫고 갔거나 세션이 만료됐을 수 있다.
  const left = fakeBox();
  writeLife(doc('갑'), 갑, left);
  ok('로그인하지 않은 사람에게도 안 보인다', readLife('', left) === null);
  ok('그때도 지운다', left.getItem(STORE_KEY) === null);

  // 5) 주인 없는 글(로그인 전에 적은 것)은 누구의 것도 아니라 살아 있다 —
  //    그 사람이 로그인하면 그때 표가 붙는다.
  const anon = fakeBox();
  writeLife(doc('나'), '', anon);
  ok('로그인 전에 적은 글은 그대로 읽는다', readLife('', anon)?.subject.name === '나');
  ok('그 글은 로그인한 사람이 이어받는다', readLife(갑, anon)?.subject.name === '나');
  writeLife(readLife(갑, anon), 갑, anon);
  ok('이어받으면 표가 붙는다 (그때부터 남이 못 읽는다)',
     markedOwner(anon) === 갑 && readLife(을, anon) === null);

  // 6) 옛 자료 — 이 규칙이 생기기 전에 남은 것에는 표가 없다. 지우지 않는다
  //    (그 컴퓨터 주인의 것이다). 다음 저장에서 표가 붙는다.
  const old = fakeBox({ [STORE_KEY]: JSON.stringify(doc('옛것')) });
  ok('표가 없던 옛 자료는 살려 둔다', readLife(갑, old)?.subject.name === '옛것');

  // 7) 통째로 버리면 네 자리가 다 빈다.
  const all = fakeBox();
  writeLife(doc('갑'), 갑, all);
  writeSide(NEXT_KEY, '["글"]', 갑, all);
  writeSide(FAIL_KEY, '못 보낸 글', 갑, all);
  forgetLife(all);
  ok('버리면 남는 것이 없다', all.size === 0, all.keys().join(','));

  // 8) **계정에서 지운 것은 사본이 되살리지 않는다** (2026-09-11 "아직 내 역사가
  //    보이는데?"). 계정을 지웠더니 화면이 브라우저 사본을 집어 그리고 그것을
  //    계정에 다시 올렸다.
  const gone = fakeBox();
  writeLife(doc('갑'), 갑, gone);
  const after = localAfterAccount({ owner: 갑, accountRead: true, accountHasDoc: false }, gone);
  ok('계정에서 지웠으면 브라우저 사본도 따라 지운다',
     after === null && gone.getItem(STORE_KEY) === null, gone.keys().join(','));

  const still = fakeBox();
  writeLife(doc('갑'), 갑, still);
  ok('계정에 있으면 그대로 (계정 것을 쓴다)',
     localAfterAccount({ owner: 갑, accountRead: true, accountHasDoc: true }, still)?.subject.name === '갑'
     && !!still.getItem(STORE_KEY));

  const offline = fakeBox();
  writeLife(doc('갑'), 갑, offline);
  ok('계정을 못 읽었으면 아무 판단도 하지 않는다',
     localAfterAccount({ owner: 갑, accountRead: false, accountHasDoc: false }, offline)?.subject.name === '갑'
     && !!offline.getItem(STORE_KEY));

  const first = fakeBox();
  writeLife(doc('나'), '', first);
  ok('로그인 전에 적은 글(빈 표)은 계정이 비어도 이어받는다',
     localAfterAccount({ owner: 갑, accountRead: true, accountHasDoc: false }, first)?.subject.name === '나'
     && !!first.getItem(STORE_KEY));

  // 표가 **없는 것**은 빈 표와 다르다 — 표가 생기기 전에 남은 사본이고, 그때는
  // 로그인한 채로 적어 계정에 올렸다. 계정이 비었다면 지운 것이다.
  const legacy = fakeBox({ [STORE_KEY]: JSON.stringify(doc('옛것')) });
  ok('표가 없는 옛 사본은 계정이 비었으면 지운다',
     localAfterAccount({ owner: 갑, accountRead: true, accountHasDoc: false }, legacy) === null
     && legacy.getItem(STORE_KEY) === null);
  const legacy2 = fakeBox({ [STORE_KEY]: JSON.stringify(doc('옛것')) });
  ok('표가 없어도 로그인하지 않았으면 건드리지 않는다',
     localAfterAccount({ owner: '', accountRead: false, accountHasDoc: false }, legacy2)?.subject.name === '옛것');

  // 9) 상자가 없거나 던져도 화면은 돈다.
  const broken = {
    getItem() { throw new Error('막혀 있다'); },
    setItem() { throw new Error('막혀 있다'); },
    removeItem() { throw new Error('막혀 있다'); },
  };
  ok('저장이 막힌 창에서도 터지지 않는다',
     readLife(갑, broken) === null && writeLife(doc('갑'), 갑, broken) === false);
  ok('곁의 자리도 마찬가지', readSide(NEXT_KEY, 갑, broken) === null);
}

console.log(`\n  ${pass} 통과 · ${fail} 실패`);
process.exit(fail ? 1 : 0);
