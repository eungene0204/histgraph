"""SQLite 그래프 저장소.

멱등(idempotent) 저장이 목표 — 같은 수집을 여러 번 돌려도 중복이 쌓이지
않아야 파이프라인을 반복 실행할 수 있다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .ontology import Edge, Node

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    label       TEXT NOT NULL,
    source      TEXT NOT NULL,
    start_date  TEXT,
    end_date    TEXT,
    lat         REAL,
    lon         REAL,
    description TEXT,
    url         TEXT,
    props       TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nodes_type   ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_label  ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source);

CREATE TABLE IF NOT EXISTS aliases (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    PRIMARY KEY (node_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);

-- src/dst/type/source 조합이 엣지의 자연키. 같은 사실을 다른 소스가
-- 말하면 별도 행으로 남겨 교차검증에 쓴다.
CREATE TABLE IF NOT EXISTS edges (
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    type       TEXT NOT NULL,
    source     TEXT NOT NULL,
    label      TEXT,
    start_date TEXT,
    end_date   TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    props      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src, dst, type, source)
);
CREATE INDEX IF NOT EXISTS idx_edges_src  ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst  ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);

-- 서로 다른 소스의 같은 실체를 잇는 링크 (엔티티 해소 결과)
CREATE TABLE IF NOT EXISTS same_as (
    a      TEXT NOT NULL,
    b      TEXT NOT NULL,
    method TEXT NOT NULL,
    score  REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source   TEXT NOT NULL,
    nodes    INTEGER NOT NULL,
    edges    INTEGER NOT NULL,
    ran_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class GraphStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # 이 프로젝트는 몇 시간짜리 추출과 수집을 나란히 돌린다. 기본값
        # (busy_timeout=0)이면 다른 쪽이 쓰는 순간 곧바로 'database is
        # locked' 로 죽어서 진행 중이던 작업을 잃는다. 기다리게 한다.
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.commit()
        self.close()

    # --- 쓰기 ---------------------------------------------------------
    def upsert_nodes(self, nodes: Iterable[Node]) -> int:
        rows, alias_rows = [], []
        for n in nodes:
            rows.append(
                (
                    n.id, n.type, n.label, n.source, n.start_date, n.end_date,
                    n.lat, n.lon, n.description, n.url,
                    json.dumps(n.props, ensure_ascii=False),
                )
            )
            alias_rows.extend((n.id, a) for a in n.aliases if a and a != n.label)

        self.conn.executemany(
            """INSERT INTO nodes
                 (id, type, label, source, start_date, end_date, lat, lon,
                  description, url, props)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 label       = excluded.label,
                 start_date  = COALESCE(excluded.start_date, nodes.start_date),
                 end_date    = COALESCE(excluded.end_date, nodes.end_date),
                 lat         = COALESCE(excluded.lat, nodes.lat),
                 lon         = COALESCE(excluded.lon, nodes.lon),
                 description = COALESCE(excluded.description, nodes.description),
                 url         = COALESCE(excluded.url, nodes.url),
                 props       = excluded.props,
                 updated_at  = datetime('now')""",
            rows,
        )
        if alias_rows:
            self.conn.executemany(
                "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)", alias_rows
            )
        self.conn.commit()
        return len(rows)

    def upsert_edges(self, edges: Iterable[Edge]) -> int:
        rows = [
            (
                e.src, e.dst, e.type, e.source, e.label, e.start_date,
                e.end_date, e.confidence, json.dumps(e.props, ensure_ascii=False),
            )
            for e in edges
        ]
        self.conn.executemany(
            """INSERT INTO edges
                 (src, dst, type, source, label, start_date, end_date, confidence, props)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(src, dst, type, source) DO UPDATE SET
                 label      = excluded.label,
                 confidence = excluded.confidence,
                 props      = excluded.props""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def log_ingest(self, source: str, nodes: int, edges: int) -> None:
        self.conn.execute(
            "INSERT INTO ingest_log (source, nodes, edges) VALUES (?,?,?)",
            (source, nodes, edges),
        )
        self.conn.commit()

    # --- 읽기 ---------------------------------------------------------
    def stats(self) -> dict[str, object]:
        c = self.conn
        return {
            "nodes_total": c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges_total": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "by_node_type": {
                r["type"]: r["n"]
                for r in c.execute(
                    "SELECT type, COUNT(*) n FROM nodes GROUP BY type ORDER BY n DESC"
                )
            },
            "by_edge_type": {
                r["type"]: r["n"]
                for r in c.execute(
                    "SELECT type, COUNT(*) n FROM edges GROUP BY type ORDER BY n DESC"
                )
            },
            "by_source": {
                r["source"]: r["n"]
                for r in c.execute(
                    "SELECT source, COUNT(*) n FROM nodes GROUP BY source ORDER BY n DESC"
                )
            },
            # 아직 수집되지 않은 노드를 가리키는 엣지 — 다음 수집 대상 큐이자
            # 데이터 완결성 지표
            "dangling_edges": c.execute(
                """SELECT COUNT(*) FROM edges e
                   WHERE NOT EXISTS (SELECT 1 FROM nodes WHERE id = e.src)
                      OR NOT EXISTS (SELECT 1 FROM nodes WHERE id = e.dst)"""
            ).fetchone()[0],
        }

    # SQLite 의 변수 개수 상한(구버전 999)에 걸리지 않게 IN 절을 나눈다.
    # 조선·대한민국 같은 허브 노드는 depth=2 에서 이웃이 수천 개가 된다.
    _CHUNK = 500

    def _query_chunked(self, sql: str, ids: set[str], per_row_repeat: int = 1) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        ordered = sorted(ids)
        for i in range(0, len(ordered), self._CHUNK):
            batch = ordered[i : i + self._CHUNK]
            marks = ",".join("?" * len(batch))
            rows.extend(
                self.conn.execute(
                    sql.format(marks=marks), tuple(batch) * per_row_repeat
                ).fetchall()
            )
        return rows

    def degrees(self, ids: set[str]) -> dict[str, int]:
        """노드별 연결 차수. 화면에 무엇을 크게 그릴지, 무엇을 먼저
        보여줄지를 정하는 기준."""
        rows = self._query_chunked(
            """SELECT n.id AS id, COUNT(e.src) AS d
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                WHERE n.id IN ({marks})
             GROUP BY n.id""",
            ids,
        )
        return {r["id"]: r["d"] for r in rows}

    def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        max_nodes: int = 3000,
        follow_same_as: bool = True,
        exclude_types: tuple[str, ...] = (),
    ) -> dict[str, list[dict]]:
        """노드 주변 서브그래프 — 프론트엔드가 실제로 그릴 단위.

        max_nodes 로 상한을 두지 않으면 허브 노드에서 그래프 절반이 딸려와
        화면에 그릴 수 없는 결과가 나온다.

        **상한에 걸리면 차수가 높은 이웃부터 남긴다.** id 순으로 자르면
        'wd:Q1…' 이 먼저 살아남을 뿐이라 무엇이 남는지가 우연에 맡겨진다.

        `exclude_types` 는 아예 따라가지 않을 타입. 연도(`period`) 노드는
        거의 모든 노드에 붙어 있어서, 그냥 두면 상한을 연도가 다 먹고
        정작 보고 싶은 인물·사건이 화면에서 밀려난다.

        follow_same_as 가 켜져 있으면 엔티티 해소 링크를 건너 다른 소스로
        넘어간다 — 이게 없으면 국가유산청 유물에서 Wikidata 인물로 가는
        경로가 존재하지 않는다."""
        seen = {node_id}
        frontier = {node_id}
        collected: list[sqlite3.Row] = []
        aliases: list[sqlite3.Row] = []
        truncated = False

        blocked: set[str] = set()
        if exclude_types:
            marks = ",".join("?" * len(exclude_types))
            blocked = {
                r["id"]
                for r in self.conn.execute(
                    f"SELECT id FROM nodes WHERE type IN ({marks})", exclude_types
                )
            } - {node_id}  # 중심 노드는 스스로 제외되지 않는다

        for _ in range(depth):
            if not frontier:
                break
            rows = self._query_chunked(
                "SELECT * FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
                frontier,
                per_row_repeat=2,
            )
            collected.extend(rows)
            nxt = ({r["src"] for r in rows} | {r["dst"] for r in rows}) - seen - blocked

            # same_as 를 따라가지 않으면 엔티티 해소가 테이블에만 존재하고
            # 실제 탐색에서는 두 소스가 여전히 끊겨 있다. 동일 실체는
            # 한 노드처럼 취급해 프론티어를 확장한다.
            if follow_same_as:
                alias_rows = self._query_chunked(
                    "SELECT a, b, method, score FROM same_as "
                    "WHERE a IN ({marks}) OR b IN ({marks})",
                    frontier,
                    per_row_repeat=2,
                )
                nxt |= (
                    ({r["a"] for r in alias_rows} | {r["b"] for r in alias_rows})
                    - seen
                    - blocked
                )
                aliases.extend(alias_rows)
            if len(seen) + len(nxt) > max_nodes:
                rank = self.degrees(nxt)
                ordered = sorted(nxt, key=lambda i: (-rank.get(i, 0), i))
                nxt = set(ordered[: max(max_nodes - len(seen), 0)])
                truncated = True
            frontier = nxt
            seen |= nxt
            if truncated:
                break

        nodes = self._query_chunked("SELECT * FROM nodes WHERE id IN ({marks})", seen)

        # **유도 부분그래프(induced subgraph)를 돌려준다.** 탐색 중에 모은
        # 엣지는 프론티어에 닿는 것뿐이라, 그것만 쓰면 이웃끼리의 관계가
        # 통째로 빠진다 — 중심에서 바큇살만 뻗은 그림이 되고 "인조반정과
        # 병자호란이 이어져 있다" 같은 것이 보이지 않는다 (실측: 조선의
        # 이웃 105개 사이에 25건이 있었다).
        collected.extend(
            r
            for r in self._query_chunked("SELECT * FROM edges WHERE src IN ({marks})", seen)
            if r["dst"] in seen
        )
        # **자연키(출처 포함)로 중복을 없앤다.** 출처를 뺀 키로 합치면
        # 같은 사실을 말한 두 소스 중 하나가 조용히 사라져, 화면이 어느
        # 소스가 확인해 줬는지 알 수 없게 된다. 교차검증은 이 그래프의
        # 신뢰도 근거라서 표현 계층까지 그대로 올려보낸다. 한 줄로 합칠지는
        # 화면이 정할 일이다.
        edges = {
            (r["src"], r["dst"], r["type"], r["source"]): r
            for r in collected
            # 자기순환은 그래프에서 의미가 없고 화면에도 그릴 수 없다
            if r["src"] in seen and r["dst"] in seen and r["src"] != r["dst"]
        }
        # same_as 는 별도로 돌려준다 — 사실 관계를 나타내는 엣지가 아니라
        # "이 둘은 같은 실체"라는 메타 정보라서 시각화도 다르게 해야 한다.
        aliases.extend(
            r
            for r in self._query_chunked("SELECT a, b, method, score FROM same_as WHERE a IN ({marks})", seen)
            if r["b"] in seen
        )
        links = {
            (r["a"], r["b"]): r
            for r in aliases
            if r["a"] in seen and r["b"] in seen and r["a"] != r["b"]
        }
        return {
            "nodes": [dict(r) for r in nodes],
            "edges": [dict(r) for r in edges.values()],
            "same_as": [dict(r) for r in links.values()],
            "truncated": truncated,
        }
