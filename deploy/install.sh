#!/usr/bin/env bash
# ELC Audit Engine 主機一鍵安裝腳本 (Phase 32 Plan 32-15, D1, C6, D-32-02, D-32-11)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${ELC_INSTALL_ROOT:-$DEFAULT_ROOT}"

if [[ "$ROOT" =~ "#" ]]; then
    echo "錯誤：安裝目錄路徑不得包含 '#' 字元：$ROOT" >&2
    exit 1
fi

DRY_RUN=0
ASSUME_YES=0

render_units_to() {
    local target_dir="$1"
    mkdir -p "$target_dir"
    local units=(
        "elc-audit-engine.service"
        "elc-audit-engine-healthcheck.service"
        "elc-audit-engine-healthcheck.timer"
        "elc-backup.service"
        "elc-backup.timer"
    )
    for u in "${units[@]}"; do
        local src="$SCRIPT_DIR/$u"
        local dst="$target_dir/$u"
        if [ -f "$src" ]; then
            sed "s#@ROOT@#${ROOT}#g" "$src" > "$dst"
        fi
    done
}

write_default_env() {
    local env_path="$1"
    mkdir -p "$(dirname "$env_path")"
    touch "$env_path"
    chmod 600 "$env_path" 2>/dev/null || true

    local defaults=(
        "ELC_SERVER_HOST=0.0.0.0"
        "ELC_SERVER_PORT=5000"
        "ELC_DISCOVERY_ENABLED=1"
        "DATA_DIR=${ROOT}/data"
        "OUTPUT_DIR=${ROOT}/data/output"
    )

    for item in "${defaults[@]}"; do
        local key="${item%%=*}"
        if ! grep -q "^${key}=" "$env_path" 2>/dev/null; then
            echo "$item" >> "$env_path"
        fi
    done
}

detect_primary_ip() {
    local ip
    ip="$(ip route get 10.255.255.255 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="src")print $(i+1)}' || true)"
    if [ -z "$ip" ]; then
        ip="$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")"
    fi
    echo "$ip"
}

is_dhcp_ip() {
    local ip="$1"
    if command -v ip >/dev/null 2>&1; then
        if ip -j -4 addr show 2>/dev/null | grep -q "\"dynamic\":true"; then
            return 0
        fi
    fi
    return 1
}

# 旗標解析
while [[ $# -gt 0 ]]; do
    case "$1" in
        --render-units)
            if [ -z "${2:-}" ]; then
                echo "錯誤：--render-units 需要指定輸出目錄" >&2
                exit 1
            fi
            render_units_to "$2"
            exit 0
            ;;
        --write-env)
            if [ -z "${2:-}" ]; then
                echo "錯誤：--write-env 需要指定檔案路徑" >&2
                exit 1
            fi
            write_default_env "$2"
            exit 0
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --yes|-y)
            ASSUME_YES=1
            shift
            ;;
        -h|--help)
            echo "用法: $0 [選項]"
            echo "  --dry-run              模擬執行，不修改系統設定或啟用服務"
            echo "  --yes, -y              非互動模式，一律採用偵測值或預設值"
            echo "  --render-units <DIR>   渲染 systemd 單元檔到指定目錄"
            echo "  --write-env <FILE>     建立或補齊環境檔預設變數"
            exit 0
            ;;
        *)
            echo "未知的選項: $1" >&2
            exit 1
            ;;
    esac
done

echo "========================================================"
echo "   ELC Audit Engine 主機端自動安裝程式"
echo "   安裝目錄: $ROOT"
echo "========================================================"

# 1. 檢查前置環境 (check_prereqs)
if [ -f /etc/os-release ]; then
    OS_ID="$(grep -oP '(?<=^ID=).+' /etc/os-release | tr -d '"' || true)"
    if [ "$OS_ID" != "ubuntu" ]; then
        echo "【提醒】偵測到作業系統為 $OS_ID (非 Ubuntu)，建議以 Ubuntu 22.04/24.04 LTS 為主。"
    fi
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "【錯誤】未偵測到 uv 套件管理工具。"
    echo "請依官方文件安裝 uv 後重新執行此腳本："
    echo "  https://docs.astral.sh/uv/getting-started/installation/"
    echo "或使用 pip 安裝："
    echo "  pip install uv"
    exit 1
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# 2. 同步相依套件與目錄 (sync_deps)
mkdir -p "$ROOT/data" "$ROOT/logs"

if [ "$DRY_RUN" -eq 0 ]; then
    echo "正在同步 Python 虛擬環境與套件 (uv sync --no-config)..."
    (cd "$ROOT" && uv sync --no-config)
else
    echo "[DRY-RUN] 跳過 uv sync"
fi

# 3. 建立或補齊環境檔 (write_env)
USER_HOME="${HOME:-$(getent passwd "$USER" | cut -d: -f6)}"
ENV_FILE="$USER_HOME/.config/elc-audit-engine/env"
if [ "$DRY_RUN" -eq 0 ]; then
    write_default_env "$ENV_FILE"
else
    echo "[DRY-RUN] 建立環境檔範本於 $ENV_FILE"
fi

# 4. 偵測信任網段 (detect_trust)
TRUST_JSON=""
if [ -x "$ROOT/.venv/bin/python" ]; then
    TRUST_JSON="$("$ROOT/.venv/bin/python" -m elc_audit_engine.lan_trust --describe 2>/dev/null || true)"
elif command -v uv >/dev/null 2>&1; then
    TRUST_JSON="$(cd "$ROOT" && uv run --no-config python -m elc_audit_engine.lan_trust --describe 2>/dev/null || true)"
fi

# 只接受恰好一個偵測結果（D-32-16 安裝人員確認；D-32-17 多候選不自動決定）。
# 舊版以 grep 解析字串欄位，但 detected 為陣列，會靜默退回 127.0.0.1，導致診間全數被拒。
if grep -q "^ELC_TRUSTED_SUBNETS=" "$ENV_FILE" 2>/dev/null; then
    echo "沿用既有手動設定的信任網段（ELC_TRUSTED_SUBNETS）。"
else
    DETECTED_COUNT=0
    DETECTED_SUBNET=""
    if [ -n "$TRUST_JSON" ]; then
        PARSED="$(echo "$TRUST_JSON" | python3 -c 'import json,sys
d = json.load(sys.stdin)
det = d.get("detected") or []
print(len(det), det[0] if det else "")' 2>/dev/null || echo "0 ")"
        DETECTED_COUNT="${PARSED%% *}"
        DETECTED_SUBNET="${PARSED#* }"
    fi

    if [ "$DETECTED_COUNT" -ne 1 ]; then
        echo "錯誤：無法自動判定唯一的院內網段（偵測結果數量：$DETECTED_COUNT）。" >&2
        echo "請於 $ENV_FILE 手動加入 ELC_TRUSTED_SUBNETS=<院內網段，例如 192.168.68.0/24>，再重新執行安裝。" >&2
        if [ "$DRY_RUN" -eq 0 ]; then
            exit 1
        fi
    else
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "[DRY-RUN] 偵測到院內網段 $DETECTED_SUBNET（未寫入）"
        elif [ "$ASSUME_YES" -eq 1 ]; then
            echo "依 --yes 採用偵測到的院內網段: $DETECTED_SUBNET"
            echo "ELC_TRUSTED_SUBNETS=$DETECTED_SUBNET" >> "$ENV_FILE"
            echo "已設定信任網段: $DETECTED_SUBNET"
        else
            read -r -p "偵測到院內網段 $DETECTED_SUBNET。診間電腦須位於此網段，是否信任此網段？[y/N] " ANS
            case "$ANS" in
                y|Y|yes|YES)
                    echo "ELC_TRUSTED_SUBNETS=$DETECTED_SUBNET" >> "$ENV_FILE"
                    echo "已設定信任網段: $DETECTED_SUBNET"
                    ;;
                *)
                    echo "已取消安裝。請手動於 $ENV_FILE 設定 ELC_TRUSTED_SUBNETS 後再執行。" >&2
                    exit 1
                    ;;
            esac
        fi
    fi
fi

# 5. 詢問備份目的端 (ask_backup_root)
BACKUP_ROOT_VAL="${ELC_BACKUP_ROOT:-}"
if [ -n "$BACKUP_ROOT_VAL" ]; then
    if [ "$DRY_RUN" -eq 0 ] && ! grep -q "^ELC_BACKUP_ROOT=" "$ENV_FILE" 2>/dev/null; then
        echo "ELC_BACKUP_ROOT=$BACKUP_ROOT_VAL" >> "$ENV_FILE"
    fi
    echo "已指定備份目的端: $BACKUP_ROOT_VAL"
else
    echo "【備份設定】尚未設定外接備份媒體 (ELC_BACKUP_ROOT)。"
    echo "若有 exFAT 外接隨身硬碟或 NAS 掛載點，請日後於 $ENV_FILE 中設定 ELC_BACKUP_ROOT。"
fi

# 6. 安裝 systemd user 單元檔 (install_units)
SYSTEMD_USER_DIR="$USER_HOME/.config/systemd/user"
if [ "$DRY_RUN" -eq 0 ]; then
    render_units_to "$SYSTEMD_USER_DIR"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable --now elc-audit-engine.service elc-audit-engine-healthcheck.timer 2>/dev/null || true
        if [ -n "$BACKUP_ROOT_VAL" ]; then
            systemctl --user enable --now elc-backup.timer 2>/dev/null || true
        fi
    fi
else
    echo "[DRY-RUN] 渲染 systemd 單元檔至 $SYSTEMD_USER_DIR"
fi

# 7. 啟用 Linger (enable_linger)
if [ "$DRY_RUN" -eq 0 ] && command -v loginctl >/dev/null 2>&1; then
    LINGER="$(loginctl show-user "$USER" -p Linger 2>/dev/null | cut -d= -f2 || true)"
    if [ "$LINGER" != "yes" ]; then
        loginctl enable-linger "$USER" 2>/dev/null || {
            echo "【提醒】建議執行下列指令讓使用者登出後服務仍持續常駐："
            echo "  sudo loginctl enable-linger $USER"
        }
    fi
fi

# 8. UFW 防火牆提示
if command -v ufw >/dev/null 2>&1; then
    if sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
        echo "【防火牆提醒】UFW 處於啟用狀態，請確保允許診間連線："
        echo "  sudo ufw allow from $DETECTED_SUBNET to any port 5000 proto tcp"
        echo "  sudo ufw allow from $DETECTED_SUBNET to any port 5002 proto udp"
    fi
fi

# 9. 印出總結 (print_summary)
HOST_IP="$(detect_primary_ip)"
echo ""
echo "========================================================"
echo "   ELC Audit Engine 安裝完成！"
echo "========================================================"
if is_dhcp_ip "$HOST_IP"; then
    echo "【重要提示】目前主機 IP ($HOST_IP) 疑似由分享器 DHCP 動態分配。"
    echo "建議在診所分享器 (Router) 後台將主機 MAC 位址綁定為固定 IP，避免重開機後診間斷線。"
    echo ""
fi
echo "請在其他電腦開啟下列網址："
echo "  - 初次設定頁面: http://${HOST_IP}:5000/setup"
echo "  - 審查工作台  : http://${HOST_IP}:5000/"
echo "  - 系統狀態監控: http://${HOST_IP}:5000/status"
echo "========================================================"
