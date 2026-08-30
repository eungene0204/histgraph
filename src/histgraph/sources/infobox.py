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

from ..extract import lifespan_conflict
from ..http import Fetcher
from ..ontology import Edge, Node
from ..store import GraphStore

log = logging.getLogger(__name__)

API_URL = "https://ko.wikipedia.org/w/api.php"
SOURCE = "kowiki:infobox"

# 인포박스 필드 -> (엣지 타입, 기대하는 상대 노드 타입, 방향).
#
# **방향을 필드마다 적어야 하는 이유.** 인포박스 필드는 문서 주인을 기준
# 으로 쓰여 있어서 관계의 방향이 필드마다 다르다. `아버지 = [[안중관]]` 은
# 안방준이 안중관의 자녀지만, `자녀 = [[안후지]]` 는 안후지가 안방준의
# 자녀다. 같은 child_of 인데 방향이 반대다.
#   "out" = 문서 주인 -> 링크 대상,  "in" = 링크 대상 -> 문서 주인
OUT, IN = "out", "in"

# 사건 문서 12건을 전수 조사해 실제 빈도로 추린 필드.
EVENT_FIELDS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "지휘관1": ("participated_in", ("person",), IN),
    "지휘관2": ("participated_in", ("person",), IN),
    "주요인물1": ("participated_in", ("person",), IN),
    "주요인물2": ("participated_in", ("person",), IN),
    "교전국1": ("participated_in", ("org",), IN),
    "교전국2": ("participated_in", ("org",), IN),
    "장소": ("occurred_at", ("place",), OUT),
    "지역": ("occurred_at", ("place",), OUT),
}

# 인물 문서의 인포박스. 산문의 족보 목록과 달리 **필드의 주인이 명확** 해서
# LLM 없이 정확하게 가져올 수 있다 (족보 목록 문제는 extract 쪽 참조).
PERSON_FIELDS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "아버지": ("child_of", ("person",), OUT),
    "어머니": ("child_of", ("person",), OUT),
    "부모": ("child_of", ("person",), OUT),
    "배우자": ("spouse_of", ("person",), OUT),
    "자녀": ("child_of", ("person",), IN),
    "출생지": ("born_in", ("place",), OUT),
    "사망지": ("died_in", ("place",), OUT),
    # 사제 관계는 온톨로지에 전용 타입이 없다. 한국사에서 학맥은 당파와
    # 직결되므로(성혼 문인 -> 서인) 버리지 않고 related_to 로 남긴다.
    "스승": ("related_to", ("person",), OUT),
    "제자": ("related_to", ("person",), IN),
}

FIELDS_BY_TYPE: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {
    "event": EVENT_FIELDS,
    "person": PERSON_FIELDS,
}

# 출생지·사망지는 **가장 구체적인 것 하나만** 쓴다.
#
# 위키백과 지명 필드는 넓은 곳에서 좁은 곳 순으로 쌓여 있고, 거기에
# 현대 행정구역이 섞인다. 실측:
#   이순신 출생지 = [[조선]] [[한성부]]
#   정몽주 사망지 = [[고려]] [[개성특급시]] [[선죽교]] [[조선민주주의인민공화국]] …
# 전부 엣지로 만들면 `정몽주 --died_in--> 조선민주주의인민공화국` 이 생긴다.
# 1392년에 죽은 사람에게 1948년 국가를 붙이는 셈이다. Wikidata 는 북한을
# 국가(Q6256)로 주고 우리 매핑은 국가를 place 로 보므로 **타입 관문이
# 이것을 막지 못한다.**
NARROWEST_ONLY = {"born_in", "died_in"}

# 파일·틀·분류 링크는 관계가 아니다. `#왕자` 같은 문서 내 앵커도 개체가
# 아니다 (실측: 세종의 `자녀 = [[#왕자|18남 4녀]]`).
LINK_SKIP = re.compile(r"^(#|파일|파일명|이미지|File|Image|틀|Template|분류|Category)")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def _template_spans(wikitext: str) -> list[str]:
    """최상위 틀(`{{…}}`) 들을 순서대로. 중첩은 하나로 묶어 돌려준다."""
    spans: list[str] = []
    depth = 0
    start = -1
    i = 0
    while i < len(wikitext) - 1:
        pair = wikitext[i : i + 2]
        if pair == "{{":
            if depth == 0:
                start = i
            depth += 1
            i += 2
            continue
        if pair == "}}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(wikitext[start : i + 2])
                start = -1
            i += 2
            continue
        i += 1
    if depth > 0 and start >= 0:  # 닫히지 않은 틀
        spans.append(wikitext[start:])
    return spans


def infobox_span(wikitext: str, fields: dict | None = None) -> str:
    """대상 필드를 담고 있는 틀의 안쪽만 돌려준다.

    **첫 번째 틀을 쓰면 안 된다.** 문서 앞에 `{{다른 뜻}}`·`{{연도 링크}}`
    같은 작은 틀이 붙어 있는 일이 흔해서(이순신·정몽주·세종이 그렇다)
    인포박스를 놓친다. 필드 이름이 실제로 들어 있는 틀을 고른다.

    **필드 값은 인포박스가 닫히는 곳에서 끝나야 한다.** 다음 `|필드 =` 가
    나올 때까지로 잡으면 마지막 필드가 본문을 통째로 삼킨다. 실측(세종):

        | 자녀 = [[#왕자|18남 4녀]]
        }}
        '''세종'''(… [[1397년]] … [[황희]] … [[장영실]] …

    `자녀` 가 도입부 전체를 먹어 황희·장영실·김종서가 세종의 자녀로
    들어왔다. 중괄호 깊이를 세어 짝이 맞는 `}}` 에서 끊는다 — 값 안에
    `{{font color|…}}` 같은 중첩 틀이 있으므로 단순히 첫 `}}` 를 찾으면
    안 된다."""
    names = fields if fields is not None else EVENT_FIELDS
    spans = _template_spans(wikitext)
    if not spans:
        return ""
    for span in spans:
        if any(re.search(rf"^\s*\|\s*{re.escape(f)}\s*=", span, re.M) for f in names):
            return span
    return ""


def parse_infobox_links(
    wikitext: str, fields: dict[str, tuple[str, tuple[str, ...], str]] | None = None
) -> dict[str, list[str]]:
    """인포박스 필드에서 위키링크 대상을 뽑는다.

    필드 값은 여러 줄에 걸치고 `<br />`, 이미지 링크, 서식이 섞여 있다.
    다음 `|필드 =` 가 나올 때까지를 한 필드의 값으로 본다.

    `fields` 는 볼 필드 표 (기본값은 사건). 노드 타입마다 다르다."""
    if fields is None:
        fields = EVENT_FIELDS
    out: dict[str, list[str]] = defaultdict(list)
    # **인포박스 틀 안쪽만 본다.** 본문까지 보면 마지막 필드가 도입부를
    # 통째로 삼킨다 (`infobox_span` 주석 참조).
    wikitext = infobox_span(wikitext, fields)
    # 필드 경계로 분할 (줄 시작의 파이프만 필드 구분자로 취급)
    parts = re.split(r"^\s*\|\s*([가-힣A-Za-z0-9_ ]+?)\s*=", wikitext, flags=re.M)
    # parts = [머리말, 필드1, 값1, 필드2, 값2, ...]
    for i in range(1, len(parts) - 1, 2):
        field = parts[i].strip()
        if field not in fields:
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
    fetcher: Fetcher,
    store: GraphStore,
    limit: int | None = None,
    node_types: tuple[str, ...] = ("event",),
) -> tuple[list[Node], list[Edge]]:
    """인포박스에서 관계를 뽑는다.

    대상은 위키백과 문서를 가진 노드 — `events`/`enrich` 가 채워둔
    `props.kowiki_url` 이 있는 것들이다. `node_types` 로 사건·인물을
    고른다 (필드 표가 타입마다 다르므로 `FIELDS_BY_TYPE` 참조)."""
    import json as _json
    import urllib.parse

    wanted = tuple(t for t in node_types if t in FIELDS_BY_TYPE)
    if not wanted:
        log.warning("인포박스 필드 표가 없는 타입입니다: %s", node_types)
        return [], []

    marks = ",".join("?" * len(wanted))
    rows = store.conn.execute(
        f"""SELECT id, label, type, props FROM nodes
            WHERE type IN ({marks})
              AND json_extract(props, '$.kowiki_url') IS NOT NULL""",
        wanted,
    ).fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        log.info("인포박스를 볼 노드가 없습니다 (먼저 `events`/`enrich` 실행)")
        return [], []

    log.info("%s 문서 %d건의 인포박스 파싱 중...", "·".join(wanted), len(rows))

    # 1단계: 인포박스에서 링크 수집. 문서 주인의 타입을 같이 들고 다녀야
    # 어느 필드 표로 읽을지, 방향이 어느 쪽인지 정할 수 있다.
    per_subject: dict[str, dict[str, list[str]]] = {}
    subject_types: dict[str, str] = {}
    all_titles: set[str] = set()
    for r in rows:
        url = _json.loads(r["props"])["kowiki_url"]
        title = urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")
        wikitext = fetch_wikitext(fetcher, title)
        if not wikitext:
            continue
        links = parse_infobox_links(wikitext, FIELDS_BY_TYPE[r["type"]])
        if links:
            per_subject[r["id"]] = links
            subject_types[r["id"]] = r["type"]
            all_titles.update(t for ts in links.values() for t in ts)

    log.info("인포박스 보유 %d건, 링크 대상 %d개 해소 중...", len(per_subject), len(all_titles))
    qids = resolve_titles(fetcher, list(all_titles))

    # 2단계: 그래프에 이미 있는 노드인지 확인. 있으면 그 타입을 신뢰한다.
    # 생몰년도 같이 들고 온다 — 가족 관계의 연대 검사에 쓴다.
    known: dict[str, str] = {}
    dates: dict[str, tuple[str | None, str | None]] = {}
    if qids:
        ids = [f"wd:{q}" for q in set(qids.values())]
        for i in range(0, len(ids), 500):
            batch = ids[i : i + 500]
            marks = ",".join("?" * len(batch))
            for row in store.conn.execute(
                f"SELECT id, type, start_date, end_date FROM nodes WHERE id IN ({marks})",
                batch,
            ):
                known[row["id"]] = row["type"]
                dates[row["id"]] = (row["start_date"], row["end_date"])

    # 문서 주인의 생몰년도 필요하다 (관계의 다른 한쪽)
    for sid in per_subject:
        if sid not in dates:
            row = store.conn.execute(
                "SELECT start_date, end_date FROM nodes WHERE id = ?", (sid,)
            ).fetchone()
            if row:
                dates[sid] = (row["start_date"], row["end_date"])

    # 3단계: 그래프에 없는 QID 의 실제 타입을 Wikidata 에 물어본다.
    # 필드 이름만 믿으면 '작전 중 사망' 같은 주석 링크가 인물이 된다.
    unknown_qids = {q for q in qids.values() if f"wd:{q}" not in known}
    fetched_types = _fetch_types(fetcher, unknown_qids) if unknown_qids else {}

    # 4단계: 엣지 생성
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    skipped_unknown = skipped_anachronism = 0

    for subject_id, links in per_subject.items():
        fields = FIELDS_BY_TYPE[subject_types[subject_id]]
        for field, targets in links.items():
            edge_type, expected, direction = fields[field]
            if edge_type in NARROWEST_ONLY and targets:
                targets = targets[-1:]
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

                src, dst = (
                    (subject_id, nid) if direction == OUT else (nid, subject_id)
                )
                if src == dst:
                    # 문서가 자기 자신을 링크한 경우. 자기순환은 만들지 않는다.
                    continue

                # **인포박스의 가족 필드에 먼 조상이 들어 있는 일이 있다.**
                # 실측 13건: `한용운(1879~1944) --child_of--> 한명회(1415~1487)`
                # 464년 차이, `조선 연산군 --child_of--> 조선 광해군` 등.
                # 링크 자체는 QID 로 정확히 해소되므로 타입 관문이 못 막는다.
                # 부모·자녀·배우자는 생애가 겹쳐야 성립한다.
                if lifespan_conflict(
                    edge_type, dates.get(src, (None, None)), dates.get(dst, (None, None))
                ):
                    skipped_anachronism += 1
                    continue
                edges.append(
                    Edge(
                        src=src,
                        dst=dst,
                        type=edge_type,
                        source=SOURCE,
                        # 구조에서 직접 왔지만 파싱이 끼어 있다. 1.0 은 아니다.
                        confidence=0.95,
                        props={"infobox_field": field},
                    )
                )

    unique = {(e.src, e.dst, e.type): e for e in edges}
    log.info(
        "인포박스 관계 %d건 (타입 불일치로 제외 %d건, 연대 충돌로 제외 %d건,"
        " 신규 노드 %d개)",
        len(unique), skipped_unknown, skipped_anachronism, len(nodes),
    )
    return list(nodes.values()), list(unique.values())
