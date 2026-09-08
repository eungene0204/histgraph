// 가입·로그인 — 화면 쪽. 서버는 src/histgraph/auth.py 다.
//
// **여기에는 토큰이 없다.** 세션은 자바스크립트가 못 읽는 쿠키(HttpOnly)에
// 있고, 이 파일이 만지는 것은 상태를 바꾸는 요청에 실어 보내는 표 하나뿐이다
// (`hg_csrf`). 그래서 이 파일이 새어도 남의 자리에 앉을 수 없다.
//
// 규칙 둘:
//  - 상태를 바꾸는 요청(POST·PUT·DELETE)에는 반드시 표를 싣는다. 안 실으면
//    서버가 400 으로 돌려보낸다 (auth.check_write).
//  - 서버가 주는 오류 문구는 **한국어 문장이다.** 그대로 화면에 옮긴다 —
//    여기서 영어 상태코드를 지어내지 않는다.

// 서버가 https 에서는 `__Host-` 를 붙인다 (auth.cookie_name). 개발(http)과
// 배포(https)가 같은 코드를 지나므로 둘 다 찾아본다.
export function csrf() {
  for (const part of document.cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === '__Host-hg_csrf' || name === 'hg_csrf') return rest.join('=');
  }
  return '';
}

async function call(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (method !== 'GET') {
    headers['X-Histgraph-CSRF'] = csrf();
    if (body !== undefined) headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, {
    method,
    headers,
    // 쿠키는 같은 출처라 기본으로 실리지만, 명시해 두면 나중에 주소가
    // 갈려도 조용히 로그아웃되지 않는다.
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload = null;
  try { payload = await res.json(); } catch { /* 본문이 없을 수 있다 */ }
  if (!res.ok) {
    const err = new Error(payload?.error || '요청을 처리하지 못했습니다.');
    err.status = res.status;
    throw err;
  }
  return payload;
}

// 신원과 즐겨찾기 목록은 **화면 전체가 하나씩만 묻는다.** 머리 줄의 계정과
// 상세의 별이 따로 물으면 노드를 옮길 때마다 요청이 두 배가 된다. 약속을
// 들고 있다가 그대로 나눠 준다 (`force` 로 다시 묻는다).
let mePromise = null;
let markPromise = null;

export const auth = {
  // 켜져 있는가 · 나는 누구인가. 화면이 맨 처음 묻는 것.
  // 서버가 꺼져 있거나 못 닿으면 **없는 것으로 친다** — 그래프는 로그인
  // 없이도 다 보이므로, 이것 때문에 화면이 멈추면 안 된다.
  me: (force = false) => {
    if (force || !mePromise) {
      mePromise = call('/api/me').catch(() => ({ enabled: false, user: null }));
    }
    return mePromise;
  },

  // 구글 동의 화면으로. 돌아올 자리를 들려 보낸다 (서버가 우리 사이트
  // 안의 경로인지 다시 확인한다 — auth._safe_next).
  login: (next = location.pathname + location.search + location.hash) => {
    location.href = `/api/auth/google?next=${encodeURIComponent(next)}`;
  },

  logout: () => call('/api/auth/logout', { method: 'POST' }),

  // 회원 탈퇴. 가입자 줄과 남긴 것이 함께 지워진다 (되돌릴 수 없다).
  withdraw: () => call('/api/me', { method: 'DELETE' }),

  bookmarks: {
    list: () => call('/api/my/bookmarks'),

    // 담아 둔 것들의 id. 노드를 옮길 때마다 서버에 묻지 않으려고 한 번만
    // 받아 들고 있는다 — 담고 빼는 것은 아래에서 이 집합도 같이 고친다.
    ids: (force = false) => {
      if (force || !markPromise) {
        markPromise = call('/api/my/bookmarks')
          .then((r) => new Set((r.목록 || []).map((m) => m.id)))
          .catch(() => new Set());
      }
      return markPromise;
    },

    add: async (id, label, note = '') => {
      await call('/api/my/bookmarks', { method: 'POST', body: { id, label, note } });
      (await auth.bookmarks.ids()).add(id);
    },
    remove: async (id) => {
      await call(`/api/my/bookmarks?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      (await auth.bookmarks.ids()).delete(id);
    },
  },

  // 내 역사 — 지금은 브라우저에만 있어 기기를 바꾸면 사라지는 것.
  life: {
    load: () => call('/api/my/life'),
    save: (doc) => call('/api/my/life', { method: 'PUT', body: { doc } }),
    remove: () => call('/api/my/life', { method: 'DELETE' }),
  },
};
