"""관리실 — `/console`. 지금은 가입자 목록 한 장이다.

**왜 auth 옆에 사는가.** 여기서 보는 것은 그래프가 아니라 **사람**이다.
가입자 표를 여는 길(`accounts.open_store`)과 '이 요청을 보낸 사람이
누구인가'(`auth.current_user`)를 그대로 쓰고, 응답도 auth 의 것을 쓴다 —
`auth.Response` 는 만들어질 때부터 `Cache-Control: private, no-store` 와
`Vary: Cookie` 를 들고 나간다. 그래프 쪽 응답처럼 엣지에 재웠다가는 **한
관리자의 화면이 다음 사람에게 배달된다.**

**문은 서버에서 잠근다.** 화면에서 단추를 감추는 것은 잠금이 아니다 —
주소를 직접 치면 열린다. 여기서는 세션 쿠키로 사람을 확인하고
`HISTGRAPH_ADMIN_EMAILS` 에 그 이메일이 있을 때만 표를 읽는다. 관리자가
아니면 **가입자가 몇 명인지도 말하지 않는다.**

**주소가 둘인 이유.** 로컬(`histgraph serve`)에는 `/console` 로 오지만,
배포에서는 rewrite 가 `/api?__p=console` 로 넘겨 `auth.route` 가 보는
경로가 `/api/console` 이 된다 (`vercel.json` · `pages.route` 와 같은 사정).
그래서 표에 두 이름을 함께 적는다 (`auth.ROUTES`).

여기 글자는 사람이 읽는 것이라 한국어다 (CLAUDE.md §1). **가입자의 이메일과
이름만이 영어일 수 있다** — 그것은 우리가 쓴 글이 아니라 그 사람의 것이다.
"""

from __future__ import annotations

import datetime
import logging
from html import escape

from . import accounts

log = logging.getLogger(__name__)

PATHS = ("/console", "/api/console")

# 한 장에 세우는 최대 인원. 넘으면 최근 순으로 자르고 몇 명이 더 있는지 적는다.
LIMIT = 500


def page(req):
    """`/console` 한 장. 관리자가 아니면 목록을 만들지 않는다."""
    from . import auth

    try:
        user = auth.current_user(req)
    except accounts.StoreError as err:
        log.warning("가입자 표 접근 실패: %s", err)
        return _html(_note("가입자 정보에 닿지 못했습니다."), 503)
    if not user:
        return _html(_note("관리자 계정으로 로그인한 뒤에 볼 수 있는 자리입니다.",
                           login=True), 401)
    if not user["admin"]:
        # 관리자가 아닌 사람에게는 **여기가 무엇을 담고 있는지도** 말하지 않는다.
        return _html(_note("이 자리를 볼 수 있는 계정이 아닙니다."), 403)

    try:
        db = auth.db()
        rows = db.query(
            "select id, email, name, created_at, last_login_at, disabled "
            "from users order by created_at desc, id desc limit $1", [LIMIT])
        total = int((db.one("select count(*) as n from users") or {}).get("n") or 0)
    except accounts.StoreError as err:
        log.warning("가입자 표 접근 실패: %s", err)
        return _html(_note("가입자 정보에 닿지 못했습니다."), 503)

    return _html(render(rows, total, user))


def _html(body: str, status: int = 200):
    from . import auth
    return auth.Response(status, body.encode("utf-8"),
                         ctype="text/html; charset=utf-8")


def _note(message: str, login: bool = False) -> str:
    """문이 열리지 않았을 때의 한 장. **로그인 자리를 여기서 준다** —
    돌아올 곳을 `/console` 로 적어 두지 않으면, 로그인을 마친 사람이
    처음 화면에 떨어져 주소를 다시 쳐야 한다."""
    link = ('<a class="go" href="/api/auth/google?next=/console">구글 계정으로 로그인</a>'
            if login else '<a class="go" href="/">처음 화면으로</a>')
    return _shell(f'''
<main>
  <h1>관리실</h1>
  <p class="sub">{escape(message)}</p>
  {link}
</main>
''')


def store_name() -> str:
    """어느 표를 보고 있는지 한국어로. **로컬과 배포를 섞어 보면 잘못 읽는다** —
    이 컴퓨터의 표에는 나 혼자 있어서 '가입자 한 명'으로 보인다 (2026-09-09 실제).
    `accounts.where()` 는 파일 이름과 제품 이름을 그대로 내므로 여기서는 안 쓴다
    (화면에 한글 아닌 글을 세우지 않는다 — CLAUDE.md §1)."""
    from . import neon
    return "배포 가입자 표" if neon.configured() else "이 컴퓨터의 가입자 표"


# 두 저장소 다 **세계시로 적는다** (Postgres `now()` · SQLite
# `CURRENT_TIMESTAMP`). 그대로 세우면 저녁에 가입한 사람이 오전에 온 것으로
# 보인다 — 읽는 사람은 한국에 있다.
KST = datetime.timezone(datetime.timedelta(hours=9))


def when(value: object) -> str:
    """저장소가 준 시각을 한국 시각 `2026-09-09 03:57` 로.

    Neon 은 `2026-09-08 18:57:56.299034+00`, SQLite 는 `2026-09-08 18:57:56`
    으로 준다. 시간대가 안 적혀 있으면 **세계시로 친다** — 두 저장소가 그렇게
    적기 때문이다. 못 읽으면 온 대로 앞 열여섯 자만 세운다."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        got = datetime.datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return text.replace("T", " ")[:16]
    if got.tzinfo is None:
        got = got.replace(tzinfo=datetime.timezone.utc)
    return got.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def render(rows: list[dict], total: int, admin: dict) -> str:
    """가입자 목록 한 장."""
    if rows:
        body = "\n".join(_row(i, r, total) for i, r in enumerate(rows))
        table = (
            '<table><thead><tr>'
            '<th class="num">#</th><th>이메일</th><th>이름</th>'
            '<th>가입일</th><th>마지막 로그인</th><th>상태</th>'
            f'</tr></thead><tbody>\n{body}\n</tbody></table>'
        )
    else:
        table = '<p class="empty">아직 가입한 사람이 없습니다.</p>'

    more = (f'<p class="empty">최근 {len(rows):,}명까지만 세웠습니다 '
            f'— {total - len(rows):,}명이 더 있습니다.</p>'
            if total > len(rows) else "")

    return _shell(f"""
<main>
  <h1>가입자</h1>
  <p class="sub">모두 <b>{total:,}</b>명 · {store_name()}를 읽었습니다. 시각은 한국 시각입니다.</p>
  {table}
  {more}
  <p class="who">{escape(admin["email"])} 로 보고 있습니다.</p>
</main>
""")


def _row(i: int, r: dict, total: int) -> str:
    """줄 하나. 번호는 **가입한 차례**다 — 목록은 최근 순이라 거꾸로 센다."""
    name = (r.get("name") or "").strip()
    state = '<span class="off">중지</span>' if r.get("disabled") else "쓰는 중"
    return (
        f'<tr><td class="num">{total - i}</td>'
        f'<td class="mail">{escape(r.get("email") or "")}</td>'
        f'<td>{escape(name) or "<span class=dash>—</span>"}</td>'
        f'<td class="when">{escape(when(r.get("created_at")))}</td>'
        f'<td class="when">{escape(when(r.get("last_login_at")))}</td>'
        f'<td>{state}</td></tr>'
    )


# 그래프 화면(`web/style.css`)·문서 장(`pages.STYLE`)과 **같은 색을 쓴다.**
# 광고와 방문 통계는 부르지 않는다 — 여기는 사람이 검색으로 닿을 자리가
# 아니고, 남의 스크립트에 가입자 이름을 보여 줄 이유도 없다.
STYLE = """
:root {
  color-scheme: dark;
  --bg: #1e1e1e; --bg2: #262626; --line: #363636;
  --text: #dadada; --text-2: #b3b3b3; --text-3: #666;
  --accent: hsl(254 80% 68%); --off: #fb6c13;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
          "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body { margin: 0; background: var(--bg); color: var(--text);
       font-family: var(--font); font-size: 15px; line-height: 1.5;
       -webkit-font-smoothing: antialiased; }
.top { border-bottom: 1px solid var(--line); background: var(--bg2); }
.top a { display: flex; align-items: center; gap: 8px; max-width: 900px;
         margin: 0 auto; padding: 10px 22px; color: var(--text);
         text-decoration: none; font-weight: 600; font-size: 13px; }
.top .mark { width: 13px; height: 13px; border-radius: 50%; background: #3d84f5;
             box-shadow: 9px 5px 0 -3px #fb6c13, 16px -3px 0 -4px #2e9e5e; }
.top .back { margin-left: auto; font-weight: 400; font-size: 12px; color: var(--text-2); }
.top a:hover .back { color: var(--accent); }
main { max-width: 900px; margin: 0 auto; padding: 32px 22px 70px; }
h1 { font-size: 20px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { margin: 0 0 22px; color: var(--text-2); font-size: 13px; }
.sub b { color: var(--text); font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--line);
         white-space: nowrap; }
th { color: var(--text-3); font-weight: 500; font-size: 12px;
     border-bottom-color: var(--text-3); }
tbody tr:hover { background: rgba(255,255,255,.04); }
td.num, th.num { width: 44px; color: var(--text-3); text-align: right;
                 font-variant-numeric: tabular-nums; }
td.mail { color: var(--text); }
td.when { color: var(--text-2); font-variant-numeric: tabular-nums; }
.dash { color: var(--text-3); }
.off { color: var(--off); }
.empty { color: var(--text-2); font-size: 13px; margin: 18px 0 0; }
.who { margin: 26px 0 0; color: var(--text-3); font-size: 12px; }
.go { display: inline-block; margin-top: 14px; color: var(--accent);
      text-decoration: none; font-size: 13px; }
.go:hover { text-decoration: underline; }
@media (max-width: 620px) {
  th, td { padding: 8px 6px; font-size: 12px; }
  td.mail { white-space: normal; word-break: break-all; }
}
"""


def _shell(body: str) -> str:
    """검색에 걸릴 자리가 아니다 — 로봇에게 담지 말라고 적는다."""
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>관리실 — histgraph</title>
<meta name="robots" content="noindex,nofollow">
<style>{STYLE}</style>
</head>
<body>

<header class="top">
  <a href="/"><span class="mark"></span>histgraph<span class="back">관계망으로 돌아가기</span></a>
</header>
{body}
</body>
</html>
"""
