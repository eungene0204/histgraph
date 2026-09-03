import { StrictMode } from 'react';
// **CSS 는 여기서 들여온다.** index.html 에 <link rel="stylesheet"> 로 걸면
// Vite 가 개발 중 CSS 를 HMR 용 JS 모듈로 감싸 내주는 탓에 MIME 이 안 맞아
// 통째로 적용되지 않는다 (화면이 하얗게 뜬다). 빌드에서도 이쪽이 맞다 —
// 번들러가 의존성으로 잡아 해시 붙은 파일로 낸다.
import '../style.css';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

// StrictMode 는 개발 중 효과를 두 번 돌린다. GraphView·TimelineRail 이
// destroy() 로 자기 뒷정리를 하므로 그걸 켜 두고 산다 — 정리를 빠뜨리면
// 여기서 바로 드러난다 (RAF 루프가 둘, 배치가 두 번 튄다).
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
