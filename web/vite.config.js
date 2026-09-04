// 프론트 개발 서버. API 는 파이썬(8100)이 그대로 맡고, 여기서는 화면만 다시
// 그린다 — `/api` 를 프록시로 넘기므로 브라우저는 한 포트만 본다.
//
// 터미널 하나면 된다:  npm run dev   (API 까지 함께 뜬다)
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const here = (name) => fileURLToPath(new URL(name, import.meta.url));

export default {
  root: '.',
  plugins: [react()],
  server: {
    // 기본값(localhost)은 이 맥에서 IPv6 [::1] 에만 붙어, 127.0.0.1:5173 이
    // 연결 거부로 떨어졌다. API 는 127.0.0.1:8100 이라 둘이 갈리면 주소를
    // 바꿔 칠 때마다 걸린다 — 같은 스택에 세운다.
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // 화면은 한 장(index.html)이지만 문서 두 장은 따로 낸다. 광고 심사가
    // 보는 페이지라 자바스크립트 없이 열려야 하고, 그래프 화면의 CSS(body
    // 를 flex·overflow:hidden 으로 잡는다)를 물려받으면 글이 잘린다.
    rollupOptions: {
      input: {
        main: here('index.html'),
        privacy: here('privacy.html'),
        terms: here('terms.html'),
      },
    },
  },
};
