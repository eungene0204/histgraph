"""연대 — 원인은 결과보다 먼저다.

2026-09-05 지적: 연표에서 공석신주사건(1636) 아래에 그 **원인**인
병자호란(1636-12-09)이 섰다 — "원인 사건이 먼저 발생해야 하는거 아닌가?"
맞다. 그런데 엣지는 참이었고 틀린 것은 날짜였다: 공석신주사건은 1638년
1월 유백증의 탄핵인데 배경이 된 해(1636)가 적혀 있었다.

실측 (화면 DB, 사건→사건 인과 251건): 원인 연도가 결과보다 뒤 8건, 같은
해인데 결과는 연도만 알고 원인은 달까지 아는 것 20건, 같은 해에 둘 다
달까지 아는데 원인이 뒤 13건. 읽어 보니 세 부류였다:

- **결과의 날짜가 틀리거나 거칠다** — 임신약조가 1510(삼포왜란의 해),
  대동법이 1624(삼도 확대의 해), 단발령이 음력 날짜를 양력처럼.
  → 정본(민백·국편)과 위키백과에서 날짜를 찾아 적는다 (`date`).
- **원인이 결과를 끝낸 것이다** — 5·18 → 서울의 봄, 이괄의 난 → 대동법
  (충청·전라분 폐지), 병인양요 → 경복궁 중건(공역 지연). 인과가 아니라
  '영향'이고, 결과가 원인보다 먼저 시작했다. → 지운다 (`drop`).
- **방향이 뒤집혔다** — 위화도 회군 → 요동 정벌. 정벌군이 회군한 것이다.
  → 뒤집는다 (`flip`).

`causes.backwards` 는 연도 단위에 1년 여유를 두므로 이것들을 못 잡는다.
그렇다고 여유를 없애면 '같은 해 안'의 참인 인과(을미사변 → 을미의병)가
먼저 죽는다. 그래서 **판정은 표가 한다** (`data/chronology.tsv`):

    date<TAB>노드 id<TAB>시작<TAB>끝<TAB>근거     끝은 비워도 된다
    drop<TAB>원인 id<TAB>결과 id<TAB>근거
    flip<TAB>원인 id<TAB>결과 id<TAB>종류<TAB>근거   결과 → 원인으로 다시 건다

날짜는 **양력**으로 적는다. 화면 DB 는 Wikidata 노드가 그레고리력이고
국편 노드가 음력 그대로라 섞여 있다 — 같은 해의 순서를 맞추려면 한쪽으로
모아야 하고, 양력이 그쪽이다. 음력을 옮겼으면 근거 칸에 원래 날짜를
적는다. 하루까지 모르면 달까지만 적는다 — 지어낸 정밀도는 거짓이다.

고친 값은 편집 계층(`overrides`)에 남는다 — 수집이 날짜를 되돌리거나
`causes` 가 같은 문서에서 지운 엣지를 다시 뽑아 와도 다시 씌워진다.

남는 것: 결과의 날짜가 원인보다 **거칠어서** 원인을 품는 경우(만주사변
1931-09-18 → 신사참배 1931)는 데이터로는 못 가른다. 그것은 화면이
맡는다 — 연표는 원인을 품는 거친 날짜를 원인 바로 뒤에 세운다
(`web/src/lib/timeline.js` `sortMarks`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov
from .ontology import Edge

ORIGIN = "chronology"
EDGE_TYPE = "caused"
SOURCE_MARK = "chronology"
ACTIONS = ("date", "drop", "flip")


class ChronologyTableError(ValueError):
    pass


@dataclass(frozen=True)
class Row:
    action: str
    a: str            # date: 노드 id · drop/flip: 원인 id
    b: str            # date: 시작 · drop/flip: 결과 id
    c: str = ""       # date: 끝 · flip: 종류
    note: str = ""


@dataclass
class Suspect:
    src: str
    dst: str
    cause: str
    effect: str
    cause_date: str
    effect_date: str
    verdict: str      # after · within


@dataclass
class Report:
    backwards: list[Suspect] = field(default_factory=list)   # 원인이 결과보다 뒤
    within: list[Suspect] = field(default_factory=list)      # 결과의 거친 날짜가 원인을 품는다
    unknown: int = 0                                          # 어느 쪽인가 연대를 모른다
    dated: int = 0
    dropped: int = 0
    flipped: int = 0
    absent: list[Row] = field(default_factory=list)           # 이 그래프에 없는 대상


# --- 표 -------------------------------------------------------------------


def load_table(path: Path) -> list[Row]:
    rows: list[Row] = []
    seen: set[tuple[str, str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        action = parts[0]
        if action not in ACTIONS:
            raise ChronologyTableError(f"{path}:{lineno} 판정은 {'/'.join(ACTIONS)} 입니다: {action!r}")
        if action == "date":
            if len(parts) < 5 or not parts[1] or not parts[2]:
                raise ChronologyTableError(
                    f"{path}:{lineno} date 는 id·시작·끝·근거 네 칸입니다 (끝은 비워도 됨): {raw!r}")
            row = Row(action, parts[1], parts[2], parts[3], parts[4])
            for d in (row.b, row.c):
                if d and _parts(d) is None:
                    raise ChronologyTableError(f"{path}:{lineno} 날짜가 아닙니다: {d!r}")
        elif action == "drop":
            if len(parts) < 4 or not parts[1] or not parts[2]:
                raise ChronologyTableError(f"{path}:{lineno} drop 은 원인·결과·근거 세 칸입니다: {raw!r}")
            row = Row(action, parts[1], parts[2], "", parts[3])
        else:
            if len(parts) < 5 or not parts[1] or not parts[2] or not parts[3]:
                raise ChronologyTableError(
                    f"{path}:{lineno} flip 은 원인·결과·종류·근거 네 칸입니다: {raw!r}")
            row = Row(action, parts[1], parts[2], parts[3], parts[4])
        if not row.note:
            raise ChronologyTableError(f"{path}:{lineno} 근거가 비었습니다: {raw!r}")
        key = (row.action if row.action != "flip" else "drop", row.a, row.b)
        if key in seen:
            raise ChronologyTableError(f"{path}:{lineno} 같은 대상이 두 번 적혔습니다: {raw!r}")
        seen.add(key)
        rows.append(row)
    return rows


# --- 날짜 -----------------------------------------------------------------


def _parts(date: str | None) -> tuple[int, ...] | None:
    """'1388-05' → (1388, 5). 기원전 '-0057' → (-57,). 날짜가 아니면 None."""
    s = (date or "").strip()
    if not s:
        return None
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    bits = s.split("-")
    if not bits or not all(b.isdigit() for b in bits):
        return None
    nums = [int(b) for b in bits[:3]]
    if neg:
        nums[0] = -nums[0]
    return tuple(nums)


def order(cause: str | None, effect: str | None) -> str:
    """원인 날짜와 결과 날짜의 관계. 둘 중 거친 쪽의 정밀도로 비교한다.

    after   원인이 결과보다 뒤 — 데이터가 틀렸다
    ok      원인이 앞
    within  결과의 거친 날짜가 원인을 품는다 (또는 같은 날) — 화면이 가른다
    unknown 어느 쪽인가 날짜가 없다
    """
    a, b = _parts(cause), _parts(effect)
    if a is None or b is None:
        return "unknown"
    n = min(len(a), len(b))
    if a[:n] > b[:n]:
        return "after"
    if a[:n] < b[:n]:
        return "ok"
    return "within"


# --- 찾기 -----------------------------------------------------------------


def find(conn: sqlite3.Connection) -> Report:
    """사건이 결과인 인과 엣지 중 원인이 결과보다 뒤인 것. 사건만 보는
    이유: 나라·단체·개념은 '시작'이 건국·창립이라 그 전의 원인이 참일 수
    있다 (임진왜란 → 명나라의 쇠퇴). `causes.backwards` 와 같은 구분."""
    rep = Report()
    rows = conn.execute(
        """SELECT e.src, e.dst, s.label AS cause, d.label AS effect,
                  s.start_date AS cs, d.start_date AS es
             FROM edges e
             JOIN nodes s ON s.id = e.src
             JOIN nodes d ON d.id = e.dst
            WHERE e.type = ? AND d.type = 'event'
            ORDER BY s.start_date, s.label""",
        (EDGE_TYPE,),
    ).fetchall()
    for r in rows:
        verdict = order(r["cs"], r["es"])
        if verdict == "unknown":
            rep.unknown += 1
            continue
        if verdict == "ok":
            continue
        sus = Suspect(r["src"], r["dst"], r["cause"], r["effect"], r["cs"] or "", r["es"] or "", verdict)
        (rep.backwards if verdict == "after" else rep.within).append(sus)
    return rep


# --- 적용 -----------------------------------------------------------------


def apply(store, table: list[Row]) -> Report:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    conn = store.conn
    rep = Report()
    node_ids: set[str] = set()
    edge_keys: set[str] = set()
    new_edges: list[Edge] = []

    def has_node(nid: str) -> bool:
        return conn.execute("SELECT 1 FROM nodes WHERE id = ?", (nid,)).fetchone() is not None

    for row in table:
        if row.action == "date":
            if not has_node(row.a):
                rep.absent.append(row)
                continue
            ov.record(conn, "node", row.a, "start_date", row.b, ORIGIN, row.note)
            # 끝을 안 적었으면 손대지 않는다 — 모르는 것을 비우면 아는 것이 사라진다.
            # 다만 옛 끝이 새 시작보다 앞서면 그것은 앎이 아니라 옛 오류의
            # 잔재다 (공석신주사건: 시작 1638-01, 끝 1636 → 머리글이
            # '1638년 ~ 1636년'). 그때만 비운다.
            if row.c:
                ov.record(conn, "node", row.a, "end_date", row.c, ORIGIN, row.note)
            else:
                cur = conn.execute("SELECT end_date FROM nodes WHERE id = ?", (row.a,)).fetchone()[0]
                if cur and order(row.b, cur) == "after":
                    ov.record(conn, "node", row.a, "end_date", None, ORIGIN,
                              f"옛 끝({cur})이 새 시작보다 앞서 비움 — {row.note}")
            # 이 표의 날짜는 양력이다. 국편 노드의 '음력' 표식은 더 이상 참이 아니다.
            ov.record(conn, "node", row.a, "props.calendar", "gregorian", ORIGIN, row.note)
            node_ids.add(row.a)
            rep.dated += 1
            continue

        key = ov.edge_key(row.a, row.b, EDGE_TYPE)
        if not (has_node(row.a) and has_node(row.b)):
            rep.absent.append(row)
            continue
        ov.record(conn, "edge", key, "deleted", True, ORIGIN, row.note)
        edge_keys.add(key)
        if row.action == "drop":
            rep.dropped += 1
            continue
        # flip: 결과 → 원인으로 다시 건다. 근거는 표의 한 줄 — 모델이 뒤집어
        # 읽은 문장이 아니라 사람이 정본에서 확인한 문장이다. 바른 방향이
        # 이미 있으면(다른 문서가 제대로 읽은 것) 지우기만 한다.
        rep.flipped += 1
        if conn.execute(
            "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND type = ? LIMIT 1",
            (row.b, row.a, EDGE_TYPE),
        ).fetchone() is not None:
            continue
        new_edges.append(Edge(
            src=row.b, dst=row.a, type=EDGE_TYPE, source=SOURCE_MARK, label=row.c,
            confidence=0.9,
            props={"how": row.note, "evidence": row.note, "doc": ORIGIN},
        ))

    ov.reapply(store, node_ids=node_ids, edge_keys=edge_keys)
    if new_edges:
        store.upsert_edges(new_edges)
    conn.commit()
    return rep
