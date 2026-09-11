"""임금 자리 관문 — 왕조가 나눠 쓰는 직위를 왕조별로 가른다.

**왜 필요했나.** 2026-09-09 지적: "왕 노드에 왜 고려왕만 연결되어 있지?
조선 왕도 있는데". 화면의 `왕(王)` 노드에는 고려 왕 34명만 서 있었고 조선
임금 28명은 이름도 타입도 다른 노드에 따로 서 있었다. 실측:

    wd:Q12087706  왕(王)      role   고려 34명 + 고구려 8명
    wd:Q22304810  조선 임금   org    조선 28명
    ex:role:고려 왕            role   1명 (추출이 따로 세운 것)
    ex:role:조선 왕            role   1명

원인은 우리 코드가 아니라 **Wikidata 의 자리 항목이 왕조마다 다르다**는
것이다. 조선에는 전용 항목('조선 임금')이 있지만 고구려·고려 임금은 일반
항목인 '왕(王)' 하나를 나눠 쓴다 — 고려·고구려 임금 자리는 Wikidata 에
항목 자체가 없다 (실측: `wbsearchentities` 로 한국어·영어 모두 0건).
`fetch_monarch_positions` 의 머리글이 이미 그 사실을 적어 두고 있다.

거기에 둘이 겹쳤다. `_labels` 가 P31 을 **아무거나 하나** 집어 오는 바람에
('조선 임금'은 P31 이 둘이다 — 자리(Q4164871)와 군주(Q116)) 조선 임금이
직위가 아니라 단체로 앉았고, 추출이 산문에서 만든 `ex:role:` 노드 둘이
한 명씩 물고 따로 서 있었다.

**가르는 규칙.** 일반 자리에 걸린 참여를 홀더의 왕조(`from_period`)로 갈라
`ex:role:{왕조} 왕` 으로 옮긴다. 왕조를 모르는 사람은 **옮기지 않고 센다**
— 고구려 임금 8명이 그렇다 (korea 묶음 밖이라 시대 엣지가 없다). 짐작으로
옮기면 광개토왕이 고려 왕이 된다.

**왕조 전용 자리는 가르지 않는다.** 대한제국 고종은 '조선 임금'을 가진 채
시대가 대한제국이라, 같은 규칙을 씌우면 없던 '대한제국 왕' 자리가 생긴다.
전용 자리는 이름과 타입만 바로잡는다 (`SEAT_FIXES`).

**옮긴 자리는 편집 계층에 남는다.** 옛 엣지에 `deleted` 를, 새 엣지에 재위
표식(`props.reign`)과 날짜를 다시 적는다 — 안 그러면 다음 `ingest` 가
일반 자리 엣지를 되살리고 왕 재위 띠가 조용히 사라진다. 새 자리 노드에는
`props.wd_position` 으로 원래 QID 를 남긴다. `reigns` 가 그 QID 로
Wikidata 에 재위를 물어보므로, 남기지 않으면 `ex:` 자리에 앉은 왕들이
재위를 영영 못 받는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import overrides as overrides_mod
from .ontology import Node
from .promote import merge_node
from .sources.wikidata import POLITIES

# 여러 왕조가 나눠 쓰는 일반 자리: 노드 id -> 자리 이름.
GENERIC_SEATS: dict[str, str] = {
    "wd:Q12087706": "왕",
    "wd:Q116": "군주",
    # Wikidata 에는 '왕' 항목이 둘이다 (2026-09-11 실측). 고대 임금의 P39 가
    # 이쪽으로 오는 일이 있어 — 동명성왕·무령왕·문무왕·지마 이사금·발해 고왕 —
    # 여기 없으면 그 다섯이 왕조 자리로 못 옮겨지고 일반 '왕'에 남는다.
    "wd:Q12097": "왕",
}

# 왕조 전용 자리인데 이름·타입이 어긋난 것: 노드 id -> (이름 또는 None, 타입).
SEAT_FIXES: dict[str, tuple[str | None, str]] = {
    "wd:Q22304810": ("조선 왕", "role"),
    # 일반 자리도 직위다. 옮기지 못한 사람이 남으면 노드가 그대로 서므로
    # 타입은 바로잡아 둔다.
    "wd:Q116": (None, "role"),
    "wd:Q12087706": (None, "role"),
    "wd:Q12097": (None, "role"),
}

WANG = "왕"


@dataclass
class Report:
    moved: list[tuple[str, str, str]] = field(default_factory=list)   # (사람, 새 자리, 왕조)
    unknown: list[tuple[str, str]] = field(default_factory=list)      # (사람, 일반 자리)
    unreigned: list[tuple[str, str]] = field(default_factory=list)    # (사람, 일반 자리)
    seats: dict[str, int] = field(default_factory=dict)               # 새 자리 -> 사람 수
    renamed: list[tuple[str, str, str]] = field(default_factory=list)  # (id, 옛 이름, 새 이름)
    retyped: list[tuple[str, str, str]] = field(default_factory=list)  # (id, 옛 타입, 새 타입)
    merged: list[tuple[str, str]] = field(default_factory=list)        # (없앤, 남긴)
    emptied: list[str] = field(default_factory=list)                   # 사람이 안 남은 일반 자리


def seat_id(polity: str) -> str:
    return f"ex:role:{polity} {WANG}"


def _reigned(row) -> bool:
    """그 자리에 실제로 앉았다는 근거 — 재위 표식(`reigns`)이나 날짜."""
    if row["start_date"] or row["end_date"]:
        return True
    try:
        return bool(json.loads(row["props"] or "{}").get("reign"))
    except json.JSONDecodeError:
        return False


# 한 자리를 두 이름으로 부르는 것들. 통일신라의 임금은 신라의 임금이고
# (문무왕 뒤로도 왕위는 하나다), 금관가야·대가야의 임금은 가야의 임금이다.
# 이 표가 없으면 같은 왕위가 '신라 왕'과 '통일신라 왕'으로 갈라 선다.
SEAT_MERGE: dict[str, str] = {
    "통일신라": "신라",
    "금관가야": "가야",
    "대가야": "가야",
    "위만조선": "고조선",
}


def _polity_of(conn, person_id: str) -> str | None:
    """그 사람의 왕조. 시대 엣지가 가리키는 이름 중 왕조 이름인 것.

    시대 노드는 '고려'(정체)와 '조선시대'(연표 눈금) 둘 다 온다. 왕조
    이름과 **정확히 같은 것**만 받는다 — '조선시대'를 잘라 쓰면 '대한제국'
    같은 이름이 어디로 갈지 규칙이 흐려진다. 왕조가 둘 이상이면 모른다고
    답한다 (짐작으로 옮기지 않는다).

    **둘 이상일 때 국적이 가른다** (2026-09-11). 고대 임금은 시대 엣지가
    여럿이다 — 동명성왕은 고구려와 부여에, 경순왕은 신라와 고려에 걸려
    있고 둘 다 참이다(부여에서 왔고, 나라를 넘긴 뒤 고려 사람이 되었다).
    어느 나라의 임금이었나는 국적(`props.polity`)이 말한다. 짐작이 아니라
    **시드 표와 Wikidata 가 적어 준 것**이고, 시대 엣지에 없는 나라를
    끌어오지는 않는다."""
    names = {
        r[0]
        for r in conn.execute(
            """SELECT n.label FROM edges e JOIN nodes n ON n.id = e.dst
                WHERE e.src = ? AND e.type = 'from_period'""",
            (person_id,),
        )
    }
    found = {SEAT_MERGE.get(n, n) for n in names & set(POLITIES.values())}
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        row = conn.execute(
            "SELECT json_extract(props,'$.polity') FROM nodes WHERE id = ?",
            (person_id,),
        ).fetchone()
        own = SEAT_MERGE.get(row[0], row[0]) if row and row[0] else None
        if own in found:
            return own
    return None


def _move_edge(conn, row, new_dst: str) -> None:
    """직위 엣지의 도착을 바꾼다. 재위 띠와 편집 계층을 같이 옮긴다."""
    old_key = overrides_mod.edge_key(row["src"], row["dst"], row["type"])
    new_key = overrides_mod.edge_key(row["src"], new_dst, row["type"])

    conn.execute(
        """INSERT INTO edges
             (src, dst, type, source, label, start_date, end_date, confidence, props)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(src, dst, type, source) DO UPDATE SET
             label = excluded.label, start_date = excluded.start_date,
             end_date = excluded.end_date, props = excluded.props""",
        (row["src"], new_dst, row["type"], row["source"], row["label"],
         row["start_date"], row["end_date"], row["confidence"], row["props"]),
    )
    # 옛 자리에 적어 둔 편집(재위 시작·끝·표식)을 새 자리 이름으로 옮긴다.
    for o in conn.execute(
        "SELECT * FROM overrides WHERE target = 'edge' AND key = ?", (old_key,)
    ).fetchall():
        if o["field"] == "deleted":
            continue
        conn.execute(
            """INSERT INTO overrides (target, key, field, value, origin, reason, apply_when, made_at)
               VALUES ('edge',?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(target, key, field) DO UPDATE SET
                 value = excluded.value, origin = excluded.origin,
                 reason = excluded.reason, apply_when = excluded.apply_when""",
            (new_key, o["field"], o["value"], o["origin"], o["reason"], o["apply_when"]),
        )
    conn.execute("DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?",
                 (row["src"], row["dst"], row["type"]))
    overrides_mod.forget(conn, "edge", old_key)
    # 다음 수집이 일반 자리 엣지를 되살리면 저장소가 그것을 **여기로 옮긴다**.
    # `deleted` 로 적으면 새로 읽어 온 재위 날짜까지 함께 버린다
    # (`overrides._apply_edge` 의 `moved_to` 주석).
    overrides_mod.record(conn, "edge", old_key, "moved_to", new_dst, "positions",
                         f"{new_dst} 로 옮긴 임금 자리")


def _ensure_seat(store, seat: str, polity: str, from_id: str) -> None:
    conn = store.conn
    if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (seat,)).fetchone():
        # 이미 적힌 QID 는 덮지 않는다. 한 자리에 일반 항목이 둘 걸리는데
        # ('왕'과 '군주'), 재위를 물어볼 QID 는 먼저 옮겨 온 쪽이다.
        conn.execute(
            """UPDATE nodes
                  SET type = 'role',
                      props = json_set(json_set(COALESCE(NULLIF(props,''),'{}'),
                                       '$.wd_position',
                                       COALESCE(json_extract(props,'$.wd_position'), ?)),
                                       '$.split_from',
                                       COALESCE(json_extract(props,'$.split_from'), ?))
                WHERE id = ?""",
            (from_id.split(":", 1)[1], from_id, seat),
        )
        return
    store.upsert_nodes([
        Node(id=seat, type="role", label=f"{polity} {WANG}", source="positions",
             props={"wd_position": from_id.split(":", 1)[1], "split_from": from_id})
    ])


def split(store, dry_run: bool = False) -> Report:
    """일반 임금 자리를 왕조별 자리로 가른다. 여러 번 돌려도 결과가 같다."""
    conn = store.conn
    rep = Report()
    for generic in GENERIC_SEATS:
        rows = conn.execute(
            """SELECT * FROM edges
                WHERE dst = ? AND type = 'held_position' ORDER BY src""",
            (generic,),
        ).fetchall()
        for row in rows:
            if not _reigned(row):
                # 재위 근거가 없는 참여는 임금 자리로 옮기지 않는다. 실측:
                # '군주'(Q116)에 임해군·순화군이 걸려 있는데 지금 Wikidata
                # 에는 그 P39 자체가 없다 (묵은 수집이 남긴 줄이다). 옮기면
                # 왕이 아닌 왕자가 조선 왕 자리에 선다.
                rep.unreigned.append((row["src"], generic))
                continue
            polity = _polity_of(conn, row["src"])
            if polity is None:
                rep.unknown.append((row["src"], generic))
                continue
            seat = seat_id(polity)
            rep.moved.append((row["src"], seat, polity))
            rep.seats[seat] = rep.seats.get(seat, 0) + 1
            if dry_run:
                continue
            _ensure_seat(store, seat, polity, generic)
            _move_edge(conn, row, seat)
        if dry_run:
            continue
        alive = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (generic,)).fetchone()
        left = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE src = ? OR dst = ?", (generic, generic)
        ).fetchone()[0]
        if alive and left == 0:
            # 사람이 하나도 안 남은 일반 자리는 그래프에 뜻이 없다. 다음
            # 수집이 되살리면 그때 다시 갈라진다 (엣지는 위에서 지운다).
            conn.execute("DELETE FROM nodes WHERE id = ?", (generic,))
            rep.emptied.append(generic)
    if not dry_run:
        conn.commit()
    return rep


def settle(store, dry_run: bool = False) -> Report:
    """왕조 전용 자리의 이름·타입을 바로잡고 같은 이름의 노드를 합친다."""
    conn = store.conn
    rep = Report()
    for seat, (want_label, ntype) in SEAT_FIXES.items():
        row = conn.execute(
            "SELECT id, label, type FROM nodes WHERE id = ?", (seat,)
        ).fetchone()
        if row is None:
            continue
        label = want_label or row["label"]
        if row["label"] != label:
            rep.renamed.append((seat, row["label"], label))
        if row["type"] != ntype:
            rep.retyped.append((seat, row["type"], ntype))
        twins = [
            r[0] for r in conn.execute(
                "SELECT id FROM nodes WHERE label = ? AND id <> ?", (label, seat)
            )
        ]
        rep.merged += [(t, seat) for t in twins]
        if dry_run:
            continue
        if row["label"] != label:
            # 없어지는 이름은 별칭으로 남는다 — 추출이 '조선 임금'을 다시
            # 만나도 같은 노드를 찾는다.
            conn.execute("INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)",
                         (seat, row["label"]))
        conn.execute("UPDATE nodes SET label = ?, type = ? WHERE id = ?",
                     (label, ntype, seat))
        overrides_mod.record(conn, "node", seat, "label", label, "positions",
                             "왕조별 임금 자리 이름")
        overrides_mod.record(conn, "node", seat, "type", ntype, "positions",
                             "직위(P39)의 도착은 자리다")
        for twin in twins:
            merge_node(store, twin, seat, method="positions")
    if not dry_run:
        conn.commit()
    return rep


def seats(conn) -> list[tuple[str, str, int]]:
    """지금 서 있는 임금 자리 — (id, 이름, 사람 수). 화면에 세울 순서대로."""
    ids = set(GENERIC_SEATS) | set(SEAT_FIXES)
    ids |= {
        r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE json_extract(props, '$.wd_position') IS NOT NULL"
        )
    }
    out = []
    for nid in sorted(ids):
        row = conn.execute("SELECT label FROM nodes WHERE id = ?", (nid,)).fetchone()
        if row is None:
            continue
        n = conn.execute(
            "SELECT COUNT(DISTINCT src) FROM edges WHERE dst = ? AND type = 'held_position'",
            (nid,),
        ).fetchone()[0]
        out.append((nid, row[0], n))
    return sorted(out, key=lambda r: -r[2])


def position_qid(conn, node_id: str) -> str | None:
    """직위 노드의 Wikidata QID. 가른 자리는 props 에 원래 QID 를 들고 있다."""
    if node_id.startswith("wd:"):
        return node_id[len("wd:"):]
    row = conn.execute("SELECT props FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0] or "{}").get("wd_position")
    except json.JSONDecodeError:
        return None
