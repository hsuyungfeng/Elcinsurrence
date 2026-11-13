"""Phase 31: 多連線監控 (Clients Monitor) 與頁面測試 (契約 §3, §5, D-31-15 ~ D-31-18c)."""

from __future__ import annotations

import datetime
from pathlib import Path
import re
import uuid
from typing import Any


from elc_audit_engine.cycles.store import create_cycle, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401


def _assert_no_phi(obj: Any) -> None:
    """遞迴檢查絕無任何 PHI 欄位 (D-31-17)."""
    forbidden_keys = {
        "soap",
        "soap_text",
        "transcript",
        "extras",
        "patient_name",
        "patient_ref",
        "record_no",
        "id_number",
        "birth_date",
    }
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in forbidden_keys, f"Found forbidden key: {k}"
            assert not k.startswith("patient"), f"Found patient-prefixed key: {k}"
            _assert_no_phi(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_phi(item)


def test_monitor_rooms_grouped(phase31_app, phase31_client):
    """Test monitor_1: 三台客戶端（room A 兩台、room B 一台、未指定 room 一台）→ rooms 分組。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())
    m2 = str(uuid.uuid4())
    m3 = str(uuid.uuid4())
    m4 = str(uuid.uuid4())

    phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m1, "room_id": "room_a", "machine_name": "PC-A1"})
    phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m2, "room_id": "room_a", "machine_name": "PC-A2"})
    phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m3, "room_id": "room_b", "machine_name": "PC-B1"})
    phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m4, "room_id": None, "machine_name": "PC-Unassigned"})

    resp = phase31_client.get("/api/clients", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "rooms" in data

    rooms = data["rooms"]
    room_map = {r["room_id"]: r["clients"] for r in rooms}

    assert "room_a" in room_map
    assert len(room_map["room_a"]) == 2
    assert "room_b" in room_map
    assert len(room_map["room_b"]) == 1
    assert None in room_map
    assert len(room_map[None]) == 1
    assert room_map[None][0]["machine_id"] == m4


def test_monitor_offline_detection(phase31_app, phase31_client, monkeypatch):
    """Test monitor_2: 最後心跳 16 秒前 → online=false、display_state="離線"；14 秒前 → online=true。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())
    m2 = str(uuid.uuid4())

    now = datetime.datetime(2026, 11, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # 模擬 m1 在 16 秒前心跳，m2 在 14 秒前心跳
    t_16s_ago = (now - datetime.timedelta(seconds=16)).isoformat()
    t_14s_ago = (now - datetime.timedelta(seconds=14)).isoformat()

    store = phase31_app.case_store
    from elc_audit_engine.cycles.presence import upsert_presence
    upsert_presence(store, machine_id=m1, machine_name="M1")
    upsert_presence(store, machine_id=m2, machine_name="M2")

    conn = store._connect()
    with conn:
        conn.execute("UPDATE client_presence SET last_seen_at = ? WHERE machine_id = ?", (t_16s_ago, m1))
        conn.execute("UPDATE client_presence SET last_seen_at = ? WHERE machine_id = ?", (t_14s_ago, m2))
    conn.close()

    # monkeypatch presence 模組內的 _now_utc
    from elc_audit_engine.cycles import presence
    monkeypatch.setattr(presence, "_now_utc", lambda: now)

    resp = phase31_client.get("/api/clients", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    clients_by_id = {}
    for r in data["rooms"]:
        for c in r["clients"]:
            clients_by_id[c["machine_id"]] = c

    assert clients_by_id[m1]["online"] is False
    assert clients_by_id[m1]["display_state"] == "離線"

    assert clients_by_id[m2]["online"] is True
    assert clients_by_id[m2]["display_state"] == "待命"


def test_monitor_display_states(phase31_app, phase31_client):
    """Test monitor_3: display_state 對 RECORDING、AWAITING_CONFIRM、最近循環 ARCHIVED、無循環分別為 錄音中、待確認、已封存、待命。"""
    store = phase31_app.case_store
    headers = {"X-API-Key": "valid-key-123"}

    m_rec = str(uuid.uuid4())
    m_conf = str(uuid.uuid4())
    m_arch = str(uuid.uuid4())
    m_idle = str(uuid.uuid4())

    # 1. 錄音中
    c_rec, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_rec)

    # 2. 待確認
    c_conf, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_conf)
    transition_cycle(store, c_conf["cycle_id"], "AWAITING_DRAFT")
    transition_cycle(store, c_conf["cycle_id"], "AWAITING_CONFIRM")

    # 3. 已封存
    c_arch, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_arch)
    transition_cycle(store, c_arch["cycle_id"], "AWAITING_DRAFT")
    transition_cycle(store, c_arch["cycle_id"], "AWAITING_CONFIRM")
    transition_cycle(store, c_arch["cycle_id"], "CONFIRMED")
    transition_cycle(store, c_arch["cycle_id"], "ARCHIVED")

    # 4. 無循環: m_idle

    for m in [m_rec, m_conf, m_arch, m_idle]:
        phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m})

    resp = phase31_client.get("/api/clients", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    cmap = {}
    for r in data["rooms"]:
        for c in r["clients"]:
            cmap[c["machine_id"]] = c["display_state"]

    assert cmap[m_rec] == "錄音中"
    assert cmap[m_conf] == "待確認"
    assert cmap[m_arch] == "已封存"
    assert cmap[m_idle] == "待命"


def test_monitor_no_phi(phase31_app, phase31_client):
    """Test monitor_4: 回應遞迴不含 soap、transcript、extras、patient 開頭的鍵 (D-31-17)。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())
    phase31_client.post("/api/clients/heartbeat", headers=headers, json={"machine_id": m1, "room_id": "r1"})

    resp = phase31_client.get("/api/clients", headers=headers)
    assert resp.status_code == 200
    _assert_no_phi(resp.get_json())


def test_monitor_subnet_attribution(phase31_app, phase31_client, monkeypatch):
    """Test monitor_5: REMOTE_ADDR=192.168.5.77 → client_subnet="192.168.5.0/24"；ELC_CLINIC_SUBNETS 判斷。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())

    phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        environ_base={"REMOTE_ADDR": "192.168.5.77"},
        json={"machine_id": m1},
    )

    # 1. 未設定 ELC_CLINIC_SUBNETS 時：192.168.5.0/24 為私有位址，in_clinic_subnet=true
    monkeypatch.delenv("ELC_CLINIC_SUBNETS", raising=False)
    resp1 = phase31_client.get("/api/clients", headers=headers)
    client1 = resp1.get_json()["rooms"][0]["clients"][0]
    assert client1["client_subnet"] == "192.168.5.0/24"
    assert client1["in_clinic_subnet"] is True

    # 2. 設定 ELC_CLINIC_SUBNETS="10.0.0.0/8" 時：in_clinic_subnet=false
    monkeypatch.setenv("ELC_CLINIC_SUBNETS", "10.0.0.0/8")
    resp2 = phase31_client.get("/api/clients", headers=headers)
    client2 = resp2.get_json()["rooms"][0]["clients"][0]
    assert client2["client_subnet"] == "192.168.5.0/24"
    assert client2["in_clinic_subnet"] is False


def test_monitor_validation_room_id(phase31_app, phase31_client):
    """Test monitor_6: 心跳 body 的 room_id 不合格式 → 422；room_id 不由 IP 推得。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())
    m2 = str(uuid.uuid4())

    # 1. room_id 格式不合法 (含特殊符號或空格)
    resp_bad = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={"machine_id": m1, "room_id": "room with spaces!"},
    )
    assert resp_bad.status_code == 422

    # 2. 同一 IP 兩台機器送不同合法 room_id，各自保留不被 IP 覆寫
    phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        environ_base={"REMOTE_ADDR": "192.168.1.100"},
        json={"machine_id": m1, "room_id": "room_alpha"},
    )
    phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        environ_base={"REMOTE_ADDR": "192.168.1.100"},
        json={"machine_id": m2, "room_id": "room_beta"},
    )

    resp = phase31_client.get("/api/clients", headers=headers)
    rooms = {r["room_id"]: r["clients"] for r in resp.get_json()["rooms"]}
    assert "room_alpha" in rooms
    assert "room_beta" in rooms
    assert rooms["room_alpha"][0]["machine_id"] == m1
    assert rooms["room_beta"][0]["machine_id"] == m2


def test_monitor_validation_fields(phase31_app, phase31_client):
    """Test monitor_7: machine_name、bar_state、soapvoice_state 超過 64 字或含控制字元 → 422。"""
    headers = {"X-API-Key": "valid-key-123"}
    m1 = str(uuid.uuid4())

    # 超過 64 字元
    resp_long = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={"machine_id": m1, "machine_name": "x" * 65},
    )
    assert resp_long.status_code == 422

    # 含控制字元 (\n)
    resp_ctrl = phase31_client.post(
        "/api/clients/heartbeat",
        headers=headers,
        json={"machine_id": m1, "bar_state": "WAITING\nCONFIRM"},
    )
    assert resp_ctrl.status_code == 422


def test_page_no_auth(phase31_app, phase31_client):
    """Test page_1: GET /clients 無 key → 200 text/html；不內嵌資料。"""
    resp = phase31_client.get("/clients")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)
    assert "machine_id" not in html
    assert "cycle_id" not in html


def test_page_security_exemptions():
    """Test page_2: 驗證 security 模組端點豁免設定。"""
    from elc_audit_engine.api.security import AUDIT_EXEMPT_ENDPOINTS, AUTH_EXEMPT_ENDPOINTS

    assert "clients.monitor_page" in AUTH_EXEMPT_ENDPOINTS
    assert "clients.monitor_page" in AUDIT_EXEMPT_ENDPOINTS

    assert "clients.client_heartbeat" in AUDIT_EXEMPT_ENDPOINTS
    assert "clients.client_heartbeat" not in AUTH_EXEMPT_ENDPOINTS

    assert "clients.list_clients" not in AUDIT_EXEMPT_ENDPOINTS
    assert "clients.list_clients" not in AUTH_EXEMPT_ENDPOINTS


def test_page_no_dangerous_dom():
    """Test page_3: static/clients.html 去除註解後不含 innerHTML、outerHTML、insertAdjacentHTML、eval。"""
    html_path = Path(__file__).resolve().parent.parent / "static" / "clients.html"
    content = html_path.read_text(encoding="utf-8")

    # 去除 HTML 與 JS 註解
    no_html_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    clean_content = re.sub(r"//.*?$|/\*.*?\*/", "", no_html_comments, flags=re.MULTILINE | re.DOTALL)

    dangerous_patterns = ["innerHTML", "outerHTML", "insertAdjacentHTML", "eval("]
    for p in dangerous_patterns:
        assert p not in clean_content, f"Found dangerous DOM pattern {p} in static/clients.html"


def test_page_required_strings():
    """Test page_4: 頁面含 /api/clients、X-API-Key、elc_api_key、setInterval 字串。"""
    html_path = Path(__file__).resolve().parent.parent / "static" / "clients.html"
    content = html_path.read_text(encoding="utf-8")

    for s in ["/api/clients", "X-API-Key", "elc_api_key", "setInterval"]:
        assert s in content, f"Missing required string {s} in static/clients.html"
