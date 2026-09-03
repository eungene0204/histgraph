import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api.js';
import { Glyph } from './Glyph.jsx';

// 검색. 치는 동안 계속 물으면 서버가 놀아나므로 140ms 쉬고 묻는다.
const DEBOUNCE_MS = 140;

export function Search({ nodeTypes, onPick }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState(null);   // null = 아직 안 물어봄
  const [cursor, setCursor] = useState(-1);
  const inputRef = useRef(null);
  const boxRef = useRef(null);

  // '/' 로 검색창에 바로 간다. 입력 중일 때는 그냥 글자로 들어가야 한다.
  useEffect(() => {
    const onKey = (ev) => {
      if (ev.key === '/' && document.activeElement !== inputRef.current) {
        ev.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // 바깥을 누르면 목록을 접는다
  useEffect(() => {
    const onClick = (ev) => {
      if (!boxRef.current?.contains(ev.target)) setRows(null);
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (!term) { setRows(null); return; }
    // 늦게 온 답이 최신 답을 덮지 않게 한다
    let alive = true;
    const timer = setTimeout(async () => {
      const found = await api.search(term);
      if (!alive) return;
      setRows(found);
      setCursor(-1);
    }, DEBOUNCE_MS);
    return () => { alive = false; clearTimeout(timer); };
  }, [q]);

  const close = () => { setRows(null); setCursor(-1); };

  const pick = (id) => { onPick(id); close(); };

  const onKeyDown = (ev) => {
    if (ev.key === 'Escape') { close(); inputRef.current?.blur(); return; }
    if (!rows?.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      setCursor((c) => (c + (ev.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length);
    } else if (ev.key === 'Enter') {
      pick(rows[Math.max(cursor, 0)].id);
    }
  };

  return (
    <div className="search" ref={boxRef}>
      <input
        id="q"
        ref={inputRef}
        type="search"
        placeholder="인물·사건·장소 검색   (예: 세종, 임진왜란, 이순신)"
        autoComplete="off"
        spellCheck="false"
        value={q}
        onChange={(ev) => setQ(ev.target.value)}
        onKeyDown={onKeyDown}
      />
      {rows && (
        <ul className="results">
          {rows.length === 0 ? (
            <li className="empty-row" style={{ color: 'var(--text-3)', cursor: 'default' }}>
              일치하는 개체가 없습니다
            </li>
          ) : rows.map((r, i) => (
            <li
              key={r.id}
              aria-selected={i === cursor}
              ref={i === cursor ? (el) => el?.scrollIntoView({ block: 'nearest' }) : null}
              onClick={() => pick(r.id)}
            >
              <Glyph type={r.type} group={r.group} size={11} />
              <span>{(r.names || [r.label]).join(' · ')}</span>
              <span className="meta">{nodeTypes?.[r.type]?.label} · {r.degree}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
