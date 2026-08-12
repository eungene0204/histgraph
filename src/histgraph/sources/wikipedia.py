"""한국어 위키백과 커넥터 — 서사 코퍼스 공급.

**왜 필요한가.** 국가유산청 `content` 2,903건은 유물 해설문이라
"이 물건이 무엇인가"를 적은 글이다 (27%는 순수 서지·규격 기술). 우리가
필요한 건 "누가 무엇을 했는가"인데, 그건 인물·사건 항목의 서사에 있다.
실록과 백과사전은 활용신청 대기 중이라, 지금 당장 막힘 없이 쓸 수 있는
서사 코퍼스는 한국어 위키백과뿐이다.

**설계.** 새 노드를 만들지 않는다. Wikidata 항목에는 한국어 위키백과
sitelink 가 달려 있으므로, 이미 그래프에 있는 노드의 `description` 을
채우는 방식으로 붙인다. 새로 만들면 엔티티 해소를 또 해야 하지만,
sitelink 를 쓰면 QID 가 곧 키라서 정확히 같은 노드에 꽂힌다.

인증키 불필요. User-Agent 는 반드시 보내야 한다 — 없으면 Wikimedia 가
차단한다(실측: 빈 UA 로 요청하면 'Wikimedia Error' HTML 이 돌아온다).
"""

from __future__ import annotations

import json
import logging
import urllib.parse

from ..http import Fetcher
from ..store import GraphStore

log = logging.getLogger(__name__)

API_URL = "https://ko.wikipedia.org/w/api.php"
SOURCE = "kowiki"

# extracts 는 인트로만 받을 때 한 번에 20건, 본문 전체는 1건이 상한이다.
INTRO_BATCH = 20

# 한국사 주요 사건 시드 목록.
#
# 분류 순회를 먼저 시도했으나 쓸 수 없었다. 한국어 위키백과의 사건 분류는
# 일관성이 없고('한국의_전쟁', '조선의_사건' 등은 아예 없음), 실제 문서에
# 달린 분류는 '1636년 분쟁', '깨진 링크를 가지고 있는 문서' 같은 연도·정비
# 분류가 대부분이다. 도메인 지식으로 직접 나열하는 편이 정확하다.
#
# 시대별로 묶어두면 사건마다 from_period 엣지를 공짜로 얻는다.
EVENT_SEEDS: dict[str, list[str]] = {
    "고구려": ["살수대첩", "안시성 전투", "여수전쟁", "고구려-당 전쟁"],
    "백제": ["황산벌 전투", "관산성 전투", "백강 전투"],
    "신라": [
        "나당전쟁", "매소성 전투", "기벌포 전투", "비담의 난",
        "김헌창의 난", "장보고", "원종·애노의 난",
    ],
    "고려": [
        "거란의 고려 침입", "귀주 대첩", "강조의 정변", "이자겸의 난",
        "묘청의 난", "무신정변", "만적의 난", "고려-몽골 전쟁",
        "처인성 전투", "삼별초", "홍건적의 고려 침공", "황산대첩",
        "진포 해전", "위화도 회군",
    ],
    "조선": [
        # 전기
        "제1차 왕자의 난", "제2차 왕자의 난", "계유정난", "이시애의 난",
        "무오사화", "갑자사화", "중종반정", "기묘사화", "을사사화",
        "삼포왜란", "을묘왜변",
        # 임진왜란
        "임진왜란", "정유재란", "한산도 대첩", "명량 해전", "노량 해전",
        "행주 대첩", "진주성 전투", "칠천량 해전",
        # 후기
        "인조반정", "이괄의 난", "정묘호란", "병자호란", "삼전도의 굴욕",
        "예송논쟁", "경신환국", "기사환국", "갑술환국", "임오화변",
        "홍경래의 난", "임술농민봉기", "신유박해", "기해박해", "병인박해",
        "병인양요", "신미양요", "운요호 사건", "강화도 조약",
    ],
    "대한제국": [
        # '대한제국' 자체는 국가이지 사건이 아니다. 시대 이름과도 같아서
        # 넣으면 from_period 가 자기 자신을 가리키는 자기순환이 된다.
        "임오군란", "갑신정변", "동학 농민 혁명", "갑오개혁", "을미사변",
        "아관파천", "을사조약", "헤이그 특사", "정미의병",
        "국채보상운동", "한일병합조약", "안중근",
    ],
    "일제강점기": [
        "3·1 운동", "대한민국 임시정부", "봉오동 전투", "청산리 전투",
        "6·10 만세운동", "광주학생항일운동", "물산장려운동", "신간회",
        "이봉창", "윤봉길", "조선어학회 사건",
    ],
    "대한민국": [
        "8·15 광복", "제주 4·3 사건", "여수·순천 사건", "한국 전쟁",
        "인천 상륙 작전", "4·19 혁명", "5·16 군사 정변", "10월 유신",
        "부마민주항쟁", "10·26 사건", "12·12 군사 반란",
        "5·18 광주 민주화 운동", "6월 항쟁", "6·29 선언",
    ],
}


def fetch_titles(
    fetcher: Fetcher, qids: list[str], chunk: int = 200
) -> dict[str, str]:
    """Wikidata QID -> 한국어 위키백과 문서명.

    노드 라벨을 그대로 문서명으로 쓰면 안 된다. 우리 라벨은 '조선 세종'
    인데 실제 문서명은 '세종'이라 조회가 빗나간다. sitelink 가 정답이다."""
    from .wikidata import _qid, _safe_query, _val

    out: dict[str, str] = {}
    failures: list[str] = []
    ordered = sorted(set(qids))

    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?item ?title WHERE {{
                  VALUES ?item {{ {values} }}
                  ?a schema:about ?item ;
                     schema:isPartOf <https://ko.wikipedia.org/> ;
                     schema:name ?title .
                }}""",
            f"sitelink/{i}",
            failures,
        )
        for r in rows:
            item, title = _val(r, "item"), _val(r, "title")
            if item and title:
                out[_qid(item)] = title

    if failures:
        log.warning("sitelink 조회 실패 %d구간", len(failures))
    log.info("QID %d개 중 한국어 위키백과 문서 %d개 확인", len(ordered), len(out))
    return out


def _api(fetcher: Fetcher, params: dict[str, str]) -> dict:
    raw = fetcher.get(API_URL, params)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        # UA 누락이면 JSON 이 아니라 HTML 오류 페이지가 온다
        hint = "User-Agent 문제일 수 있음" if raw.lstrip().startswith("<") else ""
        raise RuntimeError(f"위키백과 응답 파싱 실패: {raw[:150]} {hint}") from err


def fetch_extracts(
    fetcher: Fetcher, titles: list[str], full: bool = False
) -> dict[str, str]:
    """문서명 -> 본문 텍스트.

    full=False 는 도입부만 받는다 (인물 항목 기준 900~1,400자). 한 번에
    20건이라 빠르고 싸다. full=True 는 본문 전체지만 요청당 1건이다."""
    out: dict[str, str] = {}
    batch_size = 1 if full else INTRO_BATCH

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "exlimit": str(batch_size),
            "redirects": "1",  # '조선 세종' 같은 넘겨주기도 따라간다
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(batch),
        }
        if not full:
            params["exintro"] = "1"

        try:
            data = _api(fetcher, params)
        except RuntimeError as err:
            log.warning("추출 실패 (건너뜀): %s", err)
            continue

        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            text = (page.get("extract") or "").strip()
            if text:
                out[page["title"]] = text

        if i and i % 200 == 0:
            log.info("  본문 %d/%d건 수집", i, len(titles))

    return out


def fetch_articles(
    fetcher: Fetcher, titles: list[str], full: bool = False
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """문서명 -> {qid, extract, title}. 없는 문서명 목록도 함께 돌려준다.

    extracts 와 pageprops 를 한 요청으로 받는다. QID 를 같이 받아야
    사건 노드를 `wd:Qxxxx` 로 만들 수 있고, 그래야 이미 그래프에 있는
    Wikidata 사건 노드와 자동으로 합쳐진다.

    full=True 는 본문 전체를 받는다. 사건 항목은 도입부가 짧아(평균 380자)
    "누가 무엇을 했는가"가 대부분 본문에 있으므로 사건 수집에는 이쪽이 맞다.
    대신 요청당 1건이라 느리다."""
    found: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    batch_size = 1 if full else INTRO_BATCH

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action": "query",
            "prop": "extracts|pageprops",
            "ppprop": "wikibase_item",
            "explaintext": "1",
            "exlimit": str(batch_size),
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(batch),
        }
        if not full:
            params["exintro"] = "1"
        try:
            data = _api(fetcher, params)
        except RuntimeError as err:
            log.warning("사건 조회 실패 (건너뜀): %s", err)
            missing.extend(batch)
            continue

        # redirects 를 따라가면 응답 title 이 요청 title 과 달라진다.
        # 어느 쪽 이름으로 요청했는지 되짚을 수 있게 매핑을 보관한다.
        redirect_from = {
            r["to"]: r["from"] for r in data.get("query", {}).get("redirects", [])
        }
        normalized = {
            r["to"]: r["from"] for r in data.get("query", {}).get("normalized", [])
        }

        for page in data.get("query", {}).get("pages", []):
            title = page["title"]
            requested = redirect_from.get(title, title)
            requested = normalized.get(requested, requested)
            if page.get("missing"):
                missing.append(requested)
                continue
            qid = page.get("pageprops", {}).get("wikibase_item")
            extract = (page.get("extract") or "").strip()
            if not qid or not extract:
                missing.append(requested)
                continue
            found[requested] = {"qid": qid, "extract": extract, "title": title}

    return found, missing


def ingest_events(
    fetcher: Fetcher,
    store: GraphStore,
    seeds: dict[str, list[str]] | None = None,
    full: bool = True,
) -> tuple[list[Node], list[Edge]]:
    """시드 목록의 사건 문서를 수집해 사건 노드로 만든다.

    차수 상위순으로 고르는 `enrich` 로는 임진왜란·병자호란 같은 핵심
    사건이 잡히지 않는다 — Wikidata 상에서 연결이 적기 때문이다. 이름으로
    직접 지정하는 경로가 따로 필요한 이유다."""
    from ..ontology import Edge, Node
    from ..resolve import PERIOD_TO_POLITY

    seeds = seeds or EVENT_SEEDS
    all_titles = [t for titles in seeds.values() for t in titles]
    title_to_era = {t: era for era, titles in seeds.items() for t in titles}

    log.info("사건 문서 %d건 조회 중 (full=%s)...", len(all_titles), full)
    found, missing = fetch_articles(fetcher, all_titles, full=full)
    if missing:
        # 문서명이 틀렸는지 실제로 없는지 구분이 안 되므로 반드시 보고한다
        log.warning("문서를 찾지 못함 %d건: %s", len(missing), ", ".join(missing))

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for requested, info in found.items():
        nid = f"wd:{info['qid']}"
        era = title_to_era.get(requested, "")
        nodes[nid] = Node(
            id=nid,
            type="event",
            label=info["title"],
            source="wd",  # QID 공간을 공유해야 기존 노드와 합쳐진다
            description=info["extract"],
            url=f"https://www.wikidata.org/entity/{info['qid']}",
            props={
                "kowiki_url": f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(info['title'])}",
                "seed_era": era,
                "seeded": True,
            },
        )
        # 시대 묶음에서 from_period 엣지를 공짜로 얻는다
        polity_qid = PERIOD_TO_POLITY.get(era)
        if polity_qid:
            pid = f"wd:{polity_qid}"
            # 시드 항목이 그 시대의 정체 자신인 경우(예: '대한제국')
            # 자기 자신을 가리키는 엣지가 된다. 방어해둔다.
            if pid != nid:
                nodes.setdefault(
                    pid, Node(id=pid, type="org", label=era, source="wd")
                )
                edges.append(
                    Edge(src=nid, dst=pid, type="from_period", source="kowiki")
                )

    log.info("사건 노드 %d개, 시대 엣지 %d개", len(nodes), len(edges))
    return list(nodes.values()), edges


def enrich(
    fetcher: Fetcher,
    store: GraphStore,
    node_types: tuple[str, ...] = ("person", "event"),
    limit: int = 500,
    full: bool = False,
) -> dict[str, int]:
    """그래프의 Wikidata 노드에 위키백과 서사를 채운다.

    연결 차수가 높은 노드부터 고른다 — 많이 연결된 인물이 문헌에도 많이
    등장하고, 위키백과 항목도 길다. 전부 받으면 3만 건이라 비현실적이다."""
    marks = ",".join("?" * len(node_types))
    rows = store.conn.execute(
        f"""SELECT n.id, n.label, COUNT(e.src) AS degree
              FROM nodes n
              LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
             WHERE n.source = 'wd' AND n.type IN ({marks})
               AND (n.description IS NULL OR length(n.description) < 100)
          GROUP BY n.id
          ORDER BY degree DESC
             LIMIT ?""",
        (*node_types, limit),
    ).fetchall()

    if not rows:
        log.info("보강할 노드가 없습니다")
        return {"titles": 0, "extracts": 0, "updated": 0}

    qid_to_node = {r["id"].split(":", 1)[1]: r["id"] for r in rows}
    titles = fetch_titles(fetcher, list(qid_to_node))
    if not titles:
        return {"titles": 0, "extracts": 0, "updated": 0}

    log.info("본문 %d건 수집 중 (full=%s)...", len(titles), full)
    extracts = fetch_extracts(fetcher, list(titles.values()), full=full)

    # 문서명 -> QID 역인덱스. redirects 를 따라가면 응답의 title 이
    # 요청한 title 과 달라질 수 있어 양쪽으로 찾는다.
    title_to_qid = {t: q for q, t in titles.items()}
    updates = []
    for title, text in extracts.items():
        qid = title_to_qid.get(title)
        if not qid:
            continue
        node_id = qid_to_node.get(qid)
        if node_id:
            updates.append((text, f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(title)}", node_id))

    store.conn.executemany(
        """UPDATE nodes
              SET description = ?,
                  props = json_set(COALESCE(NULLIF(props,''), '{}'), '$.kowiki_url', ?),
                  updated_at = datetime('now')
            WHERE id = ?""",
        updates,
    )
    store.conn.commit()

    log.info(
        "위키백과 보강: 문서명 %d, 본문 %d, 노드 갱신 %d",
        len(titles), len(extracts), len(updates),
    )
    return {"titles": len(titles), "extracts": len(extracts), "updated": len(updates)}
