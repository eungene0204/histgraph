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


def _persist(store: GraphStore, source: str, nodes: list[Node], edges: list[Edge]) -> None:
    node_map = {n.id: n for n in nodes}
    problems = [msg for e in edges if (msg := validate_edge_endpoints(e, node_map))]
    if problems:
        for msg in sorted(set(problems))[:5]:
            print(f"  ⚠ 스키마 경고: {msg}", file=sys.stderr)

    n = store.upsert_nodes(nodes)
    e = store.upsert_edges(edges)
    store.log_ingest(source, n, e)
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
        before = store.stats()["by_edge_type"].get("participated_in", 0)
        nodes, edges = infobox.ingest(fetcher, store, limit=args.limit)
        if not edges:
            print("  인포박스에서 관계를 찾지 못했습니다", file=sys.stderr)
            return 1
        _persist(store, "kowiki:infobox", nodes, edges)
        after = store.stats()["by_edge_type"].get("participated_in", 0)
        print(f"  participated_in: {before:,} → {after:,}")
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
                                 node_types=tuple(args.types) if args.types else None)
        if not docs:
            print(
                "  추출할 산문이 없습니다. 먼저 `ingest heritage` 로 content 를 수집하세요.",
                file=sys.stderr,
            )
            return 1

        gazetteer = ex.build_gazetteer(store)
        print(f"→ 문서 {len(docs)}건, 가제티어 {sum(len(v) for v in gazetteer.values())}개 개체")

        if args.dry_run:
            # 비용을 쓰기 전에 실제로 보낼 프롬프트를 눈으로 확인한다
            print("\n=== 첫 문서 프롬프트 (dry-run) ===")
            print(ex.build_prompt(docs[0], gazetteer)[:2000])
            return 0

        results: dict[str, list[dict]] = {}

        if args.backend == "anthropic" and not args.sync:
            # Claude 는 배치가 절반 값이다. 로컬 모델엔 배치 개념이 없다.
            client = ex.get_client()
            batch_id = ex.submit_batch(client, docs, gazetteer)
            print(f"  배치 ID: {batch_id} (완료까지 최대 24시간)")
            results = ex.collect_batch(client, batch_id, docs)
        else:
            backend = build_backend(args.backend, args.model)
            print(f"  백엔드: {backend.name} ({args.model or '기본 모델'})")
            empty = 0
            # 근거 검증에 원문이 필요하다. 같은 노드의 여러 조각을 이어붙여
            # 둬야 조각 경계에 걸친 근거도 원문에 있는 것으로 인정된다.
            texts: dict[str, str] = {}
            for doc in docs:
                texts[doc.node_id] = texts.get(doc.node_id, "") + doc.text
            for i, doc in enumerate(docs, 1):
                part = f" [{doc.chunk + 1}/{doc.total_chunks}]" if doc.total_chunks > 1 else ""
                rels = ex.extract_one(backend, doc, gazetteer)
                if not rels:
                    empty += 1
                results.setdefault(doc.node_id, []).extend(rels)
                if i % 10 == 0 or i == len(docs):
                    print(f"    {i}/{len(docs)}  관계 {sum(len(v) for v in results.values()):,}건 (빈 응답 {empty})")
                del part

        all_nodes, all_edges = [], []
        for node_id, relations in results.items():
            n, e = ex.to_graph(relations, node_id, store, doc_text=texts.get(node_id))
            all_nodes.extend(n)
            all_edges.extend(e)

        _persist(store, "extract", all_nodes, all_edges)
        print(f"  추출된 관계 {len(all_edges):,}건 (문서 {len(results)}건에서)")
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
    p_ib.add_argument("--limit", type=int, default=None, help="처리할 사건 수")
    p_ib.add_argument("--interval", type=float, default=0.5)
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
    p_ex.add_argument("--scope", default=None,
                      help="시대 서브그래프 DB 경로. 그 노드들의 산문만 추출 (예: data/joseon.sqlite)")
    p_ex.set_defaults(func=cmd_extract)

    p_sc = sub.add_parser("scope", help="한 시대만 별도 그래프로 추출")
    p_sc.add_argument("era", choices=["joseon", "goryeo", "silla", "goguryeo", "baekje"])
    p_sc.add_argument("--out", default=str(ROOT / "data" / "joseon.sqlite"))
    p_sc.add_argument("--hops", type=int, default=1, help="씨앗에서 확장할 홉 수")
    p_sc.add_argument("--keep-isolated", action="store_true", help="엣지 없는 노드도 유지")
    p_sc.set_defaults(func=cmd_scope)

    sub.add_parser("stats", help="그래프 통계").set_defaults(func=cmd_stats)

    p_show = sub.add_parser("show", help="노드 주변 서브그래프")
    p_show.add_argument("node_id")
    p_show.add_argument("--depth", type=int, default=1)
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
