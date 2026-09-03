import { useEffect, useRef } from 'react';
import { TimelineRail } from '../lib/timeline.js';

// 왼쪽 연표. 그래프는 무엇이 무엇과 이어져 있는지만 말하고 언제인지는
// 말하지 않는다 — 고른 노드를 시간 위에 얹어 주는 것이 이 막대의 일이다.
//
// TimelineRail 은 `.tl-head`·`.tl-body` 를 직접 찾아 쓰고 root 의 hidden 도
// 자기가 여닫는다. 그래서 **React 는 hidden 을 건드리지 않는다** — 둘이
// 같은 속성을 두고 다투면 보이다 말다 한다.
export function TimelinePanel({ railRef, data, onPick }) {
  const rootRef = useRef(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;

  useEffect(() => {
    const rail = new TimelineRail(rootRef.current, {
      onPick: (id) => onPickRef.current(id),
    });
    rootRef.current.hidden = true;   // 첫 화면에서는 접혀 있다
    railRef.current = rail;
    return () => {
      rail.destroy();
      if (railRef.current === rail) railRef.current = null;
    };
  }, [railRef]);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    if (data) rail.show(data);
    else rail.hide();
  }, [data, railRef]);

  return (
    <aside className="timeline" ref={rootRef}>
      <div className="tl-head" />
      <div className="tl-body" />
    </aside>
  );
}
