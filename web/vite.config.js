// 프론트 개발 서버. API 는 파이썬(8100)이 그대로 맡고, 여기서는 화면만 다시
// 그린다 — `/api` 를 프록시로 넘기므로 브라우저는 한 포트만 본다.
//
// 터미널 둘:
//   npm run dev:api    8100 — 그래프 API
//   npm run dev        5173 — 화면 (HMR)
export default {
  root: '.',
  server: {
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
