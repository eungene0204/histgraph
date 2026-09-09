"""무게(重) — 이 그래프에서 무엇이 중심인가.

지금까지 그 자리를 **연결 차수**가 맡고 있었다. 차수는 세기 쉽고 거짓말을
하지 않지만, 이 그래프에서 차수는 역사가 아니라 **문서의 길이**다. 위키백과
문서가 길면 자녀·배우자·출생지·사망지·연도가 줄줄이 딸려 오고, 짧으면 아무것도
없다. 조선 노드의 차수 710 은 조선이 중요해서가 아니라 조선에 속한 것이
많아서다 (2026-09-06 지적: 명성황후를 폈더니 화면이 조선의 그래프가 됐다).

## 무엇을 재기로 했나 — 여섯 측도를 실측하고 고른 것

같은 그래프(노드 12,106 · 엣지 32,270)에 여섯 가지를 다 돌려 보고, **연대를
아는 사건 564건의 시대 분포**와 견줬다. 어떤 측도가 상위 100건을 한 시대에
몰아넣는가가 판정 기준이다 — 몰아넣는 측도는 중요도가 아니라 **자료의 밀도**를
재고 있는 것이다 (실제 분포: 고려 14% · 조선 38% · 대한제국~일제 16% ·
광복 이후 31%).

| 측도 | 고려 | 조선 | 상위에 선 것 | 판정 |
|---|---|---|---|---|
| 차수 | 8% | 62% | 조선·국회의원·서울특별시 | 문서 길이를 잰다 |
| 조화 중심성 (Boldi–Vigna 2014) | 1% | 93% | 조선 언저리 인물 | 큰 덩어리에 붙어 있으면 이긴다 |
| k-코어 (Kitsak 2010) | — | — | 임진왜란 해전 22건과 그 장수들 | 인포박스 틀이 만든 클리크 |
| 고유벡터 | — | — | 조선 0.61 · 다음 0.15 | 허브 하나에 몰린다 |
| 비되돌이 (Martin–Zhang–Newman 2014) | 0% | 98% | 임진왜란 해전 | 허브 쏠림은 고쳤으나 클리크에 몰린다 |
| **타입 가중 PageRank (아래)** | **13%** | **56%** | 임진왜란·병자호란·3·1운동·무신정변 | **쓴다** |

조화 중심성은 흩어진 그래프에서도 정의된다는 점(공리적으로 가장 낫다는 것이
Boldi–Vigna 의 결론이다)이 우리 조건에 맞아 기대가 컸는데, 실제로는 가장
심하게 몰렸다 — 이 그래프는 조선 덩어리가 워낙 크고 촘촘해서 "많은 것에
가깝다"가 곧 "조선에 붙어 있다"가 된다. k-코어와 고유벡터 계열이 임진왜란
해전에 몰린 것은 **자료의 성질**이다: 위키백과 해전 인포박스가 같은 장수 열둘을
스물두 번 되풀이해 적어 두어 거의 완전그래프가 하나 생겼다. 밀집 구조를 상으로
주는 측도는 전부 거기에 빨려 든다.

PageRank 가 남은 이유는 **텔레포트**다. 무작위 보행자가 이따금 아무 데서나 다시
시작하므로 큰 덩어리가 그래프 전체의 점수를 빨아들이지 못하고, 변두리 무리도
제 안에서 제 몫을 갖는다. 고려의 무신정변·위화도 회군이 상위에 서는 측도는
이것뿐이었다.

## 무게가 일하는 자리는 **나눌 때**뿐이다

이 점을 모르면 무게 표를 잘못 짠다. 무향 그래프의 PageRank 에서 노드는 제 몫을
이웃에게 무게에 **비례해** 나눠 준다 — 나가는 몫을 제 무게의 합으로 나누므로,
한 노드의 엣지가 전부 같은 타입이면 무게를 어떻게 정하든 결과가 같다. 무게가
갈리는 자리는 **한 노드가 여러 종류의 관계를 함께 가질 때**다: 사건 노드는
연도(0.15)보다 참여자(1.0)에게 훨씬 많이 보내고, 연도 노드는 걸린 수백 개에
똑같이 나눈다. 그래서 연도로만 이어진 노드는 아무리 많이 이어져도 무거워지지
않는다.

무게를 씌운 값은 안 씌운 값보다 나았다 (시대 왜곡 0.21 → 0.19). 크지 않지만
방향이 맞다 — 태종·대한제국 고종이 올라오고 문서만 긴 노드가 내려갔다.

**같은 이유로 버린 것이 하나 더 있다.** 무게를 '이 엣지를 받아들일 확률'로 읽어
가벼운 관계에서 보행자를 새어 나가게 하면(엣지별 감쇠) 무게가 나눌 때 말고도
일하게 된다. 돌려 보니 자리 25개를 혼자 지낸 김명준이 1위가 됐다 — 그의 엣지는
전부 `held_position`(1.0)이라 아무것도 새지 않고, 임금들은 `dated_to` 로 샌다.
**적게 새는 것이 중요한 것은 아니다.**

## 무게는 온톨로지가 정한다

두 번째 손질은 **모든 엣지가 같은 말을 하지 않는다**는 것이다. `dated_to` 는
"1592년에 있었다"이고 `participated_in` 은 "이 사람이 이 일을 했다"이다.
앞엣것은 문서가 길면 저절로 늘고 뒤엣것은 사람이 적어야 는다. 그래서 무게를
갈랐다 (`EDGE_WEIGHT`).

무게를 **자료에서 뽑는 길**(흔한 관계일수록 가볍게 — IDF)도 재 봤는데 버렸다.
그러면 `dated_to` 가 0 이 되는 것까지는 맞지만 `participated_in`·`caused` 도
바닥으로 내려가고 `about`(1건)·`adapted_from`(5건)이 가장 무거워진다. **드문
것이 중요한 것은 아니다.** 무게는 그 관계가 무엇을 주장하는가로 정한다.

## 재지 않는 것

**자르지 않는다.** 이 값은 차례를 정할 뿐이다 (CLAUDE.md §1-3: 연표에 수를
세는 문턱을 다시 놓지 않는다). 그리고 **크기로 말하지 않는다** — 노드 반지름은
지금처럼 차수다 (`design.md`: 크기로 확신도·타입·중요도를 말하지 않는다).
중심성은 화면에 숫자로도 뜨지 않는다. 무엇을 먼저 보여줄지에만 쓴다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# 엣지가 무엇을 주장하는가로 가른 무게. 네 무리다.
#
#   1.0  행위·주장 — 사람이 문서를 읽고 적어야 생기는 것
#   0.6  다룸·상위 — 작품이 무엇을 다루는가, 무엇의 일부인가
#   0.5  관련      — 뜻이 아직 안 갈린 것 (`untangle` 이 줄이는 중)
#   0.4  곳        — 어디서 일어났나
#   0.25 좌표      — 어디서 나고 죽었나, 어디에 있나
#   0.15 때·족보   — 문서가 길면 저절로 늘어나는 것
#
# `dated_to` 가 가장 가벼운 이유: 10,555건으로 전체 엣지의 3분의 1인데
# 그중 무엇도 "이 노드가 중요하다"고 말하지 않는다. 그래도 0 은 아니다 —
# 0 으로 두면 연도로만 이어진 노드 2,082개가 한 점수에 뭉쳐 차례를 잃는다.
EDGE_WEIGHT: dict[str, float] = {
    "participated_in": 1.0,
    "caused": 1.0,
    "held_position": 1.0,
    "member_of": 1.0,
    "taught": 1.0,
    "created": 1.0,
    "depicts": 0.6,
    "about": 0.6,
    "part_of": 0.6,
    "adapted_from": 0.6,
    "related_to": 0.5,
    "occurred_at": 0.4,
    "set_in": 0.4,
    "located_in": 0.25,
    "born_in": 0.25,
    "died_in": 0.25,
    "from_period": 0.3,
    "occurred_during": 0.3,
    "dated_to": 0.15,
    "child_of": 0.15,
    "spouse_of": 0.15,
}
# 표에 없는 타입이 들어오면 이 값. 새 엣지 타입이 무게 없이 들어와도
# 조용히 0 이 되지 않게 한다 (테스트가 표에 없는 타입을 잡는다).
DEFAULT_WEIGHT = 0.5

# **잎은 증언하지 못한다.** 이웃이 나 하나뿐인 노드는 나를 설명하려고 생긴
# 것이지 나를 인정해 주는 것이 아니다. 그런데 무향 그래프의 PageRank 에서
# 잎은 **거울**이다 — 갈 데가 하나뿐이라 받은 몫을 고스란히 되돌려 준다.
# 잎을 많이 단 노드는 그래서 저 혼자 무거워진다. 실측: 김명준(1870년)이
# 인물 4위로 문 앞에 섰다. 자리 25개가 '삼천리 필진'·'만몽박람회 상담역'처럼
# 그 사람 말고는 아무도 앉은 적 없는 이력 줄이었다 (`role` 노드 285개 중
# 202개가 한 사람짜리다 — 자료 쪽에서 따로 걷어낼 것).
#
# 그래서 **잎이 돌려주는 몫만** 줄이고 그 나머지는 그래프 전체에 고르게
# 흘린다 (엣지 무게를 줄이는 것으로는 안 된다 — 나가는 몫은 제 무게의 합으로
# 나눠지므로, 갈 데가 하나뿐인 잎에게는 무게를 아무리 줄여도 100% 가 그대로
# 돌아간다). 잎이 **받는** 몫은 그대로다 — 잎에도 제 점수가 있어야 한다.
#
# 값은 재서 골랐다. 4분의 1까지 조이면 김명준은 153위로 내려가지만 시대
# 왜곡이 0.19 에서 0.21 로 나빠진다 — 자료가 얇은 시대의 사건이 잎을 많이
# 달고 있어서 같이 맞는다. 0.75 면 김명준은 문 앞에서 물러나고(4위 → 26위)
# 시대 분포는 그대로다.
#
# `_anchors` 가 "`ex:` 이고 차수 < 2 인 추출 고아는 뼈대가 못 된다"고 적어 둔
# 것과 같은 규칙이다.
LEAF_RETURN = 0.75

# 텔레포트 확률 0.15. 이 값이 곧 **변두리를 지키는 폭**이다 — 1 에 가까울수록
# 큰 덩어리가 다 먹고, 0.5·0.7 로 낮춰도 시대 분포는 거의 그대로였다(왜곡
# 0.18~0.19). 널리 쓰는 0.85 를 그대로 둔다.
DAMPING = 0.85
MAX_ITERS = 200
TOLERANCE = 1e-12


@dataclass
class Result:
    score: dict[str, float] = field(default_factory=dict)
    iters: int = 0
    converged: bool = False
    nodes: int = 0
    edges: int = 0
    #: 무게 표에 없어 기본값으로 잰 엣지 타입
    unweighted: dict[str, int] = field(default_factory=dict)


def _graph(conn: sqlite3.Connection) -> tuple[list[str], list[dict[int, float]], dict[str, int]]:
    """무게 붙은 무향 그래프. 같은 두 노드를 여러 소스가 이었으면 **가장 무거운
    관계 하나로 센다** — 위키백과와 국편이 같은 참여를 둘 다 적었다고 그 사람이
    두 배 중요해지지는 않는다."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM nodes ORDER BY id")]
    idx = {nid: i for i, nid in enumerate(ids)}
    adj: list[dict[int, float]] = [{} for _ in ids]
    missing: dict[str, int] = {}
    for row in conn.execute("SELECT src, dst, type FROM edges"):
        a, b = idx.get(row["src"]), idx.get(row["dst"])
        if a is None or b is None or a == b:
            continue
        w = EDGE_WEIGHT.get(row["type"])
        if w is None:
            missing[row["type"]] = missing.get(row["type"], 0) + 1
            w = DEFAULT_WEIGHT
        if w > adj[a].get(b, 0.0):
            adj[a][b] = w
            adj[b][a] = w
    return ids, adj, missing


def compute(conn: sqlite3.Connection, *, damping: float = DAMPING) -> Result:
    """타입 가중 PageRank. 12,106 노드에 몇 초 걸린다."""
    ids, adj, missing = _graph(conn)
    n = len(ids)
    if n == 0:
        return Result()
    out = [sum(row.values()) for row in adj]
    # 잎이 내보내는 몫. 나머지는 아래에서 그래프 전체에 고르게 흘린다.
    emit = [LEAF_RETURN if len(row) == 1 else 1.0 for row in adj]
    base = (1.0 - damping) / n
    rank = [1.0 / n] * n
    iters = 0
    converged = False
    for iters in range(1, MAX_ITERS + 1):
        nxt = [base] * n
        loose = 0.0
        for v in range(n):
            if out[v] <= 0.0:
                # 엣지가 없는 노드가 쥔 몫은 **모두에게 고르게 흘린다.**
                # 흘리지 않으면 반복마다 점수 총합이 새어 나간다.
                loose += rank[v]
                continue
            loose += rank[v] * (1.0 - emit[v])
            share = damping * rank[v] * emit[v] / out[v]
            for u, w in adj[v].items():
                nxt[u] += share * w
        spill = damping * loose / n
        nxt = [x + spill for x in nxt]
        delta = sum(abs(nxt[i] - rank[i]) for i in range(n))
        rank = nxt
        if delta < TOLERANCE * n:
            converged = True
            break
    return Result(
        score={ids[i]: rank[i] for i in range(n)},
        iters=iters,
        converged=converged,
        nodes=n,
        edges=sum(len(row) for row in adj) // 2,
        unweighted=missing,
    )


def save(conn: sqlite3.Connection, result: Result) -> int:
    """`centrality` 표에 적는다. **편집 계층이 아니다** — 세어서 나온 값이라
    언제든 다시 만들 수 있고, 사람이 고칠 것도 아니다."""
    order = sorted(result.score, key=lambda nid: (-result.score[nid], nid))
    conn.execute("DELETE FROM centrality")
    conn.executemany(
        "INSERT INTO centrality (node_id, score, rank) VALUES (?,?,?)",
        [(nid, result.score[nid], i) for i, nid in enumerate(order, 1)],
    )
    conn.commit()
    return len(order)


def load(conn: sqlite3.Connection) -> dict[str, float]:
    if not present(conn):
        return {}
    return {r["node_id"]: r["score"] for r in conn.execute("SELECT node_id, score FROM centrality")}


def present(conn: sqlite3.Connection) -> bool:
    """표가 있고 비어 있지 않은가. 배포 DB 는 읽기 전용으로 열려 스키마가
    돌지 않으므로, 묻는 쪽이 없을 때를 견뎌야 한다 — 없으면 차수로 물러난다."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='centrality'"
    ).fetchone()
    if row is None:
        return False
    return conn.execute("SELECT 1 FROM centrality LIMIT 1").fetchone() is not None


def top(conn: sqlite3.Connection, limit: int = 30, node_type: str | None = None) -> list[sqlite3.Row]:
    where = "WHERE n.type = ?" if node_type else ""
    args: tuple = (node_type, limit) if node_type else (limit,)
    return list(conn.execute(
        f"""SELECT n.id, n.type, n.label, n.start_date, c.score, c.rank,
                   (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS degree
              FROM centrality c JOIN nodes n ON n.id = c.node_id
              {where}
          ORDER BY c.score DESC
             LIMIT ?""",
        args,
    ))
