"""동명이인 관문 — 이름이 같을 뿐 다른 사람인 것을 가른다.

**왜 필요했나.** 화면의 연표에 '여진 정벌'(1107)이 조선 쪽에 서 있는 것을
보고 사용자가 물었다 — "여진 정벌은 고려때 일이야 왜 조선과 연결된지
모르겠어. 아마 왕이름이 겹쳐서 그럴거야. 조선왕과 고려왕 이름이 같을때가
있는데 구분을 반드시해야해" (2026-09-04).

그 날짜의 원인은 딴 것이었지만(`sources/nikh.era_window`), 이름이 겹친다는
지적은 맞았고 실제 피해는 더 컸다. 실측:

    조선 예종의 휘가 이황(李晄) 이라 별칭에 '이황' 이 있다. 퇴계 이황
    (李滉, 1501~1570) 문서에서 나온 관계 22건 — 김해 허씨와의 혼인,
    문인이 남인·북인으로 갈린 학맥, 양명학 배척, 생원시 급제 — 이 전부
    예종(1450~1469)에게 갔다. 32년 차이라 생몰 검사(여유 40년)에 안 걸리고,
    예종의 차수가 커서 후보 고르기에서 이겼다.

**고치는 것은 한 가지뿐이다.** 출처 문서의 주인공이 남에게 가 있는 엣지 —
이황 문서에서 나온 '이황'은 이황이다. 판정에 짐작이 없다. 앞으로 들어올
것은 `extract.pick_candidate` 가 같은 규칙으로 막는다.

**나머지 둘은 세어서 보여만 준다.** 지우면 참인 것이 먼저 사라진다:

  - *연대가 어긋나는 참여.* 양만춘의 생년이 Wikidata 에 700년으로 적혀
    있어 안시성 전투(645)보다 늦다. 틀린 것은 엣지가 아니라 **생년**이다.
    프랑스가 6.25 전쟁보다 1,389년 앞서는 것도 같다 (프랑크 왕국의
    연대가 프랑스 노드에 붙어 있다). 김종직(~1492)이 무오사화(1498)에
    얽힌 것은 부관참시라 연결 자체는 참이다 — 관계 이름이 틀렸을 뿐이고,
    역할은 `roles` 가 말뭉치 근거로 판정한다.

    그래서 이 목록은 **틀린 날짜를 찾는 창**으로 쓴다. 곽승우(1351~1431)가
    여진 정벌(1107)에 참여했다고 나온 것이 그 사건의 연도가 고려의 것임을
    말해 주었다.

  - *다른 노드의 라벨이기도 한 별칭.* '고려'가 고구려의 별칭이고, '이황'이
    조선 예종의 별칭이다. 지우면 멀쩡한 이름이 사라진다 ('김유'는 김류의
    다른 표기일 수도 있다). 고칠 곳은 `data/ko_labels.tsv` 와 `promote` 다.

경계는 100년이다. 동명이인은 대개 세기가 다르고, 그 안쪽은 지저분한
날짜이거나 부관참시다 (실측: 참여 엣지의 연대 충돌 69건 중 100년을 넘는
것 12건은 전부 다른 사람이거나 사건의 해가 틀린 것이었다).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .timeline import _year_of

# 참여를 재는 관계. `related_to` 는 넣지 않는다 — 추숭·학맥은 시대가
# 달라도 참이다 (`extract.LIFESPAN_CHECKED` 의 주석과 같은 이유).
PARTICIPATION = "participated_in"

# 이 너머는 동명이인이거나 연도가 틀린 것이다. 안쪽은 보고만 한다.
CENTURY = 100

Conflict = tuple[str, str, str, str, tuple[int, int], int, int]


@dataclass(slots=True)
class Report:
    misrouted: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)   # 100년 넘게 어긋남
    near: list[Conflict] = field(default_factory=list)        # 그 안쪽
    alias_clashes: list[tuple[str, str, str, str]] = field(default_factory=list)
    repointed: int = 0
    dropped: int = 0


def misrouted_edges(conn: sqlite3.Connection) -> list[tuple[str, str, str, str, str]]:
    """문서의 주인공이 남에게 가 있는 추출 엣지.

    (엣지 src, dst, type, 잘못 붙은 노드, 돌려놓을 문서 노드).

    조건은 셋이다. (1) 상대가 출처 문서의 이름을 **라벨로 쓰지 않고**
    별칭으로만 갖고 있다 — 라벨까지 같으면 같은 이름의 노드가 둘인 병합
    문제이지(`promote`) 이름이 겹친 것이 아니다. (2) 타입이 같다.
    (3) 문서 노드가 그 자리에 설 수 있다."""
    nodes = {
        r["id"]: (r["label"], r["type"])
        for r in conn.execute("SELECT id, label, type FROM nodes")
    }
    out: list[tuple[str, str, str, str, str]] = []
    for row in conn.execute(
        "SELECT src, dst, type, props FROM edges WHERE source = 'extract'"
    ):
        doc = (json.loads(row["props"] or "{}")).get("extracted_from")
        if doc not in nodes:
            continue
        doc_label, doc_type = nodes[doc]
        for end in (row["src"], row["dst"]):
            if end == doc or end not in nodes:
                continue
            end_label, end_type = nodes[end]
            if end_label == doc_label or end_type != doc_type:
                continue
            hit = conn.execute(
                "SELECT 1 FROM aliases WHERE node_id = ? AND alias = ?",
                (end, doc_label),
            ).fetchone()
            if hit:
                out.append((row["src"], row["dst"], row["type"], end, doc))
    return out


def chronology(conn: sqlite3.Connection) -> tuple[list[Conflict], list[Conflict]]:
    """(100년 넘게 어긋난 참여, 그 안쪽). 어긋난 햇수가 큰 것부터.

    각 줄은 (참여자 id, 이름, 사건 id, 이름, 생몰 구간, 사건의 해, 햇수)."""
    from .promote import life_span

    dates = {
        r["id"]: (r["label"], r["start_date"], r["end_date"])
        for r in conn.execute("SELECT id, label, start_date, end_date FROM nodes")
    }
    rows: list[Conflict] = []
    for e in conn.execute("SELECT src, dst FROM edges WHERE type = ?", (PARTICIPATION,)):
        who, what = dates.get(e["src"]), dates.get(e["dst"])
        if who is None or what is None:
            continue
        span = life_span(who[1], who[2])
        year = _year_of(what[1])
        if span is None or year is None:
            continue
        gap = max(span[0], year) - min(span[1], year)
        if gap > 0:
            rows.append((e["src"], who[0], e["dst"], what[0], span, year, gap))
    rows.sort(key=lambda r: -r[6])
    return ([r for r in rows if r[6] > CENTURY],
            [r for r in rows if r[6] <= CENTURY])


def alias_clashes(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    """다른 노드의 라벨이기도 한 별칭. (별칭, 가진 노드 id, 그 이름, 겹치는 노드).

    `same_as` 로 이미 같은 것이라 아는 짝은 뺀다."""
    same: set[frozenset[str]] = set()
    try:
        for r in conn.execute("SELECT a, b FROM same_as"):
            same.add(frozenset((r["a"], r["b"])))
    except sqlite3.Error:
        pass                                   # same_as 가 없는 파생본
    out = []
    for r in conn.execute(
        """SELECT a.alias AS alias, a.node_id AS node_id,
                  n1.label AS owner, n2.id AS clash
             FROM aliases a
             JOIN nodes n1 ON n1.id = a.node_id
             JOIN nodes n2 ON n2.label = a.alias AND n2.type = n1.type
                          AND n2.id <> a.node_id
         ORDER BY a.alias"""
    ):
        if frozenset((r["node_id"], r["clash"])) in same:
            continue
        out.append((r["alias"], r["node_id"], r["owner"], r["clash"]))
    return out


def sweep(conn: sqlite3.Connection, apply: bool = True) -> Report:
    """셋을 재고, 짐작이 없는 하나만 고친다."""
    rep = Report()
    rep.misrouted = misrouted_edges(conn)
    rep.conflicts, rep.near = chronology(conn)
    rep.alias_clashes = alias_clashes(conn)
    if not apply:
        return rep

    for src, dst, etype, wrong, doc in rep.misrouted:
        old = conn.execute(
            "SELECT label, start_date, end_date, confidence, props FROM edges"
            " WHERE src = ? AND dst = ? AND type = ? AND source = 'extract'",
            (src, dst, etype),
        ).fetchone()
        if old is None:            # 앞 줄이 이미 옮겼다 (양끝이 다 틀린 엣지)
            continue
        conn.execute(
            "DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?"
            " AND source = 'extract'", (src, dst, etype))
        new_src = doc if src == wrong else src
        new_dst = doc if dst == wrong else dst
        if new_src == new_dst:     # 문서가 제 자신에게 붙는다 — 자기순환
            rep.dropped += 1
            continue
        props = json.loads(old["props"] or "{}")
        props["repointed_from"] = wrong
        # 옮길 자리에 이미 엣지가 있으면 버린다 (기본키가 같다).
        cur = conn.execute(
            "INSERT OR IGNORE INTO edges (src, dst, type, source, label,"
            " start_date, end_date, confidence, props)"
            " VALUES (?, ?, ?, 'extract', ?, ?, ?, ?, ?)",
            (new_src, new_dst, etype, old["label"], old["start_date"],
             old["end_date"], old["confidence"],
             json.dumps(props, ensure_ascii=False)))
        if cur.rowcount:
            rep.repointed += 1
        else:
            rep.dropped += 1
    conn.commit()
    return rep
