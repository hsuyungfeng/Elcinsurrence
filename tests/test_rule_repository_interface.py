"""get_rule() 單一查詢介面契約測試（D-07/D-08，REQ-rule-repository）。

Wave 0 預期紅燈：`get_rule` 尚未實作（Plan 05 落地），
本檔案應以 ImportError/ModuleNotFoundError 收集失敗，而非語法錯誤。
"""

from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.models import RuleResult


def test_get_rule_known_code_returns_found_result():
    result = get_rule("64140C")
    assert result.found is True


def test_get_rule_unknown_code_returns_not_found_not_exception():
    result = get_rule("ZZZZZZ99")
    assert result.found is False


def test_get_rule_return_type_is_ruleresult():
    result = get_rule("64140C")
    assert isinstance(result, RuleResult)
