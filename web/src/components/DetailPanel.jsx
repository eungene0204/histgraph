import { Fragment, useEffect, useRef, useState } from 'react';
import { nodeColor } from '../lib/graph-view.js';
import {
  groupRelations, cardsFor, sentence, whyEmpty, fmtDate, LONG_DESC,
} from '../lib/relations.js';
import { Glyph } from './Glyph.jsx';
import { ChainPanel } from './ChainPanel.jsx';

// 설명칸. 비어 있을 때 아무것도 그리지 않으면 "이 노드는 원래 설명이
// 없는 것"처럼 보인다. 왜 비었는지를 대신 적는다.
//
// **어느 자료에서 왔는지는 적지 않는다.** 'Wikidata 한 줄 설명' 같은
// 딱지는 읽는 사람이 묻지 않은 것을 답하면서 정작 궁금한 것(이 사람이
// 누구인가)은 밀어낸다. 수집 경로는 화면이 아니라 props 에 남는다.
function Description({ d }) {
  const [open, setOpen] = useState(false);

  // 다른 노드로 옮겨가면 접힌 상태로 되돌린다
  useEffect(() => { setOpen(false); }, [d.id]);

  if (!d.description) {
    return <p className="d-nodesc">설명 없음 — {whyEmpty(d)}</p>;
  }
  // 접힌 높이를 넘길 만큼 길 때만 단추를 낸다. 세 줄짜리 글에 '전문 보기'가
  // 붙어 있으면 눌러도 아무 일이 없다.
  const long = d.description.length > LONG_DESC;
  return (
    <>
      <div className={`d-desc${long && !open ? '' : ' open'}`}>{d.description}</div>
      {/* 넘겨주기를 따라온 글은 이 노드를 설명하는 글이 아닐 수 있다
          ('판의금부사' → '의금부'). 읽는 사람이 알고 읽어야 한다. */}
      {d.desc_via && (
        <p className="d-desc-src">‘{d.desc_via}’ 문서에서 넘겨받은 글입니다</p>
      )}
      {long && (
        <button className="d-more" onClick={() => setOpen((v) => !v)}>
          {open ? '접기' : '전문 보기'}
        </button>
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

        {/* 인과 사슬은 관계 목록보다 먼저 — 한 걸음짜리 관계보다 여러
            걸음의 '왜'가 이 그래프가 답하려는 물음이다. */}
        <ChainPanel node={d} onVisit={onVisit} />

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
                    {r.type === 'caused' && r.edge_label && <span className="chain-kind">{r.edge_label}</span>}
                  </span>
                  {/* 인과는 이름만으로는 아무 말도 아니다 — 어떻게 이어졌는지를 같이 적는다 */}
                  {r.type === 'caused' && (r.as || r.how) && (
                    <span className="rel-how">{r.as && <b>{r.as}</b>}{r.as && r.how && ' · '}{r.how}</span>
                  )}
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
