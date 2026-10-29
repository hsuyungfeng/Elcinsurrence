"""Phase 15-04：當月申報 API（上傳匯入＋比對、批次清單、批次報告 JSON／HTML）。

全部使用 `make_api_app`（暫存 CaseStore、暫存上傳目錄、合成規則庫），不寫入正式資料庫。
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile

import pytest

from config import settings
from elc_audit_engine.monthly_audit import ARTIFACT_NAME
from elc_audit_engine.rule_repository.db import (
    SCHEMA_DRUG,
    SCHEMA_PAYMENT,
    SCHEMA_RULE_MAPPING,
)

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"

RULE_TEXT = "本項目限下列適應症使用。ICD‑10 S00.1、S00.2 等診斷需附病歷。"


def _ddata(seq: int, *, dept: str, doctor: str, orders: list[tuple[str, str, str, str]], total: str = "2000") -> str:
    pdatas = "".join(
        f"<pdata><p1>0</p1><p3>{cat}</p3><p4>{code}</p4><p10>1.0</p10>"
        f"<p11>{unit}</p11><p12>{points}</p12><p13>{i + 1}</p13></pdata>"
        for i, (code, cat, unit, points) in enumerate(orders)
    )
    return (
        f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody>"
        f"<d3>M{seq:04d}</d3><d8>{dept}</d8><d9>1120718</d9><d19>S00123A</d19>"
        f"<d30>{doctor}</d30><d39>{total}</d39><d49>測試病患</d49>{pdatas}</dbody></ddata>"
    )


def _zip_bytes(cases: list[str], *, t3: str = "11207", name: str = "TOTFA.xml") -> bytes:
    text = (
        '<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
        f"<tdata><t1>10</t1><t3>{t3}</t3></tdata>\r\n" + "\r\n".join(cases) + "\r\n</outpatient>\r\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, text.encode("big5"))
    return buf.getvalue()


def _sample_zip() -> bytes:
    return _zip_bytes([
        _ddata(1, dept="03", doctor="DOC_A", orders=[("TST1", "2", "1", "400"), ("PLAIN", "2", "1", "10")]),
        # 案 2 醫療總點數 500 ≤ 1000：報告中不納入（上傳回應的審計統計仍計入）
        _ddata(2, dept="01", doctor="DOC_B", orders=[("TSTDRUG", "4", "0.00", "0")], total="500"),
    ])


@pytest.fixture
def rules_db(tmp_path) -> str:
    path = str(tmp_path / "rules.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA_PAYMENT)
    conn.execute(SCHEMA_DRUG)
    conn.execute(SCHEMA_RULE_MAPPING)
    conn.execute("INSERT INTO payment_rules VALUES (?,?,?,?,?)", ("TST1", "測試項目", RULE_TEXT, "2023-01-01", "2910-12-31"))
    conn.execute("INSERT INTO drug_rules VALUES (?,?,?,?,?)", ("TSTDRUG", "測試藥", "限治療糖尿病使用。", "2023-01-01", "2910-12-31"))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def app(make_api_app, rules_db):
    return make_api_app(ELC_RULES_DB_PATH=rules_db)


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def _upload(client, data: bytes, filename: str = "TOTFA.zip", headers=KEY):
    return client.post(
        "/api/monthly/upload",
        data={"file": (io.BytesIO(data), filename)},
        headers=headers,
        content_type="multipart/form-data",
    )


# ── 認證 ─────────────────────────────────────────────────────────


def test_monthly_endpoints_allow_access_without_api_key_for_integration(client):
    """月申報端點支援與外部系統整合，免強制 X-API-Key。"""
    res = client.get("/api/monthly/batches")
    assert res.status_code == 200


# ── 上傳 ─────────────────────────────────────────────────────────


def test_upload_ingests_and_audits_batch(client, app):
    resp = _upload(client, _sample_zip())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["batch"] == BATCH
    assert body["ingest"] == {"created": 2, "skipped_existing": 0, "rejected": 0}
    assert body["report"]["totals"]["cases_total"] == 2
    assert body["report"]["totals"]["findings"] == 2  # TST1 + TSTDRUG（PLAIN 無旗標）
    # 上傳回應只含總計與彙總，不含案件明細（姓名）。注意：Flask 會把非 ASCII 轉成 \uXXXX，
    # 因此必須解碼後再比對，不可直接搜尋原始 bytes。
    assert "測試病患" not in json.dumps(body, ensure_ascii=False)


def test_upload_persists_per_case_artifacts(client, app):
    _upload(client, _sample_zip())
    store = app.extensions["elc"].case_store
    flagged = [r for r in store.list_by_batch(BATCH) if store.get_artifact(r.case_id, ARTIFACT_NAME)]
    assert len(flagged) == 2


def test_reupload_is_idempotent(client):
    _upload(client, _sample_zip())
    body = _upload(client, _sample_zip()).get_json()
    assert body["ingest"] == {"created": 0, "skipped_existing": 2, "rejected": 0}


def test_upload_requires_zip_extension(client):
    resp = _upload(client, _sample_zip(), filename="TOTFA.xml")
    assert resp.status_code == 400


def test_upload_without_file_field_is_400(client):
    resp = client.post("/api/monthly/upload", data={}, headers=KEY, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_corrupt_zip_gives_safe_400(client):
    resp = _upload(client, b"this is not a zip")
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "無法解析" in message
    assert "Traceback" not in message and "BadZipFile" not in message


def test_zip_without_totfa_xml_is_400(client):
    resp = _upload(client, _zip_bytes([], name="other.xml"))
    assert resp.status_code == 400


def test_oversize_upload_is_413_and_not_left_on_disk(client, app):
    big = b"0" * (10 * 1024 * 1024 + 1)
    resp = _upload(client, big)
    assert resp.status_code == 413
    raw_dir = app.config["ELC_RAW_DIR"]
    assert not os.path.isdir(raw_dir) or os.listdir(raw_dir) == []


def test_temp_zip_is_removed_after_success(client, app):
    _upload(client, _sample_zip())
    raw_dir = app.config["ELC_RAW_DIR"]
    assert os.listdir(raw_dir) == []
    # 驗證伺服機端持久留存：上傳總檔 .zip 與分析報告 .html
    upload_dir = app.config["ELC_UPLOAD_DIR"]
    assert os.path.exists(os.path.join(upload_dir, f"{BATCH}.zip"))
    out_dir = app.config.get("ELC_OUTPUT_DIR") or settings.OUTPUT_DIR
    assert os.path.exists(os.path.join(out_dir, f"report_{BATCH}.html"))


def test_missing_rules_database_still_200_but_undetermined(make_api_app, tmp_path):
    app = make_api_app(ELC_RULES_DB_PATH=str(tmp_path / "missing" / "rules.sqlite3"))
    with app.test_client() as c:
        body = _upload(c, _sample_zip()).get_json()
    assert body["report"]["totals"]["rule_status"] == {"undetermined": 2}


# ── 批次清單 ─────────────────────────────────────────────────────


def test_batches_listing(client):
    assert client.get("/api/monthly/batches", headers=KEY).get_json() == []
    _upload(client, _sample_zip())
    assert client.get("/api/monthly/batches", headers=KEY).get_json() == [{"batch": BATCH, "cases": 2}]


# ── 批次報告 ─────────────────────────────────────────────────────


def test_report_json_includes_reasoning_tree_and_soap(client):
    _upload(client, _sample_zip())
    resp = client.get(f"/api/monthly/batch/{BATCH}/report", headers=KEY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["batch"] == BATCH
    findings = [f for case in data["cases"] for f in case["findings"]]
    assert findings
    for finding in findings:
        assert finding["reasoning"]["tree"]["kind"] == "root"
        assert "soap_checklist" in finding["reasoning"]
    tst1 = next(f for f in findings if f["code"] == "TST1")
    assert tst1["rule_status"] == "restriction_present"
    assert any(item["section"] == "A" for item in tst1["reasoning"]["soap_checklist"])
    # 報告 JSON 含患者識別欄位（需求：案件明細顯示病歷號／姓名）
    assert data["cases"][0]["patient_name"] == "測試病患"
    assert data["cases"][0]["patient_id"] == "M0001"
    # 完整規則全文只在報告端點輸出
    assert tst1["rule_full_text"] == RULE_TEXT
    assert tst1["total_qty"] == "1.0"
    assert tst1["unit_price"] == "1"


def test_report_json_by_case_seq_keyed_by_case_id(client):
    _upload(client, _sample_zip())
    data = client.get(f"/api/monthly/batch/{BATCH}/report", headers=KEY).get_json()
    for case_ids in data["report"]["by_case_seq"].values():
        assert all(cid.startswith("MON-") for cid in case_ids)


def test_report_html_is_self_contained_html(client):
    _upload(client, _sample_zip())
    resp = client.get(f"/api/monthly/batch/{BATCH}/report?format=html", headers=KEY)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/html")
    html = resp.get_data(as_text=True)
    assert html.startswith("<!doctype html>")
    assert BATCH in html
    assert "https://" not in html
    assert "測試病患" in html  # 報告含姓名（PHI），僅經認證端點提供


def test_report_rejects_bad_batch_id_format(client):
    _upload(client, _sample_zip())
    assert client.get("/api/monthly/batch/MONTHLY-2023/report", headers=KEY).status_code == 400
    # 路徑成分被 Flask 解碼後不匹配路由（404）；重點是不得 200、不得穿越
    assert client.get("/api/monthly/batch/..%2Fetc/report", headers=KEY).status_code in (400, 404)


def test_report_rejects_unknown_format(client):
    _upload(client, _sample_zip())
    assert client.get(f"/api/monthly/batch/{BATCH}/report?format=pdf", headers=KEY).status_code == 400


def test_report_unknown_batch_is_404_not_empty_success(client):
    _upload(client, _sample_zip())
    resp = client.get("/api/monthly/batch/MONTHLY-209901/report", headers=KEY)
    assert resp.status_code == 404
