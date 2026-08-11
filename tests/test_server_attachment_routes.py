import io
import json
import pytest
from config import settings

def test_attachment_api_endpoints(client, tmp_path, monkeypatch):
    """Test attachment upload, list, delete, and generate endpoints in server.py."""
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))

    # 1. Upload valid file
    png_bytes = b"\x89PNG\r\n\x1a\nfake_image_content"
    data = {
        "case_seq": "case303",
        "order_seq": "1",
        "file": (io.BytesIO(png_bytes), "sono.png"),
    }
    resp = client.post("/api/appeal/attachments/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    res_data = resp.get_json()
    assert res_data["status"] == "success"
    assert res_data["attachment"]["case_seq"] == "case303"

    # 2. List attachments
    resp_list = client.get("/api/appeal/attachments/case303")
    assert resp_list.status_code == 200
    list_data = resp_list.get_json()
    assert len(list_data["attachments"]) == 1

    # 3. Delete attachment
    att_id = list_data["attachments"][0]["id"]
    resp_del = client.delete(f"/api/appeal/attachments/case303/{att_id}")
    assert resp_del.status_code == 200
    assert resp_del.get_json()["status"] == "success"
