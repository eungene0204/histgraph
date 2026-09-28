"""사람과 사람 사이의 '관련'을 이름 있는 관계로 가른다 (`related_to` → 친족·벗·사제).

2026-09-23 사용자: "대한민국 역사 노드에서 아버지, 어머니, 친구, 연인 등등이
단순히 '관계'라고 되어 있는지 전수 조사해서 수정하도록 해". 재 보니 사람끼리의
`related_to` 가 원본에 922건이었다 — 산문 추출이 낸 876건과 `spouses` 가 혼인이
아니라고 낮춘 46건(사위·장인·형수…). 온톨로지에 사람끼리의 타입은 자녀·배우자·
사제 셋뿐이라, 형제·장인·벗·연인은 담을 자리가 없어 전부 '관련'으로 서 있었다.
화면은 그것을 "A 와 B 는 관련이 있다"로 읽는다 — 이산해와 사위 이덕형도, 정약용과
형 정약전도.

## 판정은 표가 한다 (`data/kin.tsv`)

    인물 id(A)<TAB>인물 id(B)<TAB>판정<TAB>근거

판정은 **"B 는 A 의 ○○"** 하나다. A·B 는 엣지의 src·dst 그대로다.

- **타입이 있는 것** — 아버지·어머니·부모 (`child_of` A→B, 앞 둘은 라벨로),
  자녀 (`child_of` B→A), 배우자 (`spouse_of`), 스승 (`taught` B→A),
  제자 (`taught` A→B). '관련' 선을 지우고 그 타입의 선을 세운다.
- **타입이 없는 것** — 형제·조부모·장인·사위·벗·연인 … (`LABELS`). '관련' 선에
  그 이름을 라벨로 단다. 화면은 라벨이 타입 이름을 이기는 길(`server.LABEL_HEADS`)
  로 읽는다: 목록 머리는 방향으로 갈라(`KIN_DIR_HEAD` — 사위 쪽에서는 '장인',
  장인 쪽에서는 '사위'), 문장은 "이산해의 사위는 이덕형이다".
- **관련** — 친족·벗·사제가 아니다 (같은 상소, 같은 전투, 추천·탄핵, 왕과 신하).
  그대로 둔다. 대부분이 이것이다 — 동료·맹우·후원자를 '벗'으로 부르지 않는다.
- **삭제** — 엣지가 거짓이다 (동명이인·오독). 지운다.

**이름만으로 정하지 않는다.** 판정은 근거 구절을 한 줄씩 읽고 적었다 — '아버지'가
문장에 있어도 남의 아버지이면 그 사이의 관계가 아니다 (§1-6 · 개인 역사의 호칭
오독과 같은 함정이다).

고친 값은 편집 계층(`overrides`)에 남아 재수집이 되돌리지 못한다. 원본과
파생본에 한 번씩:

    uv run histgraph kin                      # 판정이 없는 후보를 센다
    uv run histgraph kin --apply
    uv run histgraph --db data/korea.sqlite kin --apply

**표에 없는 후보가 남으면 종료 코드 1.** 추출을 다시 돌려 새 사람끼리의 '관련'이
들어오면 여기서 묻는다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov
from .ontology import MAX_TARGETS
from .store import GraphStore

TABLE = Path("data/kin.tsv")
ORIGIN = "kin"
SOURCE_MARK = "kin"

# 묻는 출처 — 산문 추출과, 혼인이 아니라고 낮춘 것(`spouses`). 위키데이터의
# '관련'(스키마가 안 맞아 낮춘 것)은 라벨이 이미 뜻을 들고 있다.
ASKED = ("extract", "spouses")

# 타입이 없는 관계 — 라벨이 된다. 값은 **B 쪽에서 본 A** 의 이름(목록 머리 'in').
# "B 는 A 의 사위" 이면 A 는 B 의 장인 또는 장모라 성별을 모르면 둘을 함께 적는다.
LABELS: dict[str, str] = {
    "형제": "형제", "사촌": "사촌", "동서": "동서", "사돈": "사돈",
    "인척": "인척", "친척": "친척", "벗": "벗", "연인": "연인",
    "조부모": "손주", "손주": "조부모",
    "외조부모": "외손", "외손": "외조부모",
    "숙부": "조카", "숙모": "조카", "조카": "숙부·숙모",
    "장인": "사위", "장모": "사위", "사위": "장인·장모",
    "시아버지": "며느리", "시어머니": "며느리", "며느리": "시부모",
    "처남": "매부", "매부": "처남·처제",
    "형수": "시동생", "시동생": "형수",
    "양부모": "양자", "양자": "양부모",
}

# 방향으로 갈라 부르는 목록 머리 (`server.LABEL_DIR_HEAD` 에 들어간다).
# out = A 의 장에서 B 를 부르는 이름, in = B 의 장에서 A 를 부르는 이름.
KIN_DIR_HEAD: dict[str, dict[str, str]] = {k: {"out": k, "in": v} for k, v in LABELS.items()}

# 타입이 있는 관계 — (타입, 뒤집기, 라벨). 뒤집기면 B→A 로 세운다.
TYPED: dict[str, tuple[str, bool, str | None]] = {
    "아버지": ("child_of", False, "아버지"),
    "어머니": ("child_of", False, "어머니"),
    "부모": ("child_of", False, None),
    "자녀": ("child_of", True, None),
    "배우자": ("spouse_of", False, None),
    "스승": ("taught", True, None),
    "제자": ("taught", False, None),
}

VERDICTS = frozenset(LABELS) | frozenset(TYPED) | {"관련", "삭제"}


class KinTableError(ValueError):
    pass


@dataclass(frozen=True)
class TableRow:
    a: str
    b: str
    verdict: str
    note: str


@dataclass
class TableReport:
    labeled: int = 0
    typed: int = 0
    already: int = 0      # 같은 타입의 선이 이미 있어 '관련'만 걷은 것
    kept: int = 0         # 관련 — 그대로 둔 것
    deleted: int = 0
    missing: int = 0      # 이 그래프에 두 노드가 다 있지는 않은 줄
    over: list[tuple[str, str, str]] = field(default_factory=list)   # 카디널리티로 못 세운 것


def candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """사람끼리의 '관련' 가운데 아직 이름이 없는 것."""
    marks = ",".join("?" * len(ASKED))
    kin = ",".join("?" * len(LABELS))
    return conn.execute(
        f"""SELECT DISTINCT e.src, e.dst, e.props, a.label AS a_label, b.label AS b_label
              FROM edges e
              JOIN nodes a ON a.id = e.src AND a.type = 'person'
              JOIN nodes b ON b.id = e.dst AND b.type = 'person'
             WHERE e.type = 'related_to' AND e.source IN ({marks})
               AND (e.label IS NULL OR e.label NOT IN ({kin}))
             ORDER BY a.label, b.label""",
        (*ASKED, *LABELS),
    ).fetchall()


def load_table(path: Path = TABLE) -> list[TableRow]:
    rows: list[TableRow] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 4 or not all(parts[:4]):
            raise KinTableError(f"{path}:{lineno} 인물 id·인물 id·판정·근거 네 칸입니다: {raw!r}")
        a, b, verdict, note = parts[:4]
        if verdict not in VERDICTS:
            raise KinTableError(f"{path}:{lineno} 모르는 판정 {verdict!r}")
        if (a, b) in seen:
            raise KinTableError(f"{path}:{lineno} 같은 쌍이 두 번 적혔습니다: {raw!r}")
        seen.add((a, b))
        rows.append(TableRow(a, b, verdict, note))
    return rows


def unjudged(conn: sqlite3.Connection, table: list[TableRow]) -> list[sqlite3.Row]:
    judged = {(r.a, r.b) for r in table}
    return [c for c in candidates(conn) if (c["src"], c["dst"]) not in judged]


def _both_here(conn: sqlite3.Connection, a: str, b: str) -> bool:
    n, = conn.execute("SELECT COUNT(*) FROM nodes WHERE id IN (?,?)", (a, b)).fetchone()
    return n == 2


def _evidence(conn: sqlite3.Connection, a: str, b: str) -> str | None:
    """걷을 '관련' 선의 근거 구절 — 새로 세우는 선이 들고 간다 (원문이 사람 말보다 낫다)."""
    for (props,) in conn.execute(
        "SELECT props FROM edges WHERE src = ? AND dst = ? AND type = 'related_to'", (a, b)
    ):
        ev = json.loads(props or "{}").get("evidence")
        if ev:
            return " / ".join(ev) if isinstance(ev, list) else ev
    return None


def apply_table(store: GraphStore, table: list[TableRow]) -> TableReport:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    c = store.conn
    rep = TableReport()
    for row in table:
        key = ov.edge_key(row.a, row.b, "related_to")
        if row.verdict == "관련":
            rep.kept += 1
            continue
        if row.verdict == "삭제":
            ov.record(c, "edge", key, "deleted", True, ORIGIN, row.note)
            c.execute("DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'related_to'",
                      (row.a, row.b))
            rep.deleted += 1
            continue
        if row.verdict in LABELS:
            ov.record(c, "edge", key, "label", row.verdict, ORIGIN, row.note)
            c.execute("UPDATE edges SET label = ? WHERE src = ? AND dst = ? AND type = 'related_to'",
                      (row.verdict, row.a, row.b))
            rep.labeled += 1
            continue

        etype, flip, label = TYPED[row.verdict]
        src, dst = (row.b, row.a) if flip else (row.a, row.b)
        if not _both_here(c, row.a, row.b):
            # 편집 계층에는 적어 둔다 — 다시 들어올 때를 위한 것이다.
            ov.record(c, "edge", key, "deleted", True, ORIGIN, row.note)
            rep.missing += 1
            continue
        evidence = _evidence(c, row.a, row.b) or row.note
        exists = c.execute(
            "SELECT 1 FROM edges WHERE type = ? AND ((src = ? AND dst = ?) OR (? = 'spouse_of' AND src = ? AND dst = ?))",
            (etype, src, dst, etype, dst, src),
        ).fetchone()
        if not exists:
            limit = MAX_TARGETS.get(etype)
            if limit is not None:
                others = {r[0] for r in c.execute(
                    "SELECT DISTINCT dst FROM edges WHERE src = ? AND type = ?", (src, etype))}
                if len(others) >= limit:
                    # 부모가 이미 둘이다 — 동명이인이거나 양부모다. 사람이 다시 본다.
                    rep.over.append((src, dst, etype))
                    continue
            c.execute(
                """INSERT INTO edges (src, dst, type, source, label, confidence, props)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(src, dst, type, source) DO UPDATE SET
                     label = excluded.label, props = excluded.props""",
                (src, dst, etype, SOURCE_MARK, label, 0.9,
                 json.dumps({"evidence": evidence, "note": row.note, "was": "related_to"},
                            ensure_ascii=False)),
            )
            rep.typed += 1
        else:
            rep.already += 1
        ov.record(c, "edge", key, "deleted", True, ORIGIN, row.note)
        c.execute("DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'related_to'",
                  (row.a, row.b))
    c.commit()
    return rep
