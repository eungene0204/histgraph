"""그래프 오염 필터.

실측 배경: Wikidata 의 `participated_in`(P1344) 엣지 5,791건 중 90.5%가
올림픽·아시안게임 출전 기록이었다. 역사 그래프에서 이것들은 노이즈이며,
"인물이 어떤 사건에 얽혔는가"라는 핵심 질문을 완전히 가려버린다.

두 층위로 거른다:
  1) Wikidata 클래스(P31) — 정확하지만 클래스가 없으면 못 잡는다
  2) 라벨 정규식 — 클래스가 비어 있는 항목까지 잡는 보완재
"""

from __future__ import annotations

import re

# 스포츠 이벤트/조직 Wikidata 클래스
SPORTS_CLASSES: frozenset[str] = frozenset({
    "Q13406554",   # 스포츠 대회
    "Q18608583",   # 반복 개최 스포츠 대회
    "Q46190676",   # 스포츠 시즌
    "Q27020041",   # 스포츠 시즌 (팀)
    "Q16510064",   # 스포츠 이벤트
    "Q1656682",    # (일반 사건 — 스포츠 아님, 오탐 방지용 제외 대상 아님)
    "Q500834",     # 토너먼트
    "Q159821",     # 올림픽
    "Q193581",     # 하계 올림픽
    "Q82414",      # 동계 올림픽
    "Q1478437",    # 아시안 게임
    "Q476300",     # 축구 대회
    "Q15991290",   # 스포츠 경기
})
# Q1656682(사건)는 일반 사건이므로 제외 목록에서 뺀다.
SPORTS_CLASSES = SPORTS_CLASSES - {"Q1656682"}

# 라벨 기반 보완 필터. P31 이 비어 있거나 목록에 없는 대회를 잡는다.
SPORTS_LABEL = re.compile(
    # 한국어
    r"올림픽|패럴림픽|아시안\s?게임|아시안컵|월드컵|선수권|유니버시아드|"
    r"체육\s?대회|체전|베이스볼\s?클래식|프리미어\s?리그|K리그|"
    r"플레이오프|그랑프리|마스터스|오픈|"
    # 영어. `\bGames\b` 는 'Asian Winter Games', 'Military World Games' 처럼
    # 수식어가 끼어드는 형태를 한 번에 잡는다.
    r"Olympi|Paralympi|\bGames\b|\bCup\b|Championship|Grand\s+Prix|"
    r"Super\s?Series|UCI\s|Masters|Open\b|League|Season|Tournament|"
    r"Baseball\s+Classic|FIFA|AFC\b|IAAF|Universiade|"
    # 'women's doubles', 'men's singles' 같은 종목 세부 항목
    r"\b(?:doubles|singles)\b|"
    # 'figure skating at the 2003 …' 형태의 종목별 세부 항목
    r"\sat\s+the\s+\d{4}",
    re.IGNORECASE,
)

# 스포츠 종목 직업 — 인물 노드 필터링용 (선택적)
ATHLETE_OCCUPATIONS: frozenset[str] = frozenset({
    "Q2066131",    # 운동선수
    "Q937857",     # 축구선수
    "Q3665646",    # 농구선수
    "Q10871364",   # 야구선수
    "Q13141064",   # 배드민턴선수
    "Q11513337",   # 육상선수
})


def is_sports(label: str | None, type_qid: str | None = None) -> bool:
    """스포츠 이벤트로 판단되면 True.

    클래스 우선, 없으면 라벨로 판정한다."""
    if type_qid and type_qid in SPORTS_CLASSES:
        return True
    if label and SPORTS_LABEL.search(label):
        return True
    return False


# NOTE: SQL LIKE 판본은 의도적으로 두지 않는다. 정규식과 LIKE 목록을
# 나란히 유지하면 반드시 갈라진다 — 실제로 갈라져서 'Open'/'Series' 가
# 빠진 SQL 쪽이 배드민턴 대회를 통과시켰다. 판정은 is_sports() 하나로만
# 하고, 대량 삭제도 파이썬에서 라벨을 훑어 처리한다.
