"""Phase 31: 快捷列按鈕狀態機、投影純函式與狀態文字 (D-31-01, D-31-02, D-31-08, D-31-11, D-31-24).

注意：本模組為純邏輯層，不依賴任何 GUI、urllib 或網路/音訊庫。
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Optional, Tuple

STATE_SOAPVOICE_OFFLINE = "SOAPVOICE_OFFLINE"
STATE_SERVER_OFFLINE = "SERVER_OFFLINE"
STATE_IDLE = "IDLE"
STATE_STARTING = "STARTING"
STATE_RECORDING = "RECORDING"
STATE_STOPPING = "STOPPING"
STATE_UPLOADING = "UPLOADING"
STATE_AWAITING_DRAFT = "AWAITING_DRAFT"
STATE_AWAITING_CONFIRM = "AWAITING_CONFIRM"
STATE_DRAFT_UNUSABLE = "DRAFT_UNUSABLE"
STATE_CONFIRMED = "CONFIRMED"
STATE_ARCHIVING = "ARCHIVING"
STATE_ARCHIVE_FAILED = "ARCHIVE_FAILED"
STATE_INTERRUPTED = "INTERRUPTED"
STATE_ERROR = "ERROR"

ALL_BAR_STATES: Tuple[str, ...] = (
    STATE_SOAPVOICE_OFFLINE,
    STATE_SERVER_OFFLINE,
    STATE_IDLE,
    STATE_STARTING,
    STATE_RECORDING,
    STATE_STOPPING,
    STATE_UPLOADING,
    STATE_AWAITING_DRAFT,
    STATE_AWAITING_CONFIRM,
    STATE_DRAFT_UNUSABLE,
    STATE_CONFIRMED,
    STATE_ARCHIVING,
    STATE_ARCHIVE_FAILED,
    STATE_INTERRUPTED,
    STATE_ERROR,
)

# 紅只在 IDLE 可按；綠只在 RECORDING 可按；黃只在 CONFIRMED 或 ARCHIVE_FAILED 可按
ENABLED: Dict[str, FrozenSet[str]] = {
    STATE_IDLE: frozenset({"red"}),
    STATE_RECORDING: frozenset({"green"}),
    STATE_CONFIRMED: frozenset({"yellow"}),
    STATE_ARCHIVE_FAILED: frozenset({"yellow"}),
}


def on_press(
    button: str,
    current_state: str,
    *,
    pending_action: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """依據當前狀態與進行中動作判定按鈕是否可點擊。

    回傳：(allowed: bool, toast: Optional[str])。
    若不可點擊，回傳 (False, 中文提示短句)。
    """
    if pending_action is not None:
        return False, "操作處理中，請稍候"

    allowed_buttons = ENABLED.get(current_state, frozenset())
    if button in allowed_buttons:
        return True, None

    if button == "red":
        return False, "目前非待命狀態，無法開始錄音"
    if button == "green":
        return False, "目前非錄音狀態，無法結束錄音"
    if button == "yellow":
        return False, "目前無可封存草稿"
    return False, "目前無法執行此操作"


def project(
    server_cycle: Optional[Dict[str, Any]],
    sv_status: Optional[Dict[str, Any]],
    *,
    server_online: bool,
    sv_online: bool,
    pending_action: Optional[str] = None,
) -> str:
    """純函式投影：由 server 循環狀態與 SoapVoice status 決定快捷列呈現之 BarState。

    規則順序：
    1. pending_action（防重擊）：starting → STARTING、stopping → STOPPING、archiving → ARCHIVING
    2. 離線判定：not sv_online → SOAPVOICE_OFFLINE、not server_online → SERVER_OFFLINE
    3. 無活躍循環（server_cycle 為 None 或為 ARCHIVED/ABANDONED）：
       - sv_status 為 RECORDING → INTERRUPTED
       - sv_status 為 ERROR → ERROR
       - 否則 → IDLE
    4. 活躍循環對應：
       - sv_status 為 ERROR → ERROR
       - RECORDING：若 sv cycle_id 不符或 sv 非 RECORDING → INTERRUPTED；否則 RECORDING
       - AWAITING_DRAFT：若 sv 有 pending chunks 或 sv 為 UPLOADING → UPLOADING；否則 AWAITING_DRAFT
       - AWAITING_CONFIRM / DRAFT_UNUSABLE / CONFIRMED / ARCHIVING / ARCHIVE_FAILED → 直接對應
    """
    if pending_action == "starting":
        return STATE_STARTING
    if pending_action == "stopping":
        return STATE_STOPPING
    if pending_action == "archiving":
        return STATE_ARCHIVING

    if not sv_online:
        return STATE_SOAPVOICE_OFFLINE
    if not server_online:
        return STATE_SERVER_OFFLINE

    c_state = server_cycle.get("state") if server_cycle else None

    # 無活躍循環
    if not c_state or c_state in ("ARCHIVED", "ABANDONED"):
        if sv_status and sv_status.get("state") == "RECORDING":
            return STATE_INTERRUPTED
        if sv_status and sv_status.get("state") == "ERROR":
            return STATE_ERROR
        return STATE_IDLE

    # 有活躍循環
    if sv_status and sv_status.get("state") == "ERROR":
        return STATE_ERROR

    if c_state == "RECORDING":
        sv_cycle_id = sv_status.get("cycle_id") if sv_status else None
        server_cycle_id = server_cycle.get("cycle_id") if server_cycle else None
        if not sv_status or sv_status.get("state") != "RECORDING" or sv_cycle_id != server_cycle_id:
            return STATE_INTERRUPTED
        return STATE_RECORDING

    if c_state == "AWAITING_DRAFT":
        if sv_status:
            pending = int(sv_status.get("chunks_pending") or 0)
            if pending > 0 or sv_status.get("state") == "UPLOADING":
                return STATE_UPLOADING
        return STATE_AWAITING_DRAFT

    if c_state in (
        STATE_AWAITING_CONFIRM,
        STATE_DRAFT_UNUSABLE,
        STATE_CONFIRMED,
        STATE_ARCHIVING,
        STATE_ARCHIVE_FAILED,
    ):
        return c_state

    return STATE_IDLE


def status_text(
    bar_state: str,
    sv_status: Optional[Dict[str, Any]] = None,
    server_cycle: Optional[Dict[str, Any]] = None,
) -> str:
    """產出快捷列顯示之中文短句（嚴禁包含病人姓名或任何 SOAP 內容）。"""
    if bar_state == STATE_SOAPVOICE_OFFLINE:
        return "SoapVoice 未連線"
    if bar_state == STATE_SERVER_OFFLINE:
        return "server 未連線"
    if bar_state == STATE_IDLE:
        return "待命"
    if bar_state == STATE_STARTING:
        return "啟動錄音中..."
    if bar_state == STATE_STOPPING:
        return "停止錄音中..."
    if bar_state == STATE_RECORDING:
        elapsed = int((sv_status or {}).get("elapsed_seconds") or 0)
        mm = elapsed // 60
        ss = elapsed % 60
        bound = bool((sv_status or {}).get("patient_bound", False))
        bound_txt = "（已綁定病人）" if bound else "（未綁定病人）"
        return f"錄音中 {mm:02d}:{ss:02d}{bound_txt}"
    if bar_state == STATE_UPLOADING:
        acked = int((sv_status or {}).get("chunks_acked") or 0)
        total = int((sv_status or {}).get("chunks_total") or 0)
        return f"上傳中 {acked}/{total}"
    if bar_state == STATE_AWAITING_DRAFT:
        return "等待草稿"
    if bar_state == STATE_AWAITING_CONFIRM:
        return "請確認草稿"
    if bar_state == STATE_DRAFT_UNUSABLE:
        return "草稿品質未通過，請在確認視窗修改"
    if bar_state == STATE_CONFIRMED:
        return "可封存"
    if bar_state == STATE_ARCHIVING:
        return "HIS 寫入中"
    if bar_state == STATE_ARCHIVE_FAILED:
        err = (server_cycle or {}).get("last_error") or "寫入失敗"
        return f"封存失敗：{err}，可再按黃燈重試"
    if bar_state == STATE_INTERRUPTED:
        return "錄音中斷，請至 server 監控頁處理"
    if bar_state == STATE_ERROR:
        err = (sv_status or {}).get("last_error") or "發生異常"
        return f"錯誤：{err}"
    return "待命"
