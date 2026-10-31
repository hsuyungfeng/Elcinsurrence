"""Plan 18-03 測試骨架：抽樣事前預審自動化閉環。

- 已實作的硬性規則（None → 待判定、未知級別拒絕）為一般測試。
- 尚未實作的流程為 strict xfail（raises=NotImplementedError）：實作完成後會變成
  XPASS 並使測試失敗，屆時移除 xfail 標記即可。
"""

from __future__ import annotations

import pytest

from elc_audit_engine import sampling_closed_loop as loop

pending_impl = pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="Plan 18-03 尚未實作",
)


# ── 已實作：硬性規則 ─────────────────────────────────────────


def test_none_judgment_maps_to_pending_not_unsupported():
    """P1-1：判定服務異常不得落為裸奔。"""
    assert loop.resolve_support_state(None, records_degraded=False) == loop.PENDING
    assert loop.resolve_support_state(None, records_degraded=True) == loop.PENDING


def test_unknown_support_level_is_rejected():
    with pytest.raises(ValueError):
        loop.resolve_support_state("亂碼", records_degraded=False)


def test_support_states_contains_four_display_states():
    assert set(loop.SUPPORT_STATES) == {"待判定", "充分", "薄弱", "裸奔"}


def test_soap_source_vocabulary_is_fixed():
    assert loop.SOAP_SOURCES == ("case", "template_specific", "template_general", "none")


def test_degraded_records_downgrade_sufficient_to_weak():
    """病歷缺席且判定為充分 → 降為薄弱，提醒醫師補強病史佐證。"""
    assert loop.resolve_support_state("充分", records_degraded=True) == loop.SUPPORT_WEAK


def test_non_degraded_sufficient_stays_sufficient():
    assert loop.resolve_support_state("充分", records_degraded=False) == loop.SUPPORT_SUFFICIENT


@pytest.mark.parametrize("level", ["薄弱", "裸奔"])
def test_degraded_does_not_change_weak_or_none(level):
    assert loop.resolve_support_state(level, records_degraded=True) == level


def test_degraded_pending_stays_pending():
    assert loop.resolve_support_state(None, records_degraded=True) == loop.PENDING


def test_warnings_empty_when_records_present():
    assert loop.presubmission_warnings("充分", records_degraded=False) == ()


def test_warnings_flag_missing_records():
    warnings = loop.presubmission_warnings("薄弱", records_degraded=True)
    assert len(warnings) == 1
    assert "病歷缺席" in warnings[0]


def test_warnings_explain_downgrade_from_sufficient():
    warnings = loop.presubmission_warnings("充分", records_degraded=True)
    assert len(warnings) == 2
    assert "降為「薄弱」" in warnings[1]


# ── 待實作：流程契約（strict xfail） ──────────────────────────


@pending_impl
def test_missing_soap_falls_back_to_template(make_api_app):
    """SOAP 缺漏時改用 soap_templates 範本，soap_source 需標示來源。"""
    app = make_api_app()
    store = app.extensions["elc"].case_store
    loop.fallback_soap(store, {"order_code": "62022C", "primary_diagnosis": "I10"})


@pending_impl
def test_missing_soap_and_template_returns_none_without_raising(make_api_app):
    """範本亦查無時回 (None, "none")，不得拋出例外。"""
    app = make_api_app()
    store = app.extensions["elc"].case_store
    soap, source = loop.fallback_soap(store, {"order_code": "99999X", "primary_diagnosis": ""})
    assert soap is None
    assert source == "none"


@pending_impl
def test_run_closed_loop_attaches_vault_labs_and_cloud(make_api_app):
    """點選案件時自動掛載佐證庫、檢驗數據與雲端病歷。"""
    app = make_api_app()
    store = app.extensions["elc"].case_store
    result = loop.run_closed_loop(store, "SAMP-closed-loop-1")
    assert result.case_id == "SAMP-closed-loop-1"
    assert result.support_state in loop.SUPPORT_STATES


@pending_impl
def test_run_closed_loop_is_idempotent(make_api_app):
    """同一案件重跑兩次，結果與寫回的 payload 必須一致。"""
    app = make_api_app()
    store = app.extensions["elc"].case_store
    first = loop.run_closed_loop(store, "SAMP-closed-loop-1")
    second = loop.run_closed_loop(store, "SAMP-closed-loop-1")
    assert first == second


@pending_impl
def test_run_closed_loop_degrades_when_patient_records_missing(make_api_app):
    """病歷目錄缺席時 records_degraded=True 並附警示，而非服務 500（P0-2／C5）。"""
    app = make_api_app()
    store = app.extensions["elc"].case_store
    result = loop.run_closed_loop(store, "SAMP-closed-loop-1", records_provider=None)
    assert result.records_degraded is True
    assert result.warnings
