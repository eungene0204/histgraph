"""관계를 사람이 읽는 말로 바꾸는 규칙 — `web/src/lib/relations.js` 의 짝.

원래는 이 규칙을 파이썬으로 옮기지 않았다. 같은 표를 두 벌 두면 한쪽만
고쳐지기 때문이다. 그런데 글로 읽는 장(`pages.py`)이 관계를 목록으로만
세우는 동안 그 장들은 **이름과 링크뿐인 종이**였고, 2026-09-16 애드센스가
그것을 `Low value content` 로 돌려보냈다. 관계를 문장으로 읽어 주는 것은
이 사이트가 남의 백과사전 대신 할 수 있는 말이라, 옮겨 오기로 했다.

두 벌을 두되 **어긋나면 걸리게** 한다 — 저작권 한 줄을 상수 둘에 두고
테스트가 글자까지 재는 것과 같은 방법이다 (CLAUDE.md §1).

    tests/data/sentences.json   두 쪽이 같이 재는 고정판 (관계 → 나와야 할 문장)
    tests/test_pipeline.py      이 파일이 고정판을 그대로 내는가 + 표의 열쇠가 같은가
    web/tests/relations.test.mjs  relations.js 가 **같은 고정판**을 그대로 내는가

그래서 한쪽에 규칙을 더하거나 문구를 고치면 다른 쪽의 시험이 빨개진다.
새 엣지 타입을 들일 때는 세 자리를 같이 연다 (CLAUDE.md §1-6 의 마지막 줄:
"새 엣지 타입은 문장 규칙을 같이 들고 와야 한다").
"""

from __future__ import annotations

# 인과의 종류(`causes.KINDS`)별 문장. 엣지 라벨이 종류다.
KIND_SENTENCE = {
    "원인": lambda a, b: f"{a}{pt(a, '은', '는')} {b}의 원인이 되었다",
    "배경": lambda a, b: f"{a}{pt(a, '은', '는')} {b}의 배경이 되었다",
    "계기": lambda a, b: f"{a}{pt(a, '은', '는')} {b}의 계기가 되었다",
    "영향": lambda a, b: f"{a}{pt(a, '은', '는')} {b}에 영향을 주었다",
}

# 작품을 만든 방식(`creators.ROLES`)별 문장. 타입 이름 하나로 부르면
# "정선이 인왕제색도를 만들었다"가 된다 — 그린 것과 쓴 것과 지은 것은 다르다.
CREATED_SENTENCE = {
    "그림": lambda a, b: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 그렸다",
    "글씨": lambda a, b: f"{a}{pt(a, '이', '가')} {b}의 글씨를 썼다",
    "저술": lambda a, b: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 지었다",
    "편찬": lambda a, b: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 엮었다",
    "제작": lambda a, b: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 만들었다",
    "발원": lambda a, b: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 만들게 했다",
}

# 사건에서 맡은 역할 (§1-6). 역할이 있으면 '참여했다'로 뭉개지 않는다.
ROLE_SENTENCE = {
    "주도": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 주도했다",
    "가담": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}에 가담했다",
    "대항": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}에 맞섰다",
    "피해": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}의 피해자다",
    "표적": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}에서 표적이 되었다",
    "수습": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 수사·재판했다",
    "언급": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b} 기록에 이름이 나온다",
    "근거 없음": lambda a, b, side=None: (
        f"{a}{pt(a, '과', '와')} {b}{pt(b, '은', '는')} 관련이 있다고 하나 근거를 찾지 못했다"),
    # 인포박스 `지휘관N` 은 그 편의 사령관이지 사건 전체의 지휘자가 아니다.
    "지휘관": lambda a, b, side=None: (
        f"{a}{pt(a, '은', '는')} {b}에서 {side} 측을 지휘했다" if side
        else f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 지휘했다"),
    "주요 인물": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}의 주요 인물이다",
    "교전": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}에서 싸웠다",
    "가해": lambda a, b, side=None: f"{a}{pt(a, '은', '는')} {b}의 가해자다",
}

# 인포박스가 이름 뒤에 적은 표식(†·{{KIA}}·☠·‡ → props.fate).
FATE_TAIL = {"사망": "죽었다", "처형": "처형되었다", "피살": "살해되었다",
             "귀양": "귀양 갔다", "포로": "포로가 되었다", "부상": "다쳤다"}
VICTIM_TAIL = {**FATE_TAIL, "사망": "살해되었다"}
COMMANDER_TAIL = {**FATE_TAIL, "사망": "전사했다"}


def pt(word: str, with_batchim: str, without: str) -> str:
    """받침이 있으면 앞말, 없으면 뒷말. '세종은' / '황진이는'."""
    tail = str(word).strip()[-1:] if str(word).strip() else ""
    code = ord(tail) - 0xAC00 if tail else -1
    if code < 0 or code > 11171:
        return without
    return with_batchim if code % 28 else without


def role_sentence(role: str, a: str, b: str, *,
                  fate: str | None = None, side_name: str | None = None) -> str | None:
    make = ROLE_SENTENCE.get(role)
    if make is None:
        return None
    base = make(a, b, side_name)
    if not fate or fate not in FATE_TAIL:
        return base
    if role == "피해":
        return f"{a}{pt(a, '은', '는')} {b}에서 {VICTIM_TAIL[fate]}"
    if role == "지휘관":
        # "…측을 지휘했다" → "…측을 지휘하다 전사했다"
        stem = base[:-len("지휘했다")] + "지휘하다" if base.endswith("지휘했다") else base
        return f"{stem} {COMMANDER_TAIL[fate]}"
    if role in ("주도", "가담", "대항"):
        # "…를 주도했다" → "…를 주도했고 처형되었다"
        stem = base[:-1] + "고" if base.endswith("다") else base
        return f"{stem} {FATE_TAIL[fate]}"
    return base


def _participated_in(a, b, o):
    if o.get("label") in ROLE_SENTENCE:
        return role_sentence(o["label"], a, b, fate=o.get("fate"),
                             side_name=o.get("side_name"))
    return f"{a}{pt(a, '은', '는')} {b}에 참여했다"


def _created(a, b, o):
    return (CREATED_SENTENCE.get(o.get("label")) or CREATED_SENTENCE["제작"])(a, b)


def _member_of(a, b, o):
    # 파조는 그 파가 갈라져 나온 사람이다 — '소속'이라 부르면 수만 명 중
    # 하나라는 말이 된다.
    if o.get("label") == "파조":
        return f"{a}{pt(a, '은', '는')} {b}의 파조다"
    return f"{a}{pt(a, '은', '는')} {b} 소속이다"


def _part_of(a, b, o):
    if o.get("label") == "분파":
        return f"{a}{pt(a, '은', '는')} {b}에서 갈라져 나온 파다"
    return f"{a}{pt(a, '은', '는')} {b}의 일부다"


def _child_of(a, b, o):
    lab = o.get("label")
    role = "어머니" if lab == "어머니" else "아버지" if lab == "아버지" else "부모"
    return f"{a}의 {role}는 {b}{pt(b, '이다', '다')}"


def _dated_to(a, b, o):
    # 인물은 연도와 같은 실체가 아니다 — '출생'·'사망'이 적힌 엣지만 그렇게 읽는다
    lab = o.get("label")
    if lab == "출생":
        return f"{a}{pt(a, '은', '는')} {b}에 태어났다"
    if lab == "사망":
        return f"{a}{pt(a, '은', '는')} {b}에 죽었다"
    return f"{a}의 연표에 {b}{pt(b, '이', '가')} 있다"


def _from_period(a, b, o):
    # 주어가 무엇이냐에 따라 시대를 부르는 말이 다르다 ('진산사건은 1791년
    # 것이다'가 나왔다).
    if o.get("label") in ("출생", "사망"):
        return _dated_to(a, b, o)
    if o.get("srcType") == "person":
        return f"{a}{pt(a, '은', '는')} {b} 사람이다"
    if o.get("srcType") == "event":
        return f"{a}{pt(a, '은', '는')} {b}에 일어난 일이다"
    return f"{a}{pt(a, '은', '는')} {b}의 것이다"


def _related_to(a, b, o):
    lab = o.get("label")
    if lab == "다음":
        return f"{a} 다음에 {b}{pt(b, '이', '가')} 일어났다"
    if lab == "원인":
        return f"{a}{pt(a, '은', '는')} {b}의 원인이 되었다"
    if lab == "이 기사의 대상":
        return f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 다룬 기록이다"
    if lab == "소속":
        return _member_of(a, b, o)
    if lab == "직위":
        return f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 지냈다"
    if lab == "본관":
        return f"{a}의 본관은 {b}{pt(b, '이다', '다')}"
    if lab in CREATED_SENTENCE:
        return CREATED_SENTENCE[lab](a, b)
    if lab in ROLE_SENTENCE:
        return role_sentence(lab, a, b, fate=o.get("fate"), side_name=o.get("side_name"))
    return f"{a}{pt(a, '과', '와')} {b}{pt(b, '은', '는')} 관련이 있다"


# 엣지 방향 그대로 주어와 목적어를 놓는다. src -> dst 순서다.
SENTENCE = {
    "participated_in": _participated_in,
    "occurred_at": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}에서 일어났다",
    "occurred_during": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}에 일어났다",
    "born_in": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}에서 태어났다",
    "died_in": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}에서 죽었다",
    "created": _created,
    "located_in": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}에 있다",
    "depicts": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 다룬다",
    "spouse_of": lambda a, b, o: f"{a}{pt(a, '과', '와')} {b}{pt(b, '은', '는')} 부부다",
    "taught": lambda a, b, o: f"{a}{pt(a, '이', '가')} {b}{pt(b, '을', '를')} 가르쳤다",
    "member_of": _member_of,
    "about": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 주제로 한다",
    "set_in": lambda a, b, o: f"{a}의 배경은 {b}{pt(b, '이다', '다')}",
    "adapted_from": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 원작으로 한다",
    "held_position": lambda a, b, o: f"{a}{pt(a, '은', '는')} {b}{pt(b, '을', '를')} 지냈다",
    "part_of": _part_of,
    "caused": lambda a, b, o: (KIND_SENTENCE.get(o.get("label")) or KIND_SENTENCE["원인"])(a, b),
    "related_to": _related_to,
    "child_of": _child_of,
    "dated_to": _dated_to,
    "from_period": _from_period,
}


def sentence(rel: dict, self_node: dict) -> str:
    """지금 보는 노드(`self_node`)와 상대 사이의 관계 하나를 문장으로.

    `relations.js` 의 `sentence(r, self)` 와 같은 일을 한다."""
    me = {"label": self_node.get("label", ""), "type": self_node.get("type")}
    # 인과의 상대가 서술구('후금의 파약 행위')로 적혀 있었으면 그 구로 부른다.
    other = dict(rel["other"])
    if rel["type"] == "caused" and rel.get("as"):
        other["label"] = rel["as"]
    src, dst = (me, other) if rel.get("dir") == "out" else (other, me)
    make = SENTENCE.get(rel["type"])
    if make is None:
        return f"{src['label']} → {dst['label']} · {rel.get('label', '')}".strip(" ·")
    return make(src["label"], dst["label"], {
        "label": rel.get("edge_label"),
        "srcType": src.get("type"),
        "fate": rel.get("fate"),
        "side_name": rel.get("side_name"),
    })
