"""LAN Server Auto-Discovery for Windows Agent (Phase 30: D-30-08, D-30-09).

Discovery sequence:
1. Try last known successful server URL.
2. Optional UDP broadcast probe (default disabled).
3. Concurrently probe /api/health across local /24 subnet.
4. Fall back to manual server URL input.

Security rules:
- Discovery probes NEVER send API keys, credentials, or PHI.
- Found candidates require manual or caller confirmation before receiving requests with keys.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("windows_agent.discovery")

EXPECTED_SERVICE_IDENTIFIER = "elc-audit-engine"

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


@dataclass
class DiscoveryResult:
    """Outcome of LAN discovery sequence."""

    candidates: List[str] = field(default_factory=list)
    chosen_url: Optional[str] = None
    needs_manual_entry: bool = False
    source: str = "none"  # "last_known", "udp", "subnet", "none"


def validate_manual_server_url(raw: str) -> str:
    """Validate and normalize user-provided server URL.

    Rules:
    - Scheme must be http.
    - Host must be an IPv4 literal belonging to RFC 1918 private subnets.
    - No username, password, query parameters, or fragments.
    - Path must be empty or '/'.
    - Port must be between 1 and 65535 (default 80).
    Returns normalized 'http://<ip>:<port>'.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("請輸入伺服器網址")

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() != "http":
        raise ValueError("僅支援 HTTP 連線（http://）")

    if parsed.username or parsed.password:
        raise ValueError("網址不得包含使用者帳密資訊")

    if parsed.query or parsed.fragment:
        raise ValueError("網址不得包含查詢參數或錨點")

    path = parsed.path.strip()
    if path and path != "/":
        raise ValueError("網址路徑必須為根目錄，不得指定子路徑")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("無法解析主機位址")

    try:
        ip = ipaddress.IPv4Address(hostname)
    except ValueError:
        raise ValueError("主機位址必須為 IPv4 位址字面值，不支援主機名稱或 IPv6")

    is_private_subnet = any(ip in net for net in _PRIVATE_NETWORKS)
    if not is_private_subnet:
        raise ValueError(f"位址 {ip} 非私有區域網路位址（僅允許 10/8、172.16/12、192.168/16）")

    port = parsed.port or 80
    if not (1 <= port <= 65535):
        raise ValueError("連接埠（port）超出有效範圍（1-65535）")

    return f"http://{ip}:{port}"


def default_probe(url: str, timeout: float = 0.5) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Lightweight health probe that sends NO API keys or request body."""
    target_url = f"{url.rstrip('/')}/api/health"
    headers = {
        "Accept": "application/json",
        "User-Agent": "ElcAgentDiscovery/1.0",
    }
    req = urllib.request.Request(target_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return status, data
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        return exc.code, data
    except Exception:
        return 0, None


def get_local_subnet_hosts() -> List[str]:
    """Infer local IPv4 /24 subnet addresses via non-sending UDP socket trick."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"

    try:
        ip = ipaddress.IPv4Address(local_ip)
        if ip.is_loopback:
            return ["127.0.0.1"]
        # Generate /24 subnet hosts excluding network and broadcast
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return [str(h) for h in network.hosts()]
    except Exception:
        return ["127.0.0.1"]


def discover_server(
    last_known_url: Optional[str] = None,
    probe: Optional[Callable[[str, float], Tuple[int, Optional[Dict[str, Any]]]]] = None,
    subnet_hosts_provider: Optional[Callable[[], List[str]]] = None,
    port: int = 5000,
    udp_probe: Optional[Callable[[], List[str]]] = None,
    max_workers: int = 64,
    timeout: float = 0.5,
) -> DiscoveryResult:
    """Execute LAN discovery sequence according to D-30-08 and D-30-09."""
    actual_probe = probe or default_probe

    # Step (a): Test last known successful URL
    if last_known_url:
        normalized_url = last_known_url.rstrip("/")
        try:
            status, body = actual_probe(normalized_url, timeout)
            if status == 200 and isinstance(body, dict) and body.get("service") == EXPECTED_SERVICE_IDENTIFIER:
                return DiscoveryResult(
                    candidates=[normalized_url],
                    chosen_url=normalized_url,
                    needs_manual_entry=False,
                    source="last_known",
                )
        except Exception as exc:
            logger.debug("Last known URL probe failed: %s", exc)

    candidates: List[str] = []

    # Step (b): Optional UDP probe
    if udp_probe is not None:
        try:
            udp_candidates = udp_probe()
            if udp_candidates:
                candidates.extend(udp_candidates)
        except Exception as exc:
            logger.debug("UDP probe error: %s", exc)

    # Step (c): Subnet scan across port
    hosts_provider = subnet_hosts_provider or get_local_subnet_hosts
    subnet_hosts = hosts_provider()

    def _check_host(host: str) -> Optional[str]:
        target = f"http://{host}:{port}"
        try:
            status, body = actual_probe(target, timeout)
            if status == 200 and isinstance(body, dict) and body.get("service") == EXPECTED_SERVICE_IDENTIFIER:
                return target
        except Exception:
            pass
        return None

    workers = max(1, min(max_workers, 64))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_check_host, h): h for h in subnet_hosts}
        for future in as_completed(future_map):
            hit = future.result()
            if hit and hit not in candidates:
                candidates.append(hit)

    # Step (d): If candidates found, return them requiring confirmation (chosen_url is None)
    if candidates:
        return DiscoveryResult(
            candidates=candidates,
            chosen_url=None,
            needs_manual_entry=False,
            source="subnet" if udp_probe is None else "discovery",
        )

    # Step (e): All failed, request manual entry
    return DiscoveryResult(
        candidates=[],
        chosen_url=None,
        needs_manual_entry=True,
        source="none",
    )
