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
          == [("wd:Q28179", 1392, 1897)], str(era_mark))
    # 왕조를 고르면 그건 '자기 자리'다. 둘 다 세우면 같은 줄이 두 번 찍힌다.
    own = tl_api.timeline("wd:Q28179")
    check("왕조를 고르면 자기 자리로만 선다",
          [m["kind"] for m in own["marks"] if m["id"] == "wd:Q28179"] == ["self"],
          str([m for m in own["marks"] if m["id"] == "wd:Q28179"]))
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
check("원인·결과는 원인에서 결과로 한 방향", ("Q3", "Q1", "related_to", "원인") in side, str(side))
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
             aliases=["갑오경장"]),
        Node(id="wd:EV2", type="event", label="무신정변", source="wd",
             props={"polity": "고려"}),
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
    dest.close()
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

    check("묶음은 시대 여럿으로 풀린다", sc.eras_of("korea") == ("joseon", "ilje", "daehan"))
    check("시대 이름은 자기 자신으로 풀린다", sc.eras_of("joseon") == ("joseon",))
    # 화면 머리말은 서버가 준다. 모르는 키에 영어를 내보내면 안 된다.
    check("묶음 이름은 한국어다", sc.label_of("korea") == "조선~대한민국")
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
    check("조선~대한민국이 한 묶음이다",
          sc2.eras_of("korea") == ("joseon", "ilje", "daehan") and sc2.label_of("korea") == "조선~대한민국")
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


print(f"\n{'='*46}\n통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
