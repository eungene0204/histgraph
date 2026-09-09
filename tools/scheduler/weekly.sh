#!/bin/sh
# 주마다 도는 사건 수집. launchd 가 부른다 (tools/scheduler/README.md).
#
# **사람이 없는 자리에서 돈다.** 그래서 하는 일이 셋뿐이다 — 걷고, 재고,
# 올린다. 판정이 안 서는 후보는 세우지 않고 로그에 이름만 남긴다
# (`data/recent.tsv` 에 사람이 적으면 다음 주에 들어온다).
#
# 관문은 새로 만들지 않았다. push 훅(tools/hooks/pre-push)이 한국어·파이썬·
# 화면·빌드를 다 재므로, 여기서 하는 일은 **훅이 재기 전에 멈출 자리**를
# 하나 더 두는 것뿐이다: 화면 DB 에 커밋 안 된 수정이 있으면 손대지 않는다.
# 이 저장소는 여러 세션이 동시에 만지고, DB 는 바이너리라 남의 작업 중인
# 파일을 커밋하면 통째로 실려 간다.
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd) || exit 1
cd "$ROOT" || exit 1

LOGDIR="$HOME/.cache/histgraph/recent"
mkdir -p "$LOGDIR" || exit 1
LOG="$LOGDIR/$(date +%Y-%m-%d).log"
exec >>"$LOG" 2>&1

# 두 번 겹쳐 돌지 않는다 (mkdir 은 원자적이다).
LOCK="$LOGDIR/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T')  이미 돌고 있습니다 — 건너뜁니다"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

DERIVED=data/korea.sqlite
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo
echo "=== $(date '+%F %T')  주간 수집 · $BRANCH ==="

# 0) 남의 작업 위에 올라타지 않는다.
if ! git diff --quiet -- "$DERIVED" || ! git diff --cached --quiet -- "$DERIVED"; then
  echo "  화면 DB 에 커밋 안 된 수정이 있습니다 — 다른 세션이 만지는 중일 수 있어"
  echo "  이번 주는 걷지 않습니다."
  exit 0
fi

# 1) 원본과 파생본에 한 번씩. 화면이 읽는 것은 파생본이다.
echo "--- 원본 (data/histgraph.sqlite)"
uv run histgraph recent || { echo "  수집 실패"; exit 1; }
echo "--- 파생본 ($DERIVED)"
# 파이프(tee)로 받지 않는다 — 파이프라인의 종료 코드는 tee 의 것이라
# 수집이 죽어도 성공으로 읽힌다. 파일로 받고 그대로 로그에 붓는다.
OUT="$LOGDIR/last.out"
uv run histgraph --db "$DERIVED" recent >"$OUT" 2>&1 || {
  cat "$OUT"; echo "  수집 실패"; exit 1; }
cat "$OUT"

if git diff --quiet -- "$DERIVED"; then
  echo "  새로 선 사건이 없습니다 — 커밋하지 않습니다."
  exit 0
fi

# 2) 관문. 배포될 DB 에 영어가 남았는지, 파이프라인이 성한지.
python3 tools/check_korean.py || { echo "  한국어 관문에 걸렸습니다"; exit 1; }
uv run tests/test_pipeline.py >/dev/null || { echo "  파이프라인 테스트 실패"; exit 1; }

# 3) 커밋 — **파일 이름을 대고 담는다.** 작업 트리의 다른 수정은 남의 것이다.
#    무엇이 들어왔는지를 커밋에 적는다. 사람이 나중에 보는 자리가 거기다.
# **한글이 바로 뒤에 오면 ${} 로 감싼다** — `$COUNT건` 은 셸이 변수 이름을
# 'COUNT건' 으로 읽어 unbound variable 로 죽는다 (실측: 첫 커밋이 그렇게
# 실패했다).
NEW=$(grep '^    + ' "$OUT" | sed 's/^    + /  /' | cut -c1-100)
COUNT=$(printf '%s\n' "$NEW" | grep -c .)
git add "$DERIVED" || exit 1
git commit -q -F - <<EOF || { echo "  커밋 실패"; exit 1; }
지금 일어나는 일 ${COUNT}건 — $(date '+%Y-%m-%d') 주간 수집

주마다 도는 수집(tools/scheduler/weekly.sh)이 한국어 위키백과의
'분류:{해}년 대한민국' 에서 걷어 화면 DB 에 세웠다.

$NEW

판정이 안 선 후보와 제외한 것은 $LOG 에 있다.
EOF

# 4) push. 훅이 여기서 한 번 더 잰다 — 걸리면 커밋은 남고 push 만 안 된다.
if git push -q origin HEAD; then
  echo "  올렸습니다 ($BRANCH)"
  [ "$BRANCH" = main ] || echo "  main 이 아니라 배포는 다음 병합 때 나갑니다"
else
  echo "  push 가 막혔습니다 — 커밋은 남아 있습니다 (사람이 보고 올리면 됩니다)"
  exit 1
fi
