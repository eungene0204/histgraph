#!/usr/bin/env python3
"""배포될 DB 에 한글 아닌 글이 있으면 실패한다 — push 전 훅과 CI 가 부른다.

**세 번 반복된 일을 기계에 맡기는 자리다.** 화면에 영어 이름·설명이 뜬 것을
사용자가 2026-09-03 에 두 번, 09-04 에 한 번 더 지적했다. 세 번 다 표와
사전은 있었고 돌리는 걸 잊었거나 파생본에 안 돌렸다. 그러니 "돌려라"를
문서에 한 줄 더 적는 것으로는 안 되고, **돌렸는지를 push 마다 묻는다.**

어느 DB 를 재는지는 여기 적지 않는다. 배포 진입점(api/index.py)이 여는
파일을 그대로 연다 — 이름을 박아 두면 진입점이 옮겨 갈 때 검사가
헛것을 지킨다 (tools/hooks/pre-push 의 같은 교훈). 다른 파일을 재려면
경로를 인자로 준다:

    python3 tools/check_korean.py                  # 배포될 DB
    python3 tools/check_korean.py data/joseon.sqlite

표준 라이브러리만 쓴다. CI 는 아무것도 설치하지 않는다.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from histgraph.labels import foreign_text  # noqa: E402


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
    try:
        found = foreign_text(conn)
        total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    finally:
        conn.close()

    if not found:
        print(f"  ✓ 한글 아닌 글 없음 — {db.name} · 노드 {total:,}")
        return 0

    print(f"  ✗ {db.name} 에 화면에 한글 아닌 글로 뜨는 노드 {len(found):,}건"
          f" (노드 {total:,} 중)")
    for nid, ntype, column, text in found[:30]:
        print(f"    {ntype:<7} {nid:>16}  {column}: {text[:60]!r}")
    if len(found) > 30:
        print(f"    … 그 밖 {len(found) - 30:,}건")
    print("\n  이름은 data/ko_labels.tsv 에 적고 `histgraph --db <파일> relabel`,"
          "\n  설명은 `histgraph --db <파일> redescribe` (사전에 없으면 비웁니다).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
