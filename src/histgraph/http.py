"""디스크 캐시 + 레이트리밋이 붙은 HTTP 페처.

공공 API 는 느리고 호출 제한이 있다. 개발 중 같은 요청을 반복하므로
응답을 캐시해서 재실행이 공짜가 되게 한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# Wikimedia 는 User-Agent 에 연락처를 요구한다 — 비워두면 요청이 차단되고
# JSON 대신 오류 HTML 이 돌아온다. 다만 공개 저장소에 개인 주소를 박아둘
# 이유는 없으므로 환경변수로 뺀다. 자기 주소를 쓰려면 .env 에 넣을 것.
CONTACT = os.environ.get(
    "HISTGRAPH_CONTACT", "7716286+eungene0204@users.noreply.github.com"
)
USER_AGENT = f"histgraph/0.1 (historical knowledge graph; contact: {CONTACT})"

# 재시도해도 소용없는 상태코드 (인증/권한/경로 오류).
NO_RETRY_STATUS = {400, 401, 404, 405, 410}
# 일시적 장애·레이트리밋. 더 긴 백오프로 재시도한다.
RETRY_STATUS = {403, 429, 500, 502, 503, 504}

_SECRET_PARAMS = re.compile(
    r"((?:serviceKey|ServiceKey|apiKey|authKey)=)[^&\s]+", re.IGNORECASE
)


def redact(text: str) -> str:
    """URL·에러메시지에서 인증키를 가린다. 로그와 예외 메시지에 키가
    그대로 찍히면 그 자체로 유출 경로가 된다."""
    return _SECRET_PARAMS.sub(r"\1***", text)


class Fetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        min_interval: float = 0.5,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last_call = 0.0

    def _cache_path(self, url: str, body: str | None) -> Path:
        key = hashlib.sha256(f"{url}|{body or ''}".encode()).hexdigest()[:32]
        return self.cache_dir / f"{key}.cache"

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def invalidate(self, url: str, params: dict[str, str] | None = None, body: str | None = None) -> bool:
        """캐시 항목을 지운다.

        응답이 HTTP 200 이어도 본문이 잘려 올 수 있다(연결 끊김, 게이트웨이
        절단). 그대로 캐시되면 파싱 실패가 재실행마다 똑같이 재현된다.
        호출부가 본문이 깨졌다고 판단하면 이걸로 무효화한다."""
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        path = self._cache_path(url, body)
        if path.exists():
            path.unlink()
            return True
        return False

    def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._fetch(url, None, headers, use_cache)

    def post(
        self,
        url: str,
        data: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        return self._fetch(url, urllib.parse.urlencode(data), headers, use_cache)

    def _fetch(
        self,
        url: str,
        body: str | None,
        headers: dict[str, str] | None,
        use_cache: bool,
    ) -> str:
        cache_file = self._cache_path(url, body)
        if use_cache and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        last_err: Exception | None = None

        for attempt in range(self.retries):
            self._throttle()
            try:
                req = urllib.request.Request(
                    url,
                    data=body.encode() if body else None,
                    headers=req_headers,
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                cache_file.write_text(text, encoding="utf-8")
                return text

            except urllib.error.HTTPError as err:
                # 공공 API 는 인증 실패 사유를 4xx 응답 '본문'에 담아 보낸다.
                # 여기서 삼켜버리면 호출부가 401 인지 경로 오류인지 알 수 없다.
                body = err.read().decode("utf-8", errors="replace")
                if err.code in NO_RETRY_STATUS:
                    # 캐시에 쓰지 않는다 — 실패 응답을 캐싱하면 신청 승인 후에도
                    # 계속 옛 에러가 돌아온다.
                    log.debug("HTTP %d %s", err.code, redact(url))
                    return body
                last_err = err
                # WDQS 는 과호출 시 403/502 로 막는다 — 공격적으로 물러난다.
                backoff = 5.0 if err.code in RETRY_STATUS else 1.0
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last_err = err
                backoff = 1.0

            wait = backoff * (2**attempt)
            log.warning(
                "요청 실패 (%d/%d) %s — %ss 후 재시도",
                attempt + 1, self.retries, redact(str(last_err)), wait,
            )
            if attempt < self.retries - 1:
                time.sleep(wait)

        raise RuntimeError(f"요청 실패: {redact(url)}") from last_err
