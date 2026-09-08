"""배포된 화면이 /api 로 부르는 곳 — Vercel 서버리스 함수 진입점.

**로컬과 같은 코드를 부른다.** 엔드포인트 표는 histgraph.server.dispatch 와
histgraph.auth.ROUTES 둘뿐이고 여기서는 HTTP 껍데기만 씌운다. 로컬
(`histgraph serve`)과 다른 점은 둘이다.

1. 정적 파일을 내주지 않는다. 화면(web/dist)은 Vercel 이 CDN 에서 바로 내주고,
   이 함수는 /api 만 맡는다.
2. DB 를 읽기 전용으로 연다. 함수의 파일시스템에는 쓸 수 없어서, 평소처럼 열면
   sqlite 가 저널을 만들려다 첫 요청부터 죽는다.

경로를 __p 로 받는 이유는 vercel.json 의 rewrite 때문이다. 파일 하나(api/index.py)
가 /api 전부를 맡아야 번들(21MB DB 포함)이 엔드포인트 수만큼 복제되지 않는다.

**가입·계정 응답은 절대 엣지에 재우지 않는다.** 그래프 응답은 배포 사이에
바뀌지 않으므로 하루 재우지만, 그 규칙이 `/api/me` 에 닿으면 한 사람의
신원이 다음 사람에게 배달된다. auth 쪽 응답은 스스로 헤더를 들고 오므로
(`auth.Response`) 여기서는 그것을 **그대로** 쓴다 — 캐시 헤더를 덧붙이지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histgraph import accounts, auth, pages  # noqa: E402

log = logging.getLogger("histgraph.api")
from histgraph.server import (  # noqa: E402
    LIFE_MAX_BODY, LIFE_POSTS, GraphAPI, dispatch, life_post,
)

# 화면이 띄우는 것은 시대 그래프다 — 전체 그래프(38,654 노드)가 아니라
# data/korea.sqlite. cli.py 의 serve 가 고르는 것과 같은 파일을 고른다.
# korea 는 시대 하나가 아니라 묶음이다 (scope.BUNDLES): 조선에서 일제강점기까지.
ERA = os.environ.get("HISTGRAPH_ERA", "korea")
DB = Path(os.environ.get("HISTGRAPH_DB") or ROOT / "data" / f"{ERA}.sqlite")

# 모듈 수준에 둔다. 함수가 따뜻할 때 재사용되어 요청마다 DB 를 다시 열지 않는다.
api = GraphAPI(DB, era=ERA, readonly=True)


def _path(url) -> str:
    """이 요청이 원래 가리키던 /api 경로.

    rewrite 가 /api/:path* 를 /api?__p=:path* 로 넘긴다. 넘어오지 않았거나
    치환이 안 된 채로 왔으면 요청 경로를 그대로 믿는다 — 둘 중 하나는 맞다."""
    q = parse_qs(url.query)
    tail = (q.get("__p") or [""])[0]
    if tail and ":path" not in tail:
        return "/api/" + tail.lstrip("/")
    if url.path.startswith("/api"):
        return url.path
    return "/api" + url.path if url.path.startswith("/") else "/api/" + url.path


class handler(BaseHTTPRequestHandler):  # noqa: N801  (Vercel 이 찾는 이름)
    server_version = "histgraph"

    # --- 가입·계정 ------------------------------------------------------

    def _read_body(self, limit: int = auth.MAX_BODY) -> bytes:
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0:
            return b""
        if size > limit:
            return b""      # 큰 것은 읽지 않는다. auth 가 400 으로 답한다.
        return self.rfile.read(size)

    def _try_auth(self, body: bytes = b"") -> bool:
        url = urlparse(self.path)
        req = auth.Request(self.command, _path(url), parse_qs(url.query),
                           dict(self.headers.items()), body)
        resp = auth.route(req)
        if resp is None:
            return False
        self.send_response(resp.status)
        for name, value in resp.headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        self.wfile.write(resp.body)
        return True

    def _auth_only(self) -> None:
        """그래프 쪽에는 GET 밖에 없다 — 나머지 메서드는 가입 경로뿐이다."""
        if self._try_auth(self._read_body()):
            return
        self._json(405, {"error": "허용되지 않는 방법입니다."})

    def do_POST(self) -> None:  # noqa: N802
        """가입 경로와 **개인 역사** 둘뿐이다.

        내 역사는 이야기를 받아 모델에게 묻는 유일한 문이라 여기 있어야 한다.
        로컬 서버와 다른 것은 셋이다 — 답이 나올 때까지 **한 요청 안에서 돈다**
        (서버리스에는 다음 요청까지 살아 있는 스레드가 없다), **파일을 남기지
        않는다** (디스크는 읽기 전용이고 남의 삶을 우리 서버에 두지 않는다),
        그리고 **로그인한 사람의 것만 받는다** (`_life_gate`)."""
        path = _path(urlparse(self.path))
        raw = self._read_body(LIFE_MAX_BODY if path in LIFE_POSTS else auth.MAX_BODY)
        if self._try_auth(raw):
            return
        if path not in LIFE_POSTS:
            self._json(405, {"error": "허용되지 않는 방법입니다."})
            return
        if self._life_gate(raw):
            return
        status, payload = life_post(api, path, raw, blocking=True, save=False)
        self._json(status, payload)

    def _life_gate(self, raw: bytes) -> bool:
        """내 역사는 로그인한 사람의 것이다. 막았으면 True (여기서 답했다).

        **여기서는 가입이 꺼져 있으면 아예 안 받는다.** 로컬 서버와 반대다 —
        거기서는 설정이 없다고 내 역사를 못 쓰게 되면 안 되지만(README '내
        역사만 로그인을 요구한다'), 열린 인터넷에서 문을 안 잠그면 아무나
        남의 이름으로 우리 모델을 부른다. 켜져 있으면 세션과 표를 함께 본다:
        표가 없으면 남의 사이트가 이 사람의 브라우저로 요청을 쏠 수 있다."""
        if not auth.enabled():
            self._json(503, {"error": "로그인이 아직 열리지 않아 내 역사를 쓸 수 없습니다."})
            return True
        url = urlparse(self.path)
        req = auth.Request(self.command, _path(url), parse_qs(url.query),
                           dict(self.headers.items()), raw)
        try:
            auth.require_user(req)
            auth.check_write(req)
        except auth.AuthError as err:
            status = 401 if str(err) == "로그인이 필요합니다." else 400
            self._json(status, {"error": str(err)})
            return True
        except accounts.StoreError as err:
            log.warning("가입자 표 접근 실패: %s", err)
            self._json(503, {"error": "가입자 정보에 닿지 못했습니다."})
            return True
        return False

    def do_PUT(self) -> None:  # noqa: N802
        self._auth_only()

    def do_DELETE(self) -> None:  # noqa: N802
        self._auth_only()

    # --- 그래프 ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if self._try_auth():
                return
            # 글로 읽는 장(`/n/<id>`·`/sitemap.xml`). rewrite 가 `/api/n/…`
            # 으로 바꿔 넘기므로 같은 표(pages.route)가 양쪽을 다 받는다.
            page = pages.route(api, _path(url))
            if page is not None:
                self._send(*page)
                return
            status, payload = dispatch(api, _path(url), parse_qs(url.query))
        except (ValueError, KeyError) as err:
            status, payload = 400, {"error": f"{type(err).__name__}: {err}"}

        self._json(status, payload, cache=True)

    def _json(self, status: int, payload: object, *, cache: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 그래프는 배포 사이에 바뀌지 않는다. 엣지에 재워 두면 같은 노드를
        # 다시 펼칠 때 함수를 깨우지 않는다. **사람마다 다른 응답은 아니다** —
        # 그래서 cache 는 그래프 쪽에서만 켠다.
        self.send_header(
            "Cache-Control",
            "public, max-age=0, s-maxage=86400" if cache else "private, no-store",
        )
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status: int, ctype: str, text: str) -> None:
        """글로 읽는 장. JSON 과 같은 이유로 엣지에 재운다 —
        그래프는 배포 사이에 바뀌지 않는다."""
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "public, max-age=0, s-maxage=86400")
        self.end_headers()
        self.wfile.write(raw)
