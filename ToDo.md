# ToDo — 콘텐츠층을 객체로 세우는 설계와 순서

[concept.md](concept.md) 가 **무엇을 할지**를 정했다. 이 문서는 **어떤 객체로
자를지, 어떤 순서로 만들지, 언제 누가 확인할지**를 정한다.

세 가지를 지킨다.

- **새 프로젝트를 그리지 않는다.** 지금 파이프라인
  (`ingest → resolve → enrich → extract → promote → serve`) 위에 얹는다.
  아래 명세에서 `(기존)` 은 이미 있는 파일이고 `(신규)` 만 새로 만든다.
- **객체는 감추기 위해 만든다.** 클래스를 늘리는 것이 목적이 아니라,
  "이 모듈이 무엇을 **모르는가**"를 적을 수 있게 만드는 것이 목적이다.
  각 명세에 `모르는 것` 칸이 있는 이유다. 그 칸이 비면 그 객체는 아직
  경계가 아니다.
- **틀린 것을 지우기 전에 셀 수 있게 만든다.** 이 저장소는 총계로 진척을
  잰 탓에 두 번 속았다(스포츠 오염, `depicts` 157건). 판정을 코드로 두고
  (§2.9) 사람이 눈으로 보는 자리를 만든다(§5).

---

## 0. 지금 무엇이 서 있고 무엇이 없나 (실측, 2026-09-04)

작업 트리에 이미 들어와 있는 것:

| | 상태 |
|---|---|
| `concept` 노드 타입 | **있음** (`ontology.py`) — 단, DB 에 `concept` 노드 0개 |
| `about` 엣지 타입 | **있음** (`ontology.py`) — 단, DB 에 `about` 엣지 0건 |
| `reclassify` 모듈·명령 | **있음** (`reclassify.py`, `cli.py`) — **아직 안 돌렸다** |
| `enrich --types` / `extract --types` | **있음** — 2단계에 그대로 쓴다 |
| `GraphAPI` 클래스 | **있음** (`server.py`) — 화면의 유일한 조회 관문 |
| `web/src/` 컴포넌트 구조 | **있음** — `App / GraphCanvas / DetailPanel / TimelinePanel` |

없는 것:

| | |
|---|---|
| `set_in` · `adapted_from` 엣지 | 없음 |
| `media.props.form` 필수 검사 | 없음 — **DB 의 media 96개 전부 `form` 이 비어 있다** |
| `fetch_media` 의 `type="event"` 기본값 제거 | 안 됨 |
| 위키백과 **분류 순회** | 없음 (`fetch_titles` 는 QID→문서명이지 분류 순회가 아니다) |
| `'등장 인물'` 섹션 절단 | 없음 |
| 작품용 추출 프로파일 | 없음 (`EXTRACTABLE` 에 `depicts`·`about`·`set_in` 이 없다) |
| 판정 도구 (`audit`) | 없음 — 지금은 `depicts_report` 하나뿐 |
| 검수 화면 | 없음 |

DB 실측: `media` 96 · `depicts` 157(대상 `event` 151 / `person` 6) ·
`concept` 0 · `about` 0 · `form` 채워진 media 0.

**0단계는 코드가 절반쯤 서 있고 실행이 안 된 상태다.** 그래서 §4 의 첫 묶음이
"만들기"가 아니라 "마저 만들고 돌리기"다.

---

## 1. 시스템을 객체로 자른다

층은 넷이고, **의존은 언제나 아래로만 흐른다.**

```
  ┌────────────────────────────────────────────────────────┐
  │ 표현층      GraphAPI · TimelineAxis · ReviewAPI        │  ← HTTP/화면만 안다
  │             web/src (App · DetailPanel · WorksLine)    │
  ├────────────────────────────────────────────────────────┤
  │ 공정층      Harvester · Cleaner · Extractor · Promoter │  ← 순서와 판정을 안다
  │             Auditor · ReviewBook                       │
  ├────────────────────────────────────────────────────────┤
  │ 규칙층      GuardChain(1~12) · GateChain · WorkIdentity│  ← 순수 규칙. I/O 모름
  │             SectionFilter · CategorySpec               │
  ├────────────────────────────────────────────────────────┤
  │ 기반층      Node · Edge · MediaForm · Confidence       │  ← 아무것도 모름
  │             GraphStore (SQLite 단일 관문)              │
  └────────────────────────────────────────────────────────┘
```

경계를 이렇게 그은 이유:

- **규칙층이 I/O 를 모르는 것이 이 설계의 전부다.** 지금 안전장치 일곱은
  `extract.py` 1,203줄 안에 함수로 흩어져 있어서, "어느 장치가 몇 건을
  걸렀나"를 물어볼 자리가 없다. 규칙을 객체로 세우면 그 집계가 공짜로
  나오고(§2.6), 그 집계가 곧 §5 의 비기술자 리포트가 된다.
- **`GraphStore` 는 SQL 을 아는 유일한 객체다.** 지금 `promote.py` ·
  `reclassify.py` · `server.py` 가 각자 `store.conn.execute` 로 SQL 을
  적고 있다. 새 코드는 이 습관을 물려받지 않는다 — 새 질의는 `GraphStore`
  의 메서드로 들어간다(§2.2). 기존 SQL 을 지금 다 옮기지는 않는다.
- **`Harvest` 라는 반환형 하나로 커넥터를 통일한다.** 지금 커넥터마다
  `(nodes, edges)` 또는 `(nodes, edges, failures)` 를 돌려주고, 호출부인
  `cli._persist` 가 그 차이를 안다. 이건 커넥터가 늘 때마다 CLI 가 바뀌는
  구조다.

---

## 2. 모듈 명세

### 2.1 `ontology` — 온톨로지 (기존, 확장)

| | |
|---|---|
| 파일 | `src/histgraph/ontology.py` |
| 역할 | 노드·엣지 타입 정의와 **자기검증**. 잘못된 값이 여기를 못 지나가게 한다 |
| 입력 | 커넥터가 만든 원시 값 |
| 출력 | `Node` · `Edge` (또는 `OntologyError`) |
| 모르는 것 | DB, 네트워크, 화면, 다른 모든 모듈 |

**데이터 구조 (추가분)**

```python
class MediaForm(StrEnum):
    """매체 형식. 노드 타입을 쪼개지 않는 대신 이것으로 가른다 (concept §4.3).

    화면에 영어를 쓰지 않으므로 한국어 라벨을 여기 함께 둔다 — 표기가
    두 군데 있으면 한 군데가 반드시 뒤처진다."""
    FILM = "film"; SERIES = "series"; DOCUMENTARY = "documentary"
    BOOK = "book"; MUSIC = "music"; GAME = "game"
    COMIC = "comic"; STAGE = "stage"

FORM_LABELS: dict[MediaForm, str] = {
    MediaForm.FILM: "영화", MediaForm.SERIES: "드라마",
    MediaForm.DOCUMENTARY: "다큐멘터리", MediaForm.BOOK: "책",
    MediaForm.MUSIC: "음악", MediaForm.GAME: "게임",
    MediaForm.COMIC: "만화", MediaForm.STAGE: "무대",
}

class Confidence:
    """`depicts` 는 사실이 아니다 — 어디서 왔는지로 값을 가른다 (concept §7-12)."""
    STRUCTURED = 1.0   # Wikidata·분류 등 구조화 소스
    INTRO      = 0.8   # 문서 인트로 문장
    PLOT       = 0.6   # 줄거리에서의 추론
```

**추가할 엣지**

| 엣지 | 출발 | 도착 | 비고 |
|---|---|---|---|
| `set_in` | `media`, `artwork` | `period`, `place`, **`org`** | 아래 참조 |
| `adapted_from` | `media` | `media`, `artwork` | Wikidata P144 |

> **concept.md §4.4 를 한 군데 고친다.** 거기서는 `set_in` 의 도착 타입을
> `period·place` 로 적었는데, `org` 를 넣어야 한다. 명단의 출처인
> `분류:조선 역사 드라마` 가 주는 배경은 '조선'이고, 이 저장소에서 조선은
> `org`(왕조)다 — `from_period` 가 이미 같은 이유로 `("period", "org")` 를
> 도착 타입으로 갖는다. `org` 를 빼면 1단계에서 얻는 `set_in` 초기값
> 대부분이 스키마 위반으로 떨어진다.

**추가할 검증** (`Node.__post_init__`)

```python
if self.type == "media" and not self.props.get("form"):
    raise OntologyError(f"media 노드에 form 이 없음: {self.id}")
```

설명(description)과 달리 예외를 던진다. 설명은 나중에 채울 수 있지만
`form` 은 수집하는 쪽이 반드시 알고 있는 값이고, 비면 화면에서 영영
구분이 안 된다. **DB 의 media 96개가 지금 전부 여기 걸린다** — 그래서
0단계에 이 96개를 채우거나 지우는 일이 들어간다(§4).

---

### 2.2 `GraphStore` — 저장소 (기존, 확장)

| | |
|---|---|
| 파일 | `src/histgraph/store.py` |
| 역할 | SQLite 를 아는 **유일한** 객체. 멱등 저장과 서브그래프 조회 |
| 입력 | `Iterable[Node]` · `Iterable[Edge]` · 조회 인자 |
| 출력 | 정수(건수) · `dict` · `sqlite3.Row` |
| 모르는 것 | 온톨로지 규칙(타입이 맞는지), 네트워크, 화면 |

**추가할 메서드** (새 질의는 전부 여기로)

```python
def migrate(self) -> list[str]: ...            # §3.2. 적용한 마이그레이션 이름을 돌려준다
def works(self, form: str | None = None) -> list[Row]: ...
def depicts_targets(self) -> list[Row]:        # (대상 타입, 라벨, 건수)
def works_of(self, node_id: str) -> list[Row]: # depicts 역방향 — 화면의 '이 사건을 다룬 작품'
def sample_edges(self, edge_type: str, n: int, seed: int) -> list[Row]: ...
def record_audit(self, stage: int, metric: str, value: float,
                 threshold: float, passed: bool) -> None: ...
def record_review(self, key: EdgeKey, verdict: str, note: str = "") -> None: ...
```

`sample_edges` 에 **`seed` 가 있는 것이 중요하다.** 표본을 매번 새로 뽑으면
"저번보다 나아졌나"를 물을 수 없다. 같은 씨앗은 같은 30건을 준다.

---

### 2.3 `Harvest` · `Source` — 수집 커넥터의 공통 모양 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/sources/__init__.py` |
| 역할 | 모든 커넥터의 반환형을 하나로. CLI 가 커넥터마다 다르게 굴지 않게 |
| 입력 | — |
| 출력 | — (형만 정의) |
| 모르는 것 | 전부. 여기엔 로직이 없다 |

```python
@dataclass(slots=True)
class Harvest:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)   # 못 물어본 구간
    notes: dict[str, Any] = field(default_factory=dict) # 분류별 건수 등

    def __add__(self, other: Harvest) -> Harvest: ...

class Source(Protocol):
    name: str
    def harvest(self) -> Harvest: ...
```

**`failures` 를 반환형에 못 박는 이유.** 이 저장소는 '결과가 없다'와
'못 물어봤다'를 섞어서 이미 두 번 데었다(sitelink 502, 재분류 배치 실패).
빈 리스트를 돌려주는 것과 실패를 돌려주는 것은 **다른 사건**이고, 형이
그것을 강제해야 다음 커넥터도 잊지 않는다.

---

### 2.4 `WorksCatalog` — 작품 명단 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/sources/works.py` |
| 역할 | 위키백과 **분류 순회**로 작품 문서 명단을 만들고, 분류에서 `form` 과 `set_in` 초기값을 얻는다 |
| 입력 | `Fetcher`, `list[CategorySpec]` |
| 출력 | `Harvest` (media 노드 + `set_in` 엣지 + 분류별 건수) |
| 모르는 것 | `GraphStore`, SQL, 화면, 추출 |

```python
@dataclass(frozen=True, slots=True)
class CategorySpec:
    """분류 하나가 무엇을 뜻하는지. **분류명은 추측하지 않는다** —
    concept §6.1 에서 '분류:한국의 사극' 등 넷이 전부 0건이었다.
    이 표에 넣기 전에 검색으로 존재를 확인하고, 확인한 날짜를 적는다."""
    name: str            # "분류:조선 역사 드라마"
    form: MediaForm      # SERIES
    setting: str | None  # "wd:Q28179"(조선) — 없으면 None, 짐작하지 않는다
    verified_on: str     # "2026-09-04" — 실측으로 문서 수를 센 날
    seen: int            # 그날 센 문서 수. 0 이면 이 줄은 틀린 것이다
```

**메서드**

| 메서드 | 하는 일 |
|---|---|
| `harvest()` | 전체 분류를 돌아 `Harvest` 를 만든다 |
| `_members(spec)` | 분류의 문서 목록 (`list=categorymembers`, 하위분류 1단계까지) |
| `_to_node(title, spec)` | 문서명 → `media` 노드. **id 는 `kowiki:{문서명}`** |
| `report()` | 분류별 (기대 건수, 실제 건수, 새 문서 수) — `catalog` 테이블로 |

**id 를 문서명으로 삼는 것이 동명 작품 문제를 절반 푼다.** 위키백과가
이미 `춘향전 (1961년 영화)` · `춘향전 (2000년 영화)` 로 갈라 놓았다.
라벨 유사도로 합치지 않는다 — 제1차/제2차 요동정벌을 한 노드로 만든 그
실패와 같은 자리다(concept §7-11). 나머지 절반은 `WorkIdentity`(§2.7).

**분류가 0건이면 예외를 던지지 않고 `failures` 에 담는다.** 위키백과가
분류를 개편하는 일이 있고, 그때 수집 전체가 멈추면 안 된다. 대신
`report()` 가 그 줄을 빨갛게 보고하고 §5 의 판정이 걸린다.

---

### 2.5 `SectionFilter` — 지뢰 섹션 절단 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/sections.py` |
| 역할 | 문서 본문에서 **추출에 넣으면 안 되는 섹션**을 잘라낸다 |
| 입력 | `str` (위키백과 본문) |
| 출력 | `CleanText(text, cut: list[str], kept: list[str])` |
| 모르는 것 | 네트워크, DB, 위키백과 API, LLM — **순수 문자열 함수다** |

```python
MINES  = ("등장 인물", "등장인물", "출연", "등장 배우", "수상", "시청률")
GOLD   = ("역사적 사실", "고증", "줄거리", "개요")

class SectionFilter:
    def clean(self, text: str) -> CleanText: ...
    def gold_only(self, text: str) -> CleanText: ...   # 금맥 섹션만 남긴다
```

**왜 별도 파일인가.** 이건 이미 아는 함정의 재발이다 — README 의
"족보 목록은 모델을 망가뜨린다"와 정확히 같은 모양이고, `extract.py` 에
`strip_kinship_lists` 로 이미 한 번 처방이 들어가 있다. 두 처방을 한
파일에 모으면 다음 사람이 세 번째 목록 함정을 만났을 때 어디를 볼지
안다. 그리고 순수 함수라서 **네트워크 없이 테스트된다** — 이게 실질적인
이유다.

---

### 2.6 `Guard` · `GuardChain` — 추출 안전장치 (기존 로직, 신규 구조)

| | |
|---|---|
| 파일 | `src/histgraph/guards.py` (신규) + `extract.py` (호출부) |
| 역할 | 추출된 관계 한 건을 받아 **버릴 이유가 있으면 그 이유를** 돌려준다 |
| 입력 | `Relation`(모델 출력 1건), `DocContext`(원문·노드·가제티어) |
| 출력 | `str | None` — 거부 사유(한국어) 또는 통과 |
| 모르는 것 | 백엔드, 네트워크, 화면. `GraphStore` 는 `DocContext` 를 통해서만 |

```python
class Guard(Protocol):
    name: str          # 화면과 리포트에 그대로 나가는 한국어 이름
    def check(self, rel: Relation, ctx: DocContext) -> str | None: ...

class GuardChain:
    def __init__(self, guards: list[Guard]) -> None: ...
    def filter(self, rels: list[Relation], ctx: DocContext) -> list[Relation]: ...
    @property
    def tally(self) -> dict[str, int]: ...   # 장치 이름 -> 걸러낸 건수
```

**기존 일곱** (`extract.py` 에서 옮겨 온다. 로직은 그대로다):

| # | 이름 | 지금 있는 곳 |
|---|---|---|
| 1 | 근거 검증 | `evidence_supported` |
| 2 | 방향 교정 | `orient` · `reversed_by_source` |
| 3 | 별칭 해소 | `name_variants` · `pick_candidate` |
| 4 | 족보 목록 제거 | `strip_kinship_lists` |
| 5 | 소유격 오독 | `possessive_mismatch` |
| 6 | 소실 문형 | `loss_context` |
| 7 | 참여 연대 | `lifespan_conflict` |

**콘텐츠용 다섯** (신규):

| # | 이름 | 규칙 |
|---|---|---|
| 8 | 배역·배우 차단 | 근거 구절이 잘려나간 섹션(§2.5)에서 왔거나, 대상이 20세기 이후 생몰인 인물이면 버린다 |
| 9 | 개념은 사건이 아니다 | 대상이 인물·사건으로 **확인되지 않으면** `event` 가 아니라 `concept` 으로 떨어뜨린다. `depicts` → `about` 으로 강등 |
| 10 | 픽션 인물 차단 | 출처가 작품 문서 하나뿐이고 사실층 어디에도 없는 이름은 노드로 만들지 않는다 (판정은 §2.7 로 넘긴다) |
| 11 | 동명 작품 분리 | 라벨만 같고 `form` 또는 발표연도가 다르면 다른 작품 (§2.7) |
| 12 | 작품은 사실이 아니다 | 근거 구절이 온 섹션으로 `Confidence` 를 정한다 (구조화 1.0 / 인트로 0.8 / 줄거리 0.6) |

**이 구조가 실제로 사는 자리는 `tally` 다.** 지금은 안전장치가 몇 건을
걸렀는지 로그를 뒤져야 안다. `tally` 가 있으면 `extract` 가 끝날 때
한국어 표 한 장이 나오고, 그 표가 §5 에서 비기술자가 보는 화면이 된다.

```
  추출 1,204건 중 붙인 것 806건 · 버린 것 398건
    근거 검증        181건   ← 원문에 없는 말을 지어낸 것
    개념은 사건 아님  96건   ← 주제어를 사건으로 만들려 한 것
    배역·배우 차단    74건
    …
```

---

### 2.7 `Gate` · `WorkIdentity` — 승격 관문 (기존 로직, 신규 구조)

| | |
|---|---|
| 파일 | `src/histgraph/promote.py` (기존) + `gates.py` (신규) |
| 역할 | 추출 고아(`ex:`) 를 실제 노드로 올릴지 판정 |
| 입력 | `Candidate(ex_id, label, type, evidence_docs, dates)` |
| 출력 | `Verdict(accept: bool, target_id: str | None, reason: str)` |
| 모르는 것 | 화면, LLM, 추출 프롬프트 |

```python
@dataclass(frozen=True, slots=True)
class WorkIdentity:
    """작품의 동일성 — **점수가 아니라 규칙이다.**
    『춘향전』은 영화만 여럿이고, 라벨 유사도로 합치면 한 노드가 된다."""
    label: str
    form: MediaForm
    released: int | None      # 발표연도. 없으면 다른 작품으로 본다(합치지 않는다)

    def key(self) -> tuple: return (self.label, self.form, self.released)
```

`released` 가 없을 때 **합치지 않는 쪽**을 고른 이유: 잘못 합친 것은
되돌리기 어렵고(엣지가 이미 섞였다), 나뉘어 있는 것은 나중에 합칠 수 있다.
`node_merge_is_half_wrong` 에서 배운 것과 같다.

**추가 관문**

| 관문 | 조건 |
|---|---|
| `NoActorGate` | 근거 문서가 작품 문서뿐 + 생년 1900년 이후 → 거부 |
| `NoFictionGate` | 출처가 작품 문서 하나뿐이고 사실층에 같은 이름이 없음 → 거부 |
| `WorkSplitGate` | 기존 `media` 와 라벨이 같아도 `WorkIdentity.key()` 가 다르면 별도 노드 |

---

### 2.8 `ExtractionProfile` — 문서 종류별 추출 설정 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/profiles.py` |
| 역할 | "이 종류의 문서에서는 어떤 관계를 어떤 프롬프트로 캐는가" |
| 입력 | `Document`, `gazetteer` |
| 출력 | `system_prompt: str`, `relations: list[str]`, `schema: dict`, `guards: GuardChain` |
| 모르는 것 | 백엔드, DB, 화면 |

```python
class ExtractionProfile(ABC):
    node_types: tuple[str, ...]
    relations: list[str]
    def system(self) -> str: ...
    def guards(self) -> GuardChain: ...

class FactProfile(ExtractionProfile):     # 기존. 인물·사건 문서
    node_types = ("person", "event", "org")
    relations = EXTRACTABLE               # participated_in · created · …

class WorkProfile(ExtractionProfile):     # 신규. 작품 문서
    node_types = ("media",)
    relations = ["depicts", "about", "set_in", "adapted_from", "created", "part_of"]
```

`WorkProfile.system()` 이 프롬프트에서 **꼭 말해야 하는 것 셋**:

1. 주어는 언제나 이 작품이다 (작품 문서의 관계는 대부분 작품 → 무엇).
2. 실존 인물·실제 사건이면 `depicts`, 주제어·소재·제도면 `about`.
   **헷갈리면 `about` 이다** — 개념은 사건보다 회수하기 쉽다.
3. 배우 이름·배역 이름은 관계가 아니다. 배역은 `depicts` 의 `label` 에만.

---

### 2.9 `Auditor` — 단계 판정 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/audit.py` |
| 역할 | concept.md §9 의 판정 기준을 **코드로** 재고, 통과·미달을 한국어로 말한다 |
| 입력 | `GraphStore`, 단계 번호 |
| 출력 | `list[Metric]` + `AuditReport.render_ko() -> str` |
| 모르는 것 | 수집, 추출, 네트워크 — **읽기만 한다** |

```python
@dataclass(frozen=True, slots=True)
class Metric:
    stage: int
    name: str          # "depicts 가 실체를 가리키는 비율"
    value: float
    threshold: float
    unit: str          # "%" | "건" | "배"
    detail: str        # 미달일 때 무엇을 보면 되는지 (한국어 한 줄)
    @property
    def passed(self) -> bool: return self.value >= self.threshold
```

| 단계 | 지표 | 기준 |
|---|---|---:|
| 0 | `depicts` 대상 중 `event`·`person` 비율 | 100% |
| 0 | `depicts` 대상 중 주제어(재분류 보류 목록과 겹치는 것) | 0건 |
| 0 | `form` 이 빈 `media` 노드 | 0개 |
| 1 | `media` 노드 수 | ≥ 300 |
| 1 | `form` 채워진 비율 | 100% |
| 1 | `set_in` 보유 비율 | ≥ 80% |
| 2 | 사실층으로 나가는 엣지를 가진 `media` 비율 | ≥ 70% |
| 2 | 표본 30건 정밀도 (§2.10) | ≥ 0.9 |
| 2 | `depicts` 총계 | ≥ 600 |
| 3 | 주요 사건 10개 중 작품이 붙어 나오는 수 | ≥ 6 |
| 4 | 두 자리 수 이상인 `form` 종류 | ≥ 5 (영화·드라마 + 3) |

`record_audit` 으로 매 실행을 `audit_run` 에 남긴다. **한 번의 통과보다
지난번과의 차이가 중요하다** — 수집을 다시 돌리다 조용히 나빠진 적이 있다.

---

### 2.10 `ReviewBook` — 사람이 하는 표본 검사 (신규)

| | |
|---|---|
| 파일 | `src/histgraph/review.py` + 화면의 검수 모드 |
| 역할 | 엣지 30건을 **한국어 문장 한 줄로** 보여주고 맞다/아니다/모르겠다를 받는다 |
| 입력 | `GraphStore`, `edge_type`, `n`, `seed` |
| 출력 | `list[ReviewItem]` → 사람의 판정 → `review` 테이블 → 정밀도 |
| 모르는 것 | 추출, 수집, LLM |

```python
@dataclass(frozen=True, slots=True)
class ReviewItem:
    key: tuple[str, str, str, str]   # (src, dst, type, source) — edges 자연키
    sentence: str                    # "《한산》은 한산도 대첩을 다룬다"
    evidence: str | None             # 근거 구절 (props.evidence)
    confidence: float
```

**문장을 화면 쪽 규칙으로 만든다.** `web/src/lib/relations.js` 의
`SENTENCE` 가 이미 엣지를 한국어 문장으로 바꾼다("A는 B를 다룬다").
검수 화면은 그것을 그대로 쓴다 — 검수자가 읽는 문장과 사용자가 화면에서
읽는 문장이 같아야 검수 결과가 화면의 품질을 뜻한다.

**정밀도 = 맞다 / (맞다 + 아니다).** '모르겠다'는 분모에서 뺀다.
모르는 것을 틀린 것으로 세면 어려운 표본이 많은 날 점수가 내려간다.

---

### 2.11 `GraphAPI` — 화면의 조회 관문 (기존, 확장)

| | |
|---|---|
| 파일 | `src/histgraph/server.py` |
| 역할 | 화면이 쓰는 유일한 조회 경로. HTTP 핸들러와 그래프 사이의 벽 |
| 입력 | 노드 id, 검색어, 토글 |
| 출력 | JSON 직렬화 가능한 `dict` |
| 모르는 것 | HTTP(핸들러가 안다), SQL 세부(`GraphStore` 가 안다) |

**추가 메서드**

```python
def works_of(self, node_id: str) -> list[dict]:      # '이 사건을 다룬 작품'
def graph(..., include_media: bool = True) -> dict:  # 콘텐츠 토글
def timeline(self, node_id: str, axis: str = "setting") -> dict:
```

**`TimelineAxis` 를 값 객체로 만든다.**

```python
class TimelineAxis(StrEnum):
    SETTING = "setting"    # 배경연도 — set_in → time:YYYY. **기본값**
    RELEASE = "release"    # 발표연도 — start_date

    def year_of(self, api: GraphAPI, row) -> tuple[int | None, str]: ...
```

`server._year_of` 는 지금 `start_date` 를 먼저 본다. 그대로 두면 『한산』이
연표의 2022년에 선다 — 임진왜란에서 430년 떨어진 자리다. **`media` 노드에
한해** `SETTING` 축이 `set_in` 을 먼저 보고, 없으면 연표에서 **숨긴다**
(concept §11-3 의 제안대로: 화면이 단정하지 않는 쪽).

---

### 2.12 화면 컴포넌트 (기존 구조에 추가)

| 컴포넌트 | 역할 | 받는 것 | 모르는 것 |
|---|---|---|---|
| `WorksLine` (신규) | 상세 패널의 '이 사건을 다룬 작품' 줄 | `works: []` | fetch, 그래프 |
| `ContentToggle` (신규) | 콘텐츠 켜기/끄기. 기본 켜짐 | `on`, `onChange` | 데이터 |
| `AxisToggle` (신규) | 연표 두 축. 기본 '배경' | `axis`, `onChange` | 데이터 |
| `FormBadge` (신규) | 라벨 옆 작은 글자 — '영화'·'드라마' | `form` | 색, 레이아웃 |
| `ReviewPanel` (신규) | 검수 모드 (§2.10) | `items`, `onVerdict` | 판정 규칙 |
| `relations.js` (기존) | 엣지 → 한국어 문장 | 엣지 | DOM |

**색은 늘리지 않는다.** `media` 는 지금 색 그대로 두고 `form` 은
`FormBadge` 의 작은 글자로만 가른다. 9색에서 15색이 되면 그건 구분이
아니라 소음이다. 그리고 `form` 은 화면에서 언제나 한국어다 —
`FORM_LABELS`(§2.1)를 거치지 않은 `form` 값이 화면에 나가면 안 된다.

---

## 3. DB 스키마

### 3.1 기존 테이블 — 그대로 둔다

`nodes` · `aliases` · `edges` · `same_as` · `ingest_log` 다섯은 손대지
않는다. 콘텐츠층이 필요로 하는 것은 이미 다 있다.

- 작품은 `nodes.type = 'media'`, 형식은 `props.form`.
- 발표연도는 `nodes.start_date`, 배경연도는 `edges(type='set_in')`.
- 근거·고증은 `edges.props`, 신뢰도는 `edges.confidence`.
- **`edges` 의 PK 가 `(src, dst, type, source)` 인 것이 중요하다.**
  같은 작품→사건 관계를 Wikidata 와 추출이 각각 말하면 두 행으로 남고,
  그게 곧 교차검증이다. 합치지 않는다.

**`props` 규약** (문서로만 강제한다 — 컬럼으로 올리지 않는다)

| 키 | 어디에 | 뜻 |
|---|---|---|
| `form` | `nodes.props` (media) | `MediaForm` 값. **필수** |
| `released` | `nodes.props` (media) | 발표연도(정수). `start_date` 의 요약 |
| `historicity` | `nodes.props` (media) | 문서의 고증 서술 (`'픽션이다'` 등) |
| `catalog` | `nodes.props` (media) | 어느 분류에서 왔는지 |
| `evidence` | `edges.props` | 근거 구절 (기존 규약) |
| `section` | `edges.props` | 근거가 온 섹션 — `Confidence` 의 근거 |

### 3.2 추가 — 생성 컬럼 하나와 테이블 셋

```sql
-- 1) form 을 질의할 수 있게. props 가 여전히 원본이고 이건 파생이다 —
--    두 곳에 쓰면 한 곳이 반드시 뒤처진다. VIRTUAL 이라 저장공간도 안 쓴다.
ALTER TABLE nodes ADD COLUMN form TEXT
  GENERATED ALWAYS AS (json_extract(props, '$.form')) VIRTUAL;
CREATE INDEX IF NOT EXISTS idx_nodes_form ON nodes(form);

-- 2) 분류 순회 이력. "분류명을 추측했다가 0건이었다"를 다시 겪지 않는다.
CREATE TABLE IF NOT EXISTS catalog (
    name        TEXT PRIMARY KEY,        -- '분류:조선 역사 드라마'
    form        TEXT NOT NULL,
    setting     TEXT,                    -- 배경 노드 id (없으면 NULL)
    expected    INTEGER NOT NULL,        -- CategorySpec.seen — 확인한 날의 문서 수
    found       INTEGER,                 -- 이번 실행이 실제로 본 수. NULL = 못 물어봄
    ran_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 3) 사람의 표본 검사. 정밀도의 유일한 근거다.
CREATE TABLE IF NOT EXISTS review (
    src     TEXT NOT NULL,
    dst     TEXT NOT NULL,
    type    TEXT NOT NULL,
    source  TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('yes', 'no', 'unsure')),
    note    TEXT,
    seed    INTEGER NOT NULL,            -- 어느 표본에서 나온 판정인지
    ran_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (src, dst, type, source)
);

-- 4) 단계 판정 이력. 한 번의 통과보다 지난번과의 차이가 중요하다.
CREATE TABLE IF NOT EXISTS audit_run (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    stage     INTEGER NOT NULL,
    metric    TEXT NOT NULL,
    value     REAL NOT NULL,
    threshold REAL NOT NULL,
    passed    INTEGER NOT NULL,
    ran_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_stage ON audit_run(stage, metric, ran_at);
```

`review` 에 **외래키를 걸지 않는다.** 검수한 엣지가 나중에 재분류로
바뀌거나 지워질 수 있는데, 그때 판정 기록까지 따라 사라지면 "예전에
사람이 아니라고 한 것을 다시 넣었다"를 못 본다. 판정은 엣지보다 오래
남아야 한다.

### 3.3 마이그레이션

`store.py` 의 `SCHEMA` 는 `CREATE TABLE IF NOT EXISTS` 라 새 테이블은
저절로 생긴다. **`ALTER TABLE` 만 다르다** — 두 번 돌면 실패한다.

```python
def migrate(self) -> list[str]:
    """이미 적용된 것은 건너뛴다. 실패해도 다른 마이그레이션을 막지 않는다."""
    cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(nodes)")}
    applied = []
    if "form" not in cols:
        self.conn.execute("ALTER TABLE nodes ADD COLUMN form TEXT "
                          "GENERATED ALWAYS AS (json_extract(props,'$.form')) VIRTUAL")
        applied.append("nodes.form")
    ...
    return applied
```

`GraphStore.__init__` 이 `executescript(SCHEMA)` 뒤에 `migrate()` 를
부른다. `data/joseon.sqlite` 같은 시대 그래프도 같은 코드를 지나므로
따로 챙길 것이 없다.

---

## 4. 구현 순서

의존이 없는 것부터. **묶음 안에서는 순서가 자유롭고, 묶음 사이에는 순서가
있다.** 각 묶음 끝에 `▶ 여기서 확인` 이 있으면 §5 의 확인 시점이다.

### 묶음 A · 아무것도 모르는 것들 (의존 0)

- [ ] `ontology.py` — `MediaForm` · `FORM_LABELS` · `Confidence` 추가
- [ ] `ontology.py` — `set_in`(도착에 `org` 포함) · `adapted_from` 엣지 추가
- [ ] `ontology.py` — `Node.__post_init__` 에 `media` 의 `form` 필수 검사
- [ ] `sections.py` (신규) — `SectionFilter` · `MINES` · `GOLD`
- [ ] `sources/__init__.py` — `Harvest` · `Source` 프로토콜
- [ ] `tests/test_pipeline.py` — 위 넷의 회귀 테스트
      (`form` 없는 `media` 가 `OntologyError`, `set_in`→`org` 통과,
      '등장 인물' 절단, `Harvest.__add__`)

### 묶음 B · 저장소 (A 의 `Harvest` 만 안다)

- [ ] `store.py` — `migrate()` 와 §3.2 의 생성 컬럼·테이블 셋
- [ ] `store.py` — `works` · `depicts_targets` · `works_of` · `sample_edges`
- [ ] `store.py` — `record_audit` · `record_review`
- [ ] 테스트 — 임시 DB 에 두 번 `migrate()` 해도 안 죽는지

### 묶음 C · 0단계, 오염 청소 (A·B 필요) ★ 다른 것보다 먼저

- [ ] `sources/wikidata.py` — `fetch_media` 의 `type="event"` 기본값 제거.
      타입을 모르면 `concept` 으로 만들고 엣지를 `about` 으로 낸다
- [ ] `fetch_media` — `P31` 로 `form` 을 정한다. **`form` 을 못 정하면
      그 작품은 만들지 않는다** (예외가 아니라 건너뛰기 + `failures`)
- [ ] **DB 의 `media` 96개 처리** — `form` 필수 검사가 지금 이걸 다 막는다.
      `P31` 재조회로 채우고, 못 채운 것은 지운다. 몇 개를 지웠는지 적는다
- [ ] `histgraph reclassify --dry-run` 실행 → 계획 검토 → 실제 적용
- [ ] `reclassify` 뒤 `invalid_edges()` 가 보고한 어긋난 엣지 처리
- [ ] `audit.py` (신규) — `Metric` · `AuditReport` · 0단계 지표 셋
- [ ] `cli.py` — `histgraph audit [단계]` 명령
- [ ] ▶ **여기서 확인 · T1** (§5.2)

### 묶음 D · 1단계, 작품 명단 (C 필요)

- [ ] **분류명 실측** — 후보 분류를 검색으로 확인하고 문서 수를 센다.
      영화·게임·도서 분류는 아직 아무도 안 세어 봤다. 추측 금지
- [ ] `sources/works.py` (신규) — `CategorySpec` 표 (실측한 것만)
- [ ] `sources/works.py` — `WorksCatalog.harvest()` · `report()`
- [ ] `sources/wikidata.py` — P144(원작) · P577(발표일) 보강 질의
- [ ] `cli.py` — `histgraph ingest works`
- [ ] `audit.py` — 1단계 지표 셋
- [ ] ▶ **여기서 확인 · T2** (§5.3)

### 묶음 E · 규칙 이관 (A 필요, D 와 병행 가능)

- [ ] `guards.py` (신규) — `Guard` · `GuardChain` · `Relation` · `DocContext`
- [ ] 기존 안전장치 1~7 을 `extract.py` 에서 `guards.py` 로 이관
      (**로직은 손대지 않는다.** 옮기는 것과 고치는 것을 같은 커밋에 섞지 않는다)
- [ ] `extract.py` — `GuardChain` 을 부르도록 교체, `tally` 출력
- [ ] 테스트 — 이관 전후 같은 입력에 같은 결과 (회귀 고정)
- [ ] `guards.py` — 안전장치 8~12 추가
- [ ] `profiles.py` (신규) — `ExtractionProfile` · `FactProfile` · `WorkProfile`

### 묶음 F · 2단계, 산문에서 엣지 (C·D·E 필요)

- [ ] `sources/wikipedia.py` — `enrich` 가 `SectionFilter` 를 지나게
- [ ] `extract.py` — `--profile {fact,work}` 로 프로파일 선택
- [ ] `gates.py` (신규) — `Gate` · `Verdict` · `WorkIdentity`
- [ ] `promote.py` — `NoActorGate` · `NoFictionGate` · `WorkSplitGate`
- [ ] `review.py` (신규) — `ReviewBook` · `ReviewItem`
- [ ] `cli.py` — `histgraph review --type depicts -n 30`
- [ ] 실행: `enrich --types media` → `extract --profile work --types media` → `promote`
- [ ] ▶ **여기서 확인 · T3** (§5.4) — 표본 30건 검수

### 묶음 G · 3단계, 화면 (F 필요)

- [ ] `server.py` — `GraphAPI.works_of`, `/api/node` 응답에 `works`
- [ ] `server.py` — `TimelineAxis`, `_year_of` 의 `media` 분기
- [ ] `server.py` — `graph(include_media=)` 와 `/api/graph?media=0`
- [ ] `web/src/components/WorksLine.jsx` · `FormBadge.jsx`
- [ ] `web/src/components/ContentToggle.jsx` · `AxisToggle.jsx`
- [ ] `web/src/lib/relations.js` — `about` · `set_in` · `adapted_from` 문장
- [ ] `web/src/components/ReviewPanel.jsx` + `/api/review` (§2.10)
- [ ] `web/tests/` — 문장 변환과 배지 렌더 테스트
- [ ] ▶ **여기서 확인 · T4** (§5.5) — 사건 10개 눌러보기

### 묶음 H · 4단계, 매체 확장 (G 필요)

- [ ] 도서·게임·다큐·음악 분류 실측 → `CategorySpec` 추가
- [ ] `doctor` 에 국내 API **활용신청 상태** 항목 추가 (승인 전엔 위키백과만)
- [ ] KMDb·국립중앙도서관 커넥터 (승인 난 것만)
- [ ] ▶ **여기서 확인 · T5**

---

## 5. 비기술자가 확인하는 시점과 방법

### 5.1 준비 — 터미널에 치는 것은 두 줄뿐이다

```bash
npm run dev            # 화면과 API 를 함께 띄운다 → http://127.0.0.1:5173
uv run histgraph audit # 지금 단계의 판정을 한국어 표로 출력
```

`npm run dev` 가 8100(API)과 5173(화면)을 함께 띄우고 Ctrl+C 로 함께
접는다. **터미널 둘을 쓸 필요가 없다** — 그걸 잊어서 빈 화면만 본 적이 있다.

`audit` 의 출력은 이런 모양이라야 한다. 숫자만이 아니라 **미달일 때 무엇을
보면 되는지**가 같은 줄에 있어야 한다.

```
0단계 · 오염 청소
  ✓ 작품이 가리키는 것 중 실체의 비율      100%  (기준 100%)
  ✓ 형식이 비어 있는 작품                    0개  (기준 0개)
  ✗ 사건인 척하는 주제어                    12개  (기준 0개)
      → 화면에서 '조직범죄' 를 검색해 보세요. 사건으로 뜨면 아직입니다.
```

### 5.2 T1 — 0단계 뒤 · 5분 (묶음 C)

**묻는 것: 개념이 사건 자리에서 비켜났나.**

1. `uv run histgraph audit 0` — 세 줄이 모두 ✓ 인가.
2. 화면 검색창에 **`조직범죄`** · **`자살`** · **`시간 여행`** 을 차례로 친다.
   - 기대: 결과에 `개념·주제` 라고 뜬다.
   - 실패: `사건` 이라고 뜨면 재분류가 안 됐거나 보류된 것이다.
3. 검색창에 **`6·25 전쟁`** 을 친다.
   - 기대: 여전히 `사건` 이다. **개념으로 옮겨졌으면 진짜 사건을 잃은 것이다** —
     이게 이 단계에서 가장 나쁜 실패다. 발견하면 즉시 알린다.

### 5.3 T2 — 1단계 뒤 · 10분 (묶음 D)

**묻는 것: 작품이 들어왔고, 배경이 붙었나.**

1. `uv run histgraph audit 1` — 작품 수 300 이상, 형식 100%, 배경 80% 이상.
2. 화면 검색창에 **`대조영`** · **`선덕여왕`** · **`한산`** 을 친다.
   - 기대: 작품이 결과에 나오고, 이름 옆에 작은 글자로 **`드라마`** ·
     **`영화`** 가 붙어 있다.
   - 실패 1: 영어로 `series` · `film` 이 보이면 알린다 (§2.12 위반).
   - 실패 2: 작은 글자가 없으면 `form` 이 빈 것이다.
3. 작품을 눌러 상세를 본다.
   - 기대: '배경' 줄에 시대(조선·고구려 등)가 있다.
   - 이 시점에는 **작품에서 사건·인물로 나가는 줄이 아직 없어도 정상이다.**
     그건 2단계가 하는 일이다.

### 5.4 T3 — 2단계 뒤 · 30~40분 (묶음 F) ★ 가장 중요한 확인

**묻는 것: 작품과 역사를 이은 줄이 맞는 말인가.**

이 확인만 사람이 대신할 수 없다. 나머지는 다 숫자로 되지만 이것은 안 된다.

```bash
uv run histgraph review --type depicts -n 30
```

또는 화면 오른쪽 위 **`검수`** 버튼. **화면 쪽을 권한다** — 근거 구절과
원문 링크가 함께 보인다.

한 화면에 한 줄씩 나온다.

```
  《한산: 용의 출현》은 한산도 대첩을 다룬다.

  근거:  … 명량대첩의 5년 전인 한산도 대첩을 모티브로 하여 …

  [ 맞다 ]   [ 아니다 ]   [ 모르겠다 ]
```

- **판단 기준은 하나다: 이 문장이 사실인가.** 문장이 어색한 것은 넘긴다
  (그건 화면 문제로 따로 적는다).
- **모르면 `모르겠다` 를 누른다.** 모르는 것은 점수에서 빠진다.
  억지로 맞다/아니다를 고르면 점수가 거짓말이 된다.
- 30건에 20~30분. 중간에 멈춰도 된다 — 판정은 그때그때 저장된다.

끝나면 `uv run histgraph audit 2` 가 정밀도를 말한다.

```
2단계 · 산문에서 엣지
  ✓ 사실층에 이어진 작품의 비율     78%  (기준 70%)
  ✓ 작품→역사 줄의 총계            641건  (기준 600건)
  ✗ 표본 30건 정밀도               0.83  (기준 0.90)
      → '아니다' 를 누른 5건: uv run histgraph review --list-no
```

**정밀도가 기준에 못 미치면 3단계로 넘어가지 않는다.** 틀린 줄이 섞인 채로
화면을 만들면, 화면을 본 사람이 그래프 전체를 못 믿게 된다.

### 5.5 T4 — 3단계 뒤 · 15분 (묶음 G)

**묻는 것: 화면에서 역사와 콘텐츠를 오갈 수 있나.**

대본대로 눌러 본다. 종이에 적어 두고 O/X 를 친다.

| # | 이렇게 한다 | 이래야 한다 |
|---|---|---|
| 1 | 조선 그래프에서 `임진왜란` 검색 | 상세에 '이 사건을 다룬 작품' 줄이 있다 |
| 2 | 그중 한 작품을 누른다 | 작품 상세가 뜨고, 거기서 사건·인물로 되돌아갈 수 있다 |
| 3 | 주요 사건 10개를 차례로 누른다 | **6개 이상**에 작품이 붙어 있다 |
| 4 | 연표를 연다 | 『한산』이 **1592년** 근처에 있다 (2022년이 아니다) |
| 5 | 연표의 축을 '발표'로 바꾼다 | 이번엔 『한산』이 2022년에 있다 |
| 6 | 콘텐츠 토글을 끈다 | 작품이 화면에서 사라지고 사실만 남는다 |
| 7 | 토글을 끈 채로 사건을 누른다 | '이 사건을 다룬 작품' 줄도 함께 사라진다 |
| 8 | 화면 전체를 훑는다 | **영어 낱말이 하나도 없다** |

3번의 사건 10개는 미리 정해 두고 매번 같은 것을 쓴다 — 그래야 지난번과
비교된다. (임진왜란 · 병자호란 · 인조반정 · 계유정난 · 무오사화 ·
갑신정변 · 동학 농민 혁명 · 3·1 운동 · 한국 전쟁 · 5·18 광주 민주화 운동)

### 5.6 T5 — 4단계 뒤

`uv run histgraph audit 4` 와 함께, 화면에서 형식별로 걸러 본다.
영화·드라마 말고 **세 종류 이상**이 두 자리 수로 있어야 한다.

### 5.7 확인하는 사람에게 주는 규칙 셋

1. **총계를 보지 않는다.** "작품 400편"은 아무것도 뜻하지 않는다. 이
   프로젝트는 총계로 두 번 속았다. 보는 것은 **비율과 표본**이다.
2. **이상하면 그 자리에서 이름을 적는다.** 나중에 다시 찾기 어렵다.
   검색창의 그 이름과 눌렀던 순서만 적어 주면 재현된다.
3. **못 본 것을 봤다고 하지 않는다.** 30건 중 12건만 봤으면 12건이라고
   적는다. 정밀도는 본 것에서만 계산된다.

---

## 6. 정해야 할 것 (concept.md §11)

각각 제안이 있다. 반대가 없으면 제안대로 간다.

- [ ] **외국 작품 범위** — 제안: `depicts` 대상이 우리 그래프 노드면
      국적을 묻지 않는다. P495(한국) 필터는 **명단 수집에만** 걸고,
      엣지 판정에는 걸지 않는다. 중국 드라마가 고구려를 다루는 경우가
      실제로 있고, 지금 방식은 그걸 통째로 놓친다.
- [ ] **웹툰·뮤지컬·판소리** — 제안: 웹툰은 `MediaForm.COMIC`,
      뮤지컬은 `STAGE`. **판소리는 `form` 에 넣지 않는다** — 『춘향가』는
      무형유산이자 작품이라 `heritage` 와 겹치고, 겹치는 것을 두 타입에
      나눠 앉히면 §2.7 의 동일성 규칙이 무너진다. 4단계에서 다시 본다.
- [ ] **배경연도를 모르는 작품** — 제안: 연표에서 **숨긴다**.
      화면이 단정하지 않는 쪽이 이 저장소의 규약이다. 그래프에는 그대로
      있으므로 검색과 사건 패널에서는 보인다.
- [ ] **`set_in` 의 `org` 도착 허용** (§2.1) — 이 문서에서 새로 제기한 것.
      허용하지 않으면 1단계 산출 대부분이 스키마 위반이 된다.

---

## 7. 하지 않을 것 (concept.md §10 그대로)

- 배우·감독·제작진 인물망 — 감독은 `created` 로 작품에만 붙인다
- 포스터·스틸 이미지 (저작권)
- 평점·리뷰·흥행 순위
- OTT 시청 링크
- 노드 타입 6종 분리
- **그리고 하나 더**: 규칙을 옮기는 커밋에서 규칙을 고치지 않는다(묶음 E).
  옮기기와 고치기를 섞으면 회귀가 났을 때 어느 쪽 탓인지 못 가린다.
