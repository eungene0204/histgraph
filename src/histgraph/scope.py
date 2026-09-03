"""시대별 서브그래프 추출.

전체 그래프는 현대 인물이 압도한다 — 인물 28,471명 중 대한민국 국적이
18,471명(65%)이고 조선은 2,923명이다. 한 시대를 먼저 제대로 만들어 보고
확장 여부를 판단하는 편이 낫다.

**원본은 건드리지 않는다.** 별도 DB 로 뽑아내므로 나중에 다른 시대를
추가하거나 기준을 바꿔 다시 뽑을 수 있다.

선정 방식:
  1) 씨앗 — 그 시대로 명시된 인물·사건·유물
  2) 1홉 확장 — 씨앗이 실제로 연결된 장소·직위·조직·인물
  3) 양끝이 모두 포함된 엣지만 유지

1홉까지만 넓히는 이유: 2홉이면 조선 인물의 현대 후손, 그 후손이 참여한
현대 사건까지 딸려 와 시대 구분이 무의미해진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .store import GraphStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Era:
    """한 시대를 고르는 기준."""

    name: str
    polity_qid: str
    polity_label: str
    # 유물 시대 라벨에서 이 왕조를 가리키는 표기들
    aliases: list[str] = field(default_factory=list)


ERAS: dict[str, Era] = {
    "joseon": Era("조선", "Q28179", "조선", ["조선"]),
    "goryeo": Era("고려", "Q28208", "고려", ["고려"]),
    "silla": Era("신라", "Q28456", "신라", ["신라", "통일신라"]),
    "goguryeo": Era("고구려", "Q28370", "고구려", ["고구려"]),
    "baekje": Era("백제", "Q28428", "백제", ["백제"]),
}


def select_seeds(store: GraphStore, era: Era) -> set[str]:
    """그 시대로 명시된 노드들.

    세 경로가 있고 서로 겹치지 않는다:
      - 인물: Wikidata 국적(P27)을 수집 때 props.polity 에 적어뒀다
      - 사건: 시드 목록의 시대 구분, 또는 왕조 노드와 직접 연결
      - 유물: 국가유산청 시대 라벨이 same_as 로 왕조에 해소된 것
    """
    c = store.conn
    seeds: set[str] = set()

    persons = [
        r["id"]
        for r in c.execute(
            "SELECT id FROM nodes WHERE type='person' AND json_extract(props,'$.polity')=?",
            (era.polity_label,),
        )
    ]
    # **국적 태그가 없는 인물이 3,390명이고 거기에 왕들이 들어 있다.**
    # '조선 정종'은 라벨에 시대가 적혀 있는데도 씨앗이 아니어서, 다른
    # 인물의 이웃으로만 딸려 들어왔다. 그 바람에 그의 어머니(한씨)처럼
    # 두 홉 밖에 있는 가족이 시대 그래프에서 통째로 잘려 나갔다.
    by_label = [
        r["id"]
        for r in c.execute(
            "SELECT id FROM nodes WHERE type='person' AND label LIKE ?",
            (f"{era.polity_label} %",),
        )
    ]
    persons = list({*persons, *by_label})
    seeds.update(persons)

    events = [
        r["id"]
        for r in c.execute(
            """SELECT id FROM nodes WHERE type='event'
               AND json_extract(props,'$.seed_era')=?""",
            (era.polity_label,),
        )
    ]
    # 왕조 노드에 from_period 로 직접 걸린 사건도 포함
    events += [
        r["src"]
        for r in c.execute(
            "SELECT src FROM edges WHERE type='from_period' AND dst=?",
            (f"wd:{era.polity_qid}",),
        )
    ]
    seeds.update(events)

    heritage = [
        r["src"]
        for r in c.execute(
            """SELECT DISTINCT e.src FROM edges e
               JOIN same_as s ON s.a = e.dst
               WHERE s.b = ? AND e.type='from_period'""",
            (f"wd:{era.polity_qid}",),
        )
    ]
    seeds.update(heritage)

    log.info(
        "%s 씨앗: 인물 %d · 사건 %d · 유물 %d (합 %d)",
        era.name, len(persons), len(set(events)), len(heritage), len(seeds),
    )
    return seeds


def expand(store: GraphStore, seeds: set[str], hops: int = 1) -> set[str]:
    """씨앗이 연결된 노드까지 넓힌다. same_as 도 따라간다."""
    seen = set(seeds)
    frontier = set(seeds)

    for hop in range(hops):
        if not frontier:
            break
        found: set[str] = set()
        ordered = sorted(frontier)
        for i in range(0, len(ordered), 500):
            batch = ordered[i : i + 500]
            marks = ",".join("?" * len(batch))
            for r in store.conn.execute(
                f"""SELECT src, dst FROM edges
                    WHERE src IN ({marks}) OR dst IN ({marks})""",
                (*batch, *batch),
            ):
                found.add(r["src"])
                found.add(r["dst"])
            for r in store.conn.execute(
                f"SELECT a, b FROM same_as WHERE a IN ({marks}) OR b IN ({marks})",
                (*batch, *batch),
            ):
                found.add(r["a"])
                found.add(r["b"])
        frontier = found - seen
        seen |= found
        log.info("  %d홉 확장: +%d 노드 (누적 %d)", hop + 1, len(frontier), len(seen))

    return seen


# 장소는 사건·인물을 설명하는 자리다. 한쪽만 남으면 그래프가 거짓말을 한다.
PLACE_EDGES = ("occurred_at", "born_in", "died_in")


def close_places(store: GraphStore, keep: set[str]) -> set[str]:
    """포함된 노드가 '어디서'를 가리키면 그 장소도 데려온다.

    **실측.** '위화도 회군'은 이성계의 이웃으로 들어왔는데, 정작 이름이
    된 위화도는 두 홉 밖이라 잘려 나갔다. 남은 발생 장소는 개경과
    평양뿐이어서 화면이 "위화도 회군은 개성시에서 일어났다"고 말했다.
    장소를 다 못 데려올 바에는 하나도 없는 편이 낫지만, 22개만 더
    담으면 되는 일이다 (조선 그래프 기준 사건 10개의 장소 25건).
    """
    added: set[str] = set()
    ordered = sorted(keep)
    marks_type = ",".join("?" * len(PLACE_EDGES))
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        for r in store.conn.execute(
            f"""SELECT dst FROM edges
                 WHERE src IN ({marks}) AND type IN ({marks_type})""",
            (*batch, *PLACE_EDGES),
        ):
            if r["dst"] not in keep:
                added.add(r["dst"])
    if added:
        log.info("장소 보강: +%d 노드", len(added))
    return keep | added


def _dated_events(store: GraphStore, ids: set[str]) -> set[str]:
    """그 가운데 연대를 아는 사건만. 연표에 놓을 자리가 있는 것들이다."""
    if not ids:
        return set()
    out: set[str] = set()
    ordered = sorted(ids)
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        out.update(
            r["id"]
            for r in store.conn.execute(
                f"""SELECT id FROM nodes
                     WHERE id IN ({marks}) AND type='event'
                       AND start_date IS NOT NULL AND start_date != ''""",
                batch,
            )
        )
    return out


def extract(
    store: GraphStore,
    era_key: str,
    out_path: str,
    hops: int = 1,
    drop_isolated: bool = True,
) -> dict[str, object]:
    """시대 서브그래프를 별도 DB 로 뽑는다."""
    from pathlib import Path

    era = ERAS.get(era_key)
    if era is None:
        raise ValueError(f"알 수 없는 시대: {era_key} (가능: {', '.join(ERAS)})")

    seeds = select_seeds(store, era)
    if not seeds:
        raise ValueError(f"{era.name} 씨앗 노드가 없습니다 — 먼저 수집·해소가 필요합니다")

    keep = expand(store, seeds, hops=hops)
    # 왕조 노드 자신도 그래프의 중심으로 포함한다
    keep.add(f"wd:{era.polity_qid}")
    keep = close_places(store, keep)

    isolated: set[str] = set()
    if drop_isolated:
        # 엣지가 하나도 없는 노드는 그래프에서 할 일이 없다. 실측: 조선
        # 인물 2,923명 중 상당수가 Wikidata 에서 노드만 오고 관계가 없어
        # 화면에 점으로만 떠 있게 된다.
        connected: set[str] = set()
        ordered_all = sorted(keep)
        for i in range(0, len(ordered_all), 500):
            batch = ordered_all[i : i + 500]
            marks = ",".join("?" * len(batch))
            for r in store.conn.execute(
                f"SELECT src, dst FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
                (*batch, *batch),
            ):
                connected.add(r["src"])
                connected.add(r["dst"])
            for r in store.conn.execute(
                f"SELECT a, b FROM same_as WHERE a IN ({marks}) OR b IN ({marks})",
                (*batch, *batch),
            ):
                connected.add(r["a"])
                connected.add(r["b"])
        isolated = keep - connected
        keep &= connected
        log.info("고립 노드 %d개 제외 (남은 노드 %d)", len(isolated), len(keep))

    out = Path(out_path)
    if out.exists():
        out.unlink()
    dest = GraphStore(out)

    ordered = sorted(keep)
    node_rows, edge_rows, alias_rows = [], [], []
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        node_rows += store.conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({marks})", batch
        ).fetchall()
        # 한쪽 끝만 배치에 걸고 가져온 뒤 파이썬에서 양끝을 검사한다.
        # SQL 에서 `src IN (batch) AND dst IN (batch)` 로 거르면 배치를
        # 넘나드는 엣지가 통째로 사라진다 — 5,143 노드에 엣지가 313개만
        # 남았던 원인이 이것이었다.
        edge_rows += store.conn.execute(
            f"SELECT * FROM edges WHERE src IN ({marks})", batch
        ).fetchall()
        alias_rows += store.conn.execute(
            f"SELECT * FROM same_as WHERE a IN ({marks})", batch
        ).fetchall()

    edge_rows = [r for r in edge_rows if r["dst"] in keep]
    alias_rows = [r for r in alias_rows if r["b"] in keep]

    cols = "id,type,label,source,start_date,end_date,lat,lon,description,url,props,updated_at"
    dest.conn.executemany(
        f"INSERT OR REPLACE INTO nodes ({cols}) VALUES ({','.join('?' * 12)})",
        [tuple(r[c] for c in cols.split(",")) for r in node_rows],
    )
    ecols = "src,dst,type,source,label,start_date,end_date,confidence,props"
    dest.conn.executemany(
        f"INSERT OR REPLACE INTO edges ({ecols}) VALUES ({','.join('?' * 9)})",
        [tuple(r[c] for c in ecols.split(",")) for r in {
            (r["src"], r["dst"], r["type"], r["source"]): r for r in edge_rows
        }.values()],
    )
    dest.conn.executemany(
        "INSERT OR REPLACE INTO same_as (a,b,method,score) VALUES (?,?,?,?)",
        [(r["a"], r["b"], r["method"], r["score"]) for r in {
            (r["a"], r["b"]): r for r in alias_rows
        }.values()],
    )
    dest.conn.commit()

    stats = dest.stats()
    dest.close()
    return {
        "era": era.name,
        "out": str(out),
        "seeds": len(seeds),
        "isolated_dropped": len(isolated),
        "kept_nodes": stats["nodes_total"],
        "kept_edges": stats["edges_total"],
        "by_node_type": stats["by_node_type"],
        "by_edge_type": stats["by_edge_type"],
        "dangling": stats["dangling_edges"],
    }
