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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extract import evidence_supported
from .store import GraphStore

log = logging.getLogger(__name__)

SOURCE_MARK = "roles"
TABLE_ORIGIN = "roles"      # 편집 계층(`overrides.origin`)에 적는 이름

# **편이 곧 역할이 아닌 사건.** 인포박스의 `지휘관1`·`지휘관2` 는 전투에서는
# 양쪽 사령관이지만, 정변·난·사화에서는 한쪽이 일으킨 쪽이고 다른 쪽이
# 당한 쪽이다 (2026-09-05 지적: "정도전은 제1차 왕자의 난을 지휘했다" —
# 그는 그 난에 죽은 사람이다). 어느 편이 무엇을 했는지는 인포박스가 말해
# 주지 않으므로, 이 이름을 가진 사건으로 들어가는 인물 참여는 **역할이
# 적혀 있어야** 한다. 없으면 `roles --table` 이 종료 코드 1 로 묻는다.
# 운동·항쟁·혁명·시위는 빼둔다 — '3·1 운동에 참여했다'는 그대로 참이다.
CONTESTED = re.compile(
    r"의 난$|난$|정변|반란|사화$|옥사|의 옥$|쿠데타|학살|암살|봉기|사변|반정|숙청"
    r"|참변|내란|고변|모반|역모|왜변|사건$|독살|피살|처형"
)

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
4. 확신도를 정직하게 매기세요. 문단이 단정하면 certain, 추정이면 probable, 암시에 그치면 possible 입니다.
5. **'주도'·'가담'은 그 사건을 일으킨 쪽의 역할입니다.** 사건의 중심 인물이라고 주도가 아닙니다.
   - 항쟁·시위·봉기가 반대한 정권·인물(예: 6월 민주 항쟁의 전두환, 6·3 항쟁의 박정희)은 '주도'가 아니라 '표적'입니다.
   - 계엄·반란·쿠데타를 막거나 해제한 사람(예: 계엄 해제 표결을 이끈 국회의장)은 '주도'가 아니라 '대항'입니다.
   - 사건의 정의 문장("X는 Y가 일으킨 사건이다")은 Y 를 주도로 볼 근거이지, 그 문장에 나오는 다른 이름의 근거가 아닙니다."""

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


def candidates(
    store: GraphStore,
    corpus,
    since: int | None = None,
    redo: bool = False,
    only_roles: frozenset[str] | set[str] | None = None,
    sources: frozenset[str] | set[str] | None = None,
) -> list[dict]:
    """판정할 엣지 — 사건으로 들어가는 인물의 participated_in.

    말뭉치에 그 사건 문서가 있는 것만. 없는 사건은 물을 글이 없다.
    `only_roles` 는 다시 물을 때 그 역할로 판정됐던 엣지만 고른다 —
    프롬프트를 고친 뒤 틀린 갈래('주도')만 다시 묻는 데 쓴다.
    `sources` 는 그 소스가 만든 엣지만 고른다 — 판정 안 된 참여가 3,665건
    이라 한 번에 다 물으면 며칠이 걸린다. 새로 들어온 것부터 묻는 칸이다."""
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
        if sources is not None and r["source"] not in sources:
            continue
        props = json.loads(r["props"] or "{}")
        if not redo and props.get("role"):
            continue
        # 사람이 표(`data/roles.tsv`)에 적은 판정은 `--redo` 로도 다시 묻지 않는다.
        # 표는 언제나 기계를 이긴다 (CLAUDE.md §1-4 와 같은 규칙).
        if props.get("role_origin") == TABLE_ORIGIN:
            continue
        if only_roles is not None and props.get("role") not in only_roles:
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
    근거 없음(verdict None)도 옮긴다 — 근거 없는 '참여'를 화면에 두지 않는다.

    판정은 편집 계층에도 적는다 — 2026-09-06 실측: 인포박스 재수집이 12·12
    군사 반란의 판정 16건을 '지휘관'으로 되돌려 놓았다 (`upsert_edges` 는
    라벨·props 를 통째로 덮어쓴다). 표(`data/roles.tsv`)와 같은 칸에 적되
    origin 을 달리해 표가 이기게 둔다."""
    c = store.conn
    props = dict(edge["props"])
    props.pop("was", None)
    if verdict is None:
        props["role"] = "근거 없음"
        props["role_model"] = model
        props.pop("role_evidence", None)
        _remember(c, edge, "근거 없음", "", participant=False)
        return _move(c, edge, "related_to", label="근거 없음", props=props, confidence=0.5)
    props["role"] = verdict["role"]
    props["role_evidence"] = verdict["evidence"]
    props["role_model"] = model
    participant = verdict["role"] in PARTICIPANT_ROLES
    _remember(c, edge, verdict["role"], verdict["evidence"], participant=participant)
    if participant:
        c.execute(
            """UPDATE edges SET label = ?, confidence = ?, props = ?
                WHERE src = ? AND dst = ? AND type = 'participated_in' AND source = ?""",
            (verdict["role"], verdict["confidence"], json.dumps(props, ensure_ascii=False),
             edge["src"], edge["dst"], edge["source"]),
        )
        return "참여"
    return _move(c, edge, "related_to", label=verdict["role"], props=props,
                 confidence=verdict["confidence"])


MODEL_ORIGIN = "roles-model"


def _remember(c, edge: dict, role: str, evidence: str, *, participant: bool) -> None:
    """모델 판정을 편집 계층에 적는다. 표의 판정이 이미 있으면 건드리지 않는다."""
    from . import overrides as ov

    k_part = ov.edge_key(edge["src"], edge["dst"], "participated_in")
    k_rel = ov.edge_key(edge["src"], edge["dst"], "related_to")
    if c.execute(
        "SELECT 1 FROM overrides WHERE target = 'edge' AND key IN (?, ?) AND origin = ? LIMIT 1",
        (k_part, k_rel, TABLE_ORIGIN),
    ).fetchone():
        return
    for k in (k_part, k_rel):
        ov.forget(c, "edge", k, "deleted")
        ov.record(c, "edge", k, "label", role, MODEL_ORIGIN, evidence)
        ov.record(c, "edge", k, "props.role", role, MODEL_ORIGIN, evidence)
        if evidence:
            ov.record(c, "edge", k, "props.role_evidence", evidence, MODEL_ORIGIN, evidence)
    if not participant:
        ov.record(c, "edge", k_part, "deleted", True, MODEL_ORIGIN, evidence)


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
    only_roles: frozenset[str] | set[str] | None = None,
    sources: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """후보를 돌며 판정한다. `backend` 가 None 이거나 dry_run 이면 묻지 않고
    근거 문단이 있는지만 센다 — 말뭉치가 얼마나 답할 수 있는지 먼저 본다."""
    todo = candidates(store, corpus, since=since, redo=redo or bool(only_roles),
                      only_roles=only_roles, sources=sources)
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


# --- 표 --------------------------------------------------------------------
#
# 모델이 못 읽는 것(말뭉치에 문단이 없는 옛 사건)과 모델이 틀린 것은 사람이
# 정본을 읽고 `data/roles.tsv` 에 적는다. 2026-09-06: 정변·난·사화·옥사
# 127건의 인물 참여 905쌍을 Claude 가 직접 읽어 적었다.
#
#     인물 id<TAB>사건 id<TAB>역할<TAB>근거
#
# 역할은 `ROLES` 일곱 중 하나, 또는 `삭제` — 엣지 자체가 거짓일 때
# (동명이인: 야구 감독 김응용이 1594년 송유진의 난에, 배우 박훈이 기묘사화에).
#
# 고친 값은 편집 계층에 남는다: 참여 역할이면 `label`·`props.role`,
# 참여가 아니면 거기에 `deleted` 를 더해 재수집이 되살린 participated_in 을
# 다시 지운다 — 옮겨 둔 related_to 는 수집이 덮어쓰지 않으므로 그대로 산다.

# 판정 하나 더: `단체`. 추출이 **단체·나라를 인물로** 세운 노드다 ('적군'·
# '영국 정부'·'사할린의용대'). 2026-09-07 전수 조사: 이런 노드의 참여를 지웠더니
# 영국이 거문도를 점령한 일, 자유시 참변의 부대들이 통째로 사라졌다. 관계는
# 참이고 틀린 것은 노드의 타입이다 — 타입을 고치고 참여를 그대로 세운다.
ORG_VERDICT = "단체"
TABLE_ROLES = frozenset(ROLES) | {"삭제", ORG_VERDICT}


class RolesTableError(ValueError):
    pass


@dataclass(frozen=True)
class TableRow:
    person: str
    event: str
    role: str
    note: str


@dataclass
class TableReport:
    applied: int = 0
    moved: int = 0        # 참여 ↔ 관련 사이를 옮긴 것
    deleted: int = 0
    absent: list[TableRow] = field(default_factory=list)   # 이 그래프에 없는 노드
    unjudged: list[tuple[str, str, str, str]] = field(default_factory=list)  # (인물, 사건, 인물 id, 사건 id)


def load_table(path: Path) -> list[TableRow]:
    rows: list[TableRow] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if len(parts) < 4 or not all(parts[:4]):
            raise RolesTableError(f"{path}:{lineno} 인물 id·사건 id·역할·근거 네 칸입니다: {raw!r}")
        person, event, role, note = parts[:4]
        if role not in TABLE_ROLES:
            raise RolesTableError(f"{path}:{lineno} 역할은 {'/'.join(sorted(TABLE_ROLES))} 중 하나: {role!r}")
        if (person, event) in seen:
            raise RolesTableError(f"{path}:{lineno} 같은 쌍이 두 번 적혔습니다: {raw!r}")
        seen.add((person, event))
        rows.append(TableRow(person, event, role, note))
    return rows


def _pair_edges(conn, person: str, event: str) -> list:
    return conn.execute(
        """SELECT rowid, src, dst, type, source, label, confidence, props FROM edges
            WHERE src = ? AND dst = ? AND type IN ('participated_in', 'related_to')""",
        (person, event),
    ).fetchall()


def apply_table(store: GraphStore, table: list[TableRow]) -> TableReport:
    """표를 편집 계층에 적고 그래프에 씌운다. 여러 번 돌려도 결과가 같다."""
    from . import overrides as ov

    c = store.conn
    rep = TableReport()
    has = lambda nid: c.execute("SELECT 1 FROM nodes WHERE id = ?", (nid,)).fetchone() is not None

    for row in table:
        if not (has(row.person) and has(row.event)):
            rep.absent.append(row)
            continue
        k_part = ov.edge_key(row.person, row.event, "participated_in")
        k_rel = ov.edge_key(row.person, row.event, "related_to")
        edges = _pair_edges(c, row.person, row.event)

        if row.role == ORG_VERDICT:
            # 노드를 단체로 고치고(편집 계층) 참여를 그대로 세운다.
            ov.record(c, "node", row.person, "type", "org", TABLE_ORIGIN, row.note)
            c.execute("UPDATE nodes SET type = 'org' WHERE id = ?", (row.person,))
            for k in (k_part, k_rel):
                ov.forget(c, "edge", k, "deleted")
            ov.record(c, "edge", k_rel, "deleted", True, TABLE_ORIGIN, row.note)
            if not edges:
                _assert_edge(c, row, "participated_in", label=None)
            else:
                for e in edges:
                    if e["type"] == "related_to":
                        c.execute("DELETE FROM edges WHERE rowid = ?", (e["rowid"],))
                        rep.moved += 1
            rep.applied += 1
            continue

        if row.role == "삭제":
            for k in (k_part, k_rel):
                ov.record(c, "edge", k, "deleted", True, TABLE_ORIGIN, row.note)
            n = c.execute(
                "DELETE FROM edges WHERE src = ? AND dst = ? AND type IN ('participated_in','related_to')",
                (row.person, row.event),
            ).rowcount
            rep.deleted += n
            rep.applied += 1
            continue

        participant = row.role in PARTICIPANT_ROLES
        target_type = "participated_in" if participant else "related_to"
        for k in (k_part, k_rel):
            ov.forget(c, "edge", k, "deleted")
        # 어느 타입으로 되살아나든 표의 역할이 씌워진다
        for k in (k_part, k_rel):
            ov.record(c, "edge", k, "label", row.role, TABLE_ORIGIN, row.note)
            ov.record(c, "edge", k, "props.role", row.role, TABLE_ORIGIN, row.note)
            ov.record(c, "edge", k, "props.role_evidence", row.note, TABLE_ORIGIN, row.note)
            ov.record(c, "edge", k, "props.role_origin", TABLE_ORIGIN, TABLE_ORIGIN, row.note)
        if not participant:
            # 재수집이 participated_in 을 다시 세우면 지운다. related_to 는 남는다.
            ov.record(c, "edge", k_part, "deleted", True, TABLE_ORIGIN, row.note)

        if not edges:
            # **표가 지웠던 관계를 되살릴 수 있어야 한다.** 2026-09-07 지적:
            # 정도전을 지운 줄 알았던 일에서 시작해 전수 조사를 했더니, 내가
            # '삭제'로 적어 정말 끊어 놓은 쌍이 114 였고 그중 43 은 관계가
            # 참인데 '참여'가 아니었을 뿐이었다 (난 문서가 배경으로 부른 왕들,
            # 부관참시된 김종직). 판정을 '언급'으로 낮추면 표가 그 관계를
            # 다시 세운다 — 근거는 표에 적은 그 줄이다.
            _assert_edge(c, row, target_type, label=row.role)
            rep.applied += 1
            continue

        for e in edges:
            props = json.loads(e["props"] or "{}")
            props["role"] = row.role
            props["role_evidence"] = row.note
            props["role_origin"] = TABLE_ORIGIN
            props.pop("role_model", None)
            if e["type"] == target_type:
                props.pop("was", None) if participant else props.setdefault("was", "participated_in")
                c.execute(
                    "UPDATE edges SET label = ?, props = ? WHERE rowid = ?",
                    (row.role, json.dumps(props, ensure_ascii=False), e["rowid"]),
                )
                continue
            # 타입을 옮긴다. 같은 소스의 목적지 엣지가 이미 있으면 그쪽을 갱신하고 이쪽은 지운다.
            if participant:
                props.pop("was", None)
            else:
                props["was"] = "participated_in"
            c.execute("DELETE FROM edges WHERE rowid = ?", (e["rowid"],))
            c.execute(
                """INSERT INTO edges (src, dst, type, source, label, confidence, props)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(src, dst, type, source) DO UPDATE SET
                     label = excluded.label, props = excluded.props""",
                (e["src"], e["dst"], target_type, e["source"], row.role, e["confidence"],
                 json.dumps(props, ensure_ascii=False)),
            )
            rep.moved += 1
        rep.applied += 1
    c.commit()
    return rep


def _assert_edge(c, row: "TableRow", etype: str, label: str | None) -> None:
    """표가 세우는 관계. 근거는 표의 근거 칸이다 — 사람이 정본을 읽고 적은 줄."""
    props = {"role_origin": TABLE_ORIGIN, "evidence": row.note}
    if label:
        props["role"] = label
        props["role_evidence"] = row.note
    c.execute(
        """INSERT INTO edges (src, dst, type, source, label, confidence, props)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(src, dst, type, source) DO UPDATE SET
             label = excluded.label, props = excluded.props""",
        (row.person, row.event, etype, SOURCE_MARK, label, 0.8,
         json.dumps(props, ensure_ascii=False)),
    )


def unjudged(store: GraphStore) -> list[tuple[str, str, str, str]]:
    """편이 곧 역할이 아닌 사건(`CONTESTED`)으로 들어가는 인물 참여 중 역할이
    없는 것. 화면이 '참여했다'·'지휘했다'로 읽어 버리는 자리다."""
    rows = store.conn.execute(
        """SELECT e.src, e.dst, e.props, p.label AS person, v.label AS event
             FROM edges e
             JOIN nodes p ON p.id = e.src AND p.type = 'person'
             JOIN nodes v ON v.id = e.dst AND v.type = 'event'
            WHERE e.type = 'participated_in'
            ORDER BY v.start_date, v.label, p.label"""
    ).fetchall()
    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if not CONTESTED.search(r["event"]):
            continue
        if json.loads(r["props"] or "{}").get("role"):
            continue
        if (r["src"], r["dst"]) in seen:
            continue
        seen.add((r["src"], r["dst"]))
        out.append((r["person"], r["event"], r["src"], r["dst"]))
    return out
