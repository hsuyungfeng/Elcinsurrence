"""醫令支持度三級分類（D-04，純函式，不依賴 LLM）。

- 無「無記載」「部分支持」「待人工」→ 充分（✅）
- 任一「部分支持」→ 薄弱（⚠️，有支持但有缺口）
  （Phase 8 E2E-01 修正：原實作把「部分支持（無無記載）」歸充分，
  使「薄弱」在 compare_case 單檢核項流程下不可達，D7 三級缺一角；
  語意上部分支持＝有記載但不足，正是薄弱）
- 有「無記載」但亦有「支持/部分支持」→ 薄弱（⚠️）
- 全部「無記載」（無任何支持證據）→ 裸奔（❌）
- 任一「待人工」→ manual_review=True（不阻斷，標記供 Phase 6）
"""

from __future__ import annotations

from .models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    Judgment,
    VERDICT_MANUAL,
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
)


def classify_support(judgments: list[Judgment]) -> tuple[str | None, bool]:
    """依檢核項判定清單計算醫令三級分類與人工複核旗標。

    Args:
        judgments: 該醫令各檢核項的判定結果（空清單視為無證據）。

    Returns:
        (support_level, manual_review)：
        - support_level 為 充分/薄弱/裸奔；judgments 為空時回傳 裸奔。
        - manual_review=True 表示任一判定為「待人工」（C5 降級）。
    """
    manual = any(j.verdict == VERDICT_MANUAL for j in judgments)
    supported = sum(
        1 for j in judgments if j.verdict in (VERDICT_SUPPORTED, VERDICT_PARTIAL)
    )
    unsupported = sum(1 for j in judgments if j.verdict == VERDICT_UNSUPPORTED)
    partial = sum(1 for j in judgments if j.verdict == VERDICT_PARTIAL)

    if partial > 0:
        # 部分支持＝有記載但有缺口 → 薄弱（E2E-01 修正）
        level: str | None = SUPPORT_WEAK
    elif unsupported == 0 and supported > 0:
        level = SUPPORT_SUFFICIENT
    elif unsupported > 0 and supported > 0:
        level = SUPPORT_WEAK
    elif unsupported > 0 and supported == 0:
        level = SUPPORT_NONE
    else:
        # 全部待人工，或無任何判定 → 無支持證據
        level = SUPPORT_NONE
    return level, manual
