"""인과(`caused`)를 사람이 판정한다 — 글로 읽는 장의 머리에 서는 것.

2026-10-05, 애드센스 `Low value content` 세 번째. 글로 읽는 장의 중심이 남의
글 요약이어서, 이 관계망만 아는 것(무엇이 이 일을 불렀고 무엇으로 이어졌는지)을
장 머리로 올렸다 (`pages._story`). 올리자 틀린 인과가 장 맨 위에 섰다 —
임진왜란 장에 '이순신의 명량 해전 승리는 임진왜란의 원인', '변협은 임진왜란의
배경(변협이 죽은 지 2년 뒤에 임진왜란이 일어났다)', '오억령은 임진왜란의
계기(침입을 경고했다)'. 엣지는 추출이 근거 문장을 갖고 낸 것이지만 근거가
**인과를 말하는지**는 기계가 못 잰다 (메모리 '인과는 근거 문장이 그 인과를
말해야 한다'). 그래서 머리에 서는 것은 **이 표가 참이라 한 것뿐**이다.

## 판정은 표가 한다 (`data/causal.tsv`)

    원인 id<TAB>결과 id<TAB>판정<TAB>근거

- **인과** — 참이다. 엣지에 `checked` 를 단다. 장 머리에 설 수 있다.
- **고침** — 인과는 참인데 붙은 설명(`how`)이 틀렸다. 근거 칸이 새 설명이 된다
  (실측: '박정희 → 10·26' 의 설명이 근거 문장의 박근혜를 김재규로 바꿔 적었다).
  근거 문장이나 정본이 적는 통설 밖의 것을 보태지 않는다 (2026-10-05 판정 15건).
- **관련** — 두 노드 사이는 참인데 **인과가 아니다** — 시간 순서뿐인 것(죽은 지
  2년 뒤), 한 일이 다른 일 안에서 일어난 것(명량 해전과 임진왜란), 경고·예견·
  평가. `related_to` 로 **낮춘다** (§1-6: 지우면 참인 관계가 먼저 사라진다).
  근거 칸의 문장이 화면에 그 관계의 근거로 뜬다.
- **뒤집기** — 방향이 반대다. 결과 → 원인으로 다시 건다 (`chronology` 의 flip
  과 같다). 근거 칸이 새 엣지의 설명이 된다.
- **삭제** — 관계 자체가 거짓이다 (동명이인, 낱말을 사람으로 읽은 것).

판정이 없는 인과는 **지우지 않는다** — 화면의 목록과 그래프에는 그대로 서고,
글로 읽는 장의 머리에만 안 선다. 고친 값은 편집 계층(`overrides`)에 남아
재추출이 되돌리지 못한다. 원본과 파생본에 한 번씩:

    uv run histgraph causal --apply
    uv run histgraph --db data/korea.sqlite causal --apply
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov
from .ontology import Edge
from .store import GraphStore

VERDICTS = ("인과", "고침", "관련", "뒤집기", "삭제")
EDGE_TYPE = "caused"
ORIGIN = "causal"
SOURCE_MARK = "causal"
TABLE = Path("data/causal.tsv")


class CausalTableError(ValueError):
    pass


@dataclass(frozen=True)
class TableRow:
    cause: str
    effect: str
    verdict: str
    note: str


@dataclass
class TableReport:
    checked: int = 0
    demoted: int = 0
    flipped: int = 0
    deleted: int = 0
    absent: list[TableRow] = field(default_factory=list)


def load_table(path: Path = TABLE) -> list[TableRow]:
    rows: list[TableRow] = []
    seen: set[tuple[str, str]] = set()
    if not path.exists():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("\t")]
        if len(parts) < 4 or not all(parts[:4]):
            raise CausalTableError(
                f"{path}:{lineno} 원인 id·결과 id·판정·근거 네 칸입니다: {raw!r}")
        cause, effect, verdict, note = parts[:4]
        if verdict not in VERDICTS:
            raise CausalTableError(
                f"{path}:{lineno} 판정은 {'/'.join(VERDICTS)} 중 하나: {verdict!r}")
        if (cause, effect) in seen:
            raise CausalTableError(f"{path}:{lineno} 같은 쌍이 두 번 적혔습니다: {raw!r}")
        seen.add((cause, effect))
        rows.append(TableRow(cause, effect, verdict, note))
    return rows


def _has(conn: sqlite3.Connection, node_id: str) -> bool:
    return conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone() is not None


def _props(conn: sqlite3.Connection, a: str, b: str) -> tuple[str | None, dict]:
    """그 인과의 종류(배경·계기…)와 props — 소스가 여럿이면 첫 줄."""
    row = conn.execute(
        "SELECT label, props FROM edges WHERE src = ? AND dst = ? AND type = ? LIMIT 1",
        (a, b, EDGE_TYPE)).fetchone()
    if row is None:
        return None, {}
    return row["label"], json.loads(row["props"] or "{}")


def apply_table(store: GraphStore, table: list[TableRow]) -> TableReport:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    c = store.conn
    rep = TableReport()
    edge_keys: set[str] = set()
    new_edges: list[Edge] = []
    for row in table:
        key = ov.edge_key(row.cause, row.effect, EDGE_TYPE)
        if not (_has(c, row.cause) and _has(c, row.effect)):
            rep.absent.append(row)
            continue
        if row.verdict in ("인과", "고침"):
            # 다른 표(`chronology` drop)가 지운 것을 되살리지 않는다 — 표시만 단다.
            ov.record(c, "edge", key, "props.checked", True, ORIGIN, row.note)
            if row.verdict == "고침":
                ov.record(c, "edge", key, "props.how", row.note, ORIGIN, row.note)
            edge_keys.add(key)
            rep.checked += 1
            continue

        label, props = _props(c, row.cause, row.effect)
        ov.record(c, "edge", key, "deleted", True, ORIGIN, row.note)
        edge_keys.add(key)
        if row.verdict == "삭제":
            rep.deleted += 1
            continue
        if row.verdict == "뒤집기":
            rep.flipped += 1
            back = ov.edge_key(row.effect, row.cause, EDGE_TYPE)
            ov.forget(c, "edge", back, "deleted")
            ov.record(c, "edge", back, "props.checked", True, ORIGIN, row.note)
            edge_keys.add(back)
            if c.execute("SELECT 1 FROM edges WHERE src = ? AND dst = ? AND type = ? LIMIT 1",
                         (row.effect, row.cause, EDGE_TYPE)).fetchone() is None:
                new_edges.append(Edge(
                    src=row.effect, dst=row.cause, type=EDGE_TYPE, source=SOURCE_MARK,
                    label=label, confidence=0.9,
                    props={"how": row.note, "evidence": props.get("evidence") or row.note,
                           "checked": True, "doc": ORIGIN}))
            continue
        # 관련 — 낮춘다. 근거 칸이 그 관계의 근거로 뜬다.
        rep.demoted += 1
        rkey = ov.edge_key(row.cause, row.effect, "related_to")
        ov.forget(c, "edge", rkey, "deleted")
        c.execute(
            """INSERT INTO edges (src, dst, type, source, label, confidence, props)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(src, dst, type, source) DO UPDATE SET props = excluded.props""",
            (row.cause, row.effect, "related_to", SOURCE_MARK, None, 0.8,
             json.dumps({"evidence": row.note, "was": EDGE_TYPE}, ensure_ascii=False)))
    ov.reapply(store, edge_keys=edge_keys)
    if new_edges:
        store.upsert_edges(new_edges)
    c.commit()
    return rep
