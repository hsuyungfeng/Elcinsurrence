"""UDP Broadcast Discovery Responder for Clinic Server (Phase 32 Plan 32-07, C2).

Listens on UDP port 5002 for ELC_DISCOVER_SERVER_V1 broadcast packets from
Windows ElcAgent clients, and replies with server URL and facility info.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from typing import Any, Dict, List, Optional

from elc_audit_engine.lan_trust import is_trusted_source, load_trusted_subnets

logger = logging.getLogger("elc_audit_engine.discovery_responder")

DISCOVERY_SERVICE = "elc-audit-engine"
DISCOVERY_PORT = int(os.getenv("ELC_DISCOVERY_PORT", "5002"))
DISCOVERY_MAGIC = b"ELC_DISCOVER_SERVER_V1"

_VERSION_CACHE: Optional[str] = None


def _get_pkg_version() -> str:
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        try:
            from importlib.metadata import version

            _VERSION_CACHE = version("elc-audit-engine")
        except Exception:
            _VERSION_CACHE = "0.1.0"
    return _VERSION_CACHE


def build_discovery_reply(
    facility: Dict[str, Any],
    host_ip: str,
    server_port: int,
    version: str,
) -> Dict[str, str]:
    """Construct 5-key discovery response dictionary without sensitive info."""
    return {
        "service": DISCOVERY_SERVICE,
        "url": f"http://{host_ip}:{server_port}",
        "facility_code": str(facility.get("code") or ""),
        "facility_name": str(facility.get("name") or ""),
        "version": str(version),
    }


def handle_datagram(
    data: bytes,
    src_ip: str,
    reply: Dict[str, Any],
    trusted_subnets: List[Any],
) -> Optional[bytes]:
    """Process incoming datagram and return serialized response bytes if valid."""
    if len(data) > 64:
        return None

    if data != DISCOVERY_MAGIC:
        return None

    if not is_trusted_source(src_ip, trusted_subnets):
        logger.warning("Ignored discovery request from untrusted IP: %s", src_ip)
        return None

    out = json.dumps(reply, ensure_ascii=False).encode("utf-8")
    if len(out) > 512:
        logger.warning("Discovery reply exceeds 512 bytes: %d bytes", len(out))
        return None

    return out


def _detect_best_host_ip(src_ip: str) -> str:
    """Determine the host IP to send in the URL."""
    # Try connecting socket to src_ip to find outbound interface IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((src_ip, 1))
            return s.getsockname()[0]
    except OSError:
        pass
    return os.getenv("ELC_SERVER_HOST", "127.0.0.1")


def _run_responder(
    sock: socket.socket,
    fixed_host_ip: Optional[str],
    server_port: int,
    stop_event: threading.Event,
) -> None:
    sock.settimeout(0.5)
    logger.info("Discovery responder running on UDP port %d", sock.getsockname()[1])

    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except OSError as exc:
            if not stop_event.is_set():
                logger.error("Discovery socket error: %s", exc)
            break

        src_ip, client_port = addr[0], addr[1]

        try:
            from config import settings

            facility = settings.load_facility_config()
        except Exception:
            facility = {}

        host_ip = fixed_host_ip if fixed_host_ip else _detect_best_host_ip(src_ip)
        version = _get_pkg_version()

        reply_dict = build_discovery_reply(facility, host_ip, server_port, version)
        trusted = load_trusted_subnets()

        payload = handle_datagram(data, src_ip, reply_dict, trusted)
        if payload is not None:
            try:
                sock.sendto(payload, addr)
                logger.debug("Sent discovery reply to %s:%d", src_ip, client_port)
            except OSError as exc:
                logger.warning("Failed to send discovery reply to %s: %s", src_ip, exc)

    sock.close()
    logger.info("Discovery responder stopped")


def start_responder(
    port: int = DISCOVERY_PORT,
    host_ip: Optional[str] = None,
    server_port: int = 5000,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Bind UDP socket and launch responder daemon thread."""
    if stop_event is None:
        stop_event = threading.Event()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))

    t = threading.Thread(
        target=_run_responder,
        args=(sock, host_ip, server_port, stop_event),
        name="DiscoveryResponderThread",
        daemon=True,
    )
    t.start()
    return t
