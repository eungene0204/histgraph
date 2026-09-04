# histgraph — 세션마다 먼저 읽는 규칙

이 파일은 짧게 둔다. 설계 배경은 [README.md](README.md), 지금 상태와
최근 작업은 [HANDOFF.md](HANDOFF.md) 에 있다. 여기는 **어겨서 지적받은
것**만 적는다.

## 1. 화면에 한글 아닌 글을 띄우지 않는다

세 번 지적받았다 (2026-09-03 두 번, 09-04 한 번: `1923 Jogono Police
Station bombing` 이 사건 이름으로 떴다). 세 번 다 원인이 같았다 —
**표(`data/ko_labels.tsv`)와 사전(`koreanize.py`)은 있었는데, 그래프를
다시 만든 뒤 돌리지 않았거나 파생본(`data/korea.sqlite`)에 안 돌렸다.**

그래서 지금은 사람이 기억하는 대신 기계가 묻는다. 관문이 셋이다:

| 어디서 | 무엇을 | 걸리면 |
|---|---|---|
| `histgraph scope` | 파생본을 만들자마자 `relabel`·`redescribe` 를 돌리고 남은 것을 센다 | 종료 코드 1 · 남은 노드를 찍는다 |
| `tools/hooks/pre-push` | 배포될 DB 를 `tools/check_korean.py` 로 센다 | push 취소 |
| `.github/workflows/test.yml` | 같은 스크립트 | 빨간불 (`--no-verify` 로 넘긴 push 를 잡는다) |

재는 기준은 하나다: **라벨·설명에 한글이 한 자도 없으면 걸린다**
(`labels.foreign_text`). 자료 출처(Wikidata·위키백과)를 화면에 적는 것도
같은 규칙으로 금지다 — 읽는 사람이 묻지 않은 것이다.

걸렸을 때 하는 일:

- **이름**: `data/ko_labels.tsv` 에 `QID<TAB>한국어<TAB>근거` 를 적고
  `uv run histgraph --db data/korea.sqlite relabel`. 원본에도 한 번
  (`uv run histgraph relabel`). 근거 칸에 어디서 온 이름인지 적는다
  (`ja=鍾路警察署爆弾事件`, `로마자 Im Ho`). 근거가 약하면 **음역이라도 적고
  그렇게 밝힌다** — 화면에 영어를 두는 것보다 낫다. 동명이인은 기존 관례대로
  `이름 (1875년)`·`이름 (주교)` 처럼 괄호로 가른다.
- **설명**: `uv run histgraph --db data/korea.sqlite redescribe`. 사전에
  없는 말은 **지어내지 않고 비운다**. 화면이 '설명 없음 — 왜 없는지'를
  한국어로 그린다. 원문은 `props.desc_en` 에 남으므로 사전을 키우면
  되살아난다.
- 이름을 고쳤더니 같은 이름이 이미 있다고 나오면 중복이다. `relabel` 은
  보고만 한다. 합치는 규칙은 `promote` 쪽.

하지 말 것:

- 커넥터마다 영어 검사를 따로 적지 않는다. 관문은 `ontology.Node.__post_init__`
  (설명) 과 위의 셋이다. **SQL 로 라벨·설명을 직접 쓰는 경로를 새로 만들면**
  그 경로는 Node 를 안 지나므로 `koreanize.to_korean` 을 거기서 한 번 더
  건다 (`wikipedia._fill_from_wikidata` 가 그 예).
- 화면 코드(`web/`)에 영어 문구·출처 딱지를 넣지 않는다. 검색·상세·연표에
  새 텍스트를 붙일 때 (1) 한글인가 (2) 자료 이름을 말하고 있지 않은가를 본다.
- 이 규칙을 "다음에 돌리자"로 미루지 않는다. 화면 DB 를 만졌으면 끝에
  `python3 tools/check_korean.py` 를 한 번 돌리고 끝낸다.

## 1-2. 이름이 겹치면 반드시 가른다

2026-09-04 지적: "조선왕과 고려왕 이름이 같을때가 있는데 구분을 반드시
해야해". 왕의 휘(諱)가 별칭으로 들어와 있어서 조선 예종(휘 이황 李晄)이
퇴계 이황의 관계 22건을 먹고 있었다.

재는 것은 `uv run histgraph homonyms` 다 (`scope` 도 같은 관문을 건다).
**고치는 것은 하나뿐이다** — 출처 문서의 주인공이 남에게 간 엣지. 나머지
둘(연대가 어긋나는 참여 · 다른 노드의 라벨이기도 한 별칭)은 **세어서
보여만 준다.** 지우면 참인 것이 먼저 사라진다: 양만춘의 생년이 Wikidata
에 700년으로 적혀 있어 안시성 전투(645)보다 늦고, 김종직이 무오사화에
얽힌 것은 부관참시라 연결 자체는 참이다. 그 목록은 **틀린 날짜를 찾는
창**으로 읽는다.

같은 이름의 사건·인물은 괄호로 가른다 — `여진 정벌 (조선)`,
`이름 (1875년)`, `이름 (주교)`.

## 2. 그래프를 다시 만들 때

수집(`ingest`·`enrich`)은 라벨·설명·엣지 props 를 통째로 덮어쓴다. 그래서
수집 뒤에는 `relabel → redescribe → reigns → precision` 을 다시 돌리고,
그 다음 `scope korea` 로 파생본을 만든다 (README "수집 뒤마다" 절).
화면이 읽는 것은 원본이 아니라 **`data/korea.sqlite`** 다 — 원본만 고치면
화면은 그대로다. 파생본은 저장소에 실려 배포되므로 다시 만들면 커밋한다.

DB 는 다른 세션이 동시에 쓴다. 파일을 복사해 되돌리지 않는다 — 그쪽
작업이 사라진다.

## 3. 자주 쓰는 것

```
uv run tests/test_pipeline.py        # 파이썬 (표준 라이브러리만, 의존성 없이 돈다)
python3 tools/check_korean.py        # 배포될 DB 에 영어가 남았는지
uv run histgraph serve               # http://127.0.0.1:8100 (8000 은 다른 프로젝트)
cd web && npm test && npm run build  # 화면
```
