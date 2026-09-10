import { useEffect, useState } from 'react';
import { auth } from '../lib/auth.js';
import { forgetLife } from '../lib/lifestore.js';

// 설정 상자. 계정 메뉴의 '설정'이 이것을 세운다 (2026-09-09 사용자: "설정버튼을
// 누르면 서브메뉴로 가지 말고 사진처럼 모달을 보여줘").
//
// 판은 둘로 나뉜다 — 왼쪽에 무엇을 볼지, 오른쪽에 그 안의 줄들. 줄 하나는
// **왼쪽이 이름, 오른쪽이 그 줄에서 할 일**이다. 좁은 메뉴 안에서는 탈퇴
// 되묻기가 판을 밀어냈는데, 여기서는 제자리에 선다.
//
// 자리가 둘뿐이라 **찾기 칸은 두지 않는다** — 두 줄을 찾아 주는 칸은 자리만
// 차지한다. 자리가 늘면 그때 넣는다.

function UserMark() {
  return (
    <svg className="set-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" /><circle cx="12" cy="10" r="3" />
      <path d="M6.2 18.6a6 6 0 0 1 11.6 0" />
    </svg>
  );
}

function StarMark() {
  return (
    <svg className="set-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m12 3.6 2.6 5.27 5.82.85-4.21 4.1.99 5.79L12 16.87l-5.2 2.74.99-5.79-4.21-4.1 5.82-.85z" />
    </svg>
  );
}

const TABS = [
  { key: 'account', 이름: '계정', 아이콘: UserMark },
  { key: 'marks', 이름: '즐겨찾기', 아이콘: StarMark },
];

export function SettingsModal({ user, onClose }) {
  const [tab, setTab] = useState('account');
  const [marks, setMarks] = useState(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose?.(); };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onClose]);

  // 즐겨찾기는 그 자리를 열 때 한 번만 부른다.
  useEffect(() => {
    if (tab !== 'marks' || marks !== null) return;
    auth.bookmarks.list().then((r) => setMarks(r.목록)).catch(() => setMarks([]));
  }, [tab, marks]);

  const run = async (what, fn) => {
    setBusy(what);
    try {
      await fn();
      // 로그아웃이든 탈퇴든 세션이 사라진다 — 브라우저에 남은 내 역사도
      // 함께 지운다. 탈퇴는 계정에서도 지워지므로 여기 남으면 지운 것이 아니다.
      forgetLife();
      location.reload();     // 세션이 사라졌다 — 화면을 처음부터 다시 그린다
    } catch (err) {
      setBusy('');
      setError(err.message);
    }
  };

  const here = TABS.find((t) => t.key === tab);

  return (
    <div className="scrim" role="presentation"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className="set-box" role="dialog" aria-modal="true" aria-label="설정">
        <nav className="set-rail">
          <h4>설정</h4>
          <ul>
            {TABS.map(({ key, 이름, 아이콘 }) => (
              <li key={key}>
                <button type="button" className={key === tab ? 'set-tab on' : 'set-tab'}
                        aria-current={key === tab || undefined}
                        onClick={() => { setTab(key); setAsking(false); }}>
                  {아이콘()}<span>{이름}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <section className="set-pane">
          <button className="set-close" type="button" onClick={onClose} title="닫기" aria-label="닫기">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                 strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
          <h2>{here.이름}</h2>

          {error && <p className="account-error">{error}</p>}

          {tab === 'account' && (
            <div className="set-rows">
              <div className="set-row">
                <span>이메일</span>
                <b className="set-value">{user.이메일}</b>
              </div>
              <div className="set-row">
                <span>가입</span>
                <span className="set-pair">
                  {/* 표식은 값 칸 **밖에** 둔다 — 안에 넣으면 딱지 안의 딱지가 된다. */}
                  {user.관리자 && <em className="account-admin">관리자</em>}
                  <b className="set-value">{user.가입일 || '날짜를 모릅니다'}</b>
                </span>
              </div>
              <div className="set-row">
                <span>로그아웃</span>
                <button type="button" className="set-act" disabled={!!busy}
                        onClick={() => run('logout', auth.logout)}>
                  {busy === 'logout' ? '나가는 중…' : '로그아웃'}
                </button>
              </div>
              <div className="set-row">
                <span>{asking
                  ? '가입 정보와 담아 둔 것이 모두 지워집니다. 되돌릴 수 없습니다.'
                  : '회원 탈퇴'}</span>
                {!asking ? (
                  <button type="button" className="set-act set-danger" disabled={!!busy}
                          onClick={() => setAsking(true)}>회원 탈퇴</button>
                ) : (
                  <span className="set-pair">
                    <button type="button" className="set-act" onClick={() => setAsking(false)}>그만</button>
                    <button type="button" className="set-act set-danger" disabled={!!busy}
                            onClick={() => run('withdraw', auth.withdraw)}>
                      {busy === 'withdraw' ? '지우는 중…' : '지웁니다'}
                    </button>
                  </span>
                )}
              </div>
            </div>
          )}

          {tab === 'marks' && (
            <div className="set-rows set-list">
              {marks === null && <p className="account-none">불러오는 중입니다…</p>}
              {marks?.length === 0 && (
                <p className="account-none">아직 없습니다. 오른쪽 상세에서 별을 누르면 여기 담깁니다.</p>
              )}
              {marks?.map((m) => (
                <div className="set-row" key={m.id}>
                  {/* 메모는 이름 **바로 옆**이다 — 줄 오른쪽 끝으로 보내면 어느
                      이름에 붙은 메모인지 눈이 다시 왼쪽으로 돌아가야 한다. */}
                  <span>
                    <a href={`#${encodeURIComponent(m.id)}`} onClick={onClose}>{m.이름 || m.id}</a>
                    {m.메모 && <span className="set-note">{m.메모}</span>}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
