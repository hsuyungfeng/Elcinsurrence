"""A-CR-03：附件不得以流水號跨病患混用。"""
import io

import pytest

import server


@pytest.fixture
def store(client, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path / "att"))
    s = server._case_store
    # 不同費用年月、同一流水號 1 的兩位病患
    s.create(case_id="APP-jan", kind="appeal", case_seq="1", payload={"id": "APP-jan"})
    s.create(case_id="APP-feb", kind="appeal", case_seq="1", payload={"id": "APP-feb"})
    s.create(case_id="APP-uniq", kind="appeal", case_seq="77", payload={"id": "APP-uniq"})
    return s


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, **form):
    form["file"] = (io.BytesIO(_png()), "x.png")
    return client.post("/api/appeal/attachments/upload", data=form, content_type="multipart/form-data")


def test_attachments_isolated_per_case_id(client, store):
    assert _upload(client, case_id="APP-jan").status_code == 200
    assert len(client.get("/api/appeal/attachments/APP-jan").get_json()["attachments"]) == 1
    assert client.get("/api/appeal/attachments/APP-feb").get_json()["attachments"] == []


def test_ambiguous_case_seq_is_rejected(client, store):
    resp = _upload(client, case_seq="1")
    assert resp.status_code == 409


def test_unique_case_seq_still_accepted_for_compat(client, store):
    resp = _upload(client, case_seq="77")
    assert resp.status_code == 200
    assert resp.get_json()["attachment"]["case_id"] == "APP-uniq"


def test_unknown_case_is_404_and_unsafe_id_is_400(client, store):
    assert _upload(client, case_id="APP-none").status_code == 404
    assert _upload(client, case_id="../etc").status_code == 400


def test_appeal_p7_uses_case_id_not_case_seq(client, store):
    _upload(client, case_id="APP-jan")
    body = {"case_seq": "1", "order_code": "64140C", "case_id": "APP-feb"}
    resp = client.post("/api/appeal/generate", json=body)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["p7_attachment"] == "N"


def test_has_attachment_must_be_bool(client, store):
    body = {"case_seq": "1", "order_code": "64140C", "has_attachment": "false"}
    assert client.post("/api/appeal/generate", json=body).status_code == 400
