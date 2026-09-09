"""씨족의 파(派)를 노드로 세운다.

**왜 필요했나.** 2026-09-10 물음: "성씨들의 파 데이터를 가지고 있나?" 없었다.
본관은 `한국역대인명정보` 의 한 칸(`ORIGINNAME`)으로 갖고 있었지만 파는
어디에도 없었고, 파를 통째로 담은 공개 자료 자체가 없다. 제일 촘촘한
나무위키는 비영리 조건이라 광고가 걸린 이 화면에는 못 쓴다 — **문장을
바꿔 써도 2차적저작물이라 조건이 따라온다.** 그래서 본관마다 쓸 수 있는
자료를 따로 찾아 표에 적는다. 지금 둘이다:

    전주 이씨   장서각 기록유산DB 왕실족보 (파 182 · 족보 수록 인물수까지)
    김해 김씨   한국어 위키백과 '김해 김씨' 분파 절 (파 66)

**파는 새 노드 타입이 아니라 `org` 다.** 타입을 쪼개면 `EDGE_TYPES` 의
출발·도착 목록과 화면의 색이 함께 늘어난다 (`ontology.FORMS` 머리글이 매체를
두고 같은 판단을 이미 적어 뒀다). 왕조도 `org` 에 있고 파도 핏줄로 묶인
무리라 자리가 같다. 가르는 것은 타입이 아니라 `props.kind == "clan"` 과
`props.clan_level`(`본관`·`파`)이다.

**세우는 것.**

    ex:org:{본관}              본관 노드 (전주 이씨 · 김해 김씨)
    ex:org:{이름}              파 노드
    {파} --part_of--> {상위 파 또는 본관}
    {본관} --related_to--> {본관 지명}   (label='본관')
    {파조} --member_of--> {파}           (label='파조')

**본관을 지명에 잇는 까닭은 참이면서 동시에 그래프의 닻이기 때문이다.**
김해 김씨는 파조 가운데 우리 그래프에 있는 사람이 하나뿐이라, 지명에 걸지
않으면 씨족 나무 전체가 어느 씨앗에서도 한 홉 안에 들지 못해 `scope` 가
통째로 잘라 낸다. 나무는 `scope.close_clans` 가 한 덩어리로 데려온다.

**파조 엣지는 한자까지 맞는 노드에만 건다.** 이름만으로는 못 가른다 —
김해 김씨 파조 이름으로 그래프를 훑으면 스무 명 남짓 걸리는데 **한자가 맞는
사람은 하나도 없었다.** 생원공파 파조 김구(金銶) 자리에 백범 김구(金九)와
청풍 김구(金構)와 부령 김구(金坵)가 서고, 횡성공파 파조 김영서(金永瑞) 자리에는
1882년생 독립운동가 김영서가 선다. 전주 이씨에도 같은 함정이 있다 —
`함양군`·`담양군`·`영양군` 은 같은 이름의 **장소** 노드가 있다 (君과 郡이다).
그래서 노드 id 는 사람이 표에 적고, 빈 칸은 빈 채로 둔다.

**사람마다 파를 붙이는 것은 아직 하지 않는다.** 왕실족보에서 `이원익` 을
찾으면 241건이 나오고 완풍군파·의안대군파·주계군파에 다 있다. 생몰년·부명으로
가려야 하고, 그것도 표가 판정할 일이다 (§1-2).

**이름이 겹치면 표가 미리 가른다** (`이름` 칸). 김해 김씨 안에서만 참판공파가
둘(경파·삼현파)이고 생원공파가 둘(김련·김구)이며, 평장사공파는 전주 이씨에도
김해 김씨에도 있다. 가르는 말은 상위 파, 그것도 같으면 파조, 본관이 다르면
본관이다 — `참판공파 (경파)` · `생원공파 (김구)` · `평장사공파 (전주 이씨)`.

**한자가 다른 같은 파도 표에서 이미 합쳤다.** 장서각 쪽 목록은 이표기를 따로
센다 (`칠산군파` 가 漆山君派·㓒山君派 둘). 같은 파라 이름으로 합치고 수록
인물수를 더했으며, 밀린 표기는 `이표기` 칸에 두어 별칭으로 선다. 다만
**한자가 남의 파 것인 줄은 별칭으로 두지 않는다** — 원본에
`순평군파(桂城君派)` 가 있는데 계성군파는 따로 있다. 그대로 두면 계성군파의
한자가 남의 파 별칭이 되어 다음 병합이 둘을 하나로 본다.

판정은 `data/clans.tsv` 가 한다. 표에서 빠진 파 노드는 지운다 — 표가 언제나
기계를 이긴다. 원본과 파생본에 한 번씩 돌린다:

    uv run histgraph clans
    uv run histgraph --db data/korea.sqlite clans
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field

from .ontology import Edge, Node

SOURCE = "clans"


@dataclass(slots=True)
class Origin:
    """본관 하나. 지명 노드는 씨족 나무를 그래프에 붙들어 매는 닻이다."""

    label: str
    place: str
    desc: str


# 본관. 인구는 2015년 인구주택총조사(통계청)의 성씨·본관별 집계다.
ORIGINS: dict[str, Origin] = {
    "전주 이씨": Origin(
        label="전주 이씨",
        place="wd:Q42140",  # 전주시
        desc=(
            "전주를 본관으로 하는 이씨. 조선 왕실의 성씨이며, 2015년 인구가 "
            "263만 명으로 성씨와 본관을 통틀어 세 번째로 많다."
        ),
    ),
    "김해 김씨": Origin(
        label="김해 김씨",
        place="wd:Q42082",  # 김해시
        desc=(
            "김해를 본관으로 하는 김씨. 가락국 김수로왕의 후손을 자처하고 "
            "김유신을 중시조로 삼으며, 2015년 인구가 446만 명으로 성씨와 "
            "본관을 통틀어 가장 많다."
        ),
    ),
}


def origin_id(label: str) -> str:
    return f"ex:org:{label}"


def pa_id(name: str) -> str:
    return f"ex:org:{name}"


@dataclass(slots=True)
class Row:
    origin: str
    pa: str
    name: str          # 겹치면 갈라 둔 이름. 노드의 라벨이자 id 다.
    hanja: str
    variants: list[str]
    upper: str         # 상위 파의 **원래 이름** (같은 본관 안에서 찾는다)
    line: str          # 계(系). 파 노드를 만들지 않고 설명에만 적는다.
    founder: str
    founder_hanja: str
    members: int
    founder_node: str


@dataclass(slots=True)
class Report:
    nodes: int = 0
    edges: int = 0
    removed: int = 0
    founded: list[tuple[str, str]] = field(default_factory=list)
    orphan: list[tuple[str, str, int]] = field(default_factory=list)
    absent: list[tuple[str, str]] = field(default_factory=list)
    unknown_origin: list[str] = field(default_factory=list)
    unknown_upper: list[tuple[str, str]] = field(default_factory=list)


def load_table(path) -> list[Row]:
    rows: list[Row] = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            pa = (r.get("파") or "").strip()
            if not pa:
                continue
            rows.append(
                Row(
                    origin=(r.get("본관") or "").strip(),
                    pa=pa,
                    name=(r.get("이름") or pa).strip(),
                    hanja=(r.get("파(한자)") or "").strip(),
                    variants=[v for v in (r.get("이표기") or "").split() if v],
                    upper=(r.get("상위") or "").strip(),
                    line=(r.get("계") or "").strip(),
                    founder=(r.get("파조") or "").strip(),
                    founder_hanja=(r.get("파조(한자)") or "").strip(),
                    members=int((r.get("수록 인물수") or "0").replace(",", "") or 0),
                    founder_node=(r.get("파조 노드") or "").strip(),
                )
            )
    return rows


def _describe(row: Row, upper_name: str | None) -> str:
    """파 노드의 설명. **비워 두면 `scope` 가 단체를 통째로 뺀다**
    (`scope.UNDESCRIBED_DROP_TYPES`). 지어내지 않고 표가 아는 것만 적는다."""
    if upper_name:
        head = f"{row.origin} {upper_name}에서 갈라진 파."
    elif row.line:
        head = f"{row.origin}의 분파. {row.line}에 속한다."
    else:
        head = f"{row.origin}의 분파."
    if row.founder and row.members:
        tail = (f" 파조는 {row.founder}이며, 족보에 오른 자손이 "
                f"{row.members:,}명이다.")
    elif row.founder:
        tail = f" 파조는 {row.founder}이다."
    elif row.members:
        tail = f" 족보에 오른 자손이 {row.members:,}명이다."
    else:
        tail = ""
    return head + tail


def build(store, table: list[Row], dry_run: bool = False) -> Report:
    """표대로 본관·파 노드와 엣지를 세우고, 표에 없는 파 노드는 지운다."""
    rep = Report()
    known = {r["id"] for r in store.conn.execute("SELECT id FROM nodes")}

    # 같은 본관 안에서 '상위' 칸이 가리키는 파를 찾는다.
    by_origin: dict[str, dict[str, Row]] = {}
    for row in table:
        by_origin.setdefault(row.origin, {})[row.pa] = row

    nodes: list[Node] = []
    edges: list[Edge] = []
    used: set[str] = set()

    for label in sorted({r.origin for r in table}):
        org = ORIGINS.get(label)
        if org is None:
            # 표에 새 본관이 들어왔는데 지명 닻이 없다. 세우되 알린다.
            rep.unknown_origin.append(label)
            org = Origin(label=label, place="", desc=f"{label}.")
        nodes.append(
            Node(
                id=origin_id(label),
                type="org",
                label=label,
                source=SOURCE,
                description=org.desc,
                props={"kind": "clan", "clan_level": "본관"},
            )
        )
        used.add(origin_id(label))
        if org.place and org.place in known:
            edges.append(
                Edge(src=origin_id(label), dst=org.place, type="related_to",
                     source=SOURCE, label="본관")
            )

    for row in table:
        upper_row = by_origin.get(row.origin, {}).get(row.upper) if row.upper else None
        if row.upper and upper_row is None:
            # **조용히 뿌리에 붙이지 않는다.** 장서각 목록에는 '효령대군파'가
            # 우산 이름으로만 있고 줄이 따로 없어서, 그 아래 63개가 전부
            # 본관 바로 아래로 올라가 세 층짜리 나무가 두 층이 됐다.
            # 가지가 없어진 것을 알아볼 방법은 이 관문뿐이다.
            rep.unknown_upper.append((row.origin, row.upper))
        nodes.append(
            Node(
                id=pa_id(row.name),
                type="org",
                label=row.name,
                source=SOURCE,
                aliases=[a for a in [row.pa, row.hanja, *row.variants]
                         if a and a != row.name],
                description=_describe(row, upper_row.pa if upper_row else None),
                props={
                    "kind": "clan",
                    "clan_level": "파",
                    "clan_origin": row.origin,
                    **({"members": row.members} if row.members else {}),
                },
            )
        )
        used.add(pa_id(row.name))
        upper_id = pa_id(upper_row.name) if upper_row else origin_id(row.origin)
        # **라벨을 붙인다.** `part_of` 의 타입 이름은 '상위'라, 화면이
        # "덕천군파는 전주 이씨의 일부다"라고 읽고 묶음 머리도 '상위 · 234'
        # 가 된다 — 무엇의 목록인지, 파가 무엇인지가 사라진다. 라벨이 있으면
        # 화면은 그 라벨의 규칙으로 읽는다: '속한 문중' · '갈라진 파' ·
        # "…에서 갈라져 나온 파다" (`server.LABEL_DIR_HEAD` · `relations.js`).
        edges.append(Edge(src=pa_id(row.name), dst=upper_id,
                          type="part_of", source=SOURCE, label="분파"))
        if not row.founder_node:
            rep.orphan.append((row.origin, row.name, row.members))
            continue
        if row.founder_node not in known:
            # 표가 가리키는 노드가 이 그래프에 없다. 파생본에서는 흔한 일이다
            # (원본에만 있는 인물). 세어서 보여만 준다.
            rep.absent.append((row.name, row.founder_node))
            continue
        edges.append(
            Edge(src=row.founder_node, dst=pa_id(row.name), type="member_of",
                 source=SOURCE, label="파조")
        )
        rep.founded.append((row.name, row.founder_node))

    stale = sorted(
        r["id"]
        for r in store.conn.execute(
            "SELECT id FROM nodes WHERE json_extract(props,'$.kind')='clan'"
        )
        if r["id"] not in used
    )
    rep.nodes, rep.edges, rep.removed = len(nodes), len(edges), len(stale)
    if not dry_run:
        # **먼저 옛 엣지를 걷어낸다.** 표가 바뀌면 상위가 바뀐다 — 김해 김씨를
        # 표에 더했을 때, 노드 이름은 그대로라 살아남고 '전주 이씨에 속한다'는
        # 옛 엣지만 남아 김해의 파 43개가 전주 이씨 아래에 섰다. 노드만
        # 지우는 청소로는 이것을 못 잡는다.
        store.conn.execute("DELETE FROM edges WHERE source = ?", (SOURCE,))
        store.upsert_nodes(nodes)
        store.upsert_edges(edges)
        if stale:
            marks = ",".join("?" * len(stale))
            store.conn.execute(
                f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
                (*stale, *stale),
            )
            store.conn.execute(f"DELETE FROM nodes WHERE id IN ({marks})", stale)
            store.conn.execute(f"DELETE FROM aliases WHERE node_id IN ({marks})", stale)
            store.conn.commit()
        store.log_ingest(SOURCE, len(nodes), len(edges))
    return rep
