"""공공데이터포털(data.go.kr) 범용 커넥터.

주의: data.go.kr 인증키는 계정 단위지만, **데이터셋마다 별도로 '활용신청'**
을 해야 그 키로 호출할 수 있다. 신청하지 않은 API 는 키가 유효해도
`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(코드 30)를 돌려준다.
`check_key()` 로 활용신청 상태를 먼저 확인할 것.

활용신청 후 곧바로 되지 않으면 반영에 최대 1시간 걸린다.
"""

from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from ..http import Fetcher

log = logging.getLogger(__name__)

SOURCE = "datagokr"

# data.go.kr 에러 코드 -> 사람이 읽을 설명
ERROR_CODES = {
    "30": "등록되지 않은 서비스키 — 해당 데이터셋에 '활용신청'이 필요합니다",
    "31": "활용기간 만료 — 연장 신청 필요",
    "22": "일일 호출 한도 초과",
    "20": "서비스 접근 거부",
    "12": "존재하지 않는 서비스 — 엔드포인트 경로가 잘못됨",
    "10": "잘못된 요청 파라미터",
}

# errMsg 문자열로도 매칭한다 (코드가 비어 오는 경우가 있음)
ERROR_MESSAGES = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": ERROR_CODES["30"],
    "NO_OPENAPI_SERVICE_ERROR": ERROR_CODES["12"],
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": ERROR_CODES["22"],
    "SERVICE_ACCESS_DENIED_ERROR": ERROR_CODES["20"],
    "DEADLINE_HAS_EXPIRED_ERROR": ERROR_CODES["31"],
}


class DataGoKrAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    """수집 대상 데이터셋. 활용신청 승인 후 여기에 추가한다."""

    key: str
    name: str
    url: str
    dataset_page: str
    params: dict[str, str]


# 역사 그래프에 쓸 만한 데이터셋 목록.
# 활용신청 승인 전에는 호출해도 코드 30 이 돌아온다.
CANDIDATES: dict[str, Endpoint] = {
    "relics": Endpoint(
        key="relics",
        name="문화체육관광부_20개 기관 유물정보",
        url="https://apis.data.go.kr/B553457/nopenapi/rest/publicperformancedisplays/realm",
        dataset_page="https://www.data.go.kr/data/15105038/openapi.do",
        params={"numOfRows": "10", "pageNo": "1"},
    ),
    "heritage_spatial": Endpoint(
        key="heritage_spatial",
        name="국가유산청_문화재 공간 정보",
        url="https://apis.data.go.kr/1400000/openapi/service/spcaService/spcaList",
        dataset_page="https://www.data.go.kr/data/3070426/openapi.do",
        params={"numOfRows": "10", "pageNo": "1"},
    ),
}


def api_key() -> str:
    key = os.environ.get("DATA_GO_KR_API_KEY", "").strip()
    if not key:
        raise DataGoKrAuthError(
            "DATA_GO_KR_API_KEY 가 설정되지 않았습니다 (.env 확인)"
        )
    return key


def _raise_on_auth_error(text: str) -> None:
    """공공데이터포털은 인증 실패도 HTTP 200 으로 준다. 본문을 봐야 한다."""
    stripped = text.lstrip()
    # 경로가 틀리면 API 응답이 아니라 게이트웨이 HTML 이 온다.
    if stripped.startswith("<!DOCTYPE") or "<html" in stripped[:200].lower():
        raise DataGoKrAuthError("엔드포인트 경로가 잘못됨 (API 명세 확인 필요)")
    if "OpenAPI_ServiceResponse" not in text and "errMsg" not in text:
        return
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return

    code = (root.findtext(".//returnReasonCode") or root.findtext(".//resultCode") or "").strip()
    msg = (root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg") or "").strip()

    # errMsg 봉투가 왔다는 건 예외 없이 실패다. 알려진 코드만 걸러내면
    # 모르는 에러가 '정상'으로 통과해 버린다.
    explain = ERROR_CODES.get(code) or ERROR_MESSAGES.get(msg)
    if explain:
        raise DataGoKrAuthError(f"[{code or msg}] {explain}")
    if msg or code:
        raise DataGoKrAuthError(f"API 오류 [{code}] {msg}")


def call(
    fetcher: Fetcher,
    endpoint: Endpoint,
    extra_params: dict[str, str] | None = None,
    *,
    response_type: str = "xml",
) -> str:
    params = {
        "serviceKey": api_key(),
        **endpoint.params,
        **(extra_params or {}),
    }
    if response_type == "json":
        params["type"] = "json"
    text = fetcher.get(endpoint.url, params, use_cache=False)
    _raise_on_auth_error(text)
    return text


def check_key(fetcher: Fetcher) -> dict[str, str]:
    """등록된 후보 데이터셋 각각에 대해 활용신청 상태를 진단한다."""
    results: dict[str, str] = {}
    for key, ep in CANDIDATES.items():
        try:
            call(fetcher, ep)
            results[key] = "OK — 호출 가능"
        except DataGoKrAuthError as err:
            results[key] = str(err)
        except Exception as err:  # 네트워크/엔드포인트 경로 문제
            results[key] = f"호출 실패: {type(err).__name__}: {err}"
    return results


def parse_items(text: str) -> list[dict]:
    """XML/JSON 응답 공통 item 추출."""
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
