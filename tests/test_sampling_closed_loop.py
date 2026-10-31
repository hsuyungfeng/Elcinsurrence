"""Plan 18-03：抽樣事前預審自動化閉環（SOAP 降級、流程、寫回與冪等）。"""

from __future__ import annotations

import os

import pytest

from config import settings
from elc_audit_engine import sampling_closed_loop as loop

KEY_PAYLOAD = {
    "order_code": "62022C",
    "order_name": "高價處置測試",
    "record_no": "A123456789",
    "visit_date": "2026-07-15",
    "clinic": "01",
    "soap": "S: 主訴胸悶\nO: 血壓 150/90\nA: 高血壓\nP: 追蹤",
    "lab_results": [{"name": "HbA1c", "value": "8.5", "unit": "%"}],
    "cloud_records": "外院紀錄：曾診斷高血壓。",
}


@pytest.fixture
def store(make_api_app):
    return make_api_app().extensions["elc"].case_store


def _create(store, case_id: str, payload: dict, kind: str = "sampling"):
    store.create(case_id=case_id, kind=kind, payload=dict(payload), actor="test")


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


# ── SOAP 降級 ────────────────────────────────────────────────


def test_fallback_soap_prefers_case_text(store):
    soap, source = loop.fallback_soap(store, KEY_PAYLOAD)
    assert source == "case"
    assert soap["s"] == "主訴胸悶"


def test_fallback_soap_keeps_unmarked_case_text_as_raw(store):
    soap, source = loop.fallback_soap(store, {"order_code": "62022C", "soap": "無標記原文"})
    assert source == "case"
    assert soap == {"raw": "無標記原文"}


def test_fallback_soap_uses_general_template_when_case_soap_missing(store):
    store.put_soap_template(
        "62022C", "", {"s": "範本S", "o": "範本O", "a": "範本A", "p": "範本P"},
        source="llm_validated", quality_score=90,
    )
    soap, source = loop.fallback_soap(store, {"order_code": "62022C", "soap": ""})
    assert source == "template_general"
    assert soap["p"] == "範本P"


def test_fallback_soap_prefers_specific_template(store):
    store.put_soap_template(
        "62022C", "I10", {"s": "專屬S", "o": "", "a": "", "p": ""},
        source="llm_validated", quality_score=90,
    )
    soap, source = loop.fallback_soap(store, {"order_code": "62022C", "primary_diagnosis": "I10"})
    assert source == "template_specific"
    assert soap["s"] == "專屬S"


def test_fallback_soap_returns_none_when_nothing_available(store):
    soap, source = loop.fallback_soap(store, {"order_code": "99999X", "primary_diagnosis": ""})
    assert soap is None
    assert source == "none"


def test_fallback_soap_without_order_code_returns_none(store):
    assert loop.fallback_soap(store, {}) == (None, "none")


# ── 閉環流程 ─────────────────────────────────────────────────


def test_run_closed_loop_rejects_non_sampling_case(store):
    _create(store, "MON-1", KEY_PAYLOAD, kind="monthly")
    with pytest.raises(ValueError):
        loop.run_closed_loop(store, "MON-1", provider=None)


def test_run_closed_loop_without_records_never_reports_sufficient(store):
    """病歷來源未設定 → records_degraded=True，任何情況下都不得標示為充分。"""
    _create(store, "SAMP-loop-1", KEY_PAYLOAD)
    result = loop.run_closed_loop(store, "SAMP-loop-1", provider=None)
    assert result.records_degraded is True
    assert result.records_source == "unconfigured"
    assert result.support_state != loop.SUPPORT_SUFFICIENT
    assert result.warnings


def test_run_closed_loop_writes_review_back_to_payload(store):
    _create(store, "SAMP-loop-2", KEY_PAYLOAD)
    result = loop.run_closed_loop(store, "SAMP-loop-2", provider=None)
    saved = store.get("SAMP-loop-2").payload["review"]
    assert saved["support_state"] == result.support_state
    assert saved["records_source"] == "unconfigured"


def test_run_closed_loop_without_write_back_leaves_payload_untouched(store):
    _create(store, "SAMP-loop-3", KEY_PAYLOAD)
    loop.run_closed_loop(store, "SAMP-loop-3", provider=None, write_back=False)
    assert "review" not in store.get("SAMP-loop-3").payload


def test_run_closed_loop_is_idempotent(store):
    _create(store, "SAMP-loop-4", KEY_PAYLOAD)
    first = loop.run_closed_loop(store, "SAMP-loop-4", provider=None)
    second = loop.run_closed_loop(store, "SAMP-loop-4", provider=None)
    assert first == second


def test_run_closed_loop_counts_labs_and_cloud_records(store):
    _create(store, "SAMP-loop-5", KEY_PAYLOAD)
    result = loop.run_closed_loop(store, "SAMP-loop-5", provider=None)
    assert result.lab_count == 1
    assert result.cloud_attached is True


def test_run_closed_loop_marks_template_soap_source(store):
    store.put_soap_template(
        "62022C", "", {"s": "範本S", "o": "", "a": "", "p": ""},
        source="llm_validated", quality_score=90,
    )
    _create(store, "SAMP-loop-6", {**KEY_PAYLOAD, "soap": ""})
    result = loop.run_closed_loop(store, "SAMP-loop-6", provider=None)
    assert result.soap_source == "template_general"
    assert any("範本" in w for w in result.warnings)


def test_run_closed_loop_counts_vault_files(store, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    vault_dir = os.path.join(str(tmp_path), "evidence_vault", "A123456789-2607", "images")
    os.makedirs(vault_dir)
    with open(os.path.join(vault_dir, "scan.jpg"), "wb") as handle:
        handle.write(b"x")
    _create(store, "SAMP-loop-7", KEY_PAYLOAD)
    result = loop.run_closed_loop(store, "SAMP-loop-7", provider=None)
    assert result.vault_key == "A123456789-2607"
    assert result.vault_file_count == 1
