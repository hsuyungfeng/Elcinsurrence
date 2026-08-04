"""攝入（ingest）套件：抽樣／核減清單的 CSV、PDF、影像匯入管道。

- media.py    型別偵測＋PDF 文字提取＋掃描 PDF／JPEG OCR（系統工具，D2 不出本機）
- sampling.py 抽樣清單 CSV 解析（自訂欄位契約，2026-08-04 使用者裁示）
- ocr_rows.py OCR 文字 → 抽樣案件行解析（紙本入口）
"""

from .media import (
    MediaExtractError,
    detect_media_type,
    extract_pdf_text,
    extract_text,
    ocr_image,
    render_pdf_pages,
)
from .ocr_rows import parse_sampling_ocr_text
from .sampling import (
    SamplingCaseRecord,
    SamplingImportError,
    SamplingImportResult,
    SamplingRejectedRow,
    parse_sampling_csv,
    parse_sampling_csv_path,
)

__all__ = [
    "MediaExtractError",
    "SamplingCaseRecord",
    "SamplingImportError",
    "SamplingImportResult",
    "SamplingRejectedRow",
    "detect_media_type",
    "extract_pdf_text",
    "extract_text",
    "ocr_image",
    "parse_sampling_csv",
    "parse_sampling_csv_path",
    "parse_sampling_ocr_text",
    "render_pdf_pages",
]
