"""그래프 탐색 서버 — 프론트엔드가 실제로 붙는 곳.

**의존성 없이 표준 라이브러리로만 만든다.** 수집 파이프라인이 그렇듯이
`uv run histgraph serve` 한 줄로 뜨는 게 이 프로젝트의 조건이다.

**전부 그리지 않는다.** 조선 그래프만 해도 노드 5,637 · 엣지 9,629 다.
한 화면에 다 뿌리면 털뭉치가 되고 브라우저도 버틴다고 그릴 뿐 읽히지
않는다. 그래서 서버는 언제나 **한 노드 주변**만 돌려준다 — 검색으로
들어가서 이웃을 펼쳐 나가는 것이 이 그래프를 읽는 방법이다.

기본값으로 연도(`period`)를 빼는 이유도 같다. 연도 노드는 거의 모든
노드에 붙어 있어서, 그냥 두면 화면 예산을 연도가 다 먹는다.
"""

from __future__ import annotations

import datetime
import json
import logging
import mimetypes
import os
import re
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import auth, pages, summaries
from .labels import screen_alias
from .ontology import EDGE_TYPES, NODE_TYPES, type_label
from .provenance import desc_origin
from .store import GraphStore

log = logging.getLogger(__name__)


WEB_SRC = Path(__file__).resolve().parents[2] / "web"
WEB_DIST = WEB_SRC / "dist"


def _web_root() -> Path:
    """정적 파일을 어디서 읽을지.

    화면이 React(JSX)라 **브라우저가 원본을 직접 못 읽는다.** `npm run build`
    가 만든 web/dist/ 를 내줘야 하고, 그게 없으면 web/ 의 index.html 이
    /src/main.jsx 를 가리켜 빈 화면이 된다. 아래 warn_if_unbuilt() 가 그때
    무엇을 하라고 말해 준다."""
    return WEB_DIST if (WEB_DIST / "index.html").is_file() else WEB_SRC


WEB_ROOT = _web_root()


def warn_if_unbuilt() -> bool:
    """화면이 빌드돼 있는지. 안 돼 있으면 무엇을 하라고 적는다.

    API 는 빌드와 무관하게 멀쩡하므로 서버를 막지는 않는다 — 빈 화면 앞에서
    이유를 못 찾는 것보다 낫다."""
    if (WEB_DIST / "index.html").is_file():
        return True
    print(
        "  ⚠ 화면이 아직 빌드되지 않았습니다 (web/dist 없음).\n"
        "    화면을 고치는 중이라면:  npm run dev      (5173, 자동 반영)\n"
        "    이 포트로 볼 것이라면:    npm run build    (그 뒤 다시 serve)\n"
        "    API 는 그대로 씁니다.",
    )
    return False

# 화면이 견디는 노드 수. 이보다 많으면 힘기반 배치가 수렴하기 전에
# 사람이 먼저 포기한다.
DEFAULT_LIMIT = 120
MAX_LIMIT = 400

# 기본으로 따라가지 않을 타입 (프론트에서 켤 수 있다)
DEFAULT_EXCLUDE = ("period",)

# 노드 타입을 갈래 4개로 묶는다. 화면은 **타입마다 다른 색**을 쓰고
# (web/src/lib/graph-view.js TYPE_COLOR), 갈래는 그 색들의 계열로 남는다 —
# 인물·단체는 파랑~보라, 사건은 주황, 장소·유물·작품은 초록~금~분홍~청록,
# 시대·직위는 무채색. 갈래가 따로 필요한 것은 **타입을 모를 때 물러날
# 자리**여서다 (GROUP_COLOR).
#
# 한때는 색을 갈래 넷으로만 쓰고 세부 타입은 모양으로 갈랐는데, 그 배치는
# 색약에서 갈래끼리도 구별되지 않았고(2형 ΔE 2.6) 타입을 나르던 것은 색이
# 아니라 모양이었다. 모양을 걷어내고 밝기까지 층으로 갈라 아홉 색을 다시
# 고른 것이 지금이다. 근거는 `uv run tools/check_palette.py`.
TYPE_GROUP: dict[str, str] = {
    "person": "actor",
    "org": "actor",
    "event": "event",
    "place": "thing",
    "heritage": "thing",
    "artwork": "thing",
    "media": "thing",
    "period": "frame",
    "role": "frame",
    # 개념은 뼈대 쪽이다. 색을 하나 더 만들지 않는다 — 아홉 색도 이미
    # 흩어진 작은 원에서는 구별이 빠듯하다. 물러나 있는 것이 맞다.
    "concept": "frame",
}


def _props(row) -> dict:
    """노드 행의 props. 열이 없거나 깨져 있으면 빈 것으로 본다."""
    if "props" not in row.keys():
        return {}
    try:
        return json.loads(row["props"] or "{}") or {}
    except (ValueError, TypeError):
        return {}


def _group(row) -> str:
    """갈래는 대개 타입이 정하지만, **한 타입 안에서 뜻이 갈리는 노드는
    스스로 말한다.** 갈래가 나르는 것은 색이 아니라 '얼마나 앞에 세우나'다
    (팔란티어의 prominent/normal/hidden — graph-drawer.md §1.1).

    지금 그런 노드는 씨족의 본관·파 하나다 (`clans.py`). `org` 이지만
    행위자가 아니라 사람을 묶는 틀이라 — 날짜가 없고, 사건에 참여하지 않고,
    하는 일이 '누구를 담는가'뿐이라 — 시대·직위와 같은 자리에서 물러난다.
    캔버스에서 밑동 반지름이 6 에서 4 로 줄고, 색은 org 크림 그대로다
    (색상은 타입이 쥔 부호다 — graph-drawer.md §12.21)."""
    if _props(row).get("kind") == "clan":
        return "frame"
    return TYPE_GROUP.get(row["type"], "thing")


def _other_brief(row) -> dict:
    """관계 줄의 상대. 색 점(갈래)과 타입 딱지를 여기서 정한다 — 상대가
    파면 '단체·국가·왕조'가 아니라 '분파'라고 적힌다."""
    props = json.loads(row["other_props"] or "{}") if row["other_props"] else {}
    return {
        "id": row["other_id"],
        "label": row["other_label"],
        "type": row["other_type"],
        "group": "frame" if props.get("kind") == "clan"
                 else TYPE_GROUP.get(row["other_type"], "thing"),
        "type_label": type_label(row["other_type"], props),
    }


# --- 연표 --------------------------------------------------------------
# 차수 내림차순으로 훑는다. **끊지는 않는다** — 아래 `_anchors` 가 적은
# 대로 연대를 아는 사건은 다 세우는 것이 규칙이다. 차례가 필요한 것은
# 이름·해가 같을 때 어느 쪽을 남길지 고르기 위해서다.
#
# 예전에는 여기서 400 에서 끊었다. 조선만 있을 때 연도 있는 사건이 73개라
# 아무것도 안 잘렸는데, 묶음이 고려~대한민국이 되면서 사건이 568개가 됐고
# **연도를 아는 사건 119건이 조용히 잘려 나갔다** (2026-09-06 지적:
# 덕종~헌종 1031~1095 의 연표가 통째로 비어 있었다). 차수가 낮은 것부터
# 잘리므로 자료가 얇은 시대가 먼저 사라진다 — 잘린 고려 사건 18건에
# 왕규의 난·귀주성 전투·안북부 전투·명주 민란이 있었고, 그 65년 창에
# 있던 두 건(1056·1067 흥왕사)도 함께 없어져 화면이 빈 칸이 됐다.
# 연표에서 빠진 사건은 읽는 사람에게 '그 시대에 없었던 일'이다.
# 한 노드에 붙일 이웃 수. 이보다 많으면 한 해에 라벨이 겹쳐 쌓인다.
TIMELINE_NEAR = 8
# 연표에 점으로 찍어도 되는 타입. **일어난 일과 만들어진 것뿐이다.**
# 사람·장소·조직은 이어지는 것이라 한 점에 찍으면 거짓을 말한다 — 윤필상
# (1427년생)을 갑자사화(1504) 옆에 '참여'라고 달아 1427년에 세우면,
# 화면은 "1427년에 참여했다"고 읽힌다. 사람이 언제 살았는지는 그 사람을
# 골랐을 때 자기 자리에서 생몰 구간으로 말한다.
POINT_TYPES = ("event", "artwork", "media")
# 이웃이 이만큼 떨어져 있으면 더는 '그 무렵'이 아니다. 실측: 갑자사화
# (1504) 참여자 목록에 1955년생 정성근이 들어 있다 — 동명이인을 붙잡은
# 것인데, 그대로 그리면 축이 450년으로 늘어나 정작 사화 앞뒤가 몇 픽셀
# 안에서 뭉개진다. 한 사람의 일생과 그 앞뒤 세대까지가 '무렵'이다.
NEAR_WINDOW = 150
# 믿을 수 있는 존속 구간의 상한. 넘으면 끝 연도를 없는 셈 친다.
# (실측: 몰년을 모르는 인물의 end_date 가 2000-01-01 로 적혀 있다 —
#  이재현 1870~2000. 사건 쪽은 정축하성이 1637~1895 로 258년짜리다.)
MAX_SPAN = {"person": 110, "event": 60}

# 관계를 볼 때 사람이 먼저 궁금해하는 순서. 상세 패널의 정렬 기준이다.
# 역할이 적힌 참여·관련은 역할이 곧 이름이다 (`roles.ROLES`·인포박스 칸 이름).
# 그래프의 선과 상세의 묶음이 '관련' 대신 '피해'·'주도'라고 말한다 —
# 2026-09-07 지적: 피해로 옮긴 정도전이 사건 상세에서 사라진 것처럼 보였다.
ROLE_HEADS = frozenset({"주도", "가담", "대항", "피해", "표적", "수습", "지휘관", "주요 인물", "교전", "가해"})
# 작품에 만든 사람을 잇는 `created` 에는 **만든 방식**이 적혀 있다
# (`creators.ROLES` — 그림·글씨·저술·편찬·제작·발원). 타입 이름 '제작' 하나로
# 부르면 그린 것·쓴 것·지은 것·엮은 것이 한 말로 뭉개진다 — "정선이 인왕제색도를
# 만들었다". 여섯 다 방향으로 갈라 부른다: 사람 쪽에서는 만든 것들의 목록이고
# 작품 쪽에서는 만든 사람이다.
CREATOR_DIR_HEAD = {
    "그림": {"out": "그린 것", "in": "그린 사람"},
    "글씨": {"out": "글씨를 쓴 것", "in": "글씨를 쓴 사람"},
    "저술": {"out": "지은 것", "in": "지은 사람"},
    "편찬": {"out": "엮은 것", "in": "엮은 사람"},
    "제작": {"out": "만든 것", "in": "만든 사람"},
    "발원": {"out": "만들게 한 것", "in": "만들게 한 사람"},
}
# 방향으로 갈라 부르는 라벨 (`relations.js` LABEL_DIR_HEAD 와 같은 표)
LABEL_DIR_HEAD = {
    "다음": {"out": "다음 일", "in": "앞선 일"},
    "이 기사의 대상": {"out": "이 기록이 다루는 것", "in": "이것을 다룬 기록"},
    # 파 → 상위(대파·본관). 나가는 쪽은 이 파가 갈라져 나온 문중이고,
    # 들어오는 쪽은 여기서 갈라진 파들이다 (전주 이씨 바로 아래만 111개).
    "분파": {"out": "속한 문중", "in": "갈라진 파"},
    # 본관 → 그 지명. 씨족 쪽에서는 '본관'이지만 지명 쪽에서 보면
    # 이곳을 본관으로 삼은 씨족들의 목록이다.
    "본관": {"out": "본관 지명", "in": "이곳을 본관으로 하는 씨족"},
    **CREATOR_DIR_HEAD,
}
# 라벨이 타입 이름보다 정확한 관계 전부 (`relations.js` LABEL_HEADS 와 같은 표).
# 그래프의 선과 연표의 딱지가 '관련' 대신 이 이름으로 말한다.
# 씨족이 셋을 더한다 (`clans.py` — 파조·분파·본관). '소속'이라고 부르면 덕천군이
# 덕천군파에 든 수만 명 중 하나로 읽히고, '상위'라고 부르면 파가 무엇인지 사라진다.
# 만든 방식 여섯은 위 표에서 그대로 딸려 온다 — 표를 늘리면 선 이름도 같이
# 늘어야 해서, 손으로 두 번 적지 않고 `LABEL_DIR_HEAD` 의 열쇠를 그대로 쓴다.
LABEL_HEADS = ROLE_HEADS | frozenset(LABEL_DIR_HEAD) | frozenset({"소속", "직위", "파조"})


def _rel_name(etype: str, direction: str, label: str | None) -> dict:
    """연표·화면이 부를 관계 이름. 라벨이 타입보다 정확하면 그것을 쓰고
    `specific` 을 달아 화면이 방향으로 다시 부르지 않게 한다.

    **타입으로 막지 않는다.** 예전에는 참여·관련에만 걸었는데, 라벨이 타입
    이름을 이기는 것은 타입의 문제가 아니라 라벨의 문제다 — `member_of`
    에 적힌 '파조'는 '소속'보다 정확하고, `part_of` 의 '분파'는 '상위'보다
    정확하다. 표에 있는 라벨만 이기므로 넓혀도 다른 관계가 흔들리지 않는다
    (`held_position`·`member_of` 에 붙은 '직위'·'소속'은 타입 이름과 같은
    말이다)."""
    if label:
        if label in LABEL_DIR_HEAD:
            return {"type": etype, "dir": direction,
                    "label": LABEL_DIR_HEAD[label][direction], "specific": True}
        if label in LABEL_HEADS:
            return {"type": etype, "dir": direction, "label": label, "specific": True}
    return {"type": etype, "dir": direction, "label": EDGE_TYPES[etype][0]}

RELATION_ORDER = [
    "caused", "participated_in", "held_position", "member_of", "created",
    "child_of", "spouse_of", "taught", "born_in", "died_in",
    "occurred_at", "located_in", "depicts", "part_of",
    "from_period", "occurred_during", "dated_to", "related_to",
]


# 라벨 서비스가 한국어·영어 어느 쪽도 못 준 노드. 라벨 자리에 QID 가
# 그대로 들어앉는다.
UNLABELED = re.compile(r"^Q\d+$")


def _year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^(-?)(\d{1,4})", value.strip())
    return int(m.group(2)) * (-1 if m.group(1) else 1) if m else None


def _year_at(value: str | None) -> float | None:
    """'1963-12-17' -> 1963.96. 해 안의 자리까지 아는 연도.

    연표의 세로 자는 해 단위라(`buildScale` 의 `pos`), 재위 띠를 해로만
    주면 12월에 취임한 대통령의 이름이 그 해 1월에 선다 — 박정희의 띠가
    1963년 1월부터 그어졌다 (2026-09-09 지적: "해당 대통령의 이름을 취임날에
    맞춰서 위치 시켜 달라고"). 화면은 두 해 사이를 이 소수로 나눠 앉힌다.

    달까지만 아는 날짜는 그 달의 첫날로 본다. 없는 정밀도를 지어내는 것보다
    낫고, 1월 1일로 적힌 거짓 정밀도(`precision`)는 어차피 해의 시작이다."""
    year = _year(value)
    if year is None:
        return None
    m = re.match(r"^-?\d{1,4}-(\d{2})(?:-(\d{2}))?", (value or "").strip())
    if not m:
        return float(year)
    month = min(max(int(m.group(1)), 1), 12)
    day = min(max(int(m.group(2) or 1), 1), 31)
    # 달의 길이를 따지지 않는다. 자의 눈금은 한 해이고 하루는 그 0.3% 라,
    # 30.5일로 고르게 나눠도 화면에서 갈리지 않는다.
    return year + ((month - 1) * 30.5 + (day - 1)) / 366.0


def _span(row) -> tuple[int | None, int | None]:
    """노드가 스스로 말하는 연대. **인물의 생년=몰년은 없는 셈 친다.**

    실측: 서장옥의 생몰이 둘 다 1900-01-01 이다(몰년만 아는 인물). 그대로
    믿으면 연표에 1900년 한 점으로 찍히고, 동학농민혁명(1894) 뒤에 태어난
    사람이 그 혁명에 참여한 그림이 된다. `promote.life_of` 와 같은 규칙이다.

    사건은 다르다 — 하루짜리 사건은 시작과 끝이 같은 게 정상이다."""
    start, end = _year(row["start_date"]), _year(row["end_date"])
    if row["type"] == "person" and start is not None and start == end:
        return None, None
    ceiling = MAX_SPAN.get(row["type"])
    if ceiling and start is not None and end is not None and end - start > ceiling:
        return start, None
    return start, end


def co_names(label: str, props: str | None) -> list[str]:
    """이 노드의 **또 하나의 이름**. 표기 변형이 아니라 진짜 다른 이름.

    실측으로 필요해진 구분이다. 기축옥사의 별칭은 셋인데 무게가 다르다.

        기축사화 · 정여립의 옥사   표기가 조금 다른 같은 말
        정여립의 난              이 사건을 부르는 **또 하나의 이름**

    셋을 '다른 이름' 한 더미에 넣으면 정여립의 난이 별명처럼 읽힌다.
    화면에서 사건을 열었을 때 그 이름이 어디에도 안 보이는 것은 틀렸다 —
    그 이름으로 이 사건을 아는 사람이 더 많다.

    **가르는 기준은 점수가 아니라 출신이다.** `merged_from` 에 있는 이름은
    우리 그래프에서 **자기 노드를 갖고 있던** 이름이다. 어떤 소스가 그
    대상의 이름으로 그렇게 적었다는 뜻이라, 위키데이터가 곁다리로 적어 둔
    altLabel 과는 격이 다르다.

    한쪽이 다른 쪽에 통째로 들어 있으면 뺀다 — '조선 세조 · 세조' 처럼
    길고 짧은 같은 이름을 두 번 쓸 이유가 없다."""
    if not props:
        return []
    try:
        merged = json.loads(props).get("merged_from") or []
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    for item in merged:
        name = (item or {}).get("label") if isinstance(item, dict) else None
        if not name or name == label:
            continue
        if name in label or label in name:
            continue
        if name not in out:
            out.append(name)
    return out


def _names(row) -> list[str]:
    """대표 이름을 앞에 두고 또 하나의 이름을 잇는다."""
    props = row["props"] if "props" in row.keys() else None
    return [row["label"], *co_names(row["label"], props)]


def _node_brief(row, degree: int = 0) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "names": _names(row),
        "type": row["type"],
        "group": _group(row),
        "degree": degree,
        "start": _year(row["start_date"]),
        "end": _year(row["end_date"]),
    }


class GraphAPI:
    """저장소 위에 얹는 조회 계층. HTTP 와 분리해 두어야 테스트할 수 있다.

    **연결은 스레드마다 따로 연다.** sqlite3 연결은 만든 스레드에서만 쓸
    수 있는데 `ThreadingHTTPServer` 는 요청마다 다른 스레드에 넘긴다.
    한 연결을 공유하면 첫 요청부터 `ProgrammingError` 로 빈 응답이 나간다
    (실측: 브라우저에 'Empty reply from server').

    경로를 주면 스레드별로 열고, 이미 만든 저장소를 주면 그대로 쓴다 —
    테스트는 단일 스레드라 새로 열 이유가 없다."""

    def __init__(
        self,
        db: Path | str | GraphStore,
        era: str = "",
        *,
        readonly: bool = False,
    ) -> None:
        self._shared = db if isinstance(db, GraphStore) else None
        self._db = db.path if isinstance(db, GraphStore) else Path(db)
        self._local = threading.local()
        self.era = era
        # 배포(서버리스)에서는 쓸 수 없는 파일시스템 위에서 연다. store.py 참고.
        self.readonly = readonly

    @property
    def store(self) -> GraphStore:
        if self._shared is not None:
            return self._shared
        store = getattr(self._local, "store", None)
        if store is None:
            store = GraphStore(self._db, readonly=self.readonly)
            self._local.store = store
        return store

    # --- 무게 ---------------------------------------------------------
    #
    # **무엇을 먼저 보여줄지는 무게가 정한다** (`central` 모듈 머리글 —
    # 타입 가중 PageRank). 차수는 문서의 길이를 재지 역사를 재지 않는다.
    # 무게는 **차례만** 정한다 — 무엇을 뺄지 정하는 데 쓰지 않는다.
    #
    # 아직 `histgraph central` 을 안 돌린 DB 도 있다. 배포 DB 는 읽기
    # 전용으로 열려 스키마가 돌지 않으므로 표 자체가 없을 수 있다 —
    # 그때는 조용히 차수로 물러난다.
    def _weighted(self) -> tuple[str, str]:
        """(조인 절, 차례 절). 표가 없으면 예전처럼 차수 순."""
        got = getattr(self._local, "central", None)
        if got is None:
            from . import central
            got = central.present(self.store.conn)
            self._local.central = got
        if not got:
            return "", "d DESC"
        return ("LEFT JOIN centrality ct ON ct.node_id = n.id",
                "COALESCE(ct.score, 0) DESC, d DESC")

    # --- 메타 ---------------------------------------------------------
    def root(self) -> str | None:
        """이 그래프의 중심. 조선 그래프의 중심은 조선이다.

        차수 1위 노드로 대신하지 않는다 — 그건 그때그때 병자호란이었다가
        선조였다가 하는 우연이고, 화면을 열었을 때 '무엇의 그래프인가'를
        말해주지 못한다. 왕조 노드가 실제로 있을 때만 쓴다.

        시대를 묶어 담은 그래프(고려~대한민국)에서는 **여는 시대**가
        중심이다. 들어가는 문이 하나여야 하고, 둘을 나란히 놓으면 화면이
        먼저 '어느 쪽이냐'를 묻게 된다. 그 시대는 묶음의 맨 앞과 다를 수
        있다 (`scope.BUNDLE_ROOT`) — 맨 앞은 연표의 바닥이고 여는 시대는
        처음 보이는 자리다. korea 묶음은 918년에서 시작해 조선에서 연다."""
        from .scope import ERAS, opening_eras

        for key in opening_eras(self.era):
            era = ERAS.get(key)
            if era is None:
                continue
            node_id = f"wd:{era.polity_qid}"
            if self.store.conn.execute(
                "SELECT 1 FROM nodes WHERE id = ?", (node_id,)
            ).fetchone():
                return node_id
        return None

    def meta(self) -> dict:
        from .scope import label_of

        stats = self.store.stats()
        return {
            "era": self.era,
            # 화면이 영어 키를 한국어로 옮기는 표를 따로 들고 있었다.
            # 시대가 늘 때마다 그 표를 같이 고쳐야 하고, 빠뜨리면 화면에
            # 영어가 뜬다 — 이 저장소가 두 번 지적받은 자리다.
            "era_label": label_of(self.era),
            "root": self.root(),
            "node_types": {
                k: {"label": v, "group": TYPE_GROUP.get(k, "thing"),
                    "count": stats["by_node_type"].get(k, 0)}
                for k, v in NODE_TYPES.items()
            },
            "edge_types": {
                k: {"label": v[0], "count": stats["by_edge_type"].get(k, 0)}
                for k, v in EDGE_TYPES.items()
            },
            "nodes_total": stats["nodes_total"],
            "edges_total": stats["edges_total"],
        }

    def seeds(self, limit: int = 12) -> list[dict]:
        """들어가는 문. 빈 화면에 검색창만 있으면 무엇을 쳐야 할지 모른다.

        **맨 위는 왕조 자신이다.** 이 그래프의 중심이고, 거기서 사람과
        사건으로 갈라져 나가는 것이 이 시대를 읽는 순서다.

        나머지는 **무게 상위순**이다 (`_weighted`). 차수로 고르면 문서가
        긴 노드가 서고, 무게로 고르면 무신정변·위화도 회군처럼 자료가 얇은
        시대의 큰일도 문 앞에 선다. 인물만 주면 사건 쪽으로 들어가는 길이
        안 보이므로 섞는다."""
        out: list[dict] = []
        root = self.root()
        if root:
            row = self.store.conn.execute(
                "SELECT id, type, label, start_date, end_date, props FROM nodes WHERE id = ?",
                (root,),
            ).fetchone()
            if row:
                out.append(_node_brief(row, self.store.degrees({root}).get(root, 0)))
                limit -= 1

        join, order = self._weighted()
        for node_type, take in (("person", limit - limit // 3), ("event", limit // 3)):
            rows = self.store.conn.execute(
                f"""SELECT n.id, n.type, n.label, n.start_date, n.end_date, n.props,
                          COUNT(e.src) AS d
                     FROM nodes n
                     LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                     {join}
                    WHERE n.type = ? AND n.description IS NOT NULL
                 GROUP BY n.id
                 ORDER BY {order}
                    LIMIT ?""",
                (node_type, take),
            ).fetchall()
            out.extend(_node_brief(r, r["d"]) for r in rows)
        return out

    def search(self, query: str, limit: int = 25) -> list[dict]:
        """라벨과 별칭을 함께 본다.

        별칭을 빼면 '이방원'으로 태종을 찾을 수 없다 — 산문이 쓰는 이름과
        그래프의 라벨이 다른 것이 이 데이터의 기본 조건이다."""
        query = query.strip()
        if not query:
            return []
        like = f"%{query}%"
        # **띄어쓰기는 사람마다 다르다.** 소스마다 표제를 다르게 단다 —
        # 국편은 '3·1운동', 위키백과는 '3·1 운동'이다 (§1-4). 라벨이
        # '전주 이씨'인데 '전주이씨'를 치면 한 줄도 안 나왔다 (2026-09-10
        # 지적). 찾는 사람이 띄어쓰기를 맞혀야 하는 검색은 없는 것과 같다.
        # 그래서 라벨·별칭과 검색어에서 공백을 빼고 한 번 더 견준다.
        tight = f"%{query.replace(' ', '')}%"
        bare = query.replace(" ", "")
        # **무게가 첫 기준이다** (`_weighted` — 타입 가중 PageRank). 문자열
        # 일치도를 앞에 두면 '세종'을 쳤을 때 세종특별자치시와 '세종 비암사
        # 극락보전'이 먼저 나오고 정작 조선 세종은 네 번째로 밀린다 —
        # 실측으로 확인한 순서다. 예전에는 이 자리가 차수였는데, 차수는
        # 문서가 긴 쪽을 세운다(`central` 모듈 머리글).
        # 연도 노드는 검색 대상이 되는 일이 드물어 뒤로 보낸다.
        #
        # **연표 눈금(`source='timeline'`)은 아예 뺀다.** '1974'를 치면
        # `time:1974`('1974년')가 첫 줄이었고, 엔터가 그걸 열어 연표 1974년
        # 자리에 '1974년'이라는 노드가 앉았다. 눈금은 날짜 없는 사건을
        # 해에 걸어 두는 뼈대지 사람이 찾을 개체가 아니다 — 그 해를
        # 찾는 사람에게는 그 해의 사건이 나와야 한다.
        join, order = self._weighted()
        rows = self.store.conn.execute(
            f"""SELECT n.id, n.type, n.label, n.start_date, n.end_date, n.props,
                      COUNT(e.src) AS d,
                      MIN(CASE WHEN n.label = ?1 THEN 0
                               WHEN REPLACE(n.label, ' ', '') = ?4 THEN 0
                               WHEN n.label LIKE ?1 || '%' THEN 1
                               WHEN REPLACE(n.label, ' ', '') LIKE ?4 || '%' THEN 1
                               ELSE 2 END) AS rank
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                 {join}
                WHERE (n.label LIKE ?2
                       OR REPLACE(n.label, ' ', '') LIKE ?5
                       OR n.id IN (SELECT node_id FROM aliases
                                    WHERE alias LIKE ?2
                                       OR REPLACE(alias, ' ', '') LIKE ?5))
                  AND n.source != 'timeline'
             GROUP BY n.id
             ORDER BY (n.type = 'period'), {order}, rank, n.label
                LIMIT ?3""",
            (query, like, limit, bare, tight),
        ).fetchall()
        return [_node_brief(r, r["d"]) for r in rows]

    # --- 그래프 -------------------------------------------------------
    def graph(
        self,
        node_id: str,
        depth: int = 1,
        limit: int = DEFAULT_LIMIT,
        exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
    ) -> dict:
        limit = max(5, min(limit, MAX_LIMIT))
        sub = self.store.neighbors(
            node_id, depth=depth, max_nodes=limit, exclude_types=exclude
        )
        if not sub["nodes"]:
            return {"center": node_id, "nodes": [], "edges": [], "same_as": [],
                    "truncated": False, "missing": True}

        ids = {n["id"] for n in sub["nodes"]}
        degree = self.store.degrees(ids)
        nodes = [_node_brief(n, degree.get(n["id"], 0)) for n in sub["nodes"]]

        # **같은 사실을 여러 소스가 말하면 한 줄로 합쳐서 보낸다.**
        # 저장소에는 소스별로 남겨둔다 — 그게 교차검증의 근거다. 하지만
        # 화면에서는 '행주대첩 → 행주산성'이 두 번 그려질 이유가 없다.
        merged: dict[tuple[str, str, str], dict] = {}
        for e in sub["edges"]:
            key = (e["src"], e["dst"], e["type"])
            row = merged.get(key)
            if row is None:
                # 인과는 종류(배경·계기·영향)가 곧 뜻이라 엣지의 라벨 열을
                # 그대로 보낸다. 다른 관계는 타입 이름 하나로 족하다.
                label = EDGE_TYPES[e["type"]][0]
                if e["type"] == "caused" and e["label"]:
                    label = e["label"]
                # 라벨이 타입 이름보다 정확하면 선의 이름도 그것이다
                # (`_rel_name` 과 같은 규칙 — 역할·파조·분파).
                if e["label"] in LABEL_HEADS:
                    label = e["label"]
                merged[key] = {
                    "s": e["src"], "t": e["dst"], "type": e["type"],
                    "label": label,
                    "conf": e["confidence"], "sources": [e["source"]],
                }
            else:
                # 가장 믿을 만한 소스가 선을 대표한다
                row["conf"] = max(row["conf"], e["confidence"])
                if e["source"] not in row["sources"]:
                    row["sources"].append(e["source"])
                if e["label"] in LABEL_HEADS:
                    row["label"] = e["label"]
        edges = list(merged.values())
        return {
            "center": node_id,
            "nodes": nodes,
            "edges": edges,
            "same_as": [{"a": s["a"], "b": s["b"]} for s in sub["same_as"]],
            "truncated": sub["truncated"],
        }

    # --- 노드 상세 ----------------------------------------------------
    def node(self, node_id: str) -> dict | None:
        row = self.store.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None

        props = json.loads(row["props"] or "{}")
        # 정본이 아닌 글은 우리 말로 새로 쓴 것(summaries)이 있으면 그것을
        # 낸다. 출처 줄은 그때 '바탕으로 새로 쓴 글'이라 말한다.
        rewritten = summaries.lookup(self.store.conn, row["id"], row["description"])
        origin = desc_origin(row["source"], props, row["url"])
        if origin and rewritten:
            origin = {**origin, "rewritten": True}
        # 또 하나의 이름은 제목 줄에 세운다. '다른 이름' 더미에 같이 두면
        # 표기 변형과 구별되지 않아 별명처럼 읽힌다 (`co_names` 참고).
        names = _names(row)
        # 별칭 칸에는 로마자 표기와 마크업 조각이 섞여 들어온다 — 화면에
        # 세울 수 있는 것만 고른다 (`labels.screen_alias`). 지우지 않는
        # 이유는 검색이 별칭으로도 찾기 때문이다.
        aliases = [
            r["alias"]
            for r in self.store.conn.execute(
                "SELECT alias FROM aliases WHERE node_id = ? ORDER BY alias", (node_id,)
            )
            if r["alias"] not in names and screen_alias(r["alias"])
        ]
        rows = self.store.conn.execute(
            """SELECT e.src, e.dst, e.type, e.source, e.confidence, e.props,
                      e.label AS edge_label,
                      n.id AS other_id, n.label AS other_label, n.type AS other_type,
                      n.props AS other_props
                 FROM edges e
                 JOIN nodes n
                   ON n.id = CASE WHEN e.src = ?1 THEN e.dst ELSE e.src END
                WHERE e.src = ?1 OR e.dst = ?1""",
            (node_id,),
        ).fetchall()

        # 소스별로 나뉜 같은 사실을 한 줄로 합친다. 실측: '행주대첩 →
        # 행주산성'이 Wikidata 와 인포박스 양쪽에 있어 화면에 두 번 나왔다.
        # 지우지는 않는다 — 두 소스가 같은 말을 했다는 것 자체가 정보다.
        by_fact: dict[tuple[str, str, str], dict] = {}
        # 파에 실린 '족보에 오른 자손 수'. **화면에 세우지 않는다** — 이미
        # 설명 문장이 한 번 말했고, 관계 줄에 수를 붙이면 그 수가 '이 관계의
        # 세기'로 읽힌다. 쓰는 자리는 차례뿐이다: 전주 이씨 아래 180개를
        # 가나다로 세우면 완풍군파(124,001명)가 목록 한가운데 묻힌다
        # (graph-drawer.md §12.21 — 무게를 차례에만 쓰는 것과 같은 자리).
        clan_members: dict[str, int] = {}
        for r in rows:
            edge_props = json.loads(r["props"] or "{}")
            direction = "out" if r["src"] == node_id else "in"
            key = (r["type"], direction, r["other_id"])
            fact = by_fact.get(key)
            if fact is None:
                fact = by_fact[key] = {
                    "type": r["type"],
                    "label": EDGE_TYPES[r["type"]][0],
                    # 엣지 자신의 이름('출생'·'사망'·'아버지'). 타입 라벨보다
                    # 구체적이라 화면이 "1506년에 태어났다"까지 말할 수 있다.
                    "edge_label": r["edge_label"] or None,
                    "dir": direction,
                    "other": _other_brief(r),
                    "confidence": r["confidence"],
                    "sources": [],
                    # 추출 엣지의 근거 구절. 이걸 화면에 띄우지 않으면
                    # 사용자는 0.9 짜리 엣지를 믿을지 판단할 방법이 없다.
                    "evidence": [],
                    "original_type": edge_props.get("original_type"),
                    # 인과 엣지의 '어떻게'. 종류(edge_label)만으로는 "A 가
                    # B 의 배경"이라는 말뿐이라 무엇이 이어졌는지 모른다.
                    "how": edge_props.get("how") or None,
                    # 상대가 서술구('후금의 파약 행위')로 적혀 있었으면 그 구.
                    "as": edge_props.get("cause_as" if direction == "in" else "effect_as") or None,
                    # 인포박스 지휘관 뒤의 표식(사망·처형·피살·귀양)과 그 편의
                    # 이름('조선'·'이방석 지지파'). "지휘했다"가 "조선 측을
                    # 지휘하다 전사했다"·"살해되었다"가 되는 재료다.
                    "fate": edge_props.get("fate") or None,
                    "side_name": edge_props.get("side_name") or None,
                }
            fact["confidence"] = max(fact["confidence"], r["confidence"])
            if not fact["how"] and edge_props.get("how"):
                fact["how"] = edge_props["how"]
            if not fact["edge_label"] and r["edge_label"]:
                fact["edge_label"] = r["edge_label"]
            for k in ("fate", "side_name"):
                if not fact[k] and edge_props.get(k):
                    fact[k] = edge_props[k]
            if r["source"] not in fact["sources"]:
                fact["sources"].append(r["source"])
            if r["other_props"] and '"members"' in r["other_props"]:
                members = json.loads(r["other_props"]).get("members")
                if isinstance(members, int):
                    clan_members[r["other_id"]] = members
            if edge_props.get("evidence"):
                fact["evidence"].append(edge_props["evidence"])
            # `roles` 가 말뭉치에서 찾은 근거. 역할('대항'·'표적')을 말할 때는
            # 그 문장을 함께 보여야 한다 — 역할은 판정이고 문장은 사실이다.
            if edge_props.get("role_evidence"):
                fact["evidence"].append(edge_props["role_evidence"])
        relations = list(by_fact.values())
        # 같은 종류 안에서는 확인할 수 있는 것을 먼저 보여준다 — 여러
        # 소스가 확인해 준 사실, 그다음 근거 구절이 달린 관계 순이다.
        order = {t: i for i, t in enumerate(RELATION_ORDER)}
        # 역할이 적힌 관련(피해·표적·수습)은 참여 바로 뒤에 선다 — 맨 끝의 '관련'
        # 더미가 아니라 사건의 사람들 자리다.
        rank = lambda x: (order["participated_in"] + 0.5
                          if x["type"] == "related_to" and x["edge_label"] in ROLE_HEADS
                          else order.get(x["type"], 99))
        relations.sort(
            key=lambda x: (
                rank(x),
                -len(x["sources"]),
                -x["confidence"],
                0 if x["evidence"] else 1,
                # 파는 큰 파부터. 족보가 실제로 센 수라 자격이 있고, 쓰는
                # 자리는 차례뿐이다 (위 `clan_members` 주석).
                -clan_members.get(x["other"]["id"], 0),
                x["other"]["label"],
            )
        )

        return {
            "id": row["id"],
            "label": row["label"],
            "names": names,
            "type": row["type"],
            "group": _group(row),
            "type_label": type_label(row["type"], _props(row)),
            "source": row["source"],
            "start": row["start_date"],
            "end": row["end_date"],
            # 화면은 **요약**만 받는다 (`pages.summarize` — 첫 절 제목 앞의
            # 도입부, 문장 단위로 360자). 전문은 DB 에 그대로 있고 추출·
            # 말뭉치가 쓴다. 2026-09-05 화면에 전문을 뿌린 것이 애드센스
            # '주의 필요'(스크랩)로 돌아왔다 — 이 자리에서 전문을 다시
            # 내보내지 않는다.
            "description": rewritten or pages.summarize(row["description"]),
            # 설명이 어디서 왔는지. 'kowiki' 는 위키백과 산문, 'wd:ko' 는
            # Wikidata 한국어 한 줄, '사전' 은 영어 한 줄을 koreanize 로
            # 옮긴 것이다. 도구가 쓰라고 남겨 둔다. 화면이 그리는 것은 아래
            # `desc_origin` 이다.
            "desc_source": props.get("desc_source"),
            # 설명 아래 한 줄로 적는 출처 — 이름·문서 주소·라이선스(한국어).
            # 남의 글을 옮겼으면 그렇다고 적는 것이 라이선스 의무다
            # (provenance.py). 모르면 None 이고, 화면은 그때 아무것도 안 적는다.
            "desc_origin": origin,
            # 영어 한 줄이 왔지만 사전으로 옮기지 못해 비운 노드.
            # 빈 칸의 이유를 화면이 정확히 말할 수 있게 한다.
            "desc_dropped": bool(props.get("desc_en") and not row["description"]),
            # 넘겨주기를 따라가 다른 문서에서 가져온 글이면 그 문서명.
            # '판의금부사'의 설명은 '의금부' 문서의 글이다 — 같은 것을
            # 설명하는 글이 아니므로 그렇다고 적어야 한다.
            "desc_via": props.get("desc_via"),
            # 빈 설명칸의 이유. 한국어 위키백과에 문서가 없어서 비어 있는
            # 것과, 아직 받아오지 않아 비어 있는 것은 다른 이야기다.
            "no_kowiki": bool(props.get("no_kowiki")),
            "url": row["url"],
            "kowiki_url": props.get("kowiki_url"),
            "merged_from": props.get("merged_from") or [],
            "aliases": aliases,
            "relations": relations,
        }


    # --- 연표 ---------------------------------------------------------
    def _linked_years(self, ids: set[str]) -> dict[str, int]:
        """`time:1504` 로 이어진 해. 노드가 스스로 날짜를 말하지 않을 때 쓴다.

        실측: 갑자사화에는 start_date 가 없는데 from_period 로 time:1504 에
        붙어 있다. 이 경로가 없으면 조선 그래프에서 사화·정변 여럿이
        연표에 자리를 못 잡는다.

        여러 해가 걸려 있으면 **가장 이른 해**를 쓴다. 인물의 dated_to 에는
        출생과 사망이 함께 걸리는데, 그중 하나를 골라야 한다면 생년이
        '언제 사람인가'에 가깝다."""
        out: dict[str, int] = {}
        rows = self.store._query_chunked(
            "SELECT src AS id, dst AS t FROM edges "
            "WHERE src IN ({marks}) AND dst LIKE 'time:%'",
            ids,
        )
        # period 노드는 자기 표기와 정규 연도가 same_as 로 이어져 있다
        # ('1862년 10월' -> time:1862). 엣지만 보면 이 경로가 빠진다.
        rows += self.store._query_chunked(
            "SELECT a AS id, b AS t FROM same_as "
            "WHERE a IN ({marks}) AND b LIKE 'time:%'",
            ids,
        )
        for r in rows:
            y = _year(r["t"][len("time:"):])
            if y is None:
                continue
            if r["id"] not in out or y < out[r["id"]]:
                out[r["id"]] = y
        return out

    def _year_of(self, row) -> tuple[int | None, int | None, str]:
        """노드의 연대와, 그것을 어디서 알았는지.

        출처를 함께 돌려주는 이유: 화면이 '1504년'이라고 단정하기 전에
        그게 노드가 적고 있는 날짜인지, 시대 노드에 붙어 있어 알게 된
        것인지 구분해서 말할 수 있어야 한다."""
        start, end = _span(row)
        if start is not None:
            return start, end, "node"
        linked = self._linked_years({row["id"]}).get(row["id"])
        return (linked, None, "edge") if linked is not None else (None, None, "")

    def _polities(self) -> list[dict]:
        """연표에 세울 나라들 — 시대 묶음의 정체 노드 중 나라인 것.

        맨 앞이 이 그래프의 중심(`root`)이고, 연표의 시작이다. 날짜가
        없는 정체(대한민국 Q884 는 장소로 앉아 있고 날짜가 없다)는 세울
        자리가 없어 뺀다 — 그 해는 '대한민국 정부 수립' 사건이 맡는다."""
        cached = getattr(self._local, "polities", None)
        if cached is not None:
            return cached
        from .scope import ERAS, eras_of

        out: list[dict] = []
        for key in eras_of(self.era):
            era = ERAS.get(key)
            if era is None or not era.state:
                continue
            for qid in (era.polity_qid, *era.successor_states):
                row = self.store.conn.execute(
                    "SELECT id, type, label, start_date, end_date FROM nodes WHERE id = ?",
                    (f"wd:{qid}",),
                ).fetchone()
                if row is None:
                    continue
                p_start, p_end = _span(row)
                if p_start is None:
                    continue
                out.append({
                    "id": row["id"], "label": row["label"], "type": row["type"],
                    "group": TYPE_GROUP.get(row["type"], "thing"),
                    "year": p_start, "end": p_end,
                    "date": row["start_date"] or "",
                    "founded": True,
                })
        self._local.polities = out
        return out

    def _anchors(self) -> list[dict]:
        """시대의 뼈대 — 그 무렵의 큰일. 연표 전체에 고르게 깔린다.

        **솎지 않는다.** 연대를 아는 사건은 다 세운다 — 연표에서 빠진
        사건은 읽는 사람에게 그 시대에 없었던 일이 된다. 몰린 곳(1592년
        한 해에 38건)은 화면이 그 해를 늘려 세우므로, 라벨이 제 해를
        떠나지 않는다.

        무게는 자를 자리가 아니라 **줄 세울 자리**다. 이름도 해도 같은
        노드가 둘일 때 무거운 쪽을 남기려고 내림차순으로 훑는다.
        수를 세어 자르면 자료가 얇은 시대가 먼저 사라진다 — 고려의 사건은
        엣지가 둘셋뿐이라 조선에 밀린다.

        연도를 못 찾은 사건은 뺀다 — 연표에 놓을 자리가 없다.
        (조선 그래프 실측: 사건 297개 중 연도가 잡히는 것은 76개다.)"""
        cached = getattr(self._local, "anchors", None)
        if cached is not None:
            return cached
        join, order = self._weighted()
        rows = self.store.conn.execute(
            f"""SELECT n.id, n.type, n.label, n.start_date, n.end_date,
                      COUNT(e.src) AS d
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                 {join}
                WHERE n.type = 'event'
             GROUP BY n.id
             ORDER BY {order}"""
        ).fetchall()
        undated = {r["id"] for r in rows if _span(r)[0] is None}
        linked = self._linked_years(undated) if undated else {}

        out: list[dict] = []
        seen_labels: set[tuple[str, int]] = set()
        for r in rows:
            start, end = _span(r)
            if start is None:
                start = linked.get(r["id"])
            if start is None:
                continue
            # **한 번 언급된 추출 고아는 뼈대가 못 된다.** `ex:` 노드는
            # 산문에서 이름만 뽑혀 나온 것이고, 엣지가 하나뿐이면 아무도
            # 확인해 주지 않았다는 뜻이다. 실측: '1908년 복권'·'1963년
            # 문집 간행'이 그렇게 들어와 축을 1963년까지 늘려 놓았다
            # (사건 이름도 아니다). 여럿이 가리키는 것은 남긴다 —
            # 진산사건(1791, 차수 3)이 1728~1791년의 빈 구간을 메운다.
            if r["id"].startswith("ex:") and r["d"] < 2:
                continue
            # **이름도 해도 같으면 한 줄만 세운다.** 실측: 임진왜란이
            # wd:Q122846639(차수 37)와 wd:Q576338(차수 1) 둘로 있어 1592년
            # 자리에 같은 이름이 나란히 찍혔다. 화면에서 둘은 구별되지
            # 않으므로 무거운 쪽만 남긴다 (rows 가 무게 내림차순).
            # 노드를 합치지는 않는다 — 라벨 유사도로 합치면 제1차/제2차
            # 요동 정벌이 한 노드가 된다. 여기서는 보이는 것만 정리한다.
            # 이름을 못 받아온 노드는 연표에 세울 수 없다. 라벨이 QID
            # 그대로면(wd:Q85881723 → 'Q85881723') 읽는 사람에게 아무
            # 말도 하지 않는 줄이 된다. 조선 그래프에 한 건 있다.
            if UNLABELED.match(r["label"]):
                continue
            if (r["label"], start) in seen_labels:
                continue
            seen_labels.add((r["label"], start))
            out.append({
                "id": r["id"], "label": r["label"], "type": r["type"],
                "group": TYPE_GROUP.get(r["type"], "thing"),
                "year": start, "end": end, "degree": r["d"],
                # 화면이 몰린 해를 늘려 세운다. 그 안의 차례가 시간 순으로
                # 읽히므로 연도만으로는 모자라다 (1592년 사건이 38건이다).
                "date": r["start_date"] or "",
            })
        out.sort(key=lambda a: a["year"])
        self._local.anchors = out
        return out

    def _reigns(self) -> list[dict]:
        """왕의 재위 띠 — 연표 왼쪽에 세로로 서는 자(尺).

        **사건의 자리를 재는 눈금은 왕이다.** 사람이 조선의 시간을 읽는
        방식이 그렇다 — '1456년'보다 '세조 2년'이, '1592년'보다 '선조
        때'가 먼저 온다. 그래서 이 띠는 고른 노드가 무엇이든 늘 서 있다.

        재위는 노드가 아니라 **엣지**에 적혀 있다 (`histgraph reigns` 가
        P39 문장의 한정어를 옮겨 적는다). 날짜가 붙은 held_position 이
        재위뿐인 것은 지금 우연이므로, `props.reign` 표식이 있는 것만
        고른다 — 나중에 영의정 재임 기간이 들어와도 왕의 띠에 서지 않는다.

        **사망은 재위의 끝이 아니다.** 태조는 1398년에 물러나 1408년에
        죽었고, 고종은 1907년에 물러나 1919년에 죽었다. 둘을 한 점으로
        합치면 상왕으로 산 10년이 사라진다. 그래서 재위 구간과 몰년을
        따로 넘긴다.

        **대통령도 같은 띠다.** 1948년 뒤의 시간은 '박정희 때'로 읽힌다.
        표식의 값이 자리의 종류(`monarch`·`president`)라 화면이 '재위'와
        '재임'을 갈라 부른다. 예전 표식 `true` 는 군주다.

        **재임 중인 사람은 끝이 없다.** 끝을 모르는 것과 아직 안 끝난 것은
        다르다 — 살아 있고 끝 날짜가 없으면 오늘까지 긋고 `ongoing` 으로
        밝힌다. 죽은 사람의 빈 끝은 전처럼 몰년으로 닫는다."""
        cached = getattr(self._local, "reigns", None)
        if cached is not None:
            return cached
        rows = self.store.conn.execute(
            """SELECT e.src AS id, e.start_date AS r_start, e.end_date AS r_end,
                      n.label, n.type, n.start_date, n.end_date,
                      p.label AS position,
                      json_extract(e.props, '$.reign') AS seat
                 FROM edges e
                 JOIN nodes n ON n.id = e.src
                 JOIN nodes p ON p.id = e.dst
                WHERE e.type = 'held_position'
                  AND json_extract(e.props, '$.reign') IS NOT NULL
                  AND e.start_date IS NOT NULL AND e.start_date != ''
             ORDER BY e.start_date"""
        ).fetchall()

        this_year = datetime.date.today().year
        out: list[dict] = []
        # **한 사람이 같은 때 두 자리에 앉지는 않는다.** 엣지의 자연키에
        # 소스가 들어 있어 같은 재위가 소스 수만큼 줄이 되고(고려 공민왕·
        # 우왕은 Wikidata 와 위키백과 양쪽에서 왔다), 자리 이름이 자료마다
        # 다르기도 하다(고려 광종은 '군주'와 '왕(王)'에 둘 다 걸려 있다).
        # 그래서 겹치는 구간은 한 띠로 모은다.
        #
        # **잇달아 있는 것은 안 모은다** — 고종의 조선 임금(1863~1897)과
        # 대한제국 황제(1897~1907)는 다른 자리이고, 합치면 대한제국이
        # 언제 섰는지가 띠에서 사라진다.
        bands: dict[str, list[dict]] = {}
        for r in rows:
            start = _year(r["r_start"])
            if start is None:
                continue
            # 해 안의 자리. 띠와 이름을 취임한 날에 앉히려면 해만으로는 모자란다.
            at_start = _year_at(r["r_start"])
            at_end = _year_at(r["r_end"])
            at_death = _year_at(r["end_date"])
            # 재위 끝이 비어 있으면(재위 중 죽은 임금 일부) 몰년으로 닫는다.
            # 그것도 없고 살아 있으면 재임 중이다. 죽었는데 몰년도 없으면
            # 한 점으로 둔다 — 모르는 끝을 오늘로 늘리지 않는다.
            death = _year(r["end_date"])
            end = _year(r["r_end"])
            ongoing = False
            if end is None:
                if death is not None:
                    end = death if death >= start else start
                    at_end = at_death if end == death else at_start
                elif r["end_date"]:
                    end = start
                    at_end = at_start
                else:
                    end = max(this_year, start)
                    ongoing = True
            # 몰년이 재위 끝과 같은 해면 소수 자리에서 앞설 수 있다 (고려
            # 광종: 끝 07-09 · 몰 07-01). 막대 위에 동그라미가 뜨지 않게
            # 막대 끝까지 민다 — 어느 쪽이 하루 이른지는 자료가 못 가른다.
            if at_death is not None and at_end is not None and at_death < at_end:
                at_death = at_end
            mine = bands.setdefault(r["id"], [])
            overlap = next(
                (b for b in mine
                 if b["kind"] == ("president" if r["seat"] == "president" else "monarch")
                 and b["start"] < end and start < b["end"]),
                None,
            )
            if overlap is not None:
                if start < overlap["start"]:
                    overlap["at_start"] = at_start
                    overlap["start_date"] = r["r_start"] or None
                overlap["start"] = min(overlap["start"], start)
                if end > overlap["end"]:
                    overlap["at_end"] = at_end
                    overlap["end_date"] = r["r_end"] or None
                overlap["end"] = max(overlap["end"], end)
                continue
            band = {
                "id": r["id"], "label": r["label"],
                "position": r["position"],
                "kind": "president" if r["seat"] == "president" else "monarch",
                "start": start, "end": end,
                # 해 안의 자리. 두 가지로 준다 — 화면이 **그 해에 선 사건들
                # 사이의 차례**로 앉힐 때는 날짜가 필요하고(`dateRuler`),
                # 사건이 하나도 없는 해는 소수로 나눠 앉힌다.
                "at_start": at_start,
                "at_end": at_end if at_end is not None and not ongoing else None,
                "start_date": r["r_start"] or None,
                "end_date": r["r_end"] if not ongoing else None,
                "ongoing": ongoing,
                # 몰년이 재위 끝보다 앞서면 둘 중 하나가 틀린 것이다.
                # 화면이 거꾸로 된 꼬리를 그리지 않게 여기서 뗀다.
                "death": death if death is not None and death >= end else None,
                "at_death": at_death if death is not None and death >= end else None,
                "death_date": r["end_date"] if death is not None and death >= end else None,
                "birth": _year(r["start_date"]),
            }
            mine.append(band)
            out.append(band)
        self._local.reigns = out
        return out

    def _mark_causes(self, marks: list[dict]) -> list[list[str]]:
        """연표에 함께 선 마크들 사이의 인과 — [원인 id, 결과 id].

        같은 해의 쌍만 준다. 화면은 해가 다른 두 마크를 축으로 이미
        갈라 놓으므로 그 쌍은 차례를 다툴 일이 없고, 뼈대를 통째로
        보내는 연표에서는 쌍의 수가 마크 수만큼 늘어나 봐야 소용이 없다.

        질의는 마크 아이디를 400개씩 끊어 몇 번으로 끝낸다 (뼈대가 수백
        이라 한 번에 넣으면 SQLite 의 변수 한도에 걸린다)."""
        year_of: dict[str, int] = {}
        for m in marks:
            year_of.setdefault(m["id"], m["year"])
        ids = list(year_of)
        if not ids:
            return []
        pairs: set[tuple[str, str]] = set()
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            holes = ",".join("?" * len(chunk))
            for r in self.store.conn.execute(
                f"""SELECT DISTINCT src, dst FROM edges
                     WHERE type = 'caused' AND src IN ({holes})""",
                chunk,
            ).fetchall():
                src, dst = r["src"], r["dst"]
                if src == dst or dst not in year_of:
                    continue
                if year_of[src] != year_of[dst]:
                    continue
                pairs.add((src, dst))
        return [[s, d] for s, d in sorted(pairs)]

    def timeline(self, node_id: str) -> dict | None:
        """이 노드가 몇 년쯤의 일이고, 그 앞뒤에 무엇이 있었나.

        세 겹으로 답한다:
          - `self`   — 노드 자신의 연도(또는 생몰·존속 구간)
          - `near`   — 연도를 아는 **직접 이웃**. 이 노드의 개인 연표다.
          - `anchor` — 그 무렵의 큰 사건. 절대 연도를 못 외우는 사람에게
                       "임진왜란 다음 해"가 훨씬 정확한 위치다.

        창(window) 밖의 큰 사건도 앞뒤로 둘씩 붙인다. 창 안이 비어 있어도
        '무엇 뒤, 무엇 앞'은 언제나 말할 수 있어야 하기 때문이다."""
        row = self.store.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None

        start, end, origin = self._year_of(row)
        polities = self._polities()
        founded_ids = {p["id"] for p in polities}
        marks: list[dict] = []
        if start is not None:
            marks.append({
                "id": row["id"], "label": row["label"], "type": row["type"],
                "group": TYPE_GROUP.get(row["type"], "thing"),
                "year": start, "end": end, "kind": "self",
                "date": row["start_date"] or "",
                # 나라 자신을 골랐으면 그 첫 해도 건국이다
                "founded": row["id"] in founded_ids,
            })

        # --- 연도를 아는 직접 이웃 -------------------------------------
        # 날짜가 있거나 시대 노드에 붙어 있는 이웃만 가져온다. 조선처럼
        # 이웃이 수천인 허브에서 전부 끌어오면 연표 한 번에 그래프 절반을
        # 읽게 된다.
        kinds = ",".join(f"'{t}'" for t in POINT_TYPES)   # 코드 안의 고정 목록이다
        rows = self.store.conn.execute(
            f"""SELECT e.type AS rel, e.label AS rel_label,
                       CASE WHEN e.src = ?1 THEN 'out' ELSE 'in' END AS dir,
                       n.id, n.type, n.label, n.start_date, n.end_date
                  FROM edges e
                  JOIN nodes n
                    ON n.id = CASE WHEN e.src = ?1 THEN e.dst ELSE e.src END
                 WHERE (e.src = ?1 OR e.dst = ?1)
                   AND n.id != ?1
                   AND n.type IN ({kinds})
                   AND ((n.start_date IS NOT NULL AND n.start_date != '')
                        OR EXISTS (SELECT 1 FROM edges t
                                    WHERE t.src = n.id AND t.dst LIKE 'time:%'))""",
            (node_id,),
        ).fetchall()

        # 상대 하나에 카드 하나. '관련'은 구체 관계에 밀린다 — 상세 패널이
        # 같은 이유로 접는 관계다.
        picked: dict[str, dict] = {}
        for r in rows:
            cur = picked.get(r["id"])
            if cur is not None and (cur["rel"] != "related_to" or r["rel"] == "related_to"):
                continue
            picked[r["id"]] = {"row": r, "rel": r["rel"], "dir": r["dir"],
                               "rel_label": r["rel_label"]}

        undated = {k for k, v in picked.items() if _span(v["row"])[0] is None}
        linked = self._linked_years(undated) if undated else {}
        near: list[dict] = []
        for nid, v in picked.items():
            y, y_end = _span(v["row"])
            if y is None:
                y = linked.get(nid)
            if y is None:
                continue
            near.append({
                "id": nid, "label": v["row"]["label"], "type": v["row"]["type"],
                "group": TYPE_GROUP.get(v["row"]["type"], "thing"),
                "year": y, "end": y_end, "kind": "near",
                "date": v["row"]["start_date"] or "",
                # 화면이 관계 이름을 붙여 부를 수 있게 그대로 넘긴다
                # 라벨이 타입보다 정확하면 그 이름으로 부른다 — 연표의 딱지가
                # '관련'이 아니라 '피해'·'다음 일'이라고 말한다. `specific` 은
                # 화면이 방향으로 다시 부르지 말라는 표식이다.
                "rel": _rel_name(v["rel"], v["dir"], v["rel_label"]),
            })
        # 노드 자신의 연도에서 가까운 것부터 남긴다. 연도를 모르면 그냥
        # 이른 순 — 아무 기준 없이 자르는 것보다 낫다.
        pivot = start if start is not None else (
            sorted(n["year"] for n in near)[len(near) // 2] if near else 0
        )
        near = [n for n in near if abs(n["year"] - pivot) <= NEAR_WINDOW]
        near.sort(key=lambda n: (abs(n["year"] - pivot), n["year"]))
        near = near[:TIMELINE_NEAR]
        marks.extend(near)

        # --- 그 무렵의 큰 사건 -----------------------------------------
        # **뼈대는 통째로 보낸다.** 고른 노드 언저리만 잘라 보내면 연표가
        # 그 노드만큼만 길어서, 화면에서 위아래로 훑어도 시대의 처음과
        # 끝에 닿지 못한다. 자를 이유도 없다 — 십년마다 둘로 솎아 두어
        # 조선 그래프에서 쉰 남짓이다.
        seen = {m["id"] for m in marks}
        # 이웃으로 이미 선 것과 이름·해가 같은 뼈대도 뺀다. 노드는 달라도
        # 화면에서는 같은 줄이 두 번 찍힌 것으로만 보인다.
        seen_labels = {(m["label"], m["year"]) for m in marks}
        anchors = self._anchors()
        marks.extend(
            dict(a, kind="anchor") for a in anchors
            if a["id"] not in seen and (a["label"], a["year"]) not in seen_labels
        )
        # **나라 자신도 세운다.** 조선의 존속 기간은 1392-08-13~1897-10-12
        # 인데 org 라서 사건 뼈대에 못 들어왔고, 1392년 자리가 비어 있었다 —
        # 연표를 훑으면 위화도 회군(1388) 다음이 곧장 제1차 왕자의
        # 난(1398)이다. 그래프에 '조선 건국' 이라는 사건 노드가 있지만
        # 날짜가 없고 엣지 둘뿐인 추출 고아라, 거기에 왕조의 P571 을
        # 옮겨 적는 것은 추측이 된다. 나라 노드가 자기 날짜로 서면 된다.
        #
        # 묶음(조선~대한민국)이면 뒤따르는 나라(대한제국)도 같은 꼴로 선다.
        # `founded` 는 화면이 그 첫 해에 '건국'을 달라는 표식이다 — 이름만
        # 적으면 '조선'이 1392년에 무엇을 했다는 것처럼 읽힌다.
        seen = {m["id"] for m in marks}
        marks.extend(
            dict(p, kind="era") for p in polities if p["id"] not in seen
        )

        # **연표는 맨 앞 나라의 건국에서 시작한다** (2026-09-05 사용자 요청).
        # 조선 그래프에 고려의 사건이 맥락으로 남아 있어(위화도 회군 1388,
        # 멀리는 1100년 '삼사') 축이 1097년부터 늘어져 있었고, 왼쪽 띠에는
        # 고려 공양왕이 섰다. 건국 앞의 뼈대·이웃·재위는 뺀다.
        #
        # **고른 노드 자신이 건국보다 앞서면 그 해까지는 연다** (태조 이성계는
        # 1335년생, 정도전은 1342년생). 자기 자리를 못 세우는 연표는 연표가
        # 아니다 — 그때는 그 해 뒤의 이웃·뼈대도 함께 남긴다.
        floor = polities[0]["year"] if polities else None
        if floor is not None:
            if start is not None:
                floor = min(floor, start)
            marks = [m for m in marks if m["kind"] == "self" or m["year"] >= floor]

        marks.sort(key=lambda m: (m["year"], m["label"]))

        # **같은 해 안의 인과.** 연표의 차례는 곧 시간 순으로 읽히므로
        # 원인이 결과보다 위에 서야 한다 (CLAUDE.md 1-5). 화면은 지금까지
        # 고른 노드와 그 이웃 사이의 인과(`rel`)만 알아서, 둘 다 뼈대인
        # 쌍은 날짜 문자열 순으로만 섰다 — 한일병합과 무단통치는 같은 날
        # (1910-08-29)이라 가나다로 갈렸고, 을사조약(1905-11-17)은 그
        # 결과인 애국계몽운동(1905) 아래에 섰다 (2026-09-08 지적).
        # 마크들 **사이의** caused 엣지를 함께 보내 화면이 차례를 세운다.
        # 다른 해의 쌍은 축이 이미 갈라 놓으므로 보내지 않는다.
        # 보내는 것은 아이디 쌍뿐이다 — 화면에 새 글자가 서지 않는다.
        causes = self._mark_causes(marks)

        # 자리를 무엇에 기대어 잡았는지. 화면이 단정할 수 있는 범위가
        # 여기서 갈린다.
        basis = "self" if start is not None else "near" if near else "era"

        # --- 축 ---------------------------------------------------------
        # **왕의 띠도 축 안에 들어와야 한다.** 축을 사건만으로 잡으면
        # 고종이 1919년에 죽은 것이 축 밖으로 밀려 띠가 잘린다.
        reigns = self._reigns()
        if floor is not None:
            reigns = [r for r in reigns if r["start"] >= floor]
        span_years = [m["year"] for m in marks] + [
            m["end"] for m in marks if m.get("end") is not None
        ] + [r["start"] for r in reigns] + [
            r["death"] or r["end"] for r in reigns
        ]
        # 처음·끝 표시가 가장자리에 딱 붙지 않게 몇 해만 띄운다. 비율로
        # 잡으면 축이 시대 전체(600년)라 앞뒤로 36년씩 빈 데가 생긴다.
        if span_years:
            axis_from, axis_to = min(span_years) - 3, max(span_years) + 3
        else:
            axis_from = axis_to = 0

        return {
            "id": row["id"],
            "label": row["label"],
            "type": row["type"],
            "group": _group(row),
            "type_label": type_label(row["type"], _props(row)),
            "year": start,
            "end": end,
            # '' 이면 이 노드의 연도를 우리가 모른다는 뜻이다. 화면은
            # 이웃의 연대로 자리만 가늠해 주고 단정하지 않는다.
            "year_source": origin,
            # self: 노드가 자기 연도를 안다 / near: 연도를 아는 이웃으로
            # 자리만 가늠했다 / era: 아무것도 몰라 시대만 펼쳤다
            "basis": basis,
            # 이 연표가 담은 처음과 끝 해. 화면의 훑기 막대가 쓰는 눈금이다.
            "axis": {"from": axis_from, "to": axis_to},
            "marks": marks,
            # [원인 id, 결과 id] — 같은 해에 함께 선 마크들 사이의 인과.
            "causes": causes,
            # 왕의 재위 띠. 고른 노드와 무관하게 늘 같은 자를 세운다.
            "reigns": reigns,
        }


    # --- 개인 역사 -----------------------------------------------------
    def context(self, year_from: int, year_to: int) -> dict:
        """어느 구간의 왕·대통령 재위 띠와 큰 사건 — 개인 연표의 왼쪽과 가운데.

        개인 연표는 한 사람의 일생(수십 년)이라 시대 전체의 뼈대를 다 보낼
        이유가 없다. 구간에 걸치는 재위(끝이 시작보다 뒤, 시작이 끝보다 앞)와
        그 안의 사건만 준다. 사건은 `_anchors` 와 같은 규칙으로 고른 것이라
        시대 연표와 개인 연표가 같은 사건을 세운다."""
        if year_to < year_from:
            year_from, year_to = year_to, year_from
        # 구간을 재는 것은 재위이지 몰년이 아니다 — 윤보선(재위 1960~62, 몰
        # 1990)이 1985년생의 축에 서면 안 된다. 띠 안의 몰년 꼬리는 화면이 긋는다.
        reigns = [r for r in self._reigns()
                  if r["start"] <= year_to and r["end"] >= year_from]
        anchors = [dict(a, kind="anchor") for a in self._anchors()
                   if year_from <= a["year"] <= year_to]
        return {"axis": {"from": year_from, "to": year_to},
                "reigns": reigns, "anchors": anchors}



# --- 개인 역사 분석 (로컬 전용) --------------------------------------------
# 화면의 '내 인생 입력하기' 가 글을 보내면 여기서 모델에게 묻는다. CLI 의
# `histgraph life 이야기.txt` 와 같은 길을 지난다 (analyze → validate → link
# → save) — 사람이 파일을 만들고 터미널을 열지 않아도 되게 한 것뿐이다.
#
# **응답에 매달아 두지 않는다.** MLX 는 35GB 를 잡고 몇 분을 돈다. 요청
# 하나를 그동안 붙들고 있으면 브라우저가 먼저 끊고, 끊긴 뒤에도 모델은
# 계속 돈다. 그래서 스레드에 맡기고 화면이 `/api/life/job` 으로 물어본다.
# **한 번에 하나만** 돈다 — 두 개를 띄우면 자리가 없어 커널이 죽인다.
#
# **배포는 그 길로 못 간다.** 서버리스 함수는 요청과 함께 태어나 응답과 함께
# 죽어서, 띄워 둔 스레드도 그것이 적은 상태도 다음 요청이 보지 못한다. 그래서
# 배포는 같은 몸통을 요청 하나 안에서 돌린다 (`life_post(blocking=True)` —
# 밖의 무료 모델이 실측 54초라 그 안에 든다). 남는 차이가 저장이다: 배포는
# 파일을 만들지 않는다 (`save=False`). 모델은 둘이다 — 로컬 MLX 와 OpenRouter
# 의 무료 모델. 어느 쪽인지는 `.env` 의 열쇠가 정한다
# (`backends.default_life_backend`).
# 모델에게 보일 그래프 사건 목록의 시작 해. CLI 는 1940 을 기본으로 물어보지만
# 화면은 생년을 묻지 않으므로 조금 앞에서 시작한다 (1900~오늘 = 사건 221건).
LIFE_FROM_YEAR = 1900
# 기다리는 사람에게 무엇을 기다리는지 적는다. 로컬 모델은 35GB 를 읽느라
# 첫 몇 분이 조용하고, OpenRouter 는 남의 GPU 라 그 줄이 없다.
FIRST_STEP = {"mlx": "모델을 올리는 중", "openrouter": "모델에게 묻는 중",
              "anthropic": "모델에게 묻는 중"}


def _life_name(name: str) -> str:
    """저장 파일 이름. 화면이 준 이름이 경로가 되지 않게 한다."""
    safe = re.sub(r"[^\w가-힣 .-]", "", (name or "").strip()).strip(". ")
    return safe[:40] or "나"


def _life_story(doc: dict) -> str | None:
    """이 그래프를 만든 이야기 원문 (data/life/<이름>.txt). 없으면 None.

    인물의 생몰년을 여기에 대 본다 — 이야기가 말하지 않은 생년은 화면에 세우지
    않는다 (2026-09-08 사용자). 이 컴퓨터에 원문이 없으면 재지 않는다."""
    from . import life as life_mod

    name = ((doc.get("subject") or {}).get("name") or "").strip()
    if not name:
        return None
    path = life_mod.LIFE_DIR / f"{_life_name(name)}.txt"
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except OSError:
        return None


class LifeAnalysis:
    """이야기 → 개인 그래프. 한 번에 하나, 상태는 화면이 물어 간다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {"state": "idle"}

    def status(self) -> dict:
        """지금 상태. **어느 모델로 읽는지도 같이 준다** — 화면이 '글이 이
        컴퓨터 밖으로 나가지 않는다'고 적어도 되는지가 그것으로 갈린다."""
        from .backends import default_life_backend

        with self._lock:
            st = dict(self._state)
        started = st.pop("started", None)
        if st.get("state") == "running" and started is not None:
            st["elapsed"] = int(time.time() - started)
        st.setdefault("backend", default_life_backend())
        # **답이 어떻게 오는가.** 배포(서버리스)에는 다음 요청까지 살아 있는
        # 스레드가 없어 분석이 요청 하나 안에서 끝난다 (`life_post(blocking=True)`).
        # 화면은 그것을 보고 기다리는 모습을 바꾼다 — 초를 스스로 세고, 창을
        # 닫아도 된다는 말을 하지 않는다 (LifeView).
        st["blocking"] = bool(os.environ.get("VERCEL"))
        return st

    def start(self, api: GraphAPI, text: str, name: str = "나",
              backend: str = "", base: dict | None = None) -> bool:
        """분석을 띄운다. 이미 돌고 있으면 False.

        백엔드를 안 주면 `.env` 를 보고 고른다 — 열쇠가 있으면 OpenRouter
        (무료 모델), 없으면 로컬 MLX (`backends.default_life_backend`).
        화면은 어느 쪽인지 묻지 않는다."""
        from .backends import default_life_backend

        kind = backend or default_life_backend()
        with self._lock:
            if self._state.get("state") == "running":
                return False
            self._state = {"state": "running", "started": time.time(), "backend": kind,
                           "step": FIRST_STEP.get(kind, "모델에게 묻는 중")}
        threading.Thread(target=self._run, args=(api, text, name, kind, base),
                         name="life-analyze", daemon=True).start()
        return True

    def _step(self, step: str) -> None:
        with self._lock:
            if self._state.get("state") == "running":
                self._state["step"] = step

    def _done(self, state: dict) -> None:
        with self._lock:
            self._state = state

    def _run(self, api: GraphAPI, text: str, name: str, backend_kind: str,
             base: dict | None = None) -> None:
        """스레드가 도는 자리. 일은 `run_analysis` 가 하고 여기는 상태만 든다."""
        self._done(run_analysis(api, text, name, backend_kind, base,
                                save=True, step=self._step))


def model_silence(why: str) -> str:
    """모델이 답을 안 준 까닭을 **한국어 한 문장으로**. 화면이 그대로 읽는다.

    까닭을 말해야 사람이 다음에 무엇을 할지 안다 — 붐비는 것이면 다시 누르면
    되고, 열쇠가 없는 것이면 눌러도 소용없다. 상류가 주는 말은 영어라 화면에
    그대로 옮기지 않는다 (CLAUDE.md §1). 원문은 `detail` 로 따로 실어 보낸다."""
    low = (why or "").lower()
    if "429" in low or "rate" in low or "quota" in low:
        return "지금 모델이 붐빕니다. 잠시 뒤에 다시 눌러 주세요."
    if any(code in low for code in ("500", "502", "503", "504")) or "연결 실패" in why:
        return "모델 쪽이 잠시 응답하지 않습니다. 잠시 뒤에 다시 눌러 주세요."
    if "api_key" in low:      # 열쇠가 없다 — 다시 눌러도 소용없다
        return "이야기를 읽을 모델이 준비되지 않았습니다."
    return "모델이 답을 돌려주지 않았습니다. 잠시 뒤에 다시 눌러 주세요."


def run_analysis(api: GraphAPI, text: str, name: str = "나", backend_kind: str = "",
                 base: dict | None = None, *, save: bool = True,
                 step: Callable[[str], None] | None = None) -> dict:
    """이야기 → 개인 그래프. **답이 나올 때까지 돈다.**

    돌려주는 것은 화면이 `/api/life/job` 에서 받는 것과 같은 상태 문서다
    (`state`·`payload`·`notes`·`took`). 부르는 자리가 둘이라 여기 있다 — 로컬
    서버는 스레드에 태워 돌리고(`LifeAnalysis`), 배포는 요청 하나 안에서 곧장
    돈다(`life_post(blocking=True)`). 서버리스에는 다음 요청까지 살아 있는
    스레드가 없어 **띄워 두고 물어보는 길이 아예 없다.**

    `base` 가 있으면 **그 그래프에 더한다** — 화면이 쥔 것을 보내 준다.
    없으면 새로 만든다 (life.merge 머리글).

    `save` 가 거짓이면 파일을 만들지 않는다. 배포가 그렇다 — 서버리스 디스크는
    읽기 전용이고, 무엇보다 **남의 삶이 적힌 글을 우리 서버에 남기지 않는다**
    (2026-09-07 결정). 그 자리에서 문서를 드는 것은 브라우저와, 사람이 '내
    계정에 저장' 을 누른 계정뿐이다.
    """
    from . import life as life_mod
    from .backends import build_backend

    # 어디까지 왔는지 적는 자리. 스레드로 돌 때만 누가 읽는다 — 한 요청 안에서
    # 도는 자리에서는 아무도 못 보므로 아무 데도 안 적는다.
    say = step or (lambda _step: None)
    started = time.time()
    try:
        # 이야기가 걸칠 만한 구간의 사건 이름을 모델에게 보인다. 생년은
        # 아직 모르니 LIFE_FROM_YEAR 부터 오늘까지다 (cli.cmd_life 와 같다).
        anchors = api.context(LIFE_FROM_YEAR, datetime.date.today().year)["anchors"]
        backend = build_backend(backend_kind)
        say("이야기를 읽는 중")
        existing = life_mod.existing_summary(base) if base else None
        raw = life_mod.analyze(text, backend, anchors=anchors, existing=existing)
        if raw is None:
            why = getattr(backend, "last_error", "")
            # `detail` 은 화면이 안 그린다 — 배포에서 로그를 못 보는 사람이
            # 무슨 일이 있었는지 물어 볼 수 있게 답에 실어 둔다.
            return {"state": "error", "error": model_silence(why), "detail": why[:300]}
        raw["_model"] = getattr(backend, "model", backend_kind)
        say("답을 검증하는 중")
        payload, notes = life_mod.validate(raw, subject=(base or {}).get("subject"), text=text,
                                   known=life_mod.known_ids(base))
        say("한국사 사건에 잇는 중")
        life_mod.link(payload, api)
        # 이야기가 부르지 않은 역사는 잇지 않는다 (2026-09-08 "세월호 사건과
        # 퍼듀대학교 졸업은 도대체 무슨 상관이지?"). 더할 때는 옛 이야기까지
        # 합쳐 옛 연결도 다시 잰다.
        life_mod.gate_connections(payload, text)
        added = None
        out = life_mod.LIFE_DIR / f"{_life_name(name)}.json" if save else None
        if base:
            say("있는 역사에 더하는 중")
            payload, added = life_mod.merge(base, payload, text)
            whole = _life_story(base) or ""
            life_mod.gate_connections(payload, "\n".join(x for x in (whole, text) if x) or None)
            notes = payload.get("notes") or notes
        if out is not None:
            say("저장하는 중")
            try:
                life_mod.save(payload, out)
                # 이야기 원문도 옆에 둔다 — 고쳐 쓰고 `histgraph life` 로
                # 다시 돌릴 수 있게. 여기도 저장소 밖이다. 더한 이야기는 뒤에 잇는다.
                txt = out.with_suffix(".txt")
                if base and txt.is_file():
                    txt.write_text(txt.read_text(encoding="utf-8").rstrip() + "\n\n" + text, encoding="utf-8")
                else:
                    txt.write_text(text, encoding="utf-8")
            except OSError as err:
                notes = [*notes, f"저장하지 못했습니다: {err}"]
                out = None
        return {"state": "done", "payload": payload, "notes": notes,
                "file": out.name if out else None, "added": added,
                "took": int(time.time() - started)}
    except Exception as err:  # 모델이 없는·메모리가 없는 자리에서도 화면은 살아야 한다
        log.exception("개인 역사 분석 실패")
        return {"state": "error", "error": f"{type(err).__name__}: {err}"}




LIFE_JOBS = LifeAnalysis()


# 개인 역사가 쓰는 POST 두 길. 몸통이 여기 하나인 것은 **부르는 자리가 둘**이기
# 때문이다 — 로컬 서버(`Handler.do_POST`)와 배포(`api/index.py`). 둘의 차이는
# 셋뿐이고 전부 인자로 나온다: 답을 기다리는가(`blocking`), 파일을 남기는가
# (`save`), 그리고 로그인을 요구하는가(부르는 쪽이 미리 잰다).
LIFE_POSTS = ("/api/life/analyze", "/api/life/refine")
# 개인 역사의 몸은 가입 요청보다 크다 — 이야기에 **지금까지 만든 그래프**(`base`,
# 계정 한도 512KB)가 함께 실린다. 가입 쪽 한도로 재면 오래 쓴 사람의 두 번째
# 이야기가 조용히 빈 몸이 되어 '이야기가 비어 있습니다' 로 떨어진다.
LIFE_MAX_BODY = 2 << 20


def life_post(api: GraphAPI, path: str, raw: bytes, *,
              blocking: bool = False, save: bool = True) -> tuple[int, dict]:
    """개인 역사의 POST 를 처리하고 `(상태코드, 몸)` 을 돌려준다.

    `blocking` 이면 분석이 끝날 때까지 돌고 **끝난 상태 문서를 그대로** 준다.
    아니면 스레드에 띄우고 202 로 물러난다 (로컬 MLX 는 몇 분이라 요청 하나에
    매달 수 없다). 화면은 둘을 **몸으로** 가른다 — `state` 가 `done`·`error`
    면 다 온 것이고 `running` 이면 `/api/life/job` 으로 물어본다.
    """
    from . import life as life_mod

    try:
        body = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "JSON 이 아닙니다"}

    # 이미 있는 그래프를 모델 없이 다듬기만 한다 (life.refine) — 화면이 브라우저·
    # 계정에서 읽은 옛 자료를 부팅 때 보내, 규칙이 는 만큼 해·연결을 채운다.
    if path == "/api/life/refine":
        if not (isinstance(body, dict) and isinstance(body.get("nodes"), list)):
            return 400, {"error": "그래프가 아닙니다"}
        # 이야기 원문이 옆에 있으면 같이 준다 — 인물·단체의 날짜를 원문에 대 본다
        # (life.gate_dates). 없으면 재지 않는다.
        return 200, life_mod.refine(body, text=_life_story(body))

    if path != "/api/life/analyze":
        return 404, {"error": "unknown endpoint", "path": path}

    if not isinstance(body, dict):
        return 400, {"error": "JSON 이 아닙니다"}
    text = str(body.get("text") or "").strip()
    # 길이 문턱은 없다 — 화면의 '입력' 도 글이 있으면 누를 수 있다 (2026-09-08).
    if not text:
        return 400, {"error": "이야기가 비어 있습니다."}
    # 화면이 이미 쥔 그래프를 같이 보내면 거기에 더한다 (life.merge).
    base = body.get("base")
    if not (isinstance(base, dict) and isinstance(base.get("nodes"), list) and base["nodes"]):
        base = None
    name = str(body.get("name") or "나")
    kind = str(body.get("backend") or "")

    if blocking:
        from .backends import default_life_backend
        state = run_analysis(api, text, name, kind or default_life_backend(),
                             base, save=save)
        return (200 if state.get("state") == "done" else 500), state

    if not LIFE_JOBS.start(api, text, name, kind, base=base):
        return 409, {"error": "이미 분석 중입니다."}
    return 202, LIFE_JOBS.status()


def safe_static_path(url_path: str, root: Path = WEB_ROOT) -> Path | None:
    """정적 파일 경로. 루트 밖을 가리키면 None.

    로컬 전용 서버라도 `/../.env` 를 그대로 읽어주는 서버를 남겨둘 이유는
    없다. 이 저장소에는 실제로 인증키가 든 .env 가 옆에 있다."""
    rel = unquote(url_path).lstrip("/") or "index.html"
    root = root.resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        return None
    return target if target.is_file() else None


def dispatch(
    api: GraphAPI, path: str, q: dict[str, list[str]]
) -> tuple[int, object]:
    """엔드포인트 하나를 골라 (상태코드, 응답) 을 돌려준다.

    HTTP 껍데기에서 떼어 둔 이유는 **이 표를 두 벌 두지 않기 위해서다.**
    로컬은 `histgraph serve` 의 Handler 가, 배포는 서버리스 함수(api/index.py)
    가 부른다. 분기가 양쪽에 흩어지면 한쪽에만 엔드포인트가 생기고, 그 차이는
    배포한 다음에야 404 로 드러난다."""
    one = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731

    if path == "/api/meta":
        return 200, api.meta()
    if path == "/api/seeds":
        return 200, api.seeds(int(one("limit", "12")))
    if path == "/api/search":
        return 200, api.search(one("q"), int(one("limit", "25")))
    if path == "/api/graph":
        exclude = tuple(t for t in one("exclude", "").split(",") if t)
        return 200, api.graph(
            one("id"),
            depth=max(1, min(int(one("depth", "1")), 3)),
            limit=int(one("limit", str(DEFAULT_LIMIT))),
            exclude=exclude,
        )
    # 인과 사슬. 한 노드의 원인·결과 나무, 또는 두 노드 사이의 최단 경로.
    if path == "/api/chain":
        from .causes import chain
        node_id = (q.get("id") or [""])[0]
        depth = max(1, min(int((q.get("depth") or ["4"])[0]), 6))
        got = chain(api.store, node_id, depth=depth)
        if got is None:
            return 404, {"error": "not found", "id": node_id}
        for n in got["nodes"].values():
            n["group"] = TYPE_GROUP.get(n["type"], "thing")
        return 200, got
    if path == "/api/path":
        from .causes import paths
        src = (q.get("from") or [""])[0]
        dst = (q.get("to") or [""])[0]
        if not src or not dst:
            return 400, {"error": "from 과 to 가 필요합니다"}
        got = paths(api.store, src, dst)
        for n in got["nodes"].values():
            n["group"] = TYPE_GROUP.get(n["type"], "thing")
        return 200, got
    if path == "/api/timeline":
        tl = api.timeline(one("id"))
        return (200, tl) if tl else (404, {"error": "not found"})
    # 개인 역사 (web/life.html). 그 구간의 재위 띠·큰 사건. 저장된 개인 그래프를
    # 서버가 골라 주던 `/api/life` 는 뺐다 (2026-09-08) — 기본으로 서는 자료는
    # 없고, 사람이 로그인해 직접 적는다.
    # 분석이 도는 중인지. 배포에서는 늘 'idle' 이다 — 거기서는 답이 POST 하나에
    # 실려 오므로 물어볼 것이 없다 (`blocking` 이 참으로 온다).
    if path == "/api/life/job":
        return 200, LIFE_JOBS.status()
    # 이 컴퓨터에 남은 이야기 원문. 화면의 '내가 적은 이야기' 상자가 **옛
    # 그래프를 위해** 한 번 묻는다 (2026-09-08 사용자: "누르면 사용자가 입력한
    # 사용자의 역사 히스토리를 보여줘. 그래서 잘못된 입력을 고칠 수 있게 해줘").
    # 앞으로 적는 것은 문서가 `stories` 로 들고 다니므로 여기를 안 지난다.
    # 배포에는 이 파일이 없다 — 빈 글이 온다.
    if path == "/api/life/story":
        return 200, {"text": _life_story({"subject": {"name": one("name", "나")}}) or ""}
    if path == "/api/context":
        return 200, api.context(int(one("from", "0")), int(one("to", "0")))
    if path.startswith("/api/node/"):
        node = api.node(unquote(path[len("/api/node/"):]))
        return (200, node) if node else (404, {"error": "not found"})
    return 404, {"error": "unknown endpoint"}


class Handler(BaseHTTPRequestHandler):
    api: GraphAPI  # 서브클래스가 채운다
    server_version = "histgraph"

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        target = safe_static_path(path)
        if target is None:
            self._json({"error": "not found", "path": path}, 404)
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _page(self, status: int, ctype: str, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # --- 가입·계정 ------------------------------------------------------
    # 표는 auth.ROUTES 하나다. 여기서는 껍데기만 씌운다 — 배포(api/index.py)
    # 도 같은 표를 읽으므로 한쪽에만 생기는 엔드포인트가 없다.

    def _read_body(self, limit: int = auth.MAX_BODY) -> bytes:
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0:
            return b""
        if size > limit:
            return b""      # 큰 것은 읽지 않는다. auth 가 400 으로 답한다.
        return self.rfile.read(size)

    def _try_auth(self, body: bytes = b"") -> bool:
        """가입·계정의 길이면 여기서 답하고 True. 아니면 False.

        본문은 **부르는 쪽이 한 번만 읽어** 넘긴다 — 여기서 읽으면
        가입 경로가 아닐 때(`/api/life/analyze`) 그쪽이 빈 몸을 받는다."""
        url = urlparse(self.path)
        req = auth.Request(self.command, url.path, parse_qs(url.query),
                           dict(self.headers.items()), body)
        resp = auth.route(req)
        if resp is None:
            return False
        self.send_response(resp.status)
        for name, value in resp.headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        self.wfile.write(resp.body)
        return True

    def do_PUT(self) -> None:  # noqa: N802
        if not self._try_auth(self._read_body()):
            self._json({"error": "unknown endpoint", "path": self.path}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._try_auth(self._read_body()):
            self._json({"error": "unknown endpoint", "path": self.path}, 404)

    def do_POST(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 규약)
        """이야기를 받아 개인 역사 분석을 띄운다.

        답을 기다리지 않는다 — 로컬 모델은 몇 분을 돌아 브라우저가 먼저 끊는다.
        띄웠다는 것만 알리고 화면이 `/api/life/job` 으로 물어본다 (LifeAnalysis).
        몸통은 배포와 같은 `life_post` 다."""
        path = urlparse(self.path).path
        raw = self._read_body(LIFE_MAX_BODY if path in LIFE_POSTS else auth.MAX_BODY)
        if self._try_auth(raw):
            return
        if path not in LIFE_POSTS:
            self._json({"error": "unknown endpoint", "path": path}, 404)
            return
        status, payload = life_post(self.api, path, raw)
        self._json(payload, status)

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 규약)
        url = urlparse(self.path)
        try:
            if self._try_auth():
                return
            # 글로 읽는 장(`/n/<id>`·`/sitemap.xml`)이 먼저다. 정적 파일보다
            # 앞에 둬야 web/public 에 같은 이름이 생겨도 이쪽이 이긴다.
            page = pages.route(self.api, url.path)
            if page is not None:
                self._page(*page)
            elif url.path.startswith("/api/"):
                status, payload = dispatch(self.api, url.path, parse_qs(url.query))
                self._json(payload, status)
            else:
                self._static(url.path)
        except (ValueError, KeyError) as err:
            self._json({"error": f"{type(err).__name__}: {err}"}, 400)
        except BrokenPipeError:
            pass  # 브라우저가 탭을 닫았다 — 서버가 죽을 일은 아니다


def serve(db: Path, host: str = "127.0.0.1", port: int = 8100, era: str = "") -> None:
    api = GraphAPI(db, era=era)
    handler = type("BoundHandler", (Handler,), {"api": api})

    httpd = ThreadingHTTPServer((host, port), handler)
    stats = api.store.stats()
    print(f"  그래프: {db}  (노드 {stats['nodes_total']:,} · 엣지 {stats['edges_total']:,})")
    warn_if_unbuilt()
    print(f"  http://{host}:{port}  — Ctrl+C 로 종료", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  종료")
    finally:
        httpd.server_close()
