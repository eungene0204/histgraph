"""참여(participated_in) 엣지 전수 조사 — 죽은 뒤의 사건에 '참여'한 오류 정리.

실측 발단: 황진이(1506~1567)가 병자호란(1636)에 참여했다고 나왔다. 근거
문장("임진왜란과 병자호란 등으로 인해 대부분 실전되었고")은 작품이
소실됐다는 뜻인데 모델이 참여로 읽었고, 근거검증·이름지목·연대검사가
모두 설계상 통과시켰다. 같은 유형을 전부 찾아 고친다.

하는 일 (두 단계, 순서 중요 — 날짜를 채워야 연대 검사가 보인다):
  1. 사건 노드 날짜 채움
     - wd: 사건인데 무연대인 것 → Wikidata API 에서 P580/P582/P585 조회
     - 라벨이 `… (YYYY년)` 인 사건 → 그 연도를 start_date 로
  2. 추출 participated_in 엣지 검사 → 위반 삭제
     - 연대 충돌: 참여자의 생애와 사건 연대가 겹치지 않는다
     - 소실 문형: 근거가 '그 사건 탓에 잃었다'는 문장이다
  판정 함수는 extract.py 의 것을 그대로 쓴다 — 두 벌로 두면 반드시 갈라진다.

기본은 계획만 출력한다. 건수를 확인한 뒤 --apply 로 실행할 것.

사용:
  PYTHONPATH=src python3 tools/sweep_participation.py [--apply] [DB ...]
  (DB 를 안 주면 data/histgraph.sqlite 와 data/joseon.sqlite 둘 다)
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.extract import (  # noqa: E402
    evidence_year,
    label_year,
    lifespan_conflict,
    loss_context,
)
from histgraph.sources.wikidata import _iso_date  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.wikidata.org/w/api.php"
UA = "histgraph/0.1 (https://github.com/eugene0204; graph cleanup)"


def wd_event_dates(qids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """QID -> (start, end). P580/P582 우선, 없으면 P585(시점)."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        url = API + "?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "claims", "format": "json",
        })
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            entities = json.load(resp).get("entities", {})
        for qid, ent in entities.items():
            claims = ent.get("claims", {})

            def first(prop: str) -> str | None:
                for st in claims.get(prop, []):
                    # '값 불명'(somevalue)은 datavalue 가 없다
                    raw = (st.get("mainsnak", {}).get("datavalue", {})
                           .get("value", {}))
                    if isinstance(raw, dict) and raw.get("time"):
                        # '+1636-12-09T…' → 부호를 벗기고 ISO 검사로 넘긴다.
                        # 연 단위 정밀도는 월·일이 00으로 온다 — SPARQL
                        # 인제스트 표기(01-01)에 맞춘다. 기원전 연도의
                        # 앞자리 0(-0057)을 건드리지 않게 끝에서만 바꾼다.
                        d = _iso_date(raw["time"].lstrip("+"))
                        return re.sub(r"-00(-00)?$", lambda m: m.group(0)
                                      .replace("00", "01"), d) if d else None
                return None

            start, end, point = first("P580"), first("P582"), first("P585")
            out[qid] = (start or point, end or point)
    return out


def sweep(db_path: Path, apply: bool) -> None:
    print(f"\n=== {db_path} {'(적용)' if apply else '(계획만)'} ===")
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    # --- 1. 사건 날짜 채움 -------------------------------------------------
    undated = db.execute("""
        SELECT id, label FROM nodes WHERE type='event'
         AND (start_date IS NULL OR start_date='')
         AND (end_date IS NULL OR end_date='')
    """).fetchall()

    # 라벨에도 연도가 없는 사건은 근거 문장이 마지막 단서다. `왕과 비 출연`
    # 은 라벨만 봐선 언제 일인지 알 수 없고, 근거의 `(KBS 1TV, 1998년~2000년
    # 배우:이광기)` 가 그것을 말해 준다.
    #
    # **이 연도는 판정에만 쓰고 DB 에 적지 않는다.** 정답을 아는 사건 57개로
    # 재보니 ±1년 안이 50개(88%)이고 신유박해를 1760년(정답 1801)으로 읽는
    # 식의 어긋남이 7개였다. 화면에 사건 연대로 뜰 값을 그 정확도로 적을 수는
    # 없다. 죽은 지 수백 년 뒤를 가리는 데에는 이 정확도로 충분하다.
    from_evidence: dict[str, str] = {}
    for r in db.execute("""
        SELECT e.dst, e.props FROM edges e JOIN nodes d ON d.id = e.dst
         WHERE e.source = 'extract' AND d.type = 'event'
           AND (d.start_date IS NULL OR d.start_date = '')
    """):
        year = evidence_year(json.loads(r["props"]).get("evidence", ""))
        if year and year < from_evidence.get(r["dst"], "9999"):
            from_evidence[r["dst"]] = year

    wd_targets = [r for r in undated if r["id"].startswith("wd:")]
    dates = wd_event_dates([r["id"][3:] for r in wd_targets]) if wd_targets else {}
    filled_wd = filled_label = 0
    for r in undated:
        if r["id"].startswith("wd:"):
            start, end = dates.get(r["id"][3:], (None, None))
            kind = "wikidata"
        else:
            start, end, kind = label_year(r["label"]), None, "라벨연도"
        if not start and not end:
            continue
        if apply:
            db.execute(
                "UPDATE nodes SET start_date=?, end_date=? WHERE id=?",
                (start, end, r["id"]),
            )
        if kind == "wikidata":
            filled_wd += 1
        else:
            filled_label += 1
        if filled_wd + filled_label <= 20:
            print(f"  날짜 채움: {r['label'][:44]}  {start or ''}~{end or ''}  ({kind})")
    print(f"무연대 사건 {len(undated)}건 중 채움: wikidata {filled_wd}건"
          f" · 라벨연도 {filled_label}건")

    # --- 2. 참여 엣지 검사 -------------------------------------------------
    def year_span(node_id: str) -> tuple[str | None, str | None]:
        row = db.execute(
            "SELECT start_date, end_date, label, type FROM nodes WHERE id=?",
            (node_id,),
        ).fetchone()
        if row is None:
            return (None, None)
        start, end = row["start_date"], row["end_date"]
        # 아직 --apply 전이면 채울 예정인 날짜로 판정한다 (계획이 실제와 같도록)
        if not start and not end and row["type"] == "event":
            if node_id.startswith("wd:"):
                start, end = dates.get(node_id[3:], (None, None))
            else:
                start = label_year(row["label"]) or from_evidence.get(node_id)
        return (start, end)

    edges = db.execute("""
        SELECT e.rowid, e.src, e.dst, e.props,
               s.label AS slabel, d.label AS dlabel
          FROM edges e
          JOIN nodes s ON s.id = e.src
          JOIN nodes d ON d.id = e.dst
         WHERE e.source = 'extract' AND e.type = 'participated_in'
    """).fetchall()

    doomed: list[tuple[int, str, str, str]] = []
    for e in edges:
        evidence = json.loads(e["props"]).get("evidence", "")
        if loss_context("participated_in", evidence):
            doomed.append((e["rowid"], e["slabel"], e["dlabel"], "소실문형"))
        elif lifespan_conflict("participated_in",
                               year_span(e["src"]), year_span(e["dst"])):
            doomed.append((e["rowid"], e["slabel"], e["dlabel"], "연대충돌"))

    for _, s, d, why in doomed:
        print(f"  삭제: {s} --참여--> {d}  ({why})")
    print(f"추출 참여 엣지 {len(edges)}건 중 삭제 대상 {len(doomed)}건")

    if apply:
        db.executemany("DELETE FROM edges WHERE rowid=?",
                       [(rid,) for rid, *_ in doomed])
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
