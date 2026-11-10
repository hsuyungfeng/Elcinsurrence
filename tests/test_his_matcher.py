from __future__ import annotations

import pytest
from elc_audit_engine.agent_desktop_bridge import (
    AgentDesktopRunner,
    HISPushAutomator,
    UIElementRef,
)


def _make_automator_with_profile(fields: dict) -> HISPushAutomator:
    profiles = {
        "test_vendor": {
            "exe_names": ["TestHIS.exe"],
            "calibrated": True,
            "fields": fields,
        }
    }
    return HISPushAutomator(runner=AgentDesktopRunner(), profiles=profiles)


def test_matcher_short_token_s_does_not_match_soap_draft():
    """Test 1: target name 'S'，元素 name 'SOAP 草稿' 不命中"""
    automator = _make_automator_with_profile({
        "soap_s": {"automation_id": "", "name": "S", "role": "Edit"},
    })
    elements = [
        UIElementRef(ref_id="@1", role="Edit", automation_id="", name="SOAP 草稿"),
    ]
    matched = automator.match_fields_to_refs("test_vendor", elements)
    assert "soap_s" not in matched


def test_matcher_short_token_s_does_not_match_status():
    """Test 2: target name 'S'，元素 name 'Status' 不命中"""
    automator = _make_automator_with_profile({
        "soap_s": {"automation_id": "", "name": "S", "role": "Edit"},
    })
    elements = [
        UIElementRef(ref_id="@1", role="Edit", automation_id="", name="Status"),
    ]
    matched = automator.match_fields_to_refs("test_vendor", elements)
    assert "soap_s" not in matched


def test_matcher_automation_id_priority_over_name():
    """Test 3: automation_id 精確相等優先於 name 命中（即使 name 命中的元素在前）"""
    automator = _make_automator_with_profile({
        "soap_s": {"automation_id": "txtSubjective", "name": "S", "role": "Edit"},
    })
    # Element @1 matches name "S", element @2 matches automation_id "txtSubjective"
    elements = [
        UIElementRef(ref_id="@1", role="Edit", automation_id="otherId", name="S"),
        UIElementRef(ref_id="@2", role="Edit", automation_id="txtSubjective", name="DifferentName"),
    ]
    matched = automator.match_fields_to_refs("test_vendor", elements)
    assert "soap_s" in matched
    assert matched["soap_s"].ref_id == "@2"


def test_matcher_name_exact_match_casefold():
    """Test 4: automation_id 皆空時，name 必須完全相等（casefold 後）才命中"""
    automator = _make_automator_with_profile({
        "soap_s": {"automation_id": "", "name": "Subjective", "role": "Edit"},
    })
    elements = [
        UIElementRef(ref_id="@1", role="Edit", automation_id="", name="subjective"),
    ]
    matched = automator.match_fields_to_refs("test_vendor", elements)
    assert "soap_s" in matched
    assert matched["soap_s"].ref_id == "@1"


def test_matcher_ambiguous_name_candidates_returns_unmatched():
    """Test 5: 多個候選僅靠 name 且無 automation_id 時視為不明確，回傳未命中（進入 copy card）"""
    automator = _make_automator_with_profile({
        "soap_s": {"automation_id": "", "name": "Note", "role": "Edit"},
    })
    elements = [
        UIElementRef(ref_id="@1", role="Edit", automation_id="", name="Note"),
        UIElementRef(ref_id="@2", role="Edit", automation_id="", name="note"),
    ]
    matched = automator.match_fields_to_refs("test_vendor", elements)
    assert "soap_s" not in matched
