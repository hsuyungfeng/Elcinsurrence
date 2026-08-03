"""評測套件（Phase 8）：LLM 判定金標準 30 組回放（C6-3）。

換模型時的回歸基準：`tests/fixtures/llm_gold_standard_30.json` 內 30 組
「檢核項×病歷段落×預期判定」，以 `scripts/replay_gold_standard.py`
對真實 llama.cpp 回放並輸出準確率；測試則注入替身 judge_fn（D-08）
驗證 harness 本身（零 LLM 依賴）。
"""

from .gold_standard import (
    GoldCase,
    GoldStandardError,
    GoldStandardResult,
    evaluate,
    load_gold_standard,
)

__all__ = [
    "GoldCase",
    "GoldStandardError",
    "GoldStandardResult",
    "evaluate",
    "load_gold_standard",
]
