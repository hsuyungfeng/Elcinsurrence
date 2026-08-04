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

# 醫令代碼：5 位數字 + 1 位英文字（前後不可接數字，避免吃到長數字）。
ORDER_CODE_RE = re.compile(r"(?<!\d)(\d{5}[A-Za-z])(?!\d)")

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
        match = ORDER_CODE_RE.search(line)
        if not match:
            continue
        order_code = match.group(1).upper()
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
        rest = line[match.end() :].strip()
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
