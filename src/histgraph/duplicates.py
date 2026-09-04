"""중복 관문 — 한 사건이 두 노드로 들어와 있는 것을 찾는다.

**발단.** 2026-09-04 지적: "사도세자 사건과, 임오화변은 같은거야. 둘중
하나로 통일 시켜야해." 실제로 두 노드였다 — `nikh:kc_i303100`(사도세자
사건)과 `wd:Q18685040`(임오화변). 둘 다 1762년 영조가 세자를 뒤주에 가둔
그 일이고, **양쪽 설명이 서로를 이칭으로 부르고 있었다.**

이름이 갈리는 이유는 소스마다 표제를 다르게 다는 데 있다. 국편은
'사도세자 사건', 위키백과는 '임오화변'이다. 띄어쓰기만 달라지는 것도
같은 원인이다 ('3·1 운동' / '3·1운동', '만보산 사건' / '만보산사건').

**찾는 규칙은 넷이다. 판정에 짐작을 넣지 않는다.**

| 규칙 | 무엇을 보나 | 예 |
|---|---|---|
| `라벨` | 공백·가운뎃점·괄호를 지우면 같은 이름 | `만보산 사건` / `만보산사건` |
| `별칭` | 한쪽의 라벨이 다른 쪽의 별칭 | `조일동맹조약` / `조일맹약` |
| `이칭` | 설명 첫 문장이 상대를 '또는 …', '…이라고도 한다'로 부른다 | `임오화변` / `사도세자 사건` |
| `핵심어` | 갈래 접미사(전투·대첩·사건…)를 떼면 같은 이름 | `홍산대첩` / `홍산 전투` |

**규칙은 후보를 찾을 뿐, 합치지 않는다.** 라벨 유사도로 합치면 절반이
틀린다 (`promote.title_variant_matches` 주석의 실측). 여기서도 같다:
`제1차 왕자의 난`과 `제2차 왕자의 난`은 핵심어가 같지만 다른 사건이고,
`설마리 전투`(1951)는 스스로를 '임진강 전투'라 부르지만 그래프의
`임진강 전투`는 1592년 것이다. 그래서 **후보마다 사람이 한 줄을 적는다**
(`data/duplicates.tsv`):

    merge<TAB>남길 id<TAB>없앨 id<TAB>근거
    keep <TAB>id       <TAB>id      <TAB>왜 다른 사건인지

표에 없는 후보가 남아 있으면 명령이 **종료 코드 1**로 묻는다. 사람이
기억하는 대신 기계가 묻는 것은 CLAUDE.md §1 의 관문들과 같은 방식이다.

**한 번 합치고 끝나는 게 아니다.** `upsert_nodes` 는 id 로 노드를 다시
세우므로, 다음 `ingest`·`nikh` 가 없앤 노드를 되살린다. `relabel` 과
똑같이 **수집 뒤마다 다시 돌리는 것을 전제로** 만들었다 — 같은 표를 몇
번 적용해도 결과가 같다(멱등). 화면이 읽는 파생본에도 한 번 더 돌린다:

    uv run histgraph dedupe --apply
    uv run histgraph --db data/korea.sqlite dedupe --apply

**남길 쪽을 고르는 기준.** 표에 사람이 적지만, 기본은 *더 많이 연결된
노드*다 — 엣지가 그 노드에 이미 쌓여 있으면 옮길 것이 적고, 화면에서
사라지는 이름은 별칭으로 남아 검색에 계속 걸린다(`promote.merge_node`).
설명이 국편(nikh)에만 있는 쪽을 없앨 때는 설명을 옮겨 적는다 — 국편이
정본이다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# 갈래 접미사. '홍산대첩'과 '홍산 전투'가 같은 싸움임을 보려면 떼야 한다.
KIND_SUFFIX = re.compile(
    r"(전투|해전|대첩|싸움|사건|의난|난|운동|혁명|개혁|조약|협약|전쟁|정변"
    r"|사화|민란|봉기|항쟁|의거|참변|학살|화변|옥사|반정)$"
)

# 차수. 이것이 어긋나면 **다른 사건이다** — 후보로도 올리지 않는다.
ORDINAL = re.compile(r"^(?:제\s*(\d+)\s*차?|(\d+)\s*차)")

# 라벨에서 지워도 같은 이름인 것들.
PUNCT = re.compile(r"[\s·․‧,.\-–—()·『』「」《》]")

# 이칭 선언 문형. `{n}` 자리에 상대의 라벨이 들어간다.
ALIAS_PHRASES = (
    r"(?:‘|'|“|\")?{n}(?:’|'|”|\")?(?:\([^)]*\))?\s*(?:이)?(?:라고도|로도)"
    r"\s*(?:한다|불린|부른|불리)",
    r"(?:또는|혹은)\s*{n}",
    r"{n}(?:\([^)]*\))?\s*(?:또는|혹은)",
    r"(?:이칭|다른 이름은?|달리)\s*(?:‘|')?{n}",
)

# 이칭을 찾을 때 상대 이름 앞에 차수가 붙어 있으면 다른 사건을 부른 것이다.
_ORD_BEFORE = re.compile(r"(제\s*\d+\s*차|제\s*\d+|\d+\s*차)\s*$")


class DuplicateTableError(ValueError):
    """표가 깨졌다 — 조용히 넘어가면 반쯤 합쳐진 그래프가 남는다."""


@dataclass(frozen=True, slots=True)
class Candidate:
    rule: str
    a: str            # id (더 많이 연결된 쪽을 앞에 둔다)
    b: str
    evidence: str

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.a, self.b))


@dataclass(slots=True)
class Verdict:
    action: str       # 'merge' | 'keep'
    keep: str
    drop: str
    note: str = ""

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.keep, self.drop))


@dataclass(slots=True)
class Report:
    candidates: list[Candidate] = field(default_factory=list)
    unjudged: list[Candidate] = field(default_factory=list)
    merged: list[tuple[str, str, int]] = field(default_factory=list)  # (남긴, 없앤, 옮긴 엣지)
    absent: list[Verdict] = field(default_factory=list)   # 이 그래프에 없는 짝
    stale: list[Verdict] = field(default_factory=list)    # 이미 합쳐진 짝
    date_clashes: list[str] = field(default_factory=list)  # 합친 짝의 연대가 어긋난다


# --- 표 -------------------------------------------------------------------


def load_table(path: Path) -> list[Verdict]:
    """`판정<TAB>id<TAB>id<TAB>근거` 표를 읽는다."""
    rows: list[Verdict] = []
    seen: set[frozenset[str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 3:
            raise DuplicateTableError(
                f"{path}:{lineno} 탭으로 나뉜 세 칸이 필요합니다: {raw!r}")
        action, keep, drop = (p.strip() for p in parts[:3])
        note = parts[3].strip() if len(parts) > 3 else ""
        if action not in ("merge", "keep"):
            raise DuplicateTableError(
                f"{path}:{lineno} 판정은 merge 또는 keep 입니다: {action!r}")
        if not keep or not drop or keep == drop:
            raise DuplicateTableError(f"{path}:{lineno} 서로 다른 두 id 가 필요합니다: {raw!r}")
        v = Verdict(action, keep, drop, note)
        if v.key in seen:
            raise DuplicateTableError(f"{path}:{lineno} 같은 짝이 두 번 적혔습니다: {raw!r}")
        seen.add(v.key)
        rows.append(v)
    return rows


# --- 규칙 -----------------------------------------------------------------


def _ordinal(label: str) -> str | None:
    m = ORDINAL.match(label.replace(" ", ""))
    if not m:
        return None
    return m.group(1) or m.group(2)


def core_name(label: str) -> str:
    """차수와 갈래 접미사를 뗀 핵심어. '제2차 진주성 전투' -> '진주성'."""
    s = PUNCT.sub("", label)
    s = ORDINAL.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = KIND_SUFFIX.sub("", s)
    return s


def lead_sentence(desc: str | None, limit: int = 400) -> str:
    """설명의 첫 문장. 이칭 선언은 여기에만 온다 — 뒤쪽 문장에서 찾으면
    본문이 언급한 남의 사건까지 이칭으로 읽는다."""
    d = (desc or "").strip()
    if not d:
        return ""
    m = re.search(r"(?<=다)\.", d[:limit])
    return d[: m.end()] if m else d[:200]


def _degree(conn: sqlite3.Connection) -> dict[str, int]:
    deg: dict[str, int] = {}
    for r in conn.execute(
        "SELECT id, (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) d"
        " FROM nodes n"
    ):
        deg[r["id"]] = r["d"]
    return deg


def find(conn: sqlite3.Connection, node_type: str = "event") -> list[Candidate]:
    """중복 후보를 규칙별로 찾는다. 큰 쪽(엣지가 많은 쪽)을 앞에 둔다."""
    nodes = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, start_date, description FROM nodes WHERE type = ?",
            (node_type,),
        )
    }
    deg = _degree(conn)
    by_label: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        by_label.setdefault(n["label"], []).append(nid)

    found: dict[frozenset[str], Candidate] = {}

    def add(rule: str, x: str, y: str, evidence: str) -> None:
        a, b = sorted((x, y), key=lambda i: (-deg.get(i, 0), i))
        key = frozenset((a, b))
        if key not in found:
            found[key] = Candidate(rule, a, b, evidence)

    # 규칙 1 — 공백·구두점만 다른 라벨.
    flat: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        flat.setdefault(PUNCT.sub("", n["label"]), []).append(nid)
    for name, ids in flat.items():
        if len(ids) > 1:
            for i, x in enumerate(ids):
                for y in ids[i + 1:]:
                    add("라벨", x, y, f"공백·구두점을 지우면 '{name}'")

    # 규칙 2 — 한쪽의 라벨이 다른 쪽의 별칭.
    for r in conn.execute("SELECT node_id, alias FROM aliases"):
        holder, alias = r["node_id"], r["alias"]
        if holder not in nodes:
            continue
        for other in by_label.get(alias, ()):
            if other != holder:
                add("별칭", holder, other,
                    f"'{alias}' 이 {nodes[holder]['label']} 의 별칭")

    # 규칙 3 — 설명 첫 문장의 이칭 선언.
    names = sorted((n for n in by_label if len(n) >= 3), key=len, reverse=True)
    for nid, n in nodes.items():
        head = lead_sentence(n["description"])
        # 자기 이름이 첫 문장에 없으면 그 문장은 이 노드를 정의하는 문장이
        # 아니다 ('조선의 역사' 가 본문에서 임진왜란을 부르는 것).
        if not head or n["label"] not in head:
            continue
        for name in names:
            if name == n["label"] or name not in head:
                continue
            for phrase in ALIAS_PHRASES:
                hit = next(
                    (m for m in re.finditer(phrase.format(n=re.escape(name)), head)
                     if not _ORD_BEFORE.search(head[: m.start()])),
                    None,
                )
                if hit is None:
                    continue
                for other in by_label[name]:
                    if other != nid:
                        add("이칭", nid, other,
                            f"{n['label']} 의 설명이 '{hit.group(0).strip()}'")
                break

    # 규칙 4 — 갈래 접미사를 뗀 핵심어가 같다. 차수가 어긋나면 다른 사건이다.
    cores: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        c = core_name(n["label"])
        if len(c) >= 2:
            cores.setdefault(c, []).append(nid)
    for c, ids in cores.items():
        if len(ids) < 2:
            continue
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                ox, oy = _ordinal(nodes[x]["label"]), _ordinal(nodes[y]["label"])
                if ox is not None and oy is not None and ox != oy:
                    continue                      # 제1차 ≠ 제2차
                add("핵심어", x, y, f"갈래를 떼면 '{c}'")

    order = {"라벨": 0, "별칭": 1, "이칭": 2, "핵심어": 3}
    return sorted(found.values(), key=lambda c: (order[c.rule], c.a))


# --- 적용 -----------------------------------------------------------------


def sweep(
    conn: sqlite3.Connection,
    table: list[Verdict],
    node_type: str = "event",
) -> Report:
    """후보를 찾고 표와 맞춰 본다. 고치지는 않는다."""
    rep = Report(candidates=find(conn, node_type))
    judged = {v.key for v in table}
    group = _merge_groups(table)
    rep.unjudged = [
        c for c in rep.candidates
        if c.key not in judged
        # 셋이 한 사건인 경우. `가↔나`, `가↔다` 를 적었으면 `나↔다` 도 판정된
        # 것이다 — 같은 것에 같은 것은 같다.
        and not (group.get(c.a) is not None and group.get(c.a) == group.get(c.b))
    ]
    have = {
        r["id"] for r in conn.execute("SELECT id FROM nodes")
    }
    for v in table:
        if v.action != "merge":
            continue
        if v.keep not in have and v.drop not in have:
            rep.absent.append(v)
        elif v.drop not in have:
            rep.stale.append(v)             # 이미 합쳐졌다 (멱등)
        elif v.keep not in have:
            rep.absent.append(v)            # 남길 쪽이 없다 — 손대지 않는다
    return rep


def _merge_groups(table: list[Verdict]) -> dict[str, int]:
    """`merge` 로 이어진 id 를 한 무리로 묶는다."""
    parent: dict[str, str] = {}

    def root(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for v in table:
        if v.action == "merge":
            parent[root(v.keep)] = root(v.drop)
    groups: dict[str, int] = {}
    ids = {i: n for n, i in enumerate(sorted({root(x) for x in parent}))}
    for x in parent:
        groups[x] = ids[root(x)]
    return groups


def apply(store, table: list[Verdict], node_type: str = "event") -> Report:
    """표의 `merge` 줄을 적용한다. 몇 번 돌려도 결과가 같다."""
    from .promote import merge_node

    conn = store.conn
    rep = sweep(conn, table, node_type)
    skip = {v.key for v in rep.absent} | {v.key for v in rep.stale}
    for v in table:
        if v.action != "merge" or v.key in skip:
            continue
        clash = _carry_content(conn, v.keep, v.drop)
        if clash:
            rep.date_clashes.append(clash)
        stats = merge_node(store, v.drop, v.keep, method="duplicate_table")
        rep.merged.append((v.keep, v.drop, stats["edges"]))
    conn.commit()
    # 합친 뒤 다시 세어야 '남은 후보'가 맞다.
    after = sweep(conn, table, node_type)
    rep.candidates, rep.unjudged = after.candidates, after.unjudged
    return rep


def _carry_content(conn: sqlite3.Connection, keep: str, drop: str) -> str | None:
    """없앨 쪽에만 있는 것을 남길 쪽으로 옮긴다. 연대가 어긋나면 알린다.

    **비어 있는 칸만 채운다** (`upsert_nodes` 와 같은 COALESCE 규칙). 양쪽에
    값이 있으면 손대지 않는다 — 더 자세해 보이는 값이 더 맞는 값은 아니다
    ('언론통폐합'의 1980-05 는 1980 보다 자세하지만 실제는 11월 30일이다).
    지워질 설명은 `props.merged_desc` 에 남긴다.

    돌려주는 것은 **연대 충돌 알림**이다. 어느 쪽이 맞는지는 기계가 모른다."""
    import json

    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, source, start_date, end_date, description, url, props"
            " FROM nodes WHERE id IN (?,?)",
            (keep, drop),
        )
    }
    k, d = rows.get(keep), rows.get(drop)
    if not k or not d:
        return None

    fill = {c: d[c] for c in ("start_date", "end_date", "description", "url")
            if not (k[c] or "").strip() and (d[c] or "").strip()}
    props = json.loads(k["props"] or "{}")
    if (d["description"] or "").strip() and "description" not in fill:
        props.setdefault("merged_desc", d["description"])
    sets = ", ".join(f"{c} = ?" for c in fill)
    conn.execute(
        f"UPDATE nodes SET {sets + ', ' if sets else ''}props = ?,"
        " updated_at = datetime('now') WHERE id = ?",
        (*fill.values(), json.dumps(props, ensure_ascii=False), keep),
    )

    for col in ("start_date", "end_date"):
        a, b = (k[col] or "").strip(), (d[col] or "").strip()
        if a and b and not (a.startswith(b) or b.startswith(a)):
            return f"{k['label']}: {col} {a} ↔ 없앤 쪽 {b}"
    return None
