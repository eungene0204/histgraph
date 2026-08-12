"""위키백과 인포박스에서 관계를 뽑는다 — LLM 없이, 구조에서 직접.

**왜 별도 경로인가.** 인포박스는 이미 구조화된 관계다:

    |지휘관1 = [[삼도수군통제사]] [[이순신]]
    |교전국1 = [[조선]]     |교전국2 = [[도요토미 정권|일본]]
    |장소   = [[울돌목]]

여기서 `이순신 --participated_in--> 명량 해전` 을 얻는 데 언어 이해가
필요 없다. LLM 추출은 서사에 흩어진 관계를 캐는 데 쓰고, 인포박스에
명시된 것은 파싱으로 확실하게 가져오는 편이 빠르고 정확하다.

**핵심은 위키링크가 QID 로 해소된다는 점이다.** `[[이순신]]` -> Q11336 이므로
이미 그래프에 있는 `wd:Q11336` 노드에 그대로 붙는다. 엔티티 해소가 필요 없다.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from ..http import Fetcher
from ..ontology import Edge, Node
from ..store import GraphStore

log = logging.getLogger(__name__)

API_URL = "https://ko.wikipedia.org/w/api.php"
SOURCE = "kowiki:infobox"

# 인포박스 필드 -> (엣지 타입, 기대하는 상대 노드 타입).
# 필드명은 사건 문서 12건을 전수 조사해 실제 빈도로 추린 것이다.
FIELD_RELATIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "지휘관1": ("participated_in", ("person",)),
    "지휘관2": ("participated_in", ("person",)),
    "주요인물1": ("participated_in", ("person",)),
    "주요인물2": ("participated_in", ("person",)),
    "교전국1": ("participated_in", ("org",)),
    "교전국2": ("participated_in", ("org",)),
    "장소": ("occurred_at", ("place",)),
    "지역": ("occurred_at", ("place",)),
}

# 파일·틀·분류 링크는 관계가 아니다
LINK_SKIP = re.compile(r"^(파일|파일명|이미지|File|Image|틀|Template|분류|Category):")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def parse_infobox_links(wikitext: str) -> dict[str, list[str]]:
    """인포박스 필드에서 위키링크 대상을 뽑는다.

    필드 값은 여러 줄에 걸치고 `<br />`, 이미지 링크, 서식이 섞여 있다.
    다음 `|필드 =` 가 나올 때까지를 한 필드의 값으로 본다."""
    out: dict[str, list[str]] = defaultdict(list)
    # 필드 경계로 분할 (줄 시작의 파이프만 필드 구분자로 취급)
    parts = re.split(r"^\s*\|\s*([가-힣A-Za-z0-9_ ]+?)\s*=", wikitext, flags=re.M)
    # parts = [머리말, 필드1, 값1, 필드2, 값2, ...]
    for i in range(1, len(parts) - 1, 2):
        field = parts[i].strip()
        if field not in FIELD_RELATIONS:
            continue
        for target in WIKILINK.findall(parts[i + 1]):
            target = target.strip()
            if target and not LINK_SKIP.match(target):
                out[field].append(target)
    return dict(out)


def resolve_titles(fetcher: Fetcher, titles: list[str]) -> dict[str, str]:
    """위키백과 문서명 -> Wikidata QID (넘겨주기 따라감)."""
    import json

    out: dict[str, str] = {}
    ordered = sorted(set(titles))

    for i in range(0, len(ordered), 50):
        batch = ordered[i : i + 50]
        try:
            raw = fetcher.get(
                API_URL,
                {
                    "action": "query",
                    "prop": "pageprops",
                    "ppprop": "wikibase_item",
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                    "titles": "|".join(batch),
                },
            )
            data = json.loads(raw)
        except Exception as err:
            log.warning("QID 해소 실패 (건너뜀): %s", err)
            continue

        redirect_from = {
            r["to"]: r["from"] for r in data.get("query", {}).get("redirects", [])
        }
        normalized = {
            r["to"]: r["from"] for r in data.get("query", {}).get("normalized", [])
        }
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            qid = page.get("pageprops", {}).get("wikibase_item")
            if not qid:
                continue
            title = page["title"]
            requested = normalized.get(redirect_from.get(title, title), redirect_from.get(title, title))
            out[requested] = qid
            out[title] = qid  # 넘겨주기 이후 이름으로도 찾을 수 있게
    return out


def fetch_wikitext(fetcher: Fetcher, title: str) -> str:
    """문서 도입부(section 0)의 원본 위키텍스트. 인포박스가 여기 있다."""
    import json

    try:
        raw = fetcher.get(
            API_URL,
            {
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "section": "0",
                "format": "json",
                "formatversion": "2",
            },
        )
        return json.loads(raw)["parse"]["wikitext"]
    except Exception as err:
        log.debug("위키텍스트 조회 실패 [%s]: %s", title, err)
        return ""


def _fetch_types(fetcher: Fetcher, qids: set[str]) -> dict[str, str]:
    """QID -> 온톨로지 노드 타입. Wikidata 의 P31 로 판정한다.

    인포박스 필드 이름은 값의 타입을 보장하지 않는다. 링크가 진짜로
    사람인지 장소인지는 Wikidata 에 물어봐야 안다."""
    from .wikidata import WD_CLASS_TO_TYPE, _qid, _safe_query, _val

    out: dict[str, str] = {}
    failures: list[str] = []
    ordered = sorted(qids)

    for i in range(0, len(ordered), 300):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + 300])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?type WHERE {{
                  VALUES ?e {{ {values} }}
                  ?e wdt:P31 ?type .
                }}""",
            f"인포박스타입/{i}",
            failures,
        )
        for r in rows:
            e, t = _val(r, "e"), _val(r, "type")
            if not e or not t:
                continue
            mapped = WD_CLASS_TO_TYPE.get(_qid(t))
            # 한 개체가 여러 P31 을 가질 수 있다. 매핑되는 첫 번째를 쓴다.
            if mapped and _qid(e) not in out:
                out[_qid(e)] = mapped

    if failures:
        log.warning("타입 조회 실패 %d구간 — 해당 링크는 제외됨", len(failures))
    return out


def ingest(
    fetcher: Fetcher, store: GraphStore, limit: int | None = None
) -> tuple[list[Node], list[Edge]]:
    """사건 노드의 인포박스에서 관계를 뽑는다.

    대상은 위키백과 문서를 가진 사건 노드 — `events`/`enrich` 가 채워둔
    `props.kowiki_url` 이 있는 것들이다."""
    import json as _json
    import urllib.parse

    rows = store.conn.execute(
        """SELECT id, label, props FROM nodes
           WHERE type = 'event' AND json_extract(props, '$.kowiki_url') IS NOT NULL"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        log.info("인포박스를 볼 사건 노드가 없습니다 (먼저 `events` 실행)")
        return [], []

    log.info("사건 %d건의 인포박스 파싱 중...", len(rows))

    # 1단계: 인포박스에서 링크 수집
    per_event: dict[str, dict[str, list[str]]] = {}
    all_titles: set[str] = set()
    for r in rows:
        url = _json.loads(r["props"])["kowiki_url"]
        title = urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")
        wikitext = fetch_wikitext(fetcher, title)
        if not wikitext:
            continue
        links = parse_infobox_links(wikitext)
        if links:
            per_event[r["id"]] = links
            all_titles.update(t for ts in links.values() for t in ts)

    log.info("인포박스 보유 %d건, 링크 대상 %d개 해소 중...", len(per_event), len(all_titles))
    qids = resolve_titles(fetcher, list(all_titles))

    # 2단계: 그래프에 이미 있는 노드인지 확인. 있으면 그 타입을 신뢰한다.
    known: dict[str, str] = {}
    if qids:
        ids = [f"wd:{q}" for q in set(qids.values())]
        for i in range(0, len(ids), 500):
            batch = ids[i : i + 500]
            marks = ",".join("?" * len(batch))
            for row in store.conn.execute(
                f"SELECT id, type FROM nodes WHERE id IN ({marks})", batch
            ):
                known[row["id"]] = row["type"]

    # 3단계: 그래프에 없는 QID 의 실제 타입을 Wikidata 에 물어본다.
    # 필드 이름만 믿으면 '작전 중 사망' 같은 주석 링크가 인물이 된다.
    unknown_qids = {q for q in qids.values() if f"wd:{q}" not in known}
    fetched_types = _fetch_types(fetcher, unknown_qids) if unknown_qids else {}

    # 4단계: 엣지 생성
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    skipped_unknown = 0

    for event_id, links in per_event.items():
        for field, targets in links.items():
            edge_type, expected = FIELD_RELATIONS[field]
            for target in targets:
                qid = qids.get(target)
                if not qid:
                    continue
                nid = f"wd:{qid}"
                actual = known.get(nid)
                if actual is None:
                    # 그래프에 없는 개체. **필드 기대 타입으로 가정하면 안 된다** —
                    # 실측: 지휘관1 의 [[작전 중 사망]] 은 전사 표시인데 인물로
                    # 들어왔다. Wikidata 에 실제 타입을 물어보고 맞을 때만 만든다.
                    actual = fetched_types.get(qid)
                    if actual is None or actual not in expected:
                        skipped_unknown += 1
                        continue
                    nodes[nid] = Node(
                        id=nid,
                        type=actual,
                        label=target,
                        source="wd",
                        url=f"https://www.wikidata.org/entity/{qid}",
                        props={"from_infobox": field},
                    )
                elif actual not in expected:
                    # 예: '지휘관1' 의 [[삼도수군통제사]] 는 직위(role)다.
                    # 사람이 아니므로 participated_in 을 붙이면 거짓이 된다.
                    skipped_unknown += 1
                    continue

                edges.append(
                    Edge(
                        src=event_id if edge_type == "occurred_at" else nid,
                        dst=nid if edge_type == "occurred_at" else event_id,
                        type=edge_type,
                        source=SOURCE,
                        # 구조에서 직접 왔지만 파싱이 끼어 있다. 1.0 은 아니다.
                        confidence=0.95,
                        props={"infobox_field": field},
                    )
                )

    unique = {(e.src, e.dst, e.type): e for e in edges}
    log.info(
        "인포박스 관계 %d건 (타입 불일치로 제외 %d건, 신규 노드 %d개)",
        len(unique), skipped_unknown, len(nodes),
    )
    return list(nodes.values()), list(unique.values())
