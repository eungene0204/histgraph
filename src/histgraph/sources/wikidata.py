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
    # 일제강점기는 왕조가 아니라 통치 기간이지만, Wikidata 는 이 시기의
    # 사람과 사건에 P27/P17 로 이 QID 를 붙인다 (실측: P27 인물 2,082명 ·
    # P17 개체 253건). 여기 없으면 35년치가 통째로 수집되지 않는다 —
    # '근현대는 명단이지 역사가 아니다'의 절반이 이 누락이었다.
    "Q503585": "일제강점기",
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
    # 라벨 대조로 확인한 것만 넣는다 (Q11514315=시대, Q16261338=대한민국 특수부대).
    # 추측한 QID 는 반드시 틀린다 — Q34049 는 고려가 아니라 셈어파였다.
    "Q11514315": "period",
    "Q16261338": "org",
    "Q11424": "media", "Q5398426": "media",
    "Q838948": "artwork", "Q3305213": "artwork",
}


# 작품 클래스 -> 매체 구분(form). 라벨 대조로 확인한 QID 만 쓴다.
MEDIA_CLASS_TO_FORM: dict[str, str] = {
    "Q11424": "film",       # 영화
    "Q5398426": "series",   # 텔레비전 시리즈
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


def fetch_descriptions(
    fetcher: Fetcher, qids: list[str], chunk: int = 300
) -> dict[str, tuple[str, str]]:
    """QID -> (한 줄 설명, 언어). 한국어가 있으면 한국어, 없으면 영어.

    `_labels` 는 라벨과 P31 만 물어본다. 그래서 엣지의 반대편으로 딸려
    들어온 노드는 이름만 있고 설명이 비어 있다 — 화면의 빈 칸은 대부분
    이 경로로 생긴다. 위키백과 문서가 아예 없는 개체에는 이 한 줄이
    유일하게 남는 설명이다.

    영어도 받아 오는 이유: `Q117196164 황진` 의 wd 설명은 'badminton
    player' 다. 조선 인물이 아니라는 뜻이고, 비어 있을 때는 알 수 없던
    사실이다. 다만 **영어 그대로 그래프에 들어가지는 않는다** — 부르는
    쪽(`_fill_from_wikidata`)이 `koreanize` 로 옮겨서 '배드민턴 선수'로
    넣고, 옮기지 못하면 넣지 않는다. 언어를 같이 돌려주는 것은 옮길
    필요가 있는지 부르는 쪽이 알아야 하기 때문이다."""
    out: dict[str, tuple[str, str]] = {}
    ordered = sorted(set(qids))
    failures: list[str] = []

    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?ko ?en WHERE {{
                  VALUES ?e {{ {values} }}
                  OPTIONAL {{ ?e schema:description ?ko FILTER(lang(?ko) = "ko") }}
                  OPTIONAL {{ ?e schema:description ?en FILTER(lang(?en) = "en") }}
                }}""",
            f"description/{i}",
            failures,
        )
        for r in rows:
            qid = _qid(_val(r, "e") or "")
            ko, en = _val(r, "ko"), _val(r, "en")
            if ko and ko.strip():
                out[qid] = (ko.strip(), "ko")
            elif en and en.strip():
                out[qid] = (en.strip(), "en")

    if failures:
        log.warning("설명 조회 실패 %d구간 — 그만큼은 빈 칸으로 남는다", len(failures))
    log.info("QID %d개 중 한 줄 설명 %d개", len(ordered), len(out))
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
    # 매체 구분을 몰라 만들지 못한 작품. 조용히 빠지면 왜 없는지 알 수 없다.
    unformed: list[tuple[str, str]] = []
    # 노드 id 를 그대로 키로 쓴다. _qid() 는 URI 용('/' 분리)이라
    # 'wd:Q123' 같은 노드 id 에 쓰면 통째로 되돌아와 조회가 전부 빗나간다.
    actual_type: dict[str, str] = {}
    for qid, inferred in targets.items():
        label, type_qid = resolved.get(qid, (qid, None))
        # 엣지 종류로 넘겨짚지 않고 실제 P31 을 우선한다. Wikidata 의
        # P463(소속) 대상에는 조직뿐 아니라 사건도 섞여 있다.
        node_type = WD_CLASS_TO_TYPE.get(type_qid or "", inferred)
        node_id = f"{SOURCE}:{qid}"
        props: dict[str, str] = {}
        if node_type == "media":
            # 작품은 매체 구분 없이는 노드가 될 수 없다 (ontology.Node).
            # P31 이 무엇인지 알면 채우고, 모르면 **만들지 않는다** —
            # 관계 상대로 딸려 온 노드라 판정할 근거가 그것뿐이다.
            form = MEDIA_CLASS_TO_FORM.get(type_qid or "")
            if form is None:
                unformed.append((node_id, label))
                continue
            props["form"] = form
        actual_type[node_id] = node_type
        nodes.append(
            Node(
                id=node_id,
                type=node_type,
                label=label,
                source=SOURCE,
                url=f"http://www.wikidata.org/entity/{qid}",
                props=props,
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
    if unformed:
        # 노드를 안 만들었으므로 그 노드로 가는 엣지는 댕글링이 된다.
        # 함께 버려야 그래프가 없는 곳을 가리키지 않는다.
        skipped = {nid for nid, _ in unformed}
        before = len(edges)
        edges[:] = [e for e in edges if e.dst not in skipped]
        log.info(
            "매체 구분을 몰라 만들지 않은 작품 %d개 (엣지 %d건 함께 버림): %s",
            len(unformed), before - len(edges),
            ", ".join(label for _, label in unformed[:5]),
        )

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
    """한국 영화·드라마와 그것이 다루는 소재(P921) 엣지.

    **P921 은 대개 역사가 아니라 주제어다.** 실체를 가리킬 때만 `depicts`,
    나머지는 `about` 으로 나간다. 이 함수만으로는 사건 판정이 끝나지 않으므로
    수집 뒤에 `reclassify` 를 돌려야 한다 — `prune` 과 같은 위치의 필수 단계다."""
    failures = failures if failures is not None else []
    # P921 의 값이 무엇인지 **같은 질의에서 함께 묻는다.** 예전에는 묻지
    # 않고 사건으로 가정했고, 그 한 줄 때문에 '자살'·'조직범죄'가 사건
    # 노드로 앉았다. 실측: 주제 500건 중 447건이 부류(개념)였고 사건은
    # 6.25 전쟁 정도였다.
    #
    # 사건이냐 개념이냐까지 여기서 가르지는 않는다 — 그 판정에 필요한
    # `P31/P279*` 를 이 질의에 얹으면 WDQS 가 504 로 거절한다(실측).
    # 인물 판정만 붙이면 6초에 끝나고, 나머지는 `reclassify` 가 계층을
    # 한 단계씩 걸어 올라가며 마저 가른다.
    rows = _safe_query(
        fetcher,
        f"""SELECT ?w ?wLabel ?date ?cls ?subj ?subjLabel ?isPerson WHERE {{
              VALUES ?cls {{ wd:Q11424 wd:Q5398426 }}
              ?w wdt:P31 ?cls ; wdt:P495 wd:Q884 ; wdt:P921 ?subj .
              OPTIONAL {{ ?w wdt:P577 ?date }}
              BIND(EXISTS {{ ?subj wdt:P31 wd:Q5 }} AS ?isPerson)
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
        # 매체 구분은 질의가 이미 알고 있다 — VALUES 로 고른 클래스가 그것이다.
        # media 노드는 form 없이는 만들어지지 않는다(ontology 참조).
        form = MEDIA_CLASS_TO_FORM.get(_qid(_val(r, "cls") or ""), "film")
        nodes[wid] = Node(
            id=wid,
            type="media",
            label=_val(r, "wLabel") or _qid(w_uri),
            source=SOURCE,
            start_date=_iso_date(_val(r, "date")),
            url=w_uri,
            props={"form": form},
        )
        sid = _nid(s_uri)
        # 판정이 안 서면 **개념으로 떨어뜨린다.** 개념을 사건으로 올리기는
        # 쉽고(`reclassify` 가 한다), 사건 틈에 낀 개념은 나중에
        # 찾아내기 어렵다 — 타입만 봐서는 멀쩡해 보이기 때문이다.
        if _val(r, "isPerson") == "true":
            subj_type, edge_type = "person", "depicts"
        else:
            subj_type, edge_type = "concept", "about"
        nodes.setdefault(
            sid,
            Node(
                id=sid,
                type=subj_type,
                label=_val(r, "subjLabel") or _qid(s_uri),
                source=SOURCE,
                url=s_uri,
            ),
        )
        edges.append(Edge(src=wid, dst=sid, type=edge_type, source=SOURCE))

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
        # P585(시점)는 하루짜리 사건의 유일한 날짜다. 시작과 끝 양쪽에
        # 같은 값을 넣는다 — 실측: 훙커우 공원 사건·종로경찰서 폭탄투척
        # 사건처럼 시드로 들어온 사건 상당수가 P580 없이 P585 만 갖고 있어
        # 연표에 설 자리가 없었다.
        point = _iso_date(_val(r, "point"))
        start = _iso_date(_val(r, "inception")) or _iso_date(_val(r, "start")) or point
        end = _iso_date(_val(r, "dissolved")) or _iso_date(_val(r, "end")) or point
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
            f"""SELECT ?o ?inception ?dissolved ?start ?end ?point WHERE {{
                  VALUES ?o {{ {values} }}
                  OPTIONAL {{ ?o wdt:P571 ?inception }}
                  OPTIONAL {{ ?o wdt:P576 ?dissolved }}
                  OPTIONAL {{ ?o wdt:P580 ?start }}
                  OPTIONAL {{ ?o wdt:P582 ?end }}
                  OPTIONAL {{ ?o wdt:P585 ?point }}
                }}""",
            f"존속 기간/{i}",
            failures if failures is not None else [],
        )
        out.update(spans_from_rows(rows))
    return out


# --- 사건 사이의 뼈대 -------------------------------------------------------
# 상하위(P361 '~의 일부' / P527 '~로 이루어짐')와 전후(P155 '이전' /
# P156 '다음'). 수집이 물어본 적 없는 관계다 — 인물↔사건(P1344)만 가져와서
# **사건끼리는 서로를 모른다**. 실측: '왕자의 난'은 제1차·제2차와 아무
# 엣지도 없이 홀로 서 있었고(연결 0건), '사화'도 무오·갑자·기묘·을사와
# 끊겨 있었다. 화면 연표에서 셋이 나란히 서니 이어져 보였을 뿐이다.
#
# 여기에 P710·P828·P1542·P276 을 같이 두는 이유: 전부 **사건이 자기 쪽에
# 적어 둔 관계**인데 수집이 인물 쪽에서만 물어봤다. 참여(P1344)는 인물의
# 속성이라 사람에게 물으면 나오지만, '이 사건에 누가 참여했나'(P710)는
# 사건의 속성이라 아무도 안 물어봤다 — 실측: 옥포 해전은 이순신과, 신임사화는
# 노론·소론과 끊겨 있었다. 원인(P828)·결과(P1542)는 아예 한 건도 없었다.
EVENT_LINK_PROPS = ("P361", "P527", "P155", "P156", "P710", "P828", "P1542", "P276")


def fetch_event_links(
    fetcher: Fetcher,
    qids: list[str],
    chunk: int = 150,
    failures: list[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """사건 QID 목록 -> (출발, 도착, 엣지 타입, 엣지 라벨).

    Wikidata 는 같은 사실을 양쪽에 적는다 (제1차는 P361 로 '왕자의 난의
    일부', 왕자의 난은 P527 로 '제1차로 이루어짐'; 병인박해는 P1542 로
    '결과는 병인양요', 병인양요는 P828 로 '원인은 병인박해'). 그대로 담으면
    같은 관계가 방향만 다른 엣지 둘이 되므로 **한 방향으로 모은다** —
    하위에서 상위로, 앞선 사건에서 뒤 사건으로, 원인에서 결과로.

    양끝 타입은 여기서 보지 않는다. '일본'이 해전의 참가자로 적혀 있는데
    우리 그래프에서 일본은 place 라 참여 엣지가 될 수 없다 — 그 판정은
    노드 타입을 아는 호출부(cli)가 한다."""
    out: set[tuple[str, str, str, str]] = set()
    ordered = sorted({q for q in qids if QID_RE.match(q)})
    props = " ".join(f"wdt:{p}" for p in EVENT_LINK_PROPS)
    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?prop ?v WHERE {{
                  VALUES ?e {{ {values} }}
                  VALUES ?p {{ {props} }}
                  ?e ?p ?v .
                  BIND(STR(?p) AS ?prop)
                }}""",
            f"사건 관계/{i}",
            failures if failures is not None else [],
        )
        out.update(links_from_rows(rows))
    return sorted(out)


def links_from_rows(rows: list[dict]) -> set[tuple[str, str, str, str]]:
    """SPARQL 결과 -> 한 방향으로 모은 관계 집합. 네트워크 없이 시험한다."""
    out: set[tuple[str, str, str, str]] = set()
    for r in rows:
        e, v, prop = _val(r, "e"), _val(r, "v"), _val(r, "prop") or ""
        if not (e and v and is_real_qid(e) and is_real_qid(v)):
            continue
        a, b = _qid(e), _qid(v)
        if a == b:            # 자기 자신의 일부인 사건은 없다
            continue
        prop = prop.rsplit("/", 1)[-1]
        if prop == "P361":    # a 는 b 의 일부
            out.add((a, b, "part_of", ""))
        elif prop == "P527":  # b 는 a 의 일부 — 방향을 뒤집어 담는다
            out.add((b, a, "part_of", ""))
        elif prop == "P156":  # a 다음이 b
            out.add((a, b, "related_to", "다음"))
        elif prop == "P155":  # a 이전이 b — 앞선 쪽을 출발로
            out.add((b, a, "related_to", "다음"))
        elif prop == "P710":  # b 가 a 에 참여했다 (사건이 적어 둔 참가자)
            out.add((b, a, "participated_in", ""))
        elif prop == "P828":  # a 의 원인이 b — 원인에서 결과로
            out.add((b, a, "related_to", "원인"))
        elif prop == "P1542":  # a 의 결과가 b
            out.add((a, b, "related_to", "원인"))
        elif prop == "P276":  # a 가 b 에서 일어났다
            out.add((a, b, "occurred_at", ""))
    return out


# --- 재위 -----------------------------------------------------------------
# 재위는 직위(P39)에 붙은 값이 아니라 **그 직위를 언제부터 언제까지 맡았나**
# 라서, 문장(statement)의 한정어(pq:P580/P582)에만 있다. `wdt:` 로는 절대
# 안 나오고, 그래서 우리 held_position 엣지 552개는 전부 날짜가 없었다.
MONARCH_ROOT = "Q116"            # 군주
# 왕비·황후도 P279* 로 군주에 닿는다 (조선 왕비 → 왕비 → 여왕 → …).
# 배우자로 있었던 기간은 재위가 아니므로 갈라낸다. 실측으로 이 두 줄이
# 없으면 조선 왕비 35명이 왕과 같은 띠에 선다.
CONSORT_ROOTS = ("Q719039", "Q7723211")   # 왕비 · 황후


def fetch_monarch_positions(
    fetcher: Fetcher,
    qids: list[str],
    chunk: int = 150,
    failures: list[str] | None = None,
) -> dict[str, str]:
    """직위 QID 중 '군주 자리'만 골라 라벨과 함께 돌려준다.

    목록을 코드에 박지 않는 이유: 왕조마다 직위 항목이 다르다. 조선은
    '조선 임금'(Q22304810)이라는 전용 항목을 쓰지만 고려 임금들은 일반
    항목인 '군주'(Q116)·'왕(王)'(Q12087706)에 걸려 있다 — 박아 두면 고려가
    통째로 빠진다. 계층(P279*)에 물어보면 그래프에 무엇이 들어오든 걸린다."""
    out: dict[str, str] = {}
    ordered = sorted({q for q in qids if QID_RE.match(q)})
    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?pos ?posLabel WHERE {{
                  VALUES ?pos {{ {values} }}
                  ?pos wdt:P279* wd:{MONARCH_ROOT} .
                  {"".join(f"FILTER NOT EXISTS {{ ?pos wdt:P279* wd:{r} }} "
                           for r in CONSORT_ROOTS)}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
                }}""",
            f"군주 직위/{i}",
            failures if failures is not None else [],
        )
        for r in rows:
            uri = _val(r, "pos")
            if uri and is_real_qid(uri):
                out[_qid(uri)] = _val(r, "posLabel") or _qid(uri)
    return out


def fetch_reigns(
    fetcher: Fetcher,
    persons: list[str],
    positions: list[str],
    chunk: int = 80,
    failures: list[str] | None = None,
) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """(인물, 직위) -> (재위 시작, 재위 끝).

    한 인물이 같은 자리에 두 번 앉기도 하고(복위), 자리를 옮기기도 한다
    (고종은 조선 임금이었다가 대한제국 황제가 된다). 그래서 열쇠가 인물
    하나가 아니라 (인물, 직위) 짝이고, 같은 짝이 여러 번 나오면 가장 이른
    시작과 가장 늦은 끝으로 모은다.

    **날짜가 없는 문장도 있다.** 추존왕(원종)은 '조선 임금' 자리를 갖고
    있지만 한정어가 비어 있다 — 재위한 적이 없기 때문이다. 그런 짝은
    아예 담지 않는다. 없는 것을 0년으로 채우면 연표에 없던 왕이 선다."""
    out: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    if not positions:
        return out
    pos_values = " ".join(f"wd:{q}" for q in sorted(set(positions)) if QID_RE.match(q))
    ordered = sorted({q for q in persons if QID_RE.match(q)})
    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])
        rows = _safe_query(
            fetcher,
            f"""SELECT ?p ?pos ?s ?e WHERE {{
                  VALUES ?p {{ {values} }}
                  VALUES ?pos {{ {pos_values} }}
                  ?p p:P39 ?st . ?st ps:P39 ?pos .
                  OPTIONAL {{ ?st pq:P580 ?s }}
                  OPTIONAL {{ ?st pq:P582 ?e }}
                }}""",
            f"재위/{i}",
            failures if failures is not None else [],
        )
        out.update(reigns_from_rows(rows))
    return out


def reigns_from_rows(
    rows: list[dict],
) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """SPARQL 결과 -> (인물, 직위)별 재위 구간. 네트워크 없이 시험한다."""
    out: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    for r in rows:
        p_uri, pos_uri = _val(r, "p"), _val(r, "pos")
        if not (p_uri and pos_uri and is_real_qid(p_uri) and is_real_qid(pos_uri)):
            continue
        start, end = _iso_date(_val(r, "s")), _iso_date(_val(r, "e"))
        if not (start or end):
            continue
        # 뒤집힌 값은 버린다. 문자열 비교로도 되는 것은 둘 다 같은
        # 자릿수의 ISO 날짜일 때뿐이라, 해는 부호 있는 정수로 본다.
        if start and end and (_year_num(end), end) < (_year_num(start), start):
            continue
        key = (_qid(p_uri), _qid(pos_uri))
        old_start, old_end = out.get(key, (None, None))
        out[key] = (
            min((x for x in (start, old_start) if x),
                key=lambda d: (_year_num(d), d), default=None),
            max((x for x in (end, old_end) if x),
                key=lambda d: (_year_num(d), d), default=None),
        )
    return out


def _year_num(date: str) -> int:
    """'-0057-01-01' -> -57. 기원전을 문자열로 비교하면 순서가 뒤집힌다."""
    neg = date.startswith("-")
    return -int(date.lstrip("-").split("-", 1)[0]) if neg else int(date.split("-", 1)[0])


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
