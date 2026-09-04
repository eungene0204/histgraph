// `npm run dev` 한 줄로 화면과 API 를 함께 띄운다.
//
// 왜 이 파일이 있나: vite 만 띄우면 화면 껍데기는 그려지는데 `/api` 프록시가
// 갈 곳이 없어 **그래프와 연표만 조용히 사라진다** (2026-09-04 실제로 겪었다 —
// vite 는 아침부터 떠 있었고 파이썬 쪽만 죽어 있었다). 머리글·범례·바닥글은
// 그대로라서 "데이터가 없나?" 로 보인다. 그러니 둘의 수명을 묶어 둔다.
import { spawn } from 'node:child_process';
import { connect } from 'node:net';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const API_PORT = 8100;

// 이미 다른 터미널에서 띄워 뒀으면 또 띄우지 않는다 (포트가 겹쳐 죽는다).
const listening = () => new Promise((done) => {
  const s = connect(API_PORT, '127.0.0.1');
  s.setTimeout(500);
  s.on('connect', () => { s.destroy(); done(true); });
  s.on('error', () => done(false));
  s.on('timeout', () => { s.destroy(); done(false); });
});

const kids = [];
// detached 로 띄워 프로세스 무리째 끈다 — `uv run` 은 파이썬을 자식으로
// 두므로 uv 만 죽이면 8100 을 잡은 파이썬이 남아 다음 실행이 막힌다.
const run = (cmd, args, cwd) => {
  const p = spawn(cmd, args, { cwd, stdio: 'inherit', detached: true });
  kids.push(p);
  return p;
};

if (await listening()) {
  console.log(`  API 는 이미 127.0.0.1:${API_PORT} 에 떠 있습니다 — 화면만 띄웁니다.`);
} else {
  run('uv', ['run', 'histgraph', 'serve'], ROOT);
}
const vite = run('npx', ['vite'], ROOT + 'web');

const stop = () => {
  for (const p of kids) { try { process.kill(-p.pid, 'SIGTERM'); } catch { /* 이미 죽었다 */ } }
};
process.on('SIGINT', () => { stop(); process.exit(0); });
process.on('SIGTERM', () => { stop(); process.exit(0); });
vite.on('exit', (code) => { stop(); process.exit(code ?? 0); });
