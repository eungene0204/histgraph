"""인과 — 한 일이 다른 일을 **어떻게** 불렀는지를 말뭉치의 근거로 적고, 그
엣지를 따라 사슬을 읽는다.

이 그래프가 단순 그래프가 아니라 온톨로지인 이유가 여기 있다. 참여·장소·
시대 엣지는 "누가 어디서 언제"를 말하지만 "왜"는 말하지 않는다 — 임진왜란
(1592)과 병자호란(1636)은 연표에서 44년 떨어져 나란히 설 뿐, 앞의 것이
명의 쇠퇴와 후금의 성장을 거쳐 뒤의 것을 불렀다는 사실은 그래프 어디에도
없었다. Wikidata 의 원인(P828)·결과(P1542)는 전체 그래프에 16건뿐이다.

그래서 **산문에 묻는다.** 사건 문서(민족문화대백과·한국사연대기·위키백과)
의 '배경'·'결과'·'의의' 절이 인과를 서술한다. 물음의 모양은 `roles` 와
같다 — 문서 하나를 주고 "여기 서술된 인과 관계"를 받되, 답은 언제나 근거
구절과 함께 온다.

안전장치는 `extract`·`roles` 의 것을 그대로 쓰고 둘을 더한다.

1. 근거 구절이 준 문단에 실제로 있어야 한다 (`extract.evidence_supported`).
   문장 단위로 되살린다 (`complete_evidence`) — 역접 어미에서 끊긴
   인용은 뜻이 뒤집힌다.
2. 양끝이 **이미 있는 노드**로 풀려야 적는다. 여기서 노드를 만들기
   시작하면 '명나라의 쇠퇴'·'민심의 이반' 같은 서술구가 노드가 된다.
   못 푼 이름은 세어서 보고한다 — 그 목록이 다음에 만들 노드의 후보다.
3. **연대가 순방향이어야 한다.** 원인의 해가 결과의 해보다 늦으면 버린다.
   모델은 "A 의 배경에 B 가 있다"를 "A 가 B 의 배경"으로 뒤집어 내기도
   하는데, 스키마는 방향을 강제하지 못하고 연대는 한다.
4. 구조화 소스(Wikidata)가 반대 방향을 이미 알고 있으면 추출본을 버린다.
5. **근거 문장이 그 인과를 말해야 한다** (`fact_check`) — 상징·추정 표현, 양끝
   이름이 없는 근거, 'X의 해소'를 X 로 푼 것, "X 이후"라는 시간 순서뿐인 것은 버린다.

엣지는 언제나 원인 → 결과다. 라벨이 인과의 종류(`KINDS`)고, '어떻게'는
`props.how` 한 구절이 말한다. 화면(`relations.js`)이 이 이름을 그대로 읽는다.

사슬은 `chain`(한 노드의 원인·결과 나무)과 `paths`(두 노드 사이의 최단
인과 경로)로 읽는다. `/api/chain`·`/api/path`·`histgraph chain` 이 이걸 쓴다.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .extract import complete_evidence, normalize_name, pick_candidate
from .koreanize import has_hangul
from .ontology import EDGE_TYPES, Edge
from .store import GraphStore

log = logging.getLogger(__name__)

SOURCE_MARK = "causes"
EDGE_TYPE = "caused"

# 인과의 종류 -> 뜻. 엣지 라벨로 들어가고 화면이 그대로 읽는다.
KINDS: dict[str, str] = {
    "원인": "이것이 없었으면 그 일이 일어나지 않았다 (직접 원인)",
    "배경": "그 일이 일어날 조건을 만들었다 (간접·구조적 배경)",
    "계기": "그 일을 촉발한 발단·구실이 되었다",
    "영향": "그 일의 방향·내용에 영향을 주었다 (원인이라 하기에는 약하다)",
}
CAUSE_TYPES = EDGE_TYPES[EDGE_TYPE][1]
EFFECT_TYPES = EDGE_TYPES[EDGE_TYPE][2]
CONFIDENCE = {"certain": 0.9, "probable": 0.7, "possible": 0.5}

# 문서에서 모델에 줄 분량. 민족문화대백과 사건 항목은 1만 자를 넘기도
# 하는데, 인과는 '배경'·'결과' 절에 몰려 있다. 그 절을 먼저 담고 남는
# 자리에 나머지를 순서대로 채운다.
DOC_CHARS = 7000
CAUSAL_SECTION = re.compile(r"배경|원인|발단|결과|영향|의의|평가")
# 이보다 긴 '어떻게'는 구절이 아니라 문장이다 — 근거를 되풀이한 것이다.
HOW_MAX = 60

SYSTEM_PROMPT = """당신은 한국사 문헌에서 사건 사이의 인과 관계를 추출하는 전문가입니다.

주어진 원문은 한 사건(또는 단체·개념)의 문서입니다. 거기 **서술된** 인과 관계를 찾아 구조화된 형태로 반환하세요.

핵심 규칙:
1. **원문에 명시된 것만 추출합니다.** 배경지식으로 아는 인과라도 원문에 없으면 쓰지 마세요.
2. 원인(cause)과 결과(effect)는 모두 **이름이 있는 사건·단체·국가·인물·개념**이어야 합니다. '후금의 파약 행위'·'도요토미 히데요시의 사망'·'명의 쇠퇴' 같은 서술구는 개체가 아닙니다 — 그 **주어**(후금·도요토미 히데요시·명나라)를 cause/effect 에 쓰고, 무엇을 했는지·어떻게 되었는지는 how 에 적으세요. 주어가 없는 서술('민심의 이반')은 추출하지 마세요.
3. **가능하면 '알려진 개체' 목록의 표기를 그대로 쓰세요.** 표기가 같아야 기존 그래프에 연결됩니다.
4. 방향은 언제나 **원인 → 결과**입니다. "A 의 배경에는 B 가 있었다"는 B 가 원인이고 A 가 결과입니다.
5. how 는 원인이 결과를 **어떻게** 불렀는지를 한 구절(40자 안)로 적습니다. 예: cause=임진왜란, effect=후금, how="명의 국력이 소진되어 누르하치가 여진을 통합할 틈이 생겼다".
6. **근거 구절(evidence)은 원문에서 그대로 인용**합니다. 요약하거나 바꿔 쓰지 마세요. 인과를 말하는 문장 하나면 충분합니다.
7. 인물이 사건에 참여했다는 것은 인과가 아닙니다. 사건이 다른 사건·상태를 불렀을 때만 적으세요.
8. 확신도를 정직하게 매기세요. 원문이 단정하면 certain, 추정 표현("~으로 보인다")이면 probable, 암시에 그치면 possible 입니다.
9. 인과 관계가 없으면 빈 배열을 반환하세요. 억지로 만들지 마세요."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "cause": {"type": "string", "description": "원인이 된 사건·단체·인물·개념의 이름"},
                    "cause_type": {"type": "string", "enum": list(CAUSE_TYPES)},
                    "effect": {"type": "string", "description": "결과로 일어난 사건·단체·개념의 이름"},
                    "effect_type": {"type": "string", "enum": list(EFFECT_TYPES)},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "how": {"type": "string", "description": "원인이 결과를 어떻게 불렀는지 한 구절 (40자 안, 한국어)"},
                    "evidence": {"type": "string", "description": "근거 구절 (원문에서 그대로 인용)"},
                    "confidence": {"type": "string", "enum": ["certain", "probable", "possible"]},
                },
                "required": ["cause", "cause_type", "effect", "effect_type", "kind", "how", "evidence", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["relations"],
    "additionalProperties": False,
}


# 모델의 답을 그대로 둔다. 판정(`accept`)은 노드를 찾아야 하는데, 해소기가
# 좋아지거나 노드가 새로 생기면 **묻지 않고 다시 판정**할 수 있어야 한다 —
# 첫 두 번의 실행(문서 737건, 약 12시간)은 답을 버려서 그러지 못했다.
ANSWERS_DDL = """
CREATE TABLE IF NOT EXISTS causes_answers (
    node_id  TEXT PRIMARY KEY,
    model    TEXT NOT NULL,
    answers  TEXT NOT NULL,
    asked_at TEXT NOT NULL
)"""



# --- 문서 -------------------------------------------------------------------
def documents(
    store: GraphStore,
    corpus,
    types: tuple[str, ...] = ("event",),
    redo: bool = False,
    limit: int | None = None,
    scope: set[str] | None = None,
) -> list[dict]:
    """물을 문서 — 말뭉치에 글이 있는 노드. **연결이 많은 사건부터** 묻는다.

    한 번 물은 문서는 `props.causes_model` 이 남아 다시 묻지 않는다.
    `ingest` 가 props 를 덮으면 표식이 사라지므로 수집 뒤에는 다시 돈다
    (다른 파생 표식과 같은 규약).

    `scope` 는 화면 DB 의 노드 id 집합이다 — 문서당 1분이라 원본 3,000건을
    다 묻기 전에 **화면에 서 있는 것부터** 묻는다 (`paraphrase --scope` 와
    같은 이유).

    `redo` 는 **답이 저장되지 않은** 문서만 다시 묻는다 — 답을 버리던 때
    물은 것이다. 답이 있는 문서는 `reresolve` 가 모델 없이 다시 판정하므로
    묻지 않는다. 그래서 하루짜리 `--redo` 가 중간에 죽어도 같은 명령이
    이어 돈다 (실측: 세션이 끝나며 500건 중 78건을 남기고 죽었다)."""
    from .corpus import has_doc

    store.conn.execute(ANSWERS_DDL)
    answered = {r["node_id"] for r in store.conn.execute("SELECT node_id FROM causes_answers")}

    marks = ",".join("?" * len(types))
    rows = store.conn.execute(
        f"""SELECT n.id, n.label, n.type, n.start_date, n.end_date, n.props,
                   (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS deg
              FROM nodes n
             WHERE n.type IN ({marks})
          ORDER BY deg DESC, n.id""",
        types,
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        props = json.loads(r["props"] or "{}")
        if scope is not None and r["id"] not in scope:
            continue
        if props.get("causes_model") and (not redo or r["id"] in answered):
            continue
        if not has_doc(corpus, r["id"]):
            continue
        out.append(dict(r, props=props))
        if limit and len(out) >= limit:
            break
    return out


def doc_passages(corpus, node_id: str, budget: int = DOC_CHARS) -> list[dict]:
    """모델에 줄 문단. 정본(`SOURCE_PRIORITY`)이 먼저, 그 안에서는 인과를
    말하는 절('배경'·'결과'…)이 먼저다. 예산에 들어온 것만 문서 순서로 돌려준다."""
    from .corpus import _PRIORITY_SQL

    rows = corpus.execute(
        f"""SELECT p.node_id, p.n, p.section, p.text, d.title, d.source, {_PRIORITY_SQL} AS prio
              FROM passages p JOIN docs d ON d.id = p.doc_id
             WHERE p.node_id = ?
          ORDER BY prio, p.n""",
        (node_id,),
    ).fetchall()
    ranked = sorted(rows, key=lambda r: (r["prio"], 0 if CAUSAL_SECTION.search(r["section"] or "") else 1, r["n"]))
    chosen: list = []
    used = 0
    for r in ranked:
        if used + len(r["text"]) > budget and chosen:
            continue
        chosen.append(r)
        used += len(r["text"])
    chosen.sort(key=lambda r: (r["prio"], r["n"]))
    return [dict(r) for r in chosen]


# --- 알려진 개체 -------------------------------------------------------------
GAZ_YEARS = 150   # 이 문서의 사건 앞뒤로 이만큼 안의 사건을 알려준다
GAZ_LIMIT = {"event": 120, "org": 50, "concept": 30, "person": 40}


def gazetteer(store: GraphStore, doc: dict) -> dict[str, list[str]]:
    """이 문서에 줄 '알려진 개체'. **이웃과 그 무렵의 사건**이다.

    전체 그래프의 사건 1,600개를 다 주면 프롬프트가 폭발하고, 차수 상위만
    주면 근현대가 조선 문서를 채운다. 문서의 연대 앞뒤 150년 안의 사건을
    차수 순으로, 거기에 이 노드의 이웃(어느 타입이든)을 더한다."""
    from .timeline import _year_of

    year = _year_of(doc.get("start_date")) or _year_of(doc.get("end_date"))
    gaz: dict[str, list[str]] = {t: [] for t in ("event", "org", "concept", "person")}
    seen: set[str] = set()

    def add(t: str, label: str) -> None:
        if t in gaz and label not in seen and len(label) >= 2 and len(gaz[t]) < GAZ_LIMIT[t]:
            gaz[t].append(label)
            seen.add(label)

    # 이웃이 먼저 — 문서가 말하는 이름은 대개 이미 이어진 것이다
    for r in store.conn.execute(
        """SELECT n.type, n.label,
                  (SELECT COUNT(*) FROM edges x WHERE x.src = n.id OR x.dst = n.id) AS deg
             FROM edges e JOIN nodes n
               ON n.id = CASE WHEN e.src = ?1 THEN e.dst ELSE e.src END
            WHERE (e.src = ?1 OR e.dst = ?1) AND n.type IN ('event','org','concept','person')
         ORDER BY deg DESC""",
        (doc["id"],),
    ):
        add(r["type"], r["label"])
    for t in ("event", "org", "concept"):
        rows = store.conn.execute(
            """SELECT n.label, n.start_date, n.end_date,
                      (SELECT COUNT(*) FROM edges x WHERE x.src = n.id OR x.dst = n.id) AS deg
                 FROM nodes n WHERE n.type = ? AND length(n.label) >= 2
             ORDER BY deg DESC LIMIT 1500""",
            (t,),
        ).fetchall()
        for r in rows:
            if year is not None and t == "event":
                y = _year_of(r["start_date"]) or _year_of(r["end_date"])
                if y is not None and abs(y - year) > GAZ_YEARS:
                    continue
            add(t, r["label"])
    return {t: names for t, names in gaz.items() if names}


def build_prompt(doc: dict, passages: list[dict], gaz: dict[str, list[str]]) -> str:
    kinds = "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    type_name = {"event": "사건", "org": "단체·국가", "concept": "개념", "person": "인물"}
    known = "\n".join(f"- {type_name[t]}: {', '.join(names)}" for t, names in gaz.items())
    body = "\n\n".join(
        f"[{p['section']}]\n{p['text']}" if p.get("section") else p["text"] for p in passages
    )
    return f"""## 인과의 종류 (kind)
{kinds}

## 알려진 개체 (표기를 맞추면 기존 그래프에 연결됩니다)
{known}

## 원문
제목: {doc['label']}

{body}

위 원문에 서술된 인과 관계를 추출하세요. '{doc['label']}'이(가) 원인이거나 결과인 관계를 우선하되, 원문이 명시한 다른 사건 사이의 인과도 적으세요."""


# --- 판정 -------------------------------------------------------------------
CANDIDATES = """
    SELECT n.id, n.type, n.start_date, n.end_date,
           (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS deg
      FROM nodes n
     WHERE (n.label = ?1
            OR EXISTS (SELECT 1 FROM aliases a WHERE a.node_id = n.id AND a.alias = ?1))
           {type_clause}
  ORDER BY deg DESC, n.id
     LIMIT 8"""


# 자국 왕조·국가는 원인도 결과도 되지 않는다. 한국사 서술의 주어는 거의
# 언제나 조선이라, 허용하면 '조선의 저항'·'조선의 여론'이 전부 조선 노드로
# 모여 사슬이 임진왜란 → 조선 → 병자호란처럼 아무 말도 안 하게 된다.
# 외국(명·청·후금·일본)은 다르다 — '임진왜란 → 명나라(의 쇠퇴)'가 바로
# 사용자가 원한 사슬이다.
HOME_POLITIES = frozenset({
    "조선", "고려", "신라", "백제", "고구려", "가야", "발해", "고조선", "통일신라",
    "대한제국", "대한민국", "조선민주주의인민공화국", "북한", "남한", "한국", "대한민국 임시정부",
})
# 서술구를 주어로 줄이는 자리. '후금의 파약 행위' → '후금', '도요토미
# 히데요시 사망' → '도요토미 히데요시'. 왼쪽부터 가장 긴 앞머리를 고른다.
_PAREN = re.compile(r"\([^)]*\)")
_SPLIT = re.compile(r"의\s+|\s+")


# 한 글자로 부르는 나라. '청의 연호 사용 강요'의 주어는 '청'인데 한 글자는
# 아무 데나 우연히 맞아서 이름으로 찾지 않는다 — 여기 적힌 것만 긴 이름으로.
SHORT_NAMES = {
    "청": "청나라", "명": "명나라", "원": "원나라", "송": "송나라", "당": "당나라",
    "수": "수나라", "요": "요나라", "금": "금나라", "왜": "일본", "한": "한나라",
}


def heads(phrase: str) -> list[str]:
    """서술구에서 주어일 수 있는 앞머리들, 긴 것부터. 구 자체는 빼고 준다."""
    base = _PAREN.sub("", phrase).strip()
    parts = _SPLIT.split(base)
    out: list[str] = []
    for i in range(len(parts) - 1, 0, -1):
        head = " ".join(parts[:i]).strip()
        if len(head) == 1:
            head = SHORT_NAMES.get(head, "")
        if len(head) >= 2 and head not in out:
            out.append(head)
    return out


# 표기 차이를 지우는 열쇠. 실측(사건 478 · 단체 259 문서): 모델 답 5,000여 건
# 중 3,237건이 '이름 못 풂'으로 버려졌는데, 그중 적잖은 것이 **있는 노드를
# 다른 표기로** 부른 것이었다 — '대한민국임시정부'(띄어쓰기), '새마을운동',
# '경제개발 5개년 계획', '6·29 선언'/'6.29 선언'(가운뎃점). 띄어쓰기·가운뎃점·
# 마침표·붙임표·괄호 한정어를 지우고 견준다. 한 글자짜리 열쇠는 우연히
# 맞으므로 쓰지 않는다.
_LOOSE_STRIP = re.compile(r"[\s·.\-–—_'\"‘’“”]|\([^)]*\)")
_LOOSE_TYPES = ("event", "org", "concept", "person")
# 접미 일치는 사건·단체·개념에만 — '중앙정보부' → '대한민국 중앙정보부'.
# 인물에 쓰면 '이황'이 '퇴계 이황'·'조선 예종(휘 이황)' 아무 데나 붙는다.
_SUFFIX_TYPES = ("event", "org", "concept")


def loose_key(name: str) -> str:
    return _LOOSE_STRIP.sub("", name)


class LooseIndex:
    """라벨·별칭의 느슨한 열쇠 -> 노드 id. 한 번 만들어 `store` 에 붙여 둔다
    (원본 4만 노드 + 별칭 7천 — 만드는 데 1초가 안 걸린다)."""

    def __init__(self, store: GraphStore) -> None:
        self.by_key: dict[str, set[str]] = defaultdict(set)
        self.suffix: dict[str, list[tuple[str, str]]] = defaultdict(list)  # 타입 -> [(열쇠, id)]
        marks = ",".join("?" * len(_LOOSE_TYPES))
        for r in store.conn.execute(
            f"""SELECT n.id, n.type, n.label AS name FROM nodes n WHERE n.type IN ({marks})
                UNION ALL
                SELECT n.id, n.type, a.alias AS name FROM aliases a JOIN nodes n ON n.id = a.node_id
                 WHERE n.type IN ({marks})""",
            (*_LOOSE_TYPES, *_LOOSE_TYPES),
        ):
            key = loose_key(r["name"] or "")
            if len(key) < 2:
                continue
            self.by_key[key].add(r["id"])
            if r["type"] in _SUFFIX_TYPES:
                self.suffix[r["type"]].append((key, r["id"]))

    def lookup(self, name: str, node_type: str) -> list[str]:
        """느슨한 열쇠가 같은 노드들. 없으면 **그 타입의 라벨이 이 이름으로
        끝나거나 시작하는** 노드들 — '중앙정보부' → '대한민국 중앙정보부',
        '4군 6진' → '4군 6진 개척'. 단, 이름이 세 글자 넘고 후보가 셋 이하일
        때만 ('운동'으로 끝나는 라벨은 수백이고 '고려'로 시작하는 라벨도 그렇다)."""
        key = loose_key(name)
        if len(key) < 2:
            return []
        ids = self.by_key.get(key)
        if ids:
            return sorted(ids)
        if len(key) < 4 or node_type not in _SUFFIX_TYPES:
            return []
        for match in (lambda k: k.endswith(key), lambda k: k.startswith(key)):
            found = sorted({nid for k, nid in self.suffix[node_type] if len(k) > len(key) and match(k)})
            if found:
                return found if len(found) <= 3 else []
        return []


def loose_index(store: GraphStore) -> LooseIndex:
    """색인은 노드·별칭 수가 그대로인 동안만 쓴다 — 노드가 늘면 다시 만든다."""
    stamp = tuple(store.conn.execute("SELECT (SELECT COUNT(*) FROM nodes), (SELECT COUNT(*) FROM aliases)").fetchone())
    cached = getattr(store, "_causes_loose", None)
    if cached is None or cached[0] != stamp:
        cached = store._causes_loose = (stamp, LooseIndex(store))  # type: ignore[attr-defined]
    return cached[1]


def _rows(store: GraphStore, ids: list[str], node_type: str | None) -> list:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    clause = "AND n.type = ?" if node_type else ""
    return store.conn.execute(
        f"""SELECT n.id, n.type, n.start_date, n.end_date,
                   (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS deg
              FROM nodes n WHERE n.id IN ({marks}) {clause}
          ORDER BY deg DESC, n.id""",
        (*ids, *((node_type,) if node_type else ())),
    ).fetchall()


def resolve(store: GraphStore, name: str, node_type: str, doc: dict) -> tuple[str, str, str] | None:
    """이름 -> (노드 id, 타입, 실제로 맞춘 표기). 없으면 None — 노드를 만들지 않는다.

    타입이 맞는 후보를 먼저, 없으면 타입을 무시하고 한 번 더 (모델이
    타입을 잘못 붙였을 수 있다). 동명이인은 `extract.pick_candidate` 가
    문서의 연대와 주인공으로 가른다. 이름 그대로 못 찾으면 서술구로 보고
    주어(`heads`)로 다시 찾는다 — 실측: 첫 3건에서 못 푼 이름 18개가
    전부 '후금의 파약 행위' 꼴이었다.

    그래도 없으면 **표기 차이**로 보고 느슨한 열쇠(`LooseIndex`)로 한 번
    더 — 정확한 표기가 먼저고 느슨한 것은 그 뒤다. 자국 왕조는 어느
    길로도 풀지 않는다."""
    from .promote import life_span

    name = normalize_name(name)
    if len(name) < 2:
        return None
    doc_span = life_span(doc.get("start_date"), doc.get("end_date"))
    candidates = [name, *heads(name)]
    for candidate in candidates:
        if candidate in HOME_POLITIES:
            return None
        for clause, args in (("AND n.type = ?2", (candidate, node_type)), ("", (candidate,))):
            row = pick_candidate(
                store.conn.execute(CANDIDATES.format(type_clause=clause), args).fetchall(),
                doc_span, doc["id"],
            )
            if row:
                return row["id"], row["type"], candidate
    idx = loose_index(store)
    home = {loose_key(h) for h in HOME_POLITIES}
    for candidate in candidates:
        if loose_key(candidate) in home:
            return None
        ids = idx.lookup(candidate, node_type)
        for typed in (node_type, None):
            row = pick_candidate(_rows(store, ids, typed), doc_span, doc["id"])
            if row:
                return row["id"], row["type"], candidate
    return None


def _years(store: GraphStore, node_id: str) -> tuple[int | None, int | None]:
    from .timeline import _year_of

    row = store.conn.execute("SELECT start_date, end_date FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None, None
    return _year_of(row["start_date"]), _year_of(row["end_date"])


def backwards(store: GraphStore, cause: str, effect: str, effect_type: str) -> bool:
    """원인이 결과보다 늦은가. 사건이 결과면 그 **시작** 전에 원인이 있어야
    하고, 나라·단체·개념이 결과면 그것이 **끝나기** 전이면 된다 — '임진왜란
    → 명나라(의 쇠퇴)'에서 명의 건국(1368)은 임진왜란보다 앞서지만 인과는
    참이다. 어느 쪽이든 연대를 모르면 막지 않는다."""
    c_start, c_end = _years(store, cause)
    e_start, e_end = _years(store, effect)
    cause_year = c_start if c_start is not None else c_end
    if effect_type == "event":
        effect_year = e_start if e_start is not None else e_end
    elif e_end is None:
        # 아직 존속하는(또는 끝을 모르는) 나라·단체·개념은 언제든 영향을
        # 받을 수 있다 — 시작 연도로 재면 '5·16 → 재향군인회(1952~) 해산'
        # 같은 참인 인과가 역행으로 버려진다.
        return False
    else:
        effect_year = e_end
    if cause_year is None or effect_year is None:
        return False
    return cause_year > effect_year + 1


def part_of_each_other(store: GraphStore, a: str, b: str) -> bool:
    """둘 사이에 상하위(`part_of`) 엣지가 있는가 — 어느 방향이든.

    실측: 사건 문서 478건에서 `북관대첩 → 임진왜란 (원인)`·`한산도 전투 →
    임진왜란 (영향)` 처럼 전투가 자기가 속한 전쟁의 원인으로 18건 적혔다.
    같은 해라 연대로는 못 잡는다. 반대 방향(`임진왜란 → 용인 전투 (배경)`)은
    틀리진 않지만 상하위가 이미 말하는 것이다 — 둘 다 적지 않는다."""
    return store.conn.execute(
        """SELECT 1 FROM edges WHERE type = 'part_of'
            AND ((src = ?1 AND dst = ?2) OR (src = ?2 AND dst = ?1)) LIMIT 1""",
        (a, b),
    ).fetchone() is not None


def prune_part_of(store: GraphStore) -> int:
    """이미 적힌 인과 엣지 중 상하위 관계와 겹치는 것을 지운다 (되돌아가며 고칠 때)."""
    cur = store.conn.execute(
        """DELETE FROM edges WHERE type = ? AND EXISTS (
             SELECT 1 FROM edges p WHERE p.type = 'part_of'
                AND ((p.src = edges.src AND p.dst = edges.dst) OR (p.src = edges.dst AND p.dst = edges.src)))""",
        (EDGE_TYPE,),
    )
    store.conn.commit()
    return cur.rowcount


def reversed_by_source(store: GraphStore, cause: str, effect: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND type = ? AND source = 'wd' LIMIT 1",
        (effect, cause, EDGE_TYPE),
    ).fetchone() is not None


# --- 팩트체크 관문 ------------------------------------------------------------
# 2026-09-06 지적: "서울올림픽이 냉전체제에 영향을 줬다는 거 사실이 아니야.
# 이런 논리비약을 피하면서 인과 사슬을 만들어야 해." 모델이 '냉전체제의 해소'를
# 결과로 냈고 해소기가 그것을 냉전체제로 풀었으며, 근거는 "서울올림픽 **이후**
# 소련이 해체되고 … 냉전체제는 해소되었다" — 시간 순서를 인과로 읽은 것이다.
# 네 가지를 근거 문장에서 직접 잰다. 배경지식으로 판정하지 않는다.
END_OF = re.compile(
    r"(?:의\s*)?(해소|해체|붕괴|종식|몰락|소멸|폐지|쇠퇴|약화|실패|패배|중단|퇴색|철폐|해산|멸망|종결|와해"
    r"|축소|폐쇄|퇴진|실각|패망|패전|좌절|무산|파탄|상실|단절|종료|폐기)$")
STRONG = re.compile(
    r"때문|인해|인하여|인한|계기|초래|야기|촉발|기인|비롯|말미암|으로써|로써|따라|따른|영향|불러|이끌"
    r"|낳[아았]|가져[오왔]|등으로|의해|의하여|결과|이에 |함께")
HEDGE = re.compile(r"상징적|상징으로|설도 있|일각에서|풍문|소문|추정된다|것으로 보인다|것으로 여겨|평가되기도|불리기도|일컫기도")
WINDOW = 250      # 근거 문장 앞뒤로 이만큼 안에서 이름을 찾는다 — "이러한 상황에서 …"는 앞 문장을 가리킨다
TEMPORAL_CAP = 0.5
TEMPORAL = re.compile(r"이후|뒤|후에|이래|다음")


def _names(store: GraphStore, node_id: str, matched: str, phrase: str) -> set[str]:
    names = {matched, phrase, *heads(phrase)}
    row = store.conn.execute("SELECT label FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row:
        names.add(row["label"])
    names.update(r["alias"] for r in store.conn.execute("SELECT alias FROM aliases WHERE node_id = ?", (node_id,)))
    return {loose_key(n) for n in names if n and len(loose_key(n)) >= 2}


# 근거 쪽 열쇠는 괄호 안을 남긴다 — "쿠데타를 일으켰다(위화도 회군)"의 이름은 괄호 안에 있다.
_TEXT_STRIP = re.compile(r"[\s·‧•・․.\-–—_'\"‘’“”()]")
HEDGE_CAP = 0.5


def loose_text(text: str) -> str:
    return _TEXT_STRIP.sub("", text)


def _found(names: set[str], key: str) -> bool:
    # 표기 차이를 봐준다 — 마지막 글자('계유정난'/'계유정란'), 앞 두 글자('흥선대원군'/'대원군').
    for n in names:
        if n in key or (len(n) >= 4 and n[:-1] in key) or (len(n) >= 5 and n[2:] in key):
            return True
    return False


def evidence_window(evidence: str, text: str) -> str:
    i = text.find(evidence)
    if i < 0:
        return evidence
    return text[max(0, i - WINDOW): i + len(evidence) + WINDOW]


def fact_check(
    store: GraphStore, doc: dict, kind: str, evidence: str,
    cause: tuple[str, str, str], effect: tuple[str, str, str], context: str | None = None,
) -> tuple[str | None, str, float | None]:
    """근거 문장이 그 인과를 **말하는지** 잰다. (버릴 이유 또는 None, 종류, 확신도 상한).

    - 상징·추정 표현("냉전 해체의 상징적 사건으로 평가되기도 한다")은 확신도를 낮춘다.
    - 근거 앞뒤(`context`, 없으면 근거만)에 양끝 이름이 있어야 한다 — 문서의 주인공은
      주어가 생략되므로 예외. 둘 다 없으면 버리고, 한쪽만 없으면 확신도를 낮춘다
      (별칭·서술로 가리킨 것일 수 있다). 한 문장이 아니라 앞뒤 `WINDOW` 자를 보는 것은
      "이러한 상황에서 … 의병이 일어났다"가 앞 문장의 원인을 가리키기 때문이다.
    - 결과가 'X의 해소·붕괴·폐지…' 꼴이면 그것은 X 가 아니라 X 의 끝이다 — 종류를
      '영향'으로 바꾸고, 근거에 인과 표현(때문·계기·초래…)이 없으면 버린다.
      (서울올림픽 → '냉전체제의 해소'가 냉전체제로 풀려 "서울올림픽이 냉전체제에
      영향을 줬다"가 됐던 것.)
    - '원인'·'영향'인데 근거가 원인을 "X 이후/뒤"로만 두면 시간 순서지 인과가 아니다 —
      버리지는 않고 '배경'으로 낮추고 확신도를 `TEMPORAL_CAP` 으로 막는다
      (삼포왜란 뒤 삼포를 폐쇄한 것은 참인 인과이므로)."""
    cid, cname, cphrase = cause
    eid, ename, ephrase = effect
    cap: float | None = HEDGE_CAP if HEDGE.search(evidence) else None
    key = loose_text(evidence)
    wide = loose_text(context) if context else key
    c_names = _names(store, cid, cname, cphrase)
    c_ok = cid == doc["id"] or _found(c_names, wide)
    e_ok = eid == doc["id"] or _found(_names(store, eid, ename, ephrase), wide)
    if not c_ok and not e_ok:
        return "근거에 양끝 이름 없음", kind, None
    if not (c_ok and e_ok):
        # 한쪽은 별칭·서술로 가리켰을 수 있다('흥선대원군의 천주교 탄압' = 병인박해) — 지우지 않고 확신도만 낮춘다.
        cap = HEDGE_CAP
    if ephrase != ename and END_OF.search(ephrase):
        if not STRONG.search(evidence):
            return "끝난 것을 결과로 (인과 표현 없음)", kind, None
        kind = "영향"
    if kind in ("원인", "영향") and not STRONG.search(evidence):
        for n in c_names:
            if re.search(re.escape(n) + r".{0,6}?(?:" + TEMPORAL.pattern + ")", key):
                kind, cap = "배경", TEMPORAL_CAP
                break
    return None, kind, cap


def accept(
    store: GraphStore, doc: dict, answers: list[dict], passages: list[dict], model: str,
) -> tuple[list[Edge], dict[str, int], list[str]]:
    """모델 답 -> 엣지. 버린 이유를 세고, 못 푼 이름을 모은다.

    순수하지는 않다(노드를 찾아야 하므로 store 를 본다) 그러나 백엔드 없이
    시험한다 — 답을 손으로 넣어서."""
    text = "\n\n".join(p["text"] for p in passages)
    counts: dict[str, int] = {}
    unresolved: list[str] = []
    edges: dict[tuple[str, str], Edge] = {}

    def drop(why: str) -> None:
        counts[why] = counts.get(why, 0) + 1

    for a in answers:
        kind = str(a.get("kind", "")).strip()
        if kind not in KINDS:
            drop("종류 밖")
            continue
        evidence = complete_evidence(str(a.get("evidence", "")), text)
        if not evidence:
            drop("근거 없음")
            continue
        cause = resolve(store, str(a.get("cause", "")), str(a.get("cause_type", "event")), doc)
        effect = resolve(store, str(a.get("effect", "")), str(a.get("effect_type", "event")), doc)
        if cause is None or effect is None:
            for got, name in ((cause, a.get("cause")), (effect, a.get("effect"))):
                if got is None and name:
                    unresolved.append(normalize_name(str(name)))
            drop("이름 못 풂")
            continue
        (cid, ctype, cname), (eid, etype, ename) = cause, effect
        if cid == eid:
            drop("자기 자신")
            continue
        if ctype not in CAUSE_TYPES or etype not in EFFECT_TYPES:
            drop("타입 안 맞음")
            continue
        if backwards(store, cid, eid, etype):
            drop("연대 역행")
            continue
        if reversed_by_source(store, cid, eid):
            drop("구조화 소스와 반대")
            continue
        if part_of_each_other(store, cid, eid):
            drop("상하위 관계")
            continue
        why_fc, kind, cap = fact_check(
            store, doc, kind, evidence,
            (cid, cname, normalize_name(str(a.get("cause", "")))),
            (eid, ename, normalize_name(str(a.get("effect", "")))),
            evidence_window(evidence, text),
        )
        if why_fc:
            drop(why_fc)
            continue
        how = " ".join(str(a.get("how", "")).split())
        if not has_hangul(how) or len(how) > HOW_MAX:
            how = ""
        # 서술구를 주어로 줄였으면 원래 구를 남긴다 — 화면이 '후금'이 아니라
        # '후금의 파약 행위'가 원인이라고 말할 수 있어야 한다.
        props: dict[str, Any] = {"how": how, "evidence": evidence, "doc": doc["id"], "model": model}
        for key, phrase, matched in (("cause_as", normalize_name(str(a.get("cause", ""))), cname),
                                     ("effect_as", normalize_name(str(a.get("effect", ""))), ename)):
            if phrase != matched and has_hangul(phrase):
                props[key] = phrase
        conf = CONFIDENCE.get(str(a.get("confidence")), 0.5)
        if cap is not None:
            conf = min(conf, cap)
        prev = edges.get((cid, eid))
        if prev is not None and prev.confidence >= conf:
            continue
        edges[(cid, eid)] = Edge(
            src=cid, dst=eid, type=EDGE_TYPE, source=SOURCE_MARK, label=kind, confidence=conf, props=props,
        )
    return list(edges.values()), counts, unresolved


def write(store: GraphStore, edges: list[Edge]) -> int:
    """엣지를 적는다. 같은 짝을 다른 문서가 더 확실하게 말했으면 그쪽을 남긴다."""
    kept: list[Edge] = []
    for e in edges:
        row = store.conn.execute(
            "SELECT confidence FROM edges WHERE src = ? AND dst = ? AND type = ? AND source = ?",
            (e.src, e.dst, e.type, e.source),
        ).fetchone()
        if row is not None and row["confidence"] > e.confidence:
            continue
        kept.append(e)
    if kept:
        store.upsert_edges(kept)
    return len(kept)


def mark(store: GraphStore, doc: dict, model: str) -> None:
    props = dict(doc.get("props") or {})
    props["causes_model"] = model
    store.conn.execute("UPDATE nodes SET props = ? WHERE id = ?",
                       (json.dumps(props, ensure_ascii=False), doc["id"]))


def keep_answers(store: GraphStore, doc: dict, answers: list[dict], model: str) -> None:
    store.conn.execute(ANSWERS_DDL)
    store.conn.execute(
        "INSERT OR REPLACE INTO causes_answers (node_id, model, answers, asked_at) VALUES (?, ?, ?, ?)",
        (doc["id"], model, json.dumps(answers, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )


def ingest_answers(store: GraphStore, corpus, items: list[dict], model: str) -> dict[str, Any]:
    """사람(또는 Claude)이 문서를 읽고 적은 답을 모델 답과 **같은 관문**으로
    넣는다 — 근거가 원문에 있어야 하고, 양끝은 있는 노드로 풀려야 하고,
    연대는 순방향이어야 하고, 상하위와 겹치지 않아야 한다.

    `items` 는 `{"doc": 노드 id, "relations": [OUTPUT_SCHEMA 의 항목…]}` 의
    목록. 답은 `causes_answers` 에 남고 문서에는 `causes_model` 표식이 붙는다
    (2026-09-05 사용자: "우리 llm 을 쓰지 말고 네가 직접 해석해서 만들어줘")."""
    counts: dict[str, int] = {"문서": 0, "엣지": 0}
    dropped: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    samples: list[str] = []
    for item in items:
        row = store.conn.execute(
            "SELECT id, label, type, start_date, end_date, props FROM nodes WHERE id = ?", (item["doc"],)
        ).fetchone()
        if row is None:
            dropped["문서 없음"] = dropped.get("문서 없음", 0) + 1
            continue
        doc = dict(row, props=json.loads(row["props"] or "{}"))
        # 사람은 문서 전체를 읽는다 — 모델에게 주는 예산(DOC_CHARS)으로 자르면
        # 뒤쪽 절에서 인용한 근거가 '없음'으로 버려진다 (실측: 인조반정 문서).
        passages = doc_passages(corpus, doc["id"], budget=10**8)
        if not passages:
            dropped["글 없음"] = dropped.get("글 없음", 0) + 1
            continue
        answers = list(item.get("relations") or [])
        edges, why, missing = accept(store, doc, answers, passages, model)
        n = write(store, edges)
        mark(store, doc, model)
        keep_answers(store, doc, answers, model)
        store.conn.commit()
        counts["문서"] += 1
        counts["엣지"] += n
        for k, v in why.items():
            dropped[k] = dropped.get(k, 0) + v
        for name in missing:
            unresolved[name] = unresolved.get(name, 0) + 1
        if why or missing:
            samples.append(f"{doc['label']}: 답 {len(answers)} · 엣지 {n} · 버림 {why}"
                           + (f" · 못 푼 이름 {missing}" if missing else ""))
    return {"counts": counts, "dropped": dropped, "unresolved": unresolved, "samples": samples}


def reresolve(store: GraphStore, corpus, scope: set[str] | None = None) -> dict[str, Any]:
    """저장된 답을 모델 없이 다시 판정한다. 이미 있는 엣지는 더 확실한 것만
    바뀌고(`write`), 새로 풀린 이름이 엣지를 더한다."""
    store.conn.execute(ANSWERS_DDL)
    rows = store.conn.execute(
        """SELECT a.node_id, a.model, a.answers, n.label, n.type, n.start_date, n.end_date, n.props
             FROM causes_answers a JOIN nodes n ON n.id = a.node_id"""
    ).fetchall()
    counts: dict[str, int] = {"문서": 0, "엣지": 0}
    dropped: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    samples: list[str] = []
    for r in rows:
        if scope is not None and r["node_id"] not in scope:
            continue
        doc = {"id": r["node_id"], "label": r["label"], "type": r["type"],
               "start_date": r["start_date"], "end_date": r["end_date"],
               "props": json.loads(r["props"] or "{}")}
        passages = doc_passages(corpus, doc["id"])
        if not passages:
            continue
        counts["문서"] += 1
        edges, why, missing = accept(store, doc, json.loads(r["answers"]), passages, r["model"])
        counts["엣지"] += write(store, edges)
        store.conn.commit()
        for k, v in why.items():
            dropped[k] = dropped.get(k, 0) + v
        for name in missing:
            unresolved[name] = unresolved.get(name, 0) + 1
    return {"counts": counts, "dropped": dropped, "unresolved": unresolved, "samples": samples}


def run(
    store: GraphStore,
    corpus,
    backend,
    types: tuple[str, ...] = ("event",),
    limit: int | None = None,
    dry_run: bool = False,
    redo: bool = False,
    scope: set[str] | None = None,
    sync_target: GraphStore | None = None,
    sync_every: int = 10,
) -> dict[str, Any]:
    """문서를 돌며 인과를 뽑는다. `backend` 가 None 이거나 dry_run 이면
    묻지 않고 물을 문서와 분량만 센다. `sync_target` 을 주면 문서 몇 건마다
    화면 DB 로 옮긴다 — 하루짜리 실행을 끝까지 기다리지 않아도 화면이 는다."""
    todo = documents(store, corpus, types=types, redo=redo, limit=limit, scope=scope)
    counts: dict[str, int] = {"문서": len(todo), "엣지": 0}
    dropped: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    samples: list[str] = []
    model = getattr(backend, "model", "?") if backend is not None else "?"
    for doc in todo:
        passages = doc_passages(corpus, doc["id"])
        if not passages:
            continue
        if dry_run or backend is None:
            if len(samples) < 8:
                samples.append(f"{doc['label']}: 문단 {len(passages)} · {sum(len(p['text']) for p in passages):,}자")
            continue
        try:
            answers = backend.complete(SYSTEM_PROMPT, build_prompt(doc, passages, gazetteer(store, doc)), OUTPUT_SCHEMA)
        except RuntimeError as err:
            log.warning("추출 실패 [%s]: %s", doc["label"], err)
            continue
        edges, why, missing = accept(store, doc, answers, passages, model)
        n = write(store, edges)
        mark(store, doc, model)
        keep_answers(store, doc, answers, model)
        # 문서마다 커밋한다 — 끝에서 한 번 하면 다른 세션이 잠금에 죽는다
        store.conn.commit()
        counts["엣지"] += n
        counts["물음"] = counts.get("물음", 0) + 1
        if sync_target is not None and counts["물음"] % sync_every == 0:
            log.info("화면 DB 로 옮김: 인과 엣지 %d건", sync(store, sync_target))
        for k, v in why.items():
            dropped[k] = dropped.get(k, 0) + v
        for name in missing:
            unresolved[name] = unresolved.get(name, 0) + 1
        labels = dict(store.conn.execute(
            f"SELECT id, label FROM nodes WHERE id IN ({','.join('?' * (2 * len(edges)))})",
            [x for e in edges for x in (e.src, e.dst)]).fetchall()) if edges else {}
        for e in edges[:3]:
            if len(samples) < 24:
                samples.append(f"{labels.get(e.src)} →[{e.label}] {labels.get(e.dst)}"
                               + (f"  ({e.props['how']})" if e.props.get("how") else ""))
        log.info("%s: 답 %d · 엣지 %d · 버림 %s", doc["label"], len(answers), n, why or "-")
    return {"counts": counts, "dropped": dropped, "unresolved": unresolved, "samples": samples}


# --- Wikidata 원인·결과를 인과 엣지로 --------------------------------------
def migrate(store: GraphStore) -> int:
    """`related_to '원인'` 으로 들어와 있던 Wikidata P828/P1542 를 `caused` 로.
    한 번 옮기면 다시 할 것이 없다 — `links` 는 이제 `caused` 로 적는다."""
    cur = store.conn.execute(
        """UPDATE OR REPLACE edges SET type = ?
            WHERE type = 'related_to' AND label = '원인' AND source = 'wd'""",
        (EDGE_TYPE,),
    )
    store.conn.commit()
    return cur.rowcount


def sync(store: GraphStore, target: GraphStore) -> int:
    """인과 엣지를 파생본(화면 DB)으로 옮긴다 — 양끝이 거기 있는 것만.

    `scope` 를 다시 돌리면 같은 결과가 나오지만, 그러려면 enrich·describe
    부터 다시 밟아야 한다. 인과 엣지만 새로 생겼을 때는 이것으로 족하다."""
    migrate(target)
    prune_part_of(store)
    prune_part_of(target)
    rows = store.conn.execute("SELECT * FROM edges WHERE type = ?", (EDGE_TYPE,)).fetchall()
    have = {r["id"] for r in target.conn.execute("SELECT id FROM nodes")}
    edges = [
        Edge(src=r["src"], dst=r["dst"], type=r["type"], source=r["source"], label=r["label"],
             start_date=r["start_date"], end_date=r["end_date"], confidence=r["confidence"],
             props=json.loads(r["props"] or "{}"))
        for r in rows if r["src"] in have and r["dst"] in have
    ]
    if edges:
        target.upsert_edges(edges)
    return len(edges)


# --- 사슬 읽기 ---------------------------------------------------------------
FANOUT = 6      # 한 노드에서 따라갈 원인·결과 수 (확신도 순)
TREE_BUDGET = 60


def _brief(store: GraphStore, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        r["id"]: {"id": r["id"], "label": r["label"], "type": r["type"],
                  "start": r["start_date"], "end": r["end_date"]}
        for r in store.conn.execute(
            f"SELECT id, label, type, start_date, end_date FROM nodes WHERE id IN ({marks})", list(ids))
    }


def _links(store: GraphStore, node_id: str, direction: str) -> list[dict]:
    """한 노드의 인과 엣지, 소스가 여럿이면 한 줄로. `out` 은 결과, `in` 은 원인."""
    col, other = ("src", "dst") if direction == "out" else ("dst", "src")
    merged: dict[str, dict] = {}
    for r in store.conn.execute(
        f"SELECT * FROM edges WHERE type = ? AND {col} = ? ORDER BY confidence DESC", (EDGE_TYPE, node_id)
    ):
        props = json.loads(r["props"] or "{}")
        row = merged.get(r[other])
        # 상대 쪽의 서술구. 결과 쪽으로 갈 때는 effect_as, 원인 쪽은 cause_as.
        phrase = props.get("effect_as" if direction == "out" else "cause_as") or ""
        if row is None:
            row = merged[r[other]] = {
                "id": r[other], "kind": r["label"] or "원인", "how": props.get("how") or "",
                "as": phrase, "evidence": [], "confidence": r["confidence"], "sources": [],
            }
        row["confidence"] = max(row["confidence"], r["confidence"])
        if not row["how"] and props.get("how"):
            row["how"] = props["how"]
        if not row["as"] and phrase:
            row["as"] = phrase
        if props.get("evidence") and props["evidence"] not in row["evidence"]:
            row["evidence"].append(props["evidence"])
        if r["source"] not in row["sources"]:
            row["sources"].append(r["source"])
    return sorted(merged.values(), key=lambda x: (-len(x["sources"]), -x["confidence"], x["id"]))


def _tree(store: GraphStore, root: str, direction: str, depth: int, budget: list[int]) -> list[dict]:
    """원인(`in`) 또는 결과(`out`) 쪽으로 내려가는 나무. 한 경로에 같은
    노드가 두 번 나오지 않게 하고, 전체 노드 수를 예산으로 막는다."""
    out: list[dict] = []
    stack = [(root, 0, out, {root})]
    while stack:
        node, d, into, path = stack.pop()
        if d >= depth:
            continue
        for link in _links(store, node, direction)[:FANOUT]:
            if link["id"] in path or budget[0] <= 0:
                continue
            budget[0] -= 1
            item = dict(link, children=[])
            into.append(item)
            stack.append((link["id"], d + 1, item["children"], path | {link["id"]}))
    return out


def chain(store: GraphStore, node_id: str, depth: int = 4) -> dict | None:
    """한 노드의 원인 나무와 결과 나무. 노드 요약은 `nodes` 에 한 번씩."""
    if store.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone() is None:
        return None
    # 예산은 두 쪽이 나눠 쓴다. 한 예산을 원인이 먼저 쓰면 원인이 많은
    # 사건(심하전투 31건)의 결과가 빈손이 된다 — 연표에는 정묘호란·인조반정이
    # 결과로 서 있는데 사슬은 '결과 0'이었다 (2026-09-06). 적은 쪽이 남긴
    # 예산은 많은 쪽이 이어 쓴다.
    half = TREE_BUDGET // 2
    left = [half]
    effects = _tree(store, node_id, "out", depth, left)
    rest = [half + left[0]]                    # 제 몫 + 결과가 남긴 것
    causes = _tree(store, node_id, "in", depth, rest)
    if rest[0] > 0 and left[0] == 0:           # 결과가 모자랐고 원인이 남겼다
        effects = _tree(store, node_id, "out", depth, [half + rest[0]])
    ids: set[str] = {node_id}

    def walk(items: list[dict]) -> None:
        for it in items:
            ids.add(it["id"])
            walk(it["children"])

    walk(causes)
    walk(effects)
    return {"center": node_id, "causes": causes, "effects": effects, "nodes": _brief(store, ids)}


def paths(store: GraphStore, src: str, dst: str, max_depth: int = 8, limit: int = 3) -> dict:
    """src 에서 dst 로 가는 **최단** 인과 경로들. 앞으로 못 가면 뒤로도 본다
    (물음이 '어떻게 이어졌나'이지 '어느 쪽이 먼저냐'가 아니므로).

    폭 우선으로 층을 쌓아 dst 에 닿은 층에서 멈추고, 그 층까지의 부모
    사슬을 되짚는다. 한 층 안에 같은 노드가 여럿으로 닿으면 경로가 갈린다."""
    for a, b, flipped in ((src, dst, False), (dst, src, True)):
        found = _shortest(store, a, b, max_depth, limit)
        if found:
            ids = {n for p in found for n in p}
            steps = []
            for p in found:
                walk = []
                for i, n in enumerate(p):
                    edge = None
                    if i > 0:
                        edge = next((l for l in _links(store, p[i - 1], "out") if l["id"] == n), None)
                    walk.append({"id": n, "edge": edge})
                steps.append(walk)
            return {"from": src, "to": dst, "found": True, "reversed": flipped,
                    "paths": steps, "nodes": _brief(store, ids)}
    return {"from": src, "to": dst, "found": False, "reversed": False, "paths": [], "nodes": {}}


def _shortest(store: GraphStore, src: str, dst: str, max_depth: int, limit: int) -> list[list[str]]:
    if src == dst:
        return []
    parents: dict[str, list[str]] = {src: []}
    frontier = [src]
    for _ in range(max_depth):
        nxt: list[str] = []
        for node in frontier:
            for link in _links(store, node, "out"):
                n = link["id"]
                if n == src:
                    continue
                if n not in parents:
                    parents[n] = [node]
                    nxt.append(n)
                elif n in nxt:      # 같은 층에서 다른 길로 또 닿았다
                    parents[n].append(node)
        if dst in parents:
            break
        if not nxt:
            return []
        frontier = nxt
    if dst not in parents:
        return []
    out: list[list[str]] = []

    def back(node: str, tail: list[str]) -> None:
        if len(out) >= limit:
            return
        if node == src:
            out.append([src, *tail])
            return
        for p in parents[node]:
            back(p, [node, *tail])

    back(dst, [])
    return out


# --- 글로 읽기 (CLI) --------------------------------------------------------
def render_chain(got: dict, direction: str = "both") -> str:
    nodes = got["nodes"]

    def name(i: str) -> str:
        n = nodes.get(i, {})
        y = (n.get("start") or "")[:4].lstrip("0") or ""
        return f"{n.get('label', i)}" + (f" ({y})" if y else "")

    lines = [name(got["center"])]

    def walk(items: list[dict], indent: int, arrow: str) -> None:
        for it in items:
            how = f" — {it['how']}" if it.get("how") else ""
            shown = f"{name(it['id'])} ({it['as']})" if it.get("as") else name(it["id"])
            lines.append(f"{'  ' * indent}{arrow} [{it['kind']}] {shown}{how}")
            walk(it["children"], indent + 1, arrow)

    if direction in ("both", "in") and got["causes"]:
        lines.append("원인:")
        walk(got["causes"], 1, "←")
    if direction in ("both", "out") and got["effects"]:
        lines.append("결과:")
        walk(got["effects"], 1, "→")
    if len(lines) == 1:
        lines.append("  (인과 엣지가 없다)")
    return "\n".join(lines)


def render_paths(got: dict) -> str:
    nodes = got["nodes"]

    def name(i: str) -> str:
        n = nodes.get(i, {})
        y = (n.get("start") or "")[:4].lstrip("0") or ""
        return f"{n.get('label', i)}" + (f" ({y})" if y else "")

    if not got["found"]:
        return "  (인과 경로가 없다)"
    lines = []
    if got["reversed"]:
        lines.append("  (앞으로는 못 가고, 반대 방향으로 이어진다)")
    for p in got["paths"]:
        parts = []
        for step in p:
            e = step["edge"]
            parts.append((f"→[{e['kind']}{' · ' + e['how'] if e.get('how') else ''}] " if e else "") + name(step["id"]))
        lines.append("  " + " ".join(parts))
    return "\n".join(lines)
