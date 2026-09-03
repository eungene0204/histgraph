"""근거 구절 전수 점검 — 잘린 인용을 문장 단위로 되살리고, 참여를 부인하는
문장에서 나온 참여 엣지를 지운다.

실측 발단: 화면에 "이완용은 3·1 운동에 참여했다"가 떴다. 근거는
"그 역시 민족 지도자들로부터 동참을 요청받았으나" 였는데, 원문은
그 뒤로 "오히려 … 탄압 필요성과 그 방안에 관한 편지를 수차례 보내기도
했다"로 이어진다. 모델이 역접 어미 `-으나` 에서 인용을 끊었고, 근거 검증은
앞 25자가 원문에 있는지만 보므로 **진짜 문장의 앞토막은 언제나 통과했다.**

하는 일 (순서 중요 — 문장을 되살려야 뒤집는 절이 보인다):
  1. 근거 복원: 인용을 원문에서 찾아 문장 끝까지 늘린다
  2. 참여 부인 검사: 복원된 문장과 **그 문단**으로 판정해 위반 삭제
  판정 함수는 extract.py 의 것을 그대로 쓴다 — 두 벌로 두면 반드시 갈라진다.

기본은 계획만 출력한다. 목록을 눈으로 확인한 뒤 --apply 로 실행할 것.

사용:
  uv run tools/sweep_evidence.py [--apply] [--verbose] [DB ...]
  (DB 를 안 주면 data/histgraph.sqlite 와 data/joseon.sqlite 둘 다)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.extract import (  # noqa: E402
    complete_evidence,
    locate_evidence,
    paragraph_span,
    participation_denied,
)

ROOT = Path(__file__).resolve().parents[1]


def sweep(path: Path, apply: bool, verbose: bool) -> None:
    if not path.exists():
        print(f"건너뜀 (없음): {path}")
        return
    print(f"\n=== {path} ===")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row

    docs: dict[str, str] = {}

    def doc_text(node_id: str) -> str:
        if node_id not in docs:
            row = db.execute(
                "SELECT description FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            docs[node_id] = (row["description"] if row else None) or ""
        return docs[node_id]

    edges = db.execute("""
        SELECT e.rowid, e.type, e.props, s.label AS slabel, d.label AS dlabel
          FROM edges e
          JOIN nodes s ON s.id = e.src
          JOIN nodes d ON d.id = e.dst
         WHERE e.source = 'extract'
    """).fetchall()

    repairs: list[tuple[int, str]] = []
    doomed: list[tuple[int, str, str, str]] = []
    lost = 0

    for e in edges:
        props = json.loads(e["props"])
        quote = props.get("evidence") or ""
        text = doc_text(props.get("extracted_from") or "")
        if not text:
            lost += 1
            continue
        span = locate_evidence(quote, text)
        if span is None:
            # 추출 당시엔 조각 본문으로 검증됐다. 지금 못 찾는다고 해서
            # 근거가 없었다는 뜻은 아니므로 지우지 않고 세기만 한다.
            lost += 1
            continue

        full = complete_evidence(quote, text) or quote
        left, right = paragraph_span(text, *span)
        if participation_denied(e["type"], e["dlabel"], full, text[left:right]):
            doomed.append((e["rowid"], e["slabel"], e["dlabel"], full))
            continue
        if full != " ".join(quote.split()):
            props["evidence"] = full
            repairs.append((e["rowid"], json.dumps(props, ensure_ascii=False)))

    for _, s, d, ev in doomed:
        print(f"  삭제: {s} --참여--> {d}")
        print(f"        {ev[:150]}")
    if verbose:
        for rid, raw in repairs:
            print(f"  복원: {json.loads(raw)['evidence'][:150]}")

    print(f"추출 엣지 {len(edges):,}건 · 근거복원 {len(repairs):,}건"
          f" · 참여부인 삭제 {len(doomed)}건 · 원문에서 못 찾음 {lost:,}건")

    if apply:
        db.executemany("UPDATE edges SET props=? WHERE rowid=?",
                       [(raw, rid) for rid, raw in repairs])
        db.executemany("DELETE FROM edges WHERE rowid=?",
                       [(rid,) for rid, *_ in doomed])
        db.commit()
        print("적용 완료")
    db.close()


def main() -> int:
    flags = {"--apply", "--verbose"}
    args = [a for a in sys.argv[1:] if a not in flags]
    paths = ([Path(a) for a in args] if args
             else [ROOT / "data" / "histgraph.sqlite",
                   ROOT / "data" / "joseon.sqlite"])
    for p in paths:
        sweep(p, "--apply" in sys.argv[1:], "--verbose" in sys.argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
