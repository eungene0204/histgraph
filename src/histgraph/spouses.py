"""산문이 혼인이라 읽은 것을 사람이 가른다 (`spouse_of`).

2026-09-16, 글로 읽는 장이 관계를 문장으로 읽기 시작하자 드러났다
(CLAUDE.md §1-15). 전에는 '배우자 · 정몽주' 라는 목록 한 줄이던 것이
**"정도전과 정몽주는 부부다"** 라는 문장이 되어 장에 섰다. 그래프 화면의
상세 패널은 이미 같은 문장을 내고 있었으니(`relations.js`) 새로 생긴 거짓은
아니고, 읽히는 자리가 늘면서 눈에 띈 것이다.

세어 보니 `spouse_of` 1,097 중 **산문 추출이 낸 40건**이 인척·지인을 혼인으로
읽고 있었다. 산문은 혼인을 이렇게 적는다 — "그의 **사위** 이덕형을 시켜",
"**장인** 정창손에게 알리고", "**형수** 현덕왕후의 묘를 파헤쳐". 추출은 두
이름이 한 문장에 혼인의 낱말과 같이 서면 혼인으로 읽었다. 그래서 며느리가
아내가 되고(영조—헌경왕후), 죽인 상대가 아내가 되었다(논개—게야무라
로쿠스케는 그를 끌어안고 남강에 뛰어들었다).

**위키데이터·인포박스는 그러지 않는다** — 거기서 온 1,057건은 혼인 칸에 적힌
것이라 믿을 만하다. 그래서 이 표가 묻는 것은 **추출이 낸 것뿐**이다
(`UNTRUSTED`).

## 판정은 표가 한다 (`data/spouses.tsv`)

    인물 id<TAB>인물 id<TAB>판정<TAB>근거

판정은 셋이다.

- **부부** — 정말 혼인이다. 엣지를 그대로 둔다 (실측 40 중 10: 삼취로 맞은
  고판례, 정실 부인 송씨, 후처 논개, 둘째 부인 정난정…). 첩·후처·계배도
  혼인이다 — 한 사람만 배우자라고 정하는 것은 우리가 할 일이 아니다.
- **관련** — 두 사람 사이는 참인데 **혼인이 아니다** (실측 29). 사위·장인·
  처남·형수·사돈·외삼촌 같은 인척이 스물, 벗·동지·추천·국문·피살이 아홉.
  `related_to` 로 **낮춘다** — 지우지 않는다. §1-6 에서 배운 것이다: '참여가
  아니다'를 '관계가 없다'로 읽어 지웠더니 114 중 43 이 참인 관계였다. 근거
  칸의 문장이 화면에 그 관계의 근거로 뜨므로 사위인지 벗인지는 거기서 읽힌다.
- **삭제** — 엣지 자체가 거짓이다 (실측 1: 송병준과 '홍씨'. 남의 첩을 어머니라
  불렀다는 문장에서 성씨 한 자를 사람으로 세운 줄이다).

**더 정확한 타입이 있는 것은 여기서 정하지 않는다.** 이수형은 이세좌의
아들이라 `child_of` 가 맞지만, 이 표가 답하는 물음은 '혼인인가' 하나다.
`related_to` 로 낮춰 두면 근거 구절이 그대로 남아 `untangle` 이 뜻 있는
타입으로 갈라 갈 수 있다 — 그것이 그 명령이 하는 일이다.

고친 값은 편집 계층(`overrides`)에 남아 재수집이 되돌리지 못한다. 원본과
파생본에 한 번씩 돌린다:

    uv run histgraph spouses                      # 판정이 없는 후보를 센다
    uv run histgraph spouses --apply
    uv run histgraph --db data/korea.sqlite spouses --apply

**표에 없는 후보가 남으면 종료 코드 1.** 추출을 다시 돌려 새 `spouse_of` 가
들어오면 여기서 묻는다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import overrides as ov
from .store import GraphStore

# 혼인을 스스로 말하지 못하는 출처. 위키데이터(P26)와 인포박스의 배우자 칸은
# 혼인이라고 적힌 자리라 묻지 않는다 — 산문만 묻는다.
UNTRUSTED = ("extract",)

VERDICTS = ("부부", "관련", "삭제")

TABLE_ORIGIN = "spouses"
SOURCE_MARK = "spouses"

TABLE = Path("data/spouses.tsv")


class SpousesTableError(ValueError):
    pass


@dataclass(frozen=True)
class TableRow:
    a: str
    b: str
    verdict: str
    note: str


@dataclass
class TableReport:
    kept: int = 0       # 부부 — 그대로 둔 것
    demoted: int = 0    # 관련 — 낮춘 것
    deleted: int = 0    # 삭제 — 지운 것
    missing: int = 0    # 이 그래프에 두 노드가 다 있지는 않은 줄 (파생본이 뺀 것)


def candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """산문 추출이 낸 `spouse_of`. 이 표가 묻는 것은 이것뿐이다."""
    marks = ",".join("?" * len(UNTRUSTED))
    return conn.execute(
        f"""SELECT e.src, e.dst, e.props, a.label AS a_label, b.label AS b_label
              FROM edges e
              JOIN nodes a ON a.id = e.src
              JOIN nodes b ON b.id = e.dst
             WHERE e.type = 'spouse_of' AND e.source IN ({marks})
             ORDER BY a.label, b.label""",
        UNTRUSTED,
    ).fetchall()


def load_table(path: Path = TABLE) -> list[TableRow]:
    rows: list[TableRow] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 4 or not all(parts[:4]):
            raise SpousesTableError(
                f"{path}:{lineno} 인물 id·인물 id·판정·근거 네 칸입니다: {raw!r}")
        a, b, verdict, note = parts[:4]
        if verdict not in VERDICTS:
            raise SpousesTableError(
                f"{path}:{lineno} 판정은 {'/'.join(VERDICTS)} 중 하나: {verdict!r}")
        if (a, b) in seen:
            raise SpousesTableError(f"{path}:{lineno} 같은 쌍이 두 번 적혔습니다: {raw!r}")
        seen.add((a, b))
        rows.append(TableRow(a, b, verdict, note))
    return rows


def unjudged(conn: sqlite3.Connection, table: list[TableRow]) -> list[sqlite3.Row]:
    """표에 판정이 없는 후보. 남으면 관문이 묻는다."""
    judged = {(r.a, r.b) for r in table}
    return [c for c in candidates(conn) if (c["src"], c["dst"]) not in judged]


def _trusted_says_married(conn: sqlite3.Connection, a: str, b: str) -> str | None:
    """혼인이라고 적힌 자리(위키데이터·인포박스)가 같은 쌍을 잇고 있는가.

    있으면 '관련'·'삭제' 로 낮출 수 없다 — 편집 계층의 `deleted` 는 출처를
    가리지 않아서 믿을 만한 줄까지 같이 지운다. 사람이 다시 봐야 하는 자리다."""
    marks = ",".join("?" * len(UNTRUSTED))
    row = conn.execute(
        f"""SELECT group_concat(DISTINCT source) FROM edges
             WHERE type = 'spouse_of' AND source NOT IN ({marks})
               AND ((src = ? AND dst = ?) OR (src = ? AND dst = ?))""",
        (*UNTRUSTED, a, b, b, a),
    ).fetchone()
    return row[0] if row and row[0] else None


def _both_here(conn: sqlite3.Connection, a: str, b: str) -> bool:
    n, = conn.execute("SELECT COUNT(*) FROM nodes WHERE id IN (?,?)", (a, b)).fetchone()
    return n == 2


def apply_table(store: GraphStore, table: list[TableRow]) -> TableReport:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    c = store.conn
    rep = TableReport()
    for row in table:
        key = ov.edge_key(row.a, row.b, "spouse_of")
        if row.verdict == "부부":
            # 참이라고 판정했으니 지우지 않는다. 전에 낮췄던 것이 있으면 푼다.
            ov.forget(c, "edge", key, "deleted")
            rep.kept += 1
            continue

        trusted = _trusted_says_married(c, row.a, row.b)
        if trusted:
            raise SpousesTableError(
                f"{row.a} ~ {row.b}: {trusted} 도 혼인이라 적었는데 판정이 "
                f"'{row.verdict}' 입니다. 편집 계층은 출처를 가리지 않아 그 줄까지 "
                f"지웁니다 — 판정을 '부부' 로 고치거나 그쪽 자료를 먼저 보세요.")

        # 재수집이 되살려도 다시 낮춰지도록 편집 계층에 적는다. 노드가 없는
        # 그래프에도 적어 둔다 — 편집 계층은 **다시 들어올 때**를 위한 것이다.
        ov.record(c, "edge", key, "deleted", True, TABLE_ORIGIN, row.note)
        c.execute("DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'spouse_of'",
                  (row.a, row.b))

        if row.verdict == "삭제":
            rep.deleted += 1
            continue

        # '관련' 은 **낮추는** 것이지 지우는 것이 아니다. 근거 칸의 문장이
        # 화면에 그 관계의 근거로 뜬다 (§1-6).
        #
        # **두 노드가 다 있을 때만 세운다.** 파생본(`scope`)은 화면 묶음 밖의
        # 노드를 빼므로 표의 절반은 여기에 상대가 없다 — 그래도 세우면 어디에도
        # 안 닿는 엣지가 남고, 화면은 그 줄을 이름조차 못 찾는다 (실측 17건).
        if not _both_here(c, row.a, row.b):
            rep.missing += 1
            continue
        ov.forget(c, "edge", ov.edge_key(row.a, row.b, "related_to"), "deleted")
        c.execute(
            """INSERT INTO edges (src, dst, type, source, label, confidence, props)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(src, dst, type, source) DO UPDATE SET
                 label = excluded.label, props = excluded.props""",
            (row.a, row.b, "related_to", SOURCE_MARK, None, 0.8,
             json.dumps({"evidence": row.note, "was": "spouse_of"}, ensure_ascii=False)),
        )
        rep.demoted += 1
    return rep
