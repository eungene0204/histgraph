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
import { LoginModal } from './src/components/LoginModal.jsx';
import { StoryLog } from './src/components/LifeView.jsx';
export { renderToString, App, SidePanel, DetailPanel, Glyph, ChainTree, PathView, LoginModal, StoryLog };
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
const { renderToString, App, SidePanel, DetailPanel, Glyph, ChainTree, PathView, LoginModal, StoryLog } = m;

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
    // 본다. 예외는 둘: 광고를 부르는 한 줄, 테마(라이트/다크)를 첫 그림 전에
    // 박는 한 줄. 둘 다 없어도 본문은 그대로 읽힌다 (테마는 어두운 기본값).
    const scripts = html.match(/<script[^>]*>/g) || [];
    ok(`${name} 은 본문이 스크립트에 기대지 않는다`,
       scripts.every((tag) => tag.includes('adsbygoogle.js') || tag.includes('/theme-boot.js')), scripts.join(' '));
    ok(`${name} 이 테마 설정을 따른다`, html.includes('src="/theme-boot.js"'));
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
  // 인과 도면이 꺼져 있는 동안 범례의 선은 전부 글자색이다 (인과는 굵기로만 갈린다)
  ok('범례의 인과 선은 굵은 글자색이다',
     !html.includes('#4f93bf') && /stroke="currentColor" stroke-width="2.8"/.test(html)
       && /stroke="currentColor" stroke-width="1.4" stroke-dasharray="5 4"/.test(html),
     html.match(/stroke="[^"]*"/g)?.join(' '));
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
  ok('관계 수가 적힌다', /관계\s*(<[^>]*>)*4/.test(plain(detailHtml)));   // 수는 칩(.flair)에 든다
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
  const chainRaw = renderToString(h(ChainTree, { data: tree, onVisit: () => {} }));
  ok('사슬은 화살표 글자가 아니라 실선으로 잇는다', !chainRaw.includes('←') && !chainRaw.includes('chain-arrow') && (chainRaw.match(/chain-elbow/g) || []).length === 2, chainRaw.slice(0, 300));
  ok('둘째 걸음은 한 단 더 들어가 있다', /padding-left:28px/.test(chainRaw) && /padding-left:14px/.test(chainRaw), chainRaw.match(/padding-left:[^;"]*/g)?.join(' '));
  // 부모(후금)의 점에서 자식(임진왜란)의 꺾인 선까지 줄기가 잇는다. 선은 점의
  // 한가운데(STEP 배수 + 4) 에 선다 — 후금 줄의 줄기 x = 14 + 4, 임진왜란 줄의 꺾인 선 x = 14 + 4.
  ok('자식이 있는 줄은 점 아래로 줄기를 내려 자식의 선과 잇는다',
     (chainRaw.match(/chain-stem/g) || []).length === 1 && /chain-stem" style="left:18px"/.test(chainRaw) && /chain-elbow" style="left:18px"/.test(chainRaw),
     chainRaw.match(/chain-(stem|elbow)" style="[^"]*"/g)?.join(' '));
  // 노드가 사건이 아니면 머리도 그 타입으로 부른다 (2026-09-06 지적:
  // 명성황후 상세에 '이 일이 부른 것'이 서 있었다).
  const personTree = { center: 'wd:MS',
    causes: [],
    effects: [{ id: 'wd:EU', kind: '원인', how: '', as: '', evidence: [], children: [] }],
    nodes: { 'wd:MS': { id: 'wd:MS', label: '명성황후', type: 'person', group: 'actor' },
             'wd:EU': { id: 'wd:EU', label: '을미사변', type: 'event', group: 'event' } } };
  const personChain = plain(renderToString(h(ChainTree, { data: personTree, onVisit: () => {} })));
  ok('인물 사슬의 머리는 사람을 사건처럼 부르지 않는다',
     personChain.includes('이 인물에서 비롯된 일') && !personChain.includes('이 일이 부른 것'), personChain.slice(0, 160));
  // '관련'은 방향을 말하지 않는다 (2026-09-06 지적). 이 나무는 이 노드에서
  // 뻗어 나간 쪽이므로 머리도 그 방향이어야 한다.
  ok('결과 쪽 머리는 방향을 말한다', !personChain.includes('이 인물 관련'), personChain.slice(0, 160));
  const placeTree = { ...personTree, center: 'wd:SEOUL',
    nodes: { ...personTree.nodes, 'wd:SEOUL': { id: 'wd:SEOUL', label: '서울', type: 'place', group: 'thing' } } };
  ok('장소 사슬의 머리는 장소로 부른다',
     plain(renderToString(h(ChainTree, { data: placeTree, onVisit: () => {} }))).includes('이 장소에서 비롯된 일'));

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

  // 긴 설명은 접어 둔다 (다섯 줄). 여는 것은 **서버가 이미 보낸 요약**의
  // 나머지지 전문이 아니다 — 전문은 화면에 내지 않는다 (2026-09-05
  // 애드센스 '주의 필요').
  ok('짧은 설명에는 전체 보기가 없다',
     !detailHtml.includes('전체 보기') && !detailHtml.includes('d-desc-more'));
  ok('짧은 설명은 접히지 않는다', detailHtml.includes('d-desc open'));
  const longHtml = renderToString(h(DetailPanel, {
    node: { ...node, description: '가'.repeat(400) },
    prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  ok('긴 설명에는 전체 보기가 붙는다', longHtml.includes('전체 보기'));
  ok('긴 설명은 접힌 채로 그려진다',
     longHtml.includes('class="d-desc"') && !longHtml.includes('d-desc open'),
     longHtml.match(/d-desc[^>]*/)?.[0]);
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
  const rewrittenHtml = renderToString(h(DetailPanel, {
    node: { ...node, desc_origin: { name: '한국어 위키백과', url: '', license: '', license_url: '', rewritten: true } },
    prev: null, onClose: () => {}, onBack: () => {}, onVisit: () => {},
  }));
  ok('새로 쓴 글은 그렇다고 말한다', plain(rewrittenHtml).includes('한국어 위키백과 문서를 바탕으로 새로 쓴 글입니다'));

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
  ok('타입 색이 그대로 나온다', html.includes('#3d84f5'), html);
  ok('모르는 타입은 갈래 색으로 물러난다',
     renderToString(h(Glyph, { type: 'nope', group: 'event' })).includes('#fb6c13'));
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

// --- 라이트/다크 --------------------------------------------------------
// 진실은 <html data-theme> 하나다. CSS 는 선택자로, 캔버스는 isLight() 로 읽는다.
{
  // 로그인 단추는 **언제나** 머리 줄 오른쪽에 있다 (2026-09-08 사용자: "그냥
  // 로그인 버튼이 항상 보이게 해줘"). 서버 렌더에는 효과가 안 돌아 /api/me 를
  // 물어보기 전 상태인데, 그때도 서 있어야 한다 — 설정이 없으면 사라지던
  // 예전 동작으로 되돌아가면 여기서 잡힌다.
  ok('로그인 단추는 설정이 없어도 머리 줄에 선다',
     appHtml.includes('class="account-login"') && appHtml.includes('로그인'),
     appHtml.slice(appHtml.indexOf('top-right')).slice(0, 300));

  // 2026-09-08 사용자: "삭제하지 말고 안 보이게 해줘 나중에 필요하면 보이게 하자."
  // 그래서 재는 것이 뒤집혔다 — 지금은 **안 보이는 것**이 맞고, 대신 되살릴
  // 스위치가 그 자리에 남아 있는지를 잰다. 지워 버리면 이 관문이 잡는다.
  const toggleSrc = readFileSync(join(WEB, 'src/components/ThemeToggle.jsx'), 'utf-8');
  ok('테마 단추는 감춰 두었다 (지운 것이 아니다)',
     !appHtml.includes('class="clickable-icon theme-toggle"')
     && /export const THEME_TOGGLE = (true|false)/.test(toggleSrc)
     && toggleSrc.includes('밝은 화면으로'),
     appHtml.slice(appHtml.indexOf('<header')).slice(0, 400));
  ok('스위치 하나를 켜면 되살아난다',
     /if \(!THEME_TOGGLE\) return null;/.test(toggleSrc));
  const css = readFileSync(join(WEB, 'style.css'), 'utf-8');
  ok('style.css 에 라이트 토큰이 있다', /:root\[data-theme="light"\]\s*\{[^}]*--color-base-00:\s*#ffffff/.test(css));
  ok('doc.css 에도 라이트 토큰이 있다',
     /:root\[data-theme="light"\]/.test(readFileSync(join(WEB, 'doc.css'), 'utf-8')));
  const boot = readFileSync(join(WEB, 'public/theme-boot.js'), 'utf-8');
  ok('부팅 스크립트가 저장값과 운영체제 설정을 읽는다',
     boot.includes("getItem('theme')") && boot.includes('prefers-color-scheme') && boot.includes('dataset.theme'));
  ok('index.html 이 첫 그림 전에 테마를 박는다',
     readFileSync(join(WEB, 'index.html'), 'utf-8').includes('src="/theme-boot.js"'));
}

// --- 내 역사는 로그인을 묻는다 -------------------------------------------
// 2026-09-08 사용자: "'내 역사' 버튼을 눌렀을때 로그인 안 돼쓰면 로그인 모달을
// 보여줘서 로그인을 하게 강제해. 내 역사는 개인별로 다 다르니깐."
{
  const box = plain(renderToString(h(LoginModal, {
    next: '/life.html', title: '내 역사는 로그인이 필요합니다',
    why: '내 역사는 사람마다 다릅니다.', dismissible: false,
  })));
  ok('로그인 상자가 왜 묻는지를 먼저 적는다',
     box.includes('내 역사는 로그인이 필요합니다') && box.includes('사람마다 다릅니다'), box.slice(0, 200));
  ok('구글로 들어가는 단추가 있다',
     box.includes('class="login-go"') && box.includes('구글 계정으로 로그인'));
  ok('약관과 방침으로 가는 길이 있다',
     box.includes('/terms.html') && box.includes('/privacy.html'));
  ok('닫을 수 없는 상자에는 돌아갈 자리를 준다',
     box.includes('한국사 그래프로 돌아가기') && !box.includes('나중에'));
  ok('아직 열리지 않았으면 누를 수 없는 단추를 세우지 않는다',
     !plain(renderToString(h(LoginModal, { title: 'ㄱ', why: 'ㄴ', ready: false })))
       .includes('class="login-go"'));

  // 머리 줄의 '내 역사'와 장 자체가 **둘 다** 막아야 한다 — 하나만 막으면
  // 주소를 치는 것으로 넘어간다.
  const appSrc = readFileSync(join(WEB, 'src/App.jsx'), 'utf-8');
  const lifeSrc = readFileSync(join(WEB, 'src/components/LifeView.jsx'), 'utf-8');
  ok("머리 줄의 '내 역사'가 로그인 전이면 옮겨가지 않는다",
     /!mine\?\.user.*preventDefault/s.test(appSrc) && appSrc.includes('setAskLogin(true)'));
  ok('주소로 곧장 들어와도 같은 문을 지난다',
     /if \(account\.enabled && !account\.user\)/.test(lifeSrc) && lifeSrc.includes('dismissible={false}'));
}

// --- 내가 적은 이야기 -----------------------------------------------------
// 2026-09-08 사용자: "'내 역사 입력하기' 오른쪽에 아이콘 하나 만들어서 누르면
// 사용자가 입력한 사용자의 역사 히스토리를 보여줘. 그래서 잘못된 입력을 고칠
// 수 있게 해줘."
{
  const box = plain(renderToString(h(StoryLog, {
    stories: [{ at: '', text: '잠실고딩학교 1학넌때 친구 김일권을 만났고' },
              { at: '2026-09-08', text: '2002년 3월에 30사단 입대' }],
    running: false, onPick: () => {}, onDrop: () => {}, onClose: () => {},
  })));
  ok('모달로 서고, 적은 글이 누를 수 있는 줄이 된다',
     box.includes('role="dialog"') && box.includes('aria-modal="true"')
     && (box.match(/class="life-log-item"/g) || []).length === 2
     && box.includes('잠실고딩학교 1학넌때'), box.slice(0, 240));
  // 2026-09-08 사용자: "최신 입력한 내용이 가장 위에 있어야해" · "'적은 날을
  // 모릅니다' 문장을 삭제해". 뒤에 적은 것이 위에 서되 글의 차례는 그대로다.
  ok('새로 적은 것이 맨 위에 선다',
     box.indexOf('30사단 입대') < box.indexOf('잠실고딩학교'), box.slice(0, 200));
  ok('적은 날을 적고, 모르면 아무 말도 안 한다',
     box.includes('2026년 9월 8일') && !box.includes('모릅니다'));
  // 2026-09-08 사용자: 설명 문단도, '고쳐서 다시 읽기' 도 뺐다. 남는 것은
  // 제목 · 누를 수 있는 줄 · 줄마다 '삭제' · '닫기' 뿐이다.
  ok('설명 문단도 다시 읽기 단추도 없다',
     !box.includes('이 글에서 그래프가 나옵니다') && !box.includes('다시 읽기')
     && box.includes('내가 적은 이야기') && box.includes('삭제') && box.includes('닫기'));
  const none = plain(renderToString(h(StoryLog, { stories: [], running: false, onPick: () => {}, onDrop: () => {}, onClose: () => {} })));
  ok('적은 것이 없으면 그렇게 적는다', none.includes('아직 적은 이야기가 없습니다'));
  // 머리 줄의 아이콘 — 그림만 서고 글자는 title·aria 로 말한다.
  const lifeSrc2 = readFileSync(join(WEB, 'src/components/LifeView.jsx'), 'utf-8');
  ok("아이콘이 '내 역사 입력하기' 오른쪽에 선다",
     /내 역사 입력하기[\s\S]{0,900}life-log-btn/.test(lifeSrc2) && lifeSrc2.includes('aria-label="내가 적은 이야기"'));
  // 지우는 것은 기록 한 줄이다 — 그래프는 그대로고, 지운 자리는 브라우저와
  // 계정에 바로 남는다 (안 남기면 새로고침에 되살아난다).
  ok('삭제는 기록에서 빼고 바로 남긴다',
     /const dropStory = useCallback/.test(lifeSrc2)
     && /stories: list[\s\S]{0,400}keepInAccount\(doc\)/.test(lifeSrc2));
  // 누른 글은 입력창으로 간다 — 상자는 브라우저에 남긴 글을 읽고 서므로
  // 거기에 적고 상자를 새로 세운다 (key 가 바뀐다).
  ok('누른 글이 입력창으로 옮겨 간다',
     lifeSrc2.includes('appendDraft(cur, text)') && lifeSrc2.includes('localStorage.setItem(STORY_KEY, next)')
     && /<StoryBox key=\{draftStamp\}/.test(lifeSrc2));
  // 2026-09-08 사용자: "입력을 클릭해도 입력창에 복사가 안 되는 경우가 있어."
  // 상자가 **세워질 때** 칸을 비우던 효과가 방금 옮긴 글을 지웠다. 비우는 것은
  // 보낼 때 한 번이고, 못 보낸 글은 되돌린다.
  ok('상자는 세워질 때 칸을 비우지 않는다',
     !/job\?\.state !== 'done'\)\s*return;/.test(lifeSrc2)
     && /const send = \(\) => \{[\s\S]{0,200}removeItem\(STORY_KEY\)/.test(lifeSrc2));
  ok('못 보낸 글은 칸에 되돌린다',
     /putDraft\(text\);\s+\/\/ 못 보낸 글/.test(lifeSrc2)
     && /st\.state === 'error' && sentRef\.current/.test(lifeSrc2));
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
