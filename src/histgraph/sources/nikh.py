"""국사편찬위원회 정본 — 한국사연대기 · 조선왕조실록 (`data/raw/nikh/`).

**이 자료가 정본이다.** 위키백과·Wikidata 와 어긋나면 이쪽이 맞다
(2026-09-04 결정). 그래서 이 커넥터는 다른 커넥터와 달리 **이미 있는
노드의 설명과 연대를 덮어쓴다.** 흔적은 `props.canon = "nikh"` 로 남긴다.

**왜 필요했나.** 세종 재위 32년의 연표에 사건이 삼포 개항 하나였다.
Wikidata 는 조선 사건을 거의 모르고(1400년대 전체 11건), 위키백과 시드
표는 난·전쟁·사화만 적어 훈민정음 창제·4군 6진·계해약조 같은 제도·문화
사건이 통째로 빠져 있었다. 산문 추출은 사건을 찾아도 연도를 못 붙였다.

**자료는 사이트에서 긁지 않는다.** db.history.go.kr · sillok · 우리역사넷
셋 다 API 가 없고 robots.txt 가 검색엔진 외 전부 막는다. 같은 자료가
공공데이터포털에 파일로 열려 있다 (활용신청 불필요, 로그인 뒤 다운로드):

    15155532  우리역사넷_한국사연대기      XLSX  항목 924 (사건 196 · 인물 429 …)
    15053647  조선왕조실록 정보_실록원문   XML   기사 380,974 (태조~철종)
    15053646  고순종실록 원문              XML   기사 32,797
    15053645  조선왕조실록 부가정보         CSV   인물 115,859 · 관직 336,255

**연대기에는 연도 열이 없다.** 웹 페이지에는 '1448년(세종 30)' 이 있는데
표에는 빠졌다. 문장의 첫 연도를 쓰면 배경 연도가 걸린다 — 병자호란
항목은 정묘호란(1627)부터 말한다. 실측 60건 정답표에서 문장 규칙만으로는
46건이 한계였다. 그래서 연도는 **후보를 여럿 모아 고른다**:

  1. 이름이 든 문장의 연도들, 그다음 설명·개요의 연도들이 후보다.
  2. 이미 있는 노드(Wikidata)의 연도가 후보 안에 있으면 그것 — 두
     자료가 같은 해를 말한다.
  3. 실록에 그 해 기사가 있으면 그 기사의 날짜 — 원문 XML 에 국역은
     없지만 **기사 제목은 한글**이다 ('훈민정음을 창제하다', 1443-12-30).
     제목을 트라이그램 FTS 로 찾고, 후보 연도와 같은 해의 가장 이른
     기사를 쓴다. 조선 사건은 대부분 여기서 일 단위로 잡힌다.
  4. 셋 다 아니면 첫 후보를 쓰되 `props.date_uncertain` 을 단다. 이
     값은 **빈 칸만 채우고 이미 있는 날짜를 밀어내지 않는다** — 정본은
     자료이지 우리의 짐작이 아니다.

**실록 제목 검색은 흔한 낱말에 걸린다.** '건립' 하나로 찾으면 서원 건립이
정자각 건립 기사에 붙고, 꼬리말을 뗀 '기묘'·'신임'은 간지와 사람 이름에
걸린다. 그래서 이름 전체와 꼬리말을 뗀 몸통(세 글자 이상)만 검색하고,
'4군 6진' 처럼 낱말이 여럿이면 제목에 **낱말이 전부** 있어야 받는다.

**실록 날짜는 음력이다.** 세종 25년 12월 30일은 양력 1444년 1월이다.
연도가 흔히 말하는 해(1443)와 같도록 음력 그대로 적고 `props.calendar =
"lunar"` 로 밝힌다.

**유물·단체는 사건이 아니지만 실록 기사는 사건이다.** 연대기의 훈민정음은
유물 항목이라 연표(사건만 세운다)에 못 선다. 그 항목이 실록 기사 하나에
닿으면 그 기사를 사건 노드로 세운다 — '훈민정음을 창제하다'(1443-12-30),
'집현전을 설치하다'. 기사 제목이 곧 사건 이름이고 날짜는 일 단위다.

**이름이 같은 노드가 여럿이면 세지 않고 가른다.** 허준·김구·임진왜란이
둘씩 있다. 시대(연대기 ID 의 자릿수)·연대·실록 인물 CSV 의 생년으로
거르고, 남은 것이 하나면 그 노드로 합친다. 둘 이상 남으면 차수가
압도적인 쪽만 받고, 아니면 새 노드를 세우고 후보를 보고한다 — 정본을
엉뚱한 노드에 씌우는 것이 빈 노드보다 나쁘다.

**`ex:` 고아는 정본 노드로 흡수한다.** `ex:event:대마도 정벌` 에 이종무의
참여 엣지가 걸려 있었다. 이름이 같은 추출 고아는 정본 노드로 합쳐
(`promote.merge_node`) 그 엣지를 살린다.

**인물 참여는 이름(漢字) 표기로 잡는다.** 연대기 본문은 '신숙주(申叔舟)'
처럼 첫 언급에 한자를 단다. 한자까지 같은 인물이 연대기에 있으면 그
노드로, 없으면 이름이 하나뿐인 기존 인물 노드로 잇는다. 한자 없는
언급은 **같은 시대의 연대기 인물**에, **설명·개요 안에서만** 받는다 —
'세종의 명으로' 를 놓치면 훈민정음이 세종과 이어지지 않지만, 4·19혁명
본문의 '세종로'를 세종으로 읽으면 안 된다 (실측: 그렇게 22건이 붙었다).
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..koreanize import has_hangul
from ..ontology import Edge, Node
from ..store import GraphStore

log = logging.getLogger(__name__)

SOURCE = "nikh"
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "nikh"
YEONDAEGI = "yeondaegi.xlsx"
SILLOK_DIRS = ("sillok", "sillok_gojong")
SILLOK_INDEX = "sillok.sqlite"
PERSONS_CSV = "persons"

# 연대기 유형 -> 온톨로지 타입
KIND_TO_TYPE: dict[str, str] = {
    "인물": "person",
    "사건": "event",
    "조직·단체": "org",
    "유물·유적": "heritage",
    "지리": "place",
    "기타": "concept",
}

# 연대기 ID 의 시대 자릿수 (`kc_r3xxxxx` 의 3) -> (정체 라벨, 창)
# 0·1 은 고대다 — 고구려·백제·신라를 이 자릿수로는 가를 수 없어 비워 둔다.
ERA_DIGIT: dict[str, tuple[str | None, tuple[int, int]]] = {
    "0": (None, (-2400, 935)),
    "1": (None, (-2400, 935)),
    "2": ("고려", (900, 1380)),
    "3": ("조선", (1380, 1870)),
    "4": (None, (1840, 1950)),   # 근대 — 연도로 대한제국/일제강점기를 가른다
    "5": ("대한민국", (1940, 2100)),
}
# 시대 라벨 -> 정체 QID (scope 가 씨앗을 고르는 열쇠)
POLITY_QID: dict[str, str] = {
    "고려": "Q28208", "조선": "Q28179", "대한제국": "Q28233",
    "일제강점기": "Q503585", "대한민국": "Q884",
}

# 연도 서식. '1376년(우왕 2)' 이 가장 믿을 만하다 — 연대기 문체가 그렇다.
YEAR_REIGN = re.compile(r"(?<![\d])(\d{3,4})년\s*\([^)]*\d+\)")
YEAR_PLAIN = re.compile(r"(?<![\d])(\d{4})년")
YEAR_PAREN = re.compile(r"[가-힣]+\s*\d+년\s*\((\d{3,4})\)")
YEAR_PATTERNS = (YEAR_REIGN, YEAR_PLAIN, YEAR_PAREN)

# 달. 연대기 문체는 해 **바로 다음**에 달을 적는다 — '1380년 9월',
# '1380년(우왕 6) 9월에'. 떨어져 있는 달은 받지 않는다: 한 문단 안에서
# 달만 따로 적히면 어느 해의 달인지 문장이 말해주지 않는다.
MONTH_AFTER_YEAR = re.compile(
    r"(?<!\d)(\d{3,4})년\s*(?:\([^)]*\))?\s*(?:에는?\s*)?(\d{1,2})월"
)
# 그 달이 **구간의 시작**이면 받지 않는다 — '10월 23일부터 11월 11일 사이에
# 이루어진 두 차례의 전투'(우금치)는 10월의 일이 아니라 두 달에 걸친 일이다.
MONTH_RANGE = re.compile(r"\s*\d{0,2}일?\s*(?:부터|~|∼|-|—)")
# 양력을 쓰기 시작한 해 (건양 원년, 1896-01-01). 그 전의 달은 음력이다.
SOLAR_FROM = 1896

# 사건 이름의 꼬리말. 떼어낸 몸통이 실록 제목에 남는다 ('이시애의 난' -> '이시애').
TAIL = re.compile(
    r"\s*(의 난|의 옥|의 변|의 정변|사건|전투|대첩|정벌|개척|반정|사화|환국|약조|조약|"
    r"봉기|운동|정책|반포|창제|편찬|설치|건립|중건|해전)$"
)

# '신숙주(申叔舟)' — 이름 뒤에 한자. 연대기는 첫 언급에 이렇게 단다.
NAME_HANJA = re.compile(r"([가-힣]{2,6})\(([一-鿿]{2,6})\)")
# 이름 뒤에 올 수 있는 조사·구두점. '로'는 뺐다 — '세종로'·'종로'가 걸린다.
AFTER_NAME = (
    r"(?=(?:이|가|은|는|의|을|를|과|와|도|께서|에게|에|이며|이다|였|과의|와의|"
    r"[\s,.·()「『”’])|$)"
)
SENTENCE_END = re.compile(r"(?<=[.。!?])\s+")
MAX_EVENT_TITLE = 40


@dataclass(slots=True)
class Entity:
    kc_id: str            # kc_r300900
    kind: str             # 사건 / 인물 / …
    label: str
    hanja: str
    summary: str          # '설명' 열
    sections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def era_digit(self) -> str:
        return self.kc_id[4] if len(self.kc_id) > 4 else ""

    @property
    def node_type(self) -> str:
        return KIND_TO_TYPE.get(self.kind, "concept")

    @property
    def overview(self) -> str:
        for title, text in self.sections:
            if title in ("개요", "개관", "머리말"):
                return text
        return self.sections[0][1] if self.sections else ""

    @property
    def core(self) -> str:
        return TAIL.sub("", self.label)

    def full_text(self) -> str:
        parts = [self.summary.strip()] if self.summary.strip() else []
        for title, text in self.sections:
            body = text.strip()
            if not body:
                continue
            parts.append(f"{title}\n{body}" if title and title != "개요" else body)
        return "\n\n".join(parts)


# --- XLSX 읽기 (표준 라이브러리만) ------------------------------------------

def read_xlsx_rows(path: Path, sheet: str = "xl/worksheets/sheet1.xml") -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = [
            "".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
            for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
        ]
        root = ET.fromstring(z.read(sheet))
    rows: list[list[str]] = []
    for r in root.iter(f"{{{ns['m']}}}row"):
        cells: dict[str, str] = {}
        for c in r.findall("m:c", ns):
            v = c.find("m:v", ns)
            s = v.text if v is not None and v.text else ""
            if c.get("t") == "s" and s:
                s = shared[int(s)]
            col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
            cells[col] = s
        width = max((ord(k) - 64 for k in cells), default=0)
        rows.append([cells.get(chr(65 + i), "") for i in range(max(width, 10))])
    return rows


def group_entities(rows: Iterable[list[str]]) -> list[Entity]:
    """행(절 단위) -> 항목. 열: 레벨아이디·링크정보·정보ID·링크명·유형·
    한글명칭·한자명칭·설명·제목·내용."""
    by_id: dict[str, Entity] = {}
    for r in rows:
        if len(r) < 10 or not r[1].startswith("kc_"):
            continue
        kc_id, kind, label, hanja, summary, title, text = (
            r[1], r[4], r[5].strip(), r[6].strip(), r[7].strip(), r[8].strip(), r[9].strip()
        )
        if not label:
            continue
        ent = by_id.get(kc_id)
        if ent is None:
            ent = by_id[kc_id] = Entity(kc_id, kind, label, hanja, summary)
        elif summary and not ent.summary:
            ent.summary = summary
        if title or text:
            ent.sections.append((title, text))
    return list(by_id.values())


def load_entities(raw_dir: Path = RAW_DIR) -> list[Entity]:
    ents = group_entities(read_xlsx_rows(raw_dir / YEONDAEGI))
    for ent in ents:
        if summary_is_alien(ent):
            log.warning("설명 칸이 딴 항목의 것이라 버린다: %s %s (%s)",
                        ent.kc_id, ent.label, ent.summary[:40])
            ent.summary = ""
    return ents


# --- 연도 ------------------------------------------------------------------

def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text or "") if s.strip()]


def _years_in(text: str, patterns=YEAR_PATTERNS) -> list[int]:
    out: list[int] = []
    for pat in patterns:
        for m in pat.finditer(text or ""):
            y = int(m.group(1))
            if y not in out:
                out.append(y)
    return out


def candidate_years(ent: Entity) -> list[int]:
    """그 일의 연도일 수 있는 해들, 믿을 만한 순서로.

    설명의 재위년 괄호 → 이름이 든 문장의 연도 → 설명 → 개요."""
    out: list[int] = []

    def add(ys: Iterable[int]) -> None:
        for y in ys:
            if y not in out:
                out.append(y)

    add(_years_in(ent.summary, (YEAR_REIGN,)))
    core = ent.core
    for sent in sentences(ent.summary + " " + ent.full_text()):
        if ent.label in sent or (len(core) >= 2 and core in sent):
            add(_years_in(sent))
    add(_years_in(ent.overview, (YEAR_REIGN,)))
    add(_years_in(ent.summary))
    add(_years_in(ent.overview))
    return out


def months_in(text: str, year: int) -> list[int]:
    """그 해에 **붙여 적힌** 달들. 문장이 해 다음에 바로 적은 것만 센다."""
    out: list[int] = []
    for m in MONTH_AFTER_YEAR.finditer(text or ""):
        if int(m.group(1)) != year:
            continue
        mo = int(m.group(2))
        if not 1 <= mo <= 12 or MONTH_RANGE.match(text, m.end()):
            continue
        if mo not in out:
            out.append(mo)
    return out


def month_of(ent: Entity, year: int | None) -> int | None:
    """설명·개요의 **첫 문장**이 말하는 그 해의 달. 갈리면 모르는 것으로 둔다.

    **본문은 보지 않는다.** 본문은 앞뒤 사건을 함께 말하므로 다른 일의 달이
    섞인다 — 황산대첩 본문은 같은 1380년의 진포대첩('8월')을 먼저 말하고,
    그 뒤에 황산의 9월이 온다. 설명('1380년 9월, 이성계 등이 …')과
    개요('1380년(우왕 6) 9월에')는 그 항목 자신을 정의하는 문장이다.

    **둘이 다르면 비운다.** 설명 칸은 한 줄로 줄이다 엉뚱한 달을 적기도
    한다 (실측: 명량해전의 설명은 이순신이 재임용된 '1597년 8월'을 적고,
    개요는 해전 자신의 '9월 16일'을 적는다). 어느 쪽이 맞는지 우리가 고를
    근거가 없으니 달은 없는 것으로 둔다."""
    if year is None:
        return None
    core = ent.core
    said = []
    for text in (ent.summary, ent.overview):
        head = (sentences(text) or [""])[0]
        # **그 문장이 이 항목을 부르고 있어야 한다.** 개요는 배경부터
        # 시작하기도 한다 — 6월민주화운동의 첫 문장은 '1987년 1월 박종철이
        # 고문으로 사망한 사건'이고, 제헌헌법의 첫 문장은 '1948년 5월 10일
        # 총선거'다. 둘 다 이 항목의 날이 아니라 그 앞의 일이다.
        if not (ent.label in head or (len(core) >= 2 and core in head)):
            continue
        months = months_in(head, year)
        if len(months) == 1:
            said.append(months[0])
    return said[0] if said and len(set(said)) == 1 else None


def dated(ent: Entity, year: int) -> tuple[str, dict]:
    """(날짜, 덧붙일 props). 달을 알면 해에 붙인다 — '1380' -> '1380-09'.

    연표는 몰린 해를 늘려 세우고 그 안의 차례를 달로 읽는다. 해만 적으면
    같은 해의 이웃 뒤에서 연도 칸이 비어 '연도를 모르는 사건'으로 보인다.
    달은 실록 날짜와 같은 규칙으로 **음력 그대로** 적고 밝힌다
    (모듈 머리글 '실록 날짜는 음력이다')."""
    month = month_of(ent, year)
    if month is None:
        return str(year), {}
    return f"{year}-{month:02d}", {} if year >= SOLAR_FROM else {"calendar": "lunar"}


def text_year(text: str) -> int | None:
    ys = _years_in(text)
    return ys[0] if ys else None


def entity_year(ent: Entity) -> int | None:
    """문장 규칙만으로 고른 연도 (실록·기존 노드 없이). 첫 후보다."""
    ys = candidate_years(ent)
    return ys[0] if ys else None


# 시대 창의 여유. 연대기 항목은 시대를 넘나드는 앞뒤를 같이 적는다
# (위화도 회군은 고려 항목이지만 1388년은 조선 창 쪽에 가깝다).
GUESS_MARGIN = (20, 30)


def era_window(ent: Entity) -> tuple[int, int]:
    """이 항목의 해가 들어야 할 창. `pick_target` 과 같은 여유를 쓴다."""
    _, (lo, hi) = ERA_DIGIT.get(ent.era_digit, (None, (-9999, 9999)))
    return lo - GUESS_MARGIN[0], hi + GUESS_MARGIN[1]


def summary_is_alien(ent: Entity) -> bool:
    """'설명' 칸이 이 항목이 아니라 딴 항목을 말하고 있는가.

    실측: 연대기의 '여진 정벌'(kc_i304300)은 조선 항목인데(본문이 태종~
    선조대의 파저강·모련위 정벌이다) 설명 칸에는 고려 예종의 1107년 정벌이
    적혀 있다. 화면은 이 칸을 설명의 첫 문단으로 그리므로, 조선 사건을 열면
    고려 이야기가 먼저 나온다 — 사용자가 지적한 자리다 (2026-09-04).

    **사건만 본다.** 인물의 설명 칸은 시대보다 앞선 해로 시작하는 것이
    당연하다 — 연대기가 근대로 분류한 이승훈(kc_n403710)의 설명은 1783년
    세례부터 말하는데, 칸이 틀린 게 아니라 분류가 그런 것이다. 실측 914
    항목에서 이 검사에 걸리는 것은 그 둘뿐이고, 사건으로 좁히면 하나다."""
    if ent.node_type != "event":
        return False
    years = _years_in(ent.summary)
    if not years:
        return False
    lo, hi = era_window(ent)
    return all(not (lo <= y <= hi) for y in years)


def era_of(ent: Entity, year: int | None) -> str | None:
    label, _ = ERA_DIGIT.get(ent.era_digit, (None, (-9999, 9999)))
    if ent.era_digit == "4" and year is not None:
        if year < 1897:
            return "조선"
        return "대한제국" if year < 1910 else "일제강점기"
    return label


# --- 실록 색인 ---------------------------------------------------------------

def _iter_articles(path: Path):
    """level5(기사) 하나씩. 국역이 없는 원문 XML 이지만 제목은 한글이다."""
    king = path.stem.split("_")[1] if "_" in path.stem else path.stem
    tree = ET.parse(path)
    for lv in tree.iter("level5"):
        art_id = lv.get("id", "")
        bib = lv.find("./front/biblioData")
        title = ""
        date = ""
        classes: list[str] = []
        if bib is not None:
            t = bib.find("./title/mainTitle")
            title = (t.text or "").strip() if t is not None else ""
            for d in bib.findall("./date/dateOccured"):
                if d.get("type") == "서기" and d.get("date"):
                    date = d.get("date", "")
            classes = [(c.text or "").strip() for c in bib.findall("subjectClass")]
        refs = sorted({
            ix.get("ref") for ix in lv.iter("index")
            if ix.get("type") == "이름" and ix.get("ref")
        })
        names = sorted({
            (ix.text or "").strip() for ix in lv.iter("index")
            if ix.get("type") == "이름" and ix.text
        })
        text = " ".join(
            "".join(p.itertext()).strip() for p in lv.iter("paragraph")
        )
        yield {
            "id": art_id, "king": king, "date": date, "title": title,
            "classes": "|".join(classes), "refs": "|".join(refs),
            "names": "|".join(names), "text": re.sub(r"\s+", " ", text),
        }


def build_sillok_index(raw_dir: Path = RAW_DIR, out: Path | None = None) -> int:
    """실록 XML -> `sillok.sqlite` (제목 트라이그램 FTS + 본문).
    RAG 저장소이자 연대기 사건의 날짜 근거다."""
    out = out or raw_dir / SILLOK_INDEX
    files = [p for d in SILLOK_DIRS for p in sorted((raw_dir / d).glob("*.xml"))]
    if not files:
        raise FileNotFoundError(f"실록 XML 이 없다: {raw_dir}")
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    conn.executescript(
        """CREATE TABLE articles (
             id TEXT PRIMARY KEY, king TEXT, date TEXT, title TEXT,
             classes TEXT, refs TEXT, names TEXT, text TEXT);
           CREATE VIRTUAL TABLE title_fts USING fts5(
             id UNINDEXED, title, tokenize='trigram');
           CREATE INDEX idx_articles_date ON articles(date);"""
    )
    n = 0
    for i, path in enumerate(files, 1):
        rows = list(_iter_articles(path))
        conn.executemany(
            "INSERT OR REPLACE INTO articles VALUES (:id,:king,:date,:title,:classes,:refs,:names,:text)",
            rows,
        )
        conn.executemany(
            "INSERT INTO title_fts (id, title) VALUES (:id, :title)", rows
        )
        n += len(rows)
        if i % 50 == 0:
            conn.commit()
            log.info("실록 색인 %d/%d 파일 · 기사 %s", i, len(files), f"{n:,}")
    conn.commit()
    conn.close()
    return n


class SillokIndex:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def article_people(self, art_id: str) -> tuple[frozenset[str], str]:
        """기사에 인명 색인으로 달린 한자 이름들과 원문 (없으면 빈 것)."""
        r = self.conn.execute(
            "SELECT names, text FROM articles WHERE id = ?", (art_id,)
        ).fetchone()
        if r is None:
            return frozenset(), ""
        return frozenset(n for n in (r["names"] or "").split("|") if n), r["text"] or ""

    def search_titles(self, term: str, limit: int = 300) -> list[sqlite3.Row]:
        # 트라이그램은 세 글자 미만을 못 찾는다 ('4군'·'6진'). 그건 LIKE 로.
        if len(term) < 3:
            return self.conn.execute(
                """SELECT id, date, title, king FROM articles
                    WHERE title LIKE ? ORDER BY date LIMIT ?""",
                (f"%{term}%", limit),
            ).fetchall()
        q = '"' + term.replace('"', '""') + '"'
        return self.conn.execute(
            """SELECT a.id, a.date, a.title, a.king FROM title_fts f
               JOIN articles a ON a.id = f.id
              WHERE title_fts MATCH ? ORDER BY a.date LIMIT ?""",
            (q, limit),
        ).fetchall()


def _search_terms(label: str) -> list[tuple[str, tuple[str, ...]]]:
    """(검색어, 제목에 전부 있어야 하는 낱말들).

    '4군 6진 개척' -> [('4군 6진 개척', ()), ('4군 6진', ()), ('6진', ('4군', '6진'))].
    꼬리말을 뗀 몸통은 세 글자 이상일 때만 — '기묘'·'신임'은 간지와
    사람 이름에 걸린다."""
    out: list[tuple[str, tuple[str, ...]]] = [(label, ())]
    core = TAIL.sub("", label)
    if core != label and len(core) >= 3:
        out.append((core, ()))
    toks = tuple(t for t in re.split(r"[\s·]+", core) if len(t) >= 2)
    if len(toks) >= 2:
        key = max(toks, key=len)
        out.append((key, toks))
        # 낱말 하나만으로도 찾는다 — 단 숫자가 든 것('6진')이나 세 글자
        # 이상만. 연도가 같은 해로 묶여 있어야 받으므로 여기까지 온다.
        for tok in toks:
            if any(ch.isdigit() for ch in tok) or len(tok) >= 3:
                out.append((tok, ()))
    return out


def _has_term(title: str, term: str) -> bool:
    """제목에 검색어가 **낱말로** 있는가. '이간의' 안의 '간의'는 아니다."""
    return re.search(r"(?<![가-힣0-9])" + re.escape(term), title) is not None


# 세우고·만들고·완성한 기사. 유물·단체의 날짜는 이런 기사에서만 받는다 —
# '규장각에 나아가 시사하다'(1777)는 규장각의 날짜가 아니다.
FOUNDING = re.compile(
    r"(설치|세우|창건|창설|건립|완공|완성|이루어지|반포|반사|편찬|찬술|찬수|창제|"
    r"간행|인출|올리|바치|짓|만들|개설|설립|처음|정하다|제정|시행|발행|주조)"
)


def _hits(index: SillokIndex, label: str) -> list[tuple[dict, str]]:
    """제목이 맞는 기사들 (날짜순), 어느 검색어로 걸렸는지 함께."""
    found: list[tuple[dict, str]] = []
    seen: set[str] = set()
    for term, must in _search_terms(label):
        for r in index.search_titles(term):
            if r["id"] in seen:
                continue
            if not _has_term(r["title"], term):
                continue
            if must and not all(_has_term(r["title"], t) for t in must):
                continue
            seen.add(r["id"])
            found.append((dict(r), term))
    found.sort(key=lambda h: h[0]["date"])
    return found


def date_from_sillok(
    index: SillokIndex, label: str, years: Iterable[int] | None,
    founding: bool = False,
) -> dict | None:
    """실록 제목으로 그 일의 날짜. 후보 연도 중 **같은 해** 기사가 있는
    첫 후보의 가장 이른 기사. 연도를 모르면 기사가 몇 건 안 될 때만.
    `founding` 이면 세우고·만든 기사만 받는다 (유물·단체)."""
    hits = _hits(index, label)
    if founding:
        hits = [h for h in hits if FOUNDING.search(h[0]["title"])]
    if not hits:
        return None
    years = list(years or [])
    if years:
        for y in years:
            same = [h for h in hits if h[0]["date"][:4].isdigit() and int(h[0]["date"][:4]) == y]
            if same:
                r, term = same[0]
                return {"id": r["id"], "date": r["date"], "title": r["title"], "term": term, "year": y}
        return None
    if len(hits) <= 5:
        r, term = hits[0]
        y = int(r["date"][:4]) if r["date"][:4].isdigit() else None
        return {"id": r["id"], "date": r["date"], "title": r["title"], "term": term, "year": y}
    return None


def sillok_events_for(
    index: SillokIndex, ent: Entity, years: Iterable[int], limit: int = 2
) -> list[dict]:
    """유물·단체 항목이 닿는 '세운·만든' 기사들 — 서로 다른 해로 최대 `limit`.
    훈민정음은 1443 창제와 1446 완성이 둘 다 사건이다."""
    out: list[dict] = []
    seen_years: set[int] = set()
    for y in years:
        if y in seen_years:
            continue
        hit = date_from_sillok(index, ent.label, [y], founding=True)
        if hit and len(hit["title"]) <= MAX_EVENT_TITLE and hit["id"] not in {h["id"] for h in out}:
            out.append(hit)
            seen_years.add(y)
        if len(out) >= limit:
            break
    return out


def named_in_article(hanja: str, names: frozenset[str], text: str) -> bool:
    """그 사람이 **그 기사에** 나오는가. 한자 이름이 인명 색인에 있거나 원문에
    글자 그대로 있어야 한다. 한글만 아는 사람은 원문(한문)에서 못 찾으므로
    아니다 — 모르면 잇지 않는다."""
    return bool(hanja) and (hanja in names or hanja in text)


def lunar_iso(date: str) -> str:
    """'1443-12-30L0' -> '1443-12-30'. 꼬리 L0/L1 은 윤달 표식."""
    return re.sub(r"L\d$", "", date or "")


# --- 실록 인물 CSV -------------------------------------------------------------

def load_persons_csv(raw_dir: Path = RAW_DIR) -> dict[tuple[str, str], tuple[str, str]]:
    """(한글명, 한자명) -> (생년, 몰년).

    같은 이름·한자가 여럿이면 **생몰년이 있는 것이 하나뿐일 때만** 그것을
    믿는다 — 이황(李滉)이 세 줄인데 둘은 빈 줄이다. 둘 이상이 연대를
    가지면 동명이인이므로 버린다."""
    files = list((raw_dir / PERSONS_CSV).glob("*인물.csv"))
    if not files:
        return {}
    dated: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    with open(files[0], encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("한글_명", "").strip(), row.get("한자_명", "").strip())
            if not key[0] or not key[1]:
                continue
            val = (row.get("생년", "").strip(), row.get("몰년", "").strip())
            if val[0] or val[1]:
                dated[key].append(val)
    return {k: v[0] for k, v in dated.items() if len(v) == 1}


# --- 기존 노드와 맞추기 ----------------------------------------------------------

def _refines(new: str | None, old: str | None) -> bool:
    """새 날짜가 옛 날짜를 **자세하게만** 만드는가. '1380' -> '1380-09'.

    두 자료가 같은 해를 말할 때 연대기가 달까지 적고 있으면 그 달을 받는다.
    이미 일 단위로 아는 날짜('1380-06-15')는 밀어내지 않는다 — 앞이 다르면
    같은 날의 더 자세한 표기가 아니라 **다른 날**이다."""
    return bool(new and old and new != old and new.startswith(old))


def _year_of(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^(-?)(\d{1,4})", value.strip())
    return int(m.group(2)) * (-1 if m.group(1) else 1) if m else None


class NodeIndex:
    """(타입, 이름) -> 노드들. 한 번 읽어 둔다 — 항목마다 SQL 로 물으면
    인명 언급 4만 건에 노드 표를 4만 번 훑는다 (실측: 2분을 넘겨 죽었다)."""

    def __init__(self, store: GraphStore):
        self.by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.rows: dict[str, dict] = {}
        deg: Counter = Counter()
        for r in store.conn.execute(
            "SELECT src AS id, COUNT(*) AS n FROM edges GROUP BY src "
            "UNION ALL SELECT dst, COUNT(*) FROM edges GROUP BY dst"
        ):
            deg[r["id"]] += r["n"]
        for r in store.conn.execute(
            "SELECT id, type, label, source, start_date, end_date, props FROM nodes"
        ):
            self.rows[r["id"]] = {
                "id": r["id"], "type": r["type"], "label": r["label"],
                "source": r["source"], "start_date": r["start_date"],
                "end_date": r["end_date"], "props": json.loads(r["props"] or "{}"),
                "d": deg.get(r["id"], 0),
            }
        for row in self.rows.values():
            self.by_key[(row["type"], row["label"])].append(row)
        for r in store.conn.execute("SELECT node_id, alias FROM aliases"):
            row = self.rows.get(r["node_id"])
            if row is not None and row not in self.by_key[(row["type"], r["alias"])]:
                self.by_key[(row["type"], r["alias"])].append(row)

    def candidates(self, label: str, node_type: str) -> list[dict]:
        return list(self.by_key.get((node_type, label), []))


def pick_target(
    index: NodeIndex, ent: Entity, years: Iterable[int] | None = None,
    birth: int | None = None,
) -> tuple[str | None, list[str], list[str]]:
    """(합칠 노드 id, 흡수할 ex: 고아들, 보고할 후보들).

    `years` 는 사건의 후보 연도들, `birth` 는 실록 인물 CSV 의 생년."""
    rows = index.candidates(ent.label, ent.node_type)
    orphans = [r["id"] for r in rows if r["id"].startswith("ex:")]
    real = [r for r in rows if not r["id"].startswith("ex:")]
    years = list(years or [])

    _, (lo, hi) = ERA_DIGIT.get(ent.era_digit, (None, (-9999, 9999)))
    fit: list[dict] = []
    for r in real:
        y = _year_of(r["start_date"])
        if y is None:
            fit.append(r)
        elif ent.node_type == "person":
            if birth is not None:
                if abs(y - birth) <= 1:
                    fit.append(r)
            elif lo - 80 <= y <= hi:
                fit.append(r)
        elif len(real) == 1:
            # 이름이 같은 사건이 하나뿐이면 시대 창만 본다. 연대기 문장의
            # 연도는 배경일 때가 있어(병인양요 항목의 첫 해는 1784) 그걸로
            # 거르면 같은 사건이 둘이 된다.
            if lo - 20 <= y <= hi + 30:
                fit.append(r)
        elif years:
            if any(abs(y - c) <= 2 for c in years):
                fit.append(r)
        elif lo <= y <= hi:
            fit.append(r)
    if not fit:
        return None, orphans, [r["id"] for r in real]
    if len(fit) == 1:
        return fit[0]["id"], orphans, []
    fit.sort(key=lambda r: -r["d"])
    if fit[0]["d"] >= 2 * fit[1]["d"] + 1:
        return fit[0]["id"], orphans, [r["id"] for r in fit[1:]]
    return None, orphans, [r["id"] for r in fit]


# --- 인물 언급 -----------------------------------------------------------------

def mentions(
    text: str, plain_names: Iterable[str] = (), plain_text: str | None = None
) -> list[tuple[str, str, str]]:
    """(이름, 한자 또는 '', 근거 문장).

    한자 표기 언급은 `text` 전체에서, 맨 이름 언급은 `plain_text`(없으면
    `text`)에서만 찾는다 — 맨 이름은 설명·개요에 한정하려는 것이다."""
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sent in sentences(text):
        for m in NAME_HANJA.finditer(sent):
            key = (m.group(1), m.group(2))
            if key not in seen:
                seen.add(key)
                out.append((m.group(1), m.group(2), sent))
    plain = sorted({n for n in plain_names if len(n) >= 2}, key=len, reverse=True)
    if not plain:
        return out
    plain_re = re.compile("(" + "|".join(re.escape(n) for n in plain) + ")" + AFTER_NAME)
    for sent in sentences(text if plain_text is None else plain_text):
        for m in plain_re.finditer(sent):
            name = m.group(1)
            # 앞이 한글이면 다른 낱말의 꼬리다 ('명종' 안의 '종')
            if m.start() > 0 and re.match(r"[가-힣]", sent[m.start() - 1]):
                continue
            if any(k[0] == name for k in seen):
                continue
            seen.add((name, ""))
            out.append((name, "", sent))
    return out


# --- 수집 ----------------------------------------------------------------------

@dataclass(slots=True)
class Report:
    matched: int = 0
    created: int = 0
    ambiguous: list[tuple[str, list[str]]] = field(default_factory=list)
    dated_sillok: int = 0
    dated_agree: int = 0
    dated_text: int = 0
    date_conflicts: list[tuple[str, int | None, int]] = field(default_factory=list)
    undated_events: list[str] = field(default_factory=list)
    person_dates: int = 0
    sillok_events: int = 0
    edges_participated: int = 0
    dead_mentions: int = 0
    absent_mentions: int = 0     # 항목 본문엔 있으나 실록 기사엔 없는 사람
    edges_period: int = 0
    merges: list[tuple[str, str]] = field(default_factory=list)   # (ex 고아, 정본)
    unresolved_mentions: Counter = field(default_factory=Counter)


def resolve_date(
    ent: Entity, index: SillokIndex | None, existing_year: int | None
) -> tuple[str | None, str | None, dict]:
    """(날짜, 근거, 덧붙일 props). 모듈 머리글의 규칙 1~4."""
    cands = candidate_years(ent)
    agreed = existing_year if existing_year is not None and existing_year in cands else None
    order = ([agreed] + [y for y in cands if y != agreed]) if agreed is not None else list(cands)
    # 기존 노드의 연도가 후보에 없어도 실록에는 물어본다 — 병인양요의
    # 연대기 문장은 1784년(천주교 전래)부터 말하지만 Wikidata 는 1866 을
    # 안다. 그 해에 기사가 있으면 그것이 답이다.
    if existing_year is not None and existing_year not in order:
        order.append(existing_year)
    if ent.node_type != "event":
        # 유물·단체는 세운 해가 곧 그 해다. 후보 순서가 아니라 **가장 이른
        # 해**부터 — 집현전 항목은 폐지(1456)를 설치(1420)보다 먼저 말한다.
        order = sorted(order)
    hit = (
        date_from_sillok(index, ent.label, order or None, founding=ent.node_type != "event")
        if index is not None else None
    )
    if hit:
        return lunar_iso(hit["date"]), "실록 기사", {
            "calendar": "lunar", "sillok_id": hit["id"],
            "sillok_title": hit["title"], "sillok_term": hit["term"],
        }
    if agreed is not None:
        date, props = dated(ent, agreed)
        return date, "연대기·기존 일치", props
    # 짐작한 해는 **그 항목의 시대 안**에 들어야 한다. 실측: '여진 정벌'
    # (kc_i304300) 은 조선 항목인데 연대기의 '설명' 칸에 고려 예종의
    # 여진 정벌(1107)이 적혀 있다 — 본문은 태종~선조대를 말하는데 설명만
    # 딴 사건이다. 첫 후보를 그대로 쓰면 조선 사건이 1107년 자리에 서고,
    # 화면에서는 고려 사건이 조선에 붙은 것으로 읽힌다.
    #
    # 실록 기사·기존 노드와의 일치는 자료끼리 맞춘 것이라 창을 안 본다.
    # 창을 보는 것은 **우리가 고른 첫 후보뿐**이다.
    lo, hi = era_window(ent)
    fits = [y for y in cands if lo <= y <= hi]
    if fits:
        date, props = dated(ent, fits[0])
        return date, "연대기 설명", {"date_uncertain": True, **props}
    return None, None, {}


def ingest(
    store: GraphStore,
    raw_dir: Path = RAW_DIR,
    index: SillokIndex | None = None,
    kinds: tuple[str, ...] | None = None,
) -> tuple[list[Node], list[Edge], Report]:
    entities = load_entities(raw_dir)
    if kinds:
        entities = [e for e in entities if e.kind in kinds]
    persons_csv = load_persons_csv(raw_dir)
    rep = Report()
    nodes_index = NodeIndex(store)

    # 1) 항목마다 노드 id 를 정한다
    target: dict[str, str] = {}
    years: dict[str, list[int]] = {}
    for ent in entities:
        birth = None
        if ent.node_type == "person":
            cy = candidate_years(ent) if not ent.hanja else []
            csv_dates = persons_csv.get((ent.label, ent.hanja)) if ent.hanja else None
            if csv_dates and csv_dates[0].isdigit():
                birth = int(csv_dates[0])
            years[ent.kc_id] = cy
        else:
            years[ent.kc_id] = candidate_years(ent)
        nid, orphans, others = pick_target(nodes_index, ent, years[ent.kc_id], birth)
        if nid is None:
            nid = f"nikh:{ent.kc_id}"
            rep.created += 1
            if others:
                rep.ambiguous.append((ent.label, others))
        else:
            rep.matched += 1
            if others:
                rep.ambiguous.append((ent.label, [nid, *others]))
        target[ent.kc_id] = nid
        rep.merges.extend((o, nid) for o in orphans if o != nid)

    # 연대기 인물: 이름 -> 항목 (참여 엣지의 도착점)
    by_name: dict[str, list[Entity]] = defaultdict(list)
    for ent in entities:
        if ent.node_type == "person":
            by_name[ent.label].append(ent)

    person_life: dict[str, tuple[int | None, int | None]] = {}
    for ent in entities:
        if ent.node_type == "person" and ent.hanja:
            d = persons_csv.get((ent.label, ent.hanja))
            if d:
                b, dd = d
                person_life[target[ent.kc_id]] = (
                    int(b) if b.isdigit() else None, int(dd) if dd.isdigit() else None
                )

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for ent in entities:
        nid = target[ent.kc_id]
        existing = nodes_index.rows.get(nid)
        props = dict(existing["props"]) if existing else {}
        props.update({
            "canon": SOURCE, "nikh_id": ent.kc_id, "kind": ent.kind,
            "nikh_url": f"https://contents.history.go.kr/front/kc/view.do?levelId={ent.kc_id}",
            # 설명을 덮어쓰므로 출처 표식도 제 것이어야 한다. 위키백과의
            # `kowiki` 가 남아 있으면 화면이 국편 글을 위키백과 글이라 적는다
            # (배포본에 21건 있었다).
            "desc_source": SOURCE,
        })
        if ent.hanja:
            props["hanja"] = ent.hanja
        start = end = None
        old_start = _year_of(existing["start_date"]) if existing else None
        old_end = _year_of(existing["end_date"]) if existing else None
        year: int | None = None
        hit_props: dict = {}

        if ent.node_type == "person":
            csv_dates = persons_csv.get((ent.label, ent.hanja)) if ent.hanja else None
            if csv_dates:
                b, d = csv_dates
                # 해가 같으면 이미 있는 (더 정밀한) 날짜를 둔다
                if b.isdigit() and int(b) != old_start:
                    start = b
                if d.isdigit() and int(d) != old_end:
                    end = d
                if start or end:
                    props["date_basis"] = "실록 인물"
                    rep.person_dates += 1
                year = int(b) if b.isdigit() else None
            era = era_of(ent, year)
            if era and not props.get("polity"):
                props["polity"] = era
        else:
            date, basis, hit_props = resolve_date(ent, index, old_start)
            year = _year_of(date)
            if basis == "실록 기사":
                start = date
                rep.dated_sillok += 1
            elif basis == "연대기·기존 일치":
                if old_start is None or _refines(date, existing["start_date"]):
                    start = date
                rep.dated_agree += 1
            elif basis == "연대기 설명":
                if old_start is None:
                    start = date
                    rep.dated_text += 1
                elif year != old_start:
                    rep.date_conflicts.append((ent.label, year, old_start))
                    hit_props = {}
                    year = old_start
            elif ent.node_type == "event":
                if old_start is None:
                    rep.undated_events.append(ent.label)
                year = old_start
            if basis and (start or basis != "연대기 설명"):
                props["date_basis"] = basis
            props.update(hit_props)
            era = era_of(ent, year)
            if ent.node_type == "event" and era:
                props["seed_era"] = era

        old_label = existing["label"] if existing else None
        label = old_label if old_label and has_hangul(old_label) else ent.label
        aliases = [ent.label] if ent.label != label else []
        # 기존 노드는 소스 열을 그대로 둔다 (wd 는 QID 공간의 표식이다).
        # 정본이 씌워졌다는 것은 props.canon 이 말한다.
        nodes[nid] = Node(
            id=nid, type=ent.node_type, label=label,
            source=existing["source"] if existing else SOURCE,
            aliases=aliases, start_date=start, end_date=end,
            description=ent.full_text() or None,
            url=props["nikh_url"] if nid.startswith("nikh:") else None,
            props=props,
        )

        if era and POLITY_QID.get(era) and ent.node_type in ("heritage", "person", "event", "org", "concept"):
            pid = f"wd:{POLITY_QID[era]}"
            if pid != nid:
                edges.append(Edge(src=nid, dst=pid, type="from_period", source=SOURCE))
                rep.edges_period += 1

        # 2) 유물·단체·개념이 실록의 '세운·만든' 기사에 닿으면 그 기사가 사건이다
        event_ids: list[tuple[str, int | None]] = (
            [(nid, year)] if ent.node_type == "event" else []
        )
        # 실록 기사 -> (인명 색인 한자, 원문). 항목 본문의 언급을 그 기사에
        # 이을지 가리는 근거다.
        article_people: dict[str, tuple[frozenset[str], str]] = {}
        if ent.node_type in ("heritage", "org", "concept") and index is not None:
            order = list(candidate_years(ent))
            if old_start is not None and old_start not in order:
                order.append(old_start)
            # 책은 창제·완성·반포가 다 사건이라 둘까지, 단체는 세운 해 하나.
            limit = 2 if ent.node_type == "heritage" else 1
            for hit in sillok_events_for(index, ent, sorted(order), limit=limit):
                eid = f"sillok:{hit['id']}"
                e_start = lunar_iso(hit["date"])
                nodes[eid] = Node(
                    id=eid, type="event", label=hit["title"], source=SOURCE,
                    start_date=e_start, description=ent.summary or None,
                    url=f"https://sillok.history.go.kr/id/{hit['id'].replace('w', 'k', 1)}",
                    props={
                        "canon": SOURCE, "nikh_id": ent.kc_id, "seed_era": era,
                        "date_basis": "실록 기사", "calendar": "lunar",
                        "sillok_id": hit["id"], "about": nid,
                    },
                )
                edges.append(Edge(src=eid, dst=nid, type="related_to", source=SOURCE,
                                  label="이 기사의 대상"))
                if era and POLITY_QID.get(era):
                    edges.append(Edge(src=eid, dst=f"wd:{POLITY_QID[era]}",
                                      type="from_period", source=SOURCE))
                event_ids.append((eid, _year_of(e_start)))
                article_people[eid] = index.article_people(hit["id"])
                rep.sillok_events += 1

        # 3) 참여자 — 본문의 이름 언급. 그 해에 살아 있던 사람만.
        #
        # 항목이 **단체·유물**이고 사건이 실록 기사일 때는 하나 더 본다: 그
        # 사람의 한자 이름이 **그 기사에** 있는가. 「규장각」 항목 본문은
        # 정조 사후 김조순이 어떻게 컸는지까지 말하는데, 그 문장이 1781년
        # '규장각에서 고사 절목을 올리다' 기사의 참여 근거로 서 있었다
        # (14명, 기사엔 아무도 없었다). 항목 본문의 언급은 그 항목에 얽힌
        # 사람이지 기사 한 건의 참여자가 아니다.
        if event_ids:
            plain = [
                n for n, es in by_name.items()
                if len(es) == 1 and es[0].era_digit == ent.era_digit
            ]
            head = (ent.summary + " " + ent.overview).strip()
            linked: set[tuple[str, str]] = set()
            for name, hanja, sent in mentions(ent.full_text(), plain, plain_text=head):
                pid = _resolve_person(nodes_index, name, hanja, by_name, target, ent)
                if pid is None:
                    rep.unresolved_mentions[name] += 1
                    continue
                life = person_life.get(pid) or _life_of_row(nodes_index.rows.get(pid))
                for eid, ey in event_ids:
                    if pid in (nid, eid) or (pid, eid) in linked:
                        continue
                    if not _alive(life, ey):
                        rep.dead_mentions += 1
                        continue
                    if eid in article_people and not named_in_article(
                        hanja, *article_people[eid]
                    ):
                        rep.absent_mentions += 1
                        continue
                    linked.add((pid, eid))
                    edges.append(Edge(
                        src=pid, dst=eid, type="participated_in", source=SOURCE,
                        confidence=1.0 if hanja else 0.95,
                        props={"evidence": sent[:300], "extracted_from": ent.kc_id},
                    ))
                    rep.edges_participated += 1

    return list(nodes.values()), edges, rep


def _life_of_row(row: dict | None) -> tuple[int | None, int | None]:
    if not row:
        return (None, None)
    return (_year_of(row.get("start_date")), _year_of(row.get("end_date")))


def _alive(life: tuple[int | None, int | None], year: int | None) -> bool:
    """생몰년을 아는 사람이 그 해에 살아 있었나. 모르면 True."""
    if year is None:
        return True
    birth, death = life
    if birth is not None and year < birth:
        return False
    if death is not None and year > death:
        return False
    return True


# 관청·건물·문 이름의 꼬리 글자. '이문원(摛文院)' 은 규장각의 부속 건물인데
# 이름이 같은 인물 이문원(李文源) 노드에 맞춰졌다. 연대기 항목의 한자와
# 맞출 때는 문제가 없고, 이름만으로 기존 노드를 고르는 갈래에서만 본다.
NOT_A_PERSON = re.compile(r"[院館閣殿堂寺門宮城署廳府司曹監庫樓臺陵廟壇]$")


def _resolve_person(
    index: NodeIndex, name: str, hanja: str,
    by_name: dict[str, list[Entity]], target: dict[str, str], ctx: Entity,
) -> str | None:
    ents = by_name.get(name, [])
    if hanja:
        same = [e for e in ents if e.hanja == hanja]
        if len(same) == 1:
            return target[same[0].kc_id]
    if len(ents) == 1 and (not hanja or not ents[0].hanja or ents[0].hanja == hanja):
        return target[ents[0].kc_id]
    if not hanja or NOT_A_PERSON.search(hanja):
        return None
    # 연대기에 없는 사람: 기존 인물 노드가 하나뿐이고 시대가 맞으면
    _, (lo, hi) = ERA_DIGIT.get(ctx.era_digit, (None, (-9999, 9999)))
    rows = [r for r in index.candidates(name, "person") if not r["id"].startswith("ex:")]
    fit = []
    for r in rows:
        y = _year_of(r["start_date"])
        if y is None or lo - 80 <= y <= hi:
            fit.append(r)
    return fit[0]["id"] if len(fit) == 1 else None


def drop_sillok_participation(store: GraphStore) -> int:
    """이전 `nikh` 가 실록 기사에 붙인 참여 엣지를 지운다. `ingest` 가 매번
    전부 다시 만드는 것이라, 지우지 않으면 관문이 걸러낸 것이 남는다."""
    cur = store.conn.execute(
        """DELETE FROM edges
            WHERE source = ? AND type = 'participated_in' AND dst LIKE 'sillok:%'""",
        (SOURCE,),
    )
    store.conn.commit()
    return cur.rowcount


def apply_merges(store: GraphStore, merges: list[tuple[str, str]]) -> int:
    """`ex:` 고아를 정본 노드로 흡수한다 (노드가 저장된 뒤에 부른다)."""
    from ..promote import merge_node

    done = 0
    for old, new in merges:
        exists = store.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (new,)).fetchone()
        if exists is None:
            continue
        merge_node(store, old, new, method="nikh:label")
        done += 1
    store.conn.commit()
    return done
