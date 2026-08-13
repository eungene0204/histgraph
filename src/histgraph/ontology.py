"""histgraph 온톨로지 스키마.

노드/엣지 타입을 한 곳에서 정의한다. 모든 소스 커넥터는 원본 필드를
여기 정의된 타입으로 정규화해서 내보내야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- 노드 타입 -------------------------------------------------------------
# 값은 저장/직렬화용 안정 키, 라벨은 UI 표기용.
NODE_TYPES: dict[str, str] = {
    "person": "인물",
    "event": "사건",
    "place": "장소",
    "artwork": "예술작품",
    "heritage": "유물·문화재",
    "media": "영화·드라마",
    "org": "단체·국가·왕조",
    "period": "시대",
    # 직위는 조직이 아니다 (영의정, 국왕…). 별도 타입이라야 "이 자리를
    # 거쳐간 인물들" 같은 질의가 가능해진다.
    "role": "직위·칭호",
}

# --- 엣지 타입 -------------------------------------------------------------
# (키, 라벨, 출발 노드 타입, 도착 노드 타입)
# 그래프의 가치는 엣지에 있다. 소스별로 어떤 엣지를 채울 수 있는지가
# 커넥터 설계의 기준이 된다.
EDGE_TYPES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "participated_in": ("참여", ("person", "org"), ("event",)),
    "occurred_at": ("발생 장소", ("event",), ("place",)),
    "occurred_during": ("발생 시기", ("event",), ("period",)),
    "born_in": ("출생지", ("person",), ("place",)),
    "died_in": ("사망지", ("person",), ("place",)),
    "created": ("제작", ("person", "org"), ("artwork", "heritage")),
    "located_in": ("소재지", ("heritage", "artwork", "place"), ("place",)),
    "depicts": ("소재로 다룸", ("media", "artwork"), ("person", "event", "place")),
    "child_of": ("자녀", ("person",), ("person",)),
    "spouse_of": ("배우자", ("person",), ("person",)),
    "member_of": ("소속", ("person",), ("org",)),
    "held_position": ("직위", ("person",), ("role", "org")),
    # 한국사에서 시대 구분은 왕조와 같다 — '조선시대'는 '조선'이라는 정체가
    # 정의한다. 따라서 org(왕조)도 도착 타입으로 허용한다. 별도 period 노드를
    # 만들면 같은 대상이 둘로 갈라진다.
    "from_period": ("시대", ("heritage", "artwork", "person", "event"), ("period", "org")),
    # 시간축. 인물·사건은 연도와 '같은 실체'가 아니므로 same_as 가 아니라
    # 엣지로 잇는다. 출생/사망/시작/종료는 엣지 label 로 구분한다.
    "dated_to": ("시점", tuple(NODE_TYPES), ("period",)),
    "part_of": ("상위", tuple(NODE_TYPES), tuple(NODE_TYPES)),
    "related_to": ("관련", tuple(NODE_TYPES), tuple(NODE_TYPES)),
}


class OntologyError(ValueError):
    pass


@dataclass(slots=True)
class Node:
    """정규화된 노드.

    id 는 `{source}:{native_id}` 형태의 전역 고유 키.
    (예: `wd:Q37682`, `khs:11-11-0000010000000`)
    """

    id: str
    type: str
    label: str
    source: str
    aliases: list[str] = field(default_factory=list)
    start_date: str | None = None  # ISO8601 또는 부분 날짜("1392", "1392-07")
    end_date: str | None = None
    lat: float | None = None
    lon: float | None = None
    description: str | None = None
    url: str | None = None
    props: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in NODE_TYPES:
            raise OntologyError(f"알 수 없는 노드 타입: {self.type!r}")
        if ":" not in self.id:
            raise OntologyError(f"노드 id 는 '{{source}}:{{id}}' 형식이어야 함: {self.id!r}")
        if not self.label:
            raise OntologyError(f"라벨이 비어 있음: {self.id}")


@dataclass(slots=True)
class Edge:
    """정규화된 엣지. 모든 엣지는 출처(provenance)를 갖는다."""

    src: str
    dst: str
    type: str
    source: str
    label: str | None = None  # 엣지별 부가 설명 (예: 직위명)
    start_date: str | None = None
    end_date: str | None = None
    confidence: float = 1.0  # 1.0=구조화 소스, <1.0=텍스트 추론
    props: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in EDGE_TYPES:
            raise OntologyError(f"알 수 없는 엣지 타입: {self.type!r}")
        if not (0.0 < self.confidence <= 1.0):
            raise OntologyError(f"confidence 범위 오류: {self.confidence}")


def validate_edge_endpoints(edge: Edge, nodes: dict[str, Node]) -> str | None:
    """엣지 양끝 노드 타입이 스키마에 맞는지 검사. 문제 없으면 None."""
    src_node, dst_node = nodes.get(edge.src), nodes.get(edge.dst)
    if src_node is None or dst_node is None:
        return None  # 아직 수집되지 않은 노드 — 댕글링은 store 에서 따로 집계
    _, allowed_src, allowed_dst = EDGE_TYPES[edge.type]
    if src_node.type not in allowed_src:
        return f"{edge.type}: 출발 타입 {src_node.type} 허용 안 됨 ({allowed_src})"
    if dst_node.type not in allowed_dst:
        return f"{edge.type}: 도착 타입 {dst_node.type} 허용 안 됨 ({allowed_dst})"
    return None
