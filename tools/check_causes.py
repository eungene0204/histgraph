"""이미 적힌 인과 엣지를 팩트체크 관문(`causes.fact_check`)에 다시 넣는다.

    uv run python tools/check_causes.py [--db data/histgraph.sqlite] [--apply]

`--apply` 면 걸린 엣지를 편집 계층(`overrides`, deleted)에 적고 지운다 — 수집이
되살리지 못한다. 원본과 파생본(`--db data/korea.sqlite`)에 한 번씩."""
import argparse, json, sys
sys.path.insert(0, "src")
from histgraph.store import GraphStore
from histgraph import causes as C, overrides as ov, corpus as K

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="data/histgraph.sqlite")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--samples", type=int, default=8)
args = ap.parse_args()

with GraphStore(args.db) as store:
    conn = K.open_corpus(None)
    texts: dict[str, str] = {}
    rows = store.conn.execute(
        """SELECT e.src, e.dst, e.label, e.confidence, e.props, a.label AS src_label, b.label AS dst_label
             FROM edges e JOIN nodes a ON a.id = e.src JOIN nodes b ON b.id = e.dst
            WHERE e.type = ? AND e.source = ?""", (C.EDGE_TYPE, C.SOURCE_MARK)).fetchall()
    bad: dict[str, list] = {}
    kinds = 0
    for r in rows:
        props = json.loads(r["props"] or "{}")
        evidence = props.get("evidence") or ""
        if not evidence:
            continue
        doc_id = props.get("doc") or ""
        if doc_id not in texts:
            texts[doc_id] = "\n\n".join(p["text"] for p in C.doc_passages(conn, doc_id, budget=10**8)) if doc_id else ""
        why, kind, cap = C.fact_check(
            store, {"id": doc_id}, r["label"] or "", evidence,
            (r["src"], r["src_label"], props.get("cause_as") or r["src_label"]),
            (r["dst"], r["dst_label"], props.get("effect_as") or r["dst_label"]),
            C.evidence_window(evidence, texts[doc_id]))
        if why:
            bad.setdefault(why, []).append((r["src"], r["dst"], r["src_label"], r["dst_label"], r["label"], evidence))
        elif kind != r["label"] or (cap is not None and (r["confidence"] or 0) > cap):
            kinds += 1
            if args.apply:
                key = ov.edge_key(r["src"], r["dst"], C.EDGE_TYPE)
                if kind != r["label"]:
                    store.conn.execute("UPDATE edges SET label = ? WHERE src = ? AND dst = ? AND type = ? AND source = ?",
                                       (kind, r["src"], r["dst"], C.EDGE_TYPE, C.SOURCE_MARK))
                    ov.record(store.conn, "edge", key, "label", kind, "factcheck",
                              "'X의 해소' 꼴 결과는 영향으로 · 'X 이후'뿐인 근거는 배경으로")
                if cap is not None and (r["confidence"] or 0) > cap:
                    store.conn.execute("UPDATE edges SET confidence = ? WHERE src = ? AND dst = ? AND type = ? AND source = ?",
                                       (cap, r["src"], r["dst"], C.EDGE_TYPE, C.SOURCE_MARK))
                    ov.record(store.conn, "edge", key, "confidence", cap, "factcheck", "'X 이후'뿐인 근거 — 확신도 상한")
    total = sum(len(v) for v in bad.values())
    print(f"인과 엣지 {len(rows):,}건 중 걸린 것 {total:,}건 · 종류만 고칠 것 {kinds}건 ({args.db})")
    for why, items in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        print(f"  {why}: {len(items)}")
        for src, dst, a, b, kind, ev in items[: args.samples]:
            print(f"      {a} → {b} ({kind}) — {ev[:80]}")
    if args.apply:
        for why, items in bad.items():
            for src, dst, a, b, kind, ev in items:
                ov.record(store.conn, "edge", ov.edge_key(src, dst, C.EDGE_TYPE), "deleted", True, "factcheck",
                          f"{why}: {a} → {b} — {ev[:60]}")
                store.conn.execute("DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?", (src, dst, C.EDGE_TYPE))
        store.conn.commit()
        print(f"  지움 {total}건 · 편집 계층에 기록")
