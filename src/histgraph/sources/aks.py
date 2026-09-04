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


def match_nodes(
    entries: list[Entry],
    nodes: list[tuple[str, str, str]],
) -> dict[str, str]:
    """항목 아이디 -> 노드 아이디. `nodes` 는 (id, label, type).

    이름(정규화)·타입이 맞고, 그 이름이 항목 쪽에서도 노드 쪽에서도
    하나뿐일 때만 잇는다. 동명이인은 잇지 않는다 — 틀린 정본은 없는
    정본보다 나쁘다. 한 노드가 이름 여럿(라벨 + 별칭)으로 올 수 있다 —
    '10월 유신'의 별칭 '10월유신'이 사전의 '10월유신'을 받는다. 노드 쪽
    '하나뿐'은 이름이 아니라 **노드** 수다."""
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
) -> list[Entry]:
    """받을 항목: 노드에 이어진 것 전부 + 지정한 유형의 근현대 항목.

    근현대가 앞, 그 안에서 사건이 앞이다 — 받다 끊겨도 지금 물음(1945년
    뒤의 역할)에 쓰이는 글부터 들어와 있게."""
    out: list[Entry] = []
    seen: set[str] = set()
    for e in entries:
        take = e.id in matched or (
            e.kind.split("/")[0] in kinds and (e.modern or not modern_only)
        )
        if take and e.id not in seen:
            seen.add(e.id)
            out.append(e)
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
) -> dict[str, int]:
    """항목을 받아 말뭉치에 넣는다. 돌려주는 값은 집계."""
    from ..corpus import drop_doc, has_doc, put_doc

    entries = load_index(raw_dir)
    names = node_names(store, node_ids)
    matched = match_nodes(entries, names)
    todo = select_entries(entries, matched, kinds=kinds)
    log.info("민족문화대백과: 항목 %d건 · 노드에 이은 것 %d건 · 받을 것 %d건",
             len(entries), len(matched), len(todo))
    fetched = empty = skipped = passages = 0
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
            "fetched": fetched, "empty": empty, "skipped": skipped, "passages": passages}
