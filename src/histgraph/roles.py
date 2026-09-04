"""역할 판정 — 사람이 그 사건에서 **무엇을 했나**를 말뭉치의 근거로 적는다.

`participated_in` 은 방향과 이름뿐이다. "이재명 → 12.3 내란" 은 그가
계엄을 편 쪽인지 막은 쪽인지 체포 명단에 오른 쪽인지 말하지 않는데,
화면은 그것을 "참여했다"로 읽는다. 구조화 소스(Wikidata P1344·인포박스
주요인물N)는 편을 적지 않으므로 이 물음은 **산문에 물어야** 한다.

물음의 모양은 추출(`extract`)과 반대다. 추출은 "이 글에 어떤 관계가
있나"이고, 여기는 "이 관계는 어떤 것인가"다 — 관계는 이미 있고 근거를
찾아 붙인다. 그래서 글 전체가 아니라 **그 사람이 나오는 문단만**
(`corpus.mentions`) 모델에 준다. 짧고, 답이 근거와 같이 온다.

안전장치는 추출과 같다: **근거 구절이 준 문단에 실제로 있어야** 판정을
받는다 (`extract.evidence_supported`). 근거가 없거나 지어냈으면 버린다.
문단이 하나도 없으면 묻지도 않고 '근거 없음'으로 적는다 — 그 엣지는
화면에서 '참여'가 아니라 '관련'으로 물러난다.

역할은 일곱이다. 셋은 참여(주도·가담·대항)고 넷은 참여가 아니다
(피해·표적·수습·언급). 후자는 엣지 타입을 `related_to` 로 옮긴다 —
피해자가 사건에 '참여'한 것이 아니듯이. 옮긴 엣지는 `props.was` 에
원래 타입을 남긴다 (`reclassify` 와 같은 규약).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .extract import evidence_supported
from .store import GraphStore

log = logging.getLogger(__name__)

SOURCE_MARK = "roles"

# 역할 -> (뜻, 참여인가). 화면(`relations.js`)이 이 이름을 그대로 읽는다.
ROLES: dict[str, tuple[str, bool]] = {
    "주도": ("사건을 일으키거나 이끌었다 (계획·명령·지휘)", True),
    "가담": ("일으킨 쪽에서 행동했다 (명령을 받아 움직였다)", True),
    "대항": ("맞선 쪽에서 행동했다 (막았다·진압했다·저항했다·해제했다)", True),
    "피해": ("죽거나 다치거나 잡히거나 재산·지위를 잃었다", False),
    "표적": ("체포·공격·제거의 대상으로 지목됐지만 피해는 서술되지 않았다", False),
    "수습": ("사건 뒤에 수사·재판·진상규명·처벌을 맡았다", False),
    "언급": ("사건 글에 이름이 나올 뿐 무엇을 했는지 서술이 없다", False),
}
PARTICIPANT_ROLES = frozenset(r for r, (_, p) in ROLES.items() if p)

SYSTEM_PROMPT = """당신은 한국 근현대사 문헌을 읽고 한 사람이 한 사건에서 맡은 역할을 판정하는 전문가입니다.

주어진 문단은 사건 문서와 인물 문서에서 그 사람이 언급된 부분만 모은 것입니다.

핵심 규칙:
1. **문단에 서술된 것만으로 판정합니다.** 배경지식으로 아는 사실이라도 문단에 없으면 쓰지 마세요.
2. 역할은 아래 목록에서 하나만 고릅니다. 판단이 서지 않으면 '언급'입니다.
3. **근거 구절(evidence)은 문단에서 그대로 인용**합니다. 요약하거나 바꿔 쓰지 마세요. 한 문장이면 충분합니다.
4. 확신도를 정직하게 매기세요. 문단이 단정하면 certain, 추정이면 probable, 암시에 그치면 possible 입니다."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # 백엔드는 `relations` 배열을 기대한다 (backends._coerce_relations).
        # 판정 하나를 그 배열의 유일한 원소로 받는다.
        "relations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list(ROLES)},
                    "evidence": {"type": "string", "description": "근거 구절 (문단에서 그대로 인용)"},
                    "confidence": {"type": "string", "enum": ["certain", "probable", "possible"]},
                },
                "required": ["role", "evidence", "confidence"],
            },
        }
    },
    "required": ["relations"],
}

CONFIDENCE = {"certain": 0.9, "probable": 0.7, "possible": 0.5}


def build_prompt(person: str, event: str, passages: list[dict]) -> str:
    roles = "\n".join(f"- {r}: {desc}" for r, (desc, _) in ROLES.items())
    body = "\n\n".join(
        f"[{i + 1}] ({p.get('title', '')}{' · ' + p['section'] if p.get('section') else ''})\n{p['text']}"
        for i, p in enumerate(passages)
    )
    return f"""## 역할 목록
{roles}

## 물음
'{person}'은(는) '{event}'에서 어떤 역할이었습니까?

## 문단
{body}

위 문단만으로 역할 하나를 고르고 근거 구절을 그대로 인용하세요."""


# --- 후보 ------------------------------------------------------------------
PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def names_of(store: GraphStore, node_id: str) -> list[str]:
    """이름과 별칭. '김용현 (군인)' 의 괄호는 문서명의 것이라 뗀다."""
    row = store.conn.execute("SELECT label FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return []
    names = [row["label"], PAREN.sub("", row["label"])]
    names += [r["alias"] for r in store.conn.execute(
        "SELECT alias FROM aliases WHERE node_id = ?", (node_id,))]
    out: list[str] = []
    for n in names:
        n = n.strip()
        if len(n) >= 2 and n not in out:
            out.append(n)
    return out


def candidates(store: GraphStore, corpus, since: int | None = None, redo: bool = False) -> list[dict]:
    """판정할 엣지 — 사건으로 들어가는 인물의 participated_in.

    말뭉치에 그 사건 문서가 있는 것만. 없는 사건은 물을 글이 없다."""
    from .corpus import has_doc
    from .timeline import _year_of

    rows = store.conn.execute(
        """SELECT e.src, e.dst, e.source, e.label, e.props,
                  p.label AS person, ev.label AS event, ev.start_date
             FROM edges e
             JOIN nodes p ON p.id = e.src AND p.type = 'person'
             JOIN nodes ev ON ev.id = e.dst AND ev.type = 'event'
            WHERE e.type = 'participated_in'"""
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        if since is not None:
            year = _year_of(r["start_date"])
            if year is None or year < since:
                continue
        props = json.loads(r["props"] or "{}")
        if not redo and props.get("role"):
            continue
        if not has_doc(corpus, r["dst"]):
            continue
        out.append(dict(r, props=props))
    return out


def gather(store: GraphStore, corpus, person_id: str, event_id: str, limit: int = 6) -> list[dict]:
    """그 사람이 사건 글에 나오는 문단 + 그 사건이 사람 글에 나오는 문단."""
    from .corpus import mentions

    got = mentions(corpus, event_id, names_of(store, person_id), limit=limit)
    if len(got) < limit:
        got += mentions(corpus, person_id, names_of(store, event_id), limit=limit - len(got))
    return got


# --- 판정 ------------------------------------------------------------------
def judge(backend, person: str, event: str, passages: list[dict]) -> dict | None:
    """모델에 묻고, 근거가 준 문단에 실제로 있을 때만 판정을 돌려준다."""
    if not passages:
        return None
    try:
        answers = backend.complete(SYSTEM_PROMPT, build_prompt(person, event, passages), OUTPUT_SCHEMA)
    except RuntimeError as err:
        log.warning("판정 실패 [%s / %s]: %s", person, event, err)
        return None
    return accept(answers, passages)


def accept(answers: list[dict], passages: list[dict]) -> dict | None:
    """모델 답 -> 판정. 순수 함수 — 백엔드 없이 시험한다.

    역할이 목록 밖이거나 근거가 문단에 없으면 None. 스키마가 강제되는
    백엔드에서도 근거는 검사한다 — 형태가 맞는 것과 인용이 진짜인 것은
    다른 문제다."""
    if not answers:
        return None
    a = answers[0]
    role = str(a.get("role", "")).strip()
    evidence = str(a.get("evidence", "")).strip()
    if role not in ROLES or not evidence:
        return None
    text = "\n\n".join(p["text"] for p in passages)
    if not evidence_supported(evidence, text):
        return None
    return {
        "role": role,
        "evidence": evidence,
        "confidence": CONFIDENCE.get(str(a.get("confidence")), 0.5),
    }


def apply(store: GraphStore, edge: dict, verdict: dict | None, model: str) -> str:
    """판정을 엣지에 적는다. 돌려주는 값은 무엇을 했나 (기록용).

    참여 역할이면 라벨·역할·근거만 적고, 아니면 related_to 로 옮긴다.
    근거 없음(verdict None)도 옮긴다 — 근거 없는 '참여'를 화면에 두지 않는다."""
    c = store.conn
    props = dict(edge["props"])
    props.pop("was", None)
    if verdict is None:
        props["role"] = "근거 없음"
        props["role_model"] = model
        props.pop("role_evidence", None)
        return _move(c, edge, "related_to", label="근거 없음", props=props, confidence=0.5)
    props["role"] = verdict["role"]
    props["role_evidence"] = verdict["evidence"]
    props["role_model"] = model
    if verdict["role"] in PARTICIPANT_ROLES:
        c.execute(
            """UPDATE edges SET label = ?, confidence = ?, props = ?
                WHERE src = ? AND dst = ? AND type = 'participated_in' AND source = ?""",
            (verdict["role"], verdict["confidence"], json.dumps(props, ensure_ascii=False),
             edge["src"], edge["dst"], edge["source"]),
        )
        return "참여"
    return _move(c, edge, "related_to", label=verdict["role"], props=props,
                 confidence=verdict["confidence"])


def _move(c, edge: dict, new_type: str, label: str, props: dict, confidence: float) -> str:
    props["was"] = "participated_in"
    c.execute(
        "DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'participated_in' AND source = ?",
        (edge["src"], edge["dst"], edge["source"]),
    )
    c.execute(
        """INSERT INTO edges (src, dst, type, source, label, confidence, props)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(src, dst, type, source) DO UPDATE SET
             label = excluded.label, confidence = excluded.confidence, props = excluded.props""",
        (edge["src"], edge["dst"], new_type, edge["source"], label, confidence,
         json.dumps(props, ensure_ascii=False)),
    )
    return "관련으로"


def run(
    store: GraphStore,
    corpus,
    backend,
    since: int | None = 1945,
    limit: int | None = None,
    dry_run: bool = False,
    redo: bool = False,
) -> dict[str, Any]:
    """후보를 돌며 판정한다. `backend` 가 None 이거나 dry_run 이면 묻지 않고
    근거 문단이 있는지만 센다 — 말뭉치가 얼마나 답할 수 있는지 먼저 본다."""
    todo = candidates(store, corpus, since=since, redo=redo)
    if limit:
        todo = todo[:limit]
    counts: dict[str, int] = {"후보": len(todo), "문단 있음": 0, "문단 없음": 0}
    by_role: dict[str, int] = {}
    samples: list[str] = []
    for e in todo:
        passages = gather(store, corpus, e["src"], e["dst"])
        counts["문단 있음" if passages else "문단 없음"] += 1
        if dry_run or backend is None:
            if passages and len(samples) < 8:
                samples.append(f"{e['person']} / {e['event']}: {passages[0]['text'][:80]}…")
            continue
        verdict = judge(backend, e["person"], e["event"], passages) if passages else None
        role = verdict["role"] if verdict else "근거 없음"
        by_role[role] = by_role.get(role, 0) + 1
        apply(store, e, verdict, getattr(backend, "model", "?"))
        # 판정마다 커밋한다 — 끝에서 한 번 하면 첫 판정부터 몇 시간 쓰기
        # 잠금을 쥐어 다른 세션(promote·extract)이 '데이터베이스 잠김'으로
        # 죽는다 (journal_mode 가 delete 라 쓰는 쪽은 하나다).
        store.conn.commit()
        if len(samples) < 12:
            samples.append(f"{e['person']} / {e['event']} → {role}"
                           + (f"  「{verdict['evidence'][:60]}」" if verdict else ""))
    if not dry_run and backend is not None:
        store.conn.commit()
    return {"counts": counts, "by_role": by_role, "samples": samples}
