// 테마 부팅. CSS 가 읽히기 전에 <html data-theme> 를 박아 첫 그림이 옳은 색으로
// 뜨게 한다 — React 가 뜬 뒤 바꾸면 어두운 화면이 한 번 번쩍인다.
// 저장 키는 'theme' ('light' | 'dark'). 없으면 운영체제 설정을 따른다.
// 그래프 화면·방침·약관 세 장이 같은 파일을 부른다 (src/lib/theme.js 와 같은 규칙).
(function () {
  var t = null;
  try { t = localStorage.getItem('theme'); } catch (e) { /* 저장소 없음 */ }
  if (t !== 'light' && t !== 'dark') {
    t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  }
  document.documentElement.dataset.theme = t;
})();
