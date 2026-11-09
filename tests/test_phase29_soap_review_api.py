"""Phase 29 T7 — SOAP 審核 API／狀態機／批次核准整合測試（29-DESIGN.md §4、§6、§11）。

對應驗收項目：
- A1 未核准不產生 HIS_PUSH 任務
- A2 狀態機與 content_hash 鎖定（舊版核准被拒絕）
- A4 同 case_id+content_hash 冪等（API 核准層）
- A6 Stage 2 案件狀態不受 SOAP 審核流程影響
- A7 日誌與審計紀錄不含 SOAP 內文
- §11.1 標準範本 = 現有 soap_templates（advisory 比對，不改狀態）
- §11.3 批次核准 POST /api/soap/batches/<batch_id>/approve
- §8.9  content_hash 只涵蓋 S/O/A/P（診斷/醫令/藥令不影響版本鎖）

與 agy 的單元測試（test_soap_draft_states.py / test_soap_review_api.py）互補：
本檔以「完整 API app + 真實 CaseStore」做整合層驗證。
"""
from __future__ import annotations

import itertools
import json
import logging
from types import SimpleNamespace

import pytest

from elc_audit_engine import audit_log
from elc_audit_engine.bridge_queue import get_job
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_APPROVED,
    STATE_DRAFT,
    STATE_FAILED,
    STATE_PUSHED,
    STATE_QUALITY_FAILED,
    STATE_QUEUED,
    STATE_REJECTED,
    STATE_VALIDATED,
    ALL_DRAFT_STATES,
    TERMINAL_DRAFT_STATES,
    compute_soap_content_hash,
    assert_draft_transition_allowed,
    IllegalDraftTransitionError,
    UnknownDraftStateError,
)

KEY = {"X-API-Key": "valid-key-123"}

# ── 固定測試資料（已驗證：SOAP_OK／SOAP_OK2 通過 validate_soap_quality，score 100）──

SOAP_OK = {
    "s": "Patient presents with a three day history of sore throat, low grade fever, and runny nose.",
    "o": "Temperature 37.8 C, pharyngeal hyperemia, tender bilateral cervical lymphadenopathy.",
    "a": "Acute pharyngitis, most consistent with viral etiology, primary diagnosis coded J02.9.",
    "p": "Advise rest, warm fluids, and symptomatic relief; follow up in five days if fever persists.",
}
SOAP_OK2 = {
    "s": "Patient returns with worsening sore throat and fever now reaching 39 C since yesterday.",
    "o": "Temperature 39.1 C, exudative tonsils, decreased breath sounds at right base on auscultation.",
    "a": "Acute tonsillopharyngitis progressing, possible bacterial superinfection, coded J03.9.",
    "p": "Prescribe symptomatic care, obtain throat culture, and schedule a follow up visit in three days.",
}
SOAP_OK3 = {
    "s": "Patient reports persistent nasal congestion and post nasal drip for one week now.",
    "o": "Mucopurulent nasal discharge, mild septal deviation, oropharynx without exudate today.",
    "a": "Acute rhinosinusitis, most likely viral, with secondary congestion, coded J01.9.",
    "p": "Advise nasal saline irrigation and antihistamine; review in four days if symptoms persist.",
}
SOAP_BAD = {"s": "short", "o": "short", "a": "short", "p": "short"}

SENTINEL_S = "SENTINEL-ZZQ7-COMPLAINT-SYMPTOMS"
SENTINEL_O = "SENTINEL-ZZQ7-PATIENT-IDENTIFIER"
SOAP_SENTINEL = {
    "s": f"Patient says {SENTINEL_S} and has a mild cough with low grade fever for two days.",
    "o": f"Chart {SENTINEL_O} records temperature 38 C and a congested oropharynx on exam.",
    "a": "Acute upper respiratory infection consistent with viral pharyngitis, coded J06.9.",
    "p": "Advise rest and fluids, symptomatic treatment, and a follow up visit in four days.",
}
SOAP_SENTINEL2 = {
    "s": f"Patient returns, {SENTINEL_S} unchanged, with new mild headache this morning.",
    "o": f"Chart {SENTINEL_O} records temperature 38.4 C and tender posterior cervical nodes.",
    "a": "Acute upper respiratory infection progressing, viral etiology suspected, coded J06.9.",
    "p": "Prescribe symptomatic care and schedule a follow up visit within three days now.",
}


@pytest.fixture()
def env(tmp_path, make_api_app):
    """隔離的 API app + 真實 CaseStore（同一 tmp DB）。"""
    store = CaseStore(db_path=str(tmp_path / "cases.sqlite3"))
    app = make_api_app(case_store=store)
    with app.test_client() as client:
        yield SimpleNamespace(store=store, client=client, tmp_path=tmp_path)


def _make_case(store, case_id: str, batch: str = "BATCH-29") -> None:
    store.create(case_id=case_id, kind="monthly", case_seq="01", payload={"batch": batch}, actor="test")
    store.advance(case_id, ["parsed", "reviewing", "reviewed"], actor="test")


def _push_drafts(client, case_id: str, soap: dict, order_code: str | None = None) -> tuple[int, dict]:
    body: dict = {"case_id": case_id, "soap": soap}
    if order_code:
        body["order_code"] = order_code
    res = client.post("/api/soap/drafts", json=body, headers=KEY)
    return res.status_code, res.get_json()


def _his_push_jobs(store, case_id: str | None = None) -> list[dict]:
    records = store.list_bridge_jobs(s_type_code="HIS_PUSH", limit=500)
    jobs = [get_job(store, r.case_id) for r in records]
    if case_id is not None:
        jobs = [j for j in jobs if (j.get("extra_payload") or {}).get("case_id") == case_id]
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# §4 狀態機（純函式層）
# ─────────────────────────────────────────────────────────────────────────────


class TestDraftStateMachine:
    LEGAL = [
        ("draft", "validated"),
        ("draft", "quality_failed"),
        ("validated", "approved"),
        ("validated", "rejected"),
        ("validated", "validated"),
        ("validated", "quality_failed"),
        ("approved", "queued"),
        ("approved", "rejected"),
        ("queued", "pushed"),
        ("queued", "failed"),
        ("failed", "queued"),
        ("failed", "approved"),
        ("failed", "rejected"),
    ]
    ILLEGAL = [
        # 未核准絕不能進入寫入流程（A1 狀態機側）
        ("draft", "approved"),
        ("draft", "queued"),
        ("draft", "pushed"),
        ("validated", "queued"),
        ("validated", "pushed"),
        ("approved", "pushed"),
        ("approved", "validated"),
        ("queued", "approved"),
        ("queued", "rejected"),
        ("failed", "pushed"),
        ("failed", "validated"),
    ]

    @pytest.mark.parametrize("frm,to", LEGAL)
    def test_legal_transition_allowed(self, frm, to):
        assert_draft_transition_allowed(frm, to)

    @pytest.mark.parametrize("frm,to", ILLEGAL)
    def test_illegal_transition_rejected(self, frm, to):
        with pytest.raises(IllegalDraftTransitionError):
            assert_draft_transition_allowed(frm, to)

    @pytest.mark.parametrize(
        "unknown", ["", "PUSHED", "approved ", "valid", "reviewed", "done"]
    )
    def test_unknown_state_raises(self, unknown):
        for other in ALL_DRAFT_STATES:
            with pytest.raises(UnknownDraftStateError):
                assert_draft_transition_allowed(unknown, other)
            with pytest.raises(UnknownDraftStateError):
                assert_draft_transition_allowed(other, unknown)

    @pytest.mark.parametrize(
        "frm,to",
        [(t, x) for t in sorted(TERMINAL_DRAFT_STATES) for x in sorted(ALL_DRAFT_STATES)],
    )
    def test_terminal_states_are_closed(self, frm, to):
        with pytest.raises(IllegalDraftTransitionError):
            assert_draft_transition_allowed(frm, to)


class TestStoreDraftTransitions:
    """store 層同樣拒絕非法轉換（不得靜默略過）。"""

    def _draft(self, store, case_id, state=STATE_DRAFT):
        return store.create_soap_draft(case_id=case_id, soap=SOAP_OK, state=state)

    def test_unapproved_draft_cannot_be_queued(self, env):
        store = env.store
        d = self._draft(store, "C-SM-01", state=STATE_DRAFT)
        with pytest.raises(IllegalDraftTransitionError):
            store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        v = self._draft(store, "C-SM-01", state=STATE_VALIDATED)
        with pytest.raises(IllegalDraftTransitionError):
            store.update_soap_draft_state(v.draft_id, STATE_QUEUED)

    def test_approved_cannot_skip_queued(self, env):
        store = env.store
        d = self._draft(store, "C-SM-02", state=STATE_VALIDATED)
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        with pytest.raises(IllegalDraftTransitionError):
            store.update_soap_draft_state(d.draft_id, STATE_PUSHED)

    def test_failed_can_be_requeued(self, env):
        store = env.store
        d = self._draft(store, "C-SM-03", state=STATE_VALIDATED)
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        d = store.update_soap_draft_state(d.draft_id, STATE_FAILED, failure_reason="readback_mismatch")
        assert d.state == STATE_FAILED
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        assert d.state == STATE_QUEUED

    def test_find_pushed_soap_draft_idempotency_helper(self, env):
        store = env.store
        d = self._draft(store, "C-SM-04", state=STATE_VALIDATED)
        assert store.find_pushed_soap_draft("C-SM-04", d.content_hash) is None
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        d = store.update_soap_draft_state(d.draft_id, STATE_PUSHED, agent_id="agent-x")
        found = store.find_pushed_soap_draft("C-SM-04", d.content_hash)
        assert found is not None
        assert found.draft_id == d.draft_id


# ─────────────────────────────────────────────────────────────────────────────
# §8.9 content_hash 範圍（只鎖 S/O/A/P）
# ─────────────────────────────────────────────────────────────────────────────


class TestContentHashScope:
    def test_hash_is_sha256_hex(self):
        h = compute_soap_content_hash(SOAP_OK)
        assert len(h) == 64
        int(h, 16)  # 純十六進制

    def test_normalization_stable(self):
        base = compute_soap_content_hash(SOAP_OK)
        normalized = {k: (v + "\r\n   ").replace("\n", "\r\n") for k, v in SOAP_OK.items()}
        assert compute_soap_content_hash(normalized) == base

    def test_different_content_different_hash(self):
        assert compute_soap_content_hash(SOAP_OK) != compute_soap_content_hash(SOAP_OK2)

    def test_diagnosis_orders_meds_do_not_change_hash(self):
        """§8.9/§11.4：診斷碼、醫令、藥令僅為建議，不納入版本鎖。"""
        core = compute_soap_content_hash(SOAP_OK)
        enriched = {
            **SOAP_OK,
            "icd10": "J02.9",
            "icd10_code": "J02.9",
            "orders": [{"name": "CBC", "result": "WBC 8.2"}],
            "meds": [{"name": "Acetaminophen", "dose": "500mg"}],
        }
        assert compute_soap_content_hash(enriched) == core


# ─────────────────────────────────────────────────────────────────────────────
# §6 審核 API — 建立與比對（§11.1 標準範本 = 現有 soap_templates）
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateDraft:
    def test_valid_soap_becomes_validated_without_job(self, env):
        """A1：建立（含 validated）不產生 HIS_PUSH 任務。"""
        _make_case(env.store, "C-A1-01")
        code, body = _push_drafts(env.client, "C-A1-01", SOAP_OK)
        assert code == 201
        draft = body["draft"]
        assert draft["state"] == STATE_VALIDATED
        assert draft["content_hash"] == compute_soap_content_hash(SOAP_OK)
        assert _his_push_jobs(env.store, "C-A1-01") == []

    def test_low_quality_soap_becomes_quality_failed(self, env):
        _make_case(env.store, "C-A1-02")
        code, body = _push_drafts(env.client, "C-A1-02", SOAP_BAD)
        assert code == 201
        draft = body["draft"]
        assert draft["state"] == STATE_QUALITY_FAILED
        assert draft["quality_score"] is not None
        assert _his_push_jobs(env.store, "C-A1-02") == []
        # quality_failed 不可核准
        res = env.client.post(
            f"/api/soap/drafts/{draft['draft_id']}/approve",
            json={"content_hash": draft["content_hash"]},
            headers=KEY,
        )
        assert res.status_code == 409
        assert _his_push_jobs(env.store, "C-A1-02") == []

    def test_template_comparison_is_advisory(self, env):
        """§11.1：比對來源為現有 soap_templates；僅建議、不改狀態。"""
        store, client = env.store, env.client
        store.put_soap_template("E5002C", "", SOAP_OK2, source="llm_validated", quality_score=95)
        _make_case(store, "C-TPL-01")
        code, body = _push_drafts(client, "C-TPL-01", SOAP_OK2, order_code="E5002C")
        assert code == 201
        draft = body["draft"]
        assert draft["state"] == STATE_VALIDATED  # 比對不得改狀態
        comp = draft["comparison"]
        assert comp is not None
        assert comp["advisory_only"] is True
        assert set(comp["section_similarities"]) == {"s", "o", "a", "p"}
        assert comp["overall_similarity"] == 1.0  # 與範本相同
        assert comp["icd10_comparison"]["consistent_with_template"] is True

    def test_template_comparison_flags_divergence(self, env):
        store, client = env.store, env.client
        store.put_soap_template("E5002C", "", SOAP_OK, source="llm_validated", quality_score=95)
        _make_case(store, "C-TPL-02")
        _, body = _push_drafts(client, "C-TPL-02", SOAP_OK2, order_code="E5002C")
        comp = body["draft"]["comparison"]
        assert comp["overall_similarity"] < 1.0
        assert comp["icd10_comparison"]["consistent_with_template"] is False

    def test_no_template_means_no_comparison(self, env):
        _make_case(env.store, "C-TPL-03")
        _, body = _push_drafts(env.client, "C-TPL-03", SOAP_OK, order_code="E5002C")
        assert body["draft"]["comparison"] is None

    def test_requires_api_key(self, env):
        _make_case(env.store, "C-AUTH-01")
        res = env.client.post("/api/soap/drafts", json={"case_id": "C-AUTH-01", "soap": SOAP_OK})
        assert res.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# §6 審核 API — 核准（A1／A2／A4）
# ─────────────────────────────────────────────────────────────────────────────


class TestApprove:
    def test_approve_with_matching_hash_queues_job(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-AP-01")
        _, body = _push_drafts(client, "C-AP-01", SOAP_OK)
        d = body["draft"]
        res = client.post(
            f"/api/soap/drafts/{d['draft_id']}/approve",
            json={"content_hash": d["content_hash"]},
            headers=KEY,
        )
        assert res.status_code == 200
        assert res.get_json()["draft"]["state"] == STATE_QUEUED
        jobs = _his_push_jobs(store, "C-AP-01")
        assert len(jobs) == 1
        job = jobs[0]
        assert job["status"] == "PENDING"
        extra = job["extra_payload"]
        assert extra["content_hash"] == d["content_hash"]
        assert extra["case_id"] == "C-AP-01"
        assert extra["draft_id"] == d["draft_id"]
        assert extra["soap"] == SOAP_OK

    def test_approve_stale_hash_rejected(self, env):
        """A2：編輯後以舊版 content_hash 核准必須 409。"""
        store, client = env.store, env.client
        _make_case(store, "C-AP-02")
        _, body = _push_drafts(client, "C-AP-02", SOAP_OK)
        d = body["draft"]
        stale_hash = d["content_hash"]
        res = client.post(
            f"/api/soap/drafts/{d['draft_id']}/edit",
            json={"soap": SOAP_OK2},
            headers=KEY,
        )
        assert res.status_code == 200
        assert res.get_json()["draft"]["content_hash"] != stale_hash
        res = client.post(
            f"/api/soap/drafts/{d['draft_id']}/approve",
            json={"content_hash": stale_hash},
            headers=KEY,
        )
        assert res.status_code == 409
        assert _his_push_jobs(store, "C-AP-02") == []

    def test_approve_without_hash_rejected(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-AP-03")
        _, body = _push_drafts(client, "C-AP-03", SOAP_OK)
        d = body["draft"]
        res = client.post(f"/api/soap/drafts/{d['draft_id']}/approve", json={}, headers=KEY)
        assert res.status_code == 409
        assert _his_push_jobs(store, "C-AP-03") == []

    def test_approve_unapproved_state_rejected_no_job(self, env):
        """A1：state=draft（未通過檢核）不可核准，且不產生任務。"""
        store, client = env.store, env.client
        _make_case(store, "C-AP-04")
        d = store.create_soap_draft(case_id="C-AP-04", soap=SOAP_OK, state=STATE_DRAFT)
        res = client.post(
            f"/api/soap/drafts/{d.draft_id}/approve",
            json={"content_hash": d.content_hash},
            headers=KEY,
        )
        assert res.status_code == 409
        assert _his_push_jobs(store, "C-AP-04") == []

    def test_approve_already_queued_rejected(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-AP-05")
        d = store.create_soap_draft(case_id="C-AP-05", soap=SOAP_OK, state=STATE_VALIDATED)
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        res = client.post(
            f"/api/soap/drafts/{d.draft_id}/approve",
            json={"content_hash": d.content_hash},
            headers=KEY,
        )
        assert res.status_code == 409
        assert len(_his_push_jobs(store, "C-AP-05")) == 0

    def test_idempotent_approve_returns_already_pushed(self, env):
        """A4：同 case_id+content_hash 已 pushed 者，再次核准直接回 already_pushed、不新增任務。"""
        store, client = env.store, env.client
        _make_case(store, "C-ID-01")
        _, body = _push_drafts(client, "C-ID-01", SOAP_OK)
        d1 = body["draft"]
        res = client.post(
            f"/api/soap/drafts/{d1['draft_id']}/approve",
            json={"content_hash": d1["content_hash"]},
            headers=KEY,
        )
        assert res.status_code == 200
        store.update_soap_draft_state(d1["draft_id"], STATE_PUSHED, agent_id="agent-x")
        assert len(_his_push_jobs(store, "C-ID-01")) == 1

        # 同一案件、同一內容的後續草稿（同 content_hash）
        _, body2 = _push_drafts(client, "C-ID-01", SOAP_OK)
        d2 = body2["draft"]
        assert d2["content_hash"] == d1["content_hash"]
        res = client.post(
            f"/api/soap/drafts/{d2['draft_id']}/approve",
            json={"content_hash": d2["content_hash"]},
            headers=KEY,
        )
        body_json = res.get_json()
        assert res.status_code == 200
        assert body_json["status"] == "already_pushed"
        assert len(_his_push_jobs(store, "C-ID-01")) == 1  # 沒有新增任務


# ─────────────────────────────────────────────────────────────────────────────
# §6 審核 API — 編修與退回
# ─────────────────────────────────────────────────────────────────────────────


class TestEditReject:
    def test_edit_bumps_version_and_revalidates(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-ER-01")
        _, body = _push_drafts(client, "C-ER-01", SOAP_OK)
        d = body["draft"]
        res = client.post(
            f"/api/soap/drafts/{d['draft_id']}/edit",
            json={"soap": SOAP_OK2},
            headers=KEY,
        )
        assert res.status_code == 200
        d2 = res.get_json()["draft"]
        assert d2["version"] == d["version"] + 1
        assert d2["state"] == STATE_VALIDATED
        assert d2["content_hash"] == compute_soap_content_hash(SOAP_OK2)
        assert d2["content_hash"] != d["content_hash"]

    def test_edit_rejected_in_write_flow_states(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-ER-02")
        d = store.create_soap_draft(case_id="C-ER-02", soap=SOAP_OK, state=STATE_VALIDATED)
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        res = client.post(
            f"/api/soap/drafts/{d.draft_id}/edit",
            json={"soap": SOAP_OK2},
            headers=KEY,
        )
        assert res.status_code == 409

    def test_reject_is_terminal(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-ER-03")
        _, body = _push_drafts(client, "C-ER-03", SOAP_OK)
        d = body["draft"]
        res = client.post(
            f"/api/soap/drafts/{d['draft_id']}/reject",
            json={"reason_code": "RC-01", "reason": "文件不足"},
            headers=KEY,
        )
        assert res.status_code == 200
        d2 = res.get_json()["draft"]
        assert d2["state"] == STATE_REJECTED
        assert "RC-01" in (d2["review_reason"] or "")
        # 終態：再核准／再退回皆被拒絕
        assert (
            client.post(
                f"/api/soap/drafts/{d['draft_id']}/approve",
                json={"content_hash": d["content_hash"]},
                headers=KEY,
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/soap/drafts/{d['draft_id']}/reject",
                json={"reason": "again"},
                headers=KEY,
            ).status_code
            == 409
        )

    def test_reject_requires_reason(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-ER-04")
        _, body = _push_drafts(client, "C-ER-04", SOAP_OK)
        d = body["draft"]
        res = client.post(f"/api/soap/drafts/{d['draft_id']}/reject", json={}, headers=KEY)
        assert res.status_code == 422

    def test_reject_pushed_draft_rejected(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-ER-05")
        d = store.create_soap_draft(case_id="C-ER-05", soap=SOAP_OK, state=STATE_VALIDATED)
        d = store.update_soap_draft_state(d.draft_id, STATE_APPROVED)
        d = store.update_soap_draft_state(d.draft_id, STATE_QUEUED)
        d = store.update_soap_draft_state(d.draft_id, STATE_PUSHED, agent_id="agent-x")
        res = client.post(
            f"/api/soap/drafts/{d.draft_id}/reject",
            json={"reason": "too late"},
            headers=KEY,
        )
        assert res.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# §11.3 批次核准
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchApprove:
    def test_batch_approve_per_case_results(self, env):
        """§11.3：逐案以各自 content_hash 核准；已變動／非待審核者標記 skipped 不予核准。"""
        store, client = env.store, env.client
        _make_case(store, "C-B-01")
        _make_case(store, "C-B-02")
        _, b1 = _push_drafts(client, "C-B-01", SOAP_OK)   # 待核准
        _, b2 = _push_drafts(client, "C-B-01", SOAP_BAD)  # quality_failed
        _, b3 = _push_drafts(client, "C-B-02", SOAP_OK2)  # 待核准（以舊 hash 送審 → skipped）

        res = client.post(
            "/api/soap/batches/BATCH-29/approve",
            json={
                "items": [
                    {"draft_id": b1["draft"]["draft_id"], "content_hash": b1["draft"]["content_hash"]},
                    {"draft_id": b2["draft"]["draft_id"], "content_hash": b2["draft"]["content_hash"]},
                    {"draft_id": b3["draft"]["draft_id"], "content_hash": "0" * 64},
                    {"draft_id": "no-such-draft", "content_hash": "0" * 64},
                ],
            },
            headers=KEY,
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["batch_id"] == "BATCH-29"
        assert body["approved_count"] == 1
        by_id = {r["draft_id"]: r for r in body["results"]}
        assert by_id[b1["draft"]["draft_id"]]["status"] == "approved"
        assert by_id[b1["draft"]["draft_id"]].get("job_id")
        assert by_id[b2["draft"]["draft_id"]]["status"] == "skipped"
        assert by_id[b3["draft"]["draft_id"]]["status"] == "skipped"
        assert by_id["no-such-draft"]["status"] == "error"

        # store 事實：核准者入列並有任務；被跳過者狀態不變
        d1 = store.get_soap_draft(b1["draft"]["draft_id"])
        assert d1.state == STATE_QUEUED
        assert len(_his_push_jobs(store, "C-B-01")) == 1
        assert len(_his_push_jobs(store, "C-B-02")) == 0
        assert store.get_soap_draft(b2["draft"]["draft_id"]).state == STATE_QUALITY_FAILED
        assert store.get_soap_draft(b3["draft"]["draft_id"]).state == STATE_VALIDATED

    def test_batch_approve_auto_finds_validated(self, env):
        """未傳 items：自動核准所有 validated 草稿。"""
        store, client = env.store, env.client
        _make_case(store, "C-B-03")
        _make_case(store, "C-B-04")
        _push_drafts(client, "C-B-03", SOAP_OK)
        _push_drafts(client, "C-B-04", SOAP_OK2)
        _, bad = _push_drafts(client, "C-B-03", SOAP_BAD)

        res = client.post("/api/soap/batches/BATCH-29/approve", json={}, headers=KEY)
        assert res.status_code == 200
        body = res.get_json()
        assert body["approved_count"] == 2
        statuses = {r["status"] for r in body["results"]}
        assert "approved" in statuses
        # 自動模式只挑選 validated 草稿；quality_failed 不屬於目標，不會出現在結果中（設計 §6）
        assert all(r["draft_id"] != bad["draft"]["draft_id"] for r in body["results"])
        assert bad["draft"]["state"] or store.get_soap_draft(bad["draft"]["draft_id"]).state == STATE_QUALITY_FAILED
        assert len(_his_push_jobs(store, "C-B-03")) == 1
        assert len(_his_push_jobs(store, "C-B-04")) == 1

    def test_batch_approve_requires_api_key(self, env):
        res = env.client.post("/api/soap/batches/BATCH-29/approve", json={})
        assert res.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# A6 Stage 2 隔離
# ─────────────────────────────────────────────────────────────────────────────


class TestStage2Isolation:
    def test_soap_review_flow_does_not_touch_stage2_state(self, env):
        store, client = env.store, env.client
        _make_case(store, "C-S2-01")  # monthly 已至 reviewed（Stage 2 完成）
        before_state = store.get("C-S2-01").state
        before_hist = [h.to_state for h in store.history("C-S2-01")]
        assert before_state == "reviewed"

        _, body = _push_drafts(client, "C-S2-01", SOAP_OK)
        d = body["draft"]
        client.post(
            f"/api/soap/drafts/{d['draft_id']}/edit", json={"soap": SOAP_OK2}, headers=KEY
        )
        client.post(
            f"/api/soap/drafts/{d['draft_id']}/approve",
            json={"content_hash": compute_soap_content_hash(SOAP_OK2)},
            headers=KEY,
        )
        _, body2 = _push_drafts(client, "C-S2-01", SOAP_OK3)
        client.post(
            f"/api/soap/drafts/{body2['draft']['draft_id']}/reject",
            json={"reason_code": "RC-02", "reason": "與病歷不符"},
            headers=KEY,
        )

        assert store.get("C-S2-01").state == "reviewed"
        assert [h.to_state for h in store.history("C-S2-01")] == before_hist


# ─────────────────────────────────────────────────────────────────────────────
# A7 日誌／審計不含 SOAP 內文
# ─────────────────────────────────────────────────────────────────────────────


class TestPhiLogSafety:
    def test_logs_and_audit_exclude_soap_text(self, env, caplog, monkeypatch):
        audit_path = env.tmp_path / "access.log"
        monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", str(audit_path))
        caplog.set_level(logging.DEBUG)
        store, client = env.store, env.client
        _make_case(store, "C-PHI-01")

        _, body = _push_drafts(client, "C-PHI-01", SOAP_SENTINEL)
        d1 = body["draft"]
        client.post(
            f"/api/soap/drafts/{d1['draft_id']}/edit",
            json={"soap": SOAP_SENTINEL2},
            headers=KEY,
        )
        client.post(
            f"/api/soap/drafts/{d1['draft_id']}/approve",
            json={"content_hash": compute_soap_content_hash(SOAP_SENTINEL2)},
            headers=KEY,
        )
        _, body2 = _push_drafts(client, "C-PHI-01", SOAP_SENTINEL)
        client.post(
            f"/api/soap/drafts/{body2['draft']['draft_id']}/reject",
            json={"reason_code": "RC-01", "reason": "文件不足"},
            headers=KEY,
        )

        # 1) 應用程式日誌
        for record in caplog.records:
            msg = record.getMessage()
            assert SENTINEL_S not in msg, f"日誌洩露 S 欄：{msg[:120]}"
            assert SENTINEL_O not in msg, f"日誌洩露 O 欄：{msg[:120]}"

        # 2) 審計紀錄（JSONL）
        entries = audit_log.read_entries(str(audit_path))
        assert entries, "審核流程應產生審計紀錄"
        for entry in entries:
            blob = json.dumps(entry, ensure_ascii=False, default=str)
            assert SENTINEL_S not in blob
            assert SENTINEL_O not in blob

        # 3) 草稿紀錄上的審核欄位（原因代碼＋說明，不得含病患資料）
        for draft in (
            store.get_soap_draft(d1["draft_id"]),
            store.get_soap_draft(body2["draft"]["draft_id"]),
        ):
            for field in (draft.review_reason, draft.review_decision):
                assert field is None or (SENTINEL_S not in field and SENTINEL_O not in field)
