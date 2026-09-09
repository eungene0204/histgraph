"""임기 표 — 대통령의 띠는 취임한 날에서 시작한다.

2026-09-09 사용자 결정: "대통령 타임라인을 대통령 취임날을 기준으로
만들어줘".

**왜 표가 필요한가.** 재위·재임 띠의 날짜는 Wikidata 의 P39 한정어에서
온다 (`reigns`). 임금은 그것으로 충분하지만 **대통령은 아니다** — 같은
자리(대한민국 대통령)에 문장이 여럿이고 그중에 취임한 날이 아닌 것이
섞여 있다. 실측 (2026-09-09):

    박정희  1962-03-24  윤보선이 사임한 뒤 **권한대행**을 맡은 날
                        (취임은 1963-12-17 제5대)
    최규하  1979-10-26  박정희 피살로 **권한대행**을 맡은 날
                        (취임은 1979-12-21 제10대)
    전두환  1980-08-27  통일주체국민회의가 **뽑은** 날
                        (취임은 1980-09-01 제11대)

`fetch_reigns` 는 같은 (인물, 자리)의 문장을 가장 이른 시작과 가장 늦은
끝으로 모으므로, 권한대행 문장이 하나라도 있으면 그것이 시작이 된다.
`drop_nested_terms` 도 못 잡는다 — 그건 **남의 임기 한가운데서** 시작하는
임기를 빼는 규칙이고(황교안), 권한대행은 앞 사람이 물러난 **뒤에**
시작하기 때문이다. 문장에 붙은 P5102(서술의 성격) 한정어로 가를 수도
있지만, 그러면 이 표가 없어지는 대신 위키가 한정어를 지우는 날 조용히
틀린다. 그래서 **사람이 적고 표가 기계를 이긴다.**

**한 사람이 여러 대를 지내도 띠는 하나다.** 시작은 첫 취임일, 끝은 마지막
임기가 끝난 날이다 (이승만 1·2·3대, 박정희 5~9대, 전두환 11·12대). 대마다
가르지 않는 것은 사용자가 고른 것이다 — 사람이 시간을 '박정희 때'로 읽지
'제7대 때'로 읽지 않는다.

**권한대행은 띠가 아니다.** 허정·박충훈·황교안·한덕수가 앉았던 구간은
어느 대통령의 띠에도 들어가지 않는다. 그래서 띠 사이에 빈 데가 생기고,
그 빈 데가 참이다 — 1962-03-24~1963-12-16 에는 대통령이 없었다.

근거는 대통령기록관(pa.go.kr)의 취임식 기록이다. 표에 없는 대통령이
남으면 종료 코드 1 로 묻는다 — 새 대통령이 들어오면 한 줄을 적어야 한다.
적은 값은 편집 계층(`overrides`)에 남아 수집이 되돌리지 못하고, `reigns`
도 마지막에 이 표를 다시 씌운다 (안 씌우면 다음 `reigns` 가 Wikidata 값을
되돌려 놓는다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov

ORIGIN = "terms"
EDGE_TYPE = "held_position"
# 표가 지키는 자리의 종류 (`props.reign`). 임금은 대가 62 라 표로 적지
# 않는다 — 위키의 재위 값이 그쪽은 취임일과 다르지 않다.
GUARDED = ("president",)
_DATE = re.compile(r"^\d{3,4}(-\d{2}(-\d{2})?)?$")


class TermsTableError(ValueError):
    pass


@dataclass(frozen=True)
class Row:
    person: str
    seat: str
    start: str
    end: str
    note: str


@dataclass
class Report:
    changed: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    # (인물, 옛 시작, 새 시작, 옛 끝, 새 끝)
    kept: int = 0                                        # 표와 그래프가 이미 같은 것
    absent: list[Row] = field(default_factory=list)      # 이 그래프에 없는 줄
    missing: list[tuple[str, str]] = field(default_factory=list)  # (인물 id, 이름) 표에 없는 대통령


def load_table(path: Path) -> list[Row]:
    rows: list[Row] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 5 or not parts[0] or not parts[1] or not parts[2]:
            raise TermsTableError(
                f"{path}:{lineno} 인물·자리·취임일·퇴임일·근거 다섯 칸입니다 "
                f"(퇴임일은 비워도 됨): {raw!r}")
        row = Row(parts[0], parts[1], parts[2], parts[3], parts[4])
        for d in (row.start, row.end):
            if d and not _DATE.match(d):
                raise TermsTableError(f"{path}:{lineno} 날짜가 아닙니다: {d!r}")
        if not row.note:
            raise TermsTableError(f"{path}:{lineno} 근거가 비었습니다: {raw!r}")
        if row.end and row.end < row.start:
            raise TermsTableError(
                f"{path}:{lineno} 퇴임일이 취임일보다 앞섭니다: {raw!r}")
        key = (row.person, row.seat)
        if key in seen:
            raise TermsTableError(f"{path}:{lineno} 같은 사람이 두 번 적혔습니다: {raw!r}")
        seen.add(key)
        rows.append(row)
    return rows


def _guarded(conn) -> list[tuple[str, str, str]]:
    """표가 지켜야 할 (인물, 자리, 이름) — 지금 띠로 서 있는 임기."""
    marks = ",".join("?" * len(GUARDED))
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            f"""SELECT DISTINCT e.src, e.dst, n.label
                  FROM edges e JOIN nodes n ON n.id = e.src
                 WHERE e.type = ?
                   AND json_extract(e.props, '$.reign') IN ({marks})""",
            (EDGE_TYPE, *GUARDED),
        )
    ]


def apply(store, table: list[Row], dry_run: bool = False) -> Report:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    conn = store.conn
    rep = Report()
    in_table = {(r.person, r.seat) for r in table}

    for row in table:
        cur = conn.execute(
            """SELECT start_date, end_date FROM edges
                WHERE src = ? AND dst = ? AND type = ?""",
            (row.person, row.seat, EDGE_TYPE),
        ).fetchone()
        if cur is None:
            rep.absent.append(row)
            continue
        old_start, old_end = cur["start_date"] or "", cur["end_date"] or ""
        if (old_start, old_end) == (row.start, row.end):
            rep.kept += 1
            continue
        rep.changed.append((row.person, old_start, row.start, old_end, row.end))
        if dry_run:
            continue
        key = ov.edge_key(row.person, row.seat, EDGE_TYPE)
        ov.record(conn, "edge", key, "start_date", row.start, ORIGIN, row.note)
        # 재임 중이면 끝을 **비운다** — 옛 끝을 남기면 띠가 거기서 잘린다.
        ov.record(conn, "edge", key, "end_date", row.end or None, ORIGIN, row.note)
        conn.execute(
            """UPDATE edges SET start_date = ?, end_date = ?
                WHERE src = ? AND dst = ? AND type = ?""",
            (row.start, row.end or None, row.person, row.seat, EDGE_TYPE),
        )

    for person, seat, label in _guarded(conn):
        if (person, seat) not in in_table:
            rep.missing.append((person, label))
    if not dry_run:
        conn.commit()
    return rep
