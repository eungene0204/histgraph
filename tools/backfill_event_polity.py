"""사건 노드에 정체(polity)를 채운다 — 시대 그래프가 사건을 놓치던 원인.

**발단.** 화면 연표에 경술국치가 없어서 따라가 보니, 전체 그래프에는
한일병합(wd:Q3277083)이 1910-08-29 로 정확히 들어와 있는데 조선 그래프에는
없었다. 같은 이유로 빠진 사건이 조선 연대(1392~1910) 안에만 94건이었다.

**원인.** `wikidata.fetch_events` 의 쿼리는 `?e wdt:P17 wd:{polity}` 로
정체를 **물어 놓고 답을 버리고** 있었다. 인물은 처음부터 `props.polity` 를
적어서 `scope.select_seeds` 가 그걸로 씨앗을 고르는데, 사건에는 그 칸이
비어 있어서 `props.seed_era`(위키백과 시드 목록)나 왕조 노드와의 직접
연결이 있는 사건만 살아남았다.

수집 코드는 고쳤지만(`fetch_events` 가 이제 `props.polity` 를 적는다) 이미
쌓인 노드는 그대로다. **다시 수집하면 안 된다** — `upsert_nodes` 가
`props = excluded.props` 로 통째로 덮어써서 `enrich`(kowiki_url)와
`promote`(merged_from)가 나중에 채운 값이 날아간다. 그래서 여기서는
`json_set` 으로 `$.polity` 한 칸만 채운다.

빠진 94건의 P17 실측:
    조선 73 · 대한제국 14 · 그밖 5(교황령 conclave 셋·일본 제국·청나라)
    · P17 없음 2

기본은 계획만 출력한다. 건수를 확인한 뒤 --apply 로 실행할 것.

사용:
  PYTHONPATH=src python3 tools/backfill_event_polity.py [--apply] [DB ...]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.http import Fetcher  # noqa: E402
from histgraph.sources.wikidata import POLITIES, _qid, _query, _val  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
CHUNK = 120


def fetch_polities(qids: list[str]) -> dict[str, list[str]]:
    """QID -> 그 사건의 P17 라벨들. 우리가 아는 정체만 남긴다.

    한 사건에 정체가 둘 붙는 일이 흔하다 — 한일병합의 P17 은 대한제국과
    일본 제국 둘이다. 우리 표(POLITIES)에 있는 것만 걸러 담는다."""
    fetcher = Fetcher(CACHE, min_interval=1.5)
    known = set(POLITIES)
    out: dict[str, list[str]] = {}
    for i in range(0, len(qids), CHUNK):
        values = " ".join(f"wd:{q}" for q in qids[i : i + CHUNK])
        rows = _query(
            fetcher,
            f"""SELECT ?e ?c WHERE {{
                  VALUES ?e {{ {values} }}
                  ?e wdt:P17 ?c .
                }}""",
        )
        for r in rows:
            e, c = _val(r, "e"), _val(r, "c")
            if not (e and c):
                continue
            cq = _qid(c)
            if cq in known:
                out.setdefault(_qid(e), []).append(POLITIES[cq])
        print(f"  {min(i + CHUNK, len(qids)):>5}/{len(qids)} 조회")
    return out


def run(db: Path, apply: bool) -> None:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in conn.execute(
            """SELECT id, label FROM nodes
                WHERE type='event' AND id LIKE 'wd:%'
                  AND json_extract(props,'$.polity') IS NULL"""
        )
    ]
    print(f"\n=== {db.name} — 정체 칸이 빈 사건 {len(rows):,}개 ===")
    if not rows:
        return

    found = fetch_polities([r["id"][len("wd:") :] for r in rows])

    plan: list[tuple[str, str, str]] = []
    for r in rows:
        names = found.get(r["id"][len("wd:") :])
        if not names:
            continue
        # 여럿이면 우리 표의 순서(고구려…대한민국)를 따라 **가장 이른**
        # 정체로 적는다. 한일병합은 대한제국·일본 제국 둘인데 일본 제국은
        # 우리 표에 없으므로 대한제국 하나만 남는다.
        order = list(POLITIES.values())
        best = min(names, key=order.index)
        plan.append((r["id"], r["label"], best))

    from collections import Counter

    print(f"  채울 것 {len(plan):,}개 / {len(rows):,}개")
    for name, n in Counter(p[2] for p in plan).most_common():
        print(f"    {name:10} {n:>5}")
    for nid, label, name in plan[:12]:
        print(f"      {label[:28]:30} → {name}")

    if not apply:
        print("\n  (계획만 출력했습니다. 실제로 쓰려면 --apply)")
        return

    for nid, _, name in plan:
        conn.execute(
            "UPDATE nodes SET props = json_set(props, '$.polity', ?) WHERE id = ?",
            (name, nid),
        )
    conn.commit()
    print(f"\n  {len(plan):,}개 기록했습니다.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    dbs = [Path(a) for a in args] or [
        ROOT / "data" / "histgraph.sqlite",
        ROOT / "data" / "joseon.sqlite",
    ]
    for db in dbs:
        if db.exists():
            run(db, apply)
        else:
            print(f"  건너뜀 (없음): {db}")
