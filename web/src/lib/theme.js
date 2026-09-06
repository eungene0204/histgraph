// 라이트/다크 테마. 진실은 <html data-theme> 하나다 — CSS 는 [data-theme="light"]
// 선택자로, 캔버스(graph-view.js)는 isLight() 로 같은 값을 읽는다.
// 첫 값은 public/theme-boot.js 가 화면이 그려지기 전에 박아 둔다.
const KEY = 'theme';

export function currentTheme() {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function isLight() {
  return currentTheme() === 'light';
}

export function applyTheme(theme) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem(KEY, t); } catch { /* 저장 못 해도 이번 화면은 바뀐다 */ }
  return t;
}

export function toggleTheme() {
  return applyTheme(isLight() ? 'dark' : 'light');
}
