"""영어 한 줄 설명을 한국어로 옮기고, 한국어 아닌 설명이 들어오는 것을 막는다.

**왜 번역기가 아니라 사전인가.** 여기 들어오는 영어는 Wikidata 의 한 줄
설명이고, 그건 산문이 아니라 거의 전부 '(국적) (직업)' 꼴의 딱지다.
실측 2,222건 중 서로 다른 문구가 881개, 국적과 괄호를 걷어내면 643개로
줄고 그중 상위 100개가 절반을 덮는다. 이런 것을 번역기에 태우면 답이
옳은지 확인할 방법이 없고, 틀리면 조용히 틀린다. 사전은 반대다 — 무엇을
무엇으로 옮겼는지 한 줄씩 읽을 수 있고, **모르는 말은 모른다고 말한다.**

그래서 `to_korean` 은 확신이 없으면 지어내지 않고 None 을 돌려준다.
부르는 쪽은 설명을 비우고, 화면은 '설명 없음 — 한국어 위키백과에 문서가
없습니다' 라고 적는다. 틀린 한국어 한 줄보다 빈 칸이 낫다.
"""

from __future__ import annotations

import re

HANGUL = re.compile(r"[가-힣]")


def has_hangul(text: str | None) -> bool:
    """이 글에 한글이 한 자라도 있는가.

    '한국어인가'를 이보다 정교하게 묻지 않는다. 한국어 산문에는 인용된
    영문 표기나 연도가 섞이는 게 정상이고, 그걸 걸러내면 멀쩡한 글이
    사라진다. 반대로 **한 자도 없으면** 그건 우리 화면에 올릴 글이 아니다.
    """
    return bool(HANGUL.search(text or ""))


# --- 사전 ---------------------------------------------------------------

# 국적·왕조. 앞에 붙기도 하고("Joseon civil servant") 뒤에 붙기도 한다
# ("queen consort of Silla"). 둘 다 받는다.
POLITY = {
    "south korean": "대한민국", "south-korean": "대한민국", "southkorean": "대한민국",
    "south korea": "대한민국", "republic of korea": "대한민국",
    "north korean": "북한", "north-korean": "북한", "dprk": "북한",
    "north korea": "북한",
    "korean": "한국", "korea": "한국",
    "joseon": "조선", "goryeo": "고려", "goryo": "고려", "silla": "신라",
    "baekje": "백제", "goguryeo": "고구려", "gojoseon": "고조선", "balhae": "발해",
    "yuan dynasty": "원", "ming dynasty": "명", "qing dynasty": "청",
    "japanese": "일본", "japan": "일본", "chinese": "중국", "china": "중국",
    "american": "미국", "german": "독일", "british": "영국", "french": "프랑스",
    "canadian": "캐나다", "spanish": "스페인", "bulgarian": "불가리아",
    "taiwanese": "대만", "costa rican": "코스타리카", "russian": "러시아",
    "korean-american": "한국계 미국", "korean american": "한국계 미국",
    "south korean-american": "한국계 미국", "korean-danish": "한국계 덴마크",
    "zainichi korean": "재일 한국", "zainichi-korean": "재일 한국",
    "korean-japanese": "재일 한국", "japanese-korean": "재일 한국",
    "south korean-japanese": "한국계 일본", "british-korean": "영국계 한국",
    # 형용사가 아니라 나라 이름으로 오는 자리 — 'municipality of Germany'
    "germany": "독일", "brazil": "브라질", "france": "프랑스", "malaysia": "말레이시아",
    "korean empire": "대한제국", "joseon dynasty": "조선", "goryeo dynasty": "고려",
}

# 전근대 왕조 — 같은 영어 낱말이 다른 한국어가 되는 자리를 가른다.
# 'Joseon civil servant' 는 공무원이 아니라 문신이고, 'Yuan dynasty
# interpreter' 는 통역사가 아니라 역관이다.
PREMODERN = {"조선", "고려", "신라", "백제", "고구려", "고조선", "발해",
             "원", "명", "청", "대한제국"}

JOB_PREMODERN = {
    "civil servant": "문신",
    "government official": "관리",
    "official": "관리",
    "bureaucrat": "관료",
    "interpreter": "역관",
    "scholar-official": "문신",
    "confucian scholar": "유학자",
    "royal": "왕족",
    "officer": "무관",
    "military officer": "무관",
    "physician": "의관",
    "scholar": "유학자",
    "general": "장군",
    "concubine": "후궁",
    "consort": "후궁",
    "royal consort": "후궁",
    "queen consort": "왕비",
    "princess": "공주",
    "prince": "왕자",
    "noblewoman": "사대부가 여성",
    "monk": "승려",
    "potter": "도공",
    "painter": "화원",
}

JOB = {
    # 구기
    "association football player": "축구 선수", "association footballer": "축구 선수",
    "footballer": "축구 선수", "football player": "축구 선수", "soccer player": "축구 선수",
    "women's football forward": "여자 축구 공격수",
    "association football midfielder": "축구 미드필더",
    "association football goalkeeper": "축구 골키퍼",
    "association football defender": "축구 수비수",
    "association football forward": "축구 공격수",
    "association football manager": "축구 감독", "football manager": "축구 감독",
    "association football referee": "축구 심판", "football referee": "축구 심판",
    "assistant referee": "부심", "referee": "심판",
    "baseball player": "야구 선수", "basketball player": "농구 선수",
    "volleyball player": "배구 선수", "handball player": "핸드볼 선수",
    "tennis player": "테니스 선수", "table tennis player": "탁구 선수",
    "badminton player": "배드민턴 선수", "squash player": "스쿼시 선수",
    "field hockey player": "필드하키 선수", "ice hockey player": "아이스하키 선수",
    "ice hockey defenceman": "아이스하키 수비수", "ice hockey defenseman": "아이스하키 수비수",
    "rugby player": "럭비 선수", "rugby union player": "럭비 선수",
    "rugby union footballer": "럭비 선수",
    "golfer": "골프 선수", "professional golfer": "골프 선수",
    "bowler": "볼링 선수", "boccia player": "보치아 선수",
    "water polo player": "수구 선수",
    # 격투·투기
    "wrestler": "레슬링 선수", "amateur wrestler": "레슬링 선수",
    "sport wrestler": "레슬링 선수", "freestyle wrestler": "자유형 레슬링 선수",
    "greco-roman wrestler": "그레코로만형 레슬링 선수",
    "professional wrestler": "프로레슬러",
    "boxer": "복싱 선수", "kickboxer": "킥복싱 선수",
    "judoka": "유도 선수", "taekwondo practitioner": "태권도 선수",
    "taekwondoin": "태권도 선수", "taekwondo athlete": "태권도 선수",
    "taekwondo master": "태권도 사범", "karateka": "가라테 선수",
    "martial artist": "무술가", "fencer": "펜싱 선수", "sambo practitioner": "삼보 선수",
    # 육상·수영
    "athlete": "운동선수", "athletics competitor": "육상 선수",
    "track and field athlete": "육상 선수", "sprinter": "단거리 육상 선수",
    "long-distance runner": "장거리 육상 선수", "distance runner": "장거리 육상 선수",
    "middle-distance runner": "중거리 육상 선수", "marathon runner": "마라톤 선수",
    "steeplechase athlete": "장애물 달리기 선수", "racewalker": "경보 선수",
    "hurdler": "허들 선수", "high jumper": "높이뛰기 선수",
    "long jumper": "멀리뛰기 선수", "pole vaulter": "장대높이뛰기 선수",
    "triple jumper": "세단뛰기 선수", "shot putter": "투포환 선수",
    "javelin thrower": "창던지기 선수", "discus thrower": "원반던지기 선수",
    "hammer thrower": "해머던지기 선수",
    "decathlete": "10종 경기 선수", "heptathlete": "7종 경기 선수",
    "pentathlete": "근대5종 선수", "modern pentathlete": "근대5종 선수",
    "triathlete": "트라이애슬론 선수",
    "swimmer": "수영 선수", "diver": "다이빙 선수", "sport diver": "다이빙 선수",
    "synchronized swimmer": "싱크로나이즈드스위밍 선수",
    "synchronised swimmer": "싱크로나이즈드스위밍 선수",
    "rower": "조정 선수", "canoeist": "카누 선수", "sailor": "요트 선수",
    # 겨울·기타 종목
    "speed skater": "스피드스케이팅 선수", "long track speed skater": "스피드스케이팅 선수",
    "short track speed skater": "쇼트트랙 선수", "figure skater": "피겨스케이팅 선수",
    "pair skater": "페어스케이팅 선수", "ice dancer": "아이스댄스 선수",
    "biathlete": "바이애슬론 선수", "cross-country skier": "크로스컨트리 스키 선수",
    "alpine skier": "알파인 스키 선수", "freestyle skier": "프리스타일 스키 선수",
    "ski jumper": "스키점프 선수", "ski mountaineer": "스키 등반 선수",
    "snowboarder": "스노보드 선수", "luger": "루지 선수", "curler": "컬링 선수",
    "bobsledder": "봅슬레이 선수", "skeleton racer": "스켈레톤 선수",
    "gymnast": "체조 선수", "artistic gymnast": "기계체조 선수",
    "rhythmic gymnast": "리듬체조 선수", "trampoline gymnast": "트램펄린 선수",
    "weightlifter": "역도 선수", "powerlifter": "파워리프팅 선수",
    "archer": "양궁 선수", "sports shooter": "사격 선수", "sport shooter": "사격 선수",
    "shooter": "사격 선수", "rifle shooter": "사격 선수", "pistol shooter": "사격 선수",
    "trap shooter": "사격 선수", "skeet shooter": "사격 선수",
    "cyclist": "사이클 선수", "racing cyclist": "사이클 선수",
    "bicycle racer": "사이클 선수", "mountain biker": "산악자전거 선수",
    "cross-country mountain biker": "산악자전거 선수",
    "equestrian": "승마 선수", "skateboarder": "스케이트보드 선수",
    "rock climber": "스포츠클라이밍 선수", "mountaineer": "산악인",
    "bodybuilder": "보디빌더", "sports coach": "스포츠 지도자", "coach": "감독",
    "archery coach": "양궁 감독", "basketball coach": "농구 감독",
    "pro gamer": "프로게이머", "esports player": "프로게이머",
    "racing driver": "카레이서", "motorcycle racer": "모터사이클 선수",
    # 정치·행정·군
    "politician": "정치인", "diplomat": "외교관", "ambassador": "대사",
    "civil servant": "공무원", "government official": "공무원",
    "official": "공무원", "bureaucrat": "관료",
    "military personnel": "군인", "military officer": "군인",
    "military leader": "무장", "general": "장군", "lieutenant general": "중장",
    "major general": "소장", "colonel": "대령", "admiral": "제독",
    "soldier": "군인", "security officer": "보안 요원", "security official": "보안 관리",
    "spy": "첩보원", "police officer": "경찰관",
    "independence activist": "독립운동가", "righteous army member": "의병",
    "anti-japanese fighter": "항일 투사", "patriotic martyr": "순국선열",
    "activist": "운동가", "human rights activist": "인권운동가",
    "human rights defender": "인권운동가", "trade unionist": "노동운동가",
    "defector": "탈북민", "refugee": "난민",
    "judge": "판사", "lawyer": "변호사", "jurist": "법학자", "prosecutor": "검사",
    # 학문·전문직
    "scholar": "학자", "academic": "학자", "researcher": "연구자",
    "university teacher": "대학교수", "professor": "교수", "teacher": "교사",
    "educator": "교육자", "docent": "도슨트", "political prisoner": "정치범",
    "historian": "역사학자", "philosopher": "철학자", "sociologist": "사회학자",
    "sociologist of religion": "종교사회학자", "economist": "경제학자",
    "physicist": "물리학자", "chemist": "화학자", "mathematician": "수학자",
    "scientist": "과학자", "engineer": "공학자", "parasitologist": "기생충학자",
    "theologian": "신학자", "musicologist": "음악학자",
    "literary scholar": "문학 연구자", "japanologist": "일본학자",
    "linguist": "언어학자", "archaeologist": "고고학자", "geographer": "지리학자",
    "physician": "의사", "traditional physician": "한의사", "doctor": "의사",
    "nurse": "간호사", "pharmacist": "약사", "veterinarian": "수의사",
    "banker": "은행가", "businessperson": "기업인", "businessman": "기업인",
    "entrepreneur": "기업인", "hotel manager": "호텔 경영자",
    "journalist": "기자", "editor": "편집자", "translator": "번역가",
    "interpreter": "통역사", "librarian": "사서", "architect": "건축가",
    # 종교
    "buddhist monk": "승려", "monk": "승려", "bhikkhu": "비구",
    "priest": "신부", "catholic priest": "가톨릭 사제",
    "roman catholic priest": "가톨릭 사제", "bishop": "주교",
    "roman catholic bishop": "가톨릭 주교", "archbishop": "대주교",
    "cardinal": "추기경", "missionary": "선교사", "pastor": "목사",
    "nun": "수녀", "shaman": "무속인",
    # 예술·연예
    "artist": "예술가", "visual artist": "시각예술가", "fine artist": "미술가",
    "new media artist": "뉴미디어 예술가", "multimedia artist": "멀티미디어 예술가",
    "digital art curator": "디지털 아트 큐레이터", "curator": "큐레이터",
    "painter": "화가", "sculptor": "조각가", "ceramic artist": "도예가",
    "potter": "도공", "illustrator": "삽화가", "drawer": "소묘가",
    "comics artist": "만화가", "cartoonist": "만화가", "manhwaga": "만화가",
    "manhwa artist": "만화가", "penciller": "만화 작화가",
    "photographer": "사진가", "designer": "디자이너",
    "jewelry designer": "보석 디자이너", "bow maker": "궁장", "dyer": "염색장",
    "musician": "음악가", "traditional musician": "국악인",
    "classical musician": "클래식 음악가",
    "singer": "가수", "opera singer": "성악가", "operatic soprano": "소프라노 성악가",
    "operatic tenor": "테너 성악가", "baritone": "바리톤 성악가",
    "soprano": "소프라노 성악가", "tenor": "테너 성악가",
    "singer-songwriter": "싱어송라이터", "rapper": "래퍼",
    "composer": "작곡가", "songwriter": "작사·작곡가", "lyricist": "작사가",
    "conductor": "지휘자", "pianist": "피아니스트", "violinist": "바이올리니스트",
    "cellist": "첼리스트", "classical cellist": "첼리스트",
    "guitarist": "기타리스트", "organist": "오르가니스트",
    "classical organist": "오르가니스트", "flutist": "플루티스트",
    "music producer": "음악 프로듀서", "music educator": "음악 교육자",
    "actor": "배우", "actress": "배우", "film actor": "영화배우",
    "film actress": "영화배우", "child actor": "아동 배우",
    "voice actor": "성우", "comedian": "코미디언", "tv personality": "방송인",
    "model": "모델", "adult model": "성인 모델", "dancer": "무용가",
    "pornographic actress": "성인영화 배우", "pornographic actor": "성인영화 배우",
    "yakuza boss": "야쿠자 두목", "grandmaster": "그랜드마스터",
    "choreographer": "안무가",
    "dance teacher": "무용 교육자",
    "film director": "영화감독", "director": "연출가", "video director": "영상 감독",
    "television director": "텔레비전 연출가", "stage director": "연출가",
    "film and television director": "영화·텔레비전 감독",
    "documentary filmmaker": "다큐멘터리 감독", "filmmaker": "영화 제작자",
    "film producer": "영화 제작자", "producer": "제작자",
    "cinematographer": "촬영감독", "cameraman": "촬영기사",
    "screenwriter": "각본가", "scriptwriter": "각본가",
    # 글
    "writer": "작가", "author": "저술가", "novelist": "소설가", "poet": "시인",
    "essayist": "수필가", "memoirist": "회고록 작가", "critic": "비평가",
    "literary critic": "문학평론가", "children's writer": "아동문학가",
    "playwright": "극작가", "editor-in-chief": "편집국장",
    "comic book writer": "만화 작가", "food writer": "음식 칼럼니스트",
    "news anchor": "뉴스 앵커", "tv news anchor": "방송 뉴스 앵커",
    # 신분·직위
    "princess": "공주", "princesse": "공주", "prince": "왕자",
    "queen consort": "왕비", "king": "왕", "queen": "왕비",
    "concubine": "후궁", "noblewoman": "귀족 여성", "nobleman": "귀족",
    "farmer": "농민", "murderer": "살인범", "esperantist": "에스페란토 운동가",
    "performer": "공연자", "scholar-official": "문신", "confucian scholar": "유학자",
    "unificationist leader": "통일교 지도자",
}

# 사건. 여기 나오는 말은 거의 다 전쟁·관직이다 — 한국사 그래프의 본체라
# 인물 딱지보다 공들여 적는다.
JOB.update({
    "battle": "전투", "naval battle": "해전", "siege": "공성전",
    "military campaign": "군사 작전", "campaign": "군사 작전",
    "invasion": "침공", "conquest": "정복", "annexation": "병합",
    "rebellion": "반란", "uprising": "봉기", "revolt": "반란",
    "peasant rebellion": "농민 반란", "political purge": "정치 숙청",
    "purge": "숙청", "coup": "정변", "coup d'etat": "정변",
    "assassination": "암살", "assassination attempt": "암살 미수",
    "war": "전쟁", "civil war": "내전", "treaty": "조약",
    "massacre": "학살", "famine": "기근", "riot": "민란",
    "guerrilla movement": "의병 운동", "independence movement": "독립운동",
    "military organisation": "군사 조직", "military organization": "군사 조직",
    "private military organisation": "사설 군사 조직",
})

# 직위·조직처럼 사람이 아닌 노드에 붙는 딱지
JOB.update({
    "governmental position": "정부 직위",
    "ministerial position": "장관직",
    "diplomatic rank": "외교 직급",
    "academic rank and position": "학술 직위",
    "academic rank": "학술 직급",
    "military rank": "군사 계급",
    "position": "직위",
    "organization": "조직",
    "art exhibition": "미술 전시",
    "municipality": "지방자치단체",
    "envoy": "사신", "ambassadorial group": "사행단",
    "court official": "조정 관리", "ministry": "부서",
    "noble title": "작위", "cardinal title": "추기경 명의",
})

# 사건을 일으킨 쪽. 나라 이름이 아니라 정권·세력으로 오는 자리가 있다.
ACTOR = {
    "japan toyotomi government": "도요토미 정권",
    "toyotomi government": "도요토미 정권",
    "mongol empire": "몽골 제국", "khitan": "거란", "jurchen": "여진",
    "qing empire": "청", "ming empire": "명",
}

# 말로 쓴 서수 — 'second rank official' 은 숫자로 오지 않는다.
ORDINAL = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
}

# 관직이 속한 기관. 품계만 남기고 기관을 지우면 '조선의 3품 관직'이
# 수십 개가 되어 서로 구별되지 않는다.
INSTITUTION = {
    "uijeongbu": "의정부", "gukjagam": "국자감", "six ministries": "육조",
    "seungjeongwon": "승정원", "saganwon": "사간원", "sahonbu": "사헌부",
    "hongmungwan": "홍문관", "chunchugwan": "춘추관", "ministry of rites": "예조",
}

# 앞에 붙어 뜻을 더하는 말. 뒤의 직업을 먼저 옮기고 여기서 감싼다.
PREFIX = {
    "olympic": "올림픽 ",
    "paralympic": "패럴림픽 ",
    "professional": "프로 ",
    "amateur": "아마추어 ",
    "former": "전 ",
    "retired": "은퇴한 ",
}

# 관사·군더더기
_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.I)


def _dates(inner: str) -> str | None:
    """괄호 안이 생몰년이면 한국어 표기로. 아니면 None.

    괄호에 연도 말고 다른 것이 들어 있으면(예: '[ch'anggang, ch'wi ong]')
    우리가 옮길 수 있는 정보가 아니다. 그때는 문구 전체를 포기한다.
    """
    s = inner.strip().strip(";,")
    if re.fullmatch(r"[?\s\-–—]*", s):
        return ""                                   # '? - ?' — 정보가 없다
    m = re.fullmatch(r"born\s+(\d{3,4})", s, re.I)
    if m:
        return f" ({m.group(1)}년생)"
    m = re.fullmatch(r"(\d{3,4})\s*[-–—]\s*(\d{3,4})", s)
    if m:
        return f" ({m.group(1)}~{m.group(2)})"
    m = re.fullmatch(r"(\d{3,4})\s*[-–—]\s*[?]?", s)
    if m:
        return f" ({m.group(1)}~)"
    m = re.fullmatch(r"[?]?\s*[-–—]\s*(\d{3,4})", s)
    if m:
        return f" (~{m.group(1)})"
    m = re.fullmatch(r"(\d{3,4})", s)
    if m:
        return f" ({m.group(1)})"
    m = re.fullmatch(r"\*\s*(\d{3,4})", s)
    if m:
        return f" ({m.group(1)}년생)"
    # 'Joseon civil servant (1370 ~ March 26, 1426)' 처럼 달·일이 섞인 것.
    # 연도만 건진다 — 우리 화면은 생몰년만 쓴다.
    years = [int(y) for y in re.findall(r"\b(\d{3,4})\b", s) if 300 <= int(y) <= 2100]
    if len(years) == 2 and years[0] <= years[1]:
        return f" ({years[0]}~{years[1]})"
    if len(years) == 1:
        return f" ({years[0]})"
    return None


def _split_polity(s: str) -> tuple[str | None, str]:
    """앞이나 뒤에 붙은 국적을 떼어낸다. 긴 이름부터 맞춰 본다 —
    'south korean' 을 'korean' 으로 먼저 잘라내면 남한이 한국이 된다."""
    low = s.lower()
    for key in sorted(POLITY, key=len, reverse=True):
        if low.startswith(key + " "):
            return POLITY[key], s[len(key) + 1 :]
        m = re.search(
            rf"\s+(?:of|from|in|during|under)\s+(?:the\s+)?{re.escape(key)}"
            rf"(?:\s+dynasty)?$",
            low,
        )
        if m:
            return POLITY[key], s[: m.start()]
    return None, s


def _lookup(word: str, polity: str | None) -> str | None:
    w = _ARTICLE.sub("", word.strip().strip(",;")).lower()
    if not w:
        return None
    if polity in PREMODERN and w in JOB_PREMODERN:
        return JOB_PREMODERN[w]
    if w in JOB:
        return JOB[w]
    # 'olympic medalist in volleyball' — 종목 이름은 이미 사전에 있다.
    # 접두어 규칙보다 **먼저** 본다. 나중에 보면 'olympic' 을 접두어로도
    # 떼고 여기서도 붙여 '올림픽 올림픽 …' 이 된다.
    m = re.fullmatch(r"(olympic\s+|paralympic\s+)?medalist in (.+)", w)
    if m:
        sport = JOB.get(f"{m.group(2)} player") or JOB.get(m.group(2))
        if sport:
            games = PREFIX.get((m.group(1) or "").strip(), "")
            return f"{games}{sport.removesuffix(' 선수')} 메달리스트"
    for pre, ko in PREFIX.items():
        if w.startswith(pre + " "):
            rest = _lookup(w[len(pre) + 1 :], polity)
            return ko + rest if rest else None
    # '3rd rank Joseon official' — 조선 관직은 품계로 말한다. 정/종은
    # 원문이 구분해 주지 않으므로 '3품'까지만 적는다. 모르는 것을 아는
    # 척하느니 덜 말하는 쪽이 낫다. 대신 기관 이름은 살린다 — 그게
    # 지평과 참찬을 가르는 유일한 단서다.
    m = re.fullmatch(
        r"(?:(\d{1,2})(?:st|nd|rd|th)|(\w+)) (?:rank|grade)"
        r"(?: (\w+))? official(?: in (?:the )?(.+))?",
        w,
    )
    if m:
        num = int(m.group(1)) if m.group(1) else ORDINAL.get(m.group(2) or "")
        if num:
            # 기관은 '의' 없이 붙인다. 뒤에서 왕조가 '조선의 …' 로 한 번
            # 더 감싸므로, 여기서도 '의'를 달면 '조선의 의정부의'가 된다.
            inst = INSTITUTION.get((m.group(4) or "").strip())
            if inst:
                return f"{inst} {num}품 관직"
            nation = POLITY.get((m.group(3) or "").strip())
            return f"{nation}의 {num}품 관직" if nation else f"{num}품 관직"

    # 'head of the Gukjagam during the Goryeo Dynasty'
    m = re.fullmatch(r"head of (?:the )?(.+)", w)
    if m:
        inst = INSTITUTION.get(m.group(1).strip())
        if inst:
            return f"{inst} 수장"

    # 'battle between Baekje & Silla' — 두 나라가 맞선 사건
    m = re.fullmatch(r"(battle|war|conflict) between (.+?) (?:and|&) (.+)", w)
    if m:
        a, b = POLITY.get(m.group(2).strip()), POLITY.get(m.group(3).strip())
        if a and b:
            return f"{a}와 {b}의 {JOB[m.group(1)]}"

    # 'invasion of Joseon by Japan Toyotomi government' — 누가 어디를
    m = re.fullmatch(r"(invasion|conquest) of (.+?) by (?:the )?(.+)", w)
    if m:
        target = POLITY.get(m.group(2).strip())
        by = POLITY.get(m.group(3).strip()) or ACTOR.get(m.group(3).strip())
        if target and by:
            return f"{by}의 {target} {JOB[m.group(1)]}"
    # 복수형. 사전에 있는 말만 받아들이므로 잘못 잘라도 통과하지 않는다.
    if w.endswith("s"):
        return _lookup(w[:-1], polity)
    return None


def _job(s: str, polity: str | None) -> str | None:
    """'A and B', 'A, B and C' 를 각각 옮겨 가운뎃점으로 잇는다.
    한 조각이라도 모르면 통째로 포기한다 — 반만 한국어인 줄은 더 나쁘다.

    쪼개기 **전에** 통째로 한 번 찾아본다. 'academic rank and position' 은
    한 덩어리로 뜻이 있는 말인데 먼저 쪼개면 '학술 직급·직위'가 된다."""
    whole = _lookup(s, polity)
    if whole:
        return whole
    parts = [p for p in re.split(r",\s*|\s+and\s+|\s+&\s+", s) if p.strip()]
    out = []
    for p in parts:
        ko = _lookup(p, polity)
        if ko is None:
            return None
        if ko not in out:
            out.append(ko)
    return "·".join(out) if out else None


def to_korean(text: str | None) -> str | None:
    """영어 한 줄 설명을 한국어로. 확신이 없으면 None.

    이미 한글이 섞인 글은 그대로 돌려준다 — 여기 손댈 이유가 없다.
    """
    if not text or not text.strip():
        return None
    s = " ".join(text.split())
    if has_hangul(s):
        return s

    tail = ""
    paren_polity = None
    m = re.search(r"\s*\(([^()]*)\)\s*$", s)
    if m:
        inner = m.group(1).strip()
        if inner.lower() in POLITY:
            # '1547 political purge in Korea (Joseon)' — 괄호가 왕조를
            # 좁혀 준다. 날짜가 아니라 국적으로 읽어야 한다.
            paren_polity = POLITY[inner.lower()]
            s = s[: m.start()].strip()
        else:
            tail = _dates(inner)
            if tail is None:
                return None                  # 연도가 아닌 괄호 — 옮길 수 없다
            s = s[: m.start()].strip()
    # 괄호 없이 꼬리에 붙은 생몰년: 'footballer born 1985'
    m = re.search(r"\s+born\s+(\d{3,4})$", s, re.I)
    if m:
        tail = f" ({m.group(1)}년생)" + tail
        s = s[: m.start()]

    # '17th century Joseon officer' — 세기는 국적 앞에 온다. 국적을 떼기
    # 전에 걷어내지 않으면 'joseon officer' 가 통째로 미지의 말이 된다.
    head = ""
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)\s+century\s+(.+)", s, re.I)
    if m:
        head, s = f"{m.group(1)}세기 ", m.group(2)
    # 사건은 연도를 앞에 달고 온다 — '1231 battle', '1592-1593 invasion'.
    m = re.match(r"(\d{3,4})\s*[-–—]\s*(\d{3,4})\s+(.+)", s)
    if m:
        head, s = f"{m.group(1)}~{m.group(2)}년 ", m.group(3)
    else:
        m = re.match(r"(\d{3,4})\s+(.+)", s)
        if m:
            head, s = f"{m.group(1)}년 ", m.group(2)

    polity, rest = _split_polity(s)
    polity = paren_polity or polity
    ko = _job(rest, polity)
    if ko is None:
        return None
    return head + (f"{polity}의 {ko}" if polity else ko) + tail


# --- 그래프에 적용 -------------------------------------------------------

import sqlite3  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class RedescribeReport:
    applied: list[tuple[str, str, str]] = field(default_factory=list)  # (id, 영어, 한국어)
    cleared: list[tuple[str, str]] = field(default_factory=list)       # (id, 옮기지 못한 영어)
    already: int = 0


def english_descriptions(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """설명에 한글이 한 자도 없는 노드 — 화면에 영어가 뜨는 노드 전부."""
    rows = conn.execute(
        "SELECT id, label, description FROM nodes"
        " WHERE description IS NOT NULL AND trim(description) <> ''"
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows if not has_hangul(r[2])]


def _pending(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """이번에 손볼 노드 — (id, 영어 원문).

    화면에 영어가 떠 있는 노드뿐 아니라, **지난번에 못 옮겨 비워 둔
    노드도 다시 본다.** 사전에 말을 더하고 다시 돌리는 것이 이 도구를
    쓰는 정상적인 방법이고, 그때 되살아나지 않으면 `desc_en` 을 남긴
    보람이 없다.
    """
    out = [(node_id, text) for node_id, _label, text in english_descriptions(conn)]
    seen = {node_id for node_id, _ in out}
    for node_id, text in conn.execute(
        """SELECT id, json_extract(props, '$.desc_en') FROM nodes
            WHERE json_extract(props, '$.desc_en') IS NOT NULL
              AND (description IS NULL OR trim(description) = '')"""
    ):
        if node_id not in seen and text:
            out.append((node_id, text))
    return out


def redescribe(conn: sqlite3.Connection, *, dry_run: bool = False) -> RedescribeReport:
    """영어 설명을 한국어로 바꾸고, 못 옮긴 것은 **비운다.**

    비우는 쪽이 지는 선택처럼 보이지만 그렇지 않다. 화면은 빈 설명을
    '설명 없음 — 왜 없는지'로 그리게 되어 있다. 영어 한 줄을 그대로 두면
    읽는 사람은 그게 우리가 고른 설명인 줄 안다.

    원문은 `props.desc_en` 에 남긴다. 사전이 자라면 다시 돌려서 그때
    옮길 수 있고, 무엇을 비웠는지 나중에도 셀 수 있다. 여러 번 돌려도
    결과가 같다 — 이미 한국어인 설명은 손대지 않는다.
    """
    report = RedescribeReport()
    for node_id, english in _pending(conn):
        korean = to_korean(english)
        if korean == english:                 # 손댈 것이 없다
            report.already += 1
            continue
        if korean:
            report.applied.append((node_id, english, korean))
        else:
            report.cleared.append((node_id, english))
        if dry_run:
            continue
        conn.execute(
            """UPDATE nodes
                  SET description = ?,
                      props = json_set(
                          json_set(COALESCE(NULLIF(props,''), '{}'),
                                   '$.desc_en', ?),
                          '$.desc_source', ?),
                      updated_at = datetime('now')
                WHERE id = ?""",
            (korean, english, "사전" if korean else None, node_id),
        )
    if not dry_run:
        conn.commit()
    return report
