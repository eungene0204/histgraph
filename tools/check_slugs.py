#!/usr/bin/env python3
"""배포될 DB 의 장들이 **제 주소를 갖고 있는지** 센다 — push 전 훅과 CI 가 부른다.

주소가 없으면 아무것도 깨지지 않는다. 장은 옛 주소(`/n/<id>`)로 그대로
열리고 화면도 멀쩡하다 — **사이트맵만 조용히 비어 간다.** 검색에서 사라지는
것은 그 다음 주다. 가장 늦게 알아채는 종류의 실패라 기계에게 맡긴다.

재는 것은 둘이다.

1. **색인에 올릴 장이 주소를 받았는가.** 문턱(`pages.indexable`)을 넘는
   장은 사이트맵에 실려야 하고, 그러려면 주소가 있어야 한다.
2. **주소에 한글 아닌 글이 없는가** (CLAUDE.md §1). 라벨이 영어면 주소도
   영어가 된다 — `check_korean.py` 가 라벨을 재고 여기서 주소를 잰다.

어느 DB 를 재는지는 여기 적지 않는다. 배포 진입점(api/index.py)이 여는
파일을 그대로 연다 (tools/check_korean.py 의 같은 교훈).

    python3 tools/check_slugs.py                  # 배포될 DB
    python3 tools/check_slugs.py data/korea.sqlite

표준 라이브러리만 쓴다. CI 는 아무것도 설치하지 않는다.
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histgraph import pages  # noqa: E402

LATIN = re.compile(r"[A-Za-z]{2,}")


def deploy_db() -> Path:
    """배포 진입점이 여는 DB. 진입점을 실제로 읽어야 이름을 따라간다."""
    spec = importlib.util.spec_from_file_location("entry", ROOT / "api" / "index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Path(module.DB)


def main(argv: list[str]) -> int:
    db = Path(argv[1]) if len(argv) > 1 else deploy_db()
    if not db.exists():
        print(f"  ✗ DB 가 없습니다: {db}")
        return 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        have = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='slugs'"
        ).fetchone()
        if not have:
            print(f"  ✗ {db.name} 에 주소 표가 없습니다 —"
                  " `uv run histgraph --db {db} slugs` 를 돌리세요")
            return 1
        # 색인에 올릴 장(요약 120자 + 관계 3건)이 주소를 받았는가.
        rows = conn.execute(
            """SELECT n.id, n.label, n.description, s.slug,
                      (SELECT COUNT(*) FROM edges e
                        WHERE e.src = n.id OR e.dst = n.id) AS degree
                 FROM nodes n
                 LEFT JOIN slugs s ON s.node_id = n.id AND s.current = 1
                WHERE COALESCE(n.description,'') <> ''
                  AND LENGTH(n.description) >= ?""",
            (pages.MIN_SUMMARY,),
        ).fetchall()
        indexable = [r for r in rows
                     if pages.indexable(pages.summarize(r["description"]), r["degree"])]
        missing = [r for r in indexable if not r["slug"]]
        # 주소의 로마자는 **이름에 있던 것만** 봐준다. 'YH 사건'·'IMF 구제금융'
        # 처럼 라벨 자체가 로마자 약칭을 품는 것은 §1 이 이미 통과시킨
        # 이름이고(한글이 있다), 주소가 그것을 지어낸 것이 아니다. 지어낸
        # 글자가 섞이면 여기서 잡힌다 — id 해시를 붙이던 때 45개가 걸렸다.
        foreign = []
        for r in conn.execute(
                """SELECT s.segment, s.slug, s.node_id, n.label FROM slugs s
                     LEFT JOIN nodes n ON n.id = s.node_id WHERE s.current = 1"""):
            label = (r["label"] or "").lower()
            made_up = [w for w in LATIN.findall(r["slug"]) if w not in label]
            if made_up or LATIN.search(r["segment"]):
                foreign.append(r)
        total = conn.execute("SELECT COUNT(*) FROM slugs WHERE current = 1").fetchone()[0]
    finally:
        conn.close()

    if missing:
        print(f"  ✗ 색인에 올릴 장 {len(indexable):,}개 중 {len(missing):,}개가"
              f" 주소를 못 받았습니다 — 그만큼 사이트맵에서 빠집니다")
        for r in missing[:20]:
            print(f"    {r['id']:>28}  {r['label'][:40]}")
        print(f"\n  `uv run histgraph --db {db} slugs --inherit data/histgraph.sqlite`")
        return 1
    if foreign:
        print(f"  ✗ 주소에 한글 아닌 글이 든 장 {len(foreign):,}개 (CLAUDE.md §1)")
        for r in foreign[:20]:
            print(f"    /{r['segment']}/{r['slug']}  ({r['node_id']})")
        return 1
    print(f"  ✓ 주소 {total:,}개 · 색인에 올릴 장 {len(indexable):,}개가 모두 제 주소로 선다"
          f" — {db.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
