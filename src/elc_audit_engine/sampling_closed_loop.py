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

import dataclasses
from dataclasses import dataclass
from datetime import date

from elc_audit_engine import evidence_vault
from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
)
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.pipeline import run_presubmission_check
from elc_audit_engine.record_aggregator import build_timeline
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date
from elc_audit_engine.sampling_preview import split_soap

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
        records_source: 病歷來源四態（ok／absent／unconfigured／no_record_no）。
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
    records_source: str = "unconfigured"
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


def _soap_from_case(text: str) -> dict[str, str]:
    """案件本身的 SOAP 文字 → dict。無 S/O/A/P 標記時保留原文（key 為 raw），不丟資料。"""
    sections = split_soap(text)
    if sections:
        return sections
    return {"raw": text.strip()}


def _soap_to_text(soap: dict[str, str]) -> str:
    """SOAP dict → 可餵給 parse_soap_text 的文字。raw 原樣輸出。"""
    if "raw" in soap:
        return soap["raw"]
    return "\n".join(f"{key.upper()}: {soap[key]}" for key in ("s", "o", "a", "p") if soap.get(key))


def fallback_soap(store, payload: dict) -> tuple[dict | None, str]:
    """SOAP 缺漏時的降級來源：先用案件本身，再查 soap_templates（指定診斷 → 通用）。

    回傳 (soap dict 或 None, soap_source)。查無範本時回 (None, "none")，不拋例外，
    對應「病歷目錄缺席」的防禦性容錯。範本命中時 soap_source 為
    template_specific（指定診斷）或 template_general（通用範本）。
    """
    case_text = str(payload.get("soap") or "")
    if case_text.strip():
        return _soap_from_case(case_text), "case"

    order_code = str(payload.get("order_code") or "").strip()
    if not order_code:
        return None, "none"
    primary_dx = str(payload.get("primary_diagnosis") or "").strip()
    template = store.get_soap_template(order_code, primary_dx)
    if template is None:
        return None, "none"
    soap = {key: str(template["soap"].get(key) or "") for key in ("s", "o", "a", "p")}
    source = "template_specific" if template["scope"] == "specific" else "template_general"
    return soap, source


def resolve_soap_text(store, payload: dict) -> tuple[str, str]:
    """供預審使用的 SOAP 文字與來源：案件本身優先，缺漏時改用範本（僅供參考）。

    回傳 (text, soap_source)；皆無時回 ("", "none")。
    """
    soap, source = fallback_soap(store, payload)
    if soap is None:
        return "", source
    return _soap_to_text(soap), source


def build_review(
    *,
    judgment_level: str | None,
    rule_found: bool,
    records_degraded: bool,
    records_source: str,
    soap_source: str,
) -> dict:
    """由比對結果組出閉環的審查結果（狀態、來源與警示），供寫回與回應共用。

    規則：查無規則視為待判定（不以裸奔呈現）；SOAP 來自範本或缺漏時加警示。
    """
    level = judgment_level if rule_found else None
    warnings: list[str] = []
    if soap_source.startswith("template"):
        warnings.append("SOAP 取自範本（非本案病歷），判定僅供參考，須醫師審核。")
    elif soap_source == "none":
        warnings.append("無本案病歷且無範本，無 SOAP 可供比對。")
    if not rule_found:
        warnings.append("查無對應規則，請人工確認（不以裸奔呈現）。")
    warnings.extend(presubmission_warnings(level, records_degraded=records_degraded))
    return {
        "support_state": resolve_support_state(level, records_degraded=records_degraded),
        "judgment_level": level,
        "records_degraded": records_degraded,
        "records_source": records_source,
        "soap_source": soap_source,
        "warnings": warnings,
    }


def save_review(store, case_id: str, review: dict) -> None:
    """把審查結果覆寫到案件 payload["review"]（不改動案件其他欄位與主狀態機）。"""
    record = store.get(case_id)
    payload = dict(record.payload or {})
    payload["review"] = review
    store.update_payload(case_id, payload)


def _load_timeline(provider, record_no, visit_date):
    """病史時間軸（C5 降級）：來源未設定／未帶病歷號／病患缺席皆回 timeline=None，不拋例外。

    基礎設施故障（RecordProviderError）照常穿透，對應 P0-2。
    """
    if provider is None:
        return None, "unconfigured"
    if not record_no:
        return None, "no_record_no"
    aggregation = build_timeline(provider, str(record_no), end_date=visit_date)
    return aggregation.timeline, ("absent" if aggregation.degraded else "ok")


def run_closed_loop(
    store,
    case_id: str,
    *,
    provider,
    write_back: bool = True,
) -> ClosedLoopResult:
    """執行一次事前預審閉環並（可選）把結果寫回案件庫。

    流程：讀案件 → fallback_soap → 病史時間軸（C5 降級）→ 比對 → 狀態流轉 →
    佐證庫與檢驗、雲端病歷統計 → 寫回 payload["review"]。

    provider：病歷來源（LocalFileProvider 或 None＝未設定）；由呼叫端注入，
    避免本模組依賴 api 套件。寫回採覆寫，重跑同一案件結果一致（冪等）。
    """
    record = store.get(case_id)
    if record.kind != "sampling":
        raise ValueError(f"案件 '{case_id}' 不是抽樣預審案件")
    payload = dict(record.payload or {})

    soap, soap_source = fallback_soap(store, payload)
    record_no = payload.get("record_no")
    visit_date = _parse_visit_date(payload.get("visit_date"))
    timeline, records_source = _load_timeline(provider, record_no, visit_date)

    order_code = str(payload.get("order_code") or "").strip()
    case = SubmissionCase(record_no=record_no or None, orders=(OrderRecord(code=order_code),))
    if visit_date is not None:
        case = dataclasses.replace(case, visit_date=visit_date.isoformat())
    soap_doc = parse_soap_text(_soap_to_text(soap)) if soap else None
    result = run_presubmission_check(case, soap_doc, timeline)

    judgments = result.comparison.order_judgments
    if not judgments:
        raise ValueError("無有效醫令可預審")
    judgment = judgments[0]
    review = build_review(
        judgment_level=judgment.support_level,
        rule_found=judgment.rule_found,
        records_degraded=bool(result.comparison.records_degraded),
        records_source=records_source,
        soap_source=soap_source,
    )

    vault_key = evidence_vault.vault_key_for_case(record_no, payload.get("visit_date"))
    vault_file_count = 0
    if vault_key is not None:
        vault_file_count = sum(len(files) for files in evidence_vault.list_vault_files(vault_key).values())
    lab_count = sum(1 for item in payload.get("lab_results") or [] if isinstance(item, dict))
    cloud_attached = bool(str(payload.get("cloud_records") or "").strip())

    loop_result = ClosedLoopResult(
        case_id=case_id,
        support_state=review["support_state"],
        soap_source=soap_source,
        records_degraded=review["records_degraded"],
        records_source=records_source,
        vault_key=vault_key,
        vault_file_count=vault_file_count,
        lab_count=lab_count,
        cloud_attached=cloud_attached,
        warnings=tuple(review["warnings"]),
    )
    if write_back:
        save_review(store, case_id, {**review, "warnings": list(review["warnings"])})
    return loop_result


def _parse_visit_date(raw) -> date | None:
    """就醫日（ISO、西元 8 碼、民國 7 碼等）→ date；無法解析回 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    iso = parse_flexible_date(raw.strip())
    return date.fromisoformat(iso) if iso else None


__all__ = [
    "PENDING",
    "SOAP_SOURCES",
    "SUPPORT_STATES",
    "ClosedLoopResult",
    "build_review",
    "fallback_soap",
    "presubmission_warnings",
    "resolve_soap_text",
    "resolve_support_state",
    "run_closed_loop",
    "save_review",
]
