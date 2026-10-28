"""規則庫管理 API：/api/rules/upload、/api/rules/sync。

使用 make_api_app（暫存規則目錄與暫存規則庫），不改動正式 data/rules 或 rules.sqlite3。
"""

from __future__ import annotations

import io
import os

import pytest

KEY = {"X-API-Key": "valid-key-123"}
DRUG_NAME = "藥品項查詢項目檔251016 AI  摘要.csv"
PAYMENT_NAME = "醫療服務給付項目_測試260801.csv"
DRUG_HEADER = "藥品代號,藥品中文名稱,給付規定,有效起日,有效迄日,支付價,AI-note"
PAYMENT_HEADER = "診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日"


def _csv(lines: list[str]) -> bytes:
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


@pytest.fixture
def rules_dir(tmp_path):
    path = tmp_path / "rules"
    path.mkdir()
    return path


@pytest.fixture
def app(make_api_app, tmp_path, rules_dir):
    return make_api_app(
        ELC_RULES_DIR=str(rules_dir),
        ELC_RULES_DB_PATH=str(tmp_path / "rules.sqlite3"),
    )


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def _upload(client, filename: str, data: bytes, headers=KEY):
    return client.post(
        "/api/rules/upload",
        data={"file": (io.BytesIO(data), filename)},
        headers=headers,
        content_type="multipart/form-data",
    )


# ── 認證（不得免認證） ────────────────────────────────────────────


def test_rules_upload_requires_api_key(client):
    assert _upload(client, DRUG_NAME, _csv([DRUG_HEADER]), headers={}).status_code == 401


def test_rules_sync_requires_api_key(client):
    assert client.post("/api/rules/sync").status_code == 401


def test_rules_endpoints_not_in_auth_exempt_list():
    from elc_audit_engine.api.security import AUTH_EXEMPT_ENDPOINTS

    assert not any(name.startswith("rules.") for name in AUTH_EXEMPT_ENDPOINTS)


# ── 上傳 ─────────────────────────────────────────────────────────


def test_upload_saves_valid_drug_csv(client, rules_dir):
    resp = _upload(client, DRUG_NAME, _csv([DRUG_HEADER, "TST1,測試,限使用,1091201,9991231,1.00,"]))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"status": "success", "saved_as": DRUG_NAME, "kind": "drug", "replaced": False}
    assert (rules_dir / DRUG_NAME).exists()


def test_upload_reports_replacement_on_second_upload(client):
    data = _csv([PAYMENT_HEADER, "T1,項目,規定,20200101,29101231"])
    _upload(client, PAYMENT_NAME, data)
    body = _upload(client, PAYMENT_NAME, data).get_json()
    assert body["kind"] == "payment" and body["replaced"] is True


def test_upload_rejects_unknown_filename(client, rules_dir):
    resp = _upload(client, "notes.csv", _csv([DRUG_HEADER]))
    assert resp.status_code == 400
    assert list(rules_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["../藥品項查詢項目檔x.csv", "..\\藥品項查詢項目檔x.csv"])
def test_upload_rejects_path_traversal_names(client, rules_dir, tmp_path, name):
    resp = _upload(client, name, _csv([DRUG_HEADER]))
    assert resp.status_code == 400
    assert not (tmp_path / "藥品項查詢項目檔x.csv").exists()


def test_upload_with_bad_header_is_rejected_and_leaves_no_file(client, rules_dir):
    resp = _upload(client, DRUG_NAME, _csv(["藥品代號,藥品中文名稱"]))
    assert resp.status_code == 400
    assert "缺少必要欄位" in resp.get_json()["message"]
    assert list(rules_dir.iterdir()) == []  # 不留下暫存或半成品


def test_upload_requires_file_field(client):
    resp = client.post("/api/rules/upload", data={}, headers=KEY, content_type="multipart/form-data")
    assert resp.status_code == 400


# ── 同步 ─────────────────────────────────────────────────────────


def test_sync_endpoint_runs_pipeline_and_returns_counts(client, rules_dir, app):
    _upload(client, DRUG_NAME, _csv([DRUG_HEADER, "TST1,測試藥,限使用,1091201,9991231,2.50,AI"]))
    _upload(client, PAYMENT_NAME, _csv([PAYMENT_HEADER, "P1,項目,規定,20200101,29101231"]))

    resp = client.post("/api/rules/sync", headers=KEY)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["drug_rows"] == 1 and body["payment_rows"] == 1
    assert body["mode"] == "upsert"
    assert body["drug_file"] == DRUG_NAME

    from elc_audit_engine.rule_repository import get_rule

    rule = get_rule("TST1", db_path=app.config["ELC_RULES_DB_PATH"])
    assert rule.found and rule.unit_price == "2.50"


def test_sync_without_uploaded_sources_returns_safe_400(client):
    resp = client.post("/api/rules/sync", headers=KEY)
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "找不到規則來源檔" in message
    assert str(os.getcwd()) not in message  # 不洩漏內部路徑
