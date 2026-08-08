"""官方紙本申復清單欄位組裝層（Phase 11 紙本申復清單列印）。

純函式模組：**無 I/O、不匯入 config/settings、不觸 config**（D-05——案件層
欄位一律由 payload/submission/facility 參數推導，不寫死在 config）。
職責：官方清單 14 個主表資料欄（含「傷病名稱」欄）＋7 個頭表欄的逐欄
來源對應、缺欄誠實降級（warnings 累積、永不捏造）、分頁決定。

## 欄位來源決策（本 session 讀碼核實）

- **患者層欄位（身份證字號/姓名/傷病名稱/審查科別/數量/金額）不在
  `AppealDraft`／`render_appeal_json` 中**——appeal JSON（render_appeal_json
  480-515）僅含 p1-p9 醫令段欄位與 sections，無身份證字號/姓名/數量/金額。
- **`CaseStore` appeal 案件 payload 的 `patient_name` 實測為 None**
  （server.py `_to_appeal_case`）——故患者層欄位一律由呼叫端另行提供的
  `submission` dict 供應（同一案件經申報 XML 匯入時才有）。
- **join key ＝ case_class（d1）＋ case_seq（d2）**：submission 的
  case_class/case_seq 與 payload 核對；orders 依 `seq`（p13 醫令序）對應
  各醫令行。
- **身份證字號**：`SubmissionCase` 無此欄、appeal JSON 亦無；唯一來源為
  `DeductionRecord.id_number`（欄 9，**健保署已遮罩後 4 碼**）。呼叫端自
  `DeductionRecord.id_number` 傳入 submission 的 `id_number` 鍵，本層
  **遮罩值照印或留空，禁止重建完整字號**（T-11-05）。
- **傷病名稱**：來源為 `submission.primary_diagnosis`（申報 XML d19，
  ICD-10）；缺席 → ""＋warning（T-11-05 誠實降級精神）。
- 每欄鍵值一律 `str` 或 `""`；所有缺欄（submission 缺席或鍵值 None/空）
  回傳 "" 並在 warnings 記錄欄位名，**不猜測補全**。

鍵名即官方資料欄順序（11-01-PLAN.md 權威契約）：案件分類/流水號/身份
證字號/姓名/傷病名稱/醫令序/內容/數量/金額/理由/審核意見/補付數量/
單價/補付金額（14 鍵；審核意見～補付金額為健保署填列欄，系統一律留空）。
"""

from __future__ import annotations

from typing import Any

# 主表資料列 14 個鍵（順序＝官方欄位順序）。
ROW_KEYS: tuple[str, ...] = (
    "案件分類",
    "流水號",
    "身份證字號",
    "姓名",
    "傷病名稱",
    "醫令序",
    "內容",
    "數量",
    "金額",
    "理由",
    "審核意見",
    "補付數量",
    "單價",
    "補付金額",
)

# 頭表 7 欄鍵（build_header 回傳 dict 的鍵）。
HEADER_KEYS: tuple[str, ...] = (
    "代號字碼",
    "醫療院所名稱",
    "審查科別",
    "原申報類別",
    "原申報日期",
    "年度",
    "月份",
)

# 民國年偏移（西元 = 民國 + 1911）。
_ROC_OFFSET = 1911


def _str_or_empty(value: Any) -> str:
    """None/空 → ""；其餘 → str（欄位值一律字串）。"""
    if value is None or value == "":
        return ""
    return str(value)


def _fmt_roc_date_iso(iso: str) -> str:
    """ISO `YYYY-MM-DD` → 民國 `YYY年M月D日`（模板「年月日」空欄語意）。"""
    parts = iso.split("-")
    if len(parts) != 3:
        return iso  # 非 ISO 原樣照印（誠實降級，不猜測）
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return iso
    return f"{int(year) - _ROC_OFFSET}年{int(month)}月{int(day)}日"


def _fmt_roc_year_month(yyyymm: str) -> str:
    """`YYYYMM` → 民國 `YYY年M月`（原申報日期備援，無日）。"""
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        return yyyymm
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    return f"{year - _ROC_OFFSET}年{month}月"


def _find_order_by_seq(submission: dict | None, order_seq: str | None) -> dict | None:
    """在 submission.orders 中依 `seq`（醫令序）找對應醫令；找不到回 None。"""
    if submission is None or order_seq is None:
        return None
    for order in submission.get("orders", []):
        if not isinstance(order, dict):
            continue
        if str(order.get("seq")) == str(order_seq):
            return order
    return None


def build_rows(
    payload: dict,
    facility: dict,
    *,
    submission: dict | None = None,
) -> tuple[list[dict], list[str]]:
    """組裝主表資料列（官方欄 ← payload/submission/facility 逐欄對應）。

    Args:
        payload: appeal_{流水號}.json 的內容（render_appeal_json 格式 dict，
            含 case_class/case_seq/order_seq/order_code/p1_order_seq/
            p2_order_code/p8_reason1/p9_reason2 等鍵；**無身份證字號/姓名/
            數量/金額鍵**——患者層欄位一律來自 submission，不得引用不存在的鍵）。
        facility: 院所層資料（D-04 dict；本函式僅備援使用，目前主表不取用）。
        submission: 自由 dict，可含 case_class/case_seq/id_number（遮罩後
            4 碼）/patient_name/primary_diagnosis/clinic/orders。orders 為
            list[dict]，每項含 code(p4)/total_qty(p10)/points(p12)/seq(p13)，
            依 seq＝醫令序對應行；金額欄=points、數量欄=total_qty，對應不到
            行即留空＋warning。

    Returns:
        (rows, warnings)：rows 為每筆醫令一列的 14 鍵 dict 清單（值一律
        str 或 ""）；warnings 累積缺欄欄位名（身份證字號/姓名/傷病名稱/
        審查科別/數量/金額）。
    """
    warnings: list[str] = []
    sub = submission if isinstance(submission, dict) else None

    # ── 案件層（payload）──
    case_class = _str_or_empty(payload.get("case_class"))
    case_seq = _str_or_empty(payload.get("case_seq"))
    order_seq = _str_or_empty(payload.get("order_seq") or payload.get("p1_order_seq"))
    order_code = _str_or_empty(payload.get("order_code") or payload.get("p2_order_code"))

    # ── 患者層（submission；缺席即留空＋warning，不捏造）──
    id_number = _str_or_empty(sub.get("id_number") if sub else None)
    if id_number == "":
        warnings.append("身份證字號")
    elif "*" not in id_number and len(id_number) >= 8:
        # 防呆：遮罩值應含 '*'（如 F10291**** 遮罩後 4 碼）；疑似完整
        # 身分證字號（無遮罩）不照印——加 warning 提示呼叫端，非阻斷。
        warnings.append("身份證字號（疑似未遮罩，請確認來源）")

    patient_name = _str_or_empty(sub.get("patient_name") if sub else None)
    if patient_name == "":
        warnings.append("姓名")

    primary_diagnosis = _str_or_empty(sub.get("primary_diagnosis") if sub else None)
    if primary_diagnosis == "":
        warnings.append("傷病名稱")

    clinic = _str_or_empty(sub.get("clinic") if sub else None)
    if clinic == "":
        warnings.append("審查科別")

    # ── 醫令層數量/金額（submission.orders 依 seq 對應；對應不到留空）──
    matched = _find_order_by_seq(sub, order_seq or None)
    if matched is None:
        total_qty = ""
        points = ""
        warnings.append("數量")
        warnings.append("金額")
    else:
        total_qty = _str_or_empty(matched.get("total_qty"))
        points = _str_or_empty(matched.get("points"))
        if total_qty == "":
            warnings.append("數量")
        if points == "":
            warnings.append("金額")

    # ── 內容：order_code 為主；submission.orders 對應行有 name 則附註「code name」──
    content = order_code
    if matched is not None:
        order_name = _str_or_empty(matched.get("name"))
        if order_name != "":
            content = f"{order_code} {order_name}"

    # ── 理由：p8/p9（reason1 為主、reason2 接續；非空段合併，均空則 ""）──
    reason1 = _str_or_empty(payload.get("p8_reason1") or payload.get("reason1"))
    reason2 = _str_or_empty(payload.get("p9_reason2") or payload.get("reason2"))
    if reason2:
        reason = reason1 + reason2
    else:
        reason = reason1

    row = {
        "案件分類": case_class,
        "流水號": case_seq,
        "身份證字號": id_number,
        "姓名": patient_name,
        "傷病名稱": primary_diagnosis,
        "醫令序": order_seq,
        "內容": content,
        "數量": total_qty,
        "金額": points,
        "理由": reason,
        # 健保署填列欄位：系統不產出，一律留空（誠實降級）。
        "審核意見": "",
        "補付數量": "",
        "單價": "",
        "補付金額": "",
    }
    return [row], warnings


def build_header(
    facility: dict,
    payload: dict,
    submission: dict | None,
    *,
    report_type: str = "送核",
) -> dict:
    """組裝頭表 7 欄（代號字碼/醫療院所名稱/審查科別/原申報類別/原申報日期/年度/月份）。

    Args:
        facility: 院所層資料（D-04 dict；code/name）。
        payload: appeal_{流水號}.json 內容（fee_year_month 為 YYYYMM）。
        submission: 自由 dict（clinic/submit_date）；缺席時相關欄位留空。
        report_type: 原申報類別參數——「送核」（預設，輸出「□送核」）或
            「補報」（輸出「□補報」）（RESEARCH Open Q#4：抽審即送核案件）。

    Returns:
        7 鍵 dict（HEADER_KEYS）。原申報日期優先 submit_date（ISO→民國
        年月日），備援 fee_year_month（民國年月）；年度/月份由
        fee_year_month（YYYYMM）拆解（年度為民國年、月份原樣 MM）。
    """
    code = _str_or_empty(facility.get("code"))
    name = _str_or_empty(facility.get("name"))
    sub = submission if isinstance(submission, dict) else None
    clinic = _str_or_empty(sub.get("clinic") if sub else None)

    report_label = f"□{report_type}" if report_type in ("送核", "補報") else "□送核"

    submit_date = _str_or_empty(sub.get("submit_date") if sub else None)
    fee_year_month = _str_or_empty(
        payload.get("fee_year_month") or (sub.get("fee_year_month") if sub else None)
    )
    if submit_date:
        report_date = _fmt_roc_date_iso(submit_date)
    elif fee_year_month:
        report_date = _fmt_roc_year_month(fee_year_month)
    else:
        report_date = ""

    if len(fee_year_month) == 6 and fee_year_month.isdigit():
        year = str(int(fee_year_month[:4]) - _ROC_OFFSET)
        month = fee_year_month[4:6]
    else:
        year, month = "", ""

    return {
        "代號字碼": code,
        "醫療院所名稱": name,
        "審查科別": clinic,
        "原申報類別": report_label,
        "原申報日期": report_date,
        "年度": year,
        "月份": month,
    }


def paginate(order_rows: list[dict], per_page: int = 15) -> list[list[dict]]:
    """醫令行分頁決定（RESEARCH A3：官方版式固定 15 行/頁，不增）。

    Args:
        order_rows: build_rows 產出的資料列清單。
        per_page: 每頁資料行數（官方模板主表 row2~row16 共 15 行）。

    Returns:
        list[list[dict]]：每頁一組資料列；空輸入回傳空清單。
    """
    if per_page <= 0:
        raise ValueError(f"per_page 必須為正整數，收到 {per_page!r}")
    return [
        order_rows[i : i + per_page] for i in range(0, len(order_rows), per_page)
    ]
