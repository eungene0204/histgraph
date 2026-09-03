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
from collections import defaultdict
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
    dropped_evidence = dropped_schema = flipped = self_loops = 0
    dropped_possessive = dropped_anachronism = dropped_reversed = 0
    dropped_unnamed = dropped_loss = dropped_departure = dropped_kin = 0

    # 가제티어 덤프는 낱개로 보면 멀쩡해 보인다. 묶음 단위로 먼저 걸러낸다.
    dumped = gazetteer_dump(relations)

    # 이름 하나가 여러 노드를 가리킬 때 **연결이 많은 쪽**을 고른다.
    # 실측: '정종'을 이름 그대로 찾으면 엣지 1개짜리 동명 노드가 걸리고,
    # 관계 25건을 가진 조선 정종(wd:Q485556)은 라벨이 '조선 정종'이라
    # 비켜간다. 그래서 화면에서 정종은 아버지도 형제도 없는 외톨이가 됐다.
    #
    # 라벨과 별칭을 **한 번에** 본다. 라벨 일치를 무조건 앞세우면 위와
    # 같은 일이 되풀이된다 — 그 이름으로 불릴 수 있는 후보를 모두 모은 뒤
    # 가장 잘 연결된 것을 고르는 편이 산문의 의도에 가깝다.
    CANDIDATES = """
        SELECT n.id, n.type, n.start_date, n.end_date,
               (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS deg
          FROM nodes n
         WHERE (n.label = ?1
                OR EXISTS (SELECT 1 FROM aliases a
                            WHERE a.node_id = n.id AND a.alias = ?1))
               {type_clause}
      ORDER BY deg DESC, n.id
         LIMIT 8"""

    # 출처 문서의 연대. 동명이인을 가를 때 기준이 된다 — 안방준(1573~1654)
    # 문서에 나온 '이황'은 예종(1450~1469)이 아니라 퇴계(1501~1570)다.
    from .promote import life_span as _life_span

    _doc = store.conn.execute(
        "SELECT start_date, end_date FROM nodes WHERE id = ?", (source_node,)
    ).fetchone()
    doc_span = _life_span(_doc["start_date"], _doc["end_date"]) if _doc else None

    def node_dates(node_id: str) -> tuple[str | None, str | None]:
        """저장된 연대. 이번에 만든 ex: 노드는 아직 store 에 없으므로
        메모리의 것을 본다 — 라벨 연도(`황진이 (2006년)`)가 여기서 잡힌다."""
        if node_id in nodes:
            return (nodes[node_id].start_date, nodes[node_id].end_date)
        row = store.conn.execute(
            "SELECT start_date, end_date FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return (row["start_date"], row["end_date"]) if row else (None, None)

    def reversed_by_source(edge_type: str, src: str, dst: str) -> bool:
        """구조화 소스가 **반대 방향**을 이미 알고 있는가.

        `child_of` 는 person→person 이라 `orient()` 가 방향을 못 가린다.
        실측: 추출 가족 관계 122건 중 50건이 구조화 소스와 어긋났고 대부분
        방향이 뒤집힌 것이었다 — `폐비 윤씨 --child_of--> 조선 연산군`
        (연산군이 그녀의 아들이다), `조선 인조 --child_of--> 소현세자`
        (소현세자가 인조의 아들이다).

        Wikidata·인포박스가 `연산군 --child_of--> 폐비 윤씨` 를 이미 갖고
        있으면 추출본은 뒤집힌 것이다. 옳은 엣지가 이미 있으므로 버린다."""
        if edge_type not in ("child_of", "spouse_of"):
            return False
        return store.conn.execute(
            """SELECT 1 FROM edges
                WHERE src = ? AND dst = ? AND type = ?
                  AND source IN ('wd', 'kowiki:infobox') LIMIT 1""",
            (dst, src, edge_type),
        ).fetchone() is not None

    def resolve(name: str, node_type: str) -> tuple[str, str]:
        """이름 -> (노드 id, 실제 노드 타입)."""
        name = normalize_name(name)
        row = pick_candidate(
            store.conn.execute(
                CANDIDATES.format(type_clause="AND n.type = ?2"), (name, node_type)
            ).fetchall(),
            doc_span,
        )
        if row:
            return row["id"], row["type"]
        # 타입을 무시하고 한 번 더 — 모델이 타입을 잘못 붙였을 수 있다
        row = pick_candidate(
            store.conn.execute(
                CANDIDATES.format(type_clause=""), (name,)
            ).fetchall(),
            doc_span,
        )
        if row:
            return row["id"], row["type"]
        nid = f"ex:{node_type}:{name}"
        nodes.setdefault(
            nid, Node(id=nid, type=node_type, label=name, source="extract",
                      start_date=label_year(name) if node_type == "event" else None)
        )
        return nid, node_type

    for index, rel in enumerate(relations):
        try:
            edge_type = rel["relation"]
            if edge_type not in EDGE_TYPES:
                continue

            if index in dumped:
                continue

            if doc_text is not None and not evidence_supported(
                rel.get("evidence", ""), doc_text
            ):
                dropped_evidence += 1
                continue

            if possessive_mismatch(edge_type, rel.get("object", ""),
                                   rel.get("evidence", "")):
                dropped_possessive += 1
                continue

            if kin_title_mismatch(edge_type, rel.get("object", ""),
                                  rel.get("evidence", ""),
                                  name_variants(rel.get("object", "") or " ")):
                dropped_kin += 1
                continue

            if loss_context(edge_type, rel.get("evidence", "")):
                dropped_loss += 1
                continue

            if movement_origin(edge_type, rel.get("object", ""),
                               rel.get("evidence", "")):
                dropped_departure += 1
                continue

            # 이름 자리에 설명구가 온 것. 가리키는 사람을 특정할 수 없으므로
            # 노드를 만들지 않는다 (`양윤순의 따님` → 이름을 모른다).
            if is_descriptive_name(rel.get("object", "")) or is_descriptive_name(
                rel.get("subject", "")
            ):
                dropped_possessive += 1
                continue

            evidence = rel.get("evidence", "")
            src, src_type = resolve(rel["subject"], rel["subject_type"])
            dst, dst_type = resolve(rel["object"], rel["object_type"])

            # 모델이 같은 개체를 양끝에 놓는 일이 있다 (실측: '기사환국이
            # 기사환국과 관련된다'). 자기순환은 아무 사실도 말하지 않는다.
            if src == dst:
                self_loops += 1
                continue

            # 사건 라벨에 연도가 없으면 근거의 연도를 임시 단서로 쓴다.
            # **저장하지는 않는다** — 실측 정확도가 88%(신유박해를 1760년
            # 으로 읽는 식)라 사실로 적을 수 없다. 죽은 지 수백 년 뒤를
            # 가리는 데에는 그 정확도로 충분하다.
            dst_dates = node_dates(dst)
            if dst_type == "event" and not any(dst_dates):
                dst_dates = (evidence_year(evidence), None)

            if lifespan_conflict(edge_type, node_dates(src), dst_dates):
                dropped_anachronism += 1
                continue

            if reversed_by_source(edge_type, src, dst):
                dropped_reversed += 1
                continue

            # 근거가 상대 인물을 지목하지 않으면 검증할 수 없는 엣지다.
            # 문서 주인은 예외 (그 글이 곧 그 사람의 글이다).
            if dst_type == "person" and dst != source_node:
                row = store.conn.execute(
                    "SELECT label FROM nodes WHERE id = ?", (dst,)
                ).fetchone()
                if row:
                    names = name_variants(row["label"]) | {
                        a["alias"]
                        for a in store.conn.execute(
                            "SELECT alias FROM aliases WHERE node_id = ?", (dst,)
                        )
                    }
                    if not evidence_names_target(rel.get("evidence", ""), names):
                        dropped_unnamed += 1
                        continue

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

    if (dropped_evidence or dropped_schema or flipped or self_loops
            or dropped_possessive or dropped_anachronism or dropped_reversed
            or dropped_unnamed or dropped_loss or dropped_departure
            or dropped_kin or dumped):
        log.info(
            "  근거없음 %d건 버림 · 스키마불일치 %d건 버림 · 자기순환 %d건 버림"
            " · 소유격오독 %d건 버림 · 소실문형 %d건 버림 · 연대충돌 %d건 버림"
            " · 역방향 %d건 버림 · 근거무지목 %d건 버림 · 가제티어덤프 %d건 버림"
            " · 떠난자리 %d건 버림 · 친족호칭 %d건 버림 · 방향교정 %d건",
            dropped_evidence, dropped_schema, self_loops, dropped_possessive,
            dropped_loss, dropped_anachronism, dropped_reversed, dropped_unnamed,
            len(dumped), dropped_departure, dropped_kin, flipped,
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

# 족보 목록 행 — 인물 문서의 '가족 관계' 절은 `증손부 : 창녕조씨` 꼴
# 목록이다. 실측(안방준 검증, 2026-08-14): 이 목록을 그대로 주면 모델이
# (1) 증손부·손서 같은 방계 인물을 본인의 spouse_of 로 붙이고,
# (2) 장남을 본인의 부모로 뒤집고 (`장남 : 안후지` → 안방준 child_of 안후지),
# (3) 같은 관계 블록을 4번 반복하는 루프에 빠져 조각당 6분을 태운다.
# 직계 가족은 서사 문단("아버지는 안중관이며, 처는…")에서 올바르게
# 뽑히므로 목록 행을 지워도 잃는 것이 없다.
#
# **호칭을 열거하려 하지 말 것.** 처음엔 생부·양부·증손부처럼 60개를 적어
# 뒀는데 실측(인물 산문 46,370줄)에서 2,265줄을 놓쳤다. 놓친 라벨 상위 30개가
# 전부 친족어였다 — 할아버지·서손자·종증조부·재종숙·손녀사위·사돈·당질…
# 한국어 친족어는 접두사(종·재종·삼종·외·처·시·양·이복)와 어간이 자유롭게
# 붙는 생성형이라 목록으로 못 덮는다. 실제로 안방준 문서의 `종조부`·
# `재종숙` 이 새어 나와 방계 9명이 그의 부모로 들어갔다.
#
# 그래서 어휘가 아니라 **구조**로 잡는다: 줄 첫머리의 짧은 한글 라벨 + 콜론.
# 이 형태로 걸리는 9,129줄 중 친족어 힌트조차 없는 것은 430줄뿐이고
# 그마저 대부분 친족이다(할아버지·사촌·올케·아내). 서술문은 걸리지 않는다
# — `아버지는 첨지중추부사 안중관이며` 는 라벨 뒤가 콜론이 아니다.
KINSHIP_LINE = re.compile(r"^\s*[가-힣]{1,6}(?:\([^)]{0,12}\))?\s*:\s")


def strip_kinship_lists(text: str) -> str:
    """족보 목록 행을 제거한다. 서사 문단은 건드리지 않는다."""
    return "\n".join(
        line for line in text.splitlines() if not KINSHIP_LINE.match(line)
    )


# 소유격을 삼켜 **한 세대를 건너뛰는** 오류를 잡는다.
#
# 실측: `처는 경주 정씨 판관 정승복(鄭承復)의 딸이다` 에서 모델이
# `안방준 --spouse_of--> 정승복` 을 냈다. 안방준의 아내는 정승복의 딸이지
# 정승복이 아니다. 근거 검증은 이걸 못 잡는다 — 근거 구절이 원문에 그대로
# 있기 때문이다. 한국어 인물 산문에서 여성은 이름 대신 `누구의 딸` 로만
# 적히는 일이 흔해서 이 형태가 반복된다.
#
# **관계 타입마다 판정이 뒤집힌다는 점이 함정이다.** `A --child_of--> B` 는
# 'A 는 B 의 자녀' 라는 뜻이므로 `안중관의 아들 안방준` 에서 나온
# `안방준 --child_of--> 안중관` 은 **옳다**. 같은 소유격이 spouse_of 에서는
# 오류고 child_of 에서는 정답이다. 한 규칙으로 뭉뚱그리면 맞는 부모 관계를
# 버린다.
#
# 딸의 이름이 원문에 없으므로 **고쳐 붙일 수 없다. 버리는 것이 맞다.**
_PARENT_KIN = r"딸|따님|아들|자제|소생|자녀"      # 한 세대 아래
_DESCENDANT_KIN = r"손자|손녀|증손|현손|후손|외손"  # 두 세대 이상 아래

# 관계 타입 -> 그 타입에서 '건너뛴 세대' 를 뜻하는 친족어
POSSESSIVE_SKIP: dict[str, str] = {
    # 배우자는 상대의 부모·조부를 가리키면 전부 오류다
    "spouse_of": rf"{_PARENT_KIN}|{_DESCENDANT_KIN}",
    # 자녀 관계에서 `X의 아들` 은 정상. `X의 손자` 만 한 세대를 건너뛴 것.
    "child_of": _DESCENDANT_KIN,
}


# 이름이 아니라 **설명구**인 것. 노드로 만들면 안 된다.
#
# 실측: `spouse_of 양윤순(梁允純)의 따님` 이라는 노드가 생겼다. 산문이
# 여성을 이름 없이 `누구의 딸` 로만 적었는데 모델이 그 구절을 통째로
# 이름으로 냈다. `possessive_mismatch` 는 **근거 안에서** 소유격을 찾으므로
# 이름 자체가 설명구인 이 경우를 놓친다.
DESCRIPTIVE_NAME = re.compile(
    rf"의\s*(?:{_PARENT_KIN}|{_DESCENDANT_KIN}"
    r"|부인|처|아내|남편|어머니|아버지|부모|형|아우|동생|누이)\s*$"
)


def name_variants(label: str) -> set[str]:
    """산문이 이 인물을 부를 법한 표기들.

    한국어 산문은 성을 떼고 부르는 일이 잦다 — `김종직` 을 `종직에게
    수업하였는데`, `윤필상` 을 `필상 등에게` 로 쓴다. 라벨만 대조하면
    멀쩡한 관계를 근거 없음으로 오판한다."""
    parts = label.split()
    bare = parts[-1]
    # 파생형은 두 글자 이상만 쓴다 — 한 글자는 본문 아무 데나 걸린다.
    derived = {x for x in (parts[-1], bare[1:] if 3 <= len(bare) <= 4 else "")
               if len(x) >= 2}
    # 원본 라벨은 길이와 무관하게 always 포함한다. 빼면 한 글자 라벨의
    # 후보가 통째로 비어 모든 관계가 '근거 무지목' 으로 버려진다.
    return {label} | derived


def evidence_names_target(evidence: str, names: set[str]) -> bool:
    """근거 구절이 상대를 실제로 지목하는가.

    실측: 인물 대상 관계 268건 중 14건(5%)이 근거에 상대 이름이 없었고
    대부분 지어낸 것이었다 — `정약종의 아들 정철상도 구속되었고` 에서
    `child_of 정약용`, 이순신·김억추 이야기에서 `child_of 이이`.
    **근거 검증은 구절이 원문에 있는지만 보므로 이것을 못 잡는다.**

    문서 주인에게는 적용하지 않는다. `3·1 운동` 문서의 문장은 그 사건
    이름을 다시 적지 않는 것이 자연스럽다 (실측: 그렇게 하면 정상 엣지
    363건이 날아간다)."""
    flat = "".join(evidence.split())
    return any("".join(n.split()) in flat for n in names)


# 가제티어 덤프. 모델이 원문을 읽는 대신 프롬프트의 '알려진 개체' 목록을
# 그대로 쏟아내고, 근거 칸에는 문서 첫 문장을 붙인다.
#
# 실측(조선 그래프): `무오사화 --from_period-->` 39건이 한 문장을 근거로
# 달려 있었고 대상 39개가 **전부** 가제티어 period 상위 150개였다
# (조선 세조 12년(1466), 조선 선조 17년(1584)…). 무오사화는 1498년이다.
# 같은 꼴로 조선 효종 23건·이순신 11건·정승충 5건이 더 있었다.
#
# 열거문과는 **지목률**로 갈린다. `시조 작품으로는 A, B, C 등이 있다` 같은
# 정상 열거문은 근거가 대상을 88~100% 지목하는데, 덤프는 0~20%다. 그래서
# 낱개로 보지 않고 **한 문장이 낳은 묶음 단위**로 본다 — 근거가 원문에
# 실제로 있고 문장 하나만 놓고 보면 멀쩡해서 낱개 검사로는 못 잡는다.
#
# 지목 못한 것만 버린다. 통째로 버리면 `손자이자 정숭조의 아들인 정승충은`
# 에서 하나뿐인 옳은 부모(정숭조)까지 같이 날아간다.
DUMP_MIN_GROUP = 5        # 이보다 작으면 열거문과 구분되지 않는다
DUMP_UNNAMED_RATIO = 0.5  # 지목 못한 것이 과반이면 읽고 쓴 것이 아니다


def gazetteer_dump(relations: list[dict]) -> set[int]:
    """버릴 관계의 인덱스. 모델 출력을 (주어, 관계, 근거)로 묶어 판정한다."""
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, rel in enumerate(relations):
        if evidence := rel.get("evidence", ""):
            groups[(rel.get("subject", ""), rel.get("relation", ""), evidence)].append(i)

    drop: set[int] = set()
    for (_, _, evidence), members in groups.items():
        if len(members) < DUMP_MIN_GROUP:
            continue
        unnamed = [
            i for i in members
            if not evidence_names_target(
                evidence, name_variants(normalize_name(relations[i].get("object", "")))
            )
        ]
        if len(unnamed) > len(members) * DUMP_UNNAMED_RATIO:
            drop.update(unnamed)
    return drop


# 한자 병기 꼬리. `송시열(宋時烈)` 이 `송시열` 과 다른 노드가 되는 것을 막는다.
HANJA_TAIL = re.compile(r"\s*\([一-鿿\s,·]+\)\s*$")

# 라벨·근거에 적힌 연도. 영화·드라마를 사건으로 추출한 노드는 start_date 가
# 비어 연대 검사에 안 걸린다 — 죽은 지 400년 뒤의 드라마에 '참여'한 엣지가
# 그래서 살아남았다.
#
# **끝자리 괄호만 보면 절반을 놓친다.** 처음에 `(YYYY년)` 꼬리만 봤더니
# `황진이 (2006년)` 은 잡고 `2021년~2022년 KBS 1TV 드라마 《태종 이방원》`,
# `1996년~1998년 …《용의 눈물》` 은 그대로 통과해 76건이 남았다. 자리를
# 가리지 않고 **처음 나오는 네 자리 연도**를 쓴다. 세 자리 미만은 받지
# 않는다 — `조선 세조 12년(1466)` 의 `12년` 은 재위년이지 연도가 아니다.
LABEL_YEAR = re.compile(r"(\d{3,4})년")


def label_year(text: str) -> str | None:
    """라벨(또는 근거)에서 처음 나오는 연도. 없으면 None."""
    m = LABEL_YEAR.search(text or "")
    return m.group(1) if m else None


def evidence_year(evidence: str) -> str | None:
    """근거에 적힌 가장 이른 연도. 라벨에 연도가 없는 사건의 마지막 단서다.

    `《왕과 비》 (KBS 1TV, 1998년~2000년 배우:이광기)` 처럼 라벨(`왕과 비
    출연`)만으로는 언제 일인지 알 수 없는 것들이 있다. **가장 이른 것**을
    쓴다 — 연대 충돌 판정을 느슨한 쪽으로 몰아 멀쩡한 엣지를 덜 죽인다."""
    years = LABEL_YEAR.findall(evidence or "")
    return min(years, key=int) if years else None


def normalize_name(name: str) -> str:
    """추출된 이름을 그래프의 라벨 표기에 맞춘다.

    실측: 같은 문서에서 `송시열` 과 `송시열(宋時烈)` 이 각각 노드가 되어
    화면에 같은 사람이 둘로 나왔다. 조헌·이상익·최영성도 마찬가지였다.
    한자 병기는 표기 차이일 뿐 다른 사람이 아니다."""
    return HANJA_TAIL.sub("", name).strip()


def is_descriptive_name(name: str) -> bool:
    """`양윤순의 따님` 처럼 이름이 아니라 설명구인가."""
    return bool(DESCRIPTIVE_NAME.search(name.strip()))


# 가족 관계는 두 사람이 **같은 시대를 살아야** 성립한다.
#
# 실측(인물↔인물 추출 엣지 81건 중 생몰년을 아는 것): 70건은 생애가 겹치고
# 121년 넘게 벌어진 7건은 전부 오류였다. 그중
#   이세좌 --child_of--> 이수원   451년 차이
#   이세좌 --spouse_of--> 이수원   451년 차이 (같은 쌍에 모순된 두 관계)
# 처럼 정의상 불가능한 것이 5건이다. 이름이 같은 다른 시대 사람에게 붙은
# 것으로, 근거 검증도 이름 해소도 막지 못한다.
#
# `related_to` 는 넣지 않는다 — `김종직 --related_to--> 주희`(498년)처럼
# 학맥·추숭 관계는 시대가 달라도 참일 수 있다.
#
# `participated_in` 도 검사한다 — 참여는 그 시대를 살아야 성립한다.
# 실측: 황진이(1506~1567)가 병자호란(1636)에 '참여'했다고 추출됐다.
# 근거 문장("임진왜란과 병자호란 등으로 인해 대부분 실전되었고")은
# 원문에 실제로 있고 상대 이름도 들어 있어 근거 검증을 다 통과한다 —
# 관계(서술어)만 틀린 오류는 연대로밖에 못 잡는다.
LIFESPAN_CHECKED = {"child_of", "spouse_of", "participated_in"}
# 생몰년 표기가 어긋나거나 한쪽만 아는 경우를 감안해 넉넉히 잡는다.
LIFESPAN_TOLERANCE = 40


def lifespan_conflict(
    edge_type: str, src_dates: tuple[str | None, str | None],
    dst_dates: tuple[str | None, str | None],
) -> bool:
    """가족 관계인데 두 사람의 생애가 겹칠 수 없는가."""
    if edge_type not in LIFESPAN_CHECKED:
        return False
    from .promote import life_span

    a, b = life_span(*src_dates), life_span(*dst_dates)
    if a is None or b is None:
        return False  # 근거가 없으면 막지 않는다
    gap = max(a[0], b[0]) - min(a[1], b[1])
    return gap > LIFESPAN_TOLERANCE


def pick_candidate(rows: list, doc_span: tuple[int, int] | None):
    """이름이 여러 노드를 가리킬 때 하나를 고른다.

    기본 기준은 **연결 차수**다 — 산문이 '정종'이라 쓸 때 엣지 1개짜리
    동명 노드가 아니라 관계 24건짜리 조선 정종을 뜻할 가능성이 크다.

    다만 차수만 보면 **왕의 휘(諱)가 다른 유명인을 잡아먹는다.** 실측:
    조선 예종의 휘가 이황(李晄)이라 별칭에 '이황'이 있는데, 안방준 문서의
    `퇴계 이황(李滉)의 문인` 에서 차수 큰 예종이 이겼다. 한글이 같을 뿐
    다른 사람이다.

    그래서 **출처 문서의 연대와 겹치는 후보를 먼저 본다.** 겹치는 것이
    있으면 그 안에서 차수로 고르고, 없으면 원래대로 차수만 본다
    (연대를 모르는 후보를 탈락시키면 멀쩡한 연결이 사라진다)."""
    if not rows:
        return None
    if doc_span is None:
        return rows[0]
    from .promote import life_span

    compatible = []
    for r in rows:
        span = life_span(r["start_date"], r["end_date"])
        if span is None:
            continue
        if not (max(span[0], doc_span[0]) - min(span[1], doc_span[1]) > LIFESPAN_TOLERANCE):
            compatible.append(r)
    return compatible[0] if compatible else rows[0]


# 이름 **앞에** 붙어 관계를 말해 주는 호칭 중 부모가 아닌 것.
#
# 실측: 윤임의 부모가 20명이었다 — 할아버지 윤보, 숙부 윤여해, 외삼촌
# 박원종, 이복 여동생 윤옥춘, 사돈 월산대군까지 전부 부모로 들어왔다.
# 산문은 이름 앞에 관계를 적어 두는데(`숙부 윤여해도 연좌되어`) 추출이
# 그 호칭을 버리고 이름만 가져간 자리다.
#
# `친정아버지`·`양아버지` 처럼 부모를 가리키는 호칭은 넣지 않는다.
NON_PARENT_TITLE = (
    r"할아버지|할머니|조부|조모|증조부|증조모|증조할아버지|고조부|외조부|외조모"
    r"|외할아버지|외할머니|시아버지|시어머니|장인|장모|사돈|삼촌|숙부|백부|계부"
    r"|외숙|당숙|족숙|고모부|이모부|고모|이모|조카|생질|사촌|재종|종형|종제|종손"
    r"|처남|매부|매형|형부|제부|올케|며느리|사위|손자|손녀|외손|후손|방계"
    r"|이복\s*여동생|이복\s*동생|여동생|남동생|동생|아우|누이|누나|언니|오빠"
    r"|형님|맏형|둘째\s*형|셋째\s*형|외조카|외삼촌|처조카|스승|제자|문인"
)
# 호칭 뒤에 조사가 붙는다: `동생은 신상으로`, `사돈 윤근수`, `할아버지:신숙권`
_TITLE_BEFORE = re.compile(
    rf"(?:{NON_PARENT_TITLE})\s*[:·,]?\s*(?:은|는|이|가|인|이며|이자|되는)?\s*$"
)


def kin_title_mismatch(edge_type: str, obj: str, evidence: str,
                       names: set[str] | None = None) -> bool:
    """근거가 상대를 **부모가 아닌 친족**으로 부르고 있는가.

    이름 바로 앞의 호칭만 본다. 한 문장에 친족어가 여럿 나오는 것은
    흔한 일이라(`아버지 신명화의 6촌 동생은 신상으로`) 문장 전체에서
    찾으면 옳은 부모까지 날아간다."""
    if edge_type != "child_of" or not obj or not evidence:
        return False
    for name in (names or {obj}):
        start = 0
        while True:
            pos = evidence.find(name, start)
            if pos < 0:
                break
            if _TITLE_BEFORE.search(evidence[max(0, pos - 14):pos]):
                return True
            start = pos + 1
    return False


def possessive_mismatch(edge_type: str, obj: str, evidence: str) -> bool:
    """근거가 `<대상>의 딸` 꼴이면 대상은 상대가 아니라 그 윗대다."""
    kin = POSSESSIVE_SKIP.get(edge_type)
    if not kin or not obj or not evidence:
        return False
    # 대상 이름 바로 뒤(한자 병기·공백은 건너뛴다)에 소유격 친족어가 오는가
    pos = evidence.find(obj)
    if pos < 0:
        return False
    tail = evidence[pos + len(obj):]
    tail = re.sub(r"^\s*\([^)]{0,20}\)", "", tail)  # `(鄭承復)` 같은 한자 병기
    return bool(re.match(rf"\s*의\s*(?:{kin})", tail))


# `~로 인해 소실되었다` — 사건이 원인으로만 언급된 문장. 참여가 아니다.
# 실측: 황진이 문서의 "임진왜란과 병자호란 등으로 인해 대부분 실전되었고"
# 에서 participated_in 두 건이 나왔다 (작품이 실전된 것이지 본인이 참전한
# 것이 아니다). 원인 문형과 소실 어휘가 **둘 다** 있어야 버린다 — 소실
# 어휘만으로 거르면 원균의 해전 참여 7건 같은 정상 엣지가 날아간다.
LOSS_CAUSE = re.compile(r"(?:으로|로)\s*인해|때문에")
LOSS_VERB = re.compile(r"소실|실전|인멸|불타|파괴|훼손|망실|유실|소각")


def loss_context(edge_type: str, evidence: str) -> bool:
    """근거가 참여가 아니라 '그 사건 탓에 잃었다'는 문장인가."""
    if edge_type != "participated_in" or not evidence:
        return False
    return bool(LOSS_CAUSE.search(evidence) and LOSS_VERB.search(evidence))


# `A를 출발하여 B에 이르렀다` — 지나온 곳이지 일어난 곳이 아니다.
# 실측: '위화도 회군'의 발생 장소가 평양시로 들어왔다. 근거는 "출정군은
# 5월 24일 평양을 출발하여 ... 위화도에 진주하였다" 로, 평양은 떠난
# 자리다. 화면은 그걸 "위화도 회군은 평양시에서 일어났다"고 읽는다.
#
# **떠남 어휘만 본다.** '~로 회군하여'·'~로 향하여' 같은 이동 문형까지
# 걸면 도착지에서 실제로 벌어진 사건(개경 정변)까지 날아간다.
DEPARTURE = "(?:출발|떠나|떠났|떠난)"


def movement_origin(edge_type: str, obj: str, evidence: str) -> bool:
    """근거에서 그 장소가 '떠나온 곳'으로만 나오는가."""
    if edge_type not in ("occurred_at", "born_in", "died_in", "located_in"):
        return False
    if not obj or not evidence:
        return False
    # '평양시'가 본문에는 '평양'으로 나온다 — 행정 접미사는 떼고 찾는다
    stem = re.sub(r"(시|군|구|현|성|부|도)$", "", obj) if len(obj) > 2 else obj
    for name in {obj, stem}:
        pattern = rf"{re.escape(name)}(?:\([^)]*\))?\s*(?:을|를|에서)\s*{DEPARTURE}"
        if re.search(pattern, evidence):
            return True
    return False


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


def structural_coverage(store: GraphStore, node_id: str) -> set[str]:
    """이 노드에 대해 **구조화 소스로 이미 확보한** 관계 타입.

    국가유산청 API, 위키백과 인포박스처럼 파싱으로 얻은 관계는 LLM 이
    다시 뽑을 이유가 없다. 추출 대상에서 빼면 요청 수가 크게 준다."""
    return {
        r["type"]
        for r in store.conn.execute(
            """SELECT DISTINCT type FROM edges
               WHERE (src = ? OR dst = ?)
                 AND source IN ('khs', 'kowiki:infobox', 'kowiki', 'wd')""",
            (node_id, node_id),
        )
    }


# 산문에서 캘 수 있지만 구조화 소스가 못 주는 관계. 이게 없으면 LLM 을
# 부를 이유가 없다.
LLM_ONLY = {"participated_in", "created", "held_position", "child_of", "spouse_of"}


# 유물 문서에서 LLM 만 줄 수 있는 것은 제작자뿐이다. 사람 이름과 함께
# 나올 때만 값이 있다 — '건립되었다' 처럼 주체 없는 서술은 관계가 안 된다.
MAKER_WITH_NAME = re.compile(
    r"[가-힣]{2,4}(?:이|가|은|는|의)\s*(?:만들|제작|지었|썼|그렸|새겼|주조|봉안)"
    r"|(?:만든|제작한|지은|쓴|그린|새긴)\s*(?:이|사람|장인)?\s*[가-힣]{2,4}"
)


def worth_extracting(store: GraphStore, node_id: str, node_type: str, text: str) -> bool:
    """이 문서에 LLM 을 부를 값이 있는가. **노드 타입별로 다르다.**

    실측 근거: 조선 추출 대상 404조각 중 270조각(67%)이 유물 해설문인데,
    거기서 뽑을 located_in·from_period 는 국가유산청 API 로 이미 5,813건
    확보돼 있다. LLM 만 줄 수 있는 제작자가 실제로 이름과 함께 나오는
    조각은 270개 중 23개(9%)뿐이었다 — 18시간을 써서 23건을 얻는 셈이다.

    주의: 여기서 인물·사건 표지를 다시 검사하면 안 된다. min_score 2.0 이
    이미 그 조건을 요구하므로 통과 문서는 전부 참이 되어 필터가 무력해진다."""
    if node_type == "heritage":
        # 소재지·시대는 구조화 API 가 이미 100% 준다. 제작자만 새롭다.
        return bool(MAKER_WITH_NAME.search(text))

    if node_type == "event":
        # 인포박스가 지휘관·교전국을 이미 뽑았다면 서사에서 더 캘 몫이 준다.
        # 다만 인포박스는 대표 인물만 주므로 본문이 길면 여전히 값이 있다.
        covered = {
            r["type"]
            for r in store.conn.execute(
                """SELECT DISTINCT type FROM edges
                   WHERE (src = ? OR dst = ?) AND source = 'kowiki:infobox'""",
                (node_id, node_id),
            )
        }
        if "participated_in" in covered and len(text) < 4000:
            return False
        return True

    # 인물·조직은 구조화 소스가 관직·참여를 거의 못 준다. 항상 대상.
    return True


def chunk_density(text: str) -> float:
    """조각의 관계 밀도 — 1,000자당 인물·사건 표지 수.

    긴 인물 문서를 앞에서부터 N조각만 취하는 방식은 쓰지 않는다. 실측:
    송시열 문서는 9번째 조각에도 인물표지가 32개 있고, 이순신은 5조각이
    고르게 분포한다. 밀도가 떨어지는 건 마지막 조각(각주·저서 목록)뿐이라
    위치가 아니라 내용으로 골라야 알짜를 버리지 않는다."""
    if not text:
        return 0.0
    hits = len(PERSON_HINT.findall(text)) + len(EVENT_HINT.findall(text))
    return hits / (len(text) / 1000)


def pick_chunks(docs: list[Document], max_per_doc: int) -> list[Document]:
    """문서당 밀도 상위 조각만 남긴다. 원래 순서는 유지한다."""
    if max_per_doc <= 0:
        return docs
    by_node: dict[str, list[Document]] = {}
    for d in docs:
        by_node.setdefault(d.node_id, []).append(d)

    kept: list[Document] = []
    for parts in by_node.values():
        if len(parts) <= max_per_doc:
            kept.extend(parts)
            continue
        top = sorted(parts, key=lambda d: chunk_density(d.text), reverse=True)[:max_per_doc]
        kept.extend(sorted(top, key=lambda d: d.chunk))
    return kept


def load_documents(
    store: GraphStore,
    limit: int | None = None,
    min_score: float = 1.0,
    scope_ids: set[str] | None = None,
    skip_covered: bool = False,
    max_chunks: int = 0,
    node_types: tuple[str, ...] | None = None,
    skip_extracted: bool = True,
) -> list[Document]:
    """추출 가치가 높은 순으로 문서를 고른다.

    min_score=1.0 은 인물이나 사건 표지 중 하나 이상을 요구한다.
    2.0 으로 올리면 둘 다 있는 글만 남는다.

    scope_ids 를 주면 그 노드들의 산문만 대상으로 한다."""
    # **넘겨받은 글은 추출에 쓰지 않는다.** `enrich` 가 위키백과 넘겨주기를
    # 따라가면 다른 개체의 문서가 붙는다 — '무관랑'의 설명은 '사다함'
    # 문서이고, '이유'의 설명은 '엠파이어 (음악 그룹)' 문서다. 화면에서는
    # 어디서 온 글인지 밝히고 보여주면 되지만, 추출은 다르다. 그 글을
    # 이 노드의 것으로 읽으면 사다함의 관계가 무관랑에게 붙는다.
    # 근거 구절 검증도 이걸 못 막는다 — 구절은 원문에 실제로 있다.
    skip_via = "AND json_extract(props, '$.desc_via') IS NULL"
    if node_types:
        marks = ",".join("?" * len(node_types))
        rows = store.conn.execute(
            f"""SELECT id, label, description FROM nodes
                WHERE description IS NOT NULL AND length(description) > 100
                  AND type IN ({marks}) {skip_via}""",
            node_types,
        ).fetchall()
    else:
        rows = store.conn.execute(
            f"""SELECT id, label, description FROM nodes
               WHERE description IS NOT NULL AND length(description) > 100
                 {skip_via}"""
        ).fetchall()

    if scope_ids is not None:
        before = len(rows)
        rows = [r for r in rows if r["id"] in scope_ids]
        log.info("범위 한정: 산문 %d건 → %d건", before, len(rows))

    # 이미 추출한 문서는 건너뛴다. **`--limit` 으로 나눠 돌리려면 필수다** —
    # 없으면 두 번째 배치가 첫 배치와 같은 문서를 다시 처리한다 (조각당
    # 200초라 하루를 통째로 버린다). 다시 뽑고 싶으면 `--redo`.
    if skip_extracted:
        done = {
            r["id"]
            for r in store.conn.execute(
                """SELECT DISTINCT json_extract(props, '$.extracted_from') AS id
                     FROM edges WHERE source = 'extract'"""
            )
            if r["id"]
        }
        if done:
            before = len(rows)
            rows = [r for r in rows if r["id"] not in done]
            log.info("이미 추출한 문서 %d건 제외 (남은 대상 %d건)",
                     before - len(rows), len(rows))

    # 족보 목록은 점수·밀도 산정 전에 지운다. 남겨두면 이름 밀도가
    # 부풀어 족보 조각이 서사 조각을 밀어내고 상위로 뽑힌다.
    rows = [
        {**dict(r), "description": strip_kinship_lists(r["description"])}
        for r in rows
    ]
    rows = [r for r in rows if len(r["description"]) > 100]

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

    if skip_covered:
        before = len(kept)
        types = {
            row["id"]: row["type"]
            for row in store.conn.execute("SELECT id, type FROM nodes")
        }
        kept = [
            (sc, r) for sc, r in kept
            if worth_extracting(store, r["id"], types.get(r["id"], ""), r["description"])
        ]
        log.info("구조화 소스가 이미 덮은 문서 %d건 제외", before - len(kept))

    docs: list[Document] = []
    for _, r in kept:
        docs.extend(split_document(r["id"], r["label"], r["description"]))
    if max_chunks:
        before = len(docs)
        docs = pick_chunks(docs, max_chunks)
        log.info("문서당 밀도 상위 %d조각만 사용: %d → %d조각", max_chunks, before, len(docs))

    long_docs = sum(1 for _, r in kept if len(r["description"]) > CHUNK_CHARS)
    if long_docs:
        log.info(
            "긴 문서 %d건을 조각내어 총 %d개 요청", long_docs, len(docs)
        )
    return docs
