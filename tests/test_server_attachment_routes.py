import io

import pytest
from config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server
    from elc_audit_engine.case_store import CaseStore

    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path / "att"))
    store = CaseStore(db_path=str(tmp_path / "cases.sqlite3"))
    monkeypatch.setattr(server, "_case_store", store)
    store.create(case_id="APP-aaa", kind="appeal", case_seq="303", payload={"id": "APP-aaa"})
    monkeypatch.setitem(server.app.config, "ELC_API_KEYS", {"valid-key-1234567": "his1"})
    c = server.app.test_client()
    c.environ_base["HTTP_X_API_KEY"] = "valid-key-1234567"
    return c


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
    return buf.getvalue()


def test_attachment_api_endpoints(client):
    """上傳（以 case_id）→ 列出 → 刪除；附件以 case_id 為鍵（A-CR-03）。"""
    data = {"case_id": "APP-aaa", "order_seq": "1", "file": (io.BytesIO(_png()), "sono.png")}
    resp = client.post("/api/appeal/attachments/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    att = resp.get_json()["attachment"]
    assert att["case_id"] == "APP-aaa"
    assert att["case_seq"] == "303"

    resp_list = client.get("/api/appeal/attachments/APP-aaa")
    assert resp_list.status_code == 200
    list_data = resp_list.get_json()
    assert len(list_data["attachments"]) == 1

    att_id = list_data["attachments"][0]["id"]
    resp_del = client.delete(f"/api/appeal/attachments/APP-aaa/{att_id}")
    assert resp_del.status_code == 200
    assert resp_del.get_json()["status"] == "success"
