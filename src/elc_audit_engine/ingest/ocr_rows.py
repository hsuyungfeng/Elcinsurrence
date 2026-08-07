"""OCR 文字 → 抽樣案件記錄的行解析（紙本掃描 JPEG／掃描 PDF 入口）。

健保醫令代碼為「5 位數字＋1 位英文字」（如 14050B、64140C），是 OCR 文字
中最可靠的錨點：逐行掃描，命中代碼即建一筆記錄（該行其餘文字視為醫令
名稱），其餘欄位留空供前端人工補齊。

**誠實降級**：OCR 無法保證欄位級精度，故：
- 每筆記錄標 `source="ocr"`＋保留原始辨識行（ocr_line）供人工核對；
- 不猜測病歷號／日期等欄位（猜錯比留空更危險）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .sampling import (
    SamplingCaseRecord,
    SamplingImportResult,
    SamplingRejectedRow,
)

# 醫令代碼：健保標準 6 碼（5位數字+1位英文字，如 14050B/64140C/01015C），或 5-6 位英數代碼。
ORDER_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{5,6})(?![A-Za-z0-9])")

# 單筆醫令名稱的字數上限（OCR 行其餘文字可能夾帶表頭/頁碼雜訊）。
_MAX_ORDER_NAME_CHARS = 60


def parse_sampling_ocr_text(text: str) -> SamplingImportResult:
    """把 OCR 純文字逐行解析成抽樣案件記錄。

    Returns:
        SamplingImportResult（source="ocr"）；找不到任何醫令代碼時 records 為空。
    """
    records: list[SamplingCaseRecord] = []
    rejected: list[SamplingRejectedRow] = []
    seen: set[str] = set()

    for idx, line in enumerate(text.splitlines(), start=1):
        # 尋找所有 5-6 碼候選
        candidates = ORDER_CODE_RE.findall(line)
        if not candidates:
            continue
        # 優先挑選符合 5數字+1英文字 之標準健保碼
        order_code = None
        for cand in candidates:
            c_upper = cand.upper()
            if len(c_upper) == 6 and c_upper[:5].isdigit() and c_upper[5].isalpha():
                order_code = c_upper
                break
        if not order_code:
            order_code = candidates[0].upper()
        # 同名代碼重複行（表頭範例／分頁重複）只取第一筆，其餘列 rejected。
        if order_code in seen:
            rejected.append(
                SamplingRejectedRow(
                    row_number=idx,
                    reason="重複的醫令代碼（OCR 重複行，已略過）",
                    raw=(line,),
                )
            )
            continue
        seen.add(order_code)
        idx_pos = line.find(order_code)
        rest = line[idx_pos + len(order_code) :].strip() if idx_pos != -1 else line[match.end() :].strip()
        # 清除行尾雜訊（日期/金額數字群），保留中英文名稱。
        name = re.sub(r"\s{2,}.*$", "", rest)[:_MAX_ORDER_NAME_CHARS].strip()
        records.append(
            SamplingCaseRecord(
                order_code=order_code,
                order_name=name or None,
                source="ocr",
                ocr_line=line.strip(),
                raw=(line.strip(),),
            )
        )

    return SamplingImportResult(
        records=tuple(records),
        rejected=tuple(rejected),
        source="ocr",
    )
