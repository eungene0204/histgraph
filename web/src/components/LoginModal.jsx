import { useEffect } from 'react';
import { auth } from '../lib/auth.js';

// 로그인을 물어보는 상자. **내 역사가 이것을 세운다** (2026-09-08 사용자:
// "'내 역사' 버튼을 눌렀을때 로그인 안 돼쓰면 로그인 모달을 보여줘서 로그인을
// 하게 강제해. 내 역사는 개인별로 다 다르니깐").
//
// 그래프는 로그인 없이 다 보인다. 막는 것은 **사람마다 다른 것** 하나뿐이라,
// 이 상자는 왜 여기서만 묻는지를 먼저 적는다 — 이유 없이 막는 화면은 그냥
// 닫힌 문이다.
//
// `dismissible` 이 거짓이면 닫는 단추 대신 **돌아갈 자리**를 준다. 막다른
// 곳에 세워 두지 않는다.
export function LoginModal({ next = '/', title, why, dismissible = true, onClose, ready = true }) {
  useEffect(() => {
    if (!dismissible) return undefined;
    const esc = (e) => { if (e.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [dismissible, onClose]);

  return (
    <div className="scrim" role="presentation"
         onMouseDown={(e) => { if (dismissible && e.target === e.currentTarget) onClose?.(); }}>
      <div className="login-box" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        <p>{why}</p>

        {ready ? (
          <button className="login-go" type="button" onClick={() => auth.login(next)}>
            <GoogleMark />
            <span>구글 계정으로 로그인</span>
          </button>
        ) : (
          // 설정이 아직 없는 화면(로컬·미리보기). 누를 수 없는 단추를 세워
          // 두는 대신 왜 안 되는지 적는다 — auth.enabled 를 화면이 그대로 읽는다.
          <p className="login-wait">
            구글 계정으로 들어오는 길을 여는 중입니다. 열리면 여기서 바로
            들어오실 수 있습니다.
          </p>
        )}

        <p className="login-fine">
          로그인하면 <a href="/terms.html">이용약관</a>과{' '}
          <a href="/privacy.html">개인정보처리방침</a>에 동의하는 것으로 봅니다.
          받는 것은 이름·이메일·프로필 사진뿐이고, 탈퇴하면 함께 지워집니다.
        </p>

        {dismissible
          ? <button className="login-back" type="button" onClick={onClose}>나중에</button>
          : <a className="login-back" href="/">한국사 그래프로 돌아가기</a>}
      </div>
    </div>
  );
}

// 구글의 표식. 로그인 단추에 이것을 다는 것이 구글 브랜드 지침이 요구하는
// 것이고, 읽는 사람에게도 '어느 계정으로 들어가는지'를 글자보다 빨리 말한다.
// **한 벌만 둔다** — 머리 줄의 계정 단추(AccountMenu)도 이것을 가져다 쓴다.
export function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.96 10.71a5.41 5.41 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  );
}
