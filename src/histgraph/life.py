"""개인 역사 엔진 — 한 사람의 인생 이야기를 역사 그래프로.

사용자가 자기 삶을 말로 적으면, 모델이 그것을 노드·엣지·연표·인과·분석으로
옮기고, 이 모듈이 그 답을 **검증하고 한국사 그래프에 잇는다**. 화면은
왼쪽에 왕·대통령의 재위 띠, 가운데에 역사 연표, 오른쪽에 개인 연표를 같은
자 위에 세운다 (`web/src/lib/life.js`).

역할이 셋으로 갈린다:

- **지시문**(`life_prompt.md`)은 사용자가 쓴 그대로다. 모델이 무엇을 만들지는
  거기 적혀 있고, 이 모듈은 그 글을 고치지 않는다.
- **스키마**(`SCHEMA`)는 지시문의 출력 형식을 기계가 강제할 수 있는 꼴로 옮긴
  것이다. MLX 백엔드는 스키마를 유한상태기계로 컴파일해 토큰을 마스킹하므로
  (`backends.MLXBackend`) 형태는 늘 맞고, 내용의 검증만 남는다.
- **검증·연결**(`validate`·`link`)은 코드가 한다. 모델이 'direct' 라고 적은
  것을 화면이 '직접'으로 읽는 표, 날짜 문자열('2000년대 초반'·'20대 초반')을
  연도로 푸는 규칙, 모델이 이름으로만 부른 역사 사건을 그래프의 노드에 잇는
  것은 모델에게 맡기지 않는다.

**개인 자료는 저장소에 두지 않는다.** `data/life/` 는 .gitignore 에 있다.
배포된 화면(Vercel)은 저장된 개인 그래프가 없으므로, 사람이 JSON 을 직접
붙여 넣거나 파일로 올린다 — 서버는 그 구간의 재위 띠와 큰 사건만 준다
(`/api/context`).

**화면에는 한글만 띄운다** (CLAUDE.md §1). 지시문의 타입·관계 이름은 영어
식별자라 화면에 그대로 내지 않는다 — `NODE_TYPE_KO`·`EDGE_TYPE_KO`·
`IMPACT_KO` 가 전부를 옮기고, 표에 없는 이름은 테스트가 잡는다.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).with_name("life_prompt.md")
# 개인 자료가 놓이는 곳. 저장소 밖(.gitignore)이다.
LIFE_DIR = Path(__file__).resolve().parents[2] / "data" / "life"


def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# --- 화면 이름표 -------------------------------------------------------
# 지시문의 식별자 → 화면에 적는 한국어. 지시문에 있는 것은 빠짐없이 둔다
# (테스트가 지시문을 읽어 대조한다). 화면 코드(`life.js`)도 같은 표를 든다.
NODE_TYPE_KO: dict[str, str] = {
    "Person": "인물", "FamilyMember": "가족", "Ancestor": "조상", "Relationship": "관계",
    "Time": "때", "LifeStage": "인생 단계", "Period": "시기",
    "PersonalEvent": "개인 사건", "HistoricalEvent": "역사 사건", "TurningPoint": "전환점",
    "Crisis": "위기", "Achievement": "성취", "Failure": "실패", "Decision": "결정",
    "Location": "장소", "BirthPlace": "출생지", "Residence": "거주지", "TravelLocation": "여행지",
    "School": "학교", "University": "대학", "Company": "회사", "Organization": "단체",
    "Community": "공동체",
    "Occupation": "직업", "Project": "프로젝트", "Business": "사업", "Investment": "투자",
    "Hobby": "취미", "Skill": "기술",
    "Book": "책", "Movie": "영화", "Music": "음악", "Religion": "종교", "Culture": "문화",
    "Technology": "기술 환경", "Comic": "만화", "Game": "게임", "Memory": "기억",
}
EDGE_TYPE_KO: dict[str, str] = {
    "parent_of": "부모", "child_of": "자녀", "grandparent_of": "조부모", "ancestor_of": "조상",
    "relative_of": "친척",
    "influenced": "영향을 줌", "inspired": "영감을 줌", "helped": "도움", "mentored_by": "스승",
    "worked_with": "함께 일함", "met": "만남",
    "caused": "원인", "triggered": "촉발", "led_to": "이어짐", "changed": "바꿈",
    "affected": "영향", "resulted_in": "결과",
    "before": "앞", "after": "뒤", "during": "동안", "overlapped": "겹침",
    "born_in": "출생지", "lived_in": "거주", "moved_to": "이주", "visited": "방문",
    "grew_up_in": "성장지",
    "studied_at": "수학", "worked_at": "근무", "member_of": "소속",
    "changed_by": "바뀜", "inspired_by": "영감을 받음",
    "read": "읽음", "changed_belief": "생각을 바꿈", "recommended_by": "추천받음",
    "shared_with": "함께 나눔",
    "listened_to": "들음", "associated_with": "연관", "reminds_of": "떠올림",
    "watched": "봄", "changed_view": "관점을 바꿈", "connected_to_event": "사건과 연결",
    "shaped_interest": "관심을 만듦", "created_memory": "기억을 남김",
    "played": "함", "learned": "배움", "built_skill": "기술을 익힘",
    "used": "사용", "enabled": "가능하게 함", "changed_life": "삶을 바꿈",
    "remembered_by": "기억됨", "connected_to": "연결", "triggered_by": "촉발됨",
    "shaped": "형성", "connected": "연결",
}
# 사건 관계 가운데 **원인 → 결과**로 읽는 것. 화면이 개인 연표에서 인과 선으로 긋는다.
CAUSAL_EDGES = frozenset({"caused", "triggered", "led_to", "resulted_in"})
IMPACT_KO = {"direct": "직접", "indirect": "간접", "possible": "가능성"}
LIFE_STAGES = ["출생", "어린 시절", "초등학교", "중학교", "고등학교", "대학",
               "사회생활", "창업", "가족 형성", "현재"]
# 연표에 점으로 찍는 타입. 사람·장소·책은 이어지는 것이라 점이 아니다
# (server.POINT_TYPES 와 같은 이유).
EVENT_TYPES = frozenset({"PersonalEvent", "HistoricalEvent", "TurningPoint", "Crisis",
                         "Achievement", "Failure", "Decision", "Memory"})


# --- 스키마 --------------------------------------------------------------
def _nullable(kind: str) -> dict:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
_CONF = {"type": "number", "minimum": 0, "maximum": 1}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": _STR,
                "type": {"type": "string", "enum": sorted(NODE_TYPE_KO)},
                "name": _STR,
                "description": _nullable("string"),
                "start_date": _nullable("string"),
                "end_date": _nullable("string"),
                "location": _nullable("string"),
                "participants": _STRS,
                "importance_score": _nullable("integer"),
                "emotional_impact": _nullable("string"),
                "author": _nullable("string"),
                "category": _nullable("string"),
                "influence": _nullable("string"),
                "confidence": _CONF,
            },
            "required": ["id", "type", "name", "confidence"],
        }},
        "edges": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "source": _STR, "target": _STR,
                "type": {"type": "string", "enum": sorted(EDGE_TYPE_KO)},
                "description": _nullable("string"),
                "confidence": _CONF,
            },
            "required": ["source", "target", "type", "confidence"],
        }},
        "timeline": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "event_id": _STR,
                "life_stage": {"type": "string", "enum": LIFE_STAGES},
                "year": _nullable("integer"),
                "age": _nullable("integer"),
                "date_text": _nullable("string"),
                "previous_event": _nullable("string"),
                "next_event": _nullable("string"),
            },
            "required": ["event_id", "life_stage"],
        }},
        "historical_connections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "personal_event": _STR,
                "historical_event": _STR,
                "year": _nullable("integer"),
                "impact_type": {"type": "string", "enum": sorted(IMPACT_KO)},
                "description": _STR,
                "confidence": _CONF,
            },
            "required": ["personal_event", "historical_event", "impact_type", "description", "confidence"],
        }},
        "family_analysis": {
            "type": "object",
            "properties": {
                "origin": _nullable("string"),
                "members": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"node_id": _STR, "relation": _STR, "description": _STR},
                    "required": ["node_id", "relation", "description"],
                }},
                "historical_flow": _nullable("string"),
                "values": _nullable("string"),
            },
            "required": ["members"],
        },
        "impact_analysis": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "event": _STR,
                "impact_type": {"type": "string", "enum": sorted(IMPACT_KO)},
                "description": _STR,
                "strength": {"type": "integer", "minimum": 1, "maximum": 10},
                "confidence": _CONF,
            },
            "required": ["event", "impact_type", "description", "strength", "confidence"],
        }},
        "turning_points": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "event": _STR,
                "turning_point_score": {"type": "integer", "minimum": 1, "maximum": 10},
                "reason": _STR,
            },
            "required": ["event", "turning_point_score", "reason"],
        }},
        "counterfactual_analysis": {"type": "array", "items": {
            "type": "object",
            "properties": {"event": _STR, "question": _STR, "possibilities": _STRS},
            "required": ["event", "question", "possibilities"],
        }},
        "life_patterns": {"type": "array", "items": {
            "type": "object",
            "properties": {"pattern": _STR, "kind": _STR, "evidence": _STRS},
            "required": ["pattern", "evidence"],
        }},
        "influence_ranking": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "category": _STR, "node": _STR,
                    "influence_score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "reason": _STR,
                },
                "required": ["category", "node", "influence_score", "reason"],
            }}},
            "required": ["items"],
        },
        "follow_up_questions": _STRS,
    },
    "required": ["nodes", "edges", "timeline", "historical_connections", "family_analysis",
                 "impact_analysis", "turning_points", "counterfactual_analysis",
                 "life_patterns", "influence_ranking", "follow_up_questions"],
}


def build_user(text: str, today: datetime.date | None = None,
               anchors: list[dict] | None = None) -> str:
    """모델에게 건네는 사용자 쪽 글. 이야기와 오늘 날짜, 그래프의 사건 이름.

    오늘을 적는 이유: '현재' 단계와 나이 계산이 날짜 없이는 안 된다.
    그래프의 사건 이름을 주는 이유: 모델은 '1997년 외환 위기'라 부르고
    그래프는 '대한민국의 IMF 구제금융 요청'이라 부른다 — 이름이 다르면
    `link` 가 못 잇는다. 이름을 보여 주면 모델이 그 이름을 그대로 쓰고,
    화면이 그 사건 노드로 옮겨 갈 수 있다. 목록에 없는 사건도 쓸 수 있다
    (그때는 화면이 '그래프에 없는 사건'으로 세운다).
    이 함수가 지시문을 되풀이하지 않는다 — 지시문은 시스템 쪽 하나뿐이다."""
    today = today or datetime.date.today()
    known = ""
    if anchors:
        names = ", ".join(f"{a['label']}({a['year']})" for a in anchors)
        known = ("\n\n한국사 그래프에 있는 이 무렵의 사건 이름이다. 역사 연결"
                 "(historical_connections.historical_event)에는 되도록 이 이름을 그대로 쓴다:\n"
                 f"{names}")
    return (
        "다음은 사용자가 자기 삶에 대해 말한 이야기다.\n\n"
        f"{text.strip()}{known}\n\n"
        f"오늘은 {today.isoformat()} 이다. 이야기에 없는 것은 지어내지 말고 null 로 둔다. "
        "모든 이름·설명·분석은 한국어로 쓴다. 지시된 JSON 만 출력한다."
    )


# 답의 크기. 절 열한 개에 노드 수십 개라 요약 한 편(800)과 다르다.
MAX_TOKENS = 12000


def analyze(text: str, backend, anchors: list[dict] | None = None) -> dict | None:
    """이야기 하나를 모델에 물어 그래프 JSON 을 받는다. 실패면 None."""
    got = backend.complete_json(system_prompt(), build_user(text, anchors=anchors), SCHEMA,
                                max_tokens=MAX_TOKENS)
    if not isinstance(got, dict):
        return None
    return got


# --- 날짜 -----------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_YEAR = re.compile(r"(\d{4})\s*년?")
_DECADE = re.compile(r"(\d{4})\s*년대\s*(초반|중반|후반)?")
_AGE = re.compile(r"(\d{1,2})\s*(?:대\s*(초반|중반|후반)?|살|세)")
_PART = {"초반": 1, "중반": 4, "후반": 7, None: 4}


def parse_when(text: str | None, birth_year: int | None = None) -> tuple[int | None, int | None, str]:
    """'언제'를 (시작 해, 끝 해, 정밀도) 로.

    정밀도는 화면이 단정의 폭을 정하는 데 쓴다 — 'exact'(날짜까지) ·
    'year' · 'decade'('2000년대 초반' 은 2000~2003) · 'age'('20대 초반' 은
    생년+20~23, 생년을 모르면 못 푼다) · '' (모른다).

    지어내지 않는다. '20대 초반'을 생년 없이 받으면 (None, None, 'age') 다."""
    s = (text or "").strip()
    if not s:
        return None, None, ""
    m = _ISO.match(s)
    if m:
        y = int(m.group(1))
        return y, y, "exact" if m.group(2) else "year"
    m = _DECADE.search(s)
    if m:
        base = int(m.group(1))
        part = m.group(2)
        lo = base + (0 if part is None else _PART[part] - 1)
        hi = base + 9 if part is None else lo + 3
        return lo, hi, "decade"
    m = _YEAR.search(s)
    if m:
        y = int(m.group(1))
        return y, y, "year"
    m = _AGE.search(s)
    if m:
        if birth_year is None:
            return None, None, "age"
        n = int(m.group(1))
        if "대" in s[m.start():m.end()]:
            lo = birth_year + n + (0 if m.group(2) is None else _PART[m.group(2)] - 1)
            hi = birth_year + n + 9 if m.group(2) is None else lo + 3
            return lo, hi, "age"
        return birth_year + n, birth_year + n, "age"
    return None, None, ""


# --- 검증 -----------------------------------------------------------------
def _norm_label(s: str) -> str:
    """이름 대조용 — 띄어쓰기·가운뎃점·괄호를 걷는다 ('3·1 운동' = '3.1운동')."""
    return re.sub(r"[\s·.\-–—()（）]", "", str(s or "")).lower()


def validate(payload: dict) -> tuple[dict, list[str]]:
    """모델의 답을 화면이 믿고 그릴 수 있는 꼴로 다듬고, 고친 것을 적어 준다.

    형태는 스키마가 지켰다고 보고 **내용**만 본다:
      - 타입·관계 이름이 표에 없으면 버린다 (화면이 영어를 띄우게 된다).
      - 엣지의 양끝이 노드에 없으면 버린다.
      - 신뢰도는 0~1 로, 점수는 1~10 으로 자른다.
      - 노드의 날짜를 풀어 `year`·`end_year`·`precision` 을 단다. 연표 항목이
        연도를 안 적었으면 노드의 것을 쓴다. 나이만 있으면 생년으로 푼다.
      - 노드 이름·설명에 한글이 한 자도 없으면 경고한다 (버리지는 않는다 —
        '2001: A Space Odyssey' 같은 제목은 그대로가 맞을 수 있다).
    """
    from .labels import HANGUL

    notes: list[str] = []
    out: dict[str, Any] = {k: payload.get(k) for k in SCHEMA["properties"]}
    nodes: list[dict] = []
    seen: set[str] = set()
    for n in payload.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id") or not n.get("name"):
            continue
        t = n.get("type")
        if t not in NODE_TYPE_KO:
            notes.append(f"모르는 노드 타입 {t!r}: {n.get('name')} — 버림")
            continue
        if n["id"] in seen:
            notes.append(f"노드 id 중복 {n['id']} — 뒤의 것을 버림")
            continue
        seen.add(n["id"])
        node = dict(n)
        node["confidence"] = _clip(n.get("confidence", 1.0), 0.0, 1.0)
        if n.get("importance_score") is not None:
            node["importance_score"] = int(_clip(n["importance_score"], 1, 10))
        if not HANGUL.search(n["name"]) and not HANGUL.search(n.get("description") or ""):
            notes.append(f"한글이 없는 노드: {n['name']}")
        nodes.append(node)
    out["nodes"] = nodes
    by_id = {n["id"]: n for n in nodes}

    # 생년 — 나이로 적힌 날짜를 푸는 열쇠. 주인공(Person) 의 start_date 다.
    me = next((n for n in nodes if n["type"] == "Person"), None)
    birth = parse_when(me.get("start_date") if me else None)[0]
    out["subject"] = {"id": me["id"], "name": me["name"], "birth_year": birth} if me else None
    for n in nodes:
        y, y2, prec = parse_when(n.get("start_date"), birth)
        e = parse_when(n.get("end_date"), birth)[0]
        n["year"], n["end_year"], n["precision"] = y, (e if e is not None else (y2 if y2 != y else None)), prec

    # 양끝을 id 대신 **이름**으로 적는 모델이 있다 (2026-09-08 실측: 무료
    # 모델 하나가 관계 열일곱 중 여섯을 그렇게 적었다). 관계는 참인데 부르는
    # 법만 다른 것이라 버리지 않고 되짚는다. 같은 이름이 둘이면 손대지 않는다.
    by_name: dict[str, str] = {}
    for n in nodes:
        by_name[_norm_label(n["name"])] = "" if _norm_label(n["name"]) in by_name else n["id"]

    def _endpoint(ref: Any) -> str | None:
        if ref in by_id:
            return str(ref)
        return by_name.get(_norm_label(ref)) or None

    edges: list[dict] = []
    for e in payload.get("edges") or []:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t not in EDGE_TYPE_KO:
            notes.append(f"모르는 관계 {t!r}: {e.get('source')} → {e.get('target')} — 버림")
            continue
        src, dst = _endpoint(e.get("source")), _endpoint(e.get("target"))
        if src is None or dst is None:
            notes.append(f"양끝이 없는 관계 {e.get('source')} → {e.get('target')} — 버림")
            continue
        if src != e.get("source") or dst != e.get("target"):
            notes.append(f"이름으로 적힌 관계를 노드에 이음: {e.get('source')} → {e.get('target')}")
        edges.append(dict(e, source=src, target=dst,
                          confidence=_clip(e.get("confidence", 1.0), 0.0, 1.0)))
    out["edges"] = edges

    timeline: list[dict] = []
    for t in payload.get("timeline") or []:
        if not isinstance(t, dict) or t.get("event_id") not in by_id:
            notes.append(f"연표 항목의 사건이 노드에 없음: {t.get('event_id') if isinstance(t, dict) else t!r}")
            continue
        node = by_id[t["event_id"]]
        item = dict(t)
        if item.get("life_stage") not in LIFE_STAGES:
            item["life_stage"] = None
        # 해의 출처 차례: 항목의 날짜 글 → 나이(생년을 알 때) → 노드의 날짜.
        # 나이가 노드의 어림 날짜('20대 초반')보다 앞서는 이유: 모델이 그 항목에
        # 적은 나이는 그 사건에 대한 말이고, 노드의 날짜는 구간일 수 있다.
        if item.get("year") is None:
            item["year"] = parse_when(item.get("date_text"), birth)[0]
        if item.get("year") is None and item.get("age") is not None and birth is not None:
            item["year"] = birth + int(item["age"])
        if item.get("year") is None:
            item["year"] = node.get("year")
        if item.get("age") is None and item.get("year") is not None and birth is not None:
            item["age"] = int(item["year"]) - birth
        timeline.append(item)
    timeline.sort(key=lambda t: (t["year"] is None, t["year"] or 0))
    out["timeline"] = timeline

    for key, field in (("impact_analysis", "strength"), ("turning_points", "turning_point_score")):
        items = []
        for it in payload.get(key) or []:
            if isinstance(it, dict) and it.get("event"):
                items.append(dict(it, **{field: int(_clip(it.get(field, 5), 1, 10))}))
        out[key] = items
    out["historical_connections"] = [
        dict(c, impact_type=c.get("impact_type") if c.get("impact_type") in IMPACT_KO else "possible")
        for c in payload.get("historical_connections") or [] if isinstance(c, dict)
    ]
    ranking = payload.get("influence_ranking") or {}
    # 지시문의 형태('{}')는 범주 → 항목일 수도, 목록일 수도 있다. 둘 다 받는다.
    if isinstance(ranking, dict) and not isinstance(ranking.get("items"), list):
        ranking = {"items": [dict(v, category=k) for k, v in ranking.items() if isinstance(v, dict)]}
    elif isinstance(ranking, list):
        ranking = {"items": ranking}
    out["influence_ranking"] = ranking
    out["follow_up_questions"] = [str(q) for q in (payload.get("follow_up_questions") or [])][:5]
    out["family_analysis"] = payload.get("family_analysis") or {"members": []}
    out["counterfactual_analysis"] = [c for c in payload.get("counterfactual_analysis") or [] if isinstance(c, dict)]
    out["life_patterns"] = [p for p in payload.get("life_patterns") or [] if isinstance(p, dict)]
    # 어느 모델이 쓴 그래프인지. 백엔드가 여럿이라(로컬 MLX·OpenRouter 무료
    # 모델) 이 값이 없으면 나중에 이상한 노드의 출처를 가릴 수 없다.
    if payload.get("_model"):
        out["_model"] = payload["_model"]
    out["notes"] = notes
    return out, notes


def _clip(v: Any, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return lo if lo > 0 else hi
    return max(lo, min(hi, x))


# --- 그래프에 잇기 -----------------------------------------------------------
# 이름 뒤에 붙은 해 — '3·1 운동(1919)' · '6.25 전쟁 (1950년)'.
_TRAILING_YEAR = re.compile(r"[（(]\s*(\d{3,4})\s*년?\s*[）)]\s*$")


def link(payload: dict, api) -> int:
    """모델이 이름으로만 부른 역사 사건을 그래프의 노드에 잇는다.

    `historical_connections[].historical_event` 는 '1997년 외환 위기' 같은
    글자다. 그래프에 그 이름의 사건 노드가 있으면 id 를 달아 화면이 그
    노드로 옮겨 갈 수 있게 한다. **이름과 해가 둘 다 맞아야 잇는다** — 해를
    모르면 이름만으로 잇되 그렇다고 적는다. 없는 것은 없는 대로 둔다 (지어서
    잇지 않는다). 이은 수를 돌려준다."""
    n = 0
    for c in payload.get("historical_connections") or []:
        label = c.get("historical_event") or ""
        if not label:
            continue
        # 모델은 우리가 보여 준 목록('이름(1997)')을 괄호째 베껴 온다
        # (2026-09-08 실측 — 그 때문에 이은 것이 0 이었다). 뒤에 붙은 해는
        # 이름이 아니라 해다. 떼어 내고 해가 비었으면 그 값을 쓴다.
        m = _TRAILING_YEAR.search(label)
        if m:
            label = label[: m.start()].strip()
            if c.get("year") is None:
                c["year"] = int(m.group(1))
        hits = api.search(label, 8) if hasattr(api, "search") else []
        want = _norm_label(label)
        best = None
        for h in hits:
            if h.get("type") != "event":
                continue
            names = [h.get("label", "")] + list(h.get("names") or [])
            if not any(_norm_label(x) == want for x in names):
                continue
            hy = h.get("start")
            if c.get("year") is not None and hy is not None and abs(int(c["year"]) - hy) > 1:
                continue
            best = h
            break
        if best is None:
            c["node_id"] = None
            continue
        c["node_id"] = best["id"]
        c["node_label"] = best.get("label")
        hy = best.get("start")
        if c.get("year") is None and hy is not None:
            c["year"] = hy
            c["year_from"] = "graph"
        n += 1
    return n


def _year_of(date: str | None) -> int | None:
    m = re.match(r"^(-?\d{1,4})", str(date or ""))
    return int(m.group(1)) if m else None


def span(payload: dict, today: datetime.date | None = None) -> tuple[int | None, int | None]:
    """개인 연표가 걸치는 해 — 축의 처음과 끝. 생년(또는 첫 사건)부터 오늘까지."""
    today = today or datetime.date.today()
    years = [t["year"] for t in payload.get("timeline") or [] if t.get("year") is not None]
    years += [n["year"] for n in payload.get("nodes") or [] if n.get("year") is not None
              and n.get("type") in EVENT_TYPES]
    subject = payload.get("subject") or {}
    if subject.get("birth_year") is not None:
        years.append(subject["birth_year"])
    if not years:
        return None, None
    return min(years), max(max(years), today.year)


# --- 파일 -------------------------------------------------------------------
def save(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find(name: str | None = None, root: Path | None = None) -> Path | None:
    """저장된 개인 그래프. 이름을 주면 그것, 없으면 가장 최근 것."""
    root = root or LIFE_DIR
    if not root.is_dir():
        return None
    if name:
        p = root / f"{name}.json"
        return p if p.is_file() else None
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None
