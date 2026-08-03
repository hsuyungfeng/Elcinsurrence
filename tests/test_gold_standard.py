"""LLM 判定金標準 30 組測試（08-01-PLAN Task 1，C6-3）。

涵蓋：fixture 完整性（恰 30 筆、id 唯一、判定合法、分佈 12/9/9）、
load_gold_standard 驗證（缺 id/壞檔/非法判定）、evaluate harness
（替身 judge_fn：全對→accuracy=1.0、部分錯→準確率與 mismatches 正確、
per-verdict 統計）、回放 CLI 具 health guard（importable、伺服器未啟動
exit 1）。零 LLM 依賴（D-08 注入替身）。
"""

import json
import os

import pytest

from elc_audit_engine.comparator.models import (
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    Judgment,
)
from elc_audit_engine.eval import (
    GoldStandardError,
    evaluate,
    load_gold_standard,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "llm_gold_standard_30.json"
)


def _judge_returning(verdict):
    return lambda item, ev: Judgment(verdict=verdict, quote="", reason="")


def _perfect_judge(cases):
    """依金標準 fixture 精確比對的完美替身（驗證 harness 統計本身）。"""
    lookup = {(c.rule_text, c.evidence): c.expected_verdict for c in cases}
    def judge(item, evidence):
        return Judgment(verdict=lookup[(item.rule_text, evidence)], quote="", reason="")
    return judge


# ── fixture 完整性 ────────────────────────────────────────────


def test_fixture_has_exactly_30_cases():
    cases = load_gold_standard(FIXTURE)
    assert len(cases) == 30


def test_fixture_ids_unique_and_ordered():
    cases = load_gold_standard(FIXTURE)
    ids = [c.id for c in cases]
    assert len(set(ids)) == 30
    assert ids == sorted(ids)


def test_fixture_verdict_distribution_12_9_9():
    cases = load_gold_standard(FIXTURE)
    counts = {"支持": 0, "部分支持": 0, "無記載": 0}
    for c in cases:
        counts[c.expected_verdict] += 1
    assert counts == {"支持": 12, "部分支持": 9, "無記載": 9}


def test_fixture_cases_have_rule_and_evidence():
    cases = load_gold_standard(FIXTURE)
    assert all(c.rule_text.strip() for c in cases)
    assert all(isinstance(c.evidence, str) for c in cases)
    assert all(c.note.strip() for c in cases)


# ── load_gold_standard 驗證 ───────────────────────────────────


def test_load_invalid_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(GoldStandardError):
        load_gold_standard(str(bad))


def test_load_duplicate_id_raises(tmp_path):
    bad = tmp_path / "dup.json"
    bad.write_text(
        json.dumps(
            [
                {"id": "GS-001", "rule_text": "r", "evidence": "e", "expected_verdict": "支持"},
                {"id": "GS-001", "rule_text": "r", "evidence": "e", "expected_verdict": "支持"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(GoldStandardError, match="重複"):
        load_gold_standard(str(bad))


def test_load_invalid_verdict_raises(tmp_path):
    bad = tmp_path / "badv.json"
    bad.write_text(
        json.dumps(
            [{"id": "GS-001", "rule_text": "r", "evidence": "e", "expected_verdict": "待人工"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(GoldStandardError, match="expected_verdict"):
        load_gold_standard(str(bad))


# ── evaluate harness（替身 judge_fn）──────────────────────────


def test_evaluate_all_correct_accuracy_1():
    cases = load_gold_standard(FIXTURE)
    result = evaluate(_perfect_judge(load_gold_standard(FIXTURE)), cases)
    assert result.total == 30
    assert result.correct == 30
    assert result.accuracy == 1.0
    assert result.mismatches == ()
    assert sum(s["total"] for s in result.per_verdict.values()) == 30


def test_evaluate_misjudge_reports_accuracy_and_mismatches():
    cases = load_gold_standard(FIXTURE)
    # 全部判支持 → 只對 支持 12 筆
    result = evaluate(_judge_returning(VERDICT_SUPPORTED), cases)
    assert result.correct == 12
    assert result.accuracy == pytest.approx(12 / 30)
    assert len(result.mismatches) == 18
    assert result.per_verdict["部分支持"]["correct"] == 0
    assert result.per_verdict["無記載"]["total"] == 9
    sample = result.mismatches[0]
    assert len(sample) == 3  # (case_id, expected, actual)


def test_evaluate_per_verdict_stats():
    cases = load_gold_standard(FIXTURE)
    result = evaluate(_perfect_judge(load_gold_standard(FIXTURE)), cases)
    assert result.per_verdict["支持"]["correct"] == 12
    assert result.per_verdict["支持"]["total"] == 12
    assert result.per_verdict["部分支持"]["correct"] == 9
    assert result.per_verdict["無記載"]["correct"] == 9


def test_evaluate_empty_cases():
    result = evaluate(_judge_returning(VERDICT_SUPPORTED), ())
    assert result.total == 0
    assert result.accuracy == 0.0


def test_evaluate_judge_receives_check_item():
    seen = {}

    def judge(item, evidence):
        seen["rule_text"] = item.rule_text
        seen["evidence"] = evidence
        return Judgment(VERDICT_SUPPORTED, "")

    cases = load_gold_standard(FIXTURE)
    evaluate(judge, cases[:1])
    assert seen["rule_text"] == cases[0].rule_text
    assert seen["evidence"] == cases[0].evidence


# ── 回放 CLI（health guard）───────────────────────────────────


def test_replay_cli_importable():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "replay_gold_standard", "scripts/replay_gold_standard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)


def test_replay_cli_exits_1_when_server_down(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "replay_gold_standard", "scripts/replay_gold_standard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_server_is_up", lambda: False)
    assert mod.main([]) == 1
