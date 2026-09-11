#!/usr/bin/env python3
"""링크를 펼칠 때 서는 그림 한 장을 그린다 (`web/public/og.png`).

카카오톡·슬랙·트위터·구글이 링크를 펼칠 때 그림이 없으면 글자만 남아
아무도 누르지 않는다. 노드마다 제 그림이 있는 것은 유산뿐이라
(국가유산청), 나머지 만 이천 장은 이 한 장을 쓴다.

**표준 라이브러리만 쓴다** (`dependencies = []`). 그림 라이브러리가 없으니
PNG 를 직접 적는다 — 배경과 동그라미 몇, 잇는 선, 그리고 제품 이름이다.
글자는 5×9 점판을 손으로 적어 키운다. 이 그림에 있는 로마자는 제품
이름뿐이다 (CLAUDE.md §1 이 봐주는 그 한 낱말).

    python3 tools/make_og.py            # web/public/og.png 를 다시 그린다
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

W, H = 1200, 630
BG = (0x1E, 0x1E, 0x1E)
LINE = (0x3A, 0x3A, 0x3A)
TEXT = (0xDA, 0xDA, 0xDA)
MUTED = (0x8A, 0x8A, 0x8A)
ACTOR = (0x3D, 0x84, 0xF5)   # 인물·단체
EVENT = (0xFB, 0x6C, 0x13)   # 사건
THING = (0x2E, 0x9E, 0x5E)   # 장소·유산·작품
FRAME = (0x2A, 0x5D, 0x78)   # 시대·자리·개념

# 5×9 점판. 위 두 줄은 올림글자(h·t·i), 아래 두 줄은 내림글자(g·p) 자리다.
GLYPHS: dict[str, dict[int, str]] = {
    "h": {0: "10000", 1: "10000", 2: "11110", 3: "10001", 4: "10001", 5: "10001", 6: "10001"},
    "i": {0: "00100", 2: "00100", 3: "00100", 4: "00100", 5: "00100", 6: "00100"},
    "s": {2: "01111", 3: "10000", 4: "01110", 5: "00001", 6: "11110"},
    "t": {0: "01000", 1: "01000", 2: "11110", 3: "01000", 4: "01000", 5: "01000", 6: "00110"},
    "g": {2: "01111", 3: "10001", 4: "10001", 5: "01111", 6: "00001", 7: "00001", 8: "01110"},
    "r": {2: "10110", 3: "11001", 4: "10000", 5: "10000", 6: "10000"},
    "a": {2: "01110", 3: "00001", 4: "01111", 5: "10001", 6: "01111"},
    "p": {2: "11110", 3: "10001", 4: "10001", 5: "11110", 6: "10000", 7: "10000", 8: "10000"},
}

# 관계망 한 조각. (x, y, 반지름, 색) 과 그 사이의 선.
NODES = [
    (300, 250, 34, ACTOR), (470, 180, 22, EVENT), (455, 350, 26, THING),
    (620, 270, 18, FRAME), (700, 160, 26, ACTOR), (760, 380, 20, EVENT),
    (900, 250, 30, THING), (880, 430, 16, ACTOR), (560, 460, 16, FRAME),
    (180, 380, 18, EVENT), (1010, 150, 16, EVENT),
]
EDGES = [(0, 1), (0, 2), (1, 2), (1, 4), (2, 3), (3, 4), (3, 5), (4, 6),
         (5, 6), (5, 7), (2, 8), (0, 9), (6, 10), (6, 7)]


def canvas() -> list[bytearray]:
    row = bytearray(bytes(BG) * W)
    return [bytearray(row) for _ in range(H)]


def put(px: list[bytearray], x: int, y: int, color: tuple[int, int, int],
        alpha: float = 1.0) -> None:
    if not (0 <= x < W and 0 <= y < H):
        return
    i = x * 3
    if alpha >= 1.0:
        px[y][i:i + 3] = bytes(color)
        return
    old = px[y][i:i + 3]
    px[y][i:i + 3] = bytes(round(o + (c - o) * alpha) for o, c in zip(old, color))


def disc(px, cx: int, cy: int, r: int, color) -> None:
    """가장자리를 한 겹 흐리게 — 톱니를 덜 보이게 한다."""
    for y in range(cy - r - 1, cy + r + 2):
        for x in range(cx - r - 1, cx + r + 2):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d <= r - 0.5:
                put(px, x, y, color)
            elif d < r + 0.5:
                put(px, x, y, color, r + 0.5 - d)


def line(px, x0: int, y0: int, x1: int, y1: int, color) -> None:
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) * 2 or 1
    for i in range(steps + 1):
        t = i / steps
        put(px, round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), color)


def word(px, text: str, x: int, y: int, scale: int, color) -> int:
    """5×9 점판을 키워 찍는다. 오른쪽 끝 x 를 돌려준다."""
    for ch in text:
        glyph = GLYPHS.get(ch)
        if glyph is None:
            x += scale * 3
            continue
        for row, bits in glyph.items():
            for col, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            put(px, x + col * scale + dx, y + row * scale + dy, color)
        x += scale * 6
    return x


def png(px: list[bytearray]) -> bytes:
    raw = b"".join(b"\x00" + bytes(row) for row in px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parents[1] / "web" / "public" / "og.png")
    px = canvas()
    for a, b in EDGES:
        x0, y0, _r0, _c0 = NODES[a]
        x1, y1, _r1, _c1 = NODES[b]
        line(px, x0, y0, x1, y1, LINE)
    for x, y, r, color in NODES:
        disc(px, x, y, r, color)
    # 제품 이름. 9 글자 × (5+1) × 눈금 = 가운데에 놓는다.
    scale = 11
    width = len("histgraph") * 6 * scale - scale
    word(px, "histgraph", (W - width) // 2, 505, scale, TEXT)
    # 밑줄 한 가닥 — 글자와 관계망을 가른다.
    for x in range((W - width) // 2, (W - width) // 2 + width):
        put(px, x, 480, MUTED, 0.35)
    out.write_bytes(png(px))
    print(f"  {out} · {W}×{H} · {out.stat().st_size:,} 바이트")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
