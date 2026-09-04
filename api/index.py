"""배포된 화면이 /api 로 부르는 곳 — Vercel 서버리스 함수 진입점.

**로컬과 같은 코드를 부른다.** 엔드포인트 표는 histgraph.server.dispatch 하나뿐이고
여기서는 HTTP 껍데기만 씌운다. 로컬(`histgraph serve`)과 다른 점은 둘이다.

1. 정적 파일을 내주지 않는다. 화면(web/dist)은 Vercel 이 CDN 에서 바로 내주고,
   이 함수는 /api 만 맡는다.
2. DB 를 읽기 전용으로 연다. 함수의 파일시스템에는 쓸 수 없어서, 평소처럼 열면
   sqlite 가 저널을 만들려다 첫 요청부터 죽는다.

경로를 __p 로 받는 이유는 vercel.json 의 rewrite 때문이다. 파일 하나(api/index.py)
가 /api 전부를 맡아야 번들(21MB DB 포함)이 엔드포인트 수만큼 복제되지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histgraph import pages  # noqa: E402
from histgraph.server import GraphAPI, dispatch  # noqa: E402

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

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            # 글로 읽는 장(`/n/<id>`·`/sitemap.xml`). rewrite 가 `/api/n/…`
            # 으로 바꿔 넘기므로 같은 표(pages.route)가 양쪽을 다 받는다.
            page = pages.route(api, _path(url))
            if page is not None:
                self._send(*page)
                return
            status, payload = dispatch(api, _path(url), parse_qs(url.query))
        except (ValueError, KeyError) as err:
            status, payload = 400, {"error": f"{type(err).__name__}: {err}"}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 그래프는 배포 사이에 바뀌지 않는다. 엣지에 재워 두면 같은 노드를
        # 다시 펼칠 때 함수를 깨우지 않는다.
        self.send_header("Cache-Control", "public, max-age=0, s-maxage=86400")
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
