"""A-CR-04：佐證包須含已保存的申復草稿與審核軌跡，病史「未查詢」不得寫成「無就醫紀錄」。"""
from unittest.mock import MagicMock

import pytest

import server
from elc_audit_engine.generators.evidence_packet.builder import build_evidence_packet_docx


@pytest.fixture
def appeal_case(client):
    server._case_store.create(case_id="APP-9", kind="appeal", case_seq="9",
                              payload={"id": "APP-9", "case_seq": "9"})
    return "APP-9"


@pytest.fixture
def fake_writer(monkeypatch):
    mock_write = MagicMock(return_value=("/tmp/out/申復佐證包_APP-9.pdf", []))
    monkeypatch.setattr("elc_audit_engine.generators.evidence_packet.write_evidence_packet", mock_write)
    return mock_write


def test_packet_requires_saved_draft(client, appeal_case, fake_writer):
    resp = client.post("/api/appeal/evidence-packet/print", json={"case_id": appeal_case})
    assert resp.status_code == 409
    fake_writer.assert_not_called()


def test_packet_uses_saved_draft_and_history(client, appeal_case, fake_writer):
    body = {"case_id": appeal_case, "case_seq": "9", "order_code": "64140C",
            "deduct_amount": 300, "claimed_points": 300}
    gen = client.post("/api/appeal/generate", json=body).get_json()
    assert gen["state_transition"] == "ok"

    resp = client.post("/api/appeal/evidence-packet/print", json={"case_id": appeal_case})
    assert resp.status_code == 200
    payload = fake_writer.call_args.args[1]
    kwargs = fake_writer.call_args.kwargs
    assert payload["sections"] == gen["sections"]
    assert [e["to_state"] for e in kwargs["tracking"]["entries"]] == ["imported", "appealed"]
    assert kwargs["timeline"] is None


def _texts(doc):
    return [p.text for p in doc.paragraphs]


def test_builder_distinguishes_not_queried_from_empty():
    doc, _ = build_evidence_packet_docx({}, None, None, {}, [])
    assert "病史未查詢（本佐證包未附病歷摘要）" in _texts(doc)
    doc, _ = build_evidence_packet_docx({}, None, {"events": []}, {}, [])
    assert "查詢期間無就醫紀錄" in _texts(doc)


def test_builder_renders_transition_history():
    tracking = {"entries": [{"case_id": "A", "from_state": None, "to_state": "imported",
                             "reason": None, "actor": "his1", "created_at": "2026-09-26T10:00:00"}]}
    doc, _ = build_evidence_packet_docx({}, tracking, None, {}, [])
    assert any("→ imported" in t and "his1" in t for t in _texts(doc))
