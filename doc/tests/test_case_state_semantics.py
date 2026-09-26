"""A-CR-09：狀態機語意——判定失敗不得記成已預審、驗證失敗不得 appealed、多步轉換原子。"""
from types import SimpleNamespace

import pytest

import server
from elc_audit_engine.case_store import CaseStore, IllegalTransitionError


def _fake_result(support_level, rule_found=True):
    oj = SimpleNamespace(
        support_level=support_level, rule_found=rule_found, narratives=(),
        judgment=None, check_item=None,
    )
    return SimpleNamespace(comparison=SimpleNamespace(order_judgments=(oj,), records_degraded=True))


@pytest.fixture
def sampling_case(client):
    server._case_store.create(case_id="SAMP-1", kind="sampling", payload={"id": "SAMP-1"})
    return "SAMP-1"


def _audit(client, case_id):
    return client.post("/api/sampling/audit", json={"case_id": case_id, "order_code": "14050B"})


def test_llm_failure_moves_case_to_failed_not_reviewed(client, sampling_case, monkeypatch):
    monkeypatch.setattr(server, "run_presubmission_check", lambda *a, **k: _fake_result(None))
    resp = _audit(client, sampling_case)
    assert resp.status_code == 200
    assert resp.get_json()["state_transition"] == "failed"
    rec = server._case_store.get(sampling_case)
    assert rec.state == "failed"
    assert "判定服務異常" in rec.failure_reason


def test_retry_after_failure_reaches_reviewed(client, sampling_case, monkeypatch):
    monkeypatch.setattr(server, "run_presubmission_check", lambda *a, **k: _fake_result(None))
    _audit(client, sampling_case)
    monkeypatch.setattr(server, "run_presubmission_check", lambda *a, **k: _fake_result("充分"))
    assert _audit(client, sampling_case).get_json()["state_transition"] == "ok"
    assert server._case_store.get(sampling_case).state == "reviewed"


def test_reaudit_of_reviewed_case_is_skipped(client, sampling_case, monkeypatch):
    monkeypatch.setattr(server, "run_presubmission_check", lambda *a, **k: _fake_result("充分"))
    _audit(client, sampling_case)
    assert _audit(client, sampling_case).get_json()["state_transition"] == "skipped"


def test_no_judgments_does_not_touch_state(client, sampling_case, monkeypatch):
    empty = SimpleNamespace(comparison=SimpleNamespace(order_judgments=(), records_degraded=True))
    monkeypatch.setattr(server, "run_presubmission_check", lambda *a, **k: empty)
    assert _audit(client, sampling_case).status_code == 400
    assert server._case_store.get(sampling_case).state == "imported"


def test_appeal_case_rejected_by_sampling_audit(client):
    server._case_store.create(case_id="APP-1", kind="appeal", payload={"id": "APP-1"})
    assert _audit(client, "APP-1").status_code == 409


def test_appeal_with_validation_errors_is_not_appealed(client):
    server._case_store.create(case_id="APP-2", kind="appeal", case_seq="9", payload={"id": "APP-2"})
    body = {"case_id": "APP-2", "case_seq": "9", "order_code": "64140C", "deduct_amount": 100}
    data = client.post("/api/appeal/generate", json=body).get_json()
    assert data["validation_errors"]
    assert data["state_transition"] == "skipped"
    assert server._case_store.get("APP-2").state == "imported"


def test_advance_is_atomic(tmp_path):
    store = CaseStore(db_path=str(tmp_path / "c.sqlite3"))
    store.create(case_id="X", kind="sampling")
    with pytest.raises(IllegalTransitionError):
        store.advance("X", ["parsed", "reviewed"])  # 第二步非法
    assert store.get("X").state == "imported"
    assert len(store.history("X")) == 1
