"""파이프라인 스모크 테스트 (네트워크 불필요).

  uv run tests/test_pipeline.py

과거에 실제로 파이프라인을 망가뜨린 버그들을 회귀 테스트로 고정한다.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.http import redact  # noqa: E402
from histgraph.ontology import (  # noqa: E402
    EDGE_TYPES,
    NODE_TYPES,
    Edge,
    Node,
    OntologyError,
    validate_edge_endpoints,
)
from histgraph.sources import heritage, wikidata  # noqa: E402
from histgraph.store import GraphStore  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name} {detail}")


print("[온톨로지]")
check("엣지 타입의 양끝이 모두 유효한 노드 타입", all(
    set(src) <= set(NODE_TYPES) and set(dst) <= set(NODE_TYPES)
    for _, src, dst in EDGE_TYPES.values()
))

try:
    Node(id="bad-id-without-colon", type="person", label="x", source="t")
    check("접두사 없는 id 거부", False)
except OntologyError:
    check("접두사 없는 id 거부", True)

try:
    Edge(src="a:1", dst="a:2", type="존재하지않는엣지", source="t")
    check("알 수 없는 엣지 타입 거부", False)
except OntologyError:
    check("알 수 없는 엣지 타입 거부", True)

nodes = {
    "a:1": Node(id="a:1", type="person", label="인물", source="t"),
    "a:2": Node(id="a:2", type="event", label="사건", source="t"),
}
check(
    "타입 불일치 엣지를 검출",
    validate_edge_endpoints(Edge(src="a:1", dst="a:2", type="member_of", source="t"), nodes)
    is not None,
)
check(
    "정상 엣지는 통과",
    validate_edge_endpoints(
        Edge(src="a:1", dst="a:2", type="participated_in", source="t"), nodes
    )
    is None,
)

print("\n[회귀: _qid 는 URI 전용]")
# 노드 id('wd:Q1')에 _qid 를 쓰면 조회가 전부 빗나가 모든 엣지가
# related_to 로 강등됐다. URI 만 처리한다는 계약을 고정한다.
check("URI 에서 QID 추출", wikidata._qid("http://www.wikidata.org/entity/Q37682") == "Q37682")
check(
    "노드 id 는 _qid 대상이 아님 (원문 반환)",
    wikidata._qid("wd:Q37682") == "wd:Q37682",
)

print("\n[회귀: 인증키 마스킹]")
leaked = "https://api.example.com/x?serviceKey=SECRET123&pageNo=1"
check("serviceKey 마스킹", "SECRET123" not in redact(leaked), redact(leaked))
check("다른 파라미터는 보존", "pageNo=1" in redact(leaked))

print("\n[회귀: 국가유산청 날짜/좌표 파싱]")
check("8자리 날짜 변환", heritage._parse_date("19621220") == "1962-12-20")
check("잘못된 날짜는 None", heritage._parse_date("1962") is None)
check("빈 좌표는 None", heritage._as_float("") is None)
check("좌표 파싱", heritage._as_float("126.97") == 126.97)

print("\n[저장소]")
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "t.sqlite")
    n = [
        Node(id="wd:Q1", type="person", label="세종", source="wd", aliases=["世宗"]),
        Node(id="wd:Q2", type="event", label="훈민정음 반포", source="wd"),
    ]
    e = [Edge(src="wd:Q1", dst="wd:Q2", type="participated_in", source="wd")]
    store.upsert_nodes(n)
    store.upsert_edges(e)
    first = store.stats()

    # 멱등성: 같은 수집을 두 번 돌려도 늘지 않아야 한다
    store.upsert_nodes(n)
    store.upsert_edges(e)
    second = store.stats()
    check("노드 upsert 멱등", first["nodes_total"] == second["nodes_total"] == 2)
    check("엣지 upsert 멱등", first["edges_total"] == second["edges_total"] == 1)

    # 같은 사실을 다른 소스가 말하면 별도 행으로 남아 교차검증이 가능해야 한다
    store.upsert_edges([Edge(src="wd:Q1", dst="wd:Q2", type="participated_in", source="khs")])
    check("소스가 다르면 별도 엣지", store.stats()["edges_total"] == 2)

    sub = store.neighbors("wd:Q1", depth=1)
    check("서브그래프 노드", len(sub["nodes"]) == 2)
    check("댕글링 엣지 0", store.stats()["dangling_edges"] == 0)

    store.upsert_edges([Edge(src="wd:Q1", dst="wd:Q999", type="participated_in", source="wd")])
    check("댕글링 엣지 집계", store.stats()["dangling_edges"] == 1)
    store.close()

print("\n[스포츠 필터]")
from histgraph.filters import is_sports  # noqa: E402

# 이 목록은 실제로 그래프를 오염시킨 항목들이다 (participated_in 의 90.5%)
for label in [
    "2008년 하계 올림픽", "2010년 아시안 게임", "2012년 하계 패럴림픽",
    "2019년 세계 군인 체육 대회", "2017년 월드 베이스볼 클래식",
    "2003 Asian Winter Games", "1987 Konica Cup – women's doubles",
    "figure skating at the 2003 Asian Winter Games",
]:
    check(f"스포츠로 판정: {label[:34]}", is_sports(label))

# 역사 사건이 스포츠로 오분류되면 그래프에서 사라진다 — 오탐이 더 위험하다
for label in [
    "국채보상운동", "제1차 왕자의 난", "계유정난", "임진왜란", "동학농민운동",
    "3·1 운동", "갑오개혁", "병자호란", "전조선 제정당사회단체 대표자 연석회의",
]:
    check(f"역사로 판정: {label[:34]}", not is_sports(label))

check("클래스로도 판정", is_sports("모호한 이름", "Q13406554"))

print("\n[엔티티 해소]")
from histgraph.resolve import (  # noqa: E402
    PERIOD_TO_POLITY,
    link_periods,
    link_places,
    normalize_period,
    normalize_place,
)

check("시도 정규화", normalize_place("서울특별시") == "서울")
check("시군구 정규화", normalize_place("경주시") == "경주")
check("도 정규화", normalize_place("경상북도") == "경상북")
check("시대 정규화", normalize_period("조선시대") == "조선")
check("시대 정규화(통일신라)", normalize_period("통일신라시대") == "통일신라")

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "r.sqlite")
    store.upsert_nodes([
        Node(id="kr:period:조선시대", type="period", label="조선시대", source="khs"),
        Node(id="wd:Q28179", type="org", label="조선", source="wd"),
        Node(id="kr:place:서울특별시:중구", type="place", label="서울특별시 중구",
             source="khs", props={"sido": "서울특별시", "sigungu": "중구"}),
        Node(id="wd:Q8684", type="place", label="서울특별시", source="wd"),
    ])
    check("시대 연결", link_periods(store) == 1)
    check("장소 연결", link_places(store) == 1)
    # 접합점이 생겼는지 — 이게 0이면 두 그래프는 여전히 분리돼 있다
    check(
        "소스 간 링크 생성",
        store.conn.execute(
            """SELECT COUNT(*) FROM same_as s
               JOIN nodes a ON a.id=s.a JOIN nodes b ON b.id=s.b
               WHERE a.source != b.source"""
        ).fetchone()[0] == 2,
    )
    store.close()

check("시대 매핑표가 유효한 QID 형식", all(
    q.startswith("Q") and q[1:].isdigit() for q in PERIOD_TO_POLITY.values()
))

print("\n[회귀: ccceName 은 자유 서술이다]")
# '시대' 접미사만 떼는 정규화로는 실제 데이터의 대부분이 매칭되지 않았다
# (757건 중 9건만 연결됐었다). 왕조명을 라벨 어디서든 찾아야 한다.
from histgraph.resolve import extract_polities  # noqa: E402

check("연호 표기", extract_polities("조선 태조 7년(1398)") == ["조선"])
check("세기 표기", extract_polities("조선시대(18세기말∼19세기초)") == ["조선"])
check("연도 우선 표기", extract_polities("1776년(조선 영조 52년)") == ["조선"])
check("복수 왕조 검출", extract_polities("통일신라시대~조선시대") == ["통일신라", "조선"])
check("통일신라가 신라를 흡수", extract_polities("통일신라시대") == ["통일신라"])
check("왕조 없으면 빈 목록", extract_polities("현종8년(1017)") == [])

print("\n[회귀: 모호한 지명에서 상위 행정구역으로 후퇴]")
# '중구'는 서울·부산·대구에 모두 있다. 모호하다고 포기하면 유물 전체가
# 연결에서 탈락한다 — 시도로 후퇴해야 한다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "a.sqlite")
    store.upsert_nodes([
        Node(id="kr:place:서울:중구", type="place", label="서울 중구", source="khs",
             props={"sido": "서울", "sigungu": "중구"}),
        Node(id="wd:Q50438", type="place", label="중구", source="wd"),
        Node(id="wd:Q50440", type="place", label="중구", source="wd"),
        Node(id="wd:Q50441", type="place", label="중구", source="wd"),
        Node(id="wd:Q8684", type="place", label="서울특별시", source="wd"),
    ])
    check("모호한 시군구 대신 시도로 연결", link_places(store) == 1)
    row = store.conn.execute("SELECT b FROM same_as").fetchone()
    check("서울특별시에 연결됨", row is not None and row["b"] == "wd:Q8684")
    store.close()

print("\n[회귀: 이웃끼리의 관계도 함께 온다]")
# 탐색 중에 모은 엣지는 프론티어에 닿는 것뿐이다. 그것만 돌려주면
# 중심에서 바큇살만 뻗은 그림이 되고, '인조반정과 병자호란이 이어져 있다'
# 같은 것이 화면에서 사라진다 (실측: 조선의 이웃 105개 사이에 25건).
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "i.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q0", type="org", label="조선", source="wd"),
        Node(id="wd:Q1", type="event", label="인조반정", source="wd"),
        Node(id="wd:Q2", type="event", label="병자호란", source="wd"),
        Node(id="wd:Q3", type="person", label="멀리 있는 사람", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:Q1", dst="wd:Q0", type="from_period", source="wd"),
        Edge(src="wd:Q2", dst="wd:Q0", type="from_period", source="wd"),
        # 중심에 닿지 않는, 이웃끼리의 관계
        Edge(src="wd:Q1", dst="wd:Q2", type="related_to", source="extract", confidence=0.9),
        # 서브그래프 밖으로 나가는 엣지는 들어오면 안 된다
        Edge(src="wd:Q3", dst="wd:Q1", type="participated_in", source="wd"),
    ])
    sub = store.neighbors("wd:Q0", depth=1)
    pairs = {(e["src"], e["dst"]) for e in sub["edges"]}
    check("중심에 닿는 엣지", ("wd:Q1", "wd:Q0") in pairs and ("wd:Q2", "wd:Q0") in pairs)
    check("이웃끼리의 엣지도 포함", ("wd:Q1", "wd:Q2") in pairs, str(pairs))
    check("범위 밖 노드로 나가는 엣지는 제외", ("wd:Q3", "wd:Q1") not in pairs)

    # 자기순환은 아무 사실도 말하지 않고 화면에도 그릴 수 없다
    store.conn.execute(
        "INSERT INTO edges (src,dst,type,source,confidence,props)"
        " VALUES ('wd:Q1','wd:Q1','related_to','extract',0.9,'{}')"
    )
    store.conn.commit()
    check("자기순환은 돌려주지 않음",
          all(e["src"] != e["dst"] for e in store.neighbors("wd:Q0")["edges"]))
    store.close()

print("\n[회귀: 두 걸음 예산을 허브가 다 먹지 않는다]")
# 명성황후를 검색했더니 화면이 조선의 그래프가 됐다 (2026-09-06 지적).
# 두 걸음째 새 노드 91개 중 68개가 조선의 이웃이라 조선이 엣지 131개를
# 달고 섰고, 정작 중심인 명성황후는 34개였다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "hub.sqlite")
    nodes = [Node(id="wd:C", type="person", label="중심", source="wd"),
             Node(id="wd:HUB", type="org", label="허브", source="wd")]
    # 중심의 이웃 다섯. 하나는 허브(이웃 200), 넷은 각자 이웃 다섯.
    for i in range(4):
        nodes.append(Node(id=f"wd:N{i}", type="event", label=f"이웃{i}", source="wd"))
        nodes += [Node(id=f"wd:N{i}x{j}", type="event", label=f"이웃{i}의{j}", source="wd")
                  for j in range(5)]
    nodes += [Node(id=f"wd:H{j}", type="event", label=f"허브의{j}", source="wd")
              for j in range(200)]
    store.upsert_nodes(nodes)
    edges = [Edge(src="wd:C", dst="wd:HUB", type="member_of", source="wd")]
    for i in range(4):
        edges.append(Edge(src="wd:C", dst=f"wd:N{i}", type="participated_in", source="wd"))
        edges += [Edge(src=f"wd:N{i}", dst=f"wd:N{i}x{j}", type="related_to", source="wd")
                  for j in range(5)]
    # 허브의 이웃은 저마다 엣지를 더 달아 차수가 높다 — 차수로 자르면 이들이 이긴다
    for j in range(200):
        edges.append(Edge(src="wd:HUB", dst=f"wd:H{j}", type="from_period", source="wd"))
        edges.append(Edge(src=f"wd:H{j}", dst="wd:HUB", type="related_to", source="wd"))
    store.upsert_edges(edges)

    sub = store.neighbors("wd:C", depth=2, max_nodes=25)
    got = {n["id"] for n in sub["nodes"]}
    check("상한에 걸렸다", sub["truncated"])
    check("중심의 이웃은 다섯 다 남는다",
          all(i in got for i in ["wd:HUB", "wd:N0", "wd:N1", "wd:N2", "wd:N3"]))
    mine = sum(1 for i in got if "x" in i)
    hubs = sum(1 for i in got if i.startswith("wd:H") and i != "wd:HUB")
    check("허브가 예산을 다 먹지 않는다", hubs <= 6, f"허브 {hubs} · 이웃의 이웃 {mine}")
    check("이웃의 이웃도 들어온다", mine >= 12, f"허브 {hubs} · 이웃의 이웃 {mine}")

    # 걸음이 하나뿐이면 나눌 상대가 없다 — 예전처럼 차수 순서로 남는다
    one = store.neighbors("wd:HUB", depth=1, max_nodes=20)
    check("한 걸음은 차수 순서 그대로", one["truncated"] and len(one["nodes"]) == 20)
    store.close()

print("\n[회귀: 탐색이 same_as 를 따라간다]")
# same_as 테이블에만 링크가 있고 탐색이 따라가지 않으면 두 소스는
# 실제로는 여전히 끊겨 있다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "b.sqlite")
    store.upsert_nodes([
        Node(id="khs:1", type="heritage", label="유물", source="khs"),
        Node(id="kr:period:조선시대", type="period", label="조선시대", source="khs"),
        Node(id="wd:Q28179", type="org", label="조선", source="wd"),
        Node(id="wd:Q1", type="person", label="어떤 인물", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="khs:1", dst="kr:period:조선시대", type="from_period", source="khs"),
        Edge(src="wd:Q1", dst="wd:Q28179", type="member_of", source="wd"),
    ])
    store.conn.execute(
        "INSERT INTO same_as (a,b,method,score) VALUES ('kr:period:조선시대','wd:Q28179','t',1.0)"
    )
    store.conn.commit()

    reached = {n["id"] for n in store.neighbors("khs:1", depth=3)["nodes"]}
    check("same_as 를 건너 Wikidata 인물에 도달", "wd:Q1" in reached)
    no_follow = {
        n["id"] for n in store.neighbors("khs:1", depth=3, follow_same_as=False)["nodes"]
    }
    check("follow_same_as=False 면 도달 못 함", "wd:Q1" not in no_follow)
    store.close()

print("\n[추출]")
from histgraph.extract import (  # noqa: E402
    CONFIDENCE,
    EXTRACTABLE,
    OUTPUT_SCHEMA,
    to_graph,
)

check("추출 엣지 타입이 모두 온톨로지에 존재", all(t in EDGE_TYPES for t in EXTRACTABLE))
check(
    "스키마 enum 이 EXTRACTABLE 과 일치",
    OUTPUT_SCHEMA["properties"]["relations"]["items"]["properties"]["relation"]["enum"]
    == EXTRACTABLE,
)
check(
    "구조화 출력에 additionalProperties:false 필수",
    OUTPUT_SCHEMA["additionalProperties"] is False
    and OUTPUT_SCHEMA["properties"]["relations"]["items"]["additionalProperties"] is False,
)
check("모든 신뢰도 등급이 1.0 미만", all(v < 1.0 for v in CONFIDENCE.values()))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "e.sqlite")
    store.upsert_nodes([Node(id="wd:Q37682", type="person", label="조선 세종", source="wd")])
    n, e = to_graph(
        [{
            "subject": "조선 세종", "subject_type": "person",
            "relation": "participated_in",
            "object": "훈민정음 반포", "object_type": "event",
            "evidence": "세종은 훈민정음을 반포하였다", "confidence": "certain",
        }],
        "khs:test", store,
    )
    # 실측: 모델이 '기사환국이 기사환국과 관련된다'를 낸다
    _, loop = to_graph(
        [{
            "subject": "어떤 사건", "subject_type": "event", "relation": "related_to",
            "object": "어떤 사건", "object_type": "event",
            "evidence": "어떤 사건은 어떤 사건과 관련이 있다", "confidence": "certain",
        }],
        "khs:test", store,
    )
    check("양끝이 같은 관계는 버린다", loop == [])

    # 실측 회귀: 동명 노드가 둘일 때 엣지 0개짜리에 붙어, 화면에서 정종이
    # 아버지도 형제도 없는 외톨이가 됐다. 연결이 많은 쪽을 골라야 한다.
    store.upsert_nodes([
        Node(id="wd:Q485556", type="person", label="정종", source="wd"),
        Node(id="wd:Q16177061", type="person", label="정종", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:Q485556", dst="wd:Q37682", type="child_of", source="wd"),
    ])
    _, kin = to_graph(
        [{
            "subject": "정종", "subject_type": "person", "relation": "child_of",
            "object": "조선 세종", "object_type": "person",
            "evidence": "정종은 세종의 자녀이다", "confidence": "certain",
        }],
        "khs:test", store,
    )
    check("동명이인 중 연결 많은 쪽을 고른다", kin and kin[0].src == "wd:Q485556",
          str([(x.src, x.dst) for x in kin]))

    check("기존 노드에 연결 (새로 만들지 않음)", e[0].src == "wd:Q37682")
    check("없는 개체는 ex: 접두사로 생성", e[0].dst.startswith("ex:"))
    check("근거 보존", e[0].props["evidence"] == "세종은 훈민정음을 반포하였다")
    check("텍스트 추론은 confidence < 1.0", e[0].confidence == 0.9)
    store.close()

print("\n[문서 선별 — 서사 점수]")
# 길이만 보고 고르면 가장 긴 문서가 '반곽 24.5×15.8cm' 같은 서지 기술이라
# API 비용이 헛돈다. 실측: 국가유산청 산문 2,903건 중 인물·사건이 함께
# 나오는 글은 634건(22%)뿐.
from histgraph.extract import load_documents, narrative_score  # noqa: E402

catalog = "상하단변 좌우쌍변에 반곽 24.5×15.8cm, 무계이며 행자수는 17행 34자, 판심에는 권차 장차 순으로 " * 3
narrative = (
    "정몽주(1337~1392)는 고려 말기 문신이자 학자로 본관은 영일, 호는 포은이다. "
    "1360년 문과에 장원급제한 뒤 예조정랑과 대사성을 지냈다. 이성계의 위화도 회군 "
    "이후 조준 등 개국 세력과 대립하다 선죽교에서 피살되었다. 조선 건국 후 그의 "
    "학문은 사림에 계승되어 문묘에 배향되었다."
)
check("서사가 서지 기술보다 높은 점수", narrative_score(narrative) > narrative_score(catalog))
check("서지 기술은 감점", narrative_score(catalog) < 1.0)
check("인물+사건 동시 등장은 2.0 이상", narrative_score(narrative) >= 2.0)

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "d.sqlite")
    store.upsert_nodes([
        Node(id="a:1", type="heritage", label="서지", source="t", description=catalog),
        Node(id="a:2", type="heritage", label="서사", source="t", description=narrative),
    ])
    docs = load_documents(store, min_score=1.0)
    check("서지 문서는 선별에서 제외", [d.node_id for d in docs] == ["a:2"])
    check("min_score=2.0 도 서사만 통과", len(load_documents(store, min_score=2.0)) == 1)
    store.close()

# 조각당 수 분이 드는 로컬 추출에서는 **대상을 좁히는 것이 유일한 비용 조절**
# 이다. 이미 참여자 65명이 붙은 병자호란을 다시 읽어도 나올 것이 없다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "pick.sqlite")
    store.upsert_nodes([
        Node(id="ev:full", type="event", label="채워진 사건", source="t",
             description=narrative),
        Node(id="ev:empty", type="event", label="빈 사건", source="t",
             description=narrative),
        Node(id="ev:stub", type="event", label="토막 사건", source="t",
             description=narrative[:120]),
        Node(id="p:1", type="person", label="갑돌", source="t"),
        Node(id="p:2", type="person", label="을순", source="t"),
    ])
    store.upsert_edges([
        Edge(src="p:1", dst="ev:full", type="participated_in", source="t"),
        Edge(src="p:2", dst="ev:full", type="participated_in", source="t"),
        Edge(src="p:1", dst="ev:empty", type="participated_in", source="t"),
    ])
    picked = lambda **kw: {d.node_id for d in load_documents(store, min_score=1.0, **kw)}
    check("참여자 상한 없으면 셋 다", picked() == {"ev:full", "ev:empty", "ev:stub"})
    check("참여자 1명 초과는 제외", picked(max_participants=1) == {"ev:empty", "ev:stub"})
    check("참여자 0명만 남기기", picked(max_participants=0) == {"ev:stub"})
    check("짧은 본문 제외", picked(min_chars=150) == {"ev:full", "ev:empty"})
    check("둘을 같이 걸기",
          picked(max_participants=1, min_chars=150) == {"ev:empty"})

    # **대상을 좁혀도 가제티어는 그대로다.** 좁히면서 아는 개체 목록까지
    # 좁히면 인물 이름이 전부 ex: 고아가 된다 (`--scope` 는 둘 다 좁힌다).
    from histgraph.extract import build_gazetteer  # noqa: E402

    check("가제티어는 대상 축소와 무관",
          set(build_gazetteer(store)["person"]) == {"갑돌", "을순"})
    store.close()

print("\n[족보 목록 제거]")
# 실측(안방준): '증손부 : 창녕조씨' 꼴 목록을 그대로 주면 모델이 방계
# 인물을 본인의 배우자로 붙이고, 같은 관계를 4번 반복하는 루프에 빠진다.
from histgraph.extract import strip_kinship_lists  # noqa: E402

genealogy = (
    "안방준은 임진왜란 때 호남의병으로 활동하였다.\n"
    "생부 : 안중관(安重寬, 1524~1605)\n"
    "증손부 : 창녕조씨(昌寧曺氏) - 조이태(曺爾泰)의 따님.\n"
    "손부(후실) : 진주하씨(晉州河氏)\n"
    "사위 : 정창서(鄭昌瑞) - 본관은 서산(瑞山)\n"
    "아버지는 첨지중추부사 안중관이며, 처는 경주 정씨이다.\n"
    "1613년(광해군 5, 41세) 조헌의 《항의신편》을 편찬함.\n"
)
stripped = strip_kinship_lists(genealogy)
check("족보 목록 행 제거", "증손부" not in stripped and "손부(후실)" not in stripped)
check("서사 문단은 보존", "임진왜란 때 호남의병" in stripped)
check("가족을 말하는 서사 문장도 보존", "아버지는 첨지중추부사" in stripped)
check("연도로 시작하는 연보 행은 보존", "《항의신편》을 편찬함" in stripped)

# 열거식 화이트리스트가 놓쳐 방계 9명이 안방준의 부모가 됐던 호칭들.
# 한국어 친족어는 생성형이라 목록으로 못 덮는다 — 구조로 잡아야 한다.
for _title in ["종조부", "재종조부", "종증조부", "재종숙", "할아버지",
               "서손자", "손녀사위", "사돈", "당질", "이복형", "본인"]:
    check(f"방계 호칭 '{_title}' 제거",
          strip_kinship_lists(f"{_title} : 안정(安艇) - 자 강빈") == "")

print("\n[소유격 오독 — 한 세대 건너뛰기]")
# 실측: `처는 정승복의 딸이다` 에서 `안방준 spouse_of 정승복` 이 나왔다.
# 아내는 정승복의 딸이지 정승복이 아니다. 근거 검증은 못 잡는다.
from histgraph.extract import possessive_mismatch  # noqa: E402

check("`X의 딸` 을 배우자로 읽으면 버린다",
      possessive_mismatch("spouse_of", "정승복", "처는 경주 정씨 판관 정승복(鄭承復)의 딸이다."))
check("한자 병기 없이도 잡는다",
      possessive_mismatch("spouse_of", "정승복", "처는 정승복의 딸이다."))
check("배우자 본인이면 통과",
      not possessive_mismatch("spouse_of", "경주정씨", "부인 : 경주정씨(1571~1642)"))
check("다른 관계 타입은 검사 안 함",
      not possessive_mismatch("related_to", "정승복", "처는 정승복의 딸이다."))
check("근거에 대상이 없으면 통과",
      not possessive_mismatch("spouse_of", "정승복", "다른 이야기"))

# **관계마다 판정이 뒤집힌다.** child_of 는 'A 는 B 의 자녀' 라는 뜻이므로
# `안중관의 아들 안방준` → `안방준 child_of 안중관` 은 옳다. 이걸 버리면
# 맞는 부모 관계가 통째로 사라진다.
check("`X의 아들` 은 child_of 에서 정상 (버리면 안 됨)",
      not possessive_mismatch("child_of", "안중관", "안중관의 아들 안방준은"))
check("`X의 딸` 도 child_of 에서 정상",
      not possessive_mismatch("child_of", "정승복", "정승복의 딸이다."))
check("서술형 부모 관계도 통과",
      not possessive_mismatch("child_of", "안중관", "아버지는 첨지중추부사 안중관이며"))
check("`X의 손자` 는 child_of 에서 세대 건너뜀 → 버린다",
      possessive_mismatch("child_of", "안민", "안민의 손자 안방준은"))

# 이름 자리에 설명구가 온 경우. 근거가 아니라 **이름 자체**가 소유격이라
# possessive_mismatch 가 놓친다.
from histgraph.extract import is_descriptive_name, normalize_name  # noqa: E402
check("`X의 따님` 은 이름이 아니다", is_descriptive_name("양윤순(梁允純)의 따님"))
check("`X의 딸` 도 이름이 아니다", is_descriptive_name("정승복의 딸"))
check("보통 이름은 통과", not is_descriptive_name("안중관"))
check("한자 병기 이름도 통과", not is_descriptive_name("송시열(宋時烈)"))
# **친족어를 낱개로 세면 반드시 샌다.** 실측(기축옥사 문서): 목록에 `처`·
# `형`·`누이` 는 있는데 `처자`·`형제`·`조상` 이 없어서 셋이 그대로 노드가
# 됐다. 집합(형제·처자·일가)과 세대(조상·후손)를 같이 본다.
for _bad in ("정여립의 처자", "정여립의 형제", "정여립의 조상", "정여립의 일가",
             "이순신의 후손", "세종의 사위", "김종직의 문인", "현종의 스승"):
    check(f"`{_bad}` 는 이름이 아니다", is_descriptive_name(_bad))
for _ok in ("정옥남", "조선 세조", "기축옥사", "의금부", "이덕형", "형조판서"):
    check(f"`{_ok}` 는 통과", not is_descriptive_name(_ok))

# 한자 병기가 붙으면 같은 사람이 두 노드가 된다
check("한자 병기 제거", normalize_name("송시열(宋時烈)") == "송시열")

print("\n[참여 오독 — 죽은 뒤의 사건]")
# 실측: 황진이(1506~1567) 문서의 "임진왜란과 병자호란 등으로 인해 대부분
# 실전되었고"(작품이 소실됐다는 뜻)에서 participated_in 이 나왔다. 근거는
# 원문에 실제로 있고 상대 이름도 들어 있어 기존 검증을 전부 통과한다.
from histgraph.extract import (  # noqa: E402
    evidence_year,
    label_year,
    lifespan_conflict,
    loss_context,
    movement_origin,
)

check("`~로 인해 실전` 은 참여가 아니다 → 버린다",
      loss_context("participated_in",
                   "그러나 임진왜란과 병자호란 등으로 인해 대부분 실전되었고"))
check("소실 어휘만으로는 안 버린다 (원균의 해전 참여가 정상)",
      not loss_context("participated_in",
                       "옥포 해전에서 조선 수군은 개전 이후 최초의 대규모 승리를"))
check("원인 문형만으로는 안 버린다",
      not loss_context("participated_in", "임진왜란으로 인해 의병을 일으켰다"))
check("다른 관계 타입은 검사 안 함",
      not loss_context("related_to", "병자호란으로 인해 소실되었고"))

# 실측 회귀: 윤임의 부모가 20명이었다 — 할아버지·숙부·외삼촌·사돈이 전부
# 부모로 들어왔다. 산문은 이름 앞에 관계를 적어 두는데 추출이 그 호칭을
# 버리고 이름만 가져간 자리다.
from histgraph.extract import kin_title_mismatch, name_variants  # noqa: E402

check("`숙부 윤여해` 는 부모가 아니다",
      kin_title_mismatch("child_of", "윤여해", "숙부 윤여해도 연좌되어 유배당했다."))
check("`할아버지:신숙권` 처럼 붙여 쓴 것도 잡는다",
      kin_title_mismatch("child_of", "신숙권", "할아버지:신숙권"))
check("`이복 여동생 : 윤옥춘`",
      kin_title_mismatch("child_of", "윤옥춘", "이복 여동생 : 윤옥춘(尹玉春, 1518 ~ ?)"))
# 한 문장에 친족어가 여럿 나오는 건 흔하다. 이름 **바로 앞**만 봐야
# 옳은 부모가 안 날아간다.
check("`아버지 신명화의 6촌 동생은 신상으로` 에서 아버지는 살린다",
      not kin_title_mismatch("child_of", "신명화",
                             "아버지 신명화의 6촌 동생은 신상으로"))
check("같은 문장에서 동생 쪽은 버린다",
      kin_title_mismatch("child_of", "신상", "아버지 신명화의 6촌 동생은 신상으로"))
check("성을 뗀 표기도 찾는다",
      kin_title_mismatch("child_of", "윤 여해", "숙부 여해도 연좌되어",
                         name_variants("윤 여해")))
check("다른 관계 타입은 검사 안 함",
      not kin_title_mismatch("spouse_of", "윤여해", "숙부 윤여해도"))

# 실측 회귀: '위화도 회군'의 발생 장소로 평양시가 들어왔다. 근거는 군대가
# 평양을 **떠난** 문장이다 — 화면은 "위화도 회군은 평양시에서 일어났다"고 읽었다.
check("`평양을 출발하여` 는 일어난 곳이 아니다 → 버린다",
      movement_origin("occurred_at", "평양시",
                      "출정군은 5월 24일 평양을 출발하여 6월 11일 압록강 하류"
                      " 위화도에 진주하였다."))
check("행정 접미사가 붙은 라벨도 본문 표기로 찾는다",
      movement_origin("occurred_at", "강화도", "인조가 강화도를 출발해 경덕궁으로 돌아왔다."))
# `~로 회군하여 정변을 일으킨` — 도착지에서 실제로 사건이 벌어졌다.
# 이동 문형까지 걸면 개경 정변이 통째로 날아간다.
check("도착지는 살린다",
      not movement_origin("occurred_at", "개성시",
                          "이성계가 개경(開京)으로 회군(回軍)하여 정변을 일으킨 사건이다."))
check("사건이 실제로 일어난 곳은 살린다",
      not movement_origin("occurred_at", "위화도",
                          "압록강 하류의 위화도까지 이른 우군 도통사 이성계가"))
check("장소 관계가 아니면 검사 안 함",
      not movement_origin("participated_in", "평양시", "평양을 출발하여"))

check("죽은 뒤의 사건 참여 → 연대 충돌",
      lifespan_conflict("participated_in", ("1506", "1544"), ("1636-12-09", None)))
check("생전의 사건 참여는 통과",
      lifespan_conflict("participated_in",
                        ("1545", "1598"), ("1592-05-23", "1593-01-01")) is False)
check("연대를 모르면 막지 않는다",
      not lifespan_conflict("participated_in", ("1506", "1544"), (None, None)))

# `황진이 (2006년)` 같은 영화·드라마 사건 노드는 라벨의 연도가 유일한
# 연대 단서다. 이게 없으면 사후 400년 뒤 드라마 '참여'가 살아남는다.
check("라벨 연도 추출", label_year("황진이 (2006년)") == "2006")
check("연도 없는 라벨은 None", label_year("병자호란") is None)
# **끝자리 괄호만 보면 절반을 놓친다.** 처음에 `(YYYY년)` 꼬리만 봤다가
# 드라마 참여 76건이 그대로 남았다 — 연도가 라벨 앞에 오는 꼴이었다.
check("라벨 앞머리 연도도 잡는다",
      label_year("2021년~2022년 KBS 1TV 드라마 《태종 이방원》") == "2021")
check("범위 라벨은 시작 연도", label_year("1996년~1998년 KBS 1TV 드라마 《용의 눈물》") == "1996")
check("재위년은 연도가 아니다 (두 자리)", label_year("조선 세조 12년(1466)") is None)

check("근거에서 가장 이른 연도", evidence_year("《왕과 비》 (KBS 1TV, 1998년~2000년 배우:이광기)") == "1998")
check("근거에 연도가 없으면 None", evidence_year("장희재가 스스로 죄를 청하였으나") is None)
check("근거 연도로 사후 참여를 잡는다",
      lifespan_conflict("participated_in", ("1418", "1446"),
                        (evidence_year("《왕과 비》 (KBS 1TV, 1998년~2000년)"), None)))
check("라벨 연도로 사후 참여를 잡는다",
      lifespan_conflict("participated_in", ("1506", "1544"),
                        (label_year("황진이 (2006년)"), None)))

print("\n[가제티어 덤프 — 한 문장이 낳은 묶음]")
# 실측: `무오사화 --from_period-->` 39건이 문서 첫 문장 하나를 근거로 달려
# 있었고 대상 39개가 전부 가제티어 period 상위 150개였다 (무오사화는
# 1498년인데 조선 선조 17년(1584)…). 낱개로 보면 근거가 원문에 실제로
# 있어 멀쩡하다 — 묶음의 **지목률**로만 갈린다.
from histgraph.extract import gazetteer_dump  # noqa: E402

_dump_ev = ("무오사화(戊午士禍)는 1498년(연산군 4년) 음력 7월 훈구파가 사림파를 대대적으로"
            " 숙청한 사건이다. 조선시대 4대사화 가운데 첫 번째 사화이다.")
_dump = [
    {"subject": "무오사화", "relation": "from_period", "object": obj, "evidence": _dump_ev}
    for obj in ("조선 세조 12년(1466)", "조선 선조 17년(1584)", "조선 숙종 9년(1683)",
                "조선 영조 4년(1728)", "조선 중종 8년(1513)", "조선시대")
]
_dropped = gazetteer_dump(_dump)
check("근거가 지목 못한 대상을 버린다", len(_dropped) == 5)
check("근거가 지목한 것은 남긴다 (조선시대)", 5 not in _dropped)

# 정상 열거문은 대상을 다 지목한다. 이걸 버리면 황진이의 시조가 사라진다.
_list_ev = "시조 작품으로는 청산리 벽계수야, 동짓달 기나긴 밤을, 내언제 신의 없어, 산은 옛 산이로되, 어져 내일이여 등이 있다."
_list = [
    {"subject": "황진이", "relation": "created", "object": obj, "evidence": _list_ev}
    for obj in ("청산리 벽계수야", "동짓달 기나긴 밤을", "내언제 신의 없어",
                "산은 옛 산이로되", "어져 내일이여")
]
check("정상 열거문은 그대로 둔다", gazetteer_dump(_list) == set())

# 묶음이 작으면 열거문과 구분되지 않는다 — 근거가 대상을 안 적는 것이
# 자연스러운 경우가 많다 (`김일경은 조선후기의 문신` → from_period 조선시대).
_small = [
    {"subject": "김일경", "relation": "from_period", "object": obj,
     "evidence": "김일경(金一鏡, 1662년 ~ 1724년)은 조선후기의 문신이다."}
    for obj in ("조선시대", "조선시대 후기")
]
check("작은 묶음은 건드리지 않는다", gazetteer_dump(_small) == set())
check("근거 없는 관계는 묶지 않는다",
      gazetteer_dump([{"subject": "a", "relation": "related_to", "object": "b"}]) == set())

print("\n[작품 표기 변이]")
# 실측: 황진이 상세에 작품이 9편으로 부풀어 있었다. `등만월대회고`
# (登滿月臺懷古)와 `만월대 회고시` 가 같은 시인데 두 노드였다.
from histgraph.promote import title_core  # noqa: E402

check("갈래 접두·접미를 벗긴다", title_core("등만월대회고") == title_core("만월대 회고시"))
check("핵심이 다르면 안 같아진다", title_core("박연폭포시") != title_core("영초월시"))
# 문자열이 비슷하다고 합치면 절반이 틀린다 — 이것들은 서로 다른 사건이다
check("차수가 다른 사건은 안 같아진다",
      title_core("제1차 요동 정벌") != title_core("제2차 요동 정벌"))
check("연도가 다른 사건은 안 같아진다",
      title_core("단종 복위 사건 (1456년)") != title_core("단종 복위 사건 (1457년)"))
check("공백 섞인 한자도 제거", normalize_name("조헌 (趙憲)") == "조헌")
check("한글 괄호는 남긴다 (동명이인 구분)",
      normalize_name("해명 (고구려)") == "해명 (고구려)")
check("괄호 없는 이름은 그대로", normalize_name("안방준") == "안방준")

print("\n[Wikidata 날짜 — '값 불명'은 URL 로 온다]")
# 실측: 노드 100개의 start_date 에 blank node URL 이 들어앉아 있었다
# (침류왕·고국원왕·왕인…). 연대를 보는 관문이 전부 헛돌았다.
from histgraph.sources.wikidata import _iso_date  # noqa: E402

check("정상 날짜", _iso_date("1397-04-18T00:00:00Z") == "1397-04-18")
check("기원전 보존", _iso_date("-0400-01-01T00:00:00Z") == "-0400-01-01")
check("세 자리 연도 보존", _iso_date("0385-01-01T00:00:00Z") == "0385-01-01")
check("blank node URL 은 모름",
      _iso_date("http://www.wikidata.org/.well-known/genid/a808c9f") is None)
check("날짜 아닌 문자열은 모름", _iso_date("불명") is None)
check("빈 값은 모름", _iso_date("") is None and _iso_date(None) is None)

print("\n[연대 충돌 — 가족 관계는 같은 시대를 살아야 한다]")
# 실측: `이세좌 --child_of--> 이수원` 451년 차이. 같은 쌍에 spouse_of 까지
# 붙어 모순이었다. 이름이 같은 다른 시대 사람에게 붙은 것.
from histgraph.extract import lifespan_conflict  # noqa: E402

sejwa, susuwon = ("1445-01-01", "1504-01-01"), ("1896-01-01", "1970-01-01")
check("451년 차이 child_of 는 버린다",
      lifespan_conflict("child_of", sejwa, susuwon))
check("451년 차이 spouse_of 도 버린다",
      lifespan_conflict("spouse_of", sejwa, susuwon))
check("생애가 겹치면 통과",
      not lifespan_conflict("child_of", ("1573-01-01", "1654-01-01"),
                            ("1524-01-01", "1605-01-01")))
check("연대를 모르면 막지 않는다",
      not lifespan_conflict("child_of", (None, None), susuwon))
# related_to 는 학맥·추숭이 있으므로 시대가 달라도 참일 수 있다
check("related_to 는 검사하지 않는다 (김종직→주희 498년)",
      not lifespan_conflict("related_to", ("1431-01-01", "1492-01-01"),
                            ("1130-01-01", "1200-01-01")))

print("\n[동명이인 — 연대가 차수보다 먼저다]")
# 실측: 조선 예종의 휘가 이황(李晄)이라 별칭에 '이황'이 있다. 안방준
# 문서의 '퇴계 이황(李滉)의 문인'에서 차수 큰 예종이 이겼다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "amb.sqlite")
    store.upsert_nodes([
        Node(id="wd:AN", type="person", label="안방준", source="wd",
             start_date="1573-01-01", end_date="1654-01-01"),
        # 예종: 차수를 크게 만들어 둔다 (왕이라 연결이 많다)
        Node(id="wd:YJ", type="person", label="조선 예종", source="wd",
             start_date="1450-01-01", end_date="1469-01-01"),
        Node(id="wd:TG", type="person", label="이황", source="wd",
             start_date="1501-01-01", end_date="1570-01-01"),
    ])
    store.upsert_edges([
        Edge(src="wd:YJ", dst="wd:AN", type="related_to", source="wd"),
        Edge(src="wd:YJ", dst="wd:TG", type="related_to", source="wd"),
    ])
    store.conn.execute("INSERT INTO aliases (node_id, alias) VALUES (?,?)",
                       ("wd:YJ", "이황"))
    _, e = to_graph([{
        "subject": "안방준", "subject_type": "person", "relation": "related_to",
        "object": "이황", "object_type": "person",
        "evidence": "퇴계 이황의 문인이었다", "confidence": "certain",
    }], "wd:AN", store)
    check("연대가 맞는 퇴계로 붙는다", e and e[0].dst == "wd:TG",
          str([(x.src, x.dst) for x in e]))
    store.close()

print("\n[근거가 상대를 지목하지 않으면 버린다]")
# 실측: 인물 대상 관계 268건 중 14건이 근거에 상대 이름이 없었고 대부분
# 지어낸 것이었다 — `정약종의 아들 정철상도` 에서 `child_of 정약용`.
from histgraph.extract import evidence_names_target, name_variants  # noqa: E402

check("성을 뗀 축약형도 인정", "종직" in name_variants("김종직"))
check("왕조 접두를 뗀 형태도 인정", "세종" in name_variants("조선 세종"))
check("두 글자 이름은 더 자르지 않음", name_variants("남은") == {"남은"})
# 한 글자 라벨의 후보가 비면 그 인물의 관계가 통째로 사라진다
check("한 글자 라벨도 후보가 비지 않음", name_variants("을") == {"을"})
check("근거가 지목하면 통과",
      evidence_names_target("종직에게 수업하였는데", name_variants("김종직")))
check("근거가 지목 안 하면 버림",
      not evidence_names_target("정약종의 아들 정철상도 구속되었고",
                                name_variants("정약용")))
check("공백 차이는 무시",
      evidence_names_target("조선  세종 때", name_variants("조선 세종")))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "named.sqlite")
    store.upsert_nodes([
        Node(id="wd:A", type="person", label="정약종", source="wd"),
        Node(id="wd:B", type="person", label="정약용", source="wd"),
    ])
    _, e = to_graph([{
        "subject": "정약종", "subject_type": "person", "relation": "child_of",
        "object": "정약용", "object_type": "person",
        "evidence": "정약종의 아들 정철상도 구속되었고", "confidence": "certain",
    }], "wd:A", store)
    check("근거에 없는 인물은 엣지가 안 생김", e == [])
    # 문서 주인은 예외 — 그 글이 곧 그 사람의 글이다
    store.upsert_nodes([Node(id="ev:1", type="event", label="3·1 운동", source="t")])
    _, e2 = to_graph([{
        "subject": "정약종", "subject_type": "person", "relation": "participated_in",
        "object": "3·1 운동", "object_type": "event",
        "evidence": "손병희 등에 의해 주도되었으며", "confidence": "certain",
    }], "ev:1", store)
    check("문서 주인은 이름이 없어도 통과", len(e2) == 1)
    store.close()

print("\n[방향 뒤집힘 — 구조화 소스가 반대를 알고 있으면 버린다]")
# child_of 는 person→person 이라 orient() 가 방향을 못 가린다. 실측:
# 추출 가족 관계 122건 중 50건이 구조화 소스와 어긋났고 대부분 뒤집힘이었다
# (`폐비 윤씨 child_of 조선 연산군` — 연산군이 그녀의 아들이다).
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "rev.sqlite")
    store.upsert_nodes([
        Node(id="wd:M", type="person", label="폐비 윤씨", source="wd"),
        Node(id="wd:S", type="person", label="조선 연산군", source="wd"),
    ])
    # 구조화 소스: 연산군이 폐비 윤씨의 자녀
    store.upsert_edges([Edge(src="wd:S", dst="wd:M", type="child_of", source="wd")])
    _, e = to_graph([{
        "subject": "폐비 윤씨", "subject_type": "person", "relation": "child_of",
        "object": "조선 연산군", "object_type": "person",
        "evidence": "폐비 윤씨는 조선 연산군의 어머니이다",
        "confidence": "certain",
    }], "wd:M", store)
    check("역방향 추출은 버린다", e == [], str([(x.src, x.dst) for x in e]))

    _, e2 = to_graph([{
        "subject": "조선 연산군", "subject_type": "person", "relation": "child_of",
        "object": "폐비 윤씨", "object_type": "person",
        "evidence": "조선 연산군은 폐비 윤씨의 아들이다",
        "confidence": "certain",
    }], "wd:S", store)
    check("같은 방향은 통과", len(e2) == 1 and e2[0].src == "wd:S")

    # 구조화 소스에 근거가 없으면 막지 않는다
    store.upsert_nodes([Node(id="wd:X", type="person", label="갑", source="wd"),
                        Node(id="wd:Y", type="person", label="을", source="wd")])
    _, e3 = to_graph([{
        "subject": "갑", "subject_type": "person", "relation": "child_of",
        "object": "을", "object_type": "person",
        "evidence": "갑은 을의 아들이다", "confidence": "certain",
    }], "wd:X", store)
    check("근거 없으면 막지 않는다", len(e3) == 1)
    store.close()

print("\n[이미 추출한 문서 건너뛰기 — --limit 배치의 전제]")
# 없으면 두 번째 배치가 첫 배치를 다시 돌린다 (조각당 200초)
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "skip.sqlite")
    store.upsert_nodes([
        Node(id="p:1", type="person", label="갑", source="t", description=narrative),
        Node(id="p:2", type="person", label="을", source="t", description=narrative),
    ])
    check("추출 전에는 둘 다 대상",
          len({d.node_id for d in load_documents(store, min_score=1.0)}) == 2)
    store.upsert_nodes([Node(id="ex:person:병", type="person", label="병", source="extract")])
    store.upsert_edges([Edge(src="p:1", dst="ex:person:병", type="related_to",
                             source="extract", props={"extracted_from": "p:1"})])
    left = {d.node_id for d in load_documents(store, min_score=1.0)}
    check("추출한 문서는 제외", left == {"p:2"}, str(left))
    check("--redo 면 다시 포함",
          len({d.node_id for d in load_documents(store, min_score=1.0,
                                                 skip_extracted=False)}) == 2)
    store.close()

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "g.sqlite")
    # 족보 행이 밀도를 부풀리지 않도록 선별 전에 지워져야 한다
    doc_text = narrative + "\n" + "장남 : 안후지(安厚之, 1590~1664)\n" * 30
    store.upsert_nodes([
        Node(id="p:1", type="person", label="안방준", source="t", description=doc_text),
    ])
    docs = load_documents(store, min_score=1.0)
    check("선별된 문서에 족보 행이 없음",
          docs and all("장남 :" not in d.text for d in docs))
    store.close()

print("\n[인포박스 — 인물 필드와 방향]")
# 인포박스 필드는 문서 주인 기준으로 쓰여 있어 방향이 필드마다 다르다.
# `아버지 = [[안중관]]` 과 `자녀 = [[안후지]]` 는 같은 child_of 인데 반대다.
from histgraph.sources.infobox import (  # noqa: E402
    EVENT_FIELDS, IN, OUT, PERSON_FIELDS, parse_infobox_links,
)

person_wikitext = """{{인물 정보
|이름 = 안방준
|아버지 = [[안중관]]
|어머니 = [[진원 박씨]]
|배우자 = [[경주 정씨]]
|자녀 = [[안후지]]<br />[[안신지]]
|스승 = [[성혼]]
|출생지 = [[보성군]]
|그림 = [[파일:Ahn.jpg|섬네일]]
|직업 = 의병장
}}"""
# **필드 값은 인포박스가 닫히는 `}}` 에서 끝나야 한다.** 실측(세종):
# `| 자녀 = [[#왕자|18남 4녀]]` 뒤에 `}}` 가 오는데 거기서 안 끊으면
# 도입부를 통째로 삼켜 황희·장영실·김종서가 세종의 자녀가 된다.
from histgraph.sources.infobox import infobox_span  # noqa: E402

sejong_like = """{{다른 뜻|세종 (동음이의)}}
{{조선의 국왕
| 이름 = 세종
| 아버지 = [[태종 (조선)|태종]]
| 자녀 = [[#왕자|18남 4녀]] {{font color|gray|(19남 7녀)}}
}}

'''세종'''은 [[1397년]]에 태어났다. [[황희]], [[장영실]], [[김종서]]를 등용했다.
"""
sejong_links = parse_infobox_links(sejong_like, PERSON_FIELDS)
check("본문 인물이 자녀로 새지 않음",
      "황희" not in sejong_links.get("자녀", [])
      and "장영실" not in sejong_links.get("자녀", []), str(sejong_links))
check("본문 연도도 새지 않음", "1397년" not in sejong_links.get("자녀", []))
check("문서 내 앵커는 개체가 아니다", "#왕자" not in sejong_links.get("자녀", []))
check("인포박스 안의 필드는 정상 추출", sejong_links.get("아버지") == ["태종 (조선)"])
# 앞에 붙은 작은 틀({{다른 뜻}})을 인포박스로 착각하면 전부 놓친다
check("앞선 작은 틀을 건너뛴다", "아버지" in infobox_span(sejong_like, PERSON_FIELDS))
check("중첩 틀에서 끊기지 않는다", "자녀" in infobox_span(sejong_like, PERSON_FIELDS))
check("대상 필드가 없으면 빈 문자열",
      infobox_span("{{다른 뜻|x}}\n본문 [[황희]]", PERSON_FIELDS) == "")

print("\n[인포박스 — 날짜·별칭·참가자]")
# 임오화변이 연표에 못 섰다. Wikidata 에 P580/P582/P585 가 없어서인데,
# **답은 인포박스에 적혀 있었다.** 파서가 링크만 뽑고 값 필드를 지나쳤다.
from histgraph.sources.infobox import (  # noqa: E402
    EVENT_FIELDS, EVENT_VALUE_FIELDS, apply_event_attrs, infobox_aliases,
    infobox_date, parse_infobox_values,
)

imo = """{{역사적 사건 정보
| 이름 = 임오화변
| 별칭 = 임오옥, 사도세자사건
| 참가자 = [[영조]]·[[노론]]<br/>[[정조|세손 산]], [[이석문 (1713년)|이석문]], 홍화보
| 장소 = {{국기|조선}}
| 날짜 = [[1762년]] (영조 38) [[7월 5일]]
| 결과 = 세자의 지위를 아들이 계승
}}
'''임오화변'''은 [[1762년]] [[7월 4일]] … [[사도세자]]가 [[노론]]과 …
"""
vals = parse_infobox_values(imo, EVENT_VALUE_FIELDS, EVENT_FIELDS)
check("값 필드를 읽는다", vals.get("날짜") == "[[1762년]] (영조 38) [[7월 5일]]", str(vals))
check("값이 본문으로 새지 않는다", "사도세자가" not in vals.get("결과", ""))
check("날짜를 ISO 로", infobox_date(vals["날짜"]) == "1762-07-05")
check("별칭을 가른다", infobox_aliases(vals["별칭"], "임오화변") == ["임오옥", "사도세자사건"])

# 위키 주석은 편집자에게 남긴 쪽지지 별칭이 아니다. 을사사화·헤이그 특사
# 사건의 `<!-- 잘 알려진 명칭으로, 사건 이름과 중복되면 쓰지 않음 -->` 이
# 쉼표에서 갈려 이름표 두 개로 화면에 섰다 (2026-09-05 지적).
memo = "<!-- 잘 알려진 명칭으로, 사건 이름과 중복되면 쓰지 않음 -->"
check("주석은 별칭이 아니다", infobox_aliases(memo, "을사사화") == [])
check("주석 뒤의 이름은 살린다", infobox_aliases(f"을사년의 옥사 {memo}", "을사사화") == ["을사년의 옥사"])
eul = "{{사건 정보\n| 사건명 = 을사사화\n| 별칭 = " + memo + "\n| 날짜 = [[1545년]]\n}}"
check("주석은 값을 읽기 전에 지운다",
      parse_infobox_values(eul, EVENT_VALUE_FIELDS, EVENT_FIELDS).get("별칭") == "",
      str(parse_infobox_values(eul, EVENT_VALUE_FIELDS, EVENT_FIELDS)))

# 괄호 안 재위 연차를 연도로 집으면 안 된다 — 거의 모든 사건에 붙어 있다.
check("재위 연차는 연도가 아니다", infobox_date("(영조 38)") is None)
check("연차가 붙어도 서기를 집는다", infobox_date("[[1504년]](연산군 10년)") == "1504-01-01")
check("범위는 시작만", infobox_date("[[1592년]] [[5월 23일]] ~ [[1598년]]") == "1592-05-23")
check("시작일 틀도 읽는다", infobox_date("{{시작일|1894|1|11}}") == "1894-01-11")
check("월만 있으면 1일로", infobox_date("[[1519년]] (중종 14) [[12월]]") == "1519-12-01")
check("못 읽으면 비운다", infobox_date("알 수 없음") is None and infobox_date("") is None)
check("13월은 버리고 연도만", infobox_date("1762년 13월") == "1762-01-01")

# 참가자는 `역사적 사건 정보` 틀의 필드다. 전투 틀의 지휘관/교전국만 보고
# 있어서 옥사·사화·정변의 인물이 통째로 빠져 있었다.
from histgraph.sources.infobox import parse_infobox_links as _pil  # noqa: E402

ilinks = _pil(imo, EVENT_FIELDS)
check("참가자 필드를 읽는다", "영조" in ilinks.get("참가자", []), str(ilinks))
check("파이프 링크는 문서명으로", "이석문 (1713년)" in ilinks.get("참가자", []))
check("링크 아닌 이름은 안 가져온다", "홍화보" not in ilinks.get("참가자", []))

# 이미 있는 날짜는 덮지 않는다 — Wikidata 는 사람이 손본 값이다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "ib.sqlite")
    store.upsert_nodes([
        Node(id="wd:A", type="event", label="빈 사건", source="wd"),
        Node(id="wd:B", type="event", label="찬 사건", source="wd",
             start_date="1500-03-04"),
    ])
    attrs = {"wd:A": {"start_date": "1762-07-05", "aliases": ["임오옥", "사도세자사건"]},
             "wd:B": {"start_date": "1600-01-01"}}
    dated, aliased = apply_event_attrs(store, attrs)
    check("빈 날짜를 채운다", dated == 1)
    check("채운 값이 들어갔다",
          store.conn.execute("SELECT start_date FROM nodes WHERE id='wd:A'").fetchone()[0]
          == "1762-07-05")
    check("있는 날짜는 안 덮는다",
          store.conn.execute("SELECT start_date FROM nodes WHERE id='wd:B'").fetchone()[0]
          == "1500-03-04")
    check("별칭이 들어갔다", aliased == 2)
    d2, _ = apply_event_attrs(store, attrs, refresh=True)
    check("--refresh 면 덮는다",
          store.conn.execute("SELECT start_date FROM nodes WHERE id='wd:B'").fetchone()[0]
          == "1600-01-01")
    check("두 번 돌려도 별칭은 안 쌓인다", apply_event_attrs(store, attrs)[1] == 0)
    store.close()

plinks = parse_infobox_links(person_wikitext, PERSON_FIELDS)
check("인물 필드를 읽는다", plinks.get("아버지") == ["안중관"])
check("여러 링크가 한 필드에", plinks.get("자녀") == ["안후지", "안신지"])
check("파일 링크는 제외", all("파일" not in t for ts in plinks.values() for t in ts))
check("표에 없는 필드는 무시", "직업" not in plinks)

check("아버지는 문서 주인이 출발 (child_of out)", PERSON_FIELDS["아버지"][2] == OUT)
check("자녀는 방향이 반대 (child_of in)", PERSON_FIELDS["자녀"][2] == IN)
check("출생지는 born_in", PERSON_FIELDS["출생지"][:2] == ("born_in", ("place",)))
check("지휘관은 사건으로 들어온다", EVENT_FIELDS["지휘관1"][2] == IN)
check("장소는 사건에서 나간다", EVENT_FIELDS["장소"][2] == OUT)

# 사건 필드 표로 읽으면 인물 필드가 안 잡혀야 한다 (표가 갈리는지 확인)
check("사건 표로는 인물 필드를 안 읽는다",
      parse_infobox_links(person_wikitext, EVENT_FIELDS) == {})

# 방향 표가 온톨로지와 어긋나면 엣지가 통째로 버려진다
from histgraph.ontology import EDGE_TYPES  # noqa: E402
for _f, (_rel, _expected, _dir) in {**EVENT_FIELDS, **PERSON_FIELDS}.items():
    _, allowed_src, allowed_dst = EDGE_TYPES[_rel]
    subject_side = "person" if _f in PERSON_FIELDS else "event"
    ok = (subject_side in allowed_src) if _dir == OUT else (subject_side in allowed_dst)
    check(f"'{_f}' 방향이 온톨로지와 맞음", ok, f"{_rel} {_dir}")

# 지명 계층에서 가장 구체적인 것만 — 안 그러면 1392년에 죽은 정몽주에게
# 1948년에 생긴 국가가 사망지로 붙는다
from histgraph.sources.infobox import NARROWEST_ONLY  # noqa: E402
check("출생지·사망지는 최협의만", NARROWEST_ONLY == {"born_in", "died_in"})
check("가족 관계는 여러 건을 다 남긴다", "child_of" not in NARROWEST_ONLY)

print("\n[긴 문서 조각내기]")
# 위키백과 본문 전체를 받으면 6·25 전쟁이 57,451자다. 통째로 넣으면
# 뒤쪽 문단 관계를 놓친다.
from histgraph.extract import CHUNK_CHARS, split_document  # noqa: E402

short = "짧은 문서입니다. " * 5
check("짧은 문서는 자르지 않음", len(split_document("n:1", "짧음", short)) == 1)
check("자르지 않은 문서는 total_chunks=1", split_document("n:1", "짧음", short)[0].total_chunks == 1)

long_text = "\n".join(f"{i}번째 문단. 이순신은 명량에서 왜군을 격파하였다. " * 12 for i in range(40))
parts = split_document("n:2", "김", long_text)
check("긴 문서는 여러 조각", len(parts) > 1)
check("모든 조각이 상한 이내", all(len(p.text) <= CHUNK_CHARS + 200 for p in parts))
check("조각이 같은 node_id 공유", all(p.node_id == "n:2" for p in parts))
check("조각 번호가 0부터 연속", [p.chunk for p in parts] == list(range(len(parts))))
check("total_chunks 가 실제 개수와 일치", all(p.total_chunks == len(parts) for p in parts))
# 경계에 걸친 서술이 사라지지 않아야 한다
check("조각 사이에 겹침 존재", parts[0].text[-100:] in parts[1].text[:600])

print("\n[추출 백엔드]")
# 스키마가 강제되지 않는 백엔드(ollama)에서 모델이 형태를 흘리는 변형들.
# 실측: ollama 0.30.7 은 format 에 스키마 객체를 줘도 무시하고 산문을 낸다.
from histgraph.backends import (  # noqa: E402
    _coerce_relations,
    _extract_json,
    build_backend,
)

rel = {"subject": "이순신", "relation": "participated_in", "object": "명량 해전"}
check("기대 형태 {relations:[...]}", _coerce_relations({"relations": [rel]}) == [rel])
check("배열만 온 경우", _coerce_relations([rel]) == [rel])
check("관계 하나만 통째로 온 경우", _coerce_relations(rel) == [rel])
check("관계가 없으면 빈 배열 유지", _coerce_relations({"relations": []}) == [])
check("형태 불명은 None (재요청 대상)", _coerce_relations({"foo": 1}) is None)
check("문자열은 None", _coerce_relations("아무 말") is None)

check("순수 JSON 파싱", _extract_json('{"relations":[]}') == {"relations": []})
check("코드펜스 제거", _extract_json('```json\n{"relations":[]}\n```') == {"relations": []})
check("앞뒤 설명 제거", _extract_json('네, 결과입니다:\n{"relations":[]}\n이상입니다') == {"relations": []})
check("JSON 없으면 None", _extract_json("관계를 찾지 못했습니다") is None)
check("빈 문자열은 None", _extract_json("") is None)

check("mlx 백엔드 생성", build_backend("mlx").name == "mlx")
check("anthropic 백엔드 생성", build_backend("anthropic").name == "anthropic")
check("ollama 백엔드 생성", build_backend("ollama").name == "ollama")
try:
    build_backend("없는백엔드")
    check("알 수 없는 백엔드는 거부", False)
except ValueError:
    check("알 수 없는 백엔드는 거부", True)

# --- OpenRouter (무료 모델). 네트워크 없이 몸통만 본다 ---------------------
import json as _j0  # noqa: E402
import os as _os0  # noqa: E402
import time as _t0  # noqa: E402
import urllib.request as _ur  # noqa: E402

import histgraph.backends as _bk  # noqa: E402

_keep_or = {k: _os0.environ.get(k) for k in (_bk.ENV_OPENROUTER_KEY, _bk.ENV_OPENROUTER_MODEL)}
_bk.OPENROUTER_MIN_INTERVAL = 0     # 테스트가 한도를 지키느라 3초씩 자지 않게
try:
    _os0.environ.pop(_bk.ENV_OPENROUTER_KEY, None)
    _os0.environ.pop(_bk.ENV_OPENROUTER_MODEL, None)
    check("열쇠가 없으면 개인 역사는 로컬 모델로", _bk.default_life_backend() == "mlx")
    check("열쇠가 없으면 부르지 않는다 (빈 답)",
          _bk.OpenRouterBackend().complete_json("s", "u", {"type": "object"}) is None)
    _os0.environ[_bk.ENV_OPENROUTER_KEY] = "sk-or-test"
    check("열쇠가 있으면 OpenRouter 로", _bk.default_life_backend() == "openrouter")
    check("모델 기본값은 무료 모델", build_backend("openrouter").model.endswith(":free"))
    _os0.environ[_bk.ENV_OPENROUTER_MODEL] = "다른/모델:free"
    check("모델은 환경변수가 정한다", build_backend("openrouter").model == "다른/모델:free")
    check("--model 이 환경변수를 이긴다", build_backend("openrouter", "고른/모델").model == "고른/모델")

    class _Resp:
        def __init__(self, body): self.body = _j0.dumps(body).encode()
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls: list[dict] = []

    def _fake_urlopen(req, timeout=None):
        calls.append(_j0.loads(req.data.decode()))
        return _Resp(replies.pop(0))

    class _NoSleep:      # 재시도의 대기를 테스트가 실제로 자지 않게
        sleep = staticmethod(lambda _s: None)
        monotonic = staticmethod(_t0.monotonic)

    _keep_urlopen, _ur.urlopen = _ur.urlopen, _fake_urlopen
    _keep_time, _bk.time = _bk.time, _NoSleep
    try:
        # 상류 오류는 **HTTP 200 으로도** 온다 — 몸을 보지 않으면 빈 답을 정답으로 읽는다.
        replies = [{"error": {"code": 502, "message": "Service temporarily overloaded"}},
                   {"choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"nodes": []}'}}]}]
        calls.clear()
        _bk.OPENROUTER_MIN_INTERVAL = 0
        back = _bk.OpenRouterBackend(retries=2)
        got = back.complete_json("s", "u", {"type": "object"}, max_tokens=100)
        check("200 으로 온 오류를 답으로 읽지 않고 다시 묻는다", got == {"nodes": []} and len(calls) == 2)
        check("사고는 꺼서 묻는다 (안 끄면 상한을 사고가 다 쓴다)",
              calls[0]["reasoning"] == {"enabled": False} and calls[0]["temperature"] == 0)
        check("스키마를 강제해 묻는다",
              calls[0]["response_format"]["json_schema"]["strict"] is True)

        # 사고를 못 끄는 모델이 있다 (liquid: 400). 켜고 다시 묻는다.
        replies = [{"error": {"code": 400, "message": "Reasoning is mandatory for this endpoint and cannot be disabled."}},
                   {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}]
        calls.clear()
        back2 = _bk.OpenRouterBackend(retries=3)
        check("사고를 못 끄는 모델은 켜고 다시 묻는다",
              back2.complete_json("s", "u", {"type": "object"}) == {}
              and "reasoning" not in calls[1] and back2.reasoning_locked)

        # 스키마를 안 받는 모델은 한 칸씩 물러난다 (strict → 느슨 → JSON 모드).
        replies = [{"error": {"code": 400, "message": "response_format.json_schema is not supported"}},
                   {"error": {"code": 400, "message": "response_format.json_schema is not supported"}},
                   {"choices": [{"finish_reason": "stop", "message": {"content": '```json\n{"a":1}\n```'}}]}]
        calls.clear()
        got3 = _bk.OpenRouterBackend(retries=1).complete_json("s", "u", {"type": "object"})
        check("스키마를 거절하면 형식을 낮춰 다시 묻는다",
              got3 == {"a": 1} and [c["response_format"]["type"] for c in calls]
              == ["json_schema", "json_schema", "json_object"])

        # 형식 탓이 아닌 거절(모델 없음)에는 물러나 봐야 소용없다 — 한 번만 묻는다.
        replies = [{"error": {"code": 404, "message": "No endpoints found for 없는/모델"}}]
        calls.clear()
        check("형식 탓이 아니면 물러나지 않는다",
              _bk.OpenRouterBackend(retries=1).complete_json("s", "u", {"type": "object"}) is None
              and len(calls) == 1)
    finally:
        _ur.urlopen = _keep_urlopen
        _bk.time = _keep_time
finally:
    for _k, _v in _keep_or.items():
        if _v is None:
            _os0.environ.pop(_k, None)
        else:
            _os0.environ[_k] = _v

print("\n[승격 — ex: 고아 노드]")
from histgraph.promote import (  # noqa: E402
    classify,
    local_matches,
    merge_node,
    prune_orphans,
    relax_invalid_edges,
)

check("관청은 조직", classify("조선총독부") == "org")
check("N인 집단은 조직", classify("민족대표 33인") == "org")
check("붕당은 조직", classify("벽파") == "org")
check("관직은 직위", classify("병조판서") == "role")
check("칭호 단독은 직위", classify("대왕대비") == "role")
# 오탐이 더 위험하다 — 아래는 전부 사람이거나 사건이다
check("칭호에 이름이 붙으면 인물", classify("인목대비") is None)
check("관직이 앞에 붙으면 인물", classify("응교 최숙생") is None)
check("이름에 관청이 들어가도 인물", classify("김정부") is None)
check("가운데 관청은 사건 그대로", classify("간도 일본 영사관 습격") is None)
check("나라 이름 아닌 제목", classify("나의 나라") is None)

# 위키백과 응답을 흉내내 승격 관문(동음이의·넘겨주기)을 고정한다
from histgraph.promote import fetch_qids  # noqa: E402


class _StubFetcher:
    """마지막 요청 파라미터를 기억하는 가짜 페처."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.params: dict[str, str] = {}

    def get(self, url: str, params: dict[str, str], **kw: object) -> str:
        import json as j

        self.params = params
        return j.dumps(self.payload)


stub = _StubFetcher({
    "query": {
        "redirects": [{"from": "리델", "to": "펠릭스클레르 리델"}],
        "pages": [
            {"title": "펠릭스클레르 리델", "pageprops": {"wikibase_item": "Q12621740"}},
            {"title": "선조", "pageprops": {"wikibase_item": "Q1", "disambiguation": ""}},
            {"title": "없는사람", "missing": True},
        ],
    }
})
found, ambiguous = fetch_qids(stub, ["리델", "선조", "없는사람"])
check("넘겨주기를 요청한 이름으로 되돌림", found == {"리델": "Q12621740"})
check("동음이의 문서는 제외", ambiguous == ["선조"])
check("없는 문서는 결과에 없음", "없는사람" not in found)

fetch_qids(stub, ["삼진 의거"], follow_redirects=False)
check("사건은 넘겨주기를 따라가지 않음", "redirects" not in stub.params)
fetch_qids(stub, ["리델"])
check("인물은 넘겨주기를 따라감", stub.params.get("redirects") == "1")

# 사건의 넘겨주기 중 **띄어쓰기만 다른 것**은 흡수가 아니라 표기 차이다.
# 실측(2026-09-04): '조미수호통상조약'이 '조미 수호 통상 조약'을 가리키는데
# 사건이라 넘겨주기를 안 따라가 문서가 없는 것으로 떨어졌다. 반대로
# '단종 복위 운동' → '세조찬위' 는 상위 사건이라 따라가면 안 된다.
spacing_stub = _StubFetcher({
    "query": {
        "redirects": [
            {"from": "조미수호통상조약", "to": "조미 수호 통상 조약"},
            {"from": "단종 복위 운동", "to": "세조찬위"},
        ],
        "pages": [
            {"title": "조미 수호 통상 조약", "pageprops": {"wikibase_item": "Q697104"}},
            {"title": "세조찬위", "pageprops": {"wikibase_item": "Q16175444"}},
        ],
    }
})
found2, _ = fetch_qids(spacing_stub, ["조미수호통상조약", "단종 복위 운동"],
                       follow_redirects=False, spacing_only=True)
check("띄어쓰기만 다른 넘겨주기는 따라간다",
      found2 == {"조미수호통상조약": "Q697104"}, str(found2))
check("이름이 다른 넘겨주기는 상위 항목으로의 흡수라 버린다",
      "단종 복위 운동" not in found2)
check("띄어쓰기만 볼 때도 넘겨주기 자체는 켠다",
      spacing_stub.params.get("redirects") == "1")

# Wikidata 의 사건은 Q1656682 와 Q1190554 두 뿌리로 갈라져 있다. 앞의
# 것만 보면 전쟁·조약·학살이 통째로 '클래스 확인 실패'가 된다 (실측:
# 국공 내전 P31=내전, 조미 수호 통상 조약 P31=조약, 자유시 참변 P31=학살).
from histgraph.promote import CATEGORY_TO_TYPE  # noqa: E402

check("사건의 두 뿌리를 다 본다",
      CATEGORY_TO_TYPE.get("Q1656682") == "event"
      and CATEGORY_TO_TYPE.get("Q1190554") == "event")

# 회귀: 문서명만 보고 승격하면 동명이인에 붙는다. 무오사화 문서의 '한유'는
# 조선 인물인데 위키백과 '한유'는 당나라 문인 韓愈(768~824)다.
from histgraph.promote import life_span, plausible_period  # noqa: E402

check("생몰년 한쪽만 있어도 구간", life_span("0768-01-01", None) == (768, 848))
check("생몰년이 없으면 구간 없음", life_span(None, None) is None)
check(
    "600년 어긋나면 동명이인",
    not plausible_period(life_span("0768-01-01", "0824-12-25"), [1431, 1491]),
)
check(
    "동시대면 통과",
    plausible_period(life_span("1431-01-01", "1491-08-19"), [1450, 1498]),
)
check("이웃에 연대가 없으면 막지 않음", plausible_period((768, 824), []))
check("생몰년을 모르면 막지 않음", plausible_period(None, [1431]))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "p.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q1", type="person", label="조선 세조", source="wd"),
        Node(id="wd:Q2", type="event", label="계유정난", source="wd"),
        Node(id="wd:Q3", type="person", label="고려 숙종", source="wd"),
        Node(id="wd:Q4", type="person", label="조선 숙종", source="wd"),
        Node(id="kr:period:조선 고종", type="period", label="조선 고종", source="khs"),
        Node(id="ex:person:세조", type="person", label="세조", source="extract"),
        Node(id="ex:person:숙종", type="person", label="숙종", source="extract"),
        Node(id="ex:person:고종", type="person", label="고종", source="extract"),
        # 띄어쓰기만 다른 고아. 산문이 적은 대로 노드가 만들어진다.
        Node(id="wd:Q5", type="event", label="단종 복위 운동", source="wd"),
        Node(id="ex:event:단종 복위운동", type="event", label="단종 복위운동",
             source="extract"),
        # 띄어쓰기를 떼도 후보가 둘이면 고르지 않는다
        Node(id="wd:Q6", type="event", label="여진 정벌 (조선)", source="wd"),
        Node(id="wd:Q7", type="event", label="여진정벌 (조선)", source="wd"),
        Node(id="ex:event:여진 정벌(조선)", type="event", label="여진 정벌(조선)",
             source="extract"),
    ])
    store.upsert_edges([
        Edge(src="ex:person:세조", dst="wd:Q2", type="participated_in",
             source="extract", confidence=0.9),
        # 이미 구조화 소스가 말한 같은 사실 — 병합이 이걸 덮어쓰면 안 된다
        Edge(src="wd:Q1", dst="wd:Q2", type="participated_in", source="wd"),
        # 양끝이 같은 노드로 합쳐지는 엣지 (자기순환이 된다)
        Edge(src="ex:person:세조", dst="wd:Q1", type="related_to", source="extract"),
    ])

    plan = {m["ex_id"]: m for m in local_matches(store)}
    check("왕조 접두로 매칭", plan["ex:person:세조"]["target"] == "wd:Q1")
    check("왕조가 둘이면 매칭하지 않음", "ex:person:숙종" not in plan)
    check("타입이 다르면 매칭하지 않음", "ex:person:고종" not in plan)
    # 실측 회귀(2026-09-04): '단종 복위운동'(고아)과 '단종 복위 운동'(진짜)이
    # 남남으로 남아, 사전에 정의가 있는데도 '같은 이름의 노드가 둘'이라
    # 설명을 못 채우고 지워졌다. 띄어쓰기는 뜻이 아니다.
    check("띄어쓰기만 다르면 같은 노드로 본다",
          plan.get("ex:event:단종 복위운동", {}).get("target") == "wd:Q5"
          and plan["ex:event:단종 복위운동"]["method"] == "label_nospace", str(plan.get("ex:event:단종 복위운동")))
    check("띄어쓰기를 떼도 후보가 둘이면 고르지 않는다",
          "ex:event:여진 정벌(조선)" not in plan)

    stats = merge_node(store, "ex:person:세조", "wd:Q1", method="dynasty_prefix")
    check("자기순환 엣지 제거", stats["self_loops"] == 1)
    check("ex 노드 삭제됨",
          store.conn.execute("SELECT 1 FROM nodes WHERE id='ex:person:세조'").fetchone() is None)
    check("엣지가 대상 노드로 이동",
          store.conn.execute(
              "SELECT COUNT(*) FROM edges WHERE src='wd:Q1' AND dst='wd:Q2'"
          ).fetchone()[0] == 2)
    check("구조화 엣지의 confidence 보존",
          store.conn.execute(
              "SELECT confidence FROM edges WHERE src='wd:Q1' AND source='wd'"
          ).fetchone()[0] == 1.0)
    check("산문 표기를 별칭으로 남김",
          store.conn.execute(
              "SELECT 1 FROM aliases WHERE node_id='wd:Q1' AND alias='세조'"
          ).fetchone() is not None)
    import json as _json  # noqa: E402

    props = _json.loads(
        store.conn.execute("SELECT props FROM nodes WHERE id='wd:Q1'").fetchone()[0]
    )
    check("병합 이력 기록", props["merged_from"][0]["id"] == "ex:person:세조")
    check("옮겨진 엣지에도 출처 기록",
          _json.loads(store.conn.execute(
              "SELECT props FROM edges WHERE src='wd:Q1' AND source='extract'"
          ).fetchone()[0])["merged_from"] == "ex:person:세조")
    store.close()

# 회귀: 별칭으로만 이어지는 것 — 화면의 '정여립의 난'에 정여립이 없었다.
# 추출이 만든 이름은 8월 30일에 들어왔고, 그 이름이 기축옥사의 별칭이라는
# 사실은 9월 3일에 들어왔다. 라벨만 보는 매칭은 이 순서를 못 따라간다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "alias.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q7836645", type="event", label="기축옥사", source="wd",
             start_date="1589-01-01", end_date="1589-01-01"),
        Node(id="wd:Q704854", type="person", label="정여립", source="wd",
             start_date="1546-01-01", end_date="1589-01-01"),
        Node(id="ex:event:정여립의 난", type="event", label="정여립의 난",
             source="extract"),
        # 왕의 휘는 별칭이 여럿에 걸린다 — 라벨 일치가 이겨야 한다
        Node(id="wd:Q100", type="person", label="조선 예종", source="wd"),
        Node(id="wd:Q101", type="person", label="이황", source="wd"),
        Node(id="ex:person:이황", type="person", label="이황", source="extract"),
        # 이름은 맞는데 시대가 어긋나는 것
        Node(id="wd:Q200", type="person", label="한유", source="wd",
             start_date="0768-01-01", end_date="0824-12-25"),
        Node(id="ex:person:창려", type="person", label="창려", source="extract"),
        Node(id="wd:Q201", type="person", label="김종직", source="wd",
             start_date="1431-01-01", end_date="1491-08-19"),
    ])
    store.upsert_edges([
        Edge(src="wd:Q704854", dst="wd:Q7836645", type="participated_in", source="wd"),
        Edge(src="ex:person:창려", dst="wd:Q201", type="related_to", source="extract"),
    ])
    store.conn.executemany(
        "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)",
        [("wd:Q7836645", "정여립의 난"), ("wd:Q7836645", "정여립의 옥사"),
         ("wd:Q100", "이황"), ("wd:Q200", "창려")],
    )
    store.conn.commit()

    plan = {m["ex_id"]: m for m in local_matches(store)}
    check("별칭으로 매칭", plan["ex:event:정여립의 난"]["target"] == "wd:Q7836645")
    check("별칭 매칭에 방법 기록",
          plan["ex:event:정여립의 난"]["method"] == "alias_exact")
    # 라벨이 정확히 같은 wd:Q101 이 있으므로 별칭(wd:Q100)이 이기면 안 된다
    check("라벨 일치가 별칭보다 앞선다", plan["ex:person:이황"]["target"] == "wd:Q101")
    check("별칭이 맞아도 시대가 어긋나면 매칭하지 않음", "ex:person:창려" not in plan)

    merge_node(store, "ex:event:정여립의 난", "wd:Q7836645", method="alias_exact")
    check("병합 뒤 사건에 정여립이 붙는다",
          store.conn.execute(
              "SELECT 1 FROM edges WHERE src='wd:Q704854' AND dst='wd:Q7836645'"
          ).fetchone() is not None)
    check("병합 뒤 빈 노드가 사라진다",
          store.conn.execute(
              "SELECT 1 FROM nodes WHERE id='ex:event:정여립의 난'"
          ).fetchone() is None)
    store.close()

# 타입을 고치면 그 노드에 걸린 엣지가 스키마와 어긋난다. 버리지 않는다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "q.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q1", type="person", label="어떤 인물", source="wd"),
        Node(id="ex:role:병조판서", type="role", label="병조판서", source="extract"),
        Node(id="wd:Q9", type="event", label="어떤 사건", source="wd"),
        Node(id="ex:person:고아", type="person", label="고아", source="extract"),
    ])
    store.conn.executemany(
        "INSERT INTO edges (src,dst,type,source,confidence,props) VALUES (?,?,?,?,?,'{}')",
        [
            # person -> role 인데 child_of 라 스키마 위반
            ("wd:Q1", "ex:role:병조판서", "child_of", "extract", 0.7),
            # 방향만 뒤집으면 맞는 엣지
            ("wd:Q9", "wd:Q1", "participated_in", "extract", 0.9),
        ],
    )
    store.conn.commit()
    fixed = relax_invalid_edges(store)
    check("뒤집으면 맞는 엣지는 방향 교정", fixed["flipped"] == 1)
    check("교정된 방향이 저장됨",
          store.conn.execute(
              "SELECT 1 FROM edges WHERE src='wd:Q1' AND dst='wd:Q9' AND type='participated_in'"
          ).fetchone() is not None)
    check("못 맞추면 related_to 로 완화", fixed["relaxed"] == 1)
    row = store.conn.execute(
        "SELECT type, props FROM edges WHERE dst='ex:role:병조판서'"
    ).fetchone()
    check("완화해도 원래 타입은 남김",
          row["type"] == "related_to" and _json.loads(row["props"])["original_type"] == "child_of")

    check("엣지 없는 ex 노드 제거", prune_orphans(store) == 1)
    check("엣지 있는 ex 노드는 유지",
          store.conn.execute("SELECT 1 FROM nodes WHERE id='ex:role:병조판서'").fetchone()
          is not None)
    store.close()

print("\n[위키백과 커넥터]")
from histgraph.sources import wikipedia  # noqa: E402

check("API 엔드포인트가 한국어 위키백과", wikipedia.API_URL.startswith("https://ko.wikipedia.org"))
check("인트로 배치 상한 20 (extracts API 제약)", wikipedia.INTRO_BATCH == 20)

# 시드 목록은 도메인 데이터라 오타가 조용히 유실을 만든다
seeds = wikipedia.EVENT_SEEDS
all_titles = [t for v in seeds.values() for t in v]
check("시드 사건에 중복 없음", len(all_titles) == len(set(all_titles)))
check("시드 시대가 모두 왕조 매핑에 존재", all(
    era in PERIOD_TO_POLITY or era in ("일제강점기", "대한민국") for era in seeds
))
# '대한제국'을 사건으로 넣으면 from_period 가 자기 자신을 가리킨다
check("시대 이름이 사건 목록에 없음", not (set(seeds) & set(all_titles)))

print("\n[이름이 엉뚱한 노드에 붙은 엣지 — 전수 조사]")
# 실측: 태조의 아들 관계가 관계 24건짜리 조선 정종이 아니라 엣지 1개짜리
# 동명 노드에 붙어, 화면에서 정종이 아버지도 형제도 없는 외톨이가 됐다.
from histgraph.promote import audit_links, repair_links  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "rl.sqlite")
    store.upsert_nodes([
        Node(id="wd:D1", type="event", label="갑자사화", source="wd",
             props={"seed_era": "조선"}),
        Node(id="wd:J", type="person", label="조선 태조", source="wd"),
        Node(id="wd:G", type="person", label="고려 태조", source="wd"),
        Node(id="ex:person:태조", type="person", label="태조", source="extract"),
        # 진짜 동명이인 — 차수가 엇비슷하면 옮기지 않는다
        Node(id="wd:K1", type="person", label="김구", source="wd"),
        Node(id="wd:K2", type="person", label="김구", source="wd"),
        Node(id="wd:X", type="person", label="누구", source="wd"),
    ])
    store.upsert_edges([
        # 조선 태조는 이미 잘 연결돼 있고, 고려 태조도 그래프에 있다
        Edge(src="wd:J", dst="wd:D1", type="participated_in", source="wd"),
        Edge(src="wd:J", dst="wd:X", type="child_of", source="wd"),
        Edge(src="wd:G", dst="wd:X", type="child_of", source="wd"),
        # 조선 문서에서 나온 추출 엣지가 고아 '태조'에 붙어 있다
        Edge(src="ex:person:태조", dst="wd:D1", type="participated_in",
             source="extract", confidence=0.9, props={"extracted_from": "wd:D1"}),
        Edge(src="wd:K1", dst="wd:D1", type="participated_in", source="extract",
             confidence=0.9, props={"extracted_from": "wd:D1"}),
        Edge(src="wd:K2", dst="wd:X", type="related_to", source="wd"),
    ])

    report = audit_links(store)
    moves = {m["label"]: m for m in report["moves"]}
    check("문서 시대로 동명이인을 가른다",
          moves.get("태조", {}).get("target") == "wd:J", str(report["moves"]))
    check("판정 근거를 남긴다", moves.get("태조", {}).get("method") == "시대일치")
    held = {a["label"] for a in report["ambiguous"]}
    check("차수가 엇비슷하면 보류", "김구" in held or not moves.get("김구"), str(report))
    check("이상 없는 끝점이 대부분", report["ok"] > 0)

    repair_links(store)
    check("추출 엣지가 옳은 노드로 옮겨짐",
          store.conn.execute(
              "SELECT 1 FROM edges WHERE src='wd:J' AND dst='wd:D1' AND source='extract'"
          ).fetchone() is not None)
    check("옮긴 자리에 출처를 남김",
          "repaired_from" in (store.conn.execute(
              "SELECT props FROM edges WHERE src='wd:J' AND source='extract'"
          ).fetchone()[0]))
    check("구조화 엣지는 건드리지 않음",
          store.conn.execute(
              "SELECT COUNT(*) FROM edges WHERE source='wd'"
          ).fetchone()[0] == 4)
    check("두 번 돌려도 더 옮길 것이 없다", repair_links(store)["moves"] == [])
    store.close()

# --- 조직·왕조의 존속 기간 (Wikidata P571/P576) --------------------------
# 실측 회귀: 수집이 조직에는 날짜를 한 번도 물어본 적이 없어서, 조선
# 그래프의 org 80개가 전부 날짜 없음이었다 — 그 안에 이 그래프의 중심인
# 조선이 있었다 (Wikidata 에는 1392-08-13 ~ 1897-10-12 로 적혀 있다).
def _b(uri, **kw):
    row = {"o": {"value": uri}}
    row.update({k: {"value": v} for k, v in kw.items()})
    return row

spans = wikidata.spans_from_rows([
    _b("http://www.wikidata.org/entity/Q28179",
       inception="1392-08-13T00:00:00Z", dissolved="1897-10-12T00:00:00Z"),
    # 설립/해체가 없으면 시작/종료로 물러난다
    _b("http://www.wikidata.org/entity/Q1", start="1616-01-01T00:00:00Z"),
    # 끝이 시작보다 앞선 값은 통째로 버린다 (Wikidata 날짜는 지저분하다)
    _b("http://www.wikidata.org/entity/Q2",
       inception="1700-01-01T00:00:00Z", dissolved="1600-01-01T00:00:00Z"),
    # '값 불명' blank node 는 날짜가 아니다
    _b("http://www.wikidata.org/entity/Q3",
       inception="http://www.wikidata.org/.well-known/genid/a808c9f"),
])
check("설립·해체를 읽는다", spans.get("Q28179") == ("1392-08-13", "1897-10-12"), str(spans))
check("설립이 없으면 시작으로 물러난다", spans.get("Q1") == ("1616-01-01", None))
check("끝이 시작보다 앞서면 버린다", "Q2" not in spans, str(spans))
check("'값 불명'은 날짜가 아니다", "Q3" not in spans, str(spans))
check("재건된 조직은 가장 이른 설립·가장 늦은 해체",
      wikidata.spans_from_rows([
          _b("http://www.wikidata.org/entity/Q9", inception="1920-01-01T00:00:00Z",
             dissolved="1930-01-01T00:00:00Z"),
          _b("http://www.wikidata.org/entity/Q9", inception="1910-01-01T00:00:00Z",
             dissolved="1940-01-01T00:00:00Z"),
      ]).get("Q9") == ("1910-01-01", "1940-01-01"))

print("\n[탐색 서버]")
from histgraph.server import GraphAPI, TYPE_GROUP, safe_static_path  # noqa: E402

check("모든 노드 타입에 색 갈래가 있음", set(TYPE_GROUP) == set(NODE_TYPES))

# 기축옥사의 별칭은 셋인데 무게가 다르다. '정여립의 난' 은 이 사건을 부르는
# **또 하나의 이름**이고 나머지 둘은 표기 변형이다. 셋을 한 더미에 넣으면
# 그 이름이 별명처럼 읽힌다 — 화면에서 안 보였고, 지적받은 자리다.
from histgraph.server import co_names  # noqa: E402

check("병합해 들인 이름은 또 하나의 이름",
      co_names("기축옥사", _json.dumps({"merged_from": [{"label": "정여립의 난"}]}))
      == ["정여립의 난"])
check("길고 짧은 같은 이름은 세우지 않음",
      co_names("조선 세조", _json.dumps({"merged_from": [{"label": "세조"}]})) == [])
check("라벨과 같은 이름은 빼기",
      co_names("기축옥사", _json.dumps({"merged_from": [{"label": "기축옥사"}]})) == [])
check("병합 이력이 없으면 없음", co_names("아무개", None) == []
      and co_names("아무개", "{}") == [])
check("깨진 props 에도 죽지 않음", co_names("아무개", "{not json") == [])
check("같은 이름이 두 번 들어와도 한 번",
      co_names("진주대첩", _json.dumps({"merged_from": [
          {"label": "제1차 진주성 전투"}, {"label": "제1차 진주성 전투"}]}))
      == ["제1차 진주성 전투"])

# 색은 갈래만 말하고 타입은 모양이 말한다 — 갈래가 넷을 넘으면 색약에서
# 구분이 무너진다 (검증기 실측: 8색 전체 조합 최악 ΔE 1.6)
check("색 갈래는 4개 이하", len(set(TYPE_GROUP.values())) <= 4)

check("루트 밖 경로 거부", safe_static_path("/../.env") is None)
check("URL 인코딩으로 우회 불가", safe_static_path("/%2e%2e/%2e%2e/.env") is None)
check("존재하지 않는 파일은 None", safe_static_path("/없는파일.js") is None)
check("정상 파일은 통과", safe_static_path("/index.html") is not None)

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "s.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q1", type="person", label="조선 세종", source="wd",
             start_date="1397-04-10", end_date="1450-02-17", description="세종은 " * 40),
        Node(id="wd:Q2", type="event", label="훈민정음 반포", source="wd"),
        Node(id="wd:Q3", type="place", label="세종", source="khs"),
        Node(id="wd:Q4", type="period", label="1443년", source="timeline"),
        Node(id="wd:Q5", type="person", label="이방원", source="wd"),
        Node(id="wd:Q28179", type="org", label="조선", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:Q1", dst="wd:Q2", type="participated_in", source="extract",
             confidence=0.9, props={"evidence": "세종은 훈민정음을 반포하였다"}),
        Edge(src="wd:Q1", dst="wd:Q5", type="child_of", source="wd"),
        Edge(src="wd:Q1", dst="wd:Q4", type="dated_to", source="timeline", label="출생"),
    ])
    api = GraphAPI(store, era="joseon")

    # 실측 회귀: '세종'을 치면 세종특별자치시가 조선 세종보다 먼저 나왔다
    hits = api.search("세종")
    check("검색은 차수 높은 쪽을 먼저", hits[0]["id"] == "wd:Q1", str(hits[:2]))
    check("부분 일치도 찾음", any(h["id"] == "wd:Q3" for h in hits))
    check("빈 검색어는 빈 결과", api.search("  ") == [])
    # 실측 회귀: '1974'를 치면 연표 눈금 time:1974 가 첫 줄로 나와 엔터가 열었다
    check("연표 눈금 노드는 검색에 안 나온다",
          all(h["id"] != "wd:Q4" for h in api.search("1443")), str(api.search("1443")))

    g = api.graph("wd:Q1", depth=1)
    check("연도 노드는 기본적으로 빼고 그린다",
          all(n["type"] != "period" for n in g["nodes"]), str(g["nodes"]))
    check("연도 노드를 빼면 그 엣지도 사라짐",
          all(e["type"] != "dated_to" for e in g["edges"]))
    check("연도를 켜면 다시 들어옴",
          any(n["type"] == "period" for n in api.graph("wd:Q1", exclude=())["nodes"]))
    check("노드에 색 갈래가 실림", g["nodes"][0]["group"] in ("actor", "event", "thing", "frame"))
    check("없는 노드는 missing", api.graph("wd:없음")["missing"] is True)

    d = api.node("wd:Q1")
    check("상세에 관계가 붙음", len(d["relations"]) == 3)
    # 근거를 화면에 못 띄우면 사용자는 0.9 짜리 엣지를 믿을지 판단할 수 없다
    ev = [r for r in d["relations"] if r["evidence"]]
    check("추출 관계는 근거 구절을 함께 준다",
          len(ev) == 1 and ev[0]["evidence"][0].startswith("세종은"))
    # 화면은 타고 들어온 관계를 문장으로 적는다 ("세종은 1443년에 태어났다").
    # 타입 라벨('시점')만으로는 출생인지 사망인지 말할 수 없다.
    dated = [r for r in d["relations"] if r["type"] == "dated_to"]
    check("엣지 자신의 이름이 상세에 실림", dated[0]["edge_label"] == "출생", str(dated))
    check("이름 없는 엣지는 None",
          [r for r in d["relations"] if r["type"] == "child_of"][0]["edge_label"] is None)
    check("관계에 출처가 실림",
          {s for r in d["relations"] for s in r["sources"]} == {"extract", "wd", "timeline"})
    check("없는 노드 상세는 None", api.node("wd:없음") is None)
    check("메타에 시대가 실림", api.meta()["era"] == "joseon")

    # 조선 그래프의 중심은 조선이다. 차수 1위로 대신하면 열 때마다
    # 병자호란이 중심인 화면이 된다.
    # 회귀: 같은 사실을 Wikidata 와 인포박스가 함께 말하면 화면에 '행주산성'
    # 이 두 번 나왔다. 저장은 소스별로 두고(교차검증의 근거) 화면에는
    # 한 줄로 합친다.
    store.upsert_edges([
        Edge(src="wd:Q1", dst="wd:Q3", type="born_in", source="wd"),
        Edge(src="wd:Q1", dst="wd:Q3", type="born_in", source="kowiki:infobox",
             confidence=0.95),
    ])
    born = [r for r in api.node("wd:Q1")["relations"] if r["type"] == "born_in"]
    check("같은 사실은 한 줄로", len(born) == 1, str(born))
    check("두 소스를 모두 남긴다", set(born[0]["sources"]) == {"wd", "kowiki:infobox"})
    check("신뢰도는 가장 높은 소스 것", born[0]["confidence"] == 1.0)
    g2 = api.graph("wd:Q1", depth=1)
    same = [e for e in g2["edges"] if e["type"] == "born_in"]
    check("그래프에도 선은 하나", len(same) == 1 and len(same[0]["sources"]) == 2)

    check("왕조 노드가 그래프의 중심", api.root() == "wd:Q28179")
    check("시작점 맨 위가 왕조", api.seeds(5)[0]["id"] == "wd:Q28179")
    check("모르는 시대는 중심 없음", GraphAPI(store, era="").root() is None)
    # 인과의 종류(배경·계기·영향)는 그래프 화면이 선 위에 적는다 — 타입 이름
    # '원인'으로 뭉개 보내면 사슬 패널과 그래프가 다른 말을 한다.
    store.upsert_edges([Edge(src="wd:Q2", dst="wd:Q1", type="caused", source="causes", label="배경", confidence=0.8)])
    g3 = api.graph("wd:Q1", depth=1)
    caused = [e for e in g3["edges"] if e["type"] == "caused"]
    check("그래프의 인과 엣지는 종류를 라벨로 준다", len(caused) == 1 and caused[0]["label"] == "배경", str(caused))
    store.close()

with tempfile.TemporaryDirectory() as tmp:
    # 왕조 노드가 없는 그래프에서 중심을 지어내면 안 된다
    store = GraphStore(Path(tmp) / "s2.sqlite")
    store.upsert_nodes([Node(id="wd:Q1", type="person", label="누구", source="wd")])
    empty_api = GraphAPI(store, era="joseon")
    check("왕조 노드가 없으면 중심도 없음", empty_api.root() is None)
    check("그래도 시작점은 나온다", isinstance(empty_api.seeds(5), list))
    store.close()

# --- 연표 ---------------------------------------------------------------
# 그래프는 무엇이 무엇과 이어져 있는지만 말한다. 왼쪽 연표가 "몇 년쯤,
# 무엇 뒤 무엇 앞"을 맡는데, 여기서 틀리면 화면이 없는 연도를 지어낸다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "tl.sqlite")
    store.upsert_nodes([
        Node(id="wd:E1", type="event", label="무오사화", source="wd",
             start_date="1498-07-01", end_date="1498-07-01"),
        # 날짜가 없고 연도 노드로만 이어진 사건 (실측: 갑자사화가 그렇다)
        Node(id="wd:E2", type="event", label="갑자사화", source="wd"),
        Node(id="wd:E3", type="event", label="중종반정", source="wd", start_date="1506"),
        Node(id="wd:E4", type="event", label="임진왜란", source="wd", start_date="1592"),
        # 400년 밖 — 이어져 있어도 '그 무렵'이 아니다
        Node(id="wd:E5", type="event", label="청산리 전투", source="wd", start_date="1920"),
        Node(id="time:1504", type="period", label="1504년", source="timeline",
             start_date="1504"),
        Node(id="wd:P1", type="person", label="조선 연산군", source="wd",
             start_date="1476", end_date="1506"),
        # 몰년만 아는 인물 — 생년으로 읽으면 안 된다
        Node(id="wd:P2", type="person", label="서장옥", source="wd",
             start_date="1900-01-01", end_date="1900-01-01"),
        # 연도를 전혀 모르는 유물
        Node(id="khs:H1", type="heritage", label="훈민정음", source="khs"),
        # 한 십년에 몰린 사건 셋 — 솎지 않고 다 세운다
        Node(id="wd:D1", type="event", label="사건가", source="wd", start_date="1560"),
        Node(id="wd:D2", type="event", label="사건나", source="wd", start_date="1562"),
        Node(id="wd:D3", type="event", label="사건다", source="wd", start_date="1565"),
        # 이름도 해도 같은 다른 노드 (실측: 임진왜란이 wd:Q122846639 과
        # wd:Q576338 둘로 있다). 화면에서 둘은 구별되지 않는다.
        Node(id="wd:DUP", type="event", label="사건가", source="wd", start_date="1560"),
        Node(id="wd:P3", type="person", label="아무개", source="wd",
             start_date="1530", end_date="1580"),
        # 산문에서 이름만 뽑혀 나온 사건. 엣지가 하나면 아무도 확인해 주지
        # 않은 것이다 (실측: '1963년 문집 간행'이 축을 1963년까지 늘렸다)
        Node(id="ex:event:홀로", type="event", label="문집 간행", source="extract",
             start_date="1700"),
        Node(id="ex:event:여럿", type="event", label="진산사건", source="extract",
             start_date="1710"),
        # 왕조 자신. org 라서 사건 뼈대에는 못 들어오지만 연표에는 서야
        # 한다 — 실측: 1392년 자리가 비어 위화도 회군 다음이 곧장 제1차
        # 왕자의 난이었다.
        Node(id="wd:Q28179", type="org", label="조선", source="wd",
             start_date="1392-08-13", end_date="1897-10-12"),
        # 건국 앞의 고려 사건. 맥락으로 그래프에 남지만 연표는 조선에서
        # 시작한다 (실측: 1100년 '삼사'가 축을 1097년부터 늘여 놓았다).
        # 조선 시대의 뒷부분인 나라 — 시대가 아니라도 자기 건국을 알린다
        Node(id="wd:Q28233", type="org", label="대한제국", source="wd",
             start_date="1897-10-12", end_date="1910-08-29"),
        Node(id="wd:G1", type="event", label="위화도 회군", source="wd",
             start_date="1388-06-11"),
        Node(id="wd:G0", type="event", label="삼사", source="wd", start_date="1100"),
        # 건국보다 먼저 태어난 사람 — 자기 자리는 서야 한다
        Node(id="wd:P4", type="person", label="조선 태조", source="wd",
             start_date="1335-10-19", end_date="1408-06-18"),
        # 같은 해의 인과. 둘 다 뼈대라 고른 노드의 `rel` 로는 알 수 없다
        # (실측: 한일병합과 무단통치가 같은 날 1910-08-29 이다).
        Node(id="wd:C1", type="event", label="앞선 일", source="wd",
             start_date="1600-05-01"),
        Node(id="wd:C2", type="event", label="뒤의 일", source="wd", start_date="1600"),
        Node(id="wd:C3", type="event", label="이듬해 일", source="wd", start_date="1601"),
    ])
    store.upsert_edges([
        Edge(src="wd:E2", dst="time:1504", type="from_period", source="timeline"),
        Edge(src="wd:P1", dst="wd:E2", type="participated_in", source="wd"),
        Edge(src="wd:P2", dst="wd:E2", type="participated_in", source="extract"),
        Edge(src="wd:E2", dst="wd:E1", type="related_to", source="wd"),
        Edge(src="wd:E2", dst="wd:E4", type="related_to", source="wd"),
        Edge(src="wd:E2", dst="wd:E5", type="related_to", source="wd"),
        Edge(src="wd:E1", dst="wd:E3", type="related_to", source="wd"),
        Edge(src="wd:P3", dst="wd:D1", type="participated_in", source="wd"),
        Edge(src="wd:P3", dst="wd:D2", type="participated_in", source="wd"),
        Edge(src="wd:D1", dst="wd:D2", type="related_to", source="wd"),
        Edge(src="ex:event:홀로", dst="wd:E5", type="related_to", source="extract"),
        Edge(src="ex:event:여럿", dst="wd:E5", type="related_to", source="extract"),
        Edge(src="ex:event:여럿", dst="wd:D3", type="related_to", source="extract"),
        Edge(src="wd:G1", dst="wd:E1", type="related_to", source="wd"),
        Edge(src="wd:G0", dst="wd:E1", type="related_to", source="wd"),
        Edge(src="wd:G1", dst="wd:G0", type="related_to", source="wd"),
        Edge(src="wd:P4", dst="wd:G1", type="participated_in", source="wd"),
        Edge(src="wd:C1", dst="wd:C2", type="caused", source="extract"),
        Edge(src="wd:C1", dst="wd:C3", type="caused", source="extract"),
    ])
    tl_api = GraphAPI(store, era="joseon")

    t = tl_api.timeline("wd:E2")
    kinds = {m["id"]: m["kind"] for m in t["marks"]}
    check("날짜가 없어도 연도 노드로 이어지면 연도를 안다", t["year"] == 1504)
    check("어디서 알았는지 함께 말한다", t["year_source"] == "edge")
    check("고른 노드가 연표에 자기 자리로 선다", kinds.get("wd:E2") == "self")
    # 실측 회귀: 갑자사화(1504) 참여자 명단에 1955년생 정성근이 있다.
    # 사람을 한 점에 찍으면 "1427년에 참여했다"로 읽히고, 축도 늘어난다.
    check("사람은 연표의 점이 되지 않는다",
          all(m["type"] != "person" for m in t["marks"]), str(t["marks"]))
    check("앞뒤 사건이 함께 선다",
          kinds.get("wd:E1") and kinds.get("wd:E3"), str(kinds))
    # 실측: 갑자사화 참여자에 1955년생이 섞여 있었다. 그대로 세우면 축이
    # 450년으로 늘어나 정작 사화 앞뒤가 몇 픽셀로 뭉개진다.
    check("400년 밖의 이웃은 연표에 세우지 않는다", kinds.get("wd:E5") != "near", str(kinds))
    check("축이 표시들을 모두 담는다",
          t["axis"]["from"] <= min(m["year"] for m in t["marks"])
          and t["axis"]["to"] >= max(m["year"] for m in t["marks"]))

    t1 = tl_api.timeline("wd:E1")
    check("이어진 사건은 이웃으로 선다",
          [m["kind"] for m in t1["marks"] if m["id"] == "wd:E2"] == ["near"])
    check("이웃에는 관계 이름이 붙는다",
          [m["rel"]["label"] for m in t1["marks"] if m["id"] == "wd:E2"] == ["관련"])

    # 생년=몰년은 몰년만 아는 인물이다. 그대로 찍으면 1900년 사람이 된다.
    check("생년=몰년인 인물은 연도가 없는 셈", tl_api.timeline("wd:P2")["year"] is None)
    check("인물의 생몰은 구간으로 말한다",
          (tl_api.timeline("wd:P1")["year"], tl_api.timeline("wd:P1")["end"]) == (1476, 1506))

    # 아무것도 모르는 개체를 축 위에 세우면 모르는 것을 아는 척한 것이 된다
    h = tl_api.timeline("khs:H1")
    check("연도를 모르면 시대만 펼친다", h["basis"] == "era" and h["year"] is None)
    check("그래도 볼 것은 준다", len(h["marks"]) > 0)
    check("없는 노드의 연표는 None", tl_api.timeline("wd:없음") is None)

    # **축은 고른 노드와 무관하다.** 노드마다 잘라 보내면 위아래로 훑어도
    # 시대의 양 끝에 닿지 못하고, 축이 달라 노드끼리 자리를 견줄 수 없다.
    check("어느 노드를 골라도 같은 축 위에 선다",
          tl_api.timeline("wd:E1")["axis"] == tl_api.timeline("wd:E3")["axis"],
          str(tl_api.timeline("wd:E1")["axis"]))

    # **원인은 결과보다 위에 선다** (CLAUDE.md 1-5). 화면은 고른 노드에 달린
    # 관계만으로는 둘 다 뼈대인 쌍의 인과를 모른다 — 같은 해에 함께 선
    # 마크들 사이의 인과를 아이디 쌍으로 함께 보낸다 (2026-09-08 지적).
    check("같은 해에 함께 선 마크들 사이의 인과를 보낸다",
          ["wd:C1", "wd:C2"] in t["causes"], str(t["causes"]))
    check("해가 다른 쌍은 보내지 않는다",
          ["wd:C1", "wd:C3"] not in t["causes"], str(t["causes"]))
    check("보내는 것은 아이디 쌍뿐이다",
          all(len(c) == 2 and all(isinstance(x, str) for x in c) for c in t["causes"]),
          str(t["causes"]))

    bones = {m["id"] for m in t["marks"] if m["kind"] == "anchor"}
    # 연표에서 빠진 사건은 그 시대에 없었던 일이 된다. 한 십년에 몰려
    # 있어도(조선 1590년대에 20건) 솎지 않는다.
    check("한 십년에 몰려도 연대를 아는 사건은 다 선다",
          {"wd:D1", "wd:D2", "wd:D3"} <= bones, str(bones))
    check("이름도 해도 같으면 차수 높은 쪽만 남는다",
          "wd:DUP" not in bones, str(bones))
    check("확인해 준 데가 없는 추출 고아는 뼈대가 못 된다",
          "ex:event:홀로" not in bones, str(bones))
    check("여럿이 가리키는 추출 사건은 뼈대로 남는다",
          "ex:event:여럿" in bones, str(bones))

    # 왕조는 org 라 사건 뼈대에 못 들어온다. 그렇다고 빼면 연표에 건국이
    # 없는 시대가 된다 — 자기 존속 기간으로 따로 세운다.
    era_mark = [m for m in t["marks"] if m["kind"] == "era"]
    check("왕조가 자기 존속 기간으로 연표에 선다",
          [(m["id"], m["year"], m["end"]) for m in era_mark]
          == [("wd:Q28179", 1392, 1897), ("wd:Q28233", 1897, 1910)], str(era_mark))
    # 이름만 세우면 '조선'이 1392년에 무엇을 했다는 것처럼 읽힌다. 화면이
    # '건국'을 달 수 있게 나라라고 표식한다 (2026-09-05 사용자 요청).
    check("나라 표식에는 건국 표식이 붙는다", all(m.get("founded") for m in era_mark))
    check("사건 뼈대에는 건국 표식이 없다",
          not any(m.get("founded") for m in t["marks"] if m["kind"] == "anchor"))
    # **연표는 조선 건국에서 시작한다.** 고려 사건은 맥락으로 그래프에
    # 남지만 축을 1100년까지 늘이지 않는다.
    check("건국 앞의 사건은 연표에 서지 않는다",
          not any(m["year"] < 1392 for m in t["marks"]),
          str([(m["label"], m["year"]) for m in t["marks"] if m["year"] < 1392]))
    check("축은 건국 몇 해 앞에서 시작한다", t["axis"]["from"] == 1389, str(t["axis"]))
    e1 = tl_api.timeline("wd:E1")
    check("건국 앞의 이웃도 서지 않는다",
          "wd:G1" not in {m["id"] for m in e1["marks"]})
    # 고른 노드가 건국보다 앞서면 그 해까지는 연다 — 자기 자리를 못 세우는
    # 연표는 연표가 아니다. 그 뒤의 이웃도 함께 산다.
    g1 = tl_api.timeline("wd:G1")
    g1_ids = {m["id"]: m["year"] for m in g1["marks"]}
    check("건국 앞의 사건을 고르면 자기 자리로 선다", g1_ids.get("wd:G1") == 1388, str(g1_ids))
    check("그래도 그보다 더 앞은 열지 않는다", "wd:G0" not in g1_ids, str(g1_ids))
    check("건국 앞 사건을 골라도 조선 건국은 선다", g1_ids.get("wd:Q28179") == 1392)
    p4 = tl_api.timeline("wd:P4")
    check("건국보다 먼저 난 사람은 생년에 선다",
          p4["year"] == 1335 and any(m["id"] == "wd:G1" for m in p4["marks"]),
          str([(m["id"], m["year"]) for m in p4["marks"]]))
    # 왕조를 고르면 그건 '자기 자리'다. 둘 다 세우면 같은 줄이 두 번 찍힌다.
    own = tl_api.timeline("wd:Q28179")
    check("왕조를 고르면 자기 자리로만 선다",
          [m["kind"] for m in own["marks"] if m["id"] == "wd:Q28179"] == ["self"],
          str([m for m in own["marks"] if m["id"] == "wd:Q28179"]))
    check("나라 자신을 골라도 건국 표식은 붙는다",
          [m.get("founded") for m in own["marks"] if m["id"] == "wd:Q28179"] == [True])
    store.close()

# --- 재시도가 질문을 바꿔치기하지 않는가 ---------------------------------
# 실측 회귀: HTTPError 처리에서 응답 본문을 `body` 에 담았는데, 그 `body` 가
# 다음 재시도에 보낼 **요청 본문**이었다. 503 한 번에 SPARQL 질문이 오류
# HTML 로 바뀌어 POST 되고, 그 응답이 원래 질문의 캐시 자리에 들어앉는다 —
# 사건 관계 수집에서 한 구간 98건이 그렇게 조용히 사라졌다.
import io  # noqa: E402
import time as _time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from histgraph import http as http_mod  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    sent: list[bytes | None] = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        sent.append(req.data)
        if len(sent) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 503, "busy", {}, io.BytesIO(b"<html>overloaded</html>"))
        return _Resp(b'{"results": {"bindings": []}}')

    real_urlopen, real_sleep = urllib.request.urlopen, _time.sleep
    urllib.request.urlopen = fake_urlopen
    http_mod.time.sleep = lambda _s: None
    try:
        f = http_mod.Fetcher(Path(tmp) / "cache", min_interval=0, retries=3)
        out = f.post("https://example.test/sparql", {"query": "SELECT ?x WHERE {}"})
    finally:
        urllib.request.urlopen = real_urlopen
        http_mod.time.sleep = real_sleep

    check("재시도가 같은 질문을 다시 보낸다", sent[0] == sent[1], str(sent))
    check("재시도 응답을 그대로 돌려준다", out.startswith('{"results"'), out[:40])
    check("오류 본문이 요청에 섞이지 않는다", b"overloaded" not in (sent[1] or b""), str(sent[1]))

# --- 사건 사이의 뼈대 ----------------------------------------------------
# 실측 회귀: '왕자의 난'은 제1차·제2차와 아무 엣지도 없이 홀로 서 있었다
# (연결 0건). 수집이 인물↔사건(P1344)만 물어봐서 사건끼리는 서로를 모른다.
# 연표에서 나란히 서니 이어져 보였을 뿐이다.
from histgraph.sources.wikidata import links_from_rows  # noqa: E402

_E = "http://www.wikidata.org/entity/"


def _lk(a, prop, b):
    return {"e": {"value": _E + a},
            "prop": {"value": "http://www.wikidata.org/prop/direct/" + prop},
            "v": {"value": _E + b}}


links = links_from_rows([
    _lk("Q624181", "P361", "Q12608468"),   # 제1차는 왕자의 난의 일부
    _lk("Q12608468", "P527", "Q624181"),   # 왕자의 난은 제1차로 이루어짐 (같은 사실)
    _lk("Q624181", "P156", "Q624222"),     # 제1차 다음은 제2차
    _lk("Q624222", "P155", "Q624181"),     # 제2차 이전은 제1차 (같은 사실)
    _lk("Q1", "P361", "Q1"),               # 자기 자신의 일부인 사건은 없다
    _lk("Q2", "P361", "genid-abc"),        # 값 불명(blank node)
])
check("상하위는 하위에서 상위로 한 방향으로 모은다",
      ("Q624181", "Q12608468", "part_of", "") in links, str(links))
check("P527 은 방향을 뒤집어 같은 엣지가 된다", len(
    [x for x in links if x[2] == "part_of"]) == 1, str(links))
check("전후는 앞선 사건에서 뒤 사건으로 모은다",
      ("Q624181", "Q624222", "related_to", "다음") in links, str(links))
check("P155 는 P156 과 같은 엣지로 접힌다",
      len([x for x in links if x[2] == "related_to"]) == 1, str(links))
check("자기 자신을 잇지 않는다", not any(x[0] == x[1] for x in links), str(links))
check("QID 가 아닌 값은 버린다", not any("genid" in x[1] for x in links), str(links))

# 사건이 자기 쪽에 적어 둔 나머지 관계 — 수집이 한 번도 안 물어본 것들
side = links_from_rows([
    _lk("Q1", "P710", "Q2"),      # 옥포 해전의 참가자 이순신
    _lk("Q1", "P828", "Q3"),      # 병인양요의 원인은 병인박해
    _lk("Q3", "P1542", "Q1"),     # 병인박해의 결과는 병인양요 (같은 사실)
    _lk("Q1", "P276", "Q4"),      # 위화도 회군은 개성에서
])
check("사건이 적어 둔 참가자는 참여 엣지가 된다 (방향은 사람 → 사건)",
      ("Q2", "Q1", "participated_in", "") in side, str(side))
check("원인·결과는 원인에서 결과로 한 방향 (인과 엣지)", ("Q3", "Q1", "caused", "원인") in side, str(side))
check("원인과 결과가 같은 엣지로 접힌다",
      len([x for x in side if x[3] == "원인"]) == 1, str(side))
check("장소는 발생 장소 엣지가 된다", ("Q1", "Q4", "occurred_at", "") in side, str(side))

# --- 사건의 시대: props 에만 있고 엣지로는 없던 것 -----------------------
# 실측: 같은 사실이 소스에 따라 갈려 있었다. 위키백과 사건은 from_period
# 엣지로 조선에 붙는데 Wikidata 사건은 props.polity 칸에만 있어서, 화면에
# 아무 관계도 없는 노드로 떴다 (조선 그래프 105건).
from histgraph.resolve import link_event_periods  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "ep.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q28179", type="org", label="조선", source="wd"),
        Node(id="wd:E1", type="event", label="무고의 옥", source="wd",
             props={"polity": "조선"}),
        Node(id="wd:E2", type="event", label="고구려 부흥운동", source="wd",
             props={"polity": "고구려"}),        # 왕조 노드가 없다
        Node(id="wd:E3", type="event", label="갑자사화", source="wd",
             props={"polity": "조선"}),
        Node(id="wd:E4", type="event", label="연도만 아는 일", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:E3", dst="wd:Q28179", type="from_period", source="kowiki"),
    ])
    n = link_event_periods(store)
    got = {(r[0], r[1]) for r in store.conn.execute(
        "SELECT src, dst FROM edges WHERE type='from_period'")}
    check("props 에만 있던 시대를 엣지로 세운다", ("wd:E1", "wd:Q28179") in got, str(got))
    check("왕조 노드가 없으면 잇지 않는다", not any(s == "wd:E2" for s, _ in got), str(got))
    check("이미 이어진 것은 다시 세지 않는다", n == 1, n)
    check("두 번 돌려도 늘지 않는다", link_event_periods(store) == 0)
    store.close()

# --- 날짜의 자릿수 -------------------------------------------------------
# 실측 회귀: Wikidata 는 '1592년'을 '1592-01-01' 로 준다. 자릿수는 값이
# 아니라 문장에 붙어 있어서 `wdt:` 로 긁는 수집이 못 가져왔고, DB 에는
# 연도만 아는 날이 전부 1월 1일로 앉아 있었다(전체 그래프 7,117개).
# 연표가 몰린 해를 늘려 세우면서 그 안의 차례가 시간 순으로 읽히게 되자,
# 지어낸 1월 1일이 4월의 동래성 전투 앞에 서는 것이 거짓말이 됐다.
from histgraph.server import _year as _server_year  # noqa: E402
from histgraph.promote import _year_of as _promote_year  # noqa: E402
from histgraph.sources.wikidata import (  # noqa: E402
    precision_from_rows, trim_to_precision,
)


def _pv(qid, t, prec):
    return {"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
            "t": {"value": t}, "prec": {"value": str(prec)}}


pv = precision_from_rows([
    _pv("Q12615813", "1592-01-01T00:00:00Z", 9),     # 정암진 전투 — 연도만
    _pv("Q497348", "1592-04-15T00:00:00Z", 11),      # 동래성 전투 — 날까지
    # 같은 날짜가 두 문장에 서로 다른 자릿수로 (선조의 생년)
    _pv("Q484359", "1552-11-21T00:00:00Z", 11),
    _pv("Q484359", "1552-11-21T00:00:00Z", 9),
    # 값 불명은 blank node 로 온다 — 날짜가 아니면 담지 않는다
    _pv("Q1", "http://www.wikidata.org/.well-known/genid/abc", 9),
])
check("문장에서 날짜 자릿수를 읽는다", pv["Q12615813"]["1592-01-01"] == 9, str(pv))
check("날까지 아는 날은 자릿수 11", pv["Q497348"]["1592-04-15"] == 11, str(pv))
check("같은 날짜가 여러 자릿수면 정밀한 쪽을 남긴다",
      pv["Q484359"]["1552-11-21"] == 11, str(pv))
check("날짜로 읽히지 않는 값은 담지 않는다", "Q1" not in pv, str(pv))

check("연도만 아는 날은 해까지 줄인다", trim_to_precision("1592-01-01", 9) == "1592")
check("달까지 아는 날은 달까지 줄인다",
      trim_to_precision("1592-09-01", 10) == "1592-09")
check("날까지 아는 날은 그대로 둔다",
      trim_to_precision("1919-03-01", 11) == "1919-03-01")
# 3·1 운동은 진짜 3월 1일이다. 날이 01 이라고 지어낸 값으로 볼 수 없다.
check("날이 01 이어도 자릿수가 11 이면 지어낸 값이 아니다",
      trim_to_precision("1919-03-01", 11) == "1919-03-01")
check("기원전은 부호 한 칸을 더 센다",
      trim_to_precision("-0037-01-01", 9) == "-0037")
check("십년대처럼 성긴 값도 해까지는 줄인다",
      trim_to_precision("1590-01-01", 8) == "1590")
check("자릿수를 모르면 건드리지 않는다",
      trim_to_precision("1592-01-01", None) == "1592-01-01")
check("날짜가 없으면 없는 대로", trim_to_precision(None, 9) is None)

# 줄인 부분 날짜를 연도로 읽는 쪽이 그대로 돌아야 한다 — 파이프라인은
# 전부 앞 네 자리를 해로 본다.
check("화면이 부분 날짜에서도 해를 읽는다", _server_year("1592") == 1592)
check("승격이 부분 날짜에서도 해를 읽는다", _promote_year("1592") == 1592)
check("기원전 부분 날짜에서도 해를 읽는다", _server_year("-0037") == -37)


# --- 왕의 재위 띠 --------------------------------------------------------
# 실측 회귀: held_position 엣지 552개가 전부 날짜 없음이었다. 재위는
# P39 문장의 한정어(pq:P580/P582)에만 있어서 `wdt:` 로 긁는 수집이 한 번도
# 가져온 적이 없다. 그리고 **사망은 재위의 끝이 아니다** — 태조는 1398년에
# 물러나 1408년에 죽었다.
from histgraph.sources.wikidata import reigns_from_rows  # noqa: E402


def _rg(p, pos, s=None, e=None):
    row = {"p": {"value": f"http://www.wikidata.org/entity/{p}"},
           "pos": {"value": f"http://www.wikidata.org/entity/{pos}"}}
    if s:
        row["s"] = {"value": s}
    if e:
        row["e"] = {"value": e}
    return row


rg = reigns_from_rows([
    _rg("Q37682", "Q22304810", "1418-08-19T00:00:00Z", "1450-02-26T00:00:00Z"),
    # 추존왕 — 자리는 있는데 앉은 적이 없다
    _rg("Q492990", "Q22304810"),
    # 같은 짝이 두 번(복위) — 가장 이른 시작, 가장 늦은 끝으로 모은다
    _rg("Q9", "Q1", "1400-01-01T00:00:00Z", "1409-01-01T00:00:00Z"),
    _rg("Q9", "Q1", "1390-01-01T00:00:00Z", "1395-01-01T00:00:00Z"),
    # 끝이 시작보다 앞선 값은 버린다
    _rg("Q8", "Q1", "1500-01-01T00:00:00Z", "1400-01-01T00:00:00Z"),
    # 기원전 — 문자열로 비교하면 순서가 뒤집힌다 (동명성왕)
    _rg("Q7", "Q1", "-0037-01-01T00:00:00Z", "-0019-01-01T00:00:00Z"),
])
check("P39 한정어에서 재위를 읽는다",
      rg[("Q37682", "Q22304810")] == ("1418-08-19", "1450-02-26"), str(rg))
check("추존왕은 재위가 없다", ("Q492990", "Q22304810") not in rg, str(rg))
check("복위는 가장 이른 시작과 가장 늦은 끝으로 모은다",
      rg[("Q9", "Q1")] == ("1390-01-01", "1409-01-01"), str(rg))
check("끝이 시작보다 앞서면 버린다", ("Q8", "Q1") not in rg, str(rg))
check("기원전 재위도 뒤집히지 않는다",
      rg[("Q7", "Q1")] == ("-0037-01-01", "-0019-01-01"), str(rg))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "rg.sqlite")
    store.upsert_nodes([
        Node(id="wd:K1", type="person", label="조선 태조", source="wd",
             start_date="1335", end_date="1408"),
        Node(id="wd:K2", type="person", label="조선 세종", source="wd",
             start_date="1397", end_date="1450"),
        Node(id="wd:K3", type="person", label="조선 원종", source="wd",
             start_date="1580", end_date="1619"),
        Node(id="wd:POS", type="role", label="조선 임금", source="wd"),
        Node(id="wd:OFC", type="role", label="영의정", source="wd"),
        Node(id="wd:P9", type="person", label="황희", source="wd",
             start_date="1363", end_date="1452"),
        Node(id="wd:E1", type="event", label="갑자사화", source="wd",
             start_date="1504"),
        Node(id="wd:Q28179", type="org", label="조선", source="wd",
             start_date="1392", end_date="1897"),
    ])
    store.upsert_edges([
        Edge(src="wd:K1", dst="wd:POS", type="held_position", source="wd",
             start_date="1392-07-25", end_date="1398-09-13", props={"reign": True}),
        Edge(src="wd:K2", dst="wd:POS", type="held_position", source="wd",
             start_date="1418-08-19", end_date="1450-02-26", props={"reign": True}),
        # 추존왕은 날짜가 없다 — 띠에 서면 안 된다
        Edge(src="wd:K3", dst="wd:POS", type="held_position", source="wd"),
        # 왕이 아닌 자리에 날짜가 붙어도 왕의 띠에는 서지 않는다
        Edge(src="wd:P9", dst="wd:OFC", type="held_position", source="wd",
             start_date="1431-09-03", end_date="1449-10-05"),
        Edge(src="wd:E1", dst="wd:Q28179", type="part_of", source="wd"),
    ])
    api = GraphAPI(store, era="joseon")
    band = {r["id"]: r for r in api.timeline("wd:E1")["reigns"]}
    check("재위가 붙은 임금만 띠에 선다", set(band) == {"wd:K1", "wd:K2"}, str(band))
    check("재위 구간을 그대로 넘긴다",
          (band["wd:K2"]["start"], band["wd:K2"]["end"]) == (1418, 1450), str(band))
    # 태조는 1398년에 물러나 1408년에 죽었다. 둘을 한 점으로 합치면
    # 상왕으로 산 10년이 사라진다.
    check("퇴위한 임금의 몰년은 재위 끝과 따로 간다",
          (band["wd:K1"]["end"], band["wd:K1"]["death"]) == (1398, 1408), str(band))
    check("재위 중에 죽었으면 재위 끝이 곧 몰년",
          band["wd:K2"]["death"] == 1450, str(band))
    check("어느 노드를 골라도 같은 띠가 선다",
          api.timeline("wd:K2")["reigns"] == api.timeline("wd:E1")["reigns"])
    # 축을 사건만으로 잡으면 태조가 상왕으로 산 10년이 축 밖으로 밀린다
    check("축이 몰년까지 담는다", api.timeline("wd:E1")["axis"]["to"] >= 1450)
    store.close()

# --- 시대 서브그래프: 장소 보강 -----------------------------------------
# 실측 회귀: '위화도 회군'이 이성계의 이웃으로 서브그래프에 들어왔는데
# 위화도는 두 홉 밖이라 잘려 나갔다. 남은 발생 장소가 개경뿐이어서
# 화면이 "위화도 회군은 개성시에서 일어났다"고 말했다.
from histgraph.scope import close_places  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "sc.sqlite")
    store.upsert_nodes([
        Node(id="wd:E", type="event", label="위화도 회군", source="wd"),
        Node(id="wd:P1", type="place", label="위화도", source="wd"),
        Node(id="wd:P2", type="place", label="개성시", source="wd"),
        Node(id="wd:H", type="person", label="이성계", source="wd"),
        Node(id="wd:X", type="place", label="상관없는 곳", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:E", dst="wd:P1", type="occurred_at", source="kowiki:infobox"),
        Edge(src="wd:E", dst="wd:P2", type="occurred_at", source="wd"),
        Edge(src="wd:H", dst="wd:E", type="participated_in", source="wd"),
        Edge(src="wd:X", dst="wd:P1", type="located_in", source="wd"),
    ])
    # 실측 회귀: 연표에 경술국치가 없어서 따라가 보니, 수집 쿼리가
    # `?e wdt:P17 wd:{polity}` 로 정체를 물어 놓고 답을 버리고 있었다.
    # 인물만 props.polity 를 갖고 있어서 사건은 씨앗이 될 길이 없었다 —
    # 조선 연대 안에서만 P17=조선 사건 73건이 통째로 빠졌다.
    from histgraph.scope import ERAS, select_seeds  # noqa: E402

    store.upsert_nodes([
        Node(id="wd:Q28179", type="org", label="조선", source="wd"),
        Node(id="wd:EV1", type="event", label="갑오개혁", source="wd",
             start_date="1894-01-01", props={"polity": "조선"},
             description="1894년 조선에서 시작된 제도 개혁.",
             aliases=["갑오경장"]),
        Node(id="wd:EV2", type="event", label="무신정변", source="wd",
             props={"polity": "고려"}),
        # 설명이 없는 사건. 연대는 알지만 화면에서 이름 말고 할 말이 없다.
        Node(id="wd:EV3", type="event", label="이름뿐인 사건", source="wd",
             start_date="1895-01-01", props={"polity": "조선"}),
    ])
    era_seeds = select_seeds(store, ERAS["joseon"])
    check("Wikidata 가 그 정체의 사건이라 한 것은 씨앗이 된다",
          "wd:EV1" in era_seeds, str(sorted(era_seeds)))
    check("다른 시대의 사건은 안 데려온다", "wd:EV2" not in era_seeds)

    kept = close_places(store, {"wd:H", "wd:E", "wd:P2"})
    check("사건이 남으면 그 사건이 일어난 곳도 데려온다", "wd:P1" in kept)
    check("이미 있던 노드는 그대로", {"wd:H", "wd:E", "wd:P2"} <= kept)
    check("사건과 무관한 노드는 안 딸려온다", "wd:X" not in kept)
    check("장소가 없으면 아무것도 안 는다",
          close_places(store, {"wd:H"}) == {"wd:H"})

    # 실측 회귀: 시대 그래프에 별칭이 **0건**이었다. 전체 그래프에는
    # 5,064건이 있는데 `scope` 가 aliases 표를 안 옮기고 있었다. 화면이
    # 읽는 것은 시대 그래프라, 이 프로젝트가 내세우는 "'이방원'으로 태종을
    # 찾는다"가 정작 화면에서는 한 번도 동작한 적이 없었다.
    from histgraph.scope import extract as scope_extract  # noqa: E402

    out_db = Path(tmp) / "era.sqlite"
    scope_extract(store, "joseon", str(out_db))
    dest = GraphStore(out_db)
    check("시대 그래프로 별칭이 함께 옮겨간다",
          dest.conn.execute(
              "SELECT COUNT(*) FROM aliases WHERE node_id='wd:EV1' AND alias='갑오경장'"
          ).fetchone()[0] == 1)
    # 갑오개혁은 엣지가 하나도 없다. 고립 노드로 버리면 연표에서 사라진다.
    check("연대를 아는 사건은 엣지가 없어도 남는다",
          dest.conn.execute(
              "SELECT 1 FROM nodes WHERE id='wd:EV1'").fetchone() is not None)
    # 사용자 지적(2026-09-04): 실록 기사 제목이 설명 없이 연표에 서 있었다.
    # "안 보여주는 게 더 좋을 것 같은데" — 연대를 알아도 할 말이 없으면
    # 세우지 않는다. 연대 있는 사건을 살리는 규칙보다 이쪽이 앞선다.
    check("설명이 없으면 연대를 알아도 빠진다",
          dest.conn.execute(
              "SELECT 1 FROM nodes WHERE id='wd:EV3'").fetchone() is None)
    dest.close()

    # 뼈대는 설명이 없어도 남는다 — 연표의 눈금과 직위가 사라지면 축과
    # 인물 상세가 무너진다.
    from histgraph.scope import UNDESCRIBED_DROP_TYPES  # noqa: E402

    check("연표 눈금은 설명 없이도 남는다", "period" not in UNDESCRIBED_DROP_TYPES)
    check("직위는 설명 없이도 남는다", "role" not in UNDESCRIBED_DROP_TYPES)
    # '서울 종로구'에 해설을 붙일 일이 없는데, 빼면 그 구에 있는 유물
    # 86건이 '어디 있는지'를 잃는다.
    check("장소는 설명 없이도 남는다", "place" not in UNDESCRIBED_DROP_TYPES)
    store.close()

# --- 사실 정합성 보수 ----------------------------------------------------
# 실측 회귀: "신사임당의 부모는 이원수다"(남편), "정약용의 부모는 정약전이다"
# (형), "김종직이 죽은 지 7년 뒤 무오사화에 참여" 를 화면이 단정해서 말했다.
from histgraph.promote import audit_facts, repair_facts, life_of  # noqa: E402

check("몰년만 아는 인물의 생몰은 없는 셈 친다",
      life_of({"type": "person", "start_date": "1900-01-01",
               "end_date": "1900-01-01"}) == (None, None))
check("하루짜리 사건은 시작=끝이 정상",
      life_of({"type": "event", "start_date": "1919-03-01",
               "end_date": "1919-03-01"}) == (1919, 1919))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "fx.sqlite")
    store.upsert_nodes([
        Node(id="wd:W", type="person", label="신사임당", source="wd",
             start_date="1504", end_date="1551"),
        Node(id="wd:H", type="person", label="이원수", source="wd", start_date="1501"),
        Node(id="wd:B1", type="person", label="정약용", source="wd", start_date="1762"),
        Node(id="wd:B2", type="person", label="정약전", source="wd", start_date="1758"),
        Node(id="wd:D", type="person", label="김종직", source="wd",
             start_date="1431", end_date="1492"),
        Node(id="wd:E", type="event", label="무오사화", source="wd",
             start_date="1498", end_date="1498"),
        Node(id="wd:S", type="person", label="이상재", source="wd", start_date="1850"),
        Node(id="wd:F", type="person", label="이희택", source="wd"),
    ])
    store.upsert_edges([
        # 남편을 부모로 (배우자는 구조화 소스에 있다)
        Edge(src="wd:W", dst="wd:H", type="spouse_of", source="wd"),
        Edge(src="wd:W", dst="wd:H", type="child_of", source="extract",
             props={"evidence": "이율곡의 어머니요, 이원수의 아내로서"}),
        # 형을 부모로 (네 살 위)
        Edge(src="wd:B1", dst="wd:B2", type="child_of", source="extract",
             props={"evidence": "둘째 형 정약전도"}),
        # 죽은 뒤의 사건 참여
        Edge(src="wd:D", dst="wd:E", type="participated_in", source="extract",
             props={"evidence": "무오사화의 원인의 하나가 된다"}),
        # 서로가 서로의 부모 — 근거는 한쪽만 말한다
        Edge(src="wd:S", dst="wd:F", type="child_of", source="extract",
             props={"evidence": "이상재는 이희택(李羲宅)과 밀양 박씨의 아들로 출생하였으며",
                    "extracted_from": "wd:S"}),
        Edge(src="wd:F", dst="wd:S", type="child_of", source="extract",
             props={"evidence": "이상재는 이희택(李羲宅)과 밀양 박씨의 아들로 출생하였으며",
                    "extracted_from": "wd:S"}),
    ])
    report = audit_facts(store)
    dropped = {d["text"].split(" -")[0] + "|" + d["text"].split("→ ")[1].split(" ·")[0]
               for d in report["drops"]}
    check("남편을 부모로 읽은 엣지를 버린다", "신사임당|이원수" in dropped, str(dropped))
    check("네 살 위인 형은 부모가 될 수 없다", "정약용|정약전" in dropped, str(dropped))
    check("죽은 뒤의 사건 참여를 버린다", "김종직|무오사화" in dropped, str(dropped))
    check("근거가 말하는 방향은 살린다", "이상재|이희택" not in dropped, str(dropped))
    check("반대 방향은 버린다", "이희택|이상재" in dropped, str(dropped))
    check("배우자 관계 자체는 건드리지 않는다",
          not any(d["text"].startswith("신사임당 -spouse_of") for d in report["drops"]))

    # 사람이 판정해 둔 거짓은 다시 들어와도 지운다
    from histgraph.promote import REJECTED  # noqa: E402
    check("판정 표에 이유가 함께 적혀 있다",
          all(len(row) == 4 and row[3].strip() for row in REJECTED))

    repair_facts(store)
    left = {(r["src"], r["dst"], r["type"]) for r in
            store.conn.execute("SELECT src, dst, type FROM edges")}
    check("보수 뒤 남는 건 참인 관계뿐",
          left == {("wd:W", "wd:H", "spouse_of"), ("wd:S", "wd:F", "child_of")}, str(left))
    check("두 번 돌려도 더 지울 게 없다", not audit_facts(store)["drops"])
    store.close()

# 옮겨 갈 자리에 같은 엣지가 이미 있으면 UNIQUE 제약에 부딪힌다. 실측
# (2026-09-04): `promote` 를 두 번째 돌릴 때 IntegrityError 로 죽었다 —
# 첫 번째가 옮겨 놓은 엣지와 부딪힌 것이라 한 번만 돌리는 동안은 안 보였다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "clash.sqlite")
    store.upsert_nodes([
        Node(id="wd:OLD", type="person", label="김철", source="wd",
             start_date="1400", end_date="1450"),
        Node(id="wd:NEW", type="person", label="김철", source="wd",
             start_date="1480", end_date="1550"),
        Node(id="wd:EV2", type="event", label="어떤 사화", source="wd",
             start_date="1500", end_date="1500"),
    ])
    store.upsert_edges([
        Edge(src="wd:OLD", dst="wd:EV2", type="participated_in", source="extract",
             props={"evidence": "김철이 이 사화에 얽혔다"}),
        Edge(src="wd:NEW", dst="wd:EV2", type="participated_in", source="extract",
             props={"evidence": "김철이 이 사화에 얽혔다"}),
    ])
    rep = repair_facts(store)
    left = {(r["src"], r["dst"]) for r in
            store.conn.execute("SELECT src, dst FROM edges")}
    check("옮길 자리가 이미 차 있으면 지운다 (죽지 않는다)",
          left == {("wd:NEW", "wd:EV2")}, str(left))
    check("부딪힌 수를 센다", rep.get("collided") == 1, str(rep.get("collided")))
    store.close()

# --- 한국어 라벨 덮어쓰기 ------------------------------------------------
# 실측 회귀: 조선 그래프에 'Sayuksin assassination plot' 이 떠 있었다.
# 수집이 라벨을 덮어쓰므로 이 단계는 몇 번이고 다시 돈다 — 멱등해야 한다.
from histgraph import labels as labels_mod  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    table = Path(tmp) / "ko.tsv"
    table.write_text(
        "# 주석과 빈 줄은 건너뛴다\n\n"
        "Q70585589\t사육신의 단종 복위 운동\ten=Sayuksin assassination plot\n"
        "Q1\t대한제국\n"          # 근거 칸은 없어도 된다
        "Q404\t없는 노드\t표에만 있는 QID\n",
        encoding="utf-8",
    )
    rows = labels_mod.load_table(table)
    check("표를 읽는다 (주석·빈 줄 제외)", len(rows) == 3, str(len(rows)))
    check("근거 칸은 없어도 된다", rows[1].label == "대한제국")

    for broken, why in [
        ("Q1\t\n", "라벨이 비었다"),
        ("wd:Q1\t라벨\n", "QID 형식이 아니다"),
        ("Q1\tlabel\n", "한글이 없다"),
        ("Q1\t가\nQ1\t나\n", "같은 QID 가 두 번"),
    ]:
        bad = Path(tmp) / "bad.tsv"
        bad.write_text(broken, encoding="utf-8")
        try:
            labels_mod.load_table(bad)
            check(f"깨진 표를 거른다 ({why})", False, "예외가 안 났다")
        except labels_mod.LabelTableError:
            check(f"깨진 표를 거른다 ({why})", True)

    store = GraphStore(Path(tmp) / "lb.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q70585589", type="event", label="Sayuksin assassination plot",
             source="wd", start_date="1456"),
        Node(id="wd:Q1", type="period", label="Q1", source="wd"),
        Node(id="wd:Q9", type="event", label="사육신의 단종 복위 운동", source="wd"),
    ])
    report = labels_mod.apply_overrides(store.conn, rows, dry_run=True)
    check("dry-run 은 라벨을 건드리지 않는다",
          store.conn.execute("SELECT label FROM nodes WHERE id='wd:Q70585589'")
          .fetchone()[0] == "Sayuksin assassination plot")
    check("dry-run 도 적용 뒤에 남는 것을 센다", report.remaining == [], str(report.remaining))

    report = labels_mod.apply_overrides(store.conn, rows)
    labels = dict(store.conn.execute("SELECT id, label FROM nodes"))
    check("영문 라벨을 한국어로 바꾼다",
          labels["wd:Q70585589"] == "사육신의 단종 복위 운동", str(labels))
    check("옛 이름은 별칭으로 남는다",
          ("wd:Q70585589", "Sayuksin assassination plot") in
          {tuple(r) for r in store.conn.execute("SELECT node_id, alias FROM aliases")})
    check("QID 가 라벨이던 노드는 별칭을 남기지 않는다",
          not store.conn.execute(
              "SELECT 1 FROM aliases WHERE node_id='wd:Q1'").fetchone())
    check("표에만 있고 그래프에 없는 QID 는 보고한다", report.absent == ["Q404"])
    check("같은 이름이 이미 있으면 중복으로 보고한다",
          report.collisions == [("wd:Q70585589", "사육신의 단종 복위 운동", "wd:Q9")],
          str(report.collisions))

    again = labels_mod.apply_overrides(store.conn, rows)
    check("두 번째부터는 바꿀 게 없다 (멱등)",
          again.applied == [] and again.already == 2, str(again.already))
    check("두 번째에는 중복 경고도 다시 뜨지 않는다", again.collisions == [])
    store.close()


# --- 설명 보강: 왜 빈 칸이 남았는가 --------------------------------------
# 화면의 '사량진왜변'(차수 1)에 설명이 없었다. 자료가 없어서가 아니라
# enrich 가 차수 상위 500개만 받았기 때문이다. 순번이 오지 않은 것과
# 문서가 없는 것을 구분해서 고정한다.
print("\n[설명 보강]")
from histgraph.sources import wikidata as wd_mod  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "en.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q1", type="person", label="많이 연결된 사람", source="wd"),
        Node(id="wd:Q2", type="event", label="사량진왜변", source="wd"),
        Node(id="wd:Q3", type="place", label="사량면", source="wd"),
        Node(id="wd:Q4", type="person", label="문서 없는 사람", source="wd"),
        Node(id="wd:Q5", type="person", label="이미 적힌 사람", source="wd",
             description="가" * 400),
        Node(id="ex:person:추출", type="person", label="추출된 사람",
             source="extract"),
    ])
    store.upsert_edges([
        Edge(src="wd:Q1", dst="wd:Q2", type="participated_in", source="wd"),
        Edge(src="wd:Q1", dst="wd:Q3", type="born_in", source="wd"),
        Edge(src="wd:Q2", dst="wd:Q3", type="occurred_at", source="wd"),
    ])

    asked: list[list[str]] = []
    ARTICLES = {"Q1": "많이 연결된 사람", "Q2": "사량진왜변", "Q3": "사량면"}

    dead: set[str] = set()   # 이 회차에 sitelink 쿼리가 죽은 QID

    def fake_titles(fetcher, qids, chunk=200, unresolved=None):
        asked.append(sorted(qids))
        if unresolved is not None:
            unresolved.update(q for q in qids if q in dead)
        return {q: t for q, t in ARTICLES.items()
                if q in set(qids) and q not in dead}

    # '판의금부사'를 물으면 '의금부' 문서가 온다 — 응답의 문서명은
    # 요청한 것과 다르다. 실제 API 와 같은 모양으로 흉내낸다.
    REDIRECT = {"사량면": "통영시 사량면"}

    # 이름이 달라지는 이유는 둘이다. 넘겨주기는 **다른 문서**로 보내고,
    # 정규화는 표기만 손질한다. 둘을 같이 세면 같은 문서를 두고
    # "다른 문서에서 넘겨받았다"고 적게 된다.
    NORMALIZED = {"많이 연결된 사람": "많이 연결된 사람"}

    def fake_extracts(fetcher, titles, full=False, resolved_from=None,
                      redirected=None):
        out = {}
        for t in titles:
            got = REDIRECT.get(t, NORMALIZED.get(t, t))
            out[got] = f"{got} 문서 본문. " + "나" * 300
            if resolved_from is not None:
                resolved_from[got] = t
            if t in REDIRECT and redirected is not None:
                redirected.add(got)
        return out

    def fake_descs(fetcher, qids, chunk=300):
        return {"Q4": ("Joseon civil servant (1738 - 1798)", "en")}

    real = (wikipedia.fetch_titles, wikipedia.fetch_extracts,
            wd_mod.fetch_descriptions)
    wikipedia.fetch_titles = fake_titles
    wikipedia.fetch_extracts = fake_extracts
    wd_mod.fetch_descriptions = fake_descs
    try:
        result = wikipedia.enrich(None, store)

        # 차수 0·1짜리도 이번 회차에 들어와야 한다. 예전 기본값(500)이
        # 아니라 '남은 전부'가 기본이라는 뜻이다.
        check("차수가 낮은 노드도 한 회차에 다 조회한다",
              asked and set(asked[0]) == {"Q1", "Q2", "Q3", "Q4"},
              str(asked[:1]))
        check("person·event 밖의 타입도 대상이다 (place)",
              "Q3" in set(asked[0]))
        check("이미 산문이 있는 노드는 다시 받지 않는다",
              "Q5" not in set(asked[0]))
        check("wd 가 아닌 노드는 대상이 아니다",
              not any(a.startswith("ex:") for a in asked[0]))

        descs = dict(store.conn.execute(
            "SELECT id, description FROM nodes"))
        check("차수 1짜리 사건에 설명이 들어간다",
              (descs["wd:Q2"] or "").startswith("사량진왜변 문서 본문"))
        check("설명 출처를 kowiki 로 남긴다", store.conn.execute(
            "SELECT json_extract(props,'$.desc_source') FROM nodes"
            " WHERE id='wd:Q3'").fetchone()[0] == "kowiki")

        # 넘겨주기를 따라간 문서를 버리면 안 된다. 요청한 이름으로만
        # 결과를 찾다가 조선 그래프 4건이 빈 설명으로 남아 있었다.
        check("넘겨주기를 따라간 본문도 노드에 붙는다",
              (descs["wd:Q3"] or "").startswith("통영시 사량면 문서 본문"),
              repr((descs["wd:Q3"] or "")[:40]))
        check("어느 문서에서 넘겨받았는지 적는다", store.conn.execute(
            "SELECT json_extract(props,'$.desc_via') FROM nodes"
            " WHERE id='wd:Q3'").fetchone()[0] == "통영시 사량면")
        check("넘겨주기가 아닌 글에는 표시가 없다", store.conn.execute(
            "SELECT json_extract(props,'$.desc_via') FROM nodes"
            " WHERE id='wd:Q2'").fetchone()[0] is None)
        check("보고에 넘겨주기 건수가 적힌다", result["redirected"] == 1,
              str(result))
        # 표기만 손질된 문서에 '넘겨받은 글' 딱지를 붙이면 안 된다
        check("정규화는 넘겨주기로 세지 않는다", store.conn.execute(
            "SELECT json_extract(props,'$.desc_via') FROM nodes"
            " WHERE id='wd:Q1'").fetchone()[0] is None)

        # 문서가 없는 것과 아직 안 받은 것은 다른 이야기다. 표시가 남아야
        # 화면이 "왜 비었는지"를 말할 수 있다.
        check("문서가 없는 노드에 no_kowiki 표시가 남는다", store.conn.execute(
            "SELECT json_extract(props,'$.no_kowiki') FROM nodes"
            " WHERE id='wd:Q4'").fetchone()[0] == 1)
        check("문서가 있는 노드에는 표시가 없다", store.conn.execute(
            "SELECT json_extract(props,'$.no_kowiki') FROM nodes"
            " WHERE id='wd:Q2'").fetchone()[0] is None)
        # 한 줄 설명은 영어로 오지만 **영어로 저장되지 않는다.** 여기는
        # Node 관문을 지나지 않고 SQL 로 바로 쓰는 자리라, 규칙이 빠지면
        # 화면에 영어가 다시 뜬다.
        check("문서 없는 노드는 한 줄 설명을 한국어로 옮겨 채운다",
              descs["wd:Q4"] == "조선의 문신 (1738~1798)", repr(descs["wd:Q4"]))
        check("사전으로 옮긴 설명임을 남긴다", store.conn.execute(
            "SELECT json_extract(props,'$.desc_source') FROM nodes"
            " WHERE id='wd:Q4'").fetchone()[0] == "사전")
        check("보고에 못 채운 쪽이 함께 적힌다",
              result["no_article"] == 1 and result["fallback"] == 1
              and result["remaining"] == 0, str(result))

        # 두 번째 회차: 헛수고를 반복하지 않는다.
        asked.clear()
        again = wikipedia.enrich(None, store)
        check("문서 없는 노드를 다음 회차에 다시 묻지 않는다",
              not asked or "Q4" not in set(asked[0]), str(asked[:1]))
        check("다 채운 뒤에는 조회할 것이 없다",
              again["updated"] == 0 and again["no_article"] == 0, str(again))

        # --refresh 는 그 표시까지 무시하고 다시 본다
        asked.clear()
        wikipedia.enrich(None, store, refresh=True)
        check("--refresh 는 no_kowiki 표시도 무시하고 다시 본다",
              asked and "Q4" in set(asked[0]), str(asked[:1]))
        check("--refresh 여도 한 줄 설명이 산문을 덮어쓰지 않는다",
              store.conn.execute(
                  "SELECT description FROM nodes WHERE id='wd:Q5'"
              ).fetchone()[0] == "가" * 400)

        # limit 을 주면 남은 수를 보고해야 한다 — 조용히 자르면 안 된다
        store.conn.execute(
            "UPDATE nodes SET description=NULL,"
            " props=json_remove(props,'$.no_kowiki')")
        store.conn.commit()
        capped = wikipedia.enrich(None, store, limit=1)
        check("--limit 으로 자른 나머지를 보고한다", capped["remaining"] == 4,
              str(capped))

        # 쿼리가 죽어서 못 물어본 것을 '문서 없음'으로 못 박으면, 타임아웃
        # 한 번에 200개가 영구히 건너뛰어진다.
        store.conn.execute(
            "UPDATE nodes SET description=NULL,"
            " props=json_remove(props,'$.no_kowiki','$.desc_source')")
        store.conn.commit()
        dead.add("Q2")
        broke = wikipedia.enrich(None, store)
        check("조회가 죽은 노드는 no_kowiki 로 못 박지 않는다",
              store.conn.execute(
                  "SELECT json_extract(props,'$.no_kowiki') FROM nodes"
                  " WHERE id='wd:Q2'").fetchone()[0] is None)
        # Q2 는 쿼리가 죽어 '모름', Q4·Q5 는 정말로 문서가 없다.
        check("조회 실패는 문서 없음과 따로 센다",
              broke["unresolved"] == 1 and broke["no_article"] == 2,
              str(broke))
        dead.clear()
        asked.clear()
        wikipedia.enrich(None, store)
        check("실패했던 노드는 다음 회차에 다시 묻는다",
              asked and "Q2" in set(asked[0]), str(asked[:1]))
    finally:
        (wikipedia.fetch_titles, wikipedia.fetch_extracts,
         wd_mod.fetch_descriptions) = real
    store.close()


# --- 넘겨받은 글은 추출에 넣지 않는다 ------------------------------------
# '무관랑'의 설명은 '사다함' 문서다. 화면에서는 출처를 밝히고 보여주면
# 되지만, 추출이 그 글을 무관랑의 것으로 읽으면 사다함의 관계가 무관랑에게
# 붙는다. 근거 구절 검증으로는 못 막는다 — 구절은 원문에 실제로 있다.
print("\n[넘겨받은 글은 추출 대상이 아니다]")
from histgraph.extract import load_documents  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "via.sqlite")
    long_text = "무관랑은 사다함의 벗이다. " + "가" * 300
    store.upsert_nodes([
        Node(id="wd:A", type="person", label="사다함", source="wd",
             description=long_text),
        Node(id="wd:B", type="person", label="무관랑", source="wd",
             description=long_text, props={"desc_via": "사다함"}),
    ])
    picked = {d.node_id for d in load_documents(store, min_score=0.0)}
    check("제 문서를 가진 노드는 추출 대상이다", "wd:A" in picked, str(picked))
    check("넘겨받은 글은 추출 대상에서 빠진다", "wd:B" not in picked, str(picked))
    store.close()


print("\n[영어 설명은 화면까지 오지 못한다]")
from histgraph import koreanize  # noqa: E402

check("현대 직업은 국적과 함께 옮긴다",
      koreanize.to_korean("South Korean wrestler") == "대한민국의 레슬링 선수",
      koreanize.to_korean("South Korean wrestler"))
# 'south korean' 을 'korean' 으로 먼저 자르면 남한이 그냥 한국이 된다
check("긴 국적을 먼저 맞춘다",
      koreanize.to_korean("North Korean footballer") == "북한의 축구 선수",
      koreanize.to_korean("North Korean footballer"))
# 같은 낱말이 시대에 따라 다른 말이 된다
check("전근대의 civil servant 는 문신",
      koreanize.to_korean("Joseon civil servant (1390 - 1453)") == "조선의 문신 (1390~1453)",
      koreanize.to_korean("Joseon civil servant (1390 - 1453)"))
check("현대의 civil servant 는 공무원",
      koreanize.to_korean("South Korean civil servant") == "대한민국의 공무원",
      koreanize.to_korean("South Korean civil servant"))
check("사건은 연도를 앞에 달고 온다",
      koreanize.to_korean("1592 military campaign") == "1592년 군사 작전",
      koreanize.to_korean("1592 military campaign"))
check("관직은 품계와 기관을 남긴다",
      koreanize.to_korean("second rank official in Uijeongbu during the Joseon Dynasty")
      == "조선의 의정부 2품 관직",
      koreanize.to_korean("second rank official in Uijeongbu during the Joseon Dynasty"))
# 접속사가 아닌 '&' — 'R&B' 를 쪼개면 가수가 사라진다
check("R&B 는 접속사로 쪼개지지 않는다",
      koreanize.to_korean("South Korean R&B singer") is None
      or "R" not in koreanize.to_korean("South Korean R&B singer"),
      repr(koreanize.to_korean("South Korean R&B singer")))
# **모르면 지어내지 않는다.** 이 규칙이 무너지면 그럴듯한 오역이 조용히 쌓인다
check("모르는 말은 옮기지 않는다",
      koreanize.to_korean("Goryeo person CBDB = 3435") is None,
      koreanize.to_korean("Goryeo person CBDB = 3435"))
check("연도가 아닌 괄호는 통째로 포기한다",
      koreanize.to_korean("born 1595; [Ch\u2019anggang]") is None)
check("한 조각이라도 모르면 통째로 포기한다",
      koreanize.to_korean("South Korean singer and flurbologist") is None,
      koreanize.to_korean("South Korean singer and flurbologist"))

# 온톨로지 관문 — 커넥터마다 검사를 적지 않아도 여기서 걸린다
gate = Node(id="wd:Q1", type="person", label="ㄱ", source="wd",
            description="North Korean judoka")
check("Node 가 영어 설명을 한국어로 바꾼다", gate.description == "북한의 유도 선수",
      repr(gate.description))
gate2 = Node(id="wd:Q2", type="person", label="ㄴ", source="wd",
             description="Goryeo person CBDB = 39526")
check("옮기지 못한 영어 설명은 비운다", gate2.description is None, repr(gate2.description))
prose = "임진왜란(壬辰倭亂)은 1592년부터\n\n두 문단짜리 글이다."
gate3 = Node(id="wd:Q3", type="event", label="ㄷ", source="wd", description=prose)
check("한국어 산문은 줄바꿈까지 그대로 둔다", gate3.description == prose)

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "ko.sqlite")
    # 관문을 지나지 않는 길(SQL 직접 쓰기)로 영어를 넣어 둔다 —
    # 이미 그렇게 들어와 있는 그래프가 redescribe 의 대상이다
    store.upsert_nodes([Node(id="wd:Q9", type="person", label="ㄹ", source="wd")])
    store.conn.execute(
        "UPDATE nodes SET description = 'South Korean fencer' WHERE id = 'wd:Q9'")
    store.upsert_nodes([Node(id="wd:Q10", type="person", label="ㅁ", source="wd")])
    store.conn.execute(
        "UPDATE nodes SET description = 'Goryeo person CBDB = 1' WHERE id = 'wd:Q10'")
    store.conn.commit()

    rep = koreanize.redescribe(store.conn)
    check("영어 설명을 바꾼다", len(rep.applied) == 1, str(rep.applied))
    check("못 옮긴 설명은 비운다", len(rep.cleared) == 1, str(rep.cleared))
    check("한글이 없는 설명이 남지 않는다",
          koreanize.english_descriptions(store.conn) == [],
          str(koreanize.english_descriptions(store.conn)))
    # 비운 노드의 원문은 남아 있어야 한다 — 사전이 자라면 다시 살린다
    kept = store.conn.execute(
        "SELECT json_extract(props,'$.desc_en') FROM nodes WHERE id='wd:Q10'").fetchone()[0]
    check("비운 설명의 원문을 남긴다", kept == "Goryeo person CBDB = 1", repr(kept))

    again = koreanize.redescribe(store.conn)
    check("두 번 돌려도 더 바꾸지 않는다", not again.applied, str(again.applied))
    # 사전이 자란 뒤 다시 돌리면 비워 둔 것이 되살아난다
    koreanize.JOB["person cbdb = 1"] = "시험용 직업"
    revived = koreanize.redescribe(store.conn)
    check("사전이 자라면 비워 둔 설명이 되살아난다",
          len(revived.applied) == 1, str(revived.applied))
    del koreanize.JOB["person cbdb = 1"]
    store.close()


print("[사건과 개념 갈라내기]")
with tempfile.TemporaryDirectory() as tmp:
    from histgraph import reclassify as rc  # noqa: E402

    store = GraphStore(Path(tmp) / "rc.sqlite")
    store.upsert_nodes([
        Node(id="wd:W1", type="media", label="영화", source="wd",
             props={"form": "film"}),
        # 주제 자리에만 있는 노드 — 다른 관계도 연대도 없다
        Node(id="wd:T1", type="event", label="조직범죄", source="wd"),
        # 주제끼리만 이어진 섬 — 엣지가 있어도 사실층에 닿지 않는다
        Node(id="wd:T2", type="event", label="상실", source="wd"),
        Node(id="wd:T3", type="event", label="상실감", source="wd"),
        # 사실층에 닿는다 — 주제 자리에 있어도 빠져야 한다
        Node(id="wd:E1", type="event", label="어떤 사건", source="wd"),
        Node(id="wd:P1", type="place", label="대한민국", source="wd"),
        # 연대를 스스로 말하는 노드도 주제로 보지 않는다
        Node(id="wd:E2", type="event", label="연대 있는 사건", source="wd",
             start_date="1801-01-01"),
    ])
    store.upsert_edges([
        Edge(src="wd:W1", dst="wd:T1", type="depicts", source="wd"),
        Edge(src="wd:W1", dst="wd:T2", type="depicts", source="wd"),
        Edge(src="wd:W1", dst="wd:T3", type="depicts", source="wd"),
        Edge(src="wd:W1", dst="wd:E1", type="depicts", source="wd"),
        Edge(src="wd:W1", dst="wd:E2", type="depicts", source="wd"),
        Edge(src="wd:T2", dst="wd:T3", type="related_to", source="wd"),
        Edge(src="wd:E1", dst="wd:P1", type="related_to", source="wd"),
    ])
    only = rc._subject_only(store)
    check("주제 자리에만 있는 노드를 고른다", "T1" in only, str(only))
    check("주제끼리 이어진 섬도 주제로 남는다", {"T2", "T3"} <= only, str(only))
    check("사실층에 닿으면 빠진다", "E1" not in only, str(only))
    check("연대가 있으면 빠진다", "E2" not in only, str(only))

    # 계획을 손으로 만들어 적용만 시험한다 (네트워크 없이)
    plan = rc.Plan(
        changes={"wd:T1": ("event", "concept")},
        labels={"wd:T1": "조직범죄"},
    )
    result = rc.apply_plan(store, plan)
    check("타입을 바꾼다", store.conn.execute(
        "SELECT type FROM nodes WHERE id='wd:T1'").fetchone()[0] == "concept")
    check("개념으로 가면 depicts 가 about 이 된다",
          result["depicts_to_about"] == 1, str(result))
    check("바뀐 뒤 어긋난 엣지가 없다", not rc.invalid_edges(store),
          str(rc.invalid_edges(store)))

    # 되돌아오는 쪽도 된다
    back = rc.Plan(changes={"wd:T1": ("concept", "event")}, labels={"wd:T1": "조직범죄"})
    result = rc.apply_plan(store, back)
    check("사건으로 되돌리면 about 이 depicts 로 돌아온다",
          result["about_to_depicts"] == 1, str(result))

    # 노드를 안 바꿔도 엣지는 어긋나 있을 수 있다
    store.conn.execute("UPDATE edges SET type='about' WHERE src='wd:W1' AND dst='wd:E1'")
    store.conn.commit()
    fixed = rc.repair_edges(store)
    check("사건을 가리키는 about 은 depicts 로 돌아온다",
          fixed["about_to_depicts"] == 1, str(fixed))

    report = rc.depicts_report(store)
    check("depicts 대상 타입을 센다", report["by_type"].get("event") == 5, str(report))
    store.close()

print("[작품 명단 — 분류에서 관계 읽기]")
from histgraph.sources import works  # noqa: E402

check("제목의 괄호가 매체를 말한다", works.form_of("대조영 (드라마)", set()) == "series")
check("괄호가 분류보다 앞선다",
      works.form_of("한산 (영화)", {"분류:조선 역사 드라마"}) == "film")
check("분류로도 매체를 읽는다",
      works.form_of("한산: 용의 출현", {"분류:조선을 배경으로 한 영화"}) == "film")
check("모르면 모른다고 한다", works.form_of("칼의 노래", {"분류:임진왜란을 소재로 한 작품"}) is None)
check("소재 분류에서 이름을 뽑는다",
      works.subject_of("분류:이순신을 소재로 한 작품") == "이순신")
check("배경 분류에서 이름을 뽑는다",
      works.setting_of("분류:조선을 배경으로 한 영화") == "조선")
check("소재와 배경을 섞지 않는다",
      works.subject_of("분류:조선을 배경으로 한 영화") is None
      and works.setting_of("분류:이순신을 소재로 한 작품") is None)
check("왕대는 왕조로 물러난다", works.polity_of("조선 세종 시기") == "조선")
check("왕조로 시작하지 않으면 물러날 곳이 없다", works.polity_of("한성부") is None)

pages = {
    "대조영 (드라마)": {"분류:고구려를 배경으로 한 작품", "분류:대조영을 소재로 한 작품"},
    "대한민국의 역사 드라마 목록": {"분류:조선 역사 드라마"},
    "칼의 노래": {"분류:임진왜란을 소재로 한 작품"},
}
nodes, skipped = works.build_nodes(pages, {"대조영 (드라마)": "Q1"}, {})
check("작품 노드는 QID 를 id 로 쓴다", [n.id for n in nodes] == ["wd:Q1"], str([n.id for n in nodes]))
check("매체를 모르면 노드를 만들지 않는다",
      ("칼의 노래", "매체를 모름") in skipped, str(skipped))
check("목록 문서는 작품이 아니다",
      ("대한민국의 역사 드라마 목록", "작품이 아님") in skipped, str(skipped))

def fake_resolve(name, allowed):
    table = {("대조영", ("person", "event", "place", "org")): "wd:Q100",
             ("고구려", ("period", "org", "place")): "wd:Q200"}
    return table.get((name, allowed))

edges, counts, unresolved = works.build_edges(nodes, fake_resolve)
check("소재 분류가 depicts 가 된다", counts["depicts"] == 1, str(counts))
check("배경 분류가 set_in 이 된다", counts["set_in"] == 1, str(counts))
check("엣지에 분류 이름을 남긴다",
      all(e.label and e.label.startswith("분류: ") for e in edges), str([e.label for e in edges]))

print("[작품 문서에서 곧바로 읽기 — LLM 없이]")
from histgraph.sources.wikipedia import strip_sections  # noqa: E402

box = """{{영화 정보
| 제목 = 한산
| 제작년도 = 2020년
| 개봉 = 일반판 : 2022년 7월 27일<br/>감독판 : 2022년 11월 16일
}}"""
check("개봉을 제작년도보다 앞세운다",
      works.parse_work_infobox(box)["start"] == "2022-07-27",
      str(works.parse_work_infobox(box)))
check("여러 날짜 중 처음 것을 쓴다", works._first_date("2006년 9월 16일 ~ 2007년 12월 23일") == "2006-09-16")
check("연도만 있어도 읽는다", works._first_date("1975년") == "1975")
tv = "{{텔레비전 방송 프로그램 정보\n|원작 = [[선우휘]]의 《[[노다지]]》\n}}"
check("원작 칸의 링크를 뽑는다", works.parse_work_infobox(tv)["adapted"] == ["선우휘", "노다지"],
      str(works.parse_work_infobox(tv)))

check("단서가 있어야 소재로 본다",
      works.subject_links("《가》는 [[한산도 대첩]]을 소재로 한 영화이다.") == ["한산도 대첩"])
check("단서가 없는 링크는 버린다",
      works.subject_links("《가》는 [[김한민]] 감독의 영화이다.") == [])
check("원작자는 소재가 아니다",
      works.subject_links("《가》는 [[선우휘]]의 소설을 바탕으로 만들었다.") == [],
      str(works.subject_links("《가》는 [[선우휘]]의 소설을 바탕으로 만들었다.")))

article = """도입 문단.

== 역사적 사실 ==
고증에 관한 글.

== 등장 인물 ==
=== 주인공 ===
최수종: 대조영 역

=== 그 외 ===
배우 이름들.

== 시청률 ==
표.

== 역사와 다른 점 ==
남아야 하는 글."""
cut = strip_sections(article)
check("등장 인물 절이 하위 절까지 사라진다", "최수종" not in cut and "배우 이름들" not in cut, cut)
check("역사적 사실은 남는다", "고증에 관한 글" in cut and "남아야 하는 글" in cut, cut)

check("작품이 주제를 가리키는 엣지가 있다", "about" in EDGE_TYPES)
check("about 의 도착은 개념뿐", EDGE_TYPES["about"][2] == ("concept",))
check("depicts 의 도착에 개념이 없다", "concept" not in EDGE_TYPES["depicts"][2])

try:
    Node(id="kw:x", type="media", label="어떤 작품", source="kowiki")
    check("매체 구분 없는 작품 거부", False)
except OntologyError:
    check("매체 구분 없는 작품 거부", True)
try:
    Node(id="kw:x", type="media", label="어떤 작품", source="kowiki",
         props={"form": "브이로그"})
    check("모르는 매체 구분 거부", False)
except OntologyError:
    check("모르는 매체 구분 거부", True)
check("아는 매체 구분은 통과",
      Node(id="kw:y", type="media", label="한산", source="kowiki",
           props={"form": "film"}).props["form"] == "film")

# --- 잘린 인용이 사실을 뒤집는다 -----------------------------------------
# 실측 발단: 화면에 "이완용은 3·1 운동에 참여했다"가 떴다. 근거는 역접 어미
# `-으나` 에서 끊긴 채였고, 원문의 뒤집는 절은 통째로 사라져 있었다.
print("\n[근거 문장 복원 · 참여 부인]")

import datetime  # noqa: E402
import re  # noqa: E402

from histgraph.extract import (  # noqa: E402
    complete_evidence,
    evidence_supported,
    paragraph_span,
    participation_denied,
    sentence_span,
    split_document,
)

IWAN = (
    "1919년 3월 1일, 조선에서는 고종의 승하와 민족자결주의 제창에 호응해 "
    "3·1 운동이 일어났다. 그 역시 민족 지도자들로부터 동참을 요청받았으나 "
    "오히려 당시 총독 데라우치 마사타케에게 탄압 필요성과 그 방안에 관한 "
    "편지를 수차례 보내기도 했다. 이완용은 공식적으로 경고문을 연달아 3회 "
    "발표하고, 3·1 운동이 불순세력에 의한 난동에 불과하다고 발언했다."
)
CUT = "그 역시 민족 지도자들로부터 동참을 요청받았으나"

check("잘린 인용도 근거 검사는 통과한다 (이 검사로는 못 막는다)",
      evidence_supported(CUT, IWAN))
full = complete_evidence(CUT, IWAN)
check("복원하면 뒤집는 절이 돌아온다", "오히려" in full and full.endswith("했다."))
check("복원이 다음 문장까지 삼키지 않는다", "경고문" not in full)
check("참여 요청을 받고 물린 것은 참여가 아니다 → 버린다",
      participation_denied("participated_in", "3·1 운동", full, IWAN))
check("잘린 인용만 주면 판정할 수 없다 (복원이 선행조건)",
      not participation_denied("participated_in", "3·1 운동", CUT, None))

# 거부는 참여의 반대말이 아니다 — 무엇에 대한 거부인지가 갈린다
check("지휘관이 건의를 물린 것은 불참이 아니다",
      not participation_denied(
          "participated_in", "울산성 전투",
          "장수들은 세 성을 포기하자는 건의를 올렸으나, 히데요시는 이를 거절하였다."))
check("중재 제의를 거부하고 원정을 강행한 것도 참여다",
      not participation_denied(
          "participated_in", "병인양요",
          "로즈는 청나라의 중재제의를 거부한채 군함 세척을 이끌고 나섰다."))

# 실측: 같은 문단에 있는 **남의** 거절을 끌어오면 정상 엣지가 날아간다
OTHER = (
    "이기축은 관찰사로 있던 자신의 친족 이명에게 거병 사실을 알리고 참여를 "
    "권고했으나 이명은 거절했다. 이기축 등은 선봉으로 연서역에 잠입, "
    "반정군에게 문을 열어주었다."
)
check("문단 안 남의 거절로 참여를 지우지 않는다",
      not participation_denied(
          "participated_in", "인조반정",
          "이기축 등은 선봉으로 연서역에 잠입, 반정군에게 문을 열어주었다.",
          OTHER))

# 실측: `신탁통치반대 국민총동원위원회` 의 '반대'가 사건 반대로 읽혔다
check("고유명사 속 '반대'는 반대가 아니다",
      not participation_denied(
          "participated_in", "모스크바 3상회담",
          "김구가 모스크바 3상회담에 반발하자 신탁통치반대 국민총동원위원회 "
          "위원이 되었다."))
check("사건에 반대한 것은 참여가 아니다 → 버린다",
      participation_denied(
          "participated_in", "제2차 요동 정벌",
          "제1차 요동 정벌(1388년)과 제2차 요동 정벌(1392년)에 반대하였으나"))
check("다른 관계 타입은 검사 안 함",
      not participation_denied("related_to", "3·1 운동", full, IWAN))

# 숫자에 붙은 마침표를 문장 끝으로 보면 `3.1 운동` 한가운데가 경계가 된다
NUM = "1919년 3.1 만세 운동이 일어났다. 그는 6.25 전쟁에도 참전했다."
check("`3.1`·`6.25` 의 마침표는 문장 끝이 아니다",
      complete_evidence("3.1 만세 운동이 일어났다", NUM)
      == "1919년 3.1 만세 운동이 일어났다.")

# 문단은 넘어가지 않는다 — 넘어가면 남의 문장을 근거로 끌어온다
PARA = "앞 문단의 마지막 문장이다\n뒤 문단이 여기서 시작한다. 그리고 이어진다."
check("문장 복원이 줄바꿈을 넘지 않는다",
      complete_evidence("뒤 문단이 여기서 시작한다", PARA)
      == "뒤 문단이 여기서 시작한다.")
check("문단 범위도 줄바꿈에서 끊긴다",
      PARA[slice(*paragraph_span(PARA, 12, 14))] == "앞 문단의 마지막 문장이다")
check("이미 완결된 문장은 그대로 둔다",
      complete_evidence("그리고 이어진다.", PARA) == "그리고 이어진다.")
check("원문에 없는 근거는 복원할 수 없다",
      complete_evidence("문서에 명시되지 않음", IWAN) is None)
check("문장 범위는 인용을 반드시 품는다",
      sentence_span(IWAN, 30, 40)[0] <= 30 and sentence_span(IWAN, 30, 40)[1] >= 40)

# 조각을 반토막 문장으로 열면 모델이 애초에 온전한 인용을 할 수 없다
LONG = "\n".join([f"{i}번째 문단이다. " + "어떤 일이 벌어졌다. " * 9
                  for i in range(8)])
parts = split_document("n", "L", LONG, size=300)
check("조각이 여럿으로 갈린다", len(parts) > 1)
check("겹침이 문장 첫머리에서 시작한다",
      all(re.match(r"(어떤 일이|\d번째 문단)", p.text) for p in parts[1:]))

print("[시대 묶음과 일제강점기]")
with tempfile.TemporaryDirectory() as tmp:
    from histgraph import resolve as rs  # noqa: E402
    from histgraph import scope as sc  # noqa: E402

    check("묶음은 시대 여럿으로 풀린다",
          sc.eras_of("korea") == ("goryeo", "joseon", "ilje", "daehan"))
    check("시대 이름은 자기 자신으로 풀린다", sc.eras_of("joseon") == ("joseon",))
    # 화면 머리말은 서버가 준다. 모르는 키에 영어를 내보내면 안 된다.
    check("묶음 이름은 한국어다", sc.label_of("korea") == "고려~대한민국")
    check("모르는 시대는 빈 이름", sc.label_of("없는시대") == "")

    store = GraphStore(Path(tmp) / "era.sqlite")
    store.upsert_nodes([
        # 시대가 장소로 앉아 있다 — 실측으로 wd:Q503585 가 그랬다
        Node(id="wd:Q503585", type="place", label="일제강점기", source="wd"),
        Node(id="wd:P1", type="person", label="나운규", source="wd",
             start_date="1902-01-01", end_date="1937-08-09"),
        # 시대 창 밖 — 시대가 시작할 때 아직 태어나지 않았다
        Node(id="wd:P2", type="person", label="박정희", source="wd",
             start_date="1917-11-14", end_date="1979-10-26"),
        # 시대 창 밖 — 시대가 시작하기 전에 죽었다
        Node(id="wd:P3", type="person", label="흥선대원군", source="wd",
             start_date="1820-01-01", end_date="1898-02-22"),
        Node(id="wd:E1", type="event", label="3·1 운동", source="wd",
             start_date="1919-03-01"),
    ])
    store.upsert_edges([
        Edge(src="wd:P1", dst="wd:Q503585", type="died_in", source="wd"),
        Edge(src="wd:E1", dst="wd:Q503585", type="from_period", source="kowiki"),
    ])

    fixed = rs.fix_period_nodes(store)
    kind = store.conn.execute(
        "SELECT type FROM nodes WHERE id='wd:Q503585'").fetchone()["type"]
    check("장소로 앉은 시대를 시대로 되돌린다", kind == "period", kind)
    moved = store.conn.execute(
        "SELECT type, json_extract(props,'$.was') AS was FROM edges "
        "WHERE src='wd:P1' AND dst='wd:Q503585'").fetchone()
    # 지우지 않는다 — '언제'를 '어디서' 칸에 적은 것뿐이다
    check("'어디서'가 시대를 가리키면 from_period 가 된다",
          moved is not None and moved["type"] == "from_period")
    check("무엇이었는지 남긴다", moved is not None and moved["was"] == "died_in")
    check("옮긴 건수를 보고한다", fixed["moved"] == 1, str(fixed))

    seeds = sc.select_seeds(store, sc.ERAS["ilje"])
    check("연대가 겹치는 인물이 씨앗이 된다", "wd:P1" in seeds)
    check("시대 뒤에 태어난 사람은 아니다", "wd:P2" not in seeds)
    check("시대 앞에 죽은 사람도 아니다", "wd:P3" not in seeds)
    check("시대에 걸린 사건도 씨앗이다", "wd:E1" in seeds)

    # 시대 자리에 설 수 없는 노드로는 from_period 를 만들지 않는다
    store.upsert_nodes([
        Node(id="wd:Q884", type="place", label="대한민국", source="wd"),
        Node(id="wd:E2", type="event", label="어떤 현대 사건", source="wd",
             props={"polity": "대한민국"}),
    ])
    rs.link_event_periods(store)
    check("장소인 정체로는 시대 엣지를 만들지 않는다",
          store.conn.execute(
              "SELECT COUNT(*) FROM edges WHERE src='wd:E2'").fetchone()[0] == 0)
    store.close()

# 재위 띠는 엣지의 props 표식으로만 서 있다. upsert 가 props 를 통째로
# 덮어쓰므로 **다시 수집하면 띠가 사라진다** — `reigns` 를 다시 돌려야 한다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "reign.sqlite")
    store.upsert_nodes([
        Node(id="wd:K1", type="person", label="조선 태조", source="wd"),
        Node(id="wd:R1", type="role", label="조선 임금", source="wd"),
    ])
    store.upsert_edges([Edge(src="wd:K1", dst="wd:R1", type="held_position",
                             source="wd", props={"reign": True})])
    store.upsert_edges([Edge(src="wd:K1", dst="wd:R1", type="held_position",
                             source="wd")])   # 다시 수집한 셈
    props = store.conn.execute(
        "SELECT props FROM edges WHERE src='wd:K1'").fetchone()["props"]
    check("다시 수집하면 재위 표식이 지워진다 (reigns 를 다시 돌릴 것)",
          "reign" not in props, props)
    store.close()

# 단체·개념은 시대에 걸릴 수 있어야 한다 — 못 걸면 엣지 0개로 들어와
# scope 의 고립 정리에서 통째로 사라진다
_, from_src, from_dst = EDGE_TYPES["from_period"]
check("단체도 시대에 걸린다", "org" in from_src)
check("개념도 시대에 걸린다", "concept" in from_src)
check("시대의 도착은 시대와 정체뿐", set(from_dst) == {"period", "org"})

# --- 누가 판정했는지 기록한다 ---------------------------------------------
# 실측: 추출 엣지 3,534건이 전부 `props.model = claude-opus-5` 였다. Claude 가
# 뽑아서가 아니라 `to_graph` 가 상수를 박았기 때문이고, 실제 판정자는 로컬
# Qwen 이었다. 틀린 이름은 없는 것만 못하다 — 모르면 적지 않는다.
print("\n[추출 모델 기록]")

from histgraph.store import GraphStore  # noqa: E402
from histgraph.ontology import Node as _N  # noqa: E402
from histgraph.extract import BATCH_MODEL, to_graph as _to_graph  # noqa: E402

_DOC = "1910년 8월 이완용은 한일 병합 조약에 직접 서명했다."
_REL = [{"subject": "이완용", "subject_type": "person",
         "relation": "participated_in", "object": "한일 병합 조약",
         "object_type": "event", "confidence": "certain", "evidence": _DOC}]
with GraphStore(":memory:") as _st:
    _st.upsert_nodes([
        _N(id="p:이완용", type="person", label="이완용", source="t"),
        _N(id="e:한일 병합 조약", type="event", label="한일 병합 조약", source="t"),
    ])
    _, _with = _to_graph(_REL, "p:이완용", _st, doc_text=_DOC,
                         model="mlx-community/Qwen3.6-35B-A3B-8bit", backend="mlx")
    _, _without = _to_graph(_REL, "p:이완용", _st, doc_text=_DOC)

check("돌린 모델을 그대로 남긴다",
      _with[0].props["model"] == "mlx-community/Qwen3.6-35B-A3B-8bit")
check("백엔드도 함께 남긴다", _with[0].props["backend"] == "mlx")
check("모르면 모델을 적지 않는다", "model" not in _without[0].props)
check("모르면 백엔드도 적지 않는다", "backend" not in _without[0].props)
check("배치 모델 상수는 요청에만 쓴다",
      BATCH_MODEL not in str(_with[0].props))

# --- 인포박스 필드가 제 것이 아닌 링크를 삼킨다 --------------------------
# 실측: 신상옥의 `자녀` 칸에 배우자 최은희가, 은신군의 `자녀` 칸에
# 남연군의 생부 이병원이 들어왔다. 둘 다 각주와 괄호 속 부연이다.
print("\n[인포박스 필드 경계]")

from histgraph.sources.infobox import (  # noqa: E402
    EVENT_FIELDS, PERSON_FIELDS, field_links, parse_infobox_links,
)

def _box(body: str) -> str:
    return "{{인물 정보\n" + body + "\n}}"

# 각주 속 링크는 그 필드의 값이 아니다
SHIN = _box("| 자녀 = 장녀: 신진환<ref>1956년 [[최은희 (배우)|최은희]]와"
            " 재혼하기 이전에 얻은 딸.</ref><br/>장남: [[신정균]]")
check("각주 속 링크를 자녀로 읽지 않는다",
      parse_infobox_links(SHIN, PERSON_FIELDS)["자녀"] == ["신정균"])

# 자기닫음 각주가 다음 `</ref>` 까지 통째로 먹으면 안 된다
SELF = "가<ref name=\"a\"/>[[김유신]]<br/>[[품일]]<ref>주석 [[관창]]</ref>"
check("자기닫음 각주가 뒤를 삼키지 않는다",
      field_links(SELF) == ["김유신", "품일"])

# 앞선 링크를 부연하는 괄호는 버린다
EUN = _box("| 자녀 = 양자 [[남연군]](생부 [[이병원]])")
check("링크를 부연하는 괄호 속 링크는 자녀가 아니다",
      parse_infobox_links(EUN, PERSON_FIELDS)["자녀"] == ["남연군"])

# 목록 전체가 괄호 안에 있으면 버리면 안 된다
SU = _box("| 자녀 = 6남 1녀<br>(그 중 아들 [[김창집]], [[김창협]], [[김창흡]])")
check("목록을 감싼 괄호는 버리지 않는다",
      parse_infobox_links(SU, PERSON_FIELDS)["자녀"]
      == ["김창집", "김창협", "김창흡"])

# 장소 필드의 괄호는 **현재 지명**을 담는다 — 버리면 발생지가 사라진다
GUI = "{{전쟁 정보\n| 장소 = 귀주(龜州, 현재의 [[평안북도]] [[구성시]])\n}}"
check("장소 괄호 속 현재 지명은 살린다",
      parse_infobox_links(GUI, EVENT_FIELDS)["장소"] == ["평안북도", "구성시"])

# 링크 안의 괄호(동음이의 꼬리표)는 링크의 일부다
DIS = _box("| 배우자 = [[최은희 (배우)|최은희]]")
check("링크 안 괄호는 건드리지 않는다",
      parse_infobox_links(DIS, PERSON_FIELDS)["배우자"] == ["최은희 (배우)"])

# 사건에서 죽은 사람을 참여자로 적으면 화면이 거짓말을 한다
check("`사망자` 는 참여가 아니라 관련이다",
      EVENT_FIELDS["사망자"][0] == "related_to")
check("`생존자` 도 관련이다", EVENT_FIELDS["생존자"][0] == "related_to")
check("`가해자` 는 참여가 맞다",
      EVENT_FIELDS["가해자"][0] == "participated_in")
check("`위치` 로 `사건 정보` 틀을 연다",
      EVENT_FIELDS["위치"][0] == "occurred_at")

print("\n[한국어 관문 — 화면에 한글 아닌 글이 뜨는 노드를 센다]")
# 세 번 반복된 일이다: 표와 사전은 있는데 파생본에 안 돌려서 영어가 화면에
# 떴다. tools/check_korean.py 와 `scope` 가 이 함수로 그걸 잰다.
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "kr.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q1", type="event", label="1923 Jogono Police Station bombing",
             source="wd"),
        Node(id="wd:Q2", type="person", label="Q2", source="wd"),
        Node(id="wd:Q3", type="person", label="김상옥", source="wd",
             description="독립운동가 (1889~1923)"),
        Node(id="wd:Q4", type="place", label="단양 (Danyang)", source="wd",
             description="   "),   # 빈 설명은 세지 않는다
    ])
    # Node 관문이 영어 설명을 걸러 버리므로, SQL 로 직접 쓰는 경로가
    # 남긴 영어 설명은 SQL 로 흉내 낸다 (wikipedia._fill_from_wikidata 류).
    store.conn.execute(
        "UPDATE nodes SET description='human settlement in South Korea' WHERE id='wd:Q4'")
    store.conn.commit()
    found = labels_mod.foreign_text(store.conn)
    check("한글 없는 라벨을 센다",
          ("wd:Q1", "event", "label", "1923 Jogono Police Station bombing") in found)
    check("QID 가 라벨인 노드도 센다", ("wd:Q2", "person", "label", "Q2") in found)
    check("한글이 섞인 라벨은 통과", not any(f[0] == "wd:Q3" for f in found))
    check("한글 없는 설명을 센다",
          ("wd:Q4", "place", "description", "human settlement in South Korea") in found,
          str(found))
    check("라벨에 한글이 섞이면 라벨은 통과 (설명만 걸린다)",
          [f for f in found if f[0] == "wd:Q4"] ==
          [("wd:Q4", "place", "description", "human settlement in South Korea")])
    check("정확히 셋", len(found) == 3, str(found))
    store.close()

    # 배포 관문 스크립트는 같은 함수를 돌리고, 걸리면 1 로 끝난다
    import subprocess
    tool = Path(__file__).resolve().parents[1] / "tools" / "check_korean.py"
    bad = subprocess.run([sys.executable, str(tool), str(Path(tmp) / "kr.sqlite")],
                         capture_output=True, text=True)
    check("check_korean.py 는 영어가 있으면 실패한다", bad.returncode == 1, bad.stdout)
    check("무엇이 걸렸는지 찍는다", "Jogono" in bad.stdout, bad.stdout)
    clean = GraphStore(Path(tmp) / "ok.sqlite")
    clean.upsert_nodes([Node(id="wd:Q3", type="person", label="김상옥", source="wd")])
    clean.close()
    good = subprocess.run([sys.executable, str(tool), str(Path(tmp) / "ok.sqlite")],
                          capture_output=True, text=True)
    check("check_korean.py 는 한글뿐이면 통과한다", good.returncode == 0, good.stdout)

# 별칭은 화면에 이름표로 그대로 선다 — 로마자 표기와 마크업 조각은 세우지
# 않는다 (2026-09-05 지적: '<!-- 잘 알려진 명칭으로' 가 이름표로 섰다).
# 지우지는 않는다: 검색은 로마자로 친 것도 별칭으로 찾아 준다.
check("로마자 별칭은 화면에 안 세운다",
      not labels_mod.screen_alias("Im Ho") and not labels_mod.screen_alias("KAPF"))
check("마크업 조각은 화면에 안 세운다",
      not labels_mod.screen_alias("<!-- 잘 알려진 명칭으로")
      and not labels_mod.screen_alias("사건 이름과 중복되면 쓰지 않음 -->"))
check("한자 이름은 세운다",
      labels_mod.screen_alias("訓民正音")
      and labels_mod.screen_alias("金剛般若波羅蜜經<卷二∼五>"))
check("로마자가 섞여도 한글이 있으면 세운다", labels_mod.screen_alias("제1차 KAL기 폭파"))
# 수집 쪽 관문 — Node 를 지나는 별칭은 마크업이 붙은 채로 들어올 수 없다
check("Node 가 마크업 별칭을 버린다",
      Node(id="wd:Q706103", type="event", label="을사사화", source="wd",
           aliases=["<!-- 잘 알려진 명칭으로", "을사년의 옥사"]).aliases == ["을사년의 옥사"])

# --- 나무위키 개요 ------------------------------------------------------------
# 제목만 같은 다른 작품이 흔하다. '태조 왕건' 을 그냥 열면 2000년 드라마가
# 나오는데 우리 노드는 1970년 영화다 — 분류의 갈래·연도로 걸러야 한다.
print("\n[나무위키 개요]")
from histgraph.sources import namu  # noqa: E402

_NAMU = (
    '<a href="/w/%EB%B6%84%EB%A5%98:2015%EB%85%84%20%EB%93%9C%EB%9D%BC%EB%A7%88">2015년 드라마</a>'
    '<a href="/w/%EB%B6%84%EB%A5%98:MBC%20%EB%8B%A8%EB%A7%89%EA%B7%B9">MBC 단막극</a>'
    "<table><tr><td>포스터</td></tr></table>"
    "<h2 class='x'><a id='s-1' href='#toc'>1.</a> <span id='개요'>개요"
    "<span><a href='/edit/x'>&#91;편집&#93;</a></span></span></h2>"
    "<div>2015년에 방영한 <a href='/w/MBC'>MBC</a> 드라마이다.<br data-v>"
    "많은 인기를 얻었다.&#91;1&#93;</div>"
    "<h2><a id='s-2'>2.</a> 줄거리</h2><div>수포자가 조선에 떨어진다.</div>"
)
cats = namu.page_categories(_NAMU)
check("분류를 읽는다", cats == ["2015년 드라마", "MBC 단막극"], str(cats))
ov = namu.overview(_NAMU)
check("첫 절만 받고 표·각주·다음 절은 버린다",
      ov == "2015년에 방영한 MBC 드라마이다.\n많은 인기를 얻었다.", repr(ov))
check("갈래·연도가 맞으면 받는다", namu.matches(cats, "series", "2015"))
check("연도가 다르면 거른다", not namu.matches(cats, "series", "2000"))
check("갈래가 다르면 거른다 (영화 노드에 드라마 문서)", not namu.matches(cats, "film", "2015"))
check("연도를 모르면 갈래만 본다", namu.matches(cats, "series", None))
check("작품 분류가 없으면 거른다", not namu.matches(["동음이의어", "성씨"], None, None))
check("라벨 괄호의 해가 날짜 칸보다 앞선다", namu.year_for("궁녀 (1972년 영화)", "2007-01-01") == "1972")
check("괄호에 해가 없으면 날짜 칸을 쓴다", namu.year_for("궁녀", "2007-01-01") == "2007")
check("등장인물 문서는 작품이 아니다", not namu.matches(["옥중화/등장인물", "한국 드라마 캐릭터"], "series", None))
check("틀 문구를 걷어낸다", "스포일러" not in namu._clean("<div>이 문서에 스포일러가 포함되어 있습니다.<br>줄거리다.</div>"))
check("제목 괄호의 갈래가 다르면 거른다 (영화 노드에 '창(만화)')", not namu.paren_fits("창(만화)", "film"))
check("괄호에 갈래가 없으면 통과", namu.paren_fits("창", "film") and namu.paren_fits("창(1997)", "film"))
check("'자세한 내용은 … 참고하십시오' 는 본문이 아니다",
      namu._clean("<div>자세한 내용은 대원군(1966) 문서를 참고하십시오.</div>") == "")
_LIST = ("<h2><a id='s-1'>1.</a> 1966년 TBC 드라마</h2><div>첫 작품.</div>"
         "<h2><a id='s-2'>2.</a> 1972년 MBC 드라마</h2><div>1972년 2월부터 방영.</div>")
check("같은 제목 목록 문서에서는 우리 해의 절만 받는다", namu.year_section(_LIST, "1972") == "1972년 2월부터 방영.")
check("괄호 앞 띄어쓰기를 없앤 제목이 후보에 든다",
      "간신(영화)" in namu.candidates("간신 (영화)", "film", "2015"))
picked = namu.pick_from_search(
    [("태조 왕건", "분류:KBS 대하드라마 분류:2002년 종영"),
     ("태조 왕건(영화)", "분류:1970년 영화"),
     ("태조 왕건/평가", "분류:한국 드라마/평가")],
    "태조 왕건 (영화)", "1970", "film")
check("검색 결과에서 연도·갈래가 맞는 제목을 앞세운다", picked == ["태조 왕건(영화)"], str(picked))


# --- 대통령의 재임 띠 ------------------------------------------------------
# 1948년 뒤의 시간은 '박정희 때'로 읽힌다 — 왕이 하던 일을 대통령이
# 이어받았다. 같은 띠, 같은 모양이고 말만 재위/재임으로 갈린다.
from histgraph.sources.wikidata import drop_nested_terms  # noqa: E402

terms = {
    ("Q138048", "Q6296418"): ("2013-02-25", "2017-03-10"),   # 박근혜
    # 황교안 — Wikidata 에 대통령으로 적혀 있고 권한대행 표식이 없다.
    # 박근혜의 임기 한가운데서 시작한다.
    ("Q12625765", "Q6296418"): ("2016-12-09", "2017-05-10"),
    ("Q21001", "Q6296418"): ("2017-05-10", "2022-05-09"),    # 문재인
    # 같은 날 넘겨받는 것은 겹침이 아니다 (박정희 사망일에 최규하 시작)
    ("Q14356", "Q6296418"): ("1962-03-24", "1979-10-26"),
    ("Q313350", "Q6296418"): ("1979-10-26", "1980-08-16"),
    # 재임 중 — 끝이 없다. 남의 임기 판정에 쓰이지 않고, 자기도 남는다.
    ("Q12612463", "Q6296418"): ("2025-06-04", None),
    # 다른 자리의 겹침은 상관없다 (고종: 조선 임금 → 대한제국 황제)
    ("Q9", "Q1"): ("1863-01-01", "1897-10-12"),
    ("Q9", "Q2"): ("1897-10-12", "1907-07-19"),
}
kept, dropped = drop_nested_terms(terms)
check("남의 임기 한가운데서 시작하는 임기는 대행이라 뺀다",
      dropped == [("Q12625765", "Q6296418")], str(dropped))
check("같은 날 넘겨받는 것은 겹침이 아니다",
      ("Q313350", "Q6296418") in kept and ("Q14356", "Q6296418") in kept)
check("재임 중인 임기도 남는다", ("Q12612463", "Q6296418") in kept)
check("뺀 것 말고는 그대로다", len(kept) == len(terms) - 1, str(kept))

with tempfile.TemporaryDirectory() as tmp:
    import datetime as _dt

    store = GraphStore(Path(tmp) / "pres.sqlite")
    store.upsert_nodes([
        Node(id="wd:K1", type="person", label="조선 고종", source="wd",
             start_date="1852", end_date="1919"),
        Node(id="wd:P1", type="person", label="이승만", source="wd",
             start_date="1875-03-26", end_date="1965-07-19"),
        Node(id="wd:P2", type="person", label="이재명", source="wd",
             start_date="1963-12-08"),
        Node(id="wd:POS", type="role", label="조선 임금", source="wd"),
        Node(id="wd:Q6296418", type="role", label="대한민국 대통령", source="wd"),
        Node(id="wd:E1", type="event", label="4·19 혁명", source="wd",
             start_date="1960-04-19"),
    ])
    store.upsert_edges([
        # 예전 표식 `true` — 군주로 읽어야 한다
        Edge(src="wd:K1", dst="wd:POS", type="held_position", source="wd",
             start_date="1863-12-13", end_date="1897-10-12", props={"reign": True}),
        Edge(src="wd:P1", dst="wd:Q6296418", type="held_position", source="wd",
             start_date="1948-07-24", end_date="1960-04-27", props={"reign": "president"}),
        # 재임 중 — 끝이 없고 살아 있다
        Edge(src="wd:P2", dst="wd:Q6296418", type="held_position", source="wd",
             start_date="2025-06-04", props={"reign": "president"}),
    ])
    api = GraphAPI(store, era="korea")
    band = {r["id"]: r for r in api.timeline("wd:E1")["reigns"]}
    check("대통령이 왕과 같은 띠에 선다", set(band) == {"wd:K1", "wd:P1", "wd:P2"}, str(band))
    check("자리의 종류를 갈라 넘긴다",
          band["wd:K1"]["kind"] == "monarch" and band["wd:P1"]["kind"] == "president")
    check("물러난 대통령의 몰년은 재임 끝과 따로 간다",
          (band["wd:P1"]["end"], band["wd:P1"]["death"]) == (1960, 1965), str(band["wd:P1"]))
    check("재임 중이면 오늘까지 긋고 그렇다고 밝힌다",
          band["wd:P2"]["ongoing"] and band["wd:P2"]["end"] == _dt.date.today().year,
          str(band["wd:P2"]))
    check("물러난 사람은 재임 중이 아니다", not band["wd:P1"]["ongoing"] and not band["wd:K1"]["ongoing"])
    check("축이 재임 중인 대통령의 오늘까지 담는다",
          api.timeline("wd:E1")["axis"]["to"] >= _dt.date.today().year)
    store.close()

# --- 대한민국 시대의 씨앗 ---------------------------------------------------
# 인물 18,471명이 대한민국 국적이다 — 국적으로 고르면 명단이 된다. 씨앗은
# 사건과 대통령 자리에서 오고, 사람은 그 이웃으로만 들어온다.
with tempfile.TemporaryDirectory() as tmp:
    from histgraph import scope as sc2  # noqa: E402

    store = GraphStore(Path(tmp) / "daehan.sqlite")
    store.upsert_nodes([
        Node(id="wd:Q884", type="place", label="대한민국", source="wd"),
        Node(id="wd:Q6296418", type="role", label="대한민국 대통령", source="wd"),
        Node(id="wd:P1", type="person", label="박정희", source="wd",
             start_date="1917-11-14", end_date="1979-10-26", props={"polity": "대한민국"}),
        # 국적만 대한민국인 사람 — 씨앗이 아니다
        Node(id="wd:P2", type="person", label="어느 운동선수", source="wd",
             start_date="1990-01-01", props={"polity": "대한민국"}),
        Node(id="wd:E1", type="event", label="5·16 군사정변", source="wd",
             start_date="1961-05-16", props={"polity": "대한민국"}),
        # P17 이 '지금 그 땅의 나라'를 적은 옛 사건 — 씨앗이 아니다
        Node(id="wd:E2", type="event", label="원종·애노의 난", source="wd",
             start_date="0889", props={"polity": "대한민국"}),
        Node(id="wd:E3", type="event", label="6·29 선언", source="wd",
             props={"seed_era": "대한민국"}),
    ])
    store.upsert_edges([
        Edge(src="wd:P1", dst="wd:Q6296418", type="held_position", source="wd"),
    ])
    seeds = sc2.select_seeds(store, sc2.ERAS["daehan"])
    check("대통령 자리에 앉았던 사람은 씨앗이다", "wd:P1" in seeds, str(seeds))
    check("국적만 대한민국인 사람은 씨앗이 아니다", "wd:P2" not in seeds, str(seeds))
    check("정체 태그가 대한민국인 사건은 씨앗이다", "wd:E1" in seeds)
    check("시대보다 앞선 사건은 태그가 있어도 씨앗이 아니다", "wd:E2" not in seeds)
    check("시드 표에서 온 사건은 날짜가 없어도 씨앗이다", "wd:E3" in seeds)
    check("고려~대한민국이 한 묶음이다",
          sc2.eras_of("korea") == ("goryeo", "joseon", "ilje", "daehan")
          and sc2.label_of("korea") == "고려~대한민국")
    store.close()

# --- 국사편찬위원회 정본 (한국사연대기 · 실록) --------------------------------
# 세종 재위 32년에 사건이 삼포 개항 하나였다. 정본 표에서 사건을 세우고
# 실록 기사 제목으로 날짜를 잡는 경로가 이 절이다.

print("\n[국편 정본 — 연대기·실록]")
from histgraph.sources import nikh  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    rows = [
        ["레벨아이디", "링크정보", "정보ID", "링크명", "유형", "한글명칭", "한자명칭", "설명", "제목", "내용"],
        ["kc_i300100_0010", "kc_i300100", "n_1", "한국사 연대기", "사건", "훈민정음 창제", "訓民正音創製",
         "", "개요", "세종의 명으로 1443년(세종 25) 훈민정음이 만들어졌다. 신숙주(申叔舟)·성삼문(成三問)이 도왔다."],
        ["kc_i300100_0020", "kc_i300100", "n_1", "한국사 연대기", "사건", "훈민정음 창제", "訓民正音創製",
         "", "반포", "1446년에 반포되었다. 세종대왕기념사업회가 뒤에 생겼다."],
        ["kc_n300200_0010", "kc_n300200", "n_2", "한국사 연대기", "인물", "세종", "世宗", "조선 4대 왕", "개요", "…"],
        ["kc_n300300_0010", "kc_n300300", "n_3", "한국사 연대기", "인물", "신숙주", "申叔舟", "", "개요", "…"],
        ["kc_i200400_0010", "kc_i200400", "n_4", "한국사 연대기", "사건", "무신정변", "武臣政變",
         "", "개요", "100년 무신정권의 시작. 의종 24년(1170)에 일어났다."],
    ]
    ents = nikh.group_entities(rows)
    check("절 단위 행이 항목으로 묶인다", len(ents) == 4 and len(ents[0].sections) == 2)
    ev = ents[0]
    check("연도는 재위년 괄호가 붙은 것을 먼저 믿는다", nikh.entity_year(ev) == 1443)
    check("'100년 무신정권' 은 연도가 아니다 — 괄호 안 1170 을 쓴다",
          nikh.entity_year(ents[3]) == 1170, str(nikh.entity_year(ents[3])))
    check("연대기 ID 의 자릿수가 시대다", nikh.era_of(ev, 1443) == "조선" and nikh.era_of(ents[3], 1170) == "고려")

    ms = nikh.mentions(ev.full_text(), ["세종", "신숙주"], plain_text=ev.overview)
    names = {(n, h) for n, h, _ in ms}
    check("이름(漢字) 언급을 잡는다", ("신숙주", "申叔舟") in names and ("성삼문", "成三問") in names, str(names))
    check("연대기 인물은 맨 이름으로도 잡는다", ("세종", "") in names, str(names))
    check("'세종대왕기념사업회' 안의 세종은 언급이 아니다",
          sum(1 for n, _, _ in ms if n == "세종") == 1, str(ms))
    check("검색어는 이름 전체, 꼬리말을 뗀 몸통, 그리고 낱말 전부를 요구하는 검색",
          nikh._search_terms("4군 6진 개척") == [("4군 6진 개척", ()), ("4군 6진", ()), ("4군", ("4군", "6진")), ("4군", ()), ("6진", ())],
          str(nikh._search_terms("4군 6진 개척")))
    check("두 글자 몸통('기묘')은 검색하지 않는다 — 간지에 걸린다",
          nikh._search_terms("기묘사화") == [("기묘사화", ())], str(nikh._search_terms("기묘사화")))

    # 실록 색인: 작은 XML 로 만든다
    raw = Path(tmp)
    (raw / "sillok").mkdir()
    (raw / "sillok" / "2nd_wda_125.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<level2 id="wda_125"><level4 id="wda_12512030">
 <level5 id="wda_12512030_001"><front><biblioData type="T"><title><mainTitle>삭제에 쓸 향과 축문을 전하다</mainTitle></title>
  <date><dateOccured date="1443-12-30L0" type="서기"/></date></biblioData></front>
  <text><content><paragraph>○傳香祝。</paragraph></content></text></level5>
 <level5 id="wda_12512030_002"><front><biblioData type="T"><title><mainTitle>훈민정음을 창제하다</mainTitle></title>
  <date><dateOccured date="1443-12-30L0" type="서기"/></date><subjectClass>어문학-문학(文學)</subjectClass></biblioData></front>
  <text><content><paragraph>○是月, 上親制諺文二十八字, 是謂<index num="1" type="서명">訓民正音</index>。</paragraph></content></text></level5>
 <level5 id="wda_12812001_001"><front><biblioData type="T"><title><mainTitle>훈민정음을 반포하다</mainTitle></title>
  <date><dateOccured date="1446-09-29L0" type="서기"/></date></biblioData></front>
  <text><content><paragraph>○<index num="2" ref="M_0000001" type="이름">鄭麟趾</index></paragraph></content></text></level5>
</level4></level2>""", encoding="utf-8")
    (raw / "sillok_gojong").mkdir()
    n = nikh.build_sillok_index(raw, raw / "sillok.sqlite")
    check("실록 기사가 색인된다", n == 3, str(n))
    idx = nikh.SillokIndex(raw / "sillok.sqlite")
    hit = nikh.date_from_sillok(idx, "훈민정음 창제", [1446, 1443])
    check("후보 연도 순서대로 같은 해 기사를 찾는다 (1446 반포가 먼저 걸린다)", hit and hit["date"] == "1446-09-29L0", str(hit))
    hit = nikh.date_from_sillok(idx, "훈민정음 창제", [1443])
    check("같은 해의 가장 이른 기사가 날짜다", hit and hit["date"] == "1443-12-30L0", str(hit))
    check("후보 연도에 기사가 없으면 고르지 않는다", nikh.date_from_sillok(idx, "훈민정음 창제", [1450]) is None)
    check("음력 날짜의 윤달 꼬리를 뗀다", nikh.lunar_iso("1443-12-30L0") == "1443-12-30")
    check("연도를 모르고 기사가 많으면 고르지 않는다",
          nikh.date_from_sillok(idx, "훈민정음", None) is not None  # 2건뿐이라 고른다
          and nikh.date_from_sillok(idx, "향과 축문", None)["date"].startswith("1443"))
    refs = idx.conn.execute("SELECT refs FROM articles WHERE id='wda_12812001_001'").fetchone()[0]
    check("인명 색인의 인물 ID 가 기사에 붙는다", refs == "M_0000001", refs)
    # 「규장각」 항목 본문의 김조순이 1781년 절목 기사의 참여자로 섰던 일.
    # 실록 기사에는 그 기사에 이름이 있는 사람만 잇는다.
    names, text = idx.article_people("wda_12812001_001")
    check("기사의 인명 색인과 원문을 준다", names == {"鄭麟趾"} and "鄭麟趾" in text, str((names, text)))
    check("한자 이름이 기사에 있어야 그 기사의 참여자다",
          nikh.named_in_article("鄭麟趾", names, text)
          and not nikh.named_in_article("金祖淳", names, text))
    check("한글만 아는 사람은 한문 기사에서 못 찾으므로 잇지 않는다",
          not nikh.named_in_article("", names, text))
    check("없는 기사는 빈 것이다", idx.article_people("없음") == (frozenset(), ""))
    check("관청·건물 한자는 사람 이름이 아니다 (이문원(摛文院) ≠ 이문원(李文源))",
          nikh.NOT_A_PERSON.search("摛文院") and not nikh.NOT_A_PERSON.search("李文源"))

    # 이름이 같은 노드 가르기
    store = GraphStore(raw / "g.sqlite")
    store.upsert_nodes([
        Node(id="wd:A", type="person", label="김구", source="wd", start_date="1876"),
        Node(id="wd:B", type="person", label="김구", source="wd", start_date="1488"),
        Node(id="wd:E1", type="event", label="임진왜란", source="wd", start_date="1592"),
        Node(id="wd:E2", type="event", label="임진왜란", source="wd", start_date="1592"),
        Node(id="wd:P", type="person", label="이순신", source="wd"),
        Node(id="ex:event:훈민정음 창제", type="event", label="훈민정음 창제", source="extract"),
    ])
    store.upsert_edges([Edge(src="wd:P", dst="wd:E1", type="participated_in", source="wd")])
    nidx = nikh.NodeIndex(store)
    p_modern = nikh.Entity("kc_n400100", "인물", "김구", "金九", "")
    p_joseon = nikh.Entity("kc_n300100", "인물", "김구", "金絿", "")
    check("같은 이름은 시대로 가른다",
          nikh.pick_target(nidx, p_modern)[0] == "wd:A"
          and nikh.pick_target(nidx, p_joseon)[0] == "wd:B")
    check("실록 인물 CSV 의 생년이 있으면 그것으로 가른다",
          nikh.pick_target(nidx, p_joseon, birth=1876)[0] == "wd:A")
    e_imjin = nikh.Entity("kc_i300500", "사건", "임진왜란", "壬辰倭亂", "1592년(선조 25) 일본이 침입한 전쟁")
    check("연대까지 같으면 차수가 압도적인 쪽만 받는다",
          nikh.pick_target(nidx, e_imjin, [1592])[0] == "wd:E1")
    nid, orphans, _ = nikh.pick_target(nidx, ev, [1443])
    check("이름이 같은 추출 고아는 흡수 대상이다", nid is None and orphans == ["ex:event:훈민정음 창제"], str((nid, orphans)))
    # 라벨의 정체 낱말이 항목의 시대와 다르면 후보가 아니다 — 고려 원종 항목이
    # '조선 원종'(정원군)에 씌워졌던 사고 (2026-09-05)
    store.upsert_nodes([
        Node(id="wd:W1", type="person", label="조선 원종", source="wd", start_date="1580", aliases=["원종"]),
        Node(id="wd:W2", type="person", label="고려 원종", source="wd", aliases=["원종"]),
    ])
    store.upsert_edges([Edge(src="wd:W1", dst="wd:E1", type="participated_in", source="wd"),
                        Edge(src="wd:W1", dst="wd:E2", type="participated_in", source="wd"),
                        Edge(src="wd:W1", dst="wd:P", type="child_of", source="wd")])
    nidx = nikh.NodeIndex(store)
    p_goryeo = nikh.Entity("kc_n203300", "인물", "원종", "元宗", "")
    check("고려 항목의 '원종'은 차수가 커도 조선 원종에게 가지 않는다",
          nikh.pick_target(nidx, p_goryeo)[0] == "wd:W2", str(nikh.pick_target(nidx, p_goryeo)))
    check("정체 낱말이 없는 라벨은 관문에 걸리지 않는다",
          not nikh.polity_mismatch("원종", "고려") and nikh.polity_mismatch("조선 원종", "고려")
          and not nikh.polity_mismatch("고려 원종", "고려"))
    store.close()


# --- 말뭉치 (RAG 저장·검색층) ---------------------------------------------
# "이재명은 12.3 내란에 참여했다"가 틀렸다는 것은 구조화 소스 어디에도
# 없고 산문에만 있다. 글을 문단으로 쪼개 두고 찾을 수 있어야 한다.
from histgraph import corpus as corpus_mod  # noqa: E402
from histgraph import roles as roles_mod  # noqa: E402
from histgraph.sources.infobox import FIELD_LABEL, FIELD_SIDE  # noqa: E402

_DOC = """12.3 내란은 2024년 12월 3일 윤석열이 비상계엄을 선포한 사건이다.

== 배경 ==
정부 지지율이 최저 17%까지 하락하는 등 부정적 평가를 받았다.

=== 국회 개회 및 계엄 해제 ===
계엄 선포 직후 국회의장 우원식은 국회를 긴급소집했다. 경찰 바리케이드를 피해 11시경 이재명, 우원식은 담을 넘어 국회 건물에 들어갔다.

=== 체포 지시 ===
여 사령관은 다음과 같은 체포 명단을 불러주며 위치 추적을 요청했다: 이재명 더불어민주당 대표 우원식 국회의장 한동훈 국민의힘 대표

== 각주 ==
1. 오마이뉴스 2024년 12월 4일
"""
parts = corpus_mod.split_passages(_DOC)
sections = [sec for sec, _ in parts]
check("절 제목이 문단에 붙는다", "체포 지시" in sections, str(sections))
check("각주 절은 글이 아니다", not any("오마이뉴스" in t for _, t in parts))
check("절이 바뀌면 묶음도 끊긴다",
      not any("담을 넘어" in t and "체포 명단" in t for _, t in parts))
long = "가나다라마바사. " * 300
check("긴 문단은 문장에서 자른다",
      all(len(t) <= corpus_mod.PASSAGE_MAX + 20 for _, t in corpus_mod.split_passages(long)))

with tempfile.TemporaryDirectory() as tmp:
    conn = corpus_mod.open_corpus(Path(tmp) / "c.sqlite")
    n = corpus_mod.put_doc(conn, "wd:EV", "12.3 내란", _DOC)
    corpus_mod.put_doc(conn, "wd:P", "이재명", "이재명은 2025년 6월 4일 대통령에 취임했다.\n\n계엄 당시 국회 담을 넘었다.")
    check("문서를 문단으로 넣는다", n >= 3 and corpus_mod.stats(conn)["docs"] == 2)
    hits = corpus_mod.search(conn, "체포 명단")
    check("두 글자 낱말을 FTS 로 찾는다", hits and "체포 명단" in hits[0]["text"], str(hits[:1]))
    hits = corpus_mod.search(conn, "우원식은")
    check("조사가 붙어도 찾는다 (앞머리 일치)", hits and "우원식" in hits[0]["text"], str(hits[:1]))
    hits = corpus_mod.search(conn, "긴급소집")
    check("어절 안의 낱말은 앞머리 일치라 찾는다", hits and "긴급소집" in hits[0]["text"], str(hits[:1]))
    hits = corpus_mod.search(conn, "담")
    check("한 글자는 LIKE 로 물러난다", any("담을 넘어" in h["text"] for h in hits))
    check("fts 질의는 토큰을 따옴표로 감싸고 기본은 AND 다",
          corpus_mod.fts_query("12.3 내란 체포") == '"12.3"* AND "내란"* AND "체포"*', corpus_mod.fts_query("12.3 내란 체포"))
    corpus_mod.put_doc(conn, "wd:P2", "형수 욕설", "이재명 이재명 이재명 이재명 이재명 이재명이 욕설을 했다.")
    hits = corpus_mod.search(conn, "체포 명단 이재명")
    check("다 있는 문단이 이름 반복에 밀리지 않는다", hits and "체포 명단" in hits[0]["text"], str(hits[:1]))
    hits = corpus_mod.search(conn, "체포 명단 없는말이다")
    check("다 있는 문단이 없으면 OR 로 물러난다", any("체포 명단" in h["text"] for h in hits))
    ment = corpus_mod.mentions(conn, "wd:EV", ["이재명"])
    check("이름이 나오는 문단을 문서 순서로 준다",
          [m["section"] for m in ment] == ["국회 개회 및 계엄 해제", "체포 지시"], str([m["section"] for m in ment]))
    corpus_mod.put_doc(conn, "wd:EV", "12.3 내란", "다시 넣은 글. 아무 이름도 없다.")
    check("같은 노드를 다시 넣으면 옛 문단이 지워진다",
          not corpus_mod.mentions(conn, "wd:EV", ["이재명"]) and corpus_mod.stats(conn)["docs"] == 3)
    corpus_mod.reindex(conn)
    check("색인을 다시 지어도 같은 것을 찾는다", any("욕설" in h["text"] for h in corpus_mod.search(conn, "욕설")))
    conn.close()

# --- 말뭉치의 정본: 한 노드에 소스가 여럿 -----------------------------------
# 사용자가 민족문화대백과·한국사연대기를 정본이라 했다 (2026-09-04). 같은
# 노드의 문단을 줄 때 정본이 앞서고, 위키백과는 지워지지 않는다.
import sqlite3  # noqa: E402
from histgraph.sources import aks as aks_mod  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "multi.sqlite"
    # 옛 파일(node_id 하나가 유일 열쇠)을 흉내 내 두고 연다 — 옮겨져야 한다
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE docs (id INTEGER PRIMARY KEY, node_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
            source TEXT NOT NULL, url TEXT, fetched_at TEXT NOT NULL, chars INTEGER NOT NULL);
        CREATE TABLE passages (id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL, n INTEGER NOT NULL, section TEXT NOT NULL DEFAULT '', text TEXT NOT NULL);
        INSERT INTO docs VALUES (1, 'wd:EV', '12.3 내란', 'kowiki', NULL, '2026', 10);
        INSERT INTO passages VALUES (1, 1, 'wd:EV', 0, '', '위키백과: 이재명은 담을 넘었다.');
    """)
    old.commit(); old.close()
    conn = corpus_mod.open_corpus(path)
    check("옛 말뭉치 파일의 열쇠가 (노드, 소스)로 바뀐다",
          "UNIQUE (node_id, source)" in conn.execute(
              "SELECT sql FROM sqlite_master WHERE name='docs'").fetchone()[0]
          and corpus_mod.stats(conn)["docs"] == 1)
    corpus_mod.put_doc(conn, "wd:EV", "12·3 비상계엄", "== 정의 ==\n정본: 이재명은 체포 대상이었다.", "aks")
    st = corpus_mod.stats(conn)
    check("같은 노드에 소스별로 글이 나란히 든다",
          st["docs"] == 2 and st["by_source"] == {"aks": 1, "kowiki": 1}, str(st))
    check("has_doc 은 소스를 가려 묻는다",
          corpus_mod.has_doc(conn, "wd:EV") and corpus_mod.has_doc(conn, "wd:EV", "aks")
          and not corpus_mod.has_doc(conn, "wd:EV", "nikh"))
    ment = corpus_mod.mentions(conn, "wd:EV", ["이재명"])
    check("같은 노드의 문단은 정본이 앞선다",
          [m["source"] for m in ment] == ["aks", "kowiki"], str([m["source"] for m in ment]))
    corpus_mod.put_doc(conn, "wd:EV", "12·3 비상계엄", "== 정의 ==\n정본을 다시 넣었다. 이름 없음.", "aks")
    check("다시 넣으면 그 소스의 글만 바뀐다",
          corpus_mod.stats(conn)["docs"] == 2
          and [m["source"] for m in corpus_mod.mentions(conn, "wd:EV", ["이재명"])] == ["kowiki"])
    conn.close()

# --- 민족문화대백과 커넥터 -------------------------------------------------
print("\n[민족문화대백과 — 잇기·본문]")
check("이름 정규화: 괄호와 띄어쓰기를 뗀다",
      aks_mod.norm_name("김용현 (군인)") == "김용현" and aks_mod.norm_name("1·4 후퇴") == "1·4후퇴")
_E = lambda i, label, kind, era="현대/대한민국": aks_mod.Entry(  # noqa: E731
    id=i, url=f"https://encykorea.aks.ac.kr/Article/{i}", label=label, hanja="",
    field="", kind=kind, era=era, definition="정의.")
entries = [
    _E("E1", "이재명", "인물/근현대 인물"),
    _E("E2", "김규식", "인물/근현대 인물"), _E("E3", "김규식", "인물/근현대 인물"),
    _E("E4", "1·4후퇴", "사건"), _E("E5", "황진이", "인물/전통 인물", "조선"),
    _E("E6", "네덜란드", "지명/국가"), _E("E7", "갑자사화", "사건", "조선"),
]
nodes = [("wd:1", "이재명", "person"), ("wd:2", "김규식", "person"),
         ("wd:4", "1·4 후퇴", "event"), ("wd:5", "황진이", "media"),
         ("wd:6", "네덜란드", "place"), ("wd:6b", "네덜란드", "place")]
m = aks_mod.match_nodes(entries, nodes)
check("이름·타입이 맞고 양쪽 다 하나뿐일 때만 잇는다", m == {"E1": "wd:1", "E4": "wd:4"}, str(m))
m2 = aks_mod.match_nodes(entries + [_E("E8", "10월유신", "사건")],
                         nodes + [("wd:8", "10월 유신", "event"), ("wd:8", "유신 체제", "event"),
                                  ("wd:8", "10월유신", "event")])
check("별칭으로도 잇되 노드 쪽 '하나뿐'은 노드 수로 센다", m2.get("E8") == "wd:8", str(m2))
todo = aks_mod.select_entries(entries, m, kinds=("사건",))
check("이은 항목 + 근현대 사건, 근현대 사건이 앞", [e.id for e in todo] == ["E4", "E1"], str([e.id for e in todo]))
page = """<html><section class="content_section"><h3 class="tit">내용 요약</h3>
<div class="detail">사전이 만든 요약</div></section>
<section class="content_section"><h3 class="tit">정의</h3><div class="detail">재미 한인들이 전개한 운동.</div></section>
<section class="content_section"><h3 class="tit">경과</h3><div class="detail"><p>첫 문단 <a href="/x">링크</a>&nbsp;끝.</p><p>둘째 문단.</p></div></section>
<section class="content_section"><h3 class="tit">참고문헌</h3><div class="detail">『책』</div></section></html>"""
secs = aks_mod.parse_article(page)
check("절 단위로 읽고 요약·참고문헌은 뺀다", [t for t, _ in secs] == ["정의", "경과"], str(secs))
check("태그를 벗기고 문단 줄을 지킨다", secs[1][1] == "첫 문단 링크 끝.\n둘째 문단.", repr(secs[1][1]))
text = aks_mod.article_text(secs)
check("말뭉치가 쪼개는 모양이다", [s for s, _ in corpus_mod.split_passages(text)] == ["정의", "경과"])

# 빈 설명을 사전의 '정의 한 문장'으로 채운다. 사용자 지적(2026-09-04)에
# 따라 설명 없는 노드를 지우기로 했으므로, 지우기 전에 채울 수 있는 것을
# 다 채우는 이 길이 먼저 있어야 한다 — 실측: 빈 설명 3,297개 중 wd 노드
# 415개는 위키백과·Wikidata 에, 304개는 이 사전에 글이 있었다.
print("\n[민족문화대백과 — 빈 설명 채우기]")
with tempfile.TemporaryDirectory() as tmp:
    raw = Path(tmp) / "raw"
    raw.mkdir()
    rows = [
        ("E1", "목민심서", "문헌/고서", "정약용이 지은 책."),
        ("E2", "영의정", "제도/관직", "조선시대 의정부의 으뜸 벼슬."),
        ("E3", "김규식", "인물/근현대 인물", "독립운동가 하나."),
        ("E4", "김규식", "인물/근현대 인물", "독립운동가 둘."),
        ("E5", "설명이있는사건", "사건", "덮어쓰면 안 되는 정의."),
        ("E6", "한자만", "사건", "漢字"),
    ]
    head = "항목 아이디,항목 고유 웹주소,대표 미디어 아이디,항목명,원어,항목 분야,항목 유형,시대,항목 정의,집필자 정보"
    body = "\n".join(
        f"{i},https://encykorea.aks.ac.kr/Article/{i},x,{label},,,{kind},조선,{d},글쓴이"
        for i, label, kind, d in rows)
    (raw / aks_mod.INDEX_CSV).write_text("\ufeff" + head + "\n" + body + "\n", encoding="utf-8")

    store = GraphStore(Path(tmp) / "desc.sqlite")
    store.upsert_nodes([
        Node(id="ex:artwork:목민심서", type="artwork", label="목민심서", source="extract"),
        Node(id="ex:role:영의정", type="role", label="영의정", source="extract"),
        Node(id="ex:person:김규식", type="person", label="김규식", source="extract"),
        Node(id="wd:HAVE", type="event", label="설명이있는사건", source="wd",
             description="이미 적혀 있는 설명."),
        Node(id="wd:HANJA", type="event", label="한자만", source="wd"),
    ])
    rep = aks_mod.fill_descriptions(store, raw_dir=raw)
    got = dict(store.conn.execute("SELECT id, description FROM nodes"))
    check("유형 표를 넓혀 문헌·관직도 받는다",
          got["ex:artwork:목민심서"] == "정약용이 지은 책."
          and got["ex:role:영의정"] == "조선시대 의정부의 으뜸 벼슬.", str(got))
    check("동명이인에는 남의 정의를 붙이지 않는다",
          not (got["ex:person:김규식"] or "") and rep["ambiguous"] == 1, str(rep))
    check("이미 적힌 설명은 덮어쓰지 않는다", got["wd:HAVE"] == "이미 적혀 있는 설명.")
    check("한글이 한 자도 없는 정의는 넣지 않는다", not (got["wd:HANJA"] or ""))
    check("채운 수를 센다", rep["filled"] == 2, str(rep))

    # 파생본 두 번째 빗질 — redescribe 가 설명을 비운 뒤에도 걸러야 한다
    from histgraph.scope import sweep_undescribed  # noqa: E402

    store.upsert_edges([
        Edge(src="wd:HAVE", dst="wd:HANJA", type="related_to", source="wd"),
    ])
    swept = sweep_undescribed(store.conn)
    left = {r[0] for r in store.conn.execute("SELECT id FROM nodes")}
    check("설명이 빈 내용 노드는 파생본에서 지운다", "wd:HANJA" not in left, str(sorted(left)))
    check("직위는 설명이 없어도 남긴다", "ex:role:영의정" in left, str(sorted(left)))
    check("지운 노드의 엣지도 같이 지운다",
          store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
          and swept["edges"] == 1, str(swept))
    store.close()

# --- 역할 판정 -------------------------------------------------------------
passages = [{"title": "12.3 내란", "section": "체포 지시",
             "text": "여 사령관은 다음과 같은 체포 명단을 불러주며 위치 추적을 요청했다: 이재명 더불어민주당 대표"}]
v = roles_mod.accept([{"role": "표적", "evidence": "체포 명단을 불러주며 위치 추적을 요청했다", "confidence": "certain"}], passages)
check("근거가 문단에 있으면 판정을 받는다", v == {"role": "표적", "evidence": "체포 명단을 불러주며 위치 추적을 요청했다", "confidence": 0.9}, str(v))
check("근거가 문단에 없으면 버린다",
      roles_mod.accept([{"role": "주도", "evidence": "그가 계엄을 계획했다", "confidence": "certain"}], passages) is None)
check("목록 밖의 역할은 버린다",
      roles_mod.accept([{"role": "영웅", "evidence": "체포 명단", "confidence": "certain"}], passages) is None)
check("빈 답은 None", roles_mod.accept([], passages) is None)
check("인포박스 칸 이름이 라벨이 되고 편 번호를 읽는다",
      FIELD_LABEL["주요인물2"] == "주요 인물" and FIELD_SIDE.search("주요인물2").group(1) == "2"
      and FIELD_SIDE.search("참가자") is None)

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "roles.sqlite")
    store.upsert_nodes([
        Node(id="wd:EV", type="event", label="12.3 내란", source="wd", start_date="2024-12-03"),
        Node(id="wd:OLD", type="event", label="갑자사화", source="wd", start_date="1504"),
        Node(id="wd:P1", type="person", label="이재명", source="wd"),
        Node(id="wd:P2", type="person", label="김용현 (군인)", source="wd"),
        Node(id="wd:P3", type="person", label="연산군", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:P1", dst="wd:EV", type="participated_in", source="kowiki:infobox",
             label="주요 인물", confidence=0.95, props={"infobox_field": "주요인물2", "side": 2}),
        Edge(src="wd:P2", dst="wd:EV", type="participated_in", source="kowiki:infobox",
             label="주요 인물", confidence=0.95, props={"infobox_field": "주요인물1", "side": 1}),
        Edge(src="wd:P3", dst="wd:OLD", type="participated_in", source="wd"),
    ])
    conn = corpus_mod.open_corpus(Path(tmp) / "c.sqlite")
    corpus_mod.put_doc(conn, "wd:EV", "12.3 내란", _DOC)
    cands = roles_mod.candidates(store, conn, since=1945)
    check("말뭉치에 문서가 있는 근현대 사건의 참여 엣지만 후보다",
          {c["src"] for c in cands} == {"wd:P1", "wd:P2"}, str([c["src"] for c in cands]))
    check("문서명 괄호를 뗀 이름으로도 찾는다", "김용현" in roles_mod.names_of(store, "wd:P2"))
    # 판정 안 된 참여가 3,665건이라 한 번에 다 물으면 며칠이 걸린다.
    # 새로 들어온 것부터 묻는 칸 (2026-09-06, `causes` 가 돌린 참여).
    check("소스를 주면 그 소스가 만든 참여만 후보다",
          {c["src"] for c in roles_mod.candidates(store, conn, since=1945,
                                                  sources=frozenset({"kowiki:infobox"}))}
          == {"wd:P1", "wd:P2"}
          and roles_mod.candidates(store, conn, since=1945,
                                   sources=frozenset({"causes"})) == [])
    got = roles_mod.gather(store, conn, "wd:P1", "wd:EV")
    check("그 사람이 나오는 문단만 모은다", got and all("이재명" in g["text"] for g in got))
    check("문단이 없으면 빈 목록", roles_mod.gather(store, conn, "wd:P2", "wd:EV") == [])

    class _Fake:
        model = "fake"
        def complete(self, system, user, schema):
            assert "이재명" in user and "체포 명단" in user
            return [{"role": "표적", "evidence": "체포 명단을 불러주며", "confidence": "certain"}]

    got = roles_mod.run(store, conn, _Fake(), since=1945)
    check("문단이 있는 것만 모델에 묻고 없는 것은 근거 없음",
          got["by_role"] == {"표적": 1, "근거 없음": 1}, str(got))
    moved = store.conn.execute(
        "SELECT type, label, json_extract(props,'$.role') AS role, json_extract(props,'$.was') AS was,"
        " json_extract(props,'$.role_evidence') AS ev FROM edges WHERE src='wd:P1' AND dst='wd:EV'").fetchall()
    check("피해·표적은 참여가 아니라 관련으로 옮긴다",
          len(moved) == 1 and moved[0]["type"] == "related_to" and moved[0]["label"] == "표적"
          and moved[0]["was"] == "participated_in" and "체포 명단" in moved[0]["ev"], str([dict(m) for m in moved]))
    none = store.conn.execute(
        "SELECT type, label FROM edges WHERE src='wd:P2' AND dst='wd:EV'").fetchone()
    check("근거 없는 참여는 화면에 두지 않는다", none["type"] == "related_to" and none["label"] == "근거 없음")
    check("한 번 판정한 엣지는 다시 묻지 않는다", roles_mod.candidates(store, conn, since=1945) == [])
    store.upsert_edges([Edge(src="wd:P3", dst="wd:EV", type="participated_in", source="roles",
                             label="주도", props={"role": "주도"})])
    check("역할을 지정하면 그 역할로 판정됐던 엣지만 다시 묻는다",
          [c["src"] for c in roles_mod.candidates(store, conn, since=1945, redo=True, only_roles={"주도"})] == ["wd:P3"])
    api = GraphAPI(store, era="korea")
    rel = [r for r in api.node("wd:P1")["relations"] if r["other"]["id"] == "wd:EV"]
    check("화면에 역할과 근거가 함께 간다",
          rel and rel[0]["edge_label"] == "표적" and any("체포 명단" in e for e in rel[0]["evidence"]), str(rel))
    conn.close()
    store.close()


# --- 동명이인 관문 ------------------------------------------------------------
# "여진 정벌은 고려때 일이야 왜 조선과 연결된지 모르겠어. 아마 왕이름이
# 겹쳐서 그럴거야" (2026-09-04). 연표의 날짜와 이름 해소 두 자리를 고정한다.
from histgraph import homonyms as hom_mod  # noqa: E402
from histgraph.extract import pick_candidate  # noqa: E402

print("\n[동명이인]")

# 1) 연대기의 '설명' 칸이 딴 사건을 말할 때. kc_i304300(조선 여진 정벌)의
#    설명은 고려 예종의 1107년 정벌이고 본문은 태종~선조대다. 첫 후보를
#    그대로 쓰면 조선 사건이 1107년 자리에 선다.
_yeojin = nikh.Entity(
    "kc_i304300", "사건", "여진 정벌", "女眞征伐",
    "예종이 숙종의 유지를 이어받아 1107년부터 시작한 여진에 대한 정벌.",
    [("개요", "조선 전기~중기에 걸쳐 이루어진 여진족에 대한 대규모 군사활동."),
     ("태종대의 여진 정벌", "최초의 여진 정벌은 1406년(태종 6) 태종에 의해 이루어졌다.")],
)
check("시대 창은 연대기 ID 의 자릿수에서 나온다",
      nikh.era_window(_yeojin) == (1360, 1900), str(nikh.era_window(_yeojin)))
_date, _basis, _ = nikh.resolve_date(_yeojin, None, None)
check("짐작한 해는 그 항목의 시대 안에 든다 (1107 이 아니라 1406)",
      (_date, _basis) == ("1406", "연대기 설명"), str((_date, _basis)))
_goryeo = nikh.Entity("kc_i204300", "사건", "여진 정벌", "女眞征伐",
                      "예종이 1107년부터 시작한 여진에 대한 정벌.")
check("고려 항목이면 1107 을 그대로 받는다",
      nikh.resolve_date(_goryeo, None, None)[0] == "1107")
_only_out = nikh.Entity("kc_i300001", "사건", "가짜 사건", "", "1107년에 있었다.")
check("시대 밖의 해뿐이면 지어내지 않고 비운다",
      nikh.resolve_date(_only_out, None, None) == (None, None, {}))
check("실록·기존 노드와 맞은 해는 창을 보지 않는다",
      nikh.resolve_date(_yeojin, None, 1107)[1] == "연대기·기존 일치")
check("시대 밖의 해만 말하는 '설명' 칸은 딴 항목의 것이다",
      nikh.summary_is_alien(_yeojin) and not nikh.summary_is_alien(_goryeo))
check("인물의 설명 칸은 시대보다 앞서도 된다",
      not nikh.summary_is_alien(
          nikh.Entity("kc_n403710", "인물", "이승훈", "", "1783년에 세례를 받았다.")))

# 국편 파일이 두 정종(3대 定宗 · 10대 靖宗)의 본문을 맞바꿔 담았다
# (2026-09-06). 합치고 나면 이 본문이 진짜 노드의 설명이 되므로 버린다.
_jeong3 = nikh.Entity("kc_n204400", "인물", "정종[고려]", "定宗",
                      "고려의 제3대 왕으로 이름은 요(堯).")
_jeong3.sections = [("머리말", "고려 10대 국왕인 정종(靖宗)은 현종의 둘째로 태어났다.")]
check("주인공 이름에 붙은 대수가 설명과 다르면 본문을 버린다",
      nikh.overview_is_alien(_jeong3))
# 고종 본문의 '조선의 25대 임금인 철종이 승하하자' 는 앞 임금 이야기다.
_gojong = nikh.Entity("kc_n400200", "인물", "고종[조선]", "高宗",
                      "조선의 제26대 국왕.")
_gojong.sections = [("머리말", "조선의 25대 임금인 철종이 승하하자 뒤를 이어 즉위하였다.")]
check("앞 임금의 대수를 말하는 본문은 버리지 않는다",
      not nikh.overview_is_alien(_gojong))
_evt = nikh.Entity("kc_i201300", "사건", "이자겸의 난", "", "1126년의 난.")
_evt.sections = [("머리말", "고려 17대 국왕인 인종 때의 일이다.")]
check("사건 본문에는 여러 임금의 대수가 섞여도 된다",
      not nikh.overview_is_alien(_evt))

# 합칠 때 설명은 안 옮기면서 출처만 옮기면 화면이 위키백과 글에 국편
# 딱지를 단다 — 라이선스 표기가 틀리는 자리다 (2026-09-06).
import json as _json  # noqa: E402
_dupdir = tempfile.TemporaryDirectory()
_dupdb = GraphStore(Path(_dupdir.name) / "dup.sqlite")
_dupdb.conn.executemany(
    "INSERT INTO nodes (id, type, label, source, description, props)"
    " VALUES (?,?,?,?,?,?)",
    [("wd:K1", "person", "고려 정종 (3대)", "wd", "위키백과에서 온 글이다.", "{}"),
     ("nikh:K1", "person", "정종[고려]", "nikh", "국편에서 온 글이다.",
      '{"canon":"nikh","desc_source":"nikh","nikh_id":"kc_x","hanja":"定宗"}')],
)
_dupdb.conn.commit()
import histgraph.duplicates as _dup
_dup._carry_content(_dupdb.conn, "wd:K1", "nikh:K1")
_kept = _dupdb.conn.execute("SELECT description, props FROM nodes WHERE id='wd:K1'").fetchone()
_kprops = _json.loads(_kept["props"])
check("남길 쪽 설명이 그대로면 국편 출처 딱지는 따라오지 않는다",
      _kept["description"] == "위키백과에서 온 글이다."
      and "canon" not in _kprops and "desc_source" not in _kprops,
      str(_kprops))
check("출처가 아닌 칸은 그래도 옮긴다", _kprops.get("hanja") == "定宗")
check("지워질 글은 되짚을 수 있게 남는다",
      _kprops.get("merged_desc") == "국편에서 온 글이다.")
_dupdb.close()
_dupdir.cleanup()

# --- 연대기가 적어 둔 달 --------------------------------------------------
# "황산대첩은 1380년 9월 …이라고 한다. 9월이라고 표시해줘" (2026-09-04).
# 연표는 몰린 해 안의 차례를 달로 읽는데, 해만 알면 같은 해의 이웃 뒤에서
# 연도 칸이 빈다. 연대기 문장은 달을 적고 있다 — 다만 **그 항목 자신의**
# 달일 때만 받는다.
print("\n[연대기의 달]")

_hwangsan = nikh.Entity(
    "kc_i201700", "사건", "황산대첩", "荒山大捷",
    "1380년 9월, 이성계 등이 전라도 지리산 부근의 황산에서 왜구를 크게 격퇴시킨 전투이다.",
    [("개요", "황산대첩은 1380년(우왕 6) 9월에 이성계(李成桂)를 중심으로 한 고려군이 "
              "황산(荒山)에서 왜구를 크게 격퇴한 전투이다."),
     ("왜구들이 모여들다", "1380년(우왕 6) 8월, 대규모의 왜선이 진포(鎭浦)에 정박하였다.")],
)
check("설명·개요가 같은 달을 말하면 그 달을 받는다",
      nikh.month_of(_hwangsan, 1380) == 9, str(nikh.month_of(_hwangsan, 1380)))
check("본문의 달은 보지 않는다 — 진포대첩의 8월이 섞인다",
      nikh.dated(_hwangsan, 1380) == ("1380-09", {"calendar": "lunar"}),
      str(nikh.dated(_hwangsan, 1380)))
check("해가 다르면 그 달이 아니다", nikh.month_of(_hwangsan, 1376) is None)

# 설명 칸은 한 줄로 줄이다 엉뚱한 달을 적기도 한다. 명량해전의 설명은
# 이순신이 재임용된 8월을, 개요는 해전 자신의 9월 16일을 적는다.
_myeongnyang = nikh.Entity(
    "kc_i300000", "사건", "명량해전", "鳴梁海戰",
    "삼도수군통제사로 재임용된 이순신이 1597년 8월 명량 해협에서 일본군을 격파한 전투.",
    [("개요", "명량해전은 1597년(선조 30) 9월 16일 명량 해협에서 조선 수군이 "
              "일본 수군을 대파한 해전이다.")],
)
check("설명과 개요가 갈리면 달은 없는 것으로 둔다",
      nikh.month_of(_myeongnyang, 1597) is None, str(nikh.month_of(_myeongnyang, 1597)))

# 개요가 배경부터 시작하면 그 달은 이 항목의 달이 아니다.
_june = nikh.Entity(
    "kc_i400000", "사건", "6월민주화운동", "",
    "", [("개요", "1987년 1월 박종철이 고문으로 인해 사망한 사건이 알려지면서 "
                  "반대시위는 격화되기 시작했다.")],
)
check("항목을 부르지 않는 첫 문장의 달은 받지 않는다",
      nikh.month_of(_june, 1987) is None, str(nikh.month_of(_june, 1987)))

# 구간의 시작은 그 달의 일이 아니다.
_ugeum = nikh.Entity(
    "kc_i400100", "사건", "우금치 전투", "",
    "", [("개요", "우금치 전투는 1894년(고종 31) 10월 23일부터 11월 11일 사이에 "
                  "이루어진 두 차례의 전투를 말한다.")],
)
check("'10월 23일부터 11월 11일 사이' 는 10월의 일이 아니다",
      nikh.month_of(_ugeum, 1894) is None, str(nikh.month_of(_ugeum, 1894)))

check("양력을 쓴 뒤의 달에는 음력 딱지를 달지 않는다",
      nikh.dated(nikh.Entity("kc_i400200", "사건", "정전협정", "", "",
                             [("개요", "정전협정은 1953년 7월 27일에 조인되었다.")]),
                 1953) == ("1953-07", {}))

# 달은 **해가 이미 맞은 날짜를 자세하게만** 만든다. 일 단위로 아는 날짜를
# 밀어내면 자세해지는 것이 아니라 딴 날이 된다.
check("해가 같고 달만 붙는 것이면 받는다", nikh._refines("1380-09", "1380"))
check("이미 일까지 아는 날짜는 밀어내지 않는다", not nikh._refines("1380-09", "1380-06-15"))
check("같은 값은 고칠 것이 없다", not nikh._refines("1380", "1380"))


# 2) 문서의 주인공을 남에게 주지 않는다. 조선 예종의 휘가 이황(李晄)이라
#    별칭이 겹치는데, 32년 차이라 생몰 검사(여유 40년)에 안 걸린다.
_rows = [{"id": "wd:Q488694", "start_date": "1450", "end_date": "1469"},
         {"id": "wd:Q486291", "start_date": "1501", "end_date": "1570"}]
check("연대만으로는 예종과 퇴계를 못 가른다",
      pick_candidate(_rows, (1501, 1570))["id"] == "wd:Q488694")
check("후보 안에 출처 문서 자신이 있으면 그것이 답이다",
      pick_candidate(_rows, (1501, 1570), "wd:Q486291")["id"] == "wd:Q486291")
check("문서가 후보에 없으면 하던 대로 고른다",
      pick_candidate(_rows, (1501, 1570), "wd:Q999")["id"] == "wd:Q488694")

with tempfile.TemporaryDirectory() as _tmp:
    store = GraphStore(Path(_tmp) / "h.sqlite")
    store.upsert_nodes([
        Node(id="wd:YEJONG", type="person", label="조선 예종", source="wd",
             start_date="1450", end_date="1469", aliases=["이황"]),
        Node(id="wd:TOEGYE", type="person", label="이황", source="wd",
             start_date="1501", end_date="1570"),
        Node(id="ex:person:김해 허씨", type="person", label="김해 허씨", source="extract"),
        Node(id="wd:EV", type="event", label="안시성 전투", source="wd", start_date="0645"),
        Node(id="wd:YANG", type="person", label="양만춘", source="wd", start_date="0700"),
        Node(id="wd:LATE", type="person", label="정성근", source="wd", start_date="1955"),
        Node(id="wd:SAHWA", type="event", label="갑자사화", source="wd", start_date="1504"),
    ])
    store.upsert_edges([
        Edge(src="wd:YEJONG", dst="ex:person:김해 허씨", type="spouse_of",
             source="extract", props={"extracted_from": "wd:TOEGYE"}),
        Edge(src="wd:YANG", dst="wd:EV", type="participated_in", source="wd"),
        Edge(src="wd:LATE", dst="wd:SAHWA", type="participated_in", source="extract"),
    ])
    found = hom_mod.misrouted_edges(store.conn)
    check("문서의 주인공이 남에게 간 엣지를 찾는다",
          found == [("wd:YEJONG", "ex:person:김해 허씨", "spouse_of",
                     "wd:YEJONG", "wd:TOEGYE")], str(found))
    rep = hom_mod.sweep(store.conn)
    moved = store.conn.execute(
        "SELECT src, json_extract(props,'$.repointed_from') AS was FROM edges"
        " WHERE type = 'spouse_of'").fetchone()
    check("퇴계의 혼인을 퇴계에게 돌려놓는다",
          rep.repointed == 1 and moved["src"] == "wd:TOEGYE"
          and moved["was"] == "wd:YEJONG", str(dict(moved)))
    check("100년 넘게 어긋난 참여만 충돌로 센다",
          [c[1] for c in rep.conflicts] == ["정성근"], str(rep.conflicts))
    check("양만춘의 틀린 생년은 지우지 않고 가까운 쪽에 둔다",
          [c[1] for c in rep.near] == ["양만춘"] and store.conn.execute(
              "SELECT COUNT(*) FROM edges WHERE type='participated_in'"
          ).fetchone()[0] == 2)
    check("다른 노드의 라벨이기도 한 별칭을 센다",
          rep.alias_clashes == [("이황", "wd:YEJONG", "조선 예종", "wd:TOEGYE")],
          str(rep.alias_clashes))
    store.close()


# --- 중복 관문: 한 사건이 두 노드로 -------------------------------------------
#
# 2026-09-04 지적: "사도세자 사건과, 임오화변은 같은거야." 소스마다 표제를
# 다르게 달아 같은 일이 두 노드가 된다. 규칙은 후보를 찾을 뿐이고, 합치는
# 것은 표에 적힌 짝뿐이다 — 라벨이 비슷하다고 합치면 절반이 틀린다.

print("\n[중복 관문]")
from histgraph import duplicates as dup_mod  # noqa: E402

check("갈래 접미사와 차수를 뗀 핵심어",
      (dup_mod.core_name("제2차 진주성 전투"), dup_mod.core_name("홍산대첩"))
      == ("진주성", "홍산"))

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "dup.sqlite")
    store.upsert_nodes([
        Node(id="nikh:SADO", type="event", label="사도세자 사건", source="nikh",
             start_date="1762-05",
             description="1762년(영조 38) 5월 영조가 아들인 사도세자를 뒤주에 가두어"
                         " 죽인 사건으로, ‘임오화변’이라고도 한다."),
        Node(id="wd:IMO", type="event", label="임오화변", source="wd",
             start_date="1762-07-05", url="https://ko.wikipedia.org/wiki/임오화변",
             description="임오화변(壬午禍變), 임오옥(壬午獄) 또는 사도세자"
                         " 사건(思悼世子事件)은 1762년 7월 4일 사도세자가 뒤주에"
                         " 갇혔다가 죽은 사건이다."),
        Node(id="nikh:SAMIL", type="event", label="3·1운동", source="nikh"),
        Node(id="wd:SAMIL", type="event", label="3·1 운동", source="wd"),
        Node(id="ex:event:반탁 운동", type="event", label="반탁 운동", source="extract"),
        Node(id="wd:BANTAK", type="event", label="신탁 통치 반대 운동", source="wd",
             description="신탁 통치 반대 운동(信託統治反對運動) 또는 반탁"
                         " 운동(反託運動)은 1945년 12월에 일어난 국민 운동이다."),
        Node(id="wd:WANGJA1", type="event", label="제1차 왕자의 난", source="wd",
             start_date="1398-10-14"),
        Node(id="wd:WANGJA2", type="event", label="제2차 왕자의 난", source="wd",
             start_date="1400"),
        Node(id="wd:HONGSAN", type="event", label="홍산대첩", source="wd",
             start_date="1376-07"),
        Node(id="ex:event:홍산 전투", type="event", label="홍산 전투", source="extract"),
        # 같은 위키백과 문서가 두 노드에 붙었다 — 이름은 하나도 안 겹친다.
        Node(id="wd:IMSUL", type="event", label="임술민란", source="wd",
             start_date="1862",
             description="임술농민봉기(壬戌農民蜂起) 혹은 임술민란(壬戌民亂)은"
                         " 1862년, 조선 각지에서 동시다발적으로 일어난 농민"
                         " 봉기이다. 세금 제도의 문란이 원인이었다."),
        Node(id="wd:JINJU", type="event", label="진주민란", source="wd",
             start_date="1862",
             description="임술농민봉기(壬戌農民蜂起) 혹은 임술민란(壬戌民亂)은"
                         " 1862년, 조선 각지에서 동시다발적으로 일어난 농민"
                         " 봉기이다. 진주에서 시작되었다."),
        # 한 항목(《고려사》)을 말하는 두 실록 기사. 설명이 같은 게 당연하다.
        Node(id="sillok:A", type="event", label="《고려사》를 올리다", source="nikh",
             description="고려사(高麗史)는 조선 초에 편찬된 고려 왕조의 정사로,"
                         " 기전체로 쓰였으며 139권에 이른다.",
             props={"about": "nikh:KORYOSA"}),
        Node(id="sillok:B", type="event", label="《고려사》를 교정하여 올리다",
             source="nikh",
             description="고려사(高麗史)는 조선 초에 편찬된 고려 왕조의 정사로,"
                         " 기전체로 쓰였으며 139권에 이른다.",
             props={"about": "nikh:KORYOSA"}),
        # 이름이 통째로 같은 두 싸움. 1592년 청주성과 1950년 정주 전투다.
        Node(id="wd:CHEONGJU1592", type="event", label="청주 전투", source="wd",
             start_date="1592-09-06", description="임진왜란 당시 조헌의 의병과"
             " 영규의 승병이 청주성을 되찾은 싸움이다."),
        Node(id="wd:CHEONGJU1950", type="event", label="청주 전투", source="wd",
             start_date="1950-10-29", description="6·25 전쟁 중 유엔군 공세"
             " 기간에 벌어진 싸움이다."),
        Node(id="wd:CHOI", type="person", label="최영", source="wd"),
        Node(id="wd:YEONGJO", type="person", label="영조", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:CHOI", dst="ex:event:홍산 전투", type="participated_in", source="extract"),
        Edge(src="wd:YEONGJO", dst="wd:IMO", type="participated_in", source="wd"),
    ])

    cands = {(c.rule, c.a, c.b) for c in dup_mod.find(store.conn)}
    check("띄어쓰기만 다른 표제를 찾는다",
          ("라벨", "nikh:SAMIL", "wd:SAMIL") in cands
          or ("라벨", "wd:SAMIL", "nikh:SAMIL") in cands, str(cands))
    check("설명이 서로를 이칭으로 부르는 짝을 찾는다",
          any(r == "이칭" and {a, b} == {"nikh:SADO", "wd:IMO"} for r, a, b in cands),
          str(cands))
    check("갈래만 다른 이름을 찾는다 (홍산대첩 ↔ 홍산 전투)",
          any(r == "핵심어" and {a, b} == {"wd:HONGSAN", "ex:event:홍산 전투"}
              for r, a, b in cands), str(cands))
    check("이름이 하나도 안 겹쳐도 같은 설명이면 찾는다 (진주민란 ↔ 임술민란)",
          any(r == "설명" and {a, b} == {"wd:IMSUL", "wd:JINJU"} for r, a, b in cands),
          str(cands))
    check("한 항목을 말하는 실록 기사끼리는 후보가 아니다",
          not any({a, b} == {"sillok:A", "sillok:B"} for _, a, b in cands), str(cands))
    check("차수가 어긋나면 후보로 올리지 않는다",
          not any({a, b} == {"wd:WANGJA1", "wd:WANGJA2"} for _, a, b in cands),
          str(cands))

    table = [
        dup_mod.Verdict("merge", "nikh:SADO", "wd:IMO", "같은 사건"),
        dup_mod.Verdict("merge", "wd:HONGSAN", "ex:event:홍산 전투", "같은 싸움"),
        dup_mod.Verdict("merge", "wd:BANTAK", "ex:event:반탁 운동", "다른 이름"),
    ]
    rep = dup_mod.sweep(store.conn, table)
    check("증거가 없는 후보만 표로 넘긴다",
          {c.rule for c in rep.unjudged} == {"설명"}, str(rep.unjudged))
    check("띄어쓰기만 다른 표제는 증거가 판정한다 (3·1운동)",
          any({c.a, c.b} == {"nikh:SAMIL", "wd:SAMIL"} for c, _ in rep.auto_same),
          str(rep.auto_same))
    check("성과 이름 사이 공백은 표기 차이로 보지 않는다",
          not dup_mod._spacing_variant("이 명희", "이명희")
          and dup_mod._spacing_variant("경주 김씨", "경주김씨"))
    check("이름이 같아도 연대가 어긋나면 다르다고 본다",
          any({c.a, c.b} == {"wd:CHEONGJU1592", "wd:CHEONGJU1950"}
              for c, _ in rep.auto_diff), str(rep.auto_diff))

    rep = dup_mod.apply(store, table)
    row = store.conn.execute(
        "SELECT label, start_date, url, description FROM nodes WHERE id='nikh:SADO'"
    ).fetchone()
    check("없앤 노드가 사라진다",
          store.conn.execute("SELECT COUNT(*) FROM nodes WHERE id='wd:IMO'").fetchone()[0] == 0)
    check("엣지가 남은 노드로 옮겨진다", store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE dst='nikh:SADO' AND src='wd:YEONGJO'"
    ).fetchone()[0] == 1)
    check("없어진 이름은 별칭으로 남는다", store.conn.execute(
        "SELECT COUNT(*) FROM aliases WHERE node_id='nikh:SADO' AND alias='임오화변'"
    ).fetchone()[0] == 1)
    check("빈 칸만 없앤 쪽에서 채운다 (url 은 오고 날짜는 그대로)",
          row["url"].endswith("임오화변") and row["start_date"] == "1762-05",
          str(dict(row)))
    check("지워질 설명은 props 에 남긴다", "임오옥" in (store.conn.execute(
        "SELECT json_extract(props,'$.merged_desc') FROM nodes WHERE id='nikh:SADO'"
    ).fetchone()[0] or ""))
    check("연대가 어긋나면 알린다",
          any("1762-05" in c for c in rep.date_clashes), str(rep.date_clashes))

    # 셋이 한 사건: 표가 `가↔나`·`가↔다` 를 적었으면 `나↔다` 도 판정된 것이다.
    check("합친 뒤 후보가 사라진다 (멱등)",
          all({c.a, c.b} != {"wd:HONGSAN", "ex:event:홍산 전투"} for c in rep.candidates),
          str(rep.candidates))
    check("증거로 합친 짝도 사라진다 (3·1운동)", store.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id IN ('nikh:SAMIL','wd:SAMIL')"
    ).fetchone()[0] == 1)
    again = dup_mod.apply(store, table)
    check("두 번 돌려도 결과가 같다", again.merged == [] and len(again.stale) == 3,
          f"{again.merged} {again.stale}")
    store.close()

with tempfile.TemporaryDirectory() as tmp:
    bad = Path(tmp) / "t.tsv"
    bad.write_text("merge\tonly-one-column\n", encoding="utf-8")
    try:
        dup_mod.load_table(bad)
        check("칸이 모자란 표를 거부한다", False)
    except dup_mod.DuplicateTableError:
        check("칸이 모자란 표를 거부한다", True)
    bad.write_text("maybe\ta:1\ta:2\t?\n", encoding="utf-8")
    try:
        dup_mod.load_table(bad)
        check("merge/keep 이 아닌 판정을 거부한다", False)
    except dup_mod.DuplicateTableError:
        check("merge/keep 이 아닌 판정을 거부한다", True)


# --- 국가유산은 지정 건마다 관리번호와 소재지를 갖는다 ------------------------
#
# 이름도 한자도 같은 '동의보감'이 셋인데 국립중앙도서관본·규장각본·
# 한국학중앙연구원본이라 서로 다른 보물이다. 반대로 '여수 진남관'은 보물
# 324호이던 것이 국보 304호가 되며 두 줄이 됐다 — 소재지가 같다.

with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "khs.sqlite")
    def _h(nid, label, addr, desc=""):
        return Node(id=nid, type="heritage", label=label, source="khs",
                    description=desc or None, props={"address": addr})
    store.upsert_nodes([
        _h("khs:12-11-0010850000100", "동의보감",
           "서울 서초구 반포대로 201, 국립중앙도서관 (반포동)", "허준이 지은 의서다."),
        _h("khs:12-11-0010850000300", "동의보감",
           "서울 관악구 관악로 1, 서울대학교 규장각한국학연구원 (신림동)",
           "허준이 지은 의서다."),
        _h("khs:11-24-0003040000000", "여수 진남관", ""),
        _h("khs:11-36-0003040000000", "여수 진남관",
           "전남광주통합특별시 여수시 동문로 11 (군자동) / (지번)전남 여수시 군자동 472",
           "전라좌수영 객사로 세운 건물이다."),
        _h("khs:12-36-0003240000000", "여수진남관", "전남 여수시 동문로 11 (군자동)",
           "조선 수군의 본거지였다."),
    ])
    rep = dup_mod.sweep(store.conn, [], "heritage")
    same = {frozenset((c.a, c.b)): why for c, why in rep.auto_same}
    diff = {frozenset((c.a, c.b)) for c, _ in rep.auto_diff}
    check("소장처가 다른 같은 이름은 다른 지정 건이다 (동의보감)",
          frozenset(("khs:12-11-0010850000100", "khs:12-11-0010850000300")) in diff,
          str(rep.auto_diff))
    check("관리번호가 같으면 같은 유산이다 (시도코드만 다른 줄)",
          "관리번호" in same.get(
              frozenset(("khs:11-24-0003040000000", "khs:11-36-0003040000000")), ""),
          str(same))
    check("소재지가 같고 종목이 다르면 지정이 바뀐 것이다 (보물 → 국보)",
          "소재지" in same.get(
              frozenset(("khs:11-36-0003040000000", "khs:12-36-0003240000000")), ""),
          str(same))

    dup_mod.apply(store, [], "heritage")
    rows = store.conn.execute(
        "SELECT id, label, json_extract(props,'$.address') AS addr FROM nodes"
        " WHERE label LIKE '%진남관%'").fetchall()
    check("셋이 사슬로 얽혀도 한 노드로 모인다", len(rows) == 1, str([dict(r) for r in rows]))
    check("남은 것은 알맹이가 있는 줄이다 (빈 줄이 이기지 않는다)",
          rows and rows[0]["id"] == "khs:11-36-0003040000000", str([dict(r) for r in rows]))
    check("없앤 줄의 props 도 이어받는다",
          store.conn.execute("SELECT COUNT(*) FROM nodes WHERE label='동의보감'"
                             ).fetchone()[0] == 2)
    check("소재지 앞 세 마디로 견준다 (시도는 뗀다)",
          dup_mod.address_key("전남 여수시 동문로 11 (군자동)")
          == dup_mod.address_key(
              "전남광주통합특별시 여수시 동문로 11 (군자동) / (지번)전남 여수시 군자동 472"))
    store.close()


# --- 표가 그래프와 맞는가 -----------------------------------------------------

_dup_table = Path(__file__).resolve().parents[1] / "data" / "duplicates.tsv"
if _dup_table.exists():
    rows = dup_mod.load_table(_dup_table)
    check("판정 표가 읽힌다", len(rows) > 0)
    check("한 짝을 두 번 적지 않았다",
          len({r.key for r in rows}) == len(rows))


# --- 인과 관문: 원인 → 결과 사슬 ---------------------------------------------
# "온톨로지 그래프이므로 모든 노드의 인과관계를 보여줘야 한다 — 임진왜란 →
# 명의 쇠퇴 → 여진족의 성장 → 병자호란" (사용자, 2026-09-04). 인과 엣지는
# 산문에서 근거와 함께 뽑되, 양끝은 있는 노드로 풀리고 연대는 순방향이어야 한다.
from histgraph import causes as causes_mod  # noqa: E402

print("\n[인과 관문]")
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "c.sqlite")
    store.upsert_nodes([
        Node(id="wd:JOSEON", type="org", label="조선", source="wd", start_date="1392", end_date="1897"),
        Node(id="wd:IMJIN", type="event", label="임진왜란", source="wd", start_date="1592", end_date="1598"),
        Node(id="wd:MING", type="org", label="명나라", source="wd", start_date="1368", end_date="1644"),
        Node(id="wd:JIN", type="org", label="후금", source="wd", start_date="1616", end_date="1636"),
        Node(id="wd:JM", type="event", label="정묘호란", source="wd", start_date="1627"),
        Node(id="wd:BJ", type="event", label="병자호란", source="wd", start_date="1636", end_date="1637"),
        Node(id="wd:GABO", type="event", label="갑오개혁", source="wd", start_date="1894"),
        Node(id="wd:BI", type="event", label="병인박해", source="wd", start_date="1866"),
        Node(id="wd:BY", type="event", label="병인양요", source="wd", start_date="1866"),
        Node(id="wd:P", type="person", label="인조", source="wd", start_date="1595", end_date="1649"),
    ])
    store.conn.execute("INSERT INTO aliases (node_id, alias) VALUES ('wd:IMJIN', '임진전쟁')")
    # 옛 방식으로 들어온 Wikidata 원인·결과
    store.upsert_edges([Edge(src="wd:BI", dst="wd:BY", type="related_to", source="wd", label="원인")])
    check("옛 '관련(원인)' 엣지를 인과 엣지로 옮긴다", causes_mod.migrate(store) == 1)
    check("옮긴 뒤 관련 엣지는 남지 않는다",
          store.conn.execute("SELECT type FROM edges WHERE src='wd:BI'").fetchone()["type"] == "caused")
    check("두 번 돌려도 더 옮길 것이 없다", causes_mod.migrate(store) == 0)

    conn = corpus_mod.open_corpus(Path(tmp) / "corpus.sqlite")
    doc_text = """병자호란은 1636년 청나라가 조선을 침입한 전쟁이다.

== 배경 ==
임진왜란으로 명나라의 국력이 크게 소진되었고, 그 틈을 타 여진의 후금이 성장하였다. 정묘호란 뒤 후금은 조선에 형제 관계를 요구하였다.

== 경과 ==
인조는 남한산성으로 피신하였다. 병자호란 이후 명나라는 멸망하였다. 명나라 멸망은 병자호란의 상징적 결과로 평가되기도 한다. 임진왜란 때문에 명나라는 쇠퇴하였다.

== 결과 ==
병자호란의 결과 조선은 청과 군신 관계를 맺었다."""
    corpus_mod.put_doc(conn, "wd:BJ", "병자호란", doc_text, source="aks")
    corpus_mod.put_doc(conn, "wd:GABO", "갑오개혁", "갑오개혁은 1894년의 개혁이다.", source="kowiki")
    docs = causes_mod.documents(store, conn)
    check("말뭉치에 글이 있는 사건만 묻는다", [d["id"] for d in docs] == ["wd:BJ", "wd:GABO"], str([d["id"] for d in docs]))
    doc = docs[0]
    passages = causes_mod.doc_passages(conn, "wd:BJ", budget=60)
    check("예산이 빠듯하면 인과를 말하는 절이 먼저 든다",
          [p["section"] for p in passages] == ["배경"], str([p["section"] for p in passages]))
    passages = causes_mod.doc_passages(conn, "wd:BJ")
    check("예산 안이면 문서 순서 그대로", [p["section"] for p in passages] == ["", "배경", "경과", "결과"],
          str([p["section"] for p in passages]))
    gaz = causes_mod.gazetteer(store, doc)
    check("알려진 개체에 그 무렵의 사건과 단체가 든다",
          "임진왜란" in gaz["event"] and "후금" in gaz["org"] and "갑오개혁" not in gaz["event"], str(gaz))
    prompt = causes_mod.build_prompt(doc, passages, gaz)
    check("프롬프트에 종류·개체·원문이 다 든다", "배경:" in prompt and "후금" in prompt and "남한산성" in prompt)

    answers = [
        # 정상 — 별칭으로 풀리고 근거가 원문에 있다
        {"cause": "임진전쟁", "cause_type": "event", "effect": "명나라", "effect_type": "org", "kind": "영향",
         "how": "명의 국력이 소진되었다", "evidence": "임진왜란으로 명나라의 국력이 크게 소진되었고", "confidence": "certain"},
        {"cause": "후금", "cause_type": "org", "effect": "병자호란", "effect_type": "event", "kind": "배경",
         "how": "형제 관계를 요구하며 압박했다", "evidence": "정묘호란 뒤 후금은 조선에 형제 관계를 요구하였다.", "confidence": "probable"},
        # 연대 역행 — 갑오개혁(1894)이 병자호란(1636)의 원인일 수 없다
        {"cause": "갑오개혁", "cause_type": "event", "effect": "병자호란", "effect_type": "event", "kind": "원인",
         "how": "", "evidence": "병자호란은 1636년 청나라가 조선을 침입한 전쟁이다.", "confidence": "certain"},
        # 이름을 못 푼다 — 노드를 만들지 않는다
        {"cause": "여진족의 성장", "cause_type": "concept", "effect": "병자호란", "effect_type": "event", "kind": "배경",
         "how": "", "evidence": "그 틈을 타 여진의 후금이 성장하였다.", "confidence": "certain"},
        # 서술구는 주어로 푼다 — 정묘호란(의 굴욕)이 원인, 구는 남긴다
        {"cause": "정묘호란 뒤의 형제 관계 요구", "cause_type": "event", "effect": "병자호란", "effect_type": "event", "kind": "배경",
         "how": "형제 관계 요구가 압박이 되었다", "evidence": "정묘호란 뒤 후금은 조선에 형제 관계를 요구하였다.", "confidence": "possible"},
        # 자국 왕조는 원인이 되지 않는다
        {"cause": "조선의 저항", "cause_type": "org", "effect": "병자호란", "effect_type": "event", "kind": "배경",
         "how": "", "evidence": "인조는 남한산성으로 피신하였다.", "confidence": "possible"},
        # 근거가 원문에 없다
        {"cause": "정묘호란", "cause_type": "event", "effect": "병자호란", "effect_type": "event", "kind": "원인",
         "how": "", "evidence": "정묘호란의 굴욕이 병자호란을 불렀다.", "confidence": "certain"},
        # 자기 자신
        {"cause": "병자호란", "cause_type": "event", "effect": "병자호란", "effect_type": "event", "kind": "원인",
         "how": "", "evidence": "병자호란의 결과 조선은 청과 군신 관계를 맺었다.", "confidence": "certain"},
        # 결과가 인물 — 타입이 안 맞는다
        {"cause": "병자호란", "cause_type": "event", "effect": "인조", "effect_type": "event", "kind": "영향",
         "how": "", "evidence": "인조는 남한산성으로 피신하였다.", "confidence": "certain"},
    ]
    edges, why, missing = causes_mod.accept(store, doc, answers, passages, "test-model")
    got = {(e.src, e.dst, e.label) for e in edges}
    check("별칭으로 푼 원인과 단체 결과가 엣지가 된다", ("wd:IMJIN", "wd:MING", "영향") in got, str(got))
    check("단체가 원인인 인과도 적는다", ("wd:JIN", "wd:BJ", "배경") in got, str(got))
    check("연대가 역행하면 버린다", why.get("연대 역행") == 1 and ("wd:GABO", "wd:BJ", "원인") not in got, str(why))
    store.upsert_nodes([Node(id="wd:ONGOING", type="org", label="재향군인회", source="wd", start_date="1952")])
    check("끝을 모르는 단체가 결과면 연대로 막지 않는다 (시작 연도로 재면 참인 인과가 사라진다)",
          not causes_mod.backwards(store, "wd:GABO", "wd:ONGOING", "org"))
    check("끝난 단체가 결과면 그 끝보다 늦은 원인은 역행이다", causes_mod.backwards(store, "wd:GABO", "wd:JIN", "org"))
    store.conn.execute("DELETE FROM nodes WHERE id = 'wd:ONGOING'")
    check("못 푼 이름은 노드를 만들지 않고 모아 둔다", missing == ["여진족의 성장", "조선의 저항"] and why.get("이름 못 풂") == 2, str(missing))
    jm = next(e for e in edges if e.src == "wd:JM")
    check("서술구는 주어로 풀고 원래 구를 남긴다", jm.props["cause_as"] == "정묘호란 뒤의 형제 관계 요구" and "effect_as" not in jm.props, str(jm.props))
    check("서술구의 주어 후보는 긴 것부터", causes_mod.heads("도요토미 히데요시의 사망") == ["도요토미 히데요시", "도요토미"], str(causes_mod.heads("도요토미 히데요시의 사망")))
    check("한 글자 나라 이름은 긴 이름으로", causes_mod.heads("청의 연호 사용 강요")[-1] == "청나라", str(causes_mod.heads("청의 연호 사용 강요")))
    hs = causes_mod.heads("후금(청)의 재차 침입 결심")
    check("괄호는 떼고 보며 구 자체는 후보가 아니다", hs[-1] == "후금" and "후금(청)의 재차 침입 결심" not in hs, str(hs))
    check("근거가 원문에 없으면 버린다", why.get("근거 없음") == 1, str(why))
    check("자기 자신은 잇지 않는다", why.get("자기 자신") == 1, str(why))
    # 모델이 결과 자리에 사람을 적을 때 하는 말은 '그 사건이 그 사람에게
    # 무슨 일을 했나'다 (실측 39건 전부 '영향'). 인과가 아니라 참여이므로
    # 버리지 않고 방향을 돌려 `roles` 에게 넘긴다 (2026-09-06 사용자 결정).
    check("인물은 결과가 아니라 참여로 돌아간다", why.get("참여로 돌림") == 1, str(why))
    _join = [e for e in edges if e.type == "participated_in"]
    check("참여는 사람 → 사건 방향이다",
          len(_join) == 1 and _join[0].src == "wd:P" and _join[0].dst == "wd:BJ",
          str([(e.src, e.dst) for e in _join]))
    check("참여에 근거가 남아 roles 가 판정할 수 있다",
          _join[0].props.get("evidence", "").startswith("인조는 남한산성")
          and _join[0].props.get("from_causes") is True, str(_join[0].props))
    check("돌린 참여에는 역할이 아직 없다", "role" not in _join[0].props)
    # 죽은 뒤의 일에는 참여할 수 없다 — 김종직(1431~1492)이 무오사화(1498)를
    # '주도'한 것으로 판정된 적이 있다. 그는 부관참시된 쪽이다.
    store.upsert_nodes([Node(id="wd:DEAD", type="person", label="김종직", source="wd",
                             start_date="1431", end_date="1492")])
    _late = [{"cause": "병자호란", "cause_type": "event", "effect": "김종직", "effect_type": "person",
              "kind": "영향", "how": "", "evidence": "인조는 남한산성으로 피신하였다.",
              "confidence": "certain"}]
    _e2, _w2, _ = causes_mod.accept(store, doc, _late, passages, "test-model")
    check("죽은 뒤의 일은 참여로 돌리지 않는다",
          _w2.get("죽은 뒤의 일") == 1 and not [e for e in _e2 if e.type == "participated_in"],
          str(_w2))
    check("생몰을 모르면 막지 않는다", causes_mod.alive_at(store, "wd:P", "wd:BJ"))
    check("근거는 문장 단위로 되살린다",
          next(e for e in edges if e.src == "wd:IMJIN").props["evidence"].endswith("성장하였다."),
          next(e for e in edges if e.src == "wd:IMJIN").props["evidence"])
    check("엣지에 '어떻게'와 출처 문서·모델이 남는다",
          all(e.props["doc"] == "wd:BJ" and e.props["model"] == "test-model" for e in edges)
          and next(e for e in edges if e.src == "wd:JIN").props["how"] == "형제 관계를 요구하며 압박했다")
    check("스키마 밖 종류는 버린다",
          causes_mod.accept(store, doc, [dict(answers[0], kind="이유")], passages, "m")[1] == {"종류 밖": 1})

    n = causes_mod.write(store, edges)
    check("엣지를 적는다 (인과 3 · 참여 1)", n == 4, str(n))
    weaker = [Edge(src="wd:JIN", dst="wd:BJ", type="caused", source="causes", label="원인", confidence=0.5,
                   props={"how": "다른 문서의 약한 말"})]
    causes_mod.write(store, weaker)
    row = store.conn.execute("SELECT label, confidence FROM edges WHERE src='wd:JIN' AND dst='wd:BJ'").fetchone()
    check("같은 짝을 더 약하게 말한 문서는 앞의 것을 덮지 않는다", row["label"] == "배경" and row["confidence"] == 0.7, str(tuple(row)))
    causes_mod.mark(store, doc, "test-model")
    check("물은 문서는 다시 묻지 않는다", [d["id"] for d in causes_mod.documents(store, conn)] == ["wd:GABO"])
    check("--redo 면 다시 묻는다", len(causes_mod.documents(store, conn, redo=True)) == 2)
    causes_mod.keep_answers(store, {"id": "wd:BJ"}, [], "m")
    check("--redo 도 답이 저장된 문서는 다시 묻지 않는다 (reresolve 몫)",
          [d["id"] for d in causes_mod.documents(store, conn, redo=True)] == ["wd:GABO"])
    store.conn.execute("DELETE FROM causes_answers")
    check("--scope 를 주면 화면에 있는 노드만 묻는다",
          [d["id"] for d in causes_mod.documents(store, conn, redo=True, scope={"wd:GABO"})] == ["wd:GABO"])

    # 표기 차이 — 실측: 모델 답 5,000여 건 중 3,237건이 '이름 못 풂'이었고, 그중
    # '대한민국임시정부'·'새마을운동'·'6.29 선언'처럼 **있는 노드를 다른 표기로**
    # 부른 것이 적잖았다. 느슨한 열쇠로 한 번 더 풀되 정확한 표기가 먼저다.
    store.upsert_nodes([
        Node(id="wd:SM", type="concept", label="새마을 운동", source="wd", start_date="1970"),
        Node(id="wd:629", type="event", label="6.29 선언", source="wd", start_date="1987"),
        Node(id="wd:KCIA", type="org", label="대한민국 중앙정보부", source="wd", start_date="1961", end_date="1981"),
        Node(id="wd:KPG", type="org", label="대한민국 임시정부", source="wd", start_date="1919", end_date="1948"),
        Node(id="wd:TOEGYE", type="person", label="퇴계 이황", source="wd", start_date="1501", end_date="1570"),
        Node(id="wd:YEJONG", type="person", label="예종", source="wd", start_date="1450", end_date="1469"),
    ])
    store.conn.execute("INSERT INTO aliases (node_id, alias) VALUES ('wd:YEJONG', '이황')")
    doc_1987 = {"id": "wd:X", "start_date": "1987", "end_date": None}
    r = causes_mod.resolve(store, "새마을운동", "concept", doc_1987)
    check("띄어쓰기가 다른 이름을 푼다", r is not None and r[0] == "wd:SM", str(r))
    r = causes_mod.resolve(store, "6·29 선언", "event", doc_1987)
    check("가운뎃점·마침표가 다른 이름을 푼다", r is not None and r[0] == "wd:629", str(r))
    r = causes_mod.resolve(store, "중앙정보부", "org", doc_1987)
    check("한정어가 앞에 붙은 라벨을 접미로 푼다 (단체)", r is not None and r[0] == "wd:KCIA", str(r))
    r = causes_mod.resolve(store, "중앙정보부의 공작", "org", doc_1987)
    check("서술구의 주어도 느슨하게 푼다", r is not None and r[0] == "wd:KCIA" and r[2] == "중앙정보부", str(r))
    check("자국 왕조는 띄어쓰기를 바꿔도 풀지 않는다", causes_mod.resolve(store, "대한민국임시정부", "org", doc_1987) is None)
    r = causes_mod.resolve(store, "이황", "person", doc_1987)
    check("정확한 표기가 있으면 느슨한 길은 밟지 않는다 (별칭 이황 = 예종)", r is not None and r[0] == "wd:YEJONG", str(r))
    check("인물은 접미로 풀지 않는다 ('이황'이 '퇴계 이황'에 붙지 않는다)",
          causes_mod.loose_index(store).lookup("황", "person") == [] and causes_mod.loose_index(store).lookup("퇴계이황", "person") == ["wd:TOEGYE"])
    check("접미 후보가 넷 넘으면 풀지 않는다", causes_mod.LooseIndex(store).lookup("운동", "concept") == [])
    store.upsert_nodes([Node(id="wd:4G6J", type="event", label="4군 6진 개척", source="wd", start_date="1433")])
    r = causes_mod.resolve(store, "4군 6진", "event", {"id": "wd:X", "start_date": "1440", "end_date": None})
    check("이름이 라벨의 앞머리면 접두로 푼다 ('4군 6진' → '4군 6진 개척')", r is not None and r[0] == "wd:4G6J", str(r))

    # 모델 답은 저장해 두고, 해소기가 좋아지면 모델 없이 다시 판정한다
    causes_mod.keep_answers(store, doc, answers, "test-model")
    row = store.conn.execute("SELECT model, answers FROM causes_answers WHERE node_id = 'wd:BJ'").fetchone()
    check("모델 답을 문서별로 저장한다", row is not None and row["model"] == "test-model" and "임진전쟁" in row["answers"])
    store.upsert_nodes([Node(id="wd:JURCHEN", type="org", label="여진족", source="wd", start_date="1000", end_date="1636")])
    got = causes_mod.reresolve(store, conn)
    check("다시 판정하면 새로 생긴 노드로 풀린 인과가 더해진다",
          got["counts"]["문서"] == 1 and store.conn.execute(
              "SELECT 1 FROM edges WHERE src='wd:JURCHEN' AND dst='wd:BJ' AND type='caused'").fetchone() is not None,
          str(got))
    check("다시 판정해도 자국 왕조는 여전히 못 푼다", got["unresolved"] == {"조선의 저항": 1}, str(got["unresolved"]))
    store.conn.execute("DELETE FROM edges WHERE src = 'wd:JURCHEN'")
    store.conn.execute("DELETE FROM nodes WHERE id = 'wd:JURCHEN'")
    store.conn.commit()

    # 구조화 소스가 반대 방향을 알면 추출본을 버린다
    store.upsert_edges([Edge(src="wd:JM", dst="wd:BJ", type="caused", source="wd", label="원인")])
    _, why2, _ = causes_mod.accept(store, doc, [
        {"cause": "병자호란", "cause_type": "event", "effect": "정묘호란", "effect_type": "event", "kind": "원인",
         "how": "", "evidence": "정묘호란 뒤 후금은 조선에 형제 관계를 요구하였다.", "confidence": "certain"}], passages, "m")
    check("구조화 소스와 반대 방향이면 버린다 (연대보다 먼저 잡히지 않아도)",
          why2.get("연대 역행") == 1 or why2.get("구조화 소스와 반대") == 1, str(why2))

    # 전투는 자기가 속한 전쟁의 원인이 아니다 — 상하위가 있는 짝은 적지 않는다
    store.upsert_nodes([Node(id="wd:HS", type="event", label="한산도 전투", source="wd", start_date="1592")])
    store.upsert_edges([Edge(src="wd:HS", dst="wd:IMJIN", type="part_of", source="wd")])
    _, why3, _ = causes_mod.accept(store, doc, [
        {"cause": "한산도 전투", "cause_type": "event", "effect": "임진왜란", "effect_type": "event", "kind": "영향",
         "how": "", "evidence": "임진왜란으로 명나라의 국력이 크게 소진되었고", "confidence": "certain"}], passages, "m")
    check("상하위 관계가 있는 짝은 인과로 적지 않는다", why3 == {"상하위 관계": 1}, str(why3))
    store.upsert_edges([Edge(src="wd:IMJIN", dst="wd:HS", type="caused", source="causes", label="배경")])
    check("이미 적힌 것은 되돌아가 지운다", causes_mod.prune_part_of(store) == 1
          and store.conn.execute("SELECT COUNT(*) FROM edges WHERE type='caused' AND dst='wd:HS'").fetchone()[0] == 0)

    # 팩트체크 관문 — 2026-09-06 "서울올림픽이 냉전체제에 영향을 줬다는 거 사실이 아니야. 논리비약을 피해"
    fc_edges, fc_why, _ = causes_mod.accept(store, doc, [
        # 'X의 멸망'은 X 가 아니라 X 의 끝 — 근거에 인과 표현이 없으면 버린다 ("이후"는 시간 순서다)
        {"cause": "병자호란", "cause_type": "event", "effect": "명나라의 멸망", "effect_type": "org", "kind": "원인",
         "how": "", "evidence": "병자호란 이후 명나라는 멸망하였다.", "confidence": "certain"},
        # 인과 표현('때문에')이 있으면 남기되 종류는 '영향'으로
        {"cause": "임진왜란", "cause_type": "event", "effect": "명나라의 쇠퇴", "effect_type": "org", "kind": "원인",
         "how": "", "evidence": "임진왜란 때문에 명나라는 쇠퇴하였다.", "confidence": "certain"},
        # 상징·추정 표현은 확신도를 낮춘다
        {"cause": "임진왜란", "cause_type": "event", "effect": "명나라", "effect_type": "org", "kind": "배경",
         "how": "", "evidence": "명나라 멸망은 병자호란의 상징적 결과로 평가되기도 한다.", "confidence": "certain"},
        # "X 이후"뿐인 '원인'은 '배경'으로 낮춘다
        {"cause": "병자호란", "cause_type": "event", "effect": "명나라", "effect_type": "org", "kind": "원인",
         "how": "", "evidence": "병자호란 이후 명나라는 멸망하였다.", "confidence": "certain"},
    ], passages, "m")
    fc = {(e.src, e.dst): e for e in fc_edges}
    check("'X의 멸망'을 X 로 풀고 근거가 시간 순서뿐이면 버린다", fc_why.get("끝난 것을 결과로 (인과 표현 없음)") == 1, str(fc_why))
    check("'X의 쇠퇴'라도 근거에 인과 표현이 있으면 '영향'으로 남긴다",
          ("wd:IMJIN", "wd:MING") in fc and fc[("wd:IMJIN", "wd:MING")].label == "영향", str({k: v.label for k, v in fc.items()}))
    check("\"X 이후\"뿐인 '원인'은 '배경'이 되고 확신도가 낮아진다",
          ("wd:BJ", "wd:MING") in fc and fc[("wd:BJ", "wd:MING")].label == "배경" and fc[("wd:BJ", "wd:MING")].confidence == 0.5,
          str([(e.label, e.confidence) for e in fc_edges]))
    far = {"id": "wd:FAR"}
    check("근거에 양끝 이름이 다 없으면 버린다",
          causes_mod.fact_check(store, far, "원인", "인조는 남한산성으로 피신하였다.",
                                ("wd:IMJIN", "임진왜란", "임진왜란"), ("wd:MING", "명나라", "명나라"))[0] == "근거에 양끝 이름 없음")
    check("한쪽만 없으면 지우지 않고 확신도만 낮춘다",
          causes_mod.fact_check(store, far, "원인", "임진왜란으로 명나라의 국력이 크게 소진되었고",
                                ("wd:IMJIN", "임진왜란", "임진왜란"), ("wd:JIN", "후금", "후금")) == (None, "원인", 0.5))
    check("상징·추정 표현은 확신도 상한 0.5",
          causes_mod.fact_check(store, far, "배경", "명나라 멸망은 병자호란의 상징적 결과로 평가되기도 한다.",
                                ("wd:BJ", "병자호란", "병자호란"), ("wd:MING", "명나라", "명나라"))[2] == 0.5)
    check("이름은 앞뒤 문맥에서 찾는다 (앞 문장의 원인을 '이러한 상황에서'로 가리킨다)",
          causes_mod.fact_check(store, far, "원인", "그 틈을 타 여진의 후금이 성장하였다.",
                                ("wd:IMJIN", "임진왜란", "임진왜란"), ("wd:JIN", "후금", "후금"),
                                context="임진왜란으로 명나라의 국력이 크게 소진되었고, 그 틈을 타 여진의 후금이 성장하였다.") == (None, "원인", None))
    check("괄호 안의 이름도 이름이다", causes_mod.loose_text("쿠데타를 일으켰다(위화도 회군).") == "쿠데타를일으켰다위화도회군")
    check("표기 차이를 봐준다 — 계유정난/계유정란, 흥선대원군/대원군",
          causes_mod._found({"계유정난"}, "계유정란을일으켜") and causes_mod._found({"흥선대원군"}, "이에대원군은"))

    # 사슬 — 임진왜란 → 명나라 (영향) · 후금 → 병자호란 (배경) · 정묘호란 → 병자호란 (wd)
    store.upsert_edges([Edge(src="wd:MING", dst="wd:JIN", type="caused", source="causes", label="배경",
                             confidence=0.7, props={"how": "명의 쇠퇴로 여진이 성장할 틈이 생겼다"})])
    tree = causes_mod.chain(store, "wd:BJ", depth=4)
    cause_ids = [c["id"] for c in tree["causes"]]
    check("원인 나무의 첫 층은 직접 원인들", set(cause_ids) == {"wd:JIN", "wd:JM"}, str(cause_ids))
    check("나무의 원인에 서술구가 붙는다", next(c for c in tree["causes"] if c["id"] == "wd:JM")["as"] == "정묘호란 뒤의 형제 관계 요구")
    jin = next(c for c in tree["causes"] if c["id"] == "wd:JIN")
    check("원인의 원인으로 내려간다 (후금 ← 명 ← 임진왜란)",
          jin["children"][0]["id"] == "wd:MING" and jin["children"][0]["children"][0]["id"] == "wd:IMJIN", str(jin))
    check("나무의 노드 요약이 한 번씩 실린다", set(tree["nodes"]) == {"wd:BJ", "wd:JIN", "wd:JM", "wd:MING", "wd:IMJIN"}, str(set(tree["nodes"])))
    # 예산은 두 쪽이 나눠 쓴다 — 원인이 많은 사건의 결과가 빈손이 되지 않게
    # (실측: 심하전투 원인 31건에 결과 0, 연표에는 정묘호란·인조반정이 결과)
    store.upsert_nodes([Node(id="wd:MANY", type="event", label="원인 많은 일", source="wd")]
                       + [Node(id=f"wd:C{i}", type="event", label=f"원인 {i}", source="wd") for i in range(5)]
                       + [Node(id="wd:E1", type="event", label="결과 하나", source="wd")])
    store.upsert_edges([Edge(src=f"wd:C{i}", dst="wd:MANY", type="caused", source="wd", label="원인") for i in range(5)]
                       + [Edge(src="wd:MANY", dst="wd:E1", type="caused", source="wd", label="원인")])
    saved_budget = causes_mod.TREE_BUDGET
    causes_mod.TREE_BUDGET = 4
    many = causes_mod.chain(store, "wd:MANY", depth=2)
    causes_mod.TREE_BUDGET = saved_budget
    check("원인이 예산을 다 써도 결과는 선다", len(many["effects"]) == 1 and len(many["causes"]) == 3,
          f"원인 {len(many['causes'])} 결과 {len(many['effects'])}")
    got = causes_mod.paths(store, "wd:IMJIN", "wd:BJ")
    check("임진왜란에서 병자호란까지 최단 인과 경로를 찾는다",
          got["found"] and [s["id"] for s in got["paths"][0]] == ["wd:IMJIN", "wd:MING", "wd:JIN", "wd:BJ"], str(got["paths"]))
    check("경로의 걸음마다 '어떻게'가 붙는다",
          got["paths"][0][2]["edge"]["how"] == "명의 쇠퇴로 여진이 성장할 틈이 생겼다", str(got["paths"][0][2]))
    back = causes_mod.paths(store, "wd:BJ", "wd:IMJIN")
    check("거꾸로 물으면 반대 방향임을 밝히고 같은 경로를 준다",
          back["found"] and back["reversed"] and back["paths"][0][0]["id"] == "wd:IMJIN", str(back))
    none = causes_mod.paths(store, "wd:GABO", "wd:BJ")
    check("이어지지 않으면 없다고 한다", not none["found"] and none["paths"] == [])
    text = causes_mod.render_chain(tree)
    check("글로 읽을 때 원인·결과와 '어떻게'가 한글로 찍힌다",
          "원인:" in text and "임진왜란 (1592)" in text and "명의 쇠퇴로" in text, text)
    check("경로 글도 마찬가지", "임진왜란 (1592)" in causes_mod.render_paths(got) and "→[배경" in causes_mod.render_paths(got))

    # 화면 DB 로 옮기기 — 양끝이 거기 있는 것만
    target = GraphStore(Path(tmp) / "korea.sqlite")
    target.upsert_nodes([Node(id="wd:JIN", type="org", label="후금", source="wd"),
                         Node(id="wd:BJ", type="event", label="병자호란", source="wd"),
                         Node(id="wd:JM", type="event", label="정묘호란", source="wd")])
    moved = causes_mod.sync(store, target)
    check("파생본에 양끝이 있는 인과 엣지만 옮긴다", moved == 3,
          str(target.conn.execute("SELECT src, dst FROM edges").fetchall()))
    api = GraphAPI(target, era="korea")
    rel = next(r for r in api.node("wd:BJ")["relations"] if r["other"]["id"] == "wd:JIN")
    check("상세에 인과 엣지가 종류·어떻게와 함께 간다",
          rel["type"] == "caused" and rel["dir"] == "in" and rel["edge_label"] == "배경"
          and rel["how"] == "형제 관계를 요구하며 압박했다", str(rel))
    check("상세 관계 목록에서 인과가 맨 앞이다", api.node("wd:BJ")["relations"][0]["type"] == "caused")
    from histgraph.server import dispatch as _dispatch
    st, body = _dispatch(api, "/api/chain", {"id": ["wd:BJ"]})
    check("/api/chain 이 나무를 준다", st == 200 and {c["id"] for c in body["causes"]} == {"wd:JIN", "wd:JM"}, str(body))
    st, body = _dispatch(api, "/api/path", {"from": ["wd:JIN"], "to": ["wd:BJ"]})
    check("/api/path 가 경로를 준다", st == 200 and body["found"] and body["nodes"]["wd:JIN"]["group"] == "actor", str(body))
    st, _ = _dispatch(api, "/api/chain", {"id": ["없음"]})
    check("없는 노드는 404", st == 404)
    conn.close(); store.close(); target.close()


# --- 글로 읽는 장 (`/n/<id>`) --------------------------------------------
#
# 관계망은 자바스크립트가 그려서, 검색 로봇과 광고 심사의 눈에는 화면이
# 빈 <div> 하나다. 이 장들이 같은 자료를 글로 낸다. 재는 것은 셋이다 —
# 글이 실제로 들어 있는가, 이웃으로 이어지는 링크가 있는가, 그리고 §1
# 대로 **사람이 읽는 자리에 영어가 없는가**.
# --- 다시 쓴 설명 (`paraphrase` — summaries.py) --------------------------
#
# 정본이 아닌 글(위키백과·나무위키·출처 모름)은 모델이 우리 말로 새로 쓰고,
# 정본(국편·민백·국가유산청)은 손대지 않는다. 새 글은 nodes.description 이
# 아니라 summaries 표에 두고, 원문 해시로 아직 유효한지 잰다.
print("\n[다시 쓴 설명]")
with tempfile.TemporaryDirectory() as tmp:
    from histgraph import summaries as sm
    from histgraph import pages as _pages
    from histgraph.server import GraphAPI as _GraphAPI

    WIKI = ("이순신(李舜臣, 1545년 4월 28일 ~ 1598년 12월 16일)은 조선 중기의 무신이다. "
            "본관은 덕수, 자는 여해, 시호는 충무이다. 임진왜란 때 삼도수군통제사로서 "
            "한산도 대첩과 명량 해전에서 일본 수군을 크게 무찔렀다.")
    store = GraphStore(Path(tmp) / "g.sqlite")
    store.upsert_nodes([
        Node(id="wd:LSS", type="person", label="이순신", source="wd", description=WIKI,
             props={"desc_source": "kowiki", "kowiki_url": "https://ko.wikipedia.org/wiki/x"}),
        Node(id="wd:KIM", type="person", label="김종서", source="wd",
             description="김종서(金宗瑞)는 조선 전기의 문신이다. 세종 때 6진을 개척하였다.",
             props={"canon": "nikh", "nikh_url": "https://contents.history.go.kr/x"}),
        Node(id="wd:UNK", type="person", label="강항", source="wd",
             description="강항(姜沆)은 조선 중기의 문신이다. 정유재란 때 일본에 잡혀갔다가 돌아왔다."),
        Node(id="ex:X", type="person", label="이름뿐", source="extract"),
    ])
    cands = sm.candidates(store)
    check("정본은 새로 쓰지 않고, 위키와 출처 모름만 후보다",
          {c["id"] for c in cands} == {"wd:LSS", "wd:UNK"}, str([c["id"] for c in cands]))

    class _Fake:
        model = "fake"
        def complete_json(self, system, user, schema):
            if "이순신" in user:
                return {"summary": "이순신은 1545년에 태어나 1598년에 죽은 조선 중기의 장수다. "
                                   "임진왜란이 일어나자 삼도수군통제사가 되어 한산도와 명량에서 "
                                   "일본 수군을 잇달아 물리쳤다."}
            # 원문을 그대로 돌려주는 모델 — 요약이 아니라 베낌이다
            return {"summary": "강항(姜沆)은 조선 중기의 문신이다. 정유재란 때 일본에 잡혀갔다가 돌아왔다. "
                               "그는 학자였고 제자를 길렀으며 글을 남겼다."}

    got = sm.run(store, _Fake())
    check("새로 쓴 글은 받고 베낀 글은 떨어뜨린다",
          got["counts"]["새로 씀"] == 1 and got["reasons"] == {"원문을 그대로 베낌": 1}, str(got))
    check("nodes.description 은 그대로다",
          store.conn.execute("SELECT description FROM nodes WHERE id='wd:LSS'").fetchone()[0] == WIKI)

    api = _GraphAPI(store, era="korea")
    d = api.node("wd:LSS")
    check("화면은 새로 쓴 글을 받는다", d["description"].startswith("이순신은 1545년에"), d["description"][:60])
    check("출처 줄은 '바탕으로 새로 쓴 글'이라 말한다",
          d["desc_origin"]["rewritten"] is True
          and "문서를 바탕으로 새로 쓴 글입니다" in _pages.node_page(api, "wd:LSS")[1])
    check("떨어진 노드는 도입부로 물러난다",
          api.node("wd:UNK")["description"].startswith("강항(姜沆)은") and api.node("wd:UNK")["desc_origin"] is None)
    check("정본은 줄인 글 그대로",
          api.node("wd:KIM")["description"].startswith("김종서(金宗瑞)는")
          and "rewritten" not in api.node("wd:KIM")["desc_origin"])
    check("한 번 쓴 것은 다시 묻지 않는다", [c["id"] for c in sm.candidates(store)] == ["wd:UNK"])

    # 수집이 설명을 바꾸면 옛 요약은 옛 글의 요약이다 — 화면은 도입부로 돌아간다.
    store.conn.execute("UPDATE nodes SET description = ? WHERE id = 'wd:LSS'", (WIKI + " 노량 해전에서 전사했다.",))
    store.conn.commit()
    check("원문이 바뀌면 옛 글은 무효다",
          api.node("wd:LSS")["description"].startswith("이순신(李舜臣")
          and "wd:LSS" in [c["id"] for c in sm.candidates(store)])

    target = GraphStore(Path(tmp) / "t.sqlite")
    target.upsert_nodes([Node(id="wd:LSS", type="person", label="이순신", source="wd", description=WIKI)])
    check("파생본으로는 거기 있는 노드 것만 옮긴다", sm.sync(store, target) == 1
          and target.conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 1)
    check("표가 없는 옛 DB 에서는 조용히 None",
          sm.lookup(sqlite3.connect(":memory:"), "wd:LSS", WIKI) is None)
    check("요약 규칙: 영어·짧음·위키 언급·베낌을 가른다",
          sm.accept("King Sejong 은 왕이다. 훈민정음을 만들었다 정말로 그렇다 그렇다 그렇다.", WIKI) == "영어가 섞임"
          and sm.accept("짧다.", WIKI).startswith("너무 짧음")
          and sm.accept("위키백과에 따르면 이순신은 조선 중기의 장수로, 임진왜란에서 큰 공을 세워 뒷날 충무공이라 불리게 된 사람이다.", WIKI) == "'위키' 언급")
    store.close(); target.close()


print("\n[글로 읽는 장]")
with tempfile.TemporaryDirectory() as tmp:
    import re as _re

    from histgraph import pages
    from histgraph.server import GraphAPI as _GraphAPI

    store = GraphStore(Path(tmp) / "g.sqlite")
    # 세종의 설명은 위키백과 본문 전체 꼴이다 — 도입부 뒤에 `== 생애 ==` 절이
    # 달려 있다. 장은 도입부만 내야 한다 (2026-09-05 애드센스 '주의 필요':
    # 남의 백과사전을 통째로 옮긴 페이지로 읽혔다).
    SEJONG_INTRO = (
        "세종(世宗, 1397년~1450년)은 조선의 제4대 국왕으로, 재위 기간은 "
        "1418년부터 1450년까지다. 훈민정음을 창제하고 측우기·자격루 같은 "
        "기구를 만들게 했으며, 4군 6진을 개척하여 국경을 넓혔다. 황희와 "
        "맹사성을 등용하여 의정부서사제를 열었다."
    )
    SEJONG_BODY = "1397년 한성 준수방에서 태종의 셋째 아들로 태어났다. 아명은 막동이다."
    store.upsert_nodes([
        Node(id="wd:S", type="person", label="세종", source="wd",
             start_date="1397-04-10", end_date="1450-02-17",
             description=f"{SEJONG_INTRO}\n\n\n== 생애 ==\n{SEJONG_BODY}",
             aliases=["이도"],
             props={"desc_source": "kowiki",
                    "kowiki_url": "https://ko.wikipedia.org/wiki/%EC%84%B8%EC%A2%85"}),
        Node(id="wd:T", type="person", label="태종", source="wd",
             description="조선의 제3대 국왕이다."),
        Node(id="wd:M", type="person", label="문종", source="wd",
             description="조선의 제5대 국왕이다."),
        Node(id="wd:H", type="person", label="황희", source="wd",
             description="조선의 영의정이다."),
        Node(id="ex:X", type="person", label="이름뿐", source="extract"),
        Node(id="wd:SL/A", type="event", label="빗금 든 것", source="wd",
             description="주소 한 칸에 담기지 않는 이름이다."),
    ])
    store.upsert_edges([
        Edge(src="wd:S", dst="wd:T", type="child_of", source="wd"),
        Edge(src="wd:M", dst="wd:S", type="child_of", source="wd"),
        Edge(src="wd:S", dst="wd:H", type="related_to", source="wd"),
    ])
    api = _GraphAPI(store, era="korea")

    def _visible(html: str) -> str:
        html = _re.sub(r"<(script|style)\b[\s\S]*?</\1>", " ", html)
        html = _re.sub(r"<!--[\s\S]*?-->", " ", html)
        return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", html)).strip()

    # 영어 관문이 봐주는 것은 제품 이름과 **저작권 한 줄**뿐이다
    # (2026-09-09 사용자 결정 · pages.COPYRIGHT). 문구를 늘리면 여기서
    # 걸리도록, 봐주는 글자를 상수 하나에서 가져온다.
    def _foreign(text: str) -> set[str]:
        text = text.replace(pages.COPYRIGHT, " ").replace("histgraph", " ")
        return set(_re.findall(r"[A-Za-z]{2,}", text))

    status, ctype, body = pages.route(api, "/n/wd:S")
    text = _visible(body)
    check("노드 장이 열린다", status == 200 and ctype.startswith("text/html"))
    check("이름·갈래·생몰이 글로 적힌다",
          "세종" in text and "인물" in text and "1397년 ~ 1450년" in text, text[:200])
    check("설명의 도입부가 본문에 들어 있다", "훈민정음을 창제하고" in text)
    # 원문 전체를 옮기면 스크랩이다. 절 본문은 내지 않고 위키 문법도 세우지 않는다.
    check("절 본문은 내지 않는다", "막동" not in text and "== " not in text, text[:400])
    check("이 사이트의 말이 먼저 온다 — 무엇이고 몇 건과 이어졌는지",
          "세종은 인물입니다. " in text and "모두 3건과 이어져 있습니다" in text
          and text.index("인물입니다") < text.index("훈민정음"), text[:400])
    check("다른 이름이 적힌다", "이도" in text)
    # 출처는 설명 아래 한 줄. §1 의 유일한 예외 — 라이선스 의무다.
    check("출처와 라이선스가 설명 아래 한 줄로 선다",
          "한국어 위키백과 문서를 줄인 글입니다 · 크리에이티브 커먼즈 저작자표시-동일조건변경허락 4.0" in text
          and text.index("훈민정음") < text.index("문서를 줄인 글입니다"), text[:600])
    check("출처 이름과 라이선스가 링크다",
          'href="https://ko.wikipedia.org/wiki/%EC%84%B8%EC%A2%85"' in body
          and 'href="https://creativecommons.org/licenses/by-sa/4.0/deed.ko"' in body)
    # 방향이 뒤집히면 아버지가 자식이 된다 — child_of 는 나가는 쪽이 부모다.
    check("부모와 자녀가 갈려 있다",
          text.index("부모") < text.index("태종") and "자녀" in text, text)
    check("이웃으로 가는 링크가 있다",
          'href="/n/wd%3AT"' in body and 'href="/n/wd%3AM"' in body)
    check("관계망으로 돌아가는 길이 있다", 'href="/#wd%3AS"' in body)
    check("정본 주소를 스스로 말한다",
          '<link rel="canonical" href="https://www.histgraph.space/n/wd%3AS">' in body)
    check("광고를 부른다", "adsbygoogle.js?client=ca-pub-" in body)
    # 방문 통계는 화면 네 장과 이 장이 **같은 파일 하나**를 부른다. 측정 ID 를
    # 여기 박으면 화면과 어긋나므로, 부르는 것은 주소뿐이다
    # (web/public/analytics.js · web/tests/render.test.mjs 가 나머지를 잰다).
    check("방문 통계도 같은 파일 하나를 부른다",
          '<script async src="/analytics.js"></script>' in body
          and not _re.search(r"G-[A-Z0-9]{6,}", Path(pages.__file__).read_text()),
          body[:400])
    check("방침·약관으로 이어진다",
          '/privacy.html' in body and '/terms.html' in body)
    check("사람이 읽는 글자에 영어가 없다 — 저작권 한 줄 말고는",
          not _foreign(text), str(_foreign(text)))
    check("저작권 한 줄이 footer 가운데에 선다",
          pages.COPYRIGHT in text and '<div class="copy">' in body
          and ".copy { text-align: center" in body, text[-120:])

    # 설명이 없는 장은 이름과 목록뿐이다. 색인에 올리면 읽을 것이 있는
    # 장까지 그 속에 묻힌다 — 왜 비었는지만 적고 물러난다.
    status, _, body = pages.route(api, "/n/ex:X")
    check("설명 없는 장은 색인에 올리지 않는다",
          status == 200 and 'content="noindex,follow"' in body)
    check("빈 설명의 이유를 적는다", "산문에서 이름만 추출된 노드라" in _visible(body))

    # 문턱: 요약이 짧거나 이어진 것이 적으면 색인에 안 올린다. 태종은
    # 설명 한 줄에 관계 하나 — 목록일 뿐이다.
    status, _, body = pages.route(api, "/n/wd:T")
    check("얇은 장은 색인에 올리지 않는다", 'content="noindex,follow"' in body)
    check("얇은 장도 읽을 수는 있다", status == 200 and "조선의 제3대 국왕이다." in _visible(body))

    # 요약 규칙 자체. 위키 문법과 마침표 없는 절 제목 앞까지가 도입부다.
    check("요약은 첫 절 제목 앞에서 멈춘다",
          pages.summarize("머리말\n갑은 을이다. 병은 정이다.\n출생과 성장\n무는 기다.")
          == "갑은 을이다. 병은 정이다.")
    check("제목뿐인 설명은 지우지 않는다", pages.summarize("화가") == "화가")
    check("문장 단위로 끊는다",
          pages.summarize("가나다라마바사아자차. 카타파하가나다라마바. 사아자차카타파하.", limit=24)
          == "가나다라마바사아자차. 카타파하가나다라마바.")
    check("상세 패널도 요약만 받는다 — 절 본문과 위키 문법이 없다",
          "== " not in api.node("wd:S")["description"]
          and "훈민정음" in api.node("wd:S")["description"]
          and "막동" not in api.node("wd:S")["description"])
    check("상세 패널이 출처를 받는다",
          api.node("wd:S")["desc_origin"]["name"] == "한국어 위키백과"
          and api.node("wd:T")["desc_origin"] is None)

    # 출처 판정 자체 (provenance.desc_origin). 표식이 확실할 때만 적는다.
    from histgraph.provenance import desc_origin as _origin
    check("나무위키는 비영리 라이선스를 적는다",
          "비영리" in _origin("kowiki", {"desc_source": "namu", "namu_url": "https://namu.wiki/w/x"})["license"])
    check("국편 정본은 우리역사넷으로 적는다",
          _origin("wd", {"canon": "nikh", "nikh_url": "https://contents.history.go.kr/x"})["name"]
          == "국사편찬위원회 우리역사넷")
    check("국가유산청 글은 노드 주소로 잇는다",
          _origin("khs", {}, "https://www.heritage.go.kr/x")["url"] == "https://www.heritage.go.kr/x")
    check("옛 수집분은 kowiki_url 로 되짚는다",
          _origin("wd", {"kowiki_url": "https://ko.wikipedia.org/wiki/x"})["name"] == "한국어 위키백과")
    check("표식이 없으면 모른다고 한다 — 틀린 출처보다 낫다", _origin("wd", {}) is None)

    status, _, body = pages.route(api, "/n/없는것")
    check("없는 노드는 404 이고 색인에 안 올린다",
          status == 404 and "noindex" in body)

    status, ctype, body = pages.route(api, "/sitemap.xml")
    check("사이트맵은 노드 장과 같은 문턱을 건다",
          "/n/wd%3AS" in body and "/n/ex%3AX" not in body and "/n/wd%3AT" not in body, body)
    check("사이트맵에 목록 장과 방침·약관이 있다",
          "/n/</loc>" in body and "/privacy.html" in body and "/terms.html" in body)
    # 주소 한 칸(:id)에 담기지 않는 id 는 링크가 죽는다. 죽은 주소를
    # 사이트맵에 실으면 로봇이 그것부터 물어 온다.
    check("빗금 든 id 는 사이트맵에서 뺀다", "SL" not in body)

    status, _, body = pages.route(api, "/n/")
    text = _visible(body)
    check("목록 장은 읽을 것이 있는 장만 세운다",
          status == 200 and "인물" in text and "세종" in text and "태종" not in text, text[:200])
    check("목록 장에도 영어가 없다 — 저작권 한 줄 말고는",
          not _foreign(text), str(_foreign(text)))
    check("목록 장에도 저작권 한 줄이 선다", pages.COPYRIGHT in text)

    # 배포에서는 rewrite 가 `/api/n/…` 으로 바꿔 넘긴다 — 같은 표가 받아야 한다.
    check("배포 경로(/api/n/…)도 같은 장을 낸다",
          pages.route(api, "/api/n/wd:S")[0] == 200)
    check("다른 경로는 건드리지 않는다",
          pages.route(api, "/api/meta") is None
          and pages.route(api, "/privacy.html") is None
          and pages.route(api, "/") is None)
    store.close()



print("\n[편집 계층 — 수집이 덮어써도 고친 값이 되살아난다]")
with tempfile.TemporaryDirectory() as _d:
    from histgraph import overrides as _ov
    from histgraph import labels as _labels_mod
    from histgraph import koreanize as _kz
    from histgraph.promote import merge_node as _merge_node

    store = GraphStore(Path(_d) / "ov.sqlite")

    # 1. relabel — 표의 이름은 수집이 영어로 되돌려도 남는다
    _wd = lambda **kw: Node(id="wd:Q1", type="event", label="Sayuksin plot", source="wd",
                            description="사육신 사건", **kw)
    store.upsert_nodes([_wd()])
    _labels_mod.apply_overrides(store.conn, [_labels_mod.Override("Q1", "사육신 사건", "표")])
    store.upsert_nodes([_wd()])          # 다시 수집
    row = store.conn.execute("SELECT label FROM nodes WHERE id='wd:Q1'").fetchone()
    check("relabel 한 이름은 재수집 뒤에도 한국어다", row[0] == "사육신 사건", row[0])
    check("영어 옛 이름은 별칭으로 남는다", store.conn.execute(
        "SELECT 1 FROM aliases WHERE node_id='wd:Q1' AND alias='Sayuksin plot'").fetchone() is not None)
    # 이미 맞는 이름도 표에 적혀야 다음 수집을 막는다
    store.upsert_nodes([Node(id="wd:Q2", type="person", label="세종", source="wd")])
    _labels_mod.apply_overrides(store.conn, [_labels_mod.Override("Q2", "세종", "표")])
    check("이미 한국어인 이름도 편집 계층에 적힌다", store.conn.execute(
        "SELECT value FROM overrides WHERE key='wd:Q2' AND field='label'").fetchone() is not None)

    # 2. redescribe — 사전이 비운 설명은 영어가 돌아오면 다시 비우고, 진짜 한국어가 오면 물러난다
    store.conn.execute("UPDATE nodes SET description='Something in English only' WHERE id='wd:Q2'")
    _kz.redescribe(store.conn)
    row = store.conn.execute("SELECT description FROM nodes WHERE id='wd:Q2'").fetchone()
    check("사전에 없는 영어 설명은 비운다", not row[0], repr(row[0]))
    # Node.__post_init__ 을 거치지 않는 SQL 경로가 영어를 다시 앉힌 상황
    store.conn.execute("UPDATE nodes SET description='Something in English only' WHERE id='wd:Q2'")
    _ov.reapply(store, node_ids=["wd:Q2"])
    row = store.conn.execute("SELECT description FROM nodes WHERE id='wd:Q2'").fetchone()
    check("영어가 되돌아오면 편집 계층이 다시 비운다", not row[0], repr(row[0]))
    store.upsert_nodes([Node(id="wd:Q2", type="person", label="세종", source="wd",
                             description="조선의 제4대 국왕")])
    row = store.conn.execute("SELECT description FROM nodes WHERE id='wd:Q2'").fetchone()
    check("진짜 한국어 설명이 오면 번역은 물러난다 (foreign 조건)", row[0] == "조선의 제4대 국왕", row[0])

    # 3. precision — 잘라 둔 날짜는 1월 1일이 돌아와도 남는다
    store.upsert_nodes([Node(id="wd:Q3", type="event", label="임진왜란", source="wd",
                             start_date="1592-01-01", description="전쟁")])
    store.conn.execute("UPDATE nodes SET start_date='1592' WHERE id='wd:Q3'")
    _ov.record(store.conn, "node", "wd:Q3", "start_date", "1592", "precision")
    store.upsert_nodes([Node(id="wd:Q3", type="event", label="임진왜란", source="wd",
                             start_date="1592-01-01", description="전쟁")])
    row = store.conn.execute("SELECT start_date FROM nodes WHERE id='wd:Q3'").fetchone()
    check("precision 이 자른 날짜는 재수집 뒤에도 '1592'", row[0] == "1592", row[0])

    # 4. reigns — 엣지의 재위 표식과 날짜가 props 덮어쓰기를 견딘다
    store.upsert_nodes([Node(id="wd:Q4", type="role", label="조선 임금", source="wd")])
    _e = lambda: Edge(src="wd:Q2", dst="wd:Q4", type="held_position", source="wd", props={"p": 1})
    store.upsert_edges([_e()])
    store.conn.execute("""UPDATE edges SET start_date='1418', end_date='1450',
                          props=json_set(props,'$.reign','monarch') WHERE src='wd:Q2'""")
    ek = _ov.edge_key("wd:Q2", "wd:Q4", "held_position")
    _ov.record(store.conn, "edge", ek, "props.reign", "monarch", "reigns")
    _ov.record(store.conn, "edge", ek, "start_date", "1418", "reigns")
    _ov.record(store.conn, "edge", ek, "end_date", "1450", "reigns")
    store.upsert_edges([_e()])
    row = store.conn.execute("SELECT start_date, end_date, props FROM edges WHERE src='wd:Q2'").fetchone()
    check("재위 표식이 재수집 뒤에도 남는다", '"reign": "monarch"' in row[2] and '"p": 1' in row[2], row[2])
    check("재위 날짜가 재수집 뒤에도 남는다", (row[0], row[1]) == ("1418", "1450"), (row[0], row[1]))

    # 5. describe — 정본 정의(always)는 수집이 위키 도입부를 가져와도 이긴다
    _ov.record(store.conn, "node", "wd:Q3", "description", "1592년 일본이 조선을 침략한 전쟁", "describe", "민백 정의")
    store.upsert_nodes([Node(id="wd:Q3", type="event", label="임진왜란", source="wd",
                             description="위키백과 도입부")])
    row = store.conn.execute("SELECT description FROM nodes WHERE id='wd:Q3'").fetchone()
    check("정본 설명은 수집이 덮어써도 남는다 (always)", row[0].startswith("1592년"), row[0])

    # 6. dedupe — 없앤 노드는 되살아나면 다시 합쳐진다
    store.upsert_nodes([Node(id="ex:event:임오화변", type="event", label="임오화변", source="extract",
                             description="사도세자가 뒤주에서 죽은 일"),
                        Node(id="wd:Q5", type="event", label="사도세자 사건", source="wd",
                             description="사도세자가 뒤주에서 죽은 일")])
    store.upsert_edges([Edge(src="wd:Q2", dst="ex:event:임오화변", type="participated_in", source="extract")])
    _merge_node(store, "ex:event:임오화변", "wd:Q5", method="duplicate_table")
    check("합친 노드는 사라진다", store.conn.execute(
        "SELECT 1 FROM nodes WHERE id='ex:event:임오화변'").fetchone() is None)
    store.upsert_nodes([Node(id="ex:event:임오화변", type="event", label="임오화변", source="extract")])
    store.upsert_edges([Edge(src="wd:Q2", dst="ex:event:임오화변", type="participated_in", source="extract")])
    check("되살아난 노드는 저장소가 다시 합친다", store.conn.execute(
        "SELECT 1 FROM nodes WHERE id='ex:event:임오화변'").fetchone() is None)
    check("되살아난 노드의 엣지는 남긴 쪽으로 간다", store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE dst='wd:Q5' AND type='participated_in'").fetchone()[0] == 1
        and store.conn.execute("SELECT COUNT(*) FROM edges WHERE dst='ex:event:임오화변'").fetchone()[0] == 0)

    # 7. 되짚기 — 표가 없던 DB 에서 재위·부분 날짜·정본을 표로 옮긴다
    store.conn.execute("DELETE FROM overrides")
    store.conn.execute("""UPDATE nodes SET props=json_set(props,'$.canon','nikh','$.desc_source','nikh'),
                          description='국편 글' WHERE id='wd:Q3'""")
    counts = _ov.seed_from_db(store.conn)
    check("되짚기가 재위·날짜·정본을 센다",
          counts["reigns"] == 1 and counts["precision"] == 1 and counts["nikh"] == 1, str(counts))
    store.upsert_nodes([Node(id="wd:Q3", type="event", label="임진왜란", source="wd",
                             start_date="1592-01-01", description="위키백과 도입부", props={})])
    row = store.conn.execute("SELECT description, start_date, props FROM nodes WHERE id='wd:Q3'").fetchone()
    check("되짚은 정본이 다음 수집을 이긴다",
          row[0] == "국편 글" and row[1] == "1592" and '"canon": "nikh"' in row[2], tuple(row))
    # 타입은 2026-09-07 부터 편집 계층이 지킨다 — `reclassify` 가 SQL 로만
    # 고쳐서 수집이 되돌리고 있었고, 추출이 단체를 인물로 세운 노드도 같은 자리다.
    _ov.record(store.conn, "node", "x:1", "type", "concept", "reclassify")
    check("노드 타입도 편집 계층이 지킨다", _ov.reapply(store, node_ids=["x:1"]).nodes >= 0
          and store.conn.execute("SELECT 1 FROM overrides WHERE key='x:1' AND field='type'").fetchone() is not None)
    try:
        _ov.record(store.conn, "node", "x:1", "source", "wd", "t")
        check("표에 없는 칸은 거부한다", False)
    except _ov.OverrideError:
        check("표에 없는 칸은 거부한다", True)
    store.close()


print("\n[카디널리티 — 출생지가 둘이면 무엇이 틀린 것인가]")
from histgraph.ontology import MAX_TARGETS as _MAXT, cardinality_problems as _cardp
from histgraph import cardinality as _card
check("카디널리티를 선언한 엣지 타입은 전부 스키마에 있다", set(_MAXT) <= set(EDGE_TYPES))
_pb = _cardp([
    Edge(src="p:1", dst="pl:a", type="born_in", source="t"),
    Edge(src="p:1", dst="pl:b", type="born_in", source="t"),
    Edge(src="p:1", dst="pl:a", type="born_in", source="u"),   # 같은 곳을 두 소스가 — 문제 아님
    Edge(src="p:2", dst="pl:a", type="born_in", source="t"),
])
check("한 묶음 안에서 출생지가 둘인 인물을 경고한다", len(_pb) == 1 and "p:1" in _pb[0], str(_pb))
check("소스만 다른 같은 사실은 세지 않는다", "p:2" not in " ".join(_pb))

with tempfile.TemporaryDirectory() as _d:
    store = GraphStore(Path(_d) / "card.sqlite")
    pl = lambda i, name: Node(id=f"wd:{i}", type="place", label=name, source="wd")
    store.upsert_nodes([
        pl("H", "함경도"), pl("M", "명천군"), pl("B", "부산광역시"), pl("G", "광주시"),
        pl("S", "서울특별시"), pl("J", "종로구"), pl("HS", "한성부"), pl("GY", "광양시"),
        pl("JN", "전라남도"), pl("JD", "전라도"),
        Node(id="wd:P1", type="person", label="이용익", source="wd"),
        Node(id="wd:P2", type="person", label="김성우", source="wd"),
        Node(id="wd:P3", type="person", label="김두한", source="wd"),
        Node(id="wd:P4", type="person", label="김안로", source="wd"),
        Node(id="wd:P5", type="person", label="강희열", source="wd"),
        Node(id="wd:P6", type="person", label="정의공주", source="wd"),
        Node(id="wd:F", type="person", label="조선 세종", source="wd"),
        Node(id="wd:M1", type="person", label="소헌왕후", source="wd"),
        Node(id="wd:M2", type="person", label="원경왕후", source="wd"),
    ])
    E = lambda s_, d, t, src="wd": Edge(src=s_, dst=d, type=t, source=src)
    store.upsert_edges([
        E("wd:M", "wd:H", "located_in"), E("wd:J", "wd:S", "located_in"),
        E("wd:GY", "wd:JN", "located_in"),
        E("wd:P1", "wd:H", "born_in"), E("wd:P1", "wd:M", "born_in", "kowiki:infobox"),   # 해상도
        E("wd:P2", "wd:B", "born_in"), E("wd:P2", "wd:G", "born_in", "kowiki:infobox"),   # 충돌
        E("wd:P3", "wd:S", "born_in"), E("wd:P3", "wd:J", "born_in", "kowiki:infobox"),   # 해상도
        E("wd:P4", "wd:S", "born_in"), E("wd:P4", "wd:HS", "born_in", "kowiki:infobox"),  # 옛 이름
        E("wd:P5", "wd:GY", "born_in"), E("wd:P5", "wd:JD", "born_in", "kowiki:infobox"), # 8도
        E("wd:P6", "wd:F", "child_of"), E("wd:P6", "wd:M1", "child_of", "kowiki:infobox"),
        E("wd:P6", "wd:M2", "child_of"),                                                   # 부모 셋
    ])
    vs = {v.src: v for v in _card.violations(store.conn)}
    check("출생지가 둘인 인물을 전부 잡는다", set(vs) == {"wd:P1", "wd:P2", "wd:P3", "wd:P4", "wd:P5", "wd:P6"}, str(set(vs)))
    check("함경도·명천군은 해상도 차이다", vs["wd:P1"].kind == "resolution")
    check("부산·광주는 충돌이다", vs["wd:P2"].kind == "conflict")
    check("서울·종로구는 해상도 차이다 (located_in 사슬)", vs["wd:P3"].kind == "resolution")
    check("한성부는 서울의 옛 이름이다", vs["wd:P4"].kind == "resolution")
    check("전라남도의 광양시는 전라도 안이다 (8도 표)", vs["wd:P5"].kind == "resolution")
    check("부모가 셋이면 충돌이다", vs["wd:P6"].kind == "conflict" and len(vs["wd:P6"].targets) == 3)
    shape = _card.summarize(list(vs.values()))
    check("요약은 타입별로 충돌·해상도를 센다",
          shape["born_in"] == {"conflict": 1, "resolution": 4} and shape["child_of"]["conflict"] == 1, str(shape))
    store.close()

from histgraph.sources.wikidata import ancestors_from_rows as _afr
_rows = [{"item": {"value": "http://www.wikidata.org/entity/Q1"}, "up": {"value": "http://www.wikidata.org/entity/Q2"}},
         {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "up": {"value": "http://www.wikidata.org/entity/Q3"}},
         {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "up": {"value": "http://www.wikidata.org/entity/Q1"}}]
check("상위 행정구역 응답을 QID 집합으로 읽고 자기 자신은 뺀다", _afr(_rows) == {"Q1": {"Q2", "Q3"}}, str(_afr(_rows)))


print("\n[related_to 갈라 내기 — 뜻 없는 선을 뜻 있는 타입으로]")
from histgraph import untangle as _unt
from histgraph.sources.wikidata import relax_type as _relax
check("출생지가 단체(조선)면 from_period 로 완화한다", _relax("born_in", "org") == "from_period")
check("단체의 구성원이 사건이면 참여로 완화한다", _relax("member_of", "event") == "participated_in")
check("갈 데 없는 불일치는 None (related_to)", _relax("held_position", "person") is None)
_ch = _unt.choices_for("person", "person")
check("인물끼리는 자녀·배우자·사제만 고를 수 있다",
      {t for t, _, _ in _ch} == {"child_of", "spouse_of", "taught"}, str(_ch))
check("비대칭 관계는 양방향, 부부는 한 방향", sum(1 for t, _, _ in _ch if t == "taught") == 2
      and sum(1 for t, _, _ in _ch if t == "spouse_of") == 1)
check("인물→장소는 출생지·사망지", {t for t, _, _ in _unt.choices_for("person", "place")} == {"born_in", "died_in"})
check("인과는 선택지에 없다 (별도 계약)", "caused" not in _unt.CHOICES)

with tempfile.TemporaryDirectory() as _d:
    store = GraphStore(Path(_d) / "unt.sqlite")
    N = lambda i, t, l: Node(id=i, type=t, label=l, source="wd")
    store.upsert_nodes([
        N("wd:S", "person", "성혼"), N("wd:J", "person", "조헌"), N("wd:K", "person", "김집"),
        N("wd:Y", "person", "이이"), N("wd:JO", "org", "조선"), N("wd:E", "event", "3·1 운동"),
        N("wd:P", "person", "손병희"), N("wd:A", "person", "정약용"), N("wd:B", "person", "정약전"),
        N("wd:PL", "place", "강진군"),
    ])
    store.upsert_edges([
        # 인포박스 스승: 예전 매핑 OUT (주인공 조헌 → 스승 성혼)
        Edge(src="wd:J", dst="wd:S", type="related_to", source="kowiki:infobox", props={"infobox_field": "스승"}),
        # Wikidata 완화: 출생지 '조선'
        Edge(src="wd:Y", dst="wd:JO", type="related_to", source="wd", label="출생지",
             props={"original_type": "born_in", "wikidata_property": "P19"}),
        Edge(src="wd:P", dst="wd:E", type="related_to", source="wd", label="소속",
             props={"original_type": "member_of"}),
        # 겹침: 정약전은 이미 정약용의 형(child_of 는 없지만 spouse 아님) — 뜻 있는 엣지가 있는 짝
        Edge(src="wd:A", dst="wd:B", type="related_to", source="extract", props={"evidence": "형 정약전"}),
        Edge(src="wd:B", dst="wd:A", type="taught", source="kowiki:infobox"),
        # 모델에 물을 것
        Edge(src="wd:K", dst="wd:Y", type="related_to", source="extract",
             props={"evidence": "김집은 이이의 문인이다.", "extracted_from": "wd:K"}),
        Edge(src="wd:A", dst="wd:PL", type="related_to", source="extract",
             props={"evidence": "정약용은 강진에서 18년을 유배 살았다."}),
    ])
    rep = _unt.Report()
    _unt.apply_rules(store, rep)
    e = lambda s_, d, t: store.conn.execute(
        "SELECT 1 FROM edges WHERE src=? AND dst=? AND type=?", (s_, d, t)).fetchone() is not None
    check("인포박스 스승은 taught 로, 방향은 스승 → 제자", e("wd:S", "wd:J", "taught") and not e("wd:J", "wd:S", "related_to"))
    check("출생지 '조선'은 from_period 조선으로", e("wd:Y", "wd:JO", "from_period") and not e("wd:Y", "wd:JO", "related_to"))
    check("3·1 운동의 구성원은 참여자로", e("wd:P", "wd:E", "participated_in"))
    check("규칙 보고는 셋", len(rep.relaxed) == 3, str(rep.relaxed))
    _unt.fold_redundant(store, rep)
    check("뜻 있는 엣지가 있는 짝의 related_to 는 접는다", rep.folded == 1 and not e("wd:A", "wd:B", "related_to"))
    mp = store.conn.execute("SELECT props FROM edges WHERE src='wd:B' AND dst='wd:A' AND type='taught'").fetchone()[0]
    check("접을 때 근거는 뜻 있는 쪽으로 옮긴다", "형 정약전" in mp, mp)
    cands = _unt.candidates(store.conn)
    check("모델에 물을 것은 근거 있는 추출 엣지 둘", {(r["src"], r["dst"]) for r in cands} == {("wd:K", "wd:Y"), ("wd:A", "wd:PL")})

    class _FakeBackend:
        model = "fake"
        def __init__(self, answers): self.answers = answers
        def complete_json(self, system, user, schema):
            for key, ans in self.answers.items():
                if key in user:
                    assert ans["type"] in schema["properties"]["type"]["enum"], (ans, schema["properties"]["type"]["enum"])
                    return ans
            return {"type": "none", "direction": "A→B", "confidence": "certain"}
    fake = _FakeBackend({
        "김집": {"type": "taught", "direction": "B→A", "confidence": "certain"},
        "강진": {"type": "born_in", "direction": "A→B", "confidence": "possible"},
    })
    _unt.run_model(store, fake, rep)
    check("문인 관계는 스승(이이) → 제자(김집) taught 가 된다", e("wd:Y", "wd:K", "taught") and not e("wd:K", "wd:Y", "related_to"))
    check("확신이 '가능'뿐이면 적지 않고 판정만 남긴다", e("wd:A", "wd:PL", "related_to") and rep.weak == 1)
    left = store.conn.execute("SELECT props FROM edges WHERE src='wd:A' AND dst='wd:PL'").fetchone()[0]
    check("판정은 원래 줄에 남는다", '"untangled": "born_in/possible"' in left, left)
    check("다시 돌리면 판정한 것은 묻지 않는다", _unt.candidates(store.conn) == [])
    check("--redo 면 다시 묻는다", len(_unt.candidates(store.conn, redo=True)) == 1)
    # 카디널리티: 이미 출생지가 있는 사람에게 두 번째 출생지를 주지 않는다
    store.upsert_nodes([N("wd:PL2", "place", "광주"), N("wd:C", "person", "김성우")])
    store.upsert_edges([
        Edge(src="wd:C", dst="wd:PL2", type="born_in", source="wd"),
        Edge(src="wd:C", dst="wd:PL", type="related_to", source="extract", props={"evidence": "강진 출생"}),
    ])
    rep2 = _unt.Report()
    _unt.run_model(store, _FakeBackend({"김성우": {"type": "born_in", "direction": "A→B", "confidence": "certain"}}), rep2)
    check("카디널리티를 넘는 판정은 적지 않고 센다", rep2.over_cardinality == [("wd:C", "wd:PL", "born_in")]
          and e("wd:C", "wd:PL", "related_to"), str(rep2.over_cardinality))
    rem = _unt.remaining(store.conn)
    check("남는 것을 갈래별로 센다", rem.get("모델이 확신하지 못한 것") == 1, str(rem))
    store.close()

# 표 경로 — 로컬 모델 대신 사람(또는 Claude)이 적은 판정 (data/untangle.tsv)
with tempfile.TemporaryDirectory() as _d:
    store = GraphStore(Path(_d) / "unt2.sqlite")
    N = lambda i, t, l: Node(id=i, type=t, label=l, source="wd")
    store.upsert_nodes([N("wd:T", "person", "이항로"), N("wd:S", "person", "최익현"),
                        N("wd:X", "person", "김평묵"), N("wd:W", "artwork", "용의 눈물")])
    store.upsert_edges([
        Edge(src="wd:S", dst="wd:T", type="related_to", source="extract", props={"evidence": "그의 스승 이항로"}),
        Edge(src="wd:S", dst="wd:X", type="related_to", source="extract", props={"evidence": "친구 김평묵"}),
        Edge(src="wd:S", dst="wd:W", type="related_to", source="extract", props={"evidence": "배우: 아무개"}),
    ])
    tbl = Path(_d) / "untangle.tsv"
    tbl.write_text("# 머리\nwd:S\twd:T\ttaught\tB→A\tcertain\t스승\nwd:S\twd:X\tnone\tA→B\tcertain\t친구\n"
                   "wd:S\twd:W\tdepicts\tB→A\tcertain\t배역\n", encoding="utf-8")
    table = _unt.load_verdicts(tbl)
    check("표를 (src, dst) 로 읽는다", set(table) == {("wd:S", "wd:T"), ("wd:S", "wd:X"), ("wd:S", "wd:W")})
    rep = _unt.Report()
    _unt.run_table(store, table, rep)
    e = lambda s_, d, t: store.conn.execute(
        "SELECT 1 FROM edges WHERE src=? AND dst=? AND type=?", (s_, d, t)).fetchone() is not None
    check("표의 스승 판정은 taught 이항로 → 최익현", e("wd:T", "wd:S", "taught") and not e("wd:S", "wd:T", "related_to"))
    check("표의 none 은 related_to 로 남고 판정 표식이 붙는다", e("wd:S", "wd:X", "related_to")
          and '"untangled": "none"' in store.conn.execute("SELECT props FROM edges WHERE dst='wd:X'").fetchone()[0])
    check("작품 → 인물은 depicts 로 뒤집힌다", e("wd:W", "wd:S", "depicts"))
    check("표에 있는 것만 묻고 모델 이름은 표로 적는다", rep.asked == 3 and _unt.TABLE_MODEL in
          store.conn.execute("SELECT props FROM edges WHERE src='wd:T' AND type='taught'").fetchone()[0])
    try:
        (Path(_d) / "bad.tsv").write_text("wd:S\twd:T\tfriend_of\tA→B\tcertain\n", encoding="utf-8")
        _unt.load_verdicts(Path(_d) / "bad.tsv")
        check("모르는 타입은 표를 거부한다", False)
    except ValueError:
        check("모르는 타입은 표를 거부한다", True)
    store.close()

print("\n[연대 — 원인은 결과보다 먼저다 (chronology)]")
with tempfile.TemporaryDirectory() as _d:
    from histgraph import chronology as _ch

    store = GraphStore(Path(_d) / "ch.sqlite")
    def _ev(i, label, start, end=None):
        return Node(id=i, type="event", label=label, source="wd", description=f"{label} 설명",
                    start_date=start, end_date=end)
    store.upsert_nodes([
        _ev("wd:H", "병자호란", "1636-12-09"), _ev("wd:G", "공석신주사건", "1636", "1636"),
        _ev("wd:Y", "요동 정벌", "1388"), _ev("wd:W", "위화도 회군", "1388-06-11"),
        _ev("wd:S", "서울의 봄", "1979-10-27"), _ev("wd:K", "5·18", "1980-05-18"),
        _ev("wd:M", "만주사변", "1931-09-18"), _ev("wd:N", "신사참배", "1931"),
    ])
    _c = lambda a, b, **kw: Edge(src=a, dst=b, type="caused", source="causes", label="원인",
                                 confidence=0.8, props={"evidence": "…", "doc": a}, **kw)
    store.upsert_edges([_c("wd:H", "wd:G"), _c("wd:W", "wd:Y"), _c("wd:K", "wd:S"), _c("wd:M", "wd:N")])

    check("거친 결과 날짜가 원인을 품으면 within", _ch.order("1636-12-09", "1636") == "within")
    check("같은 날도 within", _ch.order("1907-08-01", "1907-08-01") == "within")
    check("원인이 결과보다 뒤면 after", _ch.order("1980-05-18", "1979-10-27") == "after"
          and _ch.order("1388-06-11", "1388-05") == "after")
    check("원인이 앞이면 ok, 모르면 unknown", _ch.order("1388-05", "1388-06-11") == "ok"
          and _ch.order("", "1636") == "unknown")
    check("기원전은 뒤집히지 않는다", _ch.order("-0100", "-0057") == "ok")
    rep = _ch.find(store.conn)
    # 위화도 회군(06-11) → 요동 정벌(1388)은 방향이 뒤집혔지만 날짜로는 못
    # 잡는다 — 결과의 거친 날짜가 원인을 품는다. 그래서 표(flip)가 있다.
    check("찾기: 원인이 뒤인 것만 backwards, 품는 것은 within",
          [s.effect for s in rep.backwards] == ["서울의 봄"]
          and sorted(s.effect for s in rep.within) == ["공석신주사건", "신사참배", "요동 정벌"],
          f"{[s.effect for s in rep.backwards]} {[s.effect for s in rep.within]}")

    tbl = Path(_d) / "chronology.tsv"
    tbl.write_text(
        "# 주석\n"
        "date\twd:G\t1638-01\t\t민백: 1638년 1월 탄핵\n"
        "date\twd:Y\t1388-05\t\t음력 4월 출정\n"
        "drop\twd:K\twd:S\t끝낸 것이지 원인이 아니다\n"
        "flip\twd:W\twd:Y\t배경\t정벌군이 회군했다\n"
        "date\twd:NOPE\t1900\t\t없는 노드\n",
        encoding="utf-8")
    table = _ch.load_table(tbl)
    check("표를 읽는다 (주석 건너뜀)", len(table) == 5 and table[0].action == "date" and table[3].c == "배경")
    bad = Path(_d) / "bad.tsv"
    bad.write_text("date\twd:G\t언젠가\t\t근거\n", encoding="utf-8")
    try:
        _ch.load_table(bad); check("날짜가 아니면 거부한다", False)
    except _ch.ChronologyTableError:
        check("날짜가 아니면 거부한다", True)
    bad.write_text("drop\twd:K\twd:S\n", encoding="utf-8")
    try:
        _ch.load_table(bad); check("근거가 없으면 거부한다", False)
    except _ch.ChronologyTableError:
        check("근거가 없으면 거부한다", True)

    ap = _ch.apply(store, table)
    d = lambda i: store.conn.execute("SELECT start_date, end_date FROM nodes WHERE id=?", (i,)).fetchone()
    e = lambda a, b: store.conn.execute(
        "SELECT source, label FROM edges WHERE src=? AND dst=? AND type='caused'", (a, b)).fetchall()
    check("날짜를 씌운다 — 새 시작보다 앞선 옛 끝은 비운다", tuple(d("wd:G")) == ("1638-01", None) and d("wd:Y")[0] == "1388-05",
          f"{tuple(d('wd:G'))} {tuple(d('wd:Y'))}")
    check("지운 인과는 없다", e("wd:K", "wd:S") == [])
    check("뒤집은 인과는 결과 → 원인으로 선다", e("wd:W", "wd:Y") == [] and [tuple(r) for r in e("wd:Y", "wd:W")] == [("chronology", "배경")],
          str(e("wd:Y", "wd:W")))
    check("없는 노드는 세어 보고만 한다", [r.a for r in ap.absent] == ["wd:NOPE"] and ap.dated == 2 and ap.dropped == 1 and ap.flipped == 1)
    check("씌운 뒤에는 원인이 뒤인 것이 없다", _ch.find(store.conn).backwards == [])
    # 수집이 옛 날짜와 지운 엣지를 되살려도 편집 계층이 다시 씌운다
    store.upsert_nodes([_ev("wd:G", "공석신주사건", "1636", "1636")])
    store.upsert_edges([_c("wd:K", "wd:S"), _c("wd:W", "wd:Y")])
    check("재수집 뒤에도 날짜는 표의 것이다", tuple(d("wd:G")) == ("1638-01", None), str(tuple(d("wd:G"))))
    check("재수집이 되살린 인과는 다시 지워진다", e("wd:K", "wd:S") == [] and e("wd:W", "wd:Y") == [])
    check("두 번 돌려도 뒤집은 엣지는 하나다", len(e("wd:Y", "wd:W")) == 1 and _ch.apply(store, table).flipped == 1
          and len(e("wd:Y", "wd:W")) == 1)
    store.close()


print("\n[연대 — 결과가 나라·단체면 끝나기 전이면 된다]")
with tempfile.TemporaryDirectory() as _d:
    from histgraph import chronology as _ch2

    store = GraphStore(Path(_d) / "ch2.sqlite")
    store.upsert_nodes([
        Node(id="wd:IM", type="event", label="임진왜란", source="wd", description="설명",
             start_date="1592-05-23", end_date="1598-12-16"),
        # 결과가 사라진 뒤의 원인 — 불가능하다
        Node(id="wd:P", type="org", label="통일민주당", source="wd", description="설명",
             start_date="1987", end_date="1990-01-01"),
        Node(id="wd:MG", type="event", label="3당 합당", source="wd", description="설명",
             start_date="1990-01-22"),
        # 창립 뒤·소멸 전 — '명나라의 쇠퇴' 꼴이라 세기만 한다
        Node(id="wd:MI", type="org", label="명나라", source="wd", description="설명",
             start_date="1368", end_date="1644"),
        # 끝을 모르는 결과는 언제든 영향을 받을 수 있다
        Node(id="wd:C", type="concept", label="한글", source="wd", description="설명",
             start_date="1443"),
        Node(id="wd:J", type="event", label="조선어학회 사건", source="wd", description="설명",
             start_date="1942-10-01"),
    ])
    _c2 = lambda a, b: Edge(src=a, dst=b, type="caused", source="causes", label="원인",
                            confidence=0.8, props={"evidence": "…", "doc": a})
    store.upsert_edges([_c2("wd:MG", "wd:P"), _c2("wd:IM", "wd:MI"), _c2("wd:J", "wd:C")])
    rep2 = _ch2.find(store.conn)
    check("결과가 사라진 뒤의 원인은 걸린다", [s.effect for s in rep2.backwards] == ["통일민주당"],
          str([s.effect for s in rep2.backwards]))
    check("존속하는 동안의 원인은 세기만 한다 (명나라의 쇠퇴)", rep2.lifetime == 2 and rep2.within == [],
          f"{rep2.lifetime} {[s.effect for s in rep2.within]}")
    check("결과가 사건이 아니어도 전수로 잰다",
          len(rep2.backwards) + len(rep2.within) + rep2.lifetime + rep2.unknown == 3)
    store.close()


print("\n[서술구 사건 — 표지도 숫자도 없는 이름은 사건 노드가 아니다]")
from histgraph.extract import is_abstract_event as _abs
check("개념·서술구는 사건이 아니다", all(_abs(x) for x in
      ["세력 강화", "민족정신", "문맹퇴치", "충군", "학문", "심리학적인 관점", "단독정부 수립론", "성호사설", "동아일보"]))
check("사건 표지가 있으면 사건이다", not any(_abs(x) for x in
      ["임진왜란", "제1차 왕자의 난", "갑신정변", "3·1 운동", "안악 사건", "신간회 결성", "조선 건국",
       "훈민정음 창제", "을사조약 체결", "만민공동회", "부산항의 개항", "정조 즉위", "이양선의 출현"]))
check("숫자가 있으면 사건으로 본다", not _abs("1971년 대통령선거") and not _abs("6.25 남침 전쟁"))
with tempfile.TemporaryDirectory() as _d:
    from histgraph import promote as _pr
    store = GraphStore(Path(_d) / "abs.sqlite")
    store.upsert_nodes([
        Node(id="nikh:R1", type="heritage", label="성호사설", source="nikh", description="이익의 저술"),
        Node(id="ex:event:성호사설", type="event", label="성호사설", source="extract"),
        Node(id="ex:event:세력 강화", type="event", label="세력 강화", source="extract"),
        Node(id="ex:event:임진왜란 발발", type="event", label="임진왜란 발발", source="extract"),
        Node(id="wd:P", type="person", label="이익", source="wd"),
    ])
    store.upsert_edges([
        Edge(src="wd:P", dst="ex:event:성호사설", type="related_to", source="extract"),
        Edge(src="wd:P", dst="ex:event:세력 강화", type="related_to", source="extract"),
    ])
    rt = _pr.retype(store)
    e = lambda s_, d: store.conn.execute("SELECT 1 FROM edges WHERE src=? AND dst=?", (s_, d)).fetchone() is not None
    check("같은 이름의 유물이 있으면 그쪽으로 흡수한다", rt["absorbed"] == [("ex:event:성호사설", "nikh:R1")]
          and e("wd:P", "nikh:R1") and store.conn.execute("SELECT 1 FROM nodes WHERE id='ex:event:성호사설'").fetchone() is None)
    check("서술구 사건은 엣지와 함께 지운다", rt["abstract"] == ["ex:event:세력 강화"]
          and store.conn.execute("SELECT COUNT(*) FROM edges WHERE dst='ex:event:세력 강화'").fetchone()[0] == 0)
    check("표지 있는 사건 고아는 그대로다", store.conn.execute("SELECT 1 FROM nodes WHERE id='ex:event:임진왜란 발발'").fetchone() is not None)
    check("흡수는 편집 계층에 남아 되살아나면 다시 합친다", store.conn.execute(
        "SELECT value FROM overrides WHERE key='ex:event:성호사설' AND field='merged_into'").fetchone()[0] == '"nikh:R1"')
    store.close()

# --- 세종 사슬에 한글이 없던 세 가지 뿌리 (2026-09-06) -------------------------
from histgraph import labels as labels_mod2, overrides as overrides_mod  # noqa: E402
from histgraph.extract import complete_evidence as _ce  # noqa: E402
from histgraph.sources import aks as aks_mod2  # noqa: E402

print("\n[민족문화대백과 — 연대가 어긋나면 잇지 않는다]")
_E2 = lambda i, label, kind, era, definition="정의.": aks_mod2.Entry(  # noqa: E731
    id=i, url=f"https://encykorea.aks.ac.kr/Article/{i}", label=label, hanja="",
    field="", kind=kind, era=era, definition=definition)
check("시대 칸을 연도 구간으로 읽는다 — 하위 시대는 좁게, '고려 | 조선'은 합쳐서",
      aks_mod2.era_span("조선/조선 후기") == (1592, 1897) and aks_mod2.era_span("고려 | 조선") == (918, 1897)
      and aks_mod2.era_span("") is None and aks_mod2.era_span("미상") is None)
check("글의 연도만 센다 — '제30호'·'3·1'은 아니다",
      aks_mod2.text_years("1397년(태조 6)에 나서 1450년에 죽었다. 국보 제30호. 3·1 운동") == [1397, 1450])
ido = _E2("E0044022", "이도", "인물/전통 인물", "조선",
          "조선 후기에, 정묘호란이 발발하자 의병을 일으켜 활동한 의병장.")
check("시대 칸이 '조선'뿐이어도 정의의 '조선 후기'가 가른다 — 세종(1397~1450)은 아니다",
      not aks_mod2.consistent(ido, (1397, 1450))
      and aks_mod2.consistent(ido, (1600, 1660)))
bare = _E2("E0044022", "이도", "인물/전통 인물", "조선", "의병장.")
check("시대 칸도 정의도 말이 없으면 못 가른다 — 본문을 받아야 한다", aks_mod2.consistent(bare, (1397, 1450)))
check("본문의 연도가 생몰년에서 110년 넘게 떨어지면 다른 사람이다",
      not aks_mod2.consistent(bare, (1397, 1450), "1627년 정묘호란이 일어나자 의병을 일으켰다. 1636년 병자호란.")
      and aks_mod2.consistent(bare, (1397, 1450), "1443년 훈민정음을 만들었다."))
check("하위 시대가 적혀 있으면 그것으로 가른다",
      not aks_mod2.consistent(_E2("E1", "이도", "인물/전통 인물", "조선/조선 후기"), (1397, 1450)))
check("정의의 연도로도 가른다",
      not aks_mod2.consistent(_E2("E1", "강봉수", "인물/전통 인물", "조선", "1573년에 난 문신."), (1971, None)))
check("현대 인물에 조선 항목은 잇지 않는다",
      not aks_mod2.consistent(_E2("E1", "강봉수", "인물/전통 인물", "조선"), (1971, None)))
check("시대 경계는 무르다 — 고려 말에 난 조선 개국공신",
      aks_mod2.consistent(_E2("E1", "정도전", "인물/전통 인물", "조선"), (1342, 1398)))
check("노드 연대를 모르면 막지 않는다", aks_mod2.consistent(ido, None) and aks_mod2.consistent(ido, (None, None)))
check("연도가 있으면 연도가 이긴다 — 시대 칸이 틀린 항목",
      aks_mod2.consistent(_E2("E1", "오익창", "인물/전통 인물", "선사/청동기", "조선 후기 의병."), (1557, 1643),
                          "1592년 임진왜란 때 의병을 일으켰다."))
check("아직 있는 단체는 뒤가 열려 있다 — 1200년에 선 종단의 1962년 출범 글",
      aks_mod2.consistent(_E2("E1", "대한불교조계종", "단체", "현대/대한민국", "1962년 출범한 종단."), (1200, 2100)))
m = aks_mod2.match_nodes([ido], [("wd:SEJONG", "이도", "person")], {"wd:SEJONG": (1397, 1450)})
check("match_nodes 는 연대를 주면 시대·정의로 거른다",
      m == {} and aks_mod2.match_nodes([_E2("E1", "이도", "인물/전통 인물", "조선/조선 후기")],
                                       [("wd:SEJONG", "이도", "person")], {"wd:SEJONG": (1397, 1450)}) == {}
      and aks_mod2.match_nodes([ido], [("wd:SEJONG", "이도", "person")]) == {"E0044022": "wd:SEJONG"})

with tempfile.TemporaryDirectory() as tmp:
    raw = Path(tmp) / "raw"
    raw.mkdir()
    head = "항목 아이디,항목 고유 웹주소,대표 미디어 아이디,항목명,원어,항목 분야,항목 유형,시대,항목 정의,집필자 정보"
    rows = [("E0044022", "이도", "인물/전통 인물", "조선", "조선 후기에 정묘호란이 발발하자 의병을 일으킨 의병장."),
            ("E2", "정도전", "인물/전통 인물", "조선", "조선 개국공신."),
            ("E3", "강봉수", "인물/전통 인물", "조선", "1573년에 난 문신.")]
    body = "\n".join(f"{i},https://encykorea.aks.ac.kr/Article/{i},x,{label},,,{kind},{era},{d},글쓴이"
                     for i, label, kind, era, d in rows)
    (raw / aks_mod2.INDEX_CSV).write_text("\ufeff" + head + "\n" + body + "\n", encoding="utf-8")
    store = GraphStore(Path(tmp) / "g.sqlite")
    store.upsert_nodes([
        Node(id="wd:SEJONG", type="person", label="조선 세종", source="wd", start_date="1397-05-15", end_date="1450-04-08",
             aliases=["이도", "세종대왕"]),
        Node(id="wd:JDJ", type="person", label="정도전", source="wd", start_date="1342", end_date="1398"),
        Node(id="wd:KBS", type="person", label="강봉수 (야구 선수)", source="wd", start_date="1971", aliases=["강봉수"]),
        Node(id="nikh:JAS", type="heritage", label="장안성", source="nikh", start_date="1935"),
    ])
    check("국가유산의 날짜는 지정일이라 연대로 재지 않는다", aks_mod2.node_years(store)["nikh:JAS"] == (None, None)
          and aks_mod2.node_years(store)["wd:KBS"] == (1971, 2061))
    rep = aks_mod2.fill_descriptions(store, raw_dir=raw)
    got = dict(store.conn.execute("SELECT id, description FROM nodes"))
    check("빈 설명 채우기도 같은 검사를 지난다 — 세종에 의병장 정의를 붙이지 않는다",
          not got["wd:SEJONG"] and not got["wd:KBS"] and got["wd:JDJ"] == "조선 개국공신." and rep["mismatched"] == 2, str(rep))

    # 검사가 없던 때 이어진 문서·설명을 되돌아본다
    conn = corpus_mod.open_corpus(Path(tmp) / "corpus.sqlite")
    corpus_mod.put_doc(conn, "wd:SEJONG", "이도", "== 정의 ==\n의병장.\n\n== 생애 ==\n1627년 정묘호란이 일어나자 의병을 일으켰다.",
                       "aks", "https://encykorea.aks.ac.kr/Article/E0044022")
    corpus_mod.put_doc(conn, "wd:SEJONG", "세종", "== 정의 ==\n조선 제4대 왕. 1443년 훈민정음을 만들었다.", "nikh")
    corpus_mod.put_doc(conn, "wd:JDJ", "정도전", "== 정의 ==\n1342년에 나서 1398년에 죽은 개국공신.",
                       "aks", "https://encykorea.aks.ac.kr/Article/E2")
    store.conn.execute("""UPDATE nodes SET description = '1573년에 난 문신.',
                          props = json_set(props, '$.desc_source', 'aks', '$.desc_url', 'https://encykorea.aks.ac.kr/Article/E3')
                          WHERE id = 'wd:KBS'""")
    overrides_mod.record(store.conn, "node", "wd:KBS", "description", "1573년에 난 문신.", "describe")
    dry = aks_mod2.audit_bindings(store, conn, raw_dir=raw, dry_run=True)
    check("미리보기는 바꾸지 않는다", corpus_mod.has_doc(conn, "wd:SEJONG", "aks") and len(dry["rebound"]) == 1)
    got = aks_mod2.audit_bindings(store, conn, raw_dir=raw)
    check("어긋난 문서는 고아 아이디로 옮기고 맞는 것은 둔다",
          [r[:2] for r in got["rebound"]] == [("wd:SEJONG", "E0044022")]
          and not corpus_mod.has_doc(conn, "wd:SEJONG", "aks") and corpus_mod.has_doc(conn, "aks:E0044022", "aks")
          and corpus_mod.has_doc(conn, "wd:SEJONG", "nikh") and corpus_mod.has_doc(conn, "wd:JDJ", "aks"), str(got))
    check("문단도 함께 옮긴다 — 세종의 문단에 의병장 글이 남지 않는다",
          {r["source"] for r in causes_mod.doc_passages(conn, "wd:SEJONG")} == {"nikh"})
    desc, props = store.conn.execute("SELECT description, props FROM nodes WHERE id='wd:KBS'").fetchone()
    check("어긋난 정의로 채운 설명은 비우고 편집 계층에서도 지운다",
          not desc and "desc_source" not in props
          and store.conn.execute("SELECT COUNT(*) FROM overrides WHERE key='wd:KBS'").fetchone()[0] == 0, str((desc, props)))
    check("두 번 돌리면 할 일이 없다", aks_mod2.audit_bindings(store, conn, raw_dir=raw)["rebound"] == [])
    conn.close()
    store.close()

print("\n[근거 대조 — 한자 괄호는 양쪽에서 뺀다]")
_T = "훈민정음(訓民正音)의 창제는 세종이 남긴 문화유산 가운데 가장 빛나는 업적이다. 세종이 훈민정음을 처음 창제한 것은 1443년(세종 25)이었다."
check("모델이 한자 괄호를 빼고 인용해도 문장을 되찾는다",
      _ce("훈민정음의 창제는 세종이 남긴 문화유산 가운데 가장 빛나는 업적이다.", _T)
      == "훈민정음(訓民正音)의 창제는 세종이 남긴 문화유산 가운데 가장 빛나는 업적이다.")
check("한자 괄호를 그대로 인용해도 된다",
      _ce("훈민정음(訓民正音)의 창제는 세종이 남긴 문화유산 가운데", _T) is not None)
check("한글·숫자 괄호는 그대로 대조한다 — '(세종 25)'는 빼지 않는다",
      _ce("세종이 훈민정음을 처음 창제한 것은 1443년(세종 25)이었다.", _T) is not None
      and _ce("세종이 훈민정음을 처음 창제한 것은 1443년이었다.", _T) is None)

print("\n[해소기 — 그 자리에 못 서는 타입은 고르지 않는다]")
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "r.sqlite")
    store.upsert_nodes([
        Node(id="wd:SEJONG", type="person", label="조선 세종", source="wd", start_date="1397", end_date="1450", aliases=["세종"]),
        Node(id="khs:HMJ", type="heritage", label="훈민정음", source="khs", start_date="1443"),
        Node(id="wd:HANGUL", type="event", label="한글", source="wd", start_date="1443"),
    ])
    doc = {"id": "wd:SEJONG", "start_date": "1397", "end_date": "1450"}
    got = causes_mod.resolve(store, "훈민정음", "event", doc)
    check("자리를 안 주면 전처럼 이름 그대로 — 유물", got and got[0] == "khs:HMJ", str(got))
    got = causes_mod.resolve(store, "훈민정음", "event", doc, allowed=causes_mod.EFFECT_TYPES)
    check("결과 자리에는 유물을 고르지 않는다 — 별칭이 없으면 못 푼다", got is None, str(got))
    table = Path(tmp) / "aliases.tsv"
    table.write_text("# 별칭 표\nwd:HANGUL\t훈민정음\t창제 당시 이름\n", encoding="utf-8")
    rows = labels_mod2.load_alias_table(table)
    arep = labels_mod2.apply_aliases(store.conn, rows)
    got = causes_mod.resolve(store, "훈민정음", "event", doc, allowed=causes_mod.EFFECT_TYPES)
    check("별칭 표를 적용하면 한글로 풀린다", arep.added == [("wd:HANGUL", "훈민정음")] and got and got[0] == "wd:HANGUL", str(got))
    answers = [{"cause": "세종", "cause_type": "person", "effect": "훈민정음", "effect_type": "event", "kind": "원인",
                "how": "창제하여 반포", "evidence": "훈민정음의 창제는 세종이 남긴 문화유산 가운데 가장 빛나는 업적이다.",
                "confidence": "certain"}]
    edges, why, _ = causes_mod.accept(store, doc, answers, [{"text": _T}], "m")
    check("세종 → 한글 인과가 선다", [(e.src, e.dst, e.label) for e in edges] == [("wd:SEJONG", "wd:HANGUL", "원인")], str(why))
    store.conn.execute("DELETE FROM aliases WHERE node_id='wd:HANGUL'")
    overrides_mod.reapply(store, node_ids=["wd:HANGUL"])
    check("별칭은 편집 계층에 남아 수집 뒤에 되살아난다",
          store.conn.execute("SELECT alias FROM aliases WHERE node_id='wd:HANGUL'").fetchone()[0] == "훈민정음")
    check("표를 두 번 적용해도 같다", labels_mod2.apply_aliases(store.conn, rows).already == 1)
    bad = Path(tmp) / "bad.tsv"
    bad.write_text("Q8222\t훈민정음\n", encoding="utf-8")
    try:
        labels_mod2.load_alias_table(bad)
        check("별칭 표는 노드 id 를 통째로 적는다", False)
    except labels_mod2.LabelTableError:
        check("별칭 표는 노드 id 를 통째로 적는다", True)
    store.close()

print("\n[사슬의 갈래가 잘릴 때 — 종류·관계 수 순, 아이디 순이 아니다]")
with tempfile.TemporaryDirectory() as tmp:
    store = GraphStore(Path(tmp) / "f.sqlite")
    nodes = [Node(id="wd:SEJONG", type="person", label="조선 세종", source="wd", start_date="1397")]
    edges = []
    for i in range(7):   # 아이디가 앞서는 결과 일곱 — 관계는 이 엣지 하나뿐
        nodes.append(Node(id=f"wd:Q1{i}", type="event", label=f"작은 일 {i}", source="wd", start_date="1420"))
        edges.append(Edge(src="wd:SEJONG", dst=f"wd:Q1{i}", type="caused", source="causes",
                          label="영향" if i == 0 else "원인", confidence=0.9))
    nodes.append(Node(id="wd:Q9", type="event", label="한글", source="wd", start_date="1443"))
    edges.append(Edge(src="wd:SEJONG", dst="wd:Q9", type="caused", source="causes", label="원인", confidence=0.9))
    for k in range(5):   # 한글은 관계가 많다
        nodes.append(Node(id=f"wd:H{k}", type="event", label=f"한글 뒤 {k}", source="wd", start_date="1500"))
        edges.append(Edge(src="wd:Q9", dst=f"wd:H{k}", type="caused", source="causes", label="배경", confidence=0.5))
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)
    got = causes_mod.chain(store, "wd:SEJONG")
    top = [r["id"] for r in got["effects"]]
    check("관계 많은 결과가 아이디에 밀려 잘리지 않는다", top[0] == "wd:Q9" and len(top) == causes_mod.FANOUT, str(top))
    check("'영향'은 '원인' 뒤라 먼저 잘린다", "wd:Q10" not in top, str(top))
    store.close()

# --- 제도·시설이 선 날을 사건으로 (2026-09-06 "이 시기 왕들때는 아무런 일이 없었어?") ---
print("\n[민백 표제 + 고려사 날짜 — 선 날의 사건]")
_spots, _founded = aks_mod2._spots, aks_mod2._founded_by
check("조사가 붙어도 낱말이다 — '국자감시를'",
      _spots("국자감시를 설치하다", "국자감시") == [4])
check("조사가 아닌 한글이 이어지면 더 긴 이름이다 — '국자감' + '시를'",
      _spots("국자감시를 설치하다", "국자감") == [])
check("앞에 한글이 붙어 있어도 낱말이 아니다",
      _spots("탐라만호부를 두다", "만호부") == [])
check("표제 바로 뒤의 술어라야 그 표제가 선 것이다",
      _founded("국자감시를 설치하다", "국자감시", "제도") == "설치"
      and _founded("국자감에 서적포를 설치하게 하다", "서적포", "제도") == "설치"
      and _founded("국자감에 서적포를 설치하게 하다", "국자감", "제도/관청") is None)
check("접속조사로 묶인 것은 술어를 나눠 가진다",
      _founded("전함병량도감과 전함조성도감을 설치하다", "전함병량도감", "제도") == "설치")
check("술어는 유형에 맞아야 한다 — 비서성(제도)이 '간행'한 것은 책이다",
      _founded("비서성에서 간행한 서적을 올리다", "비서성", "제도") is None
      and _founded("『해동비록』이 편찬되다", "해동비록", "문헌/고서") == "편찬")
check("바치고 올린 것은 선 것이 아니다",
      _founded("탁라의 유격장군이 방물을 바치다", "유격장군", "제도/관직") is None)
check("청하고 건의한 것은 선 것이 아니다 — 날짜가 어긋난다",
      _founded("안향이 섬학전 설치를 건의하다", "섬학전", "제도") is None
      and _founded("탐라총관부를 없애고 만호부 설치를 청하다", "만호부", "제도/관청") is None)

with tempfile.TemporaryDirectory() as tmp:
    raw = Path(tmp) / "raw"
    raw.mkdir()
    head = "항목 아이디,항목 고유 웹주소,대표 미디어 아이디,항목명,원어,항목 분야,항목 유형,시대,항목 정의,집필자 정보"
    rows = [("E1", "국자감시", "제도", "고려", "국자감에서 치러진 예부시의 예비시험."),
            ("E2", "국자감", "제도/관청", "고려", "고려시대 개경에 설치한 최고 교육기관."),
            ("E3", "묘법연화경", "문헌/고서", "고려", "1286년에 간행한 불교경전."),
            ("E4", "유격장군", "제도/관직", "고려", "고려시대 무산계 산직의 하나.")]
    body = "\n".join(f"{i},https://encykorea.aks.ac.kr/Article/{i},x,{label},,,{kind},{era},{d},글쓴이"
                     for i, label, kind, era, d in rows)
    (raw / aks_mod2.INDEX_CSV).write_text("\ufeff" + head + "\n" + body + "\n", encoding="utf-8")

    idx_path = Path(tmp) / "index.sqlite"
    conn = sqlite3.connect(idx_path)
    conn.executescript(
        """CREATE TABLE articles (
             id TEXT PRIMARY KEY, king TEXT, date TEXT, title TEXT,
             classes TEXT, refs TEXT, names TEXT, text TEXT,
             book TEXT NOT NULL DEFAULT '실록', calendar TEXT NOT NULL DEFAULT 'lunar');
           CREATE VIRTUAL TABLE title_fts USING fts5(id UNINDEXED, title, tokenize='trigram');""")
    arts = [("a1", "1031-11-22", "국자감시를 설치하다", "고려사", "gregorian"),
            ("a2", "", "국자감시를 처음 실시하다", "고려사", ""),
            ("a3", "1101-05-17", "금글자로 쓴 묘법연화경의 완성을 경축하고 시를 짓다", "고려사", "gregorian"),
            ("a4", "1086-02-23", "탁라의 유격장군이 방물을 바치다", "고려사", "gregorian")]
    for aid, date, title, book, cal in arts:
        conn.execute("INSERT INTO articles (id,king,date,title,classes,refs,names,text,book,calendar)"
                     " VALUES (?,'',?,?,'','','','',?,?)", (aid, date, title, book, cal))
        conn.execute("INSERT INTO title_fts (id, title) VALUES (?,?)", (aid, title))
    conn.commit()
    conn.close()

    store = GraphStore(Path(tmp) / "g.sqlite")
    store.upsert_nodes([Node(id="wd:Q28208", type="org", label="고려", source="wd", start_date="0918")])
    rep = aks_mod2.founding_events(store, nikh.SillokIndex(idx_path), raw_dir=raw)
    made = {m[1]: m[0] for m in rep["made"]}
    check("정본 둘을 겹쳐 세운다 — 이름은 민백 표제, 날짜는 고려사 기사",
          made == {"국자감시": "1031-11-22"}, str(made))
    got = store.conn.execute("SELECT type, label, description FROM nodes WHERE id='aks:E1'").fetchone()
    check("설명은 민백의 정의 한 문장이다 — 기사 제목을 세우지 않는다 (§1-3)",
          tuple(got) == ("event", "국자감시", "국자감에서 치러진 예부시의 예비시험."), str(tuple(got)))
    check("그 시대에 잇는다",
          store.conn.execute("SELECT COUNT(*) FROM edges WHERE src='aks:E1' AND dst='wd:Q28208'"
                             " AND type='from_period'").fetchone()[0] == 1)
    check("고친 값은 편집 계층에 남는다 — 다음 수집이 덮어써도 돌아온다",
          store.conn.execute("SELECT COUNT(*) FROM overrides WHERE key='aks:E1'").fetchone()[0] >= 3)
    check("기사의 해가 항목 연대와 어긋나면 세우지 않는다 — 1286년 경전에 1101년 기사",
          [m[0] for m in rep["mismatched"]] == ["묘법연화경"], str(rep["mismatched"]))
    rep2 = aks_mod2.founding_events(store, nikh.SillokIndex(idx_path), raw_dir=raw)
    check("두 번 돌려도 같은 노드다 — 이름이 이미 있으면 세지 않고 넘긴다",
          rep2["made"] == [] and [c[0] for c in rep2["collided"]] == ["국자감시"], str(rep2["collided"]))
    store.close()


# --- 역할 표 ---------------------------------------------------------------
# 2026-09-05 지적: "정도전은 제1차 왕자의 난을 지휘했다". 인포박스 지휘관1 이
# 그대로 라벨이 됐고 † 는 버려졌다. 표가 판정하고 표식이 결말을 말한다.
print("\n[역할 표 — 정변·난·사화의 편은 역할이 아니다]")
if True:
    import json as _json
    import tempfile as _tf

    from histgraph import overrides as ov_mod
    from histgraph.sources import infobox as _ib

    # 인포박스 표식·편 이름
    wt = ("{{전쟁 정보\n|분쟁 = 제1차 왕자의 난\n|교전국1 = 이방석 지지파\n|교전국2 = 이방원 지지파\n"
          "|지휘관1 = [[의안대군 (1382년)|이방석]][[작전 중 사망|†]]<br />[[정도전]][[작전 중 사망|†]]\n"
          "|지휘관2 = [[태종 (조선)|정안대군]]<br /> [[하륜]]\n}}")
    fates, sides = _ib.parse_infobox_marks(wt)
    check("† 는 사망 표식이다", fates == {("지휘관1", "의안대군 (1382년)"): "사망", ("지휘관1", "정도전"): "사망"}, str(fates))
    check("교전국 이름을 편 번호로 준다", sides == {1: "이방석 지지파", 2: "이방원 지지파"}, str(sides))
    check("{{KIA}}·{{처형}}·☠·‡", _ib.link_fates("[[최경회]]{{KIA}}<br />[[박포]]{{처형}}<br />[[이괄]] [[암살|☠]]<br />[[회안대군]] [[귀양|‡]]<br />[[김충선]]")
          == {"최경회": "사망", "박포": "처형", "이괄": "피살", "회안대군": "귀양"})
    check("그림 링크·감싸는 틀·목록 틀·같은 줄의 다음 칸·연도 주석을 벗긴다",
          _ib.side_names("{{전쟁 정보\n|교전국1 = {{가운데|[[파일:Flag.svg|65px]]<br>[[조선]]}}\n|교전국2 = 홍경래 반란군 ||지휘관1 = [[순조]]\n|지휘관1 = [[이순신]]\n}}") == {1: "조선", 2: "홍경래 반란군"}
          and _ib.side_names("{{전쟁 정보\n|교전국1 = {{기호 없는 목록 |{{국기나라 그림|a.svg}} [[중화민국]] |[[소련]]}}\n|교전국2 = {{국기그림|미국|1912}} [[미군정]] <small>(-1948)</small>\n|지휘관1 = [[장제스]]\n}}") == {1: "중화민국·소련", 2: "미군정"})
    check("한글 없는 편 이름은 화면에 세우지 않는다", _ib.side_names("{{전쟁 정보\n|교전국1 = {{국기나라|PRK}}\n|교전국2 = [[유엔]]\n|지휘관1 = [[김일성]]\n}}") == {2: "유엔"})
    check("국기 그림 틀은 버리고 국기 틀은 이름만", _ib.side_names("{{전쟁 정보\n|교전국1 = {{국기나라 그림|Flag.svg}} [[조선]]<br />{{국기|청나라}}\n|교전국2 = {{중앙|[[도요토미 정권]]}}\n|지휘관1 = [[고종]]\n}}")
          == {1: "조선·청나라", 2: "도요토미 정권"})

    store = GraphStore(":memory:")
    store.upsert_nodes([
        Node(id="wd:JD", type="person", label="정도전", source="wd", start_date="1342", end_date="1398"),
        Node(id="wd:TJ", type="person", label="태종", source="wd", start_date="1367", end_date="1422"),
        Node(id="wd:KY", type="person", label="김응용", source="wd", start_date="1941"),
        Node(id="wd:COUP", type="event", label="제1차 왕자의 난", source="wd", start_date="1398"),
        Node(id="wd:SEA", type="event", label="옥포 해전", source="wd", start_date="1592"),
    ])
    part = lambda s, d, src, label=None, props=None: Edge(src=s, dst=d, type="participated_in", source=src, label=label, confidence=0.9, props=props or {})
    store.upsert_edges([
        part("wd:JD", "wd:COUP", "kowiki:infobox", "지휘관", {"side": 1, "fate": "사망"}),
        part("wd:JD", "wd:COUP", "wd"),
        part("wd:TJ", "wd:COUP", "kowiki:infobox", "지휘관", {"side": 2}),
        part("wd:KY", "wd:COUP", "extract", None, {"evidence": "김응용이 반란군을 설득했다"}),
        part("wd:TJ", "wd:SEA", "wd"),
    ])
    left = roles_mod.unjudged(store)
    check("정변에 역할 없이 선 참여를 센다 (전투는 안 센다)", sorted(p for p, _, _, _ in left) == ["김응용", "정도전", "태종"], str(left))

    with _tf.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as fh:
        fh.write("# 표\nwd:JD\twd:COUP\t피해\t이방원 측에 살해되었다\nwd:TJ\twd:COUP\t주도\t난을 일으켰다\n"
                 "wd:KY\twd:COUP\t삭제\t동명이인\nwd:NOPE\twd:COUP\t가담\t없는 노드\n")
        path = Path(fh.name)
    table = roles_mod.load_table(path)
    check("표를 읽는다", len(table) == 4 and table[0].role == "피해")
    rep = roles_mod.apply_table(store, table)
    rows = lambda s, d: [tuple(r) for r in store.conn.execute(
        "SELECT type, source, label, json_extract(props,'$.role'), json_extract(props,'$.fate') FROM edges WHERE src=? AND dst=? ORDER BY source", (s, d))]
    check("피해는 모든 소스가 관련으로 물러나고 라벨·역할이 붙는다",
          rows("wd:JD", "wd:COUP") == [("related_to", "kowiki:infobox", "피해", "피해", "사망"), ("related_to", "wd", "피해", "피해", None)], str(rows("wd:JD", "wd:COUP")))
    check("주도는 참여로 남고 라벨이 바뀐다", rows("wd:TJ", "wd:COUP") == [("participated_in", "kowiki:infobox", "주도", "주도", None)], str(rows("wd:TJ", "wd:COUP")))
    check("삭제는 엣지를 지운다", rows("wd:KY", "wd:COUP") == [] and rep.deleted == 1)
    check("없는 노드는 세어 보고만 한다", [r.person for r in rep.absent] == ["wd:NOPE"] and rep.applied == 3 and rep.moved == 2)
    check("씌운 뒤에는 역할 없는 참여가 없다", roles_mod.unjudged(store) == [], str(roles_mod.unjudged(store)))
    check("표의 판정은 모델 후보에서 빠진다",
          all(_json.loads(r["props"])["role_origin"] == "roles" for r in store.conn.execute("SELECT props FROM edges WHERE dst='wd:COUP'")))
    # 재수집이 participated_in 을 되살려도 편집 계층이 다시 지우고, 표의 역할이 다시 씌워진다
    store.upsert_edges([part("wd:JD", "wd:COUP", "wd"), part("wd:KY", "wd:COUP", "extract"), part("wd:TJ", "wd:COUP", "kowiki:infobox", "지휘관", {"side": 2})])
    check("재수집이 되살린 피해자의 참여는 다시 사라진다", rows("wd:JD", "wd:COUP") == [("related_to", "kowiki:infobox", "피해", "피해", "사망"), ("related_to", "wd", "피해", "피해", None)], str(rows("wd:JD", "wd:COUP")))
    check("재수집이 되살린 동명이인은 다시 지워진다", rows("wd:KY", "wd:COUP") == [])
    check("재수집이 지휘관으로 되돌려도 표의 주도가 이긴다", rows("wd:TJ", "wd:COUP") == [("participated_in", "kowiki:infobox", "주도", "주도", None)], str(rows("wd:TJ", "wd:COUP")))
    check("두 번 씌워도 같다", roles_mod.apply_table(store, table).moved == 0 and len(rows("wd:JD", "wd:COUP")) == 2)
    # 2026-09-07 지적: 피해로 옮긴 정도전이 사건 상세·그래프에서 '관련'에 묻혀 사라진 것처럼 보였다.
    # 역할이 선의 이름이고 묶음의 머리다. 참여 바로 뒤에 선다.
    from histgraph import pages as _pg
    from histgraph.server import GraphAPI as _API
    api = _API(store)
    ev = api.node("wd:COUP")
    heads = [(r["other"]["label"], r["type"], r["edge_label"]) for r in ev["relations"]]
    check("피해는 참여 바로 뒤에 선다", heads[:2] == [("태종", "participated_in", "주도"), ("정도전", "related_to", "피해")], str(heads))
    check("정적 페이지의 묶음 머리도 역할이다", [h for h, _ in _pg._groups(ev["relations"])][:2] == ["주도", "피해"])
    g = api.graph("wd:COUP")
    labels = {(e["s"], e["t"]): e["label"] for e in g["edges"]}
    # 2026-09-07 전수 조사: '삭제'로 적어 정말 끊어 놓은 쌍이 114 였고 그중
    # 43 은 관계가 참인데 '참여'가 아니었을 뿐이었다. 판정을 낮추면 표가 되살린다.
    tbl2 = Path(path.parent / "t2.tsv")
    tbl2.write_text("wd:KY\twd:COUP\t언급\t난 문서가 배경으로 부른 이름이다\n", encoding="utf-8")
    roles_mod.apply_table(store, roles_mod.load_table(tbl2))
    check("판정을 낮추면 지웠던 관계가 되살아난다",
          rows("wd:KY", "wd:COUP") == [("related_to", "roles", "언급", "언급", None)], str(rows("wd:KY", "wd:COUP")))
    check("되살린 관계의 근거는 표의 근거 칸이다",
          _json.loads(store.conn.execute("SELECT props FROM edges WHERE src='wd:KY'").fetchone()["props"])["evidence"]
          == "난 문서가 배경으로 부른 이름이다")
    # '단체' — 추출이 단체를 인물로 세운 노드. 관계는 참이고 타입이 틀렸다.
    store.upsert_nodes([Node(id="ex:person:적군", type="person", label="적군", source="extract")])
    tbl3 = Path(path.parent / "t3.tsv")
    tbl3.write_text("ex:person:적군\twd:COUP\t단체\t추출이 단체를 인물로 세웠다\n", encoding="utf-8")
    roles_mod.apply_table(store, roles_mod.load_table(tbl3))
    check("단체 판정은 타입을 고치고 참여를 세운다",
          store.conn.execute("SELECT type FROM nodes WHERE id='ex:person:적군'").fetchone()[0] == "org"
          and rows("ex:person:적군", "wd:COUP") == [("participated_in", "roles", None, None, None)],
          str(rows("ex:person:적군", "wd:COUP")))
    check("고친 타입은 편집 계층에 남는다",
          store.conn.execute("SELECT value FROM overrides WHERE target='node' AND key='ex:person:적군' AND field='type'").fetchone()[0] == '"org"')
    store.upsert_nodes([Node(id="ex:person:적군", type="person", label="적군", source="extract")])
    ov_mod.reapply(store, node_ids=["ex:person:적군"])
    check("수집이 인물로 되돌려도 편집 계층이 다시 단체로 세운다",
          store.conn.execute("SELECT type FROM nodes WHERE id='ex:person:적군'").fetchone()[0] == "org")
    tbl2.unlink(); tbl3.unlink()
    check("그래프의 선 이름이 '관련'이 아니라 '피해'다", labels.get(("wd:JD", "wd:COUP")) == "피해" and labels.get(("wd:TJ", "wd:COUP")) == "주도", str(labels))
    bad = Path(path.parent / "bad.tsv"); bad.write_text("wd:JD\twd:COUP\t영웅\t근거\n", encoding="utf-8")
    try:
        roles_mod.load_table(bad); check("모르는 역할은 거부한다", False)
    except roles_mod.RolesTableError:
        check("모르는 역할은 거부한다", True)
    path.unlink(); bad.unlink()
    store.close()

# 2026-09-07 전수 조사: `set_in`·`adapted_from`·`about` 에 문장 규칙이 없어
# 화면이 "성균관 스캔들 → 제도 · 주제" 라는 화살표를 그리고 있었다. 관문을
# 걸어 둔다 — 새 엣지 타입은 사람이 읽는 말도 같이 들고 와야 한다.
print("\n[관문: 모든 엣지 타입에 문장 규칙이 있다]")
if True:
    import re as _re

    from histgraph.ontology import EDGE_TYPES as _ET

    _js = Path("web/src/lib/relations.js").read_text(encoding="utf-8")
    _body = _js[_js.index("export const SENTENCE = {"):]
    _known = set(_re.findall(r"^  (\w+):", _body, _re.M))
    _missing = [t for t in _ET if t not in _known]
    check("EDGE_TYPES 전부에 SENTENCE 규칙이 있다", not _missing, f"빠진 것: {_missing}")
    # 화면과 정적 페이지가 같은 이름을 쓴다
    from histgraph import pages as _pgs
    from histgraph.server import LABEL_HEADS as _LH
    _js_heads = set(_re.findall(r"'([^']+)'", _js[_js.index("export const LABEL_HEADS"):_js.index("export function relHead")]))
    check("라벨 머리 표가 서버·화면·정적 페이지에서 같다", _LH == _pgs.LABEL_HEADS, f"{sorted(_LH ^ _pgs.LABEL_HEADS)}")


# ---------------------------------------------------------------------------
print("\n[개인 역사 — life]")
with tempfile.TemporaryDirectory() as tmp:
    from histgraph import life as life_mod
    from histgraph.server import GraphAPI as _LifeAPI, dispatch as _life_dispatch

    # 지시문의 식별자는 빠짐없이 한국어 이름이 있어야 한다 — 화면에 영어가 뜨는 자리다.
    prompt = life_mod.system_prompt()
    core = prompt[prompt.index("# Node 타입"):prompt.index("# Person Node 구조")]
    node_types = {ln.strip() for ln in core.splitlines() if re.fullmatch(r"[A-Z][a-z][A-Za-z]+", ln.strip())}
    node_types |= set(re.findall(r'type:"([A-Za-z]+)"', prompt))
    node_types |= set(re.findall(r"^## [^(\n]+\(([A-Z][A-Za-z]+)\)", prompt, re.M))
    check("지시문의 노드 타입 전부에 한국어 이름이 있다 (%d)" % len(node_types),
          node_types <= set(life_mod.NODE_TYPE_KO) and len(node_types) >= 38, str(node_types - set(life_mod.NODE_TYPE_KO)))
    check("이름표는 전부 한글", all(re.search(r"[가-힣]", v) for v in
          [*life_mod.NODE_TYPE_KO.values(), *life_mod.EDGE_TYPE_KO.values(), *life_mod.IMPACT_KO.values()]))
    check("스키마의 타입·관계 enum 이 표와 같다",
          set(life_mod.SCHEMA["properties"]["nodes"]["items"]["properties"]["type"]["enum"]) == set(life_mod.NODE_TYPE_KO)
          and set(life_mod.SCHEMA["properties"]["edges"]["items"]["properties"]["type"]["enum"]) == set(life_mod.EDGE_TYPE_KO))
    class _Fake:
        model = "fake"
        def complete_json(self, system, user, schema, max_tokens=None):
            self.got = (system, user, schema, max_tokens)
            return {"nodes": []}
    fake = _Fake()
    check("analyze 는 지시문·스키마·넉넉한 상한으로 묻는다",
          life_mod.analyze("이야기", fake) == {"nodes": []} and fake.got[0] == prompt
          and fake.got[2] is life_mod.SCHEMA and fake.got[3] >= 8000)
    check("사용자 프롬프트가 그래프의 사건 이름을 보인다",
          "대한민국의 IMF 구제금융 요청(1997)" in life_mod.build_user("이야기", anchors=[{"label": "대한민국의 IMF 구제금융 요청", "year": 1997}]))

    # 날짜 — 지어내지 않는다
    check("'2000년대 초반' 은 2000~2003", life_mod.parse_when("2000년대 초반") == (2000, 2003, "decade"))
    check("'20대 초반' 은 생년 없이는 모른다", life_mod.parse_when("20대 초반") == (None, None, "age"))
    check("'20대 초반' + 생년 1985", life_mod.parse_when("20대 초반", 1985) == (2005, 2008, "age"))
    check("ISO 는 exact", life_mod.parse_when("1997-12-03") == (1997, 1997, "exact"))

    raw = {
        "nodes": [
            {"id": "me", "type": "Person", "name": "나", "start_date": "1985-04", "confidence": 1.0},
            {"id": "e1", "type": "Crisis", "name": "아버지 인쇄소 부도", "start_date": "1997-12", "importance_score": 14, "confidence": 1.0},
            {"id": "e2", "type": "TurningPoint", "name": "서울 이사", "start_date": "20대 초반", "confidence": 0.9},
            {"id": "x", "type": "Alien", "name": "외계", "confidence": 1.0},
            {"id": "en", "type": "Book", "name": "Cosmos", "description": "Science book", "confidence": 1.0},
        ],
        "edges": [
            {"source": "e1", "target": "e2", "type": "caused", "confidence": 1.0},
            {"source": "me", "target": "x", "type": "met", "confidence": 1.0},
            {"source": "me", "target": "e1", "type": "flew", "confidence": 1.0},
        ],
        "timeline": [
            {"event_id": "e1", "life_stage": "초등학교"},
            {"event_id": "e2", "life_stage": "없는 단계", "age": 13},
            {"event_id": "ghost", "life_stage": "대학"},
        ],
        "historical_connections": [
            {"personal_event": "e1", "historical_event": "대한민국의 IMF 구제금융 요청", "year": 1997, "impact_type": "direct", "description": "외환위기", "confidence": 1.0},
            {"personal_event": "e1", "historical_event": "없는 사건", "year": None, "impact_type": "뭐", "description": "…", "confidence": 0.5},
        ],
        "influence_ranking": {"인물": {"node": "me", "influence_score": 9, "reason": "…"}},
        "follow_up_questions": ["q%d" % i for i in range(9)],
    }
    payload, notes = life_mod.validate(raw)
    ids = {n["id"] for n in payload["nodes"]}
    check("모르는 타입은 버리고 적는다", "x" not in ids and any("Alien" in n for n in notes), str(notes))
    check("양끝 없는 관계·모르는 관계는 버린다",
          [e["type"] for e in payload["edges"] if e["type"] != "experienced"] == ["caused"], str(payload["edges"]))
    check("버려서 섬이 된 사건은 주인공에게 잇는다 (me -flew-> e1 이 사라진 자리)",
          {e["target"] for e in payload["edges"] if e["type"] == "experienced" and e["source"] == "me"} == {"e1", "e2"},
          str(payload["edges"]))
    check("점수는 1~10 로 자른다", next(n for n in payload["nodes"] if n["id"] == "e1")["importance_score"] == 10)
    check("주인공과 생년", payload["subject"] == {"id": "me", "name": "나", "birth_year": 1985})
    e2 = next(n for n in payload["nodes"] if n["id"] == "e2")
    check("'20대 초반' 이 생년으로 풀린다", (e2["year"], e2["end_year"], e2["precision"]) == (2005, 2008, "age"), str(e2))
    tl = {t["event_id"]: t for t in payload["timeline"]}
    check("연표: 노드의 해를 받고 나이를 센다", tl["e1"]["year"] == 1997 and tl["e1"]["age"] == 12, str(tl["e1"]))
    check("연표: 나이만 있으면 생년으로 푼다 · 모르는 단계는 비운다",
          tl["e2"]["year"] == 1998 and tl["e2"]["life_stage"] is None, str(tl["e2"]))
    check("연표: 노드에 없는 사건은 버린다", "ghost" not in tl)
    check("영향 종류가 표 밖이면 '가능성'", payload["historical_connections"][1]["impact_type"] == "possible")
    check("순위표: 범주 → 항목 꼴도 목록으로", payload["influence_ranking"]["items"][0]["category"] == "인물")
    check("물음은 다섯까지", len(payload["follow_up_questions"]) == 5)
    check("한글 없는 이름은 메모하지 않는다 (2026-09-08 — nullSpace 는 본인의 회사 이름)",
          not any("한글" in n for n in notes), str(notes))
    check("구간은 생년부터 오늘까지", life_mod.span(payload, datetime.date(2026, 9, 7)) == (1985, 2026))

    # 인물의 생몰년은 원문이 말한 것만 (2026-09-08 사용자: "인물들의 출생연도 나이는
    # 사용자가 입력하지 않은 이상 추측해서 명시 하지마"). 실측: 모델이 친구에게
    # 주인공과 같은 생일을 달았고, 주인공의 생일도 이야기는 해만 말했다.
    story = ("나는 1982년에 태어났다. 1997년 잠실고등학교에 들어갔고 1학년 때 김일권을 만났다.\n"
             "아버지는 1955년 3월 2일에 태어나셨다.")
    people = {
        "nodes": [
            {"id": "me", "type": "Person", "name": "나", "start_date": "1982-01-01", "confidence": 1.0},
            {"id": "dad", "type": "FamilyMember", "name": "아버지", "start_date": "1955", "confidence": 1.0},
            {"id": "kim", "type": "Person", "name": "김일권", "start_date": "1982-01-01", "confidence": 0.9},
        ],
        "edges": [], "historical_connections": [],
        "timeline": [{"event_id": "kim", "life_stage": "출생", "year": 1982},
                     {"event_id": "dad", "life_stage": "출생", "year": 1955}],
    }
    gated, gnotes = life_mod.validate(people, text=story)
    got = {n["id"]: (n.get("start_date"), n.get("year")) for n in gated["nodes"]}
    check("주인공의 생일은 이야기가 말한 만큼만 (1982-01-01 → 1982)", got["me"] == ("1982", 1982), str(got))
    check("이야기가 그 사람에 대해 말한 생년은 남는다", got["dad"] == ("1955-03-02", 1955), str(got))
    # 생년은 비우되 **그 사람이 내 삶에 들어온 해**는 남는다 (year) — 이야기가
    # '1997년 … 1학년 때 김일권을 만났다' 고 말했다. 화면은 이 해를 생년으로 읽지
    # 않는다: 날짜 줄도 연표도 start_date 를 본다 (life.js dateSaid).
    check("이야기가 말하지 않은 남의 생년은 비운다", got["kim"] == (None, 1997), str(got))
    check("뺀 것을 적어 준다", any("김일권" in n for n in gnotes), str(gnotes))
    check("생년이 없어진 사람은 연표에서도 내린다 (그 자리가 곧 '0세 · 출생'이다)",
          [t["event_id"] for t in gated["timeline"]] == ["dad"], str(gated["timeline"]))
    check("주인공의 생년은 남는다 — 연표가 여기서 선다", gated["subject"]["birth_year"] == 1982, str(gated["subject"]))
    check("원문을 모르면 재지 않는다",
          {n["id"]: n.get("start_date") for n in life_mod.validate(people)[0]["nodes"]}["kim"] == "1982-01-01")
    # 옛 그래프도 부팅 때 같은 관문을 지난다 (server 가 원문 파일을 같이 준다)
    old_doc = {"nodes": [dict(n) for n in people["nodes"]], "edges": [], "timeline": [],
               "subject": {"id": "me", "name": "나", "birth_year": 1982}}
    for n in old_doc["nodes"]:
        n["year"], n["precision"] = life_mod.parse_when(n["start_date"])[0], "exact"
    refined = life_mod.refine(old_doc, text=story)
    kim = next(n for n in refined["nodes"] if n["id"] == "kim")
    check("refine 도 원문을 알면 지어낸 생년을 뺀다", (kim["start_date"], kim["year"]) == (None, 1997), str(kim))

    # 해를 안 말한 만남 — 나이와 시절로 셈해서 **사건으로 세운다** (2026-09-09 사용자:
    # "'만20세', '공익생활'이라고 언급 했으면 이미 존재하는 역사를 보면 충분히 유추 할
    # 수 있었는데 그걸 못했어"). 실측한 모델 답 그대로다: 사람 노드 하나와, 옛 그래프의
    # 공익근무 사건을 가리키는 관계.
    met_base = {
        "subject": {"id": "me", "name": "나", "birth_year": 1982},
        "nodes": [
            {"id": "me", "type": "Person", "name": "나", "start_date": "1982-02-27",
             "year": 1982, "precision": "exact", "confidence": 1.0},
            {"id": "duty", "type": "PersonalEvent", "name": "천호3동 사무소 공익요원 근무 시작",
             "start_date": "2002-04", "year": 2002, "precision": "year", "confidence": 1.0},
            {"id": "out", "type": "PersonalEvent", "name": "소집해제", "start_date": "2004",
             "year": 2004, "precision": "year", "confidence": 1.0},
        ],
        "edges": [{"source": "me", "target": "duty", "type": "experienced", "confidence": 1.0},
                  {"source": "me", "target": "out", "type": "experienced", "confidence": 1.0}],
        "timeline": [{"event_id": "duty", "life_stage": "군복무", "year": 2002, "age": 20},
                     {"event_id": "out", "life_stage": "군복무", "year": 2004, "age": 22}],
        "historical_connections": [], "stories": [],
    }
    met_text = "공익생활을 하던 시절 만20살때 여자친구를 만났고, 이름은 정혜림 이었다."
    met_raw = {
        "nodes": [{"id": "gf", "type": "Person", "name": "정혜림", "start_date": "2002-01-01",
                   "confidence": 0.7}],
        "edges": [{"source": "me", "target": "gf", "type": "met", "confidence": 1.0},
                  {"source": "gf", "target": "duty", "type": "met", "confidence": 1.0}],
        "timeline": [{"event_id": "duty", "life_stage": "군복무", "age": 20}],
    }
    check("'공익생활'도 군복무로 읽는다 (2026-09-09)", bool(life_mod.MILITARY.search("공익생활을 하던 시절")))
    check("이야기의 '만20살때' 를 생년으로 셈한다",
          life_mod.year_from_story(met_text, "정혜림", 1982, {}) == (2002, "age"),
          str(life_mod.year_from_story(met_text, "정혜림", 1982, {})))
    check("이야기가 그 사람을 안 부르면 셈하지 않는다",
          life_mod.year_from_story(met_text, "김일권", 1982, {}) == (None, ""))
    met_val, met_notes = life_mod.validate(met_raw, subject=met_base["subject"], text=met_text,
                                           known=life_mod.known_ids(met_base))
    check("옛 그래프의 id 를 관계의 끝으로 받는다 (없으면 '양끝이 없다'고 버려졌다)",
          {(e["source"], e["target"]) for e in met_val["edges"]} >= {("gf", "duty")},
          str(met_val["edges"]) + str(met_notes))
    met_out, met_stats = life_mod.merge(met_base, met_val, met_text)
    ev = next((n for n in met_out["nodes"] if n["id"] == "met_gf"), None)
    check("만난 일이 사건으로 선다 — 사람은 연표의 점이 아니다",
          ev is not None and (ev["type"], ev["name"], ev["year"]) == ("PersonalEvent", "정혜림을 만남", 2002),
          str(ev))
    check("만남의 설명은 이야기가 그 사람을 부른 문장 그대로다",
          ev is not None and "만20살때" in str(ev.get("description")), str(ev))
    check("만남은 나와 그 사람 둘 다에 이어진다",
          {(e["source"], e["target"], e.get("role")) for e in met_out["edges"]}
          >= {("me", "met_gf", "만남"), ("gf", "met_gf", "함께")}, str(met_out["edges"]))
    check("'그 시절에 만났다' 는 그 사건을 겪은 것이 아니라 그 사이의 일이다 (during)",
          {(e["source"], e["target"], e["type"]) for e in met_out["edges"]}
          >= {("met_gf", "duty", "during")}
          and not any(e["source"] == "gf" and e["target"] == "duty" for e in met_out["edges"]),
          str(met_out["edges"]))
    met_tl = {t["event_id"]: t for t in met_out["timeline"]}
    check("만남이 연표에 서고 단계는 앞뒤에서 온다 (공익 시절의 만남은 '군복무')",
          "met_gf" in met_tl and (met_tl["met_gf"]["year"], met_tl["met_gf"]["age"],
                                  met_tl["met_gf"]["life_stage"]) == (2002, 20, "군복무"),
          str(met_tl.get("met_gf")))
    check("사람은 연표에 서지 않는다 (그 자리가 곧 생년이 된다)", "gf" not in met_tl, str(list(met_tl)))
    check("refine 이 세운 것도 '더한 수'에 센다", met_stats["nodes"] >= 1, str(met_stats))
    check("더한 노드의 id 를 알려 준다 — 화면이 그리로 간다",
          "met_gf" in met_stats["ids"] and "gf" in met_stats["ids"], str(met_stats["ids"]))
    check("두 번 돌려도 만남은 하나다",
          len([n for n in life_mod.refine(met_out, met_text)["nodes"] if n["id"] == "met_gf"]) == 1)

    # '신구대학 시절' — 이야기가 **이미 선 노드의 이름**으로 때를 말한다 (2026-09-09
    # 사용자: "이미 내 역사에 신구대학 시절이 이미 있는데 이걸 이용하지 못하네").
    # 해도 나이도 학년도 없는 문장이라 이름이 마지막 근거다. 만든 모임도 사건이다.
    club_text = "신구대학 시절 만난 친구들은 최근호, 석민혁, 이수혁이고 우리는 a-club이란 모임도 만들었어."
    check("이야기가 부른 이름이 해를 빌려 준다",
          life_mod.year_from_story(club_text, "최근호", 1982, {}, {"신구대학": 2000}) == (2000, "year"))
    check("이름이 여럿 걸리면 긴 쪽이 이긴다",
          life_mod.year_from_story("신구대학 컴퓨터정보학과 시절 최근호를 만났어", "최근호", 1982, {},
                                   {"신구대학": 2000, "신구대학 컴퓨터정보학과": 1999}) == (1999, "year"))
    check("이야기가 스스로 말한 해가 이름을 이긴다",
          life_mod.year_from_story("1998년에 신구대학에서 최근호를 만났어", "최근호", 1982, {},
                                   {"신구대학": 2000}) == (1998, "year"))
    check("때의 닻에 사람은 넣지 않는다 (그 사람의 해가 이 일의 해는 아니다)",
          life_mod.time_anchors([{"id": "p", "type": "Person", "name": "김일권", "year": 1997},
                                 {"id": "s", "type": "School", "name": "신구대학", "year": 2000}],
                                None) == {"신구대학": 2000})
    club = life_mod.refine({
        "subject": {"id": "me", "name": "나", "birth_year": 1982},
        "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                  {"id": "col", "type": "School", "name": "신구대학", "year": 2000},
                  {"id": "entry", "type": "PersonalEvent", "name": "신구대학 입학", "year": 2000},
                  {"id": "f1", "type": "Person", "name": "최근호", "confidence": 1.0},
                  {"id": "club", "type": "Organization", "name": "a-club", "confidence": 1.0}],
        "edges": [{"source": "me", "target": "entry", "type": "experienced", "confidence": 1.0},
                  {"source": "me", "target": "f1", "type": "met", "confidence": 1.0},
                  {"source": "me", "target": "club", "type": "member_of", "confidence": 1.0},
                  {"source": "f1", "target": "club", "type": "member_of", "confidence": 1.0}],
        "timeline": [{"event_id": "entry", "life_stage": "대학", "year": 2000}]}, club_text)
    club_by = {n["id"]: n for n in club["nodes"]}
    check("'신구대학 시절' 이 사람의 해가 된다", club_by["f1"].get("year") == 2000, str(club_by["f1"]))
    check("만든 모임도 사건으로 선다",
          club_by.get("made_club", {}).get("name") == "a-club 결성"
          and club_by["made_club"]["year"] == 2000, str(club_by.get("made_club")))
    check("같이 만든 사람은 '함께' 로 선다",
          {(e["source"], e.get("role")) for e in club["edges"] if e["target"] == "made_club"}
          == {("me", "결성"), ("f1", "함께")}, str([e for e in club["edges"] if e["target"] == "made_club"]))
    club_tl = {t["event_id"]: t for t in club["timeline"]}
    check("같은 해의 앞 항목에서 단계를 잇는다",
          club_tl["made_club"]["life_stage"] == "대학" and club_tl["met_f1"]["life_stage"] == "대학",
          str(club["timeline"]))
    made_again = life_mod.refine(club, club_text)
    check("두 번 돌려도 만든 일은 하나다",
          len([n for n in made_again["nodes"] if n["id"] == "made_club"]) == 1)
    check("들어간 것은 만든 것이 아니다 (가입은 세우지 않는다)",
          "made_club2" not in {n["id"] for n in life_mod.refine({
              "subject": {"id": "me", "name": "나", "birth_year": 1982},
              "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                        {"id": "club2", "type": "Organization", "name": "산악회", "year": 2010}],
              "edges": [{"source": "me", "target": "club2", "type": "member_of", "confidence": 1.0}],
              "timeline": []}, "2010년에 산악회에 들어갔어.")["nodes"]})

    # **모델이 달라져도 같은 화면이 나와야 한다** (2026-09-09 사용자: "llm 모델이
    # 달라져도 똑같이 적용할 수 있는 하네스지?"). 모델마다 답하는 버릇이 다르다 —
    # 양끝을 id 로 적기도 이름으로 적기도 하고(무료 모델 실측), 날짜를 지어내기도
    # 한다. 규칙은 모델의 답이 아니라 **이야기**에 걸려 있으므로 셋 다 같아야 한다.
    def _club_base():
        return {"subject": {"id": "me", "name": "나", "birth_year": 1982},
                "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982",
                           "year": 1982, "precision": "year", "confidence": 1.0},
                          {"id": "col", "type": "School", "name": "신구대학", "year": 2000,
                           "precision": "year", "confidence": 1.0},
                          {"id": "entry", "type": "PersonalEvent", "name": "신구대학 입학",
                           "start_date": "2000", "year": 2000, "precision": "year", "confidence": 1.0}],
                "edges": [{"source": "me", "target": "entry", "type": "experienced", "confidence": 1.0},
                          {"source": "me", "target": "col", "type": "studied_at", "confidence": 1.0}],
                "timeline": [{"event_id": "entry", "life_stage": "대학", "year": 2000, "age": 18}],
                "historical_connections": [], "stories": [{"at": "2026-09-09", "text": "2000년에 신구대학에 들어갔어."}]}

    def _club_run(raw):
        base = _club_base()
        val, _ = life_mod.validate(raw, subject=base["subject"], text=club_text,
                                   known=life_mod.known_ids(base))
        out, _ = life_mod.merge(base, val, club_text)
        life_mod.refine(out, "2000년에 신구대학에 들어갔어.\n\n" + club_text)
        return sorted((n["name"], n.get("year")) for n in out["nodes"]
                      if n["id"].startswith(("met_", "made_")))

    _want = [("a-club 결성", 2000), ("석민혁을 만남", 2000), ("이수혁을 만남", 2000), ("최근호를 만남", 2000)]
    _people = [("f1", "최근호"), ("f2", "석민혁"), ("f3", "이수혁")]
    # (가) 양끝을 id 로 적는 모델
    check("모델이 id 로 이어도", _club_run({
        "nodes": [*({"id": i, "type": "Person", "name": n, "confidence": 1.0} for i, n in _people),
                  {"id": "club", "type": "Organization", "name": "a-club", "confidence": 1.0}],
        "edges": [*({"source": "me", "target": i, "type": "met", "confidence": 1.0} for i, _ in _people),
                  *({"source": i, "target": "club", "type": "member_of", "confidence": 1.0} for i, _ in _people),
                  {"source": "me", "target": "club", "type": "member_of", "confidence": 1.0}],
        "timeline": []}) == _want)
    # (나) 양끝을 **이름**으로 적는 모델 — 주인공을 '나' 라고 부른다
    check("모델이 이름으로 이어도 (주인공을 '나' 라 불러도)", _club_run({
        "nodes": [*({"id": f"p{k}", "type": "Person", "name": n, "confidence": 1.0}
                    for k, (_, n) in enumerate(_people)),
                  {"id": "o1", "type": "Community", "name": "a-club", "confidence": 1.0}],
        "edges": [*({"source": "나", "target": n, "type": "friend_of", "confidence": 1.0} for _, n in _people),
                  {"source": "나", "target": "a-club", "type": "member_of", "confidence": 1.0}],
        "timeline": []}) == _want)
    # (다) 날짜를 지어내는 모델 — 이야기에 없는 해는 단체에서도 비운다
    check("모델이 날짜를 지어내도 (이야기가 말한 해가 이긴다)", _club_run({
        "nodes": [*({"id": i, "type": "Person", "name": n, "start_date": "1995-01-01", "confidence": 0.6}
                    for i, n in _people),
                  {"id": "club", "type": "Organization", "name": "a-club", "start_date": "1995", "confidence": 0.6}],
        "edges": [*({"source": "me", "target": i, "type": "met", "confidence": 1.0} for i, _ in _people),
                  {"source": "me", "target": "club", "type": "member_of", "confidence": 1.0}],
        "timeline": []}) == _want)

    # 단계는 뒤로 가지 않는다 — 스무 살에 '초등학교'인 삶은 없다. 모델은 사람 노드의
    # 연표 항목에 단계를 아무렇게나 적는다 (실측: 2002년 항목이 '초등학교').
    back = life_mod.refine({
        "subject": {"id": "me", "name": "나", "birth_year": 1982},
        "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                  {"id": "a", "type": "PersonalEvent", "name": "대학 입학", "year": 2000},
                  {"id": "b", "type": "PersonalEvent", "name": "첫 출근", "year": 2006},
                  {"id": "c", "type": "PersonalEvent", "name": "이사", "year": 2008}],
        "edges": [], "timeline": [
            {"event_id": "a", "life_stage": "대학", "year": 2000},
            {"event_id": "b", "life_stage": "초등학교", "year": 2006},
            {"event_id": "c", "life_stage": None, "year": 2008}]})
    back_tl = {t["event_id"]: t["life_stage"] for t in back["timeline"]}
    check("뒤로 간 단계는 앞 단계로 되돌린다", back_tl["b"] == "대학", str(back_tl))
    check("뒤가 없으면 빈 단계는 채우지 않는다 (앞만 보고 이으면 십 년 뒤가 '초등학교')",
          back_tl["c"] is None, str(back_tl))

    # 주인공의 생일 — '출생' 사건이 든 날짜가 이긴다 (2026-09-08 사용자: "2월 27일에
    # 태어 났다고 했는데, 왜 헷갈리게 '1982-01-01 · 0세 · 출생' 이라고 써있지").
    born = {"nodes": [
        {"id": "me", "type": "Person", "name": "나", "start_date": "1982-01-01",
         "description": "1982년 2월 27일 서울에서 태어난 사람."},
        {"id": "b1", "type": "Time", "name": "출생", "start_date": "1982-02-27"},
    ], "edges": [{"source": "me", "target": "b1", "type": "experienced", "role": "출생"}],
        "timeline": [{"event_id": "b1", "life_stage": "출생", "age": 0, "date_text": "1982-02-27"},
                     {"event_id": "me", "life_stage": "출생", "age": 0}],
        "subject": {"id": "me", "name": "나"}}
    got = life_mod.refine(born)
    me_n = next(n for n in got["nodes"] if n["id"] == "me")
    check("모델이 적어 둔 1월 1일 대신 '출생' 사건의 날짜를 쓴다",
          (me_n["start_date"], me_n["precision"]) == ("1982-02-27", "exact"), str(me_n))
    check("주인공은 연표의 항목이 아니다 ('출생' 옆에 같은 것이 둘 서지 않는다)",
          [t["event_id"] for t in got["timeline"]] == ["b1"], str(got["timeline"]))
    check("생년은 그대로", got["subject"]["birth_year"] == 1982, str(got["subject"]))
    # 사건이 없으면 설명이 말한 날짜로. 다른 해를 말하는 '출생'은 남의 것이라 안 쓴다.
    only_desc = {"nodes": [dict(born["nodes"][0])], "edges": [], "timeline": [],
                 "subject": {"id": "me", "name": "나"}}
    check("사건이 없으면 설명의 '1982년 2월 27일 … 태어난'",
          life_mod.refine(only_desc)["nodes"][0]["start_date"] == "1982-02-27")
    other = {"nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982-01-01"},
                       {"id": "b1", "type": "Time", "name": "출생", "start_date": "1955-03-02"}],
             "edges": [], "timeline": [], "subject": {"id": "me", "name": "나"}}
    check("해가 다른 '출생'은 남의 것이라 가져오지 않는다",
          life_mod.refine(other)["nodes"][0]["start_date"] == "1982-01-01")

    # 항목의 해와 노드의 날짜가 어긋나면 달까지 아는 날짜가 이긴다 (2026-09-08
    # 사용자: "메탈리카 공연은 1998년 이었어" — 1998-04-24 공연이 항목에는
    # 1997 · 만 15세로 적혀 와 연표의 1997 칸에 '4월'로 섰다).
    off = {"nodes": [
        {"id": "me", "type": "Person", "name": "나", "start_date": "1982-02-27"},
        {"id": "gig", "type": "PersonalEvent", "name": "메탈리카 공연 관람", "start_date": "1998-04-24"},
        {"id": "grad", "type": "PersonalEvent", "name": "중학교 졸업", "start_date": "1997"},
    ], "edges": [],
        "timeline": [{"event_id": "gig", "age": 15, "year": 1997},
                     {"event_id": "grad", "age": 15, "year": 1997}],
        "subject": {"id": "me", "name": "나", "birth_year": 1982}}
    tl = {t["event_id"]: t for t in life_mod.refine(off)["timeline"]}
    check("달까지 아는 날짜가 항목의 해를 이긴다", tl["gig"]["year"] == 1998, str(tl["gig"]))
    check("어림한 나이도 다시 센다", tl["gig"]["age"] == 16, str(tl["gig"]))
    check("해까지만 아는 날짜는 항목의 해를 두고 본다", tl["grad"]["year"] == 1997, str(tl["grad"]))
    check("달만 아는 날짜도 해를 준다", life_mod.month_year("1998-04") == 1998
          and life_mod.month_year("1998") is None and life_mod.month_year(None) is None)

    # 원문은 마지막 단계까지 원문이어야 한다. `refine` 안에서 반복문이 `text` 를
    # 가려(`for text in …`, `text = f"{이름} {설명}"`) 역사 연결의 관문이 원문 대신
    # 남의 노드 설명을 읽고 있었다 — 이야기가 부른 사건까지 통째로 버려졌다.
    grounded_doc = {"nodes": [
        {"id": "me", "type": "Person", "name": "나", "start_date": "1982-02-27"},
        {"id": "kim", "type": "Person", "name": "김일권", "description": "고등학교 1학년 때 만난 친구"},
        {"id": "bust", "type": "Crisis", "name": "아버지 인쇄소 부도", "start_date": "1998"},
    ], "edges": [], "timeline": [{"event_id": "bust", "year": 1998}],
        "subject": {"id": "me", "name": "나", "birth_year": 1982},
        "historical_connections": [{"historical_event": "외환 위기", "personal_event": "bust",
                                    "impact_type": "direct", "year": 1997,
                                    "description": "외환 위기로 일감이 끊겼다"}]}
    kept = life_mod.refine(grounded_doc, text="1998년에 외환 위기로 아버지 인쇄소가 부도났어")
    check("이야기가 부른 역사 연결은 남는다 (원문이 가려지지 않는다)",
          len(kept["historical_connections"]) == 1, str(kept.get("notes")))

    # 함께한 사람 (2026-09-08 사용자: "친구 김일권과 같이 갔다고 분명 말했는데
    # '함께 person_1' 이라고 말하고 있어"). 모델이 participants 에 주인공만 적었다.
    def gig_doc():
        return {"nodes": [
            {"id": "me", "type": "Person", "name": "나", "start_date": "1982-02-27"},
            {"id": "kim", "type": "Person", "name": "김일권"},
            {"id": "gig", "type": "PersonalEvent", "name": "메탈리카 공연 관람",
             "start_date": "1998-04-24", "participants": ["me"]},
            {"id": "ticket", "type": "Memory", "name": "메탈리카 공연 티켓",
             "start_date": "1998-04-24", "participants": ["me"]},
        ], "edges": [{"source": "me", "target": "gig", "type": "experienced"}],
            "timeline": [{"event_id": "gig", "year": 1998}],
            "subject": {"id": "me", "name": "나", "birth_year": 1982},
            "stories": [{"at": "", "text": "1998년 4월 24일 메탈리카 공연을 친구 김일권과 함께 갔어. 티켓도 아직 가지고 있어."}]}
    got = life_mod.refine(gig_doc())
    by_gig = {n["id"]: n for n in got["nodes"]}
    check("이야기 한 문장이 사건과 사람을 함께 부르면 함께한 사람이다",
          "kim" in by_gig["gig"]["participants"], str(by_gig["gig"]["participants"]))
    check("그 사람은 사건에 이어진다 (역할 함께)",
          any(e["source"] == "kim" and e["target"] == "gig" and e["type"] == "experienced"
              and e.get("role") == "함께" for e in got["edges"]), str(got["edges"]))
    check("기억(티켓)은 날짜로 잡지 않는다", "kim" not in by_gig["ticket"]["participants"])
    named = gig_doc()
    named["nodes"][2]["participants"] = ["나", "김일권", "person_9"]
    parts = {n["id"]: n for n in life_mod.refine(named)["nodes"]}["gig"]["participants"]
    check("이름으로 적어 온 것도 노드 id 로 풀고 못 푸는 식별자는 버린다",
          parts == ["me", "kim"], str(parts))
    loose = gig_doc()
    loose["stories"] = [{"at": "", "text": "1998년에 김일권과 자주 만났어. 메탈리카 공연도 갔어."}]
    far = {n["id"]: n for n in life_mod.refine(loose)["nodes"]}["gig"]["participants"]
    check("해만 말한 문장으로는 잇지 않는다", "kim" not in far, str(far))
    check("달까지 아는 날짜만 잰다",
          life_mod.says_date("1998년 4월 24일 공연", "1998-04-24")
          and life_mod.says_date("1998-04-24 공연", "1998-04-24")
          and not life_mod.says_date("1998년에 공연", "1998-04-24")
          and not life_mod.says_date("1998년 공연", "1998"))

    # 섬 — 더하기로 붙인 토막의 사건이 주인공과 안 이어져 따로 떠 있었다
    # (2026-09-08 사용자: "'나'와의 연결이 없이 떨어진 그래프들이 보이는데 왜 따로 떼어둔거지?")
    island = {"nodes": [
        {"id": "me", "type": "Person", "name": "나", "start_date": "1982"},
        {"id": "a1", "type": "PersonalEvent", "name": "30사단 훈련소 입소", "start_date": "2002-03"},
        {"id": "a2", "type": "PersonalEvent", "name": "천호3동 사무소 공익요원 근무 시작", "start_date": "2002-04"},
        {"id": "a3", "type": "PersonalEvent", "name": "소집해제", "start_date": "2004"},
        {"id": "ofc", "type": "Location", "name": "천호3동 사무소"},
        {"id": "dad", "type": "FamilyMember", "name": "아버지"},
        {"id": "bust", "type": "Crisis", "name": "아버지 인쇄소 부도", "start_date": "1997"},
        {"id": "imf", "type": "HistoricalEvent", "name": "IMF 구제금융", "start_date": "1997-12"},
    ], "edges": [
        {"source": "a1", "target": "a2", "type": "led_to", "confidence": 1.0},
        {"source": "a2", "target": "a3", "type": "led_to", "confidence": 1.0},
        {"source": "dad", "target": "bust", "type": "experienced", "confidence": 1.0},
    ], "timeline": [], "subject": {"id": "me", "name": "나", "birth_year": 1982}}
    got = life_mod.refine(island)
    mine = {e["target"] for e in got["edges"] if e["type"] == "experienced" and e["source"] == "me"}
    check("떨어진 사건은 주인공이 겪은 것으로 잇는다", mine == {"a1", "a2", "a3"}, str(mine))
    check("이은 선에도 이름을 단다 (입소·근무 시작·소집해제)",
          {e.get("role") for e in got["edges"] if e["source"] == "me"} == {"입소", "근무 시작", "소집해제"},
          str([e.get("role") for e in got["edges"] if e["source"] == "me"]))
    check("남의 사건은 잇지 않는다 (아버지의 부도)", "bust" not in mine)
    check("세계사 사건도 잇지 않는다 (내가 겪은 것이 아니라 옆에 선 것)", "imf" not in mine)
    check("이름이 불린 곳은 그 사건에 잇는다 (천호3동 사무소)",
          any(e["source"] == "a2" and e["target"] == "ofc" and e["type"] == "at" for e in got["edges"]),
          str(got["edges"]))
    check("한 번 이은 것을 두 번 잇지 않는다", life_mod.link_orphans(got["nodes"], got["edges"], got["nodes"][0]) == 0)

    # 사람이 상세의 '편집'에서 뺀 선은 섬 잇기가 다시 긋지 않는다 (2026-09-09 사용자가
    # 관계를 빼고 완료를 눌렀는데 그대로 서 있었다). 두 결정이 부딪히는 자리에서는
    # 사람이 이긴다 — 한국사 쪽 편집 계층과 같은 규칙.
    import copy as _copy

    cut = _copy.deepcopy(island)
    cut["unlinked"] = ["me>a2|experienced"]
    kept = life_mod.refine(cut)
    check("사람이 뺀 선은 다시 서지 않는다",
          not any(e["source"] == "me" and e["target"] == "a2" for e in kept["edges"]),
          str([(e["source"], e["target"], e["type"]) for e in kept["edges"]]))
    check("뺀 선의 노드는 그대로 있다", any(n["id"] == "a2" for n in kept["nodes"]))
    check("남의 선은 걷지 않는다",
          any(e["source"] == "me" and e["target"] == "a1" for e in kept["edges"]))
    check("방향이 뒤집혀도 같은 선으로 본다",
          life_mod.drop_unlinked([{"source": "a", "target": "b", "type": "met"}], ["b>a|met"]) == 1)
    check("같은 두 끝의 다른 관계는 남는다",
          life_mod.drop_unlinked([{"source": "a", "target": "b", "type": "caused"}], ["a>b|led_to"]) == 0)

    # 가족은 이야기가 호칭으로 말한다 (2026-09-08 사용자: "왜 엄마라고 분명히 말했고
    # 엄마는 매우 중요한 사람인데 그래프에서 나와 엄마 사이에 엣지를 그리지 않았지?").
    # 실측: 더한 토막의 답이 person_mother → person_1 을 적었는데 주인공 노드가 새 답에
    # 없어(옛 그래프에 있다) validate 가 "양끝이 없다"고 버렸고, 부팅 refine 은 이름
    # 문장('성함은 백경순이야')에 날짜가 없다고 생일까지 지웠다.
    import copy

    mom_text = "우리 엄마는 1953년 7월 9일에 태어나셨어. 성함은 백경순이야."
    mom_base = {"nodes": [
        {"id": "person_1", "type": "Person", "name": "나", "start_date": "1982-02-27", "year": 1982, "precision": "exact"},
        {"id": "kim", "type": "Person", "name": "김일권", "description": "고등학교 1학년 때 만난 친구"},
        {"id": "gig", "type": "PersonalEvent", "name": "메탈리카 공연 관람", "start_date": "1998-04-24", "year": 1998},
    ], "edges": [{"source": "person_1", "target": "gig", "type": "experienced", "role": "관람"},
                 {"source": "kim", "target": "gig", "type": "experienced", "role": "함께"}],
        "timeline": [{"event_id": "gig", "year": 1998}],
        "subject": {"id": "person_1", "name": "나", "birth_year": 1982},
        "stories": [{"at": "", "text": "1998년 4월 24일 메탈리카 공연을 친구 김일권과 함께 갔어."}]}
    mom_add = {"nodes": [{"id": "person_mother", "type": "Person", "name": "백경순",
                          "start_date": "1953-07-09", "confidence": 1.0}],
               "edges": [{"source": "person_mother", "target": "person_1", "type": "parent_of", "confidence": 1.0}],
               "timeline": [], "historical_connections": []}
    mv, mnotes = life_mod.validate(copy.deepcopy(mom_add), subject=mom_base["subject"], text=mom_text)
    check("더하는 답에서 주인공을 가리키는 관계는 버리지 않는다 (주인공은 옛 그래프에 있다)",
          len(mv["edges"]) == 1 and mv["edges"][0]["target"] == "person_1", str(mnotes))
    check("새 답의 첫 인물(어머니)을 주인공으로 잡지 않는다", mv["subject"]["id"] == "person_1", str(mv["subject"]))
    mm, _ = life_mod.merge(copy.deepcopy(mom_base), mv, mom_text)
    mom_e = [e for e in mm["edges"] if "person_mother" in (e["source"], e["target"])]
    check("합친 그래프에 어머니 → 나 부모 관계가 서고 호칭이 선의 이름이다",
          len(mom_e) == 1 and mom_e[0]["type"] == "parent_of" and mom_e[0]["source"] == "person_mother"
          and mom_e[0].get("role") == "엄마", str(mom_e))
    # 모델이 관계를 아예 안 적어도 코드가 이야기에서 읽어 잇는다
    no_edge = copy.deepcopy(mom_add); no_edge["edges"] = []
    mv0, _ = life_mod.validate(no_edge, subject=mom_base["subject"], text=mom_text)
    mm0, _ = life_mod.merge(copy.deepcopy(mom_base), mv0, mom_text)
    mom_e0 = [e for e in mm0["edges"] if "person_mother" in (e["source"], e["target"])]
    check("관계를 안 적어 와도 '엄마' 호칭으로 잇는다 (확신 1)",
          len(mom_e0) == 1 and mom_e0[0]["type"] == "parent_of" and mom_e0[0]["role"] == "엄마"
          and mom_e0[0]["confidence"] == 1.0, str(mom_e0))
    # 브라우저에 남은 옛 그래프(어머니가 홀로 뜬 것)도 부팅 refine 이 원문으로 잇는다
    old = copy.deepcopy(mom_base)
    old["nodes"].append({"id": "person_mother", "type": "Person", "name": "백경순",
                         "start_date": "1953-07-09", "year": 1953, "precision": "exact", "confidence": 1.0})
    whole = mom_base["stories"][0]["text"] + "\n\n" + mom_text
    rb = life_mod.refine(old, text=whole)
    momn = next(n for n in rb["nodes"] if n["id"] == "person_mother")
    check("옛 그래프도 새로고침(refine)으로 이어진다",
          any(e["source"] == "person_mother" and e["target"] == "person_1" and e["type"] == "parent_of"
              and e.get("role") == "엄마" for e in rb["edges"]), str(rb["edges"]))
    check("사용자가 말한 생일 1953-07-09 는 남는다 (앞 문장이 말했다)",
          (momn.get("start_date"), momn.get("year")) == ("1953-07-09", 1953), str(momn))
    kim_e = [e for e in rb["edges"] if "kim" in (e["source"], e["target"])]
    check("이미 이어진 사람(김일권)은 가족으로 잇지 않는다 (설명의 '친구'는 refine 4 가 friend_of 로)",
          not any(e["type"] in life_mod._FAMILY_EDGES for e in kim_e)
          and {e["type"] for e in kim_e} <= {"experienced", "friend_of"}, str(kim_e))
    check("두 번 다듬어도 그대로", len(life_mod.refine(copy.deepcopy(rb), text=whole)["edges"]) == len(rb["edges"]))
    check("'나형철'의 '형'은 호칭이 아니다", life_mod.kin_in("이름은 나형철이고 지금까지 만나고 있어", ["나형철"]) is None)
    check("'우리형은' 은 형, '동생 박준영' 은 친척(대칭)에 호칭",
          life_mod.kin_in("우리형은 1980년생이야")[:3] == ("형", "relative_of", "sym")
          and life_mod.kin_in("동생 박준영과 갔어")[1] == "relative_of")
    me_n = {"id": "me", "type": "Person", "name": "나"}
    two = lambda: [me_n, {"id": "k", "type": "Person", "name": "김일권"}]  # noqa: E731
    e1: list = []
    life_mod.link_people(two(), e1, me_n, "친구 김일권의 엄마는 선생님이셨어.")
    check("남의 가족('김일권의 엄마')은 내 가족이 아니다 — 이름이 불렸으니 만난 사이(0.8)",
          len(e1) == 1 and e1[0]["type"] == "met" and e1[0]["confidence"] == 0.8, str(e1))
    e2: list = []
    life_mod.link_people(two(), e2, me_n, "내 아들 김일권은 2010년에 태어났어.")
    check("아들은 나 → 그 사람 (부모 → 자녀)", e2 and e2[0]["type"] == "parent_of" and e2[0]["source"] == "me"
          and e2[0]["role"] == "아들", str(e2))
    e3 = [{"source": "k", "target": "me", "type": "parent_of", "confidence": 1}]
    check("모델이 이미 이은 가족 관계에는 호칭만 단다",
          life_mod.link_people(two(), e3, me_n, "우리 아버지는 김일권이야.") == 0 and e3[0].get("role") == "아버지")
    check("이름이 이야기에 없으면 잇지 않는다", life_mod.link_people(two(), [], me_n, "우리 엄마는 1953년에 태어나셨어.") == 0)
    check("이야기가 없으면 아무것도 안 한다", life_mod.link_people(two(), [], me_n, None) == 0)

    # 군복무 — 공익근무도 병역이다 (2026-09-08 사용자: "사실 공익근무는 군복무 기간이야.
    # 훈련소, 공익근무 역시 군복무로 인식할 수 있게 해줘"). 모델은 '사회생활'로 적어 왔다.
    army = dict(island, timeline=[
        {"event_id": "a1", "life_stage": "사회생활", "year": 2002},
        {"event_id": "a2", "life_stage": "사회생활", "year": 2002},
        {"event_id": "a3", "life_stage": "사회생활", "year": 2004},
        {"event_id": "bust", "life_stage": "고등학교", "year": 1997}])
    stages = {t["event_id"]: t["life_stage"] for t in life_mod.refine(army)["timeline"]}
    check("훈련소·공익근무·소집해제는 군복무다", [stages[i] for i in ("a1", "a2", "a3")] == ["군복무"] * 3, str(stages))
    check("병역이 아닌 것은 그대로", stages["bust"] == "고등학교", str(stages))
    check("'군복무'가 모델이 고를 수 있는 단계에 있다 (스키마의 enum)",
          "군복무" in life_mod.LIFE_STAGES and "군복무" in life_mod.SCHEMA["properties"]["timeline"]["items"]["properties"]["life_stage"]["enum"])
    check("지시문의 단계 목록에도 있다", "- 군복무" in life_mod.system_prompt())
    check("'제대로'는 제대가 아니다", not life_mod.MILITARY.search("제대로 하지 못했다"))

    # --- 만약 없었다면 — 물음에는 답이 따라와야 한다 (2026-09-09 사용자) ---
    # "질문만 있고 답변이 없어. 질문을 클릭하면 답을 볼수 있게 답안도 작성해줘."
    # 지시문·스키마가 `answer` 를 받고, 옛 문서는 `answer_counterfactuals` 가 채운다.
    _cf = life_mod.SCHEMA["properties"]["counterfactual_analysis"]["items"]
    check("스키마가 물음마다 답을 받는다",
          "answer" in _cf["properties"] and "answer" in _cf["required"])
    check("지시문도 답을 시킨다", "answer" in life_mod.system_prompt())
    _doc = {"nodes": [{"id": "e1", "name": "창업 실패", "description": "2013년에 접었다"},
                      {"id": "e2", "name": "독립 개발"}],
            "edges": [{"source": "e1", "target": "e2", "type": "led_to"}],
            "counterfactual_analysis": [
                {"event": "e1", "question": "창업이 실패하지 않았다면?", "possibilities": ["남았을 가능성"]},
                {"event": "e2", "question": "이미 답이 있는 물음", "answer": "있는 답은 그대로 둔다."}]}
    check("답이 빈 물음만 센다", [c["question"] for c in life_mod.unanswered(_doc)] == ["창업이 실패하지 않았다면?"])

    class _CF:
        name = model = "fake"
        def complete_json(self, system, user, schema, max_tokens=None):
            self.got = (system, user, schema)
            return {"answers": [{"question": "창업이 실패하지 않았다면?", "answer": "그 회사에 남았을 것이다."},
                                {"question": "이미 답이 있는 물음", "answer": "덮어쓰면 안 된다."}]}
    _be = _CF()
    check("빈 답만 채운다", life_mod.answer_counterfactuals(_doc, _be, "이야기") == 1
          and _doc["counterfactual_analysis"][0]["answer"] == "그 회사에 남았을 것이다."
          and _doc["counterfactual_analysis"][1]["answer"] == "있는 답은 그대로 둔다.")
    check("그 사건 뒤에 이어진 일을 모델에게 보인다", "독립 개발" in _be.got[1] and "이야기" in _be.got[1])
    check("물을 것이 없으면 모델을 안 부른다", life_mod.answer_counterfactuals(_doc, None) == 0)

    class _Bad:
        name = model = "fake"
        def complete_json(self, system, user, schema, max_tokens=None):
            return {"answers": [{"question": "창업이 실패하지 않았다면?", "answer": "would have stayed"}]}
    _doc2 = {"nodes": [], "edges": [], "counterfactual_analysis": [
        {"event": "e1", "question": "창업이 실패하지 않았다면?"}]}
    check("한국어가 아닌 답은 안 받는다", life_mod.answer_counterfactuals(_doc2, _Bad()) == 0
          and not _doc2["counterfactual_analysis"][0].get("answer"))
    # 한자가 한 자 섞여 오기도 한다 (실측: '더 오래続했을') — 화면에 세우지 않는다.
    check("한자·가나가 섞이면 안 받는다", life_mod.korean_line("더 오래続했을 수 있다") == ""
          and life_mod.korean_line("nullSpace 를 만들지 못했을 수 있다"))
    _kept, _ = life_mod.validate({"nodes": [], "edges": [], "counterfactual_analysis": [
        {"event": "e", "question": "ㄱ?", "answer": "한국어 답", "possibilities": []},
        {"event": "f", "question": "ㄴ?", "answer": "english only", "possibilities": []}]})
    check("검증도 같은 관문을 건다",
          [c.get("answer") for c in _kept["counterfactual_analysis"]] == ["한국어 답", None])

    # 옛 문서에 다시 물으면 빈 답이 채워진다 (merge 의 겹친 줄).
    _old = {"nodes": [], "edges": [], "timeline": [], "historical_connections": [],
            "counterfactual_analysis": [{"event": "e1", "question": "ㄱ?", "possibilities": ["ㄷ"]}]}
    _new = {"nodes": [], "edges": [], "timeline": [], "historical_connections": [],
            "counterfactual_analysis": [{"event": "e1", "question": "ㄱ?", "answer": "채워진 답"}]}
    _mg, _ = life_mod.merge(_old, _new)
    check("겹친 물음은 빈 답만 채운다", len(_mg["counterfactual_analysis"]) == 1
          and _mg["counterfactual_analysis"][0]["answer"] == "채워진 답"
          and _mg["counterfactual_analysis"][0]["possibilities"] == ["ㄷ"])

    # 그래프에 잇기 + 엔드포인트
    store = GraphStore(Path(tmp) / "korea.sqlite")
    store.upsert_nodes([
        Node(id="wd:IMF", type="event", label="대한민국의 IMF 구제금융 요청", source="wd", start_date="1997-12-03"),
        Node(id="wd:IMF2", type="event", label="대한민국의 IMF 구제금융 요청", source="wd", start_date="1897"),
        Node(id="wd:COV", type="event", label="대한민국의 코로나19 범유행", source="wd", start_date="2020-01-20"),
        Node(id="wd:KDJ", type="person", label="김대중", source="wd", start_date="1924-01-06", end_date="2009-08-18"),
        Node(id="wd:PRES", type="role", label="대한민국의 대통령", source="wd"),
    ])
    store.upsert_edges([Edge(src="wd:KDJ", dst="wd:PRES", type="held_position", source="wd",
                             start_date="1998-02-25", end_date="2003-02-24", props={"reign": "president"})])
    api = _LifeAPI(store, era="korea")
    linked = life_mod.link(payload, api)
    c0 = payload["historical_connections"][0]
    check("이름과 해가 맞는 사건 노드에 잇는다 (1897 년의 동명 사건이 아니라)", linked == 1 and c0["node_id"] == "wd:IMF", str(c0))
    check("못 이은 것은 None 으로 둔다", payload["historical_connections"][1]["node_id"] is None)
    # 무료 모델이 실제로 낸 두 가지 어긋남 (2026-09-08). 관계·연결은 참인데
    # 부르는 법만 다르다 — 버리면 화면에서 그 사건이 없었던 일이 된다.
    named = {
        "nodes": [{"id": "p1", "type": "Person", "name": "나", "confidence": 1.0},
                  {"id": "l1", "type": "Residence", "name": "서울 관악구", "confidence": 1.0},
                  {"id": "l2", "type": "Residence", "name": "대구", "confidence": 1.0},
                  {"id": "l3", "type": "TravelLocation", "name": "대구", "confidence": 1.0}],
        "edges": [{"source": "나", "target": "서울관악구", "type": "lived_in", "confidence": 1.0},
                  {"source": "p1", "target": "대구", "type": "born_in", "confidence": 1.0},
                  {"source": "p1", "target": "없는 것", "type": "lived_in", "confidence": 1.0}],
        "timeline": [],
        "historical_connections": [
            {"personal_event": "나", "historical_event": "대한민국의 IMF 구제금융 요청(1997)",
             "impact_type": "direct", "description": "…", "confidence": 1.0}],
        "_model": "무료/모델:free",
    }
    fixed, fnotes = life_mod.validate(named)
    check("역사 연결의 개인 사건도 이름으로 적어 오면 id 로 되짚는다 ('나' → p1)",
          fixed["historical_connections"][0]["personal_event"] == "p1", str(fixed["historical_connections"]))
    check("양끝을 이름으로 적은 관계는 노드에 이어 준다",
          [(e["source"], e["target"]) for e in fixed["edges"]] == [("p1", "l1")], str(fixed["edges"]))
    check("같은 이름이 둘이면 잇지 않는다 (대구가 둘)",
          any("대구" in n for n in fnotes) and any("없는 것" in n for n in fnotes), str(fnotes))
    check("어느 모델이 쓴 그래프인지 남긴다", fixed["_model"] == "무료/모델:free")
    who, _ = life_mod.validate({"nodes": [{"id": "p1", "type": "Person", "name": "사용자", "confidence": 1.0}],
                                "edges": [], "timeline": [], "historical_connections": []})
    check("주인공을 '사용자'라 적어 와도 '나'다 (2026-09-08)",
          who["nodes"][0]["name"] == "나" and who["subject"]["name"] == "나", str(who["subject"]))
    # 손으로 적은 별칭도 이름이다 — 이야기가 '외환위기'라 불러도 IMF 노드에 댄다.
    store.conn.execute("INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?, ?)", ("wd:IMF", "외환 위기"))
    store.conn.commit()
    check("이름 뒤에 붙은 해는 이름이 아니다 — 떼고 잇는다",
          life_mod.link(fixed, api) == 1
          and fixed["historical_connections"][0]["node_id"] == "wd:IMF"
          and fixed["historical_connections"][0]["year"] == 1997,
          str(fixed["historical_connections"][0]))
    check("그래프의 별칭을 연결에 달아 온다 ('외환 위기')",
          "외환 위기" in fixed["historical_connections"][0].get("node_names", []),
          str(fixed["historical_connections"][0].get("node_names")))
    fixed_copy = {"nodes": fixed["nodes"], "timeline": [], "historical_connections": [dict(fixed["historical_connections"][0])]}
    check("이야기가 '외환위기'라 불러도 별칭으로 남는다",
          not life_mod.gate_connections(fixed_copy, "외환위기 때 아버지 사업이 망했어") and len(fixed_copy["historical_connections"]) == 1)
    # 이야기가 부르지 않은 역사는 잇지 않는다 (2026-09-08 사용자: "세월호 사건과
    # 사용자의 퍼듀대학교 졸업은 도대체 무슨 상관이지? 연평해전과 동사무소 공익요원
    # 시작은 어떤 관계가 있지?"). 모델이 같은 해의 큰 사건을 목록에서 집어 왔다.
    story = "IMF 때 아버지 인쇄소가 부도났어. 2002년 4월에 동사무소 공익요원으로 들어갔고 2011년에 졸업했어."
    guessed = {
        "nodes": [{"id": "me", "type": "Person", "name": "나", "confidence": 1.0},
                  {"id": "ev_bust", "type": "Crisis", "name": "인쇄소 부도", "start_date": "1998", "confidence": 1.0},
                  {"id": "ev_serve", "type": "PersonalEvent", "name": "공익요원 시작", "start_date": "2002-04", "confidence": 1.0},
                  {"id": "ev_grad", "type": "Achievement", "name": "졸업", "start_date": "2011-05", "confidence": 1.0}],
        "edges": [], "timeline": [],
        "historical_connections": [
            {"personal_event": "ev_bust", "historical_event": "대한민국의 IMF 구제금융 요청", "year": 1997,
             "impact_type": "direct", "description": "부도", "confidence": 1.0},
            {"personal_event": "ev_bust", "historical_event": "6·25 전쟁", "year": 1950, "node_label": "한국 전쟁",
             "node_names": ["6.25 전쟁"], "impact_type": "indirect", "description": "…", "confidence": 0.5},
            {"personal_event": "ev_serve", "historical_event": "제2연평해전", "year": 2002,
             "impact_type": "indirect", "description": "국가적 책임감을 강화했을 수 있음", "confidence": 0.6},
            {"personal_event": "ev_grad", "historical_event": "세월호 침몰 사고", "year": 2014,
             "impact_type": "indirect", "description": "이후 인식 변화의 배경", "confidence": 0.5},
            {"personal_event": "ev_grad", "historical_event": "졸업", "year": 2012,
             "impact_type": "direct", "description": "이름은 이야기에 있지만 해가 뒤", "confidence": 0.5},
        ],
    }
    gated, vnotes = life_mod.validate(guessed, text=story)
    check("검증만으로도 결과보다 늦은 원인은 빠진다 (세월호 2014 → 졸업 2011)",
          sum("보다 뒤" in n for n in vnotes) == 2
          and not any(c["historical_event"] == "세월호 침몰 사고" for c in gated["historical_connections"]), str(vnotes))
    dropped = life_mod.gate_connections(gated, story)
    left = [(c["personal_event"], c["historical_event"]) for c in gated["historical_connections"]]
    check("이야기가 부른 사건(IMF)만 남는다 — 연평해전·6·25는 버린다",
          left == [("ev_bust", "대한민국의 IMF 구제금융 요청")], str(left))
    check("버린 사유를 적는다 (부르지 않은 사건)",
          sum("부르지 않은" in n for n in dropped) == 2 and dropped == gated["notes"][-2:], str(dropped))
    check("원문을 모르면 이름으로는 안 버린다", life_mod.grounded(None, "제2연평해전"))
    check("겹친 낱말이 '전쟁'·'사건'뿐이면 부른 것이 아니다",
          not life_mod.grounded("전쟁 같은 사건이었어", "한국 전쟁") and life_mod.grounded("6.25때 피난", "6·25 전쟁"))
    check("그래프의 다른 이름으로도 댄다 ('한국 전쟁' ← '6·25')",
          life_mod.grounded("6·25 때 할아버지가 피난을", "한국 전쟁", "6·25 전쟁"))
    check("지시문이 이야기가 말한 역사만 이으라고 한다",
          "이야기가 직접 말한" in life_mod.build_user("이야기", anchors=[{"label": "제2연평해전", "year": 2002}]))
    # 학년은 해다 (2026-09-08 사용자: "1997년 고등학교 입학했다고 했고 1학년때
    # 누굴 만나고 2학년때 누굴 만났다고 하면 … 유추해서 알 수 있지 않나?").
    check("프롬프트가 앞뒤에서 해를 셈하라고 한다", "'2학년 때'는 1998년" in life_mod.build_user("이야기", anchors=[]))
    grade = {
        "nodes": [{"id": "me", "type": "Person", "name": "나", "confidence": 1.0},
                  {"id": "hs", "type": "School", "name": "한별고등학교", "start_date": "1997", "confidence": 1.0},
                  {"id": "m1", "type": "PersonalEvent", "name": "친구 A 를 만남", "start_date": "고등학교 1학년", "confidence": 0.8},
                  {"id": "m2", "type": "PersonalEvent", "name": "친구 B 를 만남", "start_date": "고2 때", "confidence": 0.8},
                  {"id": "u3", "type": "PersonalEvent", "name": "동아리", "start_date": "대학 3학년", "confidence": 0.8}],
        "edges": [], "timeline": [{"event_id": "m2", "life_stage": "고등학교", "date_text": "고등학교 2학년 봄"}],
        "historical_connections": [],
    }
    g, _ = life_mod.validate(grade)
    ys = {n["id"]: (n["year"], n["precision"]) for n in g["nodes"]}
    check("입학 해에서 학년을 센다 (1997 입학 → 1학년 1997 · 고2 1998)",
          ys["m1"] == (1997, "year") and ys["m2"] == (1998, "year"), str(ys))
    check("연표 항목의 '고등학교 2학년 봄'도 1998", g["timeline"][0]["year"] == 1998, str(g["timeline"]))
    check("입학 해도 생년도 모르는 학교는 못 센다 (대학 3학년)", ys["u3"] == (None, "age"), str(ys))
    grade["nodes"][0]["start_date"] = "1981"
    g, _ = life_mod.validate(grade)
    ys = {n["id"]: (n["year"], n["precision"]) for n in g["nodes"]}
    check("생년을 알면 어림으로 센다 (1981년생 대학 3학년 = 2002 · 고2 는 여전히 입학 해에서)",
          ys["u3"] == (2002, "age") and ys["m2"] == (1998, "year"), str(ys))
    # 실측 (2026-09-08, 무료 모델의 답 꼴): 생년은 '출생' 노드에, 친구는 설명에만
    # '잠실고등학교 1학년 때 만난' 이라 적히고 주인공·학교와 아무 관계가 없었다.
    # 사용자: "고등학교에서 만났다고 하면 내가 입학했다고 말한 고등학교와 연결
    # 시켜줘야 하는거야. 지금 그걸 못하고 있어. 연표에 추가도 안되고 있고."
    check("프롬프트가 만난 사람을 주인공·만난 곳과 이으라고 한다", "met 관계로 잇고" in life_mod.build_user("이야기", anchors=[]))
    told = {
        "nodes": [{"id": "person_1", "type": "Person", "name": "나", "confidence": 1.0,
                   "description": "1982년 2월 27일 서울에서 태어난 사람. 1997년 잠실고등학교 입학."},  # 실측: 이 문장이 입학 해를 생년으로 만들었다
                  {"id": "birth_1", "type": "Time", "name": "출생", "start_date": "1982-02-27", "confidence": 1.0},
                  {"id": "hs_entry", "type": "PersonalEvent", "name": "잠실고등학교 입학", "start_date": "1997-03-01", "confidence": 1.0},
                  {"id": "hs_school", "type": "School", "name": "잠실고등학교", "confidence": 1.0},
                  {"id": "kim", "type": "Person", "name": "김일권", "confidence": 1.0, "description": "잠실고등학교 1학년 때 만난 친구"},
                  {"id": "park", "type": "Person", "name": "박준영", "confidence": 1.0, "description": "잠실고등학교 2학년 때 만난 친구"}],
        "edges": [{"source": "person_1", "target": "birth_1", "type": "born_in", "confidence": 1.0},
                  {"source": "hs_entry", "target": "hs_school", "type": "studied_at", "confidence": 1.0},
                  {"source": "kim", "target": "park", "type": "worked_with", "confidence": 1.0}],
        "timeline": [{"event_id": "hs_entry", "life_stage": "고등학교", "date_text": "1997-03-01"},
                     {"event_id": "kim", "life_stage": "고등학교", "age": 15},
                     {"event_id": "park", "life_stage": "고등학교", "age": 16}],
        "historical_connections": [],
    }
    t, _ = life_mod.validate(told)
    tn = {n["id"]: n for n in t["nodes"]}
    check("생년은 '출생' 노드에서 찾는다", t["subject"]["birth_year"] == 1982, str(t["subject"]))
    check("설명의 '1학년 때 만난' 이 해가 된다 (입학 해에서: 1997 · 1998)",
          (tn["kim"]["year"], tn["park"]["year"]) == (1997, 1998), str((tn["kim"].get("year"), tn["park"].get("year"))))
    check("학교 노드는 입학 사건의 해를 받는다", tn["hs_school"]["year"] == 1997)
    te = {(e["source"], e["target"], e["type"]) for e in t["edges"]}
    check("친구를 이야기 속 그 학교에 잇는다", ("kim", "hs_school", "studied_at") in te and ("park", "hs_school", "studied_at") in te, str(te))
    check("만난 사람은 주인공과 잇는다 — 설명이 '친구'라 하니 friend_of",
          ("person_1", "kim", "friend_of") in te and ("person_1", "park", "friend_of") in te, str(te))
    check("연표의 친구 항목이 해를 얻어 선다 (나이 → 생년)",
          [(x["event_id"], x["year"]) for x in t["timeline"]] == [("hs_entry", 1997), ("kim", 1997), ("park", 1998)], str(t["timeline"]))
    check("두 번 돌려도 관계가 늘지 않는다", len(life_mod.refine(t)["edges"]) == len(te))
    # 관계의 이름 (2026-09-08 사용자: "지금 그래프의 엣지 설명이 엉망이야. 친구들은
    # 만남이 아니라 '친구'라고 표시해야. 그리고 '뒤', '동안' 이런 설명은 도대체 뭐야?")
    # — 실측 그래프의 꼴 그대로: 주인공 → 자기 사건이 after·during, 친구 셋이 서로
    # worked_with(0.5), 나형철이 양방향 met.
    messy = {
        "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "confidence": 1.0},
                  {"id": "mv", "type": "PersonalEvent", "name": "미국으로 이주", "start_date": "2005", "confidence": 1.0},
                  {"id": "hs", "type": "PersonalEvent", "name": "잠실고등학교 입학", "start_date": "1997", "confidence": 1.0},
                  {"id": "gr", "type": "PersonalEvent", "name": "성내중학교 졸업", "start_date": "1997", "confidence": 1.0},
                  {"id": "fail", "type": "Failure", "name": "첫 창업 실패", "start_date": "2010", "confidence": 1.0},
                  {"id": "sch", "type": "School", "name": "잠실고등학교", "confidence": 1.0},
                  {"id": "major", "type": "Occupation", "name": "수학 전공", "confidence": 1.0},
                  {"id": "usa", "type": "Location", "name": "미국", "confidence": 1.0},
                  {"id": "kim", "type": "Person", "name": "김일권", "confidence": 1.0, "description": "잠실고등학교 1학년 때 만난 친구"},
                  {"id": "park", "type": "Person", "name": "박준영", "confidence": 1.0, "description": "잠실고등학교 2학년 때 만난 친구"},
                  {"id": "na", "type": "Person", "name": "나형철", "confidence": 1.0},
                  {"id": "lee", "type": "Person", "name": "이대표", "confidence": 1.0, "description": "첫 회사 동료"}],
        "edges": [{"source": "me", "target": "mv", "type": "after", "confidence": 1.0},
                  {"source": "hs", "target": "me", "type": "during", "confidence": 1.0},
                  {"source": "me", "target": "fail", "type": "after", "confidence": 1.0},
                  {"source": "gr", "target": "hs", "type": "before", "confidence": 1.0},
                  {"source": "hs", "target": "sch", "type": "studied_at", "confidence": 1.0},
                  {"source": "hs", "target": "major", "type": "studied_at", "confidence": 1.0},
                  {"source": "mv", "target": "usa", "type": "moved_to", "confidence": 1.0},
                  {"source": "me", "target": "kim", "type": "met", "confidence": 0.8},
                  {"source": "me", "target": "park", "type": "met", "confidence": 0.8},
                  {"source": "me", "target": "lee", "type": "met", "confidence": 0.8},
                  {"source": "kim", "target": "park", "type": "worked_with", "confidence": 0.5},
                  {"source": "me", "target": "na", "type": "met", "confidence": 0.9},
                  {"source": "na", "target": "me", "type": "met", "confidence": 0.9}],
        "timeline": [], "historical_connections": [],
    }
    m, _ = life_mod.validate(messy)
    mk = {(e["source"], e["target"]): e["type"] for e in m["edges"]}
    check("주인공 → 자기 사건의 시간 관계는 참여(experienced)다 (뒤·동안이 아니다)", mk[("me", "mv")] == "experienced", str(mk))
    check("사건 → 주인공으로 뒤집혀 온 것도 주인공 → 사건 experienced 로", mk.get(("me", "hs")) == "experienced" and ("hs", "me") not in mk, str(mk))
    check("친구라고 적힌 만남은 friend_of, 동료는 worked_with, 아무 말 없으면 met 그대로",
          mk[("me", "kim")] == "friend_of" and mk[("me", "lee")] == "worked_with" and mk[("me", "na")] == "met", str(mk))
    check("일한 곳 없이 미룬 '함께 일함'은 같은 학교면 schoolmate (둘 다 그 학교에 이어진 뒤)", mk[("kim", "park")] == "schoolmate", str(mk))
    check("양방향 met 은 하나만 남는다", ("na", "me") not in mk and ("me", "na") in mk)
    # 차례만 말하는 엣지는 세우지 않는다 (2026-09-08 사용자: "다음 이라는 메뉴는 뭐야?
    # 별 정보값이 없는데 그냥 삭제해") — 그 차례는 연표가 이미 연도로 그린다. 옮길 데가
    # 있는 것(주인공 → 자기 사건의 after)은 위에서 참여로 남으므로 버리는 것은 사건 → 사건뿐.
    check("사건 → 사건의 before 는 세우지 않는다 (차례는 연표가 그린다)", ("gr", "hs") not in mk, str(mk))
    check("사건 → 학교·전공의 studied_at 은 재학이 아니라 그 곳(at)이다 — 온톨로지의 출발 갈래가 사람뿐",
          mk[("hs", "sch")] == "at" and mk[("hs", "major")] == "at", str(mk))
    mr = {(e["source"], e["target"]): e.get("role") for e in m["edges"]}
    check("사람 → 사건의 역할은 사건 이름의 술어다 (이주·입학), 술어가 없으면 사건의 종류(실패)",
          (mr[("me", "mv")], mr[("me", "hs")], mr[("me", "fail")]) == ("이주", "입학", "실패"), str(mr))
    check("옮기면서 원래 타입이 말하던 것은 역할로 남는다 (studied_at → 전공 = '전공')", mr[("hs", "major")] == "전공", str(mr))
    mn = {n["id"]: n["type"] for n in m["nodes"]}
    lab = lambda a, b: life_mod.edge_label(mk[(a, b)], mn[a], mn[b], mr.get((a, b)))
    got = (lab("me", "mv"), lab("me", "fail"), lab("hs", "sch"), lab("hs", "major"), lab("mv", "usa"), lab("me", "kim"), lab("kim", "park"))
    check("선 위의 말: 역할이 이기고, 없으면 양끝을 본다 — 이주 · 실패 · 학교 · 전공 · 이주지 · 친구 · 같은 학교",
          got == ("이주", "실패", "학교", "전공", "이주지", "친구", "같은 학교"), str(got))
    check("사람 → 학교는 재학, 표에 없는 조합은 일반 이름", life_mod.edge_label("studied_at", "Person", "School") == "재학"
          and life_mod.edge_label("led_to", "PersonalEvent", "PersonalEvent") == "이어짐")
    check("화면에 '뒤'·'동안'·'다음'·'수학'·'겪음'이 서지 않는다 — 실측 그래프의 모든 선",
          not {lab(a, b) for a, b in mk} & {"뒤", "동안", "다음", "이전", "수학", "앞", "겪음"}, str({lab(a, b) for a, b in mk}))
    check("술어 읽기: '스타트업 경력 시작' → '경력 시작', '30사단 훈련소 입소' → '입소', 술어 없는 개인 사건은 None",
          (life_mod.deed_of({"name": "스타트업 경력 시작", "type": "PersonalEvent"}), life_mod.deed_of({"name": "30사단 훈련소 입소", "type": "PersonalEvent"}),
           life_mod.deed_of({"name": "아버지 인쇄소 부도", "type": "PersonalEvent"})) == ("경력 시작", "입소", None))
    # 온톨로지 관문 (한국사의 "모든 엣지 타입에 문장 규칙이 있다" 와 같은 자리)
    check("이름표(EDGE_TYPE_KO)와 온톨로지(LIFE_EDGES)의 관계가 같고 일반 이름이 같다",
          set(life_mod.EDGE_TYPE_KO) == set(life_mod.LIFE_EDGES)
          and all(life_mod.EDGE_TYPE_KO[k] == v[0] for k, v in life_mod.LIFE_EDGES.items()),
          str({k for k, v in life_mod.LIFE_EDGES.items() if life_mod.EDGE_TYPE_KO.get(k) != v[0]} | (set(life_mod.EDGE_TYPE_KO) ^ set(life_mod.LIFE_EDGES))))
    def _relax_fits():
        for (kind, sc, dc), moved in life_mod.RELAX.items():
            if kind not in life_mod.LIFE_EDGES or moved not in life_mod.LIFE_EDGES:
                return f"{kind}→{moved} 모르는 타입"
            spec = life_mod.LIFE_EDGES[moved]
            a, b = (dc, sc) if moved == "experienced" and sc == "event" else (sc, dc)
            if a not in spec[1] or b not in spec[2]:
                return f"{kind}({sc}→{dc}) → {moved} 가 표에 안 맞음"
            if sc in life_mod.LIFE_EDGES[kind][1] and dc in life_mod.LIFE_EDGES[kind][2]:
                return f"{kind}({sc}→{dc}) 는 이미 맞는데 RELAX 에 있음"
        return ""
    check("RELAX 의 결과는 전부 온톨로지에 맞고, 이미 맞는 짝은 옮기지 않는다", _relax_fits() == "", _relax_fits())
    check("모든 노드 타입에 갈래가 있고 갈래는 캔버스의 여덟 색", set(life_mod.GRAPH_TYPE) == set(life_mod.NODE_TYPE_KO)
          and set(life_mod.GRAPH_TYPE.values()) <= set(life_mod._ANY))
    check("일반 이름은 전부 한글", all(re.search(r"[가-힣]", v[0]) for v in life_mod.LIFE_EDGES.values()))
    check("표 밖 엣지는 버리지 않고 센다", life_mod.tidy_edges(
        [{"id": "a", "type": "Book", "name": "책"}, {"id": "b", "type": "School", "name": "학교"}],
        [{"source": "a", "target": "b", "type": "parent_of", "confidence": 1.0}], None) != []
        and len(life_mod.tidy_edges([{"id": "a", "type": "Book", "name": "책"}, {"id": "b", "type": "School", "name": "학교"}],
                                    (ee := [{"source": "a", "target": "b", "type": "parent_of", "confidence": 1.0}]), None)) == 1 and len(ee) == 1)
    check("지시문이 주인공의 사건은 experienced, 친구는 friend_of 라 한다",
          "experienced 로 잇는다" in life_mod.build_user("이야기", anchors=[]) and "friend_of" in life_mod.build_user("이야기", anchors=[]))
    # 화면은 부팅 때 옛 자료를 POST /api/life/refine 으로 보내 같은 다듬기를 받는다
    # (Handler.do_POST — 소켓이 필요해 여기서는 refine 만 잰다).
    # 더하는 이야기 — 옛 그래프에 붙이지, 지우고 새로 만들지 않는다 (2026-09-08).
    base = {
        "nodes": [{"id": "person_1", "type": "Person", "name": "나", "start_date": "1985", "year": 1985, "confidence": 1.0},
                  {"id": "ev_move", "type": "PersonalEvent", "name": "서울 이사", "year": 1998, "confidence": 1.0},
                  {"id": "seoul", "type": "Residence", "name": "서울 관악구", "confidence": 1.0}],
        "edges": [{"source": "person_1", "target": "seoul", "type": "lived_in", "confidence": 1.0}],
        "timeline": [{"event_id": "ev_move", "life_stage": "중학교", "year": 1998, "previous_event": None, "next_event": None}],
        "historical_connections": [], "turning_points": [{"event": "ev_move", "turning_point_score": 7, "reason": "…"}],
        "impact_analysis": [], "counterfactual_analysis": [], "life_patterns": [],
        "influence_ranking": {"items": []}, "family_analysis": {"members": []}, "follow_up_questions": ["옛 물음"],
        "subject": {"id": "person_1", "name": "나", "birth_year": 1985},
    }
    add_raw = {
        "nodes": [{"id": "father", "type": "Person", "name": "아버지", "confidence": 1.0},   # 첫 인물이 주인공이 아니다
                  {"id": "me2", "type": "Person", "name": "사용자", "confidence": 1.0},        # 주인공을 딴 id 로 불렀다
                  {"id": "ev_move2", "type": "PersonalEvent", "name": "서울 이사", "start_date": "1998-03", "confidence": 1.0},  # 이름이 같다
                  {"id": "ev_univ", "type": "PersonalEvent", "name": "대학 입학", "start_date": "20살", "confidence": 1.0}],
        "edges": [{"source": "father", "target": "me2", "type": "parent_of", "confidence": 1.0},
                  {"source": "me2", "target": "seoul", "type": "lived_in", "confidence": 1.0},   # 이미 있는 관계
                  {"source": "ev_move2", "target": "ev_univ", "type": "caused", "confidence": 0.8}],
        "timeline": [{"event_id": "ev_univ", "life_stage": "대학", "age": 20}],
        "historical_connections": [],
        "turning_points": [{"event": "ev_move2", "turning_point_score": 8, "reason": "다시"}, {"event": "ev_univ", "turning_point_score": 6, "reason": "…"}],
        "follow_up_questions": ["새 물음"],
    }
    prompt = life_mod.build_user("더하는 이야기", anchors=[], existing=life_mod.existing_summary(base))
    check("더할 때는 있는 노드와 주인공 id 를 모델에게 보인다",
          "ev_move · 개인 사건 · 서울 이사 · 1998" in prompt and "주인공은 id person_1" in prompt and "생년은 1985년" in prompt, prompt[-400:])
    addv, _ = life_mod.validate(add_raw, subject=base["subject"])
    check("더할 때 주인공은 첫 인물이 아니라 옛 주인공이다", addv["subject"]["id"] == "me2" and addv["subject"]["name"] == "나", str(addv["subject"]))
    check("옛 주인공의 생년으로 나이를 푼다 (20살 → 2005)", addv["nodes"][3]["year"] == 2005, str(addv["nodes"][3]))
    merged, added = life_mod.merge(base, addv)
    ids = [n["id"] for n in merged["nodes"]]
    check("있던 노드는 남고 새 것만 는다 (아버지·대학 입학)", ids == ["person_1", "ev_move", "seoul", "father", "ev_univ"] and added["nodes"] == 2, str(ids))
    check("딴 id 로 부른 주인공은 옛 주인공에 잇는다",
          any(e["source"] == "father" and e["target"] == "person_1" and e["type"] == "parent_of" for e in merged["edges"]), str(merged["edges"]))
    check("같은 이름의 사건은 하나로 — 빈 칸만 채운다", merged["nodes"][1]["start_date"] == "1998-03" and merged["nodes"][1]["year"] == 1998)
    check("이미 있는 관계는 두 번 세지 않는다",
          sum(1 for e in merged["edges"] if e["type"] == "lived_in") == 1, str(merged["edges"]))
    check("더한 사건은 주인공에게 이어져 온다 (섬으로 붙지 않는다)",
          {e["target"] for e in merged["edges"] if e["type"] == "experienced" and e["source"] == "person_1"}
          == {"ev_move", "ev_univ"} and added["edges"] == 4, str(merged["edges"]))
    check("연표는 해 순으로 다시 서고 앞뒤가 이어진다",
          [t["event_id"] for t in merged["timeline"]] == ["ev_move", "ev_univ"] and merged["timeline"][0]["next_event"] == "ev_univ"
          and merged["timeline"][1]["previous_event"] == "ev_move", str(merged["timeline"]))
    check("분석은 없던 것만 붙는다 (전환점 서울 이사는 옛 것 그대로)",
          [(t["event"], t["turning_point_score"]) for t in merged["turning_points"]] == [("ev_move", 7), ("ev_univ", 6)], str(merged["turning_points"]))
    check("물음은 새 것으로", merged["follow_up_questions"] == ["새 물음"])
    check("주인공·생년은 옛 것", merged["subject"] == {"id": "person_1", "name": "나", "birth_year": 1985})
    check("옛 그래프는 손대지 않는다 (복사본에 더한다)", len(base["nodes"]) == 3 and len(base["edges"]) == 1)
    st, ctx = _life_dispatch(api, "/api/context", {"from": ["1985"], "to": ["2026"]})
    check("/api/context 가 구간의 재위 띠와 사건을 준다",
          st == 200 and [r["label"] for r in ctx["reigns"]] == ["김대중"] and {a["id"] for a in ctx["anchors"]} == {"wd:IMF", "wd:COV"}, str(ctx))
    st, ctx = _life_dispatch(api, "/api/context", {"from": ["1900"], "to": ["1990"]})
    check("구간 밖의 재위·사건은 안 준다", ctx["reigns"] == [] and ctx["anchors"] == [])
    life_mod.LIFE_DIR, keep_dir = Path(tmp) / "life", life_mod.LIFE_DIR
    # 서버는 폴더의 개인 파일을 화면에 주지 않는다 (2026-09-08 — 기본 자료 없음).
    st, body = _life_dispatch(api, "/api/life", {})
    check("저장된 개인 그래프를 서버가 골라 주는 길은 없다", st == 404, str(st))

    # 화면의 '내 인생 입력하기' — 글을 받아 스레드에서 묻고, 화면이 물어 간다.
    # 모델은 부르지 않는다 (MLX 는 35GB 를 잡는다). 백엔드를 가짜로 바꿔 낀다.
    import time  # noqa: E402  (여기서만 쓴다)
    import histgraph.backends as _backends
    from histgraph.server import LifeAnalysis as _LifeJob, _life_name

    class _FakeLife:
        model = "fake"
        def complete_json(self, system, user, schema, max_tokens=None):
            self.user = user
            return {"nodes": [{"id": "me", "type": "Person", "name": "나", "confidence": 1.0}],
                    "edges": [], "timeline": [], "historical_connections": []}
    made = _FakeLife()
    keep_build, _backends.build_backend = _backends.build_backend, lambda kind, model=None: made
    # 분석은 다른 스레드에서 돈다 — 저장소를 통째로 준 api(테스트용, 연결
    # 하나)가 아니라 서버가 쓰는 것처럼 경로로 연 api 를 준다.
    tapi = _LifeAPI(Path(tmp) / "korea.sqlite", era="korea")
    try:
        job = _LifeJob()
        idle = job.status()
        check("분석 전에는 idle", idle["state"] == "idle")
        # 화면이 '글이 이 컴퓨터 밖으로 나가지 않는다'고 적어도 되는지가
        # 이 값으로 갈린다 (LifeView 의 `local`).
        check("어느 모델로 읽는지 같이 알린다", idle["backend"] in ("mlx", "openrouter"))
        check("이야기를 주면 띄운다", job.start(tapi, "이야기", name="시험"))
        for _ in range(200):
            if job.status()["state"] != "running":
                break
            time.sleep(0.02)
        st = job.status()
        check("끝나면 화면이 쓸 그래프를 준다",
              st["state"] == "done" and st["payload"]["subject"]["name"] == "나" and st["file"] == "시험.json", str(st)[:200])
        check("저장까지 한다 (data/life 밖으로 안 나간다)", (life_mod.LIFE_DIR / "시험.json").is_file()
              and (life_mod.LIFE_DIR / "시험.txt").read_text(encoding="utf-8") == "이야기")
        check("모델에게 그래프의 사건 이름을 보인다", "대한민국의 IMF 구제금융 요청" in made.user)
        check("있는 그래프를 주면 거기에 더한다", job.start(tapi, "더", name="시험", base=st["payload"]))
        for _ in range(200):
            if job.status()["state"] != "running":
                break
            time.sleep(0.02)
        st2 = job.status()
        check("더한 결과는 옛 주인공을 지키고 더한 수를 알린다",
              st2["state"] == "done" and st2["added"] == {"nodes": 0, "edges": 0, "timeline": 0, "connections": 0, "ids": []}
              and st2["payload"]["subject"]["id"] == st["payload"]["subject"]["id"] and "그래프는 이미 있다" in made.user, str(st2)[:300])
        check("원문은 파일에 이어 둔다", (life_mod.LIFE_DIR / "시험.txt").read_text(encoding="utf-8") == "이야기\n\n더")
        st, body = _life_dispatch(api, "/api/life/job", {})
        check("/api/life/job 이 상태를 준다 (배포에서는 늘 idle)", st == 200 and "state" in body)
        class _Slow(_FakeLife):
            def complete_json(self, *a, **kw):
                time.sleep(0.3)
                return super().complete_json(*a, **kw)
        made2 = _Slow()
        _backends.build_backend = lambda kind, model=None: made2
        job2 = _LifeJob()
        job2.start(tapi, "이야기", name="시험2")
        check("한 번에 하나만 돈다 (MLX 는 자리를 두 벌 못 잡는다)", job2.start(tapi, "또", name="시험3") is False)
        for _ in range(200):
            if job2.status()["state"] != "running":
                break
            time.sleep(0.02)
    finally:
        _backends.build_backend = keep_build
    check("이름이 경로가 되지 않는다", "/" not in _life_name("../../etc/passwd") and _life_name("") == "나")

    # --- 배포는 요청 하나 안에서 돈다 (2026-09-09 "개인 역사도 이제 배포 해줘") ---
    # 서버리스 함수는 응답과 함께 죽어서 **띄워 둔 스레드도 그것이 적은 상태도
    # 다음 요청이 못 본다.** 그래서 배포는 같은 몸통(`life_post`)을 blocking 으로
    # 돌리고, 파일은 남기지 않는다 — 남의 삶이 적힌 글을 우리 서버에 두지 않는다.
    import os as _osl  # noqa: E402  (여기서만 쓴다)

    from histgraph.server import LIFE_POSTS as _LIFE_POSTS  # noqa: E402
    from histgraph.server import life_post as _life_post  # noqa: E402
    from histgraph.server import LIFE_JOBS as _LIFE_JOBS  # noqa: E402

    made3 = _FakeLife()
    _backends.build_backend = lambda kind, model=None: made3
    try:
        st, body = _life_post(tapi, "/api/life/analyze",
                              _j0.dumps({"text": "이야기", "name": "배포시험"}).encode("utf-8"),
                              blocking=True, save=False)
        check("배포 — 답이 요청 하나에 실려 온다",
              st == 200 and body["state"] == "done" and body["payload"]["subject"]["name"] == "나",
              str(body)[:200])
        check("배포 — 파일을 남기지 않는다 (남의 삶을 우리 서버에 두지 않는다)",
              body["file"] is None and not (life_mod.LIFE_DIR / "배포시험.json").exists())
        st, body = _life_post(tapi, "/api/life/analyze", b'{"text": "   "}', blocking=True, save=False)
        check("빈 이야기는 400", st == 400 and "비어" in body["error"], str(body))
        st, body = _life_post(tapi, "/api/life/analyze", b"not json", blocking=True, save=False)
        check("JSON 이 아니면 400", st == 400, str(body))
        st, body = _life_post(tapi, "/api/life/refine",
                              _j0.dumps({"subject": {"id": "me"}, "nodes": [], "edges": []}).encode("utf-8"))
        check("다듬는 길은 모델 없이 200", st == 200 and "nodes" in body, str(body)[:120])
        st, body = _life_post(tapi, "/api/life/analyze", b'{"text": "\uc774\uc57c\uae30"}')
        check("로컬은 띄우고 202 로 물러난다", st == 202 and body["state"] == "running", str(body)[:120])
        for _ in range(200):
            if _LIFE_JOBS.status()["state"] != "running":
                break
            time.sleep(0.02)
    finally:
        _backends.build_backend = keep_build
    check("두 길의 이름은 한 곳에 있다", _LIFE_POSTS == ("/api/life/analyze", "/api/life/refine"))

    # 모델이 답을 안 줬을 때 **까닭을 한국어로** 말한다. 까닭을 말해야 사람이
    # 다음에 뭘 할지 안다 — 붐비면 다시 누르면 되고, 열쇠가 없으면 소용없다.
    # 상류가 주는 말은 영어라 화면에 옮기지 않는다 (CLAUDE.md §1).
    from histgraph.server import model_silence as _silence  # noqa: E402

    check("붐비는 것과 멎은 것과 열쇠 없는 것을 갈라 말한다",
          "붐빕" in _silence("HTTP 429: rate limit")
          and "응답하지 않" in _silence("HTTP 503: busy")
          and "응답하지 않" in _silence("연결 실패: timed out")
          and "준비되지 않" in _silence("OPENROUTER_API_KEY 없음")
          and "돌려주지 않" in _silence("답에 choices 가 없음"))
    check("어느 문구에도 영어가 없다",
          not any(ch.isascii() and ch.isalpha() for w in
                  ("HTTP 429", "HTTP 503", "연결 실패", "OPENROUTER_API_KEY 없음", "")
                  for ch in _silence(w)))
    # 모델이 답을 안 주면 그 까닭이 답에 실려 온다 (화면은 안 그리고, 사람이 물어볼 때 쓴다).
    class _Silent(_FakeLife):
        last_error = "HTTP 429: rate limited"
        def complete_json(self, *a, **kw):
            return None
    _backends.build_backend = lambda kind, model=None: _Silent()
    try:
        st, body = _life_post(tapi, "/api/life/analyze", b'{"text": "x"}', blocking=True, save=False)
        check("답이 없으면 까닭을 한국어로, 원문은 detail 로",
              st == 500 and "붐빕" in body["error"] and "429" in body["detail"], str(body)[:200])
    finally:
        _backends.build_backend = keep_build

    # 화면이 기다리는 모습을 여기서 가른다 — 창을 닫아도 되는지가 이것으로 갈린다.
    _keep_vercel = _osl.environ.pop("VERCEL", None)
    try:
        check("로컬은 물어 가는 길이라고 알린다", _LifeJob().status()["blocking"] is False)
        _osl.environ["VERCEL"] = "1"
        check("배포는 답이 한 번에 온다고 알린다", _LifeJob().status()["blocking"] is True)
    finally:
        _osl.environ.pop("VERCEL", None)
        if _keep_vercel is not None:
            _osl.environ["VERCEL"] = _keep_vercel

    # --- 학제의 차례 (2026-09-08 사용자: "초등학교 졸업을 해야 중학교 입학을 하지.
    # 같은 연도에 일어난 일이지만 월을 입력 하지 않아서 … 논리상 초등학교 졸업이
    # 무조건 먼저 일어나야 하잖아?") — 달을 모르는 차례는 모델이 아니라 규칙이 정한다.
    ev = lambda name, desc=None: {"type": "PersonalEvent", "name": name, "description": desc}
    check("사다리 — 초등 입학 10 · 초등 졸업 12 · 중학 입학 20 · 대학 졸업 42 · 대학원 50",
          [life_mod.ladder(ev(x)) for x in ("성일초등학교 입학", "성내초등학교 졸업", "성내중학교 입학",
                                            "퍼듀대학교 졸업", "대학원 입학")] == [10, 12, 20, 42, 50])
    check("학제와 무관한 것은 사다리에 없다",
          life_mod.ladder(ev("미국으로 이주")) is None
          and life_mod.ladder({"type": "School", "name": "성내중학교"}) is None)
    check("이름이 층을 말하면 설명은 안 본다 (설명은 앞뒤를 같이 말한다)",
          life_mod.ladder(ev("성내중학교 입학", "성내초등학교를 졸업하고 성내중학교에 입학함")) == 20)
    ordered = life_mod.refine({
        "subject": {"id": "me", "birth_year": 1982},
        "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                  {"id": "ms_in", "type": "PersonalEvent", "name": "성내중학교 입학", "year": 1994},
                  {"id": "move", "type": "PersonalEvent", "name": "이사", "year": 1994},
                  {"id": "es_out", "type": "PersonalEvent", "name": "성내초등학교 졸업", "year": 1994}],
        "edges": [],
        "timeline": [{"event_id": "ms_in", "life_stage": "중학교", "year": 1994},
                     {"event_id": "move", "life_stage": "어린 시절", "year": 1994},
                     {"event_id": "es_out", "life_stage": "초등학교", "year": 1994}],
    })
    check("같은 해면 초등 졸업이 중학 입학보다 먼저 선다 (사다리에 없는 것은 제자리)",
          [t["event_id"] for t in ordered["timeline"]] == ["es_out", "move", "ms_in"],
          str([t["event_id"] for t in ordered["timeline"]]))
    check("앞뒤도 다시 이어 준다", ordered["timeline"][0]["next_event"] == "move"
          and ordered["timeline"][2]["previous_event"] == "move")
    crossed = life_mod.refine({
        "subject": {"id": "me", "birth_year": 1982},
        "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                  {"id": "ms_in", "type": "PersonalEvent", "name": "성내중학교 입학", "year": 1993},
                  {"id": "es_out", "type": "PersonalEvent", "name": "성내초등학교 졸업", "year": 1994}],
        "edges": [],
        "timeline": [{"event_id": "ms_in", "life_stage": "중학교", "year": 1993},
                     {"event_id": "es_out", "life_stage": "초등학교", "year": 1994}],
    })
    check("해가 사다리를 어기면 해가 틀린 것이라 알린다 (연표는 해의 축 위에 선다)",
          any("차례가 어긋난다" in n and "성내중학교 입학(1993)" in n for n in crossed.get("notes") or []),
          str(crossed.get("notes")))

    # --- 정정 — 나중에 한 말이 앞서 한 말을 이긴다 (실측: 고쳐 말했는데 1993 이 남았다)
    base_g = {"subject": {"id": "me", "birth_year": 1982},
              "nodes": [{"id": "me", "type": "Person", "name": "나", "start_date": "1982", "year": 1982},
                        {"id": "ms_in", "type": "PersonalEvent", "name": "성내중학교 입학",
                         "start_date": "1993-03-01", "year": 1993, "precision": "exact"}],
              "edges": [], "timeline": [{"event_id": "ms_in", "life_stage": "중학교",
                                         "date_text": "1993-03-01", "age": 11, "year": 1993}]}
    add_g = {"nodes": [{"id": "ms_entry_1994", "type": "PersonalEvent", "name": "성내중학교 입학",
                        "start_date": "1994", "year": 1994, "precision": "year"}],
             "edges": [], "timeline": []}
    said = "성내중학교 입학년도를 잘못 말했어 1994년에 입학해서 1997년에 졸업했어."
    fixed_g, _ = life_mod.merge(base_g, add_g, said)
    node_g = {n["id"]: n for n in fixed_g["nodes"]}["ms_in"]
    check("고쳐 말한 해가 앞서 든 해를 이긴다 (노드도 연표도)",
          node_g["year"] == 1994 and node_g["start_date"] == "1994"
          and fixed_g["timeline"][0]["year"] == 1994 and fixed_g["timeline"][0]["age"] == 12, str(node_g))
    check("무엇을 고쳤는지 적는다", any("이야기가 고쳐 말했다" in n for n in fixed_g.get("notes") or []),
          str(fixed_g.get("notes")))
    kept_g, _ = life_mod.merge(base_g, {"nodes": [dict(add_g["nodes"][0], start_date="1995", year=1995)],
                                        "edges": [], "timeline": []}, said)
    check("이야기에 없는 해로는 덮지 않는다 (모델이 흐릿하게 되뇐 것)",
          {n["id"]: n for n in kept_g["nodes"]}["ms_in"]["year"] == 1993)
    kept2_g, _ = life_mod.merge(base_g, add_g, None)
    check("이야기를 모르면 고치지 않는다", {n["id"]: n for n in kept2_g["nodes"]}["ms_in"]["year"] == 1993)

    life_mod.LIFE_DIR = keep_dir
    check("개인 자료 폴더는 저장소 밖", "data/life/" in (Path(__file__).resolve().parents[1] / ".gitignore").read_text())


print("\n[가입·로그인 — 세션·CSRF·열린 리다이렉트 (auth)]")
# 네트워크도 DB 도 안 쓴다. 여기서 재는 것은 **틀리면 계정이 털리는 자리**다.
import json as _js  # noqa: E402
import os as _os  # noqa: E402
import time as _tm  # noqa: E402

import histgraph.auth as _auth  # noqa: E402
import histgraph.neon as _neon  # noqa: E402
import histgraph.neon as neon_mod  # noqa: E402

_keep_env = {k: _os.environ.get(k) for k in
             ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
              "HISTGRAPH_SESSION_SECRET", "DATABASE_URL", "HISTGRAPH_ADMIN_EMAILS")}
try:
    _os.environ["HISTGRAPH_SESSION_SECRET"] = "x" * 48

    # --- 서명 ---------------------------------------------------------
    signed = _auth._sign(b'{"s":"abc"}')
    check("서명한 값을 되읽는다", _auth._unsign(signed) == b'{"s":"abc"}')
    body, _, sig = signed.partition(".")
    check("값을 바꾸면 서명이 안 맞는다",
          _auth._unsign(_auth.b64u(b'{"s":"evil"}') + "." + sig) is None)
    check("서명만 있고 값이 없으면 버린다", _auth._unsign(".abc") is None)
    check("점이 없으면 버린다", _auth._unsign("abc") is None)
    _os.environ["HISTGRAPH_SESSION_SECRET"] = "y" * 48
    check("열쇠가 바뀌면 옛 서명은 죽는다", _auth._unsign(signed) is None)
    _os.environ["HISTGRAPH_SESSION_SECRET"] = "x" * 48

    # --- CSRF 표 ------------------------------------------------------
    t1, t2 = "session-one", "session-two"
    check("CSRF 표는 세션마다 다르다", _auth.csrf_token(t1) != _auth.csrf_token(t2))
    check("같은 세션이면 같은 표", _auth.csrf_token(t1) == _auth.csrf_token(t1))

    # --- 열린 리다이렉트 -------------------------------------------------
    # 이걸 놓치면 우리 주소로 시작하는 피싱 링크가 만들어진다.
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example",
                "evil.example", "/n/x\r\nSet-Cookie: a=b"):
        check(f"바깥으로 나가는 next 를 막는다 ({bad[:22]})", _auth._safe_next(bad) == "/")
    check("우리 안의 경로는 그대로 둔다", _auth._safe_next("/n/wd:Q1?a=1#b") == "/n/wd:Q1?a=1#b")

    # --- Host 헤더를 믿지 않는다 ------------------------------------------
    check("모르는 Host 는 배포 주소로 친다", _auth.origin_for("evil.example") == _auth.SITE)
    check("Host 가 없어도 배포 주소", _auth.origin_for(None) == _auth.SITE)
    check("로컬 되돌이 주소는 포트를 가리지 않는다",
          _auth.origin_for("127.0.0.1:8100") == "http://127.0.0.1:8100"
          and _auth.origin_for("localhost:5173") == "http://localhost:5173"
          and _auth.origin_for("[::1]:8123") == "http://[::1]:8123")
    _os.environ["VERCEL"] = "1"
    check("배포에서는 Host 를 아예 보지 않는다",
          _auth.origin_for("127.0.0.1:8100") == _auth.SITE)
    _os.environ.pop("VERCEL", None)

    # --- 쿠키 ----------------------------------------------------------
    jar = _auth.parse_cookies('a=1; __Host-hg_session=tok=en; b="q"')
    check("쿠키를 첫 = 에서만 자른다", jar["__Host-hg_session"] == "tok=en")
    check("따옴표를 벗긴다", jar["b"] == "q")
    made = _auth.set_cookie("__Host-hg_session", "v", secure=True, max_age=60)
    check("세션 쿠키는 HttpOnly·Secure·SameSite 를 다 든다",
          "HttpOnly" in made and "Secure" in made and "SameSite=Lax" in made
          and "Path=/" in made, made)
    check("http 에서는 Secure 를 붙이지 않는다 (개발)",
          "Secure" not in _auth.set_cookie("hg_session", "v", secure=False, max_age=60))
    check("https 에서는 __Host- 를 붙인다",
          _auth.cookie_name("hg_session", True) == "__Host-hg_session"
          and _auth.cookie_name("hg_session", False) == "hg_session")

    # https 요청은 접두사 없는 쿠키를 **보지 않는다** — 하위 도메인이 심어 둔
    # 것이 이기면 접두사를 붙인 뜻이 없어진다 (세션 고정).
    req = _auth.Request("GET", "/api/me", {},
                        {"Host": "www.histgraph.space", "Cookie": "hg_session=심은것"})
    check("https 에서 접두사 없는 세션 쿠키는 무시한다", req.cookie(_auth.COOKIE_SESSION) == "")
    req2 = _auth.Request("GET", "/api/me", {},
                         {"Host": "www.histgraph.space", "Cookie": "__Host-hg_session=진짜"})
    check("https 에서 __Host- 쿠키는 읽는다", req2.cookie(_auth.COOKIE_SESSION) == "진짜")

    # --- 응답은 캐시에 재우지 않는다 ---------------------------------------
    # 배포는 /api 를 엣지에 하루 재운다. 이게 뚫리면 한 사람의 신원이
    # 다음 사람에게 배달된다.
    heads = dict(_auth.Response.json({"user": None}).headers)
    check("계정 응답은 no-store 다", heads["Cache-Control"] == "private, no-store", str(heads))
    check("쿠키에 따라 갈린다고 적는다", heads.get("Vary") == "Cookie")
    check("302 도 no-store 다",
          dict(_auth.Response.redirect("/").headers)["Cache-Control"] == "private, no-store")
    check("Location 에 줄바꿈을 싣지 않는다",
          "\n" not in dict(_auth.Response.redirect("/a\r\nX: 1").headers)["Location"])

    # --- ID 토큰의 주장 ---------------------------------------------------
    _os.environ["GOOGLE_CLIENT_ID"] = "our-app.apps.googleusercontent.com"
    good = {"iss": "https://accounts.google.com", "aud": "our-app.apps.googleusercontent.com",
            "exp": _tm.time() + 600, "nonce": "n1", "sub": "1", "email": "a@b.c",
            "email_verified": True}
    _auth._check_claims(dict(good), "n1")     # 안 터지면 통과
    check("바른 토큰은 지나간다", True)
    for name, bad in (
        ("남의 앱에 발급된 것", {**good, "aud": "other.apps.googleusercontent.com"}),
        ("발급자가 구글이 아닌 것", {**good, "iss": "https://evil.example"}),
        ("만료된 것", {**good, "exp": _tm.time() - 1}),
        ("이번 요청의 것이 아닌 것(nonce)", {**good, "nonce": "n2"}),
        ("확인되지 않은 이메일", {**good, "email_verified": False}),
    ):
        try:
            _auth._check_claims(dict(bad), "n1")
            check(f"{name}을 막는다", False, "지나갔다")
        except _auth.AuthError:
            check(f"{name}을 막는다", True)

    made = _auth.decode_id_token(
        _auth.b64u(b'{"alg":"RS256"}') + "." + _auth.b64u(b'{"sub":"9"}') + ".sig")
    check("ID 토큰의 가운데 마디를 읽는다", made == {"sub": "9"})

    # --- 표 --------------------------------------------------------------
    check("로그아웃은 POST 만 (GET 링크 하나로 남을 로그아웃시킬 수 없다)",
          _auth.ROUTES["/api/auth/logout"][0] == frozenset({"POST"}))
    check("탈퇴는 DELETE /api/me", "DELETE" in _auth.ROUTES["/api/me"][0])

    # --- 꺼져 있을 때 -----------------------------------------------------
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "DATABASE_URL"):
        _os.environ.pop(k, None)
    check("설정이 없으면 기능이 꺼진다", _auth.enabled() is False)
    off = _auth.route(_auth.Request("GET", "/api/me", {}, {"Host": "x"}))
    check("꺼져 있어도 /api/me 는 답한다 (화면이 단추를 안 세운다)",
          off.status == 200 and _js.loads(off.body)["enabled"] is False)
    off2 = _auth.route(_auth.Request("POST", "/api/auth/logout", {}, {"Host": "x"}))
    check("꺼져 있으면 나머지는 503", off2.status == 503)
    check("가입과 무관한 길은 넘긴다 (그래프 쪽으로)",
          _auth.route(_auth.Request("GET", "/api/meta", {}, {"Host": "x"})) is None)

    # --- Neon 주소 --------------------------------------------------------
    check("연결 문자열에서 HTTP 질의 주소를 만든다",
          _neon.sql_endpoint("postgresql://u:p@ep-cool-1.ap-northeast-2.aws.neon.tech/db")
          == "https://api.ap-northeast-2.aws.neon.tech/sql")
    check("-pooler 호스트도 같은 자리로",
          _neon.sql_endpoint("postgresql://u:p@ep-cool-1-pooler.us-east-2.aws.neon.tech/db")
          == "https://api.us-east-2.aws.neon.tech/sql")
    check("오류 메시지에 비밀번호를 싣지 않는다",
          "s3cret" not in _neon._scrub("postgres://u:s3cret@h/db 에 못 닿음"))
finally:
    for k, v in _keep_env.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v


print("\n[가입·로그인 — 왕복 전체를 실제로 돌려 본다]")
# 구글에 나가는 한 번(`_exchange`)만 가짜로 끼우고, 나머지는 **진짜 코드**다 —
# 쿠키를 굽고 세션을 만들고 표에 적고 다시 읽는다. 표는 로컬 SQLite
# (accounts.LocalStore) 라 계정도 네트워크도 필요 없다.
import histgraph.accounts as _acct  # noqa: E402

_keep2 = {k: _os.environ.get(k) for k in
          ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "HISTGRAPH_SESSION_SECRET",
           "DATABASE_URL", "HISTGRAPH_ADMIN_EMAILS", "HISTGRAPH_ACCOUNTS_DB", "VERCEL")}
_tmp = tempfile.TemporaryDirectory()
try:
    _os.environ.pop("DATABASE_URL", None)
    _os.environ.pop("VERCEL", None)
    _os.environ["GOOGLE_CLIENT_ID"] = "our-app.apps.googleusercontent.com"
    _os.environ["GOOGLE_CLIENT_SECRET"] = "s3cret"
    _os.environ["HISTGRAPH_SESSION_SECRET"] = "z" * 48
    _os.environ["HISTGRAPH_ADMIN_EMAILS"] = "boss@example.com"

    store = _acct.LocalStore()
    store.path = Path(_tmp.name) / "accounts.sqlite"
    _acct.init_schema(store)
    _auth._db = store
    check("설정이 갖춰지면 켜진다 (표는 로컬 SQLite)", _auth.enabled() is True)

    def req(method, path, q=None, cookies="", body=b"", extra=None):
        head = {"Host": "127.0.0.1:8100", "Cookie": cookies}
        head.update(extra or {})
        return _auth.Request(method, path, q or {}, head, body)

    # 1) 동의 화면으로 — 서명 쿠키에 state·검증자·nonce 가 담긴다
    started = _auth.route(req("GET", "/api/auth/google", {"next": ["/n/wd:Q1"]}))
    heads = dict(started.headers)
    check("동의 화면으로 보낸다", started.status == 302
          and heads["Location"].startswith(_auth.GOOGLE_AUTH)
          and "code_challenge_method=S256" in heads["Location"])
    tx_cookie = heads["Set-Cookie"].split(";")[0]
    tx = _js.loads(_auth._unsign(tx_cookie.split("=", 1)[1]))

    # 쿠키가 안에 적은 시각보다 먼저 죽으면, 오래 걸린 사람에게 '쿠키가
    # 막혀 있다'는 엉뚱한 말이 뜬다 (2026-09-09 지적).
    _maxage = int(next(b.split("=")[1] for b in heads["Set-Cookie"].split("; ")
                       if b.startswith("Max-Age=")))
    check("왕복 쿠키는 안에 적은 시각보다 오래 산다", _maxage > _auth.TX_TTL)

    # 없는 것과 맞지 않는 것을 갈라 말한다 — 둘 다 400 이지만 문장이 다르다.
    _no_cookie = _auth.route(req("GET", "/api/auth/callback",
                                 {"code": ["c"], "state": [tx["s"]]})).body.decode()
    _bad_sign = _auth.route(req("GET", "/api/auth/callback",
                                {"code": ["c"], "state": [tx["s"]]},
                                cookies="hg_oauth=" + tx_cookie.split("=", 1)[1][:-4]
                                        + "AAAA")).body.decode()
    check("쿠키가 없을 때와 서명이 틀릴 때를 갈라 말한다",
          "쿠키를 막고" in _no_cookie and "이 서버의 것이 아닙니다" in _bad_sign)
    check("실패 화면은 다시 시작할 자리를 준다", "/api/auth/google" in _no_cookie)

    # 2) 구글이 돌려보낸 자리. 토큰 교환만 가로챈다.
    seen = {}
    def fake_exchange(code, verifier, redirect_uri):
        seen.update(code=code, verifier=verifier, redirect_uri=redirect_uri)
        return {"iss": "https://accounts.google.com",
                "aud": "our-app.apps.googleusercontent.com",
                "exp": _tm.time() + 600, "nonce": tx["n"], "sub": "google-sub-1",
                "email": "Boss@Example.com", "email_verified": True,
                "name": "홍길동", "picture": "https://lh3.example/photo"}
    keep_exchange, _auth._exchange = _auth._exchange, fake_exchange
    try:
        done = _auth.route(req("GET", "/api/auth/callback",
                               {"code": ["the-code"], "state": [tx["s"]]},
                               cookies=tx_cookie))
    finally:
        _auth._exchange = keep_exchange

    check("PKCE 검증자를 함께 보낸다", seen.get("verifier") == tx["v"])
    check("redirect_uri 는 이 요청이 사는 주소다",
          seen.get("redirect_uri") == "http://127.0.0.1:8100/api/auth/callback")
    dh = [v for k, v in done.headers if k == "Set-Cookie"]
    check("로그인을 마치면 원래 자리로 돌려보낸다",
          done.status == 302 and dict(done.headers)["Location"] == "/n/wd:Q1")
    session = next(c.split(";")[0].split("=", 1)[1] for c in dh if c.startswith("hg_session="))
    csrf = next(c.split(";")[0].split("=", 1)[1] for c in dh if c.startswith("hg_csrf="))
    check("왕복 쿠키는 지운다", any(c.startswith("hg_oauth=;") for c in dh), str(dh))
    check("세션 쿠키는 자바스크립트가 못 읽는다",
          all("HttpOnly" in c for c in dh if c.startswith("hg_session=")))
    check("CSRF 표는 자바스크립트가 읽어야 한다",
          all("HttpOnly" not in c for c in dh if c.startswith("hg_csrf=")))

    # 쿠키 값 자체는 어디에도 안 적혀 있다 — 해시만.
    rows = store.query("select token_hash from sessions", [])
    check("세션은 해시로만 저장된다",
          len(rows) == 1 and rows[0]["token_hash"] != session
          and rows[0]["token_hash"] == _auth._hash_token(session))

    # 3) 가입자 한 줄이 생겼다
    user = store.one("select * from users", [])
    check("가입자 한 줄이 생긴다 (이메일은 소문자로도 남는다)",
          user["google_sub"] == "google-sub-1" and user["email"] == "Boss@Example.com"
          and user["email_lower"] == "boss@example.com")

    jar = f"hg_session={session}"
    csrf_head = {"X-Histgraph-CSRF": csrf, "Origin": "http://127.0.0.1:8100"}

    me = _js.loads(_auth.route(req("GET", "/api/me", cookies=jar)).body)
    check("/api/me 가 나를 알아본다",
          me["user"]["이름"] == "홍길동" and me["user"]["이메일"] == "Boss@Example.com")
    check("관리자를 가려낸다 (대소문자 무관)", me["user"]["관리자"] is True)
    check("프로필 사진을 그대로 준다", me["user"]["사진"] == "https://lh3.example/photo")
    check("남의 쿠키로는 아무도 아니다",
          _js.loads(_auth.route(req("GET", "/api/me", cookies="hg_session=지어낸값")).body)["user"] is None)

    # 3-2) 관리실(`/console`) — **문은 서버에서 잠근다.** 화면에서 단추를
    # 감추는 것은 잠금이 아니다: 주소를 직접 치면 열린다.
    anon = _auth.route(req("GET", "/console"))
    check("로그인하지 않으면 관리실이 열리지 않는다",
          anon.status == 401 and "Boss@Example.com" not in anon.body.decode())
    check("관리실 문 앞에서 로그인하면 다시 관리실로 돌아온다",
          "next=/console" in anon.body.decode())

    _os.environ["HISTGRAPH_ADMIN_EMAILS"] = "someone-else@example.com"
    outsider = _auth.route(req("GET", "/console", cookies=jar))
    _os.environ["HISTGRAPH_ADMIN_EMAILS"] = "boss@example.com"
    check("관리자가 아니면 가입자를 볼 수 없다 (몇 명인지도)",
          outsider.status == 403 and "Boss@Example.com" not in outsider.body.decode())

    room = _auth.route(req("GET", "/console", cookies=jar))
    _room = room.body.decode()
    check("관리자에게는 가입자 목록이 보인다",
          room.status == 200 and "Boss@Example.com" in _room and "홍길동" in _room)
    check("관리실은 어디에도 재우지 않는다",
          ("Cache-Control", "private, no-store") in room.headers
          and ("Vary", "Cookie") in room.headers)
    check("관리실은 검색에 담기지 않는다", 'content="noindex,nofollow"' in _room)
    # 두 저장소 다 세계시로 적는다 — 그대로 세우면 저녁에 온 사람이 오전에
    # 온 것으로 보인다. 시간대가 없으면 세계시로 친다.
    import histgraph.console as _con  # noqa: E402
    check("가입 시각은 한국 시각으로 세운다",
          _con.when("2026-09-08 18:57:56.299034+00") == "2026-09-09 03:57"
          and _con.when("2026-09-08 18:57:56") == "2026-09-09 03:57",
          _con.when("2026-09-08 18:57:56"))
    # §1 — 사람이 읽는 자리에 한글 아닌 글을 세우지 않는다. **가입자의
    # 이메일과 이름만이 예외다**: 우리가 쓴 글이 아니라 그 사람의 것이다.
    _seen = re.sub(r"<[^>]+>", " ", _room[_room.find("<main"):_room.find("</main>")])
    for _mine in ("Boss@Example.com", "홍길동"):
        _seen = _seen.replace(_mine, "")
    check("관리실 글자에 영어가 없다 (가입자의 이메일·이름 말고는)",
          not re.search(r"[A-Za-z]", _seen), _seen.strip()[:120])
    # 배포에서는 rewrite 가 `/api/console` 로 넘긴다 (vercel.json) — 같은 장이다.
    check("배포 경로(/api/console)도 같은 장을 낸다",
          _auth.route(req("GET", "/api/console", cookies=jar)).body == room.body)

    # 4) 즐겨찾기 — 담고, 읽고, 뺀다
    _auth.route(req("POST", "/api/my/bookmarks", cookies=jar, extra=csrf_head,
                    body=b'{"id":"wd:Q1","label":"\xec\x84\xb8\xec\xa2\x85","note":"\xeb\x82\x98\xec\xa4\x91\xec\x97\x90"}'))
    got = _js.loads(_auth.route(req("GET", "/api/my/bookmarks", cookies=jar)).body)
    check("즐겨찾기를 담고 읽는다",
          got["목록"][0]["id"] == "wd:Q1" and got["목록"][0]["이름"] == "세종"
          and got["목록"][0]["메모"] == "나중에", str(got))
    _auth.route(req("DELETE", "/api/my/bookmarks", {"id": ["wd:Q1"]}, cookies=jar, extra=csrf_head))
    check("빼면 없어진다",
          _js.loads(_auth.route(req("GET", "/api/my/bookmarks", cookies=jar)).body)["목록"] == [])

    # 5) 내 역사 — 올리고 내린다
    _auth.route(req("PUT", "/api/my/life", cookies=jar, extra=csrf_head,
                    body='{"doc":{"nodes":[{"id":"me","name":"나"}]}}'.encode()))
    life = _js.loads(_auth.route(req("GET", "/api/my/life", cookies=jar)).body)
    check("내 역사를 계정에 담고 되읽는다", life["doc"]["nodes"][0]["name"] == "나", str(life)[:120])

    # 5-2) **내 역사의 문 (배포 함수)** — 이야기를 모델에게 보내는 길은
    # 로그인한 사람의 것만 받는다. 이 관문이 없으면 남의 사이트가 이 사람의
    # 브라우저로 우리 모델을 부를 수 있다 (2026-09-09 배포와 함께 낸 길).
    import importlib.util as _ilu  # noqa: E402  (여기서만 쓴다)

    _spec = _ilu.spec_from_file_location(
        "vercel_api", Path(__file__).resolve().parents[1] / "api" / "index.py")
    _vapi = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_vapi)

    def gate(cookies="", extra=None):
        """배포 함수의 `_life_gate` 를 그대로 부른다 → (막았나, (상태, 몸))."""
        h = _vapi.handler.__new__(_vapi.handler)
        h.command, h.path = "POST", "/api/life/analyze"
        h.headers = {"Host": "127.0.0.1:8100", "Cookie": cookies, **(extra or {})}
        said = []
        h._json = lambda status, payload: said.append((status, payload))
        return h._life_gate(b'{"text": "\uc774\uc57c\uae30"}'), (said[0] if said else (None, None))

    check("배포 함수가 개인 역사의 POST 를 받는다",
          _vapi.LIFE_POSTS == ("/api/life/analyze", "/api/life/refine"))

    # 배포 번들에 **패키지가 읽는 파일**이 실리는가. 파이썬 런타임은 임포트를
    # 따라간 `.py` 만 담으므로 그 밖의 파일은 `includeFiles` 로 이름을 대야 하고,
    # `excludeFiles` 에 걸려서도 안 된다. 2026-09-09 실측: 배포에서 이야기를
    # 보내면 `src/histgraph/life_prompt.md` 가 없다며 FileNotFoundError 로
    # 떨어졌다 — 문서를 뺀다고 `*.md` 를 적은 것이 하나, 이름을 안 댄 것이 하나.
    import fnmatch as _fn  # noqa: E402

    _root = Path(__file__).resolve().parents[1]
    _ex = _js.loads((_root / "vercel.json").read_text(encoding="utf-8"))
    _pats = _ex["functions"]["api/index.py"]["excludeFiles"].strip("{}").split(",")
    _needed = [q for q in (_root / "src").rglob("*")
               if q.is_file() and q.suffix != ".py" and "__pycache__" not in q.parts]
    # 걷어내는 자리가 **둘**이다 — `vercel.json` 의 excludeFiles 와 `.vercelignore`.
    # 뒤엣것은 "CLI 로 올릴 때만 쓰인다"고 적혀 있었지만 Git 연동 배포도 본다.
    _pats += [ln.strip() for ln in (_root / ".vercelignore").read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.strip().startswith(("#", "!"))]
    _cut = [str(q.relative_to(_root)) for q in _needed
            if any(_fn.fnmatch(str(q.relative_to(_root)), pat) or _fn.fnmatch(q.name, pat)
                   for pat in _pats)]
    _inc = _ex["functions"]["api/index.py"].get("includeFiles", "")
    _missed = [str(q.relative_to(_root)) for q in _needed
               if not _fn.fnmatch(str(q.relative_to(_root)), _inc)]
    check("배포 번들이 패키지가 읽는 파일을 걷어내지 않는다 (두 자리 다)",
          not _cut and any(q.name == "life_prompt.md" for q in _needed), str(_cut))
    check("배포 번들이 패키지가 읽는 파일을 이름 대어 싣는다", not _missed, str(_missed))
    blocked, (st, body) = gate()
    check("로그인 없이 이야기를 보내면 401",
          blocked is True and st == 401 and body["error"] == "로그인이 필요합니다.", str((st, body)))
    blocked, (st, body) = gate(cookies=jar)
    check("로그인해도 표가 없으면 400 (남의 사이트가 쏜 요청)",
          blocked is True and st == 400, str((st, body)))
    blocked, _ = gate(cookies=jar, extra=csrf_head)
    check("로그인하고 표가 맞으면 지나간다", blocked is False)
    # 로컬 서버와 반대다 — 열린 인터넷에서 문을 안 잠그면 아무나 우리 모델을 부른다.
    _keep_cid = _os.environ.pop("GOOGLE_CLIENT_ID", None)
    try:
        blocked, (st, body) = gate(cookies=jar, extra=csrf_head)
        check("가입이 안 열린 배포에서는 내 역사를 아예 안 받는다 (503)",
              blocked is True and st == 503 and "로그인이 아직" in body["error"], str((st, body)))
    finally:
        if _keep_cid is not None:
            _os.environ["GOOGLE_CLIENT_ID"] = _keep_cid

    # 6) 로그아웃 — **서버에서** 지운다
    out = _auth.route(req("POST", "/api/auth/logout", cookies=jar, extra=csrf_head))
    check("로그아웃은 세션을 서버에서 지운다",
          out.status == 200 and store.query("select 1 from sessions", []) == [])
    check("지워진 세션으로는 못 들어온다",
          _js.loads(_auth.route(req("GET", "/api/me", cookies=jar)).body)["user"] is None)

    # 7) 회원 탈퇴 — 담아 둔 것까지 한 트랜잭션으로
    started2 = _auth.route(req("GET", "/api/auth/google"))
    tx2c = dict(started2.headers)["Set-Cookie"].split(";")[0]
    tx2 = _js.loads(_auth._unsign(tx2c.split("=", 1)[1]))
    def fake2(code, verifier, redirect_uri):
        return {**fake_exchange(code, verifier, redirect_uri), "nonce": tx2["n"]}
    keep_exchange, _auth._exchange = _auth._exchange, fake2
    try:
        done2 = _auth.route(req("GET", "/api/auth/callback",
                                {"code": ["c"], "state": [tx2["s"]]}, cookies=tx2c))
    finally:
        _auth._exchange = keep_exchange
    check("두 번째 로그인은 가입자를 새로 만들지 않는다 (sub 이 열쇠)",
          len(store.query("select id from users", [])) == 1)
    s2 = next(v.split(";")[0].split("=", 1)[1]
              for k, v in done2.headers if k == "Set-Cookie" and v.startswith("hg_session="))
    jar2 = f"hg_session={s2}"
    head2 = {"X-Histgraph-CSRF": _auth.csrf_token(s2), "Origin": "http://127.0.0.1:8100"}
    _auth.route(req("POST", "/api/my/bookmarks", cookies=jar2, extra=head2, body=b'{"id":"wd:Q2"}'))
    gone = _auth.route(req("DELETE", "/api/me", cookies=jar2, extra=head2))
    check("탈퇴하면 가입자·세션·담아 둔 것이 함께 사라진다",
          gone.status == 200
          and store.query("select 1 from users", []) == []
          and store.query("select 1 from sessions", []) == []
          and store.query("select 1 from bookmarks", []) == []
          and store.query("select 1 from life_docs", []) == [])

    # 로컬과 배포의 표가 어긋나면 로컬에서 되던 것이 배포에서 깨진다
    import re as _re
    def cols(ddl, table):
        body = _re.search(rf"create table if not exists {table} \((.*?)\n\);", ddl, _re.S).group(1)
        return {ln.strip().split()[0] for ln in body.strip().splitlines()
                if ln.strip() and not ln.strip().startswith("primary key")}
    for t in ("users", "sessions", "life_docs", "bookmarks"):
        check(f"로컬 표와 Neon 표의 열이 같다 ({t})",
              cols(_acct.SCHEMA, t) == cols(neon_mod.SCHEMA, t),
              str(cols(_acct.SCHEMA, t) ^ cols(neon_mod.SCHEMA, t)))

    # 배포에서는 파일로 물러나지 않는다 — 물러나면 가입자가 조용히 사라진다
    _os.environ["VERCEL"] = "1"
    check("배포에서 DATABASE_URL 이 없으면 꺼진다", _auth.enabled() is False)
    try:
        _acct.open_store()
        check("배포에서는 SQLite 로 물러나지 않는다", False, "물러났다")
    except _acct.StoreError:
        check("배포에서는 SQLite 로 물러나지 않는다", True)
finally:
    _auth._db = None
    _tmp.cleanup()
    for k, v in _keep2.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v

print(f"\n{'='*46}\n통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
