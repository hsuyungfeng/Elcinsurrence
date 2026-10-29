"""HIS 整合 REST API：認證、冪等建檔、雙語建議的故障分離、審批回寫（含 Webhook 成功／失敗）。

LLM 與 Webhook 皆以假物件取代，測試不連網路。
"""

from __future__ import annotations

import urllib.error

import pytest

from elc_audit_engine.api.routes import his_integration
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult, not_found

KEY = {"X-API-Key": "valid-key-123"}

PUSH_BODY = {
    "record_no": "A123456789",
    "patient_name": "測試病患",
    "order_code": "14050B",
    "order_name": "糖化血色素檢驗",
    "visit_date": "1120718",
    "clinic": "03",
    "his_encounter_id": "ENC-1",
    "soap_text": "S: DM follow up\nO: Blood sugar elevated\nA: DM\nP: Check HbA1c",
}

STRUCTURED = {
    "status": "success",
    "comparison": "雲端病歷顯示間隔正常。",
    "recommended_soap": {
        "s": "Patient presents for routine DM follow-up.",
        "o": "BP 130/80 mmHg, random blood glucose 150 mg/dL.",
        "a": "Type 2 diabetes mellitus without complications (E11.9).",
        "p": "Order HbA1c test (14050B) for 3-month glycemic evaluation.",
    },
    "approval_advice": "建議主治醫師核可，符合3個月給付間隔規定。",
}


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture
def fake_advice(monkeypatch):
    """可切換的 LLM 假回應；預設為結構完整的成功結果。"""
    state = {"result": dict(STRUCTURED)}

    def _fake(**kwargs):
        return state["result"]

    monkeypatch.setattr(his_integration, "generate_soap_advice", _fake)
    return state


@pytest.fixture
def fake_rule(monkeypatch):
    state = {"rule": RuleResult(
        code="14050B", source="payment", name="糖化血色素", payment_text="限糖尿病患者使用。",
        effective_from=None, effective_to=None, article_location=None,
        article_full_text=None, article_source=None, found=True,
    )}

    def _fake(code, db_path=None):
        if isinstance(state["rule"], Exception):
            raise state["rule"]
        return state["rule"]

    monkeypatch.setattr(his_integration, "get_rule", _fake)
    return state


# ── 認證 ─────────────────────────────────────────────────────────


def test_all_his_endpoints_require_api_key(client):
    assert client.post("/api/his/v1/cases/push", json=PUSH_BODY).status_code == 401
    assert client.post("/api/his/v1/cases/soap-enhance", json={"order_code": "X"}).status_code == 401
    assert client.post("/api/his/v1/cases/HIS-x/approve-callback", json={"approved_soap": "S"}).status_code == 401


# ── 建檔 ─────────────────────────────────────────────────────────


def test_push_creates_his_case_with_content_hash_id(client, app):
    res = client.post("/api/his/v1/cases/push", headers=KEY, json=PUSH_BODY)
    assert res.status_code == 201
    data = res.get_json()
    assert data["case_id"].startswith("HIS-") and len(data["case_id"]) == 4 + 32
    record = app.extensions["elc"].case_store.get(data["case_id"])
    assert record.kind == "his"  # 不混入抽樣清單
    assert record.payload["record_no"] == "A123456789"


def test_repeated_push_is_idempotent_not_silent_overwrite(client):
    first = client.post("/api/his/v1/cases/push", headers=KEY, json=PUSH_BODY)
    second = client.post("/api/his/v1/cases/push", headers=KEY, json=PUSH_BODY)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"
    assert second.get_json()["case_id"] == first.get_json()["case_id"]


def test_push_accepts_soap_longer_than_default_field_limit(client):
    body = dict(PUSH_BODY, soap_text="S: " + "很長的主訴內容。" * 40)  # 超過一般欄位的 200 字
    assert client.post("/api/his/v1/cases/push", headers=KEY, json=body).status_code == 201


def test_push_rejects_soap_over_limit(client):
    body = dict(PUSH_BODY, soap_text="x" * 10_001)
    assert client.post("/api/his/v1/cases/push", headers=KEY, json=body).status_code == 400


def test_push_requires_record_and_order(client):
    body = {k: v for k, v in PUSH_BODY.items() if k != "record_no"}
    assert client.post("/api/his/v1/cases/push", headers=KEY, json=body).status_code == 400


# ── 雙語建議與故障分離 ─────────────────────────────────────────────


def test_soap_enhance_returns_english_template_and_review_flag(client, fake_advice, fake_rule):
    res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY, json={
        "order_code": "14050B", "order_name": "糖化血色素檢驗", "soap_text": "S: DM\nO: High sugar",
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["example_soap_template"].startswith("S: Patient presents")
    assert "A: Type 2 diabetes" in data["example_soap_template"]
    assert data["review_required"] is True
    assert data["rule_found"] is True
    assert "建議主治醫師核可" in data["bilingual_advice"]["approval_advice"]


def test_llm_failure_is_503_undetermined_with_no_template(client, fake_advice, fake_rule):
    fake_advice["result"] = {"status": "error", "recommended_soap": {}, "comparison": "逾時"}
    res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY, json={"order_code": "14050B"})
    assert res.status_code == 503
    data = res.get_json()
    assert data["status"] == "undetermined"
    assert "example_soap_template" not in data


def test_unstructured_model_output_is_fallback_without_template(client, fake_advice, fake_rule):
    fake_advice["result"] = {"status": "fallback", "recommended_soap": {"p": "raw text"}}
    res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY, json={"order_code": "14050B"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "fallback"
    assert data["example_soap_template"] == ""
    assert data["warning"]


def test_rule_database_failure_is_503_not_silent_empty_rule(client, fake_advice, fake_rule):
    fake_rule["rule"] = RuleRepositoryError("disk I/O error")
    res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY, json={"order_code": "14050B"})
    assert res.status_code == 503
    assert res.get_json()["status"] == "undetermined"


def test_unknown_rule_still_generates_advice_with_rule_found_false(client, fake_advice, fake_rule):
    fake_rule["rule"] = not_found("NOPE")
    res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY, json={"order_code": "NOPE"})
    assert res.status_code == 200
    assert res.get_json()["rule_found"] is False


# ── 審批回寫 ─────────────────────────────────────────────────────


@pytest.fixture
def case_id(client):
    return client.post("/api/his/v1/cases/push", headers=KEY, json=PUSH_BODY).get_json()["case_id"]


APPROVE_BODY = {
    "approved_soap": "S: Routine DM check\nO: Stable\nA: E11.9\nP: HbA1c done",
    "doctor_id": "DR_LIN_01",
    "approval_status": "approved",
}


def test_approve_for_unknown_case_is_404(client):
    res = client.post("/api/his/v1/cases/HIS-missing/approve-callback", headers=KEY, json=APPROVE_BODY)
    assert res.status_code == 404


def test_approve_rejects_unknown_status(client, case_id):
    res = client.post(f"/api/his/v1/cases/{case_id}/approve-callback", headers=KEY,
                      json=dict(APPROVE_BODY, approval_status="maybe"))
    assert res.status_code == 400


def test_approve_without_webhook_is_stored_and_honestly_not_sent(client, case_id, app, monkeypatch):
    monkeypatch.delenv("HIS_WEBHOOK_URL", raising=False)
    res = client.post(f"/api/his/v1/cases/{case_id}/approve-callback", headers=KEY, json=APPROVE_BODY)
    assert res.status_code == 200
    record = res.get_json()["record"]
    assert record["written_to_his"] is False
    assert record["delivery"]["status"] == "not_sent"
    stored = app.extensions["elc"].case_store.get_artifact(case_id, his_integration.APPROVED_ARTIFACT)
    assert stored["final_soap"] == APPROVE_BODY["approved_soap"]


class _FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_webhook_success_marks_written_to_his(client, case_id, monkeypatch):
    monkeypatch.setenv("HIS_WEBHOOK_URL", "https://his.clinic.example/hook")
    sent = {}

    def _fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["timeout"] = timeout
        return _FakeResponse(200)

    monkeypatch.setattr(his_integration.urllib.request, "urlopen", _fake_urlopen)
    res = client.post(f"/api/his/v1/cases/{case_id}/approve-callback", headers=KEY, json=APPROVE_BODY)
    assert res.status_code == 200
    assert res.get_json()["record"]["written_to_his"] is True
    assert sent["url"] == "https://his.clinic.example/hook"
    assert sent["timeout"] == his_integration.WEBHOOK_TIMEOUT_SECONDS


def test_webhook_failure_is_502_but_still_stored_locally(client, case_id, app, monkeypatch):
    monkeypatch.setenv("HIS_WEBHOOK_URL", "https://his.clinic.example/hook")

    def _boom(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(his_integration.urllib.request, "urlopen", _boom)
    res = client.post(f"/api/his/v1/cases/{case_id}/approve-callback", headers=KEY, json=APPROVE_BODY)
    assert res.status_code == 502
    body = res.get_json()
    assert body["status"] == "delivery_failed"
    assert body["record"]["delivery"] == {"status": "failed", "error": "URLError"}
    assert app.extensions["elc"].case_store.get_artifact(case_id, his_integration.APPROVED_ARTIFACT) is not None


def test_webhook_destination_is_not_taken_from_request(client, case_id, monkeypatch):
    monkeypatch.delenv("HIS_WEBHOOK_URL", raising=False)
    called = []
    monkeypatch.setattr(his_integration.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    body = dict(APPROVE_BODY, webhook_url="https://attacker.example/steal")
    res = client.post(f"/api/his/v1/cases/{case_id}/approve-callback", headers=KEY, json=body)
    assert res.status_code == 200
    assert called == []  # 請求中的網址被忽略，未送出任何連線
