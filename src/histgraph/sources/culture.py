"""문화공공데이터광장(culture.go.kr / api.kcisa.kr) 커넥터.

data.go.kr 과 마찬가지로 **API 별 활용신청**이 필요하다. 신청 전에는
어떤 경로로 호출해도 `{"message":"Unauthorized","http_status_code":401}`
이 돌아온다 (키가 유효해도 마찬가지).

실측한 호출 규약:
  - 호스트/경로: http://api.kcisa.kr/openapi/service/rest/{그룹}/{오퍼레이션}
                 또는 http://api.kcisa.kr/{API_ID}/request
  - `/openapi/API_*` 형태는 "No context-path matches" — 잘못된 경로다.
  - 인증은 serviceKey 쿼리파라미터. Authorization 헤더도 시도했으나
    동일하게 401 이라 신청 승인 전에는 구분되지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from ..http import Fetcher

log = logging.getLogger(__name__)

SOURCE = "kcisa"
BASE = "http://api.kcisa.kr"


class CultureAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    key: str
    name: str
    path: str
    detail_page: str


# 역사 그래프에 쓸 후보 API. 활용신청 승인 후 실제 응답 스펙에 맞춰
# 정규화 함수를 붙인다.
CANDIDATES: dict[str, Endpoint] = {
    "museum_relics": Endpoint(
        key="museum_relics",
        name="국립중앙박물관 소장품 (유물)",
        path="/API_CNV_049/request",
        detail_page="https://www.culture.go.kr/data/openapi/openapiList.do?category=B",
    ),
    "heritage_meta": Endpoint(
        key="heritage_meta",
        name="문화유산 메타데이터",
        path="/openapi/service/rest/meta/HNPperf",
        detail_page="https://www.culture.go.kr/data/openapi/openapiView.do?id=311&category=B&gubun=A",
    ),
}


def api_key() -> str:
    key = os.environ.get("CULTURE_API_KEY", "").strip()
    if not key:
        raise CultureAuthError("CULTURE_API_KEY 가 설정되지 않았습니다 (.env 확인)")
    return key


def _raise_on_auth_error(text: str) -> None:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        if data.get("http_status_code") == 401 or data.get("message") == "Unauthorized":
            raise CultureAuthError(
                "401 Unauthorized — 해당 API 에 '활용신청'이 필요합니다 "
                "(문화공공데이터광장 > 마이페이지 > 활용신청)"
            )
        return

    # 경로가 틀리면 게이트웨이가 평문/HTML 을 돌려준다. 데이터로 오인하면
    # 안 되므로 명시적으로 구분한다.
    if "No context-path" in text or stripped.startswith("<!DOCTYPE"):
        raise CultureAuthError("엔드포인트 경로가 잘못됨 (API 명세 확인 필요)")


def call(
    fetcher: Fetcher, endpoint: Endpoint, extra_params: dict[str, str] | None = None
) -> str:
    params = {
        "serviceKey": api_key(),
        "numOfRows": "10",
        "pageNo": "1",
        **(extra_params or {}),
    }
    text = fetcher.get(f"{BASE}{endpoint.path}", params, use_cache=False)
    _raise_on_auth_error(text)
    return text


def check_key(fetcher: Fetcher) -> dict[str, str]:
    """후보 API 별 활용신청 상태 진단."""
    results: dict[str, str] = {}
    for key, ep in CANDIDATES.items():
        try:
            call(fetcher, ep)
            results[ep.name] = "OK — 호출 가능"
        except CultureAuthError as err:
            results[ep.name] = str(err)
        except Exception as err:
            results[ep.name] = f"호출 실패: {type(err).__name__}: {err}"
    return results


def parse_items(text: str) -> list[dict]:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(text)
        body = data.get("response", {}).get("body", {})
        items = body.get("items", {})
        if isinstance(items, dict):
            items = items.get("item", [])
        return items if isinstance(items, list) else [items]

    root = ET.fromstring(text)
    return [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.iter("item")
    ]
