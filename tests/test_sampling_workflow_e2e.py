"""Phase 16-03 端到端：申報批次抽樣 → 多源證據 → 影像附件 → 預覽 HTML → 健保抽審 XML 導出。

測試資料為合成案件（MON-…、合成病患），以 CaseStore 暫存庫建立，不讀取正式資料。
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from elc_audit_engine import attachment_store
from elc_audit_engine.api.routes import sampling as sampling_routes

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(buf, format="PNG")
    return buf.getvalue()


def _monthly_payload(index: int) -> dict:
    """模擬 TOTFA 解析後的申報總檔案件（欄位形狀同 case_store/monthly.py::_payload）。"""
    return {
        "batch": BATCH,
        "case_class": "3",
        "case_seq": f"{index:04d}",
        "record_no": f"M{index:06d}",
        "patient_name": f"合成病患{index}",
        "birth_date": "0650101",
        "total_points": "2000",
        "clinic": "01",
        "doctor_code": "D1234",
        "visit_date": "1120718",
        "primary_diagnosis": "E119",
        "secondary_diagnoses": ["I10"],
        "orders": [
            {"p1": "01", "p2": "A", "p3": "2", "p4": f"14050{j}", "p5": "1", "p12": str(points), "p13": str(j + 1)}
            for j, points in enumerate([index * 10 + 1, index * 7 + 3, 5])
        ],
        "warnings": [],
    }


@pytest.fixture
def api(make_api_app, tmp_path, monkeypatch):
    # 附件儲存位置為全域設定（非 CaseStore），須指向暫存目錄，避免寫入正式資料
    monkeypatch.setattr(attachment_store.settings, "ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    app = make_api_app()
    store = app.extensions["elc"].case_store
    for index in range(1, 31):
        store.create(case_id=f"MON-{index:03d}", kind="monthly", payload=_monthly_payload(index))
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def _decode_export(body: bytes) -> ET.Element:
    """Big5 位元組 → 文字 → 解析。stdlib expat 不支援 Big5，需先解碼並移除宣告。"""
    text = body.decode("big5")
    assert text.startswith('<?xml version="1.0" encoding="Big5"?>')
    return ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", text).strip())


def test_full_closed_loop(client, api):
    # 1. 申報批次抽樣：20 隨機＋10 立意，入庫為 kind='sampling'
    res = client.post(
        "/api/sampling/sample-batch",
        json={"batch": BATCH, "random_count": 20, "intentional_count": 10, "seed": 42},
        headers=KEY,
    )
    assert res.status_code == 200
    sampled = res.get_json()
    assert (sampled["sampled"], sampled["random"], sampled["intentional"]) == (30, 20, 10)
    assert sampled["case_store_persisted"] == 30

    case_id = sampled["cases"][0]["id"]
    store = api.extensions["elc"].case_store
    stored = store.get(case_id).payload
    # 來源申報案件原始欄位已透傳（XML 必要欄位的唯一來源）
    assert stored["monthly_source"]["case_class"] == "3"
    assert len(stored["monthly_source"]["orders"]) == 3

    # 2. 寫入多源證據：檢驗數據與健保雲端病歷
    labs = [{"name": "HbA1c", "value": "8.5", "unit": "%", "date": "2026-07-10"}]
    cloud = "外院跨院病歷：第二型糖尿病，規律使用 Metformin。"
    res = client.put(
        f"/api/sampling/cases/{case_id}/evidence",
        json={"lab_results": labs, "cloud_records": cloud},
        headers=KEY,
    )
    assert res.status_code == 200

    # 3. 上傳影像佐證（與既有附件端點共用，抽樣案件以 case_id 對應）
    res = client.post(
        "/api/appeal/attachments/upload",
        data={"case_id": case_id, "file": (io.BytesIO(_png_bytes()), "report.png")},
        headers=KEY,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["attachment"]["mime_type"] == "image/png"

    res = client.get(f"/api/appeal/attachments/{case_id}", headers=KEY)
    # 儲存時檔名會改為內容雜湊形式，只驗證數量與副檔名
    names = [a["filename"] for a in res.get_json()["attachments"]]
    assert len(names) == 1 and names[0].endswith(".png")

    # 4. 視覺化預審卡片：含檢驗與雲端病歷
    res = client.get(f"/api/sampling/cases/{case_id}/preview-html", headers=KEY)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "HbA1c" in html
    assert "Metformin" in html

    # 5. 導出健保抽審 XML（Big5 附件）
    res = client.get(f"/api/sampling/cases/{case_id}/export-xml", headers=KEY)
    assert res.status_code == 200
    assert res.mimetype == "application/xml"
    assert res.headers["Content-Disposition"].startswith("attachment; filename=")
    root = _decode_export(res.data)
    assert root.tag == "outpatient"
    assert root.find("tdata/t3").text == "11207"  # 2023-07 → 民國 112 年 07 月
    assert root.find("ddata/dhead/d1").text == "3"
    assert root.find("ddata/dhead/d2").text == stored["case_seq"]
    assert root.find("ddata/dbody/d3").text == stored["record_no"]
    assert len(root.findall("ddata/dbody/pdata")) == 3
    # 證據不進健保上傳檔（規格外欄位），只在預覽呈現
    exported_text = res.data.decode("big5")
    assert "HbA1c" not in exported_text
    assert "Metformin" not in exported_text


def test_export_rejects_sampling_case_without_monthly_source(client, api):
    """非由批次抽樣產生（缺來源申報總檔）的案件不得導出殘缺 XML。"""
    store = api.extensions["elc"].case_store
    store.create(
        case_id="SAMP-manual01",
        kind="sampling",
        payload={"batch": BATCH, "case_seq": "9", "record_no": "M999999", "orders": []},
        actor="test",
    )
    res = client.get("/api/sampling/cases/SAMP-manual01/export-xml", headers=KEY)
    assert res.status_code == 422
    assert "申報總檔來源" in res.get_json()["message"]


def test_export_is_404_for_unknown_or_non_sampling_case(client, api):
    res = client.get("/api/sampling/cases/MON-001/export-xml", headers=KEY)
    assert res.status_code == 404


def test_audit_llm_receives_evidence_context(client, api, monkeypatch):
    """LLM 智慧審核應參考檢驗數據與雲端病歷（不只 SOAP）。"""
    captured: dict = {}

    def _fake_advice(**kwargs):
        captured.update(kwargs)
        return {"status": "error"}

    monkeypatch.setattr(sampling_routes, "generate_soap_advice", _fake_advice)

    res = client.post(
        "/api/sampling/sample-batch",
        json={"batch": BATCH, "random_count": 1, "intentional_count": 0, "seed": 1},
        headers=KEY,
    )
    case_id = res.get_json()["cases"][0]["id"]
    client.put(
        f"/api/sampling/cases/{case_id}/evidence",
        json={
            "lab_results": [{"name": "HbA1c", "value": "8.5", "unit": "%"}],
            "cloud_records": "外院跨院病歷：第二型糖尿病。",
        },
        headers=KEY,
    )
    res = client.post(
        "/api/sampling/audit",
        json={"case_id": case_id, "order_code": "14050B", "soap_text": "S: DM\nO: HbA1c 8.5\nA: E11.9\nP: 追蹤"},
        headers=KEY,
    )
    assert res.status_code == 200
    history = captured["patient_history"]
    assert "HbA1c: 8.5 %" in history
    assert "第二型糖尿病" in history
