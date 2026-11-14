#!/usr/bin/env bash
# ELC Audit Engine D4 每日增量備份任務
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ELC_DATA_DIR="${ELC_DATA_DIR:-$ROOT/data}"
export ELC_BACKUP_STATUS_FILE="${ELC_BACKUP_STATUS_FILE:-$ROOT/logs/backup-status.json}"

mkdir -p "$(dirname "$ELC_BACKUP_STATUS_FILE")"

cd "$ROOT"

if command -v uv >/dev/null 2>&1; then
    exec uv run --no-config python -m elc_audit_engine.backup_job
elif [ -x "$ROOT/.venv/bin/python" ]; then
    exec "$ROOT/.venv/bin/python" -m elc_audit_engine.backup_job
else
    exec python3 -m elc_audit_engine.backup_job
fi
