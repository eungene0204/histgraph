"""지금 일어나는 일을 걷는다 (`recent`).

**왜 있는가.** 현대사가 2025년 6월 3일 제21대 대통령 선거에서 끝나 있었다
(2026-09-09 사용자 요청: "그 이후 사건을 주기적으로 수집"). 사건 시드 표
(`wikipedia.EVENT_SEEDS`)는 사람이 손으로 적는 명단이라 **어제 일어난 일을
담지 못한다.** 그래서 해마다 저절로 자라는 자리에서 걷는다 — 한국어
위키백과의 `분류:{해}년 대한민국`.

**무엇으로 가르는가.** 그 분류에는 사건과 드라마와 프로야구가 함께 산다
(실측 2026-09-09: 후보 92건 중 사건 29 · 드라마 13 · 스포츠 16). 이름으로
짐작하지 않는다 — 스포츠 오염 때와 같은 처방으로 **Wikidata 클래스 계층에
물어본다** (`reclassify` 의 사다리와 같은 뿌리 Q1190554). 드라마는 사건
계층에 닿지 않아 저절로 빠지고, 스포츠는 닿으므로 `filters` 로 한 번 더
거른다.

**QID 가 없는 문서가 넷 중 하나다** (실측 25/92). 어제 생긴 문서일수록
그렇고, 하필 그쪽이 사고·화재·붕괴·재판처럼 연표에 서야 할 것들이다.
Wikidata 가 붙을 때까지 기다리면 그 시기가 다시 빈 칸이 되므로, 그런 문서는
**자기 분류로 가른다** (`분류:2026년 화재`·`분류:대한민국의 철도 사고`).
분류도 아무 말을 안 하면 **보류한다** — 짐작으로 세우지 않는다.

**판정은 표가 이긴다.** `data/recent.tsv` 에 사람이 적은 줄은 기계의 판정
앞에 선다 (`판정<TAB>문서명<TAB>날짜<TAB>근거`). 보류한 후보는 그 표에
적으라고 이름을 찍어 준다.

**날짜.** Wikidata 의 P585/P580 이 먼저고, 없으면 문서 **첫 문장**에서
읽는다 ("…는 2025년 9월 26일 저녁 …에서 발생한 화재이다"). 첫 문장으로
좁히는 이유는 뒤 문단에 딴 날짜가 널려 있기 때문이다 — 2025년 대한민국
산불의 본문 둘째 문장에는 5월 15일이 나온다.

**목록 조회는 캐시를 쓰지 않는다.** `Fetcher` 의 캐시에는 기한이 없어서,
주마다 도는 수집이 첫 주의 세상을 영영 다시 본다. 분류 목록과 도입부는
`use_cache=False` 로 받고, 클래스 계층 질의만 캐시에 맡긴다 (거의 안 변한다).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .filters import SPORTS_CLASSES, is_sports
from .http import Fetcher
from .labels import HANGUL
from .store import GraphStore

log = logging.getLogger(__name__)

SOURCE = "kowiki:recent"
# 이 커넥터가 담는 시대. `scope.select_seeds` 가 `props.seed_era` 로 사건을
# 고르므로 이 이름이 곧 화면에 들어가는 조건이다.
ERA = "대한민국"
API_URL = "https://ko.wikipedia.org/w/api.php"

# 해마다 저절로 자라는 자리. 한국어 위키백과가 그 해에 일어난 일을 여기
# 모은다 — 우리가 이름을 적어 넣을 필요가 없는 유일한 명단이다.
CATEGORY = "분류:{year}년 대한민국"

# 한 번에 물어볼 문서 수. `prop=extracts` 의 상한이 20이다.
BATCH = 20

# 사건 계층의 뿌리 (`reclassify.OCCURRENCE` 와 같은 것).
OCCURRENCE = "Q1190554"

# 사건 계층에 닿지만 **역사가 아닌** 클래스. 스포츠와 같은 이유로 뺀다 —
# 해마다 한 번씩 열리는 명단이라, 세우면 연표가 그것들로 덮인다.
# 표 밖의 클래스는 통과시킨다. 잘못 들어온 것은 `data/recent.tsv` 에
# 한 줄 적어 빼는 쪽이, 짐작으로 막아 진짜 사건을 잃는 것보다 낫다.
NOT_EVENT_CLASSES: dict[str, str] = {
    "Q18340514": "연도 문서",              # '2025년 대한민국' 자체
    "Q13406463": "위키미디어 목록 문서",    # '이재명의 대통령 순방 목록'
    "Q4167410": "동음이의어 문서",
    "Q4504495": "시상식",                  # 백상예술대상
}

# --- QID 가 없는 문서를 가르는 표 -------------------------------------------
#
# 문서가 스스로 달고 있는 분류로 가른다. 라벨 정규식이 아니라 분류를 보는
# 이유는, 이름에는 '사건'이 없어도 분류에는 있기 때문이다 ('누리호 4차 발사'
# 는 이름만으로는 못 가르고, '광주대표도서관 붕괴 사고'는 분류가 '2025년
# 재난'이라고 말해 준다).
#
# **빼는 표를 먼저 본다** — '2025년 KBO 포스트시즌'은 '2025년 야구'와
# '2025년 대한민국'을 함께 달고 있다.
DROP_CATEGORY = re.compile(
    r"드라마|영화|텔레비전|라디오|방송\s*프로그램|프로그램|음반|음악|애니메이션|"
    r"만화|웹툰|소설|공연|뮤지컬|예능|"
    r"야구|축구|배구|농구|바둑|골프|스포츠|경기\s*결과|포스트시즌|리그|시즌|"
    r"올림픽|아시안\s*게임|선수권|선수단|체육\s*대회|전국체육대회|"
    r"대학수학능력시험|수능"
)
# 남기는 표. 사건·사고·재난과 그 자리에서 벌어진 일들이다.
KEEP_CATEGORY = re.compile(
    r"사건|사고|재난|참사|화재|산불|폭발|붕괴|침몰|추락|탈선|추돌|"
    r"자연재해|기상|폭설|홍수|호우|지진|태풍|"
    r"시위|항의행동|사회\s*운동|파업|농성|"
    r"살인|범죄|테러|납치|학살|"
    r"재판|판결|탄핵|계엄|"
    r"선거|국민투표|"
    r"회의|정상회담|조약|협정|외교"
)

# 도입부에서 날짜를 읽을 창. 첫 문장 언저리만 본다.
FIRST_SENTENCE = 300
# 괄호 묶음. 안에 든 날짜는 이 사건의 날짜가 아니다 (생몰년·한자·원어).
_PAREN = re.compile(r"\([^()]*\)")
# 날짜 한 덩어리. 월·일은 없을 수 있다 ('2025년 3월', '1994년').
_DATE = re.compile(r"(\d{4})년(?:\s*(\d{1,2})월(?:\s*(\d{1,2})일)?)?")
# 믿을 수 있는 연도의 창. 이보다 밖이면 다른 이야기의 연도를 읽은 것이다.
MIN_YEAR = 1900


@dataclass
class Candidate:
    """분류에서 걸린 문서 하나."""

    title: str
    year: int                       # 걸린 분류의 해
    qid: str | None = None
    intro: str = ""
    categories: list[str] = field(default_factory=list)
    verdict: str = "보류"           # 수집 · 제외 · 보류 · 이미 있음
    reason: str = ""
    start: str | None = None
    end: str | None = None
    date_from: str = ""             # 날짜를 어디서 읽었는지 (props 에 남는다)
    node_id: str = ""

    @property
    def url(self) -> str:
        return "https://ko.wikipedia.org/wiki/" + urllib.parse.quote(self.title)


@dataclass
class Report:
    collected: list[Candidate] = field(default_factory=list)
    dropped: list[Candidate] = field(default_factory=list)
    held: list[Candidate] = field(default_factory=list)
    known: list[Candidate] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    nodes: int = 0

    @property
    def counted(self) -> str:
        return (
            f"수집 {len(self.collected)} · 이미 있음 {len(self.known)}"
            f" · 제외 {len(self.dropped)} · 보류 {len(self.held)}"
        )


# --- 사람이 적는 표 ---------------------------------------------------------

TABLE_PATH = "data/recent.tsv"
VERDICTS = ("수집", "제외")


def load_table(path: str | Path) -> dict[str, tuple[str, str, str]]:
    """`판정<TAB>문서명<TAB>날짜<TAB>근거` — 문서명 -> (판정, 날짜, 근거).

    **표는 언제나 기계를 이긴다** (`dedupe`·`roles` 와 같은 규칙). 날짜 칸은
    비워도 되고, 적으면 Wikidata 와 도입부보다 앞선다."""
    table: dict[str, tuple[str, str, str]] = {}
    p = Path(path)
    if not p.exists():
        return table
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 2 or cols[0] not in VERDICTS:
            log.warning("%s:%d 알 수 없는 줄: %s", p, lineno, raw[:60])
            continue
        verdict, title = cols[0], cols[1]
        date = cols[2] if len(cols) > 2 else ""
        why = cols[3] if len(cols) > 3 else ""
        table[title] = (verdict, date, why)
    return table


# --- 위키백과 조회 ----------------------------------------------------------


def _api(fetcher: Fetcher, params: dict[str, str], *, cache: bool = False) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    raw = fetcher.get(API_URL, params, use_cache=cache)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        hint = "User-Agent 문제일 수 있음" if raw.lstrip().startswith("<") else ""
        raise RuntimeError(f"위키백과 응답 파싱 실패: {raw[:150]} {hint}") from err


def category_members(fetcher: Fetcher, title: str) -> list[dict]:
    """분류에 든 문서와 하위 분류. 이어받기(continue)를 끝까지 따라간다."""
    out: list[dict] = []
    cont: str | None = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": title,
            "cmlimit": "500",
            "cmtype": "page|subcat",
        }
        if cont:
            params["cmcontinue"] = cont
        data = _api(fetcher, params)
        out += data.get("query", {}).get("categorymembers", [])
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            return out


def discover(fetcher: Fetcher, years: list[int]) -> dict[str, Candidate]:
    """해마다의 분류에서 후보 문서를 모은다. 하위 분류도 한 단계 따라간다
    (`분류:2026년 대한민국의 선거` 에 그 해의 선거가 들어 있다)."""
    found: dict[str, Candidate] = {}
    for year in years:
        titles: set[str] = set()
        for m in category_members(fetcher, CATEGORY.format(year=year)):
            if m.get("ns") == 14:
                titles |= {
                    s["title"] for s in category_members(fetcher, m["title"])
                    if s.get("ns") == 0
                }
            elif m.get("ns") == 0:
                titles.add(m["title"])
        log.info("%d년 분류: 문서 %d건", year, len(titles))
        for t in titles:
            # 같은 문서가 두 해에 걸려 있으면 **먼저 걸린 해**를 남긴다.
            found.setdefault(t, Candidate(title=t, year=year))
    return found


def fill_articles(fetcher: Fetcher, cands: dict[str, Candidate]) -> None:
    """후보에 도입부·QID·분류를 채운다. 한 요청에 20건이다."""
    titles = sorted(cands)
    for i in range(0, len(titles), BATCH):
        batch = titles[i : i + BATCH]
        data = _api(fetcher, {
            "action": "query",
            "prop": "extracts|pageprops|categories",
            "ppprop": "wikibase_item",
            "explaintext": "1",
            "exintro": "1",
            "exlimit": str(BATCH),
            "cllimit": "500",
            "clshow": "!hidden",
            "redirects": "1",
            "titles": "|".join(batch),
        })
        query = data.get("query", {})
        # 넘겨주기·정규화를 되짚어 우리가 물어본 이름에 채운다.
        back = {r["to"]: r["from"] for r in query.get("redirects", [])}
        norm = {r["to"]: r["from"] for r in query.get("normalized", [])}
        for page in query.get("pages", []):
            asked = back.get(page["title"], page["title"])
            asked = norm.get(asked, asked)
            cand = cands.get(asked) or cands.get(page["title"])
            if cand is None or page.get("missing"):
                continue
            cand.qid = page.get("pageprops", {}).get("wikibase_item")
            cand.intro = (page.get("extract") or "").strip()
            cand.categories = [
                c["title"].replace("분류:", "") for c in page.get("categories", [])
            ]


# --- 판정 -------------------------------------------------------------------


def judge_by_category(cand: Candidate) -> tuple[str, str]:
    """QID 가 없는 문서를 자기 분류로 가른다. (판정, 근거)."""
    if is_sports(cand.title):
        return "제외", "스포츠"
    for cat in cand.categories:
        if DROP_CATEGORY.search(cat):
            return "제외", f"분류 '{cat}'"
    for cat in cand.categories:
        if KEEP_CATEGORY.search(cat):
            return "수집", f"분류 '{cat}'"
    return "보류", "Wikidata 항목도 없고 분류도 사건이라 하지 않는다"


def judge_by_class(
    cand: Candidate, classes: set[str], reach: set[str]
) -> tuple[str, str]:
    """Wikidata 클래스 계층으로 가른다. `reach` 는 사건 계층에 닿는 클래스."""
    if is_sports(cand.title) or (classes & SPORTS_CLASSES):
        return "제외", "스포츠"
    blocked = classes & set(NOT_EVENT_CLASSES)
    if blocked:
        return "제외", NOT_EVENT_CLASSES[sorted(blocked)[0]]
    if not classes:
        # P31 이 없다. 클래스로는 아무 말도 못 하므로 분류에 물어본다.
        return judge_by_category(cand)
    if classes & reach:
        return "수집", "Wikidata 가 사건 계층에 둔 항목"
    return "제외", "사건 계층에 닿지 않는다"


# --- 날짜 -------------------------------------------------------------------


def first_date(text: str, title: str = "") -> tuple[str | None, str | None]:
    """도입부 첫 문장에서 (시작, 끝) 을 읽는다.

    문서 이름을 먼저 잘라 낸다 — 도입부는 이름으로 시작하는데 그 이름에
    해가 박혀 있는 것이 많아('2025년 대한민국 산불'), 그대로 읽으면 달을
    잃는다. 이름 뒤부터 읽으면 '…은 2025년 3월 …' 이 걸린다."""
    if not text:
        return None, None
    body = text
    if title:
        at = text.find(title)
        if 0 <= at <= 80:
            body = text[at + len(title):]
    # **괄호 안의 날짜는 이 사건의 날짜가 아니다.** 정의 문장이 사람을
    # 부를 때 생몰년을 괄호로 단다 — '노동자 김충현(1975년 ~ 2025년 6월
    # 2일)이 …' 을 그대로 읽으면 2025년의 사고가 1975년에 선다.
    head = _PAREN.sub(" ", body[:FIRST_SENTENCE])
    matches = list(_DATE.finditer(head))
    if not matches:
        return None, None

    def iso(m: re.Match[str]) -> str | None:
        year = int(m.group(1))
        if year < MIN_YEAR or year > dt.date.today().year + 1:
            return None
        out = f"{year:04d}"
        if m.group(2):
            out += f"-{int(m.group(2)):02d}"
            if m.group(3):
                out += f"-{int(m.group(3)):02d}"
        return out

    start = iso(matches[0])
    if start is None:
        return None, None
    end = None
    # '1994년부터 2011년까지' — 사이에 '부터', 뒤에 '까지' 가 있을 때만
    # 끝으로 읽는다. 그냥 두 번째 날짜는 다른 일의 날짜일 수 있다.
    if len(matches) > 1:
        between = head[matches[0].end():matches[1].start()]
        after = head[matches[1].end():matches[1].end() + 3]
        if "부터" in between and "까지" in after:
            end = iso(matches[1])
    return start, end


def _trim_fake(date: str | None) -> str | None:
    """Wikidata 의 거짓 정밀도를 걷는다.

    해만 아는 항목도 `2026-01-01T00:00:00Z` 로 돌아온다 — 정밀도가 값이
    아니라 옆 칸에 적혀 있기 때문이다. 1월 1일을 해로 물리면 진짜 새해
    첫날의 일을 하루 잃지만, 그런 사건은 정의 문장에 날짜가 적혀 있어
    이 자리까지 오지 않는다."""
    if date and date.endswith("-01-01"):
        return date[:4]
    return date


# --- 수집 -------------------------------------------------------------------


def _existing(store: GraphStore) -> tuple[set[str], dict[str, str]]:
    """이미 있는 노드 id 와 (사건 라벨 -> id).

    라벨로도 보는 이유: QID 가 없어 `kowiki:` 로 세운 노드에 나중에
    Wikidata 가 붙으면, 같은 사건이 `wd:` 로 한 번 더 들어온다. 이름이
    같으면 만들지 않고 이미 있는 쪽을 그대로 둔다 — 중복을 만들어 놓고
    `dedupe` 로 되찾는 것보다 안 만드는 쪽이 싸다."""
    ids = {r["id"] for r in store.conn.execute("SELECT id FROM nodes")}
    labels = {
        r["label"]: r["id"]
        for r in store.conn.execute("SELECT id, label FROM nodes WHERE type='event'")
    }
    return ids, labels


def _node_id(cand: Candidate) -> str:
    """QID 가 있으면 `wd:` — 그래야 이미 있는 Wikidata 사건과 한 노드가
    된다. 없으면 문서 이름으로 세운다 (`works` 가 작품에 쓰는 것과 같은
    자리다)."""
    return f"wd:{cand.qid}" if cand.qid else f"kowiki:{cand.title}"


def collect(
    fetcher: Fetcher,
    store: GraphStore,
    years: list[int],
    *,
    table: str | Path = TABLE_PATH,
    dry_run: bool = False,
    limit: int | None = None,
) -> Report:
    """분류에서 걷고, 가르고, 새 사건만 그래프에 세운다."""
    from .ontology import Node
    from .reclassify import _root_reach
    from .sources.wikidata import _qid, _safe_query, _val

    report = Report()
    rules = load_table(table)
    cands = discover(fetcher, years)
    if limit:
        cands = dict(sorted(cands.items())[:limit])
    if not cands:
        return report
    fill_articles(fetcher, cands)

    ids, labels = _existing(store)

    # 1) 사람이 적은 표가 먼저다.
    machine: list[Candidate] = []
    for cand in cands.values():
        rule = rules.get(cand.title)
        if rule:
            cand.verdict, date, cand.reason = rule[0], rule[1], rule[2] or "표"
            if date:
                cand.start, cand.date_from = date, "표"
            if cand.verdict == "제외":
                report.dropped.append(cand)
                continue
        machine.append(cand)

    # 2) Wikidata 에 클래스와 날짜를 물어본다 (QID 가 있는 것만).
    qids = [c.qid for c in machine if c.qid]
    classes: dict[str, set[str]] = {}
    dates: dict[str, tuple[str | None, str | None]] = {}
    if qids:
        values = " ".join(f"wd:{q}" for q in sorted(set(qids)))
        rows = _safe_query(
            fetcher,
            f"""SELECT ?e ?c ?p ?s ?end WHERE {{ VALUES ?e {{ {values} }}
                  OPTIONAL {{ ?e wdt:P31 ?c }}
                  OPTIONAL {{ ?e wdt:P585 ?p }}
                  OPTIONAL {{ ?e wdt:P580 ?s }}
                  OPTIONAL {{ ?e wdt:P582 ?end }} }}""",
            "사건 클래스·날짜",
            report.failures,
        )
        for r in rows:
            q = _qid(_val(r, "e") or "")
            if _val(r, "c"):
                classes.setdefault(q, set()).add(_qid(_val(r, "c") or ""))
            start = (_val(r, "p") or _val(r, "s") or "")[:10] or None
            end = (_val(r, "end") or "")[:10] or None
            if start or end:
                dates[q] = (start, end)
    reach: set[str] = set()
    all_classes = {c for cs in classes.values() for c in cs}
    if all_classes:
        got, _failed = _root_reach(fetcher, all_classes, report.failures)
        reach = got.get(OCCURRENCE, set())

    # 3) 가른다. 표가 이미 '수집'이라 한 것은 다시 묻지 않는다.
    for cand in machine:
        if cand.verdict != "수집":
            if cand.qid and not report.failures:
                cand.verdict, cand.reason = judge_by_class(
                    cand, classes.get(cand.qid, set()), reach
                )
            elif cand.qid:
                # 질의가 실패했으면 '클래스가 없다'와 구분이 안 된다.
                # 부재를 근거로 삼는 판정이라 그대로 보류한다.
                cand.verdict, cand.reason = "보류", "Wikidata 조회 실패"
            else:
                cand.verdict, cand.reason = judge_by_category(cand)
        if cand.verdict == "제외":
            report.dropped.append(cand)
            continue
        if cand.verdict == "보류":
            report.held.append(cand)
            continue

        # 날짜 — 표 > 도입부 첫 문장 > Wikidata.
        #
        # **도입부가 Wikidata 보다 앞선다.** Wikidata 는 정밀도를 값과 따로
        # 적어서, 해만 아는 항목도 `2026-01-01T00:00:00Z` 로 돌아온다
        # (실측: '2026년 대전 자동차 부품 공장 화재'·'인천 송도 총격 사건'이
        # 그렇게 1월 1일에 섰다). 정의 문장은 그런 거짓 정밀도를 만들지
        # 않는다 — "…는 2026년 1월 30일 오후 4시 …에 발생한" 이다.
        if not cand.start:
            cand.start, cand.end = first_date(cand.intro, cand.title)
            cand.date_from = "문서 첫 문장" if cand.start else ""
        if not cand.start and cand.qid in dates:
            cand.start, cand.end = (_trim_fake(d) for d in dates[cand.qid])
            cand.date_from = "wikidata"
        if not cand.start:
            cand.verdict = "보류"
            cand.reason = (
                "도입부가 비어 있다 — 설명 없는 사건은 화면이 세우지 않는다"
                if not cand.intro else
                "날짜를 못 찾았다 — 연표에 세울 자리가 없다"
            )
            report.held.append(cand)
            continue

        cand.node_id = _node_id(cand)
        if cand.node_id in ids or cand.title in labels:
            cand.verdict = "이미 있음"
            report.known.append(cand)
            continue
        if not HANGUL.search(cand.title):
            # §1 관문. 여기까지 오는 일은 거의 없지만, 한 번 서면 화면에
            # 영어 이름이 뜬다.
            cand.verdict = "보류"
            cand.reason = "이름에 한글이 없다"
            report.held.append(cand)
            continue
        report.collected.append(cand)

    if not report.collected or dry_run:
        return report

    # 4) 받아들인 것만 본문을 통째로 받는다 (요청당 1건이라 비싸다).
    from .sources import wikipedia

    full = wikipedia.fetch_extracts(
        fetcher, [c.title for c in report.collected], full=True
    )
    nodes = []
    for cand in report.collected:
        text = full.get(cand.title) or cand.intro
        nodes.append(Node(
            id=cand.node_id,
            type="event",
            label=cand.title,
            source="wd" if cand.qid else "kowiki",
            start_date=cand.start,
            end_date=cand.end,
            description=text,
            url=(
                f"https://www.wikidata.org/entity/{cand.qid}"
                if cand.qid else cand.url
            ),
            props={
                "kowiki_url": cand.url,
                # `scope.select_seeds` 가 이 칸으로 사건을 고른다.
                "seed_era": ERA,
                "seeded": True,
                "recent": True,
                "date_from": cand.date_from,
                "collected": dt.date.today().isoformat(),
            },
        ))
    report.nodes = store.upsert_nodes(nodes)
    store.log_ingest(SOURCE, report.nodes, 0)
    return report


def years_since(store: GraphStore, since: str | None = None) -> list[int]:
    """걸을 해. 그래프의 마지막 사건이 선 해부터 올해까지.

    마지막 사건의 해부터 다시 걷는 이유: 그 해의 나머지 달이 아직 비어
    있다. 이미 있는 것은 `_existing` 이 걸러 낸다."""
    if since:
        start = int(since[:4])
    else:
        # **글자로 비교하면 안 된다** — '982' 가 '2025' 보다 크다.
        row = store.conn.execute(
            """SELECT MAX(CAST(substr(start_date, 1, 4) AS INTEGER)) AS y
                 FROM nodes WHERE type='event' AND start_date IS NOT NULL"""
        ).fetchone()
        start = int(row["y"]) if row and row["y"] else dt.date.today().year
    end = dt.date.today().year
    # **지난해는 늘 다시 훑는다.** 분류는 뒤늦게도 자란다 — 지난해 12월의
    # 사고 문서가 올해 2월에 서기도 한다. 마지막 사건이 올해 것이라고
    # 올해만 걸으면 그런 것을 영영 못 본다. 이미 있는 것은 걸러지므로
    # 한 해를 더 걷는 값은 요청 몇 번이다.
    return list(range(min(start, end - 1), end + 1))
