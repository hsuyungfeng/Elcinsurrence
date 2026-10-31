"""抽樣案件事前預審自動化閉環（Plan 18-03 骨架）。

點選抽樣案件（如 62022C / `L221543164-2307`）時的自動流程：
1. 讀取案件 payload；SOAP 缺漏時降級為 `soap_templates` 範本（不拋例外）。
2. 依 `vault_key_for_case` 掛載 Evidence Vault 佐證檔案清單。
3. 帶入檢驗數據（lab_results）與健保跨院雲端病歷（cloud_records）。
4. 呼叫 `run_presubmission_check` 做醫令支持度預先審核。
5. 支持度狀態流轉：待判定 ⏳ → 充分 ✅ ／ 薄弱 ⚠️ ／ 裸奔 ❌。
6. 可選：產出預審卡片 HTML（sampling_preview）與健保局抽審 XML。

骨架狀態：
- 狀態常數、結果型別與 `resolve_support_state` 的硬性規則（None → 待判定）已實作。
- `run_closed_loop`、`fallback_soap` 以 NotImplementedError 佔位。
- 對應測試：tests/test_sampling_closed_loop.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
)

# 狀態字串沿用 comparator.models 的中文值，待判定為本模組新增的顯示狀態。
PENDING = "待判定"
SUPPORT_STATES: tuple[str, ...] = (PENDING, SUPPORT_SUFFICIENT, SUPPORT_WEAK, SUPPORT_NONE)

# soap_source 取值：案件本身 / 指定診斷範本 / 通用範本 / 無。
SOAP_SOURCES: tuple[str, ...] = ("case", "template_specific", "template_general", "none")


@dataclass(frozen=True)
class ClosedLoopResult:
    """閉環一次執行的結果，供路由組裝 JSON 回應與預審卡片。

    Attributes:
        case_id: 案件識別。
        support_state: 流轉後的支持度狀態（SUPPORT_STATES 之一）。
        soap_source: SOAP 來源（SOAP_SOURCES 之一）。
        records_degraded: 病歷缺席降級（僅以當次 SOAP 判定）。
        vault_key: 掛載的佐證庫鍵；None 表示無佐證庫。
        vault_file_count: 掛載的佐證檔案數量。
        lab_count: 帶入的檢驗筆數。
        cloud_attached: 是否帶入健保雲端病歷。
        warnings: 給醫師看的提示（如病歷缺席、範本降級）。
    """

    case_id: str
    support_state: str
    soap_source: str
    records_degraded: bool
    vault_key: str | None = None
    vault_file_count: int = 0
    lab_count: int = 0
    cloud_attached: bool = False
    warnings: tuple[str, ...] = ()


def resolve_support_state(judgment_level: str | None, *, records_degraded: bool) -> str:
    """把比對器的支持級別（或 None）轉成案件的顯示狀態。

    硬性規則：
    - 判定服務異常（judgment_level 為 None）一律回「待判定」，絕不可落為「裸奔」（P1-1）。
    - 病歷缺席（records_degraded=True，僅以當次 SOAP 判定）時，「充分」降為「薄弱」：
      缺少半年病史佐證，不宜直接標示為完全充分，應提醒醫師補強。
    - 未知字串直接拒絕。
    """
    if judgment_level is None:
        return PENDING
    if judgment_level not in (SUPPORT_SUFFICIENT, SUPPORT_WEAK, SUPPORT_NONE):
        raise ValueError(f"未知的支持級別：{judgment_level!r}")
    if records_degraded and judgment_level == SUPPORT_SUFFICIENT:
        return SUPPORT_WEAK
    return judgment_level


def presubmission_warnings(judgment_level: str | None, *, records_degraded: bool) -> tuple[str, ...]:
    """回傳給醫師看的提示文字（與狀態判定分開，便於路由直接附在回應中）。

    病歷缺席時一律加上提示；若因此由「充分」降為「薄弱」，另加補強說明。
    """
    if not records_degraded:
        return ()
    warnings = ["⚠ 本案未取得半年病史佐證（病歷缺席），僅以當次 SOAP 判定。"]
    if judgment_level == SUPPORT_SUFFICIENT:
        warnings.append("支持度由「充分」降為「薄弱」，請醫師補強病史佐證後再行判定。")
    return tuple(warnings)


def fallback_soap(store, payload: dict) -> tuple[dict | None, str]:
    """SOAP 缺漏時的降級來源：先用案件本身，再查 soap_templates（指定診斷 → 通用）。

    回傳 (soap dict 或 None, soap_source)。查無範本時回 (None, "none")，不拋例外，
    對應「病歷目錄缺席」的防禦性容錯。

    TODO(Plan 18-03)：呼叫 store.get_soap_template(order_code, primary_diagnosis)；
    其回傳的 scope 為 "specific" 或 "general"，需對應到 soap_source。
    """
    raise NotImplementedError("Plan 18-03: fallback_soap 尚未實作")


def run_closed_loop(
    store,
    case_id: str,
    *,
    records_provider=None,
    write_back: bool = True,
) -> ClosedLoopResult:
    """執行一次事前預審閉環並（可選）把結果寫回案件庫。

    流程：讀案件 → fallback_soap → 掛載佐證庫 → 帶入檢驗與雲端病歷 →
    run_presubmission_check → resolve_support_state → 寫回 payload（store.update_payload）。

    records_provider 為 None 時沿用系統預設 Provider；病歷缺席（PatientRecordsNotFound）
    必須降級為 records_degraded=True，不得讓服務拋出 500（P0-2／C5）。
    基礎設施故障（RecordProviderError）則照常穿透。

    TODO(Plan 18-03)：實作上述流程並保證冪等（重跑同一案件結果一致）。
    """
    raise NotImplementedError("Plan 18-03: run_closed_loop 尚未實作")


__all__ = [
    "PENDING",
    "SOAP_SOURCES",
    "SUPPORT_STATES",
    "ClosedLoopResult",
    "fallback_soap",
    "presubmission_warnings",
    "resolve_support_state",
    "run_closed_loop",
]
