"""사건과 개념을 갈라낸다.

실측 배경: 화면의 `depicts` 157건 중 실제 역사 사건을 가리키는 것은
6.25 전쟁 6건뿐이었다. 나머지는 '자살'·'간통죄'·'조직범죄' 같은 **주제어**
였고, 그것들이 전부 **사건 노드**로 앉아 있었다. 원인은 `fetch_media` 가
P921(주제)의 값을 타입도 모른 채 `event` 로 만들어 넣은 한 줄이다.

스포츠 오염 때와 같은 처방을 쓴다 — **이름을 보고 짐작하지 않고 Wikidata 의
클래스 계층에 직접 물어본다.** 다른 점은 지우지 않는다는 것이다. 주제어는
쓰레기가 아니라 자리를 잘못 찾은 개념이다. `concept` 으로 옮기고 그 엣지를
`depicts` 에서 `about` 으로 바꾼다.

판정 사다리 (점수가 아니라 규칙이다):

  1. **P279(상위 부류)를 갖고 있으면 개념이다.** 개별 사건은 상위 부류를
     갖지 않는다. '전쟁'(Q198)·'살인'(Q118322)은 사건 계층에 닿지만 부류이고,
     '6.25 전쟁'·'황산벌 전투'는 P279 가 없다. 이 검사를 먼저 두는 이유가
     그것이다 — 사건 계층 검사만 하면 부류가 사건으로 통과한다.
  2. P31/P279* 가 Q1190554(사건)에 닿으면 **사건**이다.
  3. P31 이 `WD_CLASS_TO_TYPE` 에 있으면 그 타입 (인물·장소·조직…).
  4. 아무것도 아니면 **보류한다.** 손대지 않고 목록으로 보고한다.
     여기서 짐작으로 옮기면 진짜 사건을 잃는다.

조회가 실패한 구간은 통째로 보류한다. **'결과가 없다'와 '못 물어봤다'를
구분하지 않으면 조용히 틀린 재분류가 된다** — 이 판정은 결과의 *부재*를
근거로 삼기 때문에 특히 그렇다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .store import GraphStore

log = logging.getLogger(__name__)

# 계층을 걸어 올라가 닿으면 그 타입이라고 보는 뿌리.
# **사건 하나뿐이다.** 조직(Q43229)도 뿌리로 써 보았지만 못 쓴다 —
# Wikidata 에서 농민 봉기 → 사회 운동 → 집단 행동 → 인포멀 그룹 → 단체로
# 이어져서 민란·시위·군사작전이 전부 조직에도 닿는다(실측). 뿌리를
# 늘리면 갈라지는 것이 아니라 겹쳐서, 진짜 사건들이 '둘 다에 닿음'으로
# 보류된다(실측: 보류가 14개에서 54개로 늘었다).
ROOTS: dict[str, str] = {
    "Q1190554": "event",  # 사건
}
OCCURRENCE = "Q1190554"

# 사람. 이 클래스만 사다리 맨 앞에서 본다.
PERSON_CLASS = "Q5"

# 개체가 아닌 문서들. 개념으로 옮기면 안 된다 — 개념이 아니라 **노드로
# 있으면 안 되는 것**이고, 지우는 판단은 사람이 해야 한다.
# 실측: '진주성 전투'가 동음이의어 문서인 채로 사건 노드에 앉아 있었다.
NOT_AN_ENTITY: dict[str, str] = {
    "Q4167410": "동음이의어 문서",
    "Q13406463": "위키미디어 목록 문서",
    "Q4167836": "위키미디어 분류",
}

# 한 번에 물어볼 QID 수. VALUES 에 속성 경로를 걸면 300개에서 60초 제한에
# 걸린다. 150이 실측으로 안전한 크기.
BATCH = 150

# 계층은 노드가 아니라 클래스 집합에 대해 걷는다 — 훨씬 작다.
CLASS_BATCH = 150

# 사건 계층까지 걸어 올라갈 최대 깊이. 실측으로 '전투'·'시위'는 1~3단계,
# 가장 먼 것도 5단계에서 사건에 닿았다.
MAX_DEPTH = 6

# **속성 경로 질의는 쓰지 않는다.** Fetcher 의 기본 timeout(30초)을 90초로
# 늘려도 WDQS 가 `?c wdt:P279* wd:Q1190554` 를 60개 VALUES 에서 504로
#거절한다(실측). 한 단계씩 걷는 질의는 같은 크기에서 2.5초에 끝난다.
TIMEOUT = 90


@dataclass
class Plan:
    """재분류 계획. `--dry-run` 이 이것만 출력한다."""

    changes: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (전, 후)
    labels: dict[str, str] = field(default_factory=dict)               # id -> 라벨
    held: list[tuple[str, str]] = field(default_factory=list)          # 보류 (id, 라벨)
    failed_batches: int = 0

    def by_target(self, target: str) -> list[str]:
        return [i for i, (_, after) in self.changes.items() if after == target]


def _root_reach(
    fetcher, classes: set[str], failures: list[str]
) -> tuple[dict[str, set[str]], bool]:
    """뿌리별로 그 계층에 닿는 클래스 집합. 두 번째 값은 '조회가 실패했나'.

    `wdt:P279*` 한 방이면 될 일이지만 **WDQS 가 그 질의를 거절한다** —
    60개 VALUES 에도 504 를 준다(실측). 한 단계씩 올라가는 질의는 같은
    크기에서 2.5초에 끝나고, 단계마다 캐시가 남아 다시 돌릴 때 공짜가 된다.
    상위로 갈수록 클래스가 합쳐지므로 깊이가 늘어도 질의는 커지지 않는다."""
    from .sources.wikidata import _qid, _safe_query, _val

    parents: dict[str, set[str]] = {}
    frontier = set(classes)
    seen = set(classes)
    failed = False

    for depth in range(MAX_DEPTH):
        if not frontier:
            break
        ordered = sorted(frontier)
        found: set[str] = set()
        for i in range(0, len(ordered), CLASS_BATCH):
            batch = ordered[i : i + CLASS_BATCH]
            values = " ".join(f"wd:{c}" for c in batch)
            before = len(failures)
            rows = _safe_query(
                fetcher,
                f"SELECT ?c ?p WHERE {{ VALUES ?c {{ {values} }} ?c wdt:P279 ?p }}",
                f"상위부류/{depth}/{i}",
                failures,
            )
            failed = failed or len(failures) > before
            for r in rows:
                child, parent = _qid(_val(r, "c") or ""), _qid(_val(r, "p") or "")
                parents.setdefault(child, set()).add(parent)
                if parent not in seen:
                    found.add(parent)
        seen |= found
        frontier = found
        log.info("  상위 부류 %d단계: 새 클래스 %d개", depth + 1, len(found))

    # 뿌리에서 아래로 되짚어 내려온다. 한 번 더 돌 때 늘어나는 것이 없으면 끝.
    reach: dict[str, set[str]] = {}
    for root, _type in ROOTS.items():
        got = {root}
        while True:
            grown = {c for c, ps in parents.items() if c not in got and ps & got}
            if not grown:
                break
            got |= grown
        reach[root] = got
    return reach, failed


def _classify(
    fetcher,
    qids: list[str],
    subject_only: set[str],
    event_role: set[str],
    failures: list[str],
) -> tuple[dict[str, str], set[str]]:
    """QID -> 판정된 타입. 두 번째 값은 판정하지 못해 보류한 QID 들.

    **그래프에서 그 노드가 하는 역할이 Wikidata 의 분류보다 무겁다.**
    앞의 두 관문이 그것이고, 클래스 계층은 그 다음에야 본다."""
    from .sources.wikidata import WD_CLASS_TO_TYPE, _qid, _safe_query, _val

    verdict: dict[str, str] = {}
    held: set[str] = set()
    subclass: set[str] = set()          # P279 를 가진 노드 = 부류
    dated: set[str] = set()             # P580/P585/P582 를 가진 노드 = 개별 사건
    classes: dict[str, set[str]] = {}   # 노드 -> P31 클래스들

    for i in range(0, len(qids), BATCH):
        batch = qids[i : i + BATCH]
        values = " ".join(f"wd:{q}" for q in batch)
        before = len(failures)

        # 부류인가와 시점을 가졌는가를 한 질의에서 함께 묻는다.
        for r in _safe_query(
            fetcher,
            f"""SELECT ?e ?isClass ?hasDate WHERE {{ VALUES ?e {{ {values} }}
                  BIND(EXISTS {{ ?e wdt:P279 ?x }} AS ?isClass)
                  BIND(EXISTS {{ ?e wdt:P580|wdt:P585|wdt:P582 ?d }} AS ?hasDate) }}""",
            f"부류·시점/{i}",
            failures,
        ):
            q = _qid(_val(r, "e") or "")
            if _val(r, "isClass") == "true":
                subclass.add(q)
            if _val(r, "hasDate") == "true":
                dated.add(q)

        for r in _safe_query(
            fetcher,
            f"SELECT ?e ?c WHERE {{ VALUES ?e {{ {values} }} ?e wdt:P31 ?c }}",
            f"클래스/{i}",
            failures,
        ):
            classes.setdefault(_qid(_val(r, "e") or ""), set()).add(_qid(_val(r, "c") or ""))

        if len(failures) > before:
            # 한 질의라도 실패하면 이 구간의 판정은 믿을 수 없다. 부재를
            # 근거로 삼는 판정이라 '못 물어본 것'이 '아닌 것'이 된다.
            held.update(batch)

    all_classes = {c for qs in classes.values() for c in qs}
    reach, class_failed = _root_reach(fetcher, all_classes, failures)

    for q in qids:
        if q in held:
            continue

        mine = classes.get(q, set())
        # 1. **사람이라고 적혀 있으면 사람이다.** 이 검사만 앞에 둔다 —
        #    실측으로 '이춘재'가 주제 자리에만 있다는 이유로 개념이 될
        #    뻔했다. 매핑표 전체를 앞세우면 반대로 다친다: 제2차 세계
        #    대전의 P31 에 '시대'가 섞여 있어 시대 노드가 됐다.
        if PERSON_CLASS in mine:
            verdict[q] = "person"
            continue

        # 2. **주제 자리에만 나타난 노드는 주제다.** 작품이 P921 로
        #    가리켰다는 것 말고는 아무 관계도 연대도 없는 노드에는 클래스
        #    계층을 믿지 않는다 — 사건 계층이 그만큼 허술하다. '플롯 장치'·
        #    '식사장애'·'유무죄인정'이 전부 사건(Q1190554)에 닿는다(실측).
        #    깊이로 자르는 것도 안 된다: 진짜 사건인 광주 학생 항일 운동이
        #    5단계, 쓰레기인 바디 스왑도 5단계다.
        #
        #    실측으로 이 자리의 노드 71개가 하나도 빠짐없이 주제어였다.
        #    되돌릴 수 있는 판정이기도 하다 — 그 노드가 나중에 연대나 다른
        #    엣지를 얻으면 이 규칙은 더는 걸리지 않는다.
        if q in subject_only:
            verdict[q] = "concept"
            continue

        # 3. **그래프가 이미 사건으로 쓰고 있으면 사건이다.** 참여자가
        #    붙어 있거나 발생 장소·시기를 갖고 있다는 뜻이다. Wikidata 가
        #    그것을 부류로 표시해 두었더라도 이쪽이 무겁다 — 실측으로
        #    신유박해(참여 28건)와 제2차 세계 대전이 P279 를 갖고 있어
        #    이 관문이 없을 때 개념으로 넘어갔다.
        if q in event_role:
            verdict[q] = "event"
            continue

        if mine & set(NOT_AN_ENTITY):
            # 4. 동음이의어·목록 문서. 개념이 아니라 노드로 있으면 안 되는
            #    것이므로 옮기지 않고 사람에게 넘긴다.
            held.add(q)
            continue

        # 5. 상위 부류를 가진 것은 부류다 — **단, 시점이 없을 때만.**
        #    개별 사건은 상위 부류를 갖지 않는다는 것이 원래 근거인데,
        #    한국사 항목에는 '신유박해'처럼 부류이면서 개별 사건인 것이
        #    섞여 있다. 그것들은 P580/P585 를 갖고 있고, 진짜 부류
        #    ('자살'·'전쟁'·'살인'·'조직범죄')는 하나도 갖고 있지 않다(실측).
        if q in subclass:
            if q in dated:
                verdict[q] = "event"
            else:
                # 시점도 없고 주제 자리도 아니다. '정미의병'이 여기 온다 —
                # Wikidata 가 클래스도 시점도 주지 않아 '보복'과 구별되지
                # 않는다. 짐작으로 옮기면 진짜 사건을 잃는다.
                held.add(q)
            continue

        if not mine:
            # 6. 클래스가 아예 없다. 물어봤지만 아무 말도 없는 것이라
            #    '아니다'라고 읽으면 안 된다. (실측: 임오화변, 원격현장감)
            held.add(q)
            continue
        if class_failed:
            # 7. 계층을 다 확인하지 못했다. 사건이 아니라고 말할 수 없다.
            held.add(q)
            continue

        # 8. 사건 계층에 닿으면 사건이다.
        hit = {ROOTS[root] for root, got in reach.items() if mine & got}
        if len(hit) == 1:
            verdict[q] = hit.pop()
            continue
        # 9. 마지막으로 매핑표를 본다. 여기까지 왔다는 것은 사건도 주제도
        #    아니라는 뜻이라, 표가 말하는 타입을 받아들일 만하다. 둘로
        #    갈리면 고르지 않는다 — 후보가 둘이면 잇지 않는다는 규칙이다.
        mapped = {WD_CLASS_TO_TYPE[c] for c in mine if c in WD_CLASS_TO_TYPE}
        if len(mapped) == 1:
            verdict[q] = mapped.pop()
            continue
        held.add(q)

    return verdict, held


def _subject_only(store: GraphStore) -> set[str]:
    """작품이 주제로 가리킨 것 말고는 **사실층에 닿지 않는** 노드들 (QID).

    연대도 보는 이유: 사건이라면 Wikidata 가 대개 날짜를 함께 준다.
    날짜가 있는데 관계만 없는 노드는 아직 안 캔 사건일 수 있다.

    주제끼리는 서로 이어져 있어도 주제다 — 실측으로 '성 도덕'과 '인간의
    성'이 part_of 로, '상실'과 '상실감'이 related_to 로 묶여 있었다. 그
    엣지 하나 때문에 둘 다 사건으로 남으면 규칙이 무의미해진다. 그래서
    '엣지가 없다'가 아니라 **'사실층에 닿지 않는다'**로 잰다. 닿는 것이
    하나라도 있으면 빠지고, 빠진 이웃에 기대던 노드도 따라 빠진다
    (실측: '이춘재 연쇄 살인 사건'은 대한민국과 이어져 있어 남는다)."""
    cands = {
        r["id"]
        for r in store.conn.execute(
            "SELECT n.id FROM nodes n WHERE n.type IN ('event','concept') AND n.source='wd' "
            "AND n.start_date IS NULL AND n.end_date IS NULL "
            "AND EXISTS (SELECT 1 FROM edges e WHERE e.dst = n.id "
            "            AND e.type IN ('depicts','about'))"
        )
    }
    links: dict[str, set[str]] = {c: set() for c in cands}
    for r in store.conn.execute(
        "SELECT src, dst FROM edges WHERE type NOT IN ('depicts','about')"
    ):
        for near, far in ((r["src"], r["dst"]), (r["dst"], r["src"])):
            if near in links:
                links[near].add(far)

    while True:
        out = {c for c in cands if links[c] - cands}
        if not out:
            break
        cands -= out
    return {c.split(":", 1)[1] for c in cands}


def plan_reclassify(store: GraphStore, fetcher=None, limit: int | None = None) -> Plan:
    """`event` 로 앉아 있는 wd 노드들을 Wikidata 에 물어 다시 가른다."""
    from .http import Fetcher

    fetcher = fetcher or Fetcher(store.path.parent / "cache", min_interval=1.5, timeout=TIMEOUT)

    # 개념도 함께 묻는다. 갈라내기는 한쪽으로만 흐르지 않는다 —
    # 개념으로 떨어뜨려 둔 것이 실은 사건이면 여기서 되돌아와야 한다.
    rows = store.conn.execute(
        "SELECT id, label, type FROM nodes WHERE type IN ('event','concept') "
        "AND source='wd' ORDER BY id"
    ).fetchall()
    if limit:
        rows = rows[:limit]
    plan = Plan(labels={r["id"]: r["label"] for r in rows})
    if not rows:
        return plan

    qids = [r["id"].split(":", 1)[1] for r in rows]
    subject_only = _subject_only(store)

    # 그래프에서 사건 노릇을 하고 있는 노드들. 참여자가 붙어 있거나,
    # 발생 장소·시기를 스스로 말하고 있다.
    event_role = {
        r["id"].split(":", 1)[1]
        for r in store.conn.execute(
            "SELECT n.id FROM nodes n WHERE n.source='wd' AND ("
            "  EXISTS (SELECT 1 FROM edges e WHERE e.dst = n.id AND e.type='participated_in')"
            "  OR EXISTS (SELECT 1 FROM edges e WHERE e.src = n.id "
            "             AND e.type IN ('occurred_at','occurred_during')))"
        )
    }
    log.info("사건·개념 노드 %d개의 클래스 조회 중...", len(qids))
    failures: list[str] = []
    verdict, held = _classify(fetcher, qids, subject_only, event_role, failures)
    plan.failed_batches = len(failures)

    current = {r["id"]: r["type"] for r in rows}
    for q in qids:
        node_id = f"wd:{q}"
        if q in held or q not in verdict:
            plan.held.append((node_id, plan.labels[node_id]))
        elif verdict[q] != current[node_id]:
            plan.changes[node_id] = (current[node_id], verdict[q])

    return plan


def apply_plan(store: GraphStore, plan: Plan) -> dict[str, int]:
    """계획을 적용한다. 타입을 바꾸고, 그 때문에 어긋난 엣지를 바로잡는다.

    개념으로 옮긴 노드로 들어오던 `depicts` 는 `about` 이 된다. 엣지를
    그대로 두면 스키마가 곧바로 어긋나고, 지우면 작품과 주제의 연결을
    잃는다 — 옮기는 것이 맞다."""
    if not plan.changes:
        return {"nodes": 0, "depicts_to_about": 0, "invalid_edges": 0}

    conn = store.conn
    conn.executemany(
        "UPDATE nodes SET type = ?, updated_at = datetime('now') WHERE id = ?",
        [(after, node_id) for node_id, (_, after) in plan.changes.items()],
    )

    def _retype_edges(node_ids: list[str], frm: str, to: str) -> int:
        moved = 0
        for i in range(0, len(node_ids), 500):
            batch = node_ids[i : i + 500]
            marks = ",".join("?" * len(batch))
            # 같은 (src,dst,source) 의 반대쪽 엣지가 이미 있으면 PK 가
            # 부딪친다. OR REPLACE 로 하나로 합친다.
            cur = conn.execute(
                f"UPDATE OR REPLACE edges SET type=? WHERE type=? AND dst IN ({marks})",
                (to, frm, *batch),
            )
            moved += cur.rowcount
        return moved

    # 개념이 된 노드로 들어오던 depicts 는 about 이 된다. 엣지를 그대로 두면
    # 스키마가 어긋나고, 지우면 작품과 주제의 연결을 잃는다 — 옮기는 것이 맞다.
    to_about = _retype_edges(plan.by_target("concept"), "depicts", "about")
    # 되돌아오는 쪽도 같다. 개념인 줄 알았던 것이 사건이면 about 은 depicts 다.
    to_depicts = _retype_edges(plan.by_target("event"), "about", "depicts")

    conn.commit()
    return {
        "nodes": len(plan.changes),
        "depicts_to_about": to_about,
        "about_to_depicts": to_depicts,
        "invalid_edges": len(invalid_edges(store)),
    }


def invalid_edges(store: GraphStore) -> list[tuple[str, str, str, str, str]]:
    """스키마에 어긋난 엣지 전수 조사 — (src, dst, 엣지, 출발타입, 도착타입).

    재분류는 노드 타입을 바꾸므로 멀쩡하던 엣지가 어긋날 수 있다.
    조용히 두면 화면이 그것을 그대로 그린다."""
    from .ontology import EDGE_TYPES

    out = []
    for r in store.conn.execute(
        "SELECT e.src, e.dst, e.type, s.type AS st, d.type AS dt FROM edges e "
        "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst"
    ):
        spec = EDGE_TYPES.get(r["type"])
        if spec is None:
            continue
        _, allowed_src, allowed_dst = spec
        if r["st"] not in allowed_src or r["dt"] not in allowed_dst:
            out.append((r["src"], r["dst"], r["type"], r["st"], r["dt"]))
    return out


def depicts_report(store: GraphStore) -> dict[str, object]:
    """판정용 지표 — `depicts` 가 무엇을 가리키고 있나.

    작품 수나 엣지 총계로는 이 오염이 보이지 않는다. **대상 노드의 타입과
    라벨 분포**가 지표다."""
    by_type = {
        r["t"]: r["n"]
        for r in store.conn.execute(
            "SELECT d.type AS t, COUNT(*) AS n FROM edges e JOIN nodes d ON d.id = e.dst "
            "WHERE e.type='depicts' GROUP BY 1 ORDER BY 2 DESC"
        )
    }
    top = [
        (r["label"], r["t"], r["n"])
        for r in store.conn.execute(
            "SELECT d.label, d.type AS t, COUNT(*) AS n FROM edges e JOIN nodes d ON d.id = e.dst "
            "WHERE e.type='depicts' GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15"
        )
    ]
    return {
        "total": sum(by_type.values()),
        "by_type": by_type,
        "top": top,
        "about": store.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE type='about'"
        ).fetchone()[0],
    }
