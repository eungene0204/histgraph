"""추출 품질 점검 — 소량으로 돌려보고 전체 실행 여부를 판단한다.

측정 항목:
  1. 관계 유형 분포 — participated_in 이 실제로 나오는가 (이게 목적이다)
  2. 가제티어 연결률 — 기존 노드에 붙는가, 아니면 고아(ex:)를 만드는가
  3. 근거 충실도 — evidence 가 원문에 실제로 있는가 (환각 탐지)
  4. 처리 속도 — 971건 전체에 얼마나 걸릴지 추정

사용:
  PYTHONPATH=src python3 tools/check_extraction.py [문서수]
"""

from __future__ import annotations

import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.backends import build_backend  # noqa: E402
from histgraph.extract import (  # noqa: E402
    build_gazetteer,
    extract_one,
    load_documents,
    to_graph,
)
from histgraph.store import GraphStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DB = Path(__file__).resolve().parents[1] / "data" / "histgraph.sqlite"


def main() -> int:
    n_docs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    backend_kind = sys.argv[2] if len(sys.argv) > 2 else "mlx"

    store = GraphStore(DB)
    gazetteer = build_gazetteer(store)
    docs = load_documents(store, limit=n_docs, min_score=2.0)
    backend = build_backend(backend_kind)

    print(f"\n{'='*60}")
    print(f"백엔드 {backend.name} · 문서 {n_docs}건 → 조각 {len(docs)}개")
    print(f"{'='*60}\n")

    all_rels: list[dict] = []
    per_doc: list[tuple[str, int, float]] = []

    for i, doc in enumerate(docs, 1):
        part = f" [{doc.chunk + 1}/{doc.total_chunks}]" if doc.total_chunks > 1 else ""
        t0 = time.monotonic()
        rels = extract_one(backend, doc, gazetteer)
        dt = time.monotonic() - t0
        per_doc.append((doc.label, len(rels), dt))
        all_rels.extend((r, doc) for r in rels)
        print(f"  {i}/{len(docs)} {doc.label[:26]:28}{part} → {len(rels):>3}건  {dt:>5.1f}초")

    if not all_rels:
        print("\n관계가 하나도 추출되지 않았습니다. 프롬프트나 모델을 점검하세요.")
        store.close()
        return 1

    print(f"\n{'─'*60}\n1) 관계 유형 분포\n{'─'*60}")
    kinds = Counter(r["relation"] for r, _ in all_rels)
    for k, v in kinds.most_common():
        bar = "█" * min(v, 40)
        mark = "  ← 목표" if k == "participated_in" else ""
        print(f"  {k:18} {v:>4}  {bar}{mark}")

    print(f"\n{'─'*60}\n2) 가제티어 연결률 (기존 노드에 붙는가)\n{'─'*60}")
    nodes, edges = [], []
    for r, doc in all_rels:
        n, e = to_graph([r], doc.node_id, store)
        nodes.extend(n)
        edges.extend(e)
    endpoints = [e.src for e in edges] + [e.dst for e in edges]
    orphan = sum(1 for x in endpoints if x.startswith("ex:"))
    linked = len(endpoints) - orphan
    if endpoints:
        print(f"  기존 노드 연결 {linked:>4} ({linked/len(endpoints)*100:.0f}%)")
        print(f"  신규 고아 노드 {orphan:>4} ({orphan/len(endpoints)*100:.0f}%)")
        print("  ※ 고아 비율이 높으면 가제티어를 키우거나 프롬프트를 조여야 한다")

    print(f"\n{'─'*60}\n3) 근거 충실도 (evidence 가 원문에 실제로 있는가)\n{'─'*60}")
    hit = miss = 0
    for r, doc in all_rels:
        ev = (r.get("evidence") or "").strip()
        # 공백 차이는 무시하고 비교한다
        if ev and "".join(ev.split())[:30] in "".join(doc.text.split()):
            hit += 1
        else:
            miss += 1
            if miss <= 3:
                print(f"  ⚠ 원문에 없음: {ev[:70]}")
    total = hit + miss
    print(f"  원문 일치 {hit}/{total} ({hit/total*100:.0f}%)")
    if miss / total > 0.2:
        print("  ※ 20% 넘게 불일치 — 모델이 근거를 지어내고 있다")

    print(f"\n{'─'*60}\n4) 속도 추정\n{'─'*60}")
    avg = sum(d for _, _, d in per_doc) / len(per_doc)
    total_docs = len(load_documents(store, min_score=2.0))
    print(f"  조각당 평균 {avg:.1f}초")
    print(f"  전체 {total_docs}조각 → 약 {avg * total_docs / 60:.0f}분 "
          f"({avg * total_docs / 3600:.1f}시간)")

    print(f"\n{'─'*60}\n샘플 관계\n{'─'*60}")
    for r, _ in all_rels[:8]:
        print(f"  {r['subject'][:16]:18} --[{r['relation']:16}]--> {r['object'][:20]}")
        print(f"     {r.get('confidence','?'):9} | {str(r.get('evidence',''))[:58]}")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
