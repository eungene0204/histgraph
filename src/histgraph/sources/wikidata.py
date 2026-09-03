"""Wikidata SPARQL 커넥터 — 엣지의 1차 공급원.

국내 공공 API 는 개체(entity)는 잘 주지만 개체 사이의 '관계'는 거의 주지
않는다. 그래프의 가치는 엣지에 있으므로, 관계는 Wikidata 에서 가져와
골격을 세우고 공공데이터로 살을 붙이는 구조를 택했다.

한계(실측): 조선 국적 인물 약 3,400명 중 '참여 사건'(P1344) 엣지는 35개뿐.
인물↔사건 엣지는 결국 텍스트에서 추출해야 한다 — extract 단계의 근거.

쿼리는 관계별로 쪼갰다. 한 쿼리에 OPTIONAL 을 여러 개 물리면 공개
엔드포인트의 60초 제한에 걸린다.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from ..http import Fetcher
from ..ontology import EDGE_TYPES, Edge, Node

log = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
SOURCE = "wd"

# 한국사 관련 국가/왕조 QID.
# 전부 wbsearchentities 로 실측 확인함 — 추측한 QID 는 엉뚱한 개체를 가리킨다
# (Q34049=셈어파, Q28194=독일 가수). `histgraph doctor` 가 라벨을 재검증한다.
POLITIES = {
    "Q28370": "고구려",
    "Q28428": "백제",
    "Q28456": "신라",
    "Q28322": "발해",
    "Q28208": "고려",
    "Q28179": "조선",
    "Q28233": "대한제국",
    "Q884": "대한민국",
    "Q423": "조선민주주의인민공화국",
}

# Wikidata 속성 -> 온톨로지 엣지 타입
PERSON_RELATIONS: dict[str, tuple[str, str]] = {
    "P22": ("child_of", "아버지"),
    "P25": ("child_of", "어머니"),
    "P26": ("spouse_of", "배우자"),
    "P19": ("born_in", "출생지"),
    "P20": ("died_in", "사망지"),
    "P1344": ("participated_in", "참여"),
    "P39": ("held_position", "직위"),
    "P463": ("member_of", "소속"),
    "P170": ("created", "제작자"),
}


# Wikidata 클래스(P31) -> 온톨로지 노드 타입.
# 전부 열거할 수는 없으므로 매칭 실패 시 엣지 종류 기반 추론으로 넘어간다.
WD_CLASS_TO_TYPE: dict[str, str] = {
    "Q5": "person",
    "Q515": "place", "Q486972": "place", "Q56061": "place", "Q82794": "place",
    "Q3957": "place", "Q532": "place", "Q6256": "place", "Q1549591": "place",
    "Q1190554": "event", "Q178561": "event", "Q198": "event", "Q625298": "event",
    "Q13418847": "event", "Q1656682": "event",
    "Q43229": "org", "Q7278": "org", "Q3024240": "org", "Q34770": "org",
    "Q4164871": "role", "Q294414": "role", "Q216107": "role", "Q12737077": "role",
    "Q11424": "media", "Q5398426": "media",
    "Q838948": "artwork", "Q3305213": "artwork",
}


class SparqlError(RuntimeError):
    pass


def _query(fetcher: Fetcher, sparql: str) -> list[dict]:
    """SPARQL 실행 후 바인딩 목록 반환. POST 를 쓰는 이유는 쿼리가 길어
    GET 의 URL 길이 제한에 걸리기 때문.

    실패 시 빈 리스트를 반환하면 '데이터 없음'과 구분되지 않아 조용히
    잘못된 그래프가 만들어진다. 반드시 예외를 던진다."""
    body = urllib.parse.urlencode({"query": sparql, "format": "json"})
    raw = fetcher.post(
        SPARQL_URL,
        {"query": sparql, "format": "json"},
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        return json.loads(raw)["results"]["bindings"]
    except (json.JSONDecodeError, KeyError) as err:
        # 깨진 응답을 캐시에 남겨두면 재실행해도 같은 실패가 반복된다.
        fetcher.invalidate(SPARQL_URL, body=body)
        if raw.lstrip().startswith("{"):
            hint = "응답이 중간에 잘림 — 캐시를 지웠으니 재실행하면 다시 시도합니다"
        elif "timeout" in raw.lower():
            hint = "쿼리 타임아웃(60초) — 더 잘게 쪼갤 것"
        else:
            hint = ""
        raise SparqlError(f"SPARQL 응답 파싱 실패: {raw[:120]} … {hint}") from err


def _safe_query(
    fetcher: Fetcher, sparql: str, desc: str, failures: list[str]
) -> list[dict]:
    """쿼리 하나가 실패해도 수집 전체를 버리지 않는다. 대신 실패를 기록해
    마지막에 반드시 보고한다 — 조용히 넘어가면 결손을 알 수 없다."""
    try:
        return _query(fetcher, sparql)
    except (SparqlError, RuntimeError) as err:
        log.error("쿼리 실패 [%s]: %s", desc, str(err)[:160])
        failures.append(desc)
        return []


def _labels(fetcher: Fetcher, qids: set[str], chunk: int = 400) -> dict[str, tuple[str, str | None]]:
    """QID -> (라벨, P31 타입 QID) 일괄 조회.

    엣지 쿼리에 label service 를 같이 물리면 결과가 커질 때 60초 제한에
    걸린다. 엣지는 QID 만 받고 라벨은 여기서 따로 채운다."""
    out: dict[str, tuple[str, str | None]] = {}
    ordered = sorted(qids)
    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _query(
            fetcher,
            f"""SELECT ?e ?eLabel ?type WHERE {{
                  VALUES ?e {{ {values} }}
                  OPTIONAL {{ ?e wdt:P31 ?type }}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
                }}""",
        )
        for r in rows:
            qid = _qid(_val(r, "e") or "")
            type_uri = _val(r, "type")
            out.setdefault(qid, (_val(r, "eLabel") or qid, _qid(type_uri) if type_uri else None))
    return out


# 진짜 개체 식별자만. Wikidata 는 '값 불명'을 blank node 로 주는데
# (`.well-known/genid/<32자리 해시>`) 그걸 QID 로 받아들이면 라벨이
# 해시인 유령 인물이 그래프에 생긴다. 실측 75개가 그렇게 들어와 있었다 —
# '누구의 어머니는 [알 수 없음]' 이 사람 노드가 된 것이다.
QID_RE = re.compile(r"^[QPL]\d+$")


def is_real_qid(uri: str) -> bool:
    """이 URI 가 실제 Wikidata 개체를 가리키는가."""
    return bool(QID_RE.match(uri.rsplit("/", 1)[-1]))


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _nid(uri_or_qid: str) -> str:
    return f"{SOURCE}:{_qid(uri_or_qid)}"


def _val(binding: dict, key: str) -> str | None:
    item = binding.get(key)
    return item.get("value") if item else None


def verify_polities(fetcher: Fetcher) -> dict[str, str]:
    """설정된 QID 가 실제로 어떤 개체인지 확인 — QID 오타 방지용."""
    values = " ".join(f"wd:{q}" for q in POLITIES)
    rows = _query(
        fetcher,
        f"""SELECT ?e ?eLabel WHERE {{
              VALUES ?e {{ {values} }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
            }}""",
    )
    return {_qid(_val(r, "e") or ""): _val(r, "eLabel") or "" for r in rows}


def fetch_persons(
    fetcher: Fetcher,
    polities: list[str] | None = None,
    limit: int = 20000,
    failures: list[str] | None = None,
) -> list[Node]:
    """정체별로 쪼개 조회한다. 9개를 한 쿼리에 넣으면 타임아웃."""
    polities = polities or list(POLITIES)
    failures = failures if failures is not None else []
    nodes: dict[str, Node] = {}

    for polity in polities:
        rows = _safe_query(
            fetcher,
            f"""SELECT ?p ?pLabel ?birth ?death WHERE {{
                  ?p wdt:P27 wd:{polity} ; wdt:P31 wd:Q5 .
                  OPTIONAL {{ ?p wdt:P569 ?birth }}
                  OPTIONAL {{ ?p wdt:P570 ?death }}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
                }} LIMIT {limit}""",
            f"인물/{POLITIES.get(polity, polity)}",
            failures,
        )
        log.info("Wikidata 인물 %s(%s): %d행", polity, POLITIES.get(polity, "?"), len(rows))

        for r in rows:
            p_uri = _val(r, "p")
            if not p_uri:
                continue
            nid = _nid(p_uri)
            if nid in nodes:  # 복수 국적 인물 — 먼저 본 것 유지
                continue
            nodes[nid] = Node(
                id=nid,
                type="person",
                label=_val(r, "pLabel") or _qid(p_uri),
                source=SOURCE,
                start_date=_iso_date(_val(r, "birth")),
                end_date=_iso_date(_val(r, "death")),
                url=p_uri,
                props={"polity": POLITIES.get(polity, polity)},
            )

    return list(nodes.values())


def fetch_person_edges(
    fetcher: Fetcher,
    polities: list[str] | None = None,
    limit: int = 5000,
    failures: list[str] | None = None,
) -> tuple[list[Node], list[Edge]]:
    """인물의 관계 엣지 + 관계 상대 노드(장소/사건/조직)를 함께 수집.

    상대 노드를 같이 넣지 않으면 전부 댕글링 엣지가 되어 그래프가 그려지지
    않는다."""
    polities = polities or list(POLITIES)
    failures = failures if failures is not None else []
    edges: list[Edge] = []
    targets: dict[str, str] = {}  # 상대 QID -> 추론 노드 타입

    for prop, (edge_type, label) in PERSON_RELATIONS.items():
        for polity in polities:
            # label service 를 빼서 쿼리를 가볍게 유지 — 라벨은 뒤에서 일괄 조회
            rows = _safe_query(
                fetcher,
                f"""SELECT ?p ?o WHERE {{
                      ?p wdt:P27 wd:{polity} ; wdt:P31 wd:Q5 ; wdt:{prop} ?o .
                    }} LIMIT {limit}""",
                f"{prop}/{POLITIES.get(polity, polity)}",
                failures,
            )
            if rows:
                log.info(
                    "Wikidata %s(%s) x %s: %d행",
                    prop, label, POLITIES.get(polity, polity), len(rows),
                )

            for r in rows:
                p_uri, o_uri = _val(r, "p"), _val(r, "o")
                if not p_uri or not o_uri:
                    continue
                # '값 불명'(blank node)은 개체가 아니다. 받아들이면 라벨이
                # 해시인 유령 인물이 생긴다 (`is_real_qid` 주석 참조).
                if not is_real_qid(p_uri) or not is_real_qid(o_uri):
                    continue
                # P22(아버지)/P25(어머니)는 '자녀 -> 부모' 방향이라
                # child_of 스키마와 그대로 일치한다.
                targets.setdefault(_qid(o_uri), _infer_type(edge_type))
                edges.append(
                    Edge(
                        src=_nid(p_uri),
                        dst=_nid(o_uri),
                        type=edge_type,
                        source=SOURCE,
                        label=label,
                        props={"wikidata_property": prop},
                    )
                )

    return _resolve_targets(fetcher, edges, targets)


def fetch_edges_for(
    fetcher: Fetcher,
    qids: list[str],
    failures: list[str] | None = None,
    chunk: int = 100,
) -> tuple[list[Node], list[Edge]]:
    """**지정한 QID** 들의 관계 엣지 + 상대 노드.

    `fetch_person_edges` 는 국적(P27)으로 대상을 고른다. 승격으로 들어온
    인물은 바로 그 국적 태그가 없어서 수집에서 빠진 사람들이라, 같은
    경로로는 몇 번을 다시 돌려도 들어오지 않는다. QID 를 직접 지정하는
    길이 따로 있어야 관계가 따라온다."""
    failures = failures if failures is not None else []
    edges: list[Edge] = []
    targets: dict[str, str] = {}
    ordered = sorted(set(qids))

    for prop, (edge_type, label) in PERSON_RELATIONS.items():
        for i in range(0, len(ordered), chunk):
            values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
            rows = _safe_query(
                fetcher,
                f"""SELECT ?p ?o WHERE {{
                      VALUES ?p {{ {values} }}
                      ?p wdt:{prop} ?o .
                    }}""",
                f"승격보강/{prop}/{i}",
                failures,
            )
            for r in rows:
                p_uri, o_uri = _val(r, "p"), _val(r, "o")
                if not p_uri or not o_uri:
                    continue
                # '값 불명'(blank node)은 개체가 아니다. 받아들이면 라벨이
                # 해시인 유령 인물이 생긴다 (`is_real_qid` 주석 참조).
                if not is_real_qid(p_uri) or not is_real_qid(o_uri):
                    continue
                targets.setdefault(_qid(o_uri), _infer_type(edge_type))
                edges.append(
                    Edge(
                        src=_nid(p_uri),
                        dst=_nid(o_uri),
                        type=edge_type,
                        source=SOURCE,
                        label=label,
                        props={"wikidata_property": prop},
                    )
                )

    log.info("승격 노드 %d개에서 관계 %d건 수집", len(ordered), len(edges))
    return _resolve_targets(fetcher, edges, targets)


def _resolve_targets(
    fetcher: Fetcher, edges: list[Edge], targets: dict[str, str]
) -> tuple[list[Node], list[Edge]]:
    """관계 상대 노드의 라벨·타입을 채우고 스키마에 맞춘다.

    상대 노드를 같이 넣지 않으면 전부 댕글링 엣지가 되어 그래프가
    그려지지 않는다."""
    log.info("관계 상대 노드 %d개 라벨 조회 중...", len(targets))
    resolved = _labels(fetcher, set(targets))

    nodes: list[Node] = []
    # 노드 id 를 그대로 키로 쓴다. _qid() 는 URI 용('/' 분리)이라
    # 'wd:Q123' 같은 노드 id 에 쓰면 통째로 되돌아와 조회가 전부 빗나간다.
    actual_type: dict[str, str] = {}
    for qid, inferred in targets.items():
        label, type_qid = resolved.get(qid, (qid, None))
        # 엣지 종류로 넘겨짚지 않고 실제 P31 을 우선한다. Wikidata 의
        # P463(소속) 대상에는 조직뿐 아니라 사건도 섞여 있다.
        node_type = WD_CLASS_TO_TYPE.get(type_qid or "", inferred)
        node_id = f"{SOURCE}:{qid}"
        actual_type[node_id] = node_type
        nodes.append(
            Node(
                id=node_id,
                type=node_type,
                label=label,
                source=SOURCE,
                url=f"http://www.wikidata.org/entity/{qid}",
            )
        )

    # 실제 타입이 스키마와 안 맞으면 버리지 않고 related_to 로 낮춘다 —
    # 관계 자체는 사실이므로 보존하되 거짓 의미를 부여하지 않는다.
    downgraded = 0
    for e in edges:
        allowed_dst = EDGE_TYPES[e.type][2]
        if actual_type.get(e.dst, "") not in allowed_dst:
            e.props["original_type"] = e.type
            e.type = "related_to"
            downgraded += 1
    if downgraded:
        log.info("스키마 불일치 엣지 %d개를 related_to 로 완화", downgraded)

    # 중복 엣지 제거 (정체별 조회에서 복수 국적 인물이 겹친다)
    unique = {(e.src, e.dst, e.type): e for e in edges}
    return nodes, list(unique.values())


EVENT_CLASSES = {
    "Q1190554": "사건",
    "Q178561": "전투",
    "Q198": "전쟁",
    "Q625298": "조약",
}


def fetch_events(
    fetcher: Fetcher,
    polities: list[str] | None = None,
    limit: int = 20000,
    failures: list[str] | None = None,
) -> tuple[list[Node], list[Edge]]:
    """한국 관련 사건/전투 + 발생 장소 엣지.

    사건 분류(?cls) x 정체(?c) 를 한 쿼리에 넣으면 wdt:P279* 전이 경로가
    폭발해 타임아웃난다. 조합별로 쪼갠다."""
    polities = polities or list(POLITIES)
    failures = failures if failures is not None else []
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    places: set[str] = set()

    # 사건 분류는 VALUES 로 묶고 정체별로만 쪼갠다. 36개 조합으로 나누면
    # 쿼리 수가 많아져 WDQS 레이트리밋("Not writable.")에 걸린다.
    class_values = " ".join(f"wd:{c}" for c in EVENT_CLASSES)

    for polity in polities:
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?eLabel ?cls ?start ?end ?point ?place WHERE {{
                  VALUES ?cls {{ {class_values} }}
                  ?e wdt:P31/wdt:P279* ?cls ; wdt:P17 wd:{polity} .
                  OPTIONAL {{ ?e wdt:P580 ?start }}
                  OPTIONAL {{ ?e wdt:P582 ?end }}
                  OPTIONAL {{ ?e wdt:P585 ?point }}
                  OPTIONAL {{ ?e wdt:P276 ?place }}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
                }} LIMIT {limit}""",
            f"사건/{POLITIES.get(polity, polity)}",
            failures,
        )
        if rows:
            log.info(
                "Wikidata 사건 x %s: %d행", POLITIES.get(polity, polity), len(rows)
            )

        for r in rows:
            e_uri = _val(r, "e")
            if not e_uri:
                continue
            eid = _nid(e_uri)
            if eid not in nodes:
                cls_uri = _val(r, "cls")
                nodes[eid] = Node(
                    id=eid,
                    type="event",
                    label=_val(r, "eLabel") or _qid(e_uri),
                    source=SOURCE,
                    # 짧은 사건은 P580/P582 없이 P585(시점)만 갖는다.
                    # 실측: 병자호란(Q487757)이 그래서 무연대로 들어왔고,
                    # 죽은 사람의 '참여'를 연대 검사가 못 걸렀다.
                    start_date=_iso_date(_val(r, "start"))
                    or _iso_date(_val(r, "point")),
                    end_date=_iso_date(_val(r, "end"))
                    or _iso_date(_val(r, "point")),
                    url=e_uri,
                    props={
                        "event_class": EVENT_CLASSES.get(_qid(cls_uri), "사건")
                        if cls_uri
                        else "사건",
                        # **어느 정체에서 걸려 왔는지 적어 둔다.** 쿼리가
                        # `?e wdt:P17 wd:{polity}` 로 물어 놓고 답을 버리고
                        # 있었다. 인물은 처음부터 props.polity 를 적었고
                        # `scope` 가 그걸로 씨앗을 고른다 — 사건은 그게
                        # 없어서 시대 그래프를 뽑을 때 통째로 떨어졌다
                        # (실측: 조선 P17 사건 73건이 그래서 빠졌다).
                        "polity": POLITIES.get(polity, polity),
                    },
                )
            if place_uri := _val(r, "place"):
                places.add(_qid(place_uri))
                edges.append(
                    Edge(src=eid, dst=_nid(place_uri), type="occurred_at", source=SOURCE)
                )

    if places:
        log.info("사건 발생지 %d개 라벨 조회 중...", len(places))
        for qid, (label, _) in _labels(fetcher, places).items():
            nodes.setdefault(
                f"{SOURCE}:{qid}",
                Node(
                    id=f"{SOURCE}:{qid}",
                    type="place",
                    label=label,
                    source=SOURCE,
                    url=f"http://www.wikidata.org/entity/{qid}",
                ),
            )

    unique = {(e.src, e.dst, e.type): e for e in edges}
    return list(nodes.values()), list(unique.values())


def fetch_media(
    fetcher: Fetcher, limit: int = 500, failures: list[str] | None = None
) -> tuple[list[Node], list[Edge]]:
    """한국 영화·드라마와 그것이 다루는 역사 소재(P921) 엣지."""
    failures = failures if failures is not None else []
    rows = _safe_query(
        fetcher,
        f"""SELECT ?w ?wLabel ?date ?subj ?subjLabel WHERE {{
              VALUES ?cls {{ wd:Q11424 wd:Q5398426 }}
              ?w wdt:P31 ?cls ; wdt:P495 wd:Q884 ; wdt:P921 ?subj .
              OPTIONAL {{ ?w wdt:P577 ?date }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
            }} LIMIT {limit}""",
        "영화·드라마",
        failures,
    )

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for r in rows:
        w_uri, s_uri = _val(r, "w"), _val(r, "subj")
        if not w_uri or not s_uri:
            continue
        wid = _nid(w_uri)
        nodes[wid] = Node(
            id=wid,
            type="media",
            label=_val(r, "wLabel") or _qid(w_uri),
            source=SOURCE,
            start_date=_iso_date(_val(r, "date")),
            url=w_uri,
        )
        sid = _nid(s_uri)
        # 소재의 실제 타입은 미확정 — 사건으로 가정하고, 다른 소스가 같은
        # QID 를 더 정확한 타입으로 덮어쓰면 갱신된다.
        nodes.setdefault(
            sid,
            Node(
                id=sid,
                type="event",
                label=_val(r, "subjLabel") or _qid(s_uri),
                source=SOURCE,
                url=s_uri,
            ),
        )
        edges.append(Edge(src=wid, dst=sid, type="depicts", source=SOURCE))

    return list(nodes.values()), edges


def _infer_type(edge_type: str) -> str:
    return {
        "born_in": "place",
        "died_in": "place",
        "participated_in": "event",
        "held_position": "org",
        "member_of": "org",
        "child_of": "person",
        "spouse_of": "person",
        "created": "person",
    }.get(edge_type, "person")


def _iso_date(raw: str | None) -> str | None:
    """'1397-04-18T00:00:00Z' -> '1397-04-18'. 기원전(-)도 보존.

    **Wikidata 는 '값 불명'을 blank node 로 준다.** `wdt:P569` 가
    `http://www.wikidata.org/.well-known/genid/…` 로 오는데, 그대로 담으면
    날짜 칸에 URL 이 들어앉는다. 실측으로 100개 노드가 그렇게 오염돼
    있었고(침류왕·고국원왕·왕인…) 연대를 보는 관문이 전부 헛돌았다.
    날짜로 읽히지 않는 값은 '모름'(None)으로 처리하는 것이 맞다."""
    if not raw:
        return None
    date = raw.split("T", 1)[0]
    # 기원전은 '-0400' 처럼 앞에 부호가 붙는다
    if not re.match(r"^-?\d{1,4}-\d{2}-\d{2}$", date):
        return None
    return date


def spans_from_rows(rows: list[dict]) -> dict[str, tuple[str | None, str | None]]:
    """SPARQL 결과 -> QID 별 (시작, 끝). 네트워크 없이 시험할 수 있게 뗀다.

    **P571(설립)을 먼저 본다.** 왕조·조직에는 설립/해체가 맞는 술어다.
    없을 때만 P580/P582(시작/종료)로 물러난다 — 전쟁처럼 사건에 가깝게
    적힌 조직이 그 짝을 쓴다.

    끝이 시작보다 앞서면 둘 다 버린다. 실측으로 Wikidata 날짜는 지저분해서
    (생년>몰년이 섞여 있다) 뒤집힌 값을 그대로 담으면 연표가 거꾸로 선다."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for r in rows:
        uri = _val(r, "o")
        if not uri or not is_real_qid(uri):
            continue
        start = _iso_date(_val(r, "inception")) or _iso_date(_val(r, "start"))
        end = _iso_date(_val(r, "dissolved")) or _iso_date(_val(r, "end"))
        if start and end and end < start:
            continue
        if not (start or end):
            continue
        # 여러 값이 걸린 개체는 가장 이른 시작·가장 늦은 끝으로 모은다
        # (조선의 P571 은 하나지만, 재건된 조직은 설립일이 둘씩 있다).
        old_start, old_end = out.get(_qid(uri), (None, None))
        out[_qid(uri)] = (
            min(x for x in (start, old_start) if x) if (start or old_start) else None,
            max(x for x in (end, old_end) if x) if (end or old_end) else None,
        )
    return out


def fetch_spans(
    fetcher: Fetcher,
    qids: list[str],
    chunk: int = 200,
    failures: list[str] | None = None,
) -> dict[str, tuple[str | None, str | None]]:
    """조직·왕조의 존속 기간. **수집이 여태 물어본 적 없는 값이다.**

    인물은 P569/P570, 사건은 P580/P582/P585 를 처음부터 가져왔지만 조직은
    다른 노드의 엣지 상대로만 들어와서 라벨과 URL 뿐이었다. 실측: 조선
    그래프의 org 80개(전체 387개) 전부가 날짜 없음이고, 그중에 이 그래프의
    중심인 조선(Q28179)이 있다 — Wikidata 에는 1392-08-13 ~ 1897-10-12 로
    적혀 있는데 우리가 안 물어봤을 뿐이다."""
    out: dict[str, tuple[str | None, str | None]] = {}
    ordered = sorted({q for q in qids if QID_RE.match(q)})
    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?o ?inception ?dissolved ?start ?end WHERE {{
                  VALUES ?o {{ {values} }}
                  OPTIONAL {{ ?o wdt:P571 ?inception }}
                  OPTIONAL {{ ?o wdt:P576 ?dissolved }}
                  OPTIONAL {{ ?o wdt:P580 ?start }}
                  OPTIONAL {{ ?o wdt:P582 ?end }}
                }}""",
            f"존속 기간/{i}",
            failures if failures is not None else [],
        )
        out.update(spans_from_rows(rows))
    return out


def fetch_aliases(
    fetcher: Fetcher, qids: list[str], chunk: int = 200
) -> dict[str, list[str]]:
    """QID -> 한국어 별칭 목록 (skos:altLabel).

    실측: 그래프에 '태종'은 있는데 '이방원'이 없어서, 추출 결과의 절반이
    기존 노드에 붙지 못하고 고아가 됐다. 한 인물이 이름·자·호·묘호로
    불리는 것은 한국사 문헌의 기본 특성이라 별칭 없이는 연결이 안 된다."""
    out: dict[str, list[str]] = {}
    failures: list[str] = []
    ordered = sorted(set(qids))

    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?alias WHERE {{
                  VALUES ?e {{ {values} }}
                  ?e skos:altLabel ?alias .
                  FILTER(LANG(?alias) = "ko")
                }}""",
            f"별칭/{i}",
            failures,
        )
        for r in rows:
            e, a = _val(r, "e"), _val(r, "alias")
            if e and a:
                out.setdefault(_qid(e), []).append(a)

    if failures:
        log.warning("별칭 조회 실패 %d구간", len(failures))
    return out
