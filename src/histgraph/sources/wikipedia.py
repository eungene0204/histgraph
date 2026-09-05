"""한국어 위키백과 커넥터 — 서사 코퍼스 공급.

**왜 필요한가.** 국가유산청 `content` 2,903건은 유물 해설문이라
"이 물건이 무엇인가"를 적은 글이다 (27%는 순수 서지·규격 기술). 우리가
필요한 건 "누가 무엇을 했는가"인데, 그건 인물·사건 항목의 서사에 있다.
실록과 백과사전은 활용신청 대기 중이라, 지금 당장 막힘 없이 쓸 수 있는
서사 코퍼스는 한국어 위키백과뿐이다.

**설계.** 새 노드를 만들지 않는다. Wikidata 항목에는 한국어 위키백과
sitelink 가 달려 있으므로, 이미 그래프에 있는 노드의 `description` 을
채우는 방식으로 붙인다. 새로 만들면 엔티티 해소를 또 해야 하지만,
sitelink 를 쓰면 QID 가 곧 키라서 정확히 같은 노드에 꽂힌다.

인증키 불필요. User-Agent 는 반드시 보내야 한다 — 없으면 Wikimedia 가
차단한다(실측: 빈 UA 로 요청하면 'Wikimedia Error' HTML 이 돌아온다).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from ..http import Fetcher
from ..store import GraphStore

log = logging.getLogger(__name__)

API_URL = "https://ko.wikipedia.org/w/api.php"
SOURCE = "kowiki"

# extracts 는 인트로만 받을 때 한 번에 20건, 본문 전체는 1건이 상한이다.
INTRO_BATCH = 20

# 한국사 주요 사건 시드 목록.
#
# 분류 순회를 먼저 시도했으나 쓸 수 없었다. 한국어 위키백과의 사건 분류는
# 일관성이 없고('한국의_전쟁', '조선의_사건' 등은 아예 없음), 실제 문서에
# 달린 분류는 '1636년 분쟁', '깨진 링크를 가지고 있는 문서' 같은 연도·정비
# 분류가 대부분이다. 도메인 지식으로 직접 나열하는 편이 정확하다.
#
# 시대별로 묶어두면 사건마다 from_period 엣지를 공짜로 얻는다.
EVENT_SEEDS: dict[str, list[str]] = {
    "고구려": ["살수대첩", "안시성 전투", "여수전쟁", "고구려-당 전쟁"],
    "백제": ["황산벌 전투", "관산성 전투", "백강 전투"],
    "신라": [
        "나당전쟁", "매소성 전투", "기벌포 전투", "비담의 난",
        "김헌창의 난", "장보고", "원종·애노의 난",
    ],
    "고려": [
        "거란의 고려 침입", "귀주 대첩", "강조의 정변", "이자겸의 난",
        "묘청의 난", "무신정변", "만적의 난", "고려-몽골 전쟁",
        "처인성 전투", "삼별초", "홍건적의 고려 침공", "황산대첩",
        "진포 해전", "위화도 회군",
    ],
    "조선": [
        # 전기
        "제1차 왕자의 난", "제2차 왕자의 난", "계유정난", "이시애의 난",
        "무오사화", "갑자사화", "중종반정", "기묘사화", "을사사화",
        "삼포왜란", "을묘왜변",
        # 임진왜란
        "임진왜란", "정유재란", "한산도 대첩", "명량 해전", "노량 해전",
        "행주 대첩", "진주성 전투", "칠천량 해전",
        # 후기
        "인조반정", "이괄의 난", "정묘호란", "병자호란", "삼전도의 굴욕",
        "예송논쟁", "경신환국", "기사환국", "갑술환국", "임오화변",
        "홍경래의 난", "임술농민봉기", "신유박해", "기해박해", "병인박해",
        "병인양요", "신미양요", "운요호 사건", "강화도 조약",
    ],
    "대한제국": [
        # '대한제국' 자체는 국가이지 사건이 아니다. 시대 이름과도 같아서
        # 넣으면 from_period 가 자기 자신을 가리키는 자기순환이 된다.
        "임오군란", "갑신정변", "동학 농민 혁명", "갑오개혁", "을미사변",
        "아관파천", "을사조약", "헤이그 특사", "정미의병",
        "국채보상운동", "한일병합조약",
        # 구한말은 조약과 의병으로 끝난다. 조약만 넣으면 당한 쪽이 없고,
        # 의병만 넣으면 무엇에 맞선 것인지가 없다.
        "거문도 사건", "방곡령", "만민공동회", "광무개혁",
        "청일 전쟁", "러일 전쟁", "가쓰라-태프트 밀약",
        "제1차 한일 협약", "한일신협약", "기유각서",
        "을미의병", "서울 진공 작전",
        "대한제국군 해산", "남한 대토벌 작전", "이토 히로부미 저격 사건",
    ],
    # 일제강점기 35년의 사건 노드가 13개였다. 씨앗이 11개였기 때문이고,
    # 그중 이봉창·윤봉길은 사람이라 사건 노드로 앉아 있었다 (reclassify 가
    # 나중에 인물로 옮겼다). **사람과 단체는 이 표에 넣지 않는다** —
    # 아래 ORG_SEEDS 로 갔다.
    "일제강점기": [
        "3·1 운동", "2·8 독립 선언", "105인 사건", "제암리 학살 사건",
        "6·10 만세 운동", "광주 학생 항일 운동", "물산장려운동",
        "민립대학설립운동", "브나로드 운동", "형평사 운동",
        "암태도 소작쟁의", "원산 총파업", "조선어학회 사건",
        # 무장 투쟁
        "봉오동 전투", "청산리 전투", "훈춘 사건", "간도참변", "자유시 참변",
        "대전자령 전투", "보천보 습격",
        "훙커우 공원 사건", "종로경찰서 폭탄투척 사건",
        # 통치와 수탈 — 정책이되 기간과 주체가 있는 '사업'이다.
        # 통치 방식 자체(무단 통치·창씨개명)는 사건이 아니라 개념이다.
        "조선 토지 조사 사업", "산미증식계획",
        # 밖에서 온 사건. 이것들이 없으면 왜 하필 그 해에 그 일이
        # 일어났는지가 그래프에서 사라진다.
        "만보산 사건", "만주사변", "중일 전쟁", "태평양 전쟁",
        "간토 대학살", "국민대표회의", "카이로 회담", "일본의 항복",
    ],
    # 1945년 뒤는 사건 12건이었다. 인물은 18,471명인데 사건이 없으니 그
    # 시대는 명단이었다. 대통령 띠(`reigns`)가 세워지면서 그 옆에 설
    # 사건이 필요해졌다 — 정부 수립부터 지금까지, 대통령마다 그 임기를
    # 읽게 하는 사건들이다.
    #
    # **문서명은 전부 조회로 확인한 것이다** (2026-09-04, 넘겨주기 포함).
    # 추측한 이름 중 '8·15 광복'은 광복절(기념일)로, '김구 암살 사건'은
    # 엉뚱한 문서로, '이한열 사망 사건'은 6월 항쟁으로 넘어갔다 — 그런
    # 것은 뺐다. 경부고속도로(장소)·1988년 올림픽(스포츠, `prune` 이
    # 지운다)·이산가족을 찾습니다(방송)도 사건이 아니라 뺐다.
    "대한민국": [
        # 해방 정국
        "모스크바 삼국 외상 회의", "신탁 통치 반대 운동", "미소공동위원회",
        "정읍 발언", "대구 10·1 사건", "제주 4·3 사건",
        "대한민국 제헌 국회의원 선거", "대한민국 정부 수립",
        "여수·순천 사건", "국회 프락치 사건",
        # 전쟁
        "한국 전쟁", "낙동강 방어선 전투", "다부동 전투", "인천 상륙 작전",
        "흥남 철수 작전", "1·4 후퇴", "장진호 전투", "백마고지 전투",
        "국민방위군 사건", "거창 양민 학살 사건", "보도연맹 학살 사건",
        "한국 군사 정전에 관한 협정", "한미상호방위조약",
        # 제1·2공화국
        "부산 정치 파동", "사사오입 개헌", "진보당 조봉암 사건",
        "3·15 부정선거", "4·19 혁명",
        # 제3·4공화국
        "5·16 군사 정변", "6·3 항쟁", "한일기본조약",
        "대한민국 국군의 베트남 전쟁 참전", "1·21 사태", "푸에블로함 피랍 사건",
        "울진·삼척 무장공비 침투 사건", "삼선 개헌", "7·4 남북 공동 성명",
        "10월 유신", "김대중 납치 사건", "민청학련 사건", "인민혁명당 사건",
        "육영수 저격 사건", "판문점 도끼 만행 사건", "YH 사건",
        "부마민주항쟁", "10·26 사건",
        # 제5·6공화국
        "12·12 군사 반란", "서울의 봄", "5·17 내란", "5·18 광주 민주화 운동",
        "언론통폐합", "대한항공 007편 격추 사건", "박종철 고문치사 사건",
        "6월 항쟁", "6·29 선언", "대한항공 858편 폭파 사건",
        "제5공화국 청문회", "3당 합당", "남북 기본합의서",
        "한반도의 비핵화에 관한 공동선언",
        "성수대교 붕괴 사고", "삼풍백화점 붕괴 사고",
        "대한민국의 IMF 구제금융 요청",
        "제1연평해전", "2000년 남북정상회담", "6·15 남북 공동선언", "제2연평해전",
        "대구 지하철 화재 참사", "노무현 대통령 탄핵소추", "2007년 남북정상회담",
        "한미 자유 무역 협정",
        "2008년 대한민국 촛불 시위", "용산4구역 철거현장 화재",
        "천안함 피격 사건", "연평도 포격전", "4대강 정비 사업",
        "세월호 침몰 사고", "2015년 대한민국의 중동호흡기증후군 유행",
        "박근혜-최순실 게이트", "박근혜 대통령 퇴진 운동", "박근혜 대통령 탄핵",
        "2018년 남북정상회담", "판문점 선언", "제1차 조미수뇌회담",
        "대한민국의 코로나19 범유행",
        "이태원 참사", "12.3 내란", "윤석열 대통령 탄핵",
        "제주항공 2216편 활주로 이탈 사고",
        "대한민국 제21대 대통령 선거",
    ],
}

# 단체 시드. **사건 표와 갈라 둔 이유는 타입이 다르기 때문이다.**
# `upsert_nodes` 는 type 을 덮어쓰지 않으므로 이미 org 로 앉은 신간회는
# 안전하지만, 처음 들어오는 단체를 사건 표에 넣으면 그대로 사건 노드가
# 된다 — 화면의 '이 시대의 사건'이 단체 목록으로 채워진다.
#
# 일제강점기는 특히 단체의 시대다. 무장 투쟁도 외교도 개인이 아니라
# 조직 이름으로 남아 있어서, 단체를 빼면 인물과 사건 사이가 끊긴다.
ORG_SEEDS: dict[str, list[str]] = {
    "대한제국": [
        "독립협회", "신민회", "대한자강회", "황국협회", "보안회",
        # 의병 부대는 사건이 아니라 조직이다 — 서울 진공 작전을
        # 벌인 쪽이 13도 창의군이고, 둘을 한 노드로 두면 누가
        # 무엇을 했는지가 사라진다.
        "13도 창의군",
    ],
    "일제강점기": [
        # 임시정부와 그 군대
        "대한민국 임시정부", "대한민국 임시의정원", "한국 광복군",
        # 무장 단체
        "북로군정서", "서로군정서", "대한독립군", "신흥무관학교",
        "한국독립군", "조선혁명군정부", "조선의용대", "조선의용군",
        # 의열 투쟁
        "의열단", "한인애국단", "대한광복단", "대한애국청년당",
        # 국내 운동과 정당
        "신간회", "근우회", "조선공산당", "한국독립당", "조선민족혁명당",
        "조선노농총동맹", "조선청년총동맹", "건국동맹",
        # 통치 기구 — 맞선 쪽만 넣으면 무엇에 맞섰는지가 없다
        "조선총독부", "동양척식주식회사", "조선사편수회", "경성제국대학",
    ],
    # 대한민국은 정당과 기관의 시대다. 정변을 일으킨 쪽(하나회·국보위)과
    # 그것을 뒤집은 쪽이 다 이름을 가진 단체다. 정당은 이름이 자주 바뀌어
    # 넘겨주기가 지금 이름으로 간다 — 그런 것(한나라당→자유한국당)은 넣지
    # 않았다. 문서명은 전부 조회로 확인했다.
    "대한민국": [
        "재조선 미국 육군사령부 군정청", "남조선과도정부",
        "반민족행위특별조사위원회", "자유당 (대한민국)",
        "국가재건최고회의", "민주공화당 (대한민국)", "대한민국 중앙정보부",
        "통일주체국민회의", "신민당 (1967년)", "하나회",
        "국가보위비상대책위원회", "민주정의당", "통일민주당", "평화민주당",
        "새정치국민회의", "열린우리당", "더불어민주당", "국민의힘",
        "전국민주노동조합총연맹", "한국노동조합총연맹", "대한민국 국가정보원",
    ],
}

# 개념 시드. 무단 통치·창씨개명은 사건이 아니다 — 시작한 날도 끝난 날도
# 하나로 적을 수 없고, '누가 참여했나'를 물을 수 없다. concept 타입이
# 생긴 자리가 여기다 (README '개념이 사건 행세를 하고 있었다').
CONCEPT_SEEDS: dict[str, list[str]] = {
    "일제강점기": [
        "무단 통치", "문화 통치", "민족말살통치",
        "창씨개명", "황국신민서사", "국가총동원법", "회사령",
        "징용", "일본군 위안부",
    ],
    # 제도와 정책. 유신은 헌법이고 새마을은 운동이라 '언제 일어났나'를
    # 하나로 적을 수 없다.
    "대한민국": [
        "농지개혁법", "대한민국의 경제 개발 5개년 계획", "새마을 운동",
        "대한민국 헌법 제8호", "긴급조치", "국가보안법 (대한민국)",
        "금융실명제", "햇볕정책",
    ],
}


def fetch_titles(
    fetcher: Fetcher,
    qids: list[str],
    chunk: int = 200,
    unresolved: set[str] | None = None,
) -> dict[str, str]:
    """Wikidata QID -> 한국어 위키백과 문서명.

    노드 라벨을 그대로 문서명으로 쓰면 안 된다. 우리 라벨은 '조선 세종'
    인데 실제 문서명은 '세종'이라 조회가 빗나간다. sitelink 가 정답이다.

    `unresolved` 를 주면 **조회 자체가 실패한 구간의 QID** 를 담아 준다.
    결과에서 빠진 QID 는 두 가지다 — 문서가 정말 없거나, 쿼리가 죽어서
    못 물어봤거나. 둘을 섞으면 타임아웃 한 번에 200개가 '문서 없음'으로
    영구 표시된다. 호출부가 구분할 수 있어야 한다."""
    from .wikidata import _qid, _safe_query, _val

    out: dict[str, str] = {}
    failures: list[str] = []
    ordered = sorted(set(qids))

    for i in range(0, len(ordered), chunk):
        batch = ordered[i : i + chunk]
        values = " ".join(f"wd:{q}" for q in batch)
        before = len(failures)
        rows = _safe_query(
            fetcher,
            f"""SELECT ?item ?title WHERE {{
                  VALUES ?item {{ {values} }}
                  ?a schema:about ?item ;
                     schema:isPartOf <https://ko.wikipedia.org/> ;
                     schema:name ?title .
                }}""",
            f"sitelink/{i}",
            failures,
        )
        if len(failures) > before and unresolved is not None:
            unresolved.update(batch)
        for r in rows:
            item, title = _val(r, "item"), _val(r, "title")
            if item and title:
                out[_qid(item)] = title

    if failures:
        log.warning(
            "sitelink 조회 실패 %d구간 — QID %d개는 문서 유무를 모른다",
            len(failures), len(unresolved or ()),
        )
    log.info("QID %d개 중 한국어 위키백과 문서 %d개 확인", len(ordered), len(out))
    return out


def _api(fetcher: Fetcher, params: dict[str, str]) -> dict:
    raw = fetcher.get(API_URL, params)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        # UA 누락이면 JSON 이 아니라 HTML 오류 페이지가 온다
        hint = "User-Agent 문제일 수 있음" if raw.lstrip().startswith("<") else ""
        raise RuntimeError(f"위키백과 응답 파싱 실패: {raw[:150]} {hint}") from err


# --- 작품 문서에서 걷어낼 절 --------------------------------------------
# **배우 이름은 역사 인물이 아니다.** 작품 문서의 '등장 인물' 절은 배역과
# 배우가 뒤섞인 목록이라, 그대로 추출에 넣으면 배우가 역사 인물로 승격된다.
# README 의 "족보 목록은 모델을 망가뜨린다 — 지우고 넣는다"와 같은 함정이고,
# 처방도 같다: 넣기 전에 지운다.
#
# 시청률·수상·각주 같은 절도 함께 걷는다. 관계가 없는 글이라 조각 예산만
# 잡아먹는다. 반대로 '역사적 사실'·'역사와 다른 점'은 **남긴다** — 작품이
# 무엇을 다루는지, 어디가 고증과 다른지를 그 절이 말한다.
CUT_SECTIONS = re.compile(
    r"^(?:등장\s*인물|등장인물|인물\s*소개|주요\s*인물|출연|출연진|캐스팅|배역|"
    r"제작진|스태프|스탭|촬영|시청률|수상|수상\s*경력|수상\s*목록|방영\s*목록|"
    r"편성|연장|결방|음반|사운드\s*트랙|OST|삽입곡|주제가|"
    r"각주|주석|참고\s*자료|참고\s*문헌|참고\s*사항|같이\s*보기|외부\s*링크|"
    r"관련\s*항목|더\s*보기)$"
)

_HEADING = re.compile(r"^(=+)[ \t]*(.+?)[ \t]*=+[ \t]*$", re.M)


def strip_sections(text: str, cut: re.Pattern[str] = CUT_SECTIONS) -> str:
    """지정한 절과 그 아래 하위 절을 통째로 걷어낸다.

    같은 수준 이상의 다음 제목이 나올 때까지 자른다 — '등장 인물' 밑에
    '대조영의 여인' 같은 하위 절이 줄줄이 달려 있어서, 제목 줄만 지우면
    배우 이름은 그대로 남는다."""
    heads = [
        (m.start(), m.end(), len(m.group(1)), m.group(2)) for m in _HEADING.finditer(text)
    ]
    keep: list[str] = []
    cursor = 0
    i = 0
    while i < len(heads):
        start, _end, level, title = heads[i]
        if not cut.match(title):
            i += 1
            continue
        keep.append(text[cursor:start])
        # 같은 수준 이상(=숫자가 같거나 작은) 제목이 나오는 곳까지 버린다
        j = i + 1
        while j < len(heads) and heads[j][2] > level:
            j += 1
        cursor = heads[j][0] if j < len(heads) else len(text)
        i = j
    keep.append(text[cursor:])
    return re.sub(r"\n{3,}", "\n\n", "".join(keep)).strip()


def fetch_extracts(
    fetcher: Fetcher,
    titles: list[str],
    full: bool = False,
    resolved_from: dict[str, str] | None = None,
    redirected: set[str] | None = None,
) -> dict[str, str]:
    """문서명 -> 본문 텍스트. 키는 **응답이 돌려준 문서명**이다.

    full=False 는 도입부만 받는다 (인물 항목 기준 900~1,400자). 한 번에
    20건이라 빠르고 싸다. full=True 는 본문 전체지만 요청당 1건이다.

    `redirects=1` 이라 응답의 문서명이 요청한 것과 달라질 수 있다
    ('신숙공주' → '순숙공주'). `resolved_from` 을 주면 {받은 이름:
    요청한 이름} 을 담아 준다. 이게 없으면 호출부가 요청한 이름으로
    결과를 찾다가 못 찾고 **넘겨주기 문서를 통째로 버린다** — 조선
    그래프에서 실제로 4건이 그렇게 빈 설명으로 남아 있었다.

    `redirected` 는 **진짜 넘겨주기로 온 문서명**만 담는다. 이름이
    달라지는 이유는 둘인데, 넘겨주기(다른 문서로 보냄)와 정규화(밑줄·
    공백 같은 표기 손질)는 뜻이 전혀 다르다. 정규화까지 넘겨주기로 세면
    같은 문서를 두고 "다른 문서에서 넘겨받았다"고 적게 된다."""
    out: dict[str, str] = {}
    batch_size = 1 if full else INTRO_BATCH

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "exlimit": str(batch_size),
            "redirects": "1",  # '조선 세종' 같은 넘겨주기도 따라간다
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(batch),
        }
        if not full:
            params["exintro"] = "1"

        try:
            data = _api(fetcher, params)
        except RuntimeError as err:
            log.warning("추출 실패 (건너뜀): %s", err)
            continue

        # 요청한 이름으로 되짚을 수 있게 넘겨주기·정규화를 모아둔다
        back = {
            r["to"]: r["from"] for r in data.get("query", {}).get("redirects", [])
        }
        norm = {
            r["to"]: r["from"] for r in data.get("query", {}).get("normalized", [])
        }

        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            text = (page.get("extract") or "").strip()
            if text:
                title = page["title"]
                out[title] = text
                if title in back and redirected is not None:
                    redirected.add(title)
                if resolved_from is not None:
                    requested = back.get(title, title)
                    resolved_from[title] = norm.get(requested, requested)

        if i and i % 200 == 0:
            log.info("  본문 %d/%d건 수집", i, len(titles))

    return out


def fetch_articles(
    fetcher: Fetcher, titles: list[str], full: bool = False
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """문서명 -> {qid, extract, title}. 없는 문서명 목록도 함께 돌려준다.

    extracts 와 pageprops 를 한 요청으로 받는다. QID 를 같이 받아야
    사건 노드를 `wd:Qxxxx` 로 만들 수 있고, 그래야 이미 그래프에 있는
    Wikidata 사건 노드와 자동으로 합쳐진다.

    full=True 는 본문 전체를 받는다. 사건 항목은 도입부가 짧아(평균 380자)
    "누가 무엇을 했는가"가 대부분 본문에 있으므로 사건 수집에는 이쪽이 맞다.
    대신 요청당 1건이라 느리다."""
    found: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    batch_size = 1 if full else INTRO_BATCH

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action": "query",
            "prop": "extracts|pageprops",
            "ppprop": "wikibase_item",
            "explaintext": "1",
            "exlimit": str(batch_size),
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
            "titles": "|".join(batch),
        }
        if not full:
            params["exintro"] = "1"
        try:
            data = _api(fetcher, params)
        except RuntimeError as err:
            log.warning("사건 조회 실패 (건너뜀): %s", err)
            missing.extend(batch)
            continue

        # redirects 를 따라가면 응답 title 이 요청 title 과 달라진다.
        # 어느 쪽 이름으로 요청했는지 되짚을 수 있게 매핑을 보관한다.
        redirect_from = {
            r["to"]: r["from"] for r in data.get("query", {}).get("redirects", [])
        }
        normalized = {
            r["to"]: r["from"] for r in data.get("query", {}).get("normalized", [])
        }

        for page in data.get("query", {}).get("pages", []):
            title = page["title"]
            requested = redirect_from.get(title, title)
            requested = normalized.get(requested, requested)
            if page.get("missing"):
                missing.append(requested)
                continue
            qid = page.get("pageprops", {}).get("wikibase_item")
            extract = (page.get("extract") or "").strip()
            if not qid or not extract:
                missing.append(requested)
                continue
            found[requested] = {"qid": qid, "extract": extract, "title": title}

    return found, missing


def ingest_seeds(
    fetcher: Fetcher,
    store: GraphStore,
    seeds: dict[str, list[str]],
    node_type: str = "event",
    full: bool = True,
) -> tuple[list[Node], list[Edge]]:
    """시드 목록의 문서를 수집해 `node_type` 노드로 만든다.

    차수 상위순으로 고르는 `enrich` 로는 임진왜란·병자호란 같은 핵심
    사건이 잡히지 않는다 — Wikidata 상에서 연결이 적기 때문이다. 이름으로
    직접 지정하는 경로가 따로 필요한 이유다.

    **타입을 인자로 받는 이유.** 시드는 사건만이 아니다. 일제강점기를
    넣으면서 단체(의열단·조선총독부)와 개념(창씨개명)이 같은 방식으로
    필요해졌는데, 한 표에 몰아넣으면 전부 사건 노드가 된다. 표를 갈라
    두고 타입을 여기서 정한다."""
    from ..ontology import Edge, Node
    from ..resolve import PERIOD_TO_POLITY, POLITY_NODE_TYPE

    all_titles = [t for titles in seeds.values() for t in titles]
    title_to_era = {t: era for era, titles in seeds.items() for t in titles}

    log.info("%s 문서 %d건 조회 중 (full=%s)...", node_type, len(all_titles), full)
    found, missing = fetch_articles(fetcher, all_titles, full=full)
    if missing:
        # 문서명이 틀렸는지 실제로 없는지 구분이 안 되므로 반드시 보고한다
        log.warning("문서를 찾지 못함 %d건: %s", len(missing), ", ".join(missing))

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for requested, info in found.items():
        nid = f"wd:{info['qid']}"
        era = title_to_era.get(requested, "")
        nodes[nid] = Node(
            id=nid,
            type=node_type,
            label=info["title"],
            source="wd",  # QID 공간을 공유해야 기존 노드와 합쳐진다
            description=info["extract"],
            url=f"https://www.wikidata.org/entity/{info['qid']}",
            props={
                "kowiki_url": f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(info['title'])}",
                "seed_era": era,
                "seeded": True,
            },
        )
        # 시대 묶음에서 from_period 엣지를 공짜로 얻는다
        polity_qid = PERIOD_TO_POLITY.get(era)
        if polity_qid:
            pid = f"wd:{polity_qid}"
            # 시드 항목이 그 시대의 정체 자신인 경우(예: '대한제국')
            # 자기 자신을 가리키는 엣지가 된다. 방어해둔다.
            if pid != nid:
                nodes.setdefault(
                    pid,
                    Node(
                        id=pid,
                        type=POLITY_NODE_TYPE.get(era, "org"),
                        label=era,
                        source="wd",
                    ),
                )
                edges.append(
                    Edge(src=nid, dst=pid, type="from_period", source="kowiki")
                )

    log.info("%s 노드 %d개, 시대 엣지 %d개", node_type, len(nodes), len(edges))
    return list(nodes.values()), edges


def ingest_events(
    fetcher: Fetcher,
    store: GraphStore,
    seeds: dict[str, list[str]] | None = None,
    full: bool = True,
) -> tuple[list[Node], list[Edge]]:
    """사건 시드. `ingest_seeds` 의 사건 전용 입구."""
    return ingest_seeds(fetcher, store, seeds or EVENT_SEEDS, "event", full=full)


# 그래프에 있는 wd 노드 타입 전부. 예전 기본값은 ('person','event') 였고,
# 그래서 장소 350·직위 33·단체 77개는 한 번도 조회된 적이 없다.
ALL_WD_TYPES: tuple[str, ...] = (
    "person", "event", "place", "org", "role", "media", "artwork", "period",
)


def enrich(
    fetcher: Fetcher,
    store: GraphStore,
    node_types: tuple[str, ...] = ALL_WD_TYPES,
    limit: int | None = None,
    full: bool = False,
    refresh: bool = False,
    scope_ids: set[str] | None = None,
    fallback: bool = True,
) -> dict[str, int]:
    """그래프의 Wikidata 노드에 위키백과 서사를 채운다.

    **왜 빈 칸이 남았는가.** 예전에는 차수 상위 500개만 받았다. 그래서
    '사량진왜변'(차수 1)처럼 연결이 하나뿐인 노드는 순번이 오지 않았다.
    화면에서 설명이 비어 있던 조선 그래프 노드 2,796개 중 2,227개가
    인물이고, 그 평균 차수는 2.1 이다 — 설명 있는 인물의 평균은 8.4 다.
    빠진 것은 '자료가 없는 노드'가 아니라 '순번이 오지 않은 노드'였다.
    그래서 `limit` 의 기본값을 없앴다. 차수 정렬은 남긴다 — 중간에 끊어도
    많이 연결된 것부터 채워지는 편이 낫다.

    **그래도 남는 것.** 실측으로 표본 300개 중 56개(19%)는 한국어
    위키백과 문서가 아예 없다. 이건 다시 돌려도 안 채워지므로
    `props.no_kowiki` 로 표시해 다음 실행이 같은 헛수고를 반복하지 않게
    한다(`--refresh` 면 그 표시도 무시하고 다시 본다). 그 노드들은
    Wikidata 한 줄 설명으로 대신 채운다(`fallback`).
    """
    marks = ",".join("?" * len(node_types))
    # refresh=True 면 이미 산문이 있는 노드도 다시 받는다. 도입부만 받아둔
    # 인물을 본문 전체로 교체할 때 필요하다 — 인물 486건이 평균 536자에
    # 그쳤는데, 관직·사건 참여는 대부분 첫 문단 뒤에 있다.
    #
    # 100자 미만을 '빈 것'으로 보므로 Wikidata 한 줄 설명(평균 30자)이
    # 들어간 노드도 다음 실행에서 다시 후보가 된다. no_kowiki 표시가
    # 그 중 헛수고인 것만 걸러낸다.
    if refresh:
        have_clause = ""
    else:
        have_clause = """AND (n.description IS NULL OR length(n.description) < 100)
               AND json_extract(n.props, '$.no_kowiki') IS NULL"""
    rows = store.conn.execute(
        # **소스가 아니라 id 로 고른다.** 문서를 찾는 열쇠는 QID 이고,
        # `works` 가 만든 작품 노드는 id 가 `wd:` 인데 소스는 `kowiki` 다.
        # 소스로 고르면 그 653편이 통째로 빠진다.
        f"""SELECT n.id, n.label, n.type, COUNT(e.src) AS degree,
                   length(n.description) AS have,
                   json_extract(n.props, '$.desc_source') AS desc_source
              FROM nodes n
              LEFT JOIN edges e ON e.src = n.id OR e.dst = n.id
             WHERE n.id LIKE 'wd:%' AND n.type IN ({marks})
               {have_clause}
          GROUP BY n.id
          ORDER BY degree DESC""",
        (*node_types,),
    ).fetchall()
    if scope_ids is not None:
        rows = [r for r in rows if r["id"] in scope_ids]
    total_candidates = len(rows)
    if limit is not None:
        rows = rows[:limit]

    if not rows:
        log.info("보강할 노드가 없습니다")
        return {"titles": 0, "extracts": 0, "updated": 0, "no_article": 0,
                "fallback": 0, "unresolved": 0, "redirected": 0, "remaining": 0}

    qid_to_node = {r["id"].split(":", 1)[1]: r["id"] for r in rows}
    # 조회가 죽은 구간은 '문서 없음'과 구분해서 받아둔다
    unresolved: set[str] = set()
    titles = fetch_titles(fetcher, list(qid_to_node), unresolved=unresolved)
    if not titles:
        return {"titles": 0, "extracts": 0, "updated": 0, "no_article": 0,
                "fallback": 0, "unresolved": len(unresolved),
                "redirected": 0, "remaining": total_candidates}

    log.info("본문 %d건 수집 중 (full=%s)...", len(titles), full)
    # 넘겨주기를 따라가면 받은 문서명이 요청한 것과 달라진다. 되짚는
    # 표가 없으면 그 문서는 버려진다.
    resolved_from: dict[str, str] = {}
    true_redirects: set[str] = set()
    extracts = fetch_extracts(
        fetcher, list(titles.values()), full=full,
        resolved_from=resolved_from, redirected=true_redirects,
    )

    title_to_qid = {t: q for q, t in titles.items()}
    node_type = {r["id"]: r["type"] for r in rows}
    # 나무위키로 채운 설명(`namu`)은 위키백과 토막글보다 길다. `--refresh`
    # 로 다시 받을 때 그걸 '《태조 왕건》은 영화이다.' 로 되돌리지 않는다 —
    # 새 글이 지금 것보다 길 때만 바꾼다.
    keep_longer = {
        r["id"]: r["have"] or 0 for r in rows
        if r["desc_source"] and "namu" in r["desc_source"]
    }
    kept = 0
    updates = []
    redirected = 0
    stripped = 0
    for title, text in extracts.items():
        requested = resolved_from.get(title, title)
        qid = title_to_qid.get(requested)
        if not qid:
            continue
        node_id = qid_to_node.get(qid)
        if not node_id:
            continue
        # '판의금부사'를 물으면 '의금부' 문서가 온다. 글은 쓸모 있지만
        # 우리 노드를 그대로 설명하는 글은 아니다 — 어느 문서에서 온
        # 글인지 남겨서 화면이 그 사실을 말할 수 있게 한다.
        via = title if title in true_redirects else None
        if via:
            redirected += 1
        if node_type.get(node_id) == "media":
            # 배우 이름을 넣지 않는다. 여기서 지우지 않으면 화면에도 남고
            # 추출에도 들어간다 — 관문은 저장하는 이 자리 하나면 된다.
            cut = strip_sections(text)
            if cut != text:
                stripped += 1
            text = cut
        if node_id in keep_longer and len(text) <= keep_longer[node_id]:
            kept += 1
            continue
        updates.append((
            text,
            f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(title)}",
            via,
            node_id,
        ))

    store.conn.executemany(
        """UPDATE nodes
              SET description = ?,
                  props = json_set(
                      json_set(
                          json_set(COALESCE(NULLIF(props,''), '{}'),
                                   '$.kowiki_url', ?),
                          '$.desc_via', ?),
                      '$.desc_source', 'kowiki'),
                  updated_at = datetime('now')
            WHERE id = ?""",
        updates,
    )
    store.conn.commit()
    if redirected:
        log.info("넘겨주기를 따라간 설명 %d건 (desc_via 로 표시)", redirected)
    if stripped:
        log.info("작품 %d건에서 등장인물·시청률 절을 걷어냄", stripped)
    if kept:
        log.info("나무위키로 채운 더 긴 설명 %d건은 그대로 둠", kept)

    # 사이트링크가 없던 QID = 한국어 위키백과에 문서가 없는 개체.
    # 쿼리가 죽어서 못 물어본 구간(`unresolved`)은 제외한다 — 타임아웃
    # 한 번으로 200개를 '문서 없음'으로 영구히 못 박으면, 다음 실행이
    # 그 노드를 영영 건너뛴다.
    no_article = [
        q for q in qid_to_node if q not in titles and q not in unresolved
    ]
    store.conn.executemany(
        """UPDATE nodes
              SET props = json_set(COALESCE(NULLIF(props,''), '{}'),
                                   '$.no_kowiki', 1)
            WHERE id = ?""",
        [(qid_to_node[q],) for q in no_article],
    )
    store.conn.commit()

    filled = _fill_from_wikidata(
        fetcher, store, {q: qid_to_node[q] for q in no_article}
    ) if (fallback and no_article) else 0

    log.info(
        "위키백과 보강: 문서명 %d, 본문 %d, 노드 갱신 %d, 문서 없음 %d(대체 %d),"
        " 조회 실패 %d",
        len(titles), len(extracts), len(updates), len(no_article), filled,
        len(unresolved),
    )
    return {
        "titles": len(titles),
        "extracts": len(extracts),
        "updated": len(updates),
        "no_article": len(no_article),
        "fallback": filled,
        "unresolved": len(unresolved),
        "redirected": redirected,
        "remaining": total_candidates - len(rows),
    }


def _fill_from_wikidata(
    fetcher: Fetcher, store: GraphStore, qid_to_node: dict[str, str]
) -> int:
    """위키백과 문서가 없는 노드를 Wikidata 한 줄 설명으로 채운다.

    산문이 아니라 한 줄이다. 덮어쓰지 않는다 — 이미 무언가 적혀 있으면
    그쪽이 더 길고 낫다.

    **영어는 그대로 넣지 않는다.** 사전으로 옮겨지면 한국어로 넣고,
    옮기지 못하면 아예 넣지 않는다. 여기는 Node 를 거치지 않고 SQL 로
    직접 쓰는 자리라 온톨로지의 관문이 걸리지 않는다 — 그래서 같은 규칙을
    여기 한 번 더 적는다."""
    from ..koreanize import to_korean
    from .wikidata import fetch_descriptions

    descs = fetch_descriptions(fetcher, list(qid_to_node))
    updates = []
    dropped = 0
    for qid, (text, lang) in descs.items():
        if qid not in qid_to_node:
            continue
        korean = text if lang == "ko" else to_korean(text)
        if not korean:
            dropped += 1
            continue
        updates.append((korean, "wd:ko" if lang == "ko" else "사전",
                        qid_to_node[qid]))
    if dropped:
        log.info("한국어로 옮기지 못한 한 줄 설명 %d개는 넣지 않았다", dropped)
    cur = store.conn.executemany(
        """UPDATE nodes
              SET description = ?,
                  props = json_set(COALESCE(NULLIF(props,''), '{}'),
                                   '$.desc_source', ?),
                  updated_at = datetime('now')
            WHERE id = ?
              AND (description IS NULL OR trim(description) = '')""",
        updates,
    )
    store.conn.commit()
    # WHERE 로 걸러지는 행이 있으므로 요청 수가 아니라 실제 갱신 수를 센다
    return max(cur.rowcount, 0)
