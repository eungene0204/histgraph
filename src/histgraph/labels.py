"""한국어 라벨 덮어쓰기 — 화면에 영어로 뜨는 노드를 한글로 바꾼다.

**발단.** 조선 그래프에서 '왕자의 난'을 따라가면 `Sayuksin assassination
plot` 이 나온다. 한국사 그래프인데 영어 이름이 붙어 있다.

**원인.** Wikidata 수집 쿼리는 라벨을 `"ko,en"` 으로 물어본다. 한국어
라벨이 없으면 영어가 오고, 그게 그대로 노드 이름이 된다. 전체 그래프에
1,490개, 조선 그래프에 32개가 그렇게 들어와 있었다.

**다시 수집해도 안 고쳐진다.** 영어로 남은 1,480개(wd 소스)를 상대로
`rdfs:label(ko)` · `skos:altLabel(ko)` · 한국어 위키백과 사이트링크를 전부
다시 물어봤더니, 새로 한글 이름을 얻을 수 있는 건 **2개**뿐이었다
(2026-09-03 실측). 나머지는 Wikidata 에 한국어 이름이 아예 없다. 그래서
이름을 손으로 적은 표(`data/ko_labels.tsv`)를 두고 그걸 덮어쓴다.

**한 번 쓰고 끝나는 게 아니다.** `upsert_nodes` 는 `label = excluded.label`
로 라벨을 통째로 덮어쓰므로, 다시 수집하면 영어로 되돌아간다. 이 단계는
수집·scope 뒤에 다시 돌리는 걸 전제로 만들었다 — 같은 표를 몇 번 적용해도
결과가 같다(멱등).

**옛 라벨은 버리지 않는다.** 영어 이름을 별칭 표에 넣는다. 화면 검색이
별칭을 보므로 `Sayuksin` 으로도 계속 찾을 수 있어야 한다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

HANGUL = re.compile(r"[가-힣]")
QID_RE = re.compile(r"^Q\d+$")


class LabelTableError(ValueError):
    """표가 깨졌다 — 조용히 넘어가면 이름이 반쯤 바뀐 그래프가 남는다."""


@dataclass
class Override:
    qid: str
    label: str
    note: str = ""

    @property
    def node_id(self) -> str:
        return f"wd:{self.qid}"


@dataclass
class RelabelReport:
    applied: list[tuple[str, str, str]] = field(default_factory=list)   # (id, 옛, 새)
    already: int = 0
    absent: list[str] = field(default_factory=list)
    # 바꾼 이름이 다른 노드의 이름과 같아진 경우 — 같은 인물이 두 노드로
    # 들어와 있다는 신호다. 여기서 합치지는 않는다(합치는 규칙은 promote 쪽).
    collisions: list[tuple[str, str, str]] = field(default_factory=list)  # (id, 라벨, 상대)
    remaining: list[tuple[str, str, str]] = field(default_factory=list)   # (id, 타입, 라벨)


def load_table(path: Path) -> list[Override]:
    """`QID<TAB>한국어<TAB>근거` 표를 읽는다.

    근거 칸은 사람이 읽는 칸이라 비어 있어도 되지만, 라벨에 한글이 없으면
    거른다 — 영어를 영어로 덮어써 봐야 화면은 그대로다."""
    rows: list[Override] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 2 or not parts[1].strip():
            raise LabelTableError(f"{path}:{lineno} 탭으로 나뉜 두 칸이 필요합니다: {raw!r}")
        qid, label = parts[0].strip(), parts[1].strip()
        note = parts[2].strip() if len(parts) > 2 else ""
        if not QID_RE.match(qid):
            raise LabelTableError(f"{path}:{lineno} QID 형식이 아닙니다: {qid!r}")
        if not HANGUL.search(label):
            raise LabelTableError(f"{path}:{lineno} 한글이 없는 라벨: {label!r}")
        if qid in seen:
            raise LabelTableError(f"{path}:{lineno} 같은 QID 가 두 번: {qid}")
        seen.add(qid)
        rows.append(Override(qid, label, note))
    return rows


def english_nodes(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """아직 한글이 한 글자도 없는 노드 — 표에 더 적을 후보."""
    return [
        (r[0], r[1], r[2])
        for r in conn.execute("SELECT id, type, label FROM nodes ORDER BY type, label")
        if not HANGUL.search(r[2])
    ]


def apply_overrides(
    conn: sqlite3.Connection, table: list[Override], *, dry_run: bool = False
) -> RelabelReport:
    """표를 그래프에 적용한다. 여러 번 돌려도 결과가 같다."""
    report = RelabelReport()
    for ov in table:
        row = conn.execute(
            "SELECT label FROM nodes WHERE id = ?", (ov.node_id,)
        ).fetchone()
        if row is None:
            report.absent.append(ov.qid)
            continue
        old = row[0]
        if old == ov.label:
            report.already += 1
            continue

        twin = conn.execute(
            "SELECT id FROM nodes WHERE label = ? AND id <> ? LIMIT 1",
            (ov.label, ov.node_id),
        ).fetchone()
        if twin:
            report.collisions.append((ov.node_id, ov.label, twin[0]))

        report.applied.append((ov.node_id, old, ov.label))
        if dry_run:
            continue
        conn.execute(
            "UPDATE nodes SET label = ?, updated_at = datetime('now') WHERE id = ?",
            (ov.label, ov.node_id),
        )
        # 옛 이름을 별칭으로 남긴다. QID 가 라벨이던 노드는 남길 게 없다.
        if old and old != ov.qid:
            conn.execute(
                "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?, ?)",
                (ov.node_id, old),
            )
    if not dry_run:
        conn.commit()
    fixed = {node_id for node_id, _, _ in report.applied}
    # dry-run 에서도 '적용 뒤에 남는 것'을 보여준다 — 미리보기가 실제와
    # 다른 수를 찍으면 그 수를 믿을 수 없다.
    report.remaining = [n for n in english_nodes(conn) if n[0] not in fixed]
    return report
