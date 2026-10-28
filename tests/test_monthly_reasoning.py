"""Phase 15-03：條件推理樹與 SOAP 補強清單（防幻覺：每一項都必須是規則原文的逐字子字串）。

規則文字為測試內合成字串（代碼 TST／SYN 開頭），不是真實給付規定。
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date

import pytest

from elc_audit_engine.monthly_audit import (
    STATUS_NOT_FOUND,
    STATUS_UNDETERMINED,
    CaseAudit,
    Evidence,
    OrderFinding,
    evaluate_order,
)
from elc_audit_engine.monthly_reasoning import (
    CATEGORY_TITLES,
    attach_reasoning,
    build_order_reasoning,
    build_reasoning_tree,
    build_soap_checklist,
    case_reasoning,
    is_verbatim,
)
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.models import RuleResult

REAL_RULES = os.path.join(os.path.dirname(__file__), "..", "data", "db", "rules.sqlite3")

RULE_TEXT = (
    "本項目限下列適應症使用。需附心電圖檢查報告。每日最多2次。"
    "ICD‑10 S00.1、S00.2 等診斷需附病歷。另有一般說明。"
)


def _rule(code: str, text: str | None = RULE_TEXT, article: str | None = None) -> RuleResult:
    return RuleResult(
        code=code,
        source="payment",
        name="合成測試項目",
        payment_text=text,
        effective_from="2023-01-01",
        effective_to="2910-12-31",
        article_location=None,
        article_full_text=article,
        article_source="csv" if article else None,
        found=True,
    )


def _finding(code: str = "TST1", *, text: str | None = RULE_TEXT, dx: str = "S001XA") -> OrderFinding:
    order = OrderRecord(code=code, category="2", unit_price="1", points="400", seq="3", raw={})
    finding = evaluate_order(
        order,
        case_diagnoses=(dx,),
        visit_date=date(2023, 7, 18),
        lookup=lambda c: _rule(c, text=text),
    )
    assert finding is not None
    return finding


def _all_nodes(node):
    yield node
    for child in node.children:
        yield from _all_nodes(child)


# ── 推理樹結構 ─────────────────────────────────────────────────────


def test_tree_contains_criteria_categories_in_order():
    tree = build_reasoning_tree(_finding(), case_dx="S001XA")
    category_labels = [n.label for n in tree.children if n.kind == "category"]
    expected = [CATEGORY_TITLES[k][0] for k in ("indication", "prerequisite", "diagnosis", "frequency")]
    assert category_labels == expected  # 順序：適應症 → 前置檢查 → 診斷 → 頻次


def test_every_criterion_quote_is_verbatim_in_its_source():
    finding = _finding()
    tree = build_reasoning_tree(finding, case_dx="S001XA")
    quotes = [n for n in _all_nodes(tree) if n.kind == "criterion"]
    assert quotes
    for node in quotes:
        assert node.quote in RULE_TEXT
        assert node.source == "payment_text"


def test_tree_node_ids_are_unique():
    tree = build_reasoning_tree(_finding(), case_dx="S001XA")
    ids = [n.node_id for n in _all_nodes(tree)]
    assert len(ids) == len(set(ids))


def test_diagnosis_fact_is_always_present_when_rule_has_text():
    tree = build_reasoning_tree(_finding(), case_dx="S001XA")
    facts = [n.label for n in tree.children if n.kind == "fact"]
    assert any(label.startswith("診斷比對：") and "S00.1" in label for label in facts)


# ── SOAP 補強 ─────────────────────────────────────────────────────


def test_soap_sections_map_to_criteria_categories():
    checklist, dropped = build_soap_checklist(_finding(), case_dx="S001XA")
    sections = {item.section for item in checklist}
    assert {"S/O", "O / ATT", "P", "A"} <= sections
    assert dropped == 0


def test_every_soap_item_is_verbatim_and_pending_verification():
    checklist, _ = build_soap_checklist(_finding(), case_dx="S001XA")
    assert checklist
    for item in checklist:
        if item.quote is not None:
            assert item.quote in RULE_TEXT
        for code in item.codes:
            assert code in RULE_TEXT
        assert item.verify_status == "待病歷比對"


def test_soap_prompts_never_assert_missing_records():
    checklist, _ = build_soap_checklist(_finding(), case_dx="S001XA")
    for item in checklist:
        assert "缺漏" not in item.prompt
        assert "未附" not in item.prompt
        assert "未記載" not in item.prompt


def test_diagnosis_item_lists_rule_codes_and_case_diagnosis():
    checklist, _ = build_soap_checklist(_finding(), case_dx="S001XA")
    a_items = [i for i in checklist if i.section == "A"]
    assert len(a_items) == 1
    assert a_items[0].codes == ("S00.1", "S00.2")
    assert "S001XA" in a_items[0].prompt
    assert a_items[0].quote is not None and "S00.1" in a_items[0].quote


def test_verbatim_guard_drops_fabricated_evidence_fail_closed():
    finding = _finding()
    fabricated = replace(
        finding,
        evidence=finding.evidence + (Evidence(source="payment_text", sentence="這句話不在規則原文中", kinds=("indication",)),),
    )
    checklist, dropped = build_soap_checklist(fabricated, case_dx="S001XA")
    assert dropped == 1
    assert all(item.quote != "這句話不在規則原文中" for item in checklist)


def test_is_verbatim_checks_named_source_and_any_source():
    finding = _finding()
    assert is_verbatim("需附心電圖檢查報告", "payment_text", finding)
    assert not is_verbatim("需附心電圖檢查報告", "article_full_text", finding)
    assert is_verbatim("每日最多2次", None, finding)
    assert not is_verbatim("每日最多3次", None, finding)


# ── 狀態分支：系統故障與查無規則不得變成條件或結論 ─────────────────────


def test_undetermined_rule_yields_no_criteria_and_no_soap():
    finding = OrderFinding(
        order_seq="1",
        code="TST9",
        category="2",
        points="400",
        unit_price=None,
        flags=("points_over_350",),
        rule_status=STATUS_UNDETERMINED,
        error="rule repository query failed",
    )
    reasoning = build_order_reasoning(finding, case_dx="S001XA")
    assert reasoning.soap_checklist == ()
    labels = [n.label for n in _all_nodes(reasoning.tree)]
    assert any("非判定結果" in label for label in labels)
    assert not any(n.kind == "category" for n in _all_nodes(reasoning.tree))


def test_not_found_rule_yields_no_criteria():
    finding = OrderFinding(
        order_seq="2",
        code="NOPE",
        category="2",
        points="400",
        unit_price=None,
        flags=("points_over_350",),
        rule_status=STATUS_NOT_FOUND,
    )
    reasoning = build_order_reasoning(finding)
    assert reasoning.soap_checklist == ()
    assert any("查無規則" in n.label for n in _all_nodes(reasoning.tree))


def test_rule_text_without_markers_yields_no_guidance():
    finding = _finding(text="一般說明文字。")
    reasoning = build_order_reasoning(finding, case_dx="S001XA")
    assert reasoning.soap_checklist == ()


# ── 案件層與 JSON 合併 ───────────────────────────────────────────


def test_case_reasoning_aligns_with_findings_and_attaches_to_dict():
    finding = _finding()
    case = CaseAudit(
        case_id="MON-t",
        batch="MONTHLY-202307",
        case_seq="1",
        department="03",
        doctor_code="D1",
        visit_date="1120718",
        primary_diagnosis="S001XA",
        secondary_diagnoses=(),
        findings=(finding,),
    )
    reasonings = case_reasoning(case)
    assert len(reasonings) == 1
    assert reasonings[0].code == "TST1"

    base = case.to_dict()
    merged = attach_reasoning(base, case)
    assert "reasoning" in merged["findings"][0]
    assert "reasoning" not in base["findings"][0]  # 不改原 dict


# ── 真實規則庫冒煙（唯讀；檔案不存在則跳過） ───────────────────────


@pytest.mark.skipif(not os.path.exists(REAL_RULES), reason="data/db/rules.sqlite3 不存在")
def test_real_rule_tree_quotes_are_verbatim_in_real_text():
    rule = get_rule("48003C", db_path=REAL_RULES)
    order = OrderRecord(code="48003C", category="2", unit_price="1", points="400", seq="1", raw={})
    finding = evaluate_order(
        order,
        case_diagnoses=("S50812A",),
        visit_date=date(2023, 7, 3),
        lookup=lambda c: get_rule(c, db_path=REAL_RULES),
    )
    assert finding is not None
    checklist, dropped = build_soap_checklist(finding, case_dx="S50812A")
    assert dropped == 0
    assert checklist
    texts = [rule.payment_text or "", rule.article_full_text or ""]
    for item in checklist:
        if item.quote is not None:
            assert any(item.quote in t for t in texts)
