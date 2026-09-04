"""설명이 어디서 온 글인지 — 화면에 **한 줄** 적기 위한 판정.

§1 은 자료 출처를 화면에 적지 말라 한다. 읽는 사람이 묻지 않은 것이라서다.
그런데 2026-09-05 사용자 결정으로 **설명 아래 한 줄**은 예외가 됐다 — 남의
글을 옮겨 왔으면 그 사실을 적어야 하는 것이 라이선스 의무이지 취향이
아니다. 위키백과 글은 저작자표시-동일조건변경허락(CC BY-SA)이고 공공기관
글(국편·국가유산청)은 출처 표시가 이용 조건이다. 그래서 규칙은 이렇다:

- 자리는 하나다 — 설명 문단 바로 아래. 제목·목록·검색에는 여전히 안 적는다.
- 말은 한국어다. 라이선스 이름도 한국어 정식 명칭으로 적는다.
- 어디서 왔는지 **확실할 때만** 적는다. 모르면 비운다 — 틀린 출처는 없는
  출처보다 나쁘다.

판정 재료는 `props.desc_source`(수집이 적어 둔 것)와 그 보조 표식들이다.
`desc_source` 가 비어 있는 옛 수집분은 `kowiki_url`·`canon`·`source` 로
되짚는다. 그래도 모르는 것이 있다 (`wd` 노드 815건 — 위키백과 글처럼
보이지만 표식이 없다). 그것은 비운다.
"""

from __future__ import annotations

CC_BY_SA = ("크리에이티브 커먼즈 저작자표시-동일조건변경허락 4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/deed.ko")
# 나무위키는 비영리 조건이 붙어 있다. 광고가 걸린 화면에 세우는 것 자체가
# 조건과 어긋난다 — 출처는 적되, 그 글은 빼는 쪽이 맞다 (HANDOFF 2026-09-05).
CC_BY_NC_SA = ("크리에이티브 커먼즈 저작자표시-비영리-동일조건변경허락 2.0 대한민국",
               "https://creativecommons.org/licenses/by-nc-sa/2.0/kr/deed.ko")


def desc_origin(source: str | None, props: dict, url: str | None = None) -> dict | None:
    """설명의 출처. {name, url, license, license_url} 또는 None(모름).

    `name` 은 화면에 적는 이름, `url` 은 그 글이 있는 문서, `license` 는
    한국어 정식 명칭(없으면 빈 문자열 — 공공기관 글은 출처 표시가 조건이지
    라이선스 이름을 세우는 것이 아니다)."""
    props = props or {}
    ds = props.get("desc_source") or ""

    # 국편 정본이 씌워진 노드가 먼저다. `nikh` 는 설명을 덮어쓰는데 옛
    # 수집분엔 위키백과 표식(`desc_source: kowiki`)이 그대로 남아 있다
    # (배포본 21건) — 그대로 두면 국편 글을 위키백과 글이라 적는다.
    if props.get("canon") == "nikh" or source == "nikh" or ds == "nikh":
        link = props.get("nikh_url") or (url if source == "nikh" else "")
        return {"name": "국사편찬위원회 우리역사넷", "url": link or "",
                "license": "", "license_url": ""}
    if "namu" in ds:
        return {"name": "나무위키", "url": props.get("namu_url") or "",
                "license": CC_BY_NC_SA[0], "license_url": CC_BY_NC_SA[1]}
    if "kowiki" in ds:
        return _kowiki(props)
    if ds == "aks":
        return {"name": "한국민족문화대백과사전", "url": props.get("desc_url") or "",
                "license": "", "license_url": ""}
    if ds in ("wd:ko", "사전"):
        # 위키데이터 한 줄은 CC0 라 의무는 없다. 그래도 어디서 왔는지는 적는다.
        return {"name": "위키데이터", "url": url or "", "license": "", "license_url": ""}

    # 여기부터는 desc_source 가 없는 옛 수집분. 보조 표식으로 되짚는다.
    if source == "khs":
        return {"name": "국가유산청 국가유산포털", "url": url or "",
                "license": "", "license_url": ""}
    if source in ("wd", "kowiki") and props.get("kowiki_url"):
        return _kowiki(props)
    return None


def _kowiki(props: dict) -> dict:
    return {"name": "한국어 위키백과", "url": props.get("kowiki_url") or "",
            "license": CC_BY_SA[0], "license_url": CC_BY_SA[1]}
