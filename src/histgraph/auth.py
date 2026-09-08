"""가입과 로그인 — 구글 계정으로 들어와 세션 쿠키로 머문다.

## 어떤 흐름인가

브라우저에는 **토큰을 한 조각도 두지 않는다.** 구글이 주는 것(인가 코드·
액세스 토큰·ID 토큰)은 전부 서버가 받아 서버에서 소진하고, 브라우저에는
우리가 만든 **불투명한 세션 쿠키 하나**만 남는다.

    1. 화면이 `/api/auth/google` 로 보낸다
       → 서버가 state·PKCE 검증자·nonce 를 만들어 **서명한 쿠키**에 담고
         구글 동의 화면으로 302
    2. 구글이 `/api/auth/callback?code=…&state=…` 로 돌려보낸다
       → 쿠키의 state 와 대조(CSRF) → 코드를 구글 토큰 엔드포인트에
         **서버 대 서버로** 교환(PKCE 검증자 동봉) → ID 토큰의 주장 검사
       → 가입자 표에 upsert → 세션을 만들고 쿠키를 심고 원래 자리로 302

## 왜 이 선택인가

- **인가 코드 + PKCE.** 암시적 흐름(토큰을 주소창으로 받는 것)은 토큰이
  기록·확장·referer 로 샌다. PKCE 는 코드를 가로채도 검증자 없이는 못
  바꾸게 한다 — 공개 클라이언트가 아니어도(우리는 client_secret 이 있다)
  거는 것이 지금 권고(OAuth 2.1)다.
- **ID 토큰 서명을 우리가 다시 확인하지 않는다.** 토큰을 브라우저에서
  받았다면 반드시 해야 하지만, 여기서는 **구글 토큰 엔드포인트와 우리
  서버가 TLS 로 직접** 주고받는다. OpenID Connect Core §3.1.3.7 이 그
  경우를 명시로 면제한다. 대신 `iss`·`aud`·`exp`·`nonce`·`email_verified`
  는 전부 확인한다 — 서명만으로는 못 잡는 것들이다.
- **세션은 되돌릴 수 있어야 한다.** JWT 를 세션으로 쓰면 로그아웃·탈퇴가
  만료까지 효력이 없다. 그래서 임의의 256비트 토큰을 쿠키에 두고, DB 에는
  그 sha256 만 둔다 (`accounts.SCHEMA`·`neon.SCHEMA` 머리글).
- **쿠키.** HttpOnly(자바스크립트가 못 읽는다 → XSS 로 세션을 못 훔친다) ·
  Secure · SameSite=Lax(다른 사이트에서 쏜 POST 에 실려 가지 않는다) ·
  https 에서는 `__Host-` 접두사(하위 도메인이 쿠키를 심어 넣지 못한다).
- **CSRF 는 두 겹.** SameSite=Lax 가 이미 막지만, 상태를 바꾸는 요청은
  (1) `Origin` 이 우리 것인지 보고 (2) 세션 토큰에서 파생한 표(`X-Histgraph-CSRF`)
  를 대조한다. 표는 세션 토큰의 HMAC 이라 세션을 모르면 만들 수 없다.

## 여기 손댈 때 조심할 것

- **응답을 캐시에 재우지 않는다.** 배포(api/index.py)는 기본으로 `/api` 를
  엣지에 하루 재운다 — 그 규칙이 `/api/me` 에 닿으면 **한 사람의 신원이
  다음 사람에게 배달된다.** 이 파일이 내는 모든 응답은 스스로
  `Cache-Control: private, no-store` 를 들고 나간다.
- **되돌아갈 주소(`next`)는 우리 사이트 안이어야 한다.** `//evil.com` 은
  브라우저가 절대 주소로 읽는다 — `_safe_next` 가 거른다.
- **오는 Host 헤더를 믿지 않는다.** redirect_uri 를 그것으로 지으면 남이
  보낸 Host 로 동의 화면을 만들 수 있다. 우리 주소는 환경변수와 로컬
  허용 목록에서만 나온다 (`origin_for`).
- SQL 은 전부 `$1` 자리표로 넘긴다 (`neon` 머리글).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import accounts

log = logging.getLogger(__name__)

# --- 설정 -----------------------------------------------------------------

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# 배포 주소. 화면이 사는 곳과 같아야 쿠키가 붙는다.
SITE = os.environ.get("HISTGRAPH_SITE", "https://www.histgraph.space").rstrip("/")
# 개발 중에 붙는 자리 — 이 이름들만 http 로 인정한다. 포트는 가리지 않는다
# (`serve --port` 로 옮겨 다니고 5173·4173 도 쓴다).
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

SESSION_DAYS = 30
SESSION_TOUCH = 24 * 3600      # 하루 지난 세션만 만료를 밀어 준다 (쓰기 줄이기)
# 로그인 왕복에 주는 시간 (초). **처음 들어오는 계정에는 10분이 모자랐다**
# (2026-09-09 지적: 처음 쓰는 구글 아이디로 들어오면 "쿠키가 차단되어
# 있습니다" 가 떴다) — 계정 고르기·비밀번호·2단계 인증·동의 화면을 다 지나야
# 하고, 그 자리에서 계정을 새로 만들면 더 걸린다. 그동안 왕복 쿠키가 먼저
# 죽으면 우리는 그 사람이 오래 걸렸다는 것을 알 길이 없다.
TX_TTL = 1800                  # 30분
# **쿠키는 그보다 조금 더 산다.** 둘이 같으면 늦게 온 사람의 쿠키가 사라져
# '시간이 지났습니다' 대신 '쿠키가 차단되어 있습니다' 라는 엉뚱한 말이 뜬다 —
# 안에 적어 둔 시각(`x`)이 먼저 걸려야 우리가 참말을 할 수 있다.
TX_COOKIE_TTL = TX_TTL + 300
MAX_BODY = 1 << 20             # 요청 본문 1MB
MAX_LIFE = 512 * 1024          # 개인 역사 문서 512KB
MAX_BOOKMARKS = 1000
MAX_NOTE = 500

COOKIE_TX = "hg_oauth"         # 로그인 왕복 동안만 사는 서명 쿠키
COOKIE_SESSION = "hg_session"
COOKIE_CSRF = "hg_csrf"        # 자바스크립트가 읽어 헤더에 실어 보내는 표

CSRF_HEADER = "X-Histgraph-CSRF"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def enabled() -> bool:
    """가입 기능을 켤 수 있는가.

    하나라도 없으면 **꺼진 것으로 친다** — 반쯤 열린 로그인보다 아예 닫힌
    편이 안전하다. 화면은 `/api/me` 의 `enabled` 를 보고, 단추를 눌렀을 때
    구글로 보낼지 "아직 준비 중"이라 답할지 정한다.

    가입자를 담을 자리는 로컬이면 저절로 생긴다 (`accounts.configured` —
    SQLite). 그래서 **이 컴퓨터에서 켜는 데 필요한 것은 구글 쪽 둘과
    서명 열쇠뿐이다.**"""
    return bool(
        _env("GOOGLE_CLIENT_ID")
        and _env("GOOGLE_CLIENT_SECRET")
        and len(_env("HISTGRAPH_SESSION_SECRET")) >= 32
        and accounts.configured()
    )


def _secret() -> bytes:
    key = _env("HISTGRAPH_SESSION_SECRET")
    if len(key) < 32:
        raise AuthError("HISTGRAPH_SESSION_SECRET 이 없거나 너무 짧습니다 (32자 이상).")
    return key.encode("utf-8")


def admins() -> set[str]:
    """관리자 이메일. 소문자로 비교한다."""
    return {
        e.strip().lower()
        for e in _env("HISTGRAPH_ADMIN_EMAILS").split(",")
        if e.strip()
    }


class AuthError(Exception):
    """사람에게 보여도 되는 실패 (한국어 문장). 비밀은 담지 않는다."""


# --- 잔손 ------------------------------------------------------------------


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    """`값.서명` — 값은 우리가 만든 것이고 서명이 그것을 증명한다."""
    mac = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return f"{b64u(payload)}.{b64u(mac)}"


def _unsign(token: str) -> bytes | None:
    """서명이 맞으면 값을, 아니면 None. 비교는 상수 시간으로."""
    body, _, sig = token.partition(".")
    if not body or not sig:
        return None
    try:
        payload, given = unb64u(body), unb64u(sig)
    except (ValueError, base64.binascii.Error):
        return None
    want = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return payload if hmac.compare_digest(want, given) else None


def csrf_token(session_token: str) -> str:
    """세션에서 파생한 CSRF 표. 세션을 모르면 만들 수 없다."""
    mac = hmac.new(_secret(), b"csrf:" + session_token.encode(), hashlib.sha256)
    return b64u(mac.digest())[:32]


def _hash_token(token: str) -> str:
    """DB 에 남기는 것. 쿠키 값 자체는 어디에도 적지 않는다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_cookies(header: str | None) -> dict[str, str]:
    """`Cookie:` 한 줄을 사전으로. 값에 `=` 가 들어 있어도 첫 `=` 에서만 자른다."""
    out: dict[str, str] = {}
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            out[name] = value.strip().strip('"')
    return out


def cookie_name(base: str, secure: bool) -> str:
    """https 에서는 `__Host-` 를 붙인다.

    그 접두사가 붙은 쿠키는 브라우저가 **Secure · Path=/ · Domain 없음**
    일 때만 받는다. 하위 도메인(evil.histgraph.space)이 상위에 쿠키를 심어
    우리 세션을 덮어쓰는 길(세션 고정)을 막는다."""
    return f"__Host-{base}" if secure else base


def set_cookie(name: str, value: str, *, secure: bool, max_age: int,
               http_only: bool = True, path: str = "/") -> str:
    bits = [
        f"{name}={value}",
        f"Path={path}",
        f"Max-Age={max_age}",
        "SameSite=Lax",
    ]
    if http_only:
        bits.append("HttpOnly")
    if secure:
        bits.append("Secure")
    return "; ".join(bits)


def clear_cookie(name: str, *, secure: bool, path: str = "/") -> str:
    return set_cookie(name, "", secure=secure, max_age=0, path=path)


def origin_for(host: str | None) -> str:
    """이 요청이 사는 주소. **Host 헤더를 그대로 쓰지 않는다.**

    이 값이 redirect_uri 와 Origin 검사의 기준이다. 남이 보낸 Host 가 여기로
    새면 동의 화면을 남의 주소로 지을 수 있으므로 두 겹으로 막는다:

    - **배포(Vercel)에서는 Host 를 아예 보지 않는다.** 주소는 하나뿐이고
      (`HISTGRAPH_SITE`), 그 밖의 것은 전부 남이 보낸 것이다.
    - 로컬에서는 되돌이 주소(127.0.0.1·localhost)만 http 로 인정한다.
      포트는 가리지 않는다 — `serve --port` 로 옮겨 다니기 때문이다."""
    if os.environ.get("VERCEL"):
        return SITE
    raw = (host or "").strip()
    # `[::1]:8100` 과 `127.0.0.1:8100` 을 같은 규칙으로 가른다.
    name = raw.rsplit(":", 1)[0] if raw.count(":") == 1 or raw.startswith("[") else raw
    if name.lower() in LOOPBACK:
        return f"http://{raw}"
    return SITE


def _safe_next(raw: str) -> str:
    """로그인 뒤 되돌아갈 자리. **우리 사이트 안의 경로만.**

    `//evil.com` 과 `/\\evil.com` 은 브라우저가 절대 주소로 읽는다 —
    열린 리다이렉트는 피싱의 단골 통로다."""
    if not raw.startswith("/") or raw.startswith("//") or raw.startswith("/\\"):
        return "/"
    if any(c in raw for c in "\r\n"):
        return "/"
    return raw[:300]


# --- 요청·응답 -------------------------------------------------------------


class Request:
    """HTTP 껍데기 둘(로컬 서버·서버리스 함수)이 같은 모양으로 넘겨 준다."""

    def __init__(self, method: str, path: str, query: dict[str, list[str]],
                 headers: dict[str, str], body: bytes = b"") -> None:
        self.method = method.upper()
        self.path = path
        self.query = query
        # 헤더 이름은 대소문자를 가리지 않는다 (RFC 9110).
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body
        self.origin = origin_for(self.headers.get("host"))
        self.secure = self.origin.startswith("https://")
        self.cookies = parse_cookies(self.headers.get("cookie"))

    def one(self, key: str, default: str = "") -> str:
        return (self.query.get(key) or [default])[0]

    def cookie(self, base: str) -> str:
        """이름은 https 여부에 따라 다르다 (`cookie_name`).

        **https 에서는 `__Host-` 가 붙은 것만 본다.** 접두사 없는 쪽으로
        물러나면 하위 도메인이 심어 둔 쿠키가 이겨 버려, 접두사를 붙인
        뜻이 없어진다."""
        return self.cookies.get(cookie_name(base, self.secure), "")

    def json_body(self) -> dict:
        if len(self.body) > MAX_BODY:
            raise AuthError("보낸 내용이 너무 큽니다.")
        try:
            got = json.loads(self.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise AuthError("JSON 이 아닙니다.") from None
        if not isinstance(got, dict):
            raise AuthError("JSON 객체여야 합니다.")
        return got


class Response:
    """상태·헤더·본문. 헤더를 직접 들고 다녀야 쿠키와 302 를 낼 수 있다."""

    def __init__(self, status: int, body: bytes = b"",
                 ctype: str = "application/json; charset=utf-8",
                 headers: list[tuple[str, str]] | None = None) -> None:
        self.status = status
        self.body = body
        # **캐시에 재우지 않는다.** 이 파일의 응답은 사람마다 다르다.
        self.headers = [
            ("Content-Type", ctype),
            ("Cache-Control", "private, no-store"),
            ("Vary", "Cookie"),
            # 이 응답들은 어디에도 끼워 넣을 것이 아니다.
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "same-origin"),
        ]
        self.headers += headers or []

    @classmethod
    def json(cls, payload: object, status: int = 200,
             headers: list[tuple[str, str]] | None = None) -> Response:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return cls(status, raw, headers=headers)

    @classmethod
    def redirect(cls, to: str,
                 headers: list[tuple[str, str]] | None = None) -> Response:
        # 헤더 값에 줄바꿈이 들어가면 응답을 쪼갤 수 있다 — 잘라 낸다.
        to = re.sub(r"[\r\n]", "", to)
        return cls(302, b"", ctype="text/plain; charset=utf-8",
                   headers=[("Location", to)] + (headers or []))

    @classmethod
    def page(cls, title: str, message: str, status: int = 400,
             retry: bool = False) -> Response:
        """사람이 읽는 실패 화면. 구글에서 돌아오는 길은 브라우저 이동이라
        JSON 을 뿌리면 날것이 그대로 보인다.

        `retry` 는 **여기서 바로 다시 시작할 자리**를 준다 — 로그인이 깨진
        자리에서 '처음 화면으로' 만 주면, 다시 하려는 사람이 단추를 찾아
        되돌아가야 한다."""
        html = (
            "<!doctype html><html lang=ko><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)} — histgraph</title>"
            "<style>body{margin:0;display:flex;min-height:100vh;align-items:center;"
            "justify-content:center;background:#1e1e1e;color:#dadada;"
            "font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',"
            "'Noto Sans KR',system-ui,sans-serif;line-height:1.8}"
            "div{max-width:420px;padding:0 24px}h1{font-size:17px;margin:0 0 10px}"
            "p{margin:0 0 18px;color:#a6a6a6;font-size:14px}"
            "a{color:#8a6cef;font-size:14px}</style>"
            f"<div><h1>{_esc(title)}</h1><p>{_esc(message)}</p>"
            + ("<a href='/api/auth/google'>다시 로그인하기</a><br>" if retry else "")
            + "<a href='/'>처음 화면으로</a></div></html>"
        )
        return cls(status, html.encode("utf-8"), ctype="text/html; charset=utf-8")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


# --- 세션 ------------------------------------------------------------------


_db = None


def db():
    """가입자 표. 로컬이면 SQLite, 배포면 Neon (`accounts.open_store`).

    함수가 따뜻할 때 재사용한다."""
    global _db
    if _db is None:
        _db = accounts.open_store()
    return _db


def current_user(req: Request) -> dict | None:
    """이 요청을 보낸 사람. 없으면 None.

    만료된 세션은 **읽는 김에 지운다** — 서버리스에는 청소 시각이 없다."""
    token = req.cookie(COOKIE_SESSION)
    if not token or not enabled():
        return None
    row = db().one(
        """select u.id, u.email, u.name, u.picture, u.created_at, u.disabled,
                  s.expires_at, s.seen_at
             from sessions s join users u on u.id = s.user_id
            where s.token_hash = $1 and s.expires_at > now()""",
        [_hash_token(token)],
    )
    if not row or row.get("disabled"):
        return None
    # 하루 넘게 쓴 세션만 만료를 민다. 요청마다 쓰면 화면 한 장에 쓰기가
    # 여러 번 나간다.
    try:
        seen = _epoch(row.get("seen_at"))
        if seen and time.time() - seen > SESSION_TOUCH:
            db().query(
                "update sessions set seen_at = now(), "
                f"expires_at = now() + interval '{SESSION_DAYS} days' "
                "where token_hash = $1",
                [_hash_token(token)],
            )
    except accounts.StoreError:
        pass  # 만료를 못 밀어도 이번 요청은 유효하다
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row.get("name") or "",
        "picture": row.get("picture") or "",
        "created_at": row.get("created_at"),
        "admin": (row["email"] or "").lower() in admins(),
    }


def _epoch(value: object) -> float | None:
    """Postgres 가 준 시각 문자열을 초로. 못 읽으면 None (밀지 않는다)."""
    if not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T", 1)
    text = re.sub(r"([+-]\d{2})$", r"\1:00", text)
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def require_user(req: Request) -> dict:
    user = current_user(req)
    if not user:
        raise AuthError("로그인이 필요합니다.")
    return user


def check_write(req: Request) -> None:
    """상태를 바꾸는 요청인가를 두 겹으로 확인한다.

    (1) `Origin` 이 우리 것인가 — 다른 사이트의 스크립트가 쏜 요청은
        브라우저가 자기 주소를 붙여 보낸다.
    (2) `X-Histgraph-CSRF` 가 세션에서 파생한 표와 같은가 — 세션 쿠키를
        읽을 수 없으면 만들 수 없는 값이다."""
    origin = req.headers.get("origin")
    if origin and origin.rstrip("/") != req.origin:
        raise AuthError("다른 사이트에서 온 요청입니다.")
    token = req.cookie(COOKIE_SESSION)
    given = req.headers.get(CSRF_HEADER.lower(), "")
    if not token or not given or not hmac.compare_digest(csrf_token(token), given):
        raise AuthError("요청 표가 맞지 않습니다. 화면을 새로 고친 뒤 다시 해 주세요.")


# --- 구글 왕복 -------------------------------------------------------------


def start(req: Request) -> Response:
    """`/api/auth/google` — 동의 화면으로 보낸다."""
    verifier = b64u(secrets.token_bytes(48))          # PKCE 검증자
    challenge = b64u(hashlib.sha256(verifier.encode()).digest())
    tx = {
        "s": b64u(secrets.token_bytes(24)),           # state
        "v": verifier,
        "n": b64u(secrets.token_bytes(16)),           # nonce
        "x": int(time.time()) + TX_TTL,
        "r": _safe_next(req.one("next", "/")),
    }
    params = {
        "client_id": _env("GOOGLE_CLIENT_ID"),
        "redirect_uri": f"{req.origin}/api/auth/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": tx["s"],
        "nonce": tx["n"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # 로그인한 구글 계정이 여럿일 때 어느 것으로 들어올지 고르게 한다.
        "prompt": "select_account",
        # 우리는 나중에 대신 부를 일이 없다 — 갱신 토큰을 받지 않는다.
        "access_type": "online",
    }
    cookie = set_cookie(
        cookie_name(COOKIE_TX, req.secure), _sign(json.dumps(tx).encode()),
        secure=req.secure, max_age=TX_COOKIE_TTL,
    )
    return Response.redirect(
        GOOGLE_AUTH + "?" + urllib.parse.urlencode(params),
        headers=[("Set-Cookie", cookie)],
    )


def callback(req: Request) -> Response:
    """`/api/auth/callback` — 구글이 돌려보낸 자리."""
    secure = req.secure
    drop_tx = ("Set-Cookie", clear_cookie(cookie_name(COOKIE_TX, secure), secure=secure))

    if req.one("error"):
        # 사용자가 동의 화면에서 취소한 것도 여기로 온다.
        return Response.page("로그인을 마치지 못했습니다",
                             "구글 로그인이 취소되었거나 거절되었습니다.", 400,
                             retry=True)

    # **없는 것과 맞지 않는 것을 갈라 적는다.** 둘을 한 문장으로 묶어 두면
    # 화면에 뜬 말로는 무엇이 일어났는지 알 수 없다 (2026-09-09).
    signed = req.cookie(COOKIE_TX)
    if not signed:
        log.info("왕복 쿠키가 없다 (secure=%s, 쿠키 %d개)", secure, len(req.cookies))
        return Response.page(
            "로그인을 마치지 못했습니다",
            "로그인을 시작한 지 오래되었거나 브라우저가 쿠키를 막고 있습니다. "
            "다시 시도해 주세요.", 400, retry=True)
    raw = _unsign(signed)
    if raw is None:
        # 서명 열쇠(HISTGRAPH_SESSION_SECRET)가 시작할 때와 달라졌다는 뜻이다.
        log.warning("왕복 쿠키의 서명이 맞지 않는다 — 서명 열쇠가 바뀌었는가")
        return Response.page("로그인을 마치지 못했습니다",
                             "로그인 표가 이 서버의 것이 아닙니다. 다시 시도해 주세요.",
                             400, retry=True)
    try:
        tx = json.loads(raw)
    except ValueError:
        return Response.page("로그인을 마치지 못했습니다", "요청이 손상되었습니다.", 400,
                             retry=True)

    if tx.get("x", 0) < time.time():
        return Response.page("로그인을 마치지 못했습니다",
                             "로그인에 30분이 넘게 걸렸습니다. 다시 시도해 주세요.", 400,
                             retry=True)
    # state 대조 — 남이 자기 계정으로 우리 세션을 만들어 두는 길을 막는다.
    if not hmac.compare_digest(str(tx.get("s", "")), req.one("state")):
        return Response.page("로그인을 마치지 못했습니다",
                             "요청이 확인되지 않았습니다. 다시 시도해 주세요.", 400,
                             retry=True)
    code = req.one("code")
    if not code:
        return Response.page("로그인을 마치지 못했습니다", "인가 코드가 없습니다.", 400,
                             retry=True)

    try:
        claims = _exchange(code, tx["v"], f"{req.origin}/api/auth/callback")
        _check_claims(claims, tx.get("n", ""))
        user_id = _upsert_user(claims)
        token = _new_session(user_id, req.headers.get("user-agent", "")[:300])
    except AuthError as err:
        return Response.page("로그인을 마치지 못했습니다", str(err), 400, retry=True)
    except accounts.StoreError as err:
        log.warning("가입 저장 실패: %s", err)
        return Response.page("가입자 정보를 저장하지 못했습니다",
                             "잠시 뒤 다시 시도해 주세요.", 503)

    max_age = SESSION_DAYS * 24 * 3600
    cookies = [
        ("Set-Cookie", set_cookie(cookie_name(COOKIE_SESSION, secure), token,
                                  secure=secure, max_age=max_age)),
        # 이 하나만 자바스크립트가 읽는다 — 헤더에 실어 되보내는 표다.
        ("Set-Cookie", set_cookie(cookie_name(COOKIE_CSRF, secure), csrf_token(token),
                                  secure=secure, max_age=max_age, http_only=False)),
        drop_tx,
    ]
    return Response.redirect(_safe_next(str(tx.get("r", "/"))), headers=cookies)


def _exchange(code: str, verifier: str, redirect_uri: str) -> dict:
    """인가 코드를 ID 토큰으로. **서버 대 서버, TLS.**"""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": _env("GOOGLE_CLIENT_ID"),
        "client_secret": _env("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(
        GOOGLE_TOKEN, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            got = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        # 본문에 client_secret 이 되비치는 일은 없지만, 그대로 화면에
        # 옮기지는 않는다 — 로그에만 남긴다.
        log.warning("토큰 교환 실패 (HTTP %s): %s", err.code,
                    err.read().decode("utf-8", errors="replace")[:300])
        raise AuthError("구글에서 로그인 정보를 받지 못했습니다.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        log.warning("토큰 교환 실패: %s", err)
        raise AuthError("구글에 닿지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from None

    id_token = got.get("id_token")
    if not id_token:
        raise AuthError("구글이 신원 토큰을 주지 않았습니다.")
    return decode_id_token(id_token)


def decode_id_token(id_token: str) -> dict:
    """서명은 확인하지 않고 주장만 꺼낸다.

    **왜 안 하는가**는 이 파일 머리글에 적었다 — 토큰이 구글 토큰
    엔드포인트에서 TLS 로 직접 온 경우의 면제(OIDC Core §3.1.3.7)다.
    **이 함수를 다른 곳(브라우저가 준 토큰)에 쓰면 안 된다.**"""
    parts = id_token.split(".")
    if len(parts) != 3:
        raise AuthError("신원 토큰의 모양이 맞지 않습니다.")
    try:
        return json.loads(unb64u(parts[1]))
    except (ValueError, base64.binascii.Error):
        raise AuthError("신원 토큰을 읽지 못했습니다.") from None


def _check_claims(claims: dict, nonce: str) -> None:
    """서명이 참이어도 이것들이 틀리면 남의 토큰이다."""
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("신원 토큰의 발급자가 구글이 아닙니다.")
    if claims.get("aud") != _env("GOOGLE_CLIENT_ID"):
        raise AuthError("다른 앱에 발급된 신원 토큰입니다.")
    if float(claims.get("exp") or 0) < time.time():
        raise AuthError("신원 토큰이 만료되었습니다.")
    if nonce and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise AuthError("신원 토큰이 이번 요청의 것이 아닙니다.")
    if not claims.get("sub"):
        raise AuthError("신원 토큰에 계정 식별자가 없습니다.")
    if not claims.get("email"):
        raise AuthError("구글 계정의 이메일을 받지 못했습니다.")
    # 확인되지 않은 이메일은 남이 선점한 주소일 수 있다 — 그 주소로 계정을
    # 잇는 순간 계정 탈취가 된다.
    if claims.get("email_verified") not in (True, "true"):
        raise AuthError("구글에서 확인되지 않은 이메일입니다.")


def _upsert_user(claims: dict) -> int:
    """가입자 표에 적는다. 처음 온 사람이면 그 줄이 가입이다.

    **`sub` 이 열쇠다.** 구글의 계정 식별자는 바뀌지 않지만 이메일은
    바뀔 수 있다 — 이메일을 열쇠로 삼으면 주소를 바꾼 사람이 남남이 된다."""
    email = str(claims["email"])
    row = db().one(
        """insert into users (google_sub, email, email_lower, name, picture)
                values ($1, $2, $3, $4, $5)
           on conflict (google_sub) do update
                set email = excluded.email,
                    email_lower = excluded.email_lower,
                    name = excluded.name,
                    picture = excluded.picture,
                    last_login_at = now()
           returning id, disabled""",
        [str(claims["sub"]), email, email.lower(),
         str(claims.get("name") or "")[:200],
         str(claims.get("picture") or "")[:500]],
    )
    if not row:
        raise AuthError("가입자 정보를 저장하지 못했습니다.")
    if row.get("disabled"):
        raise AuthError("이용이 중지된 계정입니다.")
    return int(row["id"])


def _new_session(user_id: int, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)      # 256비트
    db().query(
        "insert into sessions (token_hash, user_id, expires_at, user_agent) "
        f"values ($1, $2, now() + interval '{SESSION_DAYS} days', $3)",
        [_hash_token(token), user_id, user_agent],
    )
    # 만료된 줄이 쌓이지 않게 가끔 쓸어 낸다. 서버리스에는 청소 시각이 없다.
    if secrets.randbelow(50) == 0:
        try:
            db().query("delete from sessions where expires_at < now()")
        except accounts.StoreError:
            pass
    return token


def logout(req: Request) -> Response:
    """세션을 **서버에서** 지운다. 쿠키만 지우면 훔쳐 간 값이 계속 산다."""
    check_write(req)
    token = req.cookie(COOKIE_SESSION)
    if token:
        try:
            db().query("delete from sessions where token_hash = $1", [_hash_token(token)])
        except accounts.StoreError as err:
            log.warning("세션 삭제 실패: %s", err)
    return Response.json({"ok": True}, headers=_drop_session(req.secure))


def _drop_session(secure: bool) -> list[tuple[str, str]]:
    return [
        ("Set-Cookie", clear_cookie(cookie_name(COOKIE_SESSION, secure), secure=secure)),
        ("Set-Cookie", clear_cookie(cookie_name(COOKIE_CSRF, secure), secure=secure)),
    ]


# --- 엔드포인트 -------------------------------------------------------------


def me(req: Request) -> Response:
    """화면이 맨 처음 묻는 것 — 켜져 있는가, 나는 누구인가."""
    if not enabled():
        return Response.json({"enabled": False, "user": None})
    user = current_user(req)
    if not user:
        return Response.json({"enabled": True, "user": None})
    return Response.json({
        "enabled": True,
        "user": {
            "이름": user["name"],
            "이메일": user["email"],
            "사진": user["picture"],
            "가입일": str(user.get("created_at") or "")[:10],
            "관리자": user["admin"],
        },
    })


def withdraw(req: Request) -> Response:
    """회원 탈퇴 — 가입자 줄과 그가 남긴 것을 **한 트랜잭션으로** 지운다.

    개인정보보호법이 요구하는 길이라 화면에 반드시 있어야 한다. 참조가
    `on delete cascade` 라 users 한 줄이면 나머지도 따라 지워지지만,
    지워지는 것을 눈에 보이게 적어 둔다."""
    check_write(req)
    user = require_user(req)
    db().batch([
        ("delete from life_docs where user_id = $1", [user["id"]]),
        ("delete from bookmarks where user_id = $1", [user["id"]]),
        ("delete from sessions where user_id = $1", [user["id"]]),
        ("delete from users where id = $1", [user["id"]]),
    ])
    return Response.json({"ok": True}, headers=_drop_session(req.secure))


def life_doc(req: Request) -> Response:
    """내 역사 문서. 지금은 브라우저에만 있어 기기를 바꾸면 사라진다."""
    user = require_user(req)
    if req.method == "GET":
        row = db().one("select doc, updated_at from life_docs where user_id = $1",
                       [user["id"]])
        if not row:
            return Response.json({"doc": None})
        doc = row["doc"]
        if isinstance(doc, str):       # jsonb 가 문자열로 오는 경우
            doc = json.loads(doc)
        return Response.json({"doc": doc, "updated_at": row.get("updated_at")})

    if req.method == "DELETE":
        check_write(req)
        db().query("delete from life_docs where user_id = $1", [user["id"]])
        return Response.json({"ok": True})

    check_write(req)
    body = req.json_body()
    doc = body.get("doc")
    if not isinstance(doc, dict):
        raise AuthError("저장할 내용이 없습니다.")
    raw = json.dumps(doc, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_LIFE:
        raise AuthError("문서가 너무 큽니다 (512KB 까지).")
    db().query(
        """insert into life_docs (user_id, doc) values ($1, $2::jsonb)
           on conflict (user_id) do update
              set doc = excluded.doc, updated_at = now()""",
        [user["id"], raw],
    )
    return Response.json({"ok": True})


def bookmarks(req: Request) -> Response:
    """즐겨찾기와 메모. 노드 하나에 한 줄."""
    user = require_user(req)
    if req.method == "GET":
        rows = db().query(
            "select node_id, label, note, created_at from bookmarks "
            "where user_id = $1 order by created_at desc limit 1000",
            [user["id"]],
        )
        return Response.json({"목록": [
            {"id": r["node_id"], "이름": r.get("label") or "",
             "메모": r.get("note") or "", "때": str(r.get("created_at") or "")[:10]}
            for r in rows
        ]})

    check_write(req)
    if req.method == "DELETE":
        node_id = req.one("id")
        if not node_id:
            raise AuthError("어느 것을 지울지 알 수 없습니다.")
        db().query("delete from bookmarks where user_id = $1 and node_id = $2",
                   [user["id"], node_id])
        return Response.json({"ok": True})

    body = req.json_body()
    node_id = str(body.get("id") or "").strip()[:200]
    if not node_id:
        raise AuthError("어느 것을 담을지 알 수 없습니다.")
    count = db().one("select count(*) as n from bookmarks where user_id = $1",
                     [user["id"]])
    if int(count["n"]) >= MAX_BOOKMARKS:
        raise AuthError(f"즐겨찾기는 {MAX_BOOKMARKS}개까지입니다.")
    db().query(
        """insert into bookmarks (user_id, node_id, label, note)
                values ($1, $2, $3, $4)
           on conflict (user_id, node_id) do update
                set label = excluded.label, note = excluded.note""",
        [user["id"], node_id,
         str(body.get("label") or "")[:200], str(body.get("note") or "")[:MAX_NOTE]],
    )
    return Response.json({"ok": True})


# --- 표 --------------------------------------------------------------------
# (경로, 허용하는 메서드) → 함수. **여기 한 표뿐이다** — 로컬 서버와
# 서버리스 함수가 같은 것을 읽는다 (`server.dispatch` 머리글과 같은 이유).
ROUTES: dict[str, tuple[frozenset[str], object]] = {
    "/api/me":             (frozenset({"GET", "DELETE"}), None),
    "/api/auth/google":    (frozenset({"GET"}), start),
    "/api/auth/callback":  (frozenset({"GET"}), callback),
    "/api/auth/logout":    (frozenset({"POST"}), logout),
    "/api/my/life":        (frozenset({"GET", "PUT", "DELETE"}), life_doc),
    "/api/my/bookmarks":   (frozenset({"GET", "POST", "DELETE"}), bookmarks),
}


def route(req: Request) -> Response | None:
    """이 요청이 가입·계정의 것인가. 아니면 None 을 돌려 그래프 쪽으로 보낸다."""
    entry = ROUTES.get(req.path)
    if entry is None:
        return None
    methods, fn = entry
    if req.method not in methods:
        return Response.json({"error": "허용되지 않는 방법입니다."}, 405)
    if not enabled():
        # `/api/me` 만은 답한다 — 화면이 '아직 안 열렸음'을 알아야 단추를 눌렀을 때
        # 구글로 보내지 않고 한국어로 말한다 (AccountMenu 머리글).
        if req.path == "/api/me" and req.method == "GET":
            return Response.json({"enabled": False, "user": None})
        # 여기는 브라우저가 주소로 곧장 올 수 있는 자리다. JSON 을 뱉으면
        # 날것이 화면에 뜬다 — 사람이 읽는 쪽지로 답한다.
        if req.path == "/api/auth/google":
            return Response.page("로그인은 아직 준비 중입니다",
                                 "구글 계정으로 들어오는 길을 여는 중입니다. "
                                 "그동안에도 그래프를 보고 검색하는 데에는 아무 제한이 없습니다.",
                                 503)
        return Response.json({"error": "가입 기능이 아직 켜져 있지 않습니다."}, 503)

    try:
        if req.path == "/api/me":
            return me(req) if req.method == "GET" else withdraw(req)
        return fn(req)                     # type: ignore[operator]
    except AuthError as err:
        status = 401 if str(err) == "로그인이 필요합니다." else 400
        return Response.json({"error": str(err)}, status)
    except accounts.StoreError as err:
        log.warning("가입자 표 접근 실패: %s", err)
        return Response.json({"error": "가입자 정보에 닿지 못했습니다."}, 503)
