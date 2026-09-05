"""정본이 아닌 설명을 **우리 말로 다시 쓴다** (`paraphrase`).

2026-09-05 사용자: "정본 말고(요약 할 수 없는 글) 나무위키나, 위키피디아에서
만든 글은 요약해서 보여주면 되잖아." 설명 칸에는 두 부류의 글이 섞여 있다.

- **정본** — 국사편찬위원회·민족문화대백과·국가유산청 글. 이 사이트가 그
  권위를 빌려 오는 자료라 손대지 않고 도입부를 그대로 낸다(`pages.summarize`).
- **위키** — 한국어 위키백과·나무위키, 그리고 표식이 없어 출처를 모르는 글.
  남의 글을 그대로 옮기면 애드센스에는 스크랩이고 라이선스로는 베낌이다.
  이쪽은 모델에게 읽히고 **새로 쓴 두세 문장**으로 바꾼다.

새로 쓴 글은 `summaries` 표에 둔다 — `nodes.description` 은 덮지 않는다.
전문은 추출·말뭉치가 읽고, 수집(`ingest`·`enrich`)이 설명을 통째로 다시 쓰는데
그때 우리가 쓴 글이 같이 지워지면 안 된다. 표는 원문의 해시(`src_hash`)를
같이 들고 있어서, 설명이 바뀌면 옛 요약은 저절로 무효가 되고 화면은 도입부로
물러난다. 다시 돌리면 새 글이 채워진다.

**받아들이는 기준은 기계가 잰다** (`accept`): 한국어일 것, 영어가 없을 것,
60~420자, 원문과 30자 넘게 겹치는 구절이 없을 것(그대로 베낀 것은 요약이
아니다), '위키'·'이 글'·'문서' 같은 말을 하지 않을 것. 떨어지면 저장하지
않는다 — 화면은 그때 도입부를 낸다. 없는 사실을 지어냈는지는 기계가 못 잰다.
그래서 프롬프트가 원문에 없는 것을 보태지 말라 하고, 표본을 사람이 읽는다.

모델은 `causes`·`roles` 와 같은 MLX 다 (35GB, 함께 띄우지 말 것). 한 건에
원문 1,200자 안팎을 넣고 200자 안팎을 받는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from .pages import summarize
from .provenance import desc_origin
from .store import GraphStore

log = logging.getLogger(__name__)

# 정본 — 새로 쓰지 않는다. `provenance.desc_origin` 의 이름으로 가른다.
CANON = {"국사편찬위원회 우리역사넷", "한국민족문화대백과사전", "국가유산청 국가유산포털", "위키데이터"}

# 모델에게 읽히는 원문 길이. 도입부 한두 문단이면 두세 문장을 새로 쓰기에
# 넉넉하다. 더 주면 절 본문(생애·평가)까지 섞여 요약이 산만해진다.
SOURCE_CHARS = 1200
MIN_LEN, MAX_LEN = 60, 420
# 원문과 이만큼 이어서 같으면 베낀 것이다. 이름·연도·관직명은 이보다 짧다.
OVERLAP_MAX = 30

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

SYSTEM = (
    "당신은 한국사 사전의 편집자입니다. 주어진 글을 읽고, 그 항목이 무엇인지를 "
    "**당신의 말로 새로** 두세 문장으로 씁니다.\n"
    "규칙:\n"
    "1. 글에 없는 사실을 보태지 않습니다. 모르는 것은 쓰지 않습니다.\n"
    "2. 이름·연도·지명·관직은 글에 있는 그대로 씁니다.\n"
    "3. 글의 문장을 그대로 옮기지 않습니다. 어순과 표현을 바꿔 새로 씁니다.\n"
    "4. 한국어로만 씁니다. 한자·영어를 괄호로 덧붙이지 않습니다.\n"
    "5. '이 글은', '위키백과', '문서', '요약' 같은 말을 쓰지 않습니다. "
    "항목 자체에 대해서만 말합니다.\n"
    "6. 문장은 '~다.'로 끝냅니다. 전체 60~400자."
)

_BAD_WORDS = ("위키", "이 글", "문서", "요약", "본문", "출처")
_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]{2,}")


def src_hash(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:16]


def is_canon(source: str | None, props: dict, url: str | None) -> bool:
    origin = desc_origin(source, props, url)
    return bool(origin) and origin["name"] in CANON


def build_prompt(label: str, kind: str, text: str) -> str:
    return (
        f"항목: {label} ({kind})\n\n"
        f"글:\n{summarize(text, limit=SOURCE_CHARS)}\n\n"
        f"'{label}'이(가) 무엇인지 당신의 말로 새로 쓰세요."
    )


def _longest_overlap(a: str, b: str) -> int:
    """두 글의 가장 긴 공통 구절 길이. 공백을 지우고 잰다 — 띄어쓰기만 바꾼
    것은 베낀 것이다."""
    a = re.sub(r"\s+", "", a)
    b = re.sub(r"\s+", "", b)
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def tidy(text: str) -> str:
    """모델 글의 잔손질. '2005 년' 처럼 숫자 뒤가 벌어진 것을 붙인다."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return re.sub(r"(\d)\s+(년|월|일|세|명|대|차|번|개)", r"\1\2", text)


def accept(text: str, source: str) -> str | None:
    """새로 쓴 글이 기준을 넘는가. 넘으면 None, 아니면 떨어진 이유.

    4B 시험 모델 실측: 6건 중 2건만 남았다 — 너무 길거나 짧거나 원문 그대로.
    경어체('~했습니다')도 온다. 사이트의 다른 설명이 전부 '~다' 라 그것도
    떨어뜨린다."""
    text = tidy(text)
    if not text:
        return "빈 응답"
    if not _HANGUL.search(text):
        return "한국어가 아님"
    if _LATIN.search(text):
        return "영어가 섞임"
    if len(text) < MIN_LEN:
        return f"너무 짧음 ({len(text)}자)"
    if len(text) > MAX_LEN:
        return f"너무 김 ({len(text)}자)"
    for w in _BAD_WORDS:
        if w in text:
            return f"'{w}' 언급"
    if not text.endswith(("다.", "다", ".")):
        return "문장이 안 끝남"
    if re.search(r"(습니다|입니다|합니다|ㅂ니다|에요|어요|아요)[.]?(\s|$)", text):
        return "경어체"
    if _longest_overlap(text, source) > OVERLAP_MAX:
        return "원문을 그대로 베낌"
    return None


def candidates(store: GraphStore, redo: bool = False) -> list[dict]:
    """새로 쓸 노드. 설명이 있고 정본이 아닌 것. 이미 쓴 것(해시가 같은 것)은
    `redo` 가 아니면 건너뛴다."""
    have = {
        r["node_id"]: r["src_hash"]
        for r in store.conn.execute("SELECT node_id, src_hash FROM summaries")
    }
    out = []
    for r in store.conn.execute(
        "SELECT id, type, label, source, description, url, props FROM nodes"
        " WHERE COALESCE(description, '') <> '' ORDER BY id"
    ):
        props = json.loads(r["props"] or "{}")
        if is_canon(r["source"], props, r["url"]):
            continue
        h = src_hash(r["description"])
        if not redo and have.get(r["id"]) == h:
            continue
        out.append({"id": r["id"], "type": r["type"], "label": r["label"],
                    "description": r["description"], "hash": h})
    return out


def run(store: GraphStore, backend, limit: int | None = None,
        dry_run: bool = False, redo: bool = False) -> dict[str, Any]:
    from .ontology import NODE_TYPES

    todo = candidates(store, redo=redo)
    if limit:
        todo = todo[:limit]
    counts = {"후보": len(todo), "새로 씀": 0, "떨어짐": 0}
    reasons: dict[str, int] = {}
    samples: list[str] = []
    if dry_run:
        return {"counts": counts, "reasons": reasons, "samples": samples}

    for i, doc in enumerate(todo, 1):
        kind = NODE_TYPES.get(doc["type"], doc["type"])
        prompt = build_prompt(doc["label"], kind, doc["description"])
        text, why = "", "빈 응답"
        # 떨어지면 이유를 붙여 한 번만 다시 묻는다. 두 번째도 떨어지면 이
        # 노드는 도입부로 남는다 — 다음 실행에서 다시 후보가 된다.
        for attempt in range(2):
            ask = prompt if not attempt else f"{prompt}\n\n(앞선 답은 '{why}'로 쓸 수 없었습니다. 규칙을 지켜 다시 쓰세요.)"
            got = backend.complete_json(SYSTEM, ask, SCHEMA)
            text = (got or {}).get("summary", "") if isinstance(got, dict) else ""
            why = accept(text, doc["description"])
            if not why:
                break
        if why:
            counts["떨어짐"] += 1
            reasons[why] = reasons.get(why, 0) + 1
            log.info("떨어짐 %s (%s): %s", doc["label"], why, text[:80])
            continue
        text = tidy(text)
        store.conn.execute(
            "INSERT OR REPLACE INTO summaries (node_id, text, model, src_hash, made_at)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            (doc["id"], text, backend.model, doc["hash"]),
        )
        store.conn.commit()
        counts["새로 씀"] += 1
        if len(samples) < 8:
            samples.append(f"{doc['label']}: {text[:90]}")
        if i % 50 == 0:
            log.info("%d/%d · 새로 씀 %d · 떨어짐 %d", i, len(todo), counts["새로 씀"], counts["떨어짐"])
    return {"counts": counts, "reasons": reasons, "samples": samples}


def lookup(conn, node_id: str, description: str | None) -> str | None:
    """화면이 낼 글. 원문이 그대로일 때만 우리가 쓴 글을 준다 — 설명이 바뀌었으면
    옛 요약은 옛 글의 요약이다. 표가 없는 DB(옛 파생본)에서는 그냥 None."""
    if not description:
        return None
    try:
        row = conn.execute(
            "SELECT text, src_hash FROM summaries WHERE node_id = ?", (node_id,)
        ).fetchone()
    except Exception:  # sqlite3.OperationalError — 표가 아직 없다
        return None
    if row and row["src_hash"] == src_hash(description):
        return row["text"]
    return None


def sync(store: GraphStore, target: GraphStore) -> int:
    """새로 쓴 글을 파생본(화면 DB)으로 옮긴다 — 거기 있는 노드 것만."""
    have = {r["id"] for r in target.conn.execute("SELECT id FROM nodes")}
    rows = [
        (r["node_id"], r["text"], r["model"], r["src_hash"], r["made_at"])
        for r in store.conn.execute("SELECT * FROM summaries") if r["node_id"] in have
    ]
    target.conn.executemany(
        "INSERT OR REPLACE INTO summaries (node_id, text, model, src_hash, made_at)"
        " VALUES (?,?,?,?,?)", rows,
    )
    target.conn.commit()
    return len(rows)
