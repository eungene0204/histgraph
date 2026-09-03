"""한국어 위키백과 분류에서 **역사를 다룬 작품** 명단을 얻는다.

**왜 분류인가.** Wikidata 는 작품 개체는 많이 주지만 역사와 잇는 엣지를
거의 주지 않는다 — 한국 영화 10,074편 중 주제(P921)가 붙은 것이 226편
(2.2%), 드라마 4,374편 중 78편(1.8%)이고, 그나마 대부분이 '조직범죄'·
'자살' 같은 주제어다. 반면 한국어 위키백과의 작품 분류는 사람이 손으로
관리해 두어서, **분류 이름 자체가 관계를 말한다.**

    분류:이순신을 소재로 한 작품     → depicts (누구를 다루는가)
    분류:조선을 배경으로 한 영화     → set_in  (언제·어디가 배경인가)
    분류:조선 역사 드라마            → form    (무슨 매체인가)

실측: 뿌리 하나(`분류:한국의 역사를 소재로 한 작품`)에서 분류 115개,
작품 599편이 나오고, 그중 98%가 QID 를 갖고 있다. 분류에서 곧바로
`depicts` 178건과 `set_in` 274건이 나온다 — **추출 없이** 얻는 엣지다.

`wikipedia.py` 는 "사건 분류는 쓸 수 없다"고 적어 두었다. 사건 쪽은
'1636년 분쟁' 같은 연도·정비 분류가 대부분이라 그렇고, **작품 쪽은
사정이 다르다.** 같은 위키백과라도 분류의 품질이 주제마다 다르다.

인증키 불필요. User-Agent 는 반드시 보낸다.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from ..http import Fetcher
from ..ontology import FORMS, Edge, Node

log = logging.getLogger(__name__)

API_URL = "https://ko.wikipedia.org/w/api.php"
SOURCE = "kowiki"

ROOT_CATEGORY = "분류:한국의 역사를 소재로 한 작품"

# 뿌리에서 4단계까지 내려간다. 실측으로 그 아래는 새 작품이 거의 없고,
# 대신 '분류:연도별 …' 같은 정비 분류로 새어 나간다.
MAX_DEPTH = 4

# 제목의 괄호와 분류 이름에서 매체를 읽는다. 앞의 것이 더 정확하다 —
# '(드라마)'는 그 문서가 무엇인지 말하지만, 분류는 그 작품이 어느 묶음에
# 들어 있는지를 말할 뿐이라 '분류:임진왜란을 소재로 한 작품' 처럼 매체를
# 말하지 않는 것도 많다.
FORM_WORDS: tuple[tuple[str, str], ...] = (
    ("다큐멘터리", "documentary"),
    ("애니메이션", "animation"),
    ("웹 만화", "comic"),
    ("만화", "comic"),
    ("드라마", "series"),
    ("텔레비전", "series"),
    ("영화", "film"),
    ("소설", "book"),
    ("비디오 게임", "game"),
    ("게임", "game"),
    ("뮤지컬", "stage"),
    ("연극", "stage"),
    ("음반", "music"),
    ("노래", "music"),
)

# Wikidata 클래스 → 매체. **라벨 대조로 확인한 것만 넣는다.**
# (Q11424=영화, Q5398426=텔레비전 시리즈, Q7725634=문학 작품, Q7889=비디오
#  게임, Q93204=다큐멘터리 영화, Q571=책, Q8261=소설)
FORM_BY_CLASS: dict[str, str] = {
    "Q11424": "film",
    "Q93204": "documentary",
    "Q5398426": "series",
    "Q7725634": "book",
    "Q571": "book",
    "Q8261": "book",
    "Q7889": "game",
}

# 작품이 아닌 문서가 분류에 섞여 들어온다. 실측으로 목록 문서와 틀이
# 잡혔다. 그 밖의 것(사람·문화유산·국보·병풍…)은 매체 판정이 안 돼서
# 저절로 걸러진다.
NOT_A_WORK = re.compile(r"목록$|^틀:|^위키프로젝트")

# '조선 세종 시기를 배경으로 한 작품' 처럼 왕대까지 적힌 분류가 34개 있다.
# 그 왕대 자체는 노드가 아니므로 왕조로 물러나 잇고, 왕대는 엣지 label 에
# 남긴다 — 나중에 재위 기간으로 연도를 뽑을 때 쓸 근거가 된다.
POLITY_PREFIX = ("조선", "대한제국", "고려", "고구려", "백제", "신라", "발해", "가야")

_SUBJECT_RE = re.compile(r"^분류:(.+?)(?:을|를) 소재로 한 .+$")
_SETTING_RE = re.compile(r"^분류:(.+?)(?:을|를) 배경으로 한 .+$")


def _api(fetcher: Fetcher, params: dict[str, str]) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    raw = fetcher.get(f"{API_URL}?{urllib.parse.urlencode(params)}")
    return json.loads(raw)


def crawl(
    fetcher: Fetcher, root: str = ROOT_CATEGORY, max_depth: int = MAX_DEPTH
) -> dict[str, set[str]]:
    """분류 나무를 훑어 `문서 -> 그 문서가 달린 분류들` 을 만든다.

    분류를 함께 들고 다니는 이유: 매체·소재·배경이 전부 분류 이름에 있다.
    문서만 모으면 그 세 가지를 다시 알아낼 길이 없다."""
    pages: dict[str, set[str]] = {}
    seen = {root}
    frontier: list[tuple[str, int]] = [(root, 0)]

    while frontier:
        category, depth = frontier.pop(0)
        cont: dict[str, str] = {}
        while True:
            data = _api(
                fetcher,
                {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": category,
                    "cmlimit": "500",
                    **cont,
                },
            )
            for m in data.get("query", {}).get("categorymembers", []):
                title = m["title"]
                if title.startswith("분류:"):
                    if depth < max_depth and title not in seen:
                        seen.add(title)
                        frontier.append((title, depth + 1))
                else:
                    pages.setdefault(title, set()).add(category)
            if "continue" not in data:
                break
            cont = data["continue"]

    log.info("분류 %d개에서 문서 %d건", len(seen), len(pages))
    return pages


def page_qids(fetcher: Fetcher, titles: list[str], chunk: int = 50) -> dict[str, str]:
    """문서 제목 -> QID. Wikidata 항목이 없는 문서는 빠진다."""
    out: dict[str, str] = {}
    for i in range(0, len(titles), chunk):
        data = _api(
            fetcher,
            {
                "action": "query",
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "titles": "|".join(titles[i : i + chunk]),
            },
        )
        for page in data.get("query", {}).get("pages", []):
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                out[page["title"]] = qid
    return out


def form_of(title: str, categories: set[str]) -> str | None:
    """제목과 분류에서 매체를 읽는다. 모르면 None."""
    paren = re.search(r"\(([^)]+)\)$", title)
    if paren:
        for word, form in FORM_WORDS:
            if word in paren.group(1):
                return form
    for category in sorted(categories):
        for word, form in FORM_WORDS:
            if word in category:
                return form
    return None


def forms_from_wikidata(fetcher: Fetcher, qids: list[str]) -> dict[str, str]:
    """P31 로 매체를 마저 읽는다 (제목·분류로 못 읽은 것들).

    실측: 제목·분류로 판정 못 한 112건 중 106건이 QID 를 갖고 있었고,
    그중 대부분이 P31 로 갈렸다 — 영화 27, 텔레비전 시리즈 23, 문학 작품
    21. 나머지(사람·국보·병풍·위키미디어 틀)는 애초에 작품이 아니다."""
    from .wikidata import _qid, _safe_query, _val

    out: dict[str, str] = {}
    failures: list[str] = []
    for i in range(0, len(qids), 120):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 120])
        for r in _safe_query(
            fetcher,
            f"SELECT ?e ?c WHERE {{ VALUES ?e {{ {values} }} ?e wdt:P31 ?c }}",
            f"작품클래스/{i}",
            failures,
        ):
            form = FORM_BY_CLASS.get(_qid(_val(r, "c") or ""))
            if form:
                out.setdefault(_qid(_val(r, "e") or ""), form)
    if failures:
        log.warning("클래스 조회 실패 %d건 — 그만큼 매체를 못 읽는다", len(failures))
    return out


def subject_of(category: str) -> str | None:
    """'분류:이순신을 소재로 한 작품' -> '이순신'."""
    m = _SUBJECT_RE.match(category)
    return m.group(1) if m else None


def setting_of(category: str) -> str | None:
    """'분류:조선을 배경으로 한 영화' -> '조선'."""
    m = _SETTING_RE.match(category)
    return m.group(1) if m else None


def polity_of(name: str) -> str | None:
    """'조선 세종 시기' -> '조선'. 왕조 이름으로 시작할 때만."""
    for polity in POLITY_PREFIX:
        if name.startswith(polity + " ") or name.startswith(polity + "의 "):
            return polity
    return None


def build_nodes(
    pages: dict[str, set[str]],
    qids: dict[str, str],
    extra_forms: dict[str, str],
) -> tuple[list[Node], list[tuple[str, str]]]:
    """작품 노드와, 매체를 못 읽어 만들지 않은 문서 목록.

    id 는 QID 가 있으면 `wd:Q…` 를 쓴다. 이미 Wikidata 로 들어온 작품과
    같은 노드가 되어야 하기 때문이다 — 제목으로 따로 만들면 『한산』이
    둘이 된다."""
    nodes: list[Node] = []
    skipped: list[tuple[str, str]] = []

    for title in sorted(pages):
        categories = pages[title]
        if NOT_A_WORK.search(title):
            skipped.append((title, "작품이 아님"))
            continue
        qid = qids.get(title)
        form = form_of(title, categories) or (extra_forms.get(qid) if qid else None)
        if form not in FORMS:
            skipped.append((title, "매체를 모름"))
            continue
        nodes.append(
            Node(
                id=f"wd:{qid}" if qid else f"{SOURCE}:{title}",
                type="media",
                label=title,
                source=SOURCE,
                url=f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                props={"form": form, "categories": sorted(categories)},
            )
        )
    return nodes, skipped


def build_edges(
    nodes: list[Node], resolve: "callable[[str, tuple[str, ...]], str | None]"
) -> tuple[list[Edge], dict[str, int], list[str]]:
    """분류 이름에서 `depicts`·`set_in` 엣지를 만든다.

    `resolve(이름, 허용 타입)` 은 그래프에서 그 이름의 노드를 찾아 준다.
    **하나로 찾아지지 않으면 잇지 않는다** — 후보가 둘이면 잇지 않는다는
    `resolve.link_places` 의 규칙과 같다. 실측으로 '임진왜란'은 노드가
    둘이고 '허준'·'김유신'은 동명이인이 있다."""
    edges: list[Edge] = []
    counts = {"depicts": 0, "set_in": 0}
    unresolved: set[str] = set()

    for node in nodes:
        for category in node.props.get("categories", []):
            name = subject_of(category)
            if name:
                target = resolve(name, ("person", "event", "place", "org"))
                if target and target != node.id:
                    edges.append(
                        Edge(src=node.id, dst=target, type="depicts", source=SOURCE,
                             label=f"분류: {name}")
                    )
                    counts["depicts"] += 1
                elif not target:
                    unresolved.add(name)
                continue
            name = setting_of(category)
            if name:
                allowed = ("period", "org", "place")
                target = resolve(name, allowed)
                if target is None:
                    fallback = polity_of(name)
                    if fallback:
                        target = resolve(fallback, allowed)
                if target and target != node.id:
                    edges.append(
                        Edge(src=node.id, dst=target, type="set_in", source=SOURCE,
                             label=f"분류: {name}")
                    )
                    counts["set_in"] += 1
                elif not target:
                    unresolved.add(name)

    unique = {(e.src, e.dst, e.type): e for e in edges}
    return list(unique.values()), counts, sorted(unresolved)


def backfill_forms(store, fetcher: Fetcher) -> tuple[int, list[tuple[str, str]]]:
    """매체 구분이 빈 작품 노드를 P31 로 채운다.

    `Node` 가 form 없는 작품을 막기 전에 들어온 노드들이 있다. 스키마의
    관문은 새로 만들어지는 노드만 지나므로, 이미 앉아 있는 것은 여기서
    따로 메운다. 못 채운 것은 목록으로 돌려준다 — 조용히 두면 화면에서
    영화와 드라마가 한 덩어리가 된다."""
    rows = store.conn.execute(
        "SELECT id, label FROM nodes WHERE type='media' "
        "AND json_extract(props,'$.form') IS NULL AND id LIKE 'wd:%'"
    ).fetchall()
    if not rows:
        return 0, []

    forms = forms_from_wikidata(fetcher, [r["id"].split(":", 1)[1] for r in rows])
    filled = 0
    for r in rows:
        form = forms.get(r["id"].split(":", 1)[1])
        if not form:
            continue
        store.conn.execute(
            "UPDATE nodes SET props = json_set(props, '$.form', ?), "
            "updated_at = datetime('now') WHERE id = ?",
            (form, r["id"]),
        )
        filled += 1
    store.conn.commit()
    left = [
        (r["id"], r["label"]) for r in rows
        if not forms.get(r["id"].split(":", 1)[1])
    ]
    return filled, left
