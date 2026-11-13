"""Phase 31: 工作站心跳認證與通知搭便車測試 (契約 §3, D-31-12, D-31-16)."""

from __future__ import annotations

import uuid
from typing import Any


from elc_audit_engine.cycles.store import create_cycle, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401


def _assert_no_phi(obj: Any) -> None:
    """遞迴檢查字典/串列中絕無任何 PHI 欄位 (契約 §3, D-31-12)."""
    forbidden_keys = {
        "soap",
        "soap_text",
        "transcript",
        "extras",
        "patient_name",
        "patient_ref",
        "record_no",
        "id_number",
        "birth_date",
    }
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in forbidden_keys, f"Found forbidden key in response: {k}"
            assert not k.startswith("patient"), f"Found patient-prefixed key: {k}"
            _assert_no_phi(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_phi(item)


def test_notify_awaiting_confirm(phase31_app, phase31_client):
    """Test notify_1: 機器 m1 有 AWAITING_CONFIRM 循環 → 心跳回應 notify 且零 PHI。"""
    store = phase31_app.case_store
    m1 = str(uuid.uuid4())
    cmd1 = uuid.uuid4().hex

    cycle, _ = create_cycle(store, command_id=cmd1, machine_id=m1, room_id="room_101")
    cid = cycle["cycle_id"]

    # 模擬建立草稿並推進到 AWAITING_CONFIRM
    draft_id = f"draft_{uuid.uuid4().hex[:8]}"
    soap_dict = {
        "s": "Shortness of breath for two days.",
        "o": "BP 120/80 mmHg.",
        "a": "Asthma exacerbation.",
        "p": "Inhaled albuterol prescribed.",
    }
    store.create_soap_draft(
        case_id="case_test_1",
        draft_id=draft_id,
        soap=soap_dict,
        state="draft",
    )

    transition_cycle(store, cid, "AWAITING_DRAFT")
    transition_cycle(store, cid, "AWAITING_CONFIRM", fields={"draft_id": draft_id})

    # 心跳請求
    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={
            "machine_id": m1,
            "machine_name": "Dr_Room_1",
            "room_id": "room_101",
            "bar_state": "WAITING_CONFIRM",
            "soapvoice_state": "IDLE",
            "chunks_pending": 0,
            "app_version": "1.0.0",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "server_time" in data

    notify = data["notify"]
    assert notify is not None
    assert notify["cycle_id"] == cid
    assert notify["state"] == "AWAITING_CONFIRM"
    assert notify["draft_id"] == draft_id
    assert notify["draft_version"] == 1

    # 嚴格零 PHI 檢查
    _assert_no_phi(data)


def test_notify_auth(phase31_app, phase31_client):
    """Test notify_2: 無 key → 401 且不含 notify；Agent key → 403。"""
    m1 = str(uuid.uuid4())

    # 1. 無 key 請求
    resp_no_key = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": m1},
    )
    assert resp_no_key.status_code == 401
    data_no_key = resp_no_key.get_json()
    assert "notify" not in (data_no_key or {})

    # 2. Agent 金鑰請求
    resp_agent = phase31_client.post(
        "/api/clients/heartbeat",
        headers={"X-API-Key": "agent-key-1"},
        json={"machine_id": m1},
    )
    assert resp_agent.status_code == 403


def test_notify_isolation(phase31_app, phase31_client):
    """Test notify_3: m2 的心跳不會收到 m1 的通知 (D-31-16)。"""
    store = phase31_app.case_store
    m1 = str(uuid.uuid4())
    m2 = str(uuid.uuid4())

    cycle1, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m1)
    transition_cycle(store, cycle1["cycle_id"], "AWAITING_DRAFT")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={"machine_id": m2},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["notify"] is None


def test_notify_no_active_cycle(phase31_app, phase31_client):
    """Test notify_4: 無未終結循環 → notify 為 null。"""
    store = phase31_app.case_store
    m1 = str(uuid.uuid4())

    # 建立循環後封存之
    c, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m1)
    transition_cycle(store, c["cycle_id"], "AWAITING_DRAFT")
    transition_cycle(store, c["cycle_id"], "AWAITING_CONFIRM")
    transition_cycle(store, c["cycle_id"], "CONFIRMED")
    transition_cycle(store, c["cycle_id"], "ARCHIVED")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={"machine_id": m1},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["notify"] is None
