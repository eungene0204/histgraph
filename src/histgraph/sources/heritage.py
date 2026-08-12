"""국가유산청(구 문화재청) Open API 커넥터.

인증키가 필요 없고 즉시 동작한다. 유물·문화재 노드의 1차 공급원.
목록 API 로 키를 모으고, 상세 API 로 시대/소재지/설명을 채운다.

  목록: https://www.khs.go.kr/cha/SearchKindOpenapiList.do
  상세: https://www.khs.go.kr/cha/SearchKindOpenapiDt.do

주의: 상세 API 의 ccbaAsno 는 목록이 돌려주는 13자리 값을 그대로 써야
한다. 8자리·10자리로 자르면 200 응답에 빈 필드가 돌아온다(에러 아님).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from ..http import Fetcher
from ..ontology import Edge, Node

log = logging.getLogger(__name__)

LIST_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiList.do"
DETAIL_URL = "https://www.khs.go.kr/cha/SearchKindOpenapiDt.do"

SOURCE = "khs"

# ccbaKdcd — 지정 종목 코드
KIND_CODES = {
    "11": "국보",
    "12": "보물",
    "13": "사적",
    "15": "명승",
    "16": "천연기념물",
    "17": "국가무형유산",
    "18": "국가민속문화유산",
    "21": "시도유형문화유산",
    "22": "시도무형유산",
    "23": "시도기념물",
    "24": "시도민속문화유산",
    "31": "문화유산자료",
    "79": "등록문화유산",
}

# ccbaCtcd — 시도 코드
CTCD_CODES = {
    "11": "서울특별시", "21": "부산광역시", "22": "인천광역시", "23": "대구광역시",
    "24": "광주광역시", "25": "대전광역시", "26": "울산광역시", "45": "세종특별자치시",
    "31": "경기도", "32": "강원특별자치도", "33": "충청북도", "34": "충청남도",
    "35": "전북특별자치도", "36": "전라남도", "37": "경상북도", "38": "경상남도",
    "50": "제주특별자치도",
}


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    val = el.text.strip()
    return val or None


def _node_id(kdcd: str, ctcd: str, asno: str) -> str:
    return f"{SOURCE}:{kdcd}-{ctcd}-{asno}"


def place_id(sido: str, sigungu: str | None = None) -> str:
    """행정구역 기반 장소 ID. 여러 소스가 같은 지역을 가리키게 하는 접합점."""
    return f"kr:place:{sido}" + (f":{sigungu}" if sigungu else "")


def period_id(name: str) -> str:
    return f"kr:period:{name}"


def _parse_date(raw: str | None) -> str | None:
    """'19621220' -> '1962-12-20'."""
    if not raw or not re.fullmatch(r"\d{8}", raw):
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def fetch_list(
    fetcher: Fetcher, kdcd: str, ctcd: str, *, page_size: int = 100
) -> Iterator[dict[str, str]]:
    """지정종목 x 시도 조합의 전체 목록을 페이지네이션하며 흘려보낸다."""
    page = 1
    while True:
        xml = fetcher.get(
            LIST_URL,
            {
                "ccbaKdcd": kdcd,
                "ccbaCtcd": ctcd,
                "pageUnit": str(page_size),
                "pageIndex": str(page),
            },
        )
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as err:
            log.warning("목록 XML 파싱 실패 kdcd=%s ctcd=%s p=%d: %s", kdcd, ctcd, page, err)
            return

        items = root.findall("item")
        if not items:
            return

        for item in items:
            yield {child.tag: (child.text or "").strip() for child in item}

        total = int(_text(root.find("totalCnt")) or 0)
        if page * page_size >= total:
            return
        page += 1


def fetch_detail(fetcher: Fetcher, kdcd: str, ctcd: str, asno: str) -> dict[str, str]:
    xml = fetcher.get(
        DETAIL_URL, {"ccbaKdcd": kdcd, "ccbaCtcd": ctcd, "ccbaAsno": asno}
    )
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        log.warning("상세 XML 파싱 실패 %s-%s-%s: %s", kdcd, ctcd, asno, err)
        return {}
    item = root.find("item")
    if item is None:
        return {}
    return {child.tag: (child.text or "").strip() for child in item}


def ingest(
    fetcher: Fetcher,
    *,
    kinds: list[str] | None = None,
    regions: list[str] | None = None,
    limit: int | None = None,
    with_detail: bool = True,
) -> tuple[list[Node], list[Edge]]:
    """국가유산 목록/상세를 온톨로지 노드·엣지로 정규화한다."""
    kinds = kinds or ["11"]  # 기본: 국보
    regions = regions or list(CTCD_CODES)

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    count = 0

    for kdcd in kinds:
        for ctcd in regions:
            for row in fetch_list(fetcher, kdcd, ctcd):
                if limit is not None and count >= limit:
                    return list(nodes.values()), edges

                asno = row.get("ccbaAsno", "")
                name = row.get("ccbaMnm1", "")
                if not asno or not name:
                    continue

                nid = _node_id(kdcd, ctcd, asno)
                detail = fetch_detail(fetcher, kdcd, ctcd, asno) if with_detail else {}

                lat = row.get("longitude"), row.get("latitude")
                sido = row.get("ccbaCtcdNm") or CTCD_CODES.get(ctcd, "")
                sigungu = row.get("ccsiName") or None

                nodes[nid] = Node(
                    id=nid,
                    type="heritage",
                    label=name,
                    source=SOURCE,
                    aliases=[a for a in [row.get("ccbaMnm2")] if a],
                    description=detail.get("content") or None,
                    lat=_as_float(lat[1]),
                    lon=_as_float(lat[0]),
                    url=(
                        "https://www.heritage.go.kr/heri/cul/culSelectDetail.do"
                        f"?ccbaKdcd={kdcd}&ccbaAsno={asno}&ccbaCtcd={ctcd}"
                    ),
                    props={
                        "designation": row.get("ccmaName") or KIND_CODES.get(kdcd),
                        "designated_on": _parse_date(detail.get("ccbaAsdt")),
                        "quantity": detail.get("ccbaQuan"),
                        "address": detail.get("ccbaLcad"),
                        "admin": row.get("ccbaAdmin"),
                        # 국가유산청이 이미 4단계 분류 체계를 제공한다 —
                        # 온톨로지 카테고리 축으로 그대로 재사용
                        "category": [
                            detail.get(k)
                            for k in ("gcodeName", "bcodeName", "mcodeName", "scodeName")
                            if detail.get(k)
                        ],
                        "image": detail.get("imageUrl") or None,
                        "kdcd": kdcd, "ctcd": ctcd, "asno": asno,
                    },
                )

                # 소재지 엣지
                if sido:
                    pid = place_id(sido.strip(), sigungu)
                    nodes.setdefault(
                        pid,
                        Node(
                            id=pid,
                            type="place",
                            label=f"{sido.strip()} {sigungu}".strip() if sigungu else sido.strip(),
                            source=SOURCE,
                            props={"sido": sido.strip(), "sigungu": sigungu},
                        ),
                    )
                    edges.append(Edge(src=nid, dst=pid, type="located_in", source=SOURCE))

                # 시대 엣지 — ccceName 예: "조선시대", "고려시대"
                era = (detail.get("ccceName") or "").strip()
                if era:
                    perid = period_id(era)
                    nodes.setdefault(
                        perid, Node(id=perid, type="period", label=era, source=SOURCE)
                    )
                    edges.append(Edge(src=nid, dst=perid, type="from_period", source=SOURCE))

                count += 1

    return list(nodes.values()), edges


def _as_float(val: str | None) -> float | None:
    try:
        return float(val) if val else None
    except ValueError:
        return None
