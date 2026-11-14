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
DISCOVERY_PORT = 5002
DISCOVERY_MAGIC = b"ELC_DISCOVER_SERVER_V1"

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


def udp_probe(
    port: int = DISCOVERY_PORT,
    timeout: float = 1.0,
    socket_factory: Optional[Callable[[], socket.socket]] = None,
    broadcast_addrs: Optional[List[str]] = None,
) -> List[str]:
    """以 UDP 廣播探索區域網路內的伺服器 (C2, D-32-12)。

    送出魔術字串到 255.255.255.255 與各介面定向廣播，收集回覆直到逾時。
    回覆過濾：
    - 回覆非 JSON、service 不符、超過 2048 bytes 丟棄
    - url 主機非私有網段（或 loopback）丟棄
    - url 主機與回覆來源 IP 不同者丟棄
    - 絕不指定 bind 埠（由 OS 自動指派來源埠，避免 Windows 防火牆彈窗）
    """
    targets: List[str] = list(broadcast_addrs) if broadcast_addrs is not None else []
    if not targets:
        targets.append("255.255.255.255")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                local_ip = s.getsockname()[0]
            ip_obj = ipaddress.IPv4Address(local_ip)
            if not ip_obj.is_loopback:
                net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
                bcast = str(net.broadcast_address)
                if bcast not in targets:
                    targets.append(bcast)
        except Exception:
            pass

    found: List[str] = []
    sock = None
    try:
        sock = socket_factory() if socket_factory else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        sock.settimeout(timeout)

        for addr in targets:
            try:
                sock.sendto(DISCOVERY_MAGIC, (addr, port))
            except OSError as exc:
                logger.debug("Failed to send UDP probe to %s:%d: %s", addr, port, exc)

        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except (socket.timeout, TimeoutError, BlockingIOError):
                break
            except OSError as exc:
                logger.debug("recvfrom error: %s", exc)
                break

            if len(data) > 2048:
                continue

            try:
                raw_json = data.decode("utf-8")
                payload = json.loads(raw_json)
            except Exception:
                continue

            if not isinstance(payload, dict):
                continue

            if payload.get("service") != EXPECTED_SERVICE_IDENTIFIER:
                continue

            url = payload.get("url")
            if not url or not isinstance(url, str):
                continue

            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme.lower() != "http":
                continue

            hostname = parsed.hostname
            if not hostname:
                continue

            # url 主機必須與回覆來源 IP 相同
            sender_ip = addr[0]
            if hostname != sender_ip:
                continue

            try:
                ip_val = ipaddress.IPv4Address(hostname)
            except ValueError:
                continue

            is_private = ip_val.is_loopback or any(ip_val in net for net in _PRIVATE_NETWORKS)
            if not is_private:
                continue

            srv_port = parsed.port or 80
            norm_url = f"http://{hostname}:{srv_port}"
            if norm_url not in found:
                found.append(norm_url)

    except OSError as exc:
        logger.debug("udp_probe socket error: %s", exc)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    return found


def rediscover_and_verify(
    settings: Any,
    probe: Optional[Callable[[str, float], Tuple[int, Optional[Dict[str, Any]]]]] = None,
    udp_probe_fn: Optional[Callable[[], List[str]]] = None,
    subnet_hosts_provider: Optional[Callable[[], List[str]]] = None,
    port: int = 5000,
    timeout: float = 0.5,
) -> Tuple[Optional[str], str]:
    """C3: 位址自動復原，依院所代碼 (facility_code) 比對確認為同一家診所。

    回傳 (url, reason)，可能之 reason:
    - "unchanged": 既有 last_server_url 可通且 facility_code 相符
    - "recovered": 重新探索成功，找到相同 facility_code 之伺服器並更新 settings
    - "mismatch": 探索到的伺服器 facility_code 皆不同（不自動切換）
    - "needs_setup": settings.facility_code 為空（尚未完成首次設定）
    - "not_found": 完全找不到任何伺服器
    """
    fac_code = getattr(settings, "facility_code", "")
    if not fac_code:
        return None, "needs_setup"

    actual_probe = probe or default_probe

    # 1. 嘗試既有 last_server_url
    last_url = getattr(settings, "last_server_url", None)
    if last_url:
        try:
            status, body = actual_probe(last_url.rstrip("/"), timeout)
            if (
                status == 200
                and isinstance(body, dict)
                and body.get("service") == EXPECTED_SERVICE_IDENTIFIER
                and body.get("facility_code") == fac_code
            ):
                return last_url.rstrip("/"), "unchanged"
        except Exception as exc:
            logger.debug("Last known URL check failed: %s", exc)

    # 2. 重新探索
    actual_udp = udp_probe_fn if udp_probe_fn is not None else udp_probe
    disc_res = discover_server(
        last_known_url=None,
        probe=actual_probe,
        subnet_hosts_provider=subnet_hosts_provider,
        port=port,
        udp_probe=actual_udp,
        timeout=timeout,
    )

    if not disc_res.candidates:
        return None, "not_found"

    # 3. 逐一比對候選的 facility_code
    for cand in disc_res.candidates:
        cand_norm = cand.rstrip("/")
        try:
            status, body = actual_probe(cand_norm, timeout)
            if (
                status == 200
                and isinstance(body, dict)
                and body.get("service") == EXPECTED_SERVICE_IDENTIFIER
                and body.get("facility_code") == fac_code
            ):
                settings.last_server_url = cand_norm
                return cand_norm, "recovered"
        except Exception as exc:
            logger.debug("Candidate probe error for %s: %s", cand, exc)

    return None, "mismatch"

