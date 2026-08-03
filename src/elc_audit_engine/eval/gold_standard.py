"""LLM 判定金標準 harness（C6-3：30 組「檢核項×病歷段落」金標準回放）。

- `load_gold_standard(path=None)`：讀取金標準 fixture（預設
  tests/fixtures/llm_gold_standard_30.json），驗證欄位與判定合法。
- `evaluate(judge_fn, cases)`：以注入的判定函式逐筆回放，回傳
  準確率、per-verdict 統計與 mismatch 清單（換模型回歸基準）。

judge_fn 為 `(CheckItem, evidence) -> Judgment`（comparator.judger.JudgeFn）；
測試注入替身（D-08），`scripts/replay_gold_standard.py` 注入真實
LLMJudger（伺服器需在 localhost:8080，health guard）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from elc_audit_engine.comparator.judger import JudgeFn
from elc_audit_engine.comparator.models import CheckItem, VERDICTS, VERDICT_MANUAL

_DEFAULT_FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "tests",
    "fixtures",
    "llm_gold_standard_30.json",
)

# 金標準預期判定只允許三種（待人工是降級結果，不是金標準答案）。
_EXPECTED_VERDICTS = tuple(v for v in VERDICTS if v != VERDICT_MANUAL)


class GoldStandardError(Exception):
    """金標準 fixture 無法讀取／格式不合法（fail-fast，不靜默）。"""


@dataclass(frozen=True)
class GoldCase:
    """單一金標準案例：檢核項（規則要求）＋病歷段落＋預期判定。

    Attributes:
        id: 唯一識別（GS-001…）。
        rule_text: 檢核項規則要求全文。
        evidence: 病歷段落文字（判定依據）。
        expected_verdict: 預期判定（支持/部分支持/無記載）。
        note: 評測備註（為何如此判定）。
    """

    id: str
    rule_text: str
    evidence: str
    expected_verdict: str
    note: str = ""


@dataclass(frozen=True)
class GoldStandardResult:
    """金標準回放結果（準確率＋逐判定統計＋mismatch 清單）。

    Attributes:
        total: 案例總數。
        correct: 判定正確筆數。
        accuracy: 正確率（0.0~1.0）。
        per_verdict: {expected_verdict: {"correct": int, "total": int}}。
        mismatches: 每筆為 (case_id, expected, actual) tuple。
    """

    total: int
    correct: int
    accuracy: float
    per_verdict: dict[str, dict[str, int]]
    mismatches: tuple[tuple[str, str, str], ...]


def load_gold_standard(path: str | os.PathLike[str] | None = None) -> tuple[GoldCase, ...]:
    """讀取並驗證金標準 fixture。

    Args:
        path: fixture 路徑；預設 tests/fixtures/llm_gold_standard_30.json。

    Returns:
        GoldCase tuple（依 fixture 順序）。

    Raises:
        GoldStandardError: 讀檔失敗、id 重複、欄位缺漏、判定非法。
    """
    resolved = os.path.abspath(path) if path else os.path.abspath(_DEFAULT_FIXTURE)
    try:
        with open(resolved, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldStandardError(f"金標準 fixture 無法讀取: {exc}") from exc

    cases: list[GoldCase] = []
    seen: set[str] = set()
    if not isinstance(data, list):
        raise GoldStandardError("金標準 fixture 必須是 JSON 陣列")
    for item in data:
        case_id = str(item.get("id", "")).strip()
        if not case_id:
            raise GoldStandardError("金標準案例缺少 id")
        if case_id in seen:
            raise GoldStandardError(f"金標準案例 id 重複: {case_id}")
        seen.add(case_id)
        rule_text = str(item.get("rule_text", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        expected = str(item.get("expected_verdict", "")).strip()
        if not rule_text:
            raise GoldStandardError(f"{case_id}: 缺少 rule_text")
        if expected not in _EXPECTED_VERDICTS:
            raise GoldStandardError(
                f"{case_id}: expected_verdict 必須是 {_EXPECTED_VERDICTS}，收到 {expected!r}"
            )
        cases.append(
            GoldCase(
                id=case_id,
                rule_text=rule_text,
                evidence=evidence,
                expected_verdict=expected,
                note=str(item.get("note", "")).strip(),
            )
        )
    return tuple(cases)


def evaluate(
    judge_fn: JudgeFn, cases: tuple[GoldCase, ...] | list[GoldCase]
) -> GoldStandardResult:
    """以注入的判定函式回放金標準案例（C6-3 回歸基準）。

    Args:
        judge_fn: `(CheckItem, evidence) -> Judgment`；測試注入替身，
            真實回放由 scripts/replay_gold_standard.py 注入 LLMJudger。
        cases: 金標準案例清單（load_gold_standard 輸出）。

    Returns:
        GoldStandardResult：正確率＋per-verdict 統計＋mismatch 清單。
    """
    total = len(cases)
    correct = 0
    per_verdict: dict[str, dict[str, int]] = {}
    mismatches: list[tuple[str, str, str]] = []

    for case in cases:
        judgment = judge_fn(CheckItem(rule_text=case.rule_text), case.evidence)
        actual = judgment.verdict
        stat = per_verdict.setdefault(case.expected_verdict, {"correct": 0, "total": 0})
        stat["total"] += 1
        if actual == case.expected_verdict:
            correct += 1
            stat["correct"] += 1
        else:
            mismatches.append((case.id, case.expected_verdict, actual))

    accuracy = correct / total if total else 0.0
    return GoldStandardResult(
        total=total,
        correct=correct,
        accuracy=accuracy,
        per_verdict=per_verdict,
        mismatches=tuple(mismatches),
    )
