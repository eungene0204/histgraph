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
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import pages
from .ontology import EDGE_TYPES, NODE_TYPES
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

# --- 연표 --------------------------------------------------------------
# 뼈대로 쓸 사건을 고르는 풀. 차수 상위부터 훑되 여기서 끊는다 — 아래로
# 내려가면 연결이 두어 개뿐인 사건이라 "그 무렵의 큰일"이 되지 못한다.
# (조선 그래프의 연도 있는 사건은 73개라 사실상 전부 들어온다.)
ANCHOR_POOL = 400
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
RELATION_ORDER = [
    "caused", "participated_in", "held_position", "member_of", "created",
    "child_of", "spouse_of", "born_in", "died_in",
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
        "group": TYPE_GROUP.get(row["type"], "thing"),
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

    # --- 메타 ---------------------------------------------------------
    def root(self) -> str | None:
        """이 그래프의 중심. 조선 그래프의 중심은 조선이다.

        차수 1위 노드로 대신하지 않는다 — 그건 그때그때 병자호란이었다가
        선조였다가 하는 우연이고, 화면을 열었을 때 '무엇의 그래프인가'를
        말해주지 못한다. 왕조 노드가 실제로 있을 때만 쓴다.

        시대를 묶어 담은 그래프(조선~일제강점기)에서는 **맨 앞 시대**가
        중심이다. 들어가는 문이 하나여야 하고, 둘을 나란히 놓으면 화면이
        먼저 '어느 쪽이냐'를 묻게 된다."""
        from .scope import ERAS, eras_of

        for key in eras_of(self.era):
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

        나머지는 차수 상위순 — 많이 연결된 개체라야 펼쳤을 때 볼 게 있다.
        인물만 주면 사건 쪽으로 들어가는 길이 안 보이므로 섞는다."""
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

        for node_type, take in (("person", limit - limit // 3), ("event", limit // 3)):
            rows = self.store.conn.execute(
                """SELECT n.id, n.type, n.label, n.start_date, n.end_date, n.props,
                          COUNT(e.src) AS d
                     FROM nodes n
                     LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                    WHERE n.type = ? AND n.description IS NOT NULL
                 GROUP BY n.id
                 ORDER BY d DESC
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
        # **차수가 첫 기준이다.** 문자열 일치도를 앞에 두면 '세종'을 쳤을 때
        # 세종특별자치시와 '세종 비암사 극락보전'이 먼저 나오고 정작 조선
        # 세종(차수 21)은 네 번째로 밀린다 — 실측으로 확인한 순서다.
        # 연도 노드는 검색 대상이 되는 일이 드물어 뒤로 보낸다.
        #
        # **연표 눈금(`source='timeline'`)은 아예 뺀다.** '1974'를 치면
        # `time:1974`('1974년')가 첫 줄이었고, 엔터가 그걸 열어 연표 1974년
        # 자리에 '1974년'이라는 노드가 앉았다. 눈금은 날짜 없는 사건을
        # 해에 걸어 두는 뼈대지 사람이 찾을 개체가 아니다 — 그 해를
        # 찾는 사람에게는 그 해의 사건이 나와야 한다.
        rows = self.store.conn.execute(
            """SELECT n.id, n.type, n.label, n.start_date, n.end_date, n.props,
                      COUNT(e.src) AS d,
                      MIN(CASE WHEN n.label = ?1 THEN 0
                               WHEN n.label LIKE ?1 || '%' THEN 1
                               ELSE 2 END) AS rank
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                WHERE (n.label LIKE ?2
                       OR n.id IN (SELECT node_id FROM aliases WHERE alias LIKE ?2))
                  AND n.source != 'timeline'
             GROUP BY n.id
             ORDER BY (n.type = 'period'), d DESC, rank, n.label
                LIMIT ?3""",
            (query, like, limit),
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
                merged[key] = {
                    "s": e["src"], "t": e["dst"], "type": e["type"],
                    "label": EDGE_TYPES[e["type"]][0],
                    "conf": e["confidence"], "sources": [e["source"]],
                }
            else:
                # 가장 믿을 만한 소스가 선을 대표한다
                row["conf"] = max(row["conf"], e["confidence"])
                if e["source"] not in row["sources"]:
                    row["sources"].append(e["source"])
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
        # 또 하나의 이름은 제목 줄에 세운다. '다른 이름' 더미에 같이 두면
        # 표기 변형과 구별되지 않아 별명처럼 읽힌다 (`co_names` 참고).
        names = _names(row)
        aliases = [
            r["alias"]
            for r in self.store.conn.execute(
                "SELECT alias FROM aliases WHERE node_id = ? ORDER BY alias", (node_id,)
            )
            if r["alias"] not in names
        ]
        rows = self.store.conn.execute(
            """SELECT e.src, e.dst, e.type, e.source, e.confidence, e.props,
                      e.label AS edge_label,
                      n.id AS other_id, n.label AS other_label, n.type AS other_type
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
                    "other": {
                        "id": r["other_id"],
                        "label": r["other_label"],
                        "type": r["other_type"],
                        "group": TYPE_GROUP.get(r["other_type"], "thing"),
                    },
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
                }
            fact["confidence"] = max(fact["confidence"], r["confidence"])
            if not fact["how"] and edge_props.get("how"):
                fact["how"] = edge_props["how"]
            if not fact["edge_label"] and r["edge_label"]:
                fact["edge_label"] = r["edge_label"]
            if r["source"] not in fact["sources"]:
                fact["sources"].append(r["source"])
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
        relations.sort(
            key=lambda x: (
                order.get(x["type"], 99),
                -len(x["sources"]),
                -x["confidence"],
                0 if x["evidence"] else 1,
                x["other"]["label"],
            )
        )

        return {
            "id": row["id"],
            "label": row["label"],
            "names": names,
            "type": row["type"],
            "group": TYPE_GROUP.get(row["type"], "thing"),
            "type_label": NODE_TYPES.get(row["type"], row["type"]),
            "source": row["source"],
            "start": row["start_date"],
            "end": row["end_date"],
            "description": row["description"],
            # 설명이 어디서 왔는지. 'kowiki' 는 위키백과 산문, 'wd:ko' 는
            # Wikidata 한국어 한 줄, '사전' 은 영어 한 줄을 koreanize 로
            # 옮긴 것이다. **화면은 이것을 그리지 않는다** — 자료 출처는
            # 읽는 사람이 묻지 않은 것이다. 도구가 쓰라고 남겨 둔다.
            "desc_source": props.get("desc_source"),
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

    def _anchors(self) -> list[dict]:
        """시대의 뼈대 — 그 무렵의 큰일. 연표 전체에 고르게 깔린다.

        **차수 상위 사건에서 고른다.** '언제쯤 일인가'를 사람은 절대
        연도가 아니라 아는 사건과의 앞뒤로 읽는다 ("임진왜란 뒤, 병자호란
        전"). 많이 연결된 사건이 곧 그 자리를 맡을 수 있는 사건이다.

        연도를 못 찾은 사건은 뺀다 — 연표에 놓을 자리가 없다.
        (조선 그래프 실측: 사건 297개 중 연도가 잡히는 것은 76개다.)

        **솎지 않는다.** 연대를 아는 사건은 다 세운다 — 연표에서 빠진
        사건은 그 시대에 없었던 일이 된다. 몰린 곳(1592년 한 해에 38건)은
        화면이 그 해를 늘려 세우므로, 라벨이 제 해를 떠나지 않는다."""
        cached = getattr(self._local, "anchors", None)
        if cached is not None:
            return cached
        rows = self.store.conn.execute(
            """SELECT n.id, n.type, n.label, n.start_date, n.end_date,
                      COUNT(e.src) AS d
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                WHERE n.type = 'event'
             GROUP BY n.id
             ORDER BY d DESC
                LIMIT ?""",
            (ANCHOR_POOL,),
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
            # 않으므로 많이 연결된 쪽만 남긴다 (rows 가 차수 내림차순).
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
        for r in rows:
            start = _year(r["r_start"])
            if start is None:
                continue
            # 재위 끝이 비어 있으면(재위 중 죽은 임금 일부) 몰년으로 닫는다.
            # 그것도 없고 살아 있으면 재임 중이다. 죽었는데 몰년도 없으면
            # 한 점으로 둔다 — 모르는 끝을 오늘로 늘리지 않는다.
            death = _year(r["end_date"])
            end = _year(r["r_end"])
            ongoing = False
            if end is None:
                if death is not None:
                    end = death if death >= start else start
                elif r["end_date"]:
                    end = start
                else:
                    end = max(this_year, start)
                    ongoing = True
            out.append({
                "id": r["id"], "label": r["label"],
                "position": r["position"],
                "kind": "president" if r["seat"] == "president" else "monarch",
                "start": start, "end": end,
                "ongoing": ongoing,
                # 몰년이 재위 끝보다 앞서면 둘 중 하나가 틀린 것이다.
                # 화면이 거꾸로 된 꼬리를 그리지 않게 여기서 뗀다.
                "death": death if death is not None and death >= end else None,
                "birth": _year(r["start_date"]),
            })
        self._local.reigns = out
        return out

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
        marks: list[dict] = []
        if start is not None:
            marks.append({
                "id": row["id"], "label": row["label"], "type": row["type"],
                "group": TYPE_GROUP.get(row["type"], "thing"),
                "year": start, "end": end, "kind": "self",
                "date": row["start_date"] or "",
            })

        # --- 연도를 아는 직접 이웃 -------------------------------------
        # 날짜가 있거나 시대 노드에 붙어 있는 이웃만 가져온다. 조선처럼
        # 이웃이 수천인 허브에서 전부 끌어오면 연표 한 번에 그래프 절반을
        # 읽게 된다.
        kinds = ",".join(f"'{t}'" for t in POINT_TYPES)   # 코드 안의 고정 목록이다
        rows = self.store.conn.execute(
            f"""SELECT e.type AS rel, CASE WHEN e.src = ?1 THEN 'out' ELSE 'in' END AS dir,
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
            picked[r["id"]] = {"row": r, "rel": r["rel"], "dir": r["dir"]}

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
                "rel": {"type": v["rel"], "dir": v["dir"],
                        "label": EDGE_TYPES[v["rel"]][0]},
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
        # **왕조 자신도 세운다.** 조선의 존속 기간은 1392-08-13~1897-10-12
        # 인데 org 라서 사건 뼈대에 못 들어왔고, 1392년 자리가 비어 있었다 —
        # 연표를 훑으면 위화도 회군(1388) 다음이 곧장 제1차 왕자의
        # 난(1398)이다. 그래프에 '조선 건국' 이라는 사건 노드가 있지만
        # 날짜가 없고 엣지 둘뿐인 추출 고아라, 거기에 왕조의 P571 을
        # 옮겨 적는 것은 추측이 된다. 왕조 노드가 자기 날짜로 서면 된다.
        root = self.root()
        if root and root not in {m["id"] for m in marks}:
            row_root = self.store.conn.execute(
                "SELECT id, type, label, start_date, end_date FROM nodes WHERE id = ?",
                (root,),
            ).fetchone()
            if row_root is not None:
                r_start, r_end = _span(row_root)
                if r_start is not None:
                    marks.append({
                        "id": row_root["id"], "label": row_root["label"],
                        "type": row_root["type"],
                        "group": TYPE_GROUP.get(row_root["type"], "thing"),
                        "year": r_start, "end": r_end, "kind": "era",
                        "date": row_root["start_date"] or "",
                    })

        marks.sort(key=lambda m: (m["year"], m["label"]))

        # 자리를 무엇에 기대어 잡았는지. 화면이 단정할 수 있는 범위가
        # 여기서 갈린다.
        basis = "self" if start is not None else "near" if near else "era"

        # --- 축 ---------------------------------------------------------
        # **왕의 띠도 축 안에 들어와야 한다.** 축을 사건만으로 잡으면
        # 고종이 1919년에 죽은 것이 축 밖으로 밀려 띠가 잘린다.
        reigns = self._reigns()
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
            "group": TYPE_GROUP.get(row["type"], "thing"),
            "type_label": NODE_TYPES.get(row["type"], row["type"]),
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
            # 왕의 재위 띠. 고른 노드와 무관하게 늘 같은 자를 세운다.
            "reigns": reigns,
        }


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

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 규약)
        url = urlparse(self.path)
        try:
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
