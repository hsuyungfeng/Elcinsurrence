#!/usr/bin/env bash
# 健康檢查：探測 /api/health，連續失敗達門檻即重啟服務並記錄原因。
# 由 elc-audit-engine-healthcheck.timer 每分鐘呼叫一次。
set -u

URL="${ELC_HEALTH_URL:-http://127.0.0.1:5000/api/health}"
UNIT="${ELC_SERVICE_UNIT:-elc-audit-engine.service}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs/healthcheck.log"
STATE="$ROOT/logs/.healthcheck_failures"
THRESHOLD="${ELC_HEALTH_FAIL_THRESHOLD:-3}"

mkdir -p "$ROOT/logs"
ts() { date -Is; }

if curl -fsS --max-time 10 -o /dev/null "$URL"; then
    # 健康：清除失敗計數（僅在有異常紀錄時才寫日誌，避免每分鐘灌水）
    if [ -f "$STATE" ]; then
        echo "$(ts) recovered after $(cat "$STATE") failure(s)" >> "$LOG"
        rm -f "$STATE"
    fi
    exit 0
fi

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
echo "$(ts) health check failed ($fails/$THRESHOLD) url=$URL" >> "$LOG"

if [ "$fails" -ge "$THRESHOLD" ]; then
    echo "$(ts) restarting $UNIT after $fails consecutive failures" >> "$LOG"
    systemctl --user restart "$UNIT" >> "$LOG" 2>&1
    rm -f "$STATE"
fi
exit 0
