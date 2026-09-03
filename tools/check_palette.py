"""팔레트 검증 — 화면의 색이 서로 구별되는가, 색약에서도 그런가.

`web/graph.js` 의 TYPE_COLOR·GROUP_COLOR 를 **파일에서 직접 읽어** 잰다.
값을 여기 베껴 두면 색을 고칠 때 한쪽만 바뀌어, 검증기가 이미 없는 색을
합격시킨다.

거리는 OKLab ΔE ×100. 색약 시뮬레이션은 Viénot(1999) — 선형 RGB 를 LMS 로
옮기고 결손 원추를 나머지 둘로부터 복원한 뒤 되돌린다. 2형(deutan)이
가장 흔하고, 여기서도 가장 나쁜 값이 나온다.

**이 수치가 말하지 않는 것:** ΔE 는 두 색을 나란히 놓고 견준 값이다.
화면에서 노드는 흩어져 있고 크기도 작아, 실제 구별은 이보다 어렵다.
그래서 낮은 값이 나오면 '색 말고 무엇이 그 뜻을 말하는가'를 물어야 한다.

사용:
  python3 tools/check_palette.py
"""

from __future__ import annotations

import itertools
import math
import re
import sys
from pathlib import Path

GRAPH_JS = Path(__file__).resolve().parents[1] / "web" / "graph.js"

# 이 아래로 떨어지면 색만으로는 못 가른다고 본다. 절대 기준이 아니라
# 눈금이다 — 낮다고 곧바로 실패가 아니라, 색 말고 다른 단서가 있어야 한다.
FLOOR = 5.0


def read_palette(name: str) -> dict[str, str]:
    src = GRAPH_JS.read_text(encoding="utf-8")
    m = re.search(rf"export const {name} = \{{(.*?)\n\}};", src, re.S)
    if not m:
        raise SystemExit(f"{GRAPH_JS} 에서 {name} 을 못 찾았습니다")
    return dict(re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", m.group(1)))


def _srgb_to_lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_lin(h: str) -> list[float]:
    h = h.lstrip("#")
    return [_srgb_to_lin(int(h[i : i + 2], 16)) for i in (0, 2, 4)]


def lin_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1 / 3) if v > 0 else -((-v) ** (1 / 3)) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


RGB2LMS = [[17.8824, 43.5161, 4.11935],
           [3.45565, 27.1554, 3.86714],
           [0.0299566, 0.184309, 1.46709]]
LMS2RGB = [[0.080944, -0.130504, 0.116721],
           [-0.0102485, 0.0540194, -0.113615],
           [-0.000365294, -0.00412163, 0.693513]]
DEFICIENCY = {
    "2형(deutan)": [[1, 0, 0], [0.494207, 0, 1.24827], [0, 0, 1]],
    "1형(protan)": [[0, 2.02344, -2.52581], [0, 1, 0], [0, 0, 1]],
    "3형(tritan)": [[1, 0, 0], [0, 1, 0], [-0.395913, 0.801109, 0]],
}


def _mul(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def simulate(lin: list[float], kind: str) -> list[float]:
    if kind == "정상 시야":
        return lin
    return _mul(LMS2RGB, _mul(DEFICIENCY[kind], _mul(RGB2LMS, lin)))


def worst_pair(colors: dict[str, str], kind: str) -> tuple[float, str, str]:
    labs = {k: lin_to_oklab(*simulate(hex_to_lin(v), kind)) for k, v in colors.items()}
    best = (1e9, "", "")
    for (ka, a), (kb, b) in itertools.combinations(labs.items(), 2):
        d = math.dist(a, b) * 100
        if d < best[0]:
            best = (d, ka, kb)
    return best


VIEWS = ["정상 시야", "2형(deutan)", "1형(protan)", "3형(tritan)"]


def table(title: str, colors: dict[str, str]) -> float:
    print(f"\n{title} — {len(colors)}색")
    lowest = 1e9
    for kind in VIEWS:
        d, a, b = worst_pair(colors, kind)
        mark = " ⚠" if d < FLOOR else ""
        print(f"  {kind:12} 최악 쌍 ΔE {d:5.1f}   {a} ↔ {b}{mark}")
        lowest = min(lowest, d)
    return lowest


def main() -> int:
    types = read_palette("TYPE_COLOR")
    groups = read_palette("GROUP_COLOR")
    low_t = table("노드 색 (타입)", types)
    low_g = table("갈래 색", groups)

    # 갈래를 색상 계열로 묶었다면, 덩어리 안보다 덩어리 사이가 멀어야 한다.
    # 그래야 '먼저 네 덩어리로 읽히고 그 안에서 갈린다'가 성립한다.
    print("\n갈래 안의 색끼리 (덩어리가 뭉쳐 보이는가)")
    families = {
        "인물·단체": ["person", "org"],
        "장소·유물·작품": ["place", "heritage", "artwork", "media"],
        "시대·직위": ["period", "role"],
    }
    for fam, keys in families.items():
        sub = {k: types[k] for k in keys if k in types}
        if len(sub) < 2:
            continue
        d, a, b = worst_pair(sub, "2형(deutan)")
        print(f"  {fam:14} 2형 최악 ΔE {d:5.1f}   {a} ↔ {b}")

    print(f"\n눈금 {FLOOR} 아래는 색만으로 가를 수 없다고 본다.")
    if min(low_t, low_g) < FLOOR:
        print("색만으로 뜻을 나르는 자리가 없는지 확인할 것 —")
        print("범례에 이름이 적혀 있는가, 고른 노드의 타입이 글자로 나오는가.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
