import { nodeColor } from '../lib/graph-view.js';

// 타입 색 견본. 모양은 다 원이고 색이 타입을 말한다 — 그래서 이 견본
// 옆에는 늘 타입 이름이 글자로 붙어 있어야 한다. 색만으로 읽어야 하는
// 자리를 만들지 않는 것이 팔레트 설계의 전제다.
export function Glyph({ type, group, size = 13 }) {
  const h = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: 'none' }} aria-hidden="true">
      <circle cx={h} cy={h} r={h - 2} fill={nodeColor(type, group)} />
    </svg>
  );
}
