"""解析器：申報XML/核減清單/SOAP文字（Phase 3 實作）。

純資料轉換層：無 LLM 呼叫、無外部服務依賴、無使用者可見輸出；不查規則庫、
不判斷醫令是否存在（03-CONTEXT.md domain，Phase 5 職責）。

三個解析器的單一入口：
- parse_submission_xml(path) -> SubmissionParseResult
- parse_deduction_file(path, ...) -> DeductionParseResult
- parse_soap_text(text) -> SOAPDocument
"""

from .models import (
    DeductionParseResult,
    DeductionRecord,
    OrderRecord,
    RejectedCase,
    RejectedRow,
    SOAPDocument,
    SOAPSegment,
    SubmissionCase,
    SubmissionParseResult,
)
from .submission_xml import (
    SubmissionXmlError,
    parse_submission_xml,
    parse_submission_xml_bytes,
    parse_submission_xml_text,
)
from .deduction import (
    COLUMN_NAMES,
    DeductionFileError,
    parse_deduction_file,
)
from .soap import parse_soap_text

__all__ = [
    "DeductionFileError",
    "DeductionParseResult",
    "DeductionRecord",
    "OrderRecord",
    "RejectedCase",
    "RejectedRow",
    "SOAPDocument",
    "SOAPSegment",
    "SubmissionCase",
    "SubmissionParseResult",
    "SubmissionXmlError",
    "COLUMN_NAMES",
    "parse_deduction_file",
    "parse_soap_text",
    "parse_submission_xml",
    "parse_submission_xml_bytes",
    "parse_submission_xml_text",
]
