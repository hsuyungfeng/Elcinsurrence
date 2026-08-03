"""三方比對器：醫令↔規則↔病歷（Phase 5）。

單一入口：compare_case(case, soap_doc, timeline, ...) -> CaseComparisonResult
——逐檢核項判定（C1）＋三級分類（充分/薄弱/裸奔，D7）＋缺口候選補強
（D8/C2）。LLM 判定/補強可注入替身（D-08），測試零 LLM 依賴。
"""

from .models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    VERDICT_MANUAL,
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    CandidateNarrative,
    CaseComparisonResult,
    CheckItem,
    Judgment,
    OrderJudgment,
)
from .evidence import build_evidence_blocks
from .support import classify_support
from .judger import LLMJudger, create_judger
from .narratives import LLMNarrativeGenerator, create_generator
from .comparator import compare_case

__all__ = [
    "SUPPORT_NONE",
    "SUPPORT_SUFFICIENT",
    "SUPPORT_WEAK",
    "VERDICT_MANUAL",
    "VERDICT_PARTIAL",
    "VERDICT_SUPPORTED",
    "VERDICT_UNSUPPORTED",
    "CandidateNarrative",
    "CaseComparisonResult",
    "CheckItem",
    "Judgment",
    "LLMJudger",
    "LLMNarrativeGenerator",
    "OrderJudgment",
    "build_evidence_blocks",
    "classify_support",
    "compare_case",
    "create_generator",
    "create_judger",
]
