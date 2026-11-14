"""Unit tests for discovery responder (Phase 32 Plan 32-07, C2)."""

import json
import os
import socket
import threading
from unittest.mock import MagicMock
import pytest

from elc_audit_engine.discovery_responder import (
    DISCOVERY_MAGIC,
    DISCOVERY_SERVICE,
    build_discovery_reply,
    handle_datagram,
    start_responder,
)
from elc_audit_engine.lan_trust import parse_trusted_subnets


def test_discovery_responder_constants_and_keys():
    assert DISCOVERY_SERVICE == "elc-audit-engine"
    facility = {
        "code": "3501020000",
        "name": "測試診所",
        "address": "機密地址不外洩",
        "physician_name": "王醫師",
    }
    reply = build_discovery_reply(facility, host_ip="192.168.1.100", server_port=5000, version="5.2.0")
    expected_keys = {"service", "url", "facility_code", "facility_name", "version"}
    assert set(reply.keys()) == expected_keys
    assert reply["service"] == "elc-audit-engine"
    assert reply["url"] == "http://192.168.1.100:5000"
    assert reply["facility_code"] == "3501020000"
    assert reply["facility_name"] == "測試診所"
    assert reply["version"] == "5.2.0"
    assert "address" not in reply
    assert "physician_name" not in reply


def test_discovery_responder_empty_facility():
    reply = build_discovery_reply({}, host_ip="10.0.0.5", server_port=5000, version="5.2.0")
    assert reply["facility_code"] == ""
    assert reply["facility_name"] == ""
    assert reply["url"] == "http://10.0.0.5:5000"


def test_handle_datagram_validation():
    trusted = parse_trusted_subnets("192.168.1.0/24")
    reply = {"service": "elc-audit-engine", "url": "http://192.168.1.1:5000"}

    # 1. Valid packet from trusted IP
    out = handle_datagram(DISCOVERY_MAGIC, "192.168.1.50", reply, trusted)
    assert out is not None
    assert len(out) <= 512
    parsed = json.loads(out.decode("utf-8"))
    assert parsed["service"] == "elc-audit-engine"

    # 2. Loopback is always trusted
    out_loop = handle_datagram(DISCOVERY_MAGIC, "127.0.0.1", reply, trusted)
    assert out_loop is not None

    # 3. Invalid magic
    assert handle_datagram(b"WRONG_MAGIC", "192.168.1.50", reply, trusted) is None

    # 4. Oversized packet (> 64 bytes)
    assert handle_datagram(b"A" * 65, "192.168.1.50", reply, trusted) is None

    # 5. Untrusted IP
    assert handle_datagram(DISCOVERY_MAGIC, "10.0.0.99", reply, trusted) is None


def test_start_responder_loopback_e2e():
    stop_event = threading.Event()
    # Bind to port 0 for dynamic available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    dyn_port = sock.getsockname()[1]
    sock.close()

    thread = start_responder(
        port=dyn_port,
        host_ip="127.0.0.1",
        server_port=5000,
        stop_event=stop_event,
    )

    try:
        # Client sends discovery magic to dyn_port
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.settimeout(2.0)
        client_sock.sendto(DISCOVERY_MAGIC, ("127.0.0.1", dyn_port))

        resp_data, _ = client_sock.recvfrom(1024)
        client_sock.close()

        resp_dict = json.loads(resp_data.decode("utf-8"))
        assert resp_dict["service"] == "elc-audit-engine"
        assert resp_dict["url"] == "http://127.0.0.1:5000"
    finally:
        stop_event.set()
        thread.join(timeout=2.0)


def test_gunicorn_conf_when_ready(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("gunicorn_conf", "deploy/gunicorn.conf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Disabled case
    monkeypatch.setenv("ELC_DISCOVERY_ENABLED", "0")
    server = MagicMock()
    mod.when_ready(server)
    # Shouldn't start or log
    assert not server.log.info.called
