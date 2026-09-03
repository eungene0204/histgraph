"""나무위키 개요로 작품 설명을 보충한다.

**언제 쓰는가.** 한국어 위키백과에 문서는 있는데 한 줄짜리 토막글인
작품이 많다 — `《태조 왕건》은 영화이다.` 처럼 열네 자로 끝나는 글이
실측 126편이다(작품 660편 중, 100자 미만 기준). 나무위키는 같은 작품에
'개요' 절을 두는 일이 많아 그 절 하나면 설명 칸이 선다. 위키백과 본문이
100자 넘게 있으면 여기 오지 않는다 — 나무위키는 보충이지 교체가 아니다.

**문서를 어떻게 찾는가.** 나무위키에는 API 가 없고 제목 규칙도 위키백과와
다르다. `퐁당퐁당 Love`(위키백과)는 나무위키에서 `퐁당퐁당 LOVE` 고,
`간신 (영화)` 는 `간신(영화)` 다(괄호 앞 띄어쓰기 없음). Wikidata 의
나무위키 ID(P8885)는 토막글 126편 중 2편에만 있어 쓸모가 없다. 그래서
(1) 제목 후보 몇 개를 바로 열어 보고, (2) 다 없으면 제목 검색 결과에서
같은 제목·작품 분류인 것을 고른다.

**문서가 열렸다고 그 작품인 게 아니다.** `창`·`숨`·`카라` 는 동음이의어
문서고, `대원군` 은 인물 문서다. 그래서 분류에 영화·드라마 같은 작품
낱말이 있어야 받아들이고, 동음이의어 문서는 그 안의 링크에서 작품 후보를
한 번 더 찾는다.

라이선스: 나무위키 본문은 CC BY-NC-SA 2.0 KR 이다. `props.desc_source`
에 `namu` 를 적어 두어 어디서 왔는지는 남긴다 (화면에는 출처를 쓰지
않는다 — CLAUDE.md §1).
"""

from __future__ import annotations

import html as html_mod
import logging
import re
import urllib.parse

from ..http import Fetcher
from ..koreanize import has_hangul
from ..store import GraphStore

log = logging.getLogger(__name__)

BASE = "https://namu.wiki"

# 분류에 이 낱말이 하나라도 있어야 작품 문서로 본다
WORK_WORDS = (
    "영화", "드라마", "사극", "뮤지컬", "소설", "만화", "웹툰", "애니메이션",
    "연극", "단막극", "시리즈", "게임", "특집극", "작품",
)
DISAMBIG = "동음이의어"
# '대원군(드라마)' 처럼 같은 제목의 작품을 해마다 절로 나눠 적은 목록 문서
SAME_TITLE = "제목이 같은"
NOT_WORK = ("등장인물", "캐릭터", "출생", "사망", "인물")
NOT_FOUND = "해당 문서를 찾을 수 없습니다"

# props.form → 나무위키 괄호 안에 흔히 쓰는 갈래 이름
FORM_WORDS: dict[str, tuple[str, ...]] = {
    "film": ("영화",),
    "series": ("드라마", "사극", "시트콤"),
    "book": ("소설", "도서", "문학"),
    "stage": ("뮤지컬", "연극", "공연"),
    "game": ("게임",),
}

_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
_HEADING = re.compile(r"<h[1-6][^>]*>.*?</h[1-6]>", re.S)
_S1 = re.compile(r"<h[1-6][^>]*>\s*<a id=['\"]s-1['\"][^>]*>.*?</h[1-6]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_FOOTNOTE = re.compile(r"\[\s*(?:\d+|[A-Za-z가-힣]{1,4}\s*\d*|편집)\s*\]")
_NOTICE = re.compile(
    r"^이 문서[는가에의 ]|스포일러가 포함|\[clearfix\]|^\[?펼치기|접기\]?$"
    r"|자세한 내용은 .*참고하십시오"
)
_CAT_LINK = re.compile(r'href="/w/(%EB%B6%84%EB%A5%98:[^"]+)"')
_SEARCH_HIT = re.compile(
    r'<h4[^>]*>.*?<a href="/w/([^"]+)"[^>]*>.*?</a></h4>\s*<div[^>]*>(.*?)</div>', re.S
)


# --- 문서 읽기 -----------------------------------------------------------

def page_url(title: str) -> str:
    return f"{BASE}/w/{urllib.parse.quote(title, safe='')}"


def fetch_page(fetcher: Fetcher, title: str) -> str | None:
    """문서 HTML. 없는 문서는 None (404 본문에 '찾을 수 없습니다'가 온다)."""
    text = fetcher.get(page_url(title), headers={"Accept": "text/html"})
    if not text or NOT_FOUND in text:
        return None
    return text


def page_categories(page: str) -> list[str]:
    """문서 머리의 분류 이름들 ('분류:' 은 뗀다)."""
    cats: list[str] = []
    for enc in _CAT_LINK.findall(page):
        name = urllib.parse.unquote(enc)
        name = name.split(":", 1)[1] if ":" in name else name
        if name not in cats:
            cats.append(name)
    return cats


def is_work(cats: list[str]) -> bool:
    return any(w in c for c in cats for w in WORK_WORDS)


def paren_fits(title: str, form: str | None) -> bool:
    """제목 괄호의 갈래가 노드 갈래와 어긋나지 않는가.

    '창' 영화 노드에 '창(만화)' 가 붙었다 — 만화 문서인데 분류에
    '한국의 범죄 영화' 가 있어 갈래 검사를 지났다. 괄호는 나무위키가
    그 문서의 갈래를 한 낱말로 밝힌 것이라 분류보다 먼저 본다."""
    words = FORM_WORDS.get(form or "", ())
    if not words:
        return True
    _, paren = split_label(title)
    kinds = [w for w in WORK_WORDS if w in paren]
    return not kinds or any(w in paren for w in words)


def matches(cats: list[str], form: str | None, year: str | None) -> bool:
    """이 문서가 **그 갈래·그 해의** 작품인가.

    제목만 같은 다른 작품이 흔하다 — '태조 왕건' 은 1970년 영화이기도
    하고 2000년 드라마이기도 한데, 나무위키에서 그냥 '태조 왕건' 을 열면
    드라마가 나온다. 갈래를 알면 분류에 그 갈래 낱말이 있어야 하고,
    문서가 연도 분류('2000년 드라마')를 달고 있으면 우리 연도와 맞아야
    한다. 연도 분류가 아예 없는 문서는 갈래만으로 받아들인다.
    """
    if not is_work(cats):
        return False
    # '옥녀' 는 드라마 옥중화의 등장인물 문서였다 — 분류에 '드라마' 가
    # 들어 있어 작품으로 보였다. 인물·캐릭터 문서는 작품이 아니다.
    if any(w in c for c in cats for w in NOT_WORK):
        return False
    words = FORM_WORDS.get(form or "", ())
    if words and not any(w in c for c in cats for w in words):
        return False
    years = {m.group(1) for c in cats for m in [re.match(r"^(\d{4})년", c)] if m}
    if year and years and year not in years:
        return False
    return True


def _clean(fragment: str) -> str:
    # 표·그림·스크립트는 본문이 아니다. 개요 절 머리에 포스터 표가 흔히 온다.
    fragment = re.sub(r"<(table|noscript|script|style|iframe)[^>]*>.*?</\1>", " ",
                      fragment, flags=re.S)
    fragment = re.sub(r"<br[^>]*>", "\n", fragment)
    fragment = re.sub(r"</(p|div|li|ul|ol|blockquote)>", "\n", fragment)
    text = _TAG.sub("", fragment)
    text = html_mod.unescape(text).replace("\xa0", " ")
    text = _FOOTNOTE.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    # '이 문서에 스포일러가 포함되어 있습니다' 같은 틀 문구는 본문이 아니다
    lines = [ln for ln in lines if ln and not _NOTICE.search(ln)]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sections(page: str) -> list[tuple[str, str]]:
    """본문의 절들 [(절 이름, 본문)]. 제목 앞의 글(표·틀)은 버린다."""
    m = _S1.search(page)
    if not m:
        return []
    out: list[tuple[str, str]] = []
    heads = list(_HEADING.finditer(page, m.start()))
    for i, h in enumerate(heads):
        name = _clean(re.sub(r"<a[^>]*href=['\"]/edit/[^>]*>.*?</a>", "", h.group(0)))
        name = re.sub(r"^[\d.]+\s*", "", name).strip()
        body = page[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(page)]
        # 마지막 절 뒤에는 각주·분류·바닥글이 온다
        cut = re.search(r"<div[^>]*class=\"[^\"]*wiki-macro-footnote|<footer", body)
        if cut:
            body = body[: cut.start()]
        out.append((name, _clean(body)))
    return out


def overview(page: str) -> str:
    """첫 절('1. 개요')의 본문. 절이 없으면 빈 문자열.

    나무위키 문서는 거의 예외 없이 '1. 개요' 로 시작한다. 절 이름을 보지
    않고 **첫 번째 제목 뒤부터 다음 제목 앞까지**를 받는다 — 이름이
    '소개'·'설명' 인 문서도 있어서다.
    """
    secs = sections(page)
    return secs[0][1] if secs else ""


# 개요 다음에 붙일 절. 작품 문서의 '개요' 는 방영 일자 한 줄인 경우가 많아
# (실측: 경성스캔들 68자, 교동 마님 44자) 그것만으로는 위키백과 토막글보다
# 짧다. 무슨 이야기인지는 '줄거리' 절에 있다.
STORY_HEADS = ("줄거리", "시놉시스", "스토리", "내용", "소개", "특징", "기획")
MAX_CHARS = 1500


def description_of(page: str) -> str:
    """개요 + 줄거리. 등장인물·시청률·여담 같은 절은 받지 않는다."""
    secs = sections(page)
    if not secs:
        return ""
    parts = [secs[0][1]]
    for name, body in secs[1:]:
        if any(w in name for w in STORY_HEADS) and body:
            parts.append(body)
        if len(parts) >= 3:
            break
    text = "\n\n".join(p for p in parts if p)
    if len(text) > MAX_CHARS:
        cut = text.rfind(".", 0, MAX_CHARS)
        text = text[: cut + 1] if cut > MAX_CHARS // 2 else text[:MAX_CHARS]
    return text.strip()


# --- 제목 찾기 -----------------------------------------------------------

def split_label(label: str) -> tuple[str, str]:
    """'논개 (1973년 영화)' → ('논개', '1973년 영화')."""
    m = _PAREN.search(label)
    if not m:
        return label.strip(), ""
    return label[: m.start()].strip(), m.group(1).strip()


def year_of(start_date: str | None) -> str | None:
    m = re.match(r"^(\d{4})", start_date or "")
    return m.group(1) if m else None


def year_for(label: str, start_date: str | None) -> str | None:
    """작품의 해. 라벨 괄호('궁녀 (1972년 영화)')가 날짜 칸보다 앞선다.

    실측: 날짜 칸이 빈 '궁녀 (1972년 영화)' 가 2007년 영화 문서를,
    '여곡성 (2018년 영화)' 가 1986년 영화 문서를 받았다. 괄호의 해는
    위키백과가 같은 제목을 가르려고 붙인 것이라 가장 믿을 만하다."""
    _, paren = split_label(label)
    m = re.search(r"(\d{4})년", paren)
    return m.group(1) if m else year_of(start_date)


def candidates(label: str, form: str | None, year: str | None) -> list[str]:
    """바로 열어 볼 제목 후보. 가능성 높은 순."""
    base, paren = split_label(label)
    words = FORM_WORDS.get(form or "", ()) or ("영화", "드라마")
    out: list[str] = []

    def add(t: str) -> None:
        if t and t not in out:
            out.append(t)

    add(label.strip())
    if paren:
        add(f"{base}({paren})")
        add(base)
    for w in words:
        if year:
            add(f"{base}({year}년 {w})")
        add(f"{base}({w})")
    if not paren:
        add(base)
    return out


def _norm(t: str) -> str:
    return re.sub(r"[\s:·\-–—!?,.'\"《》〈〉]", "", t).lower()


def search_titles(fetcher: Fetcher, base: str) -> list[tuple[str, str]]:
    """제목 검색 결과 [(문서 제목, 결과 요약문)]. 분류·틀·파일·하위 문서는 뺀다."""
    page = fetcher.get(
        f"{BASE}/Search",
        {"q": base, "target": "title"},
        headers={"Accept": "text/html"},
    )
    hits: list[tuple[str, str]] = []
    for enc, snippet in _SEARCH_HIT.findall(page or ""):
        title = urllib.parse.unquote(enc)
        if ":" in title.split("(", 1)[0] or "/" in title:
            continue
        hits.append((title, _clean(snippet)))
    return hits


def pick_from_search(
    hits: list[tuple[str, str]], label: str, year: str | None, form: str | None = None,
) -> list[str]:
    """검색 결과 중 같은 작품일 법한 제목들. 연도가 맞는 것을 앞에 둔다.

    문서를 열면 `matches` 가 다시 재므로 여기서는 후보를 넓게 잡되,
    갈래를 알면 그 갈래 낱말이 요약이나 괄호에 있어야 한다."""
    base, _ = split_label(label)
    want = _norm(base)
    words = FORM_WORDS.get(form or "", ()) or WORK_WORDS
    good: list[tuple[int, str]] = []
    for title, snippet in hits:
        tbase, tparen = split_label(title)
        if _norm(tbase) != want:
            continue
        if not any(w in snippet or w in tparen for w in words):
            continue
        score = 0
        if year and year in tparen:
            score += 2
        if year and year in snippet:
            score += 1
        good.append((-score, title))
    good.sort()
    return [t for _, t in good]


def disambig_links(page: str, label: str) -> list[str]:
    """동음이의어 문서 안에서 같은 제목의 작품 문서 링크."""
    base, _ = split_label(label)
    want = _norm(base)
    out: list[str] = []
    for enc in re.findall(r"href=['\"]/w/([^'\"#?]+)['\"]", page):
        title = urllib.parse.unquote(enc)
        tbase, tparen = split_label(title)
        if tparen and _norm(tbase) == want and any(w in tparen for w in WORK_WORDS):
            if title not in out:
                out.append(title)
    return out


# --- 채우기 ----------------------------------------------------------------

def find_overview(
    fetcher: Fetcher, label: str, form: str | None, year: str | None,
) -> tuple[str, str] | None:
    """(문서 제목, 개요 본문). 못 찾으면 None."""
    tried: set[str] = set()
    queue = candidates(label, form, year)
    searched = False
    while queue or not searched:
        if not queue:
            searched = True
            queue = pick_from_search(
                search_titles(fetcher, split_label(label)[0]), label, year, form)
            if not queue:
                break
        title = queue.pop(0)
        if title in tried:
            continue
        tried.add(title)
        page = fetch_page(fetcher, title)
        if page is None:
            continue
        cats = page_categories(page)
        if DISAMBIG in " ".join(cats) or DISAMBIG in title:
            queue = [t for t in disambig_links(page, label) if t not in tried] + queue
            continue
        if any(SAME_TITLE in c for c in cats):
            # 해마다 절이 있는 목록 문서. 우리 해의 절이 있으면 그것을 받고,
            # 없으면 안에 걸린 작품 문서를 후보로 넣는다.
            text = year_section(page, year)
            if text and has_hangul(text):
                return title, text
            queue = [t for t in disambig_links(page, label) if t not in tried] + queue
            continue
        if not paren_fits(title, form) or not matches(cats, form, year):
            continue
        text = description_of(page)
        if text and has_hangul(text):
            return title, text
    return None


def year_section(page: str, year: str | None) -> str:
    """절 이름에 우리 해가 든 절('1972년 MBC 드라마')의 본문."""
    if not year:
        return ""
    for name, body in sections(page):
        if year in name and body:
            return body[:MAX_CHARS]
    return ""


def fill(
    store: GraphStore,
    fetcher: Fetcher,
    node_types: tuple[str, ...] = ("media",),
    *,
    min_chars: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
) -> dict[str, object]:
    """설명이 비었거나 `min_chars` 미만인 작품에 나무위키 개요를 넣는다.

    지금 설명보다 길 때만 바꾼다. 한 번 못 찾은 노드는 `props.no_namu` 로
    표시해 다음 실행이 같은 요청을 반복하지 않게 한다 (`refresh` 면 무시).
    """
    marks = ",".join("?" * len(node_types))
    skip = "" if refresh else "AND json_extract(props, '$.no_namu') IS NULL"
    rows = store.conn.execute(
        f"""SELECT id, label, description, start_date,
                   json_extract(props, '$.form') AS form
              FROM nodes
             WHERE type IN ({marks})
               AND (description IS NULL OR length(trim(description)) < ?)
               {skip}
          ORDER BY label""",
        (*node_types, min_chars),
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]

    filled: list[tuple[str, str, str]] = []
    missed: list[tuple[str, str]] = []
    for r in rows:
        found = find_overview(fetcher, r["label"], r["form"], year_for(r["label"], r["start_date"]))
        cur = (r["description"] or "").strip()
        if found:
            # 나무위키 글이 더 길면 바꾸고, 짧으면 토막글 뒤에 덧붙인다 —
            # '개요' 가 방영 일자 한 줄뿐인 문서도 그 한 줄은 새 정보다.
            title, text = found
            if len(text) > len(cur):
                new_desc, source = text, "namu"
            else:
                new_desc, source = f"{cur}\n\n{text}", "kowiki+namu"
            filled.append((r["id"], r["label"], title))
            if not dry_run:
                store.conn.execute(
                    """UPDATE nodes
                          SET description = ?,
                              props = json_set(
                                  json_remove(COALESCE(NULLIF(props,''), '{}'), '$.no_namu'),
                                  '$.desc_source', ?,
                                  '$.namu_url', ?),
                              updated_at = datetime('now')
                        WHERE id = ?""",
                    (new_desc, source, page_url(title), r["id"]),
                )
        else:
            missed.append((r["id"], r["label"]))
            if not dry_run:
                store.conn.execute(
                    """UPDATE nodes
                          SET props = json_set(COALESCE(NULLIF(props,''), '{}'), '$.no_namu', 1)
                        WHERE id = ?""",
                    (r["id"],),
                )
        if not dry_run:
            store.conn.commit()
        log.info("%s %s → %s", "✓" if found else "·", r["label"], found[0] if found else "없음")

    return {"candidates": len(rows), "filled": filled, "missed": missed}
