"""Phase 9-01 API key 認證測試（parse/load/resolve 純函式＋原始碼規則）。

Flask 整合測試（`before_request`／errorhandler／六端點 401／審計掛鉤）
於 Task 3 併入本檔（server.py 掛線後）。
"""

from __future__ import annotations

import inspect

import pytest

from elc_audit_engine import auth
from elc_audit_engine.auth import (
    AuthConfigError,
    AuthenticationError,
    load_api_keys,
    parse_api_keys,
    resolve_caller,
)

_KEY_HIS1 = "0123456789abcdef0123"
_KEY_HIS2 = "fedcba9876543210fedc"


# --- parse_api_keys ------------------------------------------------------


def test_parse_api_keys_two_callers():
    raw = f"his1:{_KEY_HIS1},his2:{_KEY_HIS2}"
    result = parse_api_keys(raw)
    assert result == {_KEY_HIS1: "his1", _KEY_HIS2: "his2"}


def test_parse_api_keys_empty_string_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys("")


def test_parse_api_keys_missing_colon_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys("his1_no_colon_key_at_all_16chars")


def test_parse_api_keys_short_key_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys("his1:tooshort")


def test_parse_api_keys_duplicate_key_raises():
    raw = f"his1:{_KEY_HIS1},his2:{_KEY_HIS1}"
    with pytest.raises(AuthConfigError):
        parse_api_keys(raw)


def test_parse_api_keys_caller_id_traversal_raises():
    raw = f"../etc/passwd:{_KEY_HIS1}"
    with pytest.raises(AuthConfigError):
        parse_api_keys(raw)


def test_parse_api_keys_empty_caller_id_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys(f":{_KEY_HIS1}")


def test_parse_api_keys_empty_key_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys("his1:")


def test_parse_api_keys_all_whitespace_raises():
    with pytest.raises(AuthConfigError):
        parse_api_keys("   ")


# --- load_api_keys --------------------------------------------------------


def test_load_api_keys_none_env_missing_raises(monkeypatch):
    monkeypatch.delenv(auth.ENV_API_KEYS, raising=False)
    with pytest.raises(AuthConfigError):
        load_api_keys(None)


def test_load_api_keys_none_env_empty_raises(monkeypatch):
    monkeypatch.setenv(auth.ENV_API_KEYS, "")
    with pytest.raises(AuthConfigError):
        load_api_keys(None)


def test_load_api_keys_reads_env(monkeypatch):
    monkeypatch.setenv(auth.ENV_API_KEYS, f"his1:{_KEY_HIS1}")
    result = load_api_keys(None)
    assert result == {_KEY_HIS1: "his1"}


def test_load_api_keys_direct_empty_string_raises():
    with pytest.raises(AuthConfigError):
        load_api_keys("")


# --- resolve_caller ---------------------------------------------------------


def test_resolve_caller_correct_key_returns_caller_id():
    keys = {_KEY_HIS1: "his1", _KEY_HIS2: "his2"}
    assert resolve_caller(_KEY_HIS1, keys) == "his1"
    assert resolve_caller(_KEY_HIS2, keys) == "his2"


def test_resolve_caller_wrong_key_raises():
    keys = {_KEY_HIS1: "his1"}
    with pytest.raises(AuthenticationError):
        resolve_caller("wrong-key-of-correct-length", keys)


def test_resolve_caller_none_raises():
    keys = {_KEY_HIS1: "his1"}
    with pytest.raises(AuthenticationError):
        resolve_caller(None, keys)


def test_resolve_caller_empty_string_raises():
    keys = {_KEY_HIS1: "his1"}
    with pytest.raises(AuthenticationError):
        resolve_caller("", keys)


def test_authentication_error_has_fixed_message():
    exc = AuthenticationError()
    assert exc.message == "認證失敗：缺少或無效的 API key"


# --- constant-time 規則守門（原始碼斷言） ------------------------------------


def test_source_uses_compare_digest_not_equality():
    source = inspect.getsource(auth)
    assert "compare_digest" in source
    # 逐行檢查，排除註解行，確認沒有用 `presented_key ==` 這種明文比對。
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "presented_key ==" not in stripped


# =============================================================================
# Task 3: Flask 整合測試（before_request 強制認證／errorhandler／審計掛鉤）
# =============================================================================

from elc_audit_engine.audit_log import read_entries  # noqa: E402

_APP_KEY_HIS1 = "0123456789abcdef0123"
_APP_KEY_HIS2 = "fedcba9876543210fedc"


@pytest.fixture()
def app_client(monkeypatch):
    """server.app test_client，以 his1/his2 兩把測試 key 覆寫認證表。

    所有需要引擎的端點以替身注入（monkeypatch server 模組命名空間的
    引用者符號，而非來源模組——from-import 後 patch 來源模組無效）。
    """
    import server as server_mod

    monkeypatch.setitem(
        server_mod.app.config,
        "ELC_API_KEYS",
        {_APP_KEY_HIS1: "his1", _APP_KEY_HIS2: "his2"},
    )
    monkeypatch.setattr(server_mod, "_sampling_cases", None)
    monkeypatch.setattr(server_mod, "_appeal_cases", None)
    return server_mod.app.test_client()


def _auth_header(key: str) -> dict:
    return {auth.API_KEY_HEADER: key}


def test_no_header_get_sampling_cases_returns_200(app_client):
    """fcde2c8：業務端點依使用者裁示不再強制 API Key（直接 HIS 對接）。"""
    r = app_client.get("/api/sampling/cases")
    assert r.status_code == 200


def test_wrong_key_get_sampling_cases_still_returns_200(app_client):
    """免強制認證後，錯誤 key 不應被拒——端點本身不驗證 key 正確性。"""
    r = app_client.get("/api/sampling/cases", headers=_auth_header("wrong-key-wrong-key-000"))
    assert r.status_code == 200


def test_correct_key_get_sampling_cases_returns_200(app_client):
    r = app_client.get("/api/sampling/cases", headers=_auth_header(_APP_KEY_HIS1))
    assert r.status_code == 200


def test_no_header_post_sampling_audit_calls_engine(app_client, monkeypatch):
    """免強制認證後，無 header 的請求仍應正常呼叫引擎（不再被攔在 401）。"""
    import server as server_mod

    calls = []
    monkeypatch.setattr(
        server_mod, "run_presubmission_check", lambda *a, **k: calls.append((a, k)) or None
    )
    r = app_client.post("/api/sampling/audit", json={"order_code": "14050B"})
    assert r.status_code != 401
    assert len(calls) == 1


def test_no_header_post_appeal_generate_not_blocked_by_auth(app_client):
    r = app_client.post(
        "/api/appeal/generate", json={"case_seq": "201", "order_code": "64140C"}
    )
    assert r.status_code != 401


def test_no_header_post_sampling_import_not_blocked_by_auth(app_client):
    r = app_client.post("/api/sampling/import", data={})
    # 缺必要欄位仍應是 400（業務驗證），而非 401（認證）。
    assert r.status_code != 401


def test_no_header_post_appeal_import_not_blocked_by_auth(app_client):
    r = app_client.post("/api/appeal/import", data={})
    assert r.status_code != 401


def test_index_no_key_returns_200(app_client):
    r = app_client.get("/")
    assert r.status_code == 200


def test_health_no_key_returns_200(app_client):
    r = app_client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_audit_log_records_correct_caller_id(app_client, tmp_path, monkeypatch):
    import server as server_mod

    log_path = str(tmp_path / "access.log")
    monkeypatch.setattr(
        "config.settings.AUDIT_LOG_PATH", log_path
    )
    monkeypatch.setattr(server_mod, "AUDIT_LOG_PATH", log_path, raising=False)

    calls = []

    def fake_record_access(**kwargs):
        calls.append(kwargs)
        return "line"

    monkeypatch.setattr(server_mod, "record_access", fake_record_access)

    r = app_client.get("/api/sampling/cases", headers=_auth_header(_APP_KEY_HIS2))
    assert r.status_code == 200
    assert len(calls) == 1
    assert calls[0]["caller_id"] == "his2"
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/api/sampling/cases"
    assert calls[0]["status"] == 200


def test_audit_log_entry_excludes_soap_content(app_client, tmp_path, monkeypatch):
    import server as server_mod

    log_path = str(tmp_path / "access.log")

    def fake_record_access(**kwargs):
        # 呼叫端不得把 request.json 塞進 detail；此處僅驗證真實
        # record_access 的行為在端點串接後仍成立（零 PHI）。
        from elc_audit_engine.audit_log import record_access as real_record_access

        return real_record_access(**{**kwargs, "log_path": log_path})

    monkeypatch.setattr(server_mod, "record_access", fake_record_access)
    monkeypatch.setattr(
        server_mod,
        "run_presubmission_check",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine not needed for this test")),
    )

    app_client.post(
        "/api/sampling/audit",
        json={
            "order_code": "14050B",
            "soap_text": "S: 機密內容 SECRET_SOAP_MARKER",
        },
        headers=_auth_header(_APP_KEY_HIS1),
    )
    entries = read_entries(log_path)
    serialized = str(entries)
    assert "SECRET_SOAP_MARKER" not in serialized
