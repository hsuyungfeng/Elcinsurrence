"""測試 generate_clinical_soap_from_transcript 定向單次重試與空摘要補齊（Phase 35 Wave 2）。"""

from __future__ import annotations

import json

from elc_audit_engine.comparator import soap_advice

_SAMPLE_TRANSCRIPT = "醫師：請問今天哪裡不舒服？病人：右肩痛了兩週，舉手會痛，晚上壓到也會痛。"

_SOAP_WITH_PLACEHOLDER = {
    "s": "Patient reports two weeks of right shoulder pain worse with elevation and lying on the affected side.",
    "o": "Tenderness over the right subacromial region with painful arc during active abduction.",
    "a": "Right shoulder impingement syndrome (M75.41); exact tear severity not documented.",
    "p": "Prescribe oral NSAID and physical therapy referral; return in two weeks for reassessment.",
    "conversation_summary": "右肩疼痛兩週伴舉手疼痛，評估為右肩夾擠症候群並開立消炎藥與復健。",
}

_SOAP_CLEAN = {
    "s": "Patient reports two weeks of right shoulder pain worse with elevation and lying on the affected side.",
    "o": "Tenderness over the right subacromial region with painful arc during active abduction.",
    "a": "Right shoulder impingement syndrome (M75.41).",
    "p": "Prescribe oral NSAID and physical therapy referral; return in two weeks for reassessment.",
    "conversation_summary": "右肩疼痛兩週伴舉手疼痛，評估為右肩夾擠症候群並開立消炎藥與復健。",
}


def test_placeholder_triggers_single_retry_with_transcript_and_succeeds(monkeypatch):
    """初次產出含 placeholder 時，執行 1 次定向修正、傳入原始逐字稿，修正合格後採用。"""
    calls: list[dict] = []
    responses = [
        json.dumps(_SOAP_WITH_PLACEHOLDER, ensure_ascii=False),
        json.dumps(_SOAP_CLEAN, ensure_ascii=False),
    ]

    def _fake_chat(system_prompt, user_prompt, **kwargs):
        calls.append({"system": system_prompt, "user": user_prompt, "kwargs": kwargs})
        return responses[len(calls) - 1]

    monkeypatch.setattr(soap_advice, "chat_completion", _fake_chat)

    res = soap_advice.generate_clinical_soap_from_transcript(_SAMPLE_TRANSCRIPT)
    assert res["status"] == "success"
    assert res["quality"]["pass"] is True
    assert res["quality"]["quality_score"] == 100
    assert res["retried"] is True
    assert res["summary_backfilled"] is False
    assert len(calls) == 2
    # 阻擋項確認：重試呼叫必須包含原始逐字稿與需修正問題
    assert _SAMPLE_TRANSCRIPT in calls[1]["user"]
    assert "placeholder" in calls[1]["user"]


def test_retry_falls_back_to_original_when_retry_not_better_and_caps_at_one(monkeypatch):
    """重試若未改善或回傳非法 JSON，安全保留原結果且嚴格最多重試 1 次。"""
    calls: list[dict] = []
    responses = [
        json.dumps(_SOAP_WITH_PLACEHOLDER, ensure_ascii=False),
        "NOT VALID JSON AT ALL",
    ]

    def _fake_chat(system_prompt, user_prompt, **kwargs):
        calls.append({"system": system_prompt, "user": user_prompt})
        return responses[len(calls) - 1]

    monkeypatch.setattr(soap_advice, "chat_completion", _fake_chat)

    res = soap_advice.generate_clinical_soap_from_transcript(_SAMPLE_TRANSCRIPT)
    assert res["status"] == "success"
    assert res["quality"]["pass"] is False
    assert res["retried"] is False
    assert len(calls) == 2  # 初次 + 最多 1 次重試


def test_empty_summary_backfills_once_with_transcript(monkeypatch):
    """SOAP 合格但繁中摘要為空時，對照原始逐字稿執行 1 次輕量摘要補齊。"""
    calls: list[dict] = []
    no_summary = dict(_SOAP_CLEAN)
    no_summary["conversation_summary"] = ""
    responses = [
        json.dumps(no_summary, ensure_ascii=False),
        "病人主訴右肩疼痛兩週且舉手加劇，評估為右肩夾擠症候群並安排藥物與復健追蹤。",
    ]

    def _fake_chat(system_prompt, user_prompt, **kwargs):
        calls.append({"system": system_prompt, "user": user_prompt, "kwargs": kwargs})
        return responses[len(calls) - 1]

    monkeypatch.setattr(soap_advice, "chat_completion", _fake_chat)

    res = soap_advice.generate_clinical_soap_from_transcript(_SAMPLE_TRANSCRIPT)
    assert res["status"] == "success"
    assert res["quality"]["pass"] is True
    assert res["retried"] is False
    assert res["summary_backfilled"] is True
    assert "右肩疼痛" in res["conversation_summary"]
    assert len(calls) == 2
    assert _SAMPLE_TRANSCRIPT in calls[1]["user"]
    assert calls[1]["kwargs"].get("max_tokens") == 200


def test_empty_summary_backfill_error_preserves_valid_soap(monkeypatch):
    """空摘要補齊若逾時／拋例外，仍優雅保留已合格的 SOAP 不影響草稿建立。"""
    calls = 0
    no_summary = dict(_SOAP_CLEAN)
    no_summary["conversation_summary"] = ""

    def _fake_chat(system_prompt, user_prompt, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(no_summary, ensure_ascii=False)
        raise TimeoutError("llm busy")

    monkeypatch.setattr(soap_advice, "chat_completion", _fake_chat)

    res = soap_advice.generate_clinical_soap_from_transcript(_SAMPLE_TRANSCRIPT)
    assert res["status"] == "success"
    assert res["quality"]["pass"] is True
    assert res["conversation_summary"] == ""
    assert res["summary_backfilled"] is False
    assert calls == 2


def test_allow_retry_false_disables_retry_and_backfill(monkeypatch):
    """allow_retry=False 時嚴格只呼叫 LLM 1 次。"""
    calls = 0
    bad_no_summary = dict(_SOAP_WITH_PLACEHOLDER)
    bad_no_summary["conversation_summary"] = ""

    def _fake_chat(system_prompt, user_prompt, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(bad_no_summary, ensure_ascii=False)

    monkeypatch.setattr(soap_advice, "chat_completion", _fake_chat)

    res = soap_advice.generate_clinical_soap_from_transcript(_SAMPLE_TRANSCRIPT, allow_retry=False)
    assert res["status"] == "success"
    assert res["retried"] is False
    assert res["summary_backfilled"] is False
    assert calls == 1


def test_clinical_pending_whitelist_and_bypass_matrix():
    """Phase 36：clinical 放行明確臨床檢驗追蹤語境 pending，但嚴格攔截全部 10 組診斷／計畫待定繞過與 template。"""
    base = {k: _SOAP_CLEAN[k] for k in ("s", "o", "a", "p")}

    # 1. clinical 放行合法臨床檢驗追蹤語境
    for allowed_a in (
        "Constipation (K59.0); dysuria (R30.0), urinalysis pending.",
        "Constipation (K59.0); dysuria (R30.0), pending urinalysis and lab review.",
    ):
        cand = dict(base, a=allowed_a)
        q_clin = soap_advice.validate_soap_quality(cand, profile="clinical")
        assert q_clin["pass"] is True, f"clinical 應放行合法檢驗語境：{allowed_a!r} -> {q_clin}"
        # template profile 維持嚴格阻斷 pending
        q_tmpl = soap_advice.validate_soap_quality(cand, profile="template")
        assert q_tmpl["pass"] is False

    # 2. clinical 嚴格攔截 10 組診斷／代碼／計畫／處置待定繞過與裸佔位
    blocked_cases = (
        "Constipation (K59.0); diagnosis pending ultrasound.",
        "Constipation (K59.0); differential pending ultrasound.",
        "Constipation (K59.0); ddx pending urinalysis.",
        "Constipation (K59.0); dx pending ultrasound.",
        "Constipation (K59.0); ICD 10 pending ultrasound.",
        "Constipation (K59.0); ICD pending urinalysis.",
        "Constipation (K59.0); plan pending ultrasound.",
        "Constipation (K59.0); treatment pending urinalysis.",
        "Constipation (K59.0); impression pending lab.",
        "Constipation (K59.0); problem pending ultrasound.",
        "Constipation (K59.0); [pending] further info.",
        "Constipation (K59.0); pending.",
    )
    for bad_a in blocked_cases:
        cand = dict(base, a=bad_a)
        q = soap_advice.validate_soap_quality(cand, profile="clinical")
        assert q["pass"] is False, f"clinical 必須攔截繞過／裸佔位：{bad_a!r}"
        assert any(it["code"] == "placeholder" for it in q["issues"])
