# 주간 사건 수집

현대사가 2025년 6월 3일 제21대 대통령 선거에서 끝나 있었다. 시드 표
(`wikipedia.EVENT_SEEDS`)는 사람이 손으로 적는 명단이라 어제 일어난 일을
담지 못한다 — 그래서 **해마다 저절로 자라는 자리**에서 주마다 걷는다.

```
sh tools/scheduler/install.sh              # 이 맥에 건다 (매주 월요일 09:00)
sh tools/scheduler/install.sh --run        # 지금 한 번 돌려 본다
sh tools/scheduler/install.sh --uninstall  # 걷는다
```

로그는 `~/.cache/histgraph/recent/{날짜}.log`. 저장소 밖에 둔다 — 커밋할
것이 아니고, 세션이 죽어도 남아야 한다.

## 주마다 하는 일

| 차례 | 무엇을 | 걸리면 |
|---|---|---|
| 0 | 화면 DB(`data/korea.sqlite`)에 커밋 안 된 수정이 있는지 | 그 주는 걷지 않는다 (다른 세션이 만지는 중) |
| 1 | `histgraph recent` — 원본과 파생본에 한 번씩 | 멈춘다 |
| 2 | `tools/check_korean.py` · `tests/test_pipeline.py` | 커밋하지 않는다 |
| 3 | 화면 DB 만 이름을 대고 커밋 | — |
| 4 | `git push origin HEAD` (pre-push 훅이 한 번 더 잰다) | 커밋은 남고 push 만 안 된다 |

지금 브랜치가 `main` 이면 push 가 곧 배포다. 아니면 다음 병합 때 나간다.

## 무엇을 걷는가

한국어 위키백과의 `분류:{해}년 대한민국` (하위 분류 한 단계까지). 그 분류에는
사건과 드라마와 프로야구가 함께 살아서, 가르는 일을 셋으로 나눈다 —
Wikidata 클래스 계층(사건 뿌리 `Q1190554`) · 스포츠 필터 · 문서 자신의 분류
(Wikidata 항목이 아직 없는 새 문서용). 자세한 것은 `src/histgraph/recent.py`
머리글에 있다.

**판정이 안 서면 세우지 않고 이름만 로그에 남긴다.** 사람이
`data/recent.tsv` 에 한 줄 적으면 다음 주에 들어온다:

```
수집<TAB>문서명<TAB>날짜<TAB>근거      제외<TAB>문서명<TAB><TAB>근거
```

## 손으로 돌릴 때

```
uv run histgraph recent --dry-run --show 40     # 적지 않고 판정만 본다
uv run histgraph recent                          # 원본
uv run histgraph --db data/korea.sqlite recent   # 파생본 (화면이 읽는 것)
```
