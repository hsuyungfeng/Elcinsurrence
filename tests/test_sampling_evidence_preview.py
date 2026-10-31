"""Plan 16-02 單元與整合測試：多源證據（檢驗、雲端病歷、影像附件）與 HTML 預覽卡片。"""

from __future__ import annotations

import io
import pytest
from PIL import Image

from elc_audit_engine import attachment_store
from elc_audit_engine.sampling_preview import split_soap

KEY = {"X-API-Key": "valid-key-123"}


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api(make_api_app, tmp_path, monkeypatch):
    # 附件儲存位置為全域設定，指向暫存目錄，避免測試殘留寫入 data/attachments
    monkeypatch.setattr(attachment_store.settings, "ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    app = make_api_app()
    store = app.extensions["elc"].case_store
    payload = {
        "case_id": "SAMP-test1602",
        "case_seq": "99",
        "record_no": "M9999",
        "patient_name": "張大千",
        "order_code": "14050B",
        "order_name": "糖化血色素檢驗 HbA1c",
        "visit_date": "20260715",
        "clinic": "01",
        "soap": "S: 糖尿病追蹤\nO: HbA1c 8.2\nA: E11.9\nP: 調整藥物",
    }
    store.create(case_id="SAMP-test1602", kind="sampling", payload=payload, actor="test")
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def test_split_soap():
    text = "S: Patient reports thirst\nO: Fasting glucose 200\nA: DM poor control\nP: HbA1c test"
    res = split_soap(text)
    assert res["s"] == "Patient reports thirst"
    assert res["o"] == "Fasting glucose 200"
    assert res["a"] == "DM poor control"
    assert res["p"] == "HbA1c test"


def test_split_soap_empty():
    assert split_soap("") == {}
    assert split_soap(None) == {}


def test_update_sampling_evidence_api(client, api):
    """PUT /api/sampling/cases/<case_id>/evidence 正常儲存檢驗與雲端紀錄。"""
    payload = {
        "lab_results": [
            {"name": "HbA1c", "value": "8.5", "unit": "%", "date": "2026-07-10"},
            {"name": "Fasting Glucose", "value": "190", "unit": "mg/dL"},
        ],
        "cloud_records": "外院跨院病歷：曾於榮總診斷第二型糖尿病，規律用藥 Metformin。",
    }
    resp = client.put(
        "/api/sampling/cases/SAMP-test1602/evidence",
        headers=KEY,
        json=payload,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert len(data["lab_results"]) == 2
    assert "榮總" in data["cloud_records"]

    # 查證 DB 確實持久化
    store = api.extensions["elc"].case_store
    updated = store.get("SAMP-test1602")
    assert updated.payload["lab_results"][0]["name"] == "HbA1c"
    assert updated.payload["cloud_records"] == payload["cloud_records"]


def test_update_sampling_evidence_validation(client):
    """驗證輸入格式檢查。"""
    # lab_results 不是 list
    resp = client.put(
        "/api/sampling/cases/SAMP-test1602/evidence",
        headers=KEY,
        json={"lab_results": "invalid"},
    )
    assert resp.status_code == 400

    # lab_results 缺少必要欄位
    resp = client.put(
        "/api/sampling/cases/SAMP-test1602/evidence",
        headers=KEY,
        json={"lab_results": [{"unit": "%"}]},
    )
    assert resp.status_code == 400

    # 404 案件
    resp = client.put(
        "/api/sampling/cases/SAMP-notfound/evidence",
        headers=KEY,
        json={"lab_results": []},
    )
    assert resp.status_code == 404


def test_sampling_attachment_upload_and_preview_html(client):
    """測試抽樣案件能透過 attachments upload 上傳影像並呈現在 preview-html。"""
    # 1. 上傳測試圖片附件（透過既有 /api/appeal/attachments/upload 端點，已支援 sampling case_id）
    data = {
        "case_id": "SAMP-test1602",
        "file": (io.BytesIO(_png_bytes()), "wound_check.png"),
        "report_text": "足部傷口紅腫檢查",
    }
    resp = client.post(
        "/api/appeal/attachments/upload",
        headers=KEY,
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    res_json = resp.get_json()
    assert res_json["status"] == "success"
    assert res_json["attachment"]["filename"].endswith(".png")

    # 2. 寫入多源證據
    client.put(
        "/api/sampling/cases/SAMP-test1602/evidence",
        headers=KEY,
        json={
            "lab_results": [{"name": "HbA1c", "value": "8.5", "unit": "%"}],
            "cloud_records": "健保跨院病歷正常",
        },
    )

    # 3. GET preview-html
    html_resp = client.get(
        "/api/sampling/cases/SAMP-test1602/preview-html",
        headers=KEY,
    )
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.content_type
    text = html_resp.get_data(as_text=True)

    # 驗證 HTML 各區塊內容存在且正確轉義
    assert "張大千" in text
    assert "14050B" in text
    assert "HbA1c" in text
    assert "8.5 %" in text
    assert "健保跨院病歷正常" in text
    assert ".png" in text
