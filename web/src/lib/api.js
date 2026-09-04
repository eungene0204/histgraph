// 그래프 API. 파이썬 서버(8100)가 SQLite 를 읽어 내주는 것들이다.
// 개발 중에는 Vite 가 /api 를 그리로 넘긴다 (vite.config.js).

async function get(path) {
  const res = await fetch(path);
  if (!res.ok && res.status !== 404) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export const api = {
  meta: () => get('/api/meta'),
  seeds: (limit = 12) => get(`/api/seeds?limit=${limit}`),
  search: (q, limit = 25) => get(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  node: (id) => get(`/api/node/${encodeURIComponent(id)}`),
  timeline: (id) => get(`/api/timeline?id=${encodeURIComponent(id)}`),
  // 인과 사슬. 한 노드의 원인·결과 나무와, 두 노드 사이의 최단 경로.
  chain: (id, depth = 4) => get(`/api/chain?id=${encodeURIComponent(id)}&depth=${depth}`),
  path: (from, to) => get(`/api/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  graph: (id, { depth = 2, limit = 120, includePeriod = false } = {}) =>
    get(`/api/graph?id=${encodeURIComponent(id)}&depth=${depth}`
      + `&limit=${limit}&exclude=${includePeriod ? '' : 'period'}`),
};
