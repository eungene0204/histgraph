"""주소가 될 이름 — `/인물/세종`.

글로 읽는 장은 `/n/wd:Q12345` 로 서 있었다. 사람도 로봇도 그 주소에서
읽을 것이 없다 — 검색 결과에 뜨는 것은 제목 밑의 주소 한 줄인데 거기
`wd:Q12345` 라고 적히면 무엇에 대한 장인지 알 수 없고, 같은 이름의 장이
여럿일 때 어느 쪽인지도 못 가른다. 그래서 **타입과 이름으로 주소를
짓는다**: `/인물/세종`, `/사건/임진왜란`, `/유산/서울-숭례문`.

**한글로 적는다** (2026-09-11 사용자 결정). 주소창도 사람이 읽는 자리라
§1 이 그대로 걸리고, 로마자로 적으면 본문은 한국어인데 주소만 영어인
장이 된다. 이름 만 개의 로마자 표기를 새로 지어야 하는데 그 표기에는
정본이 없다 — 이정(李霆)과 이정(李貞)이 같은 `yi-jeong` 이 된다.

**한 번 준 주소는 거두지 않는다.** 검색 로봇이 색인에 올린 주소가 사라지면
그 장이 쌓아 둔 것이 같이 사라진다. 그래서 이 표는 **쌓기만 한다** —
노드의 이름이 바뀌거나 타입이 바뀌면 새 줄을 얹고 옛 줄에는 `current=0`
을 적는다. 옛 주소로 오면 새 주소로 301 로 보낸다 (`pages.route`).

**표는 원본에서 짓고 파생본이 물려받는다** (`scope.extract` 가 옮긴다).
파생본에서 따로 지으면 같은 노드가 두 주소를 갖게 된다 — 이름이 겹치는
노드 하나가 파생본에 없으면 남은 쪽이 맨 이름을 차지하기 때문이다.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

SCHEMA = """
CREATE TABLE IF NOT EXISTS slugs (
    segment TEXT NOT NULL,
    slug    TEXT NOT NULL,
    node_id TEXT NOT NULL,
    -- 0 이면 옛 주소다. 지우지 않고 남겨 301 로 새 주소를 알려 준다.
    current INTEGER NOT NULL DEFAULT 1,
    made_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (segment, slug)
);
CREATE INDEX IF NOT EXISTS idx_slugs_node ON slugs(node_id, current);
"""

# 타입 → 주소의 첫 칸. **화면의 타입 딱지와 같은 말이되 짧은 쪽을 고른다** —
# 주소는 검색 결과에 `histgraph.space › 인물 › 세종` 으로 풀려 뜬다.
SEGMENTS: dict[str, str] = {
    "person": "인물",
    "event": "사건",
    "place": "장소",
    "org": "단체",
    "heritage": "유산",
    "artwork": "작품",
    "period": "시대",
    "role": "직위",
    "concept": "개념",
}

# 매체는 **타입이 하나(`media`)이고 갈래(form)가 여럿**이다 (ontology.FORMS
# 머리글 — 쪼개면 엣지 표와 색이 여섯 배로 는다). 주소에서는 갈래로 가른다:
# 사람이 찾는 것은 '매체 노다지'가 아니라 '드라마 노다지'다.
MEDIA_SEGMENTS: dict[str, str] = {
    "film": "영화",
    "series": "드라마",
    "documentary": "다큐멘터리",
    "animation": "애니메이션",
    "book": "책",
    "comic": "만화",
    "game": "게임",
    "music": "음악",
    "stage": "무대",
}

# 주소의 첫 칸 → (타입, 갈래). 갈래가 None 이면 타입 전체다.
SEGMENT_TYPE: dict[str, tuple[str, str | None]] = {
    **{seg: (t, None) for t, seg in SEGMENTS.items()},
    **{seg: ("media", form) for form, seg in MEDIA_SEGMENTS.items()},
}

# 사이트맵 파일 이름에 쓰는 영문 키 (`/sitemap-person-1.xml`). 로봇만 읽는
# 이름이라 §1 의 '화면'이 아니다 — 한글을 넣으면 주소가 퍼센트로 도배된다.
SEGMENT_KEY: dict[str, str] = {
    **{seg: t for t, seg in SEGMENTS.items()},
    **{seg: form for form, seg in MEDIA_SEGMENTS.items()},
}

# 주소에 남길 글자: 한글·숫자·로마자. 나머지는 사이표가 된다.
_KEEP = re.compile(r"[^가-힣ㄱ-ㅎㅏ-ㅣ0-9A-Za-z]+")
_DASHES = re.compile(r"-{2,}")


def segment_of(node_type: str, props: dict | None = None) -> str | None:
    """이 노드가 설 주소의 첫 칸. 모르는 타입이면 None."""
    if node_type == "media":
        form = (props or {}).get("form")
        return MEDIA_SEGMENTS.get(form) or SEGMENTS["artwork"]
    return SEGMENTS.get(node_type)


def slugify(label: str) -> str:
    """이름 → 주소 한 칸. '여진 정벌 (조선)' → '여진-정벌-조선'.

    괄호로 가른 동명이인은 그대로 주소에 남는다 (§1-2 의 관례가 곧 주소의
    구분이 된다). 담을 글자가 하나도 없으면 빈 문자열 — 부르는 쪽이
    노드 id 로 물러난다."""
    text = unicodedata.normalize("NFC", label or "").strip().lower()
    text = _DASHES.sub("-", _KEEP.sub("-", text)).strip("-")
    # 주소 한 칸이 너무 길면 아무도 읽지 않는다. 자를 때 음절 중간이
    # 끊기지 않게 사이표에서 끊는다.
    if len(text) > 80:
        text = text[:80].rsplit("-", 1)[0] or text[:80]
    return text


def _short(node_id: str) -> str:
    """이름에서 담을 글자가 하나도 안 남은 노드의 마지막 자리. **숫자다** —
    글자를 쓰면 주소에 로마자가 선다 (§1)."""
    return str(int(hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:8], 16) % 1000000)


def _year(value: str | None) -> str:
    if not value:
        return ""
    digits = ""
    for ch in str(value).lstrip("-"):
        if not ch.isdigit():
            break
        digits += ch
    return f"{int(digits)}년" if digits else ""


def _candidates(base: str, row) -> list[str]:
    """겹칠 때 덧붙일 차례. **연대가 먼저다** — '이정-1541년' 은 어느 이정인지
    말하지만 '이정-2' 는 아무것도 말하지 않는다.

    연대도 없으면 번호다. **글자를 붙이지 않는다** — id 의 해시를 붙여
    봤더니 `/장소/중구-208ea4` 처럼 주소에 로마자가 섰다 (§1)."""
    out = [base]
    for value in (row["start_date"], row["end_date"]):
        year = _year(value)
        if year and f"{base}-{year}" not in out:
            out.append(f"{base}-{year}")
    out += [f"{base}-{n}" for n in range(2, 100)]
    return out


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def assign(conn) -> dict[str, int]:
    """주소가 없는 노드에 주소를 준다. **이미 준 주소는 손대지 않는다.**

    타입이나 이름이 바뀌어 주소가 달라져야 하는 노드는 옛 줄을 `current=0`
    으로 내리고 새 줄을 얹는다 — 옛 주소는 그대로 살아서 새 주소를 가리킨다.
    """
    ensure_table(conn)
    taken = {(r["segment"], r["slug"]) for r in
             conn.execute("SELECT segment, slug FROM slugs")}
    current = {r["node_id"]: (r["segment"], r["slug"]) for r in
               conn.execute("SELECT node_id, segment, slug FROM slugs WHERE current = 1")}

    # 차수가 높은 노드가 맨 이름을 갖는다 — '세종' 은 임금이지 같은 이름의
    # 딴 사람이 아니다. 한 번 정해지면 차수가 바뀌어도 그대로다 (위의 taken).
    rows = conn.execute(
        """SELECT n.id, n.type, n.label, n.props, n.start_date, n.end_date,
                  (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) AS degree
             FROM nodes n
            ORDER BY degree DESC, n.id"""
    ).fetchall()

    added = moved = skipped = 0
    for row in rows:
        props = json.loads(row["props"] or "{}")
        segment = segment_of(row["type"], props)
        if segment is None:
            skipped += 1
            continue
        base = slugify(row["label"]) or slugify(row["id"]) or _short(row["id"])
        have = current.get(row["id"])
        if have and have[0] == segment and (have[1] == base or have[1].startswith(f"{base}-")):
            continue        # 이미 이 이름으로 서 있다
        pick = next((c for c in _candidates(base, row) if (segment, c) not in taken), None)
        if pick is None:
            skipped += 1
            continue
        if have:
            conn.execute(
                "UPDATE slugs SET current = 0 WHERE segment = ? AND slug = ?", have)
            moved += 1
        else:
            added += 1
        conn.execute(
            "INSERT INTO slugs (segment, slug, node_id) VALUES (?,?,?)",
            (segment, pick, row["id"]))
        taken.add((segment, pick))
        current[row["id"]] = (segment, pick)
    conn.commit()
    return {"added": added, "moved": moved, "skipped": skipped,
            "total": len(current)}


def path(segment: str, slug: str) -> str:
    return f"/{segment}/{slug}"


def lookup(conn, segment: str, slug: str) -> tuple[str, bool] | None:
    """주소 → (노드 id, 지금 주소인가). 없으면 None."""
    row = conn.execute(
        "SELECT node_id, current FROM slugs WHERE segment = ? AND slug = ?",
        (segment, slug)).fetchone()
    if row is None:
        return None
    return row["node_id"], bool(row["current"])


def path_for(conn, node_id: str) -> str | None:
    row = conn.execute(
        "SELECT segment, slug FROM slugs WHERE node_id = ? AND current = 1",
        (node_id,)).fetchone()
    return path(row["segment"], row["slug"]) if row else None


def paths_for(conn, node_ids) -> dict[str, str]:
    """여럿을 한 번에. 관계 줄마다 물어보면 한 장에 수백 번 묻는다."""
    ids = [i for i in dict.fromkeys(node_ids)]
    out: dict[str, str] = {}
    for i in range(0, len(ids), 400):
        batch = ids[i:i + 400]
        marks = ",".join("?" * len(batch))
        for r in conn.execute(
            f"""SELECT node_id, segment, slug FROM slugs
                 WHERE current = 1 AND node_id IN ({marks})""", batch):
            out[r["node_id"]] = path(r["segment"], r["slug"])
    return out


def counts(conn) -> dict[str, int]:
    """첫 칸마다 몇 장인가 (목록 장·사이트맵이 쓴다)."""
    return {r["segment"]: r["n"] for r in conn.execute(
        "SELECT segment, COUNT(*) AS n FROM slugs WHERE current = 1 GROUP BY segment")}


def missing(conn) -> int:
    """주소를 못 받은 노드 수. 파생본을 만들고 나서 세는 관문."""
    ensure_table(conn)
    return conn.execute(
        """SELECT COUNT(*) FROM nodes n
            WHERE NOT EXISTS (SELECT 1 FROM slugs s
                               WHERE s.node_id = n.id AND s.current = 1)"""
    ).fetchone()[0]


__all__ = ["SCHEMA", "SEGMENTS", "MEDIA_SEGMENTS", "SEGMENT_TYPE", "SEGMENT_KEY",
           "assign", "counts", "ensure_table", "lookup", "missing",
           "path", "path_for", "paths_for", "segment_of", "slugify"]
