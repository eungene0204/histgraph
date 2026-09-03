"""그래프 탐색 서버 — 프론트엔드가 실제로 붙는 곳.

**의존성 없이 표준 라이브러리로만 만든다.** 수집 파이프라인이 그렇듯이
`python3 -m histgraph serve` 한 줄로 뜨는 게 이 프로젝트의 조건이다.

**전부 그리지 않는다.** 조선 그래프만 해도 노드 5,637 · 엣지 9,629 다.
한 화면에 다 뿌리면 털뭉치가 되고 브라우저도 버틴다고 그릴 뿐 읽히지
않는다. 그래서 서버는 언제나 **한 노드 주변**만 돌려준다 — 검색으로
들어가서 이웃을 펼쳐 나가는 것이 이 그래프를 읽는 방법이다.

기본값으로 연도(`period`)를 빼는 이유도 같다. 연도 노드는 거의 모든
노드에 붙어 있어서, 그냥 두면 화면 예산을 연도가 다 먹는다.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .ontology import EDGE_TYPES, NODE_TYPES
from .store import GraphStore

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"

# 화면이 견디는 노드 수. 이보다 많으면 힘기반 배치가 수렴하기 전에
# 사람이 먼저 포기한다.
DEFAULT_LIMIT = 120
MAX_LIMIT = 400

# 기본으로 따라가지 않을 타입 (프론트에서 켤 수 있다)
DEFAULT_EXCLUDE = ("period",)

# 노드 타입을 색 3개로 묶는다. 9색을 한 화면에 쓰면 색약 사용자는
# 물론이고 정상 시야에서도 구분이 안 된다(검증기 실측: 8색 전체 조합에서
# 최악 쌍 ΔE 1.6). 색은 큰 갈래만 말하고, 세부 타입은 **모양**이 말한다.
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
}

# 관계를 볼 때 사람이 먼저 궁금해하는 순서. 상세 패널의 정렬 기준이다.
RELATION_ORDER = [
    "participated_in", "held_position", "member_of", "created",
    "child_of", "spouse_of", "born_in", "died_in",
    "occurred_at", "located_in", "depicts", "part_of",
    "from_period", "occurred_during", "dated_to", "related_to",
]


def _year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^(-?)(\d{1,4})", value.strip())
    return int(m.group(2)) * (-1 if m.group(1) else 1) if m else None


def _node_brief(row, degree: int = 0) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
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

    def __init__(self, db: Path | str | GraphStore, era: str = "") -> None:
        self._shared = db if isinstance(db, GraphStore) else None
        self._db = db.path if isinstance(db, GraphStore) else Path(db)
        self._local = threading.local()
        self.era = era

    @property
    def store(self) -> GraphStore:
        if self._shared is not None:
            return self._shared
        store = getattr(self._local, "store", None)
        if store is None:
            store = GraphStore(self._db)
            self._local.store = store
        return store

    # --- 메타 ---------------------------------------------------------
    def root(self) -> str | None:
        """이 그래프의 중심. 조선 그래프의 중심은 조선이다.

        차수 1위 노드로 대신하지 않는다 — 그건 그때그때 병자호란이었다가
        선조였다가 하는 우연이고, 화면을 열었을 때 '무엇의 그래프인가'를
        말해주지 못한다. 왕조 노드가 실제로 있을 때만 쓴다."""
        from .scope import ERAS

        era = ERAS.get(self.era)
        if era is None:
            return None
        node_id = f"wd:{era.polity_qid}"
        found = self.store.conn.execute(
            "SELECT 1 FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return node_id if found else None

    def meta(self) -> dict:
        stats = self.store.stats()
        return {
            "era": self.era,
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
                "SELECT id, type, label, start_date, end_date FROM nodes WHERE id = ?",
                (root,),
            ).fetchone()
            if row:
                out.append(_node_brief(row, self.store.degrees({root}).get(root, 0)))
                limit -= 1

        for node_type, take in (("person", limit - limit // 3), ("event", limit // 3)):
            rows = self.store.conn.execute(
                """SELECT n.id, n.type, n.label, n.start_date, n.end_date,
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
        rows = self.store.conn.execute(
            """SELECT n.id, n.type, n.label, n.start_date, n.end_date,
                      COUNT(e.src) AS d,
                      MIN(CASE WHEN n.label = ?1 THEN 0
                               WHEN n.label LIKE ?1 || '%' THEN 1
                               ELSE 2 END) AS rank
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                WHERE n.label LIKE ?2
                   OR n.id IN (SELECT node_id FROM aliases WHERE alias LIKE ?2)
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
        aliases = [
            r["alias"]
            for r in self.store.conn.execute(
                "SELECT alias FROM aliases WHERE node_id = ? ORDER BY alias", (node_id,)
            )
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
                }
            fact["confidence"] = max(fact["confidence"], r["confidence"])
            if not fact["edge_label"] and r["edge_label"]:
                fact["edge_label"] = r["edge_label"]
            if r["source"] not in fact["sources"]:
                fact["sources"].append(r["source"])
            if edge_props.get("evidence"):
                fact["evidence"].append(edge_props["evidence"])
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
            "type": row["type"],
            "group": TYPE_GROUP.get(row["type"], "thing"),
            "type_label": NODE_TYPES.get(row["type"], row["type"]),
            "source": row["source"],
            "start": row["start_date"],
            "end": row["end_date"],
            "description": row["description"],
            "url": row["url"],
            "kowiki_url": props.get("kowiki_url"),
            "merged_from": props.get("merged_from") or [],
            "aliases": aliases,
            "relations": relations,
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

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 규약)
        url = urlparse(self.path)
        q = parse_qs(url.query)
        one = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731

        try:
            if url.path == "/api/meta":
                self._json(self.api.meta())
            elif url.path == "/api/seeds":
                self._json(self.api.seeds(int(one("limit", "12"))))
            elif url.path == "/api/search":
                self._json(self.api.search(one("q"), int(one("limit", "25"))))
            elif url.path == "/api/graph":
                exclude = tuple(t for t in one("exclude", "").split(",") if t)
                self._json(self.api.graph(
                    one("id"),
                    depth=max(1, min(int(one("depth", "1")), 3)),
                    limit=int(one("limit", str(DEFAULT_LIMIT))),
                    exclude=exclude,
                ))
            elif url.path.startswith("/api/node/"):
                node = self.api.node(unquote(url.path[len("/api/node/"):]))
                self._json(node or {"error": "not found"}, 200 if node else 404)
            elif url.path.startswith("/api/"):
                self._json({"error": "unknown endpoint"}, 404)
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
    print(f"  http://{host}:{port}  — Ctrl+C 로 종료", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  종료")
    finally:
        httpd.server_close()
