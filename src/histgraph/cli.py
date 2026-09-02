"""histgraph 수집 파이프라인 CLI.

  python -m histgraph doctor              # 소스별 접근 가능 여부 진단
  python -m histgraph ingest heritage --kinds 11 --limit 50
  python -m histgraph ingest wikidata
  python -m histgraph stats
  python -m histgraph show wd:Q37682 --depth 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .backends import build_backend
from .http import Fetcher
from .ontology import Edge, Node, validate_edge_endpoints
from .sources import culture, datagokr, heritage, wikidata
from .store import GraphStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "histgraph.sqlite"
DEFAULT_CACHE = ROOT / "data" / "cache"


def load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 읽는다. 이미 설정된 환경변수가 우선."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def _persist(
    store: GraphStore,
    source: str,
    nodes: list[Node],
    edges: list[Edge],
    quiet: bool = False,
) -> None:
    node_map = {n.id: n for n in nodes}
    problems = [msg for e in edges if (msg := validate_edge_endpoints(e, node_map))]
    if problems:
        for msg in sorted(set(problems))[:5]:
            print(f"  ⚠ 스키마 경고: {msg}", file=sys.stderr)

    n = store.upsert_nodes(nodes)
    e = store.upsert_edges(edges)
    store.log_ingest(source, n, e)
    if not quiet:
        print(f"  ✓ {source}: 노드 {n:,}개, 엣지 {e:,}개 저장")


def cmd_doctor(args: argparse.Namespace) -> int:
    fetcher = Fetcher(DEFAULT_CACHE, min_interval=0.3)
    print("=== 소스 접근 진단 ===\n")

    print("[1] 국가유산청 Open API (인증키 불필요)")
    try:
        rows = list(heritage.fetch_list(fetcher, "11", "11", page_size=3))
        print(f"  ✓ 정상 — 샘플: {', '.join(r.get('ccbaMnm1', '?') for r in rows[:3])}\n")
    except Exception as err:
        print(f"  ✗ 실패: {err}\n")

    print("[2] Wikidata SPARQL (인증키 불필요)")
    try:
        actual = wikidata.verify_polities(fetcher)
        # QID 는 추측하면 반드시 틀린다. 기대 라벨과 대조해 조용한 오염을 막는다.
        bad = [
            f"{qid}: 기대={want!r} 실제={actual.get(qid, '(없음)')!r}"
            for qid, want in wikidata.POLITIES.items()
            if want not in actual.get(qid, "")
        ]
        if bad:
            print(f"  ✗ QID 불일치 {len(bad)}건:")
            for line in bad:
                print(f"      {line}")
        else:
            print(f"  ✓ 정상 — 왕조 QID {len(actual)}개 라벨 일치")
        print()
    except Exception as err:
        print(f"  ✗ 실패: {err}\n")

    print("[3] 공공데이터포털 data.go.kr (데이터셋별 활용신청 필요)")
    key = os.environ.get("DATA_GO_KR_API_KEY", "")
    print(f"  키: {'설정됨 (' + str(len(key)) + '자)' if key else '없음'}")
    if key:
        for name, status in datagokr.check_key(fetcher).items():
            print(f"  {'✓' if status.startswith('OK') else '✗'} {name}: {status}")

    print("\n[4] 문화공공데이터광장 culture.go.kr (API별 활용신청 필요)")
    ckey = os.environ.get("CULTURE_API_KEY", "")
    print(f"  키: {'설정됨 (' + str(len(ckey)) + '자)' if ckey else '없음'}")
    if ckey:
        for name, status in culture.check_key(fetcher).items():
            print(f"  {'✓' if status.startswith('OK') else '✗'} {name}: {status}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    fetcher = Fetcher(DEFAULT_CACHE, min_interval=args.interval)

    # 엣지 자연키에 type 이 포함되므로, 정규화 로직을 바꾼 뒤 그냥 재실행하면
    # 옛 타입의 행이 남아 중복 집계된다. 로직 변경 후에는 --reset 이 필요하다.
    if args.reset and args.db.exists():
        args.db.unlink()
        print(f"  기존 DB 삭제: {args.db}")

    with GraphStore(args.db) as store:
        if args.source in ("heritage", "all"):
            print("→ 국가유산청 수집 중...")
            nodes, edges = heritage.ingest(
                fetcher,
                kinds=args.kinds,
                regions=args.regions,
                limit=args.limit,
                with_detail=not args.no_detail,
            )
            _persist(store, "heritage", nodes, edges)

        if args.source in ("wikidata", "all"):
            # WDQS 는 과호출에 403/502 로 응답한다. 공용 엔드포인트이므로
            # 넉넉한 간격을 둔다.
            wd_fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
            failures: list[str] = []

            print("→ Wikidata 인물 수집 중...")
            people = wikidata.fetch_persons(wd_fetcher, failures=failures)
            rel_nodes, rel_edges = wikidata.fetch_person_edges(
                wd_fetcher, failures=failures
            )
            _persist(store, "wikidata:person", people + rel_nodes, rel_edges)

            print("→ Wikidata 사건 수집 중...")
            ev_nodes, ev_edges = wikidata.fetch_events(wd_fetcher, failures=failures)
            _persist(store, "wikidata:event", ev_nodes, ev_edges)

            print("→ Wikidata 영화·드라마 수집 중...")
            m_nodes, m_edges = wikidata.fetch_media(wd_fetcher, failures=failures)
            _persist(store, "wikidata:media", m_nodes, m_edges)

            # 부분 실패를 조용히 넘기면 결손된 그래프를 완전한 것으로 착각한다.
            if failures:
                print(
                    f"\n  ⚠ 실패한 쿼리 {len(failures)}건 — 해당 관계는 누락됨:",
                    file=sys.stderr,
                )
                for desc in failures:
                    print(f"      - {desc}", file=sys.stderr)
                print("    재실행하면 캐시된 성공분은 건너뛰고 실패분만 다시 시도합니다.", file=sys.stderr)

    return 0


def cmd_events(args: argparse.Namespace) -> int:
    """한국사 주요 사건을 이름으로 직접 수집한다.

    차수 상위순으로 고르는 enrich 로는 임진왜란·병자호란이 잡히지 않는다."""
    from .sources import wikipedia

    fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.0))
    with GraphStore(args.db) as store:
        before = store.stats()["by_node_type"].get("event", 0)
        nodes, edges = wikipedia.ingest_events(fetcher, store, full=not args.intro_only)
        _persist(store, "kowiki:event", nodes, edges)
        after = store.stats()["by_node_type"].get("event", 0)
        print(f"  사건 노드: {before:,} → {after:,}")
    return 0


def cmd_infobox(args: argparse.Namespace) -> int:
    """위키백과 인포박스에서 관계를 뽑는다 (LLM 불필요)."""
    from .sources import infobox

    fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 0.5))
    with GraphStore(args.db) as store:
        types = tuple(args.types)
        before = store.stats()["by_edge_type"]
        nodes, edges = infobox.ingest(
            fetcher, store, limit=args.limit, node_types=types
        )
        if not edges:
            print("  인포박스에서 관계를 찾지 못했습니다", file=sys.stderr)
            return 1
        _persist(store, "kowiki:infobox", nodes, edges)
        after = store.stats()["by_edge_type"]
        # 인물 인포박스는 participated_in 을 거의 안 준다. 한 종류만 찍으면
        # 성과가 없는 것처럼 보이므로 늘어난 타입을 모두 보여준다.
        for kind in sorted(set(before) | set(after)):
            b, a = before.get(kind, 0), after.get(kind, 0)
            if a > b:
                print(f"  {kind}: {b:,} → {a:,}")
    return 0


def ex_scope_ids(path: str | None) -> set[str] | None:
    if not path:
        return None
    from .extract import load_scope_ids

    return load_scope_ids(path)


def cmd_enrich(args: argparse.Namespace) -> int:
    """한국어 위키백과 서사를 기존 노드에 채운다."""
    from .sources import wikipedia

    fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.0))
    with GraphStore(args.db) as store:
        print(f"→ 위키백과 보강 중 (상위 {args.limit}개 노드, full={args.full})...")
        result = wikipedia.enrich(
            fetcher,
            store,
            node_types=tuple(args.types),
            limit=args.limit,
            full=args.full,
            refresh=args.refresh,
            scope_ids=ex_scope_ids(args.scope),
        )
        print(
            f"  ✓ 문서명 {result['titles']:,} · 본문 {result['extracts']:,}"
            f" · 노드 갱신 {result['updated']:,}"
        )
        if result["updated"] == 0 and result["titles"] > 0:
            print("  ⚠ 본문은 받았지만 노드에 반영되지 않았습니다", file=sys.stderr)
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """스포츠 이벤트 제거 — 이걸 안 하면 participated_in 의 90%가 올림픽이다."""
    from . import resolve as resolve_mod

    with GraphStore(args.db) as store:
        before = store.stats()
        result = resolve_mod.prune_sports(store)
        print(f"  라벨 기준: 노드 {result['nodes']:,}개, 엣지 {result['edges']:,}개 제거")

        if not args.labels_only:
            # 이름만으로는 못 잡는 대회들을 Wikidata 클래스 계층으로 마저 거른다
            print("→ Wikidata 클래스 조회 중 (이름으로 못 잡는 대회용)...")
            by_class = resolve_mod.prune_sports_by_class(store)
            print(
                f"  클래스 기준: 노드 {by_class['nodes']:,}개,"
                f" 엣지 {by_class['edges']:,}개 제거"
            )
        after = store.stats()
        print(
            f"  participated_in: {before['by_edge_type'].get('participated_in', 0):,}"
            f" → {after['by_edge_type'].get('participated_in', 0):,}"
        )
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    """엔티티 해소 — 국가유산청 섬과 Wikidata 섬을 잇는다."""
    from . import resolve as resolve_mod

    with GraphStore(args.db) as store:
        print("→ 시대 연결 중...")
        periods = resolve_mod.link_periods(store)
        print(f"  ✓ {periods}건")

        print("→ 장소 연결 중...")
        places = resolve_mod.link_places(store)
        print(f"  ✓ {places}건")

        report = resolve_mod.bridge_report(store)
        print("\n=== 연결 검증 ===")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["cross_source"] == 0:
            print(
                "\n  ⚠ 소스를 건너뛰는 링크가 0건입니다 — 두 그래프는 아직 분리돼 있습니다.",
                file=sys.stderr,
            )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """산문에서 인물↔사건 엣지를 추출한다 (Claude API)."""
    from . import extract as ex

    with GraphStore(args.db) as store:
        scope_ids = ex.load_scope_ids(args.scope) if args.scope else None
        docs = ex.load_documents(store, limit=args.limit, min_score=args.min_score,
                                 scope_ids=scope_ids, skip_covered=not args.no_skip_covered,
                                 max_chunks=args.max_chunks,
                                 node_types=tuple(args.types) if args.types else None,
                                 skip_extracted=not args.redo)
        if not docs:
            print(
                "  추출할 산문이 없습니다. 먼저 `ingest heritage` 로 content 를 수집하세요.",
                file=sys.stderr,
            )
            return 1

        gazetteer = ex.build_gazetteer(store, scope_ids=scope_ids)
        print(f"→ 문서 {len(docs)}건, 가제티어 {sum(len(v) for v in gazetteer.values())}개 개체")

        if args.dry_run:
            # 비용을 쓰기 전에 실제로 보낼 프롬프트를 눈으로 확인한다
            print("\n=== 첫 문서 프롬프트 (dry-run) ===")
            print(ex.build_prompt(docs[0], gazetteer)[:2000])
            return 0

        # 근거 검증에 원문이 필요하다. 같은 노드의 여러 조각을 이어붙여
        # 둬야 조각 경계에 걸친 근거도 원문에 있는 것으로 인정된다.
        texts: dict[str, str] = {}
        for doc in docs:
            texts[doc.node_id] = texts.get(doc.node_id, "") + doc.text

        if args.backend == "anthropic" and not args.sync:
            # Claude 는 배치가 절반 값이다. 로컬 모델엔 배치 개념이 없다.
            client = ex.get_client()
            batch_id = ex.submit_batch(client, docs, gazetteer)
            print(f"  배치 ID: {batch_id} (완료까지 최대 24시간)")
            results = ex.collect_batch(client, batch_id, docs)

            all_nodes, all_edges = [], []
            for node_id, relations in results.items():
                n, e = ex.to_graph(relations, node_id, store, doc_text=texts.get(node_id))
                all_nodes.extend(n)
                all_edges.extend(e)
            _persist(store, "extract", all_nodes, all_edges)
            print(f"  추출된 관계 {len(all_edges):,}건 (문서 {len(results)}건에서)")
            return 0

        backend = build_backend(args.backend, args.model)
        print(f"  백엔드: {backend.name} ({args.model or '기본 모델'})")

        # **문서 단위로 저장한다.** 로컬 추출은 조각당 수십 초라 400조각이면
        # 몇 시간짜리 작업이 된다. 끝에 한 번만 저장하면 중간에 죽었을 때
        # 전부 잃는다. 한 노드의 조각이 끝날 때마다 커밋해서 손실을
        # 마지막 노드 하나로 제한한다.
        done = empty = saved_edges = saved_docs = 0
        pending: list[dict] = []
        current = docs[0].node_id

        def flush(node_id: str, relations: list[dict]) -> int:
            nodes, edges = ex.to_graph(
                relations, node_id, store, doc_text=texts.get(node_id)
            )
            if not nodes and not edges:
                return 0  # 빈 결과까지 기록하면 ingest_log 가 문서 수만큼 늘어난다
            _persist(store, "extract", nodes, edges, quiet=True)
            return len(edges)

        for doc in docs:
            if doc.node_id != current:
                saved_edges += flush(current, pending)
                saved_docs += 1
                pending, current = [], doc.node_id
            rels = ex.extract_one(backend, doc, gazetteer)
            if not rels:
                empty += 1
            pending.extend(rels)
            done += 1
            if done % 10 == 0 or done == len(docs):
                # 대기 중인 것을 따로 보여준다 — 저장은 노드가 끝나야 일어나므로
                # 저장 수만 찍으면 마지막 노드가 통째로 사라진 것처럼 보인다
                print(
                    f"    {done}/{len(docs)}  저장 {saved_edges:,}건"
                    f" · 대기 {len(pending):,}건 (빈 응답 {empty})"
                )
        saved_edges += flush(current, pending)
        saved_docs += 1

        print(f"  추출된 관계 {saved_edges:,}건 (문서 {saved_docs}건에서)")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """추출이 만든 ex: 고아 노드를 실제 노드로 승격·병합한다."""
    from . import promote as pr

    with GraphStore(args.db) as store:
        before = store.stats()
        ex_before = store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id LIKE 'ex:%'"
        ).fetchone()[0]

        if not args.dry_run:
            # 산문은 '정종'이라 쓰고 우리 라벨은 '조선 정종'이다. 별칭을
            # 먼저 달아야 이어지는 매칭이 같은 노드를 찾는다.
            print(f"→ 왕조 접두 별칭 {pr.add_bare_name_aliases(store)}개 추가")

        # 이름으로 붙은 엣지가 옳은 노드에 갔는지 전수 조사
        audit = pr.repair_links(store, dry_run=args.dry_run)
        print(
            f"\n→ 추출 엣지 끝점 {audit['checked']:,}개 검사"
            f" · 이상 없음 {audit['ok']:,}"
            f" · 옮김 {len(audit['moves'])}"
            f" · 보류 {len(audit['ambiguous'])}"
        )
        for m in audit["moves"][: args.show]:
            print(
                f"    {m['label']:12} (엣지 {m['degree']}) → {m['target_label']}"
                f" (엣지 {m['target_degree']})  [{m['method']}"
                + (f" · {m['doc_era']} 문서]" if m["doc_era"] else "]")
            )
        if len(audit["moves"]) > args.show:
            print(f"    … 외 {len(audit['moves']) - args.show}건")
        if audit["ambiguous"]:
            print("  보류 (진짜 동명이인 — 규칙 없이 옮기지 않는다):")
            for a in audit["ambiguous"][:5]:
                others = ", ".join(
                    f"{c['label']}({c['degree']})" for c in a["candidates"][:3]
                )
                print(f"    {a['label']}({a['degree']}) ↔ {others}")

        # 같은 작품이 표기만 달라 두 노드가 된 것. 승격 앞에 둔다 —
        # 뒤에 두면 다음 실행까지 화면에 중복이 남는다.
        variants = pr.title_variant_matches(store)
        print(f"\n→ 작품 표기 변이 {len(variants)}쌍")
        for v in variants[: args.show]:
            print(f"    {v['label']} → {v['target_label']}  (핵심 '{v['core']}')")
        if not args.dry_run:
            for v in variants:
                pr.merge_node(store, v["ex_id"], v["target"], v["method"], v["score"])
            store.conn.commit()

        if not args.no_retype:
            plan = pr.retype(store, dry_run=args.dry_run)["plan"]
            print(f"→ 타입 교정 {len(plan)}건")
            for old_id, _, label, new_type in plan[:12]:
                print(f"    {label} : {old_id.split(':')[1]} → {new_type}")
            if len(plan) > 12:
                print(f"    … 외 {len(plan) - 12}건")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.0))
        result = pr.promote(
            store,
            fetcher,
            types=tuple(args.types),
            limit=args.limit,
            local_only=args.local_only,
            dry_run=args.dry_run,
        )
        print(
            f"\n→ 승격 대상 {result['candidates']:,}개 중 {result['planned']:,}개 매칭"
            f"  {result['by_method']}"
        )
        if result["skipped"]:
            print(f"  건너뜀: {result['skipped']}")
        for item in result["plan"][: args.show]:
            print(f"    {item['label']:20} → {item['target']:16} ({item['method']})")
        if len(result["plan"]) > args.show:
            print(f"    … 외 {len(result['plan']) - args.show}건")

        if args.dry_run:
            print("\n  (dry-run — 아무것도 바꾸지 않았습니다)")
            return 0

        # QID 를 찾은 것만으로는 이름을 바꾼 데 지나지 않는다. 그 QID 에
        # 달린 관계를 끌어와야 고아였던 인물이 그래프에 얽힌다.
        pending = pr.pending_backfill(store)
        if pending and not args.no_backfill:
            print(f"\n→ 승격 노드 {len(pending)}개의 Wikidata 관계 보강 중...")
            back = pr.backfill_relations(store, pending)
            print(f"  ✓ 관계 상대 노드 {back['nodes']:,}개 · 엣지 {back['edges']:,}건")

        # 스키마 정리는 **맨 끝에** 한다. 타입 교정·병합·보강이 모두
        # 엣지 양끝을 바꾸므로, 먼저 돌리면 그 뒤에 들어온 불일치가 남는다
        # (실측: 보강 뒤에 63건이 남아 다음 실행에서야 정리됐다).
        fixed = pr.relax_invalid_edges(store)
        print(f"  스키마 정리: 방향교정 {fixed['flipped']}건 · 완화 {fixed['relaxed']}건")

        if args.prune_orphans:
            print(f"  고립 ex 노드 {pr.prune_orphans(store)}개 제거")

        after = store.stats()
        ex_after = store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id LIKE 'ex:%'"
        ).fetchone()[0]
        print(f"\n  ex 노드: {ex_before:,} → {ex_after:,}")
        print(f"  전체 노드: {before['nodes_total']:,} → {after['nodes_total']:,}")
        print(f"  전체 엣지: {before['edges_total']:,} → {after['edges_total']:,}")
        print("\n  시대 서브그래프는 다시 뽑아야 반영됩니다: python3 -m histgraph scope joseon")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    """한 시대만 뽑아 별도 그래프로 만든다. 원본은 그대로 둔다."""
    from . import scope as scope_mod

    with GraphStore(args.db) as store:
        result = scope_mod.extract(store, args.era, args.out, hops=args.hops,
                                   drop_isolated=not args.keep_isolated)
    print(f"\n=== {result['era']} 서브그래프 ===")
    print(f"  출력: {result['out']}")
    print(f"  씨앗 {result['seeds']:,} → 노드 {result['kept_nodes']:,} · 엣지 {result['kept_edges']:,}")
    if result["isolated_dropped"]:
        print(f"  고립 노드 {result['isolated_dropped']:,}개 제외 (엣지가 없어 그래프에 기여하지 않음)")
    print(f"  댕글링 엣지: {result['dangling']}")
    print("\n  노드 구성:")
    for k, v in result["by_node_type"].items():
        print(f"    {k:10} {v:>6,}")
    print("\n  관계 구성:")
    for k, v in result["by_edge_type"].items():
        print(f"    {k:16} {v:>6,}")
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    """연도를 일급 개체로 정규화한다."""
    from . import timeline

    with GraphStore(args.db) as store:
        result = timeline.build(store, link_attributes=not args.labels_only)
        print(f"  연도 노드 {result['year_nodes']:,}개  ({result['span']})")
        print(f"  라벨 연결 {result['label_links']:,}건 · 속성 연결 {result['attribute_edges']:,}건")
        print(f"  연도 미해독 라벨 {result['unparsed_labels']:,}건 (왕대·세기 표기 — 환산표 없이는 추정 불가)")
        if args.year:
            print(f"\n  === {args.year}년에 일어난 일 ===")
            for row in timeline.whats_in(store, args.year):
                print(f"    [{row['type']:8}] {row['label'][:40]:42} ({row['rel'] or row['via']})")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """그래프 탐색 화면을 띄운다."""
    from . import server

    db = args.db
    if args.era and db == DEFAULT_DB:
        # scope 로 뽑아둔 시대 그래프가 기본 대상 — 전체 그래프(37,158 노드)는
        # 탐색용으로는 너무 크고, 조선만 보겠다는 게 지금의 목표다.
        candidate = ROOT / "data" / f"{args.era}.sqlite"
        if candidate.exists():
            db = candidate
        else:
            print(
                f"  {candidate} 가 없습니다. 먼저 만드세요:\n"
                f"    python3 -m histgraph scope {args.era} --out {candidate}",
                file=sys.stderr,
            )
            return 1
    server.serve(db, host=args.host, port=args.port, era=args.era)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with GraphStore(args.db) as store:
        print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with GraphStore(args.db) as store:
        sub = store.neighbors(args.node_id, depth=args.depth)
        print(json.dumps(sub, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser(prog="histgraph", description="역사 온톨로지 그래프 수집기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="소스 접근 가능 여부 진단").set_defaults(func=cmd_doctor)

    p_ing = sub.add_parser("ingest", help="데이터 수집")
    p_ing.add_argument("source", choices=["heritage", "wikidata", "all"])
    p_ing.add_argument("--kinds", nargs="*", default=None, help="지정종목 코드 (기본 11=국보)")
    p_ing.add_argument("--regions", nargs="*", default=None, help="시도 코드")
    p_ing.add_argument("--limit", type=int, default=None)
    p_ing.add_argument("--no-detail", action="store_true", help="상세 API 생략 (빠름)")
    p_ing.add_argument("--interval", type=float, default=0.3, help="요청 간 최소 간격(초)")
    p_ing.add_argument("--reset", action="store_true", help="수집 전 DB 삭제 (정규화 로직 변경 후 필수)")
    p_ing.set_defaults(func=cmd_ingest)

    p_ev = sub.add_parser("events", help="한국사 주요 사건을 이름으로 직접 수집")
    p_ev.add_argument("--interval", type=float, default=1.0)
    p_ev.add_argument("--intro-only", action="store_true", help="본문 전체 대신 도입부만 (빠름, 서사 얕음)")
    p_ev.set_defaults(func=cmd_events)

    p_ib = sub.add_parser("infobox", help="위키백과 인포박스에서 관계 추출 (LLM 불필요)")
    p_ib.add_argument("--limit", type=int, default=None, help="처리할 문서 수")
    p_ib.add_argument("--interval", type=float, default=0.5)
    p_ib.add_argument("--types", nargs="*", default=["event"],
                      help="대상 노드 타입 (event·person). 인물은 부모·배우자·"
                           "스승을 LLM 없이 준다")
    p_ib.set_defaults(func=cmd_infobox)

    p_en = sub.add_parser("enrich", help="한국어 위키백과 서사로 노드 보강")
    p_en.add_argument("--limit", type=int, default=500, help="보강할 노드 수 (차수 상위순)")
    p_en.add_argument("--types", nargs="*", default=["person", "event"])
    p_en.add_argument("--full", action="store_true", help="도입부 대신 본문 전체 (요청당 1건, 느림)")
    p_en.add_argument("--interval", type=float, default=1.0)
    p_en.add_argument("--refresh", action="store_true", help="이미 산문이 있는 노드도 다시 받기")
    p_en.add_argument("--scope", default=None, help="시대 서브그래프 DB 로 대상 한정")
    p_en.set_defaults(func=cmd_enrich)

    p_prune = sub.add_parser("prune", help="스포츠 이벤트 노드 제거")
    p_prune.add_argument("--labels-only", action="store_true", help="Wikidata 클래스 조회 생략 (빠름)")
    p_prune.set_defaults(func=cmd_prune)
    sub.add_parser("resolve", help="엔티티 해소 (소스 간 연결)").set_defaults(func=cmd_resolve)

    p_ex = sub.add_parser("extract", help="산문에서 관계 추출 (Claude API)")
    p_ex.add_argument("--limit", type=int, default=None, help="처리할 문서 수")
    p_ex.add_argument(
        "--min-score", type=float, default=1.0,
        help="서사 점수 하한 (1.0=인물 또는 사건, 2.0=둘 다). 낮추면 비용만 든다",
    )
    p_ex.add_argument("--sync", action="store_true", help="배치 대신 동기 호출 (비쌈, 소량 테스트용)")
    p_ex.add_argument("--backend", choices=["anthropic", "mlx", "ollama"], default="mlx",
                      help="추출 백엔드. 기본값은 로컬 MLX(키·비용 불필요, 스키마 강제)")
    p_ex.add_argument("--model", default=None, help="모델 이름 (백엔드 기본값 사용하려면 생략)")
    p_ex.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")
    p_ex.add_argument("--no-skip-covered", action="store_true",
                      help="구조화 소스가 이미 덮은 문서도 추출 (기본은 건너뜀)")
    p_ex.add_argument("--types", nargs="*", default=["event", "org"],
                      help="추출 대상 노드 타입 (기본: 사건·조직)")
    p_ex.add_argument("--max-chunks", type=int, default=3,
                      help="문서당 사용할 조각 수 (밀도 상위순, 0=제한없음)")
    p_ex.add_argument("--redo", action="store_true",
                      help="이미 추출한 문서도 다시 처리 (기본은 건너뜀). "
                           "--limit 으로 나눠 돌릴 때 기본값을 유지할 것")
    p_ex.add_argument("--scope", default=None,
                      help="시대 서브그래프 DB 경로. 그 노드들의 산문만 추출 (예: data/joseon.sqlite)")
    p_ex.set_defaults(func=cmd_extract)

    p_pm = sub.add_parser("promote", help="추출 고아(ex:) 노드를 실제 노드로 승격")
    p_pm.add_argument("--dry-run", action="store_true", help="바꾸지 않고 계획만 출력")
    p_pm.add_argument("--local-only", action="store_true",
                      help="위키백과 조회 없이 그래프 안에서만 매칭")
    p_pm.add_argument("--no-retype", action="store_true", help="타입 교정 단계 생략")
    p_pm.add_argument("--no-backfill", action="store_true",
                      help="승격된 QID 의 Wikidata 관계 보강 생략")
    p_pm.add_argument("--prune-orphans", action="store_true",
                      help="엣지도 same_as 도 없는 ex 노드 제거")
    p_pm.add_argument("--types", nargs="*",
                      default=["person", "event", "org", "place", "role", "period"])
    p_pm.add_argument("--limit", type=int, default=None, help="처리할 ex 노드 수")
    p_pm.add_argument("--show", type=int, default=20, help="출력할 매칭 예시 수")
    p_pm.add_argument("--interval", type=float, default=1.0)
    p_pm.set_defaults(func=cmd_promote)

    p_sc = sub.add_parser("scope", help="한 시대만 별도 그래프로 추출")
    p_sc.add_argument("era", choices=["joseon", "goryeo", "silla", "goguryeo", "baekje"])
    p_sc.add_argument("--out", default=str(ROOT / "data" / "joseon.sqlite"))
    p_sc.add_argument("--hops", type=int, default=1, help="씨앗에서 확장할 홉 수")
    p_sc.add_argument("--keep-isolated", action="store_true", help="엣지 없는 노드도 유지")
    p_sc.set_defaults(func=cmd_scope)

    p_tl = sub.add_parser("timeline", help="연도를 일급 개체로 정규화")
    p_tl.add_argument("--labels-only", action="store_true", help="날짜 속성 연결 생략")
    p_tl.add_argument("--year", type=int, default=None, help="그 해에 무슨 일이 있었는지 확인")
    p_tl.set_defaults(func=cmd_timeline)

    p_sv = sub.add_parser("serve", help="그래프 탐색 화면 (브라우저)")
    p_sv.add_argument("--era", default="joseon", help="띄울 시대 그래프 (data/{era}.sqlite)")
    p_sv.add_argument("--host", default="127.0.0.1")
    p_sv.add_argument("--port", type=int, default=8100)
    p_sv.set_defaults(func=cmd_serve)

    sub.add_parser("stats", help="그래프 통계").set_defaults(func=cmd_stats)

    p_show = sub.add_parser("show", help="노드 주변 서브그래프")
    p_show.add_argument("node_id")
    p_show.add_argument("--depth", type=int, default=1)
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
