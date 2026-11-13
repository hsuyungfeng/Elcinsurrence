"""Phase 31: 快捷列端 IPC 與 Server 客戶端契約測試 (契約 §1, §3)."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Any, Dict, List
import uuid

import pytest

from deploy.windows_agent.config import load_settings, save_settings
from deploy.windows_agent.traffic_bar.server_client import (
    CycleServerClient,
)
from deploy.windows_agent.traffic_bar.soapvoice_client import (
    IpcRejected,
    IpcUnavailable,
    SoapVoiceControlClient,
)
from tests.phase31_support import load_contract


class MockHttpHandler(BaseHTTPRequestHandler):
    """自訂假伺服器處理函式，用於捕捉請求標頭、路徑與內文。"""

    recorded_requests: List[Dict[str, Any]] = []
    response_code = 200
    response_body: Dict[str, Any] = {}

    def log_message(self, format, *args):
        pass  # 靜音

    def do_GET(self):
        self._record_and_reply()

    def do_POST(self):
        self._record_and_reply()

    def _record_and_reply(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        parsed_body = None
        if body:
            try:
                parsed_body = json.loads(body)
            except Exception:
                parsed_body = body

        self.recorded_requests.append({
            "method": self.command,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": parsed_body,
        })

        resp_bytes = json.dumps(self.response_body).encode("utf-8")
        self.send_response(self.response_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


@pytest.fixture
def mock_server():
    MockHttpHandler.recorded_requests = []
    MockHttpHandler.response_code = 200
    MockHttpHandler.response_body = {}

    server = HTTPServer(("127.0.0.1", 0), MockHttpHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield server, port, MockHttpHandler

    server.shutdown()
    server.server_close()


def test_soapvoice_client_status(mock_server):
    """Test 1: status() 送出 X-Local-Token 與 Host 127.0.0.1:{port}，解析欄位與契約一致。"""
    _, port, handler = mock_server
    contract = load_contract()
    status_example = contract["ipc"]["status"]["response"]

    handler.response_code = 200
    handler.response_body = status_example

    token = "secret-token-xyz"
    client = SoapVoiceControlClient(port=port, token=token)

    st = client.status()
    assert st["contract"] == "elc-p31-ipc/1"
    assert st["state"] == status_example["state"]

    req = handler.recorded_requests[0]
    assert req["method"] == "GET"
    assert req["path"] == "/control/v1/status"
    assert req["headers"].get("x-local-token") == token
    assert req["headers"].get("host") == f"127.0.0.1:{port}"


def test_soapvoice_client_start_stop_archived(mock_server):
    """Test 2: start、stop、archived 路徑與 body 一致；409 busy 與連線中斷處理。"""
    _, port, handler = mock_server
    token = "secret-token-xyz"
    client = SoapVoiceControlClient(port=port, token=token)

    cmd_id = uuid.uuid4().hex
    c_id = uuid.uuid4().hex

    # 1. start
    handler.response_code = 200
    handler.response_body = {"contract": "elc-p31-ipc/1", "state": "RECORDING"}
    resp = client.start(cmd_id, c_id)
    assert resp["state"] == "RECORDING"
    req_start = handler.recorded_requests[-1]
    assert req_start["path"] == "/control/v1/start"
    assert req_start["body"] == {"command_id": cmd_id, "cycle_id": c_id}

    # 2. 409 busy
    handler.response_code = 409
    handler.response_body = {"error": "busy", "message": "已有進行中的錄音"}
    with pytest.raises(IpcRejected) as exc_info:
        client.start(cmd_id, c_id)
    assert exc_info.value.status == 409
    assert exc_info.value.error_code == "busy"

    # 3. stop
    handler.response_code = 200
    handler.response_body = {"contract": "elc-p31-ipc/1", "state": "UPLOADING"}
    resp_stop = client.stop(cmd_id, c_id)
    assert resp_stop["state"] == "UPLOADING"
    req_stop = handler.recorded_requests[-1]
    assert req_stop["path"] == "/control/v1/stop"
    assert req_stop["body"] == {"command_id": cmd_id, "cycle_id": c_id}

    # 4. archived
    handler.response_code = 200
    handler.response_body = {"cycle_id": c_id, "cleanup_eligible": True}
    resp_arch = client.archived(c_id)
    assert resp_arch["cleanup_eligible"] is True
    req_arch = handler.recorded_requests[-1]
    assert req_arch["path"] == "/control/v1/archived"
    assert req_arch["body"] == {"cycle_id": c_id}

    # 5. 連不上（測試無伺服器之隨機未監聽埠）
    bad_client = SoapVoiceControlClient(port=59999, token=token, timeout=0.1)
    with pytest.raises(IpcUnavailable):
        bad_client.status()


def test_soapvoice_client_host_validation():
    """Test 3: host 不是 127.0.0.1 或 localhost 時拒絕連線 (T-31-44)。"""
    with pytest.raises(ValueError, match="僅允許連線 127.0.0.1 或 localhost"):
        SoapVoiceControlClient(host="192.168.1.10")

    with pytest.raises(ValueError, match="僅允許連線 127.0.0.1 或 localhost"):
        SoapVoiceControlClient(host="evil.com")


def test_cycle_server_client(mock_server):
    """Test 4: 測試 CycleServerClient 各方法：路徑、方法、operator_key、202 與 409 回應。"""
    _, port, handler = mock_server
    base_url = f"http://127.0.0.1:{port}"
    op_key = "op-key-test-999"
    client = CycleServerClient(base_url, operator_key=op_key)

    c_id = uuid.uuid4().hex
    cmd_id = uuid.uuid4().hex
    m_id = str(uuid.uuid4())

    # 1. create_cycle
    handler.response_code = 201
    handler.response_body = {"cycle": {"cycle_id": c_id, "state": "RECORDING"}}
    created = client.create_cycle(cmd_id, m_id, room_id="room_1")
    assert created["cycle_id"] == c_id
    req = handler.recorded_requests[-1]
    assert req["path"] == "/api/cycles"
    assert req["headers"].get("x-api-key") == op_key
    assert req["body"] == {"command_id": cmd_id, "machine_id": m_id, "room_id": "room_1"}

    # 2. archive: 202 his_pending
    handler.response_code = 202
    handler.response_body = {"status": "his_pending"}
    st_code, body = client.archive(c_id, cmd_id)
    assert st_code == 202
    assert body["status"] == "his_pending"

    # 3. archive: 409 his_failed
    handler.response_code = 409
    handler.response_body = {"status": "his_failed", "reason": "timeout"}
    st_code, body = client.archive(c_id, cmd_id)
    assert st_code == 409
    assert body["status"] == "his_failed"
    assert body["reason"] == "timeout"

    # 4. heartbeat
    handler.response_code = 200
    handler.response_body = {"status": "ok", "server_time": "2026-11-12T00:00:00Z", "notify": None}
    hb = client.heartbeat(machine_id=m_id, machine_name="PC-1", bar_state="IDLE")
    assert hb["status"] == "ok"
    req_hb = handler.recorded_requests[-1]
    assert req_hb["path"] == "/api/clients/heartbeat"
    assert req_hb["body"]["bar_state"] == "IDLE"


def test_agent_settings_backwards_compatibility(tmp_path):
    """Test 5: 舊版設定檔以 load_settings 載入成功，新欄位為預設值；save 後保持一致；operator_key 隱藏於 repr。"""
    cfg_file = tmp_path / "config.json"
    old_data = {
        "vendor_key": "vision",
        "app_name": "VisionHIS.exe",
        "agent_id": "agent-007",
        "agent_key": "sec-agent-key",
        "operator_key": "sec-op-key",
        "machine_id": "m-old-123",
        "schema_version": 1,
    }
    cfg_file.write_text(json.dumps(old_data), encoding="utf-8")

    loaded = load_settings(cfg_file)
    assert loaded.agent_id == "agent-007"
    assert loaded.operator_key == "sec-op-key"
    assert loaded.room_id == ""
    assert loaded.bar_x is None
    assert loaded.bar_y is None
    assert loaded.soapvoice_control_port == 18765

    # repr 不含敏感金鑰
    r = repr(loaded)
    assert "sec-agent-key" not in r
    assert "sec-op-key" not in r

    # 修改新欄位儲存後再載入
    loaded.room_id = "room_302"
    loaded.bar_x = 100
    loaded.bar_y = 200
    save_settings(cfg_file, loaded)

    reloaded = load_settings(cfg_file)
    assert reloaded.room_id == "room_302"
    assert reloaded.bar_x == 100
    assert reloaded.bar_y == 200


def test_clients_logging_no_secrets(mock_server, caplog):
    """Test 6: 客戶端日誌不含 token 與 operator_key (T-31-45)。"""
    caplog.set_level(logging.DEBUG)
    _, port, handler = mock_server

    secret_token = "my-super-secret-token"
    secret_op_key = "my-super-secret-operator-key"

    handler.response_code = 200
    handler.response_body = {"contract": "elc-p31-ipc/1", "state": "IDLE"}

    sv_client = SoapVoiceControlClient(port=port, token=secret_token)
    sv_client.status()

    server_client = CycleServerClient(f"http://127.0.0.1:{port}", operator_key=secret_op_key)
    server_client.get_active("m1")

    # 檢查 caplog 絕無 secret
    all_logs = caplog.text
    assert secret_token not in all_logs
    assert secret_op_key not in all_logs
