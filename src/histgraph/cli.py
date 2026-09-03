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
from .ontology import EDGE_TYPES, FORMS, NODE_TYPES, Edge, Node, validate_edge_endpoints
from .sources import culture, datagokr, heritage, wikidata
from .store import GraphStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "histgraph.sqlite"
DEFAULT_CACHE = ROOT / "data" / "cache"
DEFAULT_LABELS = ROOT / "data" / "ko_labels.tsv"


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
    """한국사 주요 사건·단체·개념을 이름으로 직접 수집한다.

    차수 상위순으로 고르는 enrich 로는 임진왜란·병자호란이 잡히지 않는다.

    **세 표를 갈라 둔 이유는 타입이다.** 의열단을 사건 표에 넣으면 사건
    노드가 되고, 창씨개명을 넣으면 개념이 사건 행세를 한다."""
    from .sources import wikipedia

    tables = {
        "event": ("kowiki:event", wikipedia.EVENT_SEEDS),
        "org": ("kowiki:org", wikipedia.ORG_SEEDS),
        "concept": ("kowiki:concept", wikipedia.CONCEPT_SEEDS),
    }
    fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.0))
    with GraphStore(args.db) as store:
        before = store.stats()["by_node_type"]
        for kind in args.kinds:
            source, seeds = tables[kind]
            if args.eras:
                seeds = {e: t for e, t in seeds.items() if e in args.eras}
            if not seeds:
                continue
            nodes, edges = wikipedia.ingest_seeds(
                fetcher, store, seeds, kind, full=not args.intro_only
            )
            # **시드 표는 타입을 말하지만 upsert 는 타입을 덮어쓰지 않는다.**
            # 이미 다른 타입으로 앉아 있던 노드는 그대로 남으므로, 조용히
            # 어긋나지 않게 반드시 보고한다. 바꾸는 것은 사람이 정한다 —
            # 타입을 바꾸면 그 노드에 걸린 엣지가 스키마와 어긋난다.
            stale = [
                (n.id, n.label, row["type"])
                for n in nodes
                if n.type == kind
                and (row := store.conn.execute(
                    "SELECT type FROM nodes WHERE id=?", (n.id,)
                ).fetchone())
                and row["type"] != kind
            ]
            _persist(store, source, nodes, edges)
            for nid, label, was in stale:
                print(
                    f"  ⚠ 시드는 {NODE_TYPES[kind]}이라 하는데 그래프에는"
                    f" {NODE_TYPES[was]}으로 있음: {label} ({nid})"
                )
        after = store.stats()["by_node_type"]
        for kind in args.kinds:
            print(f"  {NODE_TYPES[kind]} 노드: {before.get(kind, 0):,} → {after.get(kind, 0):,}")
    return 0


def cmd_infobox(args: argparse.Namespace) -> int:
    """위키백과 인포박스에서 관계를 뽑는다 (LLM 불필요)."""
    from .sources import infobox

    fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 0.5))
    with GraphStore(args.db) as store:
        types = tuple(args.types)
        before = store.stats()["by_edge_type"]
        nodes, edges = infobox.ingest(
            fetcher, store, limit=args.limit, node_types=types,
            refresh=args.refresh,
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
        target = f"상위 {args.limit:,}개" if args.limit else "남은 전부"
        print(f"→ 위키백과 보강 중 ({target}, full={args.full})...")
        result = wikipedia.enrich(
            fetcher,
            store,
            node_types=tuple(args.types),
            limit=args.limit,
            full=args.full,
            refresh=args.refresh,
            scope_ids=ex_scope_ids(args.scope),
            fallback=not args.no_fallback,
        )
        print(
            f"  ✓ 문서명 {result['titles']:,} · 본문 {result['extracts']:,}"
            f" · 노드 갱신 {result['updated']:,}"
        )
        # 못 채운 쪽도 반드시 적는다. 빈 설명칸이 왜 비어 있는지는
        # '아직 안 받았다'와 '문서가 없다'가 전혀 다른 이야기다.
        if result["no_article"]:
            print(
                f"  · 한국어 위키백과 문서 없음 {result['no_article']:,}개"
                f" → Wikidata 한 줄 설명 {result['fallback']:,}개로 대체"
            )
        if result["unresolved"]:
            print(
                f"  ⚠ sitelink 조회가 죽어 문서 유무를 모르는 노드"
                f" {result['unresolved']:,}개 — 다시 실행하면 재시도합니다",
                file=sys.stderr,
            )
        if result["redirected"]:
            print(
                f"  · 넘겨주기를 따라간 설명 {result['redirected']:,}개"
                f" — 다른 문서의 글이라 화면에 그렇게 표시됩니다"
            )
        if result["remaining"]:
            print(f"  · --limit 으로 남긴 노드 {result['remaining']:,}개")
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


def cmd_works(args: argparse.Namespace) -> int:
    """역사를 다룬 작품 명단 — 한국어 위키백과 분류에서.

    분류 이름이 곧 관계다: '이순신을 소재로 한'은 `depicts`, '조선을
    배경으로 한'은 `set_in`, '역사 드라마'는 매체 구분이 된다."""
    from .sources import works

    fetcher = Fetcher(Path(args.db).parent / "cache", min_interval=args.interval)

    with GraphStore(args.db) as store:
        print(f"→ 분류 나무를 훑는 중 ({works.ROOT_CATEGORY})...")
        pages = works.crawl(fetcher, args.root or works.ROOT_CATEGORY,
                            args.depth or works.MAX_DEPTH)
        print(f"  문서 {len(pages):,}건")

        titles = sorted(pages)
        qids = works.page_qids(fetcher, titles)
        print(f"  그중 QID 있는 것 {len(qids):,}건 ({len(qids) * 100 // max(len(titles), 1)}%)")

        # 제목·분류로 매체를 못 읽은 것만 Wikidata 에 물어본다.
        need = [
            qids[t] for t in titles
            if t in qids and not works.form_of(t, pages[t])
        ]
        extra = works.forms_from_wikidata(fetcher, need) if need else {}
        if need:
            print(f"  제목·분류로 매체를 못 읽은 {len(need):,}건 중 {len(extra):,}건을 P31 로 읽음")

        nodes, skipped = works.build_nodes(pages, qids, extra)
        by_form: dict[str, int] = {}
        for n in nodes:
            by_form[n.props["form"]] = by_form.get(n.props["form"], 0) + 1
        print(
            "  작품 노드 {:,}개 — {}".format(
                len(nodes),
                " · ".join(f"{FORMS[k]} {v:,}" for k, v in sorted(by_form.items(), key=lambda kv: -kv[1])),
            )
        )

        resolver = _label_resolver(store)
        edges, counts, unresolved = works.build_edges(nodes, resolver)
        print(f"  분류에서 나온 엣지 — 소재 {counts['depicts']:,}건 · 배경 {counts['set_in']:,}건")

        if args.dry_run:
            print("\n  --dry-run 입니다. 저장하지 않았습니다.")
        else:
            store.upsert_nodes(nodes)
            store.upsert_edges(edges)
            store.log_ingest("kowiki-works", len(nodes), len(edges))
            print(f"\n  ✓ 노드 {len(nodes):,}개 · 엣지 {len(edges):,}개 저장")

        if not args.dry_run:
            filled, left = works.backfill_forms(store, fetcher)
            if filled or left:
                print(f"  매체 구분이 비어 있던 기존 작품 {filled + len(left):,}개 중 {filled:,}개를 채움")
            for node_id, label in left[: args.show]:
                print(f"    · 못 채움: {label} ({node_id})", file=sys.stderr)

        if args.harvest:
            print("\n→ 작품 문서에서 발표일·원작·소재를 읽는 중 (LLM 없이)...")
            got = works.harvest(store, fetcher, resolver, limit=args.harvest_limit)
            print(f"  문서 {got['read']:,}건을 읽어"
                  f" 발표일 {len(got['dates']):,}건 · 엣지 {len(got['edges']):,}건")
            by_type: dict[str, int] = {}
            for e in got["edges"]:
                by_type[e.type] = by_type.get(e.type, 0) + 1
            if by_type:
                print("   " + " · ".join(
                    f"{EDGE_TYPES[k][0]} {v:,}" for k, v in sorted(by_type.items())))
            if got["dropped"]:
                print(f"  몰년 관문에서 버린 인물 링크 {len(got['dropped']):,}건"
                      " (배우·감독을 막는 관문이다)")
            if not args.dry_run:
                store.conn.executemany(
                    "UPDATE nodes SET start_date = ?, updated_at = datetime('now') "
                    "WHERE id = ? AND start_date IS NULL",
                    got["dates"],
                )
                store.conn.commit()
                store.upsert_edges(got["edges"])
                print(f"  ✓ 저장했습니다")

        if skipped:
            print(f"\n  만들지 않은 문서 {len(skipped):,}건 (매체를 모르면 노드로 만들지 않는다):")
            for title, why in skipped[: args.show]:
                print(f"    · {title} — {why}")
        if unresolved:
            print(f"\n  그래프에서 하나로 찾지 못한 이름 {len(unresolved):,}개 (엣지를 잇지 않음):")
            print("    " + ", ".join(unresolved[: args.show * 2]))
    return 0


def _label_resolver(store: GraphStore):
    """이름 -> 노드 id. 하나로 찾아지지 않으면 None.

    라벨을 먼저 보고 없으면 별칭을 본다. **후보가 둘이면 잇지 않는다** —
    '허준'·'김유신'은 동명이인이 있고 '임진왜란'은 노드가 둘이다. 자동으로
    고르면 틀린 곳에 붙는다."""

    def same_entity(ids: list[str]) -> bool:
        """이미 same_as 로 이어 둔 후보들은 둘이 아니라 하나다.

        실측: '조선'은 `wd:Q28179`(왕조)와 `kr:period:조선`(시대) 둘로
        나오는데, `resolve` 가 이미 같은 실체로 이어 두었다. 이걸 '후보가
        둘'로 세면 조선을 배경으로 한 작품 수십 편이 배경을 잃는다."""
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                linked = store.conn.execute(
                    "SELECT 1 FROM same_as WHERE (a=? AND b=?) OR (a=? AND b=?)",
                    (a, b, b, a),
                ).fetchone()
                if not linked:
                    return False
        return True

    def resolve(name: str, allowed: tuple[str, ...]) -> str | None:
        rows = store.conn.execute(
            "SELECT id, type FROM nodes WHERE label = ?", (name,)
        ).fetchall()
        if not rows:
            rows = store.conn.execute(
                "SELECT n.id, n.type FROM aliases a JOIN nodes n ON n.id = a.node_id "
                "WHERE a.alias = ?",
                (name,),
            ).fetchall()
        hits = [r["id"] for r in rows if r["type"] in allowed]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1 and same_entity(hits):
            # 같은 실체라면 Wikidata 쪽을 대표로 쓴다 — 다른 소스가 붙을 때
            # 기준이 되는 것이 QID 다.
            return sorted(hits, key=lambda i: (not i.startswith("wd:"), i))[0]
        return None

    return resolve


def cmd_reclassify(args: argparse.Namespace) -> int:
    """개념을 사건에서 갈라낸다 — 화면의 '이 사건을 다룬 작품'이 서려면 먼저.

    지우는 명령이 아니다. 주제어는 쓰레기가 아니라 자리를 잘못 찾은
    개념이므로 `concept` 으로 옮기고 엣지를 `about` 으로 바꾼다."""
    from . import reclassify as rc

    with GraphStore(args.db) as store:
        before = rc.depicts_report(store)
        # 재분류 전에는 이 비율이 늘 100%다 — 개념이 사건 행세를 하고 있으니
        # 타입만 봐서는 멀쩡해 보인다. 오염은 대상 라벨에서 드러난다.
        print(f"→ 지금 depicts {before['total']:,}건이 가리키는 것:")
        for label, node_type, n in before["top"][:8]:
            print(f"    {n:>3}  {label} ({NODE_TYPES[node_type]})")

        plan = rc.plan_reclassify(store, limit=args.limit)
        if plan.failed_batches:
            print(
                f"  ⚠ 조회 실패 {plan.failed_batches}건 — 그 구간은 보류합니다"
                " (다시 돌리면 캐시된 구간은 건너뜁니다)",
                file=sys.stderr,
            )

        buckets: dict[tuple[str, str], list[str]] = {}
        for node_id, move in plan.changes.items():
            buckets.setdefault(move, []).append(plan.labels[node_id])
        for (before_type, after), labels in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            head = ", ".join(labels[: args.show])
            more = f" 외 {len(labels) - args.show:,}개" if len(labels) > args.show else ""
            print(
                f"  {NODE_TYPES[before_type]} → {NODE_TYPES[after]}"
                f" {len(labels):,}개: {head}{more}"
            )
        if plan.held:
            print(f"  보류 {len(plan.held):,}개 (판정 못 함 — 손대지 않습니다)")
            for node_id, label in plan.held[: args.show]:
                print(f"    · {label} ({node_id})")

        if args.dry_run:
            print("\n  --dry-run 입니다. 실제로 바꾸려면 --dry-run 을 빼고 다시 실행하세요.")
            return 0
        if not plan.changes:
            fixed = rc.repair_edges(store)
            if any(fixed.values()):
                print(f"  노드는 그대로 두고 엣지만 바로잡음 — "
                      f"about → 소재로 다룸 {fixed['about_to_depicts']:,}건, "
                      f"소재로 다룸 → about {fixed['depicts_to_about']:,}건")
            else:
                print("  바꿀 것이 없습니다.")
            return 0

        result = rc.apply_plan(store, plan)
        # 노드를 안 바꿔도 엣지는 어긋나 있을 수 있다 — 수집이 다시 돌면
        # 새 주제 엣지가 이미 사건인 노드를 가리킨 채 들어온다.
        fixed = rc.repair_edges(store)
        for key in ("about_to_depicts", "depicts_to_about"):
            result[key] = result.get(key, 0) + fixed[key]
        print(
            f"\n  ✓ 노드 {result['nodes']:,}개 재분류,"
            f" depicts → about {result['depicts_to_about']:,}건,"
            f" about → depicts {result['about_to_depicts']:,}건"
        )

        after = rc.depicts_report(store)
        print(
            f"  depicts {before['total']:,} → {after['total']:,}건,"
            f" about {after['about']:,}건"
            f" (실체를 가리키던 것은 처음부터 {after['total']:,}건이었다)"
        )
        print("  이제 depicts 가 가리키는 것:")
        for label, node_type, n in after["top"]:
            print(f"    {n:>3}  {label} ({NODE_TYPES[node_type]})")

        bad = rc.invalid_edges(store)
        if bad:
            print(f"\n  ⚠ 타입이 바뀌면서 어긋난 엣지 {len(bad)}건:", file=sys.stderr)
            for src, dst, etype, st, dt in bad[: args.show]:
                print(f"    {etype}: {st} → {dt}  ({src} → {dst})", file=sys.stderr)
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    """엔티티 해소 — 국가유산청 섬과 Wikidata 섬을 잇는다."""
    from . import resolve as resolve_mod

    with GraphStore(args.db) as store:
        # 시대가 장소로 앉아 있으면 그 뒤의 모든 연결이 그 위에 쌓인다.
        # 맨 앞에 둔다.
        print("→ 시대 노드 점검 중...")
        fixed = resolve_mod.fix_period_nodes(store)
        for nid, was, now in fixed["retyped"]:
            print(f"  타입 교정: {nid}  {NODE_TYPES[was]} → {NODE_TYPES[now]}")
        if fixed["stale"]:
            print(f"  시대가 될 수 없는 노드를 가리키던 시대 엣지 {fixed['stale']:,}건 제거")
        if fixed["moved"] or fixed["dropped"]:
            print(
                f"  '어디서' 칸에 적힌 시대 {fixed['moved']}건을 from_period 로 옮김"
                + (f" (옮길 수 없어 버림 {fixed['dropped']}건)" if fixed["dropped"] else "")
            )

        print("→ 시대 연결 중...")
        periods = resolve_mod.link_periods(store)
        print(f"  ✓ {periods}건")

        print("→ 장소 연결 중...")
        places = resolve_mod.link_places(store)
        print(f"  ✓ {places}건")

        # 같은 사실이 소스에 따라 엣지(위키백과)와 props(Wikidata)로 갈려
        # 있었다. 화면이 읽는 것은 엣지다.
        print("→ 사건의 시대를 엣지로 세우는 중...")
        eras = resolve_mod.link_event_periods(store)
        print(f"  ✓ {eras}건")

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
                                 skip_extracted=not args.redo,
                                 max_participants=args.max_participants,
                                 min_chars=args.min_chars)
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
                n, e = ex.to_graph(relations, node_id, store,
                                   doc_text=texts.get(node_id),
                                   model=ex.BATCH_MODEL, backend="anthropic")
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
                relations, node_id, store, doc_text=texts.get(node_id),
                model=backend.model, backend=backend.name,
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

        # 그래프가 스스로 모순인 관계(남편이 부모, 죽은 뒤의 참여…)를 보수
        facts = pr.repair_facts(store, dry_run=args.dry_run)
        print(
            f"\n→ 모순 관계 {len(facts['drops']):,}건 정리"
            f" · 옳은 인물로 옮김 {len(facts['moves'])}"
            f" · 사람 손 필요 {len(facts['holds'])}"
        )
        for d in facts["drops"][:5]:
            print(f"    - {d['text']} ({d['reason']})")

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
        print("\n  시대 서브그래프는 다시 뽑아야 반영됩니다: uv run histgraph scope joseon")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    """시대를 뽑아 별도 그래프로 만든다. 원본은 그대로 둔다."""
    from . import scope as scope_mod

    # 이름을 인자로 두 번 적게 하지 않는다. 시대 하나면 그 이름, 묶음이면
    # 묶음 이름이 곧 파일 이름이다 (serve --era 가 같은 규칙으로 찾는다).
    out = args.out or str(ROOT / "data" / f"{'+'.join(args.era)}.sqlite")

    with GraphStore(args.db) as store:
        result = scope_mod.extract(store, args.era, out, hops=args.hops,
                                   drop_isolated=not args.keep_isolated)

    # **파생본에 한국어 관문을 바로 건다.** scope 는 원본을 그대로 베끼므로
    # 원본에서 relabel·redescribe 를 잊었으면 영어가 그대로 화면에 간다.
    # "relabel 은 파생본에도 한 번 더"를 README 에 적어 두는 방식은 세 번
    # 실패했다 (2026-09-03 ×2 · 09-04). 그래서 사람이 기억하지 않아도 되게
    # 여기서 돌리고, 그러고도 남으면 **실패로 끝낸다** — 파일은 남되 종료
    # 코드가 1 이라 파이프라인이 알아챈다. 남은 것은 표에 적고 다시 돌린다.
    from . import koreanize
    from . import labels as labels_mod

    table = labels_mod.load_table(args.table)
    with GraphStore(Path(out)) as derived:
        relabeled = labels_mod.apply_overrides(derived.conn, table)
        redescribed = koreanize.redescribe(derived.conn)
        foreign = labels_mod.foreign_text(derived.conn)

    print(f"\n=== {result['era']} 서브그래프 ===")
    print(f"  출력: {result['out']}")
    print(f"  씨앗 {result['seeds']:,} → 노드 {result['kept_nodes']:,} · 엣지 {result['kept_edges']:,}"
          f" · 별칭 {result['kept_aliases']:,}")
    if result["isolated_dropped"]:
        print(f"  고립 노드 {result['isolated_dropped']:,}개 제외 (엣지가 없어 그래프에 기여하지 않음)")
    print(f"  댕글링 엣지: {result['dangling']}")
    print("\n  노드 구성:")
    for k, v in result["by_node_type"].items():
        print(f"    {k:10} {v:>6,}")
    print("\n  관계 구성:")
    for k, v in result["by_edge_type"].items():
        print(f"    {k:16} {v:>6,}")

    print(f"\n  한국어 관문: 이름 {len(relabeled.applied):,}개 · 설명"
          f" {len(redescribed.applied):,}개 옮김 · 설명 {len(redescribed.cleared):,}개 비움")
    if foreign:
        print(f"\n  ✗ 화면에 한글 아닌 글이 뜨는 노드 {len(foreign):,}건 —"
              f" {args.table.relative_to(ROOT) if args.table.is_relative_to(ROOT) else args.table}"
              " 에 이름을 적고 다시 돌리세요"
              f" (표만 고쳤다면 `histgraph --db {out} relabel` 로 충분합니다):")
        for nid, ntype, column, text in foreign[:40]:
            print(f"    {ntype:<7} {nid:>16}  {column}: {text[:60]}")
        if len(foreign) > 40:
            print(f"    … 그 밖 {len(foreign) - 40:,}건")
        return 1
    print("  한글 아닌 글이 뜨는 노드가 없습니다.")
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


def cmd_spans(args: argparse.Namespace) -> int:
    """조직·왕조의 존속 기간을 Wikidata 에서 채운다.

    **수집이 여태 물어본 적 없는 값이다.** 인물은 P569/P570, 사건은
    P580/P582 를 처음부터 가져왔는데 조직은 다른 노드의 엣지 상대로만
    들어와 라벨과 URL 뿐이었다 — 조선 그래프의 org 80개가 전부 날짜
    없음이고 거기에 이 그래프의 중심인 조선이 있었다.

    이미 적혀 있는 날짜는 건드리지 않는다. 채우기만 한다."""
    with GraphStore(args.db) as store:
        rows = store.conn.execute(
            f"""SELECT id, label FROM nodes
                 WHERE type IN ({",".join("?" * len(args.types))})
                   AND id LIKE 'wd:%'
                   AND (start_date IS NULL OR start_date = '')
                   AND (end_date IS NULL OR end_date = '')""",
            tuple(args.types),
        ).fetchall()
        if not rows:
            print("  채울 노드가 없습니다.")
            return 0
        print(f"  날짜 없는 {'·'.join(args.types)} 노드 {len(rows):,}개 조회 중...")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
        failures: list[str] = []
        spans = wikidata.fetch_spans(
            fetcher, [r["id"][len("wd:"):] for r in rows], failures=failures
        )

        filled = 0
        for r in rows:
            start, end = spans.get(r["id"][len("wd:"):], (None, None))
            if not (start or end):
                continue
            store.conn.execute(
                """UPDATE nodes
                      SET start_date = COALESCE(start_date, ?),
                          end_date   = COALESCE(end_date, ?),
                          updated_at = datetime('now')
                    WHERE id = ?""",
                (start, end, r["id"]),
            )
            filled += 1
            if filled <= 15:
                print(f"    {r['label'][:24]:26} {start or '?'} ~ {end or '?'}")
        store.conn.commit()

        print(f"\n  채운 노드 {filled:,}개 / {len(rows):,}개")
        # 못 채운 것이 대부분일 수 있다. 그건 Wikidata 에 없는 것이지
        # 우리가 잘못 물은 것이 아니라는 걸 숫자로 남긴다.
        print(f"  Wikidata 에도 없음 {len(rows) - filled:,}개")
        if failures:
            print(f"  ⚠ 실패한 쿼리 {len(failures)}건 — 재실행하면 그 구간만 다시 시도합니다.",
                  file=sys.stderr)
    return 0


# 엣지에 남길 출처 표기. 어느 속성에서 왔는지 적어 두지 않으면 나중에
# 이 엣지를 다시 검증할 길이 없다.
_LINK_PROP = {
    ("part_of", ""): "P361/P527",
    ("related_to", "다음"): "P155/P156",
    ("related_to", "원인"): "P828/P1542",
    ("participated_in", ""): "P710",
    ("occurred_at", ""): "P276",
}


def cmd_links(args: argparse.Namespace) -> int:
    """사건이 자기 쪽에 적어 둔 관계를 채운다.

    **수집은 사건 쪽에서 물어본 적이 없다.** 관계를 인물의 속성으로만
    긁었다(P1344 '참여'). 그래서 사건이 자기 문서에 적어 둔 것 — 상하위
    (P361/P527) · 전후(P155/P156) · 참가자(P710) · 원인(P828) · 결과
    (P1542) · 장소(P276) — 은 통째로 빠져 있었다.

    실측: '왕자의 난'은 제1차·제2차와 아무 엣지도 없이 홀로 서 있었고
    (연결 0건), 옥포 해전은 이순신과, 신임사화는 노론·소론과 끊겨 있었다.
    원인·결과 엣지는 그래프 전체에 한 건도 없었다 — 병인박해가 병인양요를
    불렀다는 것을 그래프는 모르고 있었다.

    **없는 사건을 새로 만들지는 않는다.** 반대쪽 끝이 그래프에 없으면
    건너뛰고 수만 보고한다 — 여기서 노드를 만들기 시작하면 교황청
    콘클라베처럼 한국사와 무관한 사건이 딸려 들어온다. 그건 events·
    enrich 가 할 일이다."""
    with GraphStore(args.db) as store:
        rows = store.conn.execute(
            "SELECT id, label FROM nodes WHERE type = 'event' AND id LIKE 'wd:%'"
        ).fetchall()
        if not rows:
            print("  Wikidata 사건 노드가 없습니다.")
            return 0
        labels = dict(store.conn.execute("SELECT id, label FROM nodes"))
        print(f"  사건 노드 {len(rows):,}개 조회 중...")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
        failures: list[str] = []
        links = wikidata.fetch_event_links(
            fetcher, [r["id"][len("wd:"):] for r in rows], failures=failures
        )

        types = dict(store.conn.execute("SELECT id, type FROM nodes"))
        known = set(labels)
        edges, outside, twins, mistyped = [], 0, [], []
        for a, b, etype, elabel in links:
            src, dst = f"wd:{a}", f"wd:{b}"
            if src not in known or dst not in known:
                outside += 1
                continue
            # **양끝 타입이 스키마에 맞아야 담는다.** Wikidata 는 옥포 해전의
            # 참가자로 이순신과 '일본'을 나란히 적어 두는데, 우리 그래프에서
            # 일본은 place 라 '장소가 해전에 참여했다'가 된다. 온톨로지가
            # 막아 주는 것을 여기서 버리고, 몇 건인지는 반드시 보고한다.
            _, ok_src, ok_dst = EDGE_TYPES[etype]
            if types.get(src) not in ok_src or types.get(dst) not in ok_dst:
                mistyped.append((src, dst, etype))
                continue
            # **이름이 같은 두 노드는 잇지 않는다.** 실측: Wikidata 는
            # 임진왜란을 1592~1593년 침입(Q122846639)과 1592~1598년
            # 전쟁(Q576338) 둘로 두고 앞의 것을 뒤의 것의 일부로 적는데,
            # 우리 그래프는 둘 다 라벨이 '임진왜란'이라 화면에 "임진왜란은
            # 임진왜란의 일부다"가 뜬다. 사실은 맞지만 읽을 수 없는 문장이고,
            # 여기서 이을 일이 아니라 노드를 합칠 일이다. 보고만 한다.
            if labels.get(src) == labels.get(dst):
                twins.append((src, dst, labels.get(src, "")))
                continue
            edges.append(Edge(
                src=src, dst=dst, type=etype, source="wd", label=elabel or None,
                props={"wikidata_property": _LINK_PROP[(etype, elabel)]},
            ))

        # 이미 있는 엣지와 새로 생기는 엣지를 갈라 센다. 다시 돌릴 때
        # '296건 이었습니다'만 찍히면 무엇이 늘었는지 알 수 없다.
        existing = {
            (r[0], r[1], r[2])
            for r in store.conn.execute(
                "SELECT src, dst, type FROM edges WHERE source = 'wd'")
        }
        fresh = [e for e in edges if (e.src, e.dst, e.type) not in existing]
        before = store.stats()["by_edge_type"]
        for e in fresh[:15]:
            head = e.label or EDGE_TYPES[e.type][0]
            print(f"    {labels.get(e.src, e.src)[:22]:24} —{head}→ {labels.get(e.dst, e.dst)}")
        if len(fresh) > 15:
            print(f"    … 그 밖 {len(fresh) - 15:,}건")
        if not args.dry_run and edges:
            store.upsert_edges(edges)
        after = store.stats()["by_edge_type"]

        head = "새로 이을 관계" if args.dry_run else "새로 이은 관계"
        kinds = {}
        for e in fresh:
            kinds[e.type] = kinds.get(e.type, 0) + 1
        shape = " · ".join(f"{k} {v:,}" for k, v in sorted(kinds.items())) or "없음"
        print(f"\n  {head} {len(fresh):,}건 ({shape})"
              f" · 이미 있던 것 {len(edges) - len(fresh):,}건")
        for kind in sorted(kinds):
            print(f"    {kind}: {before.get(kind, 0):,} → {after.get(kind, 0):,}")
        # 반대쪽 끝이 없는 관계도 반드시 센다. '없는 관계'와 '못 담은
        # 관계'가 같은 얼굴이면 그래프의 결손을 알 수 없다.
        print(f"  반대쪽 개체가 그래프에 없어 건너뜀 {outside:,}건")
        if mistyped:
            kinds2: dict[str, int] = {}
            for _, _, t in mistyped:
                kinds2[t] = kinds2.get(t, 0) + 1
            shape2 = " · ".join(f"{k} {v:,}" for k, v in sorted(kinds2.items()))
            print(f"  양끝 타입이 스키마에 안 맞아 건너뜀 {len(mistyped):,}건 ({shape2})")
            for src, dst, t in mistyped[:5]:
                print(f"    {labels.get(src, src)}({types.get(src)})"
                      f" -{t}-> {labels.get(dst, dst)}({types.get(dst)})")
        if twins:
            print(f"\n  ⚠ 이름이 같은 두 노드를 잇는 관계 {len(twins)}건 — 중복 의심,"
                  f" 잇지 않았습니다:")
            for src, dst, label in twins[:6]:
                print(f"    {label}: {src} ↔ {dst}")
        if failures:
            print(f"  ⚠ 실패한 쿼리 {len(failures)}건 — 재실행하면 그 구간만 다시 시도합니다.",
                  file=sys.stderr)
    return 0


def cmd_precision(args: argparse.Namespace) -> int:
    """연도만 아는 날짜에서 지어낸 1월 1일을 걷어낸다 (P585 등의 자릿수).

    **Wikidata 는 '1592년'을 '1592-01-01' 로 준다.** 자릿수(9=연)는 값이
    아니라 문장에 붙어 있는데 `wdt:` 로 긁는 우리 수집은 값만 가져왔다.
    그래서 DB 에는 연도만 아는 날이 전부 1월 1일로 앉아 있다 (실측: 전체
    그래프에서 시작일이 1월 1일인 노드 7,117개).

    연표가 몰린 해를 늘려 세우기 전에는 티가 안 났다. 늘려 세우고 나니
    그 안의 **차례가 곧 시간 순으로 읽히는데**, 지어낸 1월 1일이 4월의
    동래성 전투보다 앞에 서면 없는 날짜로 순서를 말한 것이 된다.

    자릿수만큼 잘라 부분 날짜로 되돌린다 — '1592', '1592-09'. 스키마는
    처음부터 부분 날짜를 허용하고(`ontology.Node`), 연도를 읽는 쪽은 전부
    앞 네 자리만 보므로 나머지 파이프라인은 그대로다.

    **수집 뒤에 다시 돌릴 것.** `upsert_nodes` 의 날짜 칸은 새 값이 있으면
    덮어쓰므로, 다시 수집하면 1월 1일이 되돌아온다 (`reigns` 와 같다)."""
    with GraphStore(args.db) as store:
        # 날이 01 인 것만 후보다. 다른 날짜는 이미 일 단위로 아는 값이다.
        rows = store.conn.execute(
            """SELECT id, label, start_date, end_date FROM nodes
                WHERE id LIKE 'wd:%'
                  AND (start_date LIKE '%-01' OR end_date LIKE '%-01')"""
        ).fetchall()
        if not rows:
            print("  1월 1일로 앉은 날짜가 없습니다.")
            return 0
        print(f"  날이 01 인 노드 {len(rows):,}개 — 자릿수 조회 중...")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
        failures: list[str] = []
        precision = wikidata.fetch_date_precision(
            fetcher, [r["id"][len("wd:"):] for r in rows], failures=failures
        )

        # 고칠 것을 다 모아 한 번에 쓴다. 원본 DB 에는 다른 세션의 `extract`
        # 가 붙어 있을 수 있어, 쓰기 잠금을 오래 쥐고 있으면 그쪽이 죽는다.
        updates: list[tuple[str | None, str | None, str]] = []
        shown = 0
        for r in rows:
            known = precision.get(r["id"][len("wd:"):], {})
            start = wikidata.trim_to_precision(
                r["start_date"], known.get(r["start_date"])
            )
            end = wikidata.trim_to_precision(r["end_date"], known.get(r["end_date"]))
            if (start, end) == (r["start_date"], r["end_date"]):
                continue
            updates.append((start, end, r["id"]))
            if shown < 12:
                shown += 1
                # 시작만 적으면 끝만 줄어든 줄이 '안 바뀐 것'처럼 보인다
                print(f"    {r['label'][:18]:20}"
                      f" {r['start_date'] or '?'}~{r['end_date'] or '?'}"
                      f"  ->  {start or '?'}~{end or '?'}")
        if not args.dry_run and updates:
            store.conn.executemany(
                "UPDATE nodes SET start_date = ?, end_date = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                updates,
            )
            store.conn.commit()

        trimmed = len(updates)
        head = "줄일 날짜" if args.dry_run else "줄인 날짜"
        # 자릿수를 못 받은 노드도 센다. 조용히 넘어가면 '고칠 게 없었다'와
        # '못 물어봤다'가 같은 얼굴로 나온다.
        unknown = sum(1 for r in rows if r["id"][len("wd:"):] not in precision)
        print(f"\n  {head} {trimmed:,}건 / 후보 {len(rows):,}건"
              f" · 자릿수를 못 받은 노드 {unknown:,}개")
        if failures:
            print(f"  실패한 쿼리 {len(failures)}건: " + " · ".join(failures[:5]))
    return 0


def cmd_reigns(args: argparse.Namespace) -> int:
    """왕의 재위 기간을 held_position 엣지에 채운다.

    **재위는 노드가 아니라 엣지의 값이다.** 인물 노드의 P569/P570 은
    생몰이고, 직위 노드(조선 임금)에 적을 수도 없다 — '언제부터 언제까지
    그 자리에 있었나'는 그 둘을 잇는 엣지의 성질이다. Wikidata 에서도
    P39 문장의 한정어(pq:P580/P582)에만 있어서 `wdt:` 로 긁는 우리 수집은
    한 번도 가져온 적이 없었다. 실측: 조선 그래프의 held_position 552개가
    전부 날짜 없음.

    다시 수집해도 지워지지는 않는다 — `upsert_edges` 의 ON CONFLICT 는
    날짜 칸을 갱신하지 않는다. 다만 props 는 덮어쓰므로(`props =
    excluded.props`) 재위 표식은 날아간다. 수집 뒤에 다시 돌릴 것."""
    with GraphStore(args.db) as store:
        pairs = store.conn.execute(
            """SELECT src, dst FROM edges
                WHERE type = 'held_position'
                  AND src LIKE 'wd:%' AND dst LIKE 'wd:%'"""
        ).fetchall()
        if not pairs:
            print("  직위 엣지가 없습니다.")
            return 0
        labels = dict(store.conn.execute("SELECT id, label FROM nodes"))
        positions = sorted({r["dst"][len("wd:"):] for r in pairs})
        print(f"  직위 엣지 {len(pairs):,}개 · 직위 {len(positions):,}종 조회 중...")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
        failures: list[str] = []
        monarch = wikidata.fetch_monarch_positions(
            fetcher, positions, failures=failures
        )
        if not monarch:
            print("  군주 자리에 해당하는 직위가 없습니다.")
            return 0
        print(f"  군주 자리 {len(monarch)}종: "
              + " · ".join(sorted(monarch.values()))[:150])

        wanted = [r for r in pairs if r["dst"][len("wd:"):] in monarch]
        persons = sorted({r["src"][len("wd:"):] for r in wanted})
        print(f"  그 자리에 앉은 인물 {len(persons):,}명 — 재위 조회 중...")
        reigns = wikidata.fetch_reigns(
            fetcher, persons, list(monarch), failures=failures
        )

        filled = 0
        seated: set[str] = set()      # 재위를 하나라도 채운 인물
        for r in wanted:
            key = (r["src"][len("wd:"):], r["dst"][len("wd:"):])
            start, end = reigns.get(key, (None, None))
            if not (start or end):
                continue
            filled += 1
            seated.add(r["src"])
            if filled <= 12:
                print(f"    {labels.get(r['src'], r['src'])[:16]:18}"
                      f" {start or '?'} ~ {end or '?'}"
                      f"  ({monarch[key[1]]})")
            if args.dry_run:
                continue
            # 날짜만 넣지 않고 '이건 재위다'를 함께 적는다. 나중에 다른
            # 직위(영의정 재임)에도 날짜가 붙으면 화면이 둘을 갈라야 한다.
            store.conn.execute(
                """UPDATE edges
                      SET start_date = ?, end_date = ?,
                          props = json_set(COALESCE(NULLIF(props, ''), '{}'),
                                           '$.reign', json('true'))
                    WHERE src = ? AND dst = ? AND type = 'held_position'""",
                (start, end, r["src"], r["dst"]),
            )
        if not args.dry_run:
            store.conn.commit()

        head = "채울 재위" if args.dry_run else "채운 재위"
        print(f"\n  {head} {filled:,}건 / 자리 {len(wanted):,}건"
              f" · 재위를 아는 인물 {len(seated):,}명 / {len(persons):,}명")
        # **한 인물이 같은 자리를 두 항목으로 갖기도 한다.** 정종은
        # '조선 임금'과 일반 '왕' 둘에 걸려 있고 날짜는 앞의 것에만 있다.
        # 빠진 자리를 세면 정종이 '재위를 모르는 왕'이 되므로, 못 채운
        # 것은 자리가 아니라 **사람**으로 센다.
        missing = [r["src"] for r in wanted if r["src"] not in seated]
        if missing:
            # 추존왕은 그 자리를 가졌지만 앉은 적이 없다. 0년으로 채우면
            # 연표에 없던 왕이 서므로 비운 채로 두고 이름만 남긴다.
            names = " · ".join(labels.get(i, i) for i in sorted(set(missing)))
            print(f"  재위 날짜가 없는 인물 {len(set(missing))}명 (추존 등): {names[:160]}")
        if failures:
            print(f"  ⚠ 실패한 쿼리 {len(failures)}건 — 재실행하면 그 구간만 다시 시도합니다.",
                  file=sys.stderr)
    return 0


def cmd_aliases(args: argparse.Namespace) -> int:
    """Wikidata 의 한국어 별칭(skos:altLabel)을 채운다.

    **`wikidata.fetch_aliases` 는 쓰이지 않는 코드였다.** 함수는 있는데
    파이프라인 어디에서도 부르지 않아, 지금 있는 별칭 5,064건은 전부
    국가유산청·위키백과가 노드에 얹어 준 것이다. 그래서 사건에는 별칭이
    420개 중 39개뿐이고, 경술국치·을사늑약·국권피탈 같은 이름으로는
    아무것도 찾을 수 없었다 (Wikidata 에는 한일병합의 한국어 별칭이
    17개나 적혀 있다).

    별칭 표는 (노드, 별칭)이 자연키라 여러 번 돌려도 쌓이지 않는다."""
    with GraphStore(args.db) as store:
        marks = ",".join("?" * len(args.types))
        rows = store.conn.execute(
            f"""SELECT id, label FROM nodes
                 WHERE id LIKE 'wd:%' AND type IN ({marks})""",
            tuple(args.types),
        ).fetchall()
        if not rows:
            print("  대상 노드가 없습니다.")
            return 0
        print(f"  {'·'.join(args.types)} 노드 {len(rows):,}개 조회 중"
              f" (배치 {len(rows) // 200 + 1}회)...")

        fetcher = Fetcher(DEFAULT_CACHE, min_interval=max(args.interval, 1.5))
        found = wikidata.fetch_aliases(fetcher, [r["id"][len("wd:"):] for r in rows])

        label_of = {r["id"]: r["label"] for r in rows}
        pairs = [
            (f"wd:{qid}", alias)
            for qid, names in found.items()
            for alias in dict.fromkeys(names)
            # 라벨과 같은 별칭은 아무것도 더하지 않는다
            if alias and alias != label_of.get(f"wd:{qid}")
        ]
        before = store.conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
        store.conn.executemany(
            "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)", pairs
        )
        store.conn.commit()
        after = store.conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
        print(f"\n  별칭을 가진 노드 {len(found):,}개 · 이름 {len(pairs):,}개")
        print(f"  별칭 표 {before:,} → {after:,} (새로 {after - before:,}건)")
    return 0


def cmd_relabel(args: argparse.Namespace) -> int:
    """영어로 들어온 노드 이름을 한국어로 바꾼다.

    수집이 라벨을 덮어쓰므로 `ingest`·`scope` 뒤에 다시 돌려야 한다.
    시대 그래프는 별도 파일이니 거기에도 한 번 더:

        uv run histgraph relabel
        uv run histgraph --db data/joseon.sqlite relabel
    """
    from . import labels as labels_mod

    try:
        table = labels_mod.load_table(args.table)
    except (OSError, labels_mod.LabelTableError) as err:
        print(f"  표를 읽지 못했습니다: {err}", file=sys.stderr)
        return 1

    with GraphStore(args.db) as store:
        report = labels_mod.apply_overrides(
            store.conn, table, dry_run=args.dry_run
        )
        head = "바꿀 이름" if args.dry_run else "바꾼 이름"
        print(f"  표 {len(table):,}개 · {head} {len(report.applied):,}개"
              f" · 이미 한국어 {report.already:,}개")
        for node_id, old, new in report.applied[:12]:
            print(f"    {node_id:>16}  {old} → {new}")
        if len(report.applied) > 12:
            print(f"    … 그 밖 {len(report.applied) - 12:,}개")

        if report.absent:
            # 표에는 있는데 그래프에 없는 QID. 시대 그래프에서는 정상이다
            # (조선 그래프에 교황청 직위가 없는 게 당연하다).
            print(f"  이 그래프에 없는 QID {len(report.absent):,}개"
                  f" (예: {', '.join(report.absent[:5])})")

        if report.collisions:
            # 이름을 고치고 나니 같은 이름이 이미 있더라 — 한 인물이 두
            # 노드로 들어와 있다는 뜻이다. 합치는 건 여기서 하지 않는다.
            print(f"\n  ⚠ 같은 이름의 노드가 이미 있는 경우 {len(report.collisions)}건"
                  f" — 중복 의심, 합치지는 않았습니다:")
            for node_id, label, twin in report.collisions[:10]:
                print(f"    {label}: {node_id} ↔ {twin}")

        rest = report.remaining
        if rest:
            by_type: dict[str, int] = {}
            for _, ntype, _ in rest:
                by_type[ntype] = by_type.get(ntype, 0) + 1
            shape = " · ".join(f"{t} {n:,}" for t, n in sorted(
                by_type.items(), key=lambda kv: -kv[1]))
            print(f"\n  아직 한글이 없는 노드 {len(rest):,}개 — {shape}")
            print("    대부분 한자 없이 로마자 표기만 있는 근현대 인물이라"
                  " 음절을 복원할 근거가 없습니다.")
            if args.list_remaining:
                for node_id, ntype, label in rest:
                    print(f"    {ntype:<7} {node_id:>16}  {label}")
        else:
            print("\n  한글이 없는 노드가 없습니다.")
    return 0


def cmd_namu(args: argparse.Namespace) -> int:
    """토막글 작품에 나무위키 개요를 보충한다.

    `enrich` 뒤에 돌린다. 위키백과 본문이 100자 넘게 있는 작품은 손대지
    않고, 한 줄짜리('《태조 왕건》은 영화이다.')만 채운다."""
    from .sources import namu

    fetcher = Fetcher(Path(args.db).parent / "cache", min_interval=max(args.interval, 1.0))
    with GraphStore(args.db) as store:
        print(f"→ 나무위키 개요 보충 중 (설명 {args.min_chars}자 미만인 {', '.join(args.types)})...")
        report = namu.fill(
            store, fetcher, tuple(args.types),
            min_chars=args.min_chars, limit=args.limit,
            dry_run=args.dry_run, refresh=args.refresh,
        )
        filled = report["filled"]
        missed = report["missed"]
        print(f"  대상 {report['candidates']:,}편 · 채움 {len(filled):,} · 못 찾음 {len(missed):,}")
        for _, label, title in filled[: args.show]:
            print(f"    ✓ {label} ← {title}")
        for _, label in missed[: args.show]:
            print(f"    · {label}", file=sys.stderr)
        if args.dry_run:
            print("\n  --dry-run 입니다. 저장하지 않았습니다.")
    return 0


def cmd_redescribe(args: argparse.Namespace) -> int:
    """영어로 들어온 노드 설명을 한국어로 바꾼다.

    `relabel` 이 이름에 하는 일을 설명에 한다. 수집이 설명을 덮어쓸 수
    있으므로 `enrich` 뒤에 다시 돌린다. 시대 그래프는 별도 파일이니
    거기에도 한 번 더:

        uv run histgraph redescribe
        uv run histgraph --db data/joseon.sqlite redescribe
    """
    from . import koreanize

    with GraphStore(args.db) as store:
        report = koreanize.redescribe(store.conn, dry_run=args.dry_run)
        head = "바꿀 설명" if args.dry_run else "바꾼 설명"
        total = len(report.applied) + len(report.cleared)
        print(f"  영어 설명 {total:,}개 · {head} {len(report.applied):,}개"
              f" · 비운 설명 {len(report.cleared):,}개")
        for node_id, old, new in report.applied[:12]:
            print(f"    {node_id:>16}  {old[:44]} → {new}")
        if len(report.applied) > 12:
            print(f"    … 그 밖 {len(report.applied) - 12:,}개")

        if report.cleared:
            # 비운 것은 실패가 아니라 '지어내지 않았다'는 기록이다.
            # 사전에 말을 더하면 다시 돌려서 살릴 수 있으므로 원문은
            # props.desc_en 에 남아 있다.
            print(f"\n  사전에 없어 비운 설명 {len(report.cleared):,}개"
                  " — 원문은 props.desc_en 에 남겼습니다:")
            for node_id, old in report.cleared[:10]:
                print(f"    {node_id:>16}  {old[:64]}")
            if args.list_cleared:
                for node_id, old in report.cleared[10:]:
                    print(f"    {node_id:>16}  {old[:64]}")

        left = koreanize.english_descriptions(store.conn)
        if args.dry_run:
            print("\n  (미리보기라 아직 아무것도 바꾸지 않았습니다)")
        elif left:
            print(f"\n  ⚠ 아직 영어인 설명 {len(left):,}개가 남아 있습니다")
        else:
            print("\n  영어로 뜨는 설명이 없습니다.")
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
                f"    uv run histgraph scope {args.era} --out {candidate}",
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

    p_ev = sub.add_parser("events", help="한국사 주요 사건·단체·개념을 이름으로 직접 수집")
    p_ev.add_argument("--interval", type=float, default=1.0)
    p_ev.add_argument("--intro-only", action="store_true", help="본문 전체 대신 도입부만 (빠름, 서사 얕음)")
    p_ev.add_argument("--kinds", nargs="+", default=["event", "org", "concept"],
                      choices=["event", "org", "concept"],
                      help="수집할 시드 표 (기본: 셋 다)")
    p_ev.add_argument("--eras", nargs="*", default=None,
                      help="이 시대만 (예: 일제강점기 대한제국). 기본은 전부")
    p_ev.set_defaults(func=cmd_events)

    p_ib = sub.add_parser("infobox", help="위키백과 인포박스에서 관계 추출 (LLM 불필요)")
    p_ib.add_argument("--limit", type=int, default=None, help="처리할 문서 수")
    p_ib.add_argument("--interval", type=float, default=0.5)
    p_ib.add_argument("--types", nargs="*", default=["event"],
                      help="대상 노드 타입 (event·person). 인물은 부모·배우자·"
                           "스승을 LLM 없이 준다")
    p_ib.add_argument("--refresh", action="store_true",
                      help="이미 날짜가 있는 사건도 인포박스 값으로 덮어쓴다")
    p_ib.set_defaults(func=cmd_infobox)

    p_en = sub.add_parser("enrich", help="한국어 위키백과 서사로 노드 보강")
    # 기본값 없음 = 남은 것을 다 채운다. 예전 기본값 500 이 화면의 빈
    # 설명칸을 만든 원인이었다 — 차수 1짜리 노드는 순번이 오지 않았다.
    p_en.add_argument("--limit", type=int, default=None,
                      help="보강할 노드 수 (차수 상위순). 기본은 전부")
    from .sources.wikipedia import ALL_WD_TYPES
    p_en.add_argument("--types", nargs="*", default=list(ALL_WD_TYPES))
    p_en.add_argument("--no-fallback", action="store_true",
                      help="위키백과 문서가 없는 노드에 Wikidata 한 줄 설명도 넣지 않기")
    p_en.add_argument("--full", action="store_true", help="도입부 대신 본문 전체 (요청당 1건, 느림)")
    p_en.add_argument("--interval", type=float, default=1.0)
    p_en.add_argument("--refresh", action="store_true", help="이미 산문이 있는 노드도 다시 받기")
    p_en.add_argument("--scope", default=None, help="시대 서브그래프 DB 로 대상 한정")
    p_en.set_defaults(func=cmd_enrich)

    p_prune = sub.add_parser("prune", help="스포츠 이벤트 노드 제거")
    p_prune.add_argument("--labels-only", action="store_true", help="Wikidata 클래스 조회 생략 (빠름)")
    p_prune.set_defaults(func=cmd_prune)
    p_wk = sub.add_parser("works", help="역사를 다룬 작품 명단 (위키백과 분류)")
    p_wk.add_argument("--dry-run", action="store_true", help="저장하지 않고 계획만 출력")
    p_wk.add_argument("--root", default=None, help="시작 분류 (기본: 한국의 역사를 소재로 한 작품)")
    p_wk.add_argument("--depth", type=int, default=None, help="분류를 따라 내려갈 깊이")
    p_wk.add_argument("--show", type=int, default=15, help="출력할 예시 수")
    p_wk.add_argument("--interval", type=float, default=0.3)
    p_wk.add_argument("--no-harvest", dest="harvest", action="store_false",
                      help="작품 문서에서 발표일·원작·소재를 읽는 단계를 건너뜀")
    p_wk.add_argument("--harvest-limit", type=int, default=None,
                      help="문서를 읽을 작품 수 (시험용)")
    p_wk.set_defaults(func=cmd_works)

    p_rc = sub.add_parser("reclassify", help="개념을 사건에서 갈라낸다 (Wikidata 클래스 계층)")
    p_rc.add_argument("--dry-run", action="store_true", help="바꾸지 않고 계획만 출력")
    p_rc.add_argument("--limit", type=int, default=None, help="검사할 사건 노드 수")
    p_rc.add_argument("--show", type=int, default=12, help="출력할 예시 수")
    p_rc.set_defaults(func=cmd_reclassify)
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
    p_ex.add_argument("--max-participants", type=int, default=None,
                      help="참여자가 이만큼 넘게 붙은 사건은 건너뛴다 (비어 있는 쪽부터)")
    p_ex.add_argument("--min-chars", type=int, default=0,
                      help="본문이 이보다 짧은 문서는 건너뛴다")
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

    p_nm = sub.add_parser("namu", help="토막글 작품에 나무위키 개요 보충 (enrich 뒤)")
    p_nm.add_argument("--types", nargs="*", default=["media"])
    p_nm.add_argument("--min-chars", type=int, default=100,
                      help="이 길이 미만인 설명만 보충 (기본 100)")
    p_nm.add_argument("--limit", type=int, default=None, help="보충할 노드 수 (시험용)")
    p_nm.add_argument("--show", type=int, default=20, help="출력할 예시 수")
    p_nm.add_argument("--interval", type=float, default=1.5)
    p_nm.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 출력")
    p_nm.add_argument("--refresh", action="store_true", help="못 찾았다고 표시한 노드도 다시 본다")
    p_nm.set_defaults(func=cmd_namu)

    p_rd = sub.add_parser("redescribe", help="영어로 들어온 설명을 한국어로")
    p_rd.add_argument("--dry-run", action="store_true", help="바꾸지 않고 미리보기")
    p_rd.add_argument("--list-cleared", action="store_true",
                      help="비운 설명을 전부 나열")
    p_rd.set_defaults(func=cmd_redescribe)

    p_sc = sub.add_parser("scope", help="시대(또는 시대 묶음)를 별도 그래프로 추출")
    p_sc.add_argument("era", nargs="+",
                      choices=["joseon", "goryeo", "silla", "goguryeo", "baekje",
                               "ilje", "korea"],
                      help="시대 여럿을 주면 한 DB 에 담는다. 'korea' 는 "
                           "조선~일제강점기 묶음")
    p_sc.add_argument("--out", default=None,
                      help="출력 DB (기본: data/{시대}.sqlite)")
    p_sc.add_argument("--hops", type=int, default=1, help="씨앗에서 확장할 홉 수")
    p_sc.add_argument("--keep-isolated", action="store_true", help="엣지 없는 노드도 유지")
    p_sc.add_argument("--table", type=Path, default=DEFAULT_LABELS,
                      help=f"파생본에 바로 적용할 한국어 라벨 표 (기본 {DEFAULT_LABELS.name})")
    p_sc.set_defaults(func=cmd_scope)

    p_tl = sub.add_parser("timeline", help="연도를 일급 개체로 정규화")
    p_tl.add_argument("--labels-only", action="store_true", help="날짜 속성 연결 생략")
    p_tl.add_argument("--year", type=int, default=None, help="그 해에 무슨 일이 있었는지 확인")
    p_tl.set_defaults(func=cmd_timeline)

    p_sp = sub.add_parser("spans", help="조직·왕조의 존속 기간 보강 (Wikidata P571/P576)")
    p_sp.add_argument("--types", nargs="+", default=["org"],
                      help="채울 노드 타입 (기본: org)")
    p_sp.add_argument("--interval", type=float, default=1.5, help="요청 간격(초)")
    p_sp.set_defaults(func=cmd_spans)

    p_al = sub.add_parser("aliases", help="Wikidata 한국어 별칭 수집 (skos:altLabel)")
    p_al.add_argument("--types", nargs="+",
                      default=["event", "org", "place", "role", "media"],
                      help="채울 노드 타입 (기본: 인물 제외 — 인물은 28,961개라 따로 돌린다)")
    p_al.add_argument("--interval", type=float, default=1.5, help="요청 간격(초)")
    p_al.set_defaults(func=cmd_aliases)

    p_lk = sub.add_parser("links", help="사건끼리의 상하위·전후 관계 (P361/P527/P155/P156)")
    p_lk.add_argument("--interval", type=float, default=1.5, help="요청 간격(초)")
    p_lk.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    p_lk.set_defaults(func=cmd_links)

    p_rg = sub.add_parser("reigns", help="왕의 재위 기간을 직위 엣지에 채운다 (P39 한정어)")
    p_rg.add_argument("--interval", type=float, default=1.5, help="요청 간격(초)")
    p_rg.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    p_rg.set_defaults(func=cmd_reigns)

    p_pr = sub.add_parser(
        "precision",
        help="연도만 아는 날짜의 지어낸 1월 1일을 걷어낸다 (수집 뒤마다)")
    p_pr.add_argument("--interval", type=float, default=1.5, help="요청 간격(초)")
    p_pr.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    p_pr.set_defaults(func=cmd_precision)

    p_rl = sub.add_parser("relabel", help="영어로 들어온 노드 이름을 한국어로 (수집 뒤마다)")
    p_rl.add_argument("--table", type=Path, default=DEFAULT_LABELS,
                      help=f"한국어 라벨 표 (기본 {DEFAULT_LABELS.name})")
    p_rl.add_argument("--dry-run", action="store_true", help="바꾸지 않고 계획만 출력")
    p_rl.add_argument("--list-remaining", action="store_true",
                      help="아직 영문인 노드를 전부 나열 (표에 더 적을 때)")
    p_rl.set_defaults(func=cmd_relabel)

    p_sv = sub.add_parser("serve", help="그래프 탐색 화면 (브라우저)")
    p_sv.add_argument("--era", default="korea",
                      help="띄울 시대 그래프 (data/{era}.sqlite). 'korea' 는 "
                           "조선~일제강점기 묶음")
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
