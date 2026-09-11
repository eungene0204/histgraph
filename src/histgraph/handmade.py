"""사람이 세우는 사건 — 어느 자료도 항목으로 갖고 있지 않은 일 (`events --table`).

2026-09-11 지적: "현대사 역사에 프로야구 개막이 없네?" 없는 것이 맞았다.
사건 시드(`wikipedia.EVENT_SEEDS`)는 **문서 이름을 적는 표**라 문서가 없는
일은 담지 못한다. 프로야구 개막이 그렇다 — 한국어 위키백과에는 리그
문서(`KBO 리그`)와 시즌 문서(`1982년 한국프로야구`)뿐이고, 시즌 문서는
스포츠 시즌이라 `prune` 이 지운다. 민족문화대백과에는 글이 있지만 항목은
'프로야구'(개념)여서 **1982년 3월 27일에 선 일**이 아니다.

그래서 마지막 자리를 하나 둔다: **정본이 문장으로는 적었는데 항목으로는
없는 일**을 사람이 표에 적고 기계가 세운다. 다른 표들과 규칙이 같다 —
표가 기계를 이기고, 근거 칸에 어디서 온 것인지 적고, 원본과 파생본에 한
번씩 돌린다.

**시드 표와 갈라 두는 이유**는 채우는 값이 다르기 때문이다. 시드는 이름만
적으면 문서가 설명·주소·날짜를 들고 오지만, 여기서는 그것을 사람이 적는다.
그래서 이 표는 **짧아야 한다** — 문서가 있는 일은 시드로 가는 것이 맞다.

관문 넷:

- 이름·설명에 한글이 있어야 한다 (§1). 설명이 비면 `scope` 가 뺀다 (§1-3).
- 근거 칸이 비면 세우지 않는다. 그 칸의 주소가 곧 화면의 출처 한 줄이다
  (`provenance.desc_origin` — 민백·국편·위키백과를 주소로 가른다).
- 같은 이름의 노드가 이미 있으면 세우지 않고 **보고한다**. 합치는 것은
  `dedupe` 쪽이다 (§1-4).
- 관계의 대상이 그래프에 없으면 그 줄의 그 엣지만 건너뛰고 센다.
  짐작으로 노드를 만들지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov
from .koreanize import has_hangul

ORIGIN = "events-table"
SOURCE = "hand"
ID_PREFIX = "kr:event:"
NODE_TYPE = "event"

# 표에 적는 관계 이름 -> (엣지 타입, 방향). `in` 은 대상에서 이 사건으로
# 들어오는 선이다 — 참여는 사람에서 사건으로 간다(`ontology.EDGE_TYPES`).
RELATIONS: dict[str, tuple[str, str]] = {
    "장소": ("occurred_at", "out"),
    "참여": ("participated_in", "in"),
    "관련": ("related_to", "out"),
    "원인": ("caused", "in"),
    "결과": ("caused", "out"),
}

# 근거 칸의 주소 -> 설명이 어디서 온 글인지 (`provenance.desc_origin` 이 읽는
# props). 표에 주소가 없으면 비운다 — 모르는 출처를 적지 않는다.
DESC_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("encykorea.aks.ac.kr", "aks", "desc_url"),
    ("contents.history.go.kr", "nikh", "nikh_url"),
    ("ko.wikipedia.org", "kowiki", "kowiki_url"),
)

_DATE = re.compile(r"^\d{3,4}(-\d{2}(-\d{2})?)?$")
_URL = re.compile(r"https?://[^\s]+")


class EventsTableError(ValueError):
    pass


@dataclass(frozen=True)
class Row:
    label: str
    start: str
    end: str
    era: str
    rels: tuple[tuple[str, str, str], ...]   # (관계 이름, 대상 id, 근거)
    desc: str
    note: str

    @property
    def node_id(self) -> str:
        return f"{ID_PREFIX}{self.label}"


@dataclass
class Report:
    made: list[str] = field(default_factory=list)        # 세운 사건 이름
    kept: int = 0                                        # 이미 같은 값으로 서 있던 것
    edges: int = 0                                       # 이은 관계
    collided: list[tuple[str, str]] = field(default_factory=list)   # (이름, 이미 있는 id)
    absent: list[tuple[str, str, str]] = field(default_factory=list)  # (이름, 관계, 없는 대상)


def _desc_props(note: str) -> dict[str, str]:
    """근거 칸의 주소로 설명의 출처를 적는다. 없으면 빈 칸이다."""
    m = _URL.search(note)
    if not m:
        return {}
    url = m.group(0).rstrip(").,")
    for host, ds, key in DESC_SOURCES:
        if host in url:
            props = {"desc_source": ds, key: url}
            if ds == "aks":
                props["canon"] = "aks"
            return props
    return {}


def load_table(path: Path) -> list[Row]:
    """표를 읽는다. 칸은 여섯이다 —
    `이름⇥날짜⇥시대⇥관계⇥설명⇥근거`.

    관계 칸은 `관계:대상 id=근거` 를 세미콜론으로 이어 적는다."""
    rows: list[Row] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 6:
            raise EventsTableError(
                f"{path}:{lineno} 이름·날짜·시대·관계·설명·근거 여섯 칸입니다: {raw!r}")
        label, date, era, rel_text, desc, note = parts[:6]
        if not label or not date or not era or not desc or not note:
            raise EventsTableError(
                f"{path}:{lineno} 관계 말고는 빈 칸을 둘 수 없습니다: {raw!r}")
        if not has_hangul(label) or not has_hangul(desc):
            raise EventsTableError(
                f"{path}:{lineno} 이름과 설명은 한국어로 적습니다 (§1): {raw!r}")
        start, _, end = date.partition("~")
        for d in (start, end):
            if d and not _DATE.match(d):
                raise EventsTableError(f"{path}:{lineno} 날짜가 아닙니다: {d!r}")
        if end and end < start:
            raise EventsTableError(f"{path}:{lineno} 끝이 시작보다 앞섭니다: {raw!r}")
        rels: list[tuple[str, str, str]] = []
        for chunk in rel_text.split(";"):
            chunk = chunk.strip()
            if not chunk or chunk == "-":
                continue
            name, _, rest = chunk.partition(":")
            target, _, evidence = rest.partition("=")
            name, target, evidence = name.strip(), target.strip(), evidence.strip()
            if name not in RELATIONS:
                raise EventsTableError(
                    f"{path}:{lineno} 모르는 관계입니다 ({'·'.join(RELATIONS)} 중 하나): {chunk!r}")
            if ":" not in target:
                raise EventsTableError(f"{path}:{lineno} 대상이 노드 id 가 아닙니다: {chunk!r}")
            # 관계의 근거는 **화면에 그 관계의 근거로 뜬다** (§1-6). 그래서
            # 줄 전체의 근거와 따로 적고, 한국어 문장이어야 한다.
            if not evidence or not has_hangul(evidence):
                raise EventsTableError(
                    f"{path}:{lineno} 관계마다 한국어 근거를 적습니다 (`관계:대상=근거`): {chunk!r}")
            rels.append((name, target, evidence))
        if label in seen:
            raise EventsTableError(f"{path}:{lineno} 같은 이름이 두 번 적혔습니다: {label!r}")
        seen.add(label)
        rows.append(Row(label, start, end, era, tuple(rels), desc, note))
    return rows


def apply(store, table: list[Row], dry_run: bool = False) -> Report:
    """표를 그래프에 세운다. 여러 번 돌려도 결과가 같다."""
    from .ontology import Edge, Node

    conn = store.conn
    rep = Report()
    nodes: list[Node] = []
    edges: list[Edge] = []

    for row in table:
        other = conn.execute(
            "SELECT id FROM nodes WHERE label = ? AND id != ?",
            (row.label, row.node_id),
        ).fetchone()
        if other is not None:
            # 이름이 겹치면 세우지 않는다 — 같은 일이면 그쪽이 이미 있고,
            # 다른 일이면 이름을 갈라 적어야 한다 (§1-2·§1-4).
            rep.collided.append((row.label, other["id"]))
            continue

        cur = conn.execute(
            "SELECT label, start_date, description FROM nodes WHERE id = ?",
            (row.node_id,),
        ).fetchone()
        if cur is not None and (cur["label"], cur["start_date"] or "",
                                cur["description"] or "") == (row.label, row.start, row.desc):
            rep.kept += 1
        else:
            rep.made.append(row.label)

        nodes.append(Node(
            id=row.node_id,
            type=NODE_TYPE,
            label=row.label,
            source=SOURCE,
            start_date=row.start,
            end_date=row.end or None,
            description=row.desc,
            props={"seed_era": row.era, "handmade": True,
                   "note": row.note, **_desc_props(row.note)},
        ))
        for name, target, evidence in row.rels:
            if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (target,)).fetchone() is None:
                rep.absent.append((row.label, name, target))
                continue
            etype, direction = RELATIONS[name]
            src, dst = ((row.node_id, target) if direction == "out"
                        else (target, row.node_id))
            edges.append(Edge(src=src, dst=dst, type=etype, source=SOURCE,
                              props={"evidence": evidence}))
            rep.edges += 1

    if dry_run:
        return rep

    if nodes:
        store.upsert_nodes(nodes)
        # 표가 기계를 이긴다. 편집 계층에 적어 두면 수집이 이 id 를 건드리는
        # 날에도 이름·설명·날짜가 되돌아온다 (§2 '편집 계층').
        for row in table:
            if any(n.id == row.node_id for n in nodes):
                ov.record(conn, "node", row.node_id, "label", row.label, ORIGIN, row.note)
                ov.record(conn, "node", row.node_id, "description", row.desc, ORIGIN, row.note)
                ov.record(conn, "node", row.node_id, "start_date", row.start, ORIGIN, row.note)
    if edges:
        store.upsert_edges(edges)
    conn.commit()
    return rep
