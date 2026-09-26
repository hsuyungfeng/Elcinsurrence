"""
核減明細原格式列印欄位映射層。
"""
from __future__ import annotations
from typing import Any

ROW_KEYS = (
    "序號",
    "案件分類/病歷號",
    "就醫日期",
    "身分證號/出生日期",
    "姓名",
    "醫令序/代碼",
    "醫令名稱",
    "申報點數/數量",
    "不予核銷金額/核減點數",
    "核減代碼及說明",
    "追扣原因",
    "院所說明",
)

HEADER_KEYS = (
    "機構代碼",
    "醫療院所名稱",
    "費用年月",
    "申請申報日期",
    "抽審件數",
    "核減件數",
    "總核減點數",
)

_ROC_OFFSET = 1911

def _str_or_empty(value: Any) -> str:
    if value is None or value == "":
        return ""
    return str(value)

def _fmt_roc_year_month(yyyymm: str) -> str:
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        return yyyymm
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    return f"{year - _ROC_OFFSET}年{month}月"

def _fmt_roc_date_iso(iso: str) -> str:
    parts = iso.split("-")
    if len(parts) != 3:
        # maybe it's YYYYMMDD?
        if len(iso) == 8 and iso.isdigit():
            year = int(iso[:4])
            month = int(iso[4:6])
            day = int(iso[6:8])
            return f"{year - _ROC_OFFSET}年{month}月{day}日"
        return iso
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return iso
    return f"{int(year) - _ROC_OFFSET}年{int(month)}月{int(day)}日"

def _deduct_amount(record: dict) -> Any:
    """不予核銷金額：DeductionRecord 形狀用 non_reimbursed_amount，
    經 case_id 取回的 _to_appeal_case payload 則是 deduct_amount。"""
    value = record.get("non_reimbursed_amount")
    return value if value not in (None, "") else record.get("deduct_amount")

def _to_int(value: Any) -> int:
    """寬鬆轉整數（容忍 None／空字串／千分位）；非數字視為 0，不讓整張表 500。"""
    if value is None or value == "":
        return 0
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return 0

def build_deduction_header(records: list[dict], facility: dict) -> dict[str, str]:
    # header is derived from the first record if any, plus facility config
    if not records:
        return {k: "" for k in HEADER_KEYS}
    
    first = records[0]
    return {
        # facility.json 的正式鍵名為 code／name（settings.REQUIRED_FACILITY_FIELDS）；
        # institution_code／facility_name 為舊呼叫端鍵名，保留相容。
        "機構代碼": _str_or_empty(
            facility.get("code") or facility.get("institution_code") or first.get("institution_code")
        ),
        "醫療院所名稱": _str_or_empty(facility.get("name") or facility.get("facility_name")),
        "費用年月": _fmt_roc_year_month(_str_or_empty(first.get("fee_year_month"))),
        "申請申報日期": _fmt_roc_date_iso(_str_or_empty(first.get("submit_date"))),
        "抽審件數": "",  # To be filled by other stats if available, currently empty
        # 以 (案件分類, 流水號) tuple 去重：字串串接會讓 "1"+"23" 與 "12"+"3" 撞在一起，
        # 且值為 None 時串接會 TypeError。
        "核減件數": str(len({
            (_str_or_empty(r.get("case_class")), _str_or_empty(r.get("case_seq")))
            for r in records if r.get("case_class") or r.get("case_seq")
        })),
        "總核減點數": str(sum(_to_int(_deduct_amount(r)) for r in records)),
    }

def build_deduction_rows(records: list[dict], submission: dict | None = None) -> tuple[list[dict[str, str]], list[str]]:
    rows = []
    warnings = []
    
    for i, record in enumerate(records, start=1):
        row = {}
        row["序號"] = str(i)
        row["案件分類/病歷號"] = f"{_str_or_empty(record.get('case_class'))} / {_str_or_empty(record.get('chart_no'))}"
        row["就醫日期"] = _fmt_roc_date_iso(_str_or_empty(record.get("visit_date")))
        
        id_num = _str_or_empty(record.get("id_number"))
        if len(id_num) > 4:
            id_num = id_num[:-4] + "****"
        elif id_num:
            id_num = "****"
        row["身分證號/出生日期"] = f"{id_num} / {_fmt_roc_date_iso(_str_or_empty(record.get('birth_date')))}"
        
        # 姓名 from submission if missing
        patient_name = _str_or_empty(record.get("patient_name"))
        if not patient_name:
            if submission and "patient_name" in submission:
                patient_name = _str_or_empty(submission["patient_name"])
            else:
                warnings.append(f"Row {i}: 缺病患姓名")
        row["姓名"] = patient_name
        
        row["醫令序/代碼"] = f"{_str_or_empty(record.get('order_seq'))} / {_str_or_empty(record.get('order_code'))}"
        
        order_name = _str_or_empty(record.get("order_name"))
        if not order_name:
            warnings.append(f"Row {i}: 缺醫令名稱")
        row["醫令名稱"] = order_name
        
        row["申報點數/數量"] = f"{_str_or_empty(record.get('claimed_points'))} / {_str_or_empty(record.get('total_qty'))}"
        row["不予核銷金額/核減點數"] = _str_or_empty(_deduct_amount(record))
        
        code = _str_or_empty(record.get("appeal_item_code"))
        desc = _str_or_empty(record.get("appeal_item_desc"))
        row["核減代碼及說明"] = f"{code} - {desc}" if code and desc else (code or desc)
        
        row["追扣原因"] = _str_or_empty(record.get("deduction_reason"))
        row["院所說明"] = _str_or_empty(record.get("institution_note"))
        
        rows.append(row)
        
    return rows, warnings
