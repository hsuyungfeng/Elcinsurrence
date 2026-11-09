import json
import tempfile
import pytest

from elc_audit_engine.api.app import create_app
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.case_store.soap_draft_states import compute_soap_content_hash


@pytest.fixture
def test_setup():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
        store = CaseStore(f.name)
        # Create a Stage 2 case in cases table to verify its state never changes
        store.create(case_id="CASE-P29-001", kind="sampling")
        store.transition("CASE-P29-001", "parsed")
        store.transition("CASE-P29-001", "reviewing")

        app = create_app(
            config={
                "TESTING": True,
                "ELC_API_KEYS": {"key_physician_123456": "dr_lin"},
                "ELC_AGENT_KEYS": {"key_agent_123456789": "win_agent_01"},
                "ELC_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver"],
            },
            case_store=store,
            migrate_legacy=False,
        )
        client = app.test_client()
        yield client, store


def test_soap_draft_full_api_workflow(test_setup):
    client, store = test_setup
    physician_headers = {"X-API-Key": "key_physician_123456"}

    # 1. Create a draft
    valid_soap = {
        "s": "Patient presented with acute right lower quadrant abdominal pain for 6 hours.",
        "o": "Tenderness and rebound tenderness at McBurney point. Low grade fever 37.8C.",
        "a": "K35.80 Acute appendicitis, other and unspecified.",
        "p": "Urgent surgical consultation and abdominal sonography scheduled.",
    }
    resp = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-P29-001", "order_code": "28016C", "soap": valid_soap},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    draft = data["draft"]
    draft_id = draft["draft_id"]
    assert draft["state"] == "validated"
    assert draft["version"] == 1
    initial_hash = draft["content_hash"]

    # 2. Get draft
    resp = client.get(f"/api/soap/drafts/{draft_id}", headers=physician_headers)
    assert resp.status_code == 200
    assert resp.get_json()["draft"]["draft_id"] == draft_id

    # 3. Edit draft -> version 2
    edited_soap = dict(valid_soap, s="Patient presented with severe right lower quadrant abdominal pain.")
    resp = client.post(
        f"/api/soap/drafts/{draft_id}/edit",
        headers=physician_headers,
        json={"soap": edited_soap},
    )
    assert resp.status_code == 200
    e_draft = resp.get_json()["draft"]
    assert e_draft["version"] == 2
    assert e_draft["content_hash"] != initial_hash

    # 4. Attempt approve with stale hash -> 409
    resp = client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        headers=physician_headers,
        json={"content_hash": initial_hash},
    )
    assert resp.status_code == 409
    assert "content_hash 與目前草稿版本不符" in resp.get_json()["message"]

    # 5. Approve with valid hash -> enqueued to HIS_PUSH
    resp = client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        headers=physician_headers,
        json={"content_hash": e_draft["content_hash"]},
    )
    assert resp.status_code == 200
    approved_data = resp.get_json()
    assert approved_data["status"] == "success"
    assert approved_data["draft"]["state"] == "queued"
    job = approved_data["job"]
    assert job["s_type_code"] == "HIS_PUSH"
    job_id = job["job_id"]

    # 6. Verify Stage 2 case state was NOT modified
    case_rec = store.get("CASE-P29-001")
    assert case_rec.state == "reviewing"

    # 7. Agent polls pending HIS_PUSH jobs
    agent_headers = {"X-API-Key": "key_agent_123456789"}
    resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers=agent_headers)
    assert resp.status_code == 200
    pending_jobs = resp.get_json()["jobs"]
    assert any(j["job_id"] == job_id for j in pending_jobs)

    # 8. Agent claims job (PENDING -> SENDING)
    resp = client.post(
        f"/api/bridge/jobs/{job_id}/status",
        headers=agent_headers,
        json={"status": "SENDING", "expected_status": "PENDING"},
    )
    assert resp.status_code == 200

    # 9. Agent reports SUCCESS -> draft state becomes 'pushed'
    resp = client.post(
        f"/api/bridge/jobs/{job_id}/status",
        headers=agent_headers,
        json={"status": "SUCCESS", "expected_status": "SENDING"},
    )
    assert resp.status_code == 200
    updated_draft = store.get_soap_draft(draft_id)
    assert updated_draft.state == "pushed"
    assert updated_draft.pushed_at is not None

    # 9. Idempotency test (§8.6): Approve same case_id + content_hash again -> already_pushed
    # Create another draft for same case and content
    resp = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-P29-001", "order_code": "28016C", "soap": edited_soap},
    )
    assert resp.status_code == 201
    draft_id_2 = resp.get_json()["draft"]["draft_id"]
    resp = client.post(
        f"/api/soap/drafts/{draft_id_2}/approve",
        headers=physician_headers,
        json={"content_hash": e_draft["content_hash"]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "already_pushed"


def test_soap_draft_reject(test_setup):
    client, store = test_setup
    physician_headers = {"X-API-Key": "key_physician_123456"}

    valid_soap = {
        "s": "Patient presented with sore throat and fever for 2 days.",
        "o": "Tonsils erythematous with purulent exudate. Temp 38.5C.",
        "a": "J03.90 Acute tonsillitis, unspecified.",
        "p": "Oral amoxicillin prescribed, warm saline gargle advised.",
    }
    resp = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-REJECT-01", "soap": valid_soap},
    )
    draft_id = resp.get_json()["draft"]["draft_id"]

    # Reject without reason -> 422
    resp = client.post(f"/api/soap/drafts/{draft_id}/reject", headers=physician_headers, json={})
    assert resp.status_code == 422

    # Reject with reason -> rejected
    resp = client.post(
        f"/api/soap/drafts/{draft_id}/reject",
        headers=physician_headers,
        json={"reason": "Inaccurate physical findings", "reason_code": "CLINICAL_MISMATCH"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["draft"]["state"] == "rejected"

    # Terminal state: cannot approve rejected draft
    resp = client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        headers=physician_headers,
        json={"content_hash": resp.get_json()["draft"]["content_hash"]},
    )
    assert resp.status_code == 409


def test_agent_heartbeat_and_security(test_setup):
    client, store = test_setup
    agent_headers = {"X-API-Key": "key_agent_123456789"}

    # 1. Send heartbeat
    resp = client.post(
        "/api/agent/heartbeat",
        headers=agent_headers,
        json={"agent_id": "win_agent_01", "version": "1.0.0", "his_status": "ready"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    # 2. Query agent status
    resp = client.get("/api/agent/status", headers=agent_headers)
    assert resp.status_code == 200
    agents = resp.get_json()["agents"]
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "win_agent_01"
    assert agents[0]["is_online"] is True

    # 3. Agent key trying to access physician review endpoint -> 403 Forbidden
    resp = client.post(
        "/api/soap/drafts",
        headers=agent_headers,
        json={"case_id": "C-1", "soap": {}},
    )
    assert resp.status_code == 403
    assert "Agent 金鑰權限不足" in resp.get_json()["message"]


def test_soap_batch_approve(test_setup):
    client, store = test_setup
    physician_headers = {"X-API-Key": "key_physician_123456"}

    valid_soap = {
        "s": "Patient presented with sore throat and fever for 2 days.",
        "o": "Tonsils erythematous with purulent exudate. Temp 38.5C.",
        "a": "J03.90 Acute tonsillitis, unspecified.",
        "p": "Oral amoxicillin prescribed, warm saline gargle advised.",
    }

    # Draft 1
    resp1 = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-BATCH-01", "soap": valid_soap},
    )
    d1 = resp1.get_json()["draft"]

    # Draft 2
    resp2 = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-BATCH-02", "soap": valid_soap},
    )
    d2 = resp2.get_json()["draft"]

    # Batch approve: d1 with correct hash, d2 with mismatched hash
    resp = client.post(
        "/api/soap/batches/batch_nov_01/approve",
        headers=physician_headers,
        json={
            "items": [
                {"draft_id": d1["draft_id"], "content_hash": d1["content_hash"]},
                {"draft_id": d2["draft_id"], "content_hash": "wrong_hash"},
            ]
        },
    )
    assert resp.status_code == 200
    b_data = resp.get_json()
    assert b_data["approved_count"] == 1
    res_map = {r["draft_id"]: r["status"] for r in b_data["results"]}
    assert res_map[d1["draft_id"]] == "approved"
    assert res_map[d2["draft_id"]] == "skipped"

    # Verify d1 state is queued
    assert store.get_soap_draft(d1["draft_id"]).state == "queued"
    # Verify d2 state remains validated
    assert store.get_soap_draft(d2["draft_id"]).state == "validated"


def test_soap_draft_template_comparison_from_store(test_setup):
    """§5, §11: 標準範本比對來源為既有 soap_templates 資料表。"""
    client, store = test_setup
    physician_headers = {"X-API-Key": "key_physician_123456"}

    # Seed standard template in soap_templates table
    tmpl_soap = {
        "s": "Standard Subjective text for appendicitis",
        "o": "Standard Objective exam tenderness McBurney",
        "a": "K35.80 Acute appendicitis",
        "p": "Standard surgical consult and sonography",
    }
    store.put_soap_template("28016C", "", tmpl_soap, source="standard", quality_score=95)

    draft_soap = {
        "s": "Patient presented with acute right lower quadrant abdominal pain for 6 hours.",
        "o": "Tenderness and rebound tenderness at McBurney point. Low grade fever 37.8C.",
        "a": "K35.80 Acute appendicitis, other and unspecified.",
        "p": "Urgent surgical consultation and abdominal sonography scheduled.",
    }
    resp = client.post(
        "/api/soap/drafts",
        headers=physician_headers,
        json={"case_id": "CASE-P29-001", "order_code": "28016C", "soap": draft_soap},
    )
    assert resp.status_code == 201
    comp = resp.get_json()["draft"]["comparison"]
    assert comp is not None
    assert "section_similarities" in comp
    assert comp["section_similarities"]["s"] >= 0.0
    assert comp["icd10_comparison"]["consistent_with_template"] is True
    assert "K35.80" in comp["icd10_comparison"]["template_icds"]
