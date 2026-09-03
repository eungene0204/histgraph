"""histgraph 온톨로지 스키마.

노드/엣지 타입을 한 곳에서 정의한다. 모든 소스 커넥터는 원본 필드를
여기 정의된 타입으로 정규화해서 내보내야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .koreanize import has_hangul, to_korean


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
    # 개념은 사건이 아니다. 자리가 없으면 개념이 사건 행세를 한다 —
    # 실측으로 '자살'·'간통죄'·'조직범죄'가 전부 사건 노드로 앉아 있었고,
    # 그 탓에 화면의 depicts 157건 중 진짜 역사 사건은 6건뿐이었다.
    # 사상·제도·풍습·소재가 여기 온다.
    "concept": "개념·주제",
}

# --- 매체 구분 -------------------------------------------------------------
# 영화·드라마·책·음악·다큐·게임을 **노드 타입으로 쪼개지 않는다.** 쪼개면
# EDGE_TYPES 의 출발·도착 목록이 여섯 배로 늘고, 화면의 색이 아홉에서
# 열다섯이 된다. 사용자가 하는 질의는 "이 사건을 다룬 **작품**"이지
# "이 사건을 다룬 **게임**"이 아니다. 매체별 필터는 화면의 토글로 충분하다.
#
# 대신 media 노드는 form 을 **반드시** 갖는다 (아래 Node.__post_init__).
# 나중에 채울 수 있는 값이 아니다 — 비면 화면에서 영영 구분이 안 된다.
FORMS: dict[str, str] = {
    "film": "영화",
    "series": "드라마",
    "documentary": "다큐멘터리",
    "animation": "애니메이션",
    "book": "책",
    "comic": "만화",
    "game": "게임",
    "music": "음악",
    "stage": "무대",
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
    # 작품이 **실체**를 다룰 때만 depicts 다. 주제어(사랑·복수·조직범죄)는
    # about 으로 간다. 둘을 섞으면 "이 사건을 다룬 작품"이라는 질의가
    # 곧바로 무너진다.
    "depicts": ("소재로 다룸", ("media", "artwork"), ("person", "event", "place", "org")),
    "about": ("주제", ("media", "artwork"), ("concept",)),
    "child_of": ("자녀", ("person",), ("person",)),
    "spouse_of": ("배우자", ("person",), ("person",)),
    "member_of": ("소속", ("person",), ("org",)),
    "held_position": ("직위", ("person",), ("role", "org")),
    # 한국사에서 시대 구분은 왕조와 같다 — '조선시대'는 '조선'이라는 정체가
    # 정의한다. 따라서 org(왕조)도 도착 타입으로 허용한다. 별도 period 노드를
    # 만들면 같은 대상이 둘로 갈라진다.
    # 출발 타입에 org·concept 이 있는 이유: 일제강점기를 넣으면서 드러났다.
    # 신흥무관학교·조선총독부(org)와 창씨개명·무단 통치(concept)는 그 시대를
    # 빼고 말할 수 없는데, 시대에 걸 길이 없으면 엣지가 하나도 없는 노드로
    # 들어와 `scope` 의 고립 노드 정리에서 통째로 사라진다.
    "from_period": (
        "시대",
        ("heritage", "artwork", "person", "event", "period", "org", "concept"),
        ("period", "org"),
    ),
    # 작품의 **배경**. 개봉연도(start_date)와 다른 축이다 — 『한산』은
    # 2022년에 나왔고 1592년을 다룬다. 연표가 어느 자리에 세울지는 이
    # 엣지가 정한다. 채우는 일은 아직 하지 않았고, 타입만 세워 둔다.
    # 도착에 org 를 허용하는 이유는 from_period 와 같다 — 한국사에서 시대
    # 구분은 왕조와 같아서, '조선을 배경으로 한 영화'의 배경은 조선이다.
    "set_in": ("배경", ("media", "artwork"), ("period", "place", "org")),
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
        # **한국어 아닌 설명은 여기서 막는다.** 소스가 늘어날 때마다
        # 커넥터마다 같은 검사를 적어 두면 언젠가 하나가 빠지고, 그 하나로
        # 화면에 영어가 다시 뜬다. 모든 커넥터가 Node 를 지나므로 관문은
        # 여기 하나면 된다. 옮길 수 있으면 옮기고, 없으면 비운다 —
        # 예외를 던지지 않는 이유는 설명 한 줄 때문에 수집 전체가 멈추면
        # 안 되기 때문이다.
        if self.description and not has_hangul(self.description):
            self.description = to_korean(self.description)
        # **작품은 무슨 매체인지 모른 채 들어올 수 없다.** 설명과 달리 이건
        # 나중에 채울 수 있는 값이 아니다 — 비어 있으면 화면에서 영화와
        # 드라마와 게임이 한 덩어리가 되고, 그 상태를 알아볼 방법도 없다.
        # 판정이 안 서는 작품은 노드를 만들지 말고 목록으로 보고할 것.
        if self.type == "media":
            form = self.props.get("form")
            if form not in FORMS:
                raise OntologyError(f"작품에 매체 구분(form)이 없거나 모름: {self.id} ({form!r})")


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
