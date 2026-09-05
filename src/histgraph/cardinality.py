"""카디널리티 — 한 사람의 출생지가 둘이면 무엇이 틀린 것인가.

`ontology.MAX_TARGETS` 가 엣지 타입마다 '한 출발 노드가 가리킬 수 있는
도착 노드의 수'를 적는다. 이 모듈은 그것을 넘는 노드를 세어 **두 종류로
가른다**:

- **해상도 차이** — 한 도착지가 다른 도착지의 상위 장소다 (`located_in`
  사슬: 명천군 ⊂ 함경도). 같은 사실을 두 소스가 다른 굵기로 말한 것이라
  틀린 것이 없다. 세어서 보여 준다.
- **충돌** — 그 관계가 없다. 대개 동명이인의 문서가 섞였거나(김성우의
  출생지 부산·광주), 소스 하나가 틀렸다(정의공주의 어머니 원경왕후 —
  Wikidata 오류, 원경왕후는 할머니다). **이것이 찾으려는 목록이다.**

지우지 않는다. 어느 쪽이 맞는지는 기계가 모르고, 지우면 참인 것이 먼저
사라진다 (CLAUDE.md §1-2 와 같은 규칙). 목록은 **틀린 소스를 찾는 창**으로
읽는다. 옛 이름과 새 이름(한성부·서울특별시, 강화도·강화군)은 `located_in`
으로 잇지 못하므로 충돌로 센다 — 그것도 `same_as` 나 장소 통합의 후보다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .ontology import MAX_TARGETS


@dataclass
class Violation:
    src: str
    src_label: str
    src_type: str
    edge_type: str
    limit: int
    targets: list[tuple[str, str, str]] = field(default_factory=list)  # (dst, 라벨, 소스들)
    kind: str = "conflict"  # conflict | resolution


# 조선의 8도와 지금 행정구역의 포함 관계. Wikidata 의 P131 은 '지금'만
# 말한다 — 광양시의 상위는 전라남도이지 전라도가 아니다. 그런데 인포박스는
# 출생지를 '전라도'로 적는다. 도 이름은 고정된 것이라 표로 둔다.
# 남북의 강원도는 어차피 같은 이름이라 여기서는 갈리지 않는다 (해상도
# 판정에만 쓰고 엣지를 긋지 않으므로 틀려도 그래프가 상하지 않는다).
HISTORIC_PARENT: dict[str, str] = {
    "전라남도": "전라도", "전라북도": "전라도", "전북특별자치도": "전라도",
    "광주광역시": "전라도", "제주특별자치도": "전라도", "제주도": "전라도",
    "충청남도": "충청도", "충청북도": "충청도", "대전광역시": "충청도",
    "세종특별자치시": "충청도",
    "경상남도": "경상도", "경상북도": "경상도", "부산광역시": "경상도",
    "대구광역시": "경상도", "울산광역시": "경상도",
    "평안남도": "평안도", "평안북도": "평안도", "평양시": "평안도",
    "평양직할시": "평안도", "자강도": "평안도",
    "함경남도": "함경도", "함경북도": "함경도", "양강도": "함경도",
    "라선특별시": "함경도",
    "황해남도": "황해도", "황해북도": "황해도",
    "강원특별자치도": "강원도",
    "인천광역시": "경기도", "서울특별시": "경기도",
}
# 옛 이름 — 같은 곳이다.
OLD_NAMES: dict[str, str] = {
    "한성부": "서울특별시", "경성부": "서울특별시", "한양": "서울특별시",
    "한성": "서울특별시", "경성": "서울특별시",
}


def _place_parents(conn: sqlite3.Connection) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = {}
    for r in conn.execute(
        """SELECT e.src, e.dst FROM edges e
             JOIN nodes a ON a.id = e.src JOIN nodes b ON b.id = e.dst
            WHERE e.type = 'located_in' AND a.type = 'place' AND b.type = 'place'"""
    ):
        parents.setdefault(r[0], set()).add(r[1])
    return parents


def _ancestors(parents: dict[str, set[str]], node: str, depth: int = 6) -> set[str]:
    seen: set[str] = set()
    frontier = {node}
    for _ in range(depth):
        nxt: set[str] = set()
        for n in frontier:
            for p in parents.get(n, ()):
                if p not in seen:
                    seen.add(p)
                    nxt.add(p)
        if not nxt:
            break
        frontier = nxt
    return seen


def _labels_of(conn: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    ordered = sorted(ids)
    for i in range(0, len(ordered), 400):
        batch = ordered[i : i + 400]
        marks = ",".join("?" * len(batch))
        out.update(
            (r[0], r[1]) for r in conn.execute(
                f"SELECT id, label FROM nodes WHERE id IN ({marks})", batch)
        )
    return out


def _norm(label: str) -> str:
    return OLD_NAMES.get(label, label)


def _same_resolution_family(
    parents: dict[str, set[str]], labels: dict[str, str], dsts: list[str]
) -> bool:
    """도착지들이 전부 한 사슬 위에 있는가 — 가장 작은 곳의 조상에 나머지가
    다 있는가. 조상은 `located_in` 사슬에 옛 도(8도)와 옛 이름을 더해 잰다."""
    for leaf in dsts:
        anc_ids = _ancestors(parents, leaf)
        names = {_norm(labels.get(a, a)) for a in anc_ids} | {_norm(labels.get(leaf, leaf))}
        names |= {HISTORIC_PARENT[n] for n in list(names) if n in HISTORIC_PARENT}
        if all(d == leaf or d in anc_ids or _norm(labels.get(d, d)) in names for d in dsts):
            return True
    return False


def violations(conn: sqlite3.Connection, edge_types: tuple[str, ...] | None = None) -> list[Violation]:
    types = tuple(edge_types or MAX_TARGETS)
    parents = _place_parents(conn)
    labels = _labels_of(conn, {p for ps in parents.values() for p in ps} | set(parents))
    out: list[Violation] = []
    for etype in types:
        limit = MAX_TARGETS.get(etype)
        if limit is None:
            continue
        rows = conn.execute(
            """SELECT e.src, n.label AS src_label, n.type AS src_type,
                      e.dst, d.label AS dst_label, group_concat(DISTINCT e.source) AS sources
                 FROM edges e
                 JOIN nodes n ON n.id = e.src
                 JOIN nodes d ON d.id = e.dst
                WHERE e.type = ?
                  AND e.src IN (SELECT src FROM edges WHERE type = ?
                                 GROUP BY src HAVING COUNT(DISTINCT dst) > ?)
             GROUP BY e.src, e.dst
             ORDER BY n.label, e.src, d.label""",
            (etype, etype, limit),
        ).fetchall()
        by_src: dict[str, Violation] = {}
        for r in rows:
            v = by_src.get(r["src"])
            if v is None:
                v = by_src[r["src"]] = Violation(
                    r["src"], r["src_label"], r["src_type"], etype, limit)
            v.targets.append((r["dst"], r["dst_label"], r["sources"] or ""))
        for v in by_src.values():
            dsts = [t[0] for t in v.targets]
            # 부모가 셋인데 그중 둘이 한 사슬이면 해상도 차이로 보지 않는다 —
            # 장소 엣지에서만 사슬을 본다.
            if etype in ("born_in", "died_in", "occurred_during"):
                labels.update((t[0], t[1]) for t in v.targets)
                if _same_resolution_family(parents, labels, dsts):
                    v.kind = "resolution"
            out.append(v)
    return out


def summarize(vs: list[Violation]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for v in vs:
        bucket = out.setdefault(v.edge_type, {"conflict": 0, "resolution": 0})
        bucket[v.kind] += 1
    return out


def fill_place_hierarchy(store, fetcher, *, failures: list[str] | None = None) -> dict[str, int]:
    """카디널리티에 걸린 장소들의 상위 행정구역을 Wikidata 에서 받아
    `located_in` 으로 잇는다. **이미 있는 장소 노드끼리만** — 새 노드를
    만들면 이름(한국어)과 설명을 다시 물어야 한다. 사슬의 양끝이 다 우리
    그래프에 있을 때만 선을 긋는다."""
    from .ontology import Edge as _Edge
    from .sources import wikidata

    conn = store.conn
    vs = violations(conn, ("born_in", "died_in", "occurred_during"))
    places = {t[0] for v in vs for t in v.targets if t[0].startswith("wd:")}
    if not places:
        return {"asked": 0, "edges": 0}
    ancestors = wikidata.fetch_place_ancestors(
        fetcher, [p[len("wd:"):] for p in places], failures=failures)
    known = {
        r[0] for r in conn.execute("SELECT id FROM nodes WHERE type = 'place'")
    }
    edges = []
    for qid, ups in ancestors.items():
        src = f"wd:{qid}"
        if src not in known:
            continue
        for up in ups:
            dst = f"wd:{up}"
            if dst in known and dst != src:
                edges.append(_Edge(src=src, dst=dst, type="located_in", source="wd"))
    if edges:
        store.upsert_edges(edges)
    return {"asked": len(places), "edges": len(edges)}
