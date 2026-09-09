"""SQLite 그래프 저장소.

멱등(idempotent) 저장이 목표 — 같은 수집을 여러 번 돌려도 중복이 쌓이지
않아야 파이프라인을 반복 실행할 수 있다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from urllib.request import pathname2url

from . import overrides as overrides_mod
from .ontology import Edge, Node

SCHEMA = overrides_mod.SCHEMA + """
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

-- 정본이 아닌 설명을 우리 말로 새로 쓴 글 (summaries.py). nodes.description
-- 은 손대지 않는다 — 수집이 설명을 통째로 다시 쓰므로, 우리가 쓴 글은 따로
-- 두고 원문 해시로 아직 유효한지 잰다.
CREATE TABLE IF NOT EXISTS summaries (
    node_id  TEXT PRIMARY KEY,
    text     TEXT NOT NULL,
    model    TEXT NOT NULL,
    src_hash TEXT NOT NULL,
    made_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 무게 — 타입 가중 PageRank (central.py). 세어서 나온 값이라 편집 계층이
-- 아니다. 수집·scope 뒤에 다시 만든다. 없으면 화면이 차수로 물러난다.
CREATE TABLE IF NOT EXISTS centrality (
    node_id TEXT PRIMARY KEY,
    score   REAL NOT NULL,
    rank    INTEGER NOT NULL,
    made_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_centrality_score ON centrality(score DESC);

CREATE TABLE IF NOT EXISTS ingest_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source   TEXT NOT NULL,
    nodes    INTEGER NOT NULL,
    edges    INTEGER NOT NULL,
    ran_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class GraphStore:
    def __init__(self, path: Path | str, *, readonly: bool = False) -> None:
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            # 배포된 서버의 파일시스템은 읽기 전용이다. 평소처럼 열면 sqlite 가
            # 저널 파일을 만들려 들고, 아래 executescript(SCHEMA) 가 곧바로
            # 'attempt to write a readonly database' 로 첫 요청을 죽인다.
            # 연결 자체를 ro 로 열어 쓰기를 시도하지 않게 한다.
            self.conn = sqlite3.connect(
                f"file:{pathname2url(str(self.path))}?mode=ro", uri=True
            )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # 이 프로젝트는 몇 시간짜리 추출과 수집을 나란히 돌린다. 기본값
        # (busy_timeout=0)이면 다른 쪽이 쓰는 순간 곧바로 'database is
        # locked' 로 죽어서 진행 중이던 작업을 잃는다. 기다리게 한다.
        self.conn.execute("PRAGMA busy_timeout = 30000")
        #: `centrality` 표가 있는가. 한 번만 묻는다 (배포 DB 는 읽기 전용이라
        #: 스키마가 돌지 않아 표가 없을 수 있다).
        self._has_centrality: bool | None = None
        if not readonly:
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
        # **편집 계층을 다시 씌운다** (`overrides` 모듈 머리글). 위의 덮어쓰기가
        # 사람이 고친 이름·정본 설명·잘라 둔 날짜를 방금 지웠을 수 있다.
        # 수집이 무엇을 가져왔든 고친 값이 마지막에 선다.
        self.last_reapply = overrides_mod.reapply(self, node_ids=[r[0] for r in rows])
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
        # 재위 표식(`reigns`)처럼 엣지에 적어 둔 값도 같은 규칙이다.
        overrides_mod.reapply(
            self, edge_keys={overrides_mod.edge_key(r[0], r[1], r[2]) for r in rows}
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

    def weights(self, ids: set[str]) -> dict[str, float]:
        """**무엇을 먼저 보여줄지 정하는 값.** 차수가 아니라 타입 가중
        PageRank 다 (`central` 모듈 머리글 — 차수는 역사가 아니라 문서의
        길이를 잰다). 아직 `histgraph central` 을 돌리지 않은 DB 에서는
        차수로 물러난다. 자르는 데 쓰는 값이 아니라 **줄 세우는** 값이다."""
        if self._has_centrality is None:
            from . import central
            self._has_centrality = central.present(self.conn)
        if not self._has_centrality:
            return {k: float(v) for k, v in self.degrees(ids).items()}
        rows = self._query_chunked(
            "SELECT node_id AS id, score FROM centrality WHERE node_id IN ({marks})", ids
        )
        got = {r["id"]: r["score"] for r in rows}
        # 표에 없는 노드(수집이 방금 넣은 것)는 맨 뒤가 아니라 0 이다 —
        # 없는 것과 낮은 것을 가르지 않는다. 다시 돌리면 제자리를 찾는다.
        return {nid: got.get(nid, 0.0) for nid in ids}

    def _share_budget(
        self,
        rows: list[sqlite3.Row],
        alias_rows: list[sqlite3.Row],
        frontier: set[str],
        candidates: set[str],
        budget: int,
    ) -> set[str]:
        """상한에 걸렸을 때 **프론티어가 예산을 나눠 갖는다.**

        차수로만 자르면 허브 하나가 예산을 통째로 먹는다 — 실측: 명성황후에서
        두 걸음을 펴면 새 노드 91개 중 68개가 '조선'의 이웃이라, 화면이
        명성황후가 아니라 조선의 그래프가 됐다 (2026-09-06 지적). 조선이
        중요해서 이긴 것이 아니라 엣지가 많아서 이긴 것이다.

        그래서 프론티어 노드마다 하나씩 돌아가며 담는다. 제 몫 안에서는 무게가
        큰 이웃이 먼저고, 이웃이 적은 노드가 남긴 자리는 많은 쪽이 이어 쓴다.
        걸음이 하나뿐이면(프론티어 = 중심 하나) 무게 순서가 그대로 남는다 —
        나눌 상대가 없다.
        """
        if budget <= 0:
            return set()
        kids: dict[str, set[str]] = {}
        pairs = [(r["src"], r["dst"]) for r in rows]
        pairs += [(r["a"], r["b"]) for r in alias_rows]
        for a, b in pairs:
            for parent, kid in ((a, b), (b, a)):
                if parent in frontier and kid in candidates:
                    kids.setdefault(parent, set()).add(kid)
        rank = self.weights(candidates)
        order = {
            p: sorted(ids, key=lambda i: (-rank.get(i, 0), i)) for p, ids in kids.items()
        }
        # 이웃이 적은 노드부터 돈다 — 몇 개 없는 쪽이 먼저 제 몫을 채우고
        # 빠져야, 남은 자리를 허브가 이어 쓰는 순서가 된다.
        parents = sorted(order, key=lambda p: (len(order[p]), p))
        at = dict.fromkeys(parents, 0)
        picked: set[str] = set()
        while len(picked) < budget:
            moved = False
            for p in parents:
                i, mine = at[p], order[p]
                while i < len(mine) and mine[i] in picked:
                    i += 1
                at[p] = i
                if i >= len(mine):
                    continue
                picked.add(mine[i])
                at[p] = i + 1
                moved = True
                if len(picked) >= budget:
                    break
            if not moved:
                break
        return picked

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

        **상한에 걸리면 무게가 큰 이웃부터 남긴다** (`weights`). id 순으로 자르면
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
            alias_rows: list[sqlite3.Row] = []
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
                nxt = self._share_budget(
                    rows, alias_rows, frontier, nxt, max(max_nodes - len(seen), 0)
                )
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
