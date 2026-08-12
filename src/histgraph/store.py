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

    def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        max_nodes: int = 3000,
        follow_same_as: bool = True,
    ) -> dict[str, list[dict]]:
        """노드 주변 서브그래프 — 프론트엔드가 실제로 그릴 단위.

        max_nodes 로 상한을 두지 않으면 허브 노드에서 그래프 절반이 딸려와
        화면에 그릴 수 없는 결과가 나온다.

        follow_same_as 가 켜져 있으면 엔티티 해소 링크를 건너 다른 소스로
        넘어간다 — 이게 없으면 국가유산청 유물에서 Wikidata 인물로 가는
        경로가 존재하지 않는다."""
        seen = {node_id}
        frontier = {node_id}
        collected: list[sqlite3.Row] = []
        aliases: list[sqlite3.Row] = []
        truncated = False

        for _ in range(depth):
            if not frontier:
                break
            rows = self._query_chunked(
                "SELECT * FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
                frontier,
                per_row_repeat=2,
            )
            collected.extend(rows)
            nxt = ({r["src"] for r in rows} | {r["dst"] for r in rows}) - seen

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
                nxt |= ({r["a"] for r in alias_rows} | {r["b"] for r in alias_rows}) - seen
                aliases.extend(alias_rows)
            if len(seen) + len(nxt) > max_nodes:
                nxt = set(sorted(nxt)[: max_nodes - len(seen)])
                truncated = True
            frontier = nxt
            seen |= nxt
            if truncated:
                break

        nodes = self._query_chunked("SELECT * FROM nodes WHERE id IN ({marks})", seen)
        edges = {
            (r["src"], r["dst"], r["type"]): r
            for r in collected
            if r["src"] in seen and r["dst"] in seen
        }
        # same_as 는 별도로 돌려준다 — 사실 관계를 나타내는 엣지가 아니라
        # "이 둘은 같은 실체"라는 메타 정보라서 시각화도 다르게 해야 한다.
        links = {
            (r["a"], r["b"]): r
            for r in aliases
            if r["a"] in seen and r["b"] in seen
        }
        return {
            "nodes": [dict(r) for r in nodes],
            "edges": [dict(r) for r in edges.values()],
            "same_as": [dict(r) for r in links.values()],
            "truncated": truncated,
        }
