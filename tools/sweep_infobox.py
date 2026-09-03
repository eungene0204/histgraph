"""파서 수정 **이전 규칙에서만 나오던** 인포박스 엣지를 지운다.

인포박스 엣지는 전부 위키텍스트에서 파생된 값인데, `ingest` 는 upsert 라
예전 규칙으로 들어온 엣지를 스스로 못 지운다.

고친 두 가지:
  1. `<ref>` 각주 속 링크가 필드 값으로 들어왔다.
     신상옥 `자녀 = … 신진환<ref>… [[최은희]]와 재혼하기 이전 …</ref>`
         -> 최은희(배우자)가 신상옥의 자녀가 됐다.
     고종  `출생지 = [[한성부]] [[경운동]] 1번지<ref>[[운현궁]] 인근에서
            태어났다 …</ref>` -> 각주가 말하는 '인근'이 출생지가 됐다.
  2. 앞선 링크를 **부연하는 괄호** 속 링크가 값으로 들어왔다.
     은신군 `자녀 = 양자 [[남연군]](생부 [[이병원]])`
         -> 남연군의 생부 이병원이 은신군의 자녀가 됐다.

**"지금 규칙에서 안 나오는 것"을 다 지우면 안 된다.** 위키 문서가 그새
바뀐 것까지 지워진다 — 김한구의 `자녀` 칸은 지금 비어 있지만 김귀주와
정순왕후가 그의 자녀인 것은 사실이다.

**`ingest` 를 두 번 돌려 비교해도 안 된다.** 문서명 해소가 망을 타므로
한 번은 풀리고 한 번은 안 풀린다 — 그 차이가 삭제 후보로 둔갑한다
(실측: 옛·새 규칙 결과가 똑같은 `김성일 --출생지--> 안동시` 가 후보로
올라왔다). 그래서 **망을 타지 않는 링크 단위로** 비교하고, 사라진
링크만 한 번에 해소한다.

기본은 계획만 출력한다. 목록을 확인한 뒤 --apply 로 실행할 것.

사용:
  uv run tools/sweep_infobox.py [--apply] [DB ...]
"""

from __future__ import annotations

import json
import logging
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from histgraph.http import Fetcher  # noqa: E402
from histgraph.sources import infobox as ib  # noqa: E402
from histgraph.store import GraphStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TYPES = ("event", "person")
FIELD_SPLIT = re.compile(r"^\s*\|\s*([가-힣A-Za-z0-9_ ]+?)\s*=", re.M)


def legacy_links(value: str) -> list[str]:
    """수정 이전의 규칙 — 필드 값의 위키링크를 그냥 다 가져온다."""
    out = []
    for target in ib.WIKILINK.findall(value):
        target = target.strip()
        if target and not ib.LINK_SKIP.match(target):
            out.append(target)
    return out


def sweep(path: Path, apply: bool) -> None:
    if not path.exists():
        print(f"건너뜀 (없음): {path}")
        return
    print(f"\n=== {path} ===")
    fetcher = Fetcher(ROOT / "data" / "cache", min_interval=0.5)

    with GraphStore(str(path)) as store:
        store.conn.execute("PRAGMA busy_timeout=60000")

        # 1) 문서마다 옛 규칙과 지금 규칙을 나란히 계산 (망을 타지 않는다)
        lost: list[tuple[str, str, str]] = []   # (주인 노드, 필드, 사라진 문서명)
        docs = 0
        for node_type in TYPES:
            fields = ib.FIELDS_BY_TYPE[node_type]
            rows = store.conn.execute(
                "SELECT id, props FROM nodes WHERE type = ?", (node_type,)
            ).fetchall()
            for r in rows:
                url = json.loads(r["props"]).get("kowiki_url")
                if not url:
                    continue
                title = urllib.parse.unquote(
                    url.rsplit("/", 1)[-1]).replace("_", " ")
                wikitext = ib.fetch_wikitext(fetcher, title)
                if not wikitext:
                    continue
                span = ib.infobox_span(wikitext, fields)
                if not span:
                    continue
                docs += 1
                parts = FIELD_SPLIT.split(span)
                for i in range(1, len(parts) - 1, 2):
                    field = parts[i].strip()
                    if field not in fields:
                        continue
                    value = parts[i + 1]
                    old = legacy_links(value)
                    new = ib.field_links(
                        value, drop_parens=field in ib.PAREN_ASIDE_FIELDS)
                    # 출생지·사망지는 가장 좁은 것 하나만 쓴다 — 목록 전체가
                    # 아니라 **마지막 한 칸**이 바뀌었는지를 봐야 한다.
                    if fields[field][0] in ib.NARROWEST_ONLY:
                        old, new = old[-1:], new[-1:]
                    for gone in set(old) - set(new):
                        lost.append((r["id"], field, gone))

        # 2) 사라진 문서명만 한 번에 해소
        titles = sorted({t for _, _, t in lost})
        qids = ib.resolve_titles(fetcher, titles) if titles else {}

        wanted: set[tuple[str, str, str]] = set()
        for owner, field, gone in lost:
            qid = qids.get(gone)
            if not qid:
                continue
            edge_type, _, direction = ib.FIELDS_BY_TYPE[
                "event" if field in ib.EVENT_FIELDS else "person"][field]
            other = f"wd:{qid}"
            src, dst = ((owner, other) if direction == ib.OUT
                        else (other, owner))
            wanted.add((src, dst, edge_type))

        rows = store.conn.execute(
            """SELECT e.src, e.dst, e.type, s.label AS sl, d.label AS dl,
                      json_extract(e.props,'$.infobox_field') AS f
                 FROM edges e
                 JOIN nodes s ON s.id = e.src
                 JOIN nodes d ON d.id = e.dst
                WHERE e.source = ?""",
            (ib.SOURCE,),
        ).fetchall()
        doomed = [r for r in rows if (r["src"], r["dst"], r["type"]) in wanted]

        for r in doomed:
            print(f"  삭제: {r['sl']} --{r['type']}--> {r['dl']}  [{r['f']}]")
        print(f"문서 {docs:,}개 · 인포박스 엣지 {len(rows):,}건"
              f" · 옛 규칙에서만 나오던 링크 {len(lost):,}건"
              f" · 지울 엣지 {len(doomed):,}건")

        if apply:
            store.conn.executemany(
                "DELETE FROM edges WHERE src=? AND dst=? AND type=? AND source=?",
                [(r["src"], r["dst"], r["type"], ib.SOURCE) for r in doomed],
            )
            store.conn.commit()
            print("적용 완료")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    args = [a for a in sys.argv[1:] if a != "--apply"]
    paths = ([Path(a) for a in args]
             if args else sorted((ROOT / "data").glob("*.sqlite")))
    for p in paths:
        sweep(p, "--apply" in sys.argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
