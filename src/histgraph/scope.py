"""시대별 서브그래프 추출.

전체 그래프는 현대 인물이 압도한다 — 인물 28,471명 중 대한민국 국적이
18,471명(65%)이고 조선은 2,923명이다. 한 시대를 먼저 제대로 만들어 보고
확장 여부를 판단하는 편이 낫다.

**원본은 건드리지 않는다.** 별도 DB 로 뽑아내므로 나중에 다른 시대를
추가하거나 기준을 바꿔 다시 뽑을 수 있다.

선정 방식:
  1) 씨앗 — 그 시대로 명시된 인물·사건·유물
  2) 1홉 확장 — 씨앗이 실제로 연결된 장소·직위·조직·인물
  3) 양끝이 모두 포함된 엣지만 유지

1홉까지만 넓히는 이유: 2홉이면 조선 인물의 현대 후손, 그 후손이 참여한
현대 사건까지 딸려 와 시대 구분이 무의미해진다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from .store import GraphStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Era:
    """한 시대를 고르는 기준."""

    name: str
    polity_qid: str
    polity_label: str
    # 유물 시대 라벨에서 이 왕조를 가리키는 표기들
    aliases: list[str] = field(default_factory=list)
    # 정체 노드가 **나라**인가. 연표는 나라를 자기 존속 기간으로 세우고
    # 시작 해에 '건국'을 단다 (2026-09-05 사용자 요청). 일제강점기는
    # 시대이지 나라가 아니라 세우지 않는다 — '일제강점기 건국'은 말이
    # 안 된다.
    state: bool = True
    # 같은 시대 안에서 뒤따르는 나라의 QID. 조선은 1897년에 대한제국이 되는데
    # 대한제국은 시대(Era)가 아니라 조선 시대의 뒷부분이다 — 연표에는 자기
    # 존속 기간(1897~1910)으로 서서 '대한제국 건국'을 알린다.
    successor_states: list[str] = field(default_factory=list)
    # 이 시대의 **사건**을 함께 담을 후계 정체. 조선은 1897년에 대한제국이
    # 되고 1910년에 끝나는데, Wikidata 는 경술국치·을사조약·군대해산의
    # P17 을 대한제국으로 적는다. 1897년에서 자르면 '조선이 어떻게 끝났나'가
    # 통째로 빠진다 — 이미 3·1 운동·청산리 전투가 인물을 타고 들어와 있어
    # 자르는 쪽이 오히려 실제와 안 맞았다.
    #
    # **인물에는 적용하지 않는다.** 대한제국 국적 인물까지 씨앗으로 삼으면
    # 근현대로 끌려간다 (전체 인물 28,471명 중 65%가 대한민국이다).
    successor_events: list[str] = field(default_factory=list)
    # 인물 씨앗으로 삼을 국적 라벨. 비우면 자기 이름 하나다.
    #
    # **일제강점기 때문에 생긴 칸이다.** 이 시대에는 나라가 없어서 사람의
    # 국적이 한 이름으로 모이지 않는다 — Wikidata 는 같은 시기 사람을
    # '일제강점기'(2,082명)와 '대한제국'(626명)에 갈라 적어 뒀다. 한쪽만
    # 씨앗으로 삼으면 안중근과 윤봉길이 다른 그래프에 산다.
    person_polities: list[str] = field(default_factory=list)
    # 인물을 **연대로** 고르는 창 (시대 시작연도, 끝연도).
    #
    # **국적으로는 이 시대 사람이 모이지 않는다.** 실측: 유관순은
    # '일제강점기', 이완용은 '조선', 김좌진은 태그 없음, 박은식은
    # '대한민국', 김원봉은 '조선민주주의인민공화국'이다. 나라가 없던
    # 시대라 P27 이 한 이름으로 모이지 않고, 그나마 '일제강점기'로 적힌
    # 1,339명은 81%가 1960년 이후에 죽은 **해방 후 인물**이다 —
    # 그 시대에 태어났을 뿐인 명단이다.
    #
    # 갈리는 것은 연대다. 이 창을 주면 '시대가 시작할 때 이미 태어나
    # 있었고, 그때까지 살아 있던 사람'을 씨앗으로 삼는다. 실측 2,187명이
    # 걸리고 유관순·김좌진·이완용·홍범도·신채호·이육사·여운형이 전부
    # 들어온다.
    person_window: tuple[int, int] | None = None
    # 국적으로 인물 씨앗을 고를 것인가. **대한민국은 아니다** — 전체 인물의
    # 65%(18,471명)가 이 국적이고 그 대부분은 역사가 아니라 명단이다
    # (운동선수·연예인). 끄면 인물은 사건의 이웃과 `seed_positions` 로만
    # 들어온다: 사건에 참여한 사람, 그리고 그 자리에 앉았던 사람.
    seed_by_polity: bool = True
    # 이 자리에 앉았던 인물은 씨앗이다 (`held_position` 의 도착 QID).
    # 대한민국의 씨앗 인물은 대통령이다 — 연표의 띠가 그들로 선다.
    seed_positions: list[str] = field(default_factory=list)
    # 이 해보다 앞선 사건은 정체 태그가 있어도 씨앗이 아니다. Wikidata 의
    # P17 은 '지금 그 땅의 나라'를 적는 일이 잦다 — 실측: 원종·애노의
    # 난(889년)이 대한민국의 사건으로 태그돼 있다.
    since: int | None = None

    def seed_polities(self) -> list[str]:
        if not self.seed_by_polity:
            return []
        return self.person_polities or [self.polity_label]


ERAS: dict[str, Era] = {
    "joseon": Era("조선", "Q28179", "조선", ["조선"], successor_events=["대한제국"],
                  successor_states=["Q28233"]),
    # 고려는 조선 앞에 선다 — 묶음의 **맨 앞 시대**가 연표의 바닥이다
    # (`server._polities` 의 `floor`; 화면을 여는 자리는 `BUNDLE_ROOT` 가
    # 따로 정한다). 조선만 있을 때는 위화도 회군(1388)·삼사(1100) 같은
    # 고려 사건이 맥락으로만 남아 축을 늘여 놓았는데, 이제 그것들이 자기
    # 시대에 선다 (2026-09-06 사용자 요청).
    "goryeo": Era("고려", "Q28208", "고려", ["고려"]),
    # 고대 (2026-09-11 사용자 요청: "고조선 부터 후삼국시대 까지 역사를
    # 추가하자"). 시대를 **나라마다** 가른 것은 삼국이 겹쳐 서기 때문이다 —
    # 고구려·백제·신라·가야는 한 축 위에 나란히 존속하므로 하나로 묶으면
    # 어느 나라의 일인지가 사라진다.
    #
    # 나라가 아닌 두 시기(원삼국·후삼국)는 `state=False` 다. '부여 건국'은
    # 말이 되지만 '원삼국 시대 건국'은 말이 안 된다 — 일제강점기와 같다.
    "gojoseon": Era(
        "고조선", "Q28405", "고조선", ["고조선"],
        person_polities=["고조선", "위만조선"],
        successor_events=["위만조선"],
    ),
    # 부여·옥저·동예·삼한이 사는 자리. 이 넷은 고조선의 뒤이지 고조선이
    # 아니고, 삼국과 겹치는 앞머리라 어느 나라에도 넣을 수 없다. 교과서가
    # 가른 자리(원삼국 시대)를 그대로 쓴다.
    "wonsamguk": Era(
        "원삼국 시대", "Q716528", "원삼국 시대", [],
        person_polities=["부여", "마한"],
        successor_events=["부여", "마한"],
        state=False,
    ),
    "silla": Era(
        "신라", "Q28456", "신라", ["신라", "통일신라"],
        # 통일신라는 시대가 아니라 신라의 뒷부분이다 (조선과 대한제국의
        # 관계와 같다). 국적·P17 이 그 이름으로 적힌 사람과 사건을 신라가
        # 함께 담지 않으면 668년 뒤가 통째로 빈다.
        person_polities=["신라", "통일신라"],
        successor_events=["통일신라"],
    ),
    "goguryeo": Era("고구려", "Q28370", "고구려", ["고구려"]),
    "baekje": Era("백제", "Q28428", "백제", ["백제"]),
    # 가야는 한 나라가 아니라 연맹이라 Wikidata 도 금관가야·대가야를 따로
    # 적는다. 셋을 한 시대로 담는다.
    "gaya": Era(
        "가야", "Q28084", "가야", ["가야", "금관가야", "대가야"],
        person_polities=["가야", "금관가야", "대가야"],
        successor_events=["금관가야", "대가야"],
    ),
    "balhae": Era("발해", "Q28322", "발해", ["발해"]),
    # 후삼국은 나라가 아니라 신라·후백제·태봉이 겹쳐 있던 45년이다.
    "husamguk": Era(
        "후삼국 시대", "Q698268", "후삼국 시대", [],
        person_polities=["후백제", "태봉"],
        successor_events=["후백제", "태봉"],
        state=False,
    ),
    "ilje": Era(
        "일제강점기", "Q503585", "일제강점기", ["일제강점기"],
        # 국적 태그는 대한제국만 믿는다 — 627명 중 생년이 1919년 이후인
        # 사람이 한 명뿐이라, 이 이름은 실제로 그 시대를 가리킨다.
        person_polities=["대한제국"],
        person_window=(1910, 1945),
        state=False,
    ),
    # 대한민국은 왕조가 아니라 지금의 나라다. 정체 노드(Q884)는 그래프에
    # **장소**로 앉아 있고(출생지 엣지 983건이 가리킨다) 시대 엣지의 도착이
    # 될 수 없으므로, 씨앗은 사건과 대통령에서 온다. 인물을 국적으로 고르면
    # 명단이 된다 (`seed_by_polity` 주석).
    "daehan": Era(
        "대한민국", "Q884", "대한민국", ["대한민국"],
        seed_by_polity=False,
        seed_positions=["Q6296418"],   # 대한민국 대통령
        since=1945,
    ),
}

# 한 화면에 담을 시대 묶음. **시대를 고르는 기준(ERAS)과 다른 것이다** —
# 조선은 1910년에 끝나지만 화면에서 1910년에 끊기면 그 다음 35년이
# 어디에도 없다. 사람도 이어진다: 대한제국에서 벼슬한 사람이 일제강점기에
# 의병이 되고, 조선의 마지막 왕이 일제강점기의 이왕(李王)이다.
BUNDLES: dict[str, tuple[str, ...]] = {
    "korea": (
        "gojoseon", "wonsamguk", "goguryeo", "baekje", "silla", "gaya",
        "balhae", "husamguk", "goryeo", "joseon", "ilje", "daehan",
    ),
}

# 묶음의 이름. 화면 머리에 뜨는 글자라 한국어여야 한다.
BUNDLE_LABEL: dict[str, str] = {
    "korea": "고조선~대한민국",
}

# **여는 자리**는 맨 앞 시대와 다르다 (2026-09-11 사용자 결정: "페이지를
# 처음 열었을때 보이는 타임라인을 조선으로"). 맨 앞 시대는 **연표의
# 바닥**이라 그 앞의 것을 덜어내는 자리고(`server` 의 `floor`), 여는 자리는
# 화면을 열었을 때 서는 노드다(`server.root`). korea 묶음의 연표는 918년
# 고려 건국에서 시작하되, 처음 보이는 자리는 조선이다 — 바닥을 조선으로
# 올리면 고려 사건 전부가 연표에서 사라진다 (CLAUDE.md 1-3 뒷절).
BUNDLE_ROOT: dict[str, str] = {
    "korea": "joseon",
}


def eras_of(key: str) -> tuple[str, ...]:
    """묶음 이름이면 그 구성 시대들, 시대 이름이면 자기 자신."""
    return BUNDLES.get(key, (key,))


def opening_eras(key: str) -> tuple[str, ...]:
    """중심(`server.root`)을 고를 차례. 여는 시대를 정해 뒀으면 그것이 맨 앞이고,
    그 시대의 왕조 노드가 그래프에 없을 때만 다음 시대로 넘어간다."""
    eras = eras_of(key)
    opener = BUNDLE_ROOT.get(key)
    if opener is None or opener not in eras:
        return eras
    return (opener, *(e for e in eras if e != opener))


def label_of(key: str) -> str:
    """화면에 쓸 이름. 모르는 이름이면 빈 문자열 — 영어 키를 내보내지 않는다."""
    if key in BUNDLE_LABEL:
        return BUNDLE_LABEL[key]
    era = ERAS.get(key)
    return era.name if era else ""


def select_seeds(store: GraphStore, era: Era) -> set[str]:
    """그 시대로 명시된 노드들.

    세 경로가 있고 서로 겹치지 않는다:
      - 인물: Wikidata 국적(P27)을 수집 때 props.polity 에 적어뒀다
      - 사건: 시드 목록의 시대 구분, 또는 왕조 노드와 직접 연결
      - 유물: 국가유산청 시대 라벨이 same_as 로 왕조에 해소된 것
    """
    c = store.conn
    seeds: set[str] = set()

    polities = era.seed_polities()
    marks = ",".join("?" * len(polities))
    persons = [
        r["id"]
        for r in c.execute(
            f"""SELECT id FROM nodes WHERE type='person'
                 AND json_extract(props,'$.polity') IN ({marks})""",
            polities,
        )
    ] if polities else []
    # 그 자리에 앉았던 사람 (Era.seed_positions 주석 참고).
    by_seat: list[str] = []
    for pos in era.seed_positions:
        by_seat += [
            r["src"]
            for r in c.execute(
                """SELECT src FROM edges WHERE type='held_position' AND dst=?""",
                (f"wd:{pos}",),
            )
        ]
    # **국적 태그가 없는 인물이 3,390명이고 거기에 왕들이 들어 있다.**
    # '조선 정종'은 라벨에 시대가 적혀 있는데도 씨앗이 아니어서, 다른
    # 인물의 이웃으로만 딸려 들어왔다. 그 바람에 그의 어머니(한씨)처럼
    # 두 홉 밖에 있는 가족이 시대 그래프에서 통째로 잘려 나갔다.
    by_label = [
        r["id"]
        for r in c.execute(
            "SELECT id FROM nodes WHERE type='person' AND label LIKE ?",
            (f"{era.polity_label} %",),
        )
    ]
    # 연대로 고르는 인물 (Era.person_window 주석 참고).
    by_year: list[str] = []
    if era.person_window:
        from .timeline import _year_of

        start = era.person_window[0]
        for r in c.execute(
            """SELECT id, start_date, end_date FROM nodes
                WHERE type='person' AND start_date IS NOT NULL AND start_date != ''"""
        ):
            born = _year_of(r["start_date"])
            if born is None or born > start:
                continue
            died = _year_of(r["end_date"])
            if died is None:
                # 몰년을 모르면 사람의 한 생애만큼 거슬러 인정한다. 이 선이
                # 없으면 몰년 없는 고대 인물이 통째로 딸려 온다.
                if born < start - 60:
                    continue
            elif died < start:
                continue
            by_year.append(r["id"])

    persons = list({*persons, *by_label, *by_year, *by_seat})
    seeds.update(persons)

    events = [
        r["id"]
        for r in c.execute(
            """SELECT id FROM nodes WHERE type='event'
               AND json_extract(props,'$.seed_era')=?""",
            (era.polity_label,),
        )
    ]
    # **Wikidata 가 그 정체의 사건이라고 말한 것.** 수집 쿼리가
    # `?e wdt:P17 wd:{polity}` 로 물어 놓고 답을 버리고 있어서, 여기 걸릴
    # 사건이 하나도 없었다. 실측: 조선 P17 사건 73건 — 진주민란·갑오개혁·
    # 신임사화·경신 대기근과 임진왜란 전투 30여 건이 통째로 빠져 있었다.
    event_polities = [era.polity_label, *era.successor_events]
    marks = ",".join("?" * len(event_polities))
    for r in c.execute(
        f"""SELECT id, start_date FROM nodes WHERE type='event'
             AND json_extract(props,'$.polity') IN ({marks})""",
        event_polities,
    ):
        if era.since is not None:
            from .timeline import _year_of

            year = _year_of(r["start_date"])
            if year is not None and year < era.since:
                continue
        events.append(r["id"])
    # 왕조 노드에 from_period 로 직접 걸린 사건도 포함
    events += [
        r["src"]
        for r in c.execute(
            "SELECT src FROM edges WHERE type='from_period' AND dst=?",
            (f"wd:{era.polity_qid}",),
        )
    ]
    seeds.update(events)

    heritage = [
        r["src"]
        for r in c.execute(
            """SELECT DISTINCT e.src FROM edges e
               JOIN same_as s ON s.a = e.dst
               WHERE s.b = ? AND e.type='from_period'""",
            (f"wd:{era.polity_qid}",),
        )
    ]
    seeds.update(heritage)

    log.info(
        "%s 씨앗: 인물 %d · 사건 %d · 유물 %d (합 %d)",
        era.name, len(persons), len(set(events)), len(heritage), len(seeds),
    )
    return seeds


def expand(store: GraphStore, seeds: set[str], hops: int = 1) -> set[str]:
    """씨앗이 연결된 노드까지 넓힌다. same_as 도 따라간다."""
    seen = set(seeds)
    frontier = set(seeds)

    for hop in range(hops):
        if not frontier:
            break
        found: set[str] = set()
        ordered = sorted(frontier)
        for i in range(0, len(ordered), 500):
            batch = ordered[i : i + 500]
            marks = ",".join("?" * len(batch))
            for r in store.conn.execute(
                f"""SELECT src, dst FROM edges
                    WHERE src IN ({marks}) OR dst IN ({marks})""",
                (*batch, *batch),
            ):
                found.add(r["src"])
                found.add(r["dst"])
            for r in store.conn.execute(
                f"SELECT a, b FROM same_as WHERE a IN ({marks}) OR b IN ({marks})",
                (*batch, *batch),
            ):
                found.add(r["a"])
                found.add(r["b"])
        frontier = found - seen
        seen |= found
        log.info("  %d홉 확장: +%d 노드 (누적 %d)", hop + 1, len(frontier), len(seen))

    return seen


# 장소는 사건·인물을 설명하는 자리다. 한쪽만 남으면 그래프가 거짓말을 한다.
PLACE_EDGES = ("occurred_at", "born_in", "died_in")


def close_places(store: GraphStore, keep: set[str]) -> set[str]:
    """포함된 노드가 '어디서'를 가리키면 그 장소도 데려온다.

    **실측.** '위화도 회군'은 이성계의 이웃으로 들어왔는데, 정작 이름이
    된 위화도는 두 홉 밖이라 잘려 나갔다. 남은 발생 장소는 개경과
    평양뿐이어서 화면이 "위화도 회군은 개성시에서 일어났다"고 말했다.
    장소를 다 못 데려올 바에는 하나도 없는 편이 낫지만, 22개만 더
    담으면 되는 일이다 (조선 그래프 기준 사건 10개의 장소 25건).
    """
    added: set[str] = set()
    ordered = sorted(keep)
    marks_type = ",".join("?" * len(PLACE_EDGES))
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        for r in store.conn.execute(
            f"""SELECT dst FROM edges
                 WHERE src IN ({marks}) AND type IN ({marks_type})""",
            (*batch, *PLACE_EDGES),
        ):
            if r["dst"] not in keep:
                added.add(r["dst"])
    if added:
        log.info("장소 보강: +%d 노드", len(added))
    return keep | added


def close_clans(store: GraphStore, keep: set[str]) -> set[str]:
    """씨족 나무는 **한 덩어리로** 데려온다. 위로도 아래로도 따라간다.

    `close_places` 와 같은 이유다. 나무의 어느 한 마디만 남으면 그 마디가
    말할 수 있는 것이 이름밖에 없다. 파는 파조(인물)를 통해 한 홉으로
    들어오는데 그 위의 대파와 본관은 두 홉 밖이라 잘려 나가고, 그러면 화면에
    '덕천군파'만 서고 그것이 전주 이씨의 파라는 말은 사라진다.

    아래로도 가는 까닭은 닻이 뿌리에 걸리는 씨족이 있어서다. 김해 김씨는
    파조 가운데 우리 그래프에 있는 사람이 하나뿐이라 본관 노드가 지명(김해시)
    으로 들어오는데, 위로만 따라가면 파 66개가 그대로 잘린다.
    """
    added: set[str] = set()
    frontier = set(keep)
    while frontier:
        found: set[str] = set()
        ordered = sorted(frontier)
        for i in range(0, len(ordered), 500):
            batch = ordered[i : i + 500]
            marks = ",".join("?" * len(batch))
            for r in store.conn.execute(
                f"""SELECT e.src AS a, e.dst AS b FROM edges e
                     JOIN nodes s ON s.id = e.src
                     JOIN nodes d ON d.id = e.dst
                     WHERE e.type='part_of'
                       AND (e.src IN ({marks}) OR e.dst IN ({marks}))
                       AND json_extract(s.props,'$.kind')='clan'
                       AND json_extract(d.props,'$.kind')='clan'""",
                (*batch, *batch),
            ):
                for nid in (r["a"], r["b"]):
                    if nid not in keep and nid not in added:
                        found.add(nid)
        added |= found
        frontier = found
    if added:
        log.info("씨족 보강: +%d 노드", len(added))
    return keep | added


def _dated_events(store: GraphStore, ids: set[str]) -> set[str]:
    """그 가운데 연대를 아는 사건만. 연표에 놓을 자리가 있는 것들이다."""
    if not ids:
        return set()
    out: set[str] = set()
    ordered = sorted(ids)
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        out.update(
            r["id"]
            for r in store.conn.execute(
                f"""SELECT id FROM nodes
                     WHERE id IN ({marks}) AND type='event'
                       AND start_date IS NOT NULL AND start_date != ''""",
                batch,
            )
        )
    return out


# 설명이 없으면 지우는 타입. **화면에서 제 이름 말고 할 말이 있어야 하는**
# 노드들이다. 사용자 지적(2026-09-04): 연표에 '백성들이 종이를 바치는 일의
# 폐단에 대해 선혜청에서 아뢰다'(실록 기사 제목)가 설명 없이 서 있었다 —
# "안 보여주는 게 더 좋을 것 같은데".
#
# **여기 없는 타입은 뼈대다.**
#   period  연표의 눈금(`time:1592`)과 유물 제작연대 문자열('1436년(조선
#           세종 18)'). 설명이 있을 수 없고, 없어도 연표가 그 자리를 그린다.
#           지우면 축이 무너진다.
#   role    직위는 인물 상세의 '직위' 줄로만 서고 연표에 안 선다. 이름
#           자체가 뜻이다 — '영의정'에 더 적을 말이 없어도 빈 칸이 아니다.
#   place   행정 지명도 이름이 곧 뜻이다. '서울 종로구'에 해설을 붙일
#           일이 없는데, 빼면 그 구에 있는 유물 86건이 '어디 있는지'를
#           잃는다 (실측: 빈 설명 장소 284개 중 상위 20개가 엣지 10건
#           이상인 행정 지명이다).
#
# **지우기 전에 채운다.** 이 관문에 걸리는 것은 '자료가 없는 노드'가
# 아니라 '아직 안 받아온 노드'인 적이 많았다 (실측: 빈 설명 wd 노드 573개
# 중 415개가 한국어 위키백과나 Wikidata 한 줄 설명을 갖고 있었다).
# `enrich` 와 `describe` 를 먼저 돌리지 않으면 이 규칙이 멀쩡한 노드를
# 지운다 — 그래서 `cmd_scope` 가 남은 수를 세어 알린다.
UNDESCRIBED_DROP_TYPES = (
    "event", "person", "org", "heritage", "artwork", "media", "concept",
)


def _undescribed(store: GraphStore, ids: set[str]) -> set[str]:
    """그 가운데 설명이 비어 있어 화면에 할 말이 없는 노드."""
    if not ids:
        return set()
    out: set[str] = set()
    ordered = sorted(ids)
    kinds = ",".join(f"'{t}'" for t in UNDESCRIBED_DROP_TYPES)  # 코드 안의 고정 목록
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        out.update(
            r["id"]
            for r in store.conn.execute(
                f"""SELECT id FROM nodes
                     WHERE id IN ({marks}) AND type IN ({kinds})
                       AND (description IS NULL OR trim(description) = '')""",
                batch,
            )
        )
    return out


def extract(
    store: GraphStore,
    era_keys: str | Sequence[str],
    out_path: str,
    hops: int = 1,
    drop_isolated: bool = True,
    drop_undescribed: bool = True,
) -> dict[str, object]:
    """시대 서브그래프를 별도 DB 로 뽑는다. 시대를 여럿 주면 한 DB 에 담는다.

    **여럿을 한 DB 에 담는 이유.** 조선을 1910년에서 자르면 그 다음 35년이
    화면 어디에도 없다. 씨앗은 시대별로 따로 고르고 — 기준이 시대마다
    다르다 — 그 다음 확장·고립정리·복사는 합집합에 한 번만 한다. 시대별로
    뽑아 나중에 합치면 시대를 걸치는 엣지(대한제국의 관료가 일제강점기의
    의병이 되는)가 양쪽 어디에도 안 남는다."""
    from pathlib import Path

    keys = [era_keys] if isinstance(era_keys, str) else list(era_keys)
    eras = []
    for key in keys:
        for sub in eras_of(key):
            era = ERAS.get(sub)
            if era is None:
                raise ValueError(
                    f"알 수 없는 시대: {sub} (가능: {', '.join(ERAS)}"
                    f" · 묶음: {', '.join(BUNDLES)})"
                )
            if era not in eras:
                eras.append(era)

    seeds: set[str] = set()
    for era in eras:
        seeds |= select_seeds(store, era)
    if not seeds:
        names = " · ".join(e.name for e in eras)
        raise ValueError(f"{names} 씨앗 노드가 없습니다 — 먼저 수집·해소가 필요합니다")

    keep = expand(store, seeds, hops=hops)
    # 왕조 노드 자신도 그래프의 중심으로 포함한다
    keep.update(f"wd:{e.polity_qid}" for e in eras)
    keep = close_places(store, keep)
    keep = close_clans(store, keep)

    # **노드 행이 없는 id 를 걸러낸다.** `expand` 는 엣지의 양끝을 모으는데,
    # 원본 그래프에도 이미 댕글링인 엣지가 있어서 노드가 없는 id 가 섞여
    # 들어온다. 그대로 복사하면 시대 그래프에 '없는 곳을 가리키는 엣지'가
    # 생긴다 (실측 19건 — 전부 child_of 라, 화면에서 부모 자리가 빈
    # 자녀 관계로 보인다).
    real: set[str] = set()
    ordered_keep = sorted(keep)
    for i in range(0, len(ordered_keep), 500):
        batch = ordered_keep[i : i + 500]
        marks = ",".join("?" * len(batch))
        real.update(
            r["id"]
            for r in store.conn.execute(
                f"SELECT id FROM nodes WHERE id IN ({marks})", batch
            )
        )
    if len(real) != len(keep):
        log.info("노드 행이 없는 끝점 %d개 제외", len(keep) - len(real))
    keep = real

    # **설명이 없는 내용 노드를 뺀다 — 고립 정리보다 먼저.** 나중에 빼면
    # 그것만 사라진 자리에 이웃이 점으로 남는다. 순서를 지키면 고립 검사가
    # 최종 노드 집합을 본다.
    undescribed: set[str] = set()
    if drop_undescribed:
        undescribed = _undescribed(store, keep)
        keep -= undescribed
        log.info("설명 없는 노드 %d개 제외 (남은 노드 %d)", len(undescribed), len(keep))

    isolated: set[str] = set()
    if drop_isolated:
        # 엣지가 하나도 없는 노드는 그래프에서 할 일이 없다. 실측: 조선
        # 인물 2,923명 중 상당수가 Wikidata 에서 노드만 오고 관계가 없어
        # 화면에 점으로만 떠 있게 된다.
        connected: set[str] = set()
        ordered_all = sorted(keep)
        for i in range(0, len(ordered_all), 500):
            batch = ordered_all[i : i + 500]
            marks = ",".join("?" * len(batch))
            for r in store.conn.execute(
                f"SELECT src, dst FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
                (*batch, *batch),
            ):
                connected.add(r["src"])
                connected.add(r["dst"])
            for r in store.conn.execute(
                f"SELECT a, b FROM same_as WHERE a IN ({marks}) OR b IN ({marks})",
                (*batch, *batch),
            ):
                connected.add(r["a"])
                connected.add(r["b"])
        isolated = keep - connected
        keep &= connected
        # **연대를 아는 사건은 엣지가 없어도 남긴다.** 고립 노드를 버리는
        # 이유는 화면에 점으로만 뜨기 때문인데, 연표에서는 '언제'라는 값
        # 하나로 제 몫을 한다. 실측: 경술국치(한일병합, 1910-08-29)가
        # 엣지 0개라 조선 그래프에서 통째로 빠져 있었다.
        rescued = _dated_events(store, isolated & seeds)
        if rescued:
            keep |= rescued
            isolated -= rescued
        log.info(
            "고립 노드 %d개 제외 (연대 있는 사건 %d개는 남김 · 남은 노드 %d)",
            len(isolated), len(rescued), len(keep),
        )

    out = Path(out_path)
    # **이미 배포된 주소를 먼저 건진다.** 파생본은 저장소에 실려 나가므로
    # 여기 든 주소가 곧 색인에 올라 있는 주소다 (원본 DB 는 저장소에 없다).
    # 다시 만들면서 이걸 버리면 남의 검색 결과에 걸린 주소가 통째로 죽는다.
    published = _published_slugs(out)
    if out.exists():
        out.unlink()
    dest = GraphStore(out)

    ordered = sorted(keep)
    node_rows, edge_rows, alias_rows, name_rows, summary_rows = [], [], [], [], []
    override_rows: list = []
    slug_rows: list = []
    for i in range(0, len(ordered), 500):
        batch = ordered[i : i + 500]
        marks = ",".join("?" * len(batch))
        node_rows += store.conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({marks})", batch
        ).fetchall()
        # **별칭도 함께 옮긴다.** 안 옮기고 있었다 — 전체 그래프에 5,064건이
        # 있는데 시대 그래프에는 0건이었다. 화면이 읽는 것은 시대 그래프라,
        # 이 프로젝트가 내세우는 "'이방원'으로 태종을 찾는다"가 정작
        # 화면에서는 한 번도 동작한 적이 없었다.
        name_rows += store.conn.execute(
            f"SELECT * FROM aliases WHERE node_id IN ({marks})", batch
        ).fetchall()
        # 한쪽 끝만 배치에 걸고 가져온 뒤 파이썬에서 양끝을 검사한다.
        # SQL 에서 `src IN (batch) AND dst IN (batch)` 로 거르면 배치를
        # 넘나드는 엣지가 통째로 사라진다 — 5,143 노드에 엣지가 313개만
        # 남았던 원인이 이것이었다.
        edge_rows += store.conn.execute(
            f"SELECT * FROM edges WHERE src IN ({marks})", batch
        ).fetchall()
        alias_rows += store.conn.execute(
            f"SELECT * FROM same_as WHERE a IN ({marks})", batch
        ).fetchall()
        # 우리 말로 새로 쓴 설명(summaries.py)도 함께 — 안 옮기면 화면이
        # 위키 원문 도입부로 물러난다.
        summary_rows += store.conn.execute(
            f"SELECT * FROM summaries WHERE node_id IN ({marks})", batch
        ).fetchall()
        # **주소도 따라간다** (`slugs.py`). 파생본에서 새로 지으면 같은
        # 노드가 두 주소를 갖는다 — 이름이 겹치던 노드 하나가 파생본에
        # 없으면 남은 쪽이 맨 이름을 차지하기 때문이다. 옛 주소(current=0)
        # 도 함께 옮긴다: 색인에 올라 있는 주소가 301 을 잃으면 안 된다.
        slug_rows += store.conn.execute(
            f"SELECT * FROM slugs WHERE node_id IN ({marks})", batch
        ).fetchall()
        # 편집 계층도 따라간다 — 파생본에 `relabel` 을 또 돌리지 않아도
        # 고친 이름·정본·재위가 그대로 서고, 파생본 위의 수집도 되돌린다.
        override_rows += store.conn.execute(
            f"""SELECT * FROM overrides
                 WHERE (target = 'node' AND key IN ({marks}))
                    OR (target = 'edge' AND substr(key, 1, instr(key, char(9)) - 1) IN ({marks}))""",
            batch + batch,
        ).fetchall()

    edge_rows = [r for r in edge_rows if r["dst"] in keep]
    alias_rows = [r for r in alias_rows if r["b"] in keep]

    cols = "id,type,label,source,start_date,end_date,lat,lon,description,url,props,updated_at"
    dest.conn.executemany(
        f"INSERT OR REPLACE INTO nodes ({cols}) VALUES ({','.join('?' * 12)})",
        [tuple(r[c] for c in cols.split(",")) for r in node_rows],
    )
    dest.conn.executemany(
        "INSERT OR IGNORE INTO aliases (node_id, alias) VALUES (?,?)",
        [(r["node_id"], r["alias"]) for r in name_rows],
    )
    ecols = "src,dst,type,source,label,start_date,end_date,confidence,props"
    dest.conn.executemany(
        f"INSERT OR REPLACE INTO edges ({ecols}) VALUES ({','.join('?' * 9)})",
        [tuple(r[c] for c in ecols.split(",")) for r in {
            (r["src"], r["dst"], r["type"], r["source"]): r for r in edge_rows
        }.values()],
    )
    dest.conn.executemany(
        "INSERT OR REPLACE INTO same_as (a,b,method,score) VALUES (?,?,?,?)",
        [(r["a"], r["b"], r["method"], r["score"]) for r in {
            (r["a"], r["b"]): r for r in alias_rows
        }.values()],
    )
    dest.conn.executemany(
        "INSERT OR REPLACE INTO summaries (node_id,text,model,src_hash,made_at) VALUES (?,?,?,?,?)",
        [(r["node_id"], r["text"], r["model"], r["src_hash"], r["made_at"]) for r in summary_rows],
    )
    dest.conn.executemany(
        "INSERT OR REPLACE INTO slugs (segment,slug,node_id,current,made_at) VALUES (?,?,?,?,?)",
        _merge_slugs(published, slug_rows, keep),
    )
    ocols = "target,key,field,value,origin,reason,apply_when,made_at"
    dest.conn.executemany(
        f"INSERT OR REPLACE INTO overrides ({ocols}) VALUES ({','.join('?' * 8)})",
        [tuple(r[c] for c in ocols.split(",")) for r in {
            (r["target"], r["key"], r["field"]): r for r in override_rows
        }.values()],
    )
    dest.conn.commit()

    stats = dest.stats()
    dest.close()
    return {
        "era": " · ".join(e.name for e in eras),
        "out": str(out),
        "seeds": len(seeds),
        "undescribed_dropped": len(undescribed),
        "isolated_dropped": len(isolated),
        "kept_aliases": len(name_rows),
        "kept_slugs": len(slug_rows),
        "kept_nodes": stats["nodes_total"],
        "kept_edges": stats["edges_total"],
        "by_node_type": stats["by_node_type"],
        "by_edge_type": stats["by_edge_type"],
        "dangling": stats["dangling_edges"],
    }


def _published_slugs(out) -> list[tuple]:
    """다시 만들기 **전** 파생본이 들고 있던 주소들. 파일이 없거나 표가
    없으면 빈 목록이다 (주소를 쓰기 전에 만든 파생본)."""
    import sqlite3
    from pathlib import Path as _Path

    path = _Path(out)
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [(r["segment"], r["slug"], r["node_id"], r["current"], r["made_at"])
                for r in conn.execute("SELECT * FROM slugs")]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _merge_slugs(published: list[tuple], source_rows, keep: set[str]) -> list[tuple]:
    """이미 나간 주소가 원본의 주소를 이긴다.

    같은 노드에 둘이 다르면 나간 쪽이 지금 주소이고 원본 쪽은 옛 주소로
    내려앉는다 — 어느 쪽도 버리지 않으므로 둘 다 그 장으로 이어진다."""
    rows = [r for r in published if r[2] in keep]
    paths = {(r[0], r[1]) for r in rows}
    nodes = {r[2] for r in rows if r[3]}
    for r in source_rows:
        key = (r["segment"], r["slug"])
        if key in paths:
            continue
        current = int(bool(r["current"]) and r["node_id"] not in nodes)
        rows.append((r["segment"], r["slug"], r["node_id"], current, r["made_at"]))
        paths.add(key)
        if current:
            nodes.add(r["node_id"])
    return rows


def sweep_undescribed(conn) -> dict[str, int]:
    """파생본에서 설명 없는 내용 노드를 지운다 — `redescribe` 뒤의 두 번째 빗질.

    `extract` 가 이미 한 번 걸렀는데도 이게 필요한 이유: `cmd_scope` 는
    파생본을 만든 **뒤에** `redescribe` 를 돌리고, 그것은 한국어로 옮기지
    못한 설명을 **비운다**. 그래서 복사할 때는 차 있던 칸이 그 다음에
    빈다. 한 번만 거르면 그 노드들이 그대로 화면에 선다.

    엣지·별칭·same_as 도 같이 지운다. 남기면 없는 곳을 가리키는 엣지가
    된다."""
    kinds = ",".join(f"'{t}'" for t in UNDESCRIBED_DROP_TYPES)  # 코드 안의 고정 목록
    ids = [
        r[0] for r in conn.execute(
            f"""SELECT id FROM nodes WHERE type IN ({kinds})
                 AND (description IS NULL OR trim(description) = '')"""
        )
    ]
    if not ids:
        return {"nodes": 0, "edges": 0}
    edges = 0
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        marks = ",".join("?" * len(batch))
        edges += conn.execute(
            f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})",
            (*batch, *batch),
        ).rowcount
        conn.execute(
            f"DELETE FROM same_as WHERE a IN ({marks}) OR b IN ({marks})",
            (*batch, *batch),
        )
        conn.execute(f"DELETE FROM aliases WHERE node_id IN ({marks})", batch)
        conn.execute(f"DELETE FROM nodes WHERE id IN ({marks})", batch)
    conn.commit()
    return {"nodes": len(ids), "edges": max(edges, 0)}
