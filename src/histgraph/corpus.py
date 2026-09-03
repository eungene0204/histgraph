"""말뭉치 — 그래프 옆에 두는 **글**의 저장·검색층 (RAG 의 아래층).

그래프는 "누가 무엇에 얽혔나"를 말하지만 **어떻게** 얽혔는지는 말하지
못한다. 12.3 내란의 인포박스는 이재명을 `주요인물2` 에 적었고, 우리는
그것을 '참여'로 만들었다 — 그는 체포 명단에 오른 사람이다. 그 사실은
구조(Wikidata·인포박스)에 없고 **산문**에 있다: "이재명, 우원식은 담을
넘어 국회 건물에 들어갔다", "여 사령관은 다음과 같은 체포 명단을 …".

그래서 글을 통째로 내려받아 문단 단위로 쪼개 두고, 물음이 있을 때 그
문단을 찾아 근거로 쓴다. 이 모듈은 저장과 검색만 한다 — 판정(누가 어느
편이었나)은 `roles` 가 하고, 그것도 여기서 찾은 문단을 **인용**해야만
쓴다 (`extract.evidence_supported` 와 같은 규칙).

**그래프 파일과 다른 파일이다** (`data/corpus.sqlite`). 글은 그래프보다
훨씬 크고, 화면 DB(`korea.sqlite`)는 저장소에 실려 배포되므로 거기에
글을 얹으면 안 된다. `*.sqlite` 는 .gitignore 가 이미 막는다.

검색은 SQLite FTS5 다. 토크나이저는 unicode61(어절 단위)이고 질의는
**앞머리 일치**(`"체포"*`)로 던진다. 한국어는 조사·어미가 붙어 '이재명은'과
'이재명'이 다른 어절인데, 앞머리 일치가 그것을 받아 준다. trigram 을 먼저
써 봤다가 물렸다 — 세 글자 미만은 못 찾는데 한국어 낱말은 '체포'·'명단'·
'내란'처럼 두 글자가 태반이다.
"""

from __future__ import annotations

import datetime
import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "data" / "corpus.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id         INTEGER PRIMARY KEY,
    node_id    TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    source     TEXT NOT NULL,
    url        TEXT,
    fetched_at TEXT NOT NULL,
    chars      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    id      INTEGER PRIMARY KEY,
    doc_id  INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    n       INTEGER NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_node ON passages(node_id, n);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text, section, content='passages', content_rowid='id', tokenize='unicode61'
);
"""
FTS_TOKENIZER = "unicode61"


def open_corpus(path: Path | str | None = None) -> sqlite3.Connection:
    """말뭉치 파일을 연다 (없으면 만든다). None 이면 기본 자리."""
    path = Path(path) if path else DEFAULT_CORPUS
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(SCHEMA)
    # 색인 방식이 바뀌었으면(trigram 시절 파일) 다시 짓는다. 가상 테이블은
    # CREATE IF NOT EXISTS 로는 안 바뀐다.
    made = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'passages_fts'").fetchone()
    if made and f"tokenize='{FTS_TOKENIZER}'" not in (made["sql"] or ""):
        reindex(conn)
    return conn


def reindex(conn: sqlite3.Connection) -> None:
    """색인을 버리고 문단 표에서 다시 짓는다."""
    conn.execute("DROP TABLE IF EXISTS passages_fts")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO passages_fts(passages_fts) VALUES('rebuild')")
    conn.commit()


# --- 쪼개기 ----------------------------------------------------------------
# 위키백과 본문은 `== 제목 ==` 으로 절이 나뉘고 빈 줄로 문단이 나뉜다.
# 절 제목을 문단에 붙여 두는 이유: "체포 명단" 문단은 '=== 체포 지시 ==='
# 아래에 있고, 그 제목이 문단 자체보다 역할을 더 잘 말해 준다.
_HEADING = re.compile(r"^(=+)[ \t]*(.+?)[ \t]*=+[ \t]*$", re.M)
# 각주·링크 절은 글이 아니다. 작품용 `CUT_SECTIONS` 보다 좁게 자른다 —
# 역사 문서의 '주요 인물' 절은 본문이다.
SKIP_SECTIONS = re.compile(
    r"^(?:각주|주석|참고\s*자료|참고\s*문헌|같이\s*보기|외부\s*링크|관련\s*항목|더\s*보기)$"
)
PASSAGE_TARGET = 700    # 한 문단 묶음의 목표 길이
PASSAGE_MAX = 1400      # 이보다 길면 문장에서 자른다
_SENT_END = re.compile(r"(?<=[.!?。])\s+")


def split_passages(text: str) -> list[tuple[str, str]]:
    """본문 -> [(절 제목, 문단 묶음)]. 순수 함수 — 네트워크 없이 시험한다.

    짧은 문단은 목표 길이까지 이어 붙이고(한 줄짜리 문단이 검색 단위가
    되면 문맥이 없다), 긴 문단은 문장 경계에서 자른다. 절이 바뀌면 묶음도
    끊는다 — 다른 절의 문장이 한 근거로 인용되면 안 된다."""
    out: list[tuple[str, str]] = []
    section = ""
    skipping = False
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append((section, "\n".join(buf).strip()))
            buf.clear()

    for block in re.split(r"\n\s*\n", text or ""):
        block = block.strip()
        if not block:
            continue
        m = _HEADING.match(block)
        if m and m.end() == len(block):
            flush()
            section = m.group(2).strip()
            skipping = bool(SKIP_SECTIONS.match(section))
            continue
        # 제목이 문단 머리에 붙어 온 경우 ('== 배경 ==\n본문')
        if m:
            flush()
            section = m.group(2).strip()
            skipping = bool(SKIP_SECTIONS.match(section))
            block = block[m.end():].strip()
            if not block:
                continue
        if skipping:
            continue
        for piece in _cut_long(block):
            if buf and sum(len(b) for b in buf) + len(piece) > PASSAGE_TARGET:
                flush()
            buf.append(piece)
    flush()
    return [(s, t) for s, t in out if t]


def _cut_long(block: str) -> list[str]:
    if len(block) <= PASSAGE_MAX:
        return [block]
    pieces: list[str] = []
    cur = ""
    for sent in _SENT_END.split(block):
        if cur and len(cur) + len(sent) > PASSAGE_MAX:
            pieces.append(cur.strip())
            cur = ""
        cur += sent + " "
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


# --- 넣기 ------------------------------------------------------------------
def put_doc(
    conn: sqlite3.Connection,
    node_id: str,
    title: str,
    text: str,
    source: str = "kowiki",
    url: str | None = None,
) -> int:
    """문서 하나를 (다시) 넣는다. 같은 노드의 옛 문서는 지운다. 문단 수를 돌려준다."""
    old = conn.execute("SELECT id FROM docs WHERE node_id = ?", (node_id,)).fetchone()
    if old is not None:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM passages WHERE doc_id = ?", (old["id"],))]
        for pid in ids:
            conn.execute(
                "INSERT INTO passages_fts(passages_fts, rowid, text, section) "
                "SELECT 'delete', id, text, section FROM passages WHERE id = ?", (pid,))
        conn.execute("DELETE FROM docs WHERE id = ?", (old["id"],))
    cur = conn.execute(
        "INSERT INTO docs (node_id, title, source, url, fetched_at, chars) VALUES (?,?,?,?,?,?)",
        (node_id, title, source, url,
         datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
         len(text)),
    )
    doc_id = cur.lastrowid
    parts = split_passages(text)
    for n, (section, body) in enumerate(parts):
        c = conn.execute(
            "INSERT INTO passages (doc_id, node_id, n, section, text) VALUES (?,?,?,?,?)",
            (doc_id, node_id, n, section, body),
        )
        conn.execute(
            "INSERT INTO passages_fts(rowid, text, section) VALUES (?,?,?)",
            (c.lastrowid, body, section),
        )
    return len(parts)


def has_doc(conn: sqlite3.Connection, node_id: str) -> bool:
    return conn.execute("SELECT 1 FROM docs WHERE node_id = ?", (node_id,)).fetchone() is not None


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    docs = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(chars), 0) AS c FROM docs").fetchone()
    passages = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    return {"docs": docs["n"], "chars": docs["c"], "passages": passages}


# --- 찾기 ------------------------------------------------------------------
_TOKEN = re.compile(r"[가-힣A-Za-z0-9·.]+")


def fts_query(query: str, all_terms: bool = True) -> str | None:
    """사람의 물음 -> FTS5 질의. 어절마다 앞머리 일치(`"체포"*`)다.

    한 글자 토큰은 뺀다 — 조사이거나 너무 흔하다. 남는 토큰이 없으면
    None, 호출부가 LIKE 로 물러난다.

    기본은 AND 다. OR 로 물으면 bm25 가 흔한 이름의 반복에 끌린다 — 실측:
    '체포 명단 이재명'이 12.3 내란의 체포 명단 문단이 아니라 '이재명'이
    열 번 나오는 형수 욕설 문단을 앞세웠다. 다 있는 문단이 없을 때만
    OR 로 물러난다 (`search`)."""
    tokens = [t for t in _TOKEN.findall(query) if len(t) >= 2]
    if not tokens:
        return None
    # 따옴표로 감싸야 '12.3' 의 점이 연산자로 읽히지 않는다. 뒤의 * 가
    # 앞머리 일치 — '체포' 가 '체포하여'·'체포된' 을 받는다.
    quoted = ['"' + t.replace('"', '""') + '"*' for t in tokens]
    return (" AND " if all_terms else " OR ").join(quoted)


def search(
    conn: sqlite3.Connection,
    query: str,
    k: int = 8,
    node_ids: Iterable[str] | None = None,
) -> list[dict]:
    """물음에 가장 가까운 문단 k개. `node_ids` 를 주면 그 문서들 안에서만."""
    q = fts_query(query)
    ids = list(node_ids) if node_ids is not None else None
    if q is None:
        like = f"%{query.strip()}%"
        sql = "SELECT p.node_id, p.section, p.text, d.title FROM passages p JOIN docs d ON d.id = p.doc_id WHERE p.text LIKE ?"
        args: list = [like]
        if ids:
            sql += f" AND p.node_id IN ({','.join('?' * len(ids))})"
            args += ids
        rows = conn.execute(sql + " LIMIT ?", (*args, k)).fetchall()
        return [dict(r, rank=0.0) for r in rows]
    sql = """SELECT p.node_id, p.section, p.text, d.title, bm25(passages_fts) AS rank
               FROM passages_fts f
               JOIN passages p ON p.id = f.rowid
               JOIN docs d ON d.id = p.doc_id
              WHERE passages_fts MATCH ?"""
    scope = ""
    scope_args: list = []
    if ids:
        scope = f" AND p.node_id IN ({','.join('?' * len(ids))})"
        scope_args = ids
    rows = conn.execute(sql + scope + " ORDER BY rank LIMIT ?", (q, *scope_args, k)).fetchall()
    if not rows:
        loose = fts_query(query, all_terms=False)
        rows = conn.execute(sql + scope + " ORDER BY rank LIMIT ?", (loose, *scope_args, k)).fetchall()
    return [dict(r) for r in rows]


def mentions(
    conn: sqlite3.Connection,
    node_id: str,
    names: Iterable[str],
    limit: int = 6,
) -> list[dict]:
    """한 문서 안에서 이 이름들이 나오는 문단을 **문서 순서대로**.

    검색이 아니라 대조다 — "이 사람이 이 사건 글에 어떻게 적혀 있나"에는
    순위보다 차례가 맞다. 앞 문단이 뒤 문단의 문맥이다."""
    wanted = [n.strip() for n in names if n and len(n.strip()) >= 2]
    if not wanted:
        return []
    cond = " OR ".join("p.text LIKE ?" for _ in wanted)
    rows = conn.execute(
        f"""SELECT p.node_id, p.n, p.section, p.text, d.title
              FROM passages p JOIN docs d ON d.id = p.doc_id
             WHERE p.node_id = ? AND ({cond})
             ORDER BY p.n LIMIT ?""",
        (node_id, *[f"%{w}%" for w in wanted], limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --- 무엇을 내려받나 -------------------------------------------------------
def pick_nodes(store, since: int = 1945) -> dict[str, str]:
    """말뭉치에 넣을 노드와 그 이유.

    사건이 뼈대다: 그 해 뒤에 일어난 사건, 그리고 그 사건에 엣지로 닿아
    있는 인물·단체. 국적으로 고르지 않는 이유는 `scope.Era.seed_by_polity`
    와 같다 — 대한민국 국적 18,471명은 명단이다."""
    from .timeline import _year_of

    picked: dict[str, str] = {}
    events: list[str] = []
    for r in store.conn.execute(
        """SELECT id, start_date, json_extract(props, '$.seed_era') AS era
             FROM nodes WHERE type = 'event'"""
    ):
        year = _year_of(r["start_date"])
        if (year is not None and year >= since) or r["era"] == "대한민국":
            events.append(r["id"])
            picked[r["id"]] = "사건"
    for i in range(0, len(events), 400):
        batch = events[i : i + 400]
        marks = ",".join("?" * len(batch))
        for r in store.conn.execute(
            f"""SELECT DISTINCT n.id, n.type FROM edges e
                  JOIN nodes n ON n.id = CASE WHEN e.src IN ({marks}) THEN e.dst ELSE e.src END
                 WHERE (e.src IN ({marks}) OR e.dst IN ({marks}))
                   AND n.type IN ('person', 'org')""",
            (*batch, *batch, *batch),
        ):
            picked.setdefault(r["id"], "사건의 이웃")
    for r in store.conn.execute(
        """SELECT id FROM nodes WHERE type IN ('org', 'concept')
            AND json_extract(props, '$.seed_era') = '대한민국'"""
    ):
        picked.setdefault(r["id"], "시드")
    return picked


def build(
    fetcher,
    store,
    conn: sqlite3.Connection,
    node_ids: Iterable[str],
    refresh: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """노드들의 한국어 위키백과 본문 전체를 내려받아 넣는다.

    문서명은 노드 라벨이 아니라 사이트링크에서 온다 (`wikipedia.fetch_titles`
    주석: 우리 라벨 '조선 세종'의 문서는 '세종'이다). 시드로 들어온 노드는
    `props.kowiki_url` 이 이미 문서명을 안다."""
    import json
    import urllib.parse

    from .sources import wikipedia

    ids = [i for i in node_ids if i.startswith("wd:")]
    if not refresh:
        ids = [i for i in ids if not has_doc(conn, i)]
    if limit:
        ids = ids[:limit]
    if not ids:
        return {"asked": 0, "fetched": 0, "missing": 0, "passages": 0}

    titles: dict[str, str] = {}
    need: list[str] = []
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        marks = ",".join("?" * len(batch))
        for r in store.conn.execute(
            f"SELECT id, props FROM nodes WHERE id IN ({marks})", batch
        ):
            url = (json.loads(r["props"] or "{}")).get("kowiki_url")
            if url:
                titles[r["id"]] = urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")
            else:
                need.append(r["id"][len("wd:"):])
    if need:
        log.info("사이트링크 조회 %d건", len(need))
        for qid, title in wikipedia.fetch_titles(fetcher, need).items():
            titles[f"wd:{qid}"] = title
    log.info("문서 %d건 내려받기 (전문)", len(titles))

    fetched = missing = passages = 0
    by_title = {t: nid for nid, t in titles.items()}
    ordered = sorted(by_title)
    for i in range(0, len(ordered), 20):
        batch = ordered[i : i + 20]
        resolved: dict[str, str] = {}
        found = wikipedia.fetch_extracts(fetcher, batch, full=True, resolved_from=resolved)
        got_asked: set[str] = set()
        for got_title, text in found.items():
            asked = resolved.get(got_title, got_title)
            nid = by_title.get(asked)
            if nid is None or not text:
                continue
            got_asked.add(asked)
            passages += put_doc(
                conn, nid, got_title, text, "kowiki",
                f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(got_title)}",
            )
            fetched += 1
        missing += len([t for t in batch if t not in got_asked])
        conn.commit()
        if (i // 20) % 10 == 0:
            log.info("  %d / %d", min(i + 20, len(ordered)), len(ordered))
    return {"asked": len(ids), "fetched": fetched,
            "missing": missing + (len(ids) - len(titles)), "passages": passages}
