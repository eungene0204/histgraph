"""가입자 표가 사는 곳 — Neon Postgres 에 HTTP 로 붙는 최소 클라이언트.

**왜 드라이버를 안 쓰는가.** 이 저장소의 규칙은 표준 라이브러리만으로 도는
것이고(`server.py` 머리글), 배포는 Vercel 서버리스 함수 하나다. psycopg 같은
드라이버는 바이너리 휠을 끌고 오는 데다, 함수가 깨어날 때마다 TCP 연결을
새로 여는 것은 서버리스에서 가장 비싼 일이다.

Neon 은 그래서 **프록시에 HTTP 한 방 질의**를 열어 둔다 — 공식 드라이버
(`@neondatabase/serverless`)가 실제로 쓰는 그 길이다. 규칙은 셋뿐이라
urllib 로 그대로 옮길 수 있다:

    POST https://api.<리전>.aws.neon.tech/sql
    Neon-Connection-String: postgres://…            (연결 문자열이 곧 인증)
    {"query": "select … where id = $1", "params": [1]}

주소는 연결 문자열의 호스트에서 **첫 마디를 `api.` 로 바꾼 것**이다
(`ep-xxx-pooler.ap-northeast-2.aws.neon.tech` → `api.ap-northeast-2.aws.neon.tech`).
여러 문장을 한 트랜잭션으로 보내려면 `{"queries": [...]}` 로 싸서 보낸다.

**질의문에 값을 이어 붙이지 않는다.** 이 파일 밖에서 SQL 을 조립할 일이
생기면 `$1` 자리표와 `params` 로만 넘긴다 — 가입자 표는 남이 적은 글
(이메일·이름)이 그대로 들어오는 자리다.

연결 문자열에는 비밀번호가 들어 있다. **예외 메시지·로그에 절대 싣지
않는다** (`_scrub`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

# 연결 문자열은 함수가 따뜻할 때 재사용된다. 없으면 이 기능 전체가 꺼진다.
ENV_URL = "DATABASE_URL"

TIMEOUT = 10          # 초. 화면이 로그인 한 번에 이보다 오래 기다릴 이유가 없다.
RETRIES = 2           # 일시적 장애만 다시. 4xx 는 다시 물어도 같은 답이다.
RETRY_STATUS = {429, 500, 502, 503, 504}


class NeonError(RuntimeError):
    """질의가 실패했다. 메시지에 연결 문자열이 실리지 않는다."""


def _scrub(text: str) -> str:
    """비밀번호가 든 URL 을 가린다. 예외는 로그로도 가고 화면으로도 간다."""
    return re.sub(r"(postgres(?:ql)?://[^:@\s]+:)[^@\s]+@", r"\1***@", text)


def configured() -> bool:
    """가입 기능을 켤 수 있는가. 안 켜져 있으면 화면에 단추를 세우지 않는다."""
    return bool(os.environ.get(ENV_URL, "").strip())


def sql_endpoint(conn: str) -> str:
    """연결 문자열에서 HTTP 질의 주소를 만든다.

    드라이버와 같은 규칙이다 — 호스트의 첫 마디를 `api.` 로 갈아 끼운다.
    `-pooler` 가 붙은 호스트도 첫 마디째 사라지므로 그대로 맞는다."""
    host = urllib.parse.urlsplit(conn).hostname or ""
    if "." not in host:
        raise NeonError(f"연결 문자열의 호스트를 읽지 못했습니다: {host!r}")
    return "https://api." + host.split(".", 1)[1] + "/sql"


class Neon:
    """Neon 한 대. 함수가 따뜻할 때 재사용하라고 모듈 수준에 하나 둔다."""

    def __init__(self, conn: str | None = None) -> None:
        self.conn = (conn or os.environ.get(ENV_URL, "")).strip()
        if not self.conn:
            raise NeonError(
                f"{ENV_URL} 이 없습니다 — Neon 연결 문자열을 환경변수에 넣어 주세요."
            )
        self.url = sql_endpoint(self.conn)

    # --- 질의 ------------------------------------------------------------

    def query(self, sql: str, params: list | tuple = ()) -> list[dict]:
        """한 문장. 돌아오는 것은 열 이름이 키인 사전들이다."""
        got = self._send({"query": sql, "params": list(params)})
        return got.get("rows") or []

    def one(self, sql: str, params: list | tuple = ()) -> dict | None:
        """첫 줄만. 없으면 None."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def batch(self, statements: list[tuple[str, list | tuple]]) -> list[list[dict]]:
        """여러 문장을 **한 트랜잭션으로**. 하나가 실패하면 전부 되돌아간다.

        회원 탈퇴처럼 '반쯤 지워진 상태'가 있으면 안 되는 자리에 쓴다."""
        body = {
            "queries": [
                {"query": s, "params": list(p)} for s, p in statements
            ]
        }
        got = self._send(body)
        return [r.get("rows") or [] for r in (got.get("results") or [])]

    # --- 전송 ------------------------------------------------------------

    def _send(self, body: dict) -> dict:
        raw = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Neon-Connection-String": self.conn,
        }
        last = ""
        for attempt in range(RETRIES + 1):
            req = urllib.request.Request(self.url, data=raw, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                text = err.read().decode("utf-8", errors="replace")[:400]
                # Postgres 의 오류는 4xx 본문에 JSON 으로 온다. 다시 물어도
                # 같은 답이므로 바로 올린다 — 다만 본문에 우리가 보낸 질의가
                # 실려 오므로 값(params)은 이미 빠져 있다.
                if err.code not in RETRY_STATUS:
                    raise NeonError(f"질의 실패 (HTTP {err.code}): {_scrub(text)}") from None
                last = f"HTTP {err.code}: {text}"
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last = str(err)
            except json.JSONDecodeError as err:
                raise NeonError(f"응답이 JSON 이 아닙니다: {err}") from None
            if attempt < RETRIES:
                time.sleep(0.3 * (2**attempt))
        raise NeonError(f"Neon 에 닿지 못했습니다: {_scrub(last)}")


# --- 표 ------------------------------------------------------------------
# `uv run histgraph accounts --init` 이 한 번 돌린다. 전부 `if not exists`
# 라서 여러 번 돌려도 안전하다 — 배포 뒤 스키마가 늘면 그냥 다시 돌린다.
#
# 세션의 **쿠키 값 자체는 어디에도 저장하지 않는다.** 저장하는 것은 그
# sha256 이다 (`token_hash`) — 표가 통째로 새어도 그것으로는 남의 자리에
# 앉을 수 없다. 비밀번호를 해시로만 두는 것과 같은 이유다.
SCHEMA = """
create table if not exists users (
  id             bigserial primary key,
  google_sub     text        not null unique,
  email          text        not null,
  email_lower    text        not null,
  name           text,
  picture        text,
  created_at     timestamptz not null default now(),
  last_login_at  timestamptz not null default now(),
  disabled       boolean     not null default false
);
create index if not exists users_email_lower_idx on users (email_lower);

create table if not exists sessions (
  token_hash   text        primary key,
  user_id      bigint      not null references users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  seen_at      timestamptz not null default now(),
  expires_at   timestamptz not null,
  user_agent   text
);
create index if not exists sessions_user_idx    on sessions (user_id);
create index if not exists sessions_expires_idx on sessions (expires_at);

create table if not exists life_docs (
  user_id    bigint      primary key references users(id) on delete cascade,
  doc        jsonb       not null,
  updated_at timestamptz not null default now()
);

create table if not exists bookmarks (
  user_id    bigint      not null references users(id) on delete cascade,
  node_id    text        not null,
  label      text,
  note       text,
  created_at timestamptz not null default now(),
  primary key (user_id, node_id)
);
"""


def init_schema(db: Neon | None = None) -> None:
    """표를 만든다 (없을 때만)."""
    db = db or Neon()
    # 한 문장씩 보낸다 — HTTP 질의는 한 방에 여러 문장을 받지 않는다.
    for stmt in (s.strip() for s in SCHEMA.split(";")):
        if stmt:
            db.query(stmt)
