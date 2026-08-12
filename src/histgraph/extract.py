"""산문에서 관계 엣지를 추출한다 (Claude API).

**이 모듈이 존재하는 이유는 실측 때문이다.** Wikidata 의 한국사
`participated_in` 엣지 5,791건 중 90.5%가 올림픽 출전 기록이고, 실제 역사
사건 엣지는 약 40건뿐이다. 프로젝트의 핵심인 "인물이 어떤 사건에
얽혔는가"는 구조화 소스에 사실상 존재하지 않는다. 유일한 현실적 공급원은
산문(국가유산청 `content`, 조선왕조실록 원문, 백과사전 항목)이다.

설계 요지:
  - **가제티어 그라운딩**: 이미 그래프에 있는 개체명을 프롬프트에 넣어
    새 노드를 지어내지 않고 기존 노드에 붙게 한다. 이게 없으면 추출
    결과가 그래프와 연결되지 않는 고아가 된다.
  - **structured outputs**: 스키마로 응답 형태를 강제해 파싱 실패를 없앤다.
  - **Batch API**: 대량 처리는 50% 저렴하다. 실시간성이 필요 없는 작업이다.
  - **근거 보존**: 모든 추출 엣지는 원문 구절(`evidence`)을 함께 남긴다.
    출처 없는 추론은 나중에 검증할 수 없다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from .ontology import EDGE_TYPES, Edge, Node
from .store import GraphStore

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"

# 텍스트 추론은 구조화 소스보다 신뢰도가 낮다. 등급을 수치로 옮겨
# `Edge.confidence` 에 기록하면 나중에 임계값으로 걸러낼 수 있다.
CONFIDENCE = {"certain": 0.9, "probable": 0.7, "possible": 0.5}

# 추출 대상 엣지 타입. 온톨로지 전체가 아니라 산문에서 실제로 캐낼 수
# 있는 관계로 좁힌다 — 선택지가 많을수록 오분류가 늘어난다.
EXTRACTABLE = [
    "participated_in",  # 인물 -> 사건  (가장 중요)
    "created",          # 인물 -> 유물/작품
    "occurred_at",      # 사건 -> 장소
    "located_in",       # 유물 -> 장소
    "from_period",      # 무엇 -> 시대
    "child_of",
    "spouse_of",
    "held_position",
    "related_to",
]

SYSTEM_PROMPT = """당신은 한국사 문헌에서 개체 간 관계를 추출하는 전문가입니다.

주어진 원문에서 관계를 추출해 구조화된 형태로 반환하세요.

핵심 규칙:
1. **원문에 명시된 것만 추출합니다.** 배경지식으로 아는 사실이라도 주어진
   글에 나오지 않으면 추출하지 마세요.
2. **가능하면 제공된 '알려진 개체' 목록의 이름을 그대로 사용하세요.** 목록에
   같은 대상이 있으면 표기를 맞춰야 기존 지식그래프에 연결됩니다.
   목록에 없는 개체는 원문의 표기를 그대로 씁니다.
3. **모든 관계에 근거 구절(evidence)을 원문에서 그대로 인용**하세요.
   요약하거나 바꿔 쓰지 마세요.
4. 확신도를 정직하게 매기세요. 원문이 단정하면 certain, 추정 표현이면
   probable, 암시에 그치면 possible 입니다.
5. 관계가 없으면 빈 배열을 반환하세요. 억지로 만들지 마세요."""

RELATION_DESCRIPTIONS = {
    "participated_in": "인물이 사건에 참여·관여함",
    "created": "인물이 유물·작품을 만듦",
    "occurred_at": "사건이 특정 장소에서 일어남",
    "located_in": "유물·장소가 특정 장소에 있음",
    "from_period": "개체가 특정 시대에 속함",
    "child_of": "인물이 다른 인물의 자녀임",
    "spouse_of": "인물이 다른 인물의 배우자임",
    "held_position": "인물이 관직·칭호를 지님",
    "related_to": "위에 해당하지 않는 명확한 관련",
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "description": "원문에서 추출한 관계 목록",
            # 상한이 없으면 모델이 계속 생성하다 max_tokens 에 잘려
            # JSON 이 닫히지 않는다 (실측: 4096 토큰에서 잘려 0건 처리됨).
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "관계의 주체 이름"},
                    "subject_type": {
                        "type": "string",
                        "enum": ["person", "event", "place", "heritage", "artwork", "org", "period", "role"],
                    },
                    "relation": {"type": "string", "enum": EXTRACTABLE},
                    "object": {"type": "string", "description": "관계의 대상 이름"},
                    "object_type": {
                        "type": "string",
                        "enum": ["person", "event", "place", "heritage", "artwork", "org", "period", "role"],
                    },
                    "evidence": {
                        "type": "string",
                        "description": "이 관계의 근거가 되는 원문 구절 (그대로 인용)",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["certain", "probable", "possible"],
                    },
                },
                "required": [
                    "subject", "subject_type", "relation",
                    "object", "object_type", "evidence", "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["relations"],
    "additionalProperties": False,
}


class ExtractError(RuntimeError):
    pass


# 위키백과 본문 전체를 받으면 문서가 매우 길어진다 (6·25 전쟁 57,451자).
# 한 요청에 통째로 넣으면 뒤쪽 문단의 관계를 놓치고 비용도 커진다.
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 400  # 경계에 걸친 문장이 잘려 관계가 사라지는 것을 막는다


@dataclass(slots=True)
class Document:
    """추출 대상 문서. `node_id` 는 이 산문이 딸린 노드.

    긴 문서는 조각으로 나뉘며, 같은 `node_id` 를 공유한다."""

    node_id: str
    label: str
    text: str
    chunk: int = 0
    total_chunks: int = 1


def split_document(
    node_id: str, label: str, text: str, size: int = CHUNK_CHARS
) -> list[Document]:
    """긴 산문을 문단 경계 기준으로 자른다.

    문단 중간에서 자르면 '이순신은 …' / '… 명량에서 승리했다' 처럼 주어와
    서술이 갈라져 관계가 통째로 사라진다. 문단 경계를 우선하고, 조각 사이에
    겹침을 둬서 경계에 걸친 서술을 양쪽에서 볼 수 있게 한다."""
    if len(text) <= size:
        return [Document(node_id=node_id, label=label, text=text)]

    chunks: list[str] = []
    paragraphs = text.split("\n")
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 1 > size:
            chunks.append(buf)
            # 직전 조각 끝부분을 다음 조각 앞에 붙인다
            buf = buf[-CHUNK_OVERLAP:] + "\n" + para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf.strip():
        chunks.append(buf)

    return [
        Document(
            node_id=node_id, label=label, text=c, chunk=i, total_chunks=len(chunks)
        )
        for i, c in enumerate(chunks)
    ]


def get_client():
    """Anthropic 클라이언트. 키가 없으면 왜 없는지 분명히 알린다."""
    try:
        import anthropic
    except ImportError as err:
        raise ExtractError(
            "anthropic 패키지가 필요합니다: pip install anthropic"
        ) from err

    if not os.environ.get("ANTHROPIC_API_KEY"):
        # 키가 없어도 `ant auth login` 프로필이 있으면 동작하므로
        # 단정적으로 실패시키지 않고 그대로 진행한다.
        log.info("ANTHROPIC_API_KEY 미설정 — ant auth 프로필을 사용합니다")
    return anthropic.Anthropic()


def build_gazetteer(
    store: GraphStore, limit: int = 150, scope_ids: set[str] | None = None
) -> dict[str, list[str]]:
    """그래프에 이미 있는 개체명 목록.

    추출 결과를 기존 노드에 붙이려면 모델이 같은 표기를 써야 한다.
    전부 넣으면 프롬프트가 폭발하므로 타입별로 상한을 둔다.

    **연결 차수 순으로 고른다.** 라벨 길이순으로 뽑으면 '진', '죄', '괌'
    같은 한 글자 잡음이 목록을 채운다 — 짧은 이름이 중요한 개체라는
    보장은 없다. 실제로 많이 연결된 개체가 문헌에도 자주 등장한다.

    두 글자 미만은 제외한다. 한 글자 라벨은 본문 아무 데나 우연히
    일치해서 모델을 엉뚱한 노드로 유도한다."""
    gaz: dict[str, list[str]] = {}
    for node_type in ("person", "event", "place", "period"):
        rows = store.conn.execute(
            """SELECT n.id, n.label, COUNT(e.src) AS degree
                 FROM nodes n
                 LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
                WHERE n.type = ? AND length(n.label) >= 2
             GROUP BY n.id
             ORDER BY degree DESC, length(n.label)""",
            (node_type,),
        ).fetchall()
        # 시대를 한정하면 가제티어도 그 시대 개체만 남긴다. 조선 문서에
        # 현대 정치인 목록을 붙여봐야 프롬프트만 길어지고 오히려 방해된다.
        if scope_ids is not None:
            rows = [r for r in rows if r["id"] in scope_ids]
        gaz[node_type] = [r["label"] for r in rows[:limit]]
    return gaz


def build_prompt(doc: Document, gazetteer: dict[str, list[str]]) -> str:
    relations = "\n".join(
        f"- {k}: {RELATION_DESCRIPTIONS[k]}" for k in EXTRACTABLE
    )
    known = "\n".join(
        f"- {t}: {', '.join(names)}" for t, names in gazetteer.items() if names
    )
    # 조각임을 알려야 모델이 잘린 문맥을 통째로 놓치지 않는다
    part = (
        f" (일부 {doc.chunk + 1}/{doc.total_chunks})" if doc.total_chunks > 1 else ""
    )
    return f"""## 추출할 관계 유형
{relations}

## 알려진 개체 (표기를 맞추면 기존 그래프에 연결됩니다)
{known}

## 원문
제목: {doc.label}{part}

{doc.text}

위 원문에서 관계를 추출하세요."""


def _request_params(doc: Document, gazetteer: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "max_tokens": 8000,  # thinking 과 응답이 이 한도를 함께 쓴다
        "system": SYSTEM_PROMPT,
        "output_config": {
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            "effort": "medium",  # 구조화 추출에는 medium 이 비용/품질 균형점
        },
        "messages": [{"role": "user", "content": build_prompt(doc, gazetteer)}],
    }


def extract_one(backend, doc: Document, gazetteer: dict[str, list[str]]) -> list[dict]:
    """문서(조각) 하나를 추출. 백엔드가 Claude 든 로컬 모델이든 동일하다."""
    try:
        return backend.complete(
            SYSTEM_PROMPT, build_prompt(doc, gazetteer), OUTPUT_SCHEMA
        )
    except RuntimeError as err:
        log.warning("추출 실패 [%s#%d]: %s", doc.node_id, doc.chunk, err)
        return []


def submit_batch(client, docs: list[Document], gazetteer: dict[str, list[str]]) -> str:
    """Batch API 제출. 표준 요금의 50%로 처리된다.

    추출은 실시간성이 필요 없는 작업이라 batch 가 기본값이어야 한다."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = [
        Request(
            custom_id=f"doc-{i}",
            params=MessageCreateParamsNonStreaming(**_request_params(d, gazetteer)),
        )
        for i, d in enumerate(docs)
    ]
    batch = client.messages.batches.create(requests=requests)
    log.info("배치 제출: %s (문서 %d건)", batch.id, len(docs))
    return batch.id


def collect_batch(client, batch_id: str, docs: list[Document]) -> dict[str, list[dict]]:
    """배치 완료를 기다렸다가 결과를 수집한다.

    결과는 임의 순서로 오므로 반드시 custom_id 로 매칭한다 — 순서를
    가정하면 관계가 엉뚱한 문서에 붙는다."""
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        log.info("배치 처리 중... (%s)", batch.request_counts)
        time.sleep(30)

    out: dict[str, list[dict]] = {}
    for result in client.messages.batches.results(batch_id):
        idx = int(result.custom_id.removeprefix("doc-"))
        doc = docs[idx]
        if result.result.type != "succeeded":
            log.warning("배치 항목 실패 [%s]: %s", doc.node_id, result.result.type)
            continue
        msg = result.result.message
        if msg.stop_reason == "refusal":
            log.warning("추출 거절됨 [%s]", doc.node_id)
            continue
        text = next((b.text for b in msg.content if b.type == "text"), "")
        if not text:
            continue
        try:
            out[doc.node_id] = json.loads(text)["relations"]
        except (json.JSONDecodeError, KeyError):
            log.warning("응답 파싱 실패 [%s]", doc.node_id)
    return out


def evidence_supported(evidence: str, text: str) -> bool:
    """근거 구절이 원문에 실제로 있는가.

    실측: 모델이 `evidence: "문서에 명시되지 않음"` 이라고 적으면서 관계는
    만들어냈다. 근거 없는 관계는 검증이 불가능하므로 버린다 — 환각을
    통째로 막는 가장 확실한 지점이다.

    공백·줄바꿈 차이는 무시한다. 모델이 요약하거나 주석을 덧붙이는 경우가
    있어 앞부분 일부만 일치해도 인정한다."""
    ev = "".join((evidence or "").split())
    if len(ev) < 8:  # 너무 짧으면 우연히 일치한다
        return False
    body = "".join(text.split())
    return ev[:25] in body


def orient(
    edge_type: str, src_type: str, dst_type: str
) -> tuple[bool, bool]:
    """(스키마에 맞는가, 뒤집어야 하는가).

    실측: 모델이 `제1차 왕자의 난 --participated_in--> 이방원` 처럼 방향을
    뒤집어 낸다. 스키마는 형태를 강제하지만 **방향은 강제하지 못한다.**
    온톨로지가 허용하는 방향을 알고 있으므로 후처리에서 바로잡는다."""
    _, allowed_src, allowed_dst = EDGE_TYPES[edge_type]
    if src_type in allowed_src and dst_type in allowed_dst:
        return True, False
    # 양끝을 바꾸면 맞는가
    if dst_type in allowed_src and src_type in allowed_dst:
        return True, True
    return False, False


def to_graph(
    relations: list[dict],
    source_node: str,
    store: GraphStore,
    doc_text: str | None = None,
) -> tuple[list[Node], list[Edge]]:
    """추출 결과를 노드·엣지로 변환.

    이름으로 기존 노드를 찾고(별칭도 본다), 없으면 새로 만든다. 새 노드에는
    `ex:` 접두사를 붙여 추출 산물임을 id 만 봐도 알 수 있게 한다.

    doc_text 를 주면 근거가 원문에 없는 관계를 버린다."""
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    dropped_evidence = dropped_schema = flipped = 0

    def resolve(name: str, node_type: str) -> tuple[str, str]:
        """이름 -> (노드 id, 실제 노드 타입)."""
        row = store.conn.execute(
            "SELECT id, type FROM nodes WHERE label = ? AND type = ? LIMIT 1",
            (name, node_type),
        ).fetchone()
        if row:
            return row["id"], row["type"]
        # 별칭으로도 찾는다 — '이방원'은 '태종'의 별칭이다
        row = store.conn.execute(
            """SELECT n.id, n.type FROM aliases a JOIN nodes n ON n.id = a.node_id
               WHERE a.alias = ? LIMIT 1""",
            (name,),
        ).fetchone()
        if row:
            return row["id"], row["type"]
        # 타입 무시하고 라벨만 — 모델이 타입을 잘못 붙였을 수 있다
        row = store.conn.execute(
            "SELECT id, type FROM nodes WHERE label = ? LIMIT 1", (name,)
        ).fetchone()
        if row:
            return row["id"], row["type"]
        nid = f"ex:{node_type}:{name}"
        nodes.setdefault(
            nid, Node(id=nid, type=node_type, label=name, source="extract")
        )
        return nid, node_type

    for rel in relations:
        try:
            edge_type = rel["relation"]
            if edge_type not in EDGE_TYPES:
                continue

            if doc_text is not None and not evidence_supported(
                rel.get("evidence", ""), doc_text
            ):
                dropped_evidence += 1
                continue

            src, src_type = resolve(rel["subject"], rel["subject_type"])
            dst, dst_type = resolve(rel["object"], rel["object_type"])

            ok, flip = orient(edge_type, src_type, dst_type)
            if not ok:
                dropped_schema += 1
                continue
            if flip:
                src, dst = dst, src
                flipped += 1

            edges.append(
                Edge(
                    src=src,
                    dst=dst,
                    type=edge_type,
                    source="extract",
                    confidence=CONFIDENCE.get(rel.get("confidence", ""), 0.5),
                    props={
                        "evidence": rel.get("evidence", ""),
                        "extracted_from": source_node,
                        "model": MODEL,
                        **({"flipped": True} if flip else {}),
                    },
                )
            )
        except (KeyError, ValueError) as err:
            log.warning("관계 변환 실패: %s (%s)", rel, err)

    if dropped_evidence or dropped_schema or flipped:
        log.info(
            "  근거없음 %d건 버림 · 스키마불일치 %d건 버림 · 방향교정 %d건",
            dropped_evidence, dropped_schema, flipped,
        )
    return list(nodes.values()), edges


def load_scope_ids(scope_db: str) -> set[str]:
    """시대 서브그래프에 속한 노드 id 집합.

    `scope` 로 뽑아둔 DB 를 그대로 재사용한다 — 추출 대상을 그 시대로
    좁히면 비용이 줄고, 결과가 그 그래프에 바로 반영되어 효과를 눈으로
    확인할 수 있다."""
    import sqlite3

    conn = sqlite3.connect(scope_db)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM nodes")}
    finally:
        conn.close()


PERSON_HINT = re.compile(
    # 신분·관직
    r"왕|대군|공주|옹주|장군|정승|판서|영의정|좌의정|우의정|관찰사|"
    r"문신|무신|학자|유학자|승려|스님|화가|서예가|선생|"
    # 인물 행위
    r"급제|출사|사사|피살|유배|배향|시호|본관은|호는|자는|"
    r"[가-힣]{2,3}(?:이|가)\s*(?:만들|짓|썼|세웠|그렸)"
)
EVENT_HINT = re.compile(
    r"전쟁|난\b|왜란|호란|반정|사화|운동|봉기|정변|사건|회군|"
    r"즉위|건립|중건|창건|소실|이전|복원|피란|천도|개국|축조|중수|"
    r"처형|폐위|책봉|출병|정벌|조약|항쟁"
)
# 서지·규격 기술 — 물건이 무엇인지 적은 글. 관계가 거의 없다.
CATALOG_HINT = re.compile(
    r"크기|규격|\dcm|재질|장정|판심|반곽|행자수|권차|장차|지질|보존상태"
)


def narrative_score(text: str) -> float:
    """이 산문에서 인물↔사건 관계를 캘 수 있을 가능성.

    국가유산청 `content` 2,903건을 표지어로 훑어보면 인물·사건이 함께
    나오는 글은 634건(22%)뿐이고, 27%는 순수 서지 기술이다. 길이만 보고
    고르면 가장 긴 문서가 판본 치수 나열인 경우가 생겨 API 비용이 헛돈다."""
    score = 0.0
    if PERSON_HINT.search(text):
        score += 1.0
    if EVENT_HINT.search(text):
        score += 1.0
    if CATALOG_HINT.search(text):
        score -= 0.5
    # 길이는 약한 보정으로만 쓴다 — 긴 글이 곧 서사는 아니다
    return score + min(len(text) / 4000, 0.5)


def load_documents(
    store: GraphStore,
    limit: int | None = None,
    min_score: float = 1.0,
    scope_ids: set[str] | None = None,
) -> list[Document]:
    """추출 가치가 높은 순으로 문서를 고른다.

    min_score=1.0 은 인물이나 사건 표지 중 하나 이상을 요구한다.
    2.0 으로 올리면 둘 다 있는 글만 남는다.

    scope_ids 를 주면 그 노드들의 산문만 대상으로 한다."""
    rows = store.conn.execute(
        """SELECT id, label, description FROM nodes
           WHERE description IS NOT NULL AND length(description) > 100"""
    ).fetchall()

    if scope_ids is not None:
        before = len(rows)
        rows = [r for r in rows if r["id"] in scope_ids]
        log.info("범위 한정: 산문 %d건 → %d건", before, len(rows))

    scored = [
        (narrative_score(r["description"]), r)
        for r in rows
    ]
    kept = sorted(
        ((s, r) for s, r in scored if s >= min_score),
        key=lambda x: x[0],
        reverse=True,
    )
    log.info(
        "산문 %d건 중 서사 점수 %.1f 이상 %d건 선별", len(rows), min_score, len(kept)
    )
    if limit:
        kept = kept[:limit]

    docs: list[Document] = []
    for _, r in kept:
        docs.extend(split_document(r["id"], r["label"], r["description"]))
    long_docs = sum(1 for _, r in kept if len(r["description"]) > CHUNK_CHARS)
    if long_docs:
        log.info(
            "긴 문서 %d건을 조각내어 총 %d개 요청", long_docs, len(docs)
        )
    return docs
