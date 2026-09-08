import { useEffect, useRef } from 'react';
import { GraphView } from '../lib/graph-view.js';

// 캔버스는 React 가 그리지 않는다. 초당 60번 다시 그려지는 곳이라 가상
// DOM 을 통과시킬 이유가 없다 — React 는 자리를 잡아주고 GraphView 의
// 수명만 관리한다.
// `onReady(view)` 는 GraphView 를 **만들 때마다** 부른다. 개발 모드의 StrictMode 가
// 마운트 직후 한 번 떼었다 다시 붙이는데, 그때 새로 만든 캔버스는 비어 있다 —
// 부모가 효과 한 번으로 setData 를 실어 두면 그 자료는 떼어진 첫 캔버스에 남고
// 화면의 캔버스는 빈 채다 (실측 2026-09-07: 개인 역사 그래프가 5173 에서만 안
// 보였다). 자료를 든 쪽이 이 신호로 다시 싣는다.
export function GraphCanvas({ viewRef, onSelect, onExpand, onCausalExit, onReady, settings, note, empty, offline }) {
  const canvasRef = useRef(null);
  // **콜백을 ref 에 담아 넘긴다.** 그냥 넘기면 onSelect 가 바뀔 때마다
  // GraphView 를 새로 만들어야 하고, 그러면 매번 배치가 처음부터 다시
  // 튄다. 안에서는 늘 최신 것을 부르되 인스턴스는 하나로 둔다.
  const handlers = useRef({ onSelect, onExpand, onCausalExit, onReady });
  handlers.current = { onSelect, onExpand, onCausalExit, onReady };

  useEffect(() => {
    const view = new GraphView(canvasRef.current, {
      onSelect: (node) => handlers.current.onSelect(node),
      onExpand: (node) => handlers.current.onExpand(node),
      onCausalExit: () => handlers.current.onCausalExit?.(),
    });
    viewRef.current = view;
    // 헤드리스 크롬(CDP)으로 화면을 검증할 때 붙잡을 손잡이. 화면 코드는 쓰지 않는다.
    window.__histgraphView = view;
    handlers.current.onReady?.(view);
    return () => {
      view.destroy();
      if (viewRef.current === view) viewRef.current = null;
    };
  }, [viewRef]);

  // 설정은 GraphView 의 필드·메서드로 흘러간다. 절마다 효과를 따로 두어
  // 슬라이더 하나가 움직일 때 배치를 다시 데우는 일이 없게 한다.
  const { showLabels, arrows, textFade, nodeScale, lineScale,
          centerForce, repelForce, linkDistance, hiddenEdges } = settings;
  useEffect(() => {
    if (viewRef.current) viewRef.current.showLabels = showLabels;
  }, [showLabels, viewRef]);
  useEffect(() => {
    viewRef.current?.setDisplay({ arrows, textFade, lineScale });
  }, [arrows, textFade, lineScale, viewRef]);
  useEffect(() => {
    viewRef.current?.setDisplay({ nodeScale });
  }, [nodeScale, viewRef]);
  useEffect(() => {
    viewRef.current?.setForces({ center: centerForce, repel: repelForce, link: linkDistance });
  }, [centerForce, repelForce, linkDistance, viewRef]);
  useEffect(() => {
    viewRef.current?.setEdgeFilter(hiddenEdges);
  }, [hiddenEdges, viewRef]);

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
            : <p>위에서 검색하거나, 왼쪽 위 조절 단추에서 시작점을 고르세요.</p>}
        </div>
      )}
    </main>
  );
}
