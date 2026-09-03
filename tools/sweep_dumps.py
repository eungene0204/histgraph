"""가제티어 덤프 전수 조사 — 한 문장이 낳은 엣지 묶음 중 근거가 대상을
지목하지 않는 것을 정리한다.

실측 발단: 황진이의 시조 5편이 상세 패널에 **같은 근거 문장**으로 나와서
들여다보니, 그건 정상 열거문("시조 작품으로는 A, B, C 등이 있다")이었다.
그런데 같은 '근거 공유' 묶음을 크기순으로 훑다가 진짜 오염이 나왔다 —
`무오사화 --from_period-->` 39건이 문서 첫 문장 하나를 근거로 달려 있고
대상 39개가 전부 가제티어 period 상위 150개였다 (무오사화는 1498년인데
조선 선조 17년(1584), 조선 숙종 9년(1683)…). 모델이 원문을 읽는 대신 보기
목록을 쏟아낸 것이다.

**낱개 검사로는 못 잡는다.** 근거 문장은 원문에 실제로 있고, 한 건만 놓고
보면 멀쩡하다. 묶음 단위로 지목률을 봐야 갈린다 — 정상 열거문은 88~100%,
덤프는 0~20%.

판정은 extract.py 의 `gazetteer_dump` 를 그대로 쓴다. 두 벌로 두면 갈라진다.

기본은 계획만 출력한다. 건수를 확인한 뒤 --apply 로 실행할 것.

사용:
  uv run tools/sweep_dumps.py [--apply] [DB ...]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.extract import (  # noqa: E402
    DUMP_MIN_GROUP,
    DUMP_UNNAMED_RATIO,
    evidence_names_target,
    name_variants,
)

ROOT = Path(__file__).resolve().parents[1]


def sweep(db_path: Path, apply: bool) -> None:
    print(f"\n=== {db_path} {'(적용)' if apply else '(계획만)'} ===")
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    rows = db.execute("""
        SELECT e.rowid, e.src, e.dst, e.type, e.props,
               s.label AS slabel, d.label AS dlabel
          FROM edges e
          JOIN nodes s ON s.id = e.src
          JOIN nodes d ON d.id = e.dst
         WHERE e.source = 'extract'
    """).fetchall()

    # 저장된 엣지에는 모델이 쓴 이름 대신 해소된 노드가 들어 있으므로
    # 라벨과 별칭으로 지목 여부를 본다 (추출 시점의 `object` 문자열과
    # 같은 것을 보게 된다 — 해소가 라벨·별칭 일치로 이뤄지기 때문).
    def names_of(node_id: str, label: str) -> set[str]:
        return name_variants(label) | {
            r["alias"] for r in
            db.execute("SELECT alias FROM aliases WHERE node_id = ?", (node_id,))
        }

    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        if evidence := json.loads(r["props"]).get("evidence", ""):
            groups[(r["src"], r["type"], evidence)].append(r)

    doomed: list[sqlite3.Row] = []
    for (_, _, evidence), members in groups.items():
        if len(members) < DUMP_MIN_GROUP:
            continue
        unnamed = [m for m in members
                   if not evidence_names_target(evidence,
                                                names_of(m["dst"], m["dlabel"]))]
        if len(unnamed) <= len(members) * DUMP_UNNAMED_RATIO:
            continue
        doomed.extend(unnamed)
        print(f"  {members[0]['slabel']} --{members[0]['type']}--> "
              f"{len(members)}건 중 {len(unnamed)}건 삭제 "
              f"(지목 {len(members) - len(unnamed)}건)")
        print(f"     근거: {evidence[:70]}")
        print(f"     대상: {', '.join(m['dlabel'] for m in unnamed[:8])}"
              f"{' …' if len(unnamed) > 8 else ''}")

    print(f"추출 엣지 {len(rows)}건 · 근거 공유 묶음 "
          f"{sum(1 for v in groups.values() if len(v) > 1)}개 "
          f"· 삭제 대상 {len(doomed)}건")

    if apply:
        db.executemany("DELETE FROM edges WHERE rowid=?",
                       [(r["rowid"],) for r in doomed])
        db.commit()
        print("적용 완료")
    db.close()


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv[1:]
    paths = ([Path(a) for a in args] if args
             else [ROOT / "data" / "histgraph.sqlite",
                   ROOT / "data" / "joseon.sqlite"])
    for p in paths:
        sweep(p, apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
