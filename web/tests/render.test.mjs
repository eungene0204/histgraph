// 화면이 실제로 조립되는지 — 브라우저 없이 서버 렌더링으로 잰다.
//
//   node web/tests/render.test.mjs
//
// 빌드가 되는 것과 그려지는 것은 다르다. 여기서는 컴포넌트를 진짜로
// 렌더해서 터지지 않는지, 그리고 **화면에 영어가 새지 않는지**를 본다.
// (효과(useEffect)는 서버 렌더링에서 돌지 않으므로 캔버스·연표는 자리만
// 잡힌 상태로 나온다 — 그거면 조립이 맞는지 보기엔 충분하다.)
import { createElement as h } from 'react';
import { build } from 'esbuild';
import { readFileSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

let pass = 0;
let fail = 0;
// React 는 인접한 텍스트 사이에 <!-- --> 를 끼운다 (하이드레이션 경계 표시).
// 화면에는 안 보이는 것이라 글자를 볼 때는 걷어내고 본다.
const plain = (html) => html.replace(/<!--\s*-->/g, '');

function ok(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? `\n      ${extra}` : ''}`); }
}

// **번들을 web/ 안에 둔다.** 임시 폴더에 두면 react-dom 을 못 찾는다 —
// 아래에서 의존성을 번들에 넣지 않고 Node 가 직접 해석하게 두기 때문이다.
const WEB = fileURLToPath(new URL('..', import.meta.url));
const out = join(WEB, `.render-test-${process.pid}.mjs`);

const ENTRY = `
import { renderToString } from 'react-dom/server';
import App from './src/App.jsx';
import { SidePanel } from './src/components/SidePanel.jsx';
import { DetailPanel } from './src/components/DetailPanel.jsx';
import { Glyph } from './src/components/Glyph.jsx';
import { ChainTree, PathView } from './src/components/ChainPanel.jsx';
export { renderToString, App, SidePanel, DetailPanel, Glyph, ChainTree, PathView };
`;

await build({
  stdin: { contents: ENTRY, resolveDir: WEB, loader: 'jsx' },
  bundle: true,
  format: 'esm',
  platform: 'node',
  jsx: 'automatic',
  // react·react-dom 은 번들에 넣지 않는다. 넣으면 CJS 안의 require('util')
  // 가 ESM 번들 안에서 터진다 — Node 가 알아서 풀게 두는 편이 맞다.
  packages: 'external',
  outfile: out,
  logLevel: 'silent',
});

const m = await import(`file://${out}`);
const { renderToString, App, SidePanel, DetailPanel, Glyph, ChainTree, PathView } = m;

console.log('\n조립 (서버 렌더링)');

// 컴포넌트는 **반드시 createElement 로 감싸 넘긴다.** 함수로 직접 부르면
// 훅이 React 바깥에서 돌아 "Invalid hook call" 로 터진다.
// --- 껍데기 -------------------------------------------------------------
let appHtml = '';
{
  // fetch 가 불려도 서버 렌더링에서는 효과가 안 도니 실제로는 안 불린다.
  // 혹시 불려도 터지지 않게 막아 둔다.
  globalThis.fetch = () => Promise.reject(new Error('서버 렌더링에서는 안 부른다'));
  appHtml = renderToString(h(App));
  ok('App 이 터지지 않고 그려진다', appHtml.length > 0);
  ok('머리·본문·캔버스 자리가 있다',
     appHtml.includes('class="top"') && appHtml.includes('class="layout')
     && appHtml.includes('<canvas'), appHtml.slice(0, 200));
  ok('연표 자리에 tl-head/tl-body 가 있다',
     appHtml.includes('tl-head') && appHtml.includes('tl-body'));
  ok('검색창이 있다', appHtml.includes('검색'));
  // 광고를 실으려면 방침·약관이 어느 화면에서든 한 번에 닿아야 한다.
  ok('바닥에 방침·약관 링크가 있다',
     appHtml.includes('href="/privacy.html"') && appHtml.includes('href="/terms.html"')
     && appHtml.includes('개인정보처리방침') && appHtml.includes('이용약관'),
     appHtml.slice(appHtml.indexOf('<footer')).slice(0, 300));
}

// --- 방침·약관 (리액트 바깥의 정적 문서) ---------------------------------
{
  const docs = [['개인정보처리방침', 'privacy.html'], ['이용약관', 'terms.html']];
  for (const [name, file] of docs) {
    const html = readFileSync(join(WEB, file), 'utf-8');
    ok(`${name} 페이지가 있다`, html.includes('<h1>') && html.length > 1000);
    // 본문이 스크립트에 기대면 안 된다 — 광고 심사와 검색 로봇이 빈 페이지를
    // 본다. 광고를 부르는 한 줄은 예외다 (본문은 그것 없이도 이미 다 있다).
    const scripts = html.match(/<script[^>]*>/g) || [];
    ok(`${name} 은 본문이 스크립트에 기대지 않는다`,
       scripts.every((tag) => tag.includes('adsbygoogle.js')), scripts.join(' '));
    ok(`${name} 이 광고를 부른다`, html.includes('adsbygoogle.js?client=ca-pub-'));
    ok(`${name} 에 그래프로 돌아가는 길이 있다`, html.includes('href="/"'));
  }
}

// --- 범례: CSS 가 기대하는 평평한 목록인가 -------------------------------
{
  const meta = {
    node_types: {
      person: { label: '인물', group: 'actor', count: 3635 },
      event: { label: '사건', group: 'event', count: 407 },
      period: { label: '시대', group: 'frame', count: 1164 },
      hidden: { label: '없는것', group: 'thing', count: 0 },
    },
  };
  const html = renderToString(h(SidePanel, {
    meta, seeds: [{ id: 'a', label: '조선', type: 'period', group: 'frame', degree: 9 }],
    settings: { depth: 2, limit: 120, includePeriod: false, showLabels: true, showRail: true },
    onSettings: () => {}, onPick: () => {},
  }));
  ok('범례 묶음 머리가 항목과 같은 층에 있다',
     /<ul class="legend">\s*<li class="legend-group">/.test(html),
     html.slice(html.indexOf('legend') - 20, html.indexOf('legend') + 160));
  // `<ul class="legend">` **다음부터** 그것이 닫히는 데까지 또 <ul> 이 없어야
  // 한다. 여는 태그 자신을 세면 늘 걸린다.
  const OPEN = '<ul class="legend">';
  const inner = html.slice(html.indexOf(OPEN) + OPEN.length);
  ok('범례에 <ul> 이 중첩되지 않는다',
     !inner.slice(0, inner.indexOf('</ul>')).includes('<ul'),
     inner.slice(0, 120));
  ok('개수가 0 인 타입은 범례에 안 나온다', !html.includes('없는것'));
  ok('타입 이름이 색 견본 옆에 글자로 붙는다', html.includes('인물') && html.includes('사건'));
  ok('시작점이 나온다', html.includes('조선'));
}

// --- 상세 패널 ----------------------------------------------------------
let detailHtml = '';
{
  const node = {
    id: 'wd:Q37682', label: '조선 세종', type: 'person', group: 'actor',
    type_label: '인물', start: '1397-01-01', end: '1450-01-01',
    description: '조선의 제4대 국왕.', aliases: ['이도', '세종대왕'],
    relations: [
      { type: 'child_of', dir: 'out', label: '자녀', edge_label: '아버지',
        other: { id: 'p1', label: '조선 태종', type: 'person', group: 'actor' }, evidence: [] },
      { type: 'child_of', dir: 'in', label: '자녀',
        other: { id: 'p2', label: '문종', type: 'person', group: 'actor' }, evidence: [] },
      { type: 'created', dir: 'out', label: '만듦',
        other: { id: 'a1', label: '훈민정음', type: 'heritage', group: 'thing' },
        evidence: ['세종이 훈민정음을 만들었다'] },
      { type: 'caused', dir: 'in', label: '원인', edge_label: '배경', how: '집현전을 세워 학자를 길렀다',
        as: '집현전 설치', other: { id: 'e1', label: '집현전', type: 'org', group: 'actor' }, evidence: [] },
    ],
  };
  detailHtml = renderToString(h(DetailPanel, {
    node, prev: { id: 'p1', label: '조선 태종' },
    onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  ok('상세가 그려진다', detailHtml.includes('조선 세종'));
  ok('생몰이 한국어로 적힌다', detailHtml.includes('1397년 ~ 1450년'), detailHtml.match(/d-dates[^<]*<[^>]*>([^<]*)/)?.[1]);
  ok('다른 이름이 나온다', detailHtml.includes('세종대왕'));

  // 기축옥사의 별칭은 셋인데 무게가 다르다. '정여립의 난' 은 이 사건을
  // 부르는 **또 하나의 이름**이라 제목 줄에 서야 한다 — '다른 이름' 더미에
  // 넣으면 별명처럼 읽히고, 그 이름으로 이 사건을 아는 사람이 더 많다.
  const twoNamed = {
    id: 'wd:Q7836645', label: '기축옥사', names: ['기축옥사', '정여립의 난'],
    type: 'event', group: 'event', type_label: '사건',
    start: '1589-01-01', end: '1589-01-01',
    description: '조선 선조 때 발생한 옥사.',
    aliases: ['기축사화', '정여립의 옥사'],
    relations: [],
  };
  const twoHtml = renderToString(h(DetailPanel, {
    node: twoNamed, prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  const title = twoHtml.match(/d-title[^>]*>([^<]*)/)?.[1] ?? '';
  ok('제목에 두 이름이 나란히', title.includes('기축옥사') && title.includes('정여립의 난'), title);
  ok('표기 변형은 다른 이름에 남는다', twoHtml.includes('기축사화'));
  ok('이름이 하나면 제목도 하나',
     (renderToString(h(DetailPanel, {
       node, prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
     })).match(/d-title[^>]*>([^<]*)/)?.[1] ?? '') === '조선 세종');
  ok('부모와 자녀가 갈려 있다', detailHtml.includes('부모') && detailHtml.includes('자녀'));
  ok('관계 수가 적힌다', /관계 4/.test(plain(detailHtml)));
  ok('인과 카드에 종류와 어떻게가 적힌다',
     detailHtml.includes('rel-how') && plain(detailHtml).includes('집현전 설치') && plain(detailHtml).includes('집현전을 세워 학자를 길렀다'),
     detailHtml.match(/rel-how[\s\S]{0,160}/)?.[0]);
  ok('인과가 원인 묶음으로 선다', plain(detailHtml).includes('원인 · 1'));

  // 인과 사슬 나무와 경로 — 서버 없이 자료를 넣어 그린다
  const tree = { center: 'wd:BJ',
    causes: [{ id: 'wd:JIN', kind: '배경', how: '형제 관계를 요구했다', as: '후금의 파약 행위', evidence: [],
               children: [{ id: 'wd:IMJIN', kind: '배경', how: '명의 쇠퇴로 여진이 성장했다', as: '', evidence: [], children: [] }] }],
    effects: [],
    nodes: { 'wd:BJ': { id: 'wd:BJ', label: '병자호란', type: 'event', group: 'event' },
             'wd:JIN': { id: 'wd:JIN', label: '후금', type: 'org', group: 'actor' },
             'wd:IMJIN': { id: 'wd:IMJIN', label: '임진왜란', type: 'event', group: 'event', start: '1592' } } };
  const chainHtml = plain(renderToString(h(ChainTree, { data: tree, onVisit: () => {} })));
  ok('사슬에 원인의 원인까지 선다', chainHtml.includes('이 일을 부른 것') && chainHtml.includes('후금') && chainHtml.includes('임진왜란'), chainHtml.slice(0, 200));
  ok('사슬 줄에 서술구와 어떻게가 붙는다', chainHtml.includes('후금의 파약 행위') && chainHtml.includes('명의 쇠퇴로 여진이 성장했다'));
  ok('비어 있으면 사슬을 그리지 않는다', renderToString(h(ChainTree, { data: { causes: [], effects: [], nodes: {} }, onVisit: () => {} })) === '');
  const pathHtml = plain(renderToString(h(PathView, { data: {
    found: true, reversed: false, nodes: tree.nodes,
    paths: [[{ id: 'wd:IMJIN', edge: null }, { id: 'wd:JIN', edge: { kind: '배경', how: '명의 쇠퇴' } }, { id: 'wd:BJ', edge: { kind: '원인', how: '' } }]],
  }, onVisit: () => {} })));
  ok('경로에 걸음과 종류가 선다', pathHtml.includes('임진왜란') && pathHtml.includes('1592년') && pathHtml.includes('배경') && pathHtml.includes('병자호란'), pathHtml.slice(0, 300));
  ok('경로가 없으면 한국어로 말한다', plain(renderToString(h(PathView, { data: { found: false, paths: [], nodes: {} }, onVisit: () => {} }))).includes('이어지지 않습니다'));
  ok('타고 들어온 관계가 문장으로 머리에 붙는다',
     detailHtml.includes('조선 세종의 아버지는 조선 태종이다'),
     detailHtml.match(/d-via-line[\s\S]{0,200}/)?.[0]);
  ok('근거 구절이 따옴표 안에 들어간다', plain(detailHtml).includes('“세종이 훈민정음을 만들었다”'));
  ok('돌아가기 단추가 있다', detailHtml.includes('d-back'));

  // 서버가 요약을 주므로 화면은 접지 않고 '전문 보기'도 없다 — 전문을
  // 화면에 내지 않는다 (2026-09-05 애드센스 '주의 필요').
  ok('전문 보기가 없다', !detailHtml.includes('전문 보기') && !detailHtml.includes('d-more'));
  // 출처는 설명 아래 한 줄 — 이름은 문서로, 라이선스는 그 조문으로 이어진다.
  const originHtml = renderToString(h(DetailPanel, {
    node: { ...node, desc_origin: {
      name: '한국어 위키백과', url: 'https://ko.wikipedia.org/wiki/%EC%84%B8%EC%A2%85',
      license: '크리에이티브 커먼즈 저작자표시-동일조건변경허락 4.0',
      license_url: 'https://creativecommons.org/licenses/by-sa/4.0/deed.ko' } },
    prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  ok('출처가 설명 아래 한 줄로 선다',
     plain(originHtml).replace(/<[^>]+>/g, '').includes('한국어 위키백과 문서를 줄인 글입니다 · 크리에이티브 커먼즈 저작자표시-동일조건변경허락 4.0'),
     originHtml.match(/d-desc-origin[\s\S]{0,300}/)?.[0]);
  ok('출처 이름과 라이선스가 링크다',
     originHtml.includes('href="https://ko.wikipedia.org/wiki/%EC%84%B8%EC%A2%85"')
     && originHtml.includes('href="https://creativecommons.org/licenses/by-sa/4.0/deed.ko"'));
  ok('출처를 모르면 아무것도 안 적는다', !detailHtml.includes('d-desc-origin'));

  // 설명이 없으면 왜 없는지를 적는다
  const emptyHtml = renderToString(h(DetailPanel, {
    node: { ...node, description: null, source: 'extract' },
    prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  ok('설명이 없으면 이유를 적는다',
     emptyHtml.includes('산문에서 이름만 추출된 노드라 원문이 없습니다'));
  ok('관계가 없으면 그렇게 적는다',
     renderToString(h(DetailPanel, {
       node: { ...node, relations: [] }, prev: null,
       onClose: () => {}, onBack: () => {}, onVisit: () => {},
     })).includes('연결된 관계가 없습니다'));
}

// --- 색 견본 ------------------------------------------------------------
{
  const html = renderToString(h(Glyph, { type: 'person', group: 'actor' }));
  ok('타입 색이 그대로 나온다', html.includes('#4a6ad8'), html);
  ok('모르는 타입은 갈래 색으로 물러난다',
     renderToString(h(Glyph, { type: 'nope', group: 'event' })).includes('#ec7e3e'));
}

// --- CSS 가 기대하는 것을 React 가 실제로 내는가 -------------------------
//
// style.css 는 그대로 두고 구조만 React 로 옮겼다. 그래서 **선택자가 계약**
// 이다. 실제로 `#canvas` 의 id 를 지웠다가 캔버스가 기본 300×150 으로 줄어
// 노드 클릭이 죽었고, `#root` 에 세로 배치를 안 넘겨 연표 스크롤까지 같이
// 죽었다. 둘 다 화면을 열기 전에는 안 보였다.
{
  const css = readFileSync(new URL('../style.css', import.meta.url), 'utf-8');

  // **선언 블록을 먼저 걷어낸다.** 안 그러면 색값(`--text: #f0efec`)이
  // id 선택자로 잡힌다. 남는 것은 선택자뿐이다.
  const selectors = css.replace(/\{[^}]*\}/g, ' ');
  const ids = [...selectors.matchAll(/#([a-zA-Z][\w-]*)/g)].map((m) => m[1]);
  const missing = [...new Set(ids)]
    .filter((id) => id !== 'root')            // #root 는 index.html 이 낸다
    .filter((id) => !appHtml.includes(`id="${id}"`));
  ok('style.css 가 잡는 id 를 화면이 모두 낸다', missing.length === 0,
     `없는 것: ${missing.join(', ')}`);

  // body 가 세로 flex 라, #root 가 그걸 이어받지 않으면 .layout 의 flex:1 이
  // 기댈 곳을 잃는다 — 높이가 무너져 연표가 스크롤되지 않는다.
  ok('#root 가 body 의 세로 배치를 이어받는다',
     /#root\s*\{[^}]*flex[^}]*\}/.test(css)
     && /#root\s*\{[^}]*min-height:\s*0/.test(css),
     css.match(/#root\s*\{[^}]*\}/)?.[0] || '#root 규칙이 없다');
}

// --- 화면에 영어를 쓰지 않는다 -------------------------------------------
// 두 번 지적받은 규칙이다. 사람이 읽는 글자에 영어가 섞이면 안 된다 —
// 클래스 이름·속성·색값은 사람이 읽는 자리가 아니므로 뺀다.
{
  // 제품 이름과 범례에 일부러 적어 둔 자료 용어는 봐준다. 막으려는 것은
  // **설명이 영어로 새는 것**이지 이름 자체가 아니다. 방침·약관의 문의
  // 메일 주소도 같다 — 한글로 옮기면 편지가 오지 않는다.
  const visibleText = (html) => plain(html)
    .replace(/<[^>]+>/g, ' ')                  // 태그를 통째로 걷어낸다
    .replace(/histgraph|same_as/g, ' ')
    .replace(/[\w.+-]+@[\w.-]+/g, ' ');
  const leaks = [];
  const pages = [['App', appHtml], ['상세', detailHtml],
                 ['방침', readFileSync(join(WEB, 'privacy.html'), 'utf-8')],
                 ['약관', readFileSync(join(WEB, 'terms.html'), 'utf-8')]];
  for (const [name, html] of pages) {
    const found = visibleText(html).match(/[A-Za-z]{2,}/g);
    if (found) leaks.push(`${name}: ${[...new Set(found)].join(', ')}`);
  }
  ok('사람이 읽는 글자에 영어가 없다', leaks.length === 0, leaks.join('\n      '));
}

rmSync(out, { force: true });

console.log('\n==============================================');
console.log(`통과 ${pass} / 실패 ${fail}`);
process.exit(fail ? 1 : 0);
