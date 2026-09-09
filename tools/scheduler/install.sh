#!/bin/sh
# 주간 수집을 이 맥에 건다 (launchd). 지우려면 --uninstall.
#
#   sh tools/scheduler/install.sh
#   sh tools/scheduler/install.sh --uninstall
#   sh tools/scheduler/install.sh --run        # 지금 한 번 돌려 본다
set -eu

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LABEL=space.histgraph.recent
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "  걷었습니다 ($LABEL)"
    exit 0
    ;;
  --run)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "  지금 한 번 돌립니다 — 로그: ~/.cache/histgraph/recent/$(date +%Y-%m-%d).log"
    exit 0
    ;;
esac

mkdir -p "$AGENTS" "$HOME/.cache/histgraph/recent"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__HOME__#$HOME#g" \
    "$ROOT/tools/scheduler/$LABEL.plist" > "$PLIST"

# 이미 걸려 있으면 갈아 끼운다.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"

echo "  걸었습니다 — 매주 월요일 09:00"
echo "  확인:  launchctl print $DOMAIN/$LABEL | head -20"
echo "  로그:  ~/.cache/histgraph/recent/"
