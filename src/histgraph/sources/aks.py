"""한국민족문화대백과사전 (한국학중앙연구원) — 근현대 말뭉치의 **정본**.

사용자가 공공데이터포털에서 받아 준 파일 둘이 `data/raw/` 에 있다:

- `한국학중앙연구원_한국학 전문사전 학술 콘텐츠_20250829.csv` — 항목 75,360건.
  아이디·문서 주소·항목명·원어(한자)·분야·유형·시대·**정의 한 문장**·집필자.
  본문은 없다.
- `한국학중앙연구원_한국민족문화대백과사전_20240130.csv` — 항목명·분야·주소뿐.
  위 파일의 부분집합이라 쓰지 않는다.

본문은 문서 주소(`https://encykorea.aks.ac.kr/Article/E00…`)에 있다.
robots.txt 는 검색·해시태그 페이지만 막고 문서 페이지는 연다. 페이지는
`<section class="content_section">` 마다 `<h3 class="tit">절 제목</h3>` 과
`<div class="detail">본문</div>` 이라 절 단위로 읽힌다 (정의·개설·역사적
배경·경과·결과·의의와 평가 …). '내용 요약'은 사전이 따로 만든 요약이라
본문이 아니고, '참고문헌'은 글이 아니다 — 둘 다 뺀다.

**위키백과보다 앞선다.** 사용자가 이 문서들을 정본이라 했다. 같은 노드에
두 소스의 글이 있으면 역할 판정(`roles`)은 이쪽 문단을 먼저 준다
(`corpus.SOURCE_PRIORITY`).

**항목을 노드에 잇는 규칙은 점수가 아니라 규칙이다** (README '노드 병합은
절반이 틀린다'). 이름을 띄어쓰기 없이 맞추고(`10·26사태` ≠ `10·26 사건`
이지만 `1·4후퇴` = `1·4 후퇴`), 유형이 노드 타입과 맞고, 양쪽 다 그 이름이
하나뿐일 때만 잇는다. 근현대 인물 항목 6,021건 중 291개 이름이 둘 이상이다
(김규식·권준 …) — 그런 이름은 잇지 않는다. 못 이은 항목도 버리지 않고
`aks:E00…` 을 노드 아이디 삼아 말뭉치에 넣는다. `ask` 는 그것도 찾는다.
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "raw"
INDEX_CSV = "한국학중앙연구원_한국학 전문사전 학술 콘텐츠_20250829.csv"
SOURCE = "aks"

# 항목 유형(앞머리) -> 노드 타입. 없는 것은 잇지 않는다.
KIND_TO_TYPE: dict[str, str] = {
    "인물": "person",
    "사건": "event",
    "단체": "org",
    "제도": "concept",
    "개념": "concept",
    "지명": "place",
    "유적": "heritage",
    "유물": "heritage",
    "작품": "media",
}
# 근현대 항목의 시대 앞머리
MODERN_ERAS = ("근대", "현대")
# 본문에서 빼는 절
SKIP_SECTIONS = {"내용 요약", "참고문헌", "관련 미디어", "집필자", "관련 항목"}


@dataclass(slots=True)
class Entry:
    id: str          # E0073678
    url: str
    label: str
    hanja: str
    field: str       # 분야
    kind: str        # 유형 (사건 / 인물/근현대 인물 …)
    era: str         # 시대 (현대/대한민국 …)
    definition: str  # 정의 한 문장

    @property
    def node_type(self) -> str | None:
        return KIND_TO_TYPE.get(self.kind.split("/")[0])

    @property
    def modern(self) -> bool:
        return self.era.startswith(MODERN_ERAS)


def load_index(raw_dir: Path = RAW_DIR) -> list[Entry]:
    """CSV -> 항목 목록. utf-8-sig 다 (BOM 이 있다)."""
    path = raw_dir / INDEX_CSV
    csv.field_size_limit(10**9)
    text = path.read_bytes().decode("utf-8-sig")
    out: list[Entry] = []
    for r in csv.DictReader(io.StringIO(text)):
        eid = (r.get("항목 아이디") or "").strip()
        if not eid:
            continue
        out.append(Entry(
            id=eid,
            url=(r.get("항목 고유 웹주소") or f"https://encykorea.aks.ac.kr/Article/{eid}").strip(),
            label=(r.get("항목명") or "").strip(),
            hanja=(r.get("원어") or "").strip(),
            field=(r.get("항목 분야") or "").strip(),
            kind=(r.get("항목 유형") or "").strip(),
            era=(r.get("시대") or "").strip(),
            definition=(r.get("항목 정의") or "").strip(),
        ))
    return out


# --- 노드에 잇기 -----------------------------------------------------------
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_SPACE = re.compile(r"\s+")


def norm_name(label: str) -> str:
    """'김용현 (군인)' -> '김용현', '1·4 후퇴' -> '1·4후퇴'. 띄어쓰기는 뜻이 아니다."""
    return _SPACE.sub("", _PAREN.sub("", label or "").strip())


# --- 연대 검증 ----------------------------------------------------------------
#
# 2026-09-06 지적의 뿌리. 세종의 휘 '이도'가 조선 후기 의병장 이도(E0044022)의
# 항목을 받았다. "이름·타입이 양쪽에서 하나뿐"이라는 규칙은 **별칭까지
# 이름으로 쓰기 때문에** 동명이인을 못 거른다 — 휘·자·호는 사전 표제와
# 우연히 겹친다. 실측: 인물 문서 3,435건 중 268건이 본문 연도가 노드
# 생몰년과 110년 넘게 떨어져 있었다 (1971년생 야구 선수 강봉수에 1573년
# 사람의 글). 그 글이 인과 추출·설명·요약에 **정본**으로 들어간다.
#
# 재는 것은 넷이고 전부 결정론적이다: 사전의 '시대' 칸, 정의 한 문장이
# 말하는 시대('조선 후기에 …')와 연도, 받은 뒤에는 본문의 연도. 어느 하나라도 노드 연대와 어긋나면 잇지
# 않는다. 노드 연대를 모르면 막지 않는다 (`causes.backwards` 와 같은 규약).
# 노드 쪽 날짜가 틀려서(Wikidata) 참인 결합을 놓칠 수는 있다 — 그 글은
# `aks:E00…` 고아 아이디로 남아 `ask` 가 찾는다. 틀린 정본은 없는 정본보다
# 나쁘다.
ERA_SPANS: dict[str, tuple[int, int]] = {
    "선사": (-100000, -300), "고대": (-2333, 935), "고려": (918, 1392),
    "조선": (1392, 1897), "근대": (1863, 1945), "현대": (1945, 2100),
    "고대/삼국": (-57, 668), "고대/남북국": (668, 935),
    "고려/고려 전기": (918, 1170), "고려/고려 후기": (1170, 1392),
    "조선/조선 전기": (1392, 1592), "조선/조선 후기": (1592, 1897),
    "근대/개항기": (1863, 1897), "근대/대한제국기": (1897, 1910),
    "근대/일제강점기": (1910, 1945),
}
# 정의 한 문장이 시대를 말하는 말 — "조선 후기에, 정묘호란이 발발하자 …". 시대
# 칸이 '조선'뿐일 때 이것이 가른다 (세종 ↔ 의병장 이도가 그랬다). 상위 시대
# 이름('조선'·'고려')은 안 본다 — 아무 데나 나온다.
ERA_PHRASES: dict[str, str] = {
    "고려 전기": "고려/고려 전기", "고려전기": "고려/고려 전기",
    "고려 후기": "고려/고려 후기", "고려후기": "고려/고려 후기",
    "조선 전기": "조선/조선 전기", "조선전기": "조선/조선 전기",
    "조선 후기": "조선/조선 후기", "조선후기": "조선/조선 후기",
    "개항기": "근대/개항기", "대한제국기": "근대/대한제국기",
    "일제강점기": "근대/일제강점기", "일제 강점기": "근대/일제강점기",
    "삼국시대": "고대/삼국", "삼국 시대": "고대/삼국",
    "남북국시대": "고대/남북국", "남북국 시대": "고대/남북국", "통일신라": "고대/남북국",
}
ERA_SLACK = 40      # 시대 경계는 무르다 — 조선 개국공신은 고려에서 났다
YEAR_WINDOW = 110   # 글의 연도 중 하나는 생몰년(사건은 연대) 구간을 이만큼 넓힌 안에
_YEAR = re.compile(r"(?<![\d,.])(\d{3,4})(?![\d,.])")


def era_span(era: str) -> tuple[int, int] | None:
    """사전의 '시대' 칸 -> 연도 구간. '고려 | 조선' 은 둘을 합친다.
    '고려/고려 후기' 처럼 아는 하위 시대는 좁게, 모르는 것은 상위로."""
    lo = hi = None
    for part in era.split("|"):
        part = part.strip()
        if not part:
            continue
        levels = part.split("/")
        span = (ERA_SPANS.get("/".join(levels[:2]))
                or ERA_SPANS.get(levels[0]))
        if span is None:
            continue
        lo = span[0] if lo is None else min(lo, span[0])
        hi = span[1] if hi is None else max(hi, span[1])
    return None if lo is None else (lo, hi)


def definition_span(text: str | None) -> tuple[int, int] | None:
    """정의 문장이 말하는 시대의 연도 구간 (여럿이면 합쳐서). 없으면 None."""
    lo = hi = None
    for phrase, era in ERA_PHRASES.items():
        if phrase in (text or ""):
            a, b = ERA_SPANS[era]
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
    return None if lo is None else (lo, hi)


def text_years(text: str | None) -> list[int]:
    """글에 적힌 연도(100~2100). '제30호'·'3·1' 은 세 자리가 아니라 안 잡힌다."""
    return [y for y in (int(m) for m in _YEAR.findall(text or "")) if 100 <= y <= 2100]


def consistent(entry: Entry, years: tuple[int | None, int | None] | None,
               body: str | None = None) -> bool:
    """이 항목이 이 연대의 노드를 말하는가. 연대를 모르면 True."""
    start, end = years or (None, None)
    if start is None and end is None:
        return True
    lo = start if start is not None else end
    hi = end if end is not None else start
    assert lo is not None and hi is not None
    # 연도가 있으면 연도가 판정한다 — 사전의 시대 칸이 틀린 항목이 있다
    # (오익창 1557~1643 이 '선사/청동기'). 시대는 연도가 없을 때만 본다.
    found = text_years(entry.definition) + (text_years(body) if body else [])
    if found:
        return any(lo - YEAR_WINDOW <= y <= hi + YEAR_WINDOW for y in found)
    for span in (era_span(entry.era), definition_span(entry.definition)):
        if span and (hi < span[0] - ERA_SLACK or lo > span[1] + ERA_SLACK):
            return False
    return True


# 끝 날짜가 없을 때 그 노드가 언제까지 있다고 볼지. 1865년에 선 국제전기통신
# 연합은 아직 있으므로 '현대' 항목과 어긋나지 않고, 몰년 없는 인물은 아흔까지
# 살았을 수 있다. 사건은 시작한 해뿐이다.
ONGOING_TYPES = frozenset({"org", "concept", "place", "role", "heritage", "period"})
LIFESPAN = 90


def node_years(store, node_ids: list[str] | None = None) -> dict[str, tuple[int | None, int | None]]:
    """노드 아이디 -> (시작 연도, 끝 연도). 인물은 생몰년, 사건은 연대.
    끝을 모르면 타입대로 짐작한다 (`ONGOING_TYPES`·`LIFESPAN`)."""
    from ..timeline import _year_of

    if node_ids is None:
        rows = store.conn.execute("SELECT id, type, start_date, end_date FROM nodes").fetchall()
    else:
        rows = []
        ids = list(node_ids)
        for i in range(0, len(ids), 500):
            batch = ids[i : i + 500]
            marks = ",".join("?" * len(batch))
            rows += store.conn.execute(
                f"SELECT id, type, start_date, end_date FROM nodes WHERE id IN ({marks})", batch
            ).fetchall()
    out: dict[str, tuple[int | None, int | None]] = {}
    for nid, ntype, start, end in rows:
        if ntype == "heritage":
            # 국가유산의 날짜는 지정일이지 만든 때가 아니다 — 1935년에 지정된
            # 고구려 장안성이 '고대' 항목과 어긋나 보인다. 연대로 재지 않는다.
            out[nid] = (None, None)
            continue
        a, b = _year_of(start), _year_of(end)
        if b is None and a is not None:
            if ntype in ONGOING_TYPES:
                b = 2100
            elif ntype == "person":
                b = a + LIFESPAN
        out[nid] = (a, b)
    return out


def match_nodes(
    entries: list[Entry],
    nodes: list[tuple[str, str, str]],
    years: dict[str, tuple[int | None, int | None]] | None = None,
) -> dict[str, str]:
    """항목 아이디 -> 노드 아이디. `nodes` 는 (id, label, type).

    이름(정규화)·타입이 맞고, 그 이름이 항목 쪽에서도 노드 쪽에서도
    하나뿐일 때만 잇는다. 동명이인은 잇지 않는다 — 틀린 정본은 없는
    정본보다 나쁘다. 한 노드가 이름 여럿(라벨 + 별칭)으로 올 수 있다 —
    '10월 유신'의 별칭 '10월유신'이 사전의 '10월유신'을 받는다. 노드 쪽
    '하나뿐'은 이름이 아니라 **노드** 수다.

    `years`(노드 -> 연대, `node_years`)를 주면 항목의 시대·정의 연도가
    그 연대와 어긋나는 것은 잇지 않는다 (`consistent`). 이름이 하나뿐이어도
    별칭(휘·자·호)이 남의 표제와 겹치는 일이 있다."""
    by_name: dict[tuple[str, str], list[Entry]] = defaultdict(list)
    for e in entries:
        t = e.node_type
        if t:
            by_name[(norm_name(e.label), t)].append(e)
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for nid, label, ntype in nodes:
        owners[(norm_name(label), ntype)].add(nid)
    out: dict[str, str] = {}
    taken: set[str] = set()
    for nid, label, ntype in nodes:
        key = (norm_name(label), ntype)
        found = by_name.get(key)
        if not found or len(found) != 1 or len(owners[key]) != 1:
            continue
        e = found[0]
        if years is not None and not consistent(e, years.get(nid)):
            continue
        if e.id in out and out[e.id] != nid:
            continue
        if nid in taken and out.get(e.id) != nid:
            # 한 노드에 항목 둘이 붙으려 한다 (라벨과 별칭이 다른 항목을 가리킴) — 첫 것만
            continue
        out[e.id] = nid
        taken.add(nid)
    return out


# --- 본문 --------------------------------------------------------------------
_SECTION = re.compile(
    r'<section[^>]*class="content_section"[^>]*>(.*?)</section>', re.S)
_TITLE = re.compile(r'<h3[^>]*class="tit"[^>]*>(.*?)</h3>', re.S)
_DETAIL = re.compile(r'<div[^>]*class="detail"[^>]*>(.*?)</div>', re.S)
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<(?:br|/p|/li|/h\d)\s*/?>", re.I)


def _text(fragment: str) -> str:
    frag = _BR.sub("\n", fragment)
    frag = _TAG.sub("", frag)
    frag = html.unescape(frag)
    lines = [_SPACE.sub(" ", ln).strip() for ln in frag.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_article(page: str) -> list[tuple[str, str]]:
    """문서 HTML -> [(절 제목, 본문)]. 순수 함수 — 네트워크 없이 시험한다."""
    out: list[tuple[str, str]] = []
    for sec in _SECTION.findall(page):
        t = _TITLE.search(sec)
        d = _DETAIL.search(sec)
        if not (t and d):
            continue
        title = _text(t.group(1)).strip()
        if title in SKIP_SECTIONS:
            continue
        body = _text(d.group(1))
        if body:
            out.append((title, body))
    return out


def article_text(sections: list[tuple[str, str]]) -> str:
    """절 목록 -> 말뭉치가 쪼개는 모양(`== 제목 ==`)의 한 글."""
    return "\n\n".join(f"== {title} ==\n{body}" for title, body in sections)


def fetch_article(fetcher, entry: Entry) -> str:
    """본문 전체. 못 받으면 빈 문자열."""
    try:
        page = fetcher.get(entry.url, headers={"Accept": "text/html"})
    except RuntimeError as err:
        log.warning("문서 실패 %s (%s): %s", entry.label, entry.id, err)
        return ""
    return article_text(parse_article(page))


# --- 말뭉치에 넣기 ---------------------------------------------------------
def select_entries(
    entries: list[Entry],
    matched: dict[str, str],
    kinds: tuple[str, ...] = ("사건",),
    modern_only: bool = True,
    eras: tuple[str, ...] | None = None,
) -> list[Entry]:
    """받을 항목: 노드에 이어진 것 전부 + 지정한 유형의 근현대 항목.

    근현대가 앞, 그 안에서 사건이 앞이다 — 받다 끊겨도 지금 물음(1945년
    뒤의 역할)에 쓰이는 글부터 들어와 있게.

    `eras` 를 주면 근현대 대신 **그 시대**의 항목을 받는다 (사전의 '시대'
    칸 앞머리 — '고려'는 '고려'·'고려/고려 후기' 를 다 받는다). 고려를
    붙일 때 생긴 칸이다 (2026-09-06): 고려 사건 99·인물 2,450 항목이
    CSV 에 있는데 노드에 이어진 것만 받고 있었다 — 정작 그래프에 없어서
    채워야 할 것이 범위 밖이었다."""
    out: list[Entry] = []
    seen: set[str] = set()
    def in_era(e: Entry) -> bool:
        if eras is not None:
            return e.era.startswith(eras)
        return e.modern or not modern_only
    for e in entries:
        take = e.id in matched or (e.kind.split("/")[0] in kinds and in_era(e))
        if take and e.id not in seen:
            seen.add(e.id)
            out.append(e)
    if eras is not None:
        out.sort(key=lambda e: (not e.era.startswith(eras), e.kind.split("/")[0] != "사건"))
    else:
        out.sort(key=lambda e: (not e.modern, e.kind.split("/")[0] != "사건"))
    return out


def node_names(store, node_ids: list[str] | None = None) -> list[tuple[str, str, str]]:
    """(노드 아이디, 이름, 타입) — 라벨 한 줄과 별칭 한 줄씩."""
    if node_ids is None:
        rows = store.conn.execute(
            "SELECT id, label, type FROM nodes UNION ALL "
            "SELECT n.id, a.alias, n.type FROM aliases a JOIN nodes n ON n.id = a.node_id"
        ).fetchall()
    else:
        rows = []
        ids = list(node_ids)
        for i in range(0, len(ids), 500):
            batch = ids[i : i + 500]
            marks = ",".join("?" * len(batch))
            rows += store.conn.execute(
                f"SELECT id, label, type FROM nodes WHERE id IN ({marks}) UNION ALL "
                f"SELECT n.id, a.alias, n.type FROM aliases a JOIN nodes n ON n.id = a.node_id"
                f" WHERE n.id IN ({marks})", (*batch, *batch)
            ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def ingest(
    fetcher,
    store,
    conn,
    node_ids: list[str] | None = None,
    kinds: tuple[str, ...] = ("사건",),
    limit: int | None = None,
    refresh: bool = False,
    raw_dir: Path = RAW_DIR,
    eras: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """항목을 받아 말뭉치에 넣는다. 돌려주는 값은 집계."""
    from ..corpus import drop_doc, has_doc, put_doc

    entries = load_index(raw_dir)
    names = node_names(store, node_ids)
    years = node_years(store, node_ids)
    matched = match_nodes(entries, names, years)
    todo = select_entries(entries, matched, kinds=kinds, eras=eras)
    log.info("민족문화대백과: 항목 %d건 · 노드에 이은 것 %d건 · 받을 것 %d건",
             len(entries), len(matched), len(todo))
    fetched = empty = skipped = passages = mismatched = 0
    for n, e in enumerate(todo):
        if limit and fetched + empty >= limit:
            break
        nid = matched.get(e.id, f"{SOURCE}:{e.id}")
        if not refresh and has_doc(conn, nid, SOURCE):
            skipped += 1
            continue
        text = fetch_article(fetcher, e)
        if not text:
            empty += 1
            continue
        # 본문의 연도로 한 번 더 — 시대 칸이 '조선'뿐이고 정의에 연도가
        # 없으면 앞 검사는 통과한다 (세종 ↔ 의병장 이도가 그랬다).
        if nid != f"{SOURCE}:{e.id}" and not consistent(e, years.get(nid), text):
            mismatched += 1
            nid = f"{SOURCE}:{e.id}"
            if not refresh and has_doc(conn, nid, SOURCE):
                skipped += 1
                continue
        # 페이지에 '정의' 절이 없을 때만 CSV 의 정의 한 문장을 머리에 둔다
        head = f"{e.definition}\n\n" if e.definition and "== 정의 ==" not in text else ""
        passages += put_doc(conn, nid, e.label, head + text, SOURCE, e.url)
        if nid != f"{SOURCE}:{e.id}":
            # 전에 못 이어 고아 아이디로 넣었던 같은 글이 있으면 지운다
            drop_doc(conn, f"{SOURCE}:{e.id}", SOURCE)
        fetched += 1
        if fetched % 50 == 0:
            conn.commit()
            log.info("  %d / %d", n + 1, len(todo))
    conn.commit()
    return {"entries": len(entries), "matched": len(matched), "todo": len(todo),
            "fetched": fetched, "empty": empty, "skipped": skipped, "passages": passages,
            "mismatched": mismatched}


# --- 빈 설명을 '정의 한 문장'으로 채우기 -------------------------------------
#
# 항목 CSV 에는 본문 말고도 **정의 한 문장**이 붙어 있다 (75,339건). 이건
# 네트워크 없이 지금 당장 읽을 수 있는 글이고, 화면의 빈 설명칸에 딱 맞는
# 길이다. 말뭉치(`ingest`)는 문서 페이지를 받아 와야 하지만 이쪽은 파일만
# 있으면 된다.
#
# **유형 표를 여기서만 넓힌다.** `KIND_TO_TYPE` 은 '이 글을 어느 노드의
# 정본으로 삼을 것인가'를 정하는 표라 좁게 뒀다 — 잘못 이으면 엉뚱한
# 문서가 정본 행세를 한다. 정의 한 문장을 옮기는 데는 그 표가 모자란다:
# `ex:artwork:목민심서` 는 사전에서 '문헌/고서'고 `ex:role:영의정` 은
# '제도/관직'인데 둘 다 표에 없어 통째로 빠졌다. 한 유형이 노드 타입
# 여럿을 받기도 한다 — 사전의 '작품'에는 그림(artwork)과 소설(media)이
# 같이 있다.
DESC_KIND_TO_TYPES: dict[str, set[str]] = {
    "인물": {"person"},
    "사건": {"event"},
    "단체": {"org"},
    "제도": {"concept"},
    "개념": {"concept"},
    "지명": {"place"},
    "유적": {"heritage", "place"},
    "유물": {"heritage"},
    "물품": {"heritage"},
    "작품": {"media", "artwork"},
    "문헌": {"artwork", "media"},
}
# 앞머리가 아니라 유형 전체로 봐야 갈리는 것. '제도/관직'의 앞머리는
# '제도'라 개념이 되는데, 영의정·관찰사는 개념이 아니라 직위다.
DESC_FULL_KIND_TO_TYPES: dict[str, set[str]] = {"제도/관직": {"role"}}


def _desc_types(entry: Entry) -> set[str]:
    if entry.kind in DESC_FULL_KIND_TO_TYPES:
        return DESC_FULL_KIND_TO_TYPES[entry.kind]
    return DESC_KIND_TO_TYPES.get(entry.kind.split("/")[0], set())


def fill_descriptions(
    store, raw_dir: Path = RAW_DIR, dry_run: bool = False
) -> dict[str, object]:
    """설명이 빈 노드를 사전의 정의 한 문장으로 채운다.

    **이름이 양쪽에서 하나뿐일 때만 채운다** — `match_nodes` 와 같은 규칙이다
    (README '노드 병합은 절반이 틀린다'). 동명이인에 남의 정의를 붙이면
    빈 칸보다 나쁘다: 빈 칸은 모른다고 말하지만 틀린 정의는 안다고
    말한다.

    **이미 적힌 설명은 건드리지 않는다.** 위키백과 서사가 들어와 있으면
    그쪽이 길고 낫다. 이 함수가 채우는 곳은 `enrich` 도 사전도 아무것도
    넣지 못한 칸뿐이다.

    여기는 Node 를 거치지 않고 SQL 로 설명을 쓰는 자리다 (CLAUDE.md §1).
    사전의 정의는 한국어지만, 한글이 한 자도 없는 글은 넣지 않는다.
    """
    from ..koreanize import has_hangul

    entries = [e for e in load_index(raw_dir) if e.definition]
    rows = store.conn.execute(
        "SELECT id, label, type, description FROM nodes"
    ).fetchall()
    aliases: dict[str, list[str]] = defaultdict(list)
    for nid, alias in store.conn.execute("SELECT node_id, alias FROM aliases"):
        aliases[nid].append(alias)
    years = node_years(store)

    # (이름, 노드타입) -> 항목들 / 노드들. 양쪽 다 하나뿐이어야 잇는다.
    by_key: dict[tuple[str, str], list[Entry]] = defaultdict(list)
    for e in entries:
        for t in _desc_types(e):
            by_key[(norm_name(e.label), t)].append(e)
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        for name in [r["label"], *aliases[r["id"]]]:
            owners[(norm_name(name), r["type"])].add(r["id"])

    updates: list[tuple[str, str, str]] = []
    skipped_ambiguous = skipped_years = 0
    for r in rows:
        if (r["description"] or "").strip():
            continue
        for name in [r["label"], *aliases[r["id"]]]:
            key = (norm_name(name), r["type"])
            found = by_key.get(key)
            if not found:
                continue
            if len(found) > 1 or len(owners[key]) > 1:
                skipped_ambiguous += 1
                break
            if not consistent(found[0], years.get(r["id"])):
                # 이름은 하나뿐인데 시대가 다르다 — 별칭이 남의 표제와 겹친 것
                skipped_years += 1
                break
            if not has_hangul(found[0].definition):
                break
            updates.append((found[0].definition, found[0].url, r["id"]))
            break

    if not dry_run and updates:
        store.conn.executemany(
            """UPDATE nodes
                  SET description = ?,
                      props = json_set(
                          json_set(COALESCE(NULLIF(props,''), '{}'),
                                   '$.desc_source', 'aks'),
                          '$.desc_url', ?),
                      updated_at = datetime('now')
                WHERE id = ?
                  AND (description IS NULL OR trim(description) = '')""",
            updates,
        )
        # 정본 정의는 편집 계층에 남는다 — 다음 수집이 위키 도입부로
        # 덮어써도 저장소가 되돌린다 (`overrides`). 국편이 나중에 같은 칸을
        # 적으면 그쪽이 이긴다 (마지막 줄이 남는다).
        from .. import overrides
        for text, url, nid in updates:
            overrides.record(store.conn, "node", nid, "description", text, "describe", "민백 정의")
            overrides.record(store.conn, "node", nid, "props.desc_source", "aks", "describe")
            if url:
                overrides.record(store.conn, "node", nid, "props.desc_url", url, "describe")
        store.conn.commit()
    return {
        "entries": len(entries),
        "filled": len(updates),
        "ambiguous": skipped_ambiguous,
        "mismatched": skipped_years,
        "samples": [(nid, text) for text, _, nid in updates[:10]],
    }


# --- 이미 이어진 것 되돌아보기 --------------------------------------------------
def _entry_id(url: str | None) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def audit_bindings(store, conn, raw_dir: Path = RAW_DIR, dry_run: bool = False) -> dict[str, object]:
    """연대 검사가 없던 때 이어진 문서와 설명을 다시 검사한다.

    어긋난 문서는 지우지 않고 고아 아이디(`aks:E00…`)로 옮긴다 — 글은
    참이고 주인만 틀렸다. 어긋난 정의로 채운 설명은 비우고 편집 계층에서도
    지운다 — 빈 칸은 모른다고 말하지만 틀린 정의는 안다고 말한다. 원본과
    파생본에 한 번씩 돌린다 (말뭉치는 하나라 두 번째는 설명만 본다)."""
    from .. import overrides
    from ..corpus import has_doc

    entries = {e.id: e for e in load_index(raw_dir)}
    years = node_years(store)
    rebound: list[tuple[str, str, str]] = []   # (노드, 항목, 표제)
    dropped: list[tuple[str, str]] = []
    docs = conn.execute(
        "SELECT id, node_id, url, title FROM docs WHERE source = ? AND node_id NOT LIKE 'aks:%'",
        (SOURCE,),
    ).fetchall()
    for d in docs:
        e = entries.get(_entry_id(d["url"]))
        if e is None or d["node_id"] not in years:
            continue
        body = " ".join(
            r[0] for r in conn.execute(
                "SELECT text FROM passages WHERE doc_id = ? ORDER BY n", (d["id"],))
        )
        if consistent(e, years.get(d["node_id"]), body):
            continue
        orphan = f"{SOURCE}:{e.id}"
        if has_doc(conn, orphan, SOURCE):
            dropped.append((d["node_id"], e.id))
            if not dry_run:
                conn.execute("DELETE FROM docs WHERE id = ?", (d["id"],))
            continue
        rebound.append((d["node_id"], e.id, d["title"]))
        if not dry_run:
            conn.execute("UPDATE docs SET node_id = ? WHERE id = ?", (orphan, d["id"]))
            conn.execute("UPDATE passages SET node_id = ? WHERE doc_id = ?", (orphan, d["id"]))
    if not dry_run:
        conn.commit()

    cleared: list[tuple[str, str]] = []
    rows = store.conn.execute(
        "SELECT id, props FROM nodes WHERE json_extract(props, '$.desc_source') = 'aks'"
    ).fetchall()
    for r in rows:
        props = json.loads(r["props"] or "{}")
        e = entries.get(_entry_id(props.get("desc_url")))
        if e is None or consistent(e, years.get(r["id"])):
            continue
        cleared.append((r["id"], e.id))
        if dry_run:
            continue
        store.conn.execute(
            """UPDATE nodes SET description = NULL,
                      props = json_remove(props, '$.desc_source', '$.desc_url'),
                      updated_at = datetime('now')
                WHERE id = ?""",
            (r["id"],),
        )
        for fld in ("description", "props.desc_source", "props.desc_url"):
            overrides.forget(store.conn, "node", r["id"], fld)
    if not dry_run:
        store.conn.commit()
    return {"checked": len(docs), "rebound": rebound, "dropped": dropped, "cleared": cleared}
