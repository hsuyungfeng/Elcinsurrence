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
