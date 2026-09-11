"""관리실 — `/console`. 탭 넷으로 가른 한 장이다.

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

**탭은 서버가 가른다** (`?tab=`). 자바스크립트로 감췄다 보였다 하면 네 탭의
자료를 한 번에 실어 보내야 하는데, 그러면 그래프 탭을 안 여는 사람에게도
가입자 표와 그래프 셈을 다 돌린다. 링크 하나에 한 탭이면 셈도 그 탭 것만
돈다.

**개인 자료는 세기만 한다.** '쓰임새' 탭은 `life_docs` 에서 주인 번호와
고친 시각만 읽는다 — 문서 칸(`doc`)은 **질의에 담지 않는다.** 관리자라도
남이 적은 삶을 읽을 자리가 아니다 (CLAUDE.md §1-10·§1-11).

**주소가 둘인 이유.** 로컬(`histgraph serve`)에는 `/console` 로 오지만,
배포에서는 rewrite 가 `/api?__p=console` 로 넘겨 `auth.route` 가 보는
경로가 `/api/console` 이 된다 (`vercel.json` · `pages.route` 와 같은 사정).
그래서 표에 두 이름을 함께 적는다 (`auth.ROUTES`).

여기 글자는 사람이 읽는 것이라 한국어다 (CLAUDE.md §1). **가입자의 이메일과
이름만이 영어일 수 있다** — 그것은 우리가 쓴 글이 아니라 그 사람의 것이다.
그래서 파일 이름·환경변수 이름도 화면에 적지 않는다: 어느 표를 읽었는지는
`store_name()` 처럼 한국어로 말한다.
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from html import escape
from pathlib import Path

from . import accounts

log = logging.getLogger(__name__)

PATHS = ("/console", "/api/console")

# 한 장에 세우는 최대 인원. 넘으면 최근 순으로 자르고 몇 명이 더 있는지 적는다.
LIMIT = 500

# 세션은 사람 수보다 몇 곱절 많을 수 있다. 세는 데만 쓰므로 넉넉히 자른다.
SESSION_LIMIT = 5000

# 탭. 차례가 곧 화면의 차례이고 첫째가 기본이다.
TABS: tuple[tuple[str, str], ...] = (
    ("users", "가입자"),
    ("use",   "쓰임새"),
    ("graph", "그래프"),
    ("ops",   "살림"),
)

#: 이 저장소의 뿌리. `data/` 는 여기 아래에 있다.
ROOT = Path(__file__).resolve().parents[2]

#: 지금 화면에 서고 있는 그래프 파일. `server.serve` 와 배포 진입점이
#: 자기가 연 파일을 여기 적어 둔다 — 안 적으면 아래 `graph_db()` 가
#: 같은 규칙으로 다시 찾는다 (거의 언제나 같은 파일이다).
ACTIVE_DB: Path | None = None


def graph_db() -> Path:
    """화면이 읽는 그래프 파일. 배포 진입점이 고르는 것과 같은 규칙이다."""
    if ACTIVE_DB is not None:
        return ACTIVE_DB
    raw = os.environ.get("HISTGRAPH_DB")
    if raw:
        return Path(raw)
    era = os.environ.get("HISTGRAPH_ERA") or "korea"
    return ROOT / "data" / f"{era}.sqlite"


def page(req):
    """`/console` 한 장. 관리자가 아니면 아무 표도 읽지 않는다."""
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

    tab = req.one("tab") or TABS[0][0]
    if tab not in dict(TABS):
        tab = TABS[0][0]
    try:
        inner = _BUILD[tab]()
    except accounts.StoreError as err:
        log.warning("가입자 표 접근 실패: %s", err)
        return _html(_note("가입자 정보에 닿지 못했습니다."), 503)
    return _html(_room(tab, inner, user))


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


def _room(tab: str, inner: str, admin: dict) -> str:
    """탭 줄 + 그 탭의 몸통. 링크는 **주소를 그대로 두고 물음표만 바꾼다** —
    로컬은 `/console`, 배포는 rewrite 뒤 같은 자리라 둘 다 맞는다."""
    nav = "".join(
        (f'<span class="on">{escape(name)}</span>' if key == tab
         else f'<a href="?tab={key}">{escape(name)}</a>')
        for key, name in TABS
    )
    return _shell(f'''
<main>
  <nav class="tabs">{nav}</nav>
  {inner}
  <p class="who">{escape(admin["email"])} 로 보고 있습니다.</p>
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


def moment(value: object) -> datetime.datetime | None:
    """저장소가 준 시각을 시간대 있는 값으로. 못 읽으면 None.

    Neon 은 `2026-09-08 18:57:56.299034+00`, SQLite 는 `2026-09-08 18:57:56`
    으로 준다. 시간대가 안 적혀 있으면 **세계시로 친다** — 두 저장소가 그렇게
    적기 때문이다."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        got = datetime.datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=datetime.timezone.utc)


def when(value: object) -> str:
    """시각 하나를 한국 시각 `2026-09-09 03:57` 로. 못 읽으면 온 대로 앞 열여섯 자."""
    got = moment(value)
    if got is None:
        text = str(value or "").strip()
        return text.replace("T", " ")[:16]
    return got.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _recent(rows: list[dict], field: str, days: int) -> int:
    """요 며칠 사이에 그 칸의 시각이 찍힌 줄이 몇인가. **셈은 파이썬에서 한다** —
    시각 칸이 한쪽은 글자(SQLite)이고 한쪽은 시각형(Postgres)이라, 날짜를
    SQL 로 견주면 두 저장소에서 다르게 읽힌다."""
    edge = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return sum(1 for r in rows if (got := moment(r.get(field))) and got >= edge)


def _count(db, sql: str) -> int:
    return int((db.one(sql) or {}).get("n") or 0)


def _facts(rows: list[tuple[str, str, bool]]) -> str:
    """'이름 — 값' 두 칸짜리 표. 셋째 칸이 참이면 값을 눈에 띄게 세운다."""
    body = "\n".join(
        f'<tr><th class="k">{escape(k)}</th>'
        f'<td class="{"v off" if warn else "v"}">{escape(v)}</td></tr>'
        for k, v, warn in rows
    )
    return f'<table class="facts"><tbody>\n{body}\n</tbody></table>'


# --- 가입자 ----------------------------------------------------------------


def _users() -> str:
    """누가 언제 와서 언제 다녀갔나."""
    from . import auth

    db = auth.db()
    rows = db.query(
        "select id, email, name, created_at, last_login_at, disabled "
        "from users order by created_at desc, id desc limit $1", [LIMIT])
    total = _count(db, "select count(*) as n from users")
    return render(rows, total)


def render(rows: list[dict], total: int) -> str:
    """가입자 목록."""
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
    # 며칠 치 셈은 **세운 목록 안에서** 낸다 (`_recent` 머리글). 잘릴 만큼
    # 사람이 많아지면 그때는 저장소별 질의를 따로 써야 한다.
    fresh, seen = _recent(rows, "created_at", 7), _recent(rows, "last_login_at", 7)

    return f"""
  <h1>가입자</h1>
  <p class="sub">모두 <b>{total:,}</b>명 · 이레 사이에 <b>{fresh:,}</b>명이 새로 오고
     <b>{seen:,}</b>명이 다녀갔습니다 · {store_name()}를 읽었습니다.
     시각은 한국 시각입니다.</p>
  {table}
  {more}
"""


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


# --- 쓰임새 ----------------------------------------------------------------


def _use() -> str:
    """사람들이 이 화면으로 무엇을 하고 있나. **개수와 시각만 센다.**"""
    from . import auth

    db = auth.db()
    total = _count(db, "select count(*) as n from users")
    # 문서 칸(`doc`)은 뽑지 않는다 — 남이 적은 삶은 관리자도 읽지 않는다.
    lives = db.query("select user_id, updated_at from life_docs", [])
    marks = _count(db, "select count(*) as n from bookmarks")
    markers = _count(db, "select count(distinct user_id) as n from bookmarks")
    sessions = db.query("select user_id, expires_at from sessions limit $1",
                        [SESSION_LIMIT])
    now = datetime.datetime.now(datetime.timezone.utc)
    here = {s.get("user_id") for s in sessions
            if (got := moment(s.get("expires_at"))) and got > now}
    last = max((moment(r.get("updated_at")) for r in lives
                if moment(r.get("updated_at"))), default=None)

    share = f" (가입자 {total:,}명 가운데)" if total else ""
    rows = [
        ("내 역사를 만든 사람", f"{len(lives):,}명{share}", False),
        ("내 역사가 마지막으로 바뀐 때",
         when(last.isoformat()) if last else "아직 없습니다", False),
        ("담아 둔 갈피", f"{marks:,}건 · {markers:,}명이 담았습니다", False),
        ("지금 들어와 있는 사람", f"{len(here):,}명 · 살아 있는 자리 {len([1 for s in sessions if (g := moment(s.get('expires_at'))) and g > now]):,}개", False),
    ]
    return f"""
  <h1>쓰임새</h1>
  <p class="sub">{store_name()}를 읽었습니다. 시각은 한국 시각입니다.</p>
  {_facts(rows)}
  <p class="empty">내 역사에 무엇을 적었는지는 이 자리에서 볼 수 없습니다.
     개수와 시각만 셉니다.</p>
"""


# --- 그래프 ----------------------------------------------------------------


def _num(conn, sql: str) -> int | None:
    """표가 없을 수도 있다 (배포본은 읽기 전용이라 스키마가 돌지 않는다)."""
    try:
        got = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    return None if got is None else int(got[0] or 0)


def _graph() -> str:
    """화면에 서는 그래프가 지금 무엇을 담고 있나."""
    from . import ontology
    from .store import GraphStore

    path = graph_db()
    if not path.exists():
        return """
  <h1>그래프</h1>
  <p class="sub">화면이 읽을 그래프 파일이 없습니다.</p>
"""
    store = GraphStore(path, readonly=True)
    try:
        conn = store.conn
        nodes = _num(conn, "select count(*) from nodes") or 0
        edges = _num(conn, "select count(*) from edges") or 0
        kinds = conn.execute(
            "select type, count(*) as n from nodes group by type order by n desc"
        ).fetchall()
        described = _num(conn, "select count(*) from nodes "
                               "where coalesce(description,'') <> ''") or 0
        dated = _num(conn, "select count(*) from nodes "
                           "where coalesce(start_date,'') <> ''") or 0
        caused = _num(conn, "select count(*) from edges where type = 'caused'") or 0
        written = _num(conn, "select count(*) from summaries")
        fixed = _num(conn, "select count(*) from overrides")
        try:
            grabbed = conn.execute("select max(ran_at) from ingest_log").fetchone()[0]
        except sqlite3.Error:
            grabbed = None
    finally:
        store.close()

    body = "\n".join(
        f'<tr><th class="k">{escape(ontology.NODE_TYPES.get(r[0], r[0]))}</th>'
        f'<td class="v">{int(r[1]):,}개</td></tr>'
        for r in kinds if ontology.NODE_TYPES.get(r[0])
    )
    share = f"{described * 100 // nodes}%" if nodes else "0%"
    rows = [
        ("설명이 있는 노드", f"{described:,}개 · 전체의 {share}", described < nodes // 2),
        ("연표에 설 수 있는 노드", f"{dated:,}개", False),
        ("원인과 결과로 이은 선", f"{caused:,}개", False),
        ("우리 말로 새로 쓴 설명",
         f"{written:,}개" if written is not None else "아직 없습니다", False),
        ("사람과 규칙이 고쳐 둔 값",
         f"{fixed:,}건" if fixed is not None else "아직 없습니다", False),
        ("마지막으로 자료를 걷은 때",
         when(grabbed) if grabbed else "알 수 없습니다", False),
    ]
    return f"""
  <h1>그래프</h1>
  <p class="sub">화면이 읽는 그래프에 노드 <b>{nodes:,}</b>개와
     선 <b>{edges:,}</b>개가 있습니다.</p>
  <p class="head">갈래별로</p>
  <table class="facts"><tbody>
{body}
  </tbody></table>
  <p class="head">그 밖에</p>
  {_facts(rows)}
"""


# --- 살림 ------------------------------------------------------------------


def _ops() -> str:
    """켜져 있어야 할 것이 켜져 있나. **열쇠 값은 적지 않는다** — 있는지만 말한다."""
    from . import auth, secretbox

    # 열쇠 이름의 주인은 `backends` 다. 여기서는 있는지만 보므로 이름만 빌린다.
    outside = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    login = auth.enabled()
    sealed = secretbox.enabled()
    path = graph_db()
    rows = [
        ("로그인", "켜짐" if login else "꺼짐 — 아무도 들어올 수 없습니다", not login),
        ("가입자 표", store_name(), False),
        ("내 역사 봉투",
         "열쇠 있음" if sealed else "열쇠 없음 — 글이 잠기지 않은 채 담깁니다",
         not sealed),
        ("내 역사를 읽는 밖의 모델",
         "열쇠 있음" if outside else "열쇠 없음 — 분석을 돌릴 수 없습니다",
         not outside),
        ("관리자", f"{len(auth.admins()):,}명", not auth.admins()),
        ("화면이 읽는 그래프",
         "있음" if path.exists() else "없음 — 화면이 비어 보입니다", not path.exists()),
    ]
    return f"""
  <h1>살림</h1>
  <p class="sub">이 자리가 지금 어떻게 차려져 있는지입니다.
     열쇠는 있는지만 보고 값은 적지 않습니다.</p>
  {_facts(rows)}
"""


_BUILD = {"users": _users, "use": _use, "graph": _graph, "ops": _ops}


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
main { max-width: 900px; margin: 0 auto; padding: 22px 22px 70px; }
h1 { font-size: 20px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { margin: 0 0 22px; color: var(--text-2); font-size: 13px; }
.sub b { color: var(--text); font-weight: 600; }
.tabs { display: flex; gap: 2px; margin: 0 0 22px; border-bottom: 1px solid var(--line); }
.tabs a, .tabs span { padding: 8px 14px; font-size: 13px; text-decoration: none;
                      color: var(--text-2); border-bottom: 2px solid transparent;
                      margin-bottom: -1px; }
.tabs a:hover { color: var(--text); }
.tabs .on { color: var(--text); font-weight: 600;
            border-bottom-color: var(--accent); }
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
.head { margin: 0 0 8px; color: var(--text-3); font-size: 12px; }
.facts { margin: 0 0 26px; }
.facts th.k { width: 42%; color: var(--text-2); font-size: 13px; font-weight: 400;
              border-bottom-color: var(--line); }
.facts td.v { color: var(--text); font-variant-numeric: tabular-nums;
              white-space: normal; }
.facts td.v.off { color: var(--off); }
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
  .tabs a, .tabs span { padding: 8px 9px; }
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
