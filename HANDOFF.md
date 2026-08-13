# 인계 문서

새 세션이 맥락을 다시 파악하지 않고 바로 이어서 작업하기 위한 문서.
설계 배경과 실측 근거는 [README.md](README.md)에 있다. 여기는 **지금 상태와
다음에 할 일**만 적는다.

## 지금 상태 (2026-08-13)

```
전체 그래프   노드 37,173 · 엣지 57,330 · same_as 1,915
조선 그래프   노드  5,629 · participated_in 565   (data/joseon.sqlite)
테스트        97/97 통과   PYTHONPATH=src python3 tests/test_pipeline.py
```

수집 소스별 산출:

| 소스 | 인증 | 산출 |
|---|---|---|
| 국가유산청 | 불필요 | 유물 4,647 · 산문 2,903건 |
| Wikidata SPARQL | 불필요 | 인물 28,961 · 관계 골격 · 인물 별칭 1,643 (전체 별칭 4,846) |
| 한국어 위키백과 | 불필요(UA 필수) | 서사 1,327건 · 사건 103건 · 인포박스 관계 676건 |
| LLM 추출 (로컬 MLX) | 키 불필요 | 관계 969건 (participated_in 454) |
| 공공데이터포털 / 문화광장 | **활용신청 대기** | 0 |

## 환경

- **ANTHROPIC_API_KEY 없음.** `ant` CLI 미설치. 추출은 로컬 MLX 로만 돌아간다.
- 모델 `mlx-community/Qwen3.6-35B-A3B-8bit` 다운로드 완료 (35GB).
- **4bit 전환은 사용자가 명시적으로 거부함.** 속도 개선은 대상 축소로만.
- ollama 는 JSON 스키마를 무시하므로 쓰지 않는다 (`backends.py` 상단 참조).

## 다음에 할 일 (우선순위)

### 1. 신규 인물 485명 편입 — 효과 가장 큼
추출이 발굴한 신규식·이종일·길선주 등이 `ex:person:이름` 고아로 떠 있다.
전체 그래프에도 없는 인물들이다(Wikidata 국적 태그 누락). 위키백과 sitelink
로 QID 를 찾아 `wd:` 노드로 승격하면 생몰년·관계가 따라온다.

```
확인: SELECT COUNT(*) FROM nodes WHERE id LIKE 'ex:%';   -- 598개
```

### 2. 타입 오분류 69건
`조선총독부`·`민족대표 33인`이 `person` 으로 들어와 있다. 접미사 규칙
(`~부/청/원/국/회/단`, `N인`, `~일파`)으로 대부분 잡힌다.

### 3. 중간 저장 — 다음 대규모 추출 전 필수
`cmd_extract` 가 `_persist` 를 **마지막에 한 번만** 호출한다. 4시간짜리
작업이 중간에 죽으면 전부 잃는다. 조각 단위 저장으로 바꿀 것.

### 4. 왕대 환산표
`신라 진흥왕대`·`조선시대 초기 15세기` 같은 표기 332건이 연표에 못 붙어
있다. 왕별 재위 기간표를 만들면 `timeline.py` 가 연결할 수 있다.
**추정으로 채우지 말 것** — 틀린 연표가 만들어진다.

### 5. 프론트엔드
`store.neighbors()` 가 `same_as`·`dated_to` 까지 따라가는 서브그래프를
돌려준다. 조선 그래프는 이제 볼 만한 밀도가 됐다.

### 6. 다른 시대 확장
`python3 -m histgraph scope goryeo --out data/goryeo.sqlite` 로 같은
파이프라인이 돈다. 다만 `wikipedia.EVENT_SEEDS` 가 조선에 치우쳐 있어
시대별 시드 보강이 먼저다.

## 대규모 추출 전 반드시 확인할 것

과거 두 번 다 **첫 실행에서 배선 누락**이 드러났다. "기능을 만들었다"와
"그 경로를 실제로 탄다"는 다른 문제다.

```sh
# 1. 근거 검증이 켜져 있는가 (doc_text 가 넘어가는가)
grep -n "to_graph" src/histgraph/cli.py        # doc_text= 가 있어야 함

# 2. 가제티어가 범위 한정되는가
grep -n "build_gazetteer" src/histgraph/cli.py # scope_ids= 가 있어야 함

# 3. 소량 검증 (3문서, 약 10분)
PYTHONPATH=src python3 tools/check_extraction.py 3 mlx data/joseon.sqlite
```

네 지표를 본다: 관계 유형 분포(`participated_in` 이 나오는가) ·
가제티어 연결률 · 근거 충실도 · 조각당 속도.

## 파이프라인 실행 순서

```sh
export PYTHONPATH=src
python3 -m histgraph doctor                      # 소스 접근 진단
python3 -m histgraph ingest heritage --kinds 11 12
python3 -m histgraph ingest wikidata
python3 -m histgraph events                      # 핵심 사건 직접 수집
python3 -m histgraph enrich --limit 1200         # 위키백과 서사
python3 -m histgraph infobox                     # 인포박스 관계 (LLM 불필요)
python3 -m histgraph prune                       # 스포츠 제거 (필수)
python3 -m histgraph resolve                     # 소스 간 연결
python3 -m histgraph timeline                    # 연도 정규화
python3 -m histgraph scope joseon                # 시대별 서브그래프
python3 -m histgraph extract --scope data/joseon.sqlite --types event org
```

## 되풀이하지 말 것

- **총계만 보고 판단하기.** `participated_in` 5,791건이 90.5% 올림픽이었다.
  엣지 수가 아니라 대상 노드의 라벨 분포를 봐야 한다.
- **가진 데이터를 확인하지 않고 말하기.** "산문에서 추출하면 된다"고 했지만
  가진 산문의 27%가 판본 치수였다. "신규식은 전체 그래프에 있을 것"이라고
  했지만 597개 중 0개였다.
- **같은 조건을 두 겹으로 쌓고 걸러진다고 착각하기.** `worth_extracting` 이
  `min_score` 와 같은 조건을 검사해 404→404 로 하나도 안 줄었다.
- **정규식과 SQL LIKE 목록을 나란히 두기.** 반드시 갈라진다.
- **문자열 구간을 잘라 통째로 교체하기.** `to_graph` 를 고치다 그 사이의
  `narrative_score` 등 4개를 같이 지웠다.
