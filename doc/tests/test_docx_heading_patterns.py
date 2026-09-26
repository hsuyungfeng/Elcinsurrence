"""B-WR-17：全形括號標題、小數／日期不誤判為標題。"""
import pytest

from elc_audit_engine.rule_repository.docx_tree.patterns import detect_heading_depth


@pytest.mark.parametrize("text, depth", [
    ("（一）總則", 6), ("(一)總則", 6), ("（1）說明", 7), ("(1)說明", 7),
    ("1. 適應症", 6), ("1.5 mg 每日", None), ("113.12.01 修正", None),
])
def test_heading_depth(text, depth):
    assert detect_heading_depth(text) == depth
