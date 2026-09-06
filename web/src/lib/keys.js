// 검색 목록의 키보드 처리. 컴포넌트 밖에 두는 것은 브라우저 없이 재기 위해서다.

// 한글 입력기가 글자를 조립하는 동안(isComposing) 온 키는 입력기의 것이다.
// 맥에서 '명성황후'의 '후'를 조립하는 채로 ↓ 를 누르면 브라우저가 keydown 을
// **두 번** 낸다 — 조립을 끝내는 것(isComposing=true) 하나, 그 뒤 진짜
// 하나. 둘 다 받으면 커서가 -1 → 0 → 1 로 뛰어 맨 위 결과를 영영 못 고른다
// (2026-09-06 지적). keyCode 229 는 옛 크롬이 조립 중 키에 주는 값.
export function imeKey(ev) {
  return Boolean(ev.isComposing) || ev.keyCode === 229;
}

// ↓·↑ 로 커서를 옮긴다. -1 은 '아직 아무것도 안 골랐다' — ↓ 는 맨 위로,
// ↑ 는 맨 아래로 간다. 끝에서는 반대편으로 돈다.
export function moveCursor(cursor, key, count) {
  if (!count) return -1;
  if (key === 'ArrowDown') return cursor < 0 ? 0 : (cursor + 1) % count;
  if (key === 'ArrowUp') return cursor < 0 ? count - 1 : (cursor + count - 1) % count;
  return cursor;
}
