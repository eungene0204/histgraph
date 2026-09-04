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

엣지는 언제나 원인 → 결과다. 라벨이 인과의 종류(`KINDS`)고, '어떻게'는
`props.how` 한 구절이 말한다. 화면(`relations.js`)이 이 이름을 그대로 읽는다.

사슬은 `chain`(한 노드의 원인·결과 나무)과 `paths`(두 노드 사이의 최단
인과 경로)로 읽는다. `/api/chain`·`/api/path`·`histgraph chain` 이 이걸 쓴다.
"""

from __future__ import annotations

import json
import logging
import re
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


# --- 문서 -------------------------------------------------------------------
def documents(
    store: GraphStore,
    corpus,
    types: tuple[str, ...] = ("event",),
    redo: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """물을 문서 — 말뭉치에 글이 있는 노드. **연결이 많은 사건부터** 묻는다.

    한 번 물은 문서는 `props.causes_model` 이 남아 다시 묻지 않는다.
    `ingest` 가 props 를 덮으면 표식이 사라지므로 수집 뒤에는 다시 돈다
    (다른 파생 표식과 같은 규약)."""
    from .corpus import has_doc

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
        if not redo and props.get("causes_model"):
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


def resolve(store: GraphStore, name: str, node_type: str, doc: dict) -> tuple[str, str, str] | None:
    """이름 -> (노드 id, 타입, 실제로 맞춘 표기). 없으면 None — 노드를 만들지 않는다.

    타입이 맞는 후보를 먼저, 없으면 타입을 무시하고 한 번 더 (모델이
    타입을 잘못 붙였을 수 있다). 동명이인은 `extract.pick_candidate` 가
    문서의 연대와 주인공으로 가른다. 이름 그대로 못 찾으면 서술구로 보고
    주어(`heads`)로 다시 찾는다 — 실측: 첫 3건에서 못 푼 이름 18개가
    전부 '후금의 파약 행위' 꼴이었다."""
    from .promote import life_span

    name = normalize_name(name)
    if len(name) < 2:
        return None
    doc_span = life_span(doc.get("start_date"), doc.get("end_date"))
    for candidate in [name, *heads(name)]:
        if candidate in HOME_POLITIES:
            return None
        for clause, args in (("AND n.type = ?2", (candidate, node_type)), ("", (candidate,))):
            row = pick_candidate(
                store.conn.execute(CANDIDATES.format(type_clause=clause), args).fetchall(),
                doc_span, doc["id"],
            )
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
    else:
        effect_year = e_end if e_end is not None else e_start
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


def run(
    store: GraphStore,
    corpus,
    backend,
    types: tuple[str, ...] = ("event",),
    limit: int | None = None,
    dry_run: bool = False,
    redo: bool = False,
) -> dict[str, Any]:
    """문서를 돌며 인과를 뽑는다. `backend` 가 None 이거나 dry_run 이면
    묻지 않고 물을 문서와 분량만 센다."""
    todo = documents(store, corpus, types=types, redo=redo, limit=limit)
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
        # 문서마다 커밋한다 — 끝에서 한 번 하면 다른 세션이 잠금에 죽는다
        store.conn.commit()
        counts["엣지"] += n
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
    budget = [TREE_BUDGET]
    causes = _tree(store, node_id, "in", depth, budget)
    effects = _tree(store, node_id, "out", depth, budget)
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
