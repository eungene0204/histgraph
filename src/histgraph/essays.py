"""해설 글 — 인과의 사슬을 따라 읽는 글 (`/글/…`).

2026-10-05, 애드센스 `Low value content` 세 번째. 글로 읽는 장은 노드 하나를
중심으로 관계를 읽어 주지만, 한 사건이 **어떻게 다음 사건을 불렀는지**를 이어서
읽어 주는 글은 없었다. 이 관계망이 판정해 둔 인과(`data/causal.tsv`)와 정본의
근거 문장을 따라 사람이 읽을 글로 엮는다.

## 글 하나 = 파일 하나 (`src/histgraph/essays/*.md`)

    제목: 임진왜란은 왜 일어났고 무엇을 남겼나
    요약: 목록과 검색 결과에 서는 한두 문장.
    상태: 초안          ← 초안 · 공개
    날짜: 2026-10-05
    ---
    본문. 빈 줄로 문단을 가른다. '## ' 로 시작하는 줄은 소제목이다.
    [[임진왜란]] · [[도요토미 히데요시|히데요시]] 는 그 이름의 장으로 이어진다.

- **초안은 공개하지 않는다.** 주소로 열 수는 있지만 `noindex` 이고 목록·사이트맵에
  없으며, 장 머리에 '검토 전 초안'이라 적는다. 사람이 사실을 확인하고 `공개` 로
  바꾼다 — 모델이 쓴 글을 그대로 세우면 그것이 곧 자동 생성 문구다.
- **출처 이름을 본문에 적지 않는다** (§1). 근거는 링크한 장마다 출처 줄로 선다.
- 이름 링크는 라벨이 **정확히 같은** 노드로 간다. 여럿이면 연결이 많은 쪽, 없으면
  링크 없이 글자만 남긴다 — 짐작으로 엉뚱한 장에 잇지 않는다.
- 파일 이름(확장자 뺀 것)이 주소다 — 한글이다 (§1, 주소창도 읽는 자리).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ESSAY_DIR = Path(__file__).parent / "essays"
SEGMENT = "글"
STATUSES = ("초안", "공개")

_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


@dataclass(frozen=True)
class Essay:
    slug: str
    title: str
    summary: str
    status: str
    date: str
    body: str

    @property
    def published(self) -> bool:
        return self.status == "공개"


class EssayError(ValueError):
    pass


def parse(slug: str, text: str) -> Essay:
    head, sep, body = text.partition("\n---\n")
    if not sep:
        raise EssayError(f"{slug}: 머리와 본문을 '---' 줄로 가르세요")
    meta: dict[str, str] = {}
    for line in head.splitlines():
        if not line.strip():
            continue
        key, colon, value = line.partition(":")
        if not colon:
            raise EssayError(f"{slug}: 머리 줄은 '이름: 값' 꼴입니다 — {line!r}")
        meta[key.strip()] = value.strip()
    for key in ("제목", "요약", "상태", "날짜"):
        if not meta.get(key):
            raise EssayError(f"{slug}: 머리에 '{key}' 가 없습니다")
    if meta["상태"] not in STATUSES:
        raise EssayError(f"{slug}: 상태는 {'·'.join(STATUSES)} 중 하나 — {meta['상태']!r}")
    return Essay(slug, meta["제목"], meta["요약"], meta["상태"], meta["날짜"], body.strip())


def load(directory: Path | None = None) -> list[Essay]:
    """날짜가 새로운 것부터. 폴더는 부를 때 읽는다 (시험이 바꿔 끼운다)."""
    directory = directory or ESSAY_DIR
    if not directory.exists():
        return []
    out = [parse(p.stem, p.read_text(encoding="utf-8"))
           for p in sorted(directory.glob("*.md"))]
    return sorted(out, key=lambda e: (e.date, e.slug), reverse=True)


def find(slug: str, directory: Path | None = None) -> Essay | None:
    return next((e for e in load(directory) if e.slug == slug), None)


def link_targets(conn, labels: set[str]) -> dict[str, str]:
    """라벨 → 노드 id. 정확히 같은 라벨만, 여럿이면 연결이 많은 쪽."""
    out: dict[str, str] = {}
    for label in labels:
        row = conn.execute(
            """SELECT n.id FROM nodes n
                WHERE n.label = ?
                ORDER BY (SELECT COUNT(*) FROM edges e WHERE e.src = n.id OR e.dst = n.id) DESC
                LIMIT 1""", (label,)).fetchone()
        if row:
            out[label] = row[0]
    return out


def labels_in(body: str) -> set[str]:
    return {m.group(1).strip() for m in _LINK.finditer(body)}


def render_body(body: str, href_of) -> str:
    """본문 → HTML. `href_of(label)` 이 주소를 주면 링크, None 이면 글자만."""
    from html import escape

    def inline(text: str) -> str:
        parts, last = [], 0
        for m in _LINK.finditer(text):
            parts.append(escape(text[last:m.start()]))
            label = m.group(1).strip()
            shown = (m.group(2) or label).strip()
            url = href_of(label)
            parts.append(f'<a href="{url}">{escape(shown)}</a>' if url else escape(shown))
            last = m.end()
        parts.append(escape(text[last:]))
        return "".join(parts)

    html = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            html.append(f"<h2>{inline(block[3:].strip())}</h2>")
        else:
            html.append(f'<p class="essay">{inline(" ".join(block.splitlines()))}</p>')
    return "\n".join(html)


def plain(body: str) -> str:
    """링크 표기를 걷은 본문 글자 (글자 수·영어 관문용)."""
    return _LINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), body)
