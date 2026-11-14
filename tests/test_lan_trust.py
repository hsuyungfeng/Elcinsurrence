"""院內網路信任模式（Phase 32-A）：取代 API key 認證的來源位址判定。

對應改進計畫 A1–A7 與「免驗證後必須補上的防護」。重點不只是「院內放行」，
更是**院外一律拒絕**、**跨站寫入拒絕**、**DNS rebinding 拒絕**——金鑰移除後
這三道是唯一的防線。
"""

from __future__ import annotations

import ipaddress

import pytest

from elc_audit_engine.lan_trust import (
    TrustConfigError,
    caller_id_for,
    describe_trust,
    detect_local_subnets,
    is_allowed_host,
    is_cross_site_request,
    is_trusted_source,
    load_trusted_subnets,
    parse_trusted_subnets,
)


# ── 信任網段解析 ────────────────────────────────────────────────


def test_parse_trusted_subnets_multiple():
    nets = parse_trusted_subnets("192.168.1.0/24, 10.0.5.0/24")
    assert nets == [
        ipaddress.ip_network("192.168.1.0/24"),
        ipaddress.ip_network("10.0.5.0/24"),
    ]


def test_parse_trusted_subnets_accepts_host_bits():
    """部署者常直接從 `ip addr` 複製 `192.168.1.50/24` 這種帶主機位的寫法。"""
    assert parse_trusted_subnets("192.168.1.50/24") == [ipaddress.ip_network("192.168.1.0/24")]


def test_parse_trusted_subnets_rejects_garbage():
    with pytest.raises(TrustConfigError):
        parse_trusted_subnets("not-a-subnet")


def test_parse_trusted_subnets_rejects_empty():
    with pytest.raises(TrustConfigError):
        parse_trusted_subnets("   ,  ")


def test_load_trusted_subnets_env_overrides_detection(monkeypatch):
    monkeypatch.setenv("ELC_TRUSTED_SUBNETS", "172.20.0.0/16")
    assert load_trusted_subnets() == [ipaddress.ip_network("172.20.0.0/16")]


def test_load_trusted_subnets_config_error_does_not_degrade_to_open(monkeypatch):
    """設定錯誤必須 fail-fast，不得降級為「信任所有來源」。"""
    monkeypatch.setenv("ELC_TRUSTED_SUBNETS", "192.168.1.0/99")
    with pytest.raises(TrustConfigError):
        load_trusted_subnets()


def test_detect_local_subnets_returns_24_of_interface():
    assert detect_local_subnets(local_ip="192.168.68.118") == [
        ipaddress.ip_network("192.168.68.0/24")
    ]


def test_detect_local_subnets_loopback_only_does_not_widen_trust():
    """未接網路時只有 loopback：不得擴張信任範圍。"""
    assert detect_local_subnets(local_ip="127.0.0.1") == []


# ── 來源位址判定 ────────────────────────────────────────────────

_SUBNETS = [ipaddress.ip_network("192.168.68.0/24")]


@pytest.mark.parametrize("addr", ["192.168.68.1", "192.168.68.42", "192.168.68.254"])
def test_in_subnet_is_trusted(addr):
    assert is_trusted_source(addr, _SUBNETS) is True


@pytest.mark.parametrize("addr", ["127.0.0.1", "::1"])
def test_loopback_always_trusted(addr):
    """伺服器本機與健康檢查腳本一律放行，與信任網段設定無關。"""
    assert is_trusted_source(addr, []) is True


@pytest.mark.parametrize(
    "addr",
    [
        "192.168.69.1",   # 相鄰網段（例如訪客 Wi-Fi）
        "10.0.0.5",       # 其他私有網段
        "172.16.0.5",     # 其他私有網段
        "8.8.8.8",        # 公網
    ],
)
def test_outside_subnet_is_rejected(addr):
    """關鍵：其他私有網段也要拒絕。

    原 `_is_private_ip` 式判定會信任整個 RFC 1918（約一千七百萬個位址），
    包含訪客 Wi-Fi 等不相干網段；收斂到實際子網才符合「院內」語意。
    """
    assert is_trusted_source(addr, _SUBNETS) is False


@pytest.mark.parametrize("addr", [None, "", "not-an-ip"])
def test_missing_or_malformed_address_is_rejected(addr):
    assert is_trusted_source(addr, _SUBNETS) is False


# ── 審計識別 ────────────────────────────────────────────────────


def test_caller_id_records_source_address():
    """無金鑰可辨識身分，改以來源位址留下「哪一台電腦」的軌跡（A3）。"""
    assert caller_id_for("192.168.68.42") == "lan:192.168.68.42"


def test_caller_id_handles_missing_address():
    assert caller_id_for(None) == "lan:unknown"


# ── CSRF（跨站寫入）防護 ────────────────────────────────────────

_ROOT = "http://192.168.68.118:5000/"


def test_cross_site_post_is_rejected():
    """惡意網頁對院內伺服器發出寫入請求——金鑰移除後的主要新攻擊面。"""
    assert is_cross_site_request("POST", "http://evil.example", "cross-site", _ROOT) is True


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_same_site_post_allowed(site):
    """`none` 為使用者直接輸入網址或書籤開啟，屬正常操作。"""
    assert is_cross_site_request("POST", None, site, _ROOT) is False


def test_get_is_not_blocked_by_csrf_check():
    """GET 不在 CSRF 範圍（讀取端點不應有副作用）；跨站讀取由 Host 檢查擋。"""
    assert is_cross_site_request("GET", "http://evil.example", "cross-site", _ROOT) is False


def test_origin_fallback_rejects_foreign_origin():
    """無 Sec-Fetch-Site 的舊瀏覽器：退回比對 Origin。"""
    assert is_cross_site_request("POST", "http://evil.example", None, _ROOT) is True


def test_origin_fallback_allows_same_origin():
    assert is_cross_site_request("POST", "http://192.168.68.118:5000", None, _ROOT) is False


def test_native_client_without_browser_headers_allowed():
    """ElcAgent／SoapVoice 以 urllib 呼叫，不帶 Origin／Sec-Fetch-Site。

    瀏覽器在跨站寫入時**必定**帶 Origin，故「兩者皆無」可安全視為非瀏覽器。
    """
    assert is_cross_site_request("POST", None, None, _ROOT) is False


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_state_changing_methods_checked(method):
    assert is_cross_site_request(method, "http://evil.example", "cross-site", _ROOT) is True


# ── Host 檢查（DNS rebinding） ─────────────────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "192.168.68.118:5000",
        "192.168.68.118",
        "127.0.0.1:5000",
        "localhost:5000",
        "10.0.5.20:5000",
        "elc-server.local:5000",
        "[::1]:5000",
    ],
)
def test_allowed_hosts(host):
    assert is_allowed_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:5000",
        "rebind.attacker.com",
        "8.8.8.8:5000",
        "",
        None,
    ],
)
def test_rejected_hosts(host):
    """DNS rebinding：惡意網域解析到院內 IP 後，來源位址檢查無法分辨，
    且 GET 讀取不受 CSRF 檢查保護，故必須另驗 Host。"""
    assert is_allowed_host(host) is False


# ── 信任範圍描述（安裝人員可見性，A5／C6） ─────────────────────


def test_describe_trust_lists_subnets():
    text = describe_trust([ipaddress.ip_network("192.168.68.0/24")])
    assert "192.168.68.0/24" in text


def test_describe_trust_loopback_only():
    assert "僅本機" in describe_trust([])
