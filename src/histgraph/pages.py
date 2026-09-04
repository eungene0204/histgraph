"""사람과 로봇이 **글로** 읽는 노드 페이지 (`/n/<id>`).

화면(`web/`)은 자바스크립트가 그리는 관계망이라, 검색 로봇과 광고 심사의
눈에는 빈 화면이다 — `index.html` 이 내주는 것은 `<div id="root">` 하나뿐이고
인물도 사건도 그 안에 없다. 그래서 같은 자료를 한 번 더, 이번에는 **문서로**
낸다. 자료는 `GraphAPI.node` 가 주는 것 그대로다.

상세 패널(`web/src/components/DetailPanel.jsx`)과 같은 것을 그리지만 같은
일을 하지 않는다. 저쪽은 **파고드는** 자리라 근거 구절·인과 사슬·자취까지
붙고, 이쪽은 **읽는** 자리라 이름·설명·이어진 것에서 멈춘다. 관계를 문장으로
바꾸는 규칙(`relations.js` 의 SENTENCE)은 옮겨 오지 않았다 — 같은 규칙을 두
벌 두면 한쪽만 고쳐진다.

여기도 §1 이 그대로 걸린다: 사람이 읽는 자리에 영어를 쓰지 않고, 자료가
어디서 왔는지 말하지 않는다.
"""

from __future__ import annotations

import os
from html import escape
from urllib.parse import quote

from .ontology import NODE_TYPES

# 링크를 절대 주소로 적어야 하는 자리(정본 주소·사이트맵). 배포 도메인이
# 바뀌면 여기 하나만 고친다.
SITE = os.environ.get("HISTGRAPH_SITE", "https://www.histgraph.space").rstrip("/")

# 광고. 화면 세 장(`web/index.html`·`privacy.html`·`terms.html`)에 걸어 둔
# 것과 같은 번호다.
ADS_CLIENT = "ca-pub-8335444243080631"

# 엣지 라벨은 출발 노드 기준이라 그대로 쓰면 방향이 뒤집힌다. `child_of` 는
# 'A → B = A 가 B 의 자녀'라, 나가는 상대는 부모이고 들어오는 상대가 자녀다.
# (같은 표가 `web/src/lib/relations.js` 의 DIR_HEAD 에도 있다. 방향이 뜻을
#  갖는 타입은 셋뿐이라 옮겨 적었다 — 늘어나면 서버가 내주는 편이 맞다.)
DIR_HEAD = {
    "child_of": {"out": "부모", "in": "자녀"},
    "part_of": {"out": "상위", "in": "하위"},
    "caused": {"out": "결과", "in": "원인"},
}
TIME_TYPES = ("from_period", "dated_to")

# 한 묶음에 이만큼까지만 적는다. 세종의 '자녀'처럼 수십이 붙는 자리가
# 있는데, 문서로 읽는 화면에서 목록이 화면을 넘기면 아무도 안 읽는다.
GROUP_MAX = 30

STYLE = """
:root {
  color-scheme: dark;
  --surface: #141413; --surface-2: #1a1a19; --surface-3: #232321;
  --line: #2f2f2c; --text: #f0efec; --text-2: #c3c2b7; --text-3: #8b8b84;
  --accent: #3987e5;
  --actor: #4a6ad8; --event: #ec7e3e; --thing: #3fb968; --frame: #8b8b84;
  --font: "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--surface); }
body {
  margin: 0; background: var(--surface); color: var(--text-2);
  font-family: var(--font); font-size: 15px; line-height: 1.75;
  -webkit-font-smoothing: antialiased;
}
.top { border-bottom: 1px solid var(--line); background: var(--surface-2); }
.top a {
  display: flex; align-items: center; gap: 9px;
  max-width: 760px; margin: 0 auto; padding: 11px 22px;
  color: var(--text); text-decoration: none; font-weight: 650; letter-spacing: -0.01em;
}
.top .mark {
  width: 13px; height: 13px; border-radius: 50%; background: var(--actor);
  box-shadow: 9px 5px 0 -3px var(--event), 16px -3px 0 -4px var(--thing);
}
.top .back { margin-left: auto; font-weight: 400; font-size: 12.5px; color: var(--text-3); }
.top a:hover .back { color: var(--accent); }
main { max-width: 760px; margin: 0 auto; padding: 36px 22px 70px; }
h1 { color: var(--text); font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 8px; }
h1 .also { color: var(--text-3); font-weight: 400; font-size: 19px; margin-left: 8px; }
.kind { display: flex; align-items: center; gap: 8px; color: var(--text-3); font-size: 13px; margin: 0 0 26px; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.desc { color: var(--text); font-size: 16px; margin: 0 0 18px; white-space: pre-wrap; }
.empty { color: var(--text-3); font-size: 14px; margin: 0 0 18px; }
.aka { color: var(--text-3); font-size: 13px; margin: 0 0 8px; }
h2 {
  color: var(--text); font-size: 15px; font-weight: 650;
  margin: 34px 0 12px; padding-top: 16px; border-top: 1px solid var(--line);
}
h3 { color: var(--text-3); font-size: 12px; font-weight: 600; letter-spacing: .04em; margin: 18px 0 6px; }
ul { list-style: none; margin: 0; padding: 0; }
li { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 14.5px; }
li a { color: var(--text); text-decoration: none; }
li a:hover { color: var(--accent); text-decoration: underline; }
li .meta { color: var(--text-3); font-size: 12px; }
.more { color: var(--text-3); font-size: 12.5px; padding: 4px 0; }
.open {
  display: inline-block; margin-top: 26px; padding: 8px 14px;
  border: 1px solid var(--line); border-radius: 8px;
  color: var(--text-2); text-decoration: none; font-size: 13.5px;
}
.open:hover { color: var(--text); border-color: var(--text-3); }
.foot {
  max-width: 760px; margin: 0 auto; padding: 0 22px 60px;
  color: var(--text-3); font-size: 12.5px;
}
.foot a { color: var(--text-3); text-decoration: none; }
.foot a:hover { color: var(--accent); }
.foot span { margin: 0 7px; }
"""

GROUP_COLOR = {"actor": "var(--actor)", "event": "var(--event)",
               "thing": "var(--thing)", "frame": "var(--frame)"}

# 타입 → 갈래. `server.TYPE_GROUP` 과 같은 표다 (서버를 들여오면 순환한다).
_GROUP = {"person": "actor", "org": "actor", "event": "event",
          "place": "thing", "heritage": "thing", "artwork": "thing",
          "media": "thing", "period": "frame", "role": "frame",
          "concept": "frame"}


def _year(value: str | None) -> str:
    """'1397-01-01' → '1397년'. 기원전은 앞말을 붙여 적는다."""
    if not value:
        return ""
    text = str(value)
    neg = text.startswith("-")
    digits = ""
    for ch in text.lstrip("-"):
        if not ch.isdigit():
            break
        digits += ch
    if not digits:
        return ""
    return f"기원전 {int(digits)}년" if neg else f"{int(digits)}년"


def _why_empty(node: dict) -> str:
    """빈 설명의 이유. 뭉뚱그려 '자료 없음'이라 적으면, 더 받아오면 채워지는
    노드와 애초에 채울 것이 없는 노드가 같은 말을 하게 된다."""
    if node.get("source") == "timeline":
        return "연표의 해를 세우는 노드라 설명이 없습니다."
    if node.get("source") == "extract":
        return "산문에서 이름만 추출된 노드라 원문이 없습니다."
    if node.get("desc_dropped"):
        return "한국어로 옮길 수 있는 설명이 아직 없습니다."
    return "아직 서사를 받아오지 않았습니다."


def _head(rel: dict) -> str:
    if rel["type"] in TIME_TYPES:
        return "시기" if rel["dir"] == "out" else "이 시기의 개체"
    return DIR_HEAD.get(rel["type"], {}).get(rel["dir"]) or rel["label"]


def _groups(relations: list[dict]) -> list[tuple[str, list[dict]]]:
    """관계를 묶음으로 정리한다. 종류·방향이 머리이고, 한 묶음 안에서 같은
    상대는 한 줄이다 — 시대와 시점이 둘 다 걸린 해가 두 번 나오지 않게."""
    out: list[tuple[str, list[dict]]] = []
    index: dict[str, int] = {}
    for rel in relations or []:
        head = _head(rel)
        if head not in index:
            index[head] = len(out)
            out.append((head, []))
        bucket = out[index[head]][1]
        if any(r["other"]["id"] == rel["other"]["id"] for r in bucket):
            continue
        bucket.append(rel)
    return out


def _link(other: dict) -> str:
    color = GROUP_COLOR.get(other.get("group"), "var(--frame)")
    kind = NODE_TYPES.get(other.get("type"), "")
    return (
        f'<li><span class="dot" style="background:{color}"></span>'
        f'<a href="/n/{quote(other["id"], safe="")}">{escape(other["label"])}</a>'
        f'<span class="meta">{escape(kind)}</span></li>'
    )


def _shell(title: str, description: str, canonical: str, body: str,
           noindex: bool = False) -> str:
    robots = '<meta name="robots" content="noindex,follow">\n' if noindex else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
{robots}<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:locale" content="ko_KR">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADS_CLIENT}"
        crossorigin="anonymous"></script>
<style>{STYLE}</style>
</head>
<body>

<header class="top">
  <a href="/"><span class="mark"></span>histgraph<span class="back">관계망으로 돌아가기</span></a>
</header>

{body}

<footer class="foot">
  <a href="/">histgraph</a><span>·</span><a href="/privacy.html">개인정보처리방침</a><span>·</span><a href="/terms.html">이용약관</a>
</footer>

</body>
</html>
"""


def node_page(api, node_id: str) -> tuple[int, str]:
    """`/n/<id>` 한 장. (상태, 본문)"""
    node = api.node(node_id)
    if node is None:
        return 404, _shell(
            "찾을 수 없는 항목 — histgraph",
            "이 주소에 해당하는 항목이 없습니다.",
            f"{SITE}/n/{quote(node_id, safe='')}",
            '<main><h1>찾을 수 없습니다</h1>'
            '<p class="empty">이 주소에 해당하는 항목이 없습니다. 이름이 바뀌었거나 '
            '다른 항목으로 합쳐졌을 수 있습니다.</p>'
            '<a class="open" href="/">관계망에서 찾아보기</a></main>',
            noindex=True,
        )

    names = node.get("names") or [node["label"]]
    title = names[0]
    also = " · ".join(names[1:])
    kind = NODE_TYPES.get(node["type"], node["type"])
    span = " ~ ".join(x for x in (_year(node.get("start")), _year(node.get("end"))) if x)
    color = GROUP_COLOR.get(node.get("group"), "var(--frame)")
    desc = (node.get("description") or "").strip()

    parts = ["<main>"]
    parts.append(
        f'<h1>{escape(title)}'
        + (f'<span class="also">{escape(also)}</span>' if also else "")
        + "</h1>"
    )
    parts.append(
        f'<p class="kind"><span class="dot" style="background:{color}"></span>'
        f'{escape(kind)}' + (f' · {escape(span)}' if span else "") + "</p>"
    )
    if desc:
        parts.append(f'<p class="desc">{escape(desc)}</p>')
    else:
        parts.append(f'<p class="empty">{escape(_why_empty(node))}</p>')

    aliases = node.get("aliases") or []
    if aliases:
        parts.append(f'<p class="aka">다른 이름 · {escape(" · ".join(aliases))}</p>')

    groups = _groups(node.get("relations") or [])
    total = sum(len(rels) for _, rels in groups)
    if total:
        parts.append(f"<h2>이어진 것 {total}</h2>")
        for head, rels in groups:
            parts.append(f"<h3>{escape(head)}</h3><ul>")
            parts.extend(_link(r["other"]) for r in rels[:GROUP_MAX])
            parts.append("</ul>")
            if len(rels) > GROUP_MAX:
                parts.append(f'<p class="more">외 {len(rels) - GROUP_MAX}개</p>')
    else:
        parts.append('<h2>이어진 것</h2><p class="empty">연결된 관계가 없습니다.</p>')

    parts.append(
        f'<a class="open" href="/#{quote(node["id"], safe="")}">관계망에서 보기 →</a>'
    )
    parts.append("</main>")

    # 설명이 비어 있는 장은 색인에 올리지 않는다. 이름과 목록만 있는 장이
    # 검색 결과에 깔리면 읽을 것이 있는 장까지 같이 묻힌다.
    summary = desc[:150] if desc else f"{title} — {kind}. 이어진 것 {total}."
    return 200, _shell(
        f"{title} — histgraph",
        summary,
        f"{SITE}/n/{quote(node['id'], safe='')}",
        "\n".join(parts),
        noindex=not desc,
    )


# 목록 장이 갈래마다 몇 개씩 세우는지. 사람이 한 화면에서 훑을 수 있는 만큼.
INDEX_EACH = 60

# 목록 장에 세울 갈래와 그 머리말. 시대·직위(frame)는 두지 않는다 —
# '조선'·'영의정' 은 읽을거리가 아니라 다른 항목을 묶는 틀이다.
INDEX_KINDS = [
    ("person", "인물"),
    ("event", "사건"),
    ("heritage", "유물·문화재"),
    ("place", "장소"),
]


def index_page(api) -> tuple[int, str]:
    """`/n/` — 글로 읽는 장들의 어귀.

    관계망은 자바스크립트가 그려서 로봇이 들어올 문이 없다. 이 장이 그
    문이다 — 갈래마다 가장 많이 이어진 것부터 세워, 여기서 각 항목으로,
    항목에서 또 이웃으로 이어진다.
    """
    parts = ["<main>", "<h1>인물과 사건, 장소와 문화재</h1>",
             '<p class="kind">한국사의 개체들이 서로 어떻게 이어져 있는지를 '
             '글과 관계망 두 가지로 봅니다.</p>']
    for kind, head in INDEX_KINDS:
        rows = api.store.conn.execute(
            """SELECT n.id, n.label, n.type,
                      (SELECT COUNT(*) FROM edges e
                        WHERE e.src = n.id OR e.dst = n.id) AS degree
                 FROM nodes n
                WHERE n.type = ? AND COALESCE(n.description,'') <> ''
                ORDER BY degree DESC, n.label
                LIMIT ?""",
            (kind, INDEX_EACH),
        ).fetchall()
        if not rows:
            continue
        parts.append(f"<h2>{escape(head)}</h2><ul>")
        parts.extend(
            _link({"id": r["id"], "label": r["label"], "type": r["type"],
                   "group": _GROUP.get(r["type"], "frame")})
            for r in rows
        )
        parts.append("</ul>")
    parts.append('<a class="open" href="/">관계망에서 보기 →</a>')
    parts.append("</main>")
    return 200, _shell(
        "인물·사건·장소·문화재 — histgraph",
        "한국사의 인물과 사건, 장소와 문화재가 시간 위에서 어떻게 이어지는지 "
        "글과 관계망으로 봅니다.",
        f"{SITE}/n/",
        "\n".join(parts),
    )


def sitemap(api) -> tuple[int, str]:
    """색인에 올릴 주소 목록. **설명이 있는 노드만** 싣는다 — 이름뿐인 장을
    수천 개 올리면 읽을 것이 있는 장이 그 속에 묻힌다."""
    rows = api.store.conn.execute(
        "SELECT id FROM nodes WHERE COALESCE(description,'') <> '' "
        "AND id NOT LIKE '%/%' ORDER BY id"
    ).fetchall()
    urls = [f"{SITE}/", f"{SITE}/n/", f"{SITE}/privacy.html", f"{SITE}/terms.html"]
    urls += [f"{SITE}/n/{quote(r['id'], safe='')}" for r in rows]
    body = "\n".join(f"  <url><loc>{escape(u)}</loc></url>" for u in urls)
    return 200, (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )


def route(api, path: str) -> tuple[int, str, str] | None:
    """이 경로가 문서 페이지인가. (상태, 콘텐츠 타입, 본문) 또는 None.

    로컬(`histgraph serve`)과 배포(`api/index.py`)가 같은 표를 본다. 배포
    쪽은 rewrite 가 `/n/…` 을 `/api/n/…` 으로 바꿔 넘긴다 (vercel.json).
    """
    for prefix in ("/api", ""):
        if path == f"{prefix}/sitemap.xml":
            status, body = sitemap(api)
            return status, "application/xml; charset=utf-8", body
        if path.startswith(f"{prefix}/n/"):
            from urllib.parse import unquote

            node_id = unquote(path[len(f"{prefix}/n/"):]).strip("/")
            status, body = (index_page(api) if not node_id
                            else node_page(api, node_id))
            return status, "text/html; charset=utf-8", body
        if path == f"{prefix}/n":
            status, body = index_page(api)
            return status, "text/html; charset=utf-8", body
    return None
