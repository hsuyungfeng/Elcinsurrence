"""CaseStore appeal payload → submission 契約 dict 標準轉換層（D-05）。

純函式模組：**零 I/O、零 logging/print**（PHI 不入日誌，T-093-01）。
職責：把 `_to_appeal_case`（server.py:382-410）產出的 CaseStore appeal
payload（或 SubmissionCase 風格 dict）轉成 Phase 11 submission 契約
dict（field_mapping.py:122-127：case_class/case_seq/id_number/patient_name/
primary_diagnosis/clinic/submit_date/orders），缺欄誠實留空＋warnings 欄名、
**不捏造**（承襲 11-01 誠實降級原則）。

## 缺欄語意（比照 field_mapping.py:144-177）

- 契約 8 鍵缺則留空（None／空 list）並 `warnings.append(欄名)`；欄名與
  field_mapping 一致：案件分類/流水號/身份證字號/姓名/傷病名稱/審查科別/
  原申報日期。
- **id_number**：遮罩值（含 `*`）照印、禁止重建完整字號（T-093-02 /
  T-11-05）；無 `*` 且長度 ≥8 → 加「身份證字號（疑似未遮罩，請確認來源）」
  warning（比照 field_mapping.py:147-150 防呆），不阻斷。
- **orders**：payload 已有 `orders`（list[dict]，SubmissionCase 風格）→
  直通（既有資料非捏造）；否則由單筆案件 order_code/order_name 構造
  `[{"code": …, "name": …}]`（name 為 None 時省略該鍵）；order_seq 存在時
  映射至 orders[0]["seq"]。無任何醫令資料 → 空 list（誠實留空）。
- **visit_date/fee_year_month** 屬既有資料直通（非捏造），允許存在於
  submission（端到端用途），warnings 不因多餘鍵而觸發。
"""

from __future__ import annotations

from typing import Any

# submission 契約 8 鍵（對齊 field_mapping.py:122-127）。
CONTRACT_KEYS: tuple[str, ...] = (
    "case_class",
    "case_seq",
    "id_number",
    "patient_name",
    "primary_diagnosis",
    "clinic",
    "submit_date",
    "orders",
)

# 缺欄 warnings 欄名（比照 field_mapping.py:144-177 語意）。
_WARN_FIELD = {
    "case_class": "案件分類",
    "case_seq": "流水號",
    "id_number": "身份證字號",
    "patient_name": "姓名",
    "primary_diagnosis": "傷病名稱",
    "clinic": "審查科別",
    "submit_date": "原申報日期",
}

# 既有資料直通鍵（端到端用途；非捏造，不觸發 warnings）。
_PASSTHROUGH_KEYS: tuple[str, ...] = ("visit_date", "fee_year_month")


def build_submission_from_case(payload: dict) -> tuple[dict, list[str]]:
    """CaseStore appeal payload → (submission 契約 dict, warnings)。

    Args:
        payload: CaseStore appeal payload（`_to_appeal_case` 輸出）或
            SubmissionCase 風格 dict。

    Returns:
        (submission, warnings)：submission 為契約 8 鍵 dict（缺欄誠實留空），
        可含 visit_date/fee_year_month 等既有資料直通鍵；warnings 為缺欄
        欄名清單（僅欄名，不含值——T-093-01 PHI 不入 warnings）。

    Raises:
        TypeError: payload 非 dict（含定位訊息）。
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload 必須為 dict，收到 {type(payload).__name__}")

    warnings: list[str] = []

    # ── 契約鍵（orders 除外）：缺欄誠實留空＋warnings 欄名，不捏造 ──
    values: dict[str, Any] = {}
    for key in _WARN_FIELD:  # 7 個帶 warning 欄名的契約鍵（orders 另處理）
        value = payload.get(key)
        if not value:
            warnings.append(_WARN_FIELD[key])
        values[key] = value

    # ── id_number 防呆（比照 field_mapping.py:147-150，不阻斷）──
    id_number = values["id_number"]
    if id_number is not None and (
        "*" not in str(id_number) and len(str(id_number)) >= 8
    ):
        warnings.append("身份證字號（疑似未遮罩，請確認來源）")

    # ── orders：已有 orders 直通；否則單筆案件構造；全無則空 list ──
    orders = payload.get("orders")
    if isinstance(orders, list):
        pass  # 直通（SubmissionCase 風格，既有資料非捏造）
    elif payload.get("order_code"):
        order: dict[str, Any] = {"code": payload["order_code"]}
        if payload.get("order_name") is not None:
            order["name"] = payload["order_name"]
        if payload.get("order_seq") is not None:
            order["seq"] = payload["order_seq"]
        orders = [order]
    else:
        orders = []

    submission = {
        "case_class": values["case_class"],
        "case_seq": values["case_seq"],
        "id_number": id_number,
        "patient_name": values["patient_name"],
        "primary_diagnosis": values["primary_diagnosis"],
        "clinic": values["clinic"],
        "submit_date": values["submit_date"],
        "orders": orders,
    }

    # ── 既有資料直通（非捏造；warnings 不因多餘鍵而觸發）──
    for key in _PASSTHROUGH_KEYS:
        value = payload.get(key)
        if value is not None:
            submission[key] = value

    return submission, warnings
