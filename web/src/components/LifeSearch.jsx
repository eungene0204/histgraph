import { useEffect, useMemo, useRef, useState } from 'react';
import { Glyph } from './Glyph.jsx';
import { imeKey, isTyping, moveCursor } from '../lib/keys.js';
import { searchNodes } from '../lib/life.js';

// 내 역사의 검색 — 머리 줄 오른쪽 끝. 한국사 장의 검색(Search.jsx)과 두
// 가지가 다르다.
//
// 1. **서버에 묻지 않는다** (lib/life.js searchNodes). 그래서 쉬었다 묻는
//    시간(디바운스)도 없다 — 치는 대로 목록이 선다.
// 2. **'/' 를 글 치는 중에는 받지 않는다** (keys.js isTyping). 이 장에는
//    이야기를 적는 큰 상자와 편집 폼이 있어서, 안 보면 '/' 가 커서를 빼앗는다.
//
// 고른 노드는 연표·그래프·상세가 함께 따라간다 (LifeView 의 pick).
export function LifeSearch({ nodes, onPick }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const inputRef = useRef(null);
  const boxRef = useRef(null);

  const life = useMemo(() => ({ nodes: nodes || [] }), [nodes]);
  const rows = useMemo(() => (q.trim() ? searchNodes(life, q) : []), [life, q]);

  // '/' 로 검색창에 바로 간다
  useEffect(() => {
    const onKey = (ev) => {
      if (ev.key !== '/' || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (isTyping(document.activeElement)) return;
      ev.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // 바깥을 누르면 목록을 접는다
  useEffect(() => {
    const onClick = (ev) => {
      if (!boxRef.current?.contains(ev.target)) setOpen(false);
    };
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  const close = () => { setOpen(false); setCursor(-1); };

  const pick = (id) => { onPick?.(id); close(); inputRef.current?.blur(); };

  const onKeyDown = (ev) => {
    // 조립 중인 한글을 끝내는 키는 입력기에 맡긴다 (keys.js 머리글) — 여기서
    // 받으면 ↓ 가 두 칸 가고 Enter 가 한 글자 전의 결과를 고른다.
    if (imeKey(ev)) return;
    if (ev.key === 'Escape') { close(); inputRef.current?.blur(); return; }
    if (ev.key === 'Enter') {
      ev.preventDefault();
      if (rows.length) pick(rows[Math.max(cursor, 0)].id);
      return;
    }
    if (!rows.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      setOpen(true);
      setCursor((c) => moveCursor(c, ev.key, rows.length));
    }
  };

  return (
    <div className="search life-search" ref={boxRef}>
      <input
        ref={inputRef}
        type="search"
        placeholder="내 역사 검색   ( / )"
        aria-label="내 역사 검색"
        autoComplete="off"
        spellCheck="false"
        value={q}
        onChange={(ev) => { setQ(ev.target.value); setOpen(true); setCursor(-1); }}
        onFocus={() => { if (q.trim()) setOpen(true); }}
        onKeyDown={onKeyDown}
      />
      {open && q.trim() && (
        <ul className="results">
          {rows.length === 0 ? (
            <li className="empty-row">찾는 것이 없습니다</li>
          ) : rows.map((r, i) => (
            <li
              key={r.id}
              aria-selected={i === cursor}
              ref={i === cursor ? (el) => el?.scrollIntoView({ block: 'nearest' }) : null}
              onClick={() => pick(r.id)}
            >
              <Glyph type={r.type} group={r.group} size={11} />
              <span className="life-search-name">{r.name}</span>
              <span className="meta">{[r.kind_label, r.year != null ? `${r.year}년` : null].filter(Boolean).join(' · ')}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
