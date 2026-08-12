"""파이프라인 스모크 테스트 (네트워크 불필요).

  PYTHONPATH=src python3 tests/test_pipeline.py

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

print(f"\n{'='*46}\n통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
