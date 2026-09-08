import { useCallback, useEffect, useRef, useState } from 'react';
import { auth } from '../lib/auth.js';
import { GoogleMark } from './LoginModal.jsx';

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
export function AccountMenu() {
  const [state, setState] = useState({ enabled: false, user: null });
  const [open, setOpen] = useState(false);
  const [marks, setMarks] = useState(null);      // 즐겨찾기 (열 때 한 번)
  const [asking, setAsking] = useState(false);   // 탈퇴를 되묻는 중
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

  const openMenu = useCallback(() => {
    setOpen((was) => !was);
    setAsking(false);
    if (marks === null) auth.bookmarks.list().then((r) => setMarks(r.목록)).catch(() => setMarks([]));
  }, [marks]);

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
  const run = async (what, fn) => {
    setBusy(what);
    try {
      await fn();
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

          <div className="account-marks">
            <h4>즐겨찾기</h4>
            {marks === null && <p className="account-none">불러오는 중입니다…</p>}
            {marks?.length === 0 && (
              <p className="account-none">아직 없습니다. 오른쪽 상세에서 별을 누르면 여기 담깁니다.</p>
            )}
            {marks?.length > 0 && (
              <ul>
                {marks.slice(0, 12).map((m) => (
                  <li key={m.id}>
                    <a href={`#${encodeURIComponent(m.id)}`} onClick={() => setOpen(false)}>
                      {m.이름 || m.id}
                    </a>
                    {m.메모 && <span className="account-note">{m.메모}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {state.오류 && <p className="account-error">{state.오류}</p>}

          <div className="account-acts">
            <button type="button" disabled={!!busy}
                    onClick={() => run('logout', auth.logout)}>
              {busy === 'logout' ? '나가는 중…' : '로그아웃'}
            </button>
            {!asking ? (
              <button type="button" className="account-danger" disabled={!!busy}
                      onClick={() => setAsking(true)}>회원 탈퇴</button>
            ) : (
              <span className="account-confirm">
                가입 정보와 담아 둔 것이 모두 지워집니다. 되돌릴 수 없습니다.
                <span>
                  <button type="button" className="account-danger" disabled={!!busy}
                          onClick={() => run('withdraw', auth.withdraw)}>
                    {busy === 'withdraw' ? '지우는 중…' : '지웁니다'}
                  </button>
                  <button type="button" onClick={() => setAsking(false)}>그만</button>
                </span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
