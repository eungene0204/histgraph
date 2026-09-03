"""엔티티 해소 — 서로 다른 소스의 같은 실체를 잇는다.

문제: 국가유산청 그래프와 Wikidata 그래프가 서로 닿지 않는 두 개의 섬이다.
숭례문에서 세종으로 가는 경로가 없으면 온톨로지 그래프로서 작동하지 않는다.

접합점은 **장소와 시대**다. 국가유산청은 유물마다 시도·시군구와 시대를
주고, Wikidata 는 같은 지명과 왕조를 항목으로 갖고 있다. 둘을 이으면
"경주에 있는 국보" 와 "경주에서 활동한 신라 인물" 이 한 그래프에서 만난다.

모든 매칭은 `same_as` 테이블에 방법과 점수를 남긴다 — 자동 매칭은 틀릴 수
있으므로 나중에 검증하거나 되돌릴 수 있어야 한다.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from .ontology import EDGE_TYPES, Edge
from .store import GraphStore

log = logging.getLogger(__name__)

# 행정구역 접미사 — 라벨 비교 전에 떼어낸다.
# '서울특별시' 와 '서울', '경주시' 와 '경주' 를 같게 보기 위함.
ADMIN_SUFFIX = re.compile(r"(특별자치시|특별자치도|광역시|특별시|[시군구도])$")

# 국가유산청 시대명 -> Wikidata 왕조 QID.
# ccceName 은 '조선시대' 처럼 '시대' 가 붙어 오고, Wikidata 는 '조선'이다.
PERIOD_TO_POLITY: dict[str, str] = {
    "고구려": "Q28370",
    "백제": "Q28428",
    "신라": "Q28456",
    "통일신라": "Q28456",
    "발해": "Q28322",
    "고려": "Q28208",
    "조선": "Q28179",
    "대한제국": "Q28233",
    "일제강점기": "Q503585",
}

# 시대를 대표하는 노드의 **타입**. 한국사의 시대 구분은 대개 왕조와 같아서
# (§ontology 의 from_period 주석) org 로 세우지만, 일제강점기는 왕조가 아니라
# 기간이다. 통치 주체인 일본 제국을 시대 이름으로 쓸 수는 없으므로 —
# '일제강점기의 사건'과 '일본 제국의 사건'은 다른 말이다 — period 로 세운다.
POLITY_NODE_TYPE: dict[str, str] = {"일제강점기": "period"}


def normalize_place(label: str) -> str:
    """지명 정규화. '서울특별시' -> '서울', '경주시' -> '경주'."""
    label = label.strip()
    # 접미사를 반복 제거 ('경상북도' -> '경상북')는 과하므로 1회만
    stripped = ADMIN_SUFFIX.sub("", label)
    return stripped or label


def normalize_period(label: str) -> str:
    """'조선시대' -> '조선', '통일신라시대' -> '통일신라'."""
    return re.sub(r"\s*시대$", "", label.strip())


# 왕조명을 라벨 어디서든 찾는다. '통일신라'가 '신라'보다 먼저 와야
# 긴 이름이 우선 매칭된다.
_POLITY_PATTERN = re.compile(
    "(" + "|".join(sorted(PERIOD_TO_POLITY, key=len, reverse=True)) + ")"
)


def extract_polities(label: str) -> list[str]:
    """시대 라벨에서 언급된 왕조를 모두 뽑는다.

    국가유산청 `ccceName` 은 깔끔한 왕조명이 아니라 자유 서술이다:
      '통일신라시대∼고려시대', '판각: 1244년(고려 고종 31), 인출: 고려 말~조선 초',
      '현종8년(1017)'
    '시대' 접미사만 떼는 정규화로는 대부분 매칭되지 않는다."""
    found: list[str] = []
    for m in _POLITY_PATTERN.finditer(label):
        name = m.group(1)
        # '통일신라'를 잡았으면 그 안의 '신라'는 중복이므로 건너뛴다
        if name not in found:
            found.append(name)
    if "통일신라" in found and "신라" in found:
        found.remove("신라")
    return found


def link_periods(store: GraphStore) -> int:
    """국가유산청 시대 노드를 Wikidata 왕조에 연결.

    매핑 표가 있으므로 확실한 매칭 — score 1.0."""
    rows = store.conn.execute(
        "SELECT id, label FROM nodes WHERE type='period' AND source='khs'"
    ).fetchall()

    links = []
    multi = unmatched = 0
    for r in rows:
        polities = extract_polities(r["label"])
        if not polities:
            unmatched += 1
            log.debug("왕조를 못 찾음: %s", r["label"])
            continue
        if len(polities) > 1:
            # '통일신라시대~조선시대' 는 어느 한 왕조와 '같은 실체'가 아니다.
            # same_as 로 이으면 거짓말이 되므로 잇지 않는다.
            multi += 1
            log.debug("복수 왕조 (건너뜀): %s -> %s", r["label"], polities)
            continue
        target = f"wd:{PERIOD_TO_POLITY[polities[0]]}"
        # 상대 노드가 실제로 그래프에 있을 때만 잇는다 — 없는 노드를
        # 가리키는 same_as 는 경로를 만들어주지 못한다.
        if store.conn.execute("SELECT 1 FROM nodes WHERE id=?", (target,)).fetchone():
            links.append((r["id"], target, "period_polity", 1.0))

    store.conn.executemany(
        "INSERT OR REPLACE INTO same_as (a, b, method, score) VALUES (?,?,?,?)", links
    )
    store.conn.commit()
    log.info(
        "시대 연결 %d건 (복수 왕조 %d건, 왕조 미검출 %d건은 건너뜀)",
        len(links), multi, unmatched,
    )
    return len(links)


def link_event_periods(store: GraphStore) -> int:
    """사건의 `props.polity` 를 `from_period` 엣지로 세운다 (그래프 안 작업).

    **같은 사실이 소스에 따라 다른 자리에 들어 있었다.** 위키백과에서 온
    사건은 `from_period` 엣지로 조선에 붙는데, Wikidata 에서 온 사건은
    `props.polity` 라는 칸에만 적혀 있다 (`fetch_events` 가 P17 을 그렇게
    담는다). 그래서 화면에서 한쪽은 '시대 · 조선'이 보이고 다른 쪽은
    아무 관계도 없는 노드로 뜬다 — 실측 198건, 조선 그래프에만 105건.

    엣지의 자연키가 (src, dst, type, source) 라 여러 번 돌려도 쌓이지 않는다.
    """
    rows = store.conn.execute(
        """SELECT id, json_extract(props, '$.polity') AS polity
             FROM nodes
            WHERE type = 'event' AND json_extract(props, '$.polity') IS NOT NULL"""
    ).fetchall()
    # 왕조 이름 -> 노드. 정체 표(POLITIES)의 QID 가 그래프에 있어야 잇는다.
    from .sources.wikidata import POLITIES

    # **시대 자리에 설 수 있는 노드만 고른다.** 정체 표에는 있지만 그래프에는
    # 장소로 앉아 있는 노드가 있다 (실측: 조선민주주의인민공화국·대한민국).
    # 타입을 보지 않고 이으면 `from_period` 가 장소를 가리켜 스키마에
    # 어긋난 엣지가 500건 만들어진다. 이 둘은 장소인 것이 틀린 게 아니라
    # — 사람들의 출생지로도 쓰인다 — 시대 노릇을 겸할 수 없을 뿐이다.
    target = {}
    skipped = []
    for qid, name in POLITIES.items():
        row = store.conn.execute(
            "SELECT type FROM nodes WHERE id=?", (f"wd:{qid}",)
        ).fetchone()
        if row is None:
            continue
        if row["type"] in ("period", "org"):
            target[name] = f"wd:{qid}"
        else:
            skipped.append(f"{name}({row['type']})")
    if skipped:
        log.warning("시대 자리에 설 수 없는 정체 %s — 그 사건들은 잇지 않는다", ", ".join(skipped))

    have = {
        (r[0], r[1])
        for r in store.conn.execute(
            "SELECT src, dst FROM edges WHERE type = 'from_period'")
    }
    edges = [
        Edge(src=r["id"], dst=target[r["polity"]], type="from_period", source="wd")
        for r in rows
        if r["polity"] in target and (r["id"], target[r["polity"]]) not in have
    ]
    if edges:
        store.upsert_edges(edges)
    log.info("사건 시대 엣지 %d건 추가 (대상 사건 %d개)", len(edges), len(rows))
    return len(edges)


# 시대 노드로 잘못 향한 엣지들. '어디서'를 묻는 엣지인데 대답이 시대다.
_PLACE_EDGES_TO_PERIOD = ("born_in", "died_in", "occurred_at", "located_in")


def fix_period_nodes(store: GraphStore) -> dict[str, object]:
    """시대가 장소·다른 무엇으로 앉아 있는 것을 바로잡는다.

    **실측으로 드러난 것.** `wd:Q503585 일제강점기` 가 **장소** 노드였고,
    인물 44명의 출생지와 2명의 사망지가 거기로 가 있었다. Wikidata 의
    P19(출생지)가 '일제강점기 조선'을 답으로 주는데, 우리는 그걸 그대로
    장소로 받아 적었다. 화면은 "나운규는 일제강점기에서 죽었다"고 말한다.

    고치는 방법은 지우는 것이 아니다 — **'언제'를 '어디서' 칸에 적은 것뿐**
    이므로 `from_period` 로 옮긴다. 그러면 44명이 그 시대 사람이라는,
    원래 맞는 사실로 남는다.

    `upsert_nodes` 가 type 을 덮어쓰지 않기 때문에 이 어긋남은 다시
    수집해도 저절로 낫지 않는다. resolve 단계가 매번 확인한다."""
    conn = store.conn
    retyped: list[tuple[str, str, str]] = []
    moved = dropped = 0

    for name, qid in PERIOD_TO_POLITY.items():
        nid = f"wd:{qid}"
        row = conn.execute("SELECT type FROM nodes WHERE id=?", (nid,)).fetchone()
        if row is None:
            continue
        want = POLITY_NODE_TYPE.get(name, "org")
        # org 도 period 도 시대의 자리다 (from_period 의 도착 타입 둘).
        # 이미 둘 중 하나면 건드리지 않는다 — 조선은 org 가 맞다.
        if row["type"] not in ("period", "org"):
            conn.execute(
                "UPDATE nodes SET type=?, updated_at=datetime('now') WHERE id=?",
                (want, nid),
            )
            retyped.append((nid, row["type"], want))

        marks = ",".join("?" * len(_PLACE_EDGES_TO_PERIOD))
        rows = conn.execute(
            f"""SELECT e.src, e.dst, e.type, e.source, n.type AS src_type
                  FROM edges e JOIN nodes n ON n.id = e.src
                 WHERE e.dst = ? AND e.type IN ({marks})""",
            (nid, *_PLACE_EDGES_TO_PERIOD),
        ).fetchall()
        allowed = EDGE_TYPES["from_period"][1]
        for r in rows:
            if r["src_type"] in allowed:
                store.upsert_edges(
                    [
                        Edge(
                            src=r["src"], dst=nid, type="from_period",
                            source=r["source"],
                            # 어디서 온 엣지인지 남긴다. 원래 born_in 이었다는
                            # 사실이 지워지면 이 교정을 되짚을 수 없다.
                            props={"was": r["type"]},
                        )
                    ]
                )
                moved += 1
            else:
                dropped += 1
            conn.execute(
                "DELETE FROM edges WHERE src=? AND dst=? AND type=? AND source=?",
                (r["src"], nid, r["type"], r["source"]),
            )

    # 시대 자리에 설 수 없는 노드를 가리키는 `from_period` 를 걷어낸다.
    # 실측 503건이 조선민주주의인민공화국·대한민국(둘 다 장소 노드)을
    # 가리키고 있었다. 잃는 것은 없다 — 같은 사실이 노드의 props.polity 에
    # 남아 있어서, 그 노드가 시대 자리에 서는 순간 link_event_periods 가
    # 다시 만든다.
    stale = conn.execute(
        """SELECT COUNT(*) FROM edges e JOIN nodes n ON n.id = e.dst
            WHERE e.type='from_period' AND n.type NOT IN ('period','org')"""
    ).fetchone()[0]
    if stale:
        conn.execute(
            """DELETE FROM edges WHERE type='from_period' AND dst IN (
                 SELECT id FROM nodes WHERE type NOT IN ('period','org'))"""
        )
        log.info("시대가 될 수 없는 노드를 가리키던 from_period %d건 제거", stale)

    conn.commit()
    if retyped or moved or dropped:
        log.info(
            "시대 노드 교정: 타입 %d개, 장소→시대 엣지 %d건 (버림 %d건)",
            len(retyped), moved, dropped,
        )
    return {"retyped": retyped, "moved": moved, "dropped": dropped, "stale": stale}


def link_places(store: GraphStore) -> int:
    """국가유산청 장소 노드를 Wikidata 장소에 연결.

    정규화한 지명이 정확히 일치할 때만 잇는다. 부분 일치는 '경주'와
    '경주 시내' 처럼 다른 대상을 엮을 위험이 커서 쓰지 않는다."""
    wd_places: dict[str, list[str]] = {}
    for r in store.conn.execute(
        "SELECT id, label FROM nodes WHERE type='place' AND source='wd'"
    ):
        wd_places.setdefault(normalize_place(r["label"]), []).append(r["id"])

    links = []
    ambiguous = 0
    for r in store.conn.execute(
        "SELECT id, label, props FROM nodes WHERE type='place' AND source='khs'"
    ):
        # 시군구가 있으면 그쪽이 더 구체적이라 우선 매칭한다
        import json

        props = json.loads(r["props"] or "{}")
        candidates = [props.get("sigungu"), props.get("sido")]

        for cand in candidates:
            if not cand:
                continue
            matches = wd_places.get(normalize_place(cand))
            if not matches:
                continue
            if len(matches) > 1:
                # 동명이인 격 ('중구'는 서울·부산·대구에 다 있다). 자동으로
                # 고르면 틀린 곳에 붙는다 — 다음 후보(시도)로 넘어간다.
                # 여기서 break 하면 유물 전체가 연결에서 탈락한다.
                ambiguous += 1
                log.debug("모호한 지명 %s -> %d개 후보, 상위 행정구역으로 후퇴", cand, len(matches))
                continue
            links.append((r["id"], matches[0], "place_label_exact", 0.9))
            break

    store.conn.executemany(
        "INSERT OR REPLACE INTO same_as (a, b, method, score) VALUES (?,?,?,?)", links
    )
    store.conn.commit()
    log.info("장소 연결 %d건 (모호해서 건너뜀 %d건)", len(links), ambiguous)
    return len(links)


def prune_sports(store: GraphStore) -> dict[str, int]:
    """스포츠 이벤트 노드와 그 엣지를 제거.

    판정은 파이썬 정규식 하나로만 한다. SQL LIKE 목록을 따로 두면 두
    패턴 목록이 반드시 갈라지고(실제로 갈라져서 배드민턴 대회가
    남았다), 어느 쪽이 진짜인지 알 수 없게 된다.

    노드만 지우면 엣지가 댕글링으로 남으므로 함께 지운다."""
    from .filters import is_sports

    ids = [
        r["id"]
        for r in store.conn.execute("SELECT id, label FROM nodes WHERE type='event'")
        if is_sports(r["label"])
    ]
    if not ids:
        return {"nodes": 0, "edges": 0}

    edges = 0
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        marks = ",".join("?" * len(batch))
        cur = store.conn.execute(
            f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
            (*batch, *batch),
        )
        edges += cur.rowcount
        store.conn.execute(f"DELETE FROM nodes WHERE id IN ({marks})", batch)

    store.conn.commit()
    log.info("스포츠 노드 %d개, 엣지 %d개 제거", len(ids), edges)
    return {"nodes": len(ids), "edges": edges}


def prune_sports_by_class(store: GraphStore, fetcher=None) -> dict[str, int]:
    """Wikidata 클래스 계층으로 스포츠 이벤트를 제거한다.

    라벨 정규식은 두더지잡기다 — 'Superseries', 'Konica Cup',
    'Internationaux de France' 처럼 이름만으로는 스포츠인지 알 수 없는
    항목이 계속 남는다. Wikidata 가 이미 P279* 계층을 갖고 있으므로
    이름을 추측하지 말고 그 계층에 직접 물어본다."""
    from .http import Fetcher
    from .sources.wikidata import SPARQL_URL, _qid, _safe_query, _val

    fetcher = fetcher or Fetcher(store.path.parent / "cache", min_interval=1.5)

    qids = [
        r["id"].split(":", 1)[1]
        for r in store.conn.execute(
            "SELECT id FROM nodes WHERE type='event' AND source='wd'"
        )
    ]
    if not qids:
        return {"nodes": 0, "edges": 0}

    log.info("사건 노드 %d개의 클래스 조회 중...", len(qids))
    sports: set[str] = set()
    failures: list[str] = []

    for i in range(0, len(qids), 300):
        batch = qids[i : i + 300]
        values = " ".join(f"wd:{q}" for q in batch)
        rows = _safe_query(
            fetcher,
            f"""SELECT DISTINCT ?e WHERE {{
                  VALUES ?e {{ {values} }}
                  VALUES ?sport {{ wd:Q13406554 wd:Q16510064 wd:Q46190676 wd:Q500834 }}
                  ?e wdt:P31/wdt:P279* ?sport .
                }}""",
            f"스포츠분류/{i}",
            failures,
        )
        sports.update(_qid(_val(r, "e") or "") for r in rows)

    if failures:
        log.warning("클래스 조회 실패 %d건 — 해당 구간은 걸러지지 않음", len(failures))
    if not sports:
        return {"nodes": 0, "edges": 0}

    ids = [f"wd:{q}" for q in sports]
    edges = 0
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        marks = ",".join("?" * len(batch))
        cur = store.conn.execute(
            f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
            (*batch, *batch),
        )
        edges += cur.rowcount
        store.conn.execute(f"DELETE FROM nodes WHERE id IN ({marks})", batch)
    store.conn.commit()

    log.info("클래스 기반 스포츠 노드 %d개, 엣지 %d개 제거", len(ids), edges)
    return {"nodes": len(ids), "edges": edges}


def bridge_report(store: GraphStore) -> dict[str, object]:
    """두 섬이 실제로 연결됐는지 검증한다.

    same_as 행 수만 세면 '연결된 것 같다'는 착각을 하기 쉽다. 실제로
    소스를 건너뛰는 경로가 생겼는지 확인한다."""
    c = store.conn
    total = c.execute("SELECT COUNT(*) FROM same_as").fetchone()[0]
    by_method = {
        r["method"]: r["n"]
        for r in c.execute(
            "SELECT method, COUNT(*) n FROM same_as GROUP BY method ORDER BY n DESC"
        )
    }
    # 서로 다른 소스를 잇는 링크만이 섬을 연결한다
    cross = c.execute(
        """SELECT COUNT(*) FROM same_as s
           JOIN nodes na ON na.id = s.a
           JOIN nodes nb ON nb.id = s.b
           WHERE na.source != nb.source"""
    ).fetchone()[0]
    # 국가유산청 유물에서 same_as 를 한 번 거쳐 Wikidata 로 나가는 경로 수
    reachable = c.execute(
        """SELECT COUNT(DISTINCT e.src) FROM edges e
           JOIN same_as s ON s.a = e.dst
           JOIN nodes n ON n.id = e.src
           WHERE n.source = 'khs'"""
    ).fetchone()[0]
    return {
        "same_as_total": total,
        "cross_source": cross,
        "by_method": by_method,
        "heritage_nodes_reaching_wikidata": reachable,
    }
