import { Fragment, useEffect, useRef } from 'react';
import { nodeColor } from '../lib/graph-view.js';
import {
  groupRelations, cardsFor, sentence, whyEmpty, fmtDate,
} from '../lib/relations.js';
import { Glyph } from './Glyph.jsx';

// 설명칸. 비어 있을 때 아무것도 그리지 않으면 "이 노드는 원래 설명이
// 없는 것"처럼 보인다. 왜 비었는지를 대신 적는다.
//
// 서버가 주는 설명은 **요약**이다 (첫 절 제목 앞의 도입부, 360자). 전문은
// 화면에 내지 않는다 — 2026-09-05 전문을 뿌린 것이 애드센스 '주의 필요'
// (스크랩)로 돌아왔다. 그래서 '전문 보기'도 없다.
//
// 출처는 **설명 아래 한 줄**에만 적는다 (`desc_origin`, 서버가 판정). 남의
// 글을 옮겨 왔으면 그렇다고 적는 것이 라이선스 의무라서 두는 §1 의 예외다.
// 서버가 출처를 모르면 아무것도 안 적는다 — 틀린 출처는 없는 것보다 나쁘다.
function Description({ d }) {
  if (!d.description) {
    return <p className="d-nodesc">설명 없음 — {whyEmpty(d)}</p>;
  }
  const o = d.desc_origin;
  return (
    <>
      <div className="d-desc open">{d.description}</div>
      {/* 넘겨주기를 따라온 글은 이 노드를 설명하는 글이 아닐 수 있다
          ('판의금부사' → '의금부'). 읽는 사람이 알고 읽어야 한다. */}
      {d.desc_via && (
        <p className="d-desc-src">‘{d.desc_via}’ 문서에서 넘겨받은 글입니다</p>
      )}
      {o && (
        <p className="d-desc-origin">
          {o.url
            ? <a href={o.url} target="_blank" rel="noopener nofollow">{o.name}</a>
            : o.name}
          {' 문서를 줄인 글입니다'}
          {o.license && (
            <>
              {' · '}
              {o.license_url
                ? <a href={o.license_url} target="_blank" rel="license noopener nofollow">{o.license}</a>
                : o.license}
            </>
          )}
        </p>
      )}
    </>
  );
}

function Evidence({ text, shared = false }) {
  return <div className={shared ? 'rel-ev shared' : 'rel-ev'}>“{text}”</div>;
}

export function DetailPanel({ node, prev, onClose, onBack, onVisit }) {
  const boxRef = useRef(null);

  // 옮겨간 곳은 머리부터 읽는다
  useEffect(() => { if (boxRef.current) boxRef.current.scrollTop = 0; }, [node?.id]);

  if (!node) return null;

  const d = node;
  const dates = [fmtDate(d.start), fmtDate(d.end)].filter(Boolean).join(' ~ ');
  const { groups, count } = groupRelations(d.relations || []);

  // 타고 들어온 관계를 맨 위에 한 줄로 적는다. 조선시대 중기에는 개체가 37개
  // 달려 있어, 방금 누른 황진이가 목록 어디에 있는지 다시 찾아야 했다.
  // 합쳐진 카드에서 가져온다 — 아래 목록과 다른 말을 하면 안 된다.
  const via = prev ? cardsFor(groups, prev.id) : [];

  return (
    <aside className="detail" ref={boxRef}>
      <button className="close" aria-label="닫기" onClick={onClose}>✕</button>
      <div>
        {prev && (
          <button className="d-back" title={`${prev.label}(으)로 돌아가기`} onClick={onBack}>
            <span aria-hidden="true">←</span> {prev.label}
          </button>
        )}

        {via.length > 0 && (
          <div className="d-via">
            {via.map((r, i) => (
              <Fragment key={`${r.other.id}-${r.type}-${i}`}>
                <div className="d-via-line">
                  <span className="rel-dot" style={{ background: nodeColor(r.other.type, r.other.group) }} />
                  <span>{sentence(r, d)}</span>
                </div>
                {[...new Set(r.evidence || [])].map((ev) => <Evidence key={ev} text={ev} />)}
              </Fragment>
            ))}
          </div>
        )}

        <span className="d-type">
          <Glyph type={d.type} group={d.group} size={11} /> {d.type_label}
        </span>
        <h2 className="d-title">{(d.names || [d.label]).join(' · ')}</h2>
        {dates && <div className="d-dates">{dates}</div>}

        <Description d={d} />

        {d.aliases?.length > 0 && (
          <>
            <div className="d-section-title">다른 이름</div>
            <div className="d-aliases">
              {d.aliases.map((a) => <span key={a}>{a}</span>)}
            </div>
          </>
        )}

        <div className="d-section-title">관계 {count}</div>
        {groups.length === 0 ? (
          <p className="hint">연결된 관계가 없습니다.</p>
        ) : groups.map((g) => (
          <div className="rel-group" key={g.head}>
            <div className="rel-head">{g.head} · {g.rels.length}</div>
            {g.shared.map((ev) => <Evidence key={ev} text={ev} shared />)}
            {g.rels.map((r, i) => {
              const own = (r.evidence || []).filter((ev) => !g.shared.includes(ev));
              return (
                // 상세에서 고른 상대가 화면에 없을 수 있다 — 그때는 그 노드로
                // 옮겨간다. 여기서 고른 것만 자취에 쌓인다: 지금 노드가
                // 데리고 있는 것이므로 그 밑으로 들어가는 것이 맞다.
                <button className="rel" key={`${r.other.id}-${r.dir}-${i}`}
                        onClick={() => onVisit(r.other.id, { nest: true })}>
                  <span className="rel-line">
                    <span className="rel-dot" style={{ background: nodeColor(r.other.type, r.other.group) }} />
                    <span className="rel-name">{r.other.label}</span>
                  </span>
                  {own.map((ev) => <Evidence key={ev} text={ev} />)}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </aside>
  );
}
