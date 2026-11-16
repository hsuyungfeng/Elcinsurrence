"""院內信任模式的端點層行為（Phase 32-A）。

單元測試（test_lan_trust.py）驗證判定函式；本檔驗證**整合進 Flask 後**
真的生效：院內放行、院外 403、跨站寫入 403、壞 Host 400、審計仍留軌跡。
"""

from __future__ import annotations

import ipaddress

import pytest

TRUSTED = "192.168.0.50"
UNTRUSTED = "192.168.99.50"
HOST = "192.168.0.10:5000"


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _get(client, path="/api/facility", addr=TRUSTED, host=HOST, **kw):
    return client.get(
        path,
        environ_base={"REMOTE_ADDR": addr},
        headers={"Host": host, **kw.pop("headers", {})},
        **kw,
    )


# ── 院內放行、院外拒絕 ──────────────────────────────────────────


def test_trusted_subnet_needs_no_api_key(client):
    """核心驗收：院內網路使用不需任何金鑰。"""
    res = _get(client)
    assert res.status_code == 200


def test_loopback_allowed(client):
    """伺服器本機（健康檢查腳本、本機瀏覽器）一律放行。"""
    assert _get(client, addr="127.0.0.1", host="127.0.0.1:5000").status_code == 200


def test_untrusted_source_is_forbidden(client):
    res = _get(client, addr=UNTRUSTED)
    assert res.status_code == 403
    assert "院內網路" in res.get_json()["message"]


def test_untrusted_source_cannot_read_phi_endpoints(client):
    """院外來源不得讀到任何病歷相關端點。"""
    for path in ("/api/facility", "/api/clients", "/api/monthly/batches"):
        res = _get(client, path=path, addr=UNTRUSTED)
        assert res.status_code == 403, f"{path} 應拒絕院外來源，實際 {res.status_code}"


def test_health_endpoint_also_restricted(client):
    """健康檢查亦不豁免：院外來源連服務是否存在都不該得知。"""
    assert _get(client, path="/api/health", addr=UNTRUSTED).status_code == 403
    assert _get(client, path="/api/health").status_code == 200


def test_facility_endpoint_no_longer_doubles_as_credential_source(client):
    """院所代碼仍可讀（院內），但已不是金鑰——移除了「代碼即金鑰」。"""
    res = _get(client, path="/api/facility")
    assert res.status_code == 200
    assert _get(client, path="/api/facility", addr=UNTRUSTED).status_code == 403


# ── CSRF ───────────────────────────────────────────────────────


def test_cross_site_write_rejected_even_from_trusted_subnet(client):
    """惡意網頁從診間電腦發出的寫入：來源位址可信，仍須擋下。"""
    res = client.post(
        "/api/facility",
        json={"code": "1234567890", "name": "x"},
        environ_base={"REMOTE_ADDR": TRUSTED},
        headers={"Host": HOST, "Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403
    assert "跨站" in res.get_json()["message"]


def test_same_origin_write_allowed_from_loopback(client):
    """管理端點自伺服器本機 (loopback) 寫入正常放行。"""
    res = client.post(
        "/api/facility",
        json={"code": "3503250461", "name": "測試院所"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"Host": "127.0.0.1:5000", "Origin": "http://127.0.0.1:5000", "Sec-Fetch-Site": "same-origin"},
    )
    assert res.status_code == 200





def test_native_client_write_allowed_without_browser_headers(client):
    """ElcAgent／SoapVoice 不帶 Origin，不得被 CSRF 檢查誤擋。"""
    res = client.post(
        "/api/clients/heartbeat",
        json={"agent_id": "agent-1", "machine_id": "m1", "room_id": "room1"},
        environ_base={"REMOTE_ADDR": TRUSTED},
        headers={"Host": HOST},
    )
    assert res.status_code != 403


def test_cross_site_get_is_rejected_d32_18(client):
    """D-32-18: 跨站 GET 請求（帶 Sec-Fetch-Site: cross-site）一律拒絕（403）。"""
    res = _get(client, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403
    assert "跨站" in res.get_json()["message"]


# ── Host 檢查（DNS rebinding） ─────────────────────────────────


def test_dns_rebinding_host_rejected(client):
    """惡意網域解析到院內 IP：來源位址可信，但 Host 是攻擊者網域。"""
    res = _get(client, host="rebind.attacker.com")
    assert res.status_code == 400


def test_dns_rebinding_blocked_for_reads_too(client):
    """GET 不受 CSRF 保護，故 Host 檢查是讀取路徑的唯一防線。"""
    assert _get(client, path="/api/facility", host="evil.example").status_code == 400


def test_no_manual_host_allowlist_needed(client):
    """任何私有 IP 與 .local 形式皆放行，無需維護 ELC_ALLOWED_HOSTS。

    原本換分享器或 DHCP 重發就要改設定，否則全院連不上（計畫 A5／C 的根因）。
    """
    for host in ("192.168.0.10:5000", "10.1.2.3:5000", "172.16.9.9:5000", "elc.local:5000"):
        assert _get(client, host=host).status_code == 200, f"{host} 應放行"


# ── 審計軌跡（A3：驗證可省、軌跡不可省） ──────────────────────


def test_audit_records_source_address(app, monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr(
        "elc_audit_engine.api.security.audit_log.record_access",
        lambda **kw: recorded.append(kw),
    )
    app.test_client().get(
        "/api/facility",
        environ_base={"REMOTE_ADDR": TRUSTED},
        headers={"Host": HOST},
    )
    assert recorded, "業務端點必須留下審計軌跡"
    assert recorded[0]["caller_id"] == f"lan:{TRUSTED}"


def test_audit_skips_noisy_health_endpoint(app, monkeypatch):
    """客戶端每數秒探測一次，寫入審計會淹沒病歷存取紀錄。"""
    recorded: list[dict] = []
    monkeypatch.setattr(
        "elc_audit_engine.api.security.audit_log.record_access",
        lambda **kw: recorded.append(kw),
    )
    app.test_client().get(
        "/api/health",
        environ_base={"REMOTE_ADDR": TRUSTED},
        headers={"Host": HOST},
    )
    assert recorded == []


# ── 設定與啟動 ─────────────────────────────────────────────────


def test_app_starts_without_any_key_env(monkeypatch, tmp_path):
    """驗收：全新安裝、不設定任何金鑰即可啟動（原本 fail-fast 拒絕啟動）。"""
    from elc_audit_engine.api import create_app
    from elc_audit_engine.case_store import CaseStore

    monkeypatch.delenv("ELC_API_KEYS", raising=False)
    monkeypatch.delenv("ELC_AGENT_KEYS", raising=False)
    monkeypatch.setenv("ELC_TRUSTED_SUBNETS", "192.168.0.0/24")

    app = create_app(
        {"TESTING": True},
        case_store=CaseStore(db_path=str(tmp_path / "c.sqlite3")),
        migrate_legacy=False,
    )
    assert app.config["ELC_TRUSTED_SUBNETS"] == [ipaddress.ip_network("192.168.0.0/24")]


def test_security_headers_still_applied(client):
    res = _get(client)
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in res.headers["Content-Security-Policy"]


def test_reverse_proxy_forwarded_header_rejected(client):
    """同機反向代理會讓外部請求的 remote_addr 變成 127.0.0.1（loopback 會被信任）。
    帶轉發標頭的請求必須一律拒絕（fail closed）。"""
    res = _get(client, addr="127.0.0.1", host="127.0.0.1:5000",
               headers={"X-Forwarded-For": "203.0.113.9"})
    assert res.status_code == 403
