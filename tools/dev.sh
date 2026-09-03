#!/usr/bin/env bash
# 화면과 API 를 한 번에 띄운다 — `npm run dev` 가 부른다.
#
# 터미널 둘을 쓰는 걸 잊어 8100 이 비어 있는 채로 화면만 보게 되는 일이
# 잦았다. 파이썬 API 를 뒤에 띄우고 Vite 를 앞에 두되, 이 셸이 끝나면 API 도
# 같이 접는다 — 5173 을 닫았는데 8100 이 남아 다음 실행을 막는 걸 본다.
#
# serve 에 줄 인자는 그대로 넘어간다:  npm run dev -- --db data/histgraph.sqlite
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT_API=8100
API_PID=""

listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    echo ""
    echo "  API 를 접는다 (pid $API_PID)"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if listening "$PORT_API"; then
  # 이미 띄워 둔 것을 뺏지 않는다. 남의 것일 수도 있고, 껐다 켜면 그쪽
  # 터미널의 로그가 끊긴다.
  echo "  $PORT_API 은 이미 떠 있다 — 그대로 쓴다."
else
  PYTHONPATH=src python3 -m histgraph serve "$@" &
  API_PID=$!
  for _ in $(seq 1 60); do
    listening "$PORT_API" && break
    # 포트가 열리기 전에 죽었으면 기다릴 이유가 없다 (DB 없음, 포트 충돌 등).
    if ! kill -0 "$API_PID" 2>/dev/null; then
      echo "  API 가 뜨지 못했다. 위 오류를 보라." >&2
      exit 1
    fi
    sleep 0.25
  done
  listening "$PORT_API" || { echo "  API 가 $PORT_API 을 열지 않았다." >&2; exit 1; }
fi

echo "  화면: http://127.0.0.1:5173  — Ctrl+C 로 둘 다 종료"
npm run dev --prefix web
