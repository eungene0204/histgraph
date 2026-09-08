import { useState } from 'react';
import { currentTheme, toggleTheme } from '../lib/theme.js';

// 단추를 화면에 세울지. 2026-09-08 사용자: "light/dark 모드 토글 버튼은
// 삭제하지 말고 안 보이게 해줘 나중에 필요하면 보이게 하자."
//
// **켜고 끄는 자리는 여기 하나다** — 부르는 쪽(App·LifeView)은 고치지 않았다.
// 다시 세우려면 이 줄을 true 로 바꾸면 된다.
//
// 지운 것이 아니라 감춘 것이다. **테마 자체는 그대로 돈다** — 진실은
// <html data-theme> 이고, public/theme-boot.js 가 첫 그림 전에 저장값과
// 운영체제 설정(prefers-color-scheme)을 읽어 박는다. 단추가 없어도 밝은
// 화면을 쓰는 사람에게는 밝게 나온다. 바뀌는 것은 '사람이 손으로 뒤집는
// 길'뿐이다.
export const THEME_TOGGLE = false;

// 라이트/다크 단추. 상태의 진실은 <html data-theme> 이고(theme.js), 여기 state 는
// 아이콘을 다시 그리기 위한 거울이다. 아이콘은 **누르면 되는 것**을 그린다 —
// 어두운 화면에서는 해(밝게), 밝은 화면에서는 달(어둡게). 이름표도 같은 말.
export function ThemeToggle({ onChange }) {
  const [theme, setTheme] = useState(() => currentTheme());
  const light = theme === 'light';
  const label = light ? '어두운 화면으로' : '밝은 화면으로';
  const flip = () => {
    const next = toggleTheme();
    setTheme(next);
    onChange?.(next);
  };
  if (!THEME_TOGGLE) return null;

  return (
    <button className="clickable-icon theme-toggle" type="button"
            aria-label={label} title={label} onClick={flip}>
      {light ? <MoonIcon /> : <SunIcon />}
    </button>
  );
}

// lucide 의 sun · moon
function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}
function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}
