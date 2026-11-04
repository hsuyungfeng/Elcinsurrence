"""病歷來源降級的說明文字政策（Phase 22-04：Flask-free，供服務層與路由共用）。"""

from __future__ import annotations

RECORDS_DEGRADED_REASONS = {
    "unconfigured": "病歷來源未設定（病歷目錄不存在）",
    "no_record_no": "請求未提供病歷號",
    "absent": "查無此病患病歷檔案",
}


def degraded_reason(records_source: str, degraded: bool) -> str | None:
    return RECORDS_DEGRADED_REASONS.get(records_source) if degraded else None

__all__ = ["RECORDS_DEGRADED_REASONS", "degraded_reason"]
