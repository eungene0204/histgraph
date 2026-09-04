import { useEffect, useRef } from 'react';
import { GraphView } from '../lib/graph-view.js';

// 캔버스는 React 가 그리지 않는다. 초당 60번 다시 그려지는 곳이라 가상
// DOM 을 통과시킬 이유가 없다 — React 는 자리를 잡아주고 GraphView 의
// 수명만 관리한다.
export function GraphCanvas({ viewRef, onSelect, onExpand, showLabels, note, empty, offline }) {
  const canvasRef = useRef(null);
  // **콜백을 ref 에 담아 넘긴다.** 그냥 넘기면 onSelect 가 바뀔 때마다
  // GraphView 를 새로 만들어야 하고, 그러면 매번 배치가 처음부터 다시
  // 튄다. 안에서는 늘 최신 것을 부르되 인스턴스는 하나로 둔다.
  const handlers = useRef({ onSelect, onExpand });
  handlers.current = { onSelect, onExpand };

  useEffect(() => {
    const view = new GraphView(canvasRef.current, {
      onSelect: (node) => handlers.current.onSelect(node),
      onExpand: (node) => handlers.current.onExpand(node),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      if (viewRef.current === view) viewRef.current = null;
    };
  }, [viewRef]);

  useEffect(() => {
    if (viewRef.current) viewRef.current.showLabels = showLabels;
  }, [showLabels, viewRef]);

  return (
    <main className="stage">
      {/* **id 를 지우지 말 것.** style.css 가 `#canvas` 로 크기(100%)와
          touch-action:none 을 준다. 빼면 캔버스가 기본 300×150 으로 줄어
          클릭 좌표가 어긋나고, 포인터 제스처를 브라우저가 가로챈다. */}
      <canvas id="canvas" ref={canvasRef} />
      {note && <div className="stage-note">{note}</div>}
      {/* 자료 서버가 죽어 있으면 화면은 '아무것도 안 고른 상태'와 똑같이
          비어 보인다. 그 둘을 가려 적는다 — 안 그러면 그래프와 연표가
          사라진 이유를 화면 어디에서도 알 수 없다. */}
      {empty && (
        <div className="empty">
          {offline
            ? <p>자료 서버에 닿지 못했습니다. 새로고침해도 그대로면 자료 서버(8100)가 떠 있는지 봅니다.</p>
            : <p>왼쪽 위 메뉴(☰)에서 시작점을 고르거나 위에서 검색하세요.</p>}
        </div>
      )}
    </main>
  );
}
