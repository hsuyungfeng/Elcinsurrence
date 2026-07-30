"""RuleResult dataclass 契約測試（D-07/D-08）。"""

import dataclasses

import pytest

from elc_audit_engine.rule_repository.models import RuleResult, not_found


def test_construct_rule_result_found():
    result = RuleResult(
        code="64140C",
        source="payment",
        name="甲床與手指重建術",
        payment_text="...",
        effective_from=None,
        effective_to=None,
        article_location=None,
        article_full_text=None,
        article_source=None,
        found=True,
    )
    assert result.found is True


def test_not_found_factory():
    result = not_found("XXXX")
    assert result.found is False
    assert result.code == "XXXX"


def test_rule_result_is_frozen():
    result = not_found("XXXX")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.found = True
