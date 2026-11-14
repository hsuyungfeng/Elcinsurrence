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

check_deep() {
    local deep_url="${ELC_HEALTH_DEEP_URL:-http://127.0.0.1:5000/api/health/deep}"
    local deep_state="$ROOT/logs/.healthcheck_deep_code"
    local deep_code
    deep_code="$(curl -s --max-time 10 -o "$ROOT/logs/health-deep.json" -w "%{http_code}" "$deep_url" 2>/dev/null || echo "000")"
    local prev_code
    prev_code="$(cat "$deep_state" 2>/dev/null || echo "")"
    if [ "$deep_code" != "$prev_code" ]; then
        echo "$deep_code" > "$deep_state"
        if [ -n "$prev_code" ]; then
            echo "$(ts) deep health status changed from $prev_code to $deep_code" >> "$LOG"
        fi
    fi
}

if curl -fsS --max-time 10 -o /dev/null "$URL"; then
    # 健康：清除失敗計數（僅在有異常紀錄時才寫日誌，避免每分鐘灌水）
    if [ -f "$STATE" ]; then
        echo "$(ts) recovered after $(cat "$STATE") failure(s)" >> "$LOG"
        rm -f "$STATE"
    fi
    check_deep
    exit 0
fi

check_deep

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
echo "$(ts) health check failed ($fails/$THRESHOLD) url=$URL" >> "$LOG"

if [ "$fails" -ge "$THRESHOLD" ]; then
    echo "$(ts) restarting $UNIT after $fails consecutive failures" >> "$LOG"
    systemctl --user restart "$UNIT" >> "$LOG" 2>&1
    rm -f "$STATE"
fi
exit 0
