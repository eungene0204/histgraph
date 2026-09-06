import { StrictMode } from 'react';
import '../style.css';
import { createRoot } from 'react-dom/client';
import LifeView from './components/LifeView.jsx';

// 개인 역사 화면의 진입점 (/life.html). 그래프 화면(main.jsx)과 CSS 를
// 같이 쓰고 React 뿌리만 다르다 — 한 장에 두 앱을 겹치지 않는다.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <LifeView />
  </StrictMode>,
);
