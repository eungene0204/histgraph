"""편집 계층 — 사람과 후처리가 고친 값은 수집이 덮어써도 되살아난다.

**발단.** `upsert_nodes` 는 라벨과 props 를 통째로 덮어쓰고 설명·날짜도
새 값이 오면 갈아 끼운다 (`store.py`). 그래서 수집 뒤에는 `relabel →
redescribe → describe → reigns → precision → dedupe` 를 사람이 순서대로
다시 돌려야 했다. 세 번 지적받은 영어 노출과 재위 띠 실종, 국편 정본 위에
위키백과 출처 딱지가 붙던 일이 전부 여기서 왔다. 관문(`scope`·pre-push·
CI)은 잊었는지를 묻지만, 잊을 수 있는 구조 자체는 그대로였다.

**팔란티어식 답.** 원천 값과 고친 값을 한 칸에 두지 않는다. 고친 값은
이 표(`overrides`)에 따로 남고, 저장소가 노드·엣지를 쓸 때마다 그 표를
다시 씌운다 (`store.upsert_nodes`·`upsert_edges` 끝). 수집이 아무리
덮어써도 결과가 같고, 무엇을 누가 왜 고쳤는지가 이력으로 남는다.

표의 한 줄은 "이 대상의 이 칸은 이 값이다"다:

    target  node | edge
    key     노드 id · 엣지는 'src\\tdst\\ttype' (모든 소스에 같이 건다)
    field   label · description · start_date · end_date · type · props.<키> · merged_into
            엣지는 여기에 deleted 가 더 있다 — '이 엣지는 없다' (연대 판정이 지운 인과)
    value   JSON. NULL 은 '비운다'
    origin  relabel · redescribe · describe · precision · reigns · dedupe · nikh …
    apply_when  always — 언제나 이긴다 (사람 표·정본)
                foreign — 지금 값에 한글이 없을 때만 (사전 번역)
                empty   — 지금 값이 비어 있을 때만 (보조 채움)

`foreign` 이 있는 이유: 사전이 옮긴 설명을 언제나 이기게 두면, 나중에
수집이 진짜 한국어 설명을 가져와도 번역이 그것을 가린다. 조건을 남기면
고친 이유가 사라졌을 때 고친 값도 물러난다.

`merged_into` 는 노드가 아니라 **없어졌다는 사실**이다. 수집이 없앤 노드를
id 로 되살리면 (`ingest`·`nikh` 가 그런다) 여기서 다시 합친다. 엣지의
`deleted` 도 같다 — `chronology` 가 지운 인과를 `causes` 가 같은 문서에서
다시 뽑아 오면 여기서 다시 지운다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field

from .koreanize import has_hangul

SCHEMA = """
CREATE TABLE IF NOT EXISTS overrides (
    target     TEXT NOT NULL,
    key        TEXT NOT NULL,
    field      TEXT NOT NULL,
    value      TEXT,
    origin     TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    apply_when TEXT NOT NULL DEFAULT 'always',
    made_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target, key, field)
);
"""

# `type` 이 여기 있는 이유: `reclassify` 가 SQL 로 직접 고쳐서 수집이 되돌리고
# 있었다 (사건 → 개념). 2026-09-07 전수 조사에서 같은 자리를 또 찾았다 —
# 추출이 단체·나라를 인물로 세운 노드('적군'·'영국 정부')다.
NODE_COLUMNS = ("label", "description", "start_date", "end_date", "type")
EDGE_COLUMNS = ("label", "start_date", "end_date", "confidence")
WHEN = ("always", "foreign", "empty")
EDGE_SEP = "\t"


class OverrideError(ValueError):
    pass


def edge_key(src: str, dst: str, etype: str) -> str:
    return EDGE_SEP.join((src, dst, etype))


def _check_field(target: str, field_name: str) -> None:
    if target == "node":
        ok = (field_name in NODE_COLUMNS or field_name.startswith("props.")
              or field_name.startswith("alias:") or field_name == "merged_into")
    elif target == "edge":
        ok = (field_name in EDGE_COLUMNS or field_name.startswith("props.")
              or field_name in ("deleted", "moved_to"))
    else:
        raise OverrideError(f"target 은 node 또는 edge: {target!r}")
    if not ok:
        raise OverrideError(f"{target} 에 없는 칸: {field_name!r}")


def record(
    conn: sqlite3.Connection,
    target: str,
    key: str,
    field_name: str,
    value: object,
    origin: str,
    reason: str = "",
    when: str = "always",
) -> None:
    """고친 값을 적는다. 같은 대상·칸은 마지막에 적은 것이 남는다 —
    국편 정본이 민백 정의 위에 오면 국편이 이긴다."""
    _check_field(target, field_name)
    if when not in WHEN:
        raise OverrideError(f"apply_when 은 {WHEN} 중 하나: {when!r}")
    conn.execute(
        """INSERT INTO overrides (target, key, field, value, origin, reason, apply_when, made_at)
           VALUES (?,?,?,?,?,?,?, datetime('now'))
           ON CONFLICT(target, key, field) DO UPDATE SET
             value = excluded.value, origin = excluded.origin,
             reason = excluded.reason, apply_when = excluded.apply_when,
             made_at = excluded.made_at""",
        (target, key, field_name,
         None if value is None else json.dumps(value, ensure_ascii=False),
         origin, reason or "", when),
    )


def record_many(conn: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    """(target, key, field, value, origin, reason, when) 여러 줄."""
    n = 0
    for row in rows:
        record(conn, *row)
        n += 1
    return n


def forget(conn: sqlite3.Connection, target: str, key: str, field_name: str | None = None) -> int:
    """고친 값을 지운다. 칸을 안 주면 그 대상의 전부."""
    if field_name is None:
        cur = conn.execute("DELETE FROM overrides WHERE target = ? AND key = ?", (target, key))
    else:
        cur = conn.execute(
            "DELETE FROM overrides WHERE target = ? AND key = ? AND field = ?",
            (target, key, field_name),
        )
    return cur.rowcount


@dataclass
class ReapplyReport:
    nodes: int = 0        # 값이 실제로 바뀐 노드 칸
    edges: int = 0        # 값이 실제로 바뀐 엣지 칸
    remerged: list[tuple[str, str]] = field(default_factory=list)  # (없앤, 남긴)
    skipped: int = 0      # 조건(foreign·empty)이 안 맞아 물러난 것


def _decode(value: str | None) -> object:
    return None if value is None else json.loads(value)


def _should_apply(when: str, current: object) -> bool:
    if when == "always":
        return True
    text = current if isinstance(current, str) else ""
    if when == "empty":
        return not text.strip()
    if when == "foreign":
        return not has_hangul(text)
    return False


def _chunks(items: list[str], size: int = 400) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def reapply(
    store,
    node_ids: Iterable[str] | None = None,
    edge_keys: Iterable[str] | None = None,
    *,
    everything: bool = False,
) -> ReapplyReport:
    """표를 그래프에 다시 씌운다. 여러 번 돌려도 결과가 같다.

    `node_ids`·`edge_keys` 를 주면 그것만 (수집이 방금 쓴 것), `everything`
    이면 표 전부. 노드 병합(`merged_into`)은 맨 뒤에 한다 — 되살아난 노드의
    다른 칸을 먼저 고쳐 봐야 어차피 사라진다."""
    conn = store.conn
    rep = ReapplyReport()
    if everything:
        rows = conn.execute("SELECT * FROM overrides").fetchall()
    else:
        rows = []
        for batch in _chunks(sorted(set(node_ids or ()))):
            marks = ",".join("?" * len(batch))
            rows += conn.execute(
                f"SELECT * FROM overrides WHERE target = 'node' AND key IN ({marks})", batch
            ).fetchall()
        for batch in _chunks(sorted(set(edge_keys or ()))):
            marks = ",".join("?" * len(batch))
            rows += conn.execute(
                f"SELECT * FROM overrides WHERE target = 'edge' AND key IN ({marks})", batch
            ).fetchall()
    # 엣지가 **없앤 노드**를 가리키면 남긴 쪽으로 옮긴다. `_persist` 는 노드를
    # 먼저 쓰고 엣지를 나중에 쓰므로, 노드가 다시 합쳐진 뒤에 도착한 엣지는
    # 이미 없는 id 에 걸린다 (댕글링). 노드 병합과 같은 규칙으로 옮긴다.
    if edge_keys or everything:
        rep.edges += _redirect_merged_endpoints(store, edge_keys, everything)
    if not rows:
        return rep

    merges: list[tuple[str, str, str]] = []
    for r in rows:
        target, key, fld = r["target"], r["key"], r["field"]
        value = _decode(r["value"])
        when = r["apply_when"]
        if target == "node":
            if fld == "merged_into":
                if isinstance(value, str):
                    merges.append((key, value, r["origin"]))
                continue
            rep.nodes += _apply_node(conn, key, fld, value, when, rep)
        else:
            rep.edges += _apply_edge(conn, key, fld, value, when, rep)

    for drop, keep, origin in merges:
        if drop == keep:
            continue
        alive = {
            row["id"] for row in conn.execute(
                "SELECT id FROM nodes WHERE id IN (?,?)", (drop, keep)
            )
        }
        if drop not in alive:
            continue
        if keep not in alive:
            # 남길 쪽이 없으면 합칠 곳이 없다. 표는 그대로 두고 다음 기회를
            # 기다린다 — 여기서 지우면 '왜 남아 있나'를 물을 수 없다.
            rep.skipped += 1
            continue
        from .promote import merge_node  # 순환 import 를 피해 여기서

        # 방법 이름은 처음 합친 명령의 것을 그대로 — 이력에 '되살아나서
        # 다시 합쳤다'가 아니라 '왜 같은 노드인가'가 남아야 한다.
        merge_node(store, drop, keep, method=origin)
        rep.remerged.append((drop, keep))
    return rep


def _redirect_merged_endpoints(store, edge_keys, everything: bool) -> int:
    conn = store.conn
    if everything:
        ends = {
            r["id"] for r in conn.execute(
                """SELECT DISTINCT src AS id FROM edges
                   UNION SELECT DISTINCT dst FROM edges"""
            )
        }
    else:
        ends = set()
        for key in edge_keys or ():
            parts = key.split(EDGE_SEP)
            if len(parts) == 3:
                ends.update(parts[:2])
    moved = 0
    for batch in _chunks(sorted(ends)):
        marks = ",".join("?" * len(batch))
        for r in conn.execute(
            f"""SELECT key, value FROM overrides
                 WHERE target = 'node' AND field = 'merged_into' AND key IN ({marks})""",
            batch,
        ).fetchall():
            drop, keep = r["key"], _decode(r["value"])
            if not isinstance(keep, str) or drop == keep:
                continue
            if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (drop,)).fetchone():
                continue  # 노드가 살아 있으면 노드 병합 쪽이 옮긴다
            if not conn.execute("SELECT 1 FROM nodes WHERE id = ?", (keep,)).fetchone():
                continue
            from .promote import _rewrite_edges

            moved += _rewrite_edges(conn, drop, keep)["edges"]
    return moved


def _apply_node(conn, node_id: str, fld: str, value, when: str, rep: ReapplyReport) -> int:
    if fld in NODE_COLUMNS:
        row = conn.execute(f"SELECT {fld} FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return 0
        current = row[0]
        if current == value:
            return 0
        if not _should_apply(when, current):
            rep.skipped += 1
            return 0
        if fld == "label" and not value:
            return 0  # 라벨은 비울 수 없다 (ontology.Node)
        conn.execute(
            f"UPDATE nodes SET {fld} = ?, updated_at = datetime('now') WHERE id = ?",
            (value, node_id),
        )
        if fld == "label" and current and current != value:
            # 옛 이름은 별칭으로 남는다 — 검색이 그 이름으로도 찾아야 한다.
            conn.execute(
                "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)",
                (node_id, current),
            )
        return 1
    if fld.startswith("props."):
        return _apply_props(conn, "nodes", "id = ?", (node_id,), fld[len("props."):], value, when, rep)
    if fld.startswith("alias:"):
        # 손으로 적은 별칭(`data/aliases.tsv`). 칸 이름에 별칭을 넣어 한 노드에
        # 여럿을 둔다. 수집이 노드를 다시 세워도 여기서 되살아난다.
        alias = fld[len("alias:"):]
        if not alias or conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone() is None:
            return 0
        cur = conn.execute("INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)", (node_id, alias))
        return cur.rowcount
    return 0


def _apply_edge(conn, key: str, fld: str, value, when: str, rep: ReapplyReport) -> int:
    parts = key.split(EDGE_SEP)
    if len(parts) != 3:
        return 0
    src, dst, etype = parts
    where, params = "src = ? AND dst = ? AND type = ?", (src, dst, etype)
    if fld == "deleted":
        # '없다'는 사실. 모든 소스의 같은 엣지를 지운다 — 방향이 뒤집힌 인과는
        # 어느 소스가 냈든 뒤집힌 것이다.
        if not value:
            return 0
        return conn.execute(f"DELETE FROM edges WHERE {where}", params).rowcount
    if fld == "moved_to":
        # **'이 엣지는 저리로 갔다'** — 노드의 `merged_into` 와 같은 말이다
        # (2026-09-11). 자리를 옮긴 엣지를 `deleted` 로 적으면 다음 수집이
        # 들고 온 **새 값까지 함께 버린다**: 왕 시드를 다시 돌려 재위 날짜를
        # 새로 읽어 와도 일반 자리로 들어오는 길이 막혀 있어, 옮겨 둔 자리의
        # 띠가 영영 비어 있었다 (혁거세 거서간·온조왕·수로왕 등 15명).
        if not value or value == dst:
            return 0
        moved = 0
        for r in conn.execute(f"SELECT rowid, * FROM edges WHERE {where}", params).fetchall():
            twin = conn.execute(
                "SELECT rowid FROM edges WHERE src=? AND dst=? AND type=? AND source=?",
                (src, value, etype, r["source"]),
            ).fetchone()
            if twin is None:
                conn.execute("UPDATE edges SET dst = ? WHERE rowid = ?", (value, r["rowid"]))
            else:
                # 이미 그 자리에 줄이 있으면 **비어 있는 칸만** 채우고 옛 줄을
                # 지운다. 적혀 있는 날짜를 덮지 않는다 — 표가 적어 준 것일 수 있다.
                conn.execute(
                    """UPDATE edges
                          SET start_date = COALESCE(NULLIF(start_date,''), ?),
                              end_date   = COALESCE(NULLIF(end_date,''), ?)
                        WHERE rowid = ?""",
                    (r["start_date"], r["end_date"], twin["rowid"]),
                )
                conn.execute("DELETE FROM edges WHERE rowid = ?", (r["rowid"],))
            moved += 1
        return moved
    if fld in EDGE_COLUMNS:
        rows = conn.execute(f"SELECT rowid, {fld} FROM edges WHERE {where}", params).fetchall()
        changed = 0
        for r in rows:
            if r[1] == value or not _should_apply(when, r[1]):
                continue
            conn.execute(f"UPDATE edges SET {fld} = ? WHERE rowid = ?", (value, r[0]))
            changed += 1
        return changed
    if fld.startswith("props."):
        return _apply_props(conn, "edges", where, params, fld[len("props."):], value, when, rep)
    return 0


def _apply_props(conn, table: str, where: str, params: tuple, key: str, value, when: str,
                 rep: ReapplyReport) -> int:
    rows = conn.execute(f"SELECT rowid, props FROM {table} WHERE {where}", params).fetchall()
    changed = 0
    for r in rows:
        props = json.loads(r["props"] or "{}")
        current = props.get(key)
        if current == value:
            continue
        if not _should_apply(when, current):
            rep.skipped += 1
            continue
        if value is None:
            props.pop(key, None)
        else:
            props[key] = value
        conn.execute(
            f"UPDATE {table} SET props = ? WHERE rowid = ?",
            (json.dumps(props, ensure_ascii=False), r[0]),
        )
        changed += 1
    return changed


def summary(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    """(target, origin, field, 건수) — 무엇이 얼마나 고쳐져 있는가."""
    return [
        (r[0], r[1], r[2], r[3])
        for r in conn.execute(
            """SELECT target, origin, field, COUNT(*) FROM overrides
               GROUP BY target, origin, field ORDER BY target, origin, field"""
        )
    ]


def seed_from_db(conn: sqlite3.Connection) -> dict[str, int]:
    """표가 없던 때 고쳐 둔 값을 지금 DB 에서 되짚어 표에 적는다 (한 번).

    되짚을 수 있는 것만 한다 — 그 값이 '고친 것'임을 DB 자체가 말하는 것:
    - 재위 표식이 붙은 직위 엣지의 날짜 (`reigns`)
    - Wikidata 노드의 부분 날짜 — Wikidata 는 언제나 온날짜를 주므로
      '1592'·'1592-09' 는 `precision` 이 자른 것이다
    - 국편 정본이 씌워진 노드의 설명·연대·표식 (`props.canon = nikh`)
    - 민족문화대백과 정의로 채운 설명 (`props.desc_source = aks`)
    - 사전이 옮긴 설명과 비운 설명 (`props.desc_en`)
    - 합쳐 없앤 노드 (남긴 쪽의 `props.merged_from`)
    라벨은 여기서 하지 않는다 — `relabel` 이 표에서 다시 적는다."""
    counts = {"reigns": 0, "precision": 0, "nikh": 0, "describe": 0, "redescribe": 0, "merged": 0}

    # 합쳐 없앤 노드 — 남긴 쪽의 `props.merged_from` 이 그 이력이다.
    for r in conn.execute(
        "SELECT id, props FROM nodes WHERE props LIKE '%\"merged_from\"%'"
    ).fetchall():
        props = json.loads(r["props"] or "{}")
        for entry in props.get("merged_from") or []:
            old_id = entry.get("id") if isinstance(entry, dict) else None
            if not old_id or old_id == r["id"]:
                continue
            record(conn, "node", old_id, "merged_into", r["id"],
                   str(entry.get("method") or "merged"), str(entry.get("label") or ""))
            counts["merged"] += 1

    for r in conn.execute(
        """SELECT src, dst, type, start_date, end_date, props FROM edges
            WHERE type = 'held_position' AND props LIKE '%"reign"%'"""
    ).fetchall():
        props = json.loads(r["props"] or "{}")
        if "reign" not in props:
            continue
        key = edge_key(r["src"], r["dst"], r["type"])
        record(conn, "edge", key, "props.reign", props["reign"], "reigns")
        if r["start_date"]:
            record(conn, "edge", key, "start_date", r["start_date"], "reigns")
        if r["end_date"]:
            record(conn, "edge", key, "end_date", r["end_date"], "reigns")
        counts["reigns"] += 1

    for r in conn.execute(
        """SELECT id, start_date, end_date FROM nodes
            WHERE id LIKE 'wd:%'
              AND (length(start_date) IN (4, 7) OR length(end_date) IN (4, 7))"""
    ).fetchall():
        for col in ("start_date", "end_date"):
            if r[col] and len(r[col]) in (4, 7):
                record(conn, "node", r["id"], col, r[col], "precision")
        counts["precision"] += 1

    for r in conn.execute(
        "SELECT id, description, start_date, end_date, props FROM nodes WHERE props LIKE '%\"canon\"%'"
    ).fetchall():
        props = json.loads(r["props"] or "{}")
        if props.get("canon") != "nikh":
            continue
        for row in canon_rows(r["id"], r["description"], r["start_date"], r["end_date"], props):
            record(conn, *row)
        counts["nikh"] += 1

    for r in conn.execute(
        "SELECT id, description, props FROM nodes WHERE props LIKE '%\"desc_source\"%'"
    ).fetchall():
        props = json.loads(r["props"] or "{}")
        ds = props.get("desc_source")
        if ds == "aks" and props.get("canon") != "nikh" and (r["description"] or "").strip():
            record(conn, "node", r["id"], "description", r["description"], "describe")
            record(conn, "node", r["id"], "props.desc_source", "aks", "describe")
            if props.get("desc_url"):
                record(conn, "node", r["id"], "props.desc_url", props["desc_url"], "describe")
            counts["describe"] += 1
        elif "desc_en" in props and props.get("canon") != "nikh":
            for row in redescribe_rows(r["id"], props["desc_en"], r["description"] or None):
                record(conn, *row)
            counts["redescribe"] += 1
    conn.commit()
    return counts


# --- 각 명령이 적는 줄의 모양 -----------------------------------------------
# 명령마다 여기 함수를 불러 같은 모양으로 적는다. 칸 이름과 조건이 한 곳에
# 있어야 `seed_from_db` 가 되짚은 것과 명령이 새로 적은 것이 같다.

def canon_rows(node_id: str, description: str | None, start: str | None, end: str | None,
               props: dict) -> list[tuple]:
    """국편 정본이 씌워진 노드 — 설명·연대·표식은 언제나 정본이 이긴다."""
    rows: list[tuple] = []
    if (description or "").strip():
        rows.append(("node", node_id, "description", description, "nikh", "국편 정본"))
    for col, val in (("start_date", start), ("end_date", end)):
        if val:
            rows.append(("node", node_id, col, val, "nikh", "국편 정본"))
    for key in ("canon", "desc_source", "nikh_id", "nikh_url", "hanja", "date_basis"):
        if props.get(key):
            rows.append(("node", node_id, f"props.{key}", props[key], "nikh", "국편 정본"))
    return rows


def redescribe_rows(node_id: str, english: str, korean: str | None) -> list[tuple]:
    """사전이 옮긴(또는 비운) 설명 — 지금 값에 한글이 없을 때만 씌운다.

    출처 표식(`desc_source`)은 적지 않는다. 조건이 '설명에 한글이 없다'인데
    표식 칸의 값으로는 그 조건을 잴 수 없어서다. 표식이 없으면 화면은 출처
    줄을 비운다 — 틀린 출처보다 낫다 (`provenance`)."""
    return [
        ("node", node_id, "description", korean, "redescribe", english[:80], "foreign"),
        ("node", node_id, "props.desc_en", english, "redescribe", ""),
    ]
