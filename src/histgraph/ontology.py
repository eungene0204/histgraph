"""histgraph 온톨로지 스키마.

노드/엣지 타입을 한 곳에서 정의한다. 모든 소스 커넥터는 원본 필드를
여기 정의된 타입으로 정규화해서 내보내야 한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
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

# --- 타입 안의 갈래 -------------------------------------------------------
# 씨족의 본관·파는 **새 타입이 아니라 `org` 다** (`clans.py` 머리글, 아래
# FORMS 와 같은 판단). 타입을 늘리면 EDGE_TYPES 의 출발·도착 목록과 화면의
# 색이 함께 늘어나는데, 파가 하는 일은 사람을 묶는 것뿐이라 그만한 값이
# 없다. 대신 **화면이 부를 이름은 있어야 한다** — 덕천군파의 타입 딱지에
# '단체·국가·왕조'라고 적으면 조선총독부와 같은 것으로 읽힌다.
# 색을 새로 뽑지 않고 글자로 가르는 이유는 graph-drawer.md §12.21 에 있다.
CLAN_LABELS: dict[str, str] = {"본관": "본관", "파": "분파"}


def type_label(node_type: str, props: dict | None = None) -> str:
    """화면의 타입 딱지에 세울 이름. 타입 안에서 뜻이 갈리는 노드는
    그 이름으로 부른다 (지금은 본관·파 하나뿐이다)."""
    props = props or {}
    if props.get("kind") == "clan":
        name = CLAN_LABELS.get(props.get("clan_level") or "")
        if name:
            return name
    return NODE_TYPES.get(node_type, node_type)


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
    # 만든 사람. 도착에 `media` 가 있는 이유: 소설·시·영화도 지은 사람이 있다
    # (『김약국의 딸들』은 박경리가 썼다). 매체를 빼 두면 `works` 가 실어 온
    # 작품 660편이 만든 이를 영영 못 받는다 (`creators`, 2026-09-10).
    "created": ("제작", ("person", "org"), ("artwork", "heritage", "media")),
    "located_in": ("소재지", ("heritage", "artwork", "place"), ("place",)),
    # 작품이 **실체**를 다룰 때만 depicts 다. 주제어(사랑·복수·조직범죄)는
    # about 으로 간다. 둘을 섞으면 "이 사건을 다룬 작품"이라는 질의가
    # 곧바로 무너진다.
    "depicts": ("소재로 다룸", ("media", "artwork"), ("person", "event", "place", "org")),
    "about": ("주제", ("media", "artwork"), ("concept",)),
    "child_of": ("자녀", ("person",), ("person",)),
    "spouse_of": ("배우자", ("person",), ("person",)),
    # 사제. 방향은 스승 → 제자. 한국사에서 학맥은 당파와 직결된다(성혼 문인
    # → 서인)는 이유로 인포박스의 '스승'·'제자'를 버리지 않고 related_to 로
    # 남겨 뒀는데, 그 뜻이 라벨에도 없어 화면은 '관련 있다'밖에 못 했다.
    # 추출이 related_to 로 낸 인물끼리의 관계 761건 중 학맥이 가장 큰 갈래다
    # (`untangle`, 2026-09-05).
    "taught": ("사제", ("person",), ("person",)),
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
    # 원작. 작품끼리의 엣지다 — 소설이 드라마가 되고 드라마가 영화가 된다.
    # 인포박스의 '원작' 칸이 이것을 그대로 준다.
    "adapted_from": ("원작", ("media", "artwork"), ("media", "artwork")),
    # 시간축. 인물·사건은 연도와 '같은 실체'가 아니므로 same_as 가 아니라
    # 엣지로 잇는다. 출생/사망/시작/종료는 엣지 label 로 구분한다.
    "dated_to": ("시점", tuple(NODE_TYPES), ("period",)),
    # 인과. **이 그래프가 온톨로지인 이유다** — "임진왜란이 수십 년 뒤
    # 병자호란에 어떻게 이어졌나"는 참여·장소·시대 엣지로는 답할 수 없고,
    # 원인에서 결과로 가는 엣지를 따라가야 한다 (`causes`·`/api/chain`).
    # 방향은 언제나 원인 → 결과. 라벨은 인과의 종류(원인·배경·계기·영향,
    # `causes.KINDS`)고, '어떻게'는 `props.how` 한 구절과 `props.evidence`
    # 인용이 말한다. 원인 쪽에 단체·인물·개념을 허용하는 이유: 한국사
    # 서술의 인과는 사건끼리만 오가지 않는다 — '후금의 성장'이 정묘호란의
    # 배경이고 '동학'이 동학농민운동의 뿌리다. 결과 쪽도 사건만이 아니다
    # ('임진왜란 → 명의 쇠퇴'는 org 가 결과다).
    "caused": ("원인", ("event", "org", "person", "concept"), ("event", "org", "concept")),
    "part_of": ("상위", tuple(NODE_TYPES), tuple(NODE_TYPES)),
    "related_to": ("관련", tuple(NODE_TYPES), tuple(NODE_TYPES)),
}


# --- 카디널리티 -----------------------------------------------------------
# 한 출발 노드가 이 엣지로 가리킬 수 있는 **서로 다른 도착 노드**의 최대 수.
# 팔란티어 파운드리는 링크마다 1:N 인지 N:M 인지를 반드시 적는데, 우리는
# 출발·도착 타입만 있었다. 사람은 한 곳에서 태어나고 한 곳에서 죽고 부모가
# 둘이다 — 그 이상이면 같은 곳을 다른 해상도로 말한 것(함경도·명천군)이거나
# 동명이인의 문서가 섞인 것이다 (실측: 정의공주의 어머니가 원경왕후와
# 소헌왕후, 김성우의 출생지가 부산과 광주). 여기 없는 타입은 제한이 없다.
# 재는 것은 `cardinality` 모듈, 쓸 때 경고하는 것은 `cardinality_problems`.
MAX_TARGETS: dict[str, int] = {
    "born_in": 1,
    "died_in": 1,
    "occurred_during": 1,
    "child_of": 2,   # 양부모는 여기 걸린다 — 인평대군의 양부 능창대군. 보고만 한다.
}


class OntologyError(ValueError):
    pass


# 이름표에 남아서는 안 되는 자국. 위키 주석·틀·링크·각주가 조각난 채로
# 별칭 칸에 들어오는 일이 있다. 꺾쇠는 국가유산 지정명(`金剛般若波羅蜜經
# <卷二∼五>`)에도 쓰이므로 **주석 자국만** 잡는다.
_MARKUP_LEFTOVER = re.compile(r"<!--|-->|\{\{|\}\}|\[\[|\]\]|<ref")


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
        # **별칭에 마크업이 섞여 들어오는 것도 여기서 막는다.** 별칭은
        # 화면에 이름표로 그대로 서므로 지우다 만 위키 문법이 남으면
        # 곧바로 보인다 — 을사사화의 '다른 이름' 칸에 있던 편집자 쪽지
        # (`<!-- 잘 알려진 명칭으로 …`)가 이름표 두 개로 섰다 (2026-09-05).
        # 소스마다 따로 검사하면 언젠가 하나가 빠진다.
        self.aliases = [a for a in self.aliases if not _MARKUP_LEFTOVER.search(a)]
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


def cardinality_problems(edges: Iterable[Edge]) -> list[str]:
    """한 묶음 안에서 카디널리티를 넘는 출발 노드. 쓰기 전에 경고할 재료."""
    targets: dict[tuple[str, str], set[str]] = {}
    for e in edges:
        limit = MAX_TARGETS.get(e.type)
        if limit is None:
            continue
        targets.setdefault((e.src, e.type), set()).add(e.dst)
    return [
        f"{etype}: {src} 가 {len(dsts)}곳을 가리킴 (최대 {MAX_TARGETS[etype]})"
        for (src, etype), dsts in sorted(targets.items())
        if len(dsts) > MAX_TARGETS[etype]
    ]
