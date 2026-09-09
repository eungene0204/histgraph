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
# 화면에 세우지 않는 관계. `before`('다음')·`after`('이전')는 사건과 사건의 **차례**만
# 말하는데 그 차례는 연표가 이미 연도로 그린다 (2026-09-08 사용자, '성일초등학교 입학'
# 상세의 `다음 성내초등학교 전학` 을 보고: "다음 이라는 메뉴는 뭐야? 별 정보값이 없는데
# 그냥 삭제해"). 모델이 답하는 것까지 막지는 않는다 — 주인공 → 자기 사건을 `after` 로
# 답하기도 하고 그것은 참여(experienced)라 뜻이 있다. 그래서 버리는 자리는 `tidy_edges`
# 의 RELAX **뒤**, 옮길 데 없이 사건 → 사건으로 남은 것뿐이다. `during`·`overlapped` 는
# 차례가 아니라 포함·겹침이라 남는다.
SEQUENCE_ONLY = frozenset({"before", "after"})
# 사건 관계 가운데 **원인 → 결과**로 읽는 것. 화면이 개인 연표에서 인과 선으로 긋는다.
CAUSAL_EDGES = frozenset({"caused", "triggered", "led_to", "resulted_in"})
IMPACT_KO = {"direct": "직접", "indirect": "간접", "possible": "가능성"}
# 인생 단계 — 지시문(life_prompt.md)의 목록에 '군복무'를 더했다 (2026-09-08 사용자:
# "공익근무는 군복무 기간이야. 훈련소, 공익근무 역시 군복무로 인식할 수 있게 해줘").
# 이 목록은 모델에게 주는 스키마의 enum 이기도 하다 — 여기 없으면 모델이 못 고른다.
LIFE_STAGES = ["출생", "어린 시절", "초등학교", "중학교", "고등학교", "대학", "군복무",
               "사회생활", "창업", "가족 형성", "현재"]
# 단계에는 **차례**가 있다. 출생부터 군복무까지는 뒤로 돌아가지 않는다 — 스무 살에
# '초등학교'인 삶은 없다 (2026-09-09 실측: 공익 시절에 만난 사람의 연표 항목이
# '초등학교'로 서 있었다. 모델이 사람 노드에 단계를 아무렇게나 적은 것이다).
# 창업·가족 형성·현재는 오갈 수 있으므로 이 자에서 뺀다.
STAGE_ORDER = {s: i for i, s in enumerate(LIFE_STAGES)}
ONE_WAY_STAGES = frozenset(LIFE_STAGES[:LIFE_STAGES.index("군복무") + 1])
# 군복무로 읽는 말. 현역만이 아니다 — 공익근무요원·사회복무요원·상근예비역·방위병·
# 의무경찰도 병역이고, 훈련소 입소부터 소집해제까지가 그 기간이다. 모델이 '사회생활'
# 이라 적어 와도 이 표가 이긴다 (사람이 정한 것이지 모델이 고를 것이 아니다).
MILITARY = re.compile(
    r"군복무|군 복무|병역|입대|입영|훈련소|신병교육|\d+\s*사단|공익\s*(?:근무|요원|생활|복무)|사회복무요원|"
    r"상근예비역|방위병|의무경찰|의경대|카투사|해병대|현역|전역|소집해제|(?<![가-힣])제대(?!로)")
# 그 단계를 **끝내는** 사건 (화면이 띠를 여기서 닫는다 — web/src/lib/life.js STAGE_END).
STAGE_ENDS_ON = re.compile(r"전역|소집해제|(?<![가-힣])제대(?!로)|만기")
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
        # 물음만 세우면 화면에 물음표만 선다 (2026-09-09 지적: "질문만 있고 답변이
        # 없어"). `answer` 는 그 물음에 대한 **문단**이고, `possibilities` 는 그
        # 아래에 갈린 길을 짧게 나열한 것이다 — 둘은 서로를 대신하지 못한다.
        "counterfactual_analysis": {"type": "array", "items": {
            "type": "object",
            "properties": {"event": _STR, "question": _STR, "answer": _STR, "possibilities": _STRS},
            "required": ["event", "question", "answer", "possibilities"],
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
    """이미 있는 그래프를 모델에게 보일 만큼만 — 노드의 id·타입·이름·구간과 주인공.

    **끝 해도 보인다.** 이야기는 시점이 아니라 구간으로도 때를 말한다 — '공익생활을
    하던 시절'은 2002년 한 해가 아니라 2002~2004 다 (2026-09-09 사용자). 해 하나만
    보이면 모델이 그 구간 안의 일을 그 한 해로 몰아 적는다.
    """
    nodes = [{"id": n["id"], "type": n.get("type"), "name": n.get("name"),
              "year": n.get("year"), "end_year": n.get("end_year")}
             for n in base.get("nodes") or [] if isinstance(n, dict) and n.get("id") and n.get("name")]
    return {"subject": base.get("subject") or None, "nodes": nodes}


def known_ids(base: dict | None) -> set[str]:
    """옛 그래프의 노드 id — 새 답이 관계의 끝으로 부를 수 있는 이름 (validate `known`)."""
    return {str(n["id"]) for n in (base or {}).get("nodes") or []
            if isinstance(n, dict) and n.get("id")}


def _span_text(n: dict) -> str:
    """모델에게 보이는 노드의 때 — ' · 2002' 또는 ' · 2002~2004'."""
    y, e = n.get("year"), n.get("end_year")
    if y is None:
        return ""
    return f" · {y}~{e}" if e is not None and e != y else f" · {y}"


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
        # 목록은 **표기**를 맞추라고 주는 것이지 고르라고 주는 것이 아니다. 2026-09-08
        # 지적: 모델이 개인 사건마다 같은 해의 큰 사건을 목록에서 집어 "간접 영향을
        # 미쳤을 수 있음"으로 이었다 — 공익요원 시작에 제2연평해전, 대학 졸업에 세월호.
        # 이야기가 말하지 않은 역사는 잇지 않는다. 코드의 관문(gate_connections)이
        # 같은 규칙으로 한 번 더 거른다.
        known = ("\n\n역사 연결(historical_connections)은 **이야기가 직접 말한** 역사 사건만 적는다 — "
                 "본인이 겪었다거나 그 때문에 무엇이 바뀌었다고 말한 것. 같은 해에 일어났다는 이유로 "
                 "잇지 않고, '영향을 미쳤을 수 있다'는 짐작으로 잇지 않는다. 이야기에 그런 사건이 없으면 "
                 "빈 배열로 둔다. 적을 때는 한국사 그래프의 이름을 쓴다 — 이 무렵의 사건 이름은 이렇다"
                 "(표기를 맞추라고 보이는 것이지 여기서 고르라는 것이 아니다):\n"
                 f"{names}")
    # **더하는 이야기**: 이미 있는 그래프의 노드를 보여 주고 같은 것은 그 id 를
    # 쓰게 한다 — 그래야 `merge` 가 새 답을 옛 그래프에 잇는다 (2026-09-08 사용자:
    # "나중에 추가해서 입력 하면 원래 있던 역사에 추가 시켜줘. 기존것을 지우고
    # 새로 만들지 말고"). 목록에 있는 것을 다시 만들지 않게도 한다.
    if existing and existing.get("nodes"):
        subj = existing.get("subject") or {}
        rows = "\n".join(f"- {n['id']} · {NODE_TYPE_KO.get(n['type'], n['type'])} · {n['name']}"
                         f"{_span_text(n)}" for n in existing["nodes"])
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
            # 정정 — 나중에 한 말이 앞서 한 말을 이긴다 (life.correct 머리글).
            " 다만 이야기가 앞서 말한 것을 **고치는** 말이면('잘못 말했어'·'아니라 …야')"
            " 그 노드를 아래와 **똑같은 이름으로** 다시 적고 고친 날짜를 적는다 —"
            " 이름을 바꾸면 같은 일이 두 개가 된다."
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
        "같은 식으로 앞뒤 사건의 해에서 센다. **나이와 시기도 셈의 근거다** — "
        "'만20살 때'는 생년에서 세고, '공익 시절'·'대학 다닐 때'처럼 이미 있는 시기를 가리키면 "
        "그 노드의 구간(위 목록의 '2002~2004') 안에서 센다. 셈한 해는 start_date 에 적고 confidence 를 "
        "0.7~0.9 로 낮춘다. 셈할 근거가 아무것도 없을 때만 null 로 둔다. "
        # 만난 사람은 주인공과, 만난 곳과 잇는다 (2026-09-08 사용자: "고등학교에서
        # 만났다고 하면 내가 입학했다고 말한 고등학교와 연결 시켜줘야 하는거야").
        "만난 사람은 주인공과 met 관계로 잇고(친구라고 했으면 friend_of, 함께 일한 사람이면 worked_with), "
        "어디서 만났는지(학교·회사·모임)를 말했으면 "
        "그 사람을 그 학교·회사 노드와도 잇는다(studied_at·worked_at·member_of) — 새 노드를 "
        "만들지 말고 이야기가 말한 그 학교·회사 노드를 쓴다. 만난 일은 timeline 에도 세운다. "
        # 함께한 사람 (2026-09-08 사용자: "친구 김일권과 같이 갔다고 분명 말했는데
        # '함께 person_1' 이라고 말하고 있어"). 모델이 participants 에 주인공만 적었다.
        "어떤 일을 **누구와 함께** 했다고 말하면 그 사람을 사건 노드의 participants 에 "
        "그 사람 **노드의 id** 로 적는다 — 주인공만 적지 말고 이야기가 부른 사람을 다 적는다. "
        "주인공의 생년월일은 주인공 노드의 start_date 에 적는다 — 이야기가 말한 만큼만이다. "
        # 남의 생년은 짐작하지 않는다 (2026-09-08 사용자: "인물들의 출생연도 나이는
        # 사용자가 입력하지 않은 이상 추측해서 명시 하지마"). 실측: 친구 노드에
        # 주인공과 같은 생일이 붙어 있었다.
        "주인공 말고 다른 사람의 생년월일·나이는 **이야기가 그 사람에 대해 말했을 때만** 적는다. "
        "말하지 않았으면 그 사람의 start_date 는 null 이다 — 또래일 것 같다고 적지 않는다. "
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


# --- '만약 없었다면' 의 답 --------------------------------------------------------
# 2026-09-09 지적: "질문만 있고 답변이 없어". 화면은 물음 아래에 갈린 길
# (`possibilities`)만 세우고 있었는데, 그것은 '한국에서 대학을 계속 다녔을
# 가능성' 같은 구절이라 **답으로 읽히지 않는다.** 그래서 물음마다 문단 하나
# (`answer`)를 받아 화면이 물음을 누르면 펴 보이게 했다.
#
# 답은 **이야기가 말한 것에서만 온다.** 없는 사실을 지어내면 그 사람의 삶에
# 남의 이야기가 섞인다 — 설명을 못 채울 때 비우는 규칙(`redescribe`)과 같다.
# 우리 말이 아닌 답은 버린다 (화면에 영어를 세우지 않는다, CLAUDE.md §1). 버린
# 자리는 화면이 '아직 답이 적히지 않았습니다' 로 그리고, 다시 물으면 채워진다.

# 한글이 한 자라도 있는가 — 화면에 낼 수 있는 말인지를 가른다 (CLAUDE.md §1).
_HANGUL = re.compile(r"[가-힣]")
# 한자·가나. 모델이 한국어 문장 한가운데에 한 자씩 흘린다 (실측: '더 오래続했을').
# 이름은 이야기에서 오므로 한글이거나 로마자다 — 여기 걸리는 것은 흘린 것이다.
_NOT_KO = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def korean_line(s: Any) -> str:
    """화면에 세울 수 있는 한국어 한 줄이면 그대로, 아니면 빈 글."""
    text = str(s or "").strip()
    return text if text and _HANGUL.search(text) and not _NOT_KO.search(text) else ""


# 이미 만든 그래프의 물음에만 답을 채울 때 쓰는 작은 스키마. 본 스키마
# (SCHEMA)를 다시 물으면 모델이 그래프를 통째로 새로 써서 노드가 흔들린다.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": _STR, "answer": _STR},
        "required": ["question", "answer"],
    }}},
    "required": ["answers"],
}

ANSWER_SYSTEM = """너는 한 사람이 적은 인생 이야기를 읽고 '만약 그 일이 없었다면?' 에 답한다.

규칙:
- 한국어로만 적는다. 한자·가나·영어 문장을 섞지 않는다.
- 물음마다 두세 문장의 문단 하나를 적는다. 목록으로 적지 않는다.
- **이야기에 나오는 이름을 부른다.** 그 일이 없었다면 이어지지 못했을 다음 일
  (학교·회사·만난 사람·옮겨 간 곳)을 이름으로 대며 적는다.
- 이야기가 말하지 않은 사실은 지어내지 않는다.
- 단정하지 않는다. '~였을 것이다', '~했을 수 있다' 로 적는다.
- **물음을 되풀이하지 않는다.** '미국에 가지 않았다면 미국에 가지 않았을 것이다'
  같은 답은 답이 아니다. 무엇이 달라졌을지를 적는다.
- 답을 모르겠으면 그 물음은 빼고 답한 것만 돌려준다.

JSON 만 돌려준다: {"answers": [{"question": "...", "answer": "..."}]}"""


def _counterfactual(item: dict) -> dict:
    """'만약 없었다면' 한 줄을 다듬는다 — 한국어가 아닌 답은 화면에 세우지 않는다."""
    out = dict(item)
    answer = korean_line(out.get("answer"))
    if answer:
        out["answer"] = answer
    else:
        out.pop("answer", None)
    return out


def unanswered(payload: dict) -> list[dict]:
    """답이 없는 '만약 없었다면' 줄들."""
    return [c for c in payload.get("counterfactual_analysis") or []
            if isinstance(c, dict) and c.get("question") and not str(c.get("answer") or "").strip()]


def answer_counterfactuals(payload: dict, backend, text: str | None = None) -> int:
    """답이 빈 물음만 모델에 물어 채운다. 채운 수를 돌려준다.

    옛 그래프를 위한 길이다 — 지시문이 `answer` 를 요구하기 전에 만든 문서에는
    물음만 있다. 그래프는 건드리지 않는다."""
    todo = unanswered(payload)
    if not todo:
        return 0
    by_id = {n["id"]: n for n in payload.get("nodes") or []
             if isinstance(n, dict) and n.get("id")}
    # 그 사건 뒤에 이어진 일들. 답이 '무엇이 달라졌을지' 를 말하려면 무엇이
    # 이어졌는지를 알아야 한다 — 그것이 없으면 모델은 물음을 되풀이한다.
    after: dict[str, list[str]] = {}
    for e in payload.get("edges") or []:
        if not isinstance(e, dict) or e.get("type") not in CAUSAL_EDGES:
            continue
        name = (by_id.get(e.get("target")) or {}).get("name")
        if name:
            after.setdefault(e.get("source"), []).append(name)
    lines = []
    for c in todo:
        ev = by_id.get(c.get("event"))
        about = ev.get("name") if ev else str(c.get("event") or "")
        desc = (ev or {}).get("description") or ""
        nxt = after.get(c.get("event")) or []
        lines.append(f"- 사건: {about}\n  물음: {c['question']}"
                     + (f"\n  사건 설명: {desc}" if desc else "")
                     + (f"\n  그 뒤에 이어진 일: {', '.join(nxt[:8])}" if nxt else ""))
    user = "\n".join(filter(None, [
        "이야기:", (text or "").strip() or "(원문이 없다 — 아래 사건 설명만 보고 답한다)",
        "", "물음:", *lines,
    ]))
    got = backend.complete_json(ANSWER_SYSTEM, user, ANSWER_SCHEMA, max_tokens=4000)
    if not isinstance(got, dict):
        return 0
    said = {}
    for a in got.get("answers") or []:
        if isinstance(a, dict) and a.get("question"):
            said[_norm_label(a["question"])] = str(a.get("answer") or "").strip()
    filled = 0
    for c in todo:
        answer = korean_line(said.get(_norm_label(c["question"])))
        if answer:
            c["answer"] = answer
            filled += 1
    return filled


# --- 다듬기: 앞뒤에서 셈하고, 만난 곳에 잇는다 -----------------------------------
# 모델이 빠뜨린 것을 이야기 안의 다른 노드에서 채운다. 검증 끝과 더하기 끝에
# 한 번씩 돈다 (옛 그래프도 다음 더하기 때 같이 고쳐진다).
#   0. 인물의 생몰년: 원문을 아는 자리에서는 근거 없는 것을 비운다 (gate_dates).
#   1. 생년: 주인공 노드의 start_date 가 비었으면 '출생' 노드나 설명에서.
#   2. 해: 학년('고등학교 2학년')은 입학 해에서, 없으면 생년에서. 사람 노드는
#      설명의 '…1학년 때 만난' 도 본다 — 그 사람이 내 삶에 들어온 해다.
#   3. 연표: 해가 빈 항목은 날짜 글 → 나이 → 노드의 해.
#   4. 잇기: 사람의 설명이 이야기 속 학교·회사 이름을 부르면 그 노드에 잇고
#      (studied_at·worked_at), 주인공과 아무 관계가 없는 '만난' 사람은 met 으로 잇는다.
_BIRTH_DESC = re.compile(r"(\d{4})\s*년[^.。]{0,25}?(태어|출생)")
_BIRTH_DESC_FULL = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일[^.。]{0,25}?(태어|출생)")
_MET_WORDS = re.compile(r"만난|만났|만나|친구|동료|선배|후배|사귀|알게")
_BIRTH_NODE = re.compile(r"^(출생|탄생|태어남)$")


# --- 인물의 생년월일은 원문이 말한 것만 -------------------------------------------
# 2026-09-08 사용자: "인물들의 출생연도 나이는 사용자가 입력하지 않은 이상 추측해서
# 명시 하지마. 모르면 그냥 아예 명시를 하지마." 실측: 모델이 친구 노드에 주인공과
# 똑같은 생일(1982-01-01, confidence 0.9)을 달아 놓았고, 주인공의 생일도 이야기는
# 해만 말했는데 1월 1일이 붙어 있었다. 화면은 그것을 그 사람의 생년으로 읽는다.
#
# 그래서 인물의 날짜는 **원문에 근거가 있어야 남는다** (인과의 fact_check 와 같은 관문).
#   - 주인공: 해는 그대로 둔다 — 연표의 나이·학년·시기가 전부 여기서 선다. 달·날은
#     이야기가 말했을 때만 적는다 (안 말했으면 해까지만).
#   - 다른 사람: 그 사람 이름을 부르는 문장이 그 해를 말할 때만 남긴다. 아니면 비운다.
# 원문이 없는 자리에서는 재지 않는다 — 없는 근거로 지우지 않는다.
PERSON_TYPES = {"Person", "FamilyMember", "Ancestor", "Relationship"}
_FULL_DATE = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")
_YEAR_MONTH = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*월")


def _sentences_about(text: str, name: str | None) -> list[str]:
    """이름을 부르는 문장과 **그 바로 앞 문장** (같은 문단 안). 앞 문장이 먼저가 아니라
    이름 문장이 먼저다 — 이름 문장에 근거가 있으면 그것을 쓴다.

    한 문단은 한 사람을 두 문장으로 말하곤 한다 — "우리 엄마는 1953년 7월 9일에
    태어나셨어. 성함은 백경순이야." (2026-09-08 실측: 이름 문장만 보니 날짜가 없어
    사용자가 말한 생일을 지웠다). 앞 문장은 **이름 문장에 해가 하나도 없고 앞 문장이
    가족 호칭으로 그 사람을 부를 때만** 본다 — 아니면 '나는 1982년에 태어났다. …
    김일권을 만났다' 의 1982 가 김일권의 생년이 된다. 문단(줄) 을 넘어서는 보지 않는다.
    """
    if not name:
        return []
    out: list[str] = []
    for para in text.split("\n"):
        sents = [s for s in re.split(r"[.!?。]", para) if s.strip()]
        for i, s in enumerate(sents):
            if name in s:
                out.append(s)
                if i > 0 and not _YEAR.search(s) and _KIN.search(sents[i - 1]):
                    out.append(sents[i - 1])
    return out


def stated_date(text: str | None, name: str | None, date: str | None, *, whole: bool = False) -> str | None:
    """원문이 말한 만큼의 날짜. 그 해를 말한 적이 없으면 None.

    `whole` 은 주인공이다 — 이야기가 자기 이름을 부르지 않으므로 글 전체에서 찾는다.
    """
    if not date or not text:
        return date
    year = parse_when(date)[0]
    if year is None:
        return None
    where = [text] if whole else _sentences_about(text, name)
    for s in where:
        for m in _FULL_DATE.finditer(s):
            if int(m.group(1)) == year:
                return f"{year:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        for m in _YEAR_MONTH.finditer(s):
            if int(m.group(1)) == year:
                return f"{year:04d}-{int(m.group(2)):02d}"
        if re.search(rf"(?<!\d){year}(?!\d)", s):
            return str(year)
    return None


def gate_dates(nodes: list[dict], me: dict | None, text: str | None,
               timeline: list[dict] | None = None) -> list[str]:
    """인물·단체 노드의 날짜를 원문에 대 보고, 근거 없는 것을 비운다.

    **단체도 사람과 같은 규칙이다** (2026-09-09). 모델이 지어낸 창립 연도는 그 노드
    하나로 끝나지 않는다 — 이야기가 그 이름을 부르면 다른 노드가 그 해를 빌려 간다
    (`time_anchors`). 실측(모델이 a-club 을 1995년으로 지어낸 답): 그 1995 가 같은
    문장의 '최근호'에게 옮아 만난 해가 됐다. 닻이 되려면 근거가 있어야 한다.

    비운 사람은 **연표에서도 내린다** (준 `timeline` 을 그 자리에서 고친다) — 연표
    항목은 그 해의 나이와 단계를 들고 있어서, 남겨 두면 화면이 그 사람 이름 아래에
    '0세 · 출생'을 적는다 (2026-09-08 실측: 친구 하나가 주인공과 같은 해에 태어난
    것으로 연표에 서 있었다).
    """
    notes: list[str] = []
    if not text:
        return notes
    dropped: set[str] = set()
    for n in nodes:
        if n.get("type") not in PERSON_TYPES | ORG_TYPES:
            continue
        mine = me is not None and n is me
        for key in ("start_date", "end_date"):
            was = n.get(key)
            if not was:
                continue
            now = stated_date(text, n.get("name"), was, whole=mine)
            if mine and now is None:
                # 주인공의 해는 남긴다 (연표가 여기서 선다) — 지어낸 달·날만 자른다.
                y = parse_when(was)[0]
                now = str(y) if y is not None else None
            if now == was:
                continue
            n[key] = now
            if key == "start_date":
                y, y2, prec = parse_when(now)
                n["year"], n["precision"] = y, prec
                if now is None:
                    n["end_year"] = None
                    dropped.add(str(n.get("id")))
            notes.append(f"이야기가 말하지 않은 날짜를 뺐다: {n.get('name')} {was}"
                         + (f" → {now}" if now else ""))
    if timeline is not None and dropped:
        keep = [t for t in timeline if not (isinstance(t, dict) and t.get("event_id") in dropped)]
        if len(keep) != len(timeline):
            notes.append(f"생년이 없어진 사람을 연표에서 내렸다: {len(timeline) - len(keep)}건")
            timeline[:] = keep
    return notes


_WHEN_TYPES = ("Time", "PersonalEvent", "LifeStage")


def birth_date_from_nodes(me: dict, nodes: list[dict], edges: list[dict]) -> str | None:
    """주인공의 생일 — '출생' 사건이 든 날짜, 없으면 설명의 '1982년 2월 27일 … 태어난'.

    **출생 사건의 날짜가 주인공 노드의 날짜를 이긴다.** 모델은 해만 아는 사람에게
    1월 1일을 적어 두는데(2026-09-08 사용자: "2월 27일에 태어 났다고 했는데, 왜
    헷갈리게 '1982-01-01 · 0세 · 출생' 이라고 써있지"), 화면은 사람 노드의 날짜를
    그 사람의 생일로 읽는다. 이야기가 날짜를 말했으면 그 말이 '출생' 노드에 서 있다.

    가장 자세한 것을 고른다 (날짜 > 달 > 해). 주인공 노드가 든 해와 다른 해는
    버린다 — 다른 사람의 출생이거나 잘못 이어진 것이다."""
    by_id = {n["id"]: n for n in nodes}
    said: list[str] = []

    def take(when: object) -> None:
        if isinstance(when, str) and parse_when(when)[0] is not None:
            said.append(when.strip())

    for e in edges:
        if not isinstance(e, dict) or e.get("source") != me.get("id"):
            continue
        t = by_id.get(e.get("target"))
        if not t or t.get("type") not in _WHEN_TYPES:
            continue
        # born_in 은 다듬기 전의 이름이고, 다듬은 뒤에는 experienced 에 역할이 '출생'이다.
        if e.get("type") == "born_in" or _BIRTH_NODE.match(str(e.get("role") or "").strip()) \
                or _BIRTH_NODE.match(str(t.get("name") or "").strip()):
            take(t.get("start_date"))
    for n in nodes:
        if n.get("type") in _WHEN_TYPES and _BIRTH_NODE.match(str(n.get("name") or "").strip()):
            take(n.get("start_date"))
    desc = str(me.get("description") or "")
    m = _BIRTH_DESC_FULL.search(desc)
    if m:
        take(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
    else:
        m = _BIRTH_DESC.search(desc)
        if m:
            take(m.group(1))
    if not said:
        return None
    year = parse_when(me.get("start_date"))[0]
    fit = [w for w in said if year is None or parse_when(w)[0] == year]
    return max(fit, key=len) if fit else None


def birth_from_nodes(me: dict, nodes: list[dict], edges: list[dict]) -> int | None:
    """주인공의 생년 — 노드 자신에 없으면 '출생' 노드나 설명에서."""
    return parse_when(birth_date_from_nodes(me, nodes, edges))[0]


def refine(payload: dict, text: str | None = None, *, added: str | None = None) -> dict:
    """모델 없이 규칙만으로 그래프를 다듬는다.

    `text` 는 이 그래프를 만든 이야기 **전부**다 — 인물의 날짜와 역사 연결의 관문이
    여기에 대 본다. `added` 는 **이번에 더한 토막**이다 — 이야기 안의 근거(함께한
    사람·가족 호칭·이름이 불린 사람)를 읽는 데만 쓰고, 관문은 걸지 않는다 (토막만
    보고 옛 이야기가 부른 역사 연결을 버리면 안 된다: `merge` 머리글).
    """
    nodes: list[dict] = payload.get("nodes") or []
    edges: list[dict] = payload.setdefault("edges", [])
    if not nodes:
        return payload
    by_id = {n["id"]: n for n in nodes}
    subject = payload.get("subject") or {}
    me = by_id.get(subject.get("id"))
    # 이야기 — 아래의 여러 규칙이 근거로 든다. 원문(text)이 없으면 그래프에 실린
    # 이야기를 잇고, 이번에 더한 토막은 뒤에 붙인다.
    story = text if text else "\n".join(
        str(r.get("text") or "") for r in (payload.get("stories") or []) if isinstance(r, dict))
    if added and added.strip() and added.strip() not in story:
        story = "\n".join(x for x in (story, added.strip()) if x)
    # 0. 인물의 생몰년 — 원문을 아는 자리에서는 여기서도 잰다 (옛 그래프가 들고 있는
    #    지어낸 생년은 이 길로 빠진다. 원문을 모르면 그대로 둔다.)
    gate_dates(nodes, me, text, payload.get("timeline"))

    # 1. 생년 — 그리고 생일. '출생' 사건이 든 날짜가 주인공 노드의 날짜를 이긴다
    #    (birth_date_from_nodes: 모델은 해만 알면 1월 1일을 적는다).
    if me is not None:
        said = birth_date_from_nodes(me, nodes, edges)
        if said and said != me.get("start_date") and len(said) >= len(str(me.get("start_date") or "")):
            me["start_date"] = said
            me["year"], _, me["precision"] = parse_when(said)
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
    # 이미 해를 아는 것들의 이름 — 이야기가 '신구대학 시절'이라 부르면 그 해를 빌린다.
    anchors = time_anchors(nodes, me)
    for n in nodes:
        if n.get("year") is not None and n.get("precision") != "age":
            continue
        y = school_year(n.get("start_date"), entries)
        prec = "year"
        if y is None and n.get("type") == "Person" and n is not me:
            y = school_year(n.get("description"), entries)
        # 그 사람이 내 삶에 들어온 해는 **이야기가 그 사람을 부르는 문장**에 있다.
        # '만20살때 여자친구를 만났고, 이름은 정혜림 이었다' 의 해는 생년+20 이다
        # (2026-09-09 사용자: "'만20세', '공익생활'이라고 언급 했으면 … 충분히 유추").
        if y is None and n is not me and n.get("type") in PERSON_TYPES | ORG_TYPES:
            y, prec = year_from_story(story, n.get("name"), birth, entries, anchors)
        if y is None and birth is not None:
            # 이름을 text 로 두지 않는다 — 이 함수의 `text` 는 **원문**이고,
            # 여기서 가리면 뒤의 관문(gate_connections)이 원문 대신 노드 설명을 읽는다.
            for said_in in (n.get("start_date"), n.get("description") if n.get("type") == "Person" and n is not me else None):
                if school_ref(said_in) is not None:
                    y, prec = parse_when(said_in, birth)[0], "age"
                    break
        if y is not None:
            n["year"], n["precision"] = y, prec

    # 3. 잇기 — 사람을 만난 곳에, 만난 사람을 나에게
    have = {(e.get("source"), e.get("target")) for e in edges}
    def linked(a: str, b: str) -> bool:
        return (a, b) in have or (b, a) in have
    places = [n for n in nodes if n.get("type") in ("School", "University", "Company", "Organization", "Community")
              and len(str(n.get("name") or "")) >= 2]
    for n in nodes:
        if n.get("type") != "Person" or n is me:
            continue
        about = f"{n.get('name') or ''} {n.get('description') or ''}"
        for pl in places:
            if pl["id"] != n["id"] and pl["name"] in about and not linked(n["id"], pl["id"]):
                kind = "studied_at" if pl["type"] in ("School", "University") else \
                       "worked_at" if pl["type"] == "Company" else "member_of"
                edges.append({"source": n["id"], "target": pl["id"], "type": kind,
                              "description": None, "confidence": 0.8})
                have.add((n["id"], pl["id"]))
        if me is not None and not linked(me["id"], n["id"]) and _MET_WORDS.search(about):
            edges.append({"source": me["id"], "target": n["id"], "type": "met",
                          "description": n.get("description"), "confidence": 0.8})
            have.add((me["id"], n["id"]))

    # 3-2. 함께한 사람 — 이야기가 한 문장에서 같이 부른 사람을 participants 에 넣고,
    #      그렇게 모인 participants 를 사람 노드로 풀어 사건에 잇는다.
    participants_from_story(nodes, story)
    link_participants(nodes, edges, me)

    # 3-3. **만난 일도 만든 일도 사건이다.** 사람·단체만 세우고 끝내면 연표에
    #      아무것도 서지 않는다.
    if meet_events(payload, nodes, edges, me, story, entries) \
            + founding_events(payload, nodes, edges, me, story):
        by_id = {n["id"]: n for n in nodes}

    # 4. 연표
    timeline: list[dict] = payload.get("timeline") or []
    # 주인공은 연표의 항목이 아니라 연표 그 자체다. 모델이 자기 노드를 0세 자리에
    # 세워 두면 '출생' 사건 옆에 같은 것이 하나 더 서고, 그 줄이 주인공 노드의 날짜를
    # 생일로 읽어 준다 (2026-09-08 사용자).
    if me is not None:
        timeline = [t for t in timeline if t.get("event_id") != me.get("id")]
    payload["timeline"] = timeline
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
        # 달까지 아는 날짜는 항목이 적어 온 해를 이긴다 — 모델은 항목의 year 를
        # 나이나 앞뒤 항목에서 어림해 적는다 (2026-09-08 지적: 1998년 4월 24일
        # 메탈리카 공연이 1997 로 적혀 와 연표의 1997 칸에 '4월'로 섰다).
        # 어림한 나이도 함께 버리고 생년에서 다시 센다 (life.js normalize 와 같다).
        fine = month_year(node.get("start_date")) if node is not None else None
        if fine is not None and fine != t.get("year"):
            t["year"], t["age"] = fine, None
        if t.get("age") is None and t.get("year") is not None and birth is not None:
            t["age"] = int(t["year"]) - birth
        if node is not None and node.get("year") is None and t.get("year") is not None:
            node["year"], node["precision"] = t["year"], "year"
    # 군복무 — 훈련소 입소부터 소집해제까지는 병역이지 사회생활이 아니다
    # (2026-09-08 사용자). 모델이 '사회생활'로 적어 와도 이름이 말하면 여기서 고친다.
    for t in timeline:
        node = by_id.get(t.get("event_id"))
        if node is not None and klass(node) in ("event", "period") \
                and MILITARY.search(f"{node.get('name') or ''} {node.get('description') or ''}"):
            t["life_stage"] = "군복무"
    timeline.sort(key=lambda t: (t.get("year") is None, t.get("year") or 0))
    # 단계는 뒤로 가지 않는다 (ONE_WAY_STAGES) — 스무 살에 '초등학교'인 삶은 없다.
    # 창업·가족 형성·현재는 오갈 수 있으므로 되돌리지 않는다.
    cur: str | None = None
    for t in timeline:
        stage = t.get("life_stage") if t.get("life_stage") in STAGE_ORDER else None
        if stage is None:
            continue
        if cur is not None and stage in ONE_WAY_STAGES and STAGE_ORDER[stage] < STAGE_ORDER[cur]:
            t["life_stage"] = cur
        else:
            cur = stage
    # 단계를 안 적은 항목은 **같은 해의 바로 앞 항목**의 단계를 잇는다 — 같은 해에 이미
    # 서 있는 일과 같은 시절이다 (2000년 신구대학 입학 다음에 선 '최근호를 만남'은 '대학').
    for i, t in enumerate(timeline):
        if i == 0 or t.get("life_stage") in STAGE_ORDER or t.get("year") is None:
            continue
        prev = timeline[i - 1]
        if prev.get("life_stage") in STAGE_ORDER and prev.get("year") == t.get("year"):
            t["life_stage"] = prev["life_stage"]
    # 그러고도 비었으면 **앞뒤가 같은 단계일 때만** 잇는다 — 공익 근무와 소집해제 사이의
    # 만남은 '군복무'다. 앞만 보고 이으면 십 년 뒤의 일이 '초등학교'가 된다 — 모르는
    # 것은 모르는 채로 둔다.
    for i, t in enumerate(timeline):
        if t.get("life_stage") in STAGE_ORDER:
            continue
        before = next((x["life_stage"] for x in reversed(timeline[:i]) if x.get("life_stage") in STAGE_ORDER), None)
        after = next((x["life_stage"] for x in timeline[i + 1:] if x.get("life_stage") in STAGE_ORDER), None)
        t["life_stage"] = before if before is not None and before == after else None
    # 해가 같으면 학제가 차례다 — 초등 졸업이 중학 입학보다 먼저다 (`ladder` 머리글).
    for note in order_by_ladder(timeline, by_id):
        if note not in (payload.get("notes") or []):
            payload["notes"] = list(payload.get("notes") or []) + [note]
    for i, t in enumerate(timeline):
        t["previous_event"] = timeline[i - 1]["event_id"] if i else None
        t["next_event"] = timeline[i + 1]["event_id"] if i + 1 < len(timeline) else None


    # 5. 관계의 이름 — 온톨로지(LIFE_EDGES)에 맞추고 역할을 단다
    for issue in tidy_edges(nodes, edges, me):
        log.warning("개인 그래프 온톨로지 밖: %s", issue)

    # 6. 섬을 잇는다 — 내 삶의 사건은 내가 겪은 것이고, 가족은 이야기가 호칭으로 말한다
    if link_orphans(nodes, edges, me) + link_people(nodes, edges, me, story):
        tidy_edges(nodes, edges, me)   # 새로 이은 선에도 이름(역할)을 단다
    #    그러고 **사람이 지운 선**을 걷는다 — 위 두 규칙이 도로 그은 것도 여기서 빠진다.
    drop_unlinked(edges, payload.get("unlinked"))

    # 7. 역사 연결의 관문 — 이야기가 부르지 않은 사건·결과보다 늦은 원인을 지운다.
    # 옛 그래프도 화면이 열 때 refine 을 지나므로(POST /api/life/refine) 여기서
    # 같이 걸린다. 원문(text)을 모르면 이름으로는 안 버리고 순서만 잰다.
    gate_connections(payload, text)
    return payload


def says_date(line: str, date: str | None) -> bool:
    """문장이 이 날짜를 말하는가. **달까지 아는 날짜만** 잰다 ('1998' 은 너무 넓다).

    '1998-04-24' · '1998년 4월 24일' · '1998년 4월' 을 같은 것으로 읽는다.
    """
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(date or ""))
    if not m:
        return False
    y, mo, d = m.group(1), m.group(2), m.group(3)
    forms = [f"{y}-{mo}" + (f"-{d}" if d else ""),
             f"{int(y)}년 {int(mo)}월" + (f" {int(d)}일" if d else ""),
             f"{int(y)}년 {int(mo)}월"]
    return any(f in line for f in forms)


# --- 만난 일은 사건이다 -------------------------------------------------------------
# 이야기가 사람을 부를 때 쓰는 말. 이 말이 있어야 '만남'을 사건으로 세운다 —
# 근거는 이야기 안에 있어야 한다 (인과의 fact_check 와 같은 규칙).
_MET_STORY = re.compile(r"만나|만난|만났|만남|사귀|알게 되|처음 보")


def _obj(word: str) -> str:
    """목적격 조사 — '정혜림을' · '이수아를'. 받침이 없으면 '를'."""
    ch = (word or "").strip()[-1:]
    if ch and "가" <= ch <= "힣":
        return "을" if (ord(ch) - 0xAC00) % 28 else "를"
    return "을"


def year_from_story(story: str | None, name: str | None, birth: int | None,
                    entries: dict[str, int], anchors: dict[str, int] | None = None) -> tuple[int | None, str]:
    """이야기가 그것을 부르는 **첫 문장**에서 그것이 내 삶에 들어온 해를 셈한다.

    2026-09-09 사용자 지적: "'만20세', '공익생활'이라고 언급 했으면 이미 존재하는
    역사를 보면 충분히 유추 할 수 있었는데 그걸 못했어." 셈하는 자는 이미 있었다 —
    학년은 입학 해에서(`school_year`), 나이는 생년에서(`parse_when`). 없던 것은
    **그 자를 이야기 문장에 대 보는 자리**뿐이다. 노드의 날짜 칸만 보고 있었다.

    `anchors` 는 **이미 해를 아는 노드의 이름 → 해**다. 같은 날 두 번째 지적: "이미
    내 역사에 신구대학 시절이 이미 있는데 이걸 이용하지 못하네" — '신구대학 시절 만난
    친구들은 …' 에는 해도 나이도 학년도 없다. 이야기가 부른 것은 **이미 선 노드의
    이름**이고 그 노드가 해를 안다. 이야기가 스스로 해를 말하면(1998년·만20살·2학년)
    그것이 먼저고 이름은 마지막 근거다 — 이름이 여럿 걸리면 긴 쪽이 이긴다
    ('신구대학 컴퓨터정보학과 입학'이 '신구대학'을 이긴다).

    돌려주는 정밀도는 화면이 단정의 폭을 정하는 데 쓴다 (`parse_when` 머리글).
    """
    for line in _sentences_about(str(story or ""), name):
        y = school_year(line, entries)
        if y is not None:
            return y, "year"
        y, _, prec = parse_when(line, birth)
        if y is not None:
            return y, prec or "year"
        said = [(len(k), v) for k, v in (anchors or {}).items() if k in line]
        if said:
            return max(said)[1], "year"
    return None, ""


# 만남으로 읽는 관계. 가족은 뺀다 — 어머니를 '만난' 것이 아니다.
MET_EDGES = frozenset({"met", "friend_of", "worked_with", "schoolmate"})
# 내가 들거나 만드는 것.
ORG_TYPES = frozenset({"Company", "Organization", "Community", "Business"})
# **때의 닻** — 이야기가 이름으로 부르면 그 해를 빌려 주는 노드의 갈래. 사람은 넣지
# 않는다: '김일권과 자주 놀았어' 의 해가 김일권을 만난 해는 아니다. 자리(학교·회사·
# 단체)와 사건은 '그 시절'을 가리키는 말로 쓰인다 — '신구대학 시절'·'공익 시절'.
ANCHOR_TYPES = EVENT_TYPES | ORG_TYPES | {"School", "University", "Period", "LifeStage", "Time"}


def time_anchors(nodes: list[dict], me: dict | None) -> dict[str, int]:
    """이미 해를 아는 것들의 이름 → 해 (`year_from_story` 의 마지막 근거)."""
    out: dict[str, int] = {}
    for n in nodes:
        name = str(n.get("name") or "").strip()
        if n is me or n.get("year") is None or len(name) < 2 or n.get("type") not in ANCHOR_TYPES:
            continue
        out.setdefault(name, int(n["year"]))
    return out


def meet_events(payload: dict, nodes: list[dict], edges: list[dict], me: dict | None,
                story: str | None, entries: dict[str, int]) -> int:
    """'…를 만났다' 를 **사건**으로 세운다. 돌아오는 것은 새로 세운 수.

    2026-09-09 사용자: '공익생활을 하던 시절 만20살때 여자친구를 만났고, 이름은
    정혜림 이었다' 를 넣었는데 화면이 아무것도 안 그렸다. 모델은 제 할 일을 했다 —
    사람을 세우고 나와 이었다. 그런데 **연표는 사건만 그린다.** 사람을 점으로 찍지
    않는 것은 정한 것이다: 그 이름 아래 나이·단계가 서면 그것이 곧 그 사람의 생년으로
    읽힌다 (2026-09-08 사용자, `personalMarks` 머리글). 그래서 사람을 세울 것이
    아니라 **만난 일**을 세운다. 지시문도 이미 '만난 일은 timeline 에도 세운다' 고
    시키는데 모델이 자주 빠뜨린다 — 빠뜨린 것을 코드가 채운다.

    근거는 셋이 다 있어야 한다: 나와 이어진 만남 관계, 그 사람을 만났다고 **말한**
    문장, 그리고 해. 하나라도 없으면 세우지 않는다 — 없는 만남을 그리느니 안 그린다.
    """
    if me is None or not story:
        return 0
    by_id = {n["id"]: n for n in nodes}
    met: dict[str, dict] = {}
    family: set[str] = set()
    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if me["id"] not in (src, dst):
            continue
        other = by_id.get(dst if src == me["id"] else src)
        if other is None or other is me or other.get("type") not in PERSON_TYPES:
            continue
        if e.get("type") in _FAMILY_EDGES:
            family.add(other["id"])
        elif e.get("type") in MET_EDGES:
            met.setdefault(other["id"], other)
    # 이미 그 사람의 이름을 단 사건이 있으면 그것이 그 만남이다 (모델이 세운 것).
    named = [str(n.get("name") or "") for n in nodes if n.get("type") in EVENT_TYPES]
    timeline: list[dict] = payload.setdefault("timeline", [])
    made = 0
    for pid, who in met.items():
        name = str(who.get("name") or "").strip()
        year = who.get("year")
        if pid in family or len(name) < 2:
            continue
        ev_id = f"met_{pid}"
        if ev_id in by_id:
            _during(by_id, edges, pid, ev_id)   # 이미 세운 만남에도 시절을 잇는다
            continue
        lines = _sentences_about(story, name)
        if year is None or not any(_MET_STORY.search(ln) for ln in lines):
            continue
        if any(name in ev for ev in named):
            continue
        event = {
            "id": ev_id, "type": "PersonalEvent", "name": f"{name}{_obj(name)} 만남",
            # 설명은 이야기가 그 사람을 부른 문장 그대로다 — 지어낸 말을 세우지 않는다.
            "description": next((ln.strip() for ln in lines if _MET_STORY.search(ln)), None),
            "start_date": str(year), "end_date": None, "location": None,
            "participants": [me["id"], pid], "importance_score": who.get("importance_score"),
            "emotional_impact": None, "confidence": min(float(who.get("confidence") or 1.0), 0.9),
            "year": year, "end_year": None, "precision": who.get("precision") or "year",
        }
        nodes.append(event)
        by_id[ev_id] = event
        edges.append({"source": me["id"], "target": ev_id, "type": "experienced",
                      "description": None, "confidence": event["confidence"], "role": "만남"})
        edges.append({"source": pid, "target": ev_id, "type": "experienced",
                      "description": None, "confidence": event["confidence"], "role": "함께"})
        # 그 사람이 연표에 서 있었으면 그 자리를 이 사건이 받는다 — 사람은 점이
        # 아니므로 화면이 그리지 않았고, 단계도 모델이 아무렇게나 적어 두었다.
        moved = next((t for t in timeline if isinstance(t, dict) and t.get("event_id") == pid), None)
        if moved is not None:
            moved["event_id"], moved["life_stage"] = ev_id, None
        else:
            timeline.append({"event_id": ev_id, "life_stage": None, "year": year,
                             "age": None, "date_text": None})
        _during(by_id, edges, pid, ev_id)
        made += 1
    return made


# 내가 만든 것으로 읽는 말. '들어갔다'·'다녔다'는 아니다 — 만든 사람만 세운다.
_FOUND_STORY = re.compile(r"만들|만든|세웠|세운|결성|창단|창립|설립|차렸|차린|꾸렸|꾸린")
# 만든 일의 이름. 회사는 창업이고 모임은 결성이다.
_FOUND_DEED = {"Company": "창업", "Business": "창업"}


def founding_events(payload: dict, nodes: list[dict], edges: list[dict], me: dict | None,
                    story: str | None) -> int:
    """'모임을 만들었어' 를 **사건**으로 세운다. 돌아오는 것은 새로 세운 수.

    2026-09-09 사용자: '신구대학 시절 만난 친구들은 … 우리는 a-club이란 모임도
    만들었어' 를 넣었는데 "전혀 반영 하지 못했어". 단체는 연표에 서지 않는다 —
    이어지는 것이라 점이 아니다. 만든 **일**은 사건이라 선다 (만남과 같은 자리:
    `meet_events` 머리글).

    근거는 셋이 다 있어야 한다: 내가 든 단체라는 관계, 이야기가 **만들었다고 말한**
    문장, 그리고 해. 들어간 것(입사·가입)은 만든 것이 아니라 세우지 않는다.
    """
    if me is None or not story:
        return 0
    by_id = {n["id"]: n for n in nodes}
    mine: dict[str, dict] = {}
    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if src != me["id"] or e.get("type") not in ("member_of", "worked_at"):
            continue
        org = by_id.get(dst)
        if org is not None and org.get("type") in ORG_TYPES:
            mine.setdefault(org["id"], org)
    named = [str(n.get("name") or "") for n in nodes if n.get("type") in EVENT_TYPES]
    people = [n for n in nodes if n.get("type") in PERSON_TYPES and n is not me
              and len(str(n.get("name") or "").strip()) >= 2]
    timeline: list[dict] = payload.setdefault("timeline", [])
    made = 0
    for oid, org in mine.items():
        name = str(org.get("name") or "").strip()
        year = org.get("year")
        ev_id = f"made_{oid}"
        if len(name) < 2 or year is None or ev_id in by_id:
            continue
        lines = [ln for ln in _sentences_about(story, name) if _FOUND_STORY.search(ln)]
        if not lines or any(name in ev for ev in named):
            continue
        deed = _FOUND_DEED.get(str(org.get("type")), "결성")
        # 같이 만든 사람 — 그 문장이 함께 부른 사람이다 ('우리는 … 만들었어').
        with_me = [p["id"] for p in people if any(p["name"] in ln for ln in lines)]
        event = {
            "id": ev_id, "type": "PersonalEvent", "name": f"{name} {deed}",
            "description": lines[0].strip(), "start_date": str(year), "end_date": None,
            "location": None, "participants": [me["id"], *with_me],
            "importance_score": org.get("importance_score"), "emotional_impact": None,
            "confidence": min(float(org.get("confidence") or 1.0), 0.9),
            "year": year, "end_year": None, "precision": org.get("precision") or "year",
        }
        nodes.append(event)
        by_id[ev_id] = event
        edges.append({"source": me["id"], "target": ev_id, "type": "experienced",
                      "description": None, "confidence": event["confidence"], "role": deed})
        for pid in with_me:
            edges.append({"source": pid, "target": ev_id, "type": "experienced",
                          "description": None, "confidence": event["confidence"], "role": "함께"})
        timeline.append({"event_id": ev_id, "life_stage": None, "year": year,
                         "age": None, "date_text": None})
        made += 1
    return made


def _during(by_id: dict[str, dict], edges: list[dict], pid: str, ev_id: str) -> None:
    """'그 시절에 만났다' 는 사람이 그 사건을 겪은 것이 아니라 **만남이 그 사이에** 있던 것이다.

    모델은 '공익생활을 하던 시절 … 만났고' 를 `정혜림 -met-> 공익요원 근무` 로 적는다.
    사람 → 사건의 만남은 온톨로지에 없고(LIFE_EDGES), 참여로 옮기면 그 사람이 공익
    근무를 한 것이 되어 거짓이다. 만남 사건과 그 시절 사이의 `during` 이 참이다.
    """
    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if pid not in (src, dst) or e.get("type") not in MET_EDGES:
            continue
        other = by_id.get(dst if src == pid else src)
        if other is None or other.get("type") not in EVENT_TYPES:
            continue
        e["source"], e["target"], e["type"] = ev_id, other["id"], "during"


def participants_from_story(nodes: list[dict], text: str | None) -> int:
    """이야기가 **한 문장 안에서** 사건과 사람을 함께 부르면 그 사람도 그 자리에 있었다.

    모델은 participants 에 주인공만 적어 놓기도 한다 (2026-09-08 사용자: "친구
    김일권과 같이 갔다고 분명 말했는데 '함께 person_1' 이라고 말하고 있어").

    문장이 사건을 **이름으로 부르거나 달까지 아는 날짜로** 가리킬 때만 잰다 —
    해만 말한 문장("1997년에 입학했고 김일권을 만났어")은 그 해의 일을 여럿
    담으므로 누가 어디에 있었는지를 가르지 못한다. 근거는 원문에 있어야 한다.
    """
    story = str(text or "").strip()
    if not story:
        return 0
    people = [n for n in nodes if n.get("type") in PERSON_TYPES and len(str(n.get("name") or "").strip()) >= 2]
    events = [n for n in nodes if n.get("type") in EVENT_TYPES]
    if not people or not events:
        return 0
    made = 0
    for line in re.split(r"[.!?。\n]+", story):
        said = [n for n in people if n["name"] in line]
        if not said:
            continue
        for ev in events:
            name = str(ev.get("name") or "").strip()
            # 날짜로 가리키는 것은 **그 날 일어난 일**이다. 기억(Memory)은 물건이 그
            # 날을 가리킬 뿐이라 날짜로 잡지 않는다 (공연에 함께 간 사람이 '공연
            # 티켓'에도 서면 안 된다). 이름으로 부른 것은 그대로 잰다.
            by_date = ev.get("type") != "Memory" and says_date(line, ev.get("start_date"))
            if not (len(name) >= 2 and name in line) and not by_date:
                continue
            have = [str(x) for x in (ev.get("participants") or [])]
            for n in said:
                if n["id"] in have or n["name"] in have:
                    continue
                have.append(n["id"])
                made += 1
            ev["participants"] = have
    return made


def drop_unlinked(edges: list[dict], unlinked: list[str] | None) -> int:
    """사람이 상세의 '편집'에서 뺀 선을 걷는다. 돌아오는 것은 걷어 낸 수.

    2026-09-09 사용자가 관계를 빼고 완료를 눌렀는데 그 선이 그대로 서 있었다 —
    문서에서는 빠졌지만 `link_orphans` 가 곧바로 다시 그었다 (인물과 안 이어진
    개인 사건은 주인공이 겪은 것으로 잇는다는 2026-09-08 결정). 두 결정이
    부딪히는 자리는 여기 하나뿐이고 **사람이 이긴다** — 한국사 쪽 편집 계층과
    같은 규칙이다 (사람이 적은 것을 수집이 되돌리지 못한다).

    재는 것은 두 끝과 관계 이름이다 (`출발>도착|관계`). 방향은 안 본다 —
    tidy_edges 가 experienced 를 뒤집기도 한다. 같은 두 노드 사이의 다른
    관계는 그대로 남는다."""
    cut = {k for k in (unlinked or []) if isinstance(k, str)}
    if not cut:
        return 0
    kept = [e for e in edges
            if f"{e.get('source')}>{e.get('target')}|{e.get('type')}" not in cut
            and f"{e.get('target')}>{e.get('source')}|{e.get('type')}" not in cut]
    gone = len(edges) - len(kept)
    edges[:] = kept
    return gone


def link_participants(nodes: list[dict], edges: list[dict], me: dict | None) -> int:
    """participants 를 사람 노드로 풀어 **하나의 꼴(노드 id)** 로 만들고 사건에 잇는다.

    모델은 여기에 id 를 적기도 하고 이름을 적기도 한다. 못 푸는 식별자는 버린다 —
    화면이 그것을 그대로 적을 자리가 없어야 한다 (2026-09-08 사용자: "person_1이라고
    변수 이름을 바로 노출 하면 안 돼"). 이은 선의 역할은 tidy_edges 가 '함께'로 단다.
    """
    by_id = {n["id"]: n for n in nodes}
    by_name = {_norm_label(n.get("name")): n for n in nodes if n.get("type") in PERSON_TYPES}
    tied = {(e.get("source"), e.get("target")) for e in edges}
    made = 0
    for ev in nodes:
        if not isinstance(ev.get("participants"), list):
            continue
        kept: list[str] = []
        for p in ev["participants"]:
            who = by_id.get(str(p)) or by_name.get(_norm_label(p))
            pid = who["id"] if who else (str(p).strip() if _HANGUL.search(str(p)) else "")
            if not pid or pid == ev["id"] or pid in kept:
                continue
            kept.append(pid)
            if who is None or who is me or who.get("type") not in PERSON_TYPES \
                    or ev.get("type") not in EVENT_TYPES:
                continue
            if (who["id"], ev["id"]) in tied or (ev["id"], who["id"]) in tied:
                continue
            edges.append({"source": who["id"], "target": ev["id"], "type": "experienced",
                          "description": None, "confidence": ev.get("confidence", 1)})
            tied.add((who["id"], ev["id"]))
            made += 1
        ev["participants"] = kept
    return made


def link_orphans(nodes: list[dict], edges: list[dict], me: dict | None) -> int:
    """주인공과 떨어져 뜬 섬을 잇는다. 돌아오는 것은 새로 이은 수.

    2026-09-08 사용자: "'나'와의 연결이 없이 떨어진 그래프들이 보이는데 왜 따로
    떼어둔거지?" 모델은 **한 번에 준 이야기 안에서는** 주인공 → 사건을 잇지만,
    더하기(merge)로 뒤에 붙인 토막에서는 사건끼리만 이어 놓는다 — 실측: 군복무 세
    사건(입소 → 공익요원 → 소집해제)이 led_to 사슬로만 서 있었고, 성내중학교
    입학·졸업은 학교하고만 이어져 섬이 됐다. 이 그래프는 **한 사람의 삶**이므로
    개인 사건은 임자가 정해져 있다. 근거는 이야기 밖에서 오지 않는다:

      1. 어떤 인물과도 안 이어진 개인 사건 → 주인공이 겪은 것(experienced).
         **남의 사건은 그대로 둔다** — 이미 인물과 이어진 사건(아버지의 부도)과
         세계사 사건(HistoricalEvent)은 임자가 주인공이 아니다.
      2. 아무 데도 안 이어진 장소·단체가 어떤 사건의 이름·설명에 그대로 불리면
         그 사건이 일어난 곳(at). 실측: '천호3동 사무소'가 '천호3동 사무소 공익요원
         근무 시작' 옆에서 홀로 떠 있었다. 이미 이어진 곳은 모델이 말한 것이 맞다.

    온톨로지를 씌운 뒤(tidy_edges)에 잰다 — 버려질 엣지를 이어진 것으로 세면
    섬이 그대로 남는다."""
    if me is None:
        return 0
    who = {n["id"] for n in nodes if n.get("type") in PERSON_TYPES}
    tied = {(e.get("source"), e.get("target")) for e in edges}
    touched = {i for pair in tied for i in pair}
    made = 0
    for n in nodes:
        if klass(n) != "event" or n.get("type") == "HistoricalEvent":
            continue
        if any((a in who and b == n["id"]) or (b in who and a == n["id"]) for a, b in tied):
            continue
        edges.append({"source": me["id"], "target": n["id"], "type": "experienced",
                      "description": None, "confidence": 0.8})
        made += 1
    for spot in nodes:
        name = str(spot.get("name") or "").strip()
        if klass(spot) not in ("place", "org") or spot["id"] in touched or len(name) < 2:
            continue
        for ev in nodes:
            if klass(ev) not in ("event", "period") or ev["id"] == spot["id"]:
                continue
            if name in f"{ev.get('name') or ''} {ev.get('description') or ''}":
                edges.append({"source": ev["id"], "target": spot["id"], "type": "at",
                              "description": None, "confidence": 0.8})
                made += 1
                break
    return made


# --- 가족은 이야기가 호칭으로 말한다 ---------------------------------------------------
# 2026-09-08 사용자: "왜 엄마라고 분명히 말했고 엄마는 매우 중요한 사람인데 그래프에서
# 나와 엄마 사이에 엣지를 그리지 않았지?" 모델은 관계를 적었지만 관문이 버렸고
# (validate 머리글), 코드에는 호칭을 읽는 자리가 없었다. 가족 호칭은 모델에게 다시
# 물을 것이 아니다 — `participants_from_story` 가 한 문장의 사건과 사람을 잇듯, 이야기가
# 호칭과 이름을 함께 부르면 코드가 잇는다. 호칭이 선의 이름(역할)이다.
#
# 호칭 → (관계, 방향). 방향은 LIFE_EDGES 의 출발·도착대로: `in` 은 그 사람 → 나
# (parent_of 는 부모 → 자녀), `out` 은 나 → 그 사람, `sym` 은 대칭(relative_of).
# 형제·배우자는 relative_of 에 호칭을 역할로 단다 — 관계 타입을 늘리면 지시문·스키마·
# 문장 규칙을 같이 늘려야 한다 (graph-drawer §1.4). 긴 호칭이 먼저다 (외할머니 ⊃ 할머니).
_KIN_TERMS: dict[str, tuple[str, str]] = {
    **{t: ("ancestor_of", "in") for t in ("증조할머니", "증조할아버지", "고조할머니", "고조할아버지",
                                          "증조부", "증조모", "고조부", "고조모")},
    **{t: ("grandparent_of", "in") for t in ("외할머니", "외할아버지", "친할머니", "친할아버지",
                                             "할머니", "할아버지", "조모", "조부")},
    **{t: ("parent_of", "in") for t in ("어머니", "어머님", "엄마", "모친", "아버지", "아버님", "아빠", "부친",
                                        "새어머니", "새아버지", "양어머니", "양아버지", "계모", "계부")},
    **{t: ("parent_of", "out") for t in ("큰아들", "작은아들", "큰딸", "작은딸", "아들", "딸", "자식", "자녀")},
    **{t: ("grandparent_of", "out") for t in ("외손자", "외손녀", "손자", "손녀")},
    **{t: ("relative_of", "sym") for t in (
        "남동생", "여동생", "형님", "누님", "쌍둥이", "형", "누나", "언니", "오빠", "동생",
        "아내", "남편", "부인", "집사람", "신랑", "배우자",
        "외삼촌", "삼촌", "이모부", "고모부", "외숙모", "이모", "고모", "숙부", "숙모", "백부", "백모",
        "큰아버지", "작은아버지", "큰어머니", "작은어머니", "사촌", "조카",
        "장인", "장모", "시아버지", "시어머니", "며느리", "사위", "처남", "처형", "처제",
        "매형", "매제", "형수", "제수", "올케", "시누이", "동서")},
}
# 호칭은 낱말이어야 한다 — 앞에 한글이 붙으면 다른 낱말이다 ('나형철'의 '형'). 다만
# '우리형'·'내동생'처럼 붙여 쓴 것은 받는다. 뒤에는 조사나 띄어쓰기가 온다 ('엄마는'·'형이').
_KIN_ALT = "|".join(sorted(_KIN_TERMS, key=len, reverse=True))
_KIN_TAIL = r"(?=[은는이가을를과와의도만께랑한로들야]|\s|[,.!?)]|$)"
_KIN = re.compile(r"(?:(?<![가-힣])|(?<=우리)|(?<=내)|(?<=저희)|(?<=울))(" + _KIN_ALT + ")" + _KIN_TAIL)
# 가족 관계 — 이미 이어진 사람은 건드리지 않되, 이 관계에 역할이 비어 있으면 호칭을 단다.
_FAMILY_EDGES = frozenset({"parent_of", "child_of", "grandparent_of", "ancestor_of", "relative_of"})


def kin_in(sentence: str, names: list[str] | None = None) -> tuple[str, str, str, int] | None:
    """문장 속 가족 호칭 하나 — (호칭, 관계, 방향, 자리). `names` 는 그 문장의 사람 이름이라
    호칭 찾기 전에 가린다 (이름 안의 글자가 호칭으로 읽히면 안 된다)."""
    masked = sentence
    for nm in names or []:
        masked = masked.replace(nm, "○" * len(nm))
    m = _KIN.search(masked)
    if not m:
        return None
    term = m.group(1)
    kind, direction = _KIN_TERMS[term]
    return term, kind, direction, m.start(1)


def _kin_of_other(sentence: str, name: str) -> bool:
    """'김일권의 엄마'·'김일권 엄마' — 남의 가족이지 내 가족이 아니다."""
    return re.search(re.escape(name) + r"\s*(?:의|네)?\s*(?:" + _KIN_ALT + ")" + _KIN_TAIL, sentence) is not None


def link_people(nodes: list[dict], edges: list[dict], me: dict | None, text: str | None) -> int:
    """주인공과 떨어진 **사람**을 잇는다. 돌아오는 것은 새로 이은 수.

    사람 섬은 남기지 않는다 (2026-09-08 사용자 — 어머니 백경순이 홀로 떠 있었다):
      1. 이야기가 한 문장(또는 바로 앞 문장까지)에서 **가족 호칭과 그 사람의 이름**을
         함께 부르면 LIFE_EDGES 의 가족 관계로 잇고 호칭을 역할로 단다 — 나와 직접
         이어져 있지 않은 사람만. 남의 가족('김일권의 엄마')은 아니다.
      2. 그러고도 주인공에게 닿지 않는 사람은, 이야기가 이름을 부르면 `met`(0.8) 로
         잇는다 — 설명이 '친구'라 하면 tidy_edges 가 friend_of 로 옮긴다.
    이미 이어진 사람은 건드리지 않는다. 근거는 이야기 밖에서 오지 않는다."""
    if me is None:
        return 0
    story = str(text or "").strip()
    if not story:
        return 0
    people = [n for n in nodes if n.get("type") in PERSON_TYPES and n is not me
              and n.get("id") != me.get("id") and len(str(n.get("name") or "").strip()) >= 2]
    if not people:
        return 0
    tied = {(e.get("source"), e.get("target")) for e in edges}
    direct = {b if a == me["id"] else a for a, b in tied if me["id"] in (a, b)}
    # 모델이 이미 가족 관계로 이었는데 역할이 비어 있으면 호칭만 단다 (선의 이름).
    unnamed: dict[str, dict] = {}
    for e in edges:
        if e.get("type") in _FAMILY_EDGES and not e.get("role") and me["id"] in (e.get("source"), e.get("target")):
            other = e["target"] if e.get("source") == me["id"] else e["source"]
            unnamed.setdefault(str(other), e)
    made = 0
    # 1. 호칭
    for n in people:
        if n["id"] in direct and n["id"] not in unnamed:
            continue
        name = str(n["name"]).strip()
        hit = None
        for para in story.split("\n"):
            sents = [s for s in re.split(r"[.!?。]", para) if s.strip()]
            for i, s in enumerate(sents):
                if name not in s or _kin_of_other(s, name):
                    continue
                names = [str(p["name"]).strip() for p in people if str(p["name"]).strip() in s]
                hit = kin_in(s, names) or (kin_in(sents[i - 1], names) if i > 0 else None)
                if hit:
                    break
            if hit:
                break
        if not hit:
            continue
        term, kind, direction, _ = hit
        if n["id"] in unnamed:
            unnamed[n["id"]]["role"] = term
            continue
        src, dst = (n["id"], me["id"]) if direction == "in" else (me["id"], n["id"])
        edges.append({"source": src, "target": dst, "type": kind, "role": term,
                      "description": None, "confidence": 1.0})
        tied.add((src, dst))
        direct.add(n["id"])
        made += 1
    # 2. 이름이 불린 사람 — 주인공에게 닿지 않으면 만난 사이로
    reach = {me["id"]}
    grew = True
    while grew:
        grew = False
        for a, b in tied:
            if (a in reach) != (b in reach):
                reach.update((a, b))
                grew = True
    for n in people:
        if n["id"] in reach or str(n["name"]).strip() not in story:
            continue
        edges.append({"source": me["id"], "target": n["id"], "type": "met",
                      "description": n.get("description"), "confidence": 0.8})
        tied.add((me["id"], n["id"]))
        reach.add(n["id"])
        made += 1
    return made


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
                   r"출생|출산|사망|합격|낙방|수상|당선|낙선|출마|입원|수술|데뷔|입양|만남|이별|재회|결성|창단|창립|설립|시작|종료)\s*$")
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
      5. 옮길 데 없이 차례만 남은 것(SEQUENCE_ONLY)은 버린다 — 연표가 이미 그린다.
      6. 대칭 관계의 역방향 중복은 하나만."""
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
        # 5. 차례만 남은 것은 버린다 — RELAX 가 옮길 데가 있었으면 이미 옮겼고(주인공 →
        #    자기 사건은 참여), 사건 → 사건으로 남았으면 연표가 이미 그리는 차례다.
        if kind in SEQUENCE_ONLY:
            continue
        # 6. 중복
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


# --- 삶의 사다리 — 뒤집히지 않는 차례 ---------------------------------------------
# 2026-09-08 사용자: "초등학교 졸업을 해야 중학교 입학을 하지 … 같은 연도에 일어난
# 일이지만 월을 입력 하지 않아서 사실 우리 서비스도 뭐가 먼저 일어난 일인지 정확하게
# 몰라. 하지만 논리상 초등학교 졸업이 무조건 먼저 일어나야 하잖아?"
#
# 달을 모르는 두 사건의 차례는 **모델에게 물을 것이 아니다.** 학제는 정해져 있다 —
# 층(초1·중2·고3·대4·대학원5)과 그 층 안의 자리(들어감 0·다님 1·나옴 2)를 한 줄로
# 세운다: 초등 입학 10 · 초등 졸업 12 · 중학 입학 20 … 대학 졸업 42.
#
#   - 해가 같으면 이 수가 차례다 (refine 3). 달을 모르는 자리를 규칙이 메운다.
#   - 해가 이 수를 어기면 **해가 틀린 것**이다. 연표는 해의 축 위에 서므로 코드가
#     해를 넘어 옮길 수는 없다 — 세어서 알리고(notes), 고치는 것은 이야기다
#     (`merge` 의 정정: 나중에 한 말이 앞서 한 말을 이긴다).
_LADDER_WORDS = (("대학원", 5), ("석사", 5), ("박사", 5),
                 ("대학교", 4), ("대학", 4), ("전문대", 4),
                 ("고등학교", 3), ("고교", 3),
                 ("중학교", 2),
                 ("초등학교", 1), ("국민학교", 1))
_LADDER_IN = re.compile(r"입학|진학|편입|복학|전학|들어갔|들어감")
_LADDER_OUT = re.compile(r"졸업|수료|자퇴|중퇴|퇴학|마쳤|마침")


def _rung(text: str) -> int | None:
    for word, level in _LADDER_WORDS:
        if word in text:
            return level * 10 + (2 if _LADDER_OUT.search(text) else 0 if _LADDER_IN.search(text) else 1)
    return None


def ladder(node: dict | None) -> int | None:
    """이 사건이 학제의 몇 째 칸인가. 학제와 무관한 사건은 None (차례를 안 건다).

    이름이 먼저다 — 설명은 앞뒤를 같이 말하곤 해서('초등학교를 졸업하고 중학교에
    입학함') 자리를 뒤집는다. 이름이 층을 말하지 않을 때만 설명을 본다.
    """
    if not node or node.get("type") not in EVENT_TYPES:
        return None
    return _rung(str(node.get("name") or "")) or _rung(str(node.get("description") or ""))


def order_by_ladder(timeline: list[dict], by_id: dict[str, dict]) -> list[str]:
    """해가 같은 칸끼리 사다리 순으로 다시 세운다. 해가 사다리를 어긴 것은 알린다.

    **사다리에 없는 항목은 제자리에 둔다** — 자리만 맞바꾼다. 이야기가 준 차례를
    학제와 상관없는 사건에까지 들이대지 않는다. `timeline` 은 이미 해 순이다.
    """
    rank = {id(t): ladder(by_id.get(t.get("event_id"))) for t in timeline}
    i = 0
    while i < len(timeline):
        j = i
        while j < len(timeline) and timeline[j].get("year") == timeline[i].get("year"):
            j += 1
        if timeline[i].get("year") is not None:
            spots = [k for k in range(i, j) if rank[id(timeline[k])] is not None]
            if len(spots) > 1:
                for spot, t in zip(spots, sorted((timeline[k] for k in spots), key=lambda t: rank[id(t)])):
                    timeline[spot] = t
        i = j
    notes = []
    ranked = [(t, rank[id(t)], t["year"]) for t in timeline
              if rank[id(t)] is not None and t.get("year") is not None]
    for t, r, y in ranked:
        worse = [(t2, y2) for t2, r2, y2 in ranked if r2 < r and y2 > y]
        if not worse:
            continue
        t2, y2 = max(worse, key=lambda p: p[1])
        name = lambda x: (by_id.get(x.get("event_id")) or {}).get("name") or x.get("event_id")
        notes.append(f"차례가 어긋난다 — {name(t)}({y})은 {name(t2)}({y2}) 뒤여야 한다. 해가 틀렸다.")
    return notes

def month_year(date: str | None) -> int | None:
    """달까지 아는 날짜의 해. 'YYYY-MM' 부터가 달을 아는 것이다 ('YYYY' 는 None)."""
    m = re.match(r"(-?\d{1,4})-(\d{2})", str(date or ""))
    return int(m.group(1)) if m else None


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


def validate(payload: dict, subject: dict | None = None, text: str | None = None,
             known: set[str] | None = None) -> tuple[dict, list[str]]:
    """모델의 답을 화면이 믿고 그릴 수 있는 꼴로 다듬고, 고친 것을 적어 준다.

    형태는 스키마가 지켰다고 보고 **내용**만 본다:
      - 타입·관계 이름이 표에 없으면 버린다 (화면이 영어를 띄우게 된다).
      - 엣지의 양끝이 노드에 없으면 버린다.
      - 신뢰도는 0~1 로, 점수는 1~10 으로 자른다.
      - 노드의 날짜를 풀어 `year`·`end_year`·`precision` 을 단다. 연표 항목이
        연도를 안 적었으면 노드의 것을 쓴다. 나이만 있으면 생년으로 푼다.
      - **인물의 생몰년은 원문(`text`)이 말한 것만 남긴다** (gate_dates).
      - 노드 이름·설명에 한글이 한 자도 없어도 손대지 않는다.

    `subject` 는 **더하는 이야기**일 때 옛 그래프의 주인공(id·생년)이다 — 새 답의
    첫 인물이 주인공이라는 짐작이 그때는 틀린다 (새로 나온 친척일 수 있다).

    `known` 은 **옛 그래프의 노드 id** 다 (`known_ids`). 더하는 이야기에서 모델은
    시킨 대로 옛 노드를 다시 만들지 않고 그 id 로만 부르므로, 그 id 를 관계·연표의
    끝으로 받아 준다 — 안 받으면 새 답이 옛 그래프에 닿는 선이 통째로 "양끝이 없다"고
    버려진다 (2026-09-09 실측: '공익생활을 하던 시절 … 여자친구를 만났고' 를 읽은
    모델이 그 사람을 옛 공익근무 사건에 이었는데 그 선이 여기서 사라졌다). 이 id 가
    정말 있는지는 `merge` 가 다시 잰다.
    """
    from .labels import HANGUL

    known = {str(i) for i in (known or ())}
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
    # 더하는 이야기의 주인공은 **옛 그래프에 있다** — 모델은 시킨 대로 그 노드를 다시
    # 만들지 않는다. 그때 새 답의 첫 인물을 주인공으로 잡으면 남(어머니)이 주인공이
    # 되고, 주인공을 가리키는 관계는 "양끝이 없다"고 버려진다 (2026-09-08 실측:
    # '우리 엄마는 … 백경순이야' 의 `person_mother → person_1` 이 그렇게 사라져
    # 어머니가 그래프에 홀로 떴다). 주인공 id 는 노드에 없어도 관계의 끝이 된다 —
    # `merge` 가 옛 그래프의 그 노드에 잇는다.
    ghost: str | None = None
    if subject and subject.get("id"):
        me = by_id.get(subject["id"]) or next(
            (n for n in nodes if n["type"] == "Person" and n["name"].strip().lower() in SELF_NAMES | {"나"}), None)
        if me is None:
            ghost = str(subject["id"])
    if me is None and ghost is None:
        me = next((n for n in nodes if n["type"] == "Person"), None)
    if me and me["name"].strip().lower() in SELF_NAMES:
        # 지시문이 화자를 '사용자'라 부르니 모델도 그 이름을 노드에 적는다.
        # 화면에서 그 사람은 '나'다 (2026-09-08 사용자: "'사용자'라고 하지 말고 '나' 라고 해줘").
        me["name"] = "나"
    # 인물의 생몰년은 원문이 말한 것만 남긴다 (gate_dates 머리글).
    notes += gate_dates(nodes, me, text, payload.get("timeline"))
    birth = parse_when(me.get("start_date") if me else None)[0]
    if birth is None and subject and subject.get("birth_year") is not None:
        birth = int(subject["birth_year"])
    if birth is None and me:
        birth = birth_from_nodes(me, nodes, payload.get("edges") or [])
    out["subject"] = {"id": me["id"], "name": me["name"], "birth_year": birth} if me else \
        (dict(subject, birth_year=birth) if ghost else None)
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
    # **주인공은 이름으로 불린다.** 더하는 이야기에서 주인공 노드는 새 답에 없고
    # (`ghost`), 양끝을 이름으로 적는 모델은 그 자리에 '나'라고 쓴다 — id 로만 찾으면
    # 그 사람이 든 모임·회사가 통째로 사라진다 (2026-09-09 실측: '나 → a-club 소속'이
    # 여기서 버려져 모임을 만든 일이 연표에 못 섰다). 모델이 바뀌어도 같아야 하는 자리다.
    if ghost or me is not None:
        who = str(ghost or me["id"])
        for label in {*SELF_NAMES, "나", str((subject or {}).get("name") or ""), 
                      str(me.get("name") or "") if me is not None else ""}:
            key = _norm_label(label)
            if key and key not in by_name:
                by_name[key] = who

    def _endpoint(ref: Any) -> str | None:
        if ref in by_id or (ghost is not None and ref == ghost) or ref in known:
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
        if not isinstance(t, dict) or (t.get("event_id") not in by_id and t.get("event_id") not in known):
            notes.append(f"연표 항목의 사건이 노드에 없음: {t.get('event_id') if isinstance(t, dict) else t!r}")
            continue
        node = by_id.get(t["event_id"]) or {}
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
    # 개인 사건도 관계처럼 **이름으로** 적어 온다 (2026-09-08 실측: 'IMF 때 아버지
    # 사업이 망했어'를 읽은 모델이 personal_event 에 'event_0' 대신 '아버지 사업
    # 실패'를 적었다). 되짚어 id 로 바꾼다 — 못 찾으면 관문이 버린다.
    conns = []
    for c in payload.get("historical_connections") or []:
        if not isinstance(c, dict):
            continue
        pe = _endpoint(c.get("personal_event"))
        if pe is None and c.get("personal_event") not in (None, ""):
            notes.append(f"역사 연결의 개인 사건 '{c.get('personal_event')}' 을 노드에서 못 찾음 — 버림")
        conns.append(dict(c, personal_event=pe or c.get("personal_event"),
                          impact_type=c.get("impact_type") if c.get("impact_type") in IMPACT_KO else "possible"))
    out["historical_connections"] = conns
    ranking = payload.get("influence_ranking") or {}
    # 지시문의 형태('{}')는 범주 → 항목일 수도, 목록일 수도 있다. 둘 다 받는다.
    if isinstance(ranking, dict) and not isinstance(ranking.get("items"), list):
        ranking = {"items": [dict(v, category=k) for k, v in ranking.items() if isinstance(v, dict)]}
    elif isinstance(ranking, list):
        ranking = {"items": ranking}
    out["influence_ranking"] = ranking
    out["follow_up_questions"] = [str(q) for q in (payload.get("follow_up_questions") or [])][:5]
    out["family_analysis"] = payload.get("family_analysis") or {"members": []}
    out["counterfactual_analysis"] = [_counterfactual(c)
                                      for c in payload.get("counterfactual_analysis") or [] if isinstance(c, dict)]
    out["life_patterns"] = [p for p in payload.get("life_patterns") or [] if isinstance(p, dict)]
    # 어느 모델이 쓴 그래프인지. 백엔드가 여럿이라(로컬 MLX·OpenRouter 무료
    # 모델) 이 값이 없으면 나중에 이상한 노드의 출처를 가릴 수 없다.
    if payload.get("_model"):
        out["_model"] = payload["_model"]
    out["notes"] = notes   # refine 이 뒤에 제 사유(역사 연결 버림)를 잇는다
    refine(out, added=text)
    return out, out["notes"]


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


# --- 정정 — 나중에 한 말이 앞서 한 말을 이긴다 -----------------------------------
# 2026-09-08 실측: 이야기가 "성내중학교 입학년도를 잘못 말했어 1994년에 입학해서"라고
# 고쳐 말했는데 화면에는 1993년이 그대로 서 있었다. 모델은 고친 해를 제대로 답했다
# (새 id `ms_entry_1994`, 같은 이름 '성내중학교 입학'). 버린 것은 `merge` 다 — `_fill`
# 은 **빈 칸만 채우므로** 이미 든 1993 을 이기지 못한다. 그래서 더할 때는 채우기 전에
# 한 번 잰다: 새 답이 **다른 해**를 말하고, 그 해가 **이번 이야기 글에 그대로 있고**,
# 그 이야기가 이 노드를 부르면(grounded) 새 해가 이긴다. 셋이 다 맞아야 고친다 —
# 모델이 옛 사건을 흐릿하게 되뇐 것으로 정확한 날짜를 덮지 않는다.
def correct(old: dict, new: dict, text: str | None) -> list[str]:
    """`old` 의 날짜를 `new` 의 것으로 고친다. 고친 사유를 돌려준다 (안 고치면 빈 목록)."""
    notes: list[str] = []
    if not text:
        return notes
    for key, ykey, pkey in (("start_date", "year", "precision"), ("end_date", "end_year", None)):
        was, now = old.get(key), new.get(key)
        if not was or not now or str(was) == str(now):
            continue
        y0, y1 = parse_when(str(was))[0], parse_when(str(now))[0]
        if y0 is None or y1 is None or y0 == y1:
            continue
        if not re.search(rf"(?<!\d){y1}(?!\d)", text) or not grounded(text, old.get("name"), new.get("name")):
            continue
        old[key] = now
        old[ykey] = new.get(ykey) if new.get(ykey) is not None else y1
        if pkey:
            old[pkey] = new.get(pkey) or parse_when(str(now))[2]
        notes.append(f"이야기가 고쳐 말했다: {old.get('name')} {was} → {now}")
    return notes


def merge(base: dict, add: dict, text: str | None = None) -> tuple[dict, dict]:
    """옛 그래프 `base` 에 새 답 `add` 를 더한다. (합친 것, 더한 수) 를 준다.

    `text` 는 **이번에 더하는 이야기**다 — 앞서 한 말을 고치는 말이 여기 있다
    (`correct` 머리글). 안 주면 고치지 않고 빈 칸만 채운다."""
    import copy

    out = copy.deepcopy(base)
    nodes: list[dict] = out.setdefault("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    by_key = {(n.get("type"), _norm_label(n.get("name"))): n["id"] for n in nodes}
    subject = out.get("subject") or {}
    subj_id = subject.get("id") if subject.get("id") in by_id else None
    # `ids` 는 **새로 생긴 노드의 id** 다. 화면이 그리로 간다 — 다 만들고도 연표가
    # 서 있던 자리에 그대로 있으면 사람 눈에는 아무 일도 안 일어난 것이다
    # (2026-09-09 사용자: "모델이 해석을 끝냈으면 그래프와 연표에 바로 적용되야
    # 하는데 그게 안 되고 있는거 같어" — 실측: 2013년 사건을 더했는데 연표는
    # 1980년대를 비추고 있었다).
    stats = {"nodes": 0, "edges": 0, "timeline": 0, "connections": 0, "ids": []}

    remap: dict[str, str] = {}
    fixed: list[str] = []
    corrected: set[str] = set()

    def _same(old_node: dict, new_node: dict) -> None:
        """이미 있던 노드에 새 답을 얹는다 — 고칠 것은 고치고 빈 칸은 채운다."""
        said = correct(old_node, new_node, text)
        if said:
            fixed.extend(said)
            corrected.add(old_node["id"])
        _fill(old_node, new_node)

    for n in add.get("nodes") or []:
        nid = n["id"]
        if nid in by_id:
            remap[nid] = nid
            _same(by_id[nid], n)
            continue
        name = str(n.get("name") or "")
        if subj_id and n.get("type") == "Person" and (
                name.strip().lower() in SELF_NAMES or name == "나" or name == by_id[subj_id].get("name")):
            remap[nid] = subj_id
            _same(by_id[subj_id], n)
            continue
        key = (n.get("type"), _norm_label(name))
        if key in by_key:
            remap[nid] = by_key[key]
            _same(by_id[by_key[key]], n)
            continue
        node = dict(n)
        nodes.append(node)
        by_id[nid] = node
        by_key[key] = nid
        remap[nid] = nid
        stats["nodes"] += 1
        stats["ids"].append(nid)

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
    # 고친 날짜는 연표 항목도 따라간다 — 항목이 옛 해를 들고 있으면 refine 이 그것을
    # 그대로 쓴다 (항목의 해가 노드의 해를 이긴다). 나이는 비워 다시 세게 한다.
    for t in timeline:
        node = by_id.get(t.get("event_id"))
        if node is None or node["id"] not in corrected or node.get("year") is None:
            continue
        if t.get("year") != node["year"]:
            t["year"], t["age"] = node["year"], None
            if t.get("date_text") and parse_when(str(t["date_text"]))[0] != node["year"]:
                t["date_text"] = None
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

    def _extend(key: str, ident, fill: tuple[str, ...] = ()) -> None:
        items = out.setdefault(key, [])
        if not isinstance(items, list):
            items = out[key] = []
        seen = {ident(it): it for it in items if isinstance(it, dict)}
        for it in add.get(key) or []:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            for f in ("event", "node", "node_id"):
                if f in it and it[f] in remap:
                    it[f] = remap[it[f]]
            k = ident(it)
            if k in seen:
                # 겹친 줄은 옛 것을 남기되 **빈 칸은 채운다** — 옛 문서의 '만약
                # 없었다면' 에는 물음만 있고 답이 없다 (지시문이 `answer` 를
                # 요구하기 전에 만든 것). 다시 물었을 때 그 답이 들어올 자리다.
                for f in fill:
                    if not str(seen[k].get(f) or "").strip() and str(it.get(f) or "").strip():
                        seen[k][f] = it[f]
                continue
            seen[k] = it
            items.append(it)

    _extend("turning_points", lambda it: _norm_label(it.get("event")))
    _extend("impact_analysis", lambda it: (_norm_label(it.get("event")), it.get("impact_type")))
    _extend("counterfactual_analysis", lambda it: _norm_label(it.get("event")), fill=("answer",))
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
    out["notes"] = list(add.get("notes") or []) + fixed
    # refine 에는 이야기를 주지 않는다 — 여기 있는 것은 **이번에 더한 토막**이라
    # 옛 이야기가 부른 역사 연결이 통째로 걸린다 (부르는 쪽이 옛 이야기까지 합쳐
    # gate_connections 를 한 번 더 돈다: server._run · cli.cmd_life).
    # 옛 그래프에 비어 있던 해·연결도 이 김에 채운다 (사유는 notes 뒤에 잇는다).
    # 이번 토막은 `added` 로 준다 — 이야기 안의 근거(함께한 사람·가족 호칭)는 읽되
    # 역사 연결의 관문은 걸지 않는다.
    was = {n["id"] for n in out.get("nodes") or []}
    was_tl = len(out.get("timeline") or [])
    refine(out, added=text)
    # refine 이 세운 것(만남 사건)도 더한 것이다 — 화면이 '무엇이 늘었나'를 이것으로 적고
    # 그리로 옮겨 간다.
    for n in out.get("nodes") or []:
        if n["id"] not in was:
            stats["nodes"] += 1
            stats["ids"].append(n["id"])
    stats["timeline"] += max(0, len(out.get("timeline") or []) - was_tl)
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
        # 그래프가 아는 다른 이름('6·25 전쟁'·'한국 전쟁'). 관문이 이야기 원문에
        # 이 이름들이 있는지 볼 때 쓴다 — 모델이 정식 이름으로 바꿔 불러도 잇는다.
        # 검색 결과의 names 는 props 의 병기 이름뿐이다. 손으로 적은 별칭
        # (data/aliases.tsv → aliases 표: '외환 위기')은 노드 상세에만 온다.
        names = list(best.get("names") or [])
        if hasattr(api, "node"):
            detail = api.node(best["id"]) or {}
            names += list(detail.get("aliases") or [])
        c["node_names"] = sorted({x for x in names if x and x != best.get("label")})
        hy = best.get("start")
        if c.get("year") is None and hy is not None:
            c["year"] = hy
            c["year_from"] = "graph"
        n += 1
    return n


# --- 역사 연결의 관문 ----------------------------------------------------------
# 2026-09-08 지적: "세월호 사건과 사용자의 퍼듀대학교 졸업은 도대체 무슨 상관이지?
# 연평해전과 동사무소 공익요원 시작은 어떤 관계가 있지?" 모델이 이야기에 없는
# 역사를 같은 해라는 이유로 이었다. 한국사 인과와 같은 관문을 둔다 — (1) 근거가
# 원문에 있어야 한다: 이야기가 그 사건을 이름으로 부르지 않았으면 버린다.
# (2) 원인은 결과보다 먼저다: 역사 사건이 개인 사건보다 뒤면 버린다.
# 이름 대조에서 빼는 낱말 — 이것만 겹친 것은 부른 것이 아니다 ('전쟁'·'사고').
_GROUND_STOP = frozenset({
    "대한민국", "대한민국의", "한국", "한국의", "조선", "서울", "사건", "사고", "사태", "요청", "시행",
    "선언", "발표", "운동", "위기", "전쟁", "항쟁", "혁명", "붕괴", "침몰", "폭발", "범유행", "유행",
    "대통령", "정부", "국가", "제", "년", "월", "일", "및", "the", "of",
})


def _ground_tokens(name: str) -> list[str]:
    toks = [t for t in re.split(r"[\s·.,()（）\-–—/]+", str(name or "")) if t]
    return [_norm_label(t) for t in toks if len(t) >= 2 and t not in _GROUND_STOP and _norm_label(t)]


def grounded(text: str | None, *names: str | None) -> bool:
    """이야기 원문이 이 사건을 부르는가. 이름 전체(띄어쓰기 무시)나, 이름의 낱말
    하나('IMF'·'연평'·'6·25')가 원문에 있으면 부른 것이다. 원문을 모르면 참."""
    if text is None:
        return True
    body = _norm_label(text)
    if not body:
        return False
    for name in names:
        if not name:
            continue
        whole = _norm_label(name)
        if whole and whole in body:
            return True
        if any(t in body for t in _ground_tokens(name)):
            return True
    return False


def _connection_year(c: dict) -> int | None:
    y = c.get("year")
    if y is None:
        y = _year_of(c.get("date"))
    return int(y) if y is not None else None


def gate_connections(payload: dict, text: str | None) -> list[str]:
    """이야기가 부르지 않은 역사와 결과보다 늦은 원인을 지운다. 지운 사유를 돌려주고
    `notes` 에도 적는다. `text` 는 이 그래프를 만든 이야기 전부다 (`stories`)."""
    years: dict[str, int] = {}
    for n in payload.get("nodes") or []:
        if n.get("year") is not None:
            years[n["id"]] = int(n["year"])
    for t in payload.get("timeline") or []:
        if t.get("year") is not None:
            years[t["event_id"]] = int(t["year"])
    ids = {n.get("id") for n in payload.get("nodes") or []}
    kept, notes = [], []
    for c in payload.get("historical_connections") or []:
        label = c.get("historical_event") or ""
        pe = c.get("personal_event")
        if pe not in ids:
            notes.append(f"역사 연결 버림 — 개인 사건이 없다: {label} → {pe}")
            continue
        if not grounded(text, label, c.get("node_label"), *(c.get("node_names") or [])):
            notes.append(f"역사 연결 버림 — 이야기가 부르지 않은 사건: {label} → {pe}")
            continue
        hy, py = _connection_year(c), years.get(pe)
        if hy is not None and py is not None and hy > py:
            notes.append(f"역사 연결 버림 — 원인({hy})이 결과({py})보다 뒤: {label} → {pe}")
            continue
        kept.append(c)
    payload["historical_connections"] = kept
    if notes:
        payload["notes"] = list(payload.get("notes") or []) + notes
    return notes


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


