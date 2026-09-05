"""`related_to` 갈라 내기 — 뜻 없는 선을 뜻 있는 타입으로.

concept.md §7: "`related_to` 로 잇지 않는다. 뜻이 없는 엣지는 그물망이
아니라 실뭉치다." 팔란티어에서는 미선언 링크가 존재할 수 없다 — 모든
링크 타입이 무엇을 뜻하는지 적혀 있다. 우리는 스키마 불일치를 버리지 않고
`related_to` 로 낮추는 완화(`wikidata`·`promote`)와, 추출 모델이 "위에
해당하지 않는 명확한 관련"으로 고른 것이 쌓여 배포본에 1,409건이 서 있었다
(2026-09-05). 그 선은 어떤 질문에도 "관련 있다"밖에 답하지 못한다.

갈래는 넷이고, 순서대로 한다:

1. **규칙** (`RELAX`·`RETYPE`) — 무엇이었는지 엣지 자신이 말하는 것.
   Wikidata 가 `original_type` 을 남긴 완화(출생지 '조선' → 조선 사람
   `from_period`, 3·1 운동의 구성원 → `participated_in`), 인포박스의
   스승·제자 → `taught`.
2. **겹침** — 같은 두 노드 사이에 이미 뜻 있는 엣지가 있는 `related_to`.
   화면은 이미 그 카드를 접고 근거만 옮긴다(`relations.js`). 여기서는
   근거를 뜻 있는 쪽에 옮기고 선을 지운다.
3. **모델** — 추출이 근거 구절과 함께 `related_to` 로 낸 것 (배포본 1,075건,
   그중 인물끼리 761). 근거 구절만 보고 양끝 타입이 허용하는 타입 중
   하나를 고르게 한다. 목록 밖이면 `none` 이고, 그러면 그대로 둔다 —
   억지로 타입을 주면 뜻 없는 선이 거짓 선이 된다. 인과(`caused`)는 고르게
   하지 않는다: 그쪽은 '어떻게' 구절과 종류가 있어야 하는 별도 계약이다
   (`causes`).
4. **남는 것** — 라벨이 뜻을 말하는 것(역할 판정 '피해'·'수습', 전후
   '다음', 실록 기사의 대상)은 그대로 둔다. 세어서 보여 준다.

안전장치는 추출의 것을 그대로 잇는다: 근거 없는 엣지는 묻지 않는다, 양끝
타입이 허용하지 않는 타입은 스키마가 아니라 선택지에서부터 막는다,
카디널리티(`ontology.MAX_TARGETS`)를 넘게 되는 판정은 버리고 센다,
확신이 '가능'뿐이면 적지 않는다. 판정은 원래 줄의 `props.untangled` 에
남아 다시 돌려도 같은 것을 두 번 묻지 않는다.

**수집 뒤마다 다시 돌린다** (`dedupe` 와 같다). `extract` 는 `related_to`
를 다시 낸다 — 이미 타입이 있는 짝이면 2단계가 접고, 새 것만 3단계가 묻는다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ontology import EDGE_TYPES, MAX_TARGETS, Edge

log = logging.getLogger(__name__)

# (원래 타입, 실제 도착 타입) → 뜻이 남는 타입. `wikidata.relax_type` 도 이 표를 본다.
RELAX: dict[tuple[str, str], str] = {
    ("born_in", "org"): "from_period",       # 출생지 '조선' = 조선 사람
    ("died_in", "org"): "from_period",
    ("member_of", "event"): "participated_in",  # 3·1 운동의 구성원 = 참여자
}

# 라벨·소스가 뜻을 말하는 완화. (소스 접두, 라벨 또는 인포박스 칸) → (타입, 뒤집기)
RETYPE_INFOBOX: dict[str, tuple[str, bool]] = {
    # 예전 매핑은 스승 OUT(주인공 → 스승), 제자 IN(제자 → 주인공)이었다.
    # taught 는 스승 → 제자이므로 둘 다 뒤집는다.
    "스승": ("taught", True),
    "제자": ("taught", True),
}

# 모델에게 고르게 할 타입과 그 뜻. X 가 출발, Y 가 도착이다.
CHOICES: dict[str, str] = {
    "child_of": "X는 Y의 자녀다",
    "spouse_of": "X와 Y는 부부다",
    "taught": "X가 Y를 가르쳤다 (X 가 스승, Y 가 제자·문인)",
    "participated_in": "X(인물·단체)가 사건 Y에 참여했다",
    "member_of": "X는 단체 Y 소속이다",
    "held_position": "X가 직위 Y를 지냈다",
    "born_in": "X가 Y에서 태어났다",
    "died_in": "X가 Y에서 죽었다",
    "occurred_at": "사건 X가 Y에서 일어났다",
    "located_in": "X가 Y에 있다",
    "created": "X가 Y를 만들었다",
    "from_period": "X는 Y(시대·왕조)에 속한다",
    "occurred_during": "사건 X가 Y 시기에 일어났다",
    "depicts": "작품 X가 Y를 소재로 다룬다",
    "set_in": "작품 X의 배경이 Y다",
}

CONFIDENCE = {"certain": 0.9, "probable": 0.7, "possible": 0.5}

SYSTEM_PROMPT = """당신은 한국사 지식그래프의 관계를 판정하는 전문가입니다.

두 개체 A, B 와 근거 문장이 주어집니다. **근거 문장만으로** 두 개체 사이의
관계를 목록에서 하나 고르세요.

규칙:
1. 근거에 적힌 것만 봅니다. 배경지식으로 아는 관계라도 문장에 없으면 고르지 않습니다.
2. 목록의 어느 것에도 딱 맞지 않으면 none 을 고릅니다. 억지로 고르지 마세요.
3. 방향을 정확히 하세요. 'A가 B의 제자'면 가르친 쪽은 B 입니다.
4. 형제·사촌·정적·동료·같은 당파는 목록에 없으므로 none 입니다.
5. 확신도: 문장이 단정하면 certain, 추정이면 probable, 암시뿐이면 possible."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "direction": {"type": "string", "enum": ["A→B", "B→A"]},
        "confidence": {"type": "string", "enum": ["certain", "probable", "possible"]},
    },
    "required": ["type", "direction", "confidence"],
    "additionalProperties": False,
}

MEANINGFUL = frozenset(EDGE_TYPES) - {"related_to", "dated_to", "part_of"}


@dataclass
class Report:
    relaxed: list[tuple[str, str, str, str]] = field(default_factory=list)   # (src, dst, 옛, 새)
    folded: int = 0                 # 뜻 있는 엣지가 이미 있어 접은 것
    asked: int = 0
    typed: list[tuple[str, str, str]] = field(default_factory=list)          # (src, dst, 타입)
    none: int = 0
    weak: int = 0                   # possible 이라 적지 않은 것
    over_cardinality: list[tuple[str, str, str]] = field(default_factory=list)
    remaining: dict[str, int] = field(default_factory=dict)                  # 갈래 → 건수


# --- 1. 규칙 --------------------------------------------------------------

def _types_of(conn: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    ordered = sorted(ids)
    for i in range(0, len(ordered), 400):
        batch = ordered[i : i + 400]
        marks = ",".join("?" * len(batch))
        out.update(conn.execute(f"SELECT id, type FROM nodes WHERE id IN ({marks})", batch))
    return out


def _retype(store, row: sqlite3.Row, new_type: str, *, flip: bool = False,
            extra: dict | None = None, rep: Report | None = None) -> bool:
    """related_to 한 줄을 새 타입으로 다시 세운다. 카디널리티를 넘으면 거절."""
    conn = store.conn
    src, dst = (row["dst"], row["src"]) if flip else (row["src"], row["dst"])
    if src == dst:
        return False
    limit = MAX_TARGETS.get(new_type)
    if limit is not None:
        others = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT dst FROM edges WHERE src = ? AND type = ?", (src, new_type))
        }
        if dst not in others and len(others) >= limit:
            if rep is not None:
                rep.over_cardinality.append((src, dst, new_type))
            return False
    props = json.loads(row["props"] or "{}")
    props.pop("untangled", None)
    props["untangled_from"] = "related_to"
    if extra:
        props.update(extra)
    store.upsert_edges([Edge(
        src=src, dst=dst, type=new_type, source=row["source"],
        label=None, start_date=row["start_date"], end_date=row["end_date"],
        confidence=float(row["confidence"] or 1.0), props=props,
    )])
    conn.execute(
        "DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'related_to' AND source = ?",
        (row["src"], row["dst"], row["source"]),
    )
    return True


def apply_rules(store, rep: Report | None = None, *, dry_run: bool = False) -> Report:
    rep = rep or Report()
    conn = store.conn
    rows = conn.execute(
        "SELECT * FROM edges WHERE type = 'related_to'"
    ).fetchall()
    types = _types_of(conn, {r["src"] for r in rows} | {r["dst"] for r in rows})
    for r in rows:
        props = json.loads(r["props"] or "{}")
        orig = props.get("original_type")
        new: str | None = None
        flip = False
        if orig:
            new = RELAX.get((orig, types.get(r["dst"], "")))
            if new is None and types.get(r["src"]) in EDGE_TYPES[orig][1] \
                    and types.get(r["dst"]) in EDGE_TYPES[orig][2]:
                new = orig   # 노드 타입이 그새 고쳐져 이제는 맞는다 (`reclassify`)
        elif props.get("infobox_field") in RETYPE_INFOBOX:
            new, flip = RETYPE_INFOBOX[props["infobox_field"]]
        if new is None:
            continue
        s_t, d_t = (types.get(r["dst"]), types.get(r["src"])) if flip else (types.get(r["src"]), types.get(r["dst"]))
        if s_t not in EDGE_TYPES[new][1] or d_t not in EDGE_TYPES[new][2]:
            continue
        if dry_run or _retype(store, r, new, flip=flip, rep=rep):
            rep.relaxed.append((r["src"], r["dst"], orig or props.get("infobox_field", ""), new))
    if not dry_run:
        conn.commit()
    return rep


# --- 2. 겹침 --------------------------------------------------------------

def fold_redundant(store, rep: Report | None = None, *, dry_run: bool = False) -> Report:
    """같은 짝에 뜻 있는 엣지가 있으면 related_to 는 근거만 남기고 접는다."""
    rep = rep or Report()
    conn = store.conn
    marks = ",".join(f"'{t}'" for t in sorted(MEANINGFUL))
    rows = conn.execute(
        f"""SELECT r.src, r.dst, r.source, r.props,
                   m.src AS m_src, m.dst AS m_dst, m.type AS m_type, m.source AS m_source, m.props AS m_props
              FROM edges r
              JOIN edges m ON ((m.src = r.src AND m.dst = r.dst) OR (m.src = r.dst AND m.dst = r.src))
                          AND m.type IN ({marks})
             WHERE r.type = 'related_to' AND r.label IS NULL"""
    ).fetchall()
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        key = (r["src"], r["dst"], r["source"])
        if key in seen:
            continue
        seen.add(key)
        rep.folded += 1
        if dry_run:
            continue
        evidence = json.loads(r["props"] or "{}").get("evidence")
        if evidence:
            mp = json.loads(r["m_props"] or "{}")
            if not mp.get("evidence"):
                mp["evidence"] = evidence
            elif evidence != mp["evidence"]:
                more = mp.setdefault("more_evidence", [])
                if evidence not in more:
                    more.append(evidence)
            conn.execute(
                "UPDATE edges SET props = ? WHERE src = ? AND dst = ? AND type = ? AND source = ?",
                (json.dumps(mp, ensure_ascii=False), r["m_src"], r["m_dst"], r["m_type"], r["m_source"]),
            )
        conn.execute(
            "DELETE FROM edges WHERE src = ? AND dst = ? AND type = 'related_to' AND source = ?",
            key,
        )
    if not dry_run:
        conn.commit()
    return rep


# --- 3. 모델 --------------------------------------------------------------

def choices_for(a_type: str, b_type: str) -> list[tuple[str, str, str]]:
    """(타입, 방향, 설명). 양끝 타입이 허용하는 것만 — 선택지에서부터 막는다."""
    out: list[tuple[str, str, str]] = []
    for t, desc in CHOICES.items():
        _, srcs, dsts = EDGE_TYPES[t]
        if a_type in srcs and b_type in dsts:
            out.append((t, "A→B", desc.replace("X", "A").replace("Y", "B")))
        if t != "spouse_of" and b_type in srcs and a_type in dsts:
            out.append((t, "B→A", desc.replace("X", "B").replace("Y", "A")))
    return out


def build_prompt(a: str, a_type: str, b: str, b_type: str, evidence: str,
                 choices: list[tuple[str, str, str]]) -> str:
    from .ontology import NODE_TYPES

    lines = [f"A: {a} ({NODE_TYPES.get(a_type, a_type)})",
             f"B: {b} ({NODE_TYPES.get(b_type, b_type)})",
             "", "## 근거", evidence.strip(), "", "## 고를 수 있는 관계"]
    for t, d, desc in choices:
        lines.append(f"- {t} {d}: {desc}")
    lines.append("- none: 위 어느 것도 아니다")
    lines.append("")
    lines.append("근거 문장만으로 하나를 고르고 방향과 확신도를 적으세요.")
    return "\n".join(lines)


def candidates(conn: sqlite3.Connection, *, redo: bool = False, limit: int | None = None) -> list[sqlite3.Row]:
    rows = conn.execute(
        """SELECT e.*, a.label AS a_label, a.type AS a_type, b.label AS b_label, b.type AS b_type
             FROM edges e JOIN nodes a ON a.id = e.src JOIN nodes b ON b.id = e.dst
            WHERE e.type = 'related_to' AND e.label IS NULL
              AND json_extract(e.props, '$.evidence') IS NOT NULL
            ORDER BY e.src, e.dst"""
    ).fetchall()
    out = []
    for r in rows:
        props = json.loads(r["props"] or "{}")
        if not redo and props.get("untangled"):
            continue
        if not choices_for(r["a_type"], r["b_type"]):
            continue
        out.append(r)
        if limit and len(out) >= limit:
            break
    return out


def judge(backend, row: sqlite3.Row) -> dict | None:
    choices = choices_for(row["a_type"], row["b_type"])
    evidence = json.loads(row["props"] or "{}").get("evidence") or ""
    schema = dict(OUTPUT_SCHEMA)
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["type"] = {"type": "string", "enum": sorted({t for t, _, _ in choices}) + ["none"]}
    prompt = build_prompt(row["a_label"], row["a_type"], row["b_label"], row["b_type"], evidence, choices)
    try:
        verdict = backend.complete_json(SYSTEM_PROMPT, prompt, schema)
    except Exception as err:  # 모델 하나가 죽어도 목록 전체를 버리지 않는다
        log.warning("판정 실패 %s → %s: %s", row["src"], row["dst"], str(err)[:120])
        return None
    return verdict if isinstance(verdict, dict) else None


def apply_verdict(store, row: sqlite3.Row, verdict: dict | None, model: str, rep: Report) -> None:
    """판정 하나를 적용한다. 무엇을 골랐든 원래 줄에 판정을 남긴다."""
    conn = store.conn
    t = (verdict or {}).get("type") or "none"
    direction = (verdict or {}).get("direction") or "A→B"
    conf = (verdict or {}).get("confidence") or "possible"
    allowed = {(c, d) for c, d, _ in choices_for(row["a_type"], row["b_type"])}
    over = False
    if t != "none" and (t, direction) in allowed and conf != "possible":
        flip = direction == "B→A"
        before = len(rep.over_cardinality)
        if _retype(store, row, t, flip=flip, rep=rep, extra={
            "untangle_model": model,
            "untangle_confidence": conf,
        }):
            conn.execute(
                "UPDATE edges SET confidence = MIN(confidence, ?) WHERE src = ? AND dst = ? AND type = ? AND source = ?",
                (CONFIDENCE[conf], row["dst"] if flip else row["src"], row["src"] if flip else row["dst"], t, row["source"]),
            )
            rep.typed.append((row["src"], row["dst"], t))
            return
        over = len(rep.over_cardinality) > before
    if over:
        pass                        # 이미 rep.over_cardinality 에 세었다
    elif t != "none" and conf == "possible":
        rep.weak += 1
    else:
        rep.none += 1
    props = json.loads(row["props"] or "{}")
    # 판정을 원래 줄에 남긴다. '/over' 는 맞는 판정이었지만 카디널리티를
    # 넘어 적지 않았다는 표식 — 그 사람의 출생지가 이미 다른 곳으로 서 있다.
    props["untangled"] = ("none" if t == "none" else f"{t}/{conf}") + ("/over" if over else "")
    props["untangle_model"] = model
    conn.execute(
        "UPDATE edges SET props = ? WHERE src = ? AND dst = ? AND type = 'related_to' AND source = ?",
        (json.dumps(props, ensure_ascii=False), row["src"], row["dst"], row["source"]),
    )


def run_model(store, backend, rep: Report, *, limit: int | None = None,
              redo: bool = False, dry_run: bool = False, log_every: int = 25) -> Report:
    rows = candidates(store.conn, redo=redo, limit=limit)
    rep.asked = len(rows)
    if dry_run or backend is None:
        return rep
    model = getattr(backend, "model", "?")
    for i, r in enumerate(rows, 1):
        apply_verdict(store, r, judge(backend, r), model, rep)
        if i % log_every == 0:
            store.conn.commit()
            log.info("판정 %d/%d · 타입 %d · none %d", i, len(rows), len(rep.typed), rep.none)
    store.conn.commit()
    return rep


# --- 3-2. 표 — 사람(또는 Claude)이 직접 판정한 것 ----------------------------
# 로컬 모델을 쓰지 않고 판정할 때의 길이다 (2026-09-05 사용자 요청 "우리 로컬
# llm 을 사용하지 말고 너가 직접 해줘"). 후보를 표로 뽑아(`export_candidates`)
# 근거 문장을 읽고 판정을 적으면(`data/untangle.tsv`), `run_table` 이 모델
# 대신 그 표를 읽는다. 표는 (src, dst) 가 키라 원본과 파생본에 같은 판정이
# 가고, 다음 수집이 같은 related_to 를 다시 내도 다시 묻지 않는다 — 표는
# 언제나 기계를 이긴다 (CLAUDE.md §1-4 와 같은 규칙).
#
#     src<TAB>dst<TAB>type<TAB>direction<TAB>confidence<TAB>메모
#     type 은 CHOICES 의 키 또는 none · direction 은 A→B / B→A · confidence 는 certain/probable/possible

TABLE_MODEL = "claude-fable-5-1 (표)"


def export_candidates(conn: sqlite3.Connection, path, *, redo: bool = False) -> int:
    """모델에 물을 후보를 표로 뽑는다 — A·B 의 이름과 타입, 근거, 고를 수 있는 타입."""
    rows = candidates(conn, redo=redo)
    lines = ["# src\tdst\tA\tA타입\tB\tB타입\t고를 수 있는 것\t근거"]
    for r in rows:
        ev = (json.loads(r["props"] or "{}").get("evidence") or "").replace("\t", " ").replace("\n", " ")
        ch = " ".join(f"{t}:{d}" for t, d, _ in choices_for(r["a_type"], r["b_type"]))
        lines.append("\t".join([r["src"], r["dst"], r["a_label"], r["a_type"], r["b_label"], r["b_type"], ch, ev]))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def load_verdicts(path) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 5:
            raise ValueError(f"{path}:{lineno} 다섯 칸(src·dst·type·direction·confidence)이 필요합니다: {raw!r}")
        src, dst, t, d, c = (x.strip() for x in parts[:5])
        if t != "none" and t not in CHOICES:
            raise ValueError(f"{path}:{lineno} 모르는 타입 {t!r}")
        if d not in ("A→B", "B→A"):
            raise ValueError(f"{path}:{lineno} 방향은 A→B 또는 B→A: {d!r}")
        if c not in CONFIDENCE:
            raise ValueError(f"{path}:{lineno} 확신도는 certain/probable/possible: {c!r}")
        out[(src, dst)] = {"type": t, "direction": d, "confidence": c,
                           "note": parts[5].strip() if len(parts) > 5 else ""}
    return out


def run_table(store, table: dict[tuple[str, str], dict], rep: Report, *, redo: bool = False) -> Report:
    """표에 있는 후보만 판정한다. 표에 없는 것은 그대로 남아 다음 표를 기다린다."""
    rows = candidates(store.conn, redo=redo)
    hit = [r for r in rows if (r["src"], r["dst"]) in table]
    rep.asked = len(hit)
    for r in hit:
        apply_verdict(store, r, table[(r["src"], r["dst"])], TABLE_MODEL, rep)
    store.conn.commit()
    return rep


# --- 4. 남는 것 -----------------------------------------------------------

def remaining(conn: sqlite3.Connection) -> dict[str, int]:
    """아직 related_to 인 것을 갈래별로 센다 — 무엇이 왜 남았는가."""
    out: dict[str, int] = {}
    for r in conn.execute("SELECT source, label, props FROM edges WHERE type = 'related_to'"):
        props = json.loads(r["props"] or "{}")
        if r["label"] in ("피해", "표적", "수습", "언급", "근거 없음"):
            key = "역할 판정 (참여가 아니라고 본 것)"
        elif r["label"] == "다음":
            key = "전후 (P155/P156)"
        elif r["label"] == "이 기사의 대상":
            key = "실록 기사의 대상"
        elif props.get("infobox_field") in ("사망자", "생존자"):
            key = "인포박스 사망자·생존자"
        elif props.get("original_type"):
            key = f"완화 (원래 {props['original_type']})"
        elif props.get("untangled"):
            u = props["untangled"]
            key = ("카디널리티를 넘어 적지 않은 것" if u.endswith("/over")
                   else "모델이 none 이라 한 것" if u == "none"
                   else "모델이 확신하지 못한 것")
        elif props.get("evidence"):
            key = "아직 묻지 않은 추출"
        elif r["label"]:
            key = f"라벨 '{r['label']}'"
        else:
            key = f"라벨 없음 ({r['source']})"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
