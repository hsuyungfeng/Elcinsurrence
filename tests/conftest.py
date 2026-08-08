import sys
import os
import json

import pytest

# Insert project root to sys.path so `config` package resolves during collection
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Phase 9-01：server.py 在 import 期即以 _init_api_keys() 讀取 ELC_API_KEYS
# （fail-fast 設計，見 elc_audit_engine.auth）。測試環境若完全不設定此變數，
# 任何匯入 server 模組的測試檔會在收集階段就以 AuthConfigError 中止。
# 這裡以 setdefault 提供一組測試用固定 key（非真實憑證，公開於版控中亦
# 無風險）；各測試檔仍可用 monkeypatch 覆寫 app.config["ELC_API_KEYS"]
# 測試特定的認證情境（如 test_auth.py 的 401/200 案例）。
os.environ.setdefault("ELC_API_KEYS", "test-suite:0000000000TESTKEY0000")


@pytest.fixture
def tmp_rule_db_path(tmp_path) -> str:
    """回傳一個尚未建立的暫存 SQLite DB 路徑（str），供規則庫測試使用。

    只回傳路徑，不建立檔案 — 實際建表由 rule_repository.db 負責
    （Plan 02）。使用 pytest 的 tmp_path，確保測試執行不會寫入
    專案正式的 data/db/rules.sqlite3。
    """
    return str(tmp_path / "test_rules.sqlite3")


# ── Phase 11 (appeal_print) fixtures ───────────────────────────


@pytest.fixture
def facility_config(tmp_path, monkeypatch):
    """測試用院所設定（D-04）：寫入 tmp_path/facility.json 並以
    monkeypatch 把 `settings.FACILITY_CONFIG_PATH` 指向該檔，回傳 dict。

    比照 test_config.py 的 monkeypatch 缺檔測試模式；11-03 才新增
    `FACILITY_CONFIG_PATH`／`load_facility_config()`，本 fixture 先行
    提供，供 11-02/11-03 的 render/write 與 config 測試使用。
    """
    from config import settings

    cfg = {
        "code": "01015C",
        "name": "測試醫療院所",
        "address": "測試市測試區測試路1號",
        "physician_name": "測試醫師",
    }
    path = tmp_path / "facility.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(path), raising=False)
    return cfg


@pytest.fixture
def sample_appeal_draft():
    """構造 AppealDraft 的共用 factory（比照 test_appeal.py `_draft(**kwargs)`）。

    回傳一個閉包：`sample_appeal_draft(**overrides) -> AppealDraft`。
    缺省值含 case_class/case_seq/order_seq/order_code/visit_date/
    fee_year_month/reason1/reason2/p6_points；各測試只覆寫差異欄位。
    """
    from elc_audit_engine.generators.appeal import AppealDraft

    def _make(**kwargs):
        base = dict(
            case_class="D2",
            case_seq="18",
            order_seq="1",
            order_code="E5002C",
            visit_date="2021-06-23",
            fee_year_month="202106",
            reason1="申復理由一",
            reason2="申復理由二",
            p6_points=300,
        )
        base.update(kwargs)
        return AppealDraft(**base)

    return _make
