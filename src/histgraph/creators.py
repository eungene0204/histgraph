"""작품에 만든 사람을 잇는다 (`created`).

2026-09-10 지적: "작품과 작품을 만든 사람의 엣지가 없어. 예를 들면 세한도는
김정희가 만들었는데 둘간의 엣지가 없어."

실측이 그대로였다 — 작품 1,777개(예술작품 19 · 유물 1,584 · 영화·드라마
174)에 `created` 엣지가 **17건**뿐이었고, 그 열일곱도 산문 추출이 덤으로
낸 것이라 절반이 틀렸다 (정약용 → 자산어보. 그 책은 형 정약전이 썼다).
화면에서 김정희를 눌러도 세한도가 없고 세한도를 눌러도 김정희가 없었다.

**왜 수집이 못 주는가.** 국가유산청 API 에는 만든 이 칸이 없다 — 이름은
설명 문장 안에 있다 ("겸재 정선(1676∼1759)이 … 그린 그림으로"). Wikidata
의 P170(제작자)은 우리 유물 노드가 `khs:` 라 닿지 않는다. 그래서 이 물음도
**산문에 물어야** 한다.

## 재는 자리 (`scan`)

작품마다 이름·설명·말뭉치 문단을 붙여 놓고 **인물 이름을 먼저 놓고** 훑는다.
동사부터 찾으면 '그림'·'건물'·'이것'이 사람이 되어 버린다 (실측: 창작 동사로
먼저 훑으니 후보 850건 중 태반이 사람이 아니었다). 인물 노드의 라벨·별칭
6,526 표기를 자리마다 맞춰 보고, 맞은 이름 **뒤 90자 안**에 창작의 틀이
있을 때만 후보로 올린다:

    paren  이름(漢字)·이름(생몰년) 뒤에 창작 동사    최해(崔瀣, 1287∼1340)가 편집한
    subj   이름 + 이/가 + 25자 안에 창작 동사        정선이 인왕산 모습을 그린
    poss   이름의 + 대표작·글씨·문집·저서            김정희의 대표작
    etc    이름 등 + 창작 동사                       윤회·권도 등이 교정하고
    label  이름표가 'X 필'·'X 어필'                  김정희 필 세한도

## 판정은 표가 한다 (`data/creators.tsv`)

    작품 id<TAB>인물 id<TAB>역할<TAB>근거

틀이 맞아도 만든 사람이 아닌 것이 절반이다. 실측으로 갈린 함정 넷:

- **초상화의 주인공은 그린 사람이 아니다.** '이제현 초상'의 이제현, '송시열
  초상'의 송시열은 그려진 쪽이다 (그 관계는 `depicts` 다).
- **간행을 명한 임금은 만든 사람이 아니다.** 조선의 책 설명은 거의 다
  "세종의 명을 받아 …"로 시작한다. 명한 것과 지은 것을 한 엣지로 부르면
  세종이 조선 책 백 권의 저자가 된다.
- **중국·인도 사람이 지은 것을 조선이 찍은 것.** 자치통감은 사마광이 짓고
  조선이 교정해 간행했다. 불경은 구마라집·현장이 옮긴 것이다. 우리 그래프에
  그 사람이 없으면 후보로 오르지도 않지만, 오르면 '없음'이다.
- **같은 이름의 딴 작품.** 영화 《도리화가》(2015)에 붙은 말뭉치 글은 신재효가
  지은 판소리 단가 「도리화가」의 것이다 (CLAUDE.md §1-2 의 그 함정).

역할은 여섯이고 그대로 **엣지의 라벨**이 된다 — 화면이 "정선이 인왕제색도를
그렸다"로 읽는다 (`relations.js` `roleSentence`). 만든 사람이 아니면 `없음`,
이미 서 있는 엣지가 거짓이면 `삭제`다.

고친 값은 편집 계층(`overrides`)에 남아 재수집이 되돌리지 못한다. 원본과
파생본에 한 번씩 돌린다:

    uv run histgraph creators --scan --show 200   # 판정이 없는 후보를 읽는다
    uv run histgraph creators --apply
    uv run histgraph --db data/korea.sqlite creators --apply
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import overrides as ov
from .store import GraphStore

SOURCE_MARK = "creators"
TABLE_ORIGIN = "creators"
EDGE_TYPE = "created"

# 작품으로 보는 타입. `heritage` 에는 석탑·건물도 들어 있지만 그것도 세운
# 사람이 적혀 있으면 만든 사람이다 — 빼는 것은 타입이 아니라 판정이다.
WORK_TYPES = ("artwork", "heritage", "media")

# 역할 -> 뜻. 엣지의 라벨로 그대로 간다.
ROLES: dict[str, str] = {
    "그림": "그린 사람 (회화·초상·지도)",
    "글씨": "쓴 사람 (서예·비문의 서자·사경)",
    "저술": "지은 사람 (책·글·시·소설)",
    "편찬": "여럿의 글을 엮은 사람 (왕명 편찬·선집·번역)",
    "제작": "만든 사람 (공예·조각·주조·건축·영상)",
    "발원": "만들게 한 사람 (시주·발원·명을 내린 이)",
}
# 표에만 있는 판정. 엣지를 세우지 않는다.
NOT_CREATOR = "없음"   # 후보가 만든 사람이 아니다 (초상의 주인공·등장인물·소장자)
DELETE = "삭제"        # 이미 서 있는 `created` 엣지가 거짓이다
TABLE_ROLES = frozenset(ROLES) | {NOT_CREATOR, DELETE}

# --- 후보를 찾는 틀 --------------------------------------------------------

_HANGUL = re.compile(r"[가-힣]")
# 창작을 말하는 말. 어간까지만 적어 활용을 다 받는다.
_MAKE = (
    r"(?:그리|그린|그렸|지은|지었|짓고|쓴|썼|만든|만들|제작|편찬|편집|저술|저작"
    r"|간행|새긴|새겨|엮은|찬술|번역|국역|언해|판각|주조|모아|편저|찬하|글씨|그림|글을)"
)
# **주격 조사는 이름에 붙어 있어야 한다.** 띄어쓰기를 넘겨 받으면 '보아
# 이때쯤 …만들어졌을'의 '보아'가 가수 보아가 되고 '미루어 보아'가 사람이
# 된다 (실측: 그 하나로 후보 12건이 늘었다). 조사 뒤에는 빈칸이 온다 —
# '정선이'는 사람이지만 '정선이라는'은 아니다.
_JOSA = r"(?:이|가)(?=\s)"
# 이름 뒤 괄호가 한자나 생몰년이면 그 이름은 사람을 가리킨다.
_PAREN = r"\(\s*(?:[一-鿿]{2,6}|[^)]{0,12}?\d{3,4}\s*[~∼\-–]\s*\d{0,4})[^)]{0,20}\)"
# 여럿이 만든 것은 이름(한자)를 쉼표·가운뎃점으로 늘어놓고 끝에 '등이'를
# 단다 — '밀기(密機), 채원(彩元), 서징(瑞澄) 등이 …제작하여'. 이 꼬리를
# 넘겨야 명단 한가운데 선 사람이 후보가 된다.
_LIST = r"(?:[,·、\s]*[가-힣]{2,6}" + _PAREN + r")*[,·、\s]*"
_F_PAREN = re.compile(_PAREN + _LIST + r"(?:등\s*)?" + _JOSA + r"\s*[^.。\n]{0,25}?" + _MAKE)
_F_SUBJ = re.compile(r"^(?:" + _PAREN + r")?" + _JOSA + r"\s*[^.。\n]{0,25}?" + _MAKE)
_F_ETC = re.compile(r"^(?:" + _PAREN + r")?" + _LIST + r"등\s*" + _JOSA)
_F_POSS = re.compile(
    r"^(?:" + _PAREN + r")?\s*의\s*(?:대표작|작품|글씨|친필|유작|그림|서화|저서|문집|시문집|저술|글씨체)"
)
# 국가유산 지정명이 만든 이를 앞에 단다 — '김정희 필 세한도'.
_F_LABEL = re.compile(r"^([가-힣]{2,5})\s*(?:필적|어필|필)\b")
# 이름 다음에 이어도 되는 글자. 한글이 이어지면 다른 낱말이다 (김시 ≠ 김시습).
_AFTER_OK = set("이가은는을를의도와과에")
# 말뭉치에서 읽는 문단 수. 만든 이는 정의와 첫머리에 나온다.
_PASSAGES = 8


@dataclass(frozen=True)
class Candidate:
    """작품 하나에 걸린 **이름 하나**. 동명이인은 후보를 늘리지 않는다 —
    같은 이름이 가리킬 수 있는 노드를 `people` 에 다 담고, 어느 쪽인지는
    표가 노드 id 로 답한다 (CLAUDE.md §1-2)."""

    work: str
    work_label: str
    work_type: str
    name: str
    people: tuple[str, ...]
    frame: str        # paren · subj · poss · etc · label
    evidence: str


def _names(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """인물의 라벨·별칭 -> 노드 id 목록. 한글 두 자 이상만 본다."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    for nid, label in conn.execute("SELECT id, label FROM nodes WHERE type = 'person'"):
        out[label].append(nid)
    for nid, alias in conn.execute(
        "SELECT a.node_id, a.alias FROM aliases a JOIN nodes n ON n.id = a.node_id"
        " WHERE n.type = 'person'"
    ):
        out[alias].append(nid)
    return {k: sorted(set(v)) for k, v in out.items()
            if 2 <= len(k) <= 6 and re.fullmatch(r"[가-힣]+", k)}


def _work_text(work, corpus: sqlite3.Connection | None) -> str:
    parts = [work["label"], work["description"] or ""]
    if corpus is not None:
        doc = corpus.execute(
            "SELECT id FROM docs WHERE node_id = ?"
            " ORDER BY CASE source WHEN 'nikh' THEN 0 WHEN 'aks' THEN 1 ELSE 2 END LIMIT 1",
            (work["id"],),
        ).fetchone()
        if doc:
            parts += [r[0] for r in corpus.execute(
                "SELECT text FROM passages WHERE doc_id = ? ORDER BY n LIMIT ?",
                (doc[0], _PASSAGES))]
    return "\n".join(p for p in parts if p)


def _frames(text: str, names: dict[str, list[str]]) -> dict[str, tuple[str, str]]:
    """이름 -> (틀, 근거 구절). 같은 이름이 여러 번 나오면 처음 걸린 틀."""
    hits: dict[str, tuple[str, str]] = {}
    n = len(text)
    i = 0
    while i < n:
        if not _HANGUL.match(text[i]) or (i and _HANGUL.match(text[i - 1])):
            i += 1
            continue
        best = None
        for length in (5, 4, 3, 2):
            word = text[i:i + length]
            if len(word) == length and word in names:
                nxt = text[i + length] if i + length < n else " "
                if not _HANGUL.match(nxt) or nxt in _AFTER_OK:
                    best = (word, length)
                    break
        if not best:
            i += 1
            continue
        word, length = best
        tail = text[i + length:i + length + 140]
        frame = None
        if _F_SUBJ.match(tail):
            frame = "subj"
        elif _F_PAREN.match(tail):
            frame = "paren"
        elif _F_POSS.match(tail):
            frame = "poss"
        elif _F_ETC.match(tail) and re.search(_MAKE, tail[:80]):
            frame = "etc"
        if frame and word not in hits:
            hits[word] = (frame, text[max(0, i - 50):i + length + 90].replace("\n", " ").strip())
        i += length
    return hits


def scan(store: GraphStore, corpus: sqlite3.Connection | None = None) -> list[Candidate]:
    """작품 전수를 훑어 만든 사람 후보를 낸다. 이름이 여러 사람을 가리키면
    **그만큼 후보가 는다** — 가르는 것은 여기가 아니라 표다 (CLAUDE.md §1-2:
    이름만으로는 아무것도 단정하지 않는다)."""
    conn = store.conn
    names = _names(conn)
    works = conn.execute(
        "SELECT id, type, label, description FROM nodes WHERE type IN"
        f" ({','.join('?' * len(WORK_TYPES))}) ORDER BY type, label", WORK_TYPES
    ).fetchall()
    out: list[Candidate] = []
    for work in works:
        text = _work_text(work, corpus)
        hits = _frames(text, names)
        m = _F_LABEL.match(work["label"])
        if m and m.group(1) in names:
            hits.setdefault(m.group(1), ("label", work["label"]))
        for word, (frame, evidence) in sorted(hits.items()):
            out.append(Candidate(work["id"], work["label"], work["type"],
                                 word, tuple(names[word]), frame, evidence))
    return out


def describe(store: GraphStore, candidate: Candidate) -> str:
    """후보 한 줄을 사람이 읽을 수 있게. 이름이 여럿을 가리키면 생몰년을
    같이 찍는다 — 고르는 근거가 이름이 아니라 연대라야 한다."""
    rows = store.conn.execute(
        f"SELECT id, label, start_date, end_date FROM nodes WHERE id IN"
        f" ({','.join('?' * len(candidate.people))})", candidate.people
    ).fetchall()
    who = " / ".join(
        f"{r['id']} {r['label']}({(r['start_date'] or '?')[:4]}~{(r['end_date'] or '')[:4]})"
        for r in rows)
    return (f"{candidate.work}  [{candidate.work_type}] {candidate.work_label}\n"
            f"    {candidate.name} [{candidate.frame}] → {who}\n"
            f"      「{candidate.evidence[:170]}」")


# --- 표 --------------------------------------------------------------------


class CreatorsTableError(ValueError):
    pass


@dataclass(frozen=True)
class TableRow:
    work: str
    person: str
    role: str
    note: str


@dataclass
class TableReport:
    made: int = 0            # 새로 세운 엣지
    relabelled: int = 0      # 이미 있던 엣지의 역할을 고친 것
    deleted: int = 0
    absent: list[TableRow] = field(default_factory=list)   # 이 그래프에 없는 노드
    unjudged: list[Candidate] = field(default_factory=list)


def load_table(path: Path) -> list[TableRow]:
    rows: list[TableRow] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 4 or not all(parts[:4]):
            raise CreatorsTableError(
                f"{path}:{lineno} 작품 id·인물 id·역할·근거 네 칸입니다: {raw!r}")
        work, person, role, note = parts[:4]
        if role not in TABLE_ROLES:
            raise CreatorsTableError(
                f"{path}:{lineno} 역할은 {'/'.join(sorted(TABLE_ROLES))} 중 하나: {role!r}")
        if (work, person) in seen:
            raise CreatorsTableError(f"{path}:{lineno} 같은 쌍이 두 번 적혔습니다: {raw!r}")
        seen.add((work, person))
        rows.append(TableRow(work, person, role, note))
    return rows


def apply_table(store: GraphStore, table: list[TableRow]) -> TableReport:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    c = store.conn
    rep = TableReport()
    has = lambda nid: c.execute("SELECT 1 FROM nodes WHERE id = ?", (nid,)).fetchone() is not None

    for row in table:
        if not (has(row.work) and has(row.person)):
            rep.absent.append(row)
            continue
        key = ov.edge_key(row.person, row.work, EDGE_TYPE)
        existing = c.execute(
            "SELECT rowid, label, props FROM edges WHERE src = ? AND dst = ? AND type = ?",
            (row.person, row.work, EDGE_TYPE),
        ).fetchall()

        if row.role in (NOT_CREATOR, DELETE):
            # **'없음'도 지운다.** 추출이 낸 거짓 엣지(정약용 → 자산어보)와
            # 후보로만 오른 것은 같은 자리에 있다 — 둘 다 만든 사람이 아니다.
            # 지웠다는 사실은 편집 계층에 남아 재수집이 되살리지 못한다.
            ov.record(c, "edge", key, "deleted", True, TABLE_ORIGIN, row.note)
            rep.deleted += c.execute(
                "DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?",
                (row.person, row.work, EDGE_TYPE),
            ).rowcount
            continue

        ov.forget(c, "edge", key, "deleted")
        ov.record(c, "edge", key, "label", row.role, TABLE_ORIGIN, row.note)
        ov.record(c, "edge", key, "props.made", row.role, TABLE_ORIGIN, row.note)
        ov.record(c, "edge", key, "props.made_evidence", row.note, TABLE_ORIGIN, row.note)
        ov.record(c, "edge", key, "props.made_origin", TABLE_ORIGIN, TABLE_ORIGIN, row.note)

        if not existing:
            c.execute(
                """INSERT INTO edges (src, dst, type, source, label, confidence, props)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(src, dst, type, source) DO UPDATE SET
                     label = excluded.label, props = excluded.props""",
                (row.person, row.work, EDGE_TYPE, SOURCE_MARK, row.role, 0.9,
                 json.dumps({"made": row.role, "made_evidence": row.note,
                             "made_origin": TABLE_ORIGIN}, ensure_ascii=False)),
            )
            rep.made += 1
            continue
        for e in existing:
            props = json.loads(e["props"] or "{}")
            props.update({"made": row.role, "made_evidence": row.note,
                          "made_origin": TABLE_ORIGIN})
            c.execute("UPDATE edges SET label = ?, props = ? WHERE rowid = ?",
                      (row.role, json.dumps(props, ensure_ascii=False), e["rowid"]))
        rep.relabelled += 1
    c.commit()
    return rep


def unjudged(store: GraphStore, table: list[TableRow],
             corpus: sqlite3.Connection | None = None) -> list[Candidate]:
    """틀에 걸렸는데 표에 판정이 없는 후보. 남아 있으면 종료 코드 1 이다 —
    수집이 작품을 더 실어 오면 만든 사람을 물어야 한다."""
    judged: dict[str, set[str]] = collections.defaultdict(set)
    for r in table:
        judged[r.work].add(r.person)
    return [c for c in scan(store, corpus)
            if not (judged.get(c.work, set()) & set(c.people))]


def standing(store: GraphStore) -> list[tuple[str, str, str, str]]:
    """지금 서 있는 `created` 엣지 (인물 라벨, 작품 라벨, 역할, 소스)."""
    return [tuple(r) for r in store.conn.execute(
        """SELECT p.label, w.label, COALESCE(e.label, ''), e.source
             FROM edges e JOIN nodes p ON p.id = e.src JOIN nodes w ON w.id = e.dst
            WHERE e.type = ? ORDER BY p.label, w.label""", (EDGE_TYPE,))]
