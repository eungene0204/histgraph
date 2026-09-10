import { useCallback, useEffect, useRef, useState } from 'react';
import { auth } from '../lib/auth.js';
import { forgetLife } from '../lib/lifestore.js';
import { GoogleMark } from './LoginModal.jsx';
import { SettingsModal } from './SettingsModal.jsx';

// 톱니 하나. 다른 아이콘들과 같은 결(24 격자·선 그리기)이라 크기만 달라진다.
function GearMark() {
  return (
    <svg className="account-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

// 머리 줄 오른쪽 끝의 계정 자리.
//
// **로그인 단추는 언제나 서 있는다** (2026-09-08 사용자: "그냥 로그인 버튼이
// 항상 보이게 해줘"). 처음엔 설정(auth.enabled)이 없으면 아무것도 안 세웠는데,
// 그러면 **아직 설정을 안 넣은 화면에서 이 기능이 없는 것처럼 보인다.**
// 지금은 늘 세우고, 아직 열리지 않았으면 눌렀을 때 한국어로 그렇게 말한다 —
// 구글로 보내지 않는다 (보내면 서버가 503 을 JSON 으로 뱉어 날것이 뜬다).
//
// 로그인한 뒤에는 **구글 프로필 사진 하나**로 바뀐다. 사진이 없는 계정이면
// 이니셜. 구글 계정 이름은 로마자인 경우가 흔한데(CLAUDE.md §1 — 화면에
// 한글 아닌 글을 띄우지 않는다), 자기 이름과 이메일은 자기만 보는 것이라
// **펼친 메뉴 안에서만** 보인다.
//
// 메뉴에는 **내가 누구인지와 갈 곳뿐이다.** 즐겨찾기·회원 탈퇴처럼 자리가
// 필요한 것은 '설정'이 여는 상자(SettingsModal)로 간다 — 처음엔 메뉴 안에서
// 장을 넘겼는데, 268px 판 안에서는 탈퇴 되묻기 한 문장이 판을 밀어냈다
// (2026-09-09 사용자: "서브메뉴로 가지 말고 사진처럼 모달을 보여줘").
export function AccountMenu() {
  const [state, setState] = useState({ enabled: false, user: null });
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(false);    // 설정 상자가 떠 있는 중
  const [busy, setBusy] = useState('');
  const [notReady, setNotReady] = useState(false);   // 아직 안 열렸다고 말하는 중
  const box = useRef(null);

  useEffect(() => { auth.me().then(setState); }, []);

  // 바깥을 누르거나 Esc 를 누르면 닫는다. 메뉴가 열린 채로 그래프를
  // 만지면 무엇이 눌린 것인지 알 수 없다.
  useEffect(() => {
    if (!open && !notReady) return undefined;
    const shut = () => { setOpen(false); setNotReady(false); };
    const away = (e) => { if (!box.current?.contains(e.target)) shut(); };
    const esc = (e) => { if (e.key === 'Escape') shut(); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open, notReady]);

  const openMenu = useCallback(() => setOpen((was) => !was), []);

  if (!state.user) {
    const ready = state.enabled;
    return (
      <div className="account" ref={box}>
        <button className="account-login" type="button"
                onClick={() => (ready ? auth.login() : setNotReady((v) => !v))}
                aria-expanded={notReady || undefined}
                title={ready ? '구글 계정으로 로그인합니다' : '로그인은 아직 준비 중입니다'}>
          <GoogleMark />
          <span>로그인</span>
        </button>
        {notReady && (
          <div className="account-menu account-wait" role="status">
            <b>로그인은 아직 준비 중입니다</b>
            <p>구글 계정으로 들어오는 길을 여는 중입니다. 열리면 이 단추로
               바로 들어오실 수 있습니다.</p>
            <p className="account-none">그동안에도 그래프를 보고 검색하는 데에는
               아무 제한이 없습니다.</p>
          </div>
        )}
      </div>
    );
  }

  const me = state.user;
  const logout = async () => {
    setBusy('logout');
    try {
      await auth.logout();
      // **나가면서 이 브라우저에 남은 내 역사를 지운다.** 계정에는 그대로
      // 있어 다시 들어오면 되살아나고, 다음에 이 컴퓨터를 쓰는 사람에게는
      // 아무것도 남지 않는다 (2026-09-11). 주인 표가 이미 한 겹 막지만,
      // 남의 삶을 기기에 남겨 둘 이유가 없다.
      forgetLife();
      location.reload();     // 세션이 사라졌다 — 화면을 처음부터 다시 그린다
    } catch (err) {
      setBusy('');
      setState((s) => ({ ...s, 오류: err.message }));
    }
  };

  return (
    <div className="account" ref={box}>
      <button className="account-face" type="button" onClick={openMenu}
              aria-expanded={open} aria-haspopup="menu" title="내 계정">
        {me.사진
          ? <img src={me.사진} alt="" referrerPolicy="no-referrer" />
          : <span className="account-initial">{(me.이름 || me.이메일 || '?').slice(0, 1)}</span>}
      </button>

      {open && (
        <div className="account-menu" role="menu">
          <div className="account-who">
            <b>{me.이름 || '내 계정'}</b>
            <span className="account-mail">{me.이메일}</span>
            <span className="account-since">
              {me.가입일 ? `${me.가입일} 가입` : '가입'}
              {me.관리자 && <em className="account-admin">관리자</em>}
            </span>
          </div>

          <div className="account-nav">
            <button type="button" className="account-row"
                    onClick={() => { setSettings(true); setOpen(false); }}>
              <GearMark /><span>설정</span>
            </button>
          </div>

          {state.오류 && <p className="account-error">{state.오류}</p>}

          <div className="account-acts">
            <button type="button" disabled={!!busy} onClick={logout}>
              {busy === 'logout' ? '나가는 중…' : '로그아웃'}
            </button>
          </div>
        </div>
      )}

      {settings && <SettingsModal user={me} onClose={() => setSettings(false)} />}
    </div>
  );
}
