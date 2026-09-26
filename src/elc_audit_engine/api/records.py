"""病史時間軸查詢與就醫日錨點（11.1-02 BLOCKER-1、B-CR-03）。"""

from __future__ import annotations

import os
from datetime import date

from config import settings
from elc_audit_engine.case_store import CaseNotFoundError, CaseStore
from elc_audit_engine.record_aggregator import LocalFileProvider, PatientTimeline, build_timeline
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date
from elc_audit_engine.safe_paths import UnsafeIdentifierError

# records_degraded 原因文案（固定中文模板，不含 RECORDS_DIR 路徑／病歷號，
# T-1112-01）。records_source 四態：ok（實查成功）／absent（已查詢、病患缺席，
# C5 降級）／unconfigured（病歷來源未設定）／no_record_no（請求未帶病歷號）。
RECORDS_DEGRADED_REASONS = {
    "unconfigured": "病歷來源未設定（病歷目錄不存在）",
    "no_record_no": "請求未提供病歷號",
    "absent": "查無此病患病歷檔案",
}


def records_provider() -> LocalFileProvider | None:
    """RECORDS_DIR 存在 → LocalFileProvider；不存在 → None（「來源未設定」，
    不是「病患缺席」——兩者語意不同）。

    RecordProviderError（JSON 損毀等 infra 故障）向外穿透至統一 500
    （P0-2/T-1112-03，不吞成業務結論）。
    """
    if os.path.isdir(settings.RECORDS_DIR):
        return LocalFileProvider(settings.RECORDS_DIR)
    return None


def parse_visit_date(raw) -> date | None:
    """就醫日期 → date（ISO、西元 8 碼、民國 7 碼、115/07/10 等）；無法解析回 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    iso = parse_flexible_date(raw.strip())
    return date.fromisoformat(iso) if iso else None


def resolve_visit_date(store: CaseStore, data: dict, case_id: str) -> date | None:
    """病史時間窗錨點（B-CR-03）：請求 visit_date 優先，其次 CaseStore 案件 payload。"""
    visit = parse_visit_date(data.get("visit_date"))
    if visit is None and case_id:
        try:
            payload = store.get(case_id).payload or {}
        except (CaseNotFoundError, UnsafeIdentifierError):
            payload = {}
        visit = parse_visit_date(payload.get("visit_date"))
    return visit


def resolve_records_source(
    provider: LocalFileProvider | None, record_no: str, visit_date: date | None = None
) -> tuple[PatientTimeline | None, str]:
    """解析 timeline 與 records_source 四態。

    visit_date：半年病史窗的迄日（B-CR-03）。必須是就醫日而非今天——
    就醫日之後的紀錄不能證明當次醫令的必要性。未知時才退回今天
    （build_timeline 預設），並由呼叫端在回應標示 records_window_anchor。
    """
    if provider is not None and record_no:
        agg = build_timeline(provider, record_no, end_date=visit_date)
        return agg.timeline, ("absent" if agg.degraded else "ok")
    if provider is not None:
        return None, "no_record_no"
    return None, "unconfigured"


def degraded_reason(records_source: str, degraded: bool) -> str | None:
    return RECORDS_DEGRADED_REASONS.get(records_source) if degraded else None
