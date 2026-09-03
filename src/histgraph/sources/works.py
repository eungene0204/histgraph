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
from .infobox import LINK_SKIP, WIKILINK

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


# --- 인포박스와 인트로에서 곧바로 얻는 것 --------------------------------
# **작품 인포박스에는 소재·배경 칸이 없다.** 실측으로 영화 정보 틀은
# 제목·장르·감독·제작·각본·출연·배급·개봉·시간·나라·등급이고, 텔레비전
# 방송 프로그램 정보 틀은 방송명·장르·방송 기간·방송 채널·기획·연출·
# 극본·출연자·원작이다. "무엇을 다루는가"를 적는 칸이 아예 없다.
#
# 그래도 인포박스가 주는 것이 둘 있다: **발표일**과 **원작**. 발표일은
# 연표의 한 축이고(배경연도와 다른 축이다), 원작은 작품끼리의 엣지다.
# 감독·출연은 뽑지 않는다 — 역사 그래프가 연예인 그래프가 된다.
# 순서가 곧 우선순위다. '제작년도'를 먼저 보면 『한산』이 2020년이 된다 —
# 만든 해와 세상에 나온 해는 다르고, 연표에 서는 것은 나온 해다.
DATE_FIELDS = ("개봉", "방송 기간", "방영 기간", "발매일", "발매", "출간일",
               "공개", "초연", "제작년도", "제작 년도")
ADAPTED_FIELDS = ("원작",)

# 링크 뒤에 이 말이 오면 그 링크는 작품의 소재다. 감독·출연 링크는
# 이런 말을 달고 오지 않는다 (실측: 이 관문 없이 인트로 링크를 다 받으면
# 절반 이상이 배우·감독이다 — 김지운·임권택·하희라·이준익).
SUBJECT_CUE = re.compile(
    r"(?:을|를|의)?\s*(소재로|다룬|다루었|다룬다|다룹니다|그린|그리고 있|"
    r"모티브|주인공으로|중심으로|각색|생애|일생|바탕으로|재구성)"
)

# 링크와 단서 사이에 이 말이 끼면 그 링크는 소재가 아니라 **만든 사람**이다.
# '[[선우휘]]의 소설을 바탕으로' 에서 선우휘는 원작자이지 다뤄진 인물이
# 아니다 — 몰년 관문은 이미 죽은 작가를 막지 못한다(실측: 선우휘·박원양).
CREATOR_NEAR = re.compile(
    r"(소설|작품|만화|희곡|원작|극본|각본|대본|연출|감독|제작|출연|주연|"
    r"각색한|번안|시나리오)"
)

_DATE_FULL = re.compile(r"(\d{4})년[^\d]{0,4}(\d{1,2})월[^\d]{0,4}(\d{1,2})일")
_DATE_YEAR = re.compile(r"(\d{4})년")
_FIELD = re.compile(r"^\s*\|\s*([^=|\n]{1,24}?)\s*=\s*(.*)$", re.M)


def _first_date(value: str) -> str | None:
    """'일반판 : 2022년 7월 27일<br/>감독판 : …' -> '2022-07-27'.

    여러 날짜가 적혀 있으면 **처음 것**을 쓴다. 재방송·감독판·해외개봉이
    뒤에 붙는데, 작품이 세상에 나온 때는 처음 것이다."""
    m = _DATE_FULL.search(value)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _DATE_YEAR.search(value)
    return f"{int(m.group(1)):04d}" if m else None


def parse_work_infobox(wikitext: str) -> dict[str, object]:
    """작품 인포박스에서 발표일과 원작을 읽는다.

    틀 전체가 아니라 `|칸 = 값` 줄만 본다. **첫 틀이 인포박스가 아닌
    경우가 많다** — '{{다른 뜻}}'이 먼저 오는 문서가 실측 60편 중 7편이라,
    칸 이름으로 찾는 편이 안전하다."""
    out: dict[str, object] = {"start": None, "adapted": []}
    dates: dict[str, str] = {}
    for name, value in _FIELD.findall(wikitext):
        if name in DATE_FIELDS and name not in dates:
            found = _first_date(value)
            if found:
                dates[name] = found
        if name in ADAPTED_FIELDS:
            out["adapted"] = [
                m.group(1).split("#")[0].strip()
                for m in WIKILINK.finditer(value)
                if not LINK_SKIP.match(m.group(1))
            ]
    for field in DATE_FIELDS:
        if field in dates:
            out["start"] = dates[field]
            break
    return out


def intro_of(wikitext: str, paragraphs: int = 4) -> str:
    """틀을 걷어낸 도입부. 인포박스 안의 링크를 소재로 오해하지 않게."""
    body = re.sub(r"\{\{[^{}]*(\{\{[^{}]*\}\}[^{}]*)*\}\}", " ", wikitext)
    return "\n".join([p for p in body.split("\n") if p.strip()][:paragraphs])


def subject_links(wikitext: str, window: int = 45) -> list[str]:
    """도입부에서 **소재를 말하는 단서 앞에 붙은** 위키링크만 고른다."""
    intro = intro_of(wikitext)
    out: list[str] = []
    for m in WIKILINK.finditer(intro):
        name = m.group(1).split("#")[0].strip()
        if not name or LINK_SKIP.match(name):
            continue
        tail = intro[m.end() : m.end() + window]
        cue = SUBJECT_CUE.search(tail)
        if not cue:
            continue
        # 링크와 단서 사이에 만든 사람을 가리키는 말이 끼어 있으면 버린다
        if CREATOR_NEAR.search(tail[: cue.start()]):
            continue
        out.append(name)
    return out


def harvest(
    store, fetcher: Fetcher, resolve, limit: int | None = None
) -> dict[str, object]:
    """작품 문서에서 발표일·원작·소재를 곧바로 읽는다 (LLM 없이).

    소재 판정에는 관문이 둘 있다:

      1. **단서 어구.** 링크 뒤에 '소재로'·'다룬'·'그린'·'모티브' 같은
         말이 붙어 있어야 한다. 이게 없으면 인트로 링크의 절반 이상이
         감독·배우다 (실측: 김지운·임권택·하희라·이준익).
      2. **몰년.** 사람은 죽은 뒤라야 소재가 된다. 몰년이 없는 인물은
         잇지 않는다 — 살아 있는 사람이 그 작품에 얽혀 있다면 만든 쪽이지
         다뤄진 쪽일 가능성이 압도적이다. 작품 발표일을 아는 경우에는
         몰년이 그보다 앞서는지도 본다.

    사건·장소·정체에는 몰년 관문을 걸지 않는다 — 배우로 오해될 일이 없다."""
    from .infobox import fetch_wikitext

    rows = store.conn.execute(
        "SELECT id, label, start_date FROM nodes "
        "WHERE type='media' AND id LIKE 'wd:%' ORDER BY id"
    ).fetchall()
    if limit:
        rows = rows[:limit]

    parsed: dict[str, dict] = {}
    for i, r in enumerate(rows, 1):
        try:
            wikitext = fetch_wikitext(fetcher, r["label"])
        except Exception as err:  # noqa: BLE001 — 문서 하나 때문에 멈추지 않는다
            log.warning("본문 실패 (건너뜀) %s: %s", r["label"], str(err)[:80])
            continue
        if not wikitext:
            continue
        info = parse_work_infobox(wikitext)
        info["subjects"] = subject_links(wikitext)
        parsed[r["id"]] = info
        if i % 200 == 0:
            log.info("  작품 %d/%d건 읽음", i, len(rows))

    names = sorted({
        n for info in parsed.values()
        for n in list(info["subjects"]) + list(info["adapted"])
    })
    qids = _resolve_titles(fetcher, names)

    dated: list[tuple[str, str]] = []
    edges: list[Edge] = []
    dropped: list[tuple[str, str, str]] = []
    have_date = {r["id"]: r["start_date"] for r in rows}

    for node_id, info in parsed.items():
        if info["start"] and not have_date.get(node_id):
            dated.append((info["start"], node_id))
        work_year = _year(info["start"] or have_date.get(node_id))

        for name in info["adapted"]:
            target = qids.get(name)
            if target and store.conn.execute(
                "SELECT 1 FROM nodes WHERE id=? AND type IN ('media','artwork')",
                (f"wd:{target}",),
            ).fetchone():
                edges.append(Edge(src=node_id, dst=f"wd:{target}", type="adapted_from",
                                  source=SOURCE, label="인포박스: 원작"))

        for name in info["subjects"]:
            target = qids.get(name)
            if not target:
                continue
            row = store.conn.execute(
                "SELECT id, type, label, end_date FROM nodes WHERE id=?",
                (f"wd:{target}",),
            ).fetchone()
            if not row or row["type"] not in ("person", "event", "place", "org"):
                continue
            if row["id"] == node_id:
                continue
            if row["type"] == "person":
                death = _year(row["end_date"])
                if death is None:
                    dropped.append((node_id, row["label"], "몰년 없음"))
                    continue
                if work_year is not None and death > work_year:
                    dropped.append((node_id, row["label"], "작품보다 나중에 죽음"))
                    continue
            # **장소는 소재가 아니라 배경이다.** '군함도'가 나가사키를,
            # '대호'가 지리산을 다루는 것이 아니라 거기를 배경으로 한다.
            kind = "set_in" if row["type"] == "place" else "depicts"
            edges.append(Edge(src=node_id, dst=row["id"], type=kind,
                              source=SOURCE, label=f"도입부: {name}"))

    unique = {(e.src, e.dst, e.type): e for e in edges}
    return {
        "read": len(parsed),
        "dates": dated,
        "edges": list(unique.values()),
        "dropped": dropped,
    }


def _year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^(-?\d{1,4})", value)
    return int(m.group(1)) if m else None


def _resolve_titles(fetcher: Fetcher, titles: list[str]) -> dict[str, str]:
    """문서 제목 -> QID. `infobox.resolve_titles` 를 그대로 쓴다."""
    from .infobox import resolve_titles

    return resolve_titles(fetcher, titles) if titles else {}
