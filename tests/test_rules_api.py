"""規則庫管理 API：/api/rules/upload、/api/rules/sync。

使用 make_api_app（暫存規則目錄與暫存規則庫），不改動正式 data/rules 或 rules.sqlite3。
"""

from __future__ import annotations

import io
import os

import pytest


# Phase 32-A：院內信任模式取代 API key。原本「未帶金鑰→401」的測試改為
# 「來源位址不在信任網段→403」——這才是現在唯一的存取控制。
UNTRUSTED_ENV = {"REMOTE_ADDR": "192.168.99.99"}

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


def test_rules_sync_rejects_untrusted_source(client):
    assert client.post("/api/rules/sync", environ_base=UNTRUSTED_ENV).status_code == 403


def test_rules_endpoints_not_audit_exempt():
    """規則庫變更必須留審計軌跡（認證可省、軌跡不可省）。"""
    from elc_audit_engine.api.security import AUDIT_EXEMPT_ENDPOINTS

    assert not any(name.startswith("rules.") for name in AUDIT_EXEMPT_ENDPOINTS)


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


def test_rules_status_endpoint_and_no_path_leak(client, rules_dir):
    """Phase 36：GET /api/rules/status 回報 DB 列數與最新檔名（僅 basename），院外來源 403。"""
    assert client.get("/api/rules/status", environ_base=UNTRUSTED_ENV).status_code == 403

    _upload(client, DRUG_NAME, _csv([DRUG_HEADER, "TST1,測試藥,限使用,1091201,9991231,2.50,AI"]))
    _upload(client, PAYMENT_NAME, _csv([PAYMENT_HEADER, "P1,項目,規定,20200101,29101231"]))
    client.post("/api/rules/sync", headers=KEY)

    resp = client.get("/api/rules/status", headers=KEY)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["db"]["payment_rows"] == 1
    assert body["db"]["drug_rows"] == 1
    assert body["sources"]["payment_file"] == PAYMENT_NAME
    assert body["sources"]["drug_file"] == DRUG_NAME
    assert str(rules_dir) not in resp.get_data(as_text=True)


def test_sync_replace_validation_conflict_lock_and_sidecars(client, rules_dir, app):
    """Phase 36：非法 replace 回 422；殘留 .lock 與 -journal/-wal 回 409 且絕不自動刪除；replace=True 正常替換與輪替備份。"""
    _upload(client, DRUG_NAME, _csv([DRUG_HEADER, "TST1,測試藥,限使用,1091201,9991231,2.50,AI"]))
    _upload(client, PAYMENT_NAME, _csv([PAYMENT_HEADER, "P1,項目,規定,20200101,29101231"]))

    # 1. 非布林 replace -> 422（不建立 DB）
    r_bad = client.post("/api/rules/sync", headers=KEY, json={"replace": "yes"})
    assert r_bad.status_code == 422
    assert not os.path.exists(app.config["ELC_RULES_DB_PATH"])

    # 2. 預放殘留 .lock -> 409、提示手動移除且不自動刪鎖檔
    db_path = app.config["ELC_RULES_DB_PATH"]
    lock_path = db_path + ".lock"
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write("pid=99999\ncreated_at=2026-11-23T00:00:00Z\n")
    r_lock = client.post("/api/rules/sync", headers=KEY, json={"replace": False})
    assert r_lock.status_code == 409
    assert "手動移除" in r_lock.get_json()["message"]
    assert os.path.exists(lock_path)  # 絕不自動刪除鎖檔
    os.remove(lock_path)

    # 3. 首次同步成功（附 audit 摘要）
    r_ok = client.post("/api/rules/sync", headers=KEY, json={"replace": False})
    assert r_ok.status_code == 200
    b_ok = r_ok.get_json()
    assert b_ok["audit"]["payment"]["total_rows"] == 1
    assert b_ok["audit"]["drug"]["total_rows"] == 1

    # 4. 存在 -journal 側車檔 -> 409 且不自動刪除
    journal_path = db_path + "-journal"
    with open(journal_path, "wb") as f:
        f.write(b"journal")
    r_j = client.post(
        "/api/rules/sync",
        headers=KEY,
        json={"replace": True, "confirm": "REPLACE_RULES"},
    )
    assert r_j.status_code == 409
    assert os.path.exists(journal_path)
    os.remove(journal_path)

    # 5. 上傳新版移除 P1、新增 P2，以 replace=True + confirm 整表替換並產生備份
    _upload(client, "醫療服務給付項目_測試261119.csv", _csv([PAYMENT_HEADER, "P2,新項目,新規定,20260101,29101231"]))
    r_rep = client.post(
        "/api/rules/sync",
        headers=KEY,
        json={"replace": True, "confirm": "REPLACE_RULES"},
    )
    assert r_rep.status_code == 200
    b_rep = r_rep.get_json()
    assert b_rep["mode"] == "replace"
    assert b_rep["backup_file"] and b_rep["backup_file"].startswith("rules.sqlite3.bak.")
    assert b_rep["payment_stale_not_in_source"] == 0

    from elc_audit_engine.rule_repository import get_rule

    assert not get_rule("P1", db_path=db_path).found
    assert get_rule("P2", db_path=db_path).found


def test_sync_replace_requires_confirm_before_sidecars_and_db_write(client, rules_dir, app):
    """Phase 37：replace=True 缺少或錯誤 confirm 一律先回 422（即使存在 -journal 側車檔），且不改動 DB。"""
    from elc_audit_engine.rule_repository import get_rule

    _upload(client, DRUG_NAME, _csv([DRUG_HEADER, "TST1,測試藥,限使用,1091201,9991231,2.50,AI"]))
    _upload(client, PAYMENT_NAME, _csv([PAYMENT_HEADER, "P1,舊項目,舊規定,20200101,29101231"]))
    assert client.post("/api/rules/sync", headers=KEY, json={"replace": False}).status_code == 200

    _upload(client, "醫療服務給付項目_測試261119.csv", _csv([PAYMENT_HEADER, "P2,新項目,新規定,20260101,29101231"]))
    db_path = app.config["ELC_RULES_DB_PATH"]

    for payload in (
        {"replace": True},
        {"replace": True, "confirm": ""},
        {"replace": True, "confirm": "replace_rules"},
        {"replace": True, "confirm": True},
    ):
        resp = client.post("/api/rules/sync", headers=KEY, json=payload)
        assert resp.status_code == 422
        assert "REPLACE_RULES" in resp.get_json()["message"]

    # 即使存在 -journal 側車檔，缺 confirm 仍應在鎖檔／側車檢查之前優先回 422 而非 409
    journal_path = db_path + "-journal"
    with open(journal_path, "wb") as f:
        f.write(b"journal")
    try:
        resp_j = client.post("/api/rules/sync", headers=KEY, json={"replace": True})
        assert resp_j.status_code == 422
        assert os.path.exists(journal_path)
    finally:
        os.remove(journal_path)

    assert get_rule("P1", db_path=db_path).found
    assert not get_rule("P2", db_path=db_path).found


def test_sync_staging_failure_preserves_original_db_and_backup_rotation(tmp_path):
    """Phase 36：雙表同步中途失敗不損原 DB；連續備份最多保留 5 份；pick_latest 正確處理 6 碼邊界。"""
    import glob as _glob
    from elc_audit_engine.rule_repository import get_rule
    from elc_audit_engine.rule_repository.loaders._csv_table import RuleCsvFormatError
    from elc_audit_engine.rule_repository.scripts.sync_latest_rules import pick_latest, sync_latest_rules

    rdir = tmp_path / "rules"
    rdir.mkdir()
    db_path = str(tmp_path / "rules.sqlite3")

    # 6 碼獨立版本號邊界：8 碼 20261119 不得被誤當成 202611 壓過 261119
    (rdir / "醫療服務給付項目_20261119_bad8.csv").write_bytes(_csv([PAYMENT_HEADER, "OLD,舊,舊,20200101,29101231"]))
    (rdir / "醫療服務給付項目支付標準261119已填支付規定.csv").write_bytes(
        _csv([PAYMENT_HEADER, "P1,正常,規定,20200101,29101231"])
    )
    assert os.path.basename(pick_latest(str(rdir), "醫療服務給付項目*.csv")) == "醫療服務給付項目支付標準261119已填支付規定.csv"
    (rdir / "醫療服務給付項目_20261119_bad8.csv").unlink()

    (rdir / DRUG_NAME).write_bytes(_csv([DRUG_HEADER, "D1,原藥,原規定,1091201,9991231,1.00,AI"]))
    sync_latest_rules(db_path=db_path, rules_dir=str(rdir), replace=True, confirm="REPLACE_RULES")
    assert get_rule("D1", db_path=db_path).name == "原藥"

    # 故意放入壞掉的新版給付 CSV（缺必要欄位），藥品新版合法 → 整庫必須維持原狀（無半切換）
    (rdir / "藥品項查詢項目檔261028AI  摘要支付價大於0.csv").write_bytes(
        _csv([DRUG_HEADER, "D1,新藥不應寫入,新規定,1150101,9991231,9.00,AI"])
    )
    (rdir / "醫療服務給付項目支付標準261201壞表頭.csv").write_bytes(_csv(["錯誤欄位"]))
    with pytest.raises(RuleCsvFormatError):
        sync_latest_rules(db_path=db_path, rules_dir=str(rdir), replace=True, confirm="REPLACE_RULES")
    assert get_rule("D1", db_path=db_path).name == "原藥"  # 未半切換
    assert not os.path.exists(db_path + ".lock")
    (rdir / "醫療服務給付項目支付標準261201壞表頭.csv").unlink()

    # 連續執行 7 次同步 → 備份輪替依檔名時間戳最多保留 5 份（不受 copy2 舊 mtime 干擾）
    for _ in range(7):
        sync_latest_rules(db_path=db_path, rules_dir=str(rdir), replace=False, max_backups=5)
    baks = _glob.glob(str(tmp_path / "rules.sqlite3.bak.*"))
    assert len(baks) == 5

    # 明確驗證依檔名時間戳排序：放一個檔名時間戳很舊但 mtime 很新的假備份，輪替後必須先淘汰它
    old_named = tmp_path / "rules.sqlite3.bak.1000000001"
    old_named.write_bytes(b"ancient")
    sync_latest_rules(db_path=db_path, rules_dir=str(rdir), replace=False, max_backups=5)
    assert not old_named.exists()
    assert len(_glob.glob(str(tmp_path / "rules.sqlite3.bak.*"))) == 5


def test_rules_upload_single_route_max_content_length_65mb(app):
    """Phase 36：POST /api/rules/upload 單路由放寬至 65 MB，其他路由維持 26 MB。"""
    from flask import request

    observed: dict[str, int | None] = {}

    @app.route("/api/_test_size_probe", methods=["POST"])
    def _probe():
        observed["other"] = request.max_content_length
        return {"ok": True}

    @app.after_request
    def _capture_upload(resp):
        if request.path == "/api/rules/upload":
            observed["rules_upload"] = request.max_content_length
        return resp

    with app.test_client() as c:
        c.post("/api/_test_size_probe", json={})
        c.post("/api/rules/upload", data={}, content_type="multipart/form-data")

    assert observed["other"] == 26 * 1024 * 1024
    assert observed["rules_upload"] == 65 * 1024 * 1024
