"""추출 고아(`ex:`) 노드 정리 — 타입 교정과 실제 노드로의 승격.

**문제.** 추출은 그래프에 없는 이름을 만나면 `ex:{타입}:{이름}` 노드를
만든다. 그 노드들이 598개 떠 있고, 두 가지 이유가 섞여 있다.

  1. **표기가 어긋났다.** 우리 라벨은 '조선 세조'인데 산문은 '세조'라고
     쓴다. 같은 인물이 두 노드로 갈라진다.
  2. **애초에 그래프에 없다.** 신규식·이종일·길선주는 Wikidata 국적
     태그가 없어 수집에서 빠졌다. 실측: ex 인물 라벨 중 전체 그래프에
     같은 라벨이 있는 것은 0개였다 — 추측이 아니라 진짜 신규 인물이다.

**해법은 세 단계이고 값싼 순서대로 간다.** 뒤 단계는 앞 단계가 붙이지
못한 것만 처리하므로 네트워크 요청이 최소가 된다.

  retype  타입 오분류 교정 — '조선총독부'가 person 으로 들어와 있다
  local   라벨·왕조접두로 기존 노드에 병합 (네트워크 불필요)
  kowiki  한국어 위키백과 문서명 → QID → `wd:` 노드로 승격

**승격은 병합이다.** ex 노드를 지우고 엣지를 대상 노드로 옮긴다. 옮기지
않고 `same_as` 만 걸면 프론트엔드에는 같은 인물이 여전히 둘로 보인다.

**되돌릴 수 있어야 한다.** 자동 매칭은 틀릴 수 있으므로 병합된 노드는
원래 라벨을 별칭으로 남기고, 대상 노드 props 에 `merged_from` 을 쌓고,
옮겨진 엣지에도 어디서 왔는지 적는다.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from .extract import HANJA_TAIL, kin_title_mismatch, name_variants, orient
from .http import Fetcher
from .ontology import EDGE_TYPES, Node
from .store import GraphStore

log = logging.getLogger(__name__)

EX_PREFIX = "ex:"

# --- 1단계: 타입 교정 -----------------------------------------------------
#
# **ex: 노드에만 적용한다.** Wikidata·국가유산청 노드의 타입은 소스가 P31
# 등으로 준 것이라 접미사 추측으로 뒤집을 근거가 없다. 실제로 그래프에는
# '김정부'라는 인물이 있다 — '정부'로 끝난다고 조직으로 바꾸면 사람이
# 사라진다.
#
# 규칙은 전부 **라벨 끝**에 걸거나 **라벨 전체**와 일치시킨다. 가운데를
# 보면 '간도 일본 영사관 습격'(사건)이 영사관 때문에 조직이 된다.
#
# '정부'는 접미사로 쓰지 않고 관청 이름을 나열한다 — 그래프에 '김정부'
# 라는 인물이 실제로 있다. 접미사 규칙이 틀려도 승격 단계가 Wikidata
# 클래스로 타입을 다시 확인하므로 잘못된 병합까지는 가지 않지만,
# 고아 노드의 타입은 그대로 틀린 채 남는다.
ORG_PATTERN = re.compile(
    r"(총독부|통감부|도독부|임시정부|신정부|공사관|영사관|대목구|학회|협회|"
    r"위원회|사령부|문중|일파|당파|\d+인|[가-힣]{2,}(?:회|단|군단|의군|농민군))$"
    # 나라 이름과 붕당은 접미사로 잡히지 않는다. 목록으로 둔다 —
    # '나라$' 같은 규칙은 '나의 나라'(드라마)까지 끌고 온다.
    r"|^(명나라|청나라|왜국|일본|프랑스|미국|영국|러시아|천주교|"
    r"대북|소윤|대윤|벽파|시파)$"
)

# 관직·칭호. '평안감사'는 자리 이름이지 사람 이름이 아니다.
# 주의: 이름이 앞에 붙은 '응교 최숙생'은 끝이 관직이 아니라서 걸리지
# 않는다 — 그게 맞다. 반대로 '인목대비'·'숙명공주'는 특정 인물이므로
# 칭호 단독일 때만(^...$) 직위로 본다.
ROLE_PATTERN = re.compile(
    r"(판서|참판|참의|참지|감사|병사|수사|절도사|절제사|관찰사|목사|부사|"
    r"부윤|현감|군수|영장|도통사|대원수|도총|제학|좌찬성|우참찬|선봉장|"
    r"분대장|대관|전권대사|독판|국무총리|국무령|대통령|주석)$"
    r"|^(대비|대왕대비|왕대비|세자|세자빈|원자|공주|옹주|귀인|중전|왕비|"
    r"승려|내관|여종|부관|참모|고문관)$"
)


def classify(label: str) -> str | None:
    """라벨이 명백히 조직·직위면 그 타입, 아니면 None.

    직위를 먼저 본다. '대한민국 임시정부 대통령'처럼 두 규칙이 함께
    걸릴 수 있는 라벨은 자리 이름이 더 구체적인 답이다."""
    if ROLE_PATTERN.search(label):
        return "role"
    if ORG_PATTERN.search(label):
        return "org"
    return None


def retype(store: GraphStore, dry_run: bool = False) -> dict[str, object]:
    """ex 노드의 타입 오분류를 고친다.

    타입이 id 에 들어 있으므로(`ex:person:조선총독부`) id 도 함께 바뀐다.
    엣지·별칭을 옮기는 일은 병합과 똑같아서 `merge_node` 를 그대로 쓴다."""
    plan: list[tuple[str, str, str, str]] = []  # (old_id, new_id, label, new_type)
    for row in store.conn.execute(
        "SELECT id, type, label FROM nodes WHERE id LIKE ?", (EX_PREFIX + "%",)
    ):
        want = classify(row["label"])
        if not want or want == row["type"]:
            continue
        plan.append((row["id"], f"{EX_PREFIX}{want}:{row['label']}", row["label"], want))

    if dry_run:
        return {"retyped": 0, "plan": plan}

    for old_id, new_id, label, new_type in plan:
        exists = store.conn.execute(
            "SELECT 1 FROM nodes WHERE id = ?", (new_id,)
        ).fetchone()
        if not exists:
            store.upsert_nodes([
                Node(id=new_id, type=new_type, label=label, source="extract",
                     props={"retyped_from": old_id})
            ])
        merge_node(store, old_id, new_id, method="retype")

    store.conn.commit()
    log.info("타입 교정 %d건", len(plan))
    return {"retyped": len(plan), "plan": plan}


# --- 병합 원시연산 --------------------------------------------------------

_EDGE_COLS = (
    "src", "dst", "type", "source", "label", "start_date", "end_date",
    "confidence", "props",
)


def _rewrite_edges(
    conn,
    old_id: str,
    new_id: str,
    sources: tuple[str, ...] | None = None,
    tag: str = "merged_from",
) -> dict[str, int]:
    """`old_id` 에 걸린 엣지를 `new_id` 로 옮긴다.

    **INSERT OR IGNORE 후 삭제**한다. 대상에 같은 엣지가 이미 있으면
    그쪽을 남긴다 — 구조화 소스가 준 confidence 1.0 짜리를 추출 엣지
    (0.9)로 덮어쓰면 신뢰도가 거꾸로 내려간다.

    양끝이 같은 노드가 되는 엣지는 버린다. 자기순환은 그래프에서 의미가
    없고 화면에도 그릴 수 없다.

    `sources` 를 주면 그 출처의 엣지만 옮긴다 — 노드를 통째로 합치는
    것과 '이 사실만 다른 노드의 것이었다'는 다른 일이다."""
    where = "(src = ?1 OR dst = ?1)"
    params: list[object] = [old_id]
    if sources:
        where += f" AND source IN ({','.join('?' * len(sources))})"
        params.extend(sources)

    rows = conn.execute(f"SELECT * FROM edges WHERE {where}", params).fetchall()
    moved, self_loops = [], 0
    for r in rows:
        src = new_id if r["src"] == old_id else r["src"]
        dst = new_id if r["dst"] == old_id else r["dst"]
        if src == dst:
            self_loops += 1
            continue
        props = json.loads(r["props"] or "{}")
        props[tag] = old_id
        moved.append((
            src, dst, r["type"], r["source"], r["label"], r["start_date"],
            r["end_date"], r["confidence"], json.dumps(props, ensure_ascii=False),
        ))

    marks = ",".join("?" * len(_EDGE_COLS))
    conn.executemany(
        f"INSERT OR IGNORE INTO edges ({','.join(_EDGE_COLS)}) VALUES ({marks})",
        moved,
    )
    conn.execute(f"DELETE FROM edges WHERE {where}", params)
    return {"edges": len(moved), "self_loops": self_loops}


def merge_node(
    store: GraphStore, old_id: str, new_id: str, method: str, score: float = 1.0
) -> dict[str, int]:
    """`old_id` 를 `new_id` 로 합치고 old 를 지운다."""
    conn = store.conn
    old_row = conn.execute("SELECT label FROM nodes WHERE id = ?", (old_id,)).fetchone()
    if old_row is None:
        return {"edges": 0, "self_loops": 0}

    stats = _rewrite_edges(conn, old_id, new_id)

    # 별칭은 노드 삭제 시 CASCADE 로 사라지므로 먼저 옮긴다.
    conn.execute(
        "UPDATE OR IGNORE aliases SET node_id = ? WHERE node_id = ?", (new_id, old_id)
    )
    new_label = conn.execute(
        "SELECT label FROM nodes WHERE id = ?", (new_id,)
    ).fetchone()
    if new_label and old_row["label"] != new_label["label"]:
        # 산문에 나온 표기를 별칭으로 남겨야 다음 추출이 같은 노드를 찾는다
        conn.execute(
            "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)",
            (new_id, old_row["label"]),
        )

    for col in ("a", "b"):
        conn.execute(
            f"UPDATE OR IGNORE same_as SET {col} = ? WHERE {col} = ?", (new_id, old_id)
        )
    conn.execute("DELETE FROM same_as WHERE a = ? OR b = ? OR a = b", (old_id, old_id))

    _record_provenance(conn, new_id, old_id, old_row["label"], method, score)
    conn.execute("DELETE FROM nodes WHERE id = ?", (old_id,))
    return stats


def _record_provenance(
    conn, new_id: str, old_id: str, old_label: str, method: str, score: float
) -> None:
    """대상 노드 props 에 병합 이력을 쌓는다.

    자동 매칭은 틀릴 수 있다. 무엇이 어떤 근거로 합쳐졌는지 남기지 않으면
    나중에 검증도 되돌리기도 못 한다."""
    row = conn.execute("SELECT props FROM nodes WHERE id = ?", (new_id,)).fetchone()
    if row is None:
        return
    props = json.loads(row["props"] or "{}")
    history = props.setdefault("merged_from", [])
    entry = {"id": old_id, "label": old_label, "method": method, "score": score}
    if entry not in history:
        history.append(entry)
    conn.execute(
        "UPDATE nodes SET props = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(props, ensure_ascii=False), new_id),
    )


def relax_invalid_edges(store: GraphStore) -> dict[str, int]:
    """타입이 바뀌면서 스키마와 어긋난 엣지를 정리한다.

    '병조판서'를 person 에서 role 로 고치면 그 노드에 걸린 `child_of`
    (person→person)는 스키마 위반이 된다. 버리지 않는다 — 방향을 뒤집어
    맞으면 뒤집고, 안 되면 `related_to` 로 낮추고 원래 타입을 props 에
    남긴다. 사실 자체는 산문에 근거가 있으므로 지울 이유가 없다."""
    conn = store.conn
    types = {r["id"]: r["type"] for r in conn.execute("SELECT id, type FROM nodes")}

    flipped = relaxed = 0
    for r in conn.execute("SELECT * FROM edges").fetchall():
        st, dt = types.get(r["src"]), types.get(r["dst"])
        if st is None or dt is None:  # 댕글링은 store.stats 가 따로 센다
            continue
        _, allowed_src, allowed_dst = EDGE_TYPES[r["type"]]
        if st in allowed_src and dt in allowed_dst:
            continue

        ok, flip = orient(r["type"], st, dt)
        props = json.loads(r["props"] or "{}")
        if ok and flip:
            new = (r["dst"], r["src"], r["type"])
            props["flipped"] = True
            flipped += 1
        else:
            new = (r["src"], r["dst"], "related_to")
            props["original_type"] = r["type"]
            relaxed += 1
        conn.execute(
            f"INSERT OR IGNORE INTO edges ({','.join(_EDGE_COLS)}) "
            f"VALUES ({','.join('?' * len(_EDGE_COLS))})",
            (*new, r["source"], r["label"], r["start_date"], r["end_date"],
             r["confidence"], json.dumps(props, ensure_ascii=False)),
        )
        conn.execute(
            "DELETE FROM edges WHERE src=? AND dst=? AND type=? AND source=?",
            (r["src"], r["dst"], r["type"], r["source"]),
        )

    conn.commit()
    if flipped or relaxed:
        log.info("스키마 정리: 방향교정 %d건 · related_to 완화 %d건", flipped, relaxed)
    return {"flipped": flipped, "relaxed": relaxed}


# --- 2단계: 그래프 안에서 찾기 (네트워크 불필요) --------------------------

# 왕 이름은 산문에서 왕조 없이 쓴다 ('세조'), 우리 라벨은 붙여 쓴다
# ('조선 세조'). 접두사를 붙여 맞춰본다.
DYNASTIES = ("조선", "고려", "신라", "백제", "고구려", "대한제국", "발해")


def add_bare_name_aliases(store: GraphStore) -> int:
    """'조선 정종' 에게 별칭 '정종' 을 달아준다.

    우리 라벨은 왕조를 붙여 쓰지만 산문은 그냥 '정종'이라고 쓴다. 별칭이
    없으면 추출이 그 이름으로 이 노드를 찾지 못하고, 하필 라벨이 정확히
    '정종'인 다른 인물이 있으면 그쪽에 사실이 붙는다 (실측: 태조의 아들
    관계가 엣지 1개짜리 동명 노드에 붙었다).

    검색에도 같이 듣는다 — `search` 가 별칭을 함께 보기 때문이다."""
    rows = store.conn.execute(
        "SELECT id, label FROM nodes WHERE type = 'person' AND source = 'wd'"
    ).fetchall()
    add = []
    for r in rows:
        head, _, bare = r["label"].partition(" ")
        # '조선 세종' 처럼 왕조 + 이름 꼴일 때만. '이순신 장군' 같은 건
        # 앞이 왕조가 아니므로 걸리지 않는다.
        if head in DYNASTIES and len(bare) >= 2:
            add.append((r["id"], bare))
    store.conn.executemany(
        "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)", add
    )
    store.conn.commit()
    log.info("왕조 접두를 뗀 별칭 %d개 추가", len(add))
    return len(add)


def local_matches(store: GraphStore, ex_ids: list[str] | None = None) -> list[dict]:
    """네트워크 없이 붙일 수 있는 것들.

    **타입이 같을 때만 잇는다.** '고종'은 인물이지만 그래프에는
    `kr:period:조선 고종`(시대)이 있다 — 타입을 안 보면 인물이 시대에
    합쳐진다.

    **후보가 둘 이상이면 잇지 않는다.** '숙종'은 조선에도 고려에도 있다.
    자동으로 고르면 절반은 틀린다.

    **별칭도 라벨과 같은 무게로 본다.** 추출은 이름을 찾을 때 별칭을
    보지만 그건 **추출이 돌던 그 순간의** 별칭표다. 자료는 순서대로 오지
    않는다 — `정여립의 난` 은 8월 30일에 추출됐고, 그 이름이 기축옥사
    (wd:Q7836645)의 별칭이라는 사실은 9월 3일 `aliases` 가 처음 돌면서
    들어왔다. 며칠 차이로 화면에서 정여립의 난에 **정여립이 없었다** —
    엣지 하나짜리 빈 노드가 떴고, 인물과 연대를 다 가진 진짜 사건은
    기축옥사라는 다른 이름으로 옆에 따로 서 있었다.

    사건은 이 길밖에 없다. `kowiki_matches` 는 사건에 대해 넘겨주기를
    일부러 안 따라가고(하위 항목이 상위 항목에 흡수된다), 정여립의 난은
    위키백과에서 기축옥사로 넘겨주기다. 두 문이 다 닫혀 있었다.
    """
    by_label: dict[str, list[dict]] = {}
    for r in store.conn.execute(
        "SELECT id, type, label FROM nodes WHERE id NOT LIKE ?", (EX_PREFIX + "%",)
    ):
        by_label.setdefault(r["label"], []).append(dict(r))

    by_alias: dict[str, list[dict]] = {}
    for r in store.conn.execute(
        """SELECT a.alias, n.id, n.type, n.label, n.start_date, n.end_date
             FROM aliases a JOIN nodes n ON n.id = a.node_id
            WHERE n.id NOT LIKE ?""",
        (EX_PREFIX + "%",),
    ):
        by_alias.setdefault(r["alias"], []).append(dict(r))

    sql = "SELECT id, type, label FROM nodes WHERE id LIKE ?"
    rows = store.conn.execute(sql, (EX_PREFIX + "%",)).fetchall()
    if ex_ids is not None:
        keep = set(ex_ids)
        rows = [r for r in rows if r["id"] in keep]

    out: list[dict] = []
    for r in rows:
        same_type = [c for c in by_label.get(r["label"], []) if c["type"] == r["type"]]
        if len(same_type) == 1:
            out.append({"ex_id": r["id"], "target": same_type[0]["id"],
                        "label": r["label"], "method": "label_exact", "score": 0.95})
            continue
        if same_type:
            continue  # 동명이인 — 자동으로 고르지 않는다

        prefixed = [
            c
            for d in DYNASTIES
            for c in by_label.get(f"{d} {r['label']}", [])
            if c["type"] == r["type"]
        ]
        if len(prefixed) == 1:
            out.append({"ex_id": r["id"], "target": prefixed[0]["id"],
                        "label": r["label"], "method": "dynasty_prefix", "score": 0.9})
            continue

        # 이 이름으로 불리는 노드가 **딱 하나**일 때만. 별칭은 라벨보다
        # 붐빈다 — `add_bare_name_aliases` 가 '조선 정종'·'고려 정종'
        # 양쪽에 '정종'을 달아두므로 왕의 휘는 여기서 후보 둘이 되어
        # 저절로 걸러진다.
        #
        # 라벨이 정확히 같은 후보가 있었으면 여기까지 오지 않는다 —
        # 위에서 이미 잇거나(하나) 포기했다(동명이인). 별칭이 남의 라벨을
        # 밀어내는 일은 없다.
        aliased = [c for c in by_alias.get(r["label"], []) if c["type"] == r["type"]]
        if len(aliased) == 1:
            target = aliased[0]
            # 이름이 같아도 시대가 어긋나면 다른 것이다 — `kowiki_matches`
            # 가 승격 전에 하는 검사를 여기서도 한다.
            if plausible_period(
                life_span(target["start_date"], target["end_date"]),
                neighbor_years(store, r["id"]),
            ):
                out.append({"ex_id": r["id"], "target": target["id"],
                            "label": r["label"], "method": "alias_exact",
                            "score": 0.95})
                continue

        # **`same_as` 가 이미 '같은 실체'라고 말했으면 그리로 합친다.**
        # 연표가 `ex:period:1871년` 을 `time:1871` 에 이어둔 것이 그 예다.
        # 두 노드가 화면에 따로 떠 있을 이유가 없다 — 판정은 이미 났고
        # 우리는 그걸 반영하지 않고 있었을 뿐이다.
        same_as_targets = [
            row["id"]
            for row in store.conn.execute(
                """SELECT n.id FROM same_as s
                     JOIN nodes n
                       ON n.id = CASE WHEN s.a = ?1 THEN s.b ELSE s.a END
                    WHERE (s.a = ?1 OR s.b = ?1)
                      AND n.type = ?2 AND n.id NOT LIKE ?3""",
                (r["id"], r["type"], EX_PREFIX + "%"),
            )
        ]
        if len(same_as_targets) == 1:
            out.append({"ex_id": r["id"], "target": same_as_targets[0],
                        "label": r["label"], "method": "same_as", "score": 0.95})
    return out


# 한시 제목은 갈래 접두·접미가 붙었다 빠졌다 한다. `등만월대회고`
# (登滿月臺懷古)와 `만월대 회고시`(滿月臺懷古詩)는 같은 시인데 라벨이 달라
# 두 노드가 됐다 — 황진이 상세에 작품이 9편으로 부풀어 있었다. 한 문서
# 안에서 두 문장이 같은 작품을 달리 부르면 그대로 두 개가 된다.
#
# **작품 타입에, 같은 창작자 안에서만 적용한다.** 문자열이 비슷하다는
# 이유로 합치면 절반이 틀린다 — 실측 후보 26쌍에 `제1차 요동 정벌`/`제2차
# 요동 정벌`, `단종 복위 사건 (1456년)`/`(1457년)`, `부산항의 개항`/`원산항의
# 개항`, `동아일보사 부사장`/`동아일보사 주필` 이 섞여 있었다. 접두·접미만
# 벗겨 **정확히 같아질 때**만 잇는다 (실측: 두 DB 전체에서 1쌍, 오탐 0).
TITLE_NOISE = re.compile(r"[《》〈〉「」『』\s]")
TITLE_PREFIX = re.compile(r"^[등영제]")  # 登(오르다)·詠/咏(읊다)·題(제하다)
TITLE_SUFFIX = re.compile(r"[시가]$")  # 詩·歌
TITLE_MIN_CORE = 4  # 이보다 짧으면 우연히 같아진다


def title_core(label: str) -> str:
    """한시 제목에서 갈래 접두·접미를 벗긴 핵심."""
    core = TITLE_NOISE.sub("", HANJA_TAIL.sub("", label))
    return TITLE_SUFFIX.sub("", TITLE_PREFIX.sub("", core))


def title_variant_matches(store: GraphStore) -> list[dict]:
    """같은 작품이 표기만 달라 두 노드가 된 것들."""
    by_creator: dict[str, dict[str, dict]] = {}
    for r in store.conn.execute(
        """SELECT e.src, e.dst, n.label
             FROM edges e JOIN nodes n ON n.id = e.dst
            WHERE e.type = 'created' AND n.type = 'artwork'
              AND n.id LIKE ?""",
        (EX_PREFIX + "%",),
    ):
        by_creator.setdefault(r["src"], {})[r["dst"]] = dict(r)

    def rank(item: dict) -> tuple[int, int, str]:
        """남길 쪽 고르기 — 연결이 많은 것, 그다음 표기가 온전한 것."""
        degree = store.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE src = ?1 OR dst = ?1", (item["dst"],)
        ).fetchone()[0]
        return (degree, len(item["label"]), item["dst"])

    plan: list[dict] = []
    for items in by_creator.values():
        groups: dict[str, list[dict]] = {}
        for item in items.values():
            core = title_core(item["label"])
            if len(core) >= TITLE_MIN_CORE:
                groups.setdefault(core, []).append(item)
        for core, members in groups.items():
            if len(members) < 2:
                continue
            keep = max(members, key=rank)
            for m in members:
                if m["dst"] == keep["dst"]:
                    continue
                plan.append({
                    "ex_id": m["dst"], "target": keep["dst"], "label": m["label"],
                    "target_label": keep["label"], "core": core,
                    "method": "title_variant", "score": 0.9,
                })
    return plan


# --- 3단계: 한국어 위키백과 문서명 -> QID ---------------------------------

TITLE_BATCH = 50  # action=query 의 titles 상한 (비봇 계정)

# P31/P279* 로 확인할 상위 클래스. 노드 타입을 **추측하지 않고** Wikidata
# 계층에 직접 물어본다 — prune_sports_by_class 와 같은 방식이다.
CATEGORY_TO_TYPE: dict[str, str] = {
    "Q5": "person",
    "Q1656682": "event",
    "Q43229": "org",
    "Q6256": "org",
    "Q7275": "org",
    "Q2221906": "place",
    "Q4164871": "role",
    "Q11514315": "period",
    "Q838948": "artwork",
    "Q11424": "media",
}

# 라벨이 이 꼴이면 위키백과에 물어볼 것도 없다. 요청만 낭비된다.
_JUNK = re.compile(r"^\s*$|[|#\[\]{}<>]|\(\s*\d*\s*\)")

# 동명이인 방어. 이웃 노드의 연대와 이만큼 넘게 어긋나면 다른 사람이다.
# 넉넉하게 잡는다 — 사건 노드에 연대가 없는 경우가 많아 근거 자체가
# 드물고, 애매한 것을 막기보다 명백한 것만 막는 편이 안전하다.
ANACHRONISM_TOLERANCE = 150


def life_span(birth: str | None, death: str | None) -> tuple[int, int] | None:
    """생몰년에서 활동 구간. 한쪽만 있으면 80년으로 채운다."""
    from .timeline import _year_of

    b, d = _year_of(birth), _year_of(death)
    if b is None and d is None:
        return None
    if b is None:
        b = d - 80  # type: ignore[operator]
    if d is None:
        d = b + 80
    return (b, d)


def plausible_period(
    span: tuple[int, int] | None,
    years: list[int],
    tolerance: int = ANACHRONISM_TOLERANCE,
) -> bool:
    """생몰년이 이웃 노드들의 연대와 겹치는가.

    **실측으로 필요해진 검사다.** 무오사화 문서에서 나온 '한유'를 문서명만
    보고 승격하면 당나라 문인 韓愈(768~824)에 붙는다 — 이웃인 김종직
    (1431~1491)과 600년이 어긋난다. 이름만으로는 동명이인을 구분할 수
    없으므로 연대를 본다.

    근거가 없으면(생몰년이 없거나 이웃에 연대가 없으면) 막지 않는다.
    모르는 것을 틀렸다고 판정하면 멀쩡한 승격이 사라진다."""
    if span is None or not years:
        return True
    lo, hi = span
    return any(lo - tolerance <= y <= hi + tolerance for y in years)


def neighbor_years(store: GraphStore, node_id: str) -> list[int]:
    """이 노드에 직접 연결된 노드들의 연대.

    추출 엣지는 어느 문서에서 나왔는지(`extracted_from`)를 남긴다.
    그 문서 노드의 연대도 같은 무게로 쓴다 — 인물이 등장한 글의 시대가
    곧 그 인물의 시대다."""
    from .timeline import _year_of

    years: list[int] = []
    seen: set[str] = set()
    rows = store.conn.execute(
        "SELECT src, dst, props FROM edges WHERE src = ? OR dst = ?",
        (node_id, node_id),
    ).fetchall()
    for r in rows:
        other = r["dst"] if r["src"] == node_id else r["src"]
        seen.add(other)
        doc = json.loads(r["props"] or "{}").get("extracted_from")
        if isinstance(doc, str):
            seen.add(doc)

    for nid in seen:
        row = store.conn.execute(
            "SELECT start_date, end_date, props FROM nodes WHERE id = ?", (nid,)
        ).fetchone()
        if row is None:
            continue
        for value in (_year_of(row["start_date"]), _year_of(row["end_date"])):
            if value is not None:
                years.append(value)
        year = json.loads(row["props"] or "{}").get("canonical_year")
        if isinstance(year, int):
            years.append(year)
    return years


def fetch_qids(
    fetcher: Fetcher, labels: list[str], follow_redirects: bool = True
) -> tuple[dict[str, str], list[str]]:
    """문서명 -> QID. (찾은 것, 동음이의로 건너뛴 것).

    **동음이의 문서는 반드시 걸러야 한다.** '선조' 같은 라벨은 목록
    문서로 이어지는데, 그 QID 로 승격하면 인물 엣지가 '동음이의 문서'
    노드에 붙는다 — 조용히 틀린 그래프가 된다.

    `follow_redirects` 는 사건에만 끈다. 인물의 넘겨주기는 이름 이표기
    ('리델' → '펠릭스클레르 리델')라 따라가는 게 맞지만, 사건의 넘겨주기는
    대개 하위 항목이 상위 항목을 가리키는 것이다 ('곽산 학살 사건' →
    '3·1 운동'). 따라가면 개별 사건이 큰 사건에 흡수돼 해상도가 사라진다."""
    from .sources.wikipedia import API_URL, _api

    found: dict[str, str] = {}
    ambiguous: list[str] = []
    clean = [t for t in labels if not _JUNK.search(t) and len(t) >= 2]

    for i in range(0, len(clean), TITLE_BATCH):
        batch = clean[i : i + TITLE_BATCH]
        params = {
            "action": "query",
            "prop": "pageprops",
            "ppprop": "wikibase_item|disambiguation",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(batch),
        }
        if follow_redirects:
            params["redirects"] = "1"
        try:
            data = _api(fetcher, params)
        except RuntimeError as err:
            log.warning("QID 조회 실패 (건너뜀): %s", err)
            continue

        query = data.get("query", {})
        # redirects 를 따라가면 응답 title 이 요청 title 과 달라진다.
        # 어느 이름으로 물었는지 되짚어야 ex 노드와 짝지을 수 있다.
        back = {r["to"]: r["from"] for r in query.get("redirects", [])}
        norm = {r["to"]: r["from"] for r in query.get("normalized", [])}
        for page in query.get("pages", []):
            title = page["title"]
            requested = back.get(title, title)
            requested = norm.get(requested, requested)
            if page.get("missing"):
                continue
            props = page.get("pageprops", {})
            if "disambiguation" in props:
                ambiguous.append(requested)
                continue
            qid = props.get("wikibase_item")
            if qid:
                found[requested] = qid

    log.info(
        "위키백과 조회: 문서명 %d개 중 QID %d개 (동음이의 %d개 제외)",
        len(clean), len(found), len(ambiguous),
    )
    return found, ambiguous


def fetch_entity_info(
    fetcher: Fetcher, qids: list[str], chunk: int = 150
) -> dict[str, dict]:
    """QID -> {types, label, birth, death}.

    타입 확인과 노드 생성에 필요한 정보를 한 번에 받는다. 클래스는
    P31/P279* 로 상위 개념까지 따라간다 — '조선총독부'의 P31 은
    '정부기관'이라 P31 만 보면 조직으로 안 잡힌다."""
    from .sources.wikidata import _iso_date, _qid, _safe_query, _val

    info: dict[str, dict] = {}
    failures: list[str] = []
    ordered = sorted(set(qids))
    cats = " ".join(f"wd:{q}" for q in CATEGORY_TO_TYPE)

    for i in range(0, len(ordered), chunk):
        values = " ".join(f"wd:{q}" for q in ordered[i : i + chunk])

        for row in _safe_query(
            fetcher,
            f"""SELECT ?item ?cat WHERE {{
                  VALUES ?item {{ {values} }}
                  VALUES ?cat {{ {cats} }}
                  ?item wdt:P31/wdt:P279* ?cat .
                }}""",
            f"승격/클래스/{i}",
            failures,
        ):
            qid, cat = _qid(_val(row, "item") or ""), _qid(_val(row, "cat") or "")
            if cat in CATEGORY_TO_TYPE:
                info.setdefault(qid, {"types": set()})["types"].add(
                    CATEGORY_TO_TYPE[cat]
                )

        for row in _safe_query(
            fetcher,
            f"""SELECT ?item ?itemLabel ?birth ?death WHERE {{
                  VALUES ?item {{ {values} }}
                  OPTIONAL {{ ?item wdt:P569 ?birth }}
                  OPTIONAL {{ ?item wdt:P570 ?death }}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ko,en". }}
                }}""",
            f"승격/라벨/{i}",
            failures,
        ):
            qid = _qid(_val(row, "item") or "")
            entry = info.setdefault(qid, {"types": set()})
            entry.setdefault("label", _val(row, "itemLabel"))
            entry.setdefault("birth", _iso_date(_val(row, "birth")))
            entry.setdefault("death", _iso_date(_val(row, "death")))

    if failures:
        log.warning("엔티티 확인 실패 %d구간 — 해당 노드는 승격되지 않음", len(failures))
    return info


def kowiki_matches(
    store: GraphStore, fetcher: Fetcher, ex_rows: list[dict]
) -> tuple[list[dict], dict[str, int]]:
    """ex 노드를 위키백과 경유로 `wd:` QID 에 짝짓는다.

    **타입이 맞아야 승격한다.** '조선총독부'가 person 으로 들어와 있어도
    Wikidata 는 조직이라고 말한다. 타입이 어긋나면 잇지 않는다 — 사람
    노드에 조직의 생몰년이 붙는 쪽이 고아로 두는 것보다 나쁘다."""
    # 연도는 `timeline` 이 정본이다. '1871년'을 위키백과에 물어봐야
    # 서기 1871년 문서가 나올 뿐이고, 우리에겐 이미 `time:1871` 이 있다.
    ex_rows = [r for r in ex_rows if r["type"] != "period"]
    labels = [r["label"] for r in ex_rows]
    # 사건만 넘겨주기를 따라가지 않는다 (하위 항목이 상위 항목에 흡수된다)
    events = [r["label"] for r in ex_rows if r["type"] == "event"]
    others = [r["label"] for r in ex_rows if r["type"] != "event"]

    qid_by_label, ambiguous = fetch_qids(fetcher, others)
    event_qids, event_ambiguous = fetch_qids(fetcher, events, follow_redirects=False)
    qid_by_label.update(event_qids)
    ambiguous.extend(event_ambiguous)
    if not qid_by_label:
        return [], {"ambiguous": len(ambiguous), "no_article": len(labels),
                    "type_mismatch": 0}

    info = fetch_entity_info(fetcher, list(qid_by_label.values()))

    plan: list[dict] = []
    skipped = {"ambiguous": len(ambiguous), "no_article": 0, "type_mismatch": 0,
               "unverified": 0, "anachronism": 0}
    for r in ex_rows:
        qid = qid_by_label.get(r["label"])
        if not qid:
            skipped["no_article"] += 1
            continue
        entry = info.get(qid)
        if not entry or not entry.get("types"):
            # 클래스를 확인 못 한 것을 그냥 붙이면 검증 없는 승격이 된다
            skipped["unverified"] += 1
            continue
        if r["type"] not in entry["types"]:
            skipped["type_mismatch"] += 1
            log.debug(
                "타입 불일치 (건너뜀): %s(%s) -> %s%s",
                r["label"], r["type"], qid, sorted(entry["types"]),
            )
            continue
        span = life_span(entry.get("birth"), entry.get("death"))
        if not plausible_period(span, neighbor_years(store, r["id"])):
            skipped["anachronism"] += 1
            log.info(
                "연대 불일치 (건너뜀): %s -> %s %s — 동명이인으로 보임",
                r["label"], qid, span,
            )
            continue
        plan.append({
            "ex_id": r["id"], "target": f"wd:{qid}", "label": r["label"],
            "method": "kowiki_sitelink", "score": 0.9, "info": entry,
        })
    return plan, skipped


def _ensure_target(store: GraphStore, item: dict, node_type: str) -> None:
    """승격 대상 `wd:` 노드가 없으면 만든다.

    이미 있으면 건드리지 않는다 — 수집으로 채워둔 라벨·설명을 위키백과
    표기로 덮어쓸 이유가 없다."""
    target = item["target"]
    if store.conn.execute("SELECT 1 FROM nodes WHERE id = ?", (target,)).fetchone():
        return
    info = item.get("info") or {}
    qid = target.split(":", 1)[1]
    store.upsert_nodes([
        Node(
            id=target,
            type=node_type,
            label=info.get("label") or item["label"],
            source="wd",
            start_date=info.get("birth"),
            end_date=info.get("death"),
            url=f"https://www.wikidata.org/entity/{qid}",
            props={
                "kowiki_url": "https://ko.wikipedia.org/wiki/"
                + urllib.parse.quote(item["label"]),
                "promoted": True,
            },
        )
    ])


def promote(
    store: GraphStore,
    fetcher: Fetcher | None = None,
    types: tuple[str, ...] = ("person", "event", "org", "place", "role", "period"),
    limit: int | None = None,
    local_only: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """ex 고아 노드를 실제 노드로 병합한다. 값싼 단계부터 순서대로."""
    marks = ",".join("?" * len(types))
    rows = [
        dict(r)
        for r in store.conn.execute(
            f"SELECT id, type, label FROM nodes "
            f"WHERE id LIKE ? AND type IN ({marks})",
            (EX_PREFIX + "%", *types),
        )
    ]
    if limit:
        rows = rows[:limit]

    plan = local_matches(store, [r["id"] for r in rows])
    matched = {p["ex_id"] for p in plan}

    remaining = [r for r in rows if r["id"] not in matched]
    skipped: dict[str, int] = {}
    if remaining and not local_only:
        fetcher = fetcher or Fetcher(store.path.parent / "cache", min_interval=1.0)
        wiki_plan, skipped = kowiki_matches(store, fetcher, remaining)
        plan.extend(wiki_plan)

    result: dict[str, object] = {
        "candidates": len(rows),
        "planned": len(plan),
        "by_method": {},
        "skipped": skipped,
        "plan": plan,
    }
    for p in plan:
        result["by_method"][p["method"]] = result["by_method"].get(p["method"], 0) + 1
    if dry_run:
        return result

    node_types = {r["id"]: r["type"] for r in rows}
    merged = edges = self_loops = 0
    created: list[str] = []
    for item in plan:
        existed = store.conn.execute(
            "SELECT 1 FROM nodes WHERE id = ?", (item["target"],)
        ).fetchone()
        _ensure_target(store, item, node_types[item["ex_id"]])
        if not existed:
            created.append(item["target"])
        stats = merge_node(
            store, item["ex_id"], item["target"], item["method"], item["score"]
        )
        merged += 1
        edges += stats["edges"]
        self_loops += stats["self_loops"]
    store.conn.commit()

    result.update({
        "merged": merged, "edges_moved": edges, "self_loops": self_loops,
        "created": created,
    })
    log.info("승격 %d건 · 엣지 이동 %d건 · 자기순환 %d건 제거", merged, edges, self_loops)
    return result


# --- 이름이 엉뚱한 노드에 붙은 엣지 고치기 -------------------------------
#
# 추출만이 **이름으로** 노드를 찾는다. 나머지 소스는 QID·유물번호가 키라
# 엉뚱한 데 붙을 수가 없다. 그래서 감사 대상은 추출 엣지뿐이다.
REPAIR_SOURCE = "extract"

# 차수만으로 옮겨도 되는 기준. 엣지 1개짜리가 25건짜리 동명 노드 옆에
# 있으면 산문이 말한 것은 후자다. 5배는 그 '명백함'의 하한이다.
DEGREE_DOMINANCE = 5
DEGREE_STUB = 2


def _era_of_node(node: dict) -> str | None:
    """이 노드가 어느 시대 것인가.

    라벨 접두가 가장 강한 신호다 — '조선 태조'와 '고려 태조'는 이름표에
    이미 답이 적혀 있다. 없으면 수집 때 적어둔 국적(P27)을 본다."""
    label = node["label"]
    head, _, rest = label.partition(" ")
    if head in DYNASTIES and rest:
        return head
    props = json.loads(node["props"] or "{}")
    polity = props.get("polity")
    return polity if isinstance(polity, str) else None


def _doc_era(nodes: dict[str, dict], doc_id: str | None) -> str | None:
    """이 관계가 어느 문서에서 나왔고, 그 문서는 어느 시대인가.

    추출 엣지는 출처 문서를 `props.extracted_from` 에 남긴다. 갑자사화
    문서에서 나온 '태조'는 조선 태조지 고려 태조가 아니다 — 전체
    그래프만 보면 알 수 없고, 이 한 줄이 있어야 판정할 수 있다."""
    doc = nodes.get(doc_id or "")
    if doc is None:
        return None
    props = json.loads(doc["props"] or "{}")
    era = props.get("seed_era") or props.get("polity")
    if isinstance(era, str):
        return era
    return _era_of_node(doc)


def audit_links(store: GraphStore) -> dict[str, object]:
    """추출 엣지의 끝점이 옳은 노드인지 **전수 조사**한다.

    같은 이름을 가진 노드가 여럿일 때만 문제가 된다. 셋 중 하나로 나뉜다:

      옳음    지금 붙은 노드가 후보 중 가장 잘 연결돼 있다
      옮김    시대가 맞는 후보가 하나뿐이거나, 차수가 압도적으로 크다
      보류    진짜 동명이인 — 김규식·이광수처럼 사람이 정말 여럿이다

    보류를 자동으로 옮기지 않는 것이 이 함수의 요점이다."""
    conn = store.conn
    nodes = {
        r["id"]: dict(r)
        for r in conn.execute("SELECT id, label, type, props FROM nodes")
    }
    degree: dict[str, int] = {}
    for r in conn.execute("SELECT src, dst FROM edges"):
        degree[r["src"]] = degree.get(r["src"], 0) + 1
        degree[r["dst"]] = degree.get(r["dst"], 0) + 1

    # 이름(라벨·별칭) -> 후보. 왕조 접두를 붙인 꼴도 같은 이름으로 본다.
    by_name: dict[tuple[str, str], set[str]] = {}
    for n in nodes.values():
        by_name.setdefault((n["label"], n["type"]), set()).add(n["id"])
    for r in conn.execute(
        "SELECT a.alias, a.node_id, n.type FROM aliases a JOIN nodes n ON n.id = a.node_id"
    ):
        by_name.setdefault((r["alias"], r["type"]), set()).add(r["node_id"])

    checked = ok = 0
    moves: dict[str, dict] = {}
    ambiguous: dict[str, dict] = {}

    for r in conn.execute(
        "SELECT src, dst, props FROM edges WHERE source = ?", (REPAIR_SOURCE,)
    ):
        doc_era = _doc_era(nodes, json.loads(r["props"] or "{}").get("extracted_from"))
        for nid in (r["src"], r["dst"]):
            node = nodes.get(nid)
            if node is None:
                continue
            checked += 1
            keys = [(node["label"], node["type"])]
            keys += [(f"{d} {node['label']}", node["type"]) for d in DYNASTIES]
            cands = {c for key in keys for c in by_name.get(key, set())} - {nid}
            if not cands:
                ok += 1
                continue

            here = degree.get(nid, 0)
            era_match = [
                c for c in cands
                if doc_era and _era_of_node(nodes[c]) == doc_era
                and degree.get(c, 0) > here
            ]
            best = max(cands, key=lambda c: degree.get(c, 0))
            if len(era_match) == 1:
                target, why = era_match[0], "시대일치"
            elif (
                here <= DEGREE_STUB
                and degree.get(best, 0) >= DEGREE_DOMINANCE * max(here, 1)
            ):
                target, why = best, "차수우세"
            elif degree.get(best, 0) <= here:
                ok += 1  # 이미 후보 중 가장 잘 연결된 노드에 붙어 있다
                continue
            else:
                ambiguous.setdefault(nid, {
                    "id": nid, "label": node["label"], "degree": here,
                    "doc_era": doc_era,
                    "candidates": [
                        {"id": c, "label": nodes[c]["label"],
                         "degree": degree.get(c, 0), "era": _era_of_node(nodes[c])}
                        for c in sorted(cands, key=lambda c: -degree.get(c, 0))
                    ],
                })
                continue

            moves.setdefault(nid, {
                "id": nid, "label": node["label"], "degree": here,
                "target": target, "target_label": nodes[target]["label"],
                "target_degree": degree.get(target, 0),
                "method": why, "doc_era": doc_era,
            })

    return {
        "checked": checked,
        "ok": ok,
        "moves": sorted(moves.values(), key=lambda m: -m["target_degree"]),
        "ambiguous": sorted(ambiguous.values(), key=lambda a: -a["degree"]),
    }


def repair_links(store: GraphStore, dry_run: bool = False) -> dict[str, object]:
    """전수 조사 결과대로 추출 엣지를 옳은 노드로 옮긴다.

    노드를 합치지 않고 **엣지만** 옮긴다. `wd:Q16177061`(정종)은 실제로
    존재하는 다른 인물이라 지우면 안 된다 — 그 문장이 말한 정종이
    아니었을 뿐이다. 옮긴 엣지에는 `repaired_from` 을 남긴다."""
    report = audit_links(store)
    if dry_run:
        return report

    edges = self_loops = 0
    for m in report["moves"]:
        stats = _rewrite_edges(
            store.conn, m["id"], m["target"],
            sources=(REPAIR_SOURCE,), tag="repaired_from",
        )
        edges += stats["edges"]
        self_loops += stats["self_loops"]
    store.conn.commit()
    log.info(
        "엣지 재연결 %d건 (노드 %d개) · 자기순환 %d건 제거 · 보류 %d개",
        edges, len(report["moves"]), self_loops, len(report["ambiguous"]),
    )
    report.update({"moved_edges": edges, "self_loops": self_loops})
    return report


def pending_backfill(store: GraphStore) -> list[str]:
    """관계를 아직 안 받아온 승격 노드.

    이번 실행에서 만든 것만 보강하면, 중간에 죽거나 예전 버전으로 승격해
    둔 노드는 영원히 관계 없이 남는다. 노드에 표시를 남겨 두고 아직
    표시가 없는 것을 매번 처리한다."""
    return [
        r["id"]
        for r in store.conn.execute(
            """SELECT id FROM nodes
                WHERE json_extract(props, '$.promoted') = 1
                  AND json_extract(props, '$.backfilled') IS NULL"""
        )
    ]


def backfill_relations(
    store: GraphStore, node_ids: list[str], fetcher: Fetcher | None = None
) -> dict[str, int]:
    """승격으로 새로 생긴 `wd:` 노드의 관계를 Wikidata 에서 채운다.

    **승격의 값은 여기서 나온다.** QID 를 찾아 노드를 만드는 것까지는
    이름을 바꾼 것에 지나지 않는다. 그 QID 에 달린 부모·배우자·직위·소속을
    끌어와야 고아였던 인물이 그래프에 실제로 얽힌다."""
    from .sources.wikidata import fetch_edges_for

    qids = [i.split(":", 1)[1] for i in node_ids if i.startswith("wd:")]
    if not qids:
        return {"nodes": 0, "edges": 0, "failures": 0}

    # WDQS 는 과호출에 403/502 로 응답한다. 위키백과보다 넉넉히 쉰다.
    fetcher = fetcher or Fetcher(store.path.parent / "cache", min_interval=1.5)
    failures: list[str] = []
    nodes, edges = fetch_edges_for(fetcher, qids, failures=failures)
    store.upsert_nodes(nodes)
    store.upsert_edges(edges)

    # 실패한 구간이 있으면 표시하지 않는다 — 다음 실행이 다시 시도한다.
    if failures:
        log.warning("관계 보강 실패 %d구간 — 표시를 남기지 않고 다음 실행에 재시도", len(failures))
    else:
        store.conn.executemany(
            """UPDATE nodes
                  SET props = json_set(COALESCE(NULLIF(props,''),'{}'), '$.backfilled', 1)
                WHERE id = ?""",
            [(i,) for i in node_ids],
        )
        store.conn.commit()
    return {"nodes": len(nodes), "edges": len(edges), "failures": len(failures)}


def prune_orphans(store: GraphStore) -> int:
    """엣지도 same_as 도 없는 ex 노드를 지운다.

    추출은 관계를 만들다 실패해도 노드는 남긴다(스키마 불일치로 엣지가
    버려진 경우). 그렇게 남은 노드는 그래프에 아무 기여도 하지 않으면서
    가제티어와 통계만 부풀린다."""
    cur = store.conn.execute(
        """DELETE FROM nodes WHERE id LIKE ?
             AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.src = nodes.id OR e.dst = nodes.id)
             AND NOT EXISTS (SELECT 1 FROM same_as s WHERE s.a = nodes.id OR s.b = nodes.id)""",
        (EX_PREFIX + "%",),
    )
    store.conn.commit()
    log.info("고립 ex 노드 %d개 제거", cur.rowcount)
    return cur.rowcount


# --- 사실 정합성 보수 -------------------------------------------------------
#
# 그래프는 자기 안에서 이미 모순을 드러낸다. "정현왕후는 윤호의 딸이자
# 아내", "소현세자와 효종이 서로의 부모", "소혜왕후의 부모가 33명",
# "김종직이 죽은 지 7년 뒤 무오사화에 참여" 같은 것들이다. 화면은 이걸
# 그대로 문장으로 읽어 준다 — 틀린 역사를 단정해서 말하는 셈이다.
#
# 판정 기준은 하나다. **파싱으로 얻은 관계(Wikidata·인포박스)가
# 추출(LLM)보다 세다.** 구조화 소스가 한쪽을 지지하면 반대쪽 추출 엣지를
# 버린다. 양쪽 다 추출이면 근거 문장이 어느 쪽을 말하는지 본다.
STRUCTURED = ("wd", "kowiki:infobox", "khs")

# --- 사람이 판정한 예외 -----------------------------------------------------
#
# 규칙으로는 가릴 수 없는 자리가 있다. 출처끼리 엇갈리거나, 출처가 맞아도
# 화면에 올리면 사건의 정의가 바뀌는 관계다. 사실 확인을 거쳐 거짓이라고
# 판정한 것을 여기 적어 두면 다시 들어와도 보수 단계에서 지운다.
#
# (id, 관계, id, 왜 거짓인가) — 이유를 함께 적는다. 근거 없이 지운 자리는
# 나중에 아무도 되돌릴 수 없다.
REJECTED: tuple[tuple[str, str, str, str], ...] = (
    (
        "wd:Q488995", "occurred_at", "wd:Q109079",
        "위화도 회군은 압록강 하류 위화도에서 군을 돌린 사건이다. 개경(개성)은"
        " 회군이 끝난 뒤 정변이 벌어진 곳이라, '일어난 곳'으로 세우면 사건의"
        " 정의가 바뀐다. 위키백과 정보상자는 장소를 '위화도 및 개경',"
        " Wikidata 는 P276=Kaesong 으로 적지만 화면은 그 둘을 구분해 주지"
        " 못한다 — 개성시 상세에 '위화도 회군은 개성시에서 일어났다'가 뜬다.",
    ),
    (
        "wd:Q490348", "occurred_at", "wd:Q109079",
        "정묘호란의 후금군은 의주-정주-안주를 거쳐 평양까지 내려왔고 개성은"
        " 방어 거점으로 군병을 조발한 곳이지 전장이 아니다. 위키백과 정보상자의"
        " 장소도 '평안도·황해도·경기도'다. 이 엣지의 근거는 배천·강음 약탈"
        " 문장으로 개성을 지목하지도 않는다.",
    ),
    (
        "wd:Q490348", "occurred_at", "ex:place:경덕궁",
        "근거가 '인조가 강화도를 출발해 경덕궁으로 돌아왔다' 이다. 전쟁이 끝난"
        " 뒤 임금이 돌아간 자리이지 전쟁이 일어난 곳이 아니다.",
    ),
    (
        "wd:Q64506", "located_in", "ex:place:양화나루 옆의 잠두봉",
        "'양화나루 옆의 잠두봉'은 지명이 아니라 설명구다. 유적이 자기 자신을"
        " 설명한 구절 안에 있다고 말하는 엣지다.",
    ),
)


# 부모와 자식의 최소 나이차. 열세 살에 아이를 얻은 기록은 없다고 보는 것이
# 아니라, 이보다 좁으면 형제·사돈·동학을 부모로 읽은 것이라고 본다.
MIN_GENERATION = 13

# `정성근의 아들`·`아버지 전창혁` — 근거가 누가 부모인지 말해 주는 꼴
# 자식을 가리키는 말. 산문은 `여섯째 딸로`, `5남 해양군` 처럼 순서를 붙인다.
_PARENT_OF = (
    r"(?:[가-힣]{1,3}째\s*)?(?:아들|딸)|자녀|소생|\d+남|\d+녀"
    r"|장남|차남|삼남|사남|장녀|차녀|삼녀|막내|맏이"
)
_PARENT_WORD = (
    "아버지|어머니|부친|모친|아비|어미|부왕|모후|생부|생모|친부|친모"
    "|친정아버지|친정어머니|양부|양모|계모|적모|서모"
)


def _year_of(value) -> int | None:
    m = re.match(r"^(-?)(\d{1,4})", str(value or ""))
    if not m:
        return None
    return -int(m.group(2)) if m.group(1) else int(m.group(2))


def life_of(node: dict) -> tuple[int | None, int | None]:
    """노드의 생몰 연도. **인물의 믿을 수 없는 값은 없는 셈 친다.**

    실측: 서장옥의 생몰이 둘 다 1900-01-01 이다(몰년만 아는 인물).
    이걸 생년으로 읽으면 동학농민혁명 참여가 연대 모순으로 잡힌다.
    사건은 다르다 — 하루짜리 사건은 시작과 끝이 같은 게 정상이다."""
    start, end = _year_of(node.get("start_date")), _year_of(node.get("end_date"))
    if node.get("type") == "person" and start is not None and start == end:
        return None, None
    return start, end


def _supports_parent(edge: dict, child: str, parent: str, parent_id: str,
                     lenient: bool = False) -> bool:
    """근거 문장이 '{parent} 가 {child} 의 부모'라고 말하는가.

    `lenient` 는 부모어와 이름 사이에 관직·수식이 끼는 꼴까지 인정한다
    (`아버지는 생원 김하중이며`, `아버지 거창부원군 신승선과`). 방향을
    가릴 때는 쓰지 않는다 — 느슨하면 양쪽이 다 참이 되어 못 가린다."""
    evidence = _evidence(edge)
    if not evidence or not child or not parent:
        return False
    p, c = re.escape(parent), re.escape(child)
    patterns = (
        rf"{p}\s*(?:\([^)]*\))?\s*의\s*(?:{_PARENT_OF})",       # 정성근의 아들
        rf"(?:{_PARENT_WORD})\s*(?:인\s*)?{p}",                  # 아버지 전창혁
        rf"{c}[^.]{{0,30}}의\s*(?:{_PARENT_WORD})\s*(?:인|는|가)?\s*{p}",
        # `정윤겸과 ... 남씨(南氏)사이에서 태어난 2남 3녀 중`
        rf"{p}[^.]{{0,10}}사이에서\s*태어",
        # `인빈 김씨 소생의 의창군`
        rf"{p}\s*(?:\([^)]*\))?\s*소생",
        # `인성군 이공의 5남 해양군 이희`
        rf"{p}[^.]{{0,15}}의\s*(?:{_PARENT_OF})\s*(?:인\s*)?{c}",
        # `남양부부인 홍씨(南陽府夫人 洪氏) 여섯째 딸로`
        rf"{p}\s*(?:\([^)]*\))?[^.]{{0,8}}(?:{_PARENT_OF})\s*(?:로|으로)",
        # `이희택(李羲宅)과 밀양 박씨의 아들로 출생하였으며` — 부모 이름이
        # `~의 아들로` 바로 앞에 붙어 있어야 한다. 사이를 넉넉히 열어 두면
        # 문장 맨 앞의 **자식 이름**까지 부모로 읽힌다("이상재는 … 아들로").
        rf"{p}\s*(?:\([^)]*\))?\s*(?:과|와|,)?\s*[^.]{{0,12}}의\s*"
        rf"(?:{_PARENT_OF})\s*(?:로|으로)\s*(?:출생|태어)",
    )
    if any(re.search(x, evidence) for x in patterns):
        return True
    # `아버지는 생원 김하중(金夏重)이며` — 부모어와 이름 사이의 관직·수식
    if lenient and re.search(
        rf"(?:{_PARENT_WORD})\s*(?:는|은|이|가|인)?\s*[-–:·]?\s*"
        rf"(?:[^,.·]{{0,10}}\s)?{p}", evidence
    ):
        return True
    # 문서 주인이 곧 부모인 글에서 `셋째 아들 이경보` 라고 하면 그가 자식이다.
    # 이름을 한 번만 적는 산문에서는 이 단서가 유일할 때가 많다.
    if json.loads(edge.get("props") or "{}").get("extracted_from") == parent_id:
        return bool(re.search(rf"(?:{_PARENT_OF})\s*(?:인\s*)?{c}", evidence))
    return False


def _evidence(edge: dict) -> str:
    return json.loads(edge.get("props") or "{}").get("evidence") or ""


def audit_facts(store: GraphStore) -> dict[str, object]:
    """그래프가 스스로 모순인 관계를 **전수 조사**한다.

    지우자고 판정한 엣지는 `drops`, 사람 손이 필요한 것은 `holds` 로
    나온다. 되돌릴 수 없는 판단은 하지 않는다 — 옮길 곳이 분명한
    엣지만 옮기고(`moves`), 나머지는 지우거나 남긴다."""
    conn = store.conn
    nodes = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, label, type, start_date, end_date FROM nodes"
        )
    }
    edges = [
        dict(r)
        for r in conn.execute(
            "SELECT rowid, src, dst, type, source, label, props FROM edges"
        )
    ]
    label = lambda i: nodes.get(i, {}).get("label", i)  # noqa: E731

    by_pair: dict[tuple[str, str], list[dict]] = {}
    for e in edges:
        by_pair.setdefault((e["src"], e["dst"]), []).append(e)

    drops: list[dict] = []
    moves: list[dict] = []
    holds: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def kind(pair, edge_type):
        return [e for e in by_pair.get(pair, ()) if e["type"] == edge_type]

    def drop(edge, reason, detail=""):
        drops.append({"rowid": edge["rowid"], "reason": reason,
                      "text": f"{label(edge['src'])} -{edge['type']}({edge['source']})→"
                              f" {label(edge['dst'])}" + (f" · {detail}" if detail else "")})

    for (a, b) in list(by_pair):
        key = (a, b) if a < b else (b, a)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        child = kind((a, b), "child_of") + kind((b, a), "child_of")
        spouse = kind((a, b), "spouse_of") + kind((b, a), "spouse_of")

        # 1) 부모이자 배우자 — 둘 중 하나는 반드시 거짓이다
        if child and spouse:
            c_struct = any(e["source"] in STRUCTURED for e in child)
            s_struct = any(e["source"] in STRUCTURED for e in spouse)
            if c_struct and not s_struct:
                for e in spouse:
                    drop(e, "부모 관계가 구조화 소스에 있다 — 배우자 쪽이 오독")
            elif s_struct and not c_struct:
                for e in child:
                    drop(e, "배우자 관계가 구조화 소스에 있다 — 부모 쪽이 오독")
            else:
                holds.append({"text": f"{label(a)} ↔ {label(b)}",
                              "reason": "부모이자 배우자인데 양쪽 다 같은 급의 소스"})

        # 2) 서로가 서로의 부모 — 한쪽은 반드시 거짓이다
        fwd = kind((a, b), "child_of")
        rev = kind((b, a), "child_of")
        if fwd and rev:
            f_struct = any(e["source"] in STRUCTURED for e in fwd)
            r_struct = any(e["source"] in STRUCTURED for e in rev)
            if f_struct and not r_struct:
                for e in rev:
                    drop(e, "반대 방향이 구조화 소스에 있다")
            elif r_struct and not f_struct:
                for e in fwd:
                    drop(e, "반대 방향이 구조화 소스에 있다")
            elif f_struct and r_struct:
                holds.append({"text": f"{label(a)} ↔ {label(b)}",
                              "reason": "양방향 부모인데 양쪽 다 구조화 소스"})
            else:
                # 근거 문장이 어느 쪽을 말하는가. 아무 쪽도 아니면 둘 다 버린다 —
                # 형제를 부모로 읽은 경우가 여기 걸린다(이시애와 그 아우 이시합).
                f_ok = any(_supports_parent(e, label(a), label(b), b) for e in fwd)
                r_ok = any(_supports_parent(e, label(b), label(a), a) for e in rev)
                if f_ok and not r_ok:
                    for e in rev:
                        drop(e, "근거는 반대 방향을 말한다")
                elif r_ok and not f_ok:
                    for e in fwd:
                        drop(e, "근거는 반대 방향을 말한다")
                else:
                    for e in fwd + rev:
                        drop(e, "서로가 서로의 부모 — 근거가 어느 쪽도 지지하지 않는다")

    # 3) 부모가 셋 이상 — 구조화 소스가 이미 둘을 주면 나머지는 군더더기
    parents: dict[str, dict[str, list[dict]]] = {}
    for e in edges:
        if e["type"] == "child_of":
            parents.setdefault(e["src"], {}).setdefault(e["dst"], []).append(e)
    for person, cand in parents.items():
        struct = {p for p, es in cand.items()
                  if any(e["source"] in STRUCTURED for e in es)}
        if len(struct) < 2:
            continue
        for p, es in cand.items():
            if p in struct:
                continue
            for e in es:
                drop(e, "구조화 소스가 이미 부모를 준다",
                     f"{label(person)}의 부모 {len(struct)}명이 이미 있다")

    # 3-b) 부모가 자식보다 어리다 — 형·아우·사돈을 부모로 읽은 자리다.
    #
    # **추출 엣지만 본다.** 삼국·고려 왕들의 생몰은 즉위년이나 전승 연대가
    # 섞여 있어(산상왕 몰 179 < 아들 동천왕 생 200) 구조화 소스까지 걸면
    # 참인 계보가 통째로 날아간다.
    for e in edges:
        if e["type"] != "child_of" or e["source"] in STRUCTURED:
            continue
        c, p = nodes.get(e["src"]), nodes.get(e["dst"])
        if not c or not p:
            continue
        c_birth, _ = life_of(c)
        p_birth, p_death = life_of(p)
        if c_birth is None:
            continue
        if p_birth is not None and p_birth > c_birth - MIN_GENERATION:
            drop(e, "부모가 한 세대 위가 아니다", f"부모 생 {p_birth} · 자식 생 {c_birth}")
        elif p_death is not None and p_death < c_birth - 1:
            drop(e, "부모가 자식보다 먼저 죽었다", f"부모 몰 {p_death} · 자식 생 {c_birth}")

    # 3-c) 근거가 상대를 부모가 아닌 친족으로 부른다 (할아버지·숙부·사돈…)
    for e in edges:
        if e["type"] != "child_of" or e["source"] in STRUCTURED:
            continue
        obj = label(e["dst"])
        if kin_title_mismatch("child_of", obj, _evidence(e), name_variants(obj)):
            drop(e, "근거는 부모가 아닌 친족이라 말한다")

    # 3-d) 근거가 부모라고 말하지 않는다.
    #
    # 남은 추출 부모의 대부분이 여기 걸린다 — `한씨를 왕비로 추숭해야
    # 한다고 주장한 대신들은 하동부원군 정인지` 같은 열거문이 소혜왕후의
    # 부모를 열둘로 만들었다. 구조화 소스는 검사하지 않는다.
    for e in edges:
        if e["type"] != "child_of" or e["source"] in STRUCTURED:
            continue
        if not _supports_parent(e, label(e["src"]), label(e["dst"]), e["dst"],
                                lenient=True):
            drop(e, "근거가 부모라고 말하지 않는다")

    # 0) 사람이 거짓이라고 판정해 둔 관계
    rejected = {(a, t, b) for a, t, b, _ in REJECTED}
    for e in edges:
        if (e["src"], e["type"], e["dst"]) in rejected:
            drop(e, "사실 확인 결과 거짓으로 판정한 관계")

    # 3-e) 서로 살아 있던 적이 없는 부부 (태종과 1598년생 흥안군)
    for e in edges:
        if e["type"] != "spouse_of" or e["source"] in STRUCTURED:
            continue
        a, b = nodes.get(e["src"]), nodes.get(e["dst"])
        if not a or not b:
            continue
        (ab, ad), (bb, bd) = life_of(a), life_of(b)
        if (ad is not None and bb is not None and bb > ad) or (
            bd is not None and ab is not None and ab > bd
        ):
            drop(e, "한쪽이 죽은 뒤에 태어난 부부")

    # 4) 죽은 뒤(또는 태어나기 전) 사건 참여
    by_label: dict[str, list[str]] = {}
    for n in nodes.values():
        if n["type"] == "person":
            by_label.setdefault(n["label"], []).append(n["id"])
    for e in edges:
        if e["type"] != "participated_in" or e["source"] in STRUCTURED:
            continue
        person, event = nodes.get(e["src"]), nodes.get(e["dst"])
        if not person or not event:
            continue
        birth, death = life_of(person)
        start, end = life_of(event)
        why = None
        if death is not None and start is not None and start > death:
            why = f"몰년 {death} < 사건 {start}"
        elif birth is not None and end is not None and end < birth:
            why = f"사건 {end} < 생년 {birth}"
        if not why:
            continue
        conflict = why
        # 같은 이름의 다른 인물이 그 사건을 살았다면 엣지를 그리로 옮긴다
        fits = []
        for other in by_label.get(person["label"], ()):
            if other == person["id"]:
                continue
            ob, od = life_of(nodes[other])
            if od is not None and start is not None and start > od:
                continue
            if ob is not None and end is not None and end < ob:
                continue
            if ob is None and od is None:
                continue
            fits.append(other)
        if len(fits) == 1:
            moves.append({"rowid": e["rowid"], "to": fits[0], "reason": why,
                          "text": f"{label(e['src'])} → {label(e['dst'])}"
                                  f" · 같은 이름의 {label(fits[0])}({fits[0]})로"})
        else:
            drop(e, "죽은 뒤(태어나기 전)의 사건 참여", conflict)

    # 같은 엣지가 두 규칙에 걸릴 수 있다. 한 번만 지운다.
    unique: dict[int, dict] = {}
    for d in drops:
        unique.setdefault(d["rowid"], d)
    moved = {m["rowid"] for m in moves}
    drops = [d for r, d in unique.items() if r not in moved]
    return {"drops": drops, "moves": moves, "holds": holds,
            "checked": len(edges)}


def repair_facts(store: GraphStore, dry_run: bool = False) -> dict[str, object]:
    """`audit_facts` 판정대로 그래프를 고친다."""
    report = audit_facts(store)
    if dry_run:
        return report
    conn = store.conn
    for m in report["moves"]:
        conn.execute("UPDATE edges SET src = ? WHERE rowid = ?", (m["to"], m["rowid"]))
    ids = [d["rowid"] for d in report["drops"]]
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        conn.execute(
            f"DELETE FROM edges WHERE rowid IN ({','.join('?' * len(batch))})", batch
        )
    conn.commit()
    log.info("모순 관계 %d건 삭제 · %d건 재연결 · 보류 %d건",
             len(ids), len(report["moves"]), len(report["holds"]))
    return report
