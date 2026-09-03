// 프론트 개발 서버. API 는 파이썬(8100)이 그대로 맡고, 여기서는 화면만 다시
// 그린다 — `/api` 를 프록시로 넘기므로 브라우저는 한 포트만 본다.
//
// 터미널 둘:
//   npm run dev:api    8100 — 그래프 API
//   npm run dev        5173 — 화면 (HMR)
export default {
  root: '.',
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
  },
}
