"""중복 관문 — 한 사건이 두 노드로 들어와 있는 것을 찾는다.

**발단.** 2026-09-04 지적: "사도세자 사건과, 임오화변은 같은거야. 둘중
하나로 통일 시켜야해." 실제로 두 노드였다 — `nikh:kc_i303100`(사도세자
사건)과 `wd:Q18685040`(임오화변). 둘 다 1762년 영조가 세자를 뒤주에 가둔
그 일이고, **양쪽 설명이 서로를 이칭으로 부르고 있었다.**

이름이 갈리는 이유는 소스마다 표제를 다르게 다는 데 있다. 국편은
'사도세자 사건', 위키백과는 '임오화변'이다. 띄어쓰기만 달라지는 것도
같은 원인이다 ('3·1 운동' / '3·1운동', '만보산 사건' / '만보산사건').

**찾는 규칙은 다섯이다. 판정에 짐작을 넣지 않는다.**

| 규칙 | 무엇을 보나 | 예 |
|---|---|---|
| `라벨` | 공백·가운뎃점·괄호를 지우면 같은 이름 | `만보산 사건` / `만보산사건` |
| `별칭` | 한쪽의 라벨이 다른 쪽의 별칭 | `조일동맹조약` / `조일맹약` |
| `이칭` | 설명 첫 문장이 상대를 '또는 …', '…이라고도 한다'로 부른다 | `임오화변` / `사도세자 사건` |
| `설명` | 설명 첫 문장이 글자 그대로 같다 (같은 문서가 두 노드에) | `진주민란` / `임술민란` |
| `핵심어` | 갈래 접미사(전투·대첩·사건…)를 떼면 같은 이름 | `홍산대첩` / `홍산 전투` |

**규칙은 후보를 찾을 뿐, 합치지 않는다.** 라벨 유사도로 합치면 절반이
틀린다 (`promote.title_variant_matches` 주석의 실측). 여기서도 같다:
`제1차 왕자의 난`과 `제2차 왕자의 난`은 핵심어가 같지만 다른 사건이고,
`설마리 전투`(1951)는 스스로를 '임진강 전투'라 부르지만 그래프의
`임진강 전투`는 1592년 것이다. 그래서 **후보마다 사람이 한 줄을 적는다**
(`data/duplicates.tsv`):

    merge<TAB>남길 id<TAB>없앨 id<TAB>근거
    keep <TAB>id       <TAB>id      <TAB>왜 다른 사건인지

표에 없는 후보가 남아 있으면 명령이 **종료 코드 1**로 묻는다. 사람이
기억하는 대신 기계가 묻는 것은 CLAUDE.md §1 의 관문들과 같은 방식이다.

**한 번 합치고 끝나는 게 아니다.** `upsert_nodes` 는 id 로 노드를 다시
세우므로, 다음 `ingest`·`nikh` 가 없앤 노드를 되살린다. `relabel` 과
똑같이 **수집 뒤마다 다시 돌리는 것을 전제로** 만들었다 — 같은 표를 몇
번 적용해도 결과가 같다(멱등). 화면이 읽는 파생본에도 한 번 더 돌린다:

    uv run histgraph dedupe --apply
    uv run histgraph --db data/korea.sqlite dedupe --apply

**남길 쪽을 고르는 기준.** 표에 사람이 적지만, 기본은 *더 많이 연결된
노드*다 — 엣지가 그 노드에 이미 쌓여 있으면 옮길 것이 적고, 화면에서
사라지는 이름은 별칭으로 남아 검색에 계속 걸린다(`promote.merge_node`).
설명이 국편(nikh)에만 있는 쪽을 없앨 때는 설명을 옮겨 적는다 — 국편이
정본이다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# 갈래 접미사. '홍산대첩'과 '홍산 전투'가 같은 싸움임을 보려면 떼야 한다.
KIND_SUFFIX = re.compile(
    r"(전투|해전|대첩|싸움|사건|의난|난|운동|혁명|개혁|조약|협약|전쟁|정변"
    r"|사화|민란|봉기|항쟁|의거|참변|학살|화변|옥사|반정)$"
)

# 차수. 이것이 어긋나면 **다른 사건이다** — 후보로도 올리지 않는다.
ORDINAL = re.compile(r"^(?:제\s*(\d+)\s*차?|(\d+)\s*차)")

# 라벨에서 지워도 같은 이름인 것들.
PUNCT = re.compile(r"[\s·․‧,.\-–—()·『』「」《》]")

# 이칭 선언 문형. `{n}` 자리에 상대의 라벨이 들어간다.
ALIAS_PHRASES = (
    r"(?:‘|'|“|\")?{n}(?:’|'|”|\")?(?:\([^)]*\))?\s*(?:이)?(?:라고도|로도)"
    r"\s*(?:한다|불린|부른|불리)",
    r"(?:또는|혹은)\s*{n}",
    r"{n}(?:\([^)]*\))?\s*(?:또는|혹은)",
    r"(?:이칭|다른 이름은?|달리)\s*(?:‘|')?{n}",
)

# 이 말이 첫 문장에 없으면 이칭 선언이 아니다 (값싼 사전 거르개).
_ALIAS_MARKERS = ("또는", "혹은", "라고도", "로도", "이칭", "다른 이름", "달리")

# 이칭을 찾을 때 상대 이름 앞에 차수가 붙어 있으면 다른 사건을 부른 것이다.
_ORD_BEFORE = re.compile(r"(제\s*\d+\s*차|제\s*\d+|\d+\s*차)\s*$")


class DuplicateTableError(ValueError):
    """표가 깨졌다 — 조용히 넘어가면 반쯤 합쳐진 그래프가 남는다."""


@dataclass(frozen=True, slots=True)
class Candidate:
    rule: str
    a: str            # id (더 많이 연결된 쪽을 앞에 둔다)
    b: str
    evidence: str

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.a, self.b))


@dataclass(slots=True)
class Verdict:
    action: str       # 'merge' | 'keep'
    keep: str
    drop: str
    note: str = ""

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.keep, self.drop))


@dataclass(slots=True)
class Report:
    candidates: list[Candidate] = field(default_factory=list)
    auto_same: list[tuple[Candidate, str]] = field(default_factory=list)
    auto_diff: list[tuple[Candidate, str]] = field(default_factory=list)
    unjudged: list[Candidate] = field(default_factory=list)   # 모름 — 표로 넘긴다
    merged: list[tuple[str, str, int]] = field(default_factory=list)  # (남긴, 없앤, 옮긴 엣지)
    absent: list[Verdict] = field(default_factory=list)   # 이 그래프에 없는 짝
    stale: list[Verdict] = field(default_factory=list)    # 이미 합쳐진 짝
    date_clashes: list[str] = field(default_factory=list)  # 합친 짝의 연대가 어긋난다


# --- 표 -------------------------------------------------------------------


def load_table(path: Path) -> list[Verdict]:
    """`판정<TAB>id<TAB>id<TAB>근거` 표를 읽는다."""
    rows: list[Verdict] = []
    seen: set[frozenset[str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 3:
            raise DuplicateTableError(
                f"{path}:{lineno} 탭으로 나뉜 세 칸이 필요합니다: {raw!r}")
        action, keep, drop = (p.strip() for p in parts[:3])
        note = parts[3].strip() if len(parts) > 3 else ""
        if action not in ("merge", "keep"):
            raise DuplicateTableError(
                f"{path}:{lineno} 판정은 merge 또는 keep 입니다: {action!r}")
        if not keep or not drop or keep == drop:
            raise DuplicateTableError(f"{path}:{lineno} 서로 다른 두 id 가 필요합니다: {raw!r}")
        v = Verdict(action, keep, drop, note)
        if v.key in seen:
            raise DuplicateTableError(f"{path}:{lineno} 같은 짝이 두 번 적혔습니다: {raw!r}")
        seen.add(v.key)
        rows.append(v)
    return rows


# --- 규칙 -----------------------------------------------------------------


def _ordinal(label: str) -> str | None:
    m = ORDINAL.match(label.replace(" ", ""))
    if not m:
        return None
    return m.group(1) or m.group(2)


def core_name(label: str) -> str:
    """차수와 갈래 접미사를 뗀 핵심어. '제2차 진주성 전투' -> '진주성'."""
    s = PUNCT.sub("", label)
    s = ORDINAL.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = KIND_SUFFIX.sub("", s)
    return s


def lead_sentence(desc: str | None, limit: int = 400) -> str:
    """설명의 첫 문장. 이칭 선언은 여기에만 온다 — 뒤쪽 문장에서 찾으면
    본문이 언급한 남의 사건까지 이칭으로 읽는다."""
    d = (desc or "").strip()
    if not d:
        return ""
    m = re.search(r"(?<=다)\.", d[:limit])
    return d[: m.end()] if m else d[:200]


def _degree(conn: sqlite3.Connection) -> dict[str, int]:
    deg: dict[str, int] = {}
    for r in conn.execute(
        "SELECT id, (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) d"
        " FROM nodes n"
    ):
        deg[r["id"]] = r["d"]
    return deg


def find(conn: sqlite3.Connection, node_type: str = "event") -> list[Candidate]:
    """중복 후보를 규칙별로 찾는다. 큰 쪽(엣지가 많은 쪽)을 앞에 둔다."""
    nodes = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, start_date, description FROM nodes WHERE type = ?",
            (node_type,),
        )
    }
    deg = _degree(conn)
    about = {
        r["id"]: r["about"]
        for r in conn.execute(
            "SELECT id, json_extract(props,'$.about') AS about FROM nodes"
            " WHERE type = ? AND about IS NOT NULL", (node_type,))
    }
    by_label: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        by_label.setdefault(n["label"], []).append(nid)

    # `same_as` 로 이어 둔 짝은 뺀다. 이미 같은 것이라 알고 있고, 그럼에도
    # 두 노드로 두는 것이 엔티티 해소의 설계다 — 국가유산청의 '서울 종로구'
    # 와 Wikidata 의 '종로구'는 서로 다른 소스의 열쇠를 들고 있어서, 합치면
    # 다음 수집이 다시 둘로 만든다 (`resolve` 모듈 머리글).
    linked: set[frozenset[str]] = set()
    try:
        for r in conn.execute("SELECT a, b FROM same_as"):
            linked.add(frozenset((r["a"], r["b"])))
    except sqlite3.OperationalError:
        pass                                   # same_as 가 없는 파생본

    found: dict[frozenset[str], Candidate] = {}

    def rank(i: str) -> tuple:
        # 남길 쪽. **설명이 있는 노드가 먼저다** — 국가유산청 목록에는
        # 이름과 관리번호만 있는 빈 줄이 섞여 들어와 있어서, 엣지 수만
        # 보면 알맹이가 있는 줄을 지우고 빈 줄을 남기게 된다.
        return (0 if (nodes[i]["description"] or "").strip() else 1,
                -deg.get(i, 0), i)

    def add(rule: str, x: str, y: str, evidence: str) -> None:
        a, b = sorted((x, y), key=rank)
        key = frozenset((a, b))
        if key in linked:
            return
        if key not in found:
            found[key] = Candidate(rule, a, b, evidence)

    # 규칙 1 — 공백·구두점만 다른 라벨.
    flat: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        flat.setdefault(PUNCT.sub("", n["label"]), []).append(nid)
    for name, ids in flat.items():
        if len(ids) > 1:
            for i, x in enumerate(ids):
                for y in ids[i + 1:]:
                    add("라벨", x, y, f"공백·구두점을 지우면 '{name}'")

    # 규칙 2 — 한쪽의 라벨이 다른 쪽의 별칭.
    for r in conn.execute("SELECT node_id, alias FROM aliases"):
        holder, alias = r["node_id"], r["alias"]
        if holder not in nodes:
            continue
        for other in by_label.get(alias, ()):
            if other != holder:
                add("별칭", holder, other,
                    f"'{alias}' 이 {nodes[holder]['label']} 의 별칭")

    # 규칙 3 — 설명 첫 문장의 이칭 선언.
    names = sorted((n for n in by_label if len(n) >= 3), key=len, reverse=True)
    for nid, n in nodes.items():
        head = lead_sentence(n["description"])
        # 자기 이름이 첫 문장에 없으면 그 문장은 이 노드를 정의하는 문장이
        # 아니다 ('조선의 역사' 가 본문에서 임진왜란을 부르는 것).
        if not head or n["label"] not in head:
            continue
        # 이칭 문형이 없으면 이름을 하나하나 맞춰 볼 것도 없다. 인물 3만
        # 개짜리 타입에서 이 한 줄이 전수 조사를 몇 분에서 몇 초로 줄인다.
        if not any(w in head for w in _ALIAS_MARKERS):
            continue
        for name in names:
            if name == n["label"] or name not in head:
                continue
            for phrase in ALIAS_PHRASES:
                hit = next(
                    (m for m in re.finditer(phrase.format(n=re.escape(name)), head)
                     if not _ORD_BEFORE.search(head[: m.start()])),
                    None,
                )
                if hit is None:
                    continue
                for other in by_label[name]:
                    if other != nid:
                        add("이칭", nid, other,
                            f"{n['label']} 의 설명이 '{hit.group(0).strip()}'")
                break

    # 규칙 4 — 설명 첫 문장이 글자 그대로 같다. 같은 문서가 두 노드에 붙은
    # 것이다 ('진주민란'과 '임술민란'이 임술농민봉기 문서를 같이 썼다).
    # **이름이 하나도 안 겹쳐도 잡히는 유일한 규칙**이다.
    #
    # 한 항목을 설명하는 여러 실록 기사는 뺀다 — 《고려사》를 올린 기사가
    # 둘이면 설명이 같은 게 당연하다 (`props.about` 이 그 항목을 가리킨다).
    same_lead: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        head = re.sub(r"\s+", "", lead_sentence(n["description"]))
        if len(head) >= 40:
            same_lead.setdefault(head, []).append(nid)
    for ids in same_lead.values():
        if len(ids) > 1:
            for i, x in enumerate(ids):
                for y in ids[i + 1:]:
                    ax, ay = about.get(x), about.get(y)
                    if ax is not None and ax == ay:
                        continue
                    add("설명", x, y, "설명 첫 문장이 글자 그대로 같다 — 같은 문서에서 왔다")

    # 규칙 5 — 갈래 접미사를 뗀 핵심어가 같다. 차수가 어긋나면 다른 사건이다.
    cores: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        c = core_name(n["label"])
        if len(c) >= 2:
            cores.setdefault(c, []).append(nid)
    for c, ids in cores.items():
        if len(ids) < 2:
            continue
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                ox, oy = _ordinal(nodes[x]["label"]), _ordinal(nodes[y]["label"])
                if ox is not None and oy is not None and ox != oy:
                    continue                      # 제1차 ≠ 제2차
                add("핵심어", x, y, f"갈래를 떼면 '{c}'")

    order = {"라벨": 0, "별칭": 1, "이칭": 2, "설명": 3, "핵심어": 4}
    return sorted(found.values(), key=lambda c: (order[c.rule], c.a))


# --- 이름 말고 무엇이 같은가 ------------------------------------------------
#
# 사건은 이름이 거의 유일해서 후보 55쌍을 사람이 한 줄씩 판정할 수 있었다.
# **인물은 아니다** — 이름이 같은 인물 후보가 5,302쌍이고 그 대부분은
# 동명이인이다(2026-09-04 실측: 시작 연대가 둘 다 있는 3,470쌍이 5년 넘게
# 어긋났다. 김지훈이 넷, 강지영이 둘이다).
#
# 그래서 이름 말고 **다른 증거**를 본다. 증거가 말해 주는 것만 기계가
# 판정하고, 나머지는 표로 넘긴다. 표는 언제나 기계를 이긴다.
#
#   다르다  한자가 서로 다르다 · 연대가 5년 넘게 어긋난다
#   같다    이름이 같고 + 생몰년이 똑같다 / 한자가 같다 / 설명 첫 문장이 같다,
#           또는 **띄어쓰기·구두점만 다른 같은 이름**
#   모름    그 밖 — 사람이 표에 적어야 한다
#
# 마지막 것이 값이 크다. 동명이인은 이름이 **통째로** 같지 띄어쓰기가
# 다르지 않다. '경주 김씨'/'경주김씨', '3·1 운동'/'3·1운동' 은 한 이름의
# 두 표기이고, 글자까지 똑같은 '청주 전투' 둘은 1592년과 1950년의 다른
# 싸움이다 — 그래서 **완전히 같은 이름은 모름**으로 남긴다.
#
# **'같다'는 이름이 같을 때만 낸다.** 설명 첫 문장이 같다는 것만으로는
# 인물에서 못 믿는다: `enrich` 가 박종철의 문서를 아버지 박정기에게도,
# 전두환의 것을 전상우에게도 붙여 놓았다 (그건 중복이 아니라 **설명이
# 잘못 붙은 것**이라 따로 고칠 일이다).

# 이 너머로 어긋나면 다른 사람·다른 것이다. 지저분한 날짜를 감안해
# 넉넉히 잡는다 (`promote.plausible_period` 와 같은 취지).
YEAR_SLACK = 5

_HANJA = re.compile(r"^[一-鿿]{2,12}$")


def _hanja_of(conn: sqlite3.Connection, node_type: str) -> tuple[dict[str, str], dict[str, set[str]]]:
    """(정본 한자, 알려진 한자 표기 전부).

    앞의 것은 `props.hanja` 뿐이다 — 국편·민족문화대백과가 항목에 달아 준
    표기라 **한 노드에 하나**고, 다르면 다른 것이라 말할 수 있다.
    뒤의 것은 한자 별칭까지 담는다. 별칭은 여럿이고 남의 것이 섞이기도
    해서(임진왜란 노드에 '丁酉再亂'이 별칭으로 붙어 있다) **같다는 근거로만
    쓰고 다르다는 근거로는 쓰지 않는다.**"""
    canon: dict[str, str] = {}
    known: dict[str, set[str]] = {}
    for r in conn.execute(
        "SELECT id, json_extract(props,'$.hanja') AS hanja FROM nodes"
        " WHERE type = ? AND hanja IS NOT NULL", (node_type,)
    ):
        canon[r["id"]] = r["hanja"]
        known.setdefault(r["id"], set()).add(r["hanja"])
    for r in conn.execute(
        "SELECT a.node_id, a.alias FROM aliases a JOIN nodes n ON n.id = a.node_id"
        " WHERE n.type = ?", (node_type,)
    ):
        if _HANJA.match(r["alias"] or ""):
            known.setdefault(r["node_id"], set()).add(r["alias"])
    return canon, known


# 국가유산청은 **지정 건마다** 관리번호와 소재지를 준다. 이름도 한자도
# 같은 '동의보감'이 셋인데 국립중앙도서관본·규장각본·한국학중앙연구원본
# 이라 서로 다른 보물이다. 반대로 '여수 진남관'은 1963년 보물 324호이던
# 것이 2001년 국보 304호가 되면서 두 줄이 됐다 — 주소가 같다.
_SIDO = re.compile(
    r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청북도|충청남도"
    r"|충북|충남|전라북도|전라남도|전북|전남|경상북도|경상남도|경북|경남|제주)\S*$"
)


def address_key(addr: str | None) -> tuple[str, ...]:
    """소재지의 앞 세 마디 (시도는 뗀다). 없으면 빈 튜플.

    괄호 안(법정동·기관명)은 뺀다 — 같은 건물을 '(군자동)'으로도
    '(지번)전남 여수시 군자동 472'로도 적어 놓기 때문이다."""
    a = re.sub(r"\([^)]*\)", " ", addr or "")
    a = re.sub(r"[,·/]", " ", a)
    # '불국로 132' 와 '불국로 132-0' 은 같은 자리다
    a = re.sub(r"(\d)-0(?=\s|$)", r"\1", a)
    toks = a.split()
    if toks and _SIDO.match(toks[0]):
        toks = toks[1:]
    return tuple(toks[:3])


# 권차·판본 표기. 국가유산은 **권마다 따로 지정된다** — '월인석보 권1~2'
# 와 '권23' 은 보물 745-1 과 745-8 로 서로 다른 지정 건이다. 설명은 책
# 자체를 풀이하므로 권이 달라도 글자까지 같다.
_VOLUME = re.compile(r"권[\s\d,~∼·\-]*|\(\d{4}(?:-\d+)?\)|제?\d+책|[가-힣]+사고본")


def _khs_verdict(a: dict, b: dict) -> tuple[str, str] | None:
    """국가유산청 노드끼리의 판정. 아니면 None (다른 규칙에 맡긴다)."""
    if not (a["id"].startswith("khs:") and b["id"].startswith("khs:")):
        return None
    asno_a, asno_b = a["id"].split("-")[-1], b["id"].split("-")[-1]
    if asno_a == asno_b:
        return "같다", f"국가유산 관리번호가 같다 ({asno_a})"
    # 이름이 다르면 다른 지정 건이다. 한 소스가 같은 유산에 두 이름을
    # 달지는 않는다 — '월인석보 권1~2'와 '권23', '조선왕조실록 정족산
    # 사고본'과 '오대산사고본'은 설명이 글자까지 같아도(설명은 책을
    # 풀이한다) 보물 745-1 과 745-8, 국보 151-1 과 151-3 이다.
    # 띄어쓰기만 다른 것은 여기서 걸러 두 줄이 같은 유산일 길을 남긴다.
    if PUNCT.sub("", a["label"]) != PUNCT.sub("", b["label"]):
        return "다르다", f"이름이 다른 두 지정 건이다 ({a['label']} ↔ {b['label']})"
    ka, kb = address_key(a["address"]), address_key(b["address"])
    if len(ka) == 3 and len(kb) == 3:
        if ka != kb:
            return "다르다", f"소재지가 다르다 ({' '.join(ka)} ↔ {' '.join(kb)})"
        # 소재지까지 같다면 **종목이 바뀐 것**일 때만 같은 유산이다
        # (보물 929 기사계첩이 2019년 국보 325 가 됐다). 같은 종목 안에서
        # 관리번호가 다른 것은 한 박물관이 같은 이름의 유물을 여럿 가진
        # 것이다 — 국보 128 과 보물 927 금동관음보살입상은 소장처가 아예
        # 다르고, 같은 소장처 안에서도 지정 건은 따로 센다.
        if a["id"].split("-")[0] != b["id"].split("-")[0]:
            return "같다", f"소재지가 같고 종목이 다르다 ({' '.join(ka)}) — 지정이 바뀐 것이다"
        return "다르다", f"소재지는 같지만 지정 건이 다르다 ({' '.join(ka)})"
    return None


def _year(date: str | None) -> int | None:
    m = re.match(r"^(-?\d{1,4})", (date or "").strip())
    return int(m.group(1)) if m else None


def _dates_agree(a: dict, b: dict) -> bool:
    """두 노드의 날짜가 서로 어긋나지 않는가.

    한쪽이 비었거나 한쪽이 다른 쪽의 앞자리이면(1592 / 1592-05-23) 맞는
    것으로 본다. **1983 과 1984 는 어긋난 것이다** — 이 한 줄이 '이 재현'
    (1984년생 음악가)과 '이재현'(1983년생 성우)을 갈랐다."""
    for col in ("start_date", "end_date"):
        x, y = (a[col] or "").strip(), (b[col] or "").strip()
        if x and y and not (x.startswith(y) or y.startswith(x)):
            return False
    return True


def _spacing_variant(x: str, y: str) -> bool:
    """두 이름이 한 이름의 두 표기인가 (띄어쓰기·구두점만 다른가).

    **첫 마디가 한 글자면 아니라고 본다.** 사람 이름은 성과 이름 사이를
    띄기도 해서 ('이 명희'/'이명희') 그 공백이 표기 차이가 아니라 관례다 —
    1969년생 배드민턴 선수와 1950년생 한진 회장이 그렇게 한 노드가 될
    뻔했다. 성은 언제나 앞에 오므로 **앞 마디만** 보면 된다: '고려 말',
    '1613년 경', '17세기 초'처럼 뒤에 붙는 한 글자는 표기 차이가 맞다."""
    for name in (x, y):
        head = name.split()
        if head and len(head[0]) < 2:
            return False
    return True


def decide(
    a: dict, b: dict, canon: dict[str, str], known: dict[str, set[str]]
) -> tuple[str, str]:
    """(판정, 근거). 판정은 '같다'·'다르다'·'모름'."""
    khs = _khs_verdict(a, b)
    if khs:
        return khs
    ha, hb = canon.get(a["id"]), canon.get(b["id"])
    if ha and hb and ha != hb:
        return "다르다", f"한자가 다르다 ({ha} ↔ {hb})"

    same_label = PUNCT.sub("", a["label"]) == PUNCT.sub("", b["label"])
    agree = _dates_agree(a, b)

    # 표기만 다른 같은 이름. **연대보다 이것이 세다** — 띄어쓰기가 다른
    # 두 표기가 우연히 만들어지지 않기 때문이다. 국편 연대기가 6·10 만세
    # 운동을 1920년, 여수·순천 사건을 2021년(특별법 제정 연도)으로 적어
    # 둔 탓에, 연대를 먼저 보면 이 둘이 다른 사건이 된다.
    if same_label and a["label"] != b["label"] and _spacing_variant(a["label"], b["label"]):
        return "같다", f"띄어쓰기·구두점만 다르다 ({a['label']} ↔ {b['label']})"

    sa, sb = _year(a["start_date"]), _year(b["start_date"])
    ea, eb = _year(a["end_date"]), _year(b["end_date"])
    if same_label and agree and sa and sb and ea and eb:
        return "같다", f"이름과 생몰년이 같다 ({a['start_date']}~{a['end_date']})"
    for x, y, what in ((sa, sb, "연대"), (ea, eb, "끝 연대")):
        if x and y and abs(x - y) > YEAR_SLACK:
            return "다르다", f"{what}가 {abs(x - y)}년 어긋난다 ({x} ↔ {y})"
    # 여기부터는 날짜가 어긋나면 아무것도 단정하지 않는다. 몇 해 차이는
    # 지저분한 날짜일 수도, 다른 사람일 수도 있다 — 그건 사람이 본다.
    if not agree:
        return "모름", ""
    if same_label:
        shared = known.get(a["id"], set()) & known.get(b["id"], set())
        if shared:
            return "같다", f"이름과 한자가 같다 ({'·'.join(sorted(shared))})"
        la = re.sub(r"\s+", "", lead_sentence(a["description"]))
        lb = re.sub(r"\s+", "", lead_sentence(b["description"]))
        if len(la) >= 40 and la == lb:
            return "같다", "이름이 같고 설명 첫 문장이 글자 그대로 같다"
    return "모름", ""


# --- 적용 -----------------------------------------------------------------


def sweep(
    conn: sqlite3.Connection,
    table: list[Verdict],
    node_type: str = "event",
) -> Report:
    """후보를 찾아 증거로 판정하고, 표와 맞춰 본다. 고치지는 않는다."""
    rep = Report(candidates=find(conn, node_type))
    judged = {v.key for v in table}
    group = _merge_groups(table)
    canon_hanja, known_hanja = _hanja_of(conn, node_type)
    nodes = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, start_date, end_date, description,"
            " json_extract(props,'$.address') AS address FROM nodes"
            " WHERE type = ?", (node_type,))
    }

    for c in rep.candidates:
        if c.key in judged:
            continue
        # 셋이 한 사건인 경우. `가↔나`, `가↔다` 를 적었으면 `나↔다` 도 판정된
        # 것이다 — 같은 것에 같은 것은 같다.
        if group.get(c.a) is not None and group.get(c.a) == group.get(c.b):
            continue
        if c.a not in nodes or c.b not in nodes:
            continue
        verdict, why = decide(nodes[c.a], nodes[c.b], canon_hanja, known_hanja)
        if verdict == "같다":
            rep.auto_same.append((c, why))
        elif verdict == "다르다":
            rep.auto_diff.append((c, why))
        else:
            rep.unjudged.append(c)

    have = {r["id"] for r in conn.execute("SELECT id FROM nodes")}
    for v in table:
        if v.action != "merge":
            continue
        if v.drop not in have:
            rep.stale.append(v)             # 이미 합쳐졌다 (멱등)
        elif v.keep not in have:
            rep.absent.append(v)            # 남길 쪽이 없다 — 손대지 않는다
    return rep


def _merge_groups(table: list[Verdict]) -> dict[str, int]:
    """`merge` 로 이어진 id 를 한 무리로 묶는다."""
    parent: dict[str, str] = {}

    def root(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for v in table:
        if v.action == "merge":
            parent[root(v.keep)] = root(v.drop)
    groups: dict[str, int] = {}
    ids = {i: n for n, i in enumerate(sorted({root(x) for x in parent}))}
    for x in parent:
        groups[x] = ids[root(x)]
    return groups


def apply(store, table: list[Verdict], node_type: str = "event") -> Report:
    """표의 `merge` 줄과 증거가 '같다'고 한 짝을 합친다. 몇 번 돌려도 같다."""
    from .promote import merge_node

    conn = store.conn
    rep = sweep(conn, table, node_type)
    skip = {v.key for v in rep.absent} | {v.key for v in rep.stale}
    pairs: list[tuple[str, str, str]] = [
        (v.keep, v.drop, "duplicate_table")
        for v in table if v.action == "merge" and v.key not in skip
    ]
    pairs += [(c.a, c.b, "duplicate_evidence") for c, _ in rep.auto_same]

    preferred = {v.keep for v in table if v.action == "merge"}
    for keep, drop, method in _resolve_chains(conn, pairs, preferred):
        clash = _carry_content(conn, keep, drop)
        if clash:
            rep.date_clashes.append(clash)
        stats = merge_node(store, drop, keep, method=method)
        rep.merged.append((keep, drop, stats["edges"]))
    conn.commit()
    # 합친 뒤 다시 세어야 '남은 후보'가 맞다.
    after = sweep(conn, table, node_type)
    rep.candidates, rep.unjudged = after.candidates, after.unjudged
    rep.auto_same, rep.auto_diff = after.auto_same, after.auto_diff
    return rep


def _resolve_chains(
    conn: sqlite3.Connection,
    pairs: list[tuple[str, str, str]],
    preferred: set[str] = frozenset(),
) -> list[tuple[str, str, str]]:
    """짝들이 사슬로 이어지면 **한 노드로** 모은다.

    '여수진남관'(보물, 빈 줄) → '여수 진남관'(국보, 빈 줄) → '여수
    진남관'(국보, 알맹이) 처럼 셋이 얽힐 때, 짝을 적힌 순서대로 합치면
    이미 지운 노드에 엣지를 붙이게 된다. 무리마다 남길 노드를 하나
    골라(설명이 있는 쪽 · 엣지가 많은 쪽) 나머지를 전부 거기로 보낸다."""
    parent: dict[str, str] = {}

    def root(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for keep, drop, _ in pairs:
        parent[root(keep)] = root(drop)

    groups: dict[str, list[str]] = {}
    for node in parent:
        groups.setdefault(root(node), []).append(node)

    # 표가 '남겨라'고 적은 노드가 먼저다 — 사람의 판정은 기계의 순서보다
    # 세다. 그 다음이 설명이 있는 쪽, 엣지가 많은 쪽이다.
    info = {
        r["id"]: (0 if r["id"] in preferred else 1,
                  0 if (r["description"] or "").strip() else 1, -r["deg"], r["id"])
        for r in conn.execute(
            "SELECT id, description,"
            " (SELECT COUNT(*) FROM edges e WHERE e.src=n.id OR e.dst=n.id) deg"
            " FROM nodes n")
    }
    method = {frozenset((k, d)): m for k, d, m in pairs}
    out: list[tuple[str, str, str]] = []
    for members in groups.values():
        alive = [m for m in members if m in info]
        if len(alive) < 2:
            continue
        winner = min(alive, key=lambda i: info[i])
        for loser in alive:
            if loser == winner:
                continue
            out.append((winner, loser,
                        method.get(frozenset((winner, loser)), "duplicate_chain")))
    return out


def _carry_content(conn: sqlite3.Connection, keep: str, drop: str) -> str | None:
    """없앨 쪽에만 있는 것을 남길 쪽으로 옮긴다. 연대가 어긋나면 알린다.

    **비어 있는 칸만 채운다** (`upsert_nodes` 와 같은 COALESCE 규칙). 양쪽에
    값이 있으면 손대지 않는다 — 더 자세해 보이는 값이 더 맞는 값은 아니다
    ('언론통폐합'의 1980-05 는 1980 보다 자세하지만 실제는 11월 30일이다).
    지워질 설명은 `props.merged_desc` 에 남긴다.

    돌려주는 것은 **연대 충돌 알림**이다. 어느 쪽이 맞는지는 기계가 모른다."""
    import json

    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, source, start_date, end_date, description, url, props"
            " FROM nodes WHERE id IN (?,?)",
            (keep, drop),
        )
    }
    k, d = rows.get(keep), rows.get(drop)
    if not k or not d:
        return None

    fill = {c: d[c] for c in ("start_date", "end_date", "description", "url")
            if not (k[c] or "").strip() and (d[c] or "").strip()}
    props = json.loads(k["props"] or "{}")
    # 없앨 쪽 props 에만 있는 칸도 가져온다 — 국가유산청 노드는 소재지·
    # 지정 종목이 거기 들어 있어서, 빈 줄을 남기면 그게 통째로 사라진다.
    for key, val in json.loads(d["props"] or "{}").items():
        if key not in ("merged_from", "merged_desc") and not props.get(key):
            props[key] = val
    if (d["description"] or "").strip() and "description" not in fill:
        props.setdefault("merged_desc", d["description"])
    sets = ", ".join(f"{c} = ?" for c in fill)
    conn.execute(
        f"UPDATE nodes SET {sets + ', ' if sets else ''}props = ?,"
        " updated_at = datetime('now') WHERE id = ?",
        (*fill.values(), json.dumps(props, ensure_ascii=False), keep),
    )

    for col in ("start_date", "end_date"):
        a, b = (k[col] or "").strip(), (d[col] or "").strip()
        if a and b and not (a.startswith(b) or b.startswith(a)):
            return f"{k['label']}: {col} {a} ↔ 없앤 쪽 {b}"
    return None
