// 프론트 개발 서버. API 는 파이썬(8100)이 그대로 맡고, 여기서는 화면만 다시
// 그린다 — `/api` 를 프록시로 넘기므로 브라우저는 한 포트만 본다.
//
// 터미널 하나면 된다:  npm run dev   (API 까지 함께 뜬다)
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const here = (name) => fileURLToPath(new URL(name, import.meta.url));

// **개인 역사(life.html)를 배포한다** (2026-09-09 사용자: "개인 역사도 이제 배포
// 해줘"). 2026-09-07 에 걸어 둔 `!process.env.VERCEL` 을 푼 자리다 — 그때는
// 이야기를 읽는 길이 로컬 서버(스레드+폴링)에만 있어 배포에 내면 껍데기였다.
// 지금은 배포도 같은 몸통을 요청 하나 안에서 돈다 (`server.life_post`).
// 켜고 끄는 자리는 여전히 여기 하나다 — 화면 코드는 `import.meta.env.VITE_LIFE`
// 만 본다.
export const LIFE_PAGE = true;

// 서치 콘솔이 주인을 확인하는 표. 값이 있을 때만 장마다 한 줄이 붙는다 —
// 빈 값을 적어 두면 구글이 그 자리를 보고 '표가 틀렸다'고 답한다. 서버가
// 찍는 장(`histgraph.pages`)은 같은 이름의 환경변수를 제 손으로 읽는다.
const verification = (process.env.HISTGRAPH_SITE_VERIFICATION || '').trim();
const verifyTag = {
  name: 'histgraph-site-verification',
  transformIndexHtml: (html) =>
    verification
      ? html.replace('</head>',
          `<meta name="google-site-verification" content="${verification}">\n</head>`)
      : html,
};

export default {
  root: '.',
  plugins: [react(), verifyTag],
  define: { 'import.meta.env.VITE_LIFE': JSON.stringify(LIFE_PAGE ? '1' : '') },
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
      // 관리실은 서버가 통째로 그려 준다 (`histgraph.console`). 여기 목록에
      // 없으면 개발 서버가 자기 index.html 을 내주어 그래프 화면이 뜬다.
      '/console': {
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
        // 개인 역사 — 그래프와 다른 앱(React 뿌리)이라 장을 따로 낸다. 로컬만.
        ...(LIFE_PAGE ? { life: here('life.html') } : {}),
      },
    },
  },
};
