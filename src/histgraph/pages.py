"""사람과 로봇이 **글로** 읽는 장 (`/인물/세종`·`/사건/임진왜란`).

화면(`web/`)은 자바스크립트가 그리는 관계망이라, 검색 로봇과 광고 심사의
눈에는 빈 화면이다 — `index.html` 이 내주는 것은 `<div id="root">` 하나뿐이고
인물도 사건도 그 안에 없다. 그래서 같은 자료를 한 번 더, 이번에는 **문서로**
낸다. 자료는 `GraphAPI.node` 가 주는 것 그대로다.

상세 패널(`web/src/components/DetailPanel.jsx`)과 같은 것을 그리지만 같은
일을 하지 않는다. 저쪽은 **파고드는** 자리라 근거 구절·인과 사슬·자취까지
붙고, 이쪽은 **읽는** 자리라 이름·설명·이어진 것에서 멈춘다. 관계를 문장으로
바꾸는 규칙(`relations.js` 의 SENTENCE)은 옮겨 오지 않았다 — 같은 규칙을 두
벌 두면 한쪽만 고쳐진다.

여기도 §1 이 그대로 걸린다: 사람이 읽는 자리에 영어를 쓰지 않는다. **주소도
사람이 읽는 자리다** — 그래서 주소의 칸도 한글이다 (`slugs.py`). 자료
출처는 **설명 아래 한 줄**에만 적는다 — 라이선스 의무라서 두는 예외다
(provenance.py). 다른 자리에는 여전히 안 적는다.

**설명은 요약까지만 낸다.** 2026-09-05 애드센스가 이 사이트를 '주의 필요'로
돌려보냈다. 그때 이 장은 설명 칸을 통째로 뿌리고 있었다 — 세조 25,093자,
태조 18,787자, `== 생애 ==` 위키 문법까지 그대로. 로봇에게 그것은 남의
백과사전을 긁어 온 페이지였다. 그래서 지금은 (1) 설명은 첫 몇 문장까지만,
(2) 이 사이트만 아는 것 — 언제의 무엇이고 무엇과 몇 건이나 이어졌는지 — 를
이 사이트의 말로 먼저 적고, (3) 그 둘이 다 얇은 장은 색인에 올리지 않는다.

장의 짜임은 넷이다 (2026-09-11):

    이름 · 갈래 · 시기      제목과 그 아래 한 줄
    이 사이트의 말 · 요약    무엇이고 몇 건과 이어졌는지, 그다음 원문 요약
    주요 사실 · 연표        속성처럼 읽히는 관계(시대·소재지·직위)와 연도가 있는 이웃
    이어진 것              관련 인물 · 사건 · 장소 · 유산과 작품 · 시대와 자리

로봇이 읽는 것은 그 위에 얹는다 — `JSON-LD`(Schema.org)·정본 주소·여는 그림·
빵부스러기. **화면에는 한 자도 더 세우지 않는다**: 그것들은 `<script>`·
`<meta>` 안에 있고 사람이 보는 글자가 아니다.
"""

from __future__ import annotations

import json
import os
import re
from html import escape
from typing import NamedTuple
from urllib.parse import quote, unquote

from . import slugs
from .ontology import NODE_TYPES

# 링크를 절대 주소로 적어야 하는 자리(정본 주소·사이트맵). 배포 도메인이
# 바뀌면 여기 하나만 고친다.
SITE = os.environ.get("HISTGRAPH_SITE", "https://www.histgraph.space").rstrip("/")

# 광고. 화면 세 장(`web/index.html`·`privacy.html`·`terms.html`)에 걸어 둔
# 것과 같은 번호다.
ADS_CLIENT = "ca-pub-8335444243080631"

# 서치 콘솔이 주인을 확인하는 표. 없으면 아무것도 안 적는다 — 빈 값을
# 적으면 구글이 그 자리를 보고 '표가 틀렸다'고 답한다.
VERIFICATION = os.environ.get("HISTGRAPH_SITE_VERIFICATION", "").strip()

# 카카오톡·슬랙·트위터가 링크를 펼칠 때 세우는 그림. 노드마다 제 그림이
# 있으면 그것을 쓰고(유산은 국가유산청이 준다), 없으면 이 한 장이다.
OG_IMAGE = f"{SITE}/og.png"
OG_IMAGE_ALT = "histgraph — 한국사 관계망"

# 저작권 한 줄. **화면에 영어를 두지 않는 규칙(CLAUDE.md §1)의 두 번째
# 예외다** (2026-09-09 사용자 결정: "원문 그대로"). 저작권 표시는 나라를
# 가리지 않고 이 문구로 굳었으므로 옮기지 않는다. 예외는 이 한 줄뿐이고,
# 방침·약관과 그래프 화면에는 세우지 않는다.
COPYRIGHT = "© 2026 histgraph. All rights reserved."

# 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다. `child_of` 는
# 'A → B = A 가 B 의 자녀'라, 나가는 상대는 부모이고 들어오는 상대가 자녀다.
# (같은 표가 `web/src/lib/relations.js` 의 DIR_HEAD 에도 있다. 방향이 뜻을
#  갖는 타입은 셋뿐이라 옮겨 적었다 — 늘어나면 서버가 내주는 편이 맞다.)
DIR_HEAD = {
    "child_of": {"out": "부모", "in": "자녀"},
    "part_of": {"out": "상위", "in": "하위"},
    "caused": {"out": "결과", "in": "원인"},
}
TIME_TYPES = ("from_period", "dated_to")
ROLE_HEADS = frozenset({"주도", "가담", "대항", "피해", "표적", "수습", "지휘관", "주요 인물", "교전", "가해"})
# 라벨이 타입보다 정확한 관계 (`relations.js` LABEL_HEADS 와 같은 표)
LABEL_DIR_HEAD = {"다음": {"out": "다음 일", "in": "앞선 일"},
                  "이 기사의 대상": {"out": "이 기록이 다루는 것", "in": "이것을 다룬 기록"},
                  # 씨족이 적는 라벨 둘 (`clans.py`) — 파 → 상위, 본관 → 지명.
                  "분파": {"out": "속한 문중", "in": "갈라진 파"},
                  "본관": {"out": "본관 지명", "in": "이곳을 본관으로 하는 씨족"},
                  # 작품에 적힌 만든 방식 (`creators.ROLES`). 타입 이름 '제작'
                  # 하나로는 그린 것·쓴 것·지은 것·엮은 것이 뭉개진다.
                  "그림": {"out": "그린 것", "in": "그린 사람"},
                  "글씨": {"out": "글씨를 쓴 것", "in": "글씨를 쓴 사람"},
                  "저술": {"out": "지은 것", "in": "지은 사람"},
                  "편찬": {"out": "엮은 것", "in": "엮은 사람"},
                  "제작": {"out": "만든 것", "in": "만든 사람"},
                  "발원": {"out": "만들게 한 것", "in": "만들게 한 사람"}}
LABEL_HEADS = ROLE_HEADS | set(LABEL_DIR_HEAD) | {"소속", "직위", "파조"}

# 한 묶음에 이만큼까지만 적는다. 세종의 '자녀'처럼 수십이 붙는 자리가
# 있는데, 문서로 읽는 화면에서 목록이 화면을 넘기면 아무도 안 읽는다.
GROUP_MAX = 30

# 설명을 이만큼까지만 낸다 (문장 단위로 끊으므로 조금 넘을 수 있다). 인물
# 항목의 도입부 한 문단이 대개 300~400자다 — 그 너머는 원문을 옮기는 일이지
# 이 장이 할 말이 아니다.
SUMMARY_MAX = 360

# 색인에 올리는 문턱. 요약이 이보다 짧고 이어진 것이 이보다 적으면 장에
# 읽을 것이 없다 — 설명이 '화가' 한 낱말인 장이 3,382개였고, 그런 장이
# 6,810개 색인 속에 깔려 읽을 것이 있는 장을 묻었다. 두 조건은 **모두**
# 넘어야 한다: 설명이 길어도 아무것과 안 이어졌으면 이 사이트에 있을 까닭이
# 없고, 관계가 많아도 설명이 한 줄이면 목록일 뿐이다.
MIN_SUMMARY = 120
MIN_RELATIONS = 3

# 위키 문법의 절 제목 (`== 생애 ==`). 본문 전체를 받은 설명에 남아 있다.
_HEADING = re.compile(r"^=+[ \t]*.+?[ \t]*=+[ \t]*$", re.M)
# 문장 끝. '다.' '이다.' 뒤에 공백이나 줄바꿈이 오는 자리에서 끊는다.
# 괄호 안의 '(음력 4월 10일)~1450년 3월 30일)' 같은 마침표 없는 구절은
# 여기 안 걸리므로 문장 중간이 잘리지 않는다.
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


class Page(NamedTuple):
    """장 하나. `location` 은 301 일 때만 찬다.

    옛 주소(`/n/wd:Q12345`)를 끊지 않고 새 주소로 보내려면 헤더가 있어야
    한다 — 튜플 셋으로는 그 말을 할 수 없어 자리를 하나 늘렸다."""

    status: int
    ctype: str
    body: str
    location: str | None = None


def summarize(text: str | None, limit: int = SUMMARY_MAX) -> str:
    """설명에서 **도입부 몇 문장**만 남긴다.

    1. 첫 절 제목 앞까지가 도입부다. `== 생애 ==` 도, 마침표 없이 짧게
       끝나는 줄('출생과 성장')도 제목이다. 글머리의 제목('머리말')은
       건너뛴다.
    2. 문장 단위로 이어 붙이다 `limit` 를 넘기면 멈춘다. 첫 문장 하나가
       이미 넘으면 그 문장은 통째로 둔다 — 문장 중간을 자르면 뜻이 남지
       않는다.
    """
    if not text:
        return ""
    # 절 제목은 두 꼴이다. 위키 문법 `== 생애 ==`, 그리고 민족문화대백과·
    # 국편 글이 본문 사이에 세우는 마침표 없는 짧은 줄('출생과 성장',
    # '호방한 기상으로 세상을 놀라게 하다'). 어느 쪽이든 **첫 제목 앞까지가
    # 도입부**다 — 제목 뒤는 절의 본문이라 이어 붙이면 뜻이 끊긴다. 글머리에
    # 선 제목('머리말')은 건너뛰고 읽는다. 제목뿐인 설명('화가')은 그대로
    # 둔다 — 지우면 빈 설명이 되어 화면이 '아직 못 받아왔다'고 거짓을 말한다.
    lines = [ln.strip() for ln in _HEADING.sub(lambda m: m.group(0).strip("= \t"),
                                               text).split("\n") if ln.strip()]
    prose: list[str] = []
    for line in lines:
        if _is_heading_line(line):
            if prose:
                break
            continue
        prose.append(line)
    text = " ".join(prose if prose else lines)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    out: list[str] = []
    size = 0
    for sentence in _SENTENCE_END.split(text):
        if out and size + len(sentence) > limit:
            break
        out.append(sentence)
        size += len(sentence) + 1
    return " ".join(out).strip()


def _is_heading_line(line: str) -> bool:
    return len(line) <= 40 and not line.endswith((".", "!", "?", "。", "다", "”", "」", ")"))


def plain_description(text: str | None) -> str:
    """설명 전문에서 위키 문법만 걷어 낸다 (`== 생애 ==` → `생애`). 상세
    패널이 전문을 보일 때 쓴다 — 요약이 아니라 **문법**만 지우는 자리다."""
    if not text:
        return ""
    return _HEADING.sub(lambda m: m.group(0).strip("= \t"), text)


def indexable(summary: str, relations: int) -> bool:
    """이 장을 색인에 올릴 만한가. 문턱은 위의 두 상수다."""
    return len(summary) >= MIN_SUMMARY and relations >= MIN_RELATIONS


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침이 있으면 앞말, 없으면 뒷말. '세종은' / '황진이는'.
    (`relations.js` 의 pt 와 같다 — 조사는 문법이지 규칙표가 아니다.)"""
    tail = word.strip()[-1:] if word.strip() else ""
    code = ord(tail) - 0xAC00 if tail else -1
    if code < 0 or code > 11171:
        return without
    return with_batchim if code % 28 else without

STYLE = """
:root {
  color-scheme: dark;
  /* Obsidian 의 기본 다크 테마 — 값은 web/style.css 와 같다 (설명은 design.md). */
  --background-primary:   #1e1e1e;
  --background-secondary: #262626;
  --background-modifier-border: #363636;
  --background-modifier-hover: rgba(255,255,255,.075);
  --text-normal: #dadada;
  --text-muted:  #b3b3b3;
  --text-faint:  #666666;
  --color-accent: hsl(254 80% 68%);
  --color-accent-2: hsl(254 80% 78%);
  --radius-s: 4px; --radius-m: 8px;
  --file-line-width: 700px;
  --font-interface: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
                    "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
  /* 옛 이름 다리 */
  --surface: var(--background-primary); --surface-2: var(--background-secondary);
  --line: var(--background-modifier-border);
  --text: var(--text-normal); --text-2: var(--text-muted); --text-3: var(--text-faint);
  --accent: var(--color-accent);
  --font: var(--font-interface);
  --actor: #3d84f5; --event: #fb6c13; --thing: #2e9e5e; --frame: #2a5d78;
}
* { box-sizing: border-box; }
html { background: var(--background-primary); }
body {
  margin: 0; background: var(--background-primary); color: var(--text-normal);
  font-family: var(--font-interface); font-size: 16px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
::selection { background: hsla(254 80% 68% / .25); }
.top { border-bottom: 1px solid var(--background-modifier-border); background: var(--background-secondary); }
.top a {
  display: flex; align-items: center; gap: 8px;
  max-width: var(--file-line-width); margin: 0 auto; padding: 10px 22px;
  color: var(--text-normal); text-decoration: none; font-weight: 600; font-size: 13px; letter-spacing: -0.01em;
}
.top .mark {
  width: 13px; height: 13px; border-radius: 50%; background: var(--actor);
  box-shadow: 9px 5px 0 -3px var(--event), 16px -3px 0 -4px var(--thing);
}
.top .back { margin-left: auto; font-weight: 400; font-size: 12px; color: var(--text-muted); }
.top a:hover .back { color: var(--color-accent); }
main { max-width: var(--file-line-width); margin: 0 auto; padding: 36px 22px 70px; }
/* 빵부스러기. 로봇은 아래 JSON-LD 로 읽고 사람은 이 줄로 읽는다. */
.crumb { color: var(--text-faint); font-size: 12px; margin: 0 0 14px; }
.crumb a { color: var(--text-muted); text-decoration: none; }
.crumb a:hover { color: var(--color-accent); }
.crumb span { margin: 0 6px; color: var(--text-faint); }
h1 { color: var(--text-normal); font-size: 1.8em; font-weight: 700; line-height: 1.2; letter-spacing: -0.02em; margin: 0 0 8px; }
h1 .also { color: var(--text-muted); font-weight: 400; font-size: .65em; margin-left: 8px; }
.kind { display: flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 13px; margin: 0 0 24px; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.lead { color: var(--text-normal); font-size: 17px; margin: 0 0 14px; }
.desc { color: var(--text-normal); font-size: 16px; margin: 0 0 8px; }
.src { color: var(--text-faint); font-size: 12px; margin: 0 0 18px; }
.src a { color: var(--text-faint); text-decoration: underline; text-underline-offset: 2px; }
.src a:hover { color: var(--color-accent); }
.empty {
  color: var(--text-muted); font-size: 14px; margin: 0 0 18px;
  background: rgba(255,255,255,.04); border-left: 3px solid #555555; border-radius: var(--radius-s); padding: 10px 14px;
}
.aka { color: var(--text-muted); font-size: 13px; margin: 0 0 8px; }
h2 a { color: inherit; text-decoration: none; }
h2 a:hover { color: var(--color-accent); }
h2 { color: var(--text-normal); font-size: 1.25em; font-weight: 600; line-height: 1.3; margin: 34px 0 12px; }
h3 { color: var(--text-muted); font-size: 13.5px; font-weight: 600; margin: 26px 0 2px; }
.head { color: var(--text-faint); font-size: 12px; font-weight: 600; margin: 14px 0 4px; }
ul { list-style: none; margin: 0; padding: 0; }
li { display: flex; align-items: center; gap: 8px; padding: 3px 6px; margin: 0 -6px; border-radius: var(--radius-s); font-size: 15px; }
li:hover { background: var(--background-modifier-hover); }
li a { color: var(--text-normal); text-decoration: none; }
li a:hover { color: var(--color-accent); text-decoration: underline; text-underline-offset: 2px; }
li .meta { color: var(--text-faint); font-size: 12px; }
.more { color: var(--text-faint); font-size: 12.5px; padding: 4px 0; }
/* 주요 사실 — 속성처럼 읽히는 관계(시대·소재지·직위)를 표로 세운다. */
.facts { margin: 0 0 4px; }
.facts div { display: flex; gap: 12px; padding: 5px 6px; margin: 0 -6px; border-radius: var(--radius-s); font-size: 15px; }
.facts div:hover { background: var(--background-modifier-hover); }
.facts dt { flex: none; width: 84px; color: var(--text-faint); font-size: 12.5px; padding-top: 2px; }
.facts dd { margin: 0; color: var(--text-normal); }
.facts dd a { color: var(--text-normal); text-decoration: none; }
.facts dd a:hover { color: var(--color-accent); text-decoration: underline; text-underline-offset: 2px; }
.facts dd span { color: var(--text-faint); }
/* 연표 — 해와 이름 두 칸. */
.marks li { align-items: baseline; }
.marks .when { flex: none; width: 84px; color: var(--text-faint); font-size: 12.5px; }
.open {
  display: inline-block; margin-top: 26px; padding: 7px 14px;
  border: 1px solid var(--background-modifier-border); border-radius: 5px;
  color: var(--text-muted); text-decoration: none; font-size: 13px;
}
.open:hover { color: var(--text-normal); background: var(--background-modifier-hover); }
.pager { display: flex; gap: 14px; margin-top: 30px; font-size: 13px; }
.pager a { color: var(--text-muted); text-decoration: none; }
.pager a:hover { color: var(--color-accent); }
.foot {
  max-width: var(--file-line-width); margin: 0 auto; padding: 0 22px 60px;
  color: var(--text-faint); font-size: 12px;
}
.foot a { color: var(--text-faint); text-decoration: none; }
.foot a:hover { color: var(--color-accent); }
.foot span { margin: 0 7px; }
/* 저작권 한 줄. 여기만 영어다 (2026-09-09 사용자 결정) — 저작권 표시는
   관례로 굳은 문구라 옮기지 않는다. 화면의 다른 글자는 그대로 한국어다. */
.foot .copy { text-align: center; margin-top: 12px; letter-spacing: -0.01em; }
"""

GROUP_COLOR = {"actor": "var(--actor)", "event": "var(--event)",
               "thing": "var(--thing)", "frame": "var(--frame)"}

# 타입 → 갈래. `server.TYPE_GROUP` 과 같은 표다 (서버를 들여오면 순환한다).
_GROUP = {"person": "actor", "org": "actor", "event": "event",
          "place": "thing", "heritage": "thing", "artwork": "thing",
          "media": "thing", "period": "frame", "role": "frame",
          "concept": "frame"}

# --- Schema.org ------------------------------------------------------------
# 로봇이 이 장을 무엇으로 읽을지. **타입을 새로 만들지 않는다** — 우리
# 온톨로지의 아홉 타입을 Schema.org 의 가장 가까운 이름에 댄다. 없으면
# `Thing` 이다: 틀린 이름을 대는 것보다 낫다 (구조화 데이터는 틀리면
# 검색 결과에서 통째로 버려진다).
SCHEMA_TYPE = {
    "person": "Person",
    "event": "Event",
    "place": "Place",
    "org": "Organization",
    "heritage": "CreativeWork",
    "artwork": "CreativeWork",
    "period": "Thing",
    "role": "Thing",
    "concept": "DefinedTerm",
}
# 매체는 갈래가 곧 종류다 (`ontology.FORMS`).
SCHEMA_FORM = {"film": "Movie", "series": "TVSeries", "documentary": "Movie",
               "animation": "Movie", "book": "Book", "comic": "CreativeWork",
               "game": "VideoGame", "music": "MusicRecording", "stage": "CreativeWork"}

# 날짜로 내보낼 수 있는 꼴만 (`1592`·`1592-04`·`1592-04-13`·`-0220`).
_ISO_DATE = re.compile(r"^-?\d{4}(-\d{2}(-\d{2})?)?$")

# 속성처럼 읽히는 관계. 목록 더미에 섞어 두면 '조선'과 '황희'가 같은 무게로
# 선다 — 앞의 표로 올리고 아래 목록에서는 뺀다. (종류, 방향) → 이름.
FACT_HEADS = {
    ("from_period", "out"): "시대",
    ("born_in", "out"): "출생지",
    ("died_in", "out"): "사망지",
    ("located_in", "out"): "소재지",
    ("occurred_at", "out"): "장소",
    ("held_position", "out"): "직위",
    ("member_of", "out"): "소속",
    ("created", "in"): "만든 사람",
}
FACT_ORDER = ["시대", "장소", "소재지", "출생지", "사망지", "직위", "소속", "만든 사람"]
# 한 사실에 이만큼까지. 직위가 열둘인 사람이 있는데 표가 화면을 넘기면
# 그 아래 것을 아무도 못 본다.
FACT_MAX = 6

# '이어진 것'을 가르는 큰 칸. **상대가 무엇인가**로 가른다 — 관계 이름
# (부모·주도·소재지)만으로 묶으면 인물과 시대가 한 줄 걸러 섞인다.
SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("관련 인물", ("person",)),
    ("관련 사건", ("event",)),
    ("관련 단체", ("org",)),
    ("관련 장소", ("place",)),
    ("관련 유산과 작품", ("heritage", "artwork", "media")),
    ("시대와 자리", ("period", "role", "concept")),
]
# 연표에 점으로 찍는 타입. 사람·장소는 이어지는 것이라 한 점에 못 찍는다
# (`server` 의 연표와 같은 판단).
MARK_TYPES = ("event", "heritage", "artwork", "media", "org", "period")
MARK_MAX = 24


def _year(value: str | None) -> str:
    """'1397-01-01' → '1397년'. 기원전은 앞말을 붙여 적는다."""
    if not value:
        return ""
    text = str(value)
    neg = text.startswith("-")
    digits = ""
    for ch in text.lstrip("-"):
        if not ch.isdigit():
            break
        digits += ch
    if not digits:
        return ""
    # 기원전은 한 해 옮겨 적는다 (`timeline.bce_text` 머리글).
    return f"기원전 {int(digits) + 1}년" if neg else f"{int(digits)}년"


def _year_num(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value)
    digits = ""
    for ch in text.lstrip("-"):
        if not ch.isdigit():
            break
        digits += ch
    if not digits:
        return None
    return -int(digits) if text.startswith("-") else int(digits)


def _why_empty(node: dict) -> str:
    """빈 설명의 이유. 뭉뚱그려 '자료 없음'이라 적으면, 더 받아오면 채워지는
    노드와 애초에 채울 것이 없는 노드가 같은 말을 하게 된다."""
    if node.get("source") == "timeline":
        return "연표의 해를 세우는 노드라 설명이 없습니다."
    if node.get("source") == "extract":
        return "산문에서 이름만 추출된 노드라 원문이 없습니다."
    if node.get("desc_dropped"):
        return "한국어로 옮길 수 있는 설명이 아직 없습니다."
    return "아직 서사를 받아오지 않았습니다."


def _head(rel: dict) -> str:
    # 타입으로 막지 않는다 — 이기는 것은 표에 적힌 라벨뿐이다
    # (`relations.js` relHead·`server._rel_name` 과 같은 규칙).
    if rel["type"] in TIME_TYPES:
        return "시기" if rel["dir"] == "out" else "이 시기의 개체"
    lab = rel.get("edge_label")
    if lab in LABEL_DIR_HEAD:
        return LABEL_DIR_HEAD[lab][rel["dir"]]
    if lab in LABEL_HEADS:
        return lab   # '피해'·'주도'·'소속'·'파조'
    return DIR_HEAD.get(rel["type"], {}).get(rel["dir"]) or rel["label"]


def _facts(relations: list[dict]) -> tuple[list[tuple[str, list[dict]]], list[dict]]:
    """속성처럼 읽히는 관계를 앞의 표로 올린다. (표, 남은 관계).

    **라벨이 따로 적힌 관계는 올리지 않는다** — '직위'라도 편집 계층이
    '이 사람이 오른 자리'라고 더 정확히 적어 두었으면 그 말이 이긴다."""
    picked: dict[str, list[dict]] = {}
    rest: list[dict] = []
    for rel in relations or []:
        name = FACT_HEADS.get((rel["type"], rel["dir"]))
        if name is None or (rel.get("edge_label") in LABEL_DIR_HEAD):
            rest.append(rel)
            continue
        bucket = picked.setdefault(name, [])
        if not any(r["other"]["id"] == rel["other"]["id"] for r in bucket):
            bucket.append(rel)
    table = [(n, picked[n]) for n in FACT_ORDER if n in picked]
    return table, rest


def _sections(relations: list[dict]) -> list[tuple[str, list[tuple[str, list[dict]]]]]:
    """관계를 큰 칸(상대의 갈래) → 묶음(관계 이름)으로 정리한다.

    한 묶음 안에서 같은 상대는 한 줄이다 — 시대와 시점이 둘 다 걸린 해가
    두 번 나오지 않게. 묶음의 차례는 **역할이 먼저**다 (§1-6: 피해·주도는
    사건의 얼굴이라 '관련' 더미에 묻히면 안 된다), 그다음 큰 묶음 순이다.
    """
    bucket_of: dict[str, str] = {}
    for title, types in SECTIONS:
        for t in types:
            bucket_of[t] = title
    grouped: dict[str, dict[str, list[dict]]] = {}
    order: dict[str, dict[str, int]] = {}
    for rel in relations or []:
        title = bucket_of.get(rel["other"]["type"], SECTIONS[-1][0])
        head = _head(rel)
        heads = grouped.setdefault(title, {})
        bucket = heads.setdefault(head, [])
        order.setdefault(title, {}).setdefault(head, len(heads))
        if any(r["other"]["id"] == rel["other"]["id"] for r in bucket):
            continue
        bucket.append(rel)
    out = []
    for title, _types in SECTIONS:
        heads = grouped.get(title)
        if not heads:
            continue
        ranked = sorted(
            heads.items(),
            key=lambda kv: (0 if kv[0] in ROLE_HEADS else 1,
                            -len(kv[1]), order[title][kv[0]]),
        )
        out.append((title, ranked))
    return out


def _lead(title: str, kind: str, era: str,
          sections: list[tuple[str, list[tuple[str, list[dict]]]]],
          facts: list[tuple[str, list[dict]]], total: int) -> str:
    """이 사이트의 말로 적는 첫 문단. 원문을 옮기지 않고 관계망이 아는
    것만 말한다 — 언제의 무엇이고, 무엇과 몇 건이나 이어졌는지.

    '조선 세종은 조선의 인물입니다. 자녀 18 · 사건 9 · 시기 3 등 모두 87건과
    이어져 있습니다.' 생몰은 바로 위 갈래 줄에 있으니 되풀이하지 않는다.
    """
    first = f"{title}{_josa(title, '은', '는')} {era}{kind}입니다."
    if not total:
        return first
    heads = [(head, len(rels)) for _title, ranked in sections for head, rels in ranked]
    heads += [(name, len(rels)) for name, rels in facts]
    heads.sort(key=lambda x: -x[1])
    shown = " · ".join(f"{head} {n}" for head, n in heads[:4])
    rest = " 등" if len(heads) > 4 else ""
    return f"{first} {shown}{rest} 모두 {total}건과 이어져 있습니다."


def _origin_line(origin: dict | None) -> str:
    """설명 아래 출처 한 줄. '한국어 위키백과 문서를 줄인 글입니다 ·
    크리에이티브 커먼즈 저작자표시-동일조건변경허락 4.0'. 이름과 라이선스는
    각각 그 주소로 이어진다. 출처를 모르면 빈 문자열 — 아무것도 안 적는다.
    (§1 의 예외 — provenance.py 머리말.)"""
    if not origin:
        return ""
    name = escape(origin["name"])
    if origin.get("url"):
        name = f'<a href="{escape(origin["url"])}" rel="nofollow">{name}</a>'
    text = (f"{name} 문서를 바탕으로 새로 쓴 글입니다" if origin.get("rewritten")
            else f"{name} 문서를 줄인 글입니다")
    if origin.get("license"):
        lic = escape(origin["license"])
        if origin.get("license_url"):
            lic = f'<a href="{escape(origin["license_url"])}" rel="license nofollow">{lic}</a>'
        text += f" · {lic}"
    return text


def href(path: str) -> str:
    """주소 한 줄. 한글은 퍼센트로 적는다 — 브라우저는 풀어서 보여 주고
    사이트맵·`canonical` 은 이 꼴이라야 규격에 맞는다. 물음표 뒤(`?p=2`)는
    주소가 아니라 물음이라 그대로 둔다."""
    base, sep, tail = path.partition("?")
    return escape(quote(base, safe="/") + sep + tail)


def _url_of(node_id: str, paths: dict[str, str]) -> str:
    """그 노드로 가는 길. 주소를 아직 못 받은 노드는 `/n/<id>` 로 물러난다
    (`slugs.assign` 을 안 돌린 DB 에서도 링크가 죽지 않게)."""
    return paths.get(node_id) or f"/n/{node_id}"


def _link(other: dict, paths: dict[str, str]) -> str:
    color = GROUP_COLOR.get(other.get("group"), "var(--frame)")
    kind = other.get("type_label") or NODE_TYPES.get(other.get("type"), "")
    return (
        f'<li><span class="dot" style="background:{color}"></span>'
        f'<a href="{href(_url_of(other["id"], paths))}">{escape(other["label"])}</a>'
        f'<span class="meta">{escape(kind)}</span></li>'
    )


def _crumbs(items: list[tuple[str, str | None]]) -> str:
    """빵부스러기 한 줄. (이름, 주소) — 마지막 칸은 주소가 없다."""
    parts = []
    for name, url in items:
        parts.append(f'<a href="{href(url)}">{escape(name)}</a>' if url
                     else f"<b>{escape(name)}</b>")
    return '<p class="crumb">' + '<span>›</span>'.join(parts) + "</p>"


def _crumb_ld(items: list[tuple[str, str | None]], canonical: str) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name,
             "item": (SITE + quote(url, safe="/")) if url else canonical}
            for i, (name, url) in enumerate(items)
        ],
    }


def _ld_block(*, canonical: str, title: str, description: str,
              crumbs: list[tuple[str, str | None]], entity: dict | None = None,
              related: list[str] | None = None) -> str:
    """로봇이 읽는 구조화 데이터 한 덩이 (`@graph`).

    장(WebPage)과 그 장이 다루는 것(entity)을 따로 적고 `mainEntity` 로
    잇는다. 둘을 한 덩이로 적으면 '세종이라는 이름의 웹페이지'가 된다.
    """
    page: dict = {
        "@type": "WebPage",
        "@id": f"{canonical}#page",
        "url": canonical,
        "name": title,
        "description": description,
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "@id": f"{SITE}/#site",
                     "name": "histgraph", "url": f"{SITE}/"},
        "breadcrumb": _crumb_ld(crumbs, canonical),
    }
    if related:
        page["relatedLink"] = related
    graph = [page]
    if entity is not None:
        page["mainEntity"] = {"@id": entity["@id"]}
        graph.append(entity)
    return ('<script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": graph},
                         ensure_ascii=False, separators=(",", ":"))
            + "</script>")


def _entity_ld(node: dict, canonical: str, summary: str,
               facts: list[tuple[str, list[dict]]],
               sections: list[tuple[str, list[tuple[str, list[dict]]]]],
               paths: dict[str, str], image: str | None) -> dict:
    """이 장이 다루는 것 하나. 관계는 **뜻이 맞는 자리에만** 적는다 —
    Schema.org 에 없는 관계를 억지로 대면 구조화 데이터 전체가 버려진다."""
    kind = SCHEMA_TYPE.get(node["type"], "Thing")
    if node["type"] == "media":
        kind = SCHEMA_FORM.get(node.get("form") or "", "CreativeWork")
    ld: dict = {
        "@type": kind,
        "@id": f"{canonical}#entity",
        "name": node["names"][0] if node.get("names") else node["label"],
        "url": canonical,
        "mainEntityOfPage": {"@id": f"{canonical}#page"},
    }
    if summary:
        ld["description"] = summary
    if image:
        ld["image"] = image
    other_names = [n for n in (node.get("names") or [])[1:]] + list(node.get("aliases") or [])
    if other_names:
        ld["alternateName"] = other_names[:12]
    start, end = node.get("start"), node.get("end")
    if kind == "Person":
        if _ISO_DATE.match(str(start or "")):
            ld["birthDate"] = start
        if _ISO_DATE.match(str(end or "")):
            ld["deathDate"] = end
    elif kind in ("Event", "Organization"):
        key = ("startDate", "endDate") if kind == "Event" else ("foundingDate", "dissolutionDate")
        if _ISO_DATE.match(str(start or "")):
            ld[key[0]] = start
        if _ISO_DATE.match(str(end or "")):
            ld[key[1]] = end
    # 출처 — 우리가 옮겨 적은 글이면 어디서 왔는지 기계에도 말한다. 화면의
    # 출처 한 줄(§1 의 예외)과 **같은 값**이고 새로 여는 자리가 아니다.
    origin = node.get("desc_origin") or {}
    if origin.get("url"):
        ld["sameAs"] = [origin["url"]]

    def ref(rel: dict, as_type: str | None = None) -> dict:
        other = rel["other"]
        out = {"@type": as_type or SCHEMA_TYPE.get(other["type"], "Thing"),
               "name": other["label"],
               "url": SITE + quote(_url_of(other["id"], paths), safe="/")}
        return out

    by_fact = {name: rels for name, rels in facts}
    for name, prop, as_type in (("출생지", "birthPlace", "Place"),
                                ("사망지", "deathPlace", "Place"),
                                ("소재지", "contentLocation", "Place"),
                                ("장소", "location", "Place"),
                                ("소속", "memberOf", "Organization"),
                                ("만든 사람", "creator", "Person")):
        rels = by_fact.get(name)
        if not rels:
            continue
        if kind == "Person" and prop == "memberOf":
            ld[prop] = [ref(r, as_type) for r in rels[:FACT_MAX]]
        elif prop in ("birthPlace", "deathPlace", "location", "contentLocation"):
            if kind == "Person" and prop in ("birthPlace", "deathPlace"):
                ld[prop] = ref(rels[0], as_type)
            elif kind == "Event" and prop == "location":
                ld[prop] = ref(rels[0], as_type)
            elif prop == "contentLocation" and kind in ("CreativeWork", "Movie", "TVSeries",
                                                        "Book", "VideoGame", "MusicRecording"):
                ld[prop] = ref(rels[0], as_type)
        elif prop == "creator" and kind not in ("Person", "Organization", "Place"):
            ld[prop] = [ref(r, as_type) for r in rels[:FACT_MAX]]

    # 사람·단체의 가족·참여는 뜻이 그대로 맞는 자리가 있다.
    heads = {head: rels for _title, ranked in sections for head, rels in ranked}
    if kind == "Person":
        for head, prop in (("부모", "parent"), ("자녀", "children"), ("배우자", "spouse")):
            if heads.get(head):
                ld[prop] = [ref(r, "Person") for r in heads[head][:GROUP_MAX]]
    if kind == "Event":
        people = [r for head, rels in heads.items() for r in rels
                  if r["other"]["type"] in ("person", "org")
                  and (head in ROLE_HEADS or head == "참여")]
        if people:
            ld["attendee"] = [ref(r) for r in people[:GROUP_MAX]]
    return ld


def _shell(title: str, description: str, canonical: str, body: str,
           noindex: bool = False, *, ld: str = "", image: str | None = None,
           keywords: str = "", prev_url: str = "", next_url: str = "") -> str:
    robots = ('<meta name="robots" content="noindex,follow">\n' if noindex else
              '<meta name="robots" content="index,follow,max-image-preview:large">\n')
    picture = image or OG_IMAGE
    head = [robots]
    if keywords:
        head.append(f'<meta name="keywords" content="{escape(keywords)}">\n')
    if VERIFICATION:
        head.append(f'<meta name="google-site-verification" content="{escape(VERIFICATION)}">\n')
    if prev_url:
        head.append(f'<link rel="prev" href="{prev_url}">\n')
    if next_url:
        head.append(f'<link rel="next" href="{next_url}">\n')
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
{"".join(head)}<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="histgraph">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:image" content="{escape(picture)}">
<meta property="og:image:alt" content="{escape(OG_IMAGE_ALT)}">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(description)}">
<meta name="twitter:image" content="{escape(picture)}">
{ld}
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADS_CLIENT}"
        crossorigin="anonymous"></script>
<script async src="/analytics.js"></script>
<style>{STYLE}</style>
</head>
<body>

<header class="top">
  <a href="/"><span class="mark"></span>histgraph<span class="back">관계망으로 돌아가기</span></a>
</header>

{body}

<footer class="foot">
  <a href="/">histgraph</a><span>·</span><a href="/n/">글로 읽기</a><span>·</span><a href="/privacy.html">개인정보처리방침</a><span>·</span><a href="/terms.html">이용약관</a>
  <div class="copy">{COPYRIGHT}</div>
</footer>

</body>
</html>
"""


def _moved(new: str) -> Page:
    """옛 주소 → 새 주소. **간 곳은 경로로 적는다** — 도메인까지 박으면
    로컬 서버가 배포된 사이트로 사람을 보낸다."""
    where = quote(new, safe="/")
    return Page(301, "text/html; charset=utf-8",
                f'<!doctype html><meta charset="utf-8">'
                f'<link rel="canonical" href="{SITE}{where}">'
                f'<p><a href="{escape(where)}">옮겨진 주소로 갑니다</a></p>',
                where)


def _html(status: int, body: str) -> Page:
    return Page(status, "text/html; charset=utf-8", body)


def _not_found(path: str) -> Page:
    canonical = f"{SITE}{quote(path, safe='/')}"
    return _html(404, _shell(
        "찾을 수 없는 항목 — histgraph",
        "이 주소에 해당하는 항목이 없습니다.",
        canonical,
        '<main><h1>찾을 수 없습니다</h1>'
        '<p class="empty">이 주소에 해당하는 항목이 없습니다. 이름이 바뀌었거나 '
        '다른 항목으로 합쳐졌을 수 있습니다.</p>'
        '<a class="open" href="/n/">글로 읽는 장에서 찾아보기</a></main>',
        noindex=True,
    ))


def _dates(conn, ids) -> dict[str, tuple[str | None, str | None]]:
    """이웃들의 날짜. 관계 줄마다 물으면 한 장에 수백 번 묻는다."""
    out: dict[str, tuple[str | None, str | None]] = {}
    unique = list(dict.fromkeys(ids))
    for i in range(0, len(unique), 400):
        batch = unique[i:i + 400]
        marks = ",".join("?" * len(batch))
        for r in conn.execute(
            f"SELECT id, start_date, end_date FROM nodes WHERE id IN ({marks})", batch):
            out[r["id"]] = (r["start_date"], r["end_date"])
    return out


def _marks(relations: list[dict], dates: dict) -> list[tuple[int, str, dict]]:
    """연표에 세울 이웃. **연도를 아는 일과 만들어진 것만** 세운다 — 사람을
    한 점에 찍으면 거짓을 말한다 (`server` 의 연표와 같은 규칙)."""
    out: list[tuple[int, str, dict]] = []
    seen: set[str] = set()
    for rel in relations:
        other = rel["other"]
        if other["type"] not in MARK_TYPES or other["id"] in seen:
            continue
        # 연표의 눈금 노드(`time:1397`)는 세우지 않는다 — '1397년에 1397년'
        # 이라고 적히고, 그 해에 무슨 일이 있었는지는 한 자도 안 말한다.
        if str(other["id"]).startswith("time:"):
            continue
        start, end = dates.get(other["id"], (None, None))
        year = _year_num(start)
        if year is None:
            continue
        seen.add(other["id"])
        span = _year(start) + (f" ~ {_year(end)}" if _year(end) and end != start else "")
        out.append((year, span, other))
    out.sort(key=lambda x: (x[0], x[2]["label"]))
    return out[:MARK_MAX]


# 제목·빵부스러기에 세울 시대 이름의 길이. '조선'·'고려'·'일제강점기'는
# 그 장이 언제 것인지 한 낱말로 말하지만, 유물에 걸린 '조선 태조 7년(1398)'
# 은 제목을 통째로 먹는다 — 그건 시대가 아니라 날짜다.
ERA_MAX = 8


def _era_of(facts: list[tuple[str, list[dict]]]) -> dict | None:
    """이 장이 어느 시대 것인가. 연표의 눈금(`time:`)과 긴 날짜 표기는
    시대 이름이 아니므로 세지 않는다. 여럿이면 짧은 쪽 — 왕대보다 왕조다."""
    for name, rels in facts:
        if name != "시대":
            continue
        named = [r["other"] for r in rels
                 if not str(r["other"]["id"]).startswith("time:")
                 and len(r["other"]["label"]) <= ERA_MAX]
        if named:
            return min(named, key=lambda o: (len(o["label"]), o["label"]))
        return None
    return None


def _clip(text: str, limit: int = 157) -> str:
    """검색 결과에 뜨는 두 줄. 낱말 가운데서 끊지 않는다 — 끊긴 조각은
    읽는 사람에게 잘린 문서로 보인다."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit(" ", 1)[0] if " " in cut[limit - 24:] else cut).rstrip(" ,·") + "…"


def _title_of(name: str, kind: str, era: str, span: str) -> str:
    """검색 결과의 첫 줄. **장마다 달라야 한다** — 같은 제목이 여럿이면
    구글이 그중 하나만 남기고 나머지를 접는다. 그래서 이름 뒤에 시대·갈래·
    시기를 붙여 '세종 — 조선의 인물 (1397년 ~ 1450년) | histgraph' 로 적는다."""
    tail = f"{era}{kind}"
    if span:
        tail += f" ({span})"
    return f"{name} — {tail} | histgraph"


def node_page(api, node_id: str, canonical_path: str | None = None) -> Page:
    """노드 한 장. `canonical_path` 는 이 장의 정본 주소 (`/인물/세종`)."""
    node = api.node(node_id)
    if node is None:
        return _not_found(canonical_path or f"/n/{node_id}")

    conn = api.store.conn
    path = canonical_path or slugs.path_for(conn, node_id) or f"/n/{node_id}"
    canonical = f"{SITE}{quote(path, safe='/')}"

    names = node.get("names") or [node["label"]]
    title = names[0]
    also = " · ".join(names[1:])
    # 타입 딱지. 파는 '단체·국가·왕조'가 아니라 '분파'다 — 서버가 판정해
    # 보낸 것을 그대로 쓴다 (`ontology.type_label`).
    kind = node.get("type_label") or NODE_TYPES.get(node["type"], node["type"])
    span = " ~ ".join(x for x in (_year(node.get("start")), _year(node.get("end"))) if x)
    color = GROUP_COLOR.get(node.get("group"), "var(--frame)")
    desc = (node.get("description") or "").strip()

    relations = node.get("relations") or []
    other_ids = [r["other"]["id"] for r in relations]
    paths = slugs.paths_for(conn, other_ids)
    dates = _dates(conn, other_ids)
    facts, rest = _facts(relations)
    sections = _sections(rest)
    total = sum(len(rels) for _t, ranked in sections for _h, rels in ranked)
    total += sum(len(rels) for _n, rels in facts)
    summary = summarize(desc)
    era_node = _era_of(facts)
    era = f"{era_node['label']}의 " if era_node else ""

    segment = path.split("/")[1] if path.count("/") >= 2 else ""
    if segment not in slugs.SEGMENT_TYPE:
        segment = slugs.segment_of(node["type"], {"form": node.get("form")}) or ""
    crumbs: list[tuple[str, str | None]] = [("홈", "/")]
    if segment in slugs.SEGMENT_TYPE:
        crumbs.append((segment, f"/{segment}/"))
    if era_node:
        crumbs.append((era_node["label"], _url_of(era_node["id"], paths)))
    crumbs.append((title, None))

    parts = ["<main>", _crumbs(crumbs)]
    parts.append(
        f'<h1>{escape(title)}'
        + (f'<span class="also">{escape(also)}</span>' if also else "")
        + "</h1>"
    )
    parts.append(
        f'<p class="kind"><span class="dot" style="background:{color}"></span>'
        f'{escape(kind)}' + (f' · {escape(span)}' if span else "") + "</p>"
    )

    # 이 사이트의 말이 먼저다 — 언제의 무엇이고 무엇과 이어졌는지는 원문이
    # 아니라 관계망이 아는 것이다. 그다음에 원문 요약이 온다.
    lead = _lead(title, kind, era, sections, facts, total)
    parts.append(f'<p class="lead">{escape(lead)}</p>')
    if summary:
        parts.append(f'<p class="desc">{escape(summary)}</p>')
        origin = _origin_line(node.get("desc_origin"))
        if origin:
            parts.append(f'<p class="src">{origin}</p>')
    else:
        parts.append(f'<p class="empty">{escape(_why_empty(node))}</p>')

    aliases = node.get("aliases") or []
    if aliases:
        parts.append(f'<p class="aka">다른 이름 · {escape(" · ".join(aliases))}</p>')

    if facts:
        parts.append("<h2>주요 사실</h2><dl class=\"facts\">")
        for name, rels in facts:
            links = " · ".join(
                f'<a href="{href(_url_of(r["other"]["id"], paths))}">'
                f'{escape(r["other"]["label"])}</a>' for r in rels[:FACT_MAX])
            if len(rels) > FACT_MAX:
                links += f' <span>외 {len(rels) - FACT_MAX}</span>'
            parts.append(f"<div><dt>{escape(name)}</dt><dd>{links}</dd></div>")
        parts.append("</dl>")

    marks = _marks(relations, dates)
    if len(marks) >= 2:
        parts.append('<h2>연표</h2><ul class="marks">')
        for _year_n, when, other in marks:
            color2 = GROUP_COLOR.get(other.get("group"), "var(--frame)")
            parts.append(
                f'<li><span class="when">{escape(when)}</span>'
                f'<span class="dot" style="background:{color2}"></span>'
                f'<a href="{href(_url_of(other["id"], paths))}">{escape(other["label"])}</a></li>')
        parts.append("</ul>")

    if total:
        parts.append(f"<h2>이어진 것 {total}</h2>")
        for section, ranked in sections:
            parts.append(f"<h3>{escape(section)}</h3>")
            for head, rels in ranked:
                parts.append(f'<p class="head">{escape(head)}</p><ul>')
                parts.extend(_link(r["other"], paths) for r in rels[:GROUP_MAX])
                parts.append("</ul>")
                if len(rels) > GROUP_MAX:
                    parts.append(f'<p class="more">외 {len(rels) - GROUP_MAX}개</p>')
    else:
        parts.append('<h2>이어진 것</h2><p class="empty">연결된 관계가 없습니다.</p>')

    parts.append(
        f'<a class="open" href="/#{quote(node["id"], safe="")}">관계망에서 보기 →</a>'
    )
    parts.append("</main>")

    # 유산의 그림은 국가유산청이 준다. 링크를 펼칠 때만 쓰고 장에 걸지는
    # 않는다 — 남의 그림을 본문에 세우는 것은 다른 이야기다.
    image = node.get("image") or None
    if image and image.startswith("http://"):
        image = "https://" + image[len("http://"):]

    # 얇은 장은 색인에 올리지 않는다 (`indexable` — 사이트맵과 같은 문턱).
    # 이름과 목록만 있는 장이 검색 결과에 깔리면 읽을 것이 있는 장까지 같이
    # 묻힌다.
    meta = _clip(f"{lead} {summary}" if summary else lead)
    words = [title, *names[1:], *aliases[:4], kind]
    if era:
        words.append(era.rstrip("의 "))
    words += [r["other"]["label"] for _n, rels in facts for r in rels[:2]]
    keywords = ", ".join(dict.fromkeys(w for w in words if w))[:250]

    related = [SITE + quote(_url_of(r["other"]["id"], paths), safe="/")
               for _t, ranked in sections for _h, rels in ranked for r in rels[:6]][:24]
    entity = _entity_ld(node, canonical, summary, facts, sections, paths, image)
    ld = _ld_block(canonical=canonical, title=_title_of(title, kind, era, span),
                   description=meta, crumbs=crumbs, entity=entity, related=related)

    return _html(200, _shell(
        _title_of(title, kind, era, span),
        meta,
        canonical,
        "\n".join(parts),
        noindex=not indexable(summary, total),
        ld=ld, image=image, keywords=keywords,
    ))


# 목록 장이 갈래마다 몇 개씩 세우는지. 사람이 한 화면에서 훑을 수 있는 만큼.
INDEX_EACH = 60
# 갈래별 목록 장은 한 쪽에 이만큼. 로봇이 여기서 각 장으로 들어간다.
PAGE_SIZE = 100

# 목록 장에 세울 갈래와 그 머리말. 시대·직위(frame)는 두지 않는다 —
# '조선'·'영의정' 은 읽을거리가 아니라 다른 항목을 묶는 틀이다.
INDEX_KINDS = [
    ("person", "인물"),
    ("event", "사건"),
    ("heritage", "유물·문화재"),
    ("place", "장소"),
]

# 갈래마다 목록 장 머리에 적는 한 줄. 빈 목록에 이름만 세우면 '얇은 장'이다.
SEGMENT_LEAD = {
    "인물": "한국사의 인물들입니다. 이름을 누르면 그 사람이 언제 사람이고 누구와 무엇으로 이어졌는지 봅니다.",
    "사건": "한국사에서 일어난 일들입니다. 무엇이 그 일을 불렀고 그 일이 무엇을 불렀는지 함께 봅니다.",
    "장소": "한국사의 장소들입니다. 그곳에서 일어난 일과 그곳에 있는 것으로 이어집니다.",
    "단체": "나라와 왕조, 관청과 문중입니다. 그곳에 속한 사람과 시대로 이어집니다.",
    "유산": "국보와 보물, 사적과 유물입니다. 만든 사람과 있는 곳, 만들어진 때로 이어집니다.",
    "작품": "그림과 글씨, 지어진 것들입니다.",
    "시대": "한국사의 시대와 해입니다. 그 시기에 선 사람과 일로 이어집니다.",
    "직위": "관직과 칭호입니다. 그 자리에 오른 사람들로 이어집니다.",
    "개념": "제도와 사상, 풍습입니다.",
    "영화": "한국사를 다룬 영화입니다. 어느 인물과 어느 사건을 다루는지로 이어집니다.",
    "드라마": "한국사를 다룬 드라마입니다. 어느 인물과 어느 사건을 다루는지로 이어집니다.",
    "다큐멘터리": "한국사를 다룬 다큐멘터리입니다.",
    "애니메이션": "한국사를 다룬 애니메이션입니다.",
    "책": "한국사를 다룬 책입니다.",
    "만화": "한국사를 다룬 만화입니다.",
    "게임": "한국사를 다룬 게임입니다.",
    "음악": "한국사와 이어진 음악입니다.",
    "무대": "한국사를 다룬 무대입니다.",
}


def _segment_rows(api, segment: str, *, limit: int | None = None,
                  offset: int = 0) -> tuple[list, int]:
    """그 갈래에서 **색인에 올릴 만한** 장들. (줄, 전부 몇 개인가)

    문턱(`indexable`)은 요약을 봐야 알 수 있는데 노드가 만 개다. 그래서
    SQL 로 먼저 걷어낸다 — 요약은 설명보다 길어질 수 없으므로 설명 길이가
    문턱보다 짧으면 요약도 짧다. 남은 것만 파이썬이 정확히 잰다."""
    node_type, form = slugs.SEGMENT_TYPE[segment]
    where = ["n.type = ?", "COALESCE(n.description,'') <> ''",
             "LENGTH(n.description) >= ?", "s.slug IS NOT NULL"]
    args: list = [node_type, MIN_SUMMARY]
    if form:
        where.append("json_extract(n.props, '$.form') = ?")
        args.append(form)
    elif node_type == "media":
        where.append("COALESCE(json_extract(n.props, '$.form'), '') = ''")
    rows = [
        r for r in api.store.conn.execute(
            f"""SELECT * FROM (
                  SELECT n.id, n.label, n.type, n.description, s.segment, s.slug,
                         (SELECT COUNT(*) FROM edges e
                           WHERE e.src = n.id OR e.dst = n.id) AS degree
                    FROM nodes n
                    LEFT JOIN slugs s ON s.node_id = n.id AND s.current = 1
                   WHERE {' AND '.join(where)}
                 )
                 WHERE degree >= ?
                 ORDER BY degree DESC, label""",
            (*args, MIN_RELATIONS),
        )
        if indexable(summarize(r["description"]), r["degree"])
    ]
    total = len(rows)
    if limit is not None:
        rows = rows[offset:offset + limit]
    return rows, total


def segment_page(api, segment: str, page: int = 1) -> Page:
    """`/인물/` — 한 갈래의 목록. 로봇이 여기서 각 장으로 들어간다."""
    if segment not in slugs.SEGMENT_TYPE:
        return _not_found(f"/{segment}/")
    page = max(1, page)
    rows, total = _segment_rows(api, segment, limit=PAGE_SIZE,
                                offset=(page - 1) * PAGE_SIZE)
    if not rows and page > 1:
        return _not_found(f"/{segment}/")
    last = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    base = f"/{segment}/"
    canonical = f"{SITE}{quote(base, safe='/')}" + (f"?p={page}" if page > 1 else "")
    lead = SEGMENT_LEAD.get(segment, "")

    crumbs: list[tuple[str, str | None]] = [("홈", "/"), (segment, None)]
    parts = ["<main>", _crumbs(crumbs), f"<h1>{escape(segment)}</h1>"]
    # 수는 제목이 아니라 그 아래 한 줄이다. '장'으로 센다 — 인물은 명,
    # 사건은 건, 장소는 곳이라 갈래마다 세는 말이 다르다.
    count = f"모두 {total:,}장" + (f" · {page}쪽 / {last}쪽" if last > 1 else "")
    parts.append(f'<p class="kind">{escape(count)}</p>')
    if lead:
        parts.append(f'<p class="lead">{escape(lead)}</p>')
    parts.append("<ul>")
    parts.extend(
        _link({"id": r["id"], "label": r["label"], "type": r["type"],
               "group": _GROUP.get(r["type"], "frame")},
              {r["id"]: slugs.path(r["segment"], r["slug"])} if r["slug"] else {})
        for r in rows
    )
    parts.append("</ul>")
    if not rows:
        parts.append('<p class="empty">아직 읽을 것이 있는 장이 없습니다.</p>')

    prev_url = next_url = ""
    pager = []
    if page > 1:
        prev_path = base if page == 2 else f"{base}?p={page - 1}"
        prev_url = f"{SITE}{quote(base, safe='/')}" + ("" if page == 2 else f"?p={page - 1}")
        pager.append(f'<a href="{href(prev_path)}">← 앞쪽</a>')
    if page < last:
        next_path = f"{base}?p={page + 1}"
        next_url = f"{SITE}{quote(base, safe='/')}?p={page + 1}"
        pager.append(f'<a href="{href(next_path)}">다음쪽 →</a>')
    if pager:
        parts.append('<p class="pager">' + "".join(pager) + "</p>")
    parts.append('<a class="open" href="/n/">다른 갈래 보기 →</a>')
    parts.append("</main>")

    description = _clip(lead or f"{segment} 목록입니다.")
    ld = _ld_block(canonical=canonical,
                   title=f"{segment} — histgraph",
                   description=description, crumbs=crumbs)
    return _html(200, _shell(
        f"{segment} — 한국사 관계망 | histgraph" if page == 1
        else f"{segment} ({page}쪽) — 한국사 관계망 | histgraph",
        description, canonical, "\n".join(parts),
        ld=ld, keywords=f"{segment}, 한국사, 역사 관계망",
        prev_url=prev_url, next_url=next_url,
    ))


def index_page(api) -> Page:
    """`/n/` — 글로 읽는 장들의 어귀.

    관계망은 자바스크립트가 그려서 로봇이 들어올 문이 없다. 이 장이 그
    문이다 — 갈래마다 가장 많이 이어진 것부터 세워, 여기서 각 항목으로,
    항목에서 또 이웃으로 이어진다.
    """
    canonical = f"{SITE}/n/"
    crumbs: list[tuple[str, str | None]] = [("홈", "/"), ("글로 읽기", None)]
    parts = ["<main>", _crumbs(crumbs), "<h1>인물과 사건, 장소와 문화재</h1>",
             '<p class="kind">한국사의 개체들이 서로 어떻게 이어져 있는지를 '
             '글과 관계망 두 가지로 봅니다.</p>']
    counts = slugs.counts(api.store.conn)
    for kind, head in INDEX_KINDS:
        segment = slugs.SEGMENTS.get(kind, "")
        rows, total = _segment_rows(api, segment, limit=INDEX_EACH) if segment else ([], 0)
        if not rows:
            continue
        # 머리말은 **언제나** 그 갈래의 목록 장으로 간다. 여기서 끊기면
        # 로봇이 60개 너머로 들어갈 문이 없다.
        parts.append(f'<h2><a href="{href(f"/{segment}/")}">{escape(head)}'
                     f' {total:,}</a></h2><ul>')
        parts.extend(
            _link({"id": r["id"], "label": r["label"], "type": r["type"],
                   "group": _GROUP.get(r["type"], "frame")},
                  {r["id"]: slugs.path(r["segment"], r["slug"])} if r["slug"] else {})
            for r in rows
        )
        parts.append("</ul>")
        if total > len(rows):
            parts.append(f'<p class="more"><a href="{href(f"/{segment}/")}">'
                         f'{escape(head)} {total:,}개 모두 보기 →</a></p>')
    # 나머지 갈래는 이름만 세운다 — 여기서 목록 장으로 들어간다.
    rest = [s for s in slugs.SEGMENT_TYPE
            if counts.get(s) and s not in [slugs.SEGMENTS[k] for k, _h in INDEX_KINDS]]
    if rest:
        parts.append("<h2>다른 갈래</h2><ul>")
        parts.extend(
            f'<li><span class="dot" style="background:var(--frame)"></span>'
            f'<a href="{href(f"/{s}/")}">{escape(s)}</a>'
            f'<span class="meta">{counts[s]:,}</span></li>' for s in rest)
        parts.append("</ul>")
    parts.append('<a class="open" href="/">관계망에서 보기 →</a>')
    parts.append("</main>")
    description = ("한국사의 인물과 사건, 장소와 문화재가 시간 위에서 어떻게 "
                   "이어지는지 글과 관계망으로 봅니다.")
    ld = _ld_block(canonical=canonical, title="인물·사건·장소·문화재 — histgraph",
                   description=description, crumbs=crumbs)
    return _html(200, _shell(
        "인물·사건·장소·문화재 — 한국사 관계망 | histgraph",
        description, canonical, "\n".join(parts), ld=ld,
        keywords="한국사, 인물, 사건, 장소, 문화재, 지식 그래프",
    ))


# --- 사이트맵 --------------------------------------------------------------
# 한 파일에 실을 주소 수. 규격은 50,000 이지만 갈래마다 갈라 두면 어느
# 갈래가 얼마나 색인됐는지 서치 콘솔에서 따로 읽힌다.
SITEMAP_CHUNK = 20000
_SITEMAP_FILE = re.compile(r"^/sitemap-([a-z]+)-(\d+)\.xml$")


def _indexable_paths(api, segment: str) -> list[str]:
    rows, _total = _segment_rows(api, segment)
    return [slugs.path(r["segment"], r["slug"]) for r in rows if r["slug"]]


def _urlset(urls: list[str]) -> str:
    body = "\n".join(
        f"  <url><loc>{escape(SITE + quote(u, safe='/'))}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


def _static_urls(api) -> list[str]:
    counts = slugs.counts(api.store.conn)
    return (["/", "/n/", "/privacy.html", "/terms.html"]
            + [f"/{s}/" for s in slugs.SEGMENT_TYPE if counts.get(s)])


def sitemap_index(api) -> Page:
    """`/sitemap.xml` — 갈래마다 하나씩, 파일 목록만 든다.

    수만 장을 한 파일에 담으면 한 군데가 틀렸을 때 전부가 함께 밀린다.
    갈래로 갈라 두면 서치 콘솔이 '인물 2,300장 중 1,900장 색인'처럼
    갈래별로 답해 준다."""
    files = ["/sitemap-pages-1.xml"]
    for segment in slugs.SEGMENT_TYPE:
        n = len(_indexable_paths(api, segment))
        for i in range((n + SITEMAP_CHUNK - 1) // SITEMAP_CHUNK):
            files.append(f"/sitemap-{slugs.SEGMENT_KEY[segment]}-{i + 1}.xml")
    body = "\n".join(f"  <sitemap><loc>{escape(SITE + u)}</loc></sitemap>" for u in files)
    return Page(200, "application/xml; charset=utf-8",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{body}\n</sitemapindex>\n")


def sitemap_file(api, key: str, chunk: int) -> Page | None:
    """`/sitemap-person-1.xml` — 그 갈래의 주소들."""
    if key == "pages":
        return Page(200, "application/xml; charset=utf-8",
                    _urlset(_static_urls(api))) if chunk == 1 else None
    segment = next((s for s, k in slugs.SEGMENT_KEY.items() if k == key), None)
    if segment is None:
        return None
    urls = _indexable_paths(api, segment)
    start = (chunk - 1) * SITEMAP_CHUNK
    part = urls[start:start + SITEMAP_CHUNK]
    if not part:
        return None
    return Page(200, "application/xml; charset=utf-8", _urlset(part))


def route(api, path: str, query: dict | None = None) -> Page | None:
    """이 경로가 문서 페이지인가. Page 또는 None.

    로컬(`histgraph serve`)과 배포(`api/index.py`)가 같은 표를 본다. 배포
    쪽은 rewrite 가 `/인물/세종` 을 `/api/인물/세종` 으로 바꿔 넘긴다
    (vercel.json).
    """
    query = query or {}
    for prefix in ("/api", ""):
        if not path.startswith(prefix or "/"):
            continue
        rest = path[len(prefix):] or "/"
        page = _route(api, rest, query)
        if page is not None:
            return page
    return None


def _route(api, path: str, query: dict) -> Page | None:
    if path == "/sitemap.xml":
        return sitemap_index(api)
    hit = _SITEMAP_FILE.match(path)
    if hit:
        return sitemap_file(api, hit.group(1), int(hit.group(2)))

    # 옛 주소(`/n/<id>`). 색인에 올라 있으므로 끊지 않고 새 주소로 보낸다.
    if path == "/n" or path.startswith("/n/"):
        node_id = unquote(path[3:]).strip("/") if path.startswith("/n/") else ""
        if not node_id:
            return index_page(api)
        new = slugs.path_for(api.store.conn, node_id)
        if new:
            return _moved(new)
        # 주소를 아직 못 받은 노드(`slugs.assign` 전)는 여기서 그대로 낸다 —
        # 새 주소로 보냈다가 그 주소가 없으면 로봇이 고리를 돈다.
        return node_page(api, node_id, f"/n/{node_id}")

    segments = [s for s in path.split("/") if s]
    if not segments or unquote(segments[0]) not in slugs.SEGMENT_TYPE:
        return None
    segment = unquote(segments[0])
    if len(segments) == 1:
        try:
            page = int((query.get("p") or ["1"])[0])
        except (TypeError, ValueError):
            page = 1
        return segment_page(api, segment, page)
    if len(segments) > 2:
        return _not_found(path)
    slug = unquote(segments[1])
    hit = slugs.lookup(api.store.conn, segment, slug)
    if hit is None:
        return _not_found(path)
    node_id, current = hit
    if not current:
        # 이름이나 타입이 바뀌어 주소가 옮겨 갔다 — 옛 주소는 살려 두고
        # 새 주소를 가리킨다.
        new = slugs.path_for(api.store.conn, node_id)
        if new and new != slugs.path(segment, slug):
            return _moved(new)
    return node_page(api, node_id, slugs.path(segment, slug))
