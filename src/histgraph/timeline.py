"""시간축 정규화 — 연도를 일급 개체로 만든다.

**문제.** 시간이 두 방식으로 동시에 표현되고 있었다:
  - 노드 (`period` 타입) 1,306개 — '조선 태조 7년(1398)', '1388년'
  - 속성 (`start_date`/`end_date`) 24,727개 노드

같은 사실이 두 군데 있으면 질의가 절반을 놓친다. "1388년에 무슨 일이
있었나"를 물으면 period 노드 경로로는 위화도 회군이 나오지만, start_date
로만 저장된 인물·사건은 안 걸린다.

표기도 제각각이다: `1388년` · `우왕 14년` · `고려 우왕대` · `신미년`.
앞의 둘은 같은 해이고, `신미년`은 60년마다 돌아온다.

**해법.** 정규 연도 노드 `time:1388` 을 만들고 양쪽을 모두 잇는다.
  - 기존 period 노드 → `same_as` (같은 해를 가리키므로 동일 실체)
  - start_date 를 가진 노드 → `dated_to` 엣지 (인물은 연도와 동일 실체가
    아니다. same_as 로 이으면 거짓이 된다)

연도를 못 읽는 라벨('조선시대 초기 15세기', '신라 진흥왕대')은 잇지 않고
남긴다 — 왕대 환산표 없이 추정하면 틀린 연표가 만들어진다.
"""

from __future__ import annotations

import logging
import re

from .ontology import Edge, Node
from .store import GraphStore

log = logging.getLogger(__name__)

SOURCE = "timeline"

# 라벨에서 4자리(또는 3자리) 연도를 뽑는다. 앞에 숫자가 붙은 경우는
# 제외해야 '1398' 에서 '398' 을 잘못 집지 않는다.
YEAR = re.compile(r"(?<!\d)(\d{3,4})\s*년?")

# 기원전 표기
BCE = re.compile(r"(?:기원전|서기전|B\.?C\.?)\s*(\d{1,4})")


def parse_years(label: str) -> list[int]:
    """라벨에서 연도를 뽑는다. 범위 표기면 여러 개가 나온다.

    '조선 태조 7년(1398)' -> [1398]
    '조선시대 후기(1617∼1892)' -> [1617, 1892]
    '조선시대 초기 15세기' -> []  (세기는 특정 연도가 아니다)
    """
    if bce := BCE.search(label):
        return [-int(bce.group(1))]
    years = [int(m) for m in YEAR.findall(label)]
    # 왕 재위 연차('태조 7년')와 서기 연도를 구분한다. 3자리 미만 값이나
    # 미래 연도는 연차·권차 같은 다른 숫자다.
    return [y for y in years if 100 <= y <= 2100]


def year_node(year: int) -> Node:
    """정규 연도 노드. id 는 `time:1398` 형식으로 고정한다."""
    label = f"기원전 {abs(year)}년" if year < 0 else f"{year}년"
    return Node(
        id=f"time:{year}",
        type="period",
        label=label,
        source=SOURCE,
        start_date=f"{year:04d}" if year > 0 else str(year),
        props={"canonical_year": year},
    )


def _year_of(date_str: str | None) -> int | None:
    """ISO 날짜 문자열에서 연도. '-0057-01-01' 같은 기원전 표기도 처리."""
    if not date_str:
        return None
    s = date_str.strip()
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    head = s.split("-", 1)[0]
    if not head.isdigit():
        return None
    y = int(head)
    if not (1 <= y <= 2100):
        return None
    return -y if neg else y


def build(store: GraphStore, link_attributes: bool = True) -> dict[str, int]:
    """연도 노드를 만들고 양쪽을 잇는다."""
    c = store.conn
    years: set[int] = set()
    alias_links: list[tuple[str, str, str, float]] = []
    edges: list[Edge] = []

    # 1) 기존 period 노드 -> same_as (같은 해를 가리키는 다른 표기)
    unparsed = 0
    for r in c.execute(
        "SELECT id, label FROM nodes WHERE type='period' AND id NOT LIKE 'time:%'"
    ):
        ys = parse_years(r["label"])
        if not ys:
            unparsed += 1
            continue
        # 범위 표기는 시작 연도에 건다. 끝 연도까지 전부 이으면 '조선시대
        # 후기(1617~1892)' 가 276개 연도와 동일 실체가 되어 버린다.
        y = ys[0]
        years.add(y)
        alias_links.append((r["id"], f"time:{y}", "year_from_label", 0.95))

    # 2) start_date/end_date 보유 노드 -> dated_to 엣지
    #    인물은 연도와 '같은 실체'가 아니므로 same_as 를 쓰면 안 된다.
    attr_edges = 0
    if link_attributes:
        for r in c.execute(
            """SELECT id, type, start_date, end_date FROM nodes
               WHERE (start_date IS NOT NULL AND start_date != '')
                  OR (end_date IS NOT NULL AND end_date != '')"""
        ):
            for field, when in (("start_date", "시작"), ("end_date", "종료")):
                y = _year_of(r[field])
                if y is None:
                    continue
                # 인물이면 출생·사망으로 부르는 편이 읽기 쉽다
                lbl = {"시작": "출생", "종료": "사망"}[when] if r["type"] == "person" else when
                years.add(y)
                edges.append(
                    Edge(
                        src=r["id"],
                        dst=f"time:{y}",
                        type="dated_to",
                        source=SOURCE,
                        label=lbl,
                    )
                )
                attr_edges += 1

    nodes = [year_node(y) for y in sorted(years)]
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)
    c.executemany(
        "INSERT OR REPLACE INTO same_as (a, b, method, score) VALUES (?,?,?,?)",
        alias_links,
    )
    c.commit()

    log.info(
        "연도 노드 %d개 · 라벨 연결 %d건 · 속성 연결 %d건 (연도 미해독 %d건)",
        len(nodes), len(alias_links), attr_edges, unparsed,
    )
    return {
        "year_nodes": len(nodes),
        "label_links": len(alias_links),
        "attribute_edges": attr_edges,
        "unparsed_labels": unparsed,
        "span": f"{min(years)} ~ {max(years)}" if years else "-",
    }


def whats_in(store: GraphStore, year: int, limit: int = 20) -> list[dict]:
    """그 해에 무슨 일이 있었나 — 정규화가 실제로 작동하는지 보는 질의.

    연도 노드 하나로 두 경로(라벨 표기·날짜 속성)를 모두 훑는다."""
    nid = f"time:{year}"
    rows = store.conn.execute(
        """SELECT n.label, n.type, e.label AS rel, 'dated_to' AS via
             FROM edges e JOIN nodes n ON n.id = e.src
            WHERE e.dst = ? AND e.type = 'dated_to'
           UNION
           SELECT n2.label, n2.type, s.method, 'same_as'
             FROM same_as s
             JOIN nodes n2 ON n2.id = s.a
            WHERE s.b = ?
           LIMIT ?""",
        (nid, nid, limit),
    ).fetchall()
    return [dict(r) for r in rows]
