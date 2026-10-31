"""Phase 17-03：第二階抽審閉環整合測試（抽樣 → 佐證庫 → 預審卡片 → 健保抽審 XML）。

測試資料為合成案件（MONTHLY-202307 批次結構、合成身分證字號），以 CaseStore 暫存庫建立，
不讀取正式申報總檔、不把真實病患個資寫入版控。佐證庫與附件目錄皆指向 tmp_path。
"""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest
from PIL import Image

from config import settings
from elc_audit_engine import attachment_store

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"
VISIT_ROC = "1120718"  # 民國 112 年 07 月 18 日 → 西元 2023-07 → vault 年月 2307


def _vault_key(record_no: str, visit_roc: str) -> str:
    """與 static/index.html 的 computeVaultKey 相同規則：身分證字號-西元年後兩碼＋月份。"""
    assert re.fullmatch(r"[A-Z][0-9]{9}", record_no)
    year = int(visit_roc[:3]) + 1911
    month = int(visit_roc[3:5])
    return f"{record_no}-{year % 100:02d}{month:02d}"


def _monthly_payload(index: int) -> dict:
    """模擬申報總檔案件（欄位形狀同 case_store/monthly.py::_payload），病歷號為合成身分證格式。"""
    return {
        "batch": BATCH,
        "case_class": "3",
        "case_seq": f"{index:04d}",
        "record_no": f"A{index:09d}",
        "patient_name": f"合成病患{index}",
        "birth_date": "0650101",
        "total_points": "2000",
        "clinic": "01",
        "doctor_code": "D1234",
        "visit_date": VISIT_ROC,
        "primary_diagnosis": "E119",
        "secondary_diagnoses": ["I10"],
        "orders": [
            {"p1": "01", "p2": "A", "p3": "2", "p4": f"14050{j}", "p5": "1", "p12": str(points), "p13": str(j + 1)}
            for j, points in enumerate([index * 10 + 1, index * 7 + 3, 5])
        ],
        "warnings": [],
    }


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="green").save(buf, format="JPEG")
    return buf.getvalue()


def _evidence_zip(tag: str) -> tuple[bytes, dict[str, bytes]]:
    """合成佐證包：相片、錄音、報告、病歷各一，置於子目錄中以驗證攤平與自動分類。"""
    files = {
        "相片/術前.jpg": _jpeg_bytes(),
        "錄音/門診對話.mp3": b"ID3-synthetic-" + tag.encode(),
        "報告/HbA1c檢驗.pdf": b"%PDF-1.4\n% synthetic " + tag.encode() + b"\n%%EOF",
        "病歷/soap.json": json.dumps({"synthetic": True, "tag": tag}, ensure_ascii=False).encode("utf-8"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue(), {name.rsplit("/", 1)[-1]: data for name, data in files.items()}


@pytest.fixture
def api(make_api_app, tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_store.settings, "ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))  # 佐證庫根目錄 = data/evidence_vault
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
    """Big5 位元組 → 文字 → 解析（expat 不支援 Big5，需先解碼並移除宣告）。"""
    text = body.decode("big5")
    assert text.startswith('<?xml version="1.0" encoding="Big5"?>')
    return ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", text).strip())


def _sample_one_case(client) -> dict:
    """以批次抽樣取得一筆抽樣案件（20 隨機＋10 立意＝全部 30 筆合成案件）。"""
    res = client.post(
        "/api/sampling/sample-batch",
        json={"batch": BATCH, "random_count": 20, "intentional_count": 10, "seed": 7},
        headers=KEY,
    )
    assert res.status_code == 200, res.get_json()
    return res.get_json()["cases"][0]


def test_stage2_closed_loop_with_vault_evidence(client, api):
    # 1. 從申報批次抽出一筆抽審案件，並由其病歷號與就醫日推導 vault_key
    case = _sample_one_case(client)
    case_id = case["id"]
    vault_key = _vault_key(case["record_no"], VISIT_ROC)
    assert vault_key == case["record_no"] + "-2307"

    # 2. 上傳該病患佐證包（ZIP，含子目錄）
    zip_bytes, expected = _evidence_zip("main")
    res = client.post(
        f"/api/vault/{vault_key}/upload",
        data={"file": (io.BytesIO(zip_bytes), "MONTHLY-202307-evidence.zip")},
        headers=KEY,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_json()
    saved = {(f["category"], f["filename"]) for f in res.get_json()["saved"]}
    assert saved == {
        ("images", "術前.jpg"),
        ("audio", "門診對話.mp3"),
        ("reports", "HbA1c檢驗.pdf"),
        ("records", "soap.json"),
    }

    # 3. 檢查 /api/vault/<vault_key> 各分類計數與清單
    res = client.get(f"/api/vault/{vault_key}", headers=KEY)
    assert res.status_code == 200
    listing = res.get_json()
    assert listing["vault_key"] == vault_key
    assert listing["total"] == 4
    for category in ("images", "audio", "reports", "records"):
        assert listing["categories"][category]["count"] == 1, category
    assert listing["categories"]["audio"]["files"][0]["url"] == (
        f"/api/vault/{vault_key}/files/audio/門診對話.mp3"
    )

    # 4. 逐一取回檔案位元組，須與原始佐證完全一致
    for category, filename in (
        ("images", "術前.jpg"),
        ("audio", "門診對話.mp3"),
        ("reports", "HbA1c檢驗.pdf"),
        ("records", "soap.json"),
    ):
        res = client.get(f"/api/vault/{vault_key}/files/{category}/{filename}", headers=KEY)
        assert res.status_code == 200, filename
        assert res.data == expected[filename], filename

    # 5. 另一位病患的佐證庫互不干擾
    other_key = _vault_key("B123456789", VISIT_ROC)
    res = client.get(f"/api/vault/{other_key}", headers=KEY)
    assert res.get_json()["total"] == 0

    # 6. 預審卡片與健保抽審 XML 可正常產出（既有閉環不被破壞）
    res = client.get(f"/api/sampling/cases/{case_id}/preview-html", headers=KEY)
    assert res.status_code == 200
    assert res.mimetype == "text/html"
    assert case["order_code"] in res.get_data(as_text=True)

    res = client.get(f"/api/sampling/cases/{case_id}/export-xml", headers=KEY)
    assert res.status_code == 200
    assert res.mimetype == "application/xml"
    root = _decode_export(res.data)
    assert root.tag == "outpatient"
    assert root.find("tdata/t3").text == "11207"
    assert root.find("ddata/dbody/d3").text == case["record_no"]
    # 佐證檔案內容不進健保上傳檔（規格外欄位）
    exported_text = res.data.decode("big5")
    assert "synthetic" not in exported_text
    assert "HbA1c檢驗" not in exported_text


def test_preview_card_lists_vault_evidence(client, api):
    case = _sample_one_case(client)
    vault_key = _vault_key(case["record_no"], VISIT_ROC)

    # 尚未上傳佐證：卡片不出現佐證區塊
    before = client.get(f"/api/sampling/cases/{case['id']}/preview-html", headers=KEY).get_data(as_text=True)
    assert vault_key not in before

    zip_bytes, _ = _evidence_zip("preview")
    client.post(
        f"/api/vault/{vault_key}/upload",
        data={"file": (io.BytesIO(zip_bytes), "evidence.zip")},
        headers=KEY,
        content_type="multipart/form-data",
    )
    html = client.get(f"/api/sampling/cases/{case['id']}/preview-html", headers=KEY).get_data(as_text=True)
    assert f"佐證庫（{vault_key}）" in html
    for filename in ("術前.jpg", "門診對話.mp3", "HbA1c檢驗.pdf", "soap.json"):
        assert filename in html, filename
    # 預覽只列清單，不嵌入佐證內容
    assert "synthetic" not in html


def test_vault_key_for_case_matches_frontend_rule():
    """後端 vault_key_for_case 與前端 computeVaultKey 規則一致（ROC 與 ISO 日期皆可）。"""
    from elc_audit_engine.evidence_vault import vault_key_for_case

    assert vault_key_for_case("A123625499", "1120718") == "A123625499-2307"
    assert vault_key_for_case("a123625499", "2026-05-10") == "A123625499-2605"
    assert vault_key_for_case("A12362549", "1120718") is None  # 不足 10 碼
    assert vault_key_for_case("M220518024", "2026-13-01") is None  # 月份不合法
    assert vault_key_for_case("A123625499", "") is None


def test_vault_path_traversal_blocked_end_to_end(client, api):
    case = _sample_one_case(client)
    vault_key = _vault_key(case["record_no"], VISIT_ROC)
    zip_bytes, _ = _evidence_zip("traversal")
    client.post(
        f"/api/vault/{vault_key}/upload",
        data={"file": (io.BytesIO(zip_bytes), "evidence.zip")},
        headers=KEY,
        content_type="multipart/form-data",
    )
    for path in (
        f"/api/vault/{vault_key}/files/images/..%2F..%2Fsecret.txt",
        f"/api/vault/{vault_key}/files/..%2Fimages/術前.jpg",
    ):
        res = client.get(path, headers=KEY)
        assert res.status_code in (400, 404), path

    # 上傳端點：非法 vault_key（路徑穿越字串）須被拒絕
    res = client.post(
        "/api/vault/..%2Fetc-2307/upload",
        data={"file": (io.BytesIO(b"x"), "a.txt")},
        headers=KEY,
        content_type="multipart/form-data",
    )
    assert res.status_code in (400, 404)
