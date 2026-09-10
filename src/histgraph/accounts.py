"""가입자 표가 어디에 사는지 — 로컬은 SQLite, 배포는 Neon.

**왜 둘인가.** 배포는 Vercel 서버리스 함수라 파일시스템에 쓸 수 없다. 거기서는
바깥 데이터베이스가 반드시 있어야 하고 그것이 Neon 이다 (`neon.py`).

그런데 그 규칙을 로컬에까지 들이밀면 **이 컴퓨터에서 로그인을 켜 보려고
클라우드 계정을 먼저 만들어야 한다.** 2026-09-08 에 실제로 그것 때문에 화면이
"로그인은 아직 준비 중입니다"에서 멈춰 있었다. 로컬에는 이미 SQLite 가 있고
쓰기도 된다 — `DATABASE_URL` 이 없으면 `data/accounts.sqlite` 에 같은 표를
세운다. **개인 자료라 저장소에는 두지 않는다** (.gitignore).

배포에서는 이 물러남을 **막는다** (`VERCEL` 이 있으면 Neon 뿐이다). 서버리스
함수의 파일시스템은 요청마다 사라지므로, 거기서 SQLite 로 물러나면 가입자가
조용히 없어진다.

## 질의는 한 벌만 쓴다

호출부(`auth.py`)는 Postgres 문법 하나로만 적는다 — `$1` 자리표, `now()`,
`on conflict … do update`, `returning`. SQLite 로 갈 때 이 파일이 그 몇 가지를
옮긴다 (`_to_sqlite`). **문법을 늘리면 여기도 같이 늘려야 한다** — 옮기지 못한
것은 조용히 틀리지 않고 그 자리에서 터진다 (`sqlite3.OperationalError`).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

from . import neon

log = logging.getLogger(__name__)

# 저장소가 낼 수 있는 실패는 한 가지 이름으로 묶는다 — 호출부는 어디에
# 저장하는지 몰라도 되고, 알 필요도 없다.
StoreError = neon.NeonError

ROOT = Path(__file__).resolve().parents[2]
LOCAL_DB = Path(os.environ.get("HISTGRAPH_ACCOUNTS_DB") or ROOT / "data" / "accounts.sqlite")


def on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def configured() -> bool:
    """가입자를 담을 자리가 있는가.

    배포에서는 Neon 이 있어야만 참이다. 로컬은 SQLite 로 언제나 참 —
    아무것도 안 만들어도 로그인을 켜 볼 수 있다."""
    return neon.configured() or not on_vercel()


def where() -> str:
    """지금 어디에 담고 있는지 (사람에게 보여 주는 한 줄)."""
    return "Neon" if neon.configured() else f"이 컴퓨터의 {LOCAL_DB.name}"


def open_store():
    """`query`·`one`·`batch` 를 가진 저장소 하나."""
    if neon.configured():
        return neon.Neon()
    if on_vercel():
        raise StoreError(
            "배포에서는 DATABASE_URL 이 반드시 있어야 합니다 — "
            "서버리스 함수는 파일에 쓸 수 없습니다."
        )
    return LocalStore()


# --- Postgres 문법을 SQLite 로 ---------------------------------------------

# `now() + interval '30 days'` — 세션 만료를 미는 자리에서만 쓴다.
_INTERVAL = re.compile(r"now\(\)\s*\+\s*interval\s*'(\d+)\s*days?'", re.I)
_PLACEHOLDER = re.compile(r"\$(\d+)")


def _to_sqlite(sql: str, params: list) -> tuple[str, list]:
    """질의와 값을 SQLite 가 읽는 모양으로.

    자리표는 **나온 차례대로** 다시 엮는다 — `$2` 가 `$1` 보다 먼저 나오거나
    같은 자리표를 두 번 쓰면 값이 어긋나기 때문이다."""
    sql = _INTERVAL.sub(lambda m: f"datetime('now','+{m.group(1)} days')", sql)
    sql = re.sub(r"\bnow\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    sql = sql.replace("::jsonb", "")

    order: list = []
    sql = _PLACEHOLDER.sub(lambda m: (order.append(params[int(m.group(1)) - 1]), "?")[1], sql)
    return sql, order


# Postgres 쪽(`neon.SCHEMA`)과 **같은 표**를 SQLite 말로 적은 것. 열 이름과
# 뜻이 어긋나면 로컬에서 되던 것이 배포에서 깨진다 — 한쪽을 고치면 다른
# 쪽도 고친다 (테스트가 열 이름을 맞춰 본다).
SCHEMA = """
create table if not exists users (
  id             integer primary key autoincrement,
  google_sub     text    not null unique,
  email          text    not null,
  email_lower    text    not null,
  name           text,
  picture        text,
  created_at     text    not null default CURRENT_TIMESTAMP,
  last_login_at  text    not null default CURRENT_TIMESTAMP,
  disabled       integer not null default 0
);
create index if not exists users_email_lower_idx on users (email_lower);

create table if not exists sessions (
  token_hash   text primary key,
  user_id      integer not null references users(id) on delete cascade,
  created_at   text    not null default CURRENT_TIMESTAMP,
  seen_at      text    not null default CURRENT_TIMESTAMP,
  expires_at   text    not null,
  user_agent   text
);
create index if not exists sessions_user_idx    on sessions (user_id);
create index if not exists sessions_expires_idx on sessions (expires_at);

create table if not exists life_docs (
  user_id    integer primary key references users(id) on delete cascade,
  doc        text    not null,
  updated_at text    not null default CURRENT_TIMESTAMP
);

create table if not exists bookmarks (
  user_id    integer not null references users(id) on delete cascade,
  node_id    text    not null,
  label      text,
  note       text,
  created_at text    not null default CURRENT_TIMESTAMP,
  primary key (user_id, node_id)
);
"""


class LocalStore:
    """로컬 개발용 가입자 표. Neon 과 같은 세 가지(`query`·`one`·`batch`)만 낸다.

    연결을 들고 있지 않고 부를 때마다 연다 — 이 서버는 요청마다 스레드가
    다른데(ThreadingHTTPServer) sqlite3 연결은 스레드를 건너 쓰지 못한다."""

    path = LOCAL_DB

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("pragma foreign_keys = on")
        return con

    def query(self, sql: str, params: list | tuple = ()) -> list[dict]:
        stmt, values = _to_sqlite(sql, list(params))
        try:
            with self._connect() as con:
                rows = con.execute(stmt, values).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.Error as err:
            raise StoreError(f"가입자 표 질의 실패: {err}") from None

    def one(self, sql: str, params: list | tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def batch(self, statements: list[tuple[str, list | tuple]]) -> list[list[dict]]:
        """한 트랜잭션. 하나가 실패하면 전부 되돌아간다 (회원 탈퇴가 이걸 쓴다)."""
        try:
            with self._connect() as con:
                out = []
                for sql, params in statements:
                    stmt, values = _to_sqlite(sql, list(params))
                    out.append([dict(r) for r in con.execute(stmt, values).fetchall()])
                return out
        except sqlite3.Error as err:
            raise StoreError(f"가입자 표 질의 실패: {err}") from None


def init_schema(store=None) -> str:
    """표를 세운다 (없을 때만). 어디에 세웠는지를 돌려준다."""
    store = store or open_store()
    if isinstance(store, LocalStore):
        with store._connect() as con:
            con.executescript(SCHEMA)
        return str(store.path)
    neon.init_schema(store)
    return "Neon"


# --- 두 표 사이에서 내 역사를 옮긴다 -------------------------------------------
# 로컬은 SQLite, 배포는 Neon 이고 **둘은 다른 표**다 (위 `open_store` 머리글의
# 2026-09-09 결정: 로컬 시험이 배포 가입자에게 닿지 않게 이름을 갈아 두었다).
# 그래서 로컬에서 적은 이야기는 배포에 안 간다 — 2026-09-09 사용자: "지금
# 로컬과 프로덕션의 내 역사가 달라". 옮기는 길은 표를 직접 건드리는 것뿐이라
# 여기 둔다 (`histgraph lifesync`).
PROD_ENV = "HISTGRAPH_PROD_DATABASE_URL"


def prod_store():
    """배포(Neon) 가입자 표. **이 이름을 읽는 곳은 여기 하나다.**

    `.env` 의 이름을 갈아 둔 뜻은 '저절로 켜지지 않는다' 이므로, 읽는 자리도
    하나여야 한다 — 이 함수를 부르는 것은 `lifesync` 뿐이고 그것은 사람이
    직접 치는 명령이다. `serve` 도 `open_store()` 도 여기로 오지 않는다."""
    url = os.environ.get(PROD_ENV, "").strip() or os.environ.get(neon.ENV_URL, "").strip()
    if not url:
        raise StoreError(f"{PROD_ENV} 이 없습니다 — .env 에 배포 연결 문자열을 넣어 주세요.")
    return neon.Neon(url)


def find_user(store, email: str | None = None, sub: str | None = None) -> dict | None:
    """가입자 한 명. **두 표를 잇는 것은 이메일이 아니라 `google_sub`** 이다
    (같은 사람의 id 가 로컬 1 · 배포 26 이다). 그래서 sub 을 먼저 본다."""
    if sub:
        row = store.one("select id, email, google_sub from users where google_sub = $1", [sub])
        if row:
            return row
    if email:
        return store.one("select id, email, google_sub from users where lower(email) = $1",
                         [email.strip().lower()])
    return None


def life_of(store, user: dict) -> tuple[dict | None, str | None]:
    """그 사람의 내 역사 문서와 마지막으로 고친 때. 없으면 (None, None).

    표에 봉투로 들어 있으면 열어서 준다 (`secretbox`). **두 곳의 큰 열쇠가
    같아야 옮길 수 있다** — 로컬 `.env` 와 배포 환경변수에 같은 값을 둔다."""
    import json

    from . import secretbox

    row = store.one("select doc, updated_at from life_docs where user_id = $1", [user["id"]])
    if not row:
        return None, None
    doc = row["doc"]
    doc = json.loads(doc) if isinstance(doc, str) else doc
    return secretbox.unseal(doc), row.get("updated_at")


def put_life(store, user: dict, doc: dict) -> int:
    """내 역사 문서를 얹는다. 돌아오는 것은 **문서**의 바이트 수 (512KB 까지).

    표에 드는 것은 봉투다 (`secretbox.seal` — 열쇠가 없으면 평문 그대로).
    한도는 봉투가 아니라 문서에 건다."""
    import json

    from . import secretbox

    raw = json.dumps(doc, ensure_ascii=False)
    size = len(raw.encode("utf-8"))
    if size > 512 * 1024:
        raise StoreError(f"문서가 너무 큽니다 — {size:,} 바이트 (512KB 까지)")
    store.query(
        """insert into life_docs (user_id, doc) values ($1, $2::jsonb)
           on conflict (user_id) do update
              set doc = excluded.doc, updated_at = now()""",
        [user["id"], json.dumps(secretbox.seal(doc), ensure_ascii=False)])
    return size
