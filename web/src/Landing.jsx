import { useState } from 'react';

function Mark() {
  return <span className="landing-mark" aria-hidden="true"><i /><i /><i /></span>;
}

function TimelineCard({ compact = false }) {
  return (
    <div className={`timeline-card${compact ? ' compact' : ''}`}>
      <div className="timeline-card-head">
        <span className="timeline-eyebrow">두 개의 시간, 하나의 이야기</span>
        <span className="timeline-range">1989 — 2016</span>
      </div>
      <div className="timeline-lines" aria-hidden="true">
        <div className="track world-track"><span>세상의 시간</span><i /><i /></div>
        <div className="track life-track"><span>나의 시간</span><i /><i /></div>
        <div className="track-link link-one" /><div className="track-link link-two" />
        <b className="year year-one">1989</b><b className="year year-two">2016</b>
      </div>
      <div className="timeline-pair pair-one">
        <div className="mini-event world-event"><span>세상에선</span><strong>베를린 장벽이 무너졌어요</strong><small>11월 9일 · 세계의 변화</small></div>
        <div className="mini-event life-event"><span>나에겐</span><strong>내가 태어났어요</strong><small>나의 시작</small></div>
      </div>
      <div className="timeline-pair pair-two">
        <div className="mini-event world-event"><span>세상에선</span><strong>알파고와 이세돌이 만났어요</strong><small>3월 · 서울</small></div>
        <div className="mini-event life-event"><span>나에겐</span><strong>우리가 가족이 되었어요</strong><small>나의 결혼</small></div>
      </div>
      {!compact && <div className="timeline-foot"><span className="pulse-dot" /> 한 사람의 삶도 역사의 한가운데에 있어요</div>}
    </div>
  );
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <main className="landing">
      <header className="landing-nav">
        <a className="landing-brand" href="/" aria-label="histgraph 홈"><Mark /><span>histgraph</span></a>
        <button className="nav-menu-toggle" type="button" aria-expanded={menuOpen} aria-label="메뉴" onClick={() => setMenuOpen(!menuOpen)}>
          <span /><span />
        </button>
        <nav className={menuOpen ? 'open' : ''} aria-label="주요 메뉴">
          <a href="#how">어떻게 보나요</a>
          <a href="#read">역사 읽기</a>
          <a href="/graph.html">한국사 둘러보기</a>
          <a className="nav-cta" href="/life.html">내 이야기 시작하기 <span aria-hidden="true">↗</span></a>
        </nav>
      </header>

      <section className="landing-hero">
        <div className="hero-copy">
          <p className="hero-kicker"><span /> 나의 시간과 세상의 시간이 만나는 곳</p>
          <h1>내가 태어난 날,<br />세상은 <em>어떤 모습</em>이었을까?</h1>
          <p className="hero-description">태어난 날부터 오늘까지, 내 삶의 순간들을 세상의 역사와 나란히 놓아 보세요. 평범했던 하루가 조금 다르게 보이기 시작합니다.</p>
          <div className="hero-actions">
            <a className="button-primary" href="/life.html">내 이야기 시작하기 <span aria-hidden="true">→</span></a>
            <a className="button-text" href="/graph.html">한국사 먼저 둘러보기 <span aria-hidden="true">↗</span></a>
          </div>
          <div className="hero-note"><span className="note-icon">✳</span><span>생일, 결혼, 이사, 그리고 당신만의 순간들</span></div>
        </div>
        <div className="hero-art" aria-label="세상의 사건과 나의 삶을 함께 놓은 연표 예시">
          <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
          <div className="art-caption caption-top"><span>THE WORLD</span><i>세상의 기록</i></div>
          <div className="art-caption caption-bottom"><span>MY LIFE</span><i>나의 이야기</i></div>
          <TimelineCard />
          <span className="floating-year year-1989">1989</span><span className="floating-year year-2016">2016</span>
        </div>
        <a href="#how" className="scroll-cue"><span /> 아래로 더 보기</a>
      </section>

      <section className="question-band" aria-label="서비스가 답하는 질문">
        <span>기억 속 그날을 떠올려 보세요</span>
        <p>내가 태어났을 때, 세상엔 어떤 일이 있었을까?</p>
        <p>우리가 결혼하던 날, 세상은 무슨 이야기를 하고 있었을까?</p>
      </section>

      <section className="how-section" id="how">
        <div className="section-intro">
          <p className="section-kicker">A LIFE IN HISTORY</p>
          <h2>각자의 시간이<br />역사의 한 장면이 됩니다</h2>
          <p>내가 겪은 일과 세상에서 일어난 일을 같은 시간 위에 놓으면, 둘 사이에 새로운 이야기가 보여요.</p>
        </div>
        <div className="how-content">
          <div className="how-steps">
            <article><span className="step-number">01</span><div><h3>내 삶의 순간을 적어요</h3><p>태어난 날, 결혼한 날, 기억하고 싶은 순간을 기록해요.</p></div></article>
            <article><span className="step-number">02</span><div><h3>같은 시절의 세상을 만나요</h3><p>그때 한국과 세계에서 일어난 사건을 곁에 놓아 드려요.</p></div></article>
            <article><span className="step-number">03</span><div><h3>나만의 역사로 이어져요</h3><p>한 사람의 삶이 시대와 어떻게 만나는지 천천히 살펴보세요.</p></div></article>
          </div>
          <div className="how-preview"><TimelineCard compact /><span className="preview-stamp">나와 세상의<br />같은 시간</span></div>
        </div>
      </section>

      <section className="reading-section" id="read">
        <div className="reading-heading">
          <p className="section-kicker">HISTORY TO READ</p>
          <h2>사람과 사건을<br />연결해서 읽어 보세요</h2>
          <p>인물의 설명만 되풀이하지 않고, 같은 자료에서 확인한 시기·장소·인물·사건의 연결을 함께 보여 줍니다. 각 문서에는 참고한 원자료의 링크도 있습니다.</p>
        </div>
        <div className="reading-cards">
          <article>
            <span>01 · 인물에서 시작</span>
            <h3><a href="/인물/조선-세종">세종의 시대와 그 주변</a></h3>
            <p>세종의 생애를 읽고 훈민정음, 집현전, 가까운 인물과 사건으로 이동해 보세요. 연표와 관계를 함께 볼 수 있습니다.</p>
            <a className="reading-more" href="/인물/조선-세종">세종 읽기 →</a>
          </article>
          <article>
            <span>02 · 사건에서 시작</span>
            <h3><a href="/사건/임진왜란">임진왜란에 이어진 것들</a></h3>
            <p>하나의 사건을 중심으로 관련된 인물, 전투와 장소를 따라가며 같은 시기의 기록을 비교해 보세요.</p>
            <a className="reading-more" href="/사건/임진왜란">임진왜란 읽기 →</a>
          </article>
          <article>
            <span>03 · 전체 목록</span>
            <h3><a href="/n/">한국사 문서 둘러보기</a></h3>
            <p>인물·사건·장소·문화재를 갈래별로 찾아볼 수 있습니다. 관심 있는 이름에서 시작해 연결된 문서로 이동하세요.</p>
            <a className="reading-more" href="/n/">문서 목록 보기 →</a>
          </article>
        </div>
        <p className="reading-method">자료를 어떻게 고르고 연결했는지 궁금하다면 <a href="/about.html">제작 방식과 자료의 한계</a>를 읽어 보세요.</p>
      </section>

      <section className="closing-cta">
        <div className="closing-spark" aria-hidden="true">✳</div>
        <p className="section-kicker">YOUR STORY, IN HISTORY</p>
        <h2>당신의 시간은<br />어떤 역사와 만나나요?</h2>
        <p>당신의 이야기에서 시작해 보세요.</p>
        <a className="button-primary" href="/life.html">내 이야기 시작하기 <span aria-hidden="true">→</span></a>
      </section>

      <footer className="landing-footer">
        <a className="landing-brand" href="/"><Mark /><span>histgraph</span></a>
        <span>세상의 시간과 나의 시간을 잇습니다.</span>
        <div><a href="/n/">역사 읽기</a><a href="/about.html">제작 방식</a><a href="/privacy.html">개인정보처리방침</a><a href="/terms.html">이용약관</a></div>
      </footer>
    </main>
  );
}
