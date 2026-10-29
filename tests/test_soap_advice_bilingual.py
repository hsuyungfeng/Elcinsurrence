"""雙語 SOAP 建議：系統提示詞規範（recommended_soap 英文、審批與比對繁中），
以及解析、退化與失敗分支。LLM 以假函式取代。
"""

from __future__ import annotations

import pytest

from elc_audit_engine.comparator import soap_advice
from elc_audit_engine.comparator.soap_advice import _SYSTEM_PROMPT, generate_soap_advice


def test_prompt_requires_english_recommended_soap():
    assert "recommended_soap" in _SYSTEM_PROMPT
    assert "Medical English" in _SYSTEM_PROMPT
    assert "MUST be written in" in _SYSTEM_PROMPT


def test_prompt_requires_traditional_chinese_for_comparison_and_approval():
    constraint = [line for line in _SYSTEM_PROMPT.splitlines() if "comparison" in line and "approval_advice" in line]
    assert constraint, "缺少 comparison／approval_advice 語言規範"
    assert "繁體中文" in constraint[0]


def test_each_soap_field_is_specified_in_english():
    for field in ("s", "o", "a", "p"):
        assert f'"{field}": "' in _SYSTEM_PROMPT
    assert "Subjective" in _SYSTEM_PROMPT and "Objective" in _SYSTEM_PROMPT
    assert "Assessment" in _SYSTEM_PROMPT and "Plan" in _SYSTEM_PROMPT


def test_prompt_forbids_extra_text_outside_json():
    assert "Output ONLY a single valid JSON object" in _SYSTEM_PROMPT


def _model_reply(monkeypatch, reply):
    captured = {}

    def _fake(system, user, max_tokens=None, temperature=None):
        captured["system"] = system
        captured["user"] = user
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(soap_advice, "chat_completion", _fake)
    return captured


def test_generate_sends_the_bilingual_system_prompt(monkeypatch):
    captured = _model_reply(monkeypatch, '{"comparison": "中文", "recommended_soap": {"s": "x"}, "approval_advice": "中文"}')
    generate_soap_advice("14050B", "HbA1c", "S: DM", "", "")
    assert captured["system"] == _SYSTEM_PROMPT


def test_structured_reply_is_parsed_with_english_soap_and_chinese_advice(monkeypatch):
    reply = (
        '{"comparison": "雲端間隔正常。", '
        '"recommended_soap": {"s": "Routine DM follow-up.", "o": "BP 130/80.", '
        '"a": "E11.9", "p": "HbA1c."}, '
        '"approval_advice": "建議核可。"}'
    )
    _model_reply(monkeypatch, reply)
    result = generate_soap_advice("14050B", "HbA1c", "S: DM", "", "")
    assert result["status"] == "success"
    assert result["recommended_soap"]["s"] == "Routine DM follow-up."
    assert result["approval_advice"] == "建議核可。"


def test_json_wrapped_in_extra_text_is_still_parsed(monkeypatch):
    _model_reply(monkeypatch, 'Here you go: {"comparison": "c", "recommended_soap": {"p": "x"}, "approval_advice": "a"} thanks')
    assert generate_soap_advice("X", "x", "")["status"] == "success"


def test_unstructured_reply_is_fallback_not_success(monkeypatch):
    _model_reply(monkeypatch, "只是一段純文字，沒有 JSON。")
    result = generate_soap_advice("X", "x", "")
    assert result["status"] == "fallback"
    assert result["recommended_soap"]["s"] == ""


def test_llm_exception_is_error_status_not_a_conclusion(monkeypatch):
    _model_reply(monkeypatch, TimeoutError("llm timeout"))
    result = generate_soap_advice("X", "x", "")
    assert result["status"] == "error"
    assert "請人工查核" in result["approval_advice"]


@pytest.mark.parametrize("reply", ["", "[]", "null"])
def test_empty_or_non_object_reply_falls_back(monkeypatch, reply):
    _model_reply(monkeypatch, reply)
    assert generate_soap_advice("X", "x", "")["status"] == "fallback"
