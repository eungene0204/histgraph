// 내 역사가 **브라우저에 남는 자리** — 읽고, 남기고, 지우는 한 길.
//
// 왜 따로 두는가. 계정에 담아 둔 내 역사는 세션 쿠키로 갈린다 — 서버가
// `user_id` 로만 찾으므로 남의 것을 부를 길이 없다 (src/histgraph/auth.py
// `life_doc`). **브라우저는 그렇지 않다.** localStorage 는 사람이 아니라
// 기기에 붙어서, 갑이 쓰고 나간 컴퓨터에서 을이 열면 같은 자리를 읽는다.
// 2026-09-11 점검에서 실제로 그랬다: 갑이 로그아웃해도 `life-json` 이 남고,
// 을이 로그인하면 계정이 빈 을에게 갑의 연표가 서고, 그것이 **을의 계정으로
// 저장까지** 됐다 (LifeView 의 부팅이 브라우저에 남은 것을 계정으로 올린다).
//
// 그래서 규칙 하나를 여기 한 곳에 둔다: **남기는 자료에는 주인을 적고,
// 지금 보는 사람과 다르면 읽지 않고 지운다.**
//
// 주인 표는 서버가 준다 (`/api/me` 의 `owner` — 사용자 번호의 HMAC, 되돌릴
// 수 없고 기기가 달라도 같다). 로그인하지 않은 사람은 빈 표(`''`)다.
//
//   적힌 표      지금 사람    어떻게
//   ─────────────────────────────────────────────────────────────
//   없음          누구든      쓴다 (로그인 전에 적은 글 — 주인이 아직 없다)
//   ''(비로그인)  갑          쓴다 · 갑의 표를 적는다 (그 사람이 로그인한 것)
//   갑            갑          쓴다
//   갑            을·비로그인 **지운다** (남의 것이다)
//
// 마지막 줄이 로그아웃에 기대지 않는 것이 요점이다 — 창을 닫고 갔든 세션이
// 만료됐든, 다음 사람이 여는 순간 걸린다. 지워도 잃는 것은 없다: 로그인한
// 사람의 문서는 적을 때마다 계정에 함께 올라간다 (LifeView `keepInAccount`).

// 브라우저에 두는 열쇠 넷. **모두 한 사람의 것이다** — 문서만 지우고 이야기
// 기록을 남기면, 다음 사람의 화면에 앞사람이 적은 글이 그대로 선다.
export const STORE_KEY = 'life-json';           // 내 역사 문서
export const OWNER_KEY = 'life-owner';          // 그 문서의 주인 표
export const NEXT_KEY = 'life-stories-next';    // 분석에 실어 보낸 이야기
export const FAIL_KEY = 'life-failed';          // 모델이 못 읽은 글

// localStorage 는 없을 수 있고(서버 렌더·사생활 보호 창) 던지기도 한다.
// 없으면 **아무것도 기억하지 못하는 것으로 친다** — 화면은 그래도 돈다.
function box(store) {
  if (store) return store;
  try { return globalThis.localStorage || null; } catch { return null; }
}

/** `/api/me` 가 준 신원에서 주인 표를 꺼낸다. 로그인하지 않았으면 빈 글자. */
export function ownerOf(me) {
  return (me && me.user && typeof me.owner === 'string') ? me.owner : '';
}

/** 이 브라우저에 적힌 주인 표. 적힌 적이 없으면 null (주인 없는 글). */
export function markedOwner(store) {
  const ls = box(store);
  if (!ls) return null;
  try {
    const got = ls.getItem(OWNER_KEY);
    return got === null ? null : got;
  } catch { return null; }
}

/** 개인 자료를 브라우저에서 **전부** 지운다. 되돌릴 수 없다. */
export function forgetLife(store) {
  const ls = box(store);
  if (!ls) return;
  for (const key of [STORE_KEY, OWNER_KEY, NEXT_KEY, FAIL_KEY]) {
    try { ls.removeItem(key); } catch { /* 못 지워도 나머지는 지운다 */ }
  }
}

/**
 * 이 브라우저에 남은 내 역사. **지금 보는 사람의 것이 아니면 지우고 null.**
 *
 * `owner` 는 `ownerOf(await auth.me())` — 로그인하지 않았으면 빈 글자다.
 */
export function readLife(owner = '', store) {
  const ls = box(store);
  if (!ls) return null;
  const mark = markedOwner(ls);
  if (mark !== null && mark !== '' && mark !== owner) {
    forgetLife(ls);           // 남의 삶이다. 다음 사람이 열기 전에 여기서 끝낸다.
    return null;
  }
  let raw = null;
  try { raw = ls.getItem(STORE_KEY); } catch { return null; }
  if (!raw) return null;
  try {
    const doc = JSON.parse(raw);
    return (doc && typeof doc === 'object') ? doc : null;
  } catch { return null; }
}

/**
 * 내 역사를 브라우저에 남기고 **주인을 적는다.** 못 남겨도 화면은 돈다.
 *
 * 로그인하지 않은 사람이 적은 글에는 빈 표가 적히고, 그 사람이 로그인하면
 * 다음 저장에서 자기 표로 바뀐다 — 그때부터 남이 못 읽는다.
 */
export function writeLife(doc, owner = '', store) {
  const ls = box(store);
  if (!ls || !doc) return false;
  try {
    ls.setItem(STORE_KEY, JSON.stringify(doc));
    ls.setItem(OWNER_KEY, owner || '');
    return true;
  } catch { return false; }
}

/** 이야기 기록·못 보낸 글처럼 문서 곁에 두는 것. 주인은 문서와 함께 적힌다. */
export function readSide(key, owner = '', store) {
  const ls = box(store);
  if (!ls) return null;
  const mark = markedOwner(ls);
  if (mark !== null && mark !== '' && mark !== owner) { forgetLife(ls); return null; }
  try { return ls.getItem(key); } catch { return null; }
}

export function writeSide(key, value, owner = '', store) {
  const ls = box(store);
  if (!ls) return;
  try {
    if (value === null || value === undefined || value === '') ls.removeItem(key);
    else { ls.setItem(key, value); ls.setItem(OWNER_KEY, owner || ''); }
  } catch { /* 못 남겨도 이번 자리에서는 들고 있다 */ }
}
