"""Tests for cycle review isolation (D-31-39, D-31-16, D-31-13).

驗證：
1. GET /api/soap/drafts/pending-review 排除已綁定循環的草稿
2. POST /api/soap/drafts/<id>/approve 與 edit 對已綁定循環的草稿阻絕 (409)
3. 兩台機器並行循環時 GET /api/cycles/<id>/draft 各自隔離
"""


from elc_audit_engine.case_store.soap_draft_states import STATE_VALIDATED
from elc_audit_engine.cycles.store import create_cycle, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401


KEY = {"X-API-Key": "valid-key-123"}


def _mk_draft(store, case_id: str, soap_dict: dict | None = None):
    soap = soap_dict or {"s": "發燒", "o": "38.5C", "a": "急性上呼吸道感染", "p": "退燒藥三日"}
    return store.create_soap_draft(
        case_id=case_id,
        soap=soap,
        state=STATE_VALIDATED,
        quality_score=95,
    )


def test_pending_review_excludes_cycle_draft(phase31_client, phase31_app):
    """Test 1: pending-review 排除已綁定循環之草稿 (D-31-39)。"""
    store = phase31_app.case_store

    # 1. 建立一筆綁定到循環的草稿 d_bound
    c, _ = create_cycle(store, command_id="c1" * 16, machine_id="m1")
    cid = c["cycle_id"]
    d_bound = _mk_draft(store, "case_bound_1")

    # 推進循環並綁定草稿
    transition_cycle(store, cid, "AWAITING_DRAFT", actor="test")
    transition_cycle(store, cid, "AWAITING_CONFIRM", actor="test", fields={"draft_id": d_bound.draft_id})

    # 2. 建立一筆未綁定循環的草稿 d_unbound
    d_unbound = _mk_draft(store, "case_unbound_2")

    # 3. 呼叫 pending-review
    res = phase31_client.get("/api/soap/drafts/pending-review", headers=KEY)
    assert res.status_code == 200
    draft_ids = [d["draft_id"] for d in res.get_json()["drafts"]]

    assert d_unbound.draft_id in draft_ids
    assert d_bound.draft_id not in draft_ids  # D-31-39: 已綁定者必須被排除


def test_generic_approve_and_edit_blocked_for_cycle_draft(phase31_client, phase31_app):
    """Test 2: 通用 approve 與 edit 對已綁定循環的草稿回 409。"""
    store = phase31_app.case_store

    c, _ = create_cycle(store, command_id="c2" * 16, machine_id="m1")
    cid = c["cycle_id"]
    d_bound = _mk_draft(store, "case_bound_3")

    transition_cycle(store, cid, "AWAITING_DRAFT", actor="test")
    transition_cycle(store, cid, "AWAITING_CONFIRM", actor="test", fields={"draft_id": d_bound.draft_id})

    # 通用 approve 應回 409
    res_app = phase31_client.post(f"/api/soap/drafts/{d_bound.draft_id}/approve", headers=KEY, json={"doctor_name": "王醫師"})
    assert res_app.status_code == 409

    # 通用 edit 應回 409
    res_edit = phase31_client.post(
        f"/api/soap/drafts/{d_bound.draft_id}/edit",
        headers=KEY,
        json={"soap": {"s": "修改", "o": "修改", "a": "修改", "p": "修改"}},
    )
    assert res_edit.status_code == 409

    # 未綁定草稿 approve 正常成功
    d_unbound = _mk_draft(store, "case_unbound_4")
    res_unbound = phase31_client.post(
        f"/api/soap/drafts/{d_unbound.draft_id}/approve",
        headers=KEY,
        json={"doctor_name": "王醫師", "content_hash": d_unbound.content_hash},
    )
    assert res_unbound.status_code == 200


def test_two_machines_cycle_draft_isolation(phase31_client, phase31_app):
    """Test 3: 兩台機器 m1、m2 的循環各自讀取綁定草稿，互不混淆 (D-31-16)。"""
    store = phase31_app.case_store

    c1, _ = create_cycle(store, command_id="m1" * 16, machine_id="mach_1")
    c2, _ = create_cycle(store, command_id="m2" * 16, machine_id="mach_2")

    d1 = _mk_draft(store, "case_mach_1")
    d2 = _mk_draft(store, "case_mach_2")

    transition_cycle(store, c1["cycle_id"], "AWAITING_DRAFT", actor="test")
    transition_cycle(store, c1["cycle_id"], "AWAITING_CONFIRM", actor="test", fields={"draft_id": d1.draft_id})

    transition_cycle(store, c2["cycle_id"], "AWAITING_DRAFT", actor="test")
    transition_cycle(store, c2["cycle_id"], "AWAITING_CONFIRM", actor="test", fields={"draft_id": d2.draft_id})

    r1 = phase31_client.get(f"/api/cycles/{c1['cycle_id']}/draft", headers=KEY)
    assert r1.status_code == 200
    assert r1.get_json()["draft"]["draft_id"] == d1.draft_id

    r2 = phase31_client.get(f"/api/cycles/{c2['cycle_id']}/draft", headers=KEY)
    assert r2.status_code == 200
    assert r2.get_json()["draft"]["draft_id"] == d2.draft_id
