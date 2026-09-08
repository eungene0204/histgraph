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
    # 아래 셋은 지시문에 없고 다듬기(tidy_edges)가 세운다 — 친구는 '만남'이 아니고,
    # 주인공과 자기 사건은 '뒤'·'동안'이 아니다 (2026-09-08 사용자: "친구들은 만남이
    # 아니라 '친구'라고 표시해야. 그리고 '뒤', '동안' 이런 설명은 도대체 뭐야?").
    "friend_of": "친구", "experienced": "당사자", "schoolmate": "같은 학교", "at": "곳",
    "caused": "원인", "triggered": "촉발", "led_to": "이어짐", "changed": "바꿈",
    "affected": "영향", "resulted_in": "결과",
    "before": "다음", "after": "이전", "during": "동안", "overlapped": "겹침",
    "born_in": "출생지", "lived_in": "거주", "moved_to": "이주", "visited": "방문",
    "grew_up_in": "성장지",
    "studied_at": "재학", "worked_at": "근무", "member_of": "소속",
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


def existing_summary(base: dict) -> dict:
    """이미 있는 그래프를 모델에게 보일 만큼만 — 노드의 id·타입·이름·해와 주인공."""
    nodes = [{"id": n["id"], "type": n.get("type"), "name": n.get("name"), "year": n.get("year")}
             for n in base.get("nodes") or [] if isinstance(n, dict) and n.get("id") and n.get("name")]
    return {"subject": base.get("subject") or None, "nodes": nodes}


def build_user(text: str, today: datetime.date | None = None,
               anchors: list[dict] | None = None, existing: dict | None = None) -> str:
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
    # **더하는 이야기**: 이미 있는 그래프의 노드를 보여 주고 같은 것은 그 id 를
    # 쓰게 한다 — 그래야 `merge` 가 새 답을 옛 그래프에 잇는다 (2026-09-08 사용자:
    # "나중에 추가해서 입력 하면 원래 있던 역사에 추가 시켜줘. 기존것을 지우고
    # 새로 만들지 말고"). 목록에 있는 것을 다시 만들지 않게도 한다.
    if existing and existing.get("nodes"):
        subj = existing.get("subject") or {}
        rows = "\n".join(f"- {n['id']} · {NODE_TYPE_KO.get(n['type'], n['type'])} · {n['name']}"
                         f"{' · ' + str(n['year']) if n.get('year') is not None else ''}"
                         for n in existing["nodes"])
        who = (f" 주인공은 id {subj['id']} '{subj.get('name') or '나'}' 이다."
               if subj.get("id") else "")
        if subj.get("birth_year") is not None:
            who += f" 주인공의 생년은 {subj['birth_year']}년이다."
        known += (
            "\n\n이 사람의 역사 그래프는 이미 있다. 아래가 그 노드다 (id · 타입 · 이름 · 해)."
            " 위 이야기는 거기에 **더하는** 이야기다. 같은 사람·장소·사건·사물이 나오면"
            " 새 id 를 만들지 말고 아래 id 를 그대로 쓴다. 아래에 있는 것을 다시 만들지"
            " 않는다 — 위 이야기가 새로 말하는 것만 만든다. 새 사건이 아래의 사건과"
            " 이어지면(원인·다음) 그 id 로 관계를 적는다. 연표·분석도 새 것만 적는다."
            f"{who}\n{rows}"
        )
    return (
        "다음은 사용자가 자기 삶에 대해 말한 이야기다.\n\n"
        f"{text.strip()}{known}\n\n"
        f"오늘은 {today.isoformat()} 이다. 이야기에 없는 것은 지어내지 말고 null 로 둔다. "
        # 해를 안 적은 말은 앞뒤에서 셈한다 (2026-09-08 사용자: "1997년 고등학교
        # 입학했다고 했고 1학년때 누굴 만나고 2학년때 누굴 만났다고 하면 …
        # 1997년에 만났고 1998년에 만났다는걸 유추해서 알 수 있지 않나?").
        "다만 해를 말하지 않은 일도 앞뒤에서 셈할 수 있으면 셈해서 적는다: "
        "1997년에 고등학교에 들어갔다면 '고등학교 1학년 때'는 1997년, '2학년 때'는 1998년, "
        "'3학년 때'는 1999년이다. '입사 이듬해'·'그해 겨울'·'대학 졸업 직후'·'군대 다녀와서'도 "
        "같은 식으로 앞뒤 사건의 해에서 센다. 셈한 해는 start_date 에 적고 confidence 를 "
        "0.7~0.9 로 낮춘다. 셈할 근거가 아무것도 없을 때만 null 로 둔다. "
        # 만난 사람은 주인공과, 만난 곳과 잇는다 (2026-09-08 사용자: "고등학교에서
        # 만났다고 하면 내가 입학했다고 말한 고등학교와 연결 시켜줘야 하는거야").
        "만난 사람은 주인공과 met 관계로 잇고(친구라고 했으면 friend_of, 함께 일한 사람이면 worked_with), "
        "어디서 만났는지(학교·회사·모임)를 말했으면 "
        "그 사람을 그 학교·회사 노드와도 잇는다(studied_at·worked_at·member_of) — 새 노드를 "
        "만들지 말고 이야기가 말한 그 학교·회사 노드를 쓴다. 만난 일은 timeline 에도 세운다. "
        "주인공의 생년월일은 주인공 노드의 start_date 에 적는다. "
        # 시간 관계는 사건과 사건 사이의 것이다 (실측 2026-09-08: 주인공 → '미국으로
        # 이주' 가 after, → '잠실고등학교 입학' 이 during 으로 와 화면에 '뒤'·'동안'이 섰다).
        "주인공과 주인공 자신의 사건은 experienced 로 잇는다 — before·after·during·overlapped 는 "
        "사건과 사건, 사건과 시기 사이에만 쓴다. "
        "모든 이름·설명·분석은 한국어로 쓴다. 지시된 JSON 만 출력한다."
    )


# 답의 크기. 절 열한 개에 노드 수십 개라 요약 한 편(800)과 다르다.
MAX_TOKENS = 12000


def analyze(text: str, backend, anchors: list[dict] | None = None,
            existing: dict | None = None) -> dict | None:
    """이야기 하나를 모델에 물어 그래프 JSON 을 받는다. 실패면 None."""
    got = backend.complete_json(system_prompt(), build_user(text, anchors=anchors, existing=existing),
                                SCHEMA, max_tokens=MAX_TOKENS)
    if not isinstance(got, dict):
        return None
    return got


# --- 다듬기: 앞뒤에서 셈하고, 만난 곳에 잇는다 -----------------------------------
# 모델이 빠뜨린 것을 이야기 안의 다른 노드에서 채운다. 검증 끝과 더하기 끝에
# 한 번씩 돈다 (옛 그래프도 다음 더하기 때 같이 고쳐진다).
#   1. 생년: 주인공 노드의 start_date 가 비었으면 '출생' 노드나 설명에서.
#   2. 해: 학년('고등학교 2학년')은 입학 해에서, 없으면 생년에서. 사람 노드는
#      설명의 '…1학년 때 만난' 도 본다 — 그 사람이 내 삶에 들어온 해다.
#   3. 연표: 해가 빈 항목은 날짜 글 → 나이 → 노드의 해.
#   4. 잇기: 사람의 설명이 이야기 속 학교·회사 이름을 부르면 그 노드에 잇고
#      (studied_at·worked_at), 주인공과 아무 관계가 없는 '만난' 사람은 met 으로 잇는다.
_BIRTH_DESC = re.compile(r"(\d{4})\s*년[^.。]{0,25}?(태어|출생)")
_MET_WORDS = re.compile(r"만난|만났|만나|친구|동료|선배|후배|사귀|알게")
_BIRTH_NODE = re.compile(r"^(출생|탄생|태어남)$")


def birth_from_nodes(me: dict, nodes: list[dict], edges: list[dict]) -> int | None:
    """주인공의 생년 — 노드 자신에 없으면 '출생' 노드(born_in 으로 이어진 것이나
    그 이름의 노드)나 설명의 '1982년 … 태어난' 에서."""
    by_id = {n["id"]: n for n in nodes}
    for e in edges:
        if isinstance(e, dict) and e.get("source") == me["id"] and e.get("type") == "born_in":
            t = by_id.get(e.get("target"))
            if t and t.get("type") in ("Time", "PersonalEvent", "LifeStage"):
                y = parse_when(t.get("start_date"))[0]
                if y is not None:
                    return y
    for n in nodes:
        if n.get("type") in ("Time", "PersonalEvent", "LifeStage") and _BIRTH_NODE.match(str(n.get("name") or "").strip()):
            y = parse_when(n.get("start_date"))[0]
            if y is not None:
                return y
    m = _BIRTH_DESC.search(str(me.get("description") or ""))
    return int(m.group(1)) if m else None


def refine(payload: dict) -> dict:
    nodes: list[dict] = payload.get("nodes") or []
    edges: list[dict] = payload.setdefault("edges", [])
    if not nodes:
        return payload
    by_id = {n["id"]: n for n in nodes}
    subject = payload.get("subject") or {}
    me = by_id.get(subject.get("id"))

    # 1. 생년
    birth = subject.get("birth_year")
    if birth is None and me is not None:
        birth = parse_when(me.get("start_date"))[0] or birth_from_nodes(me, nodes, edges)
        if birth is not None:
            payload["subject"] = dict(subject, birth_year=birth)
            if me.get("year") is None:
                me["year"], me["precision"] = birth, me.get("precision") or "year"

    # 2. 해 — 학교 노드의 해는 입학 사건에서
    for e in edges:
        if e.get("type") == "studied_at" and by_id.get(e.get("target"), {}).get("type") in ("School", "University"):
            src, dst = by_id.get(e.get("source")), by_id[e["target"]]
            if src and src.get("year") is not None and dst.get("year") is None and "졸업" not in str(src.get("name") or ""):
                dst["year"], dst["precision"] = src["year"], "year"
    entries = school_entries(nodes)
    for n in nodes:
        if n.get("year") is not None and n.get("precision") != "age":
            continue
        y = school_year(n.get("start_date"), entries)
        prec = "year"
        if y is None and n.get("type") == "Person" and n is not me:
            y = school_year(n.get("description"), entries)
        if y is None and birth is not None:
            for text in (n.get("start_date"), n.get("description") if n.get("type") == "Person" and n is not me else None):
                if school_ref(text) is not None:
                    y, prec = parse_when(text, birth)[0], "age"
                    break
        if y is not None:
            n["year"], n["precision"] = y, prec

    # 3. 연표
    timeline: list[dict] = payload.get("timeline") or []
    for t in timeline:
        node = by_id.get(t.get("event_id"))
        if t.get("year") is None:
            t["year"] = school_year(t.get("date_text"), entries)
        if t.get("year") is None:
            t["year"] = parse_when(t.get("date_text"), birth)[0]
        if t.get("year") is None and t.get("age") is not None and birth is not None:
            t["year"] = birth + int(t["age"])
        if t.get("year") is None and node is not None:
            t["year"] = node.get("year")
        if t.get("age") is None and t.get("year") is not None and birth is not None:
            t["age"] = int(t["year"]) - birth
        if node is not None and node.get("year") is None and t.get("year") is not None:
            node["year"], node["precision"] = t["year"], "year"
    timeline.sort(key=lambda t: (t.get("year") is None, t.get("year") or 0))
    for i, t in enumerate(timeline):
        t["previous_event"] = timeline[i - 1]["event_id"] if i else None
        t["next_event"] = timeline[i + 1]["event_id"] if i + 1 < len(timeline) else None

    # 4. 잇기
    have = {(e.get("source"), e.get("target")) for e in edges}
    def linked(a: str, b: str) -> bool:
        return (a, b) in have or (b, a) in have
    places = [n for n in nodes if n.get("type") in ("School", "University", "Company", "Organization", "Community")
              and len(str(n.get("name") or "")) >= 2]
    for n in nodes:
        if n.get("type") != "Person" or n is me:
            continue
        text = f"{n.get('name') or ''} {n.get('description') or ''}"
        for pl in places:
            if pl["id"] != n["id"] and pl["name"] in text and not linked(n["id"], pl["id"]):
                kind = "studied_at" if pl["type"] in ("School", "University") else \
                       "worked_at" if pl["type"] == "Company" else "member_of"
                edges.append({"source": n["id"], "target": pl["id"], "type": kind,
                              "description": None, "confidence": 0.8})
                have.add((n["id"], pl["id"]))
        if me is not None and not linked(me["id"], n["id"]) and _MET_WORDS.search(text):
            edges.append({"source": me["id"], "target": n["id"], "type": "met",
                          "description": n.get("description"), "confidence": 0.8})
            have.add((me["id"], n["id"]))

    # 5. 관계의 이름 — 온톨로지(LIFE_EDGES)에 맞추고 역할을 단다
    for issue in tidy_edges(nodes, edges, me):
        log.warning("개인 그래프 온톨로지 밖: %s", issue)
    return payload


# --- 온톨로지: 관계마다 출발·도착 갈래 ---------------------------------------------
# 한국사 그래프의 `ontology.EDGE_TYPES` 와 같은 꼴 — (일반 이름, 출발 갈래, 도착 갈래).
# 갈래는 캔버스의 여덟 색(GRAPH_TYPE: person·event·org·place·artwork·media·period·role)
# 이다. 관계의 뜻은 이 표가 정한다 (concept.md §1: "선마다 무슨 관계인지가 정해져
# 있어야 한다. 그것이 온톨로지다"). 지시문(life_prompt.md)의 관계는 출발·도착이
# 없어서 모델이 주인공 → 자기 사건을 after·during 으로, 사건 → 학교를 studied_at
# 으로 적어 왔다 (2026-09-08 실측). 어긋난 엣지는 **버리지 않고** RELAX 표가 뜻이
# 남는 타입으로 옮긴다 (`untangle.RELAX` 와 같다). 표에 없으면 세어서 알린다.
GRAPH_TYPE: dict[str, str] = {
    "Person": "person", "FamilyMember": "person", "Ancestor": "person", "Relationship": "person",
    "Time": "period", "LifeStage": "period", "Period": "period",
    "PersonalEvent": "event", "HistoricalEvent": "event", "TurningPoint": "event", "Crisis": "event",
    "Achievement": "event", "Failure": "event", "Decision": "event", "Memory": "event",
    "Location": "place", "BirthPlace": "place", "Residence": "place", "TravelLocation": "place",
    "School": "org", "University": "org", "Company": "org", "Organization": "org", "Community": "org",
    "Business": "org", "Project": "org", "Investment": "org",
    "Occupation": "role", "Hobby": "role", "Skill": "role",
    "Book": "artwork", "Movie": "artwork", "Music": "artwork", "Comic": "artwork", "Game": "artwork",
    "Religion": "media", "Culture": "media", "Technology": "media",
}
_P, _E, _O, _L, _T, _R = ("person",), ("event",), ("org",), ("place",), ("period",), ("role",)
_W = ("artwork", "media")
_ANY = ("person", "event", "org", "place", "artwork", "media", "period", "role")
# 지시문의 관계 전부 + 다듬기가 세우는 셋(experienced·friend_of·schoolmate) + at.
LIFE_EDGES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    # 가족 — 사람 사이
    "parent_of": ("부모", _P, _P), "child_of": ("자녀", _P, _P), "grandparent_of": ("조부모", _P, _P),
    "ancestor_of": ("조상", _P, _P), "relative_of": ("친척", _P, _P),
    # 인생 관계 — 사람 사이. RELATIONSHIP 어휘(friendOf·hasMet·colleagueOf)처럼 '만난 사이'와
    # '친구'는 다른 관계다. schoolmate 는 '같은 학교에 다녔다'까지만 말한다.
    "friend_of": ("친구", _P, _P), "met": ("만남", _P, _P), "worked_with": ("함께 일함", _P, _P),
    "schoolmate": ("같은 학교", _P, _P), "mentored_by": ("스승", _P, _P), "helped": ("도움", _P, _P),
    "influenced": ("영향을 줌", _P + _E + _W + _O, _P + _E), "inspired": ("영감을 줌", _P + _E + _W + _O, _P + _E),
    # 사건 참여 — 한국사의 participated_in. 방향은 사람 → 사건이고 **역할**이 선의 이름이다
    # (BIO 어휘의 principal: 그 삶의 사건의 당사자). 역할은 사건 이름의 술어(입학·졸업·
    # 이주·창업)에서 읽고, 없으면 사건의 종류(전환점·위기·성취·실패·결정·기억)다.
    "experienced": ("당사자", _P, _E + _T),   # 도착에 period: 모델이 '출생'을 Time 으로 세운다
    # 사건 사이 — 인과와 차례
    "caused": ("원인", _E + _P + _O + _W, _E), "triggered": ("촉발", _E + _P + _O + _W, _E),
    "led_to": ("이어짐", _E, _E), "resulted_in": ("결과", _E, _E),
    "changed": ("바꿈", _E + _W + _P, _P + _E + _R), "affected": ("영향", _E + _W + _P, _P + _E + _R),
    "before": ("다음", _E + _T, _E + _T), "after": ("이전", _E + _T, _E + _T),
    "during": ("동안", _E, _E + _T), "overlapped": ("겹침", _E + _T, _E + _T),
    # 사건이 일어난 곳 — 한국사의 occurred_at. '잠실고등학교 입학 → 잠실고등학교' 는 사건이
    # 학교에 재학한 것이 아니라 그 학교**에서** 일어난 것이다.
    "at": ("곳", _E + _T, _O + _L + _R),
    # 장소 — 사람·사건 → 장소
    "born_in": ("출생지", _P + _E + _T, _L), "lived_in": ("거주", _P + _E, _L), "moved_to": ("이주", _P + _E, _L),
    "visited": ("방문", _P + _E, _L), "grew_up_in": ("성장지", _P, _L),
    # 조직 — 사람 → 학교·회사·단체
    "studied_at": ("재학", _P, _O + _R), "worked_at": ("근무", _P, _O + _R), "member_of": ("소속", _P, _O),
    # 문화 — 사람 ↔ 책·영화·음악·게임·기술
    "read": ("읽음", _P, _W), "watched": ("봄", _P, _W), "listened_to": ("들음", _P, _W),
    "played": ("함", _P, _W), "used": ("사용", _P, _W), "learned": ("배움", _P, _W + _R),
    "built_skill": ("기술을 익힘", _P + _W + _E, _R), "recommended_by": ("추천받음", _P + _W, _P),
    "shared_with": ("함께 나눔", _P + _W, _P), "changed_belief": ("생각을 바꿈", _W + _E + _P, _P),
    "changed_view": ("관점을 바꿈", _W + _E + _P, _P), "changed_life": ("삶을 바꿈", _W + _E + _P + _O, _P),
    "changed_by": ("바뀜", _P + _E, _W + _E + _P), "inspired_by": ("영감을 받음", _P + _E + _W, _W + _P + _E),
    "shaped_interest": ("관심을 만듦", _W + _E + _P, _P + _R), "shaped": ("형성", _W + _E + _P + _O, _P + _R),
    "enabled": ("가능하게 함", _W + _E + _P + _O, _E + _P + _O),
    "created_memory": ("기억을 남김", _W + _E + _P + _L, _E + _P), "remembered_by": ("기억됨", _ANY, _P),
    "reminds_of": ("떠올림", _W + _L + _E, _ANY), "associated_with": ("연관", _ANY, _ANY),
    "connected_to_event": ("사건과 연결", _ANY, _E), "triggered_by": ("촉발됨", _E, _E + _P + _W + _O),
    "connected_to": ("연결", _ANY, _ANY), "connected": ("연결", _ANY, _ANY),
}
# 한 출발 노드가 이 관계로 가리킬 수 있는 서로 다른 도착 노드의 수 (ontology.MAX_TARGETS).
# 넘으면 같은 곳을 두 해상도로 말한 것이다 — 세어서 알린다.
MAX_TARGETS = {"born_in": 1}
# (원래 타입, 출발 갈래, 도착 갈래) → 뜻이 남는 타입. 시간 관계는 사건 사이의 것이라
# 사람 → 사건이면 참여(experienced)고, 사건 → 학교·회사·전공은 재학이 아니라 그 곳(at)이다.
RELAX: dict[tuple[str, str, str], str] = {
    **{(t, "person", "event"): "experienced" for t in ("before", "after", "during", "overlapped")},
    **{(t, "event", "person"): "experienced" for t in ("before", "after", "during", "overlapped")},
    ("born_in", "person", "period"): "experienced",       # 나 → '출생'(Time) 은 출생지가 아니라 출생 사건
    **{(t, "event", c): "at" for t in ("studied_at", "worked_at", "member_of", "during", "lived_in")
       for c in ("org", "role")},
    **{(t, "period", c): "at" for t in ("studied_at", "worked_at", "member_of") for c in ("org", "role")},
}
# RELAX 가 옮기면서 남기는 역할 — 원래 타입이 말하던 것 (studied_at → 전공 = '전공').
RELAX_ROLE: dict[tuple[str, str], str] = {("studied_at", "role"): "전공", ("worked_at", "role"): "직업",
                                          ("born_in", "period"): "출생"}
_SYMMETRIC = frozenset({"met", "friend_of", "worked_with", "schoolmate", "relative_of", "shared_with", "overlapped"})
_FRIEND = re.compile(r"친구|벗|단짝|절친|죽마고우")
_COLLEAGUE = re.compile(r"동료|같이 일|함께 일|같은 회사|같은 팀")
# 사건 이름 꼬리의 술어 — 당사자가 그 사건에서 한 일. 이것이 선의 이름이다
# (한국사 그래프의 역할 머리말 '주도'·'지휘'와 같은 자리).
_DEED = re.compile(r"(입학|졸업|수료|자퇴|휴학|복학|편입|전학|유학|이주|이사|이민|귀국|출국|귀화|창업|개업|폐업|"
                   r"입사|퇴사|이직|취업|취직|승진|발령|전근|파견|은퇴|입소|입대|전역|제대|소집해제|결혼|이혼|약혼|"
                   r"출생|출산|사망|합격|낙방|수상|당선|낙선|출마|입원|수술|데뷔|입양|이별|재회|시작|종료)\s*$")
_EVENT_KIND_ROLE = {"TurningPoint": "전환점", "Crisis": "위기", "Achievement": "성취",
                    "Failure": "실패", "Decision": "결정", "Memory": "기억"}


def klass(node: dict | None) -> str | None:
    return GRAPH_TYPE.get(str((node or {}).get("type"))) if node else None


def deed_of(event: dict) -> str | None:
    """'잠실고등학교 입학' → '입학'. 이름 꼬리가 술어가 아니면 사건의 종류, 그것도 아니면 None."""
    name = str(event.get("name") or "").strip()
    m = _DEED.search(name)
    if m and m.group(1) not in ("시작", "종료"):
        return m.group(1)
    if m:   # '스타트업 경력 시작' → '경력 시작' — 무엇의 시작인지 한 낱말을 붙인다
        head = name[:m.start()].split()
        if head:
            return f"{head[-1]} {m.group(1)}"
    return _EVENT_KIND_ROLE.get(str(event.get("type")))


def fits(kind: str, src: dict | None, dst: dict | None) -> bool:
    spec = LIFE_EDGES.get(kind)
    return bool(spec) and klass(src) in spec[1] and klass(dst) in spec[2]


def tidy_edges(nodes: list[dict], edges: list[dict], me: dict | None) -> list[str]:
    """모델이 고른 타입을 온톨로지와 증거로 고친다. 고친 자리는 `props`가 아니라 엣지의
    `role`(선의 이름)에 남는다. 돌아오는 것은 표에 안 맞아 **그대로 둔** 엣지의 목록이다.

    실측 (2026-09-08, 사용자 "지금 그래프의 엣지 설명이 엉망이야"): 주인공 → 자기 사건 7건이
    after·during, 친구 셋이 met, 그 셋이 서로 worked_with(0.5 — 이야기에 일한 곳이 없다),
    나형철이 양방향 met. 규칙은 다섯이고 전부 이야기 안의 다른 것을 증거로 든다:
      1. 출발·도착이 표에 어긋나면 RELAX 로 옮긴다 (없으면 세어서 돌려준다).
      2. met 인데 설명이 '친구'라 하면 friend_of, '동료'면 worked_with.
      3. 미룬(확신 < 1) worked_with 인데 둘 다 일한 곳이 없고 같은 학교면 schoolmate.
      4. 사람 → 사건은 역할을 단다 — 당사자는 사건의 술어(입학·졸업), 남은 '함께'.
      5. 대칭 관계의 역방향 중복은 하나만."""
    by_id = {n["id"]: n for n in nodes}
    schools: dict[str, set[str]] = {}
    works: dict[str, set[str]] = {}
    for e in edges:
        s, t = by_id.get(e.get("source")), by_id.get(e.get("target"))
        if not s or not t or klass(s) != "person":
            continue
        if e.get("type") == "studied_at" and t.get("type") in ("School", "University"):
            schools.setdefault(s["id"], set()).add(t["id"])
        if e.get("type") == "worked_at" or t.get("type") in ("Company", "Business"):
            works.setdefault(s["id"], set()).add(t["id"])
    out: list[dict] = []
    issues: list[str] = []
    seen: set = set()
    targets: dict[tuple[str, str], set[str]] = {}
    for e in edges:
        s, t = by_id.get(e.get("source")), by_id.get(e.get("target"))
        kind = e.get("type")
        role = e.get("role")
        if s and t and kind in LIFE_EDGES:
            # 1. 출발·도착
            if not fits(kind, s, t):
                moved = RELAX.get((kind, klass(s), klass(t)))
                if moved == "experienced" and klass(s) == "event":
                    e["source"], e["target"], s, t = t["id"], s["id"], t, s
                if moved:
                    role = role or RELAX_ROLE.get((kind, klass(t)))
                    kind = moved
                else:
                    issues.append(f"{kind}: {s.get('name')}({klass(s)}) → {t.get('name')}({klass(t)}) — 표 밖")
            # 2. 만남의 실제
            if kind == "met":
                others = [n for n in (s, t) if n is not me]
                text = " ".join([str(e.get("description") or ""), *(str(n.get("description") or "") for n in others)])
                if _FRIEND.search(text):
                    kind = "friend_of"
                elif _COLLEAGUE.search(text):
                    kind = "worked_with"
            # 3. 함께 일함의 근거
            if (kind == "worked_with" and (e.get("confidence") or 1) < 1
                    and not works.get(s["id"]) and not works.get(t["id"])
                    and schools.get(s["id"], set()) & schools.get(t["id"], set())):
                kind = "schoolmate"
            # 4. 역할
            if kind == "experienced" and not role:
                role = deed_of(t) if (me is None or s is me) else "함께"
        # 5. 중복
        a, b = e.get("source"), e.get("target")
        key = (frozenset((a, b)), kind) if kind in _SYMMETRIC else (a, b, kind)
        if key in seen:
            continue
        seen.add(key)
        if kind in MAX_TARGETS:
            got = targets.setdefault((a, kind), set())
            got.add(b)
            if len(got) > MAX_TARGETS[kind]:
                issues.append(f"{kind}: {by_id.get(a, {}).get('name')} 의 도착이 {len(got)}개")
        e["type"] = kind
        if role:
            e["role"] = role
        elif "role" in e:
            del e["role"]
        out.append(e)
    edges[:] = out
    return issues


# 선 위에 적는 말. 역할(`role`)이 있으면 그것이 타입 이름을 이긴다 (한국사 그래프의
# LABEL_HEADS 규칙 — '주도'가 '참여'보다 정확하다). 없으면 양끝을 본다: 사건이 일어난
# 곳(at)은 도착이 학교면 '학교', 전공이면 '전공'이고, 사건 → 장소의 moved_to 는 '이주지'다.
# 그것도 없으면 타입의 일반 이름이다. 화면 코드(life.js edgeLabel)와 같은 규칙이다.
_AT_LABEL = {"School": "학교", "University": "학교", "Company": "회사", "Business": "회사",
             "Organization": "단체", "Community": "단체", "Project": "프로젝트", "Investment": "투자",
             "Occupation": "직업", "Skill": "기술", "Hobby": "취미", "Location": "장소", "BirthPlace": "장소",
             "Residence": "장소", "TravelLocation": "장소"}
_EVENT_TO = {"moved_to": "이주지", "visited": "방문지", "lived_in": "거주지", "born_in": "출생지"}


def edge_label(kind: str, src_type: str | None, dst_type: str | None, role: str | None = None) -> str:
    if role:
        return role
    if kind == "at":
        return _AT_LABEL.get(dst_type or "", "곳")
    if GRAPH_TYPE.get(src_type or "") in ("event", "period") and kind in _EVENT_TO:
        return _EVENT_TO[kind]
    return LIFE_EDGES[kind][0] if kind in LIFE_EDGES else EDGE_TYPE_KO.get(kind, kind)


# --- 날짜 -----------------------------------------------------------------
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_YEAR = re.compile(r"(\d{4})\s*년?")
_DECADE = re.compile(r"(\d{4})\s*년대\s*(초반|중반|후반)?")
_AGE = re.compile(r"(\d{1,2})\s*(?:대\s*(초반|중반|후반)?|살|세)")
_PART = {"초반": 1, "중반": 4, "후반": 7, None: 4}
# '고등학교 2학년'·'고2'·'중학교 1학년 때' — 학년은 해를 말한 것이다. 입학 해를
# 알면 거기서, 모르면 생년에서 센다 (초1 = 생년+7, 중1 = +13, 고1 = +16, 대1 = +19).
_SCHOOL = re.compile(r"(초등학교|국민학교|초등|중학교|고등학교|고교|대학교|대학원|대학)\s*(\d)\s*학년")
_SCHOOL_SHORT = re.compile(r"(?<![가-힣\d])(초|중|고|대)\s?(\d)(?![\d학년\-])")
_SCHOOL_LEVEL = {"초등학교": "초", "국민학교": "초", "초등": "초", "중학교": "중", "고등학교": "고",
                 "고교": "고", "대학교": "대", "대학": "대", "대학원": "원"}
_ENTRY_AGE = {"초": 7, "중": 13, "고": 16, "대": 19}
_ENTRY = re.compile(r"(초등학교|국민학교|중학교|고등학교|고교|대학교|대학원|대학)[^,.。]{0,14}?(입학|들어갔|들어감|진학|에 갔)")


def school_ref(text: str | None) -> tuple[str, int] | None:
    """'고등학교 2학년' → ('고', 2). 학년이 아니면 None."""
    s = str(text or "")
    m = _SCHOOL.search(s)
    if m:
        return _SCHOOL_LEVEL[m.group(1)], int(m.group(2))
    m = _SCHOOL_SHORT.search(s)
    if m:
        return m.group(1), int(m.group(2))
    return None


def school_entries(nodes: list[dict]) -> dict[str, int]:
    """이야기 안의 입학 사건에서 학교별 입학 해. '1997년 고등학교 입학' → {'고': 1997}."""
    out: dict[str, int] = {}
    for n in nodes:
        # 사람 노드는 안 본다 — 주인공 설명의 '1997년 고등학교 입학' 이 주인공의
        # 해(생년)와 짝지어져 입학 해가 생년이 됐다 (실측 2026-09-08).
        if n.get("year") is None or n.get("type") == "Person":
            continue
        m = _ENTRY.search(f"{n.get('name') or ''} {n.get('description') or ''}")
        if m:
            out.setdefault(_SCHOOL_LEVEL[m.group(1)], int(n["year"]))
            continue
        # 학교 노드 자체의 시작 해도 입학 해다 ('OO고등학교', start_date 1997).
        if n.get("type") in ("School", "University"):
            name = n.get("name") or ""
            level = next((_SCHOOL_LEVEL[k] for k in ("초등학교", "국민학교", "중학교", "고등학교", "고교", "대학원", "대학교", "대학")
                          if k in name), "대" if n["type"] == "University" else None)
            if level:
                out.setdefault(level, int(n["year"]))
    return out


def school_year(text: str | None, entries: dict[str, int]) -> int | None:
    """'고등학교 2학년' 을 입학 해에서 센다. 그 학교의 입학 해를 모르면 None."""
    ref = school_ref(text)
    if ref is None or ref[0] not in entries:
        return None
    return entries[ref[0]] + ref[1] - 1


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
    ref = school_ref(s)
    if ref is not None:
        if birth_year is None or ref[0] not in _ENTRY_AGE:
            return None, None, "age"
        y = birth_year + _ENTRY_AGE[ref[0]] + ref[1] - 1
        return y, y, "age"
    return None, None, ""


# --- 검증 -----------------------------------------------------------------
def _norm_label(s: str) -> str:
    """이름 대조용 — 띄어쓰기·가운뎃점·괄호를 걷는다 ('3·1 운동' = '3.1운동')."""
    return re.sub(r"[\s·.\-–—()（）]", "", str(s or "")).lower()


# 모델이 주인공에게 붙이는 남의 이름. 화면에서 그 사람은 '나'다.
SELF_NAMES = {"사용자", "본인", "화자", "주인공", "나 (사용자)", "사용자 (나)", "user", "me", "self"}


def validate(payload: dict, subject: dict | None = None) -> tuple[dict, list[str]]:
    """모델의 답을 화면이 믿고 그릴 수 있는 꼴로 다듬고, 고친 것을 적어 준다.

    형태는 스키마가 지켰다고 보고 **내용**만 본다:
      - 타입·관계 이름이 표에 없으면 버린다 (화면이 영어를 띄우게 된다).
      - 엣지의 양끝이 노드에 없으면 버린다.
      - 신뢰도는 0~1 로, 점수는 1~10 으로 자른다.
      - 노드의 날짜를 풀어 `year`·`end_year`·`precision` 을 단다. 연표 항목이
        연도를 안 적었으면 노드의 것을 쓴다. 나이만 있으면 생년으로 푼다.
      - 노드 이름·설명에 한글이 한 자도 없어도 손대지 않는다.

    `subject` 는 **더하는 이야기**일 때 옛 그래프의 주인공(id·생년)이다 — 새 답의
    첫 인물이 주인공이라는 짐작이 그때는 틀린다 (새로 나온 친척일 수 있다).
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
        # 이름에 한글이 없어도 메모하지 않는다 — 회사·서비스 이름(nullSpace)은
        # 본인이 그렇게 부르는 것이다 (2026-09-08 사용자: "알려줄 필요 없어").
        nodes.append(node)
    out["nodes"] = nodes
    by_id = {n["id"]: n for n in nodes}

    # 생년 — 나이로 적힌 날짜를 푸는 열쇠. 주인공(Person) 의 start_date 다.
    me = None
    if subject and subject.get("id"):
        me = by_id.get(subject["id"]) or next(
            (n for n in nodes if n["type"] == "Person" and n["name"].strip().lower() in SELF_NAMES | {"나"}), None)
    if me is None:
        me = next((n for n in nodes if n["type"] == "Person"), None)
    if me and me["name"].strip().lower() in SELF_NAMES:
        # 지시문이 화자를 '사용자'라 부르니 모델도 그 이름을 노드에 적는다.
        # 화면에서 그 사람은 '나'다 (2026-09-08 사용자: "'사용자'라고 하지 말고 '나' 라고 해줘").
        me["name"] = "나"
    birth = parse_when(me.get("start_date") if me else None)[0]
    if birth is None and subject and subject.get("birth_year") is not None:
        birth = int(subject["birth_year"])
    if birth is None and me:
        birth = birth_from_nodes(me, nodes, payload.get("edges") or [])
    out["subject"] = {"id": me["id"], "name": me["name"], "birth_year": birth} if me else None
    for n in nodes:
        y, y2, prec = parse_when(n.get("start_date"), birth)
        e = parse_when(n.get("end_date"), birth)[0]
        n["year"], n["end_year"], n["precision"] = y, (e if e is not None else (y2 if y2 != y else None)), prec
    # 학년은 해다. 이야기가 입학 해를 말했으면 거기서 센다 — 생년에서 센 어림
    # (parse_when) 보다 낫다. '1997년 고등학교 입학' + '고등학교 2학년' = 1998.
    entries = school_entries(nodes)
    for n in nodes:
        y = school_year(n.get("start_date"), entries)
        if y is not None and (n["year"] is None or n["precision"] == "age"):
            n["year"], n["precision"] = y, "year"
            if n.get("end_year") is None or n["end_year"] < y:
                n["end_year"] = None

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
            item["year"] = school_year(item.get("date_text"), entries)
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
    refine(out)
    out["notes"] = notes
    return out, notes


def _clip(v: Any, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return lo if lo > 0 else hi
    return max(lo, min(hi, x))


# --- 옛 그래프에 더하기 -------------------------------------------------------
# 사람은 삶을 한 번에 다 적지 않는다. 뒤에 더 적은 이야기는 **있는 그래프에
# 더한다** — 지우고 새로 만들지 않는다 (2026-09-08 사용자 결정). 모델에게는
# 있는 노드를 보여 같은 것은 같은 id 를 쓰게 했고(build_user), 여기서는 그래도
# 겹친 것을 이름으로 다시 잡는다. 겹친 노드는 옛 것을 남기고 빈 칸만 새 답으로
# 채운다. 관계·연표·역사 연결·분석은 없던 것만 붙인다.
_FILL_KEYS = ("description", "start_date", "end_date", "year", "end_year", "precision",
              "location", "importance_score", "emotional_impact")


def _fill(old: dict, new: dict) -> None:
    for k in _FILL_KEYS:
        if old.get(k) in (None, "", []) and new.get(k) not in (None, "", []):
            old[k] = new[k]


def merge(base: dict, add: dict) -> tuple[dict, dict]:
    """옛 그래프 `base` 에 새 답 `add` 를 더한다. (합친 것, 더한 수) 를 준다."""
    import copy

    out = copy.deepcopy(base)
    nodes: list[dict] = out.setdefault("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    by_key = {(n.get("type"), _norm_label(n.get("name"))): n["id"] for n in nodes}
    subject = out.get("subject") or {}
    subj_id = subject.get("id") if subject.get("id") in by_id else None
    stats = {"nodes": 0, "edges": 0, "timeline": 0, "connections": 0}

    remap: dict[str, str] = {}
    for n in add.get("nodes") or []:
        nid = n["id"]
        if nid in by_id:
            remap[nid] = nid
            _fill(by_id[nid], n)
            continue
        name = str(n.get("name") or "")
        if subj_id and n.get("type") == "Person" and (
                name.strip().lower() in SELF_NAMES or name == "나" or name == by_id[subj_id].get("name")):
            remap[nid] = subj_id
            _fill(by_id[subj_id], n)
            continue
        key = (n.get("type"), _norm_label(name))
        if key in by_key:
            remap[nid] = by_key[key]
            _fill(by_id[by_key[key]], n)
            continue
        node = dict(n)
        nodes.append(node)
        by_id[nid] = node
        by_key[key] = nid
        remap[nid] = nid
        stats["nodes"] += 1

    def _id(ref: Any) -> str | None:
        r = remap.get(ref, ref)
        return r if r in by_id else None

    edges: list[dict] = out.setdefault("edges", [])
    have = {(e.get("source"), e.get("target"), e.get("type")) for e in edges}
    for e in add.get("edges") or []:
        src, dst = _id(e.get("source")), _id(e.get("target"))
        if src is None or dst is None or src == dst:
            continue
        key = (src, dst, e.get("type"))
        if key in have:
            continue
        have.add(key)
        edges.append(dict(e, source=src, target=dst))
        stats["edges"] += 1

    timeline: list[dict] = out.setdefault("timeline", [])
    on_line = {t.get("event_id") for t in timeline}
    for t in add.get("timeline") or []:
        eid = _id(t.get("event_id"))
        if eid is None or eid in on_line:
            continue
        on_line.add(eid)
        timeline.append(dict(t, event_id=eid))
        stats["timeline"] += 1
    # 해 순으로 다시 세우고 앞뒤를 다시 잇는다 — 새 사건이 옛 사건 사이에 낄 수 있다.
    timeline.sort(key=lambda t: (t.get("year") is None, t.get("year") or 0))
    for i, t in enumerate(timeline):
        t["previous_event"] = timeline[i - 1]["event_id"] if i else None
        t["next_event"] = timeline[i + 1]["event_id"] if i + 1 < len(timeline) else None

    conns: list[dict] = out.setdefault("historical_connections", [])
    have_c = {(c.get("personal_event"), _norm_label(c.get("historical_event"))) for c in conns}
    for c in add.get("historical_connections") or []:
        pe = _id(c.get("personal_event"))
        key = (pe, _norm_label(c.get("historical_event")))
        if pe is None or key in have_c:
            continue
        have_c.add(key)
        conns.append(dict(c, personal_event=pe))
        stats["connections"] += 1

    def _extend(key: str, ident) -> None:
        items = out.setdefault(key, [])
        if not isinstance(items, list):
            items = out[key] = []
        seen = {ident(it) for it in items if isinstance(it, dict)}
        for it in add.get(key) or []:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            for f in ("event", "node", "node_id"):
                if f in it and it[f] in remap:
                    it[f] = remap[it[f]]
            k = ident(it)
            if k in seen:
                continue
            seen.add(k)
            items.append(it)

    _extend("turning_points", lambda it: _norm_label(it.get("event")))
    _extend("impact_analysis", lambda it: (_norm_label(it.get("event")), it.get("impact_type")))
    _extend("counterfactual_analysis", lambda it: _norm_label(it.get("event")))
    _extend("life_patterns", lambda it: _norm_label(it.get("pattern")))

    ranking = out.get("influence_ranking")
    if not isinstance(ranking, dict) or not isinstance(ranking.get("items"), list):
        ranking = out["influence_ranking"] = {"items": []}
    seen_r = {_norm_label(it.get("node")) for it in ranking["items"] if isinstance(it, dict)}
    for it in ((add.get("influence_ranking") or {}).get("items") or []):
        if not isinstance(it, dict):
            continue
        it = dict(it, node=remap.get(it.get("node"), it.get("node")))
        if _norm_label(it.get("node")) in seen_r:
            continue
        seen_r.add(_norm_label(it.get("node")))
        ranking["items"].append(it)

    fam = out.get("family_analysis")
    if not isinstance(fam, dict):
        fam = out["family_analysis"] = {"members": []}
    fam_add = add.get("family_analysis") or {}
    for k in ("origin", "historical_flow", "values"):
        if not fam.get(k) and fam_add.get(k):
            fam[k] = fam_add[k]
    members = fam.setdefault("members", [])
    seen_m = {m.get("node_id") for m in members if isinstance(m, dict)}
    for m in fam_add.get("members") or []:
        if not isinstance(m, dict):
            continue
        m = dict(m, node_id=remap.get(m.get("node_id"), m.get("node_id")))
        if m["node_id"] in seen_m:
            continue
        seen_m.add(m["node_id"])
        members.append(m)

    # 물음은 지금 빠진 것에 대한 것이라 새 답의 것을 쓴다.
    if add.get("follow_up_questions"):
        out["follow_up_questions"] = list(add["follow_up_questions"])[:5]
    if subject and subject.get("birth_year") is None and (add.get("subject") or {}).get("birth_year") is not None:
        out["subject"] = dict(subject, birth_year=add["subject"]["birth_year"])
    if add.get("_model"):
        out["_model"] = add["_model"]
    refine(out)   # 옛 그래프에 비어 있던 해·연결도 이 김에 채운다
    out["notes"] = list(add.get("notes") or [])
    return out, stats


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


