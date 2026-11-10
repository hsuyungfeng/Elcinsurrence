from __future__ import annotations

import json
import pytest
from deploy.windows_agent.discovery import (
    EXPECTED_SERVICE_IDENTIFIER,
    DiscoveryResult,
    default_probe,
    discover_server,
    validate_manual_server_url,
)
from elc_audit_engine.api.app import create_app


# --- Task 1: /api/health Endpoint Service Identification Tests ---

def test_api_health_endpoint_service_identifier():
    """Test 1: GET /api/health 回應 JSON 含 service 欄位，值為 'elc-audit-engine'"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert data.get("service") == EXPECTED_SERVICE_IDENTIFIER


def test_api_health_endpoint_no_sensitive_info():
    """Test 2: 回應不含資料庫路徑、版本以外的內部設定、或任何金鑰字樣"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/api/health")
        raw_text = resp.get_data(as_text=True)
        assert "key" not in raw_text.lower()
        assert "password" not in raw_text.lower()
        assert "/" not in raw_text  # No path leakages


# --- Task 2: discover_server Ordered Discovery & Confirmation Tests ---

def test_discover_server_last_known_url_first_stops_subnet():
    """Test 1: last_known_url 可用時，探測順序第一個呼叫為該 URL，且找到後不再做子網掃描"""
    probe_calls = []

    def mock_probe(url: str, timeout: float):
        probe_calls.append(url)
        if url == "http://192.168.1.100:5000":
            return 200, {"status": "ok", "service": EXPECTED_SERVICE_IDENTIFIER}
        return 0, None

    subnet_called = False

    def mock_subnet():
        nonlocal subnet_called
        subnet_called = True
        return ["192.168.1.50", "192.168.1.51"]

    res = discover_server(
        last_known_url="http://192.168.1.100:5000",
        probe=mock_probe,
        subnet_hosts_provider=mock_subnet,
    )
    assert res.source == "last_known"
    assert res.chosen_url == "http://192.168.1.100:5000"
    assert res.candidates == ["http://192.168.1.100:5000"]
    assert len(probe_calls) == 1
    assert subnet_called is False


def test_discover_server_subnet_candidate_requires_confirmation():
    """Test 2: 注入 fake subnet_hosts 含一台回傳 service=elc-audit-engine 的 stub，回傳候選且 chosen_url 為 None"""
    def mock_probe(url: str, timeout: float):
        if url == "http://192.168.1.50:5000":
            return 200, {"status": "ok", "service": EXPECTED_SERVICE_IDENTIFIER}
        return 0, None

    res = discover_server(
        last_known_url=None,
        probe=mock_probe,
        subnet_hosts_provider=lambda: ["192.168.1.49", "192.168.1.50"],
        port=5000,
    )
    assert res.source == "subnet"
    assert res.chosen_url is None  # Requires confirmation before receiving key
    assert res.candidates == ["http://192.168.1.50:5000"]
    assert res.needs_manual_entry is False


def test_discover_server_mismatched_service_rejected():
    """Test 3: 回應 service 欄位不符（例如其他服務、或 HTTP 200 但無欄位）的主機不列為候選"""
    def mock_probe(url: str, timeout: float):
        if url == "http://192.168.1.50:5000":
            return 200, {"status": "ok", "service": "other-printer-service"}
        if url == "http://192.168.1.51:5000":
            return 200, {"status": "ok"}  # Missing service field
        return 0, None

    res = discover_server(
        last_known_url=None,
        probe=mock_probe,
        subnet_hosts_provider=lambda: ["192.168.1.50", "192.168.1.51"],
        port=5000,
    )
    assert len(res.candidates) == 0
    assert res.needs_manual_entry is True


def test_probe_sends_no_api_key_or_phi(monkeypatch):
    """Test 4: 所有探測的請求標頭皆不含 X-API-Key 或 Authorization，且 body 為空"""
    intercepted_requests = []

    class MockHTTPResponse:
        def __init__(self):
            self.status = 200

        def read(self):
            return json.dumps({"status": "ok", "service": EXPECTED_SERVICE_IDENTIFIER}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(req, timeout=None):
        intercepted_requests.append(req)
        return MockHTTPResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    status, body = default_probe("http://127.0.0.1:5000", timeout=0.5)
    assert status == 200
    assert len(intercepted_requests) == 1
    req = intercepted_requests[0]
    headers_lower = {k.lower(): v for k, v in req.headers.items()}
    assert "x-api-key" not in headers_lower
    assert "authorization" not in headers_lower
    assert req.data is None  # No body


def test_discover_server_timeout_parameter(monkeypatch):
    """Test 5: 子網探測傳入逾時參數為 0.5 秒"""
    recorded_timeouts = []

    def mock_probe(url: str, timeout: float):
        recorded_timeouts.append(timeout)
        return 0, None

    discover_server(
        last_known_url=None,
        probe=mock_probe,
        subnet_hosts_provider=lambda: ["192.168.1.1"],
        timeout=0.5,
    )
    assert recorded_timeouts == [0.5]


def test_discover_server_all_failed_requests_manual_entry():
    """Test 6: 全部失敗時回傳 DiscoveryResult(candidates=[], needs_manual_entry=True)"""
    res = discover_server(
        last_known_url=None,
        probe=lambda u, t: (0, None),
        subnet_hosts_provider=lambda: ["192.168.1.1"],
    )
    assert res.candidates == []
    assert res.chosen_url is None
    assert res.needs_manual_entry is True
    assert res.source == "none"


def test_discover_server_udp_probe_default_none_no_udp():
    """Test 7: udp_probe 預設為 None 時不做任何 UDP 動作"""
    udp_called = False

    def fake_udp():
        nonlocal udp_called
        udp_called = True
        return ["http://192.168.1.99:5000"]

    res = discover_server(
        last_known_url=None,
        probe=lambda u, t: (0, None),
        subnet_hosts_provider=lambda: [],
        udp_probe=None,
    )
    assert udp_called is False
    assert res.candidates == []


# --- Task 3: Manual Server URL Validation Tests ---

def test_manual_server_url_valid_with_port():
    """Test 1: 'http://192.168.1.20:8000' 通過並回傳標準化 URL（去除結尾斜線）"""
    assert validate_manual_server_url("http://192.168.1.20:8000/") == "http://192.168.1.20:8000"


def test_manual_server_url_valid_default_port_80():
    """Test 2: 'http://10.0.0.5' 通過（預設 port 80）"""
    assert validate_manual_server_url("http://10.0.0.5") == "http://10.0.0.5:80"


def test_manual_server_url_rejects_https():
    """Test 3: 'https://192.168.1.20' 被拒絕（研究建議僅 http）"""
    with pytest.raises(ValueError) as exc:
        validate_manual_server_url("https://192.168.1.20")
    assert "僅支援 HTTP" in str(exc.value)


def test_manual_server_url_rejects_public_ip():
    """Test 4: 'http://8.8.8.8' 被拒絕（非私有位址）"""
    with pytest.raises(ValueError) as exc:
        validate_manual_server_url("http://8.8.8.8")
    assert "非私有區域網路位址" in str(exc.value)


def test_manual_server_url_rejects_hostname():
    """Test 5: 'http://example.com' 被拒絕（非 IP 字面值）"""
    with pytest.raises(ValueError) as exc:
        validate_manual_server_url("http://example.com")
    assert "必須為 IPv4 位址字面值" in str(exc.value)


def test_manual_server_url_rejects_path_query_userinfo():
    """Test 6: 含路徑、query、或 user:pass@ 的輸入被拒絕"""
    with pytest.raises(ValueError):
        validate_manual_server_url("http://user:pass@192.168.1.1:5000")

    with pytest.raises(ValueError):
        validate_manual_server_url("http://192.168.1.1:5000/api/v1")

    with pytest.raises(ValueError):
        validate_manual_server_url("http://192.168.1.1:5000?foo=bar")
