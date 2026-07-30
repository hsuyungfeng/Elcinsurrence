"""patterns.detect_heading_depth 驗收測試（Plan 02-03 Task 1）。"""

from elc_audit_engine.rule_repository.docx_tree.patterns import detect_heading_depth


def test_detect_heading_depth_section_level():
    assert detect_heading_depth("第七節　手術") == 3


def test_detect_heading_depth_chinese_numeral_list():
    assert detect_heading_depth("一、") == 5


def test_detect_heading_depth_body_text_returns_none():
    assert detect_heading_depth("這是一段普通內文") is None
