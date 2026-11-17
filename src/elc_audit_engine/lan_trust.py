"""院內網路信任模式（Phase 32-A & Phase 32-06：取代 API key 認證）。

**設計決策（使用者裁示 2026-11-13 & 2026-11-14 D-32-16..D-32-18）**

本系統僅供診所區域網路內使用，不對外提供服務。醫師不應被要求輸入任何
金鑰——原本的 `X-API-Key` 機制既增加操作負擔，又因「院所代碼可當金鑰」
而實質上沒有保護力。

因此改以**來源位址**作為唯一的信任判準：
- 請求來自 loopback 或伺服器所在子網 → 放行。
- 其他來源 → **一律拒絕 403**。
- 跨站 GET 請求（Sec-Fetch-Site: cross-site）一律拒絕 403（D-32-18）。
- 網段偵測讀取真實遮罩，自動排除 VPN/虛擬介面，多介面時由安裝確認（D-32-16, D-32-17）。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import subprocess
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 環境變數：覆寫信任網段（逗號分隔的 CIDR，例如 `192.168.1.0/24,10.0.5.0/24`）。
ENV_TRUSTED_SUBNETS = "ELC_TRUSTED_SUBNETS"
ENV_TRUSTED_INTERFACE = "ELC_TRUSTED_INTERFACE"

#: 拒絕訊息（固定字串，不洩漏信任網段的內容）。
UNTRUSTED_MESSAGE = "本服務僅限院內網路使用，您的來源位址不在信任範圍內"

#: 跨站請求拒絕訊息。
CROSS_SITE_MESSAGE = "拒絕跨站請求：請直接開啟本系統頁面操作"

#: Host 標頭不合法的拒絕訊息。
BAD_HOST_MESSAGE = "不允許的 Host"

#: 會變更狀態、需檢查跨站來源的 HTTP 方法。
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: `Sec-Fetch-Site` 中屬於同源／同站的值。
_SAME_SITE_VALUES = frozenset({"same-origin", "same-site", "none"})

#: 排除的虛擬/VPN 介面名稱前綴（D-32-17）。
EXCLUDED_IFACE_PREFIXES = (
    "lo",
    "tun",
    "tap",
    "ppp",
    "wg",
    "docker",
    "br-",
    "veth",
    "virbr",
    "zt",
    "tailscale",
)


class TrustConfigError(RuntimeError):
    """信任網段設定格式錯誤（啟動期 fail-fast）。"""


def parse_trusted_subnets(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析 `ELC_TRUSTED_SUBNETS`（逗號分隔 CIDR）。"""
    items = [item.strip() for item in raw.split(",") if item.strip()]
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in items:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise TrustConfigError(
                f"{ENV_TRUSTED_SUBNETS} 設定錯誤：{item!r} 不是合法的網段（CIDR）寫法"
            ) from exc
    if not networks:
        raise TrustConfigError(f"{ENV_TRUSTED_SUBNETS} 設定錯誤：未解析出任何網段")
    return networks


def list_candidate_interfaces(
    ip_json_provider: Optional[Callable[[], str]] = None,
) -> List[Dict[str, Any]]:
    """列舉實體網路介面候選清單（排除 loopback 與虛擬/VPN 介面，D-32-17）。

    回傳：[{"name": str, "address": str, "prefixlen": int, "network": str}]
    """
    raw_json = ""
    if ip_json_provider is not None:
        try:
            raw_json = ip_json_provider()
        except Exception as exc:
            logger.debug("ip_json_provider failed: %s", exc)
            return []
    else:
        try:
            proc = subprocess.run(
                ["ip", "-j", "-4", "addr"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0:
                raw_json = proc.stdout
        except Exception as exc:
            logger.debug("Failed to run ip -j -4 addr: %s", exc)
            return []

    if not raw_json or not raw_json.strip():
        return []

    try:
        data = json.loads(raw_json)
        if not isinstance(data, list):
            return []
    except Exception as exc:
        logger.warning("Failed to parse ip -j JSON output: %s", exc)
        return []

    candidates: List[Dict[str, Any]] = []
    for iface in data:
        if not isinstance(iface, dict):
            continue
        ifname = iface.get("ifname", "")
        flags = iface.get("flags", [])
        if "LOOPBACK" in flags or ifname == "lo":
            continue

        # 排除虛擬與 VPN 介面
        if any(ifname.startswith(pfx) for pfx in EXCLUDED_IFACE_PREFIXES):
            continue

        addr_info = iface.get("addr_info", [])
        if not isinstance(addr_info, list):
            continue

        for addr in addr_info:
            if not isinstance(addr, dict):
                continue
            local = addr.get("local")
            prefixlen = addr.get("prefixlen")
            if not local or prefixlen is None:
                continue

            try:
                ip = ipaddress.ip_address(local)
            except ValueError:
                continue

            # 只納入私有 IPv4，排除 loopback 與 link-local
            if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                net = ipaddress.ip_network(f"{local}/{prefixlen}", strict=False)
                candidates.append({
                    "name": ifname,
                    "address": str(ip),
                    "prefixlen": int(prefixlen),
                    "network": str(net),
                })

    return candidates


def detect_local_subnets(
    local_ip: Optional[str] = None,
    interfaces_provider: Optional[Callable[[], str]] = None,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """偵測伺服器所在的子網（預設信任範圍，D-32-16 & D-32-17）。"""
    # 測試注入或相容既有調用
    if local_ip is not None:
        try:
            ip = ipaddress.ip_address(local_ip)
        except ValueError:
            logger.warning("偵測到的本機位址 %r 無法解析；僅信任本機 loopback", local_ip)
            return []
        if ip.is_loopback:
            return []
        return [ipaddress.ip_network(f"{ip}/24", strict=False)]

    candidates = list_candidate_interfaces(interfaces_provider)

    if len(candidates) == 1:
        c = candidates[0]
        if c["prefixlen"] != 24:
            logger.warning(
                "偵測到非 /24 遮罩子網：%s（需要安裝人員確認，D-32-16）",
                c["network"],
            )
        return [ipaddress.ip_network(c["network"])]

    elif len(candidates) > 1:
        env_iface = os.environ.get(ENV_TRUSTED_INTERFACE, "").strip()
        if env_iface:
            matched = [c for c in candidates if c["name"] == env_iface]
            if matched:
                return [ipaddress.ip_network(matched[0]["network"])]

        # 多個介面若位於同一網段（例如有線與無線同接一台分享器），不構成歧義，直接採用。
        unique_networks = {c["network"] for c in candidates}
        if len(unique_networks) == 1:
            return [ipaddress.ip_network(unique_networks.pop())]

        # D-32-17: 多個不同網段時由安裝人員於 install.sh 中選擇並寫入 ELC_TRUSTED_SUBNETS。
        # 未指定時 fail-closed（回傳空清單，僅信任 loopback）
        logger.warning(
            "偵測到多個候選網路介面（%s），未指定 %s 或 %s；退回僅信任本機 loopback",
            [c["name"] for c in candidates],
            ENV_TRUSTED_INTERFACE,
            ENV_TRUSTED_SUBNETS,
        )
        return []

    # 候選清單為空時，退回 UDP socket 探測（相容非 Linux 或無 ip 工具）
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            sock_ip = s.getsockname()[0]
            ip = ipaddress.ip_address(sock_ip)
            if not ip.is_loopback and ip.is_private:
                return [ipaddress.ip_network(f"{ip}/24", strict=False)]
    except OSError as exc:
        logger.warning("無法偵測本機網段（%s）；僅信任本機 loopback", exc)

    return []


def load_trusted_subnets(
    raw: Optional[str] = None,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """載入信任網段：有 `ELC_TRUSTED_SUBNETS` 用它，否則自動偵測。"""
    if raw is None:
        raw = os.environ.get(ENV_TRUSTED_SUBNETS)
    if raw and raw.strip():
        return parse_trusted_subnets(raw)
    return detect_local_subnets()


def is_trusted_source(
    remote_addr: Optional[str],
    trusted_subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """判斷來源位址是否可信（loopback 或信任網段內）。"""
    if not remote_addr:
        return False
    try:
        ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    if ip.is_loopback:
        return True

    return any(ip in net for net in trusted_subnets)


def caller_id_for(remote_addr: Optional[str]) -> str:
    """產生審計日誌用的呼叫方識別。"""
    return f"lan:{remote_addr}" if remote_addr else "lan:unknown"


def is_cross_site_request(
    method: str,
    origin: Optional[str],
    sec_fetch_site: Optional[str],
    host_url_root: str,
) -> bool:
    """判斷是否為應拒絕的跨站寫入請求（CSRF 防護）。"""
    if method.upper() not in UNSAFE_METHODS:
        return False

    if sec_fetch_site:
        return sec_fetch_site.strip().lower() not in _SAME_SITE_VALUES

    if origin:
        return origin.rstrip("/").lower() != host_url_root.rstrip("/").lower()

    return False


def is_cross_site_read(method: str, sec_fetch_site: Optional[str]) -> bool:
    """D-32-18: 跨站 GET 請求（帶 Sec-Fetch-Site: cross-site）一律拒絕。"""
    if method.upper() in ("GET", "HEAD"):
        if sec_fetch_site and sec_fetch_site.strip().lower() == "cross-site":
            return True
    return False


def is_allowed_host(host: Optional[str]) -> bool:
    """驗證 `Host` 標頭，防 DNS rebinding。"""
    if not host:
        return False

    raw = host.strip().lower()
    if raw.startswith("["):
        hostname = raw.split("]", 1)[0].lstrip("[")
    else:
        hostname = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw

    if not hostname:
        return False

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return ip.is_loopback or ip.is_private

    if hostname == "localhost" or hostname.endswith(".local"):
        return True

    try:
        own_name = socket.gethostname().lower()
    except OSError:
        return False
    return hostname == own_name or hostname == f"{own_name}.local"


def describe_trust(
    trusted_subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> str:
    """回傳人類可讀的信任範圍描述。"""
    if not trusted_subnets:
        return "僅本機（127.0.0.1）"
    return "、".join(str(net) for net in trusted_subnets) + "（及本機 127.0.0.1）"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Describe LAN trust configuration")
    parser.add_argument("--describe", action="store_true", help="Output JSON description")
    args = parser.parse_args()

    if args.describe:
        raw_env = os.environ.get(ENV_TRUSTED_SUBNETS)
        configured = (
            [str(n) for n in parse_trusted_subnets(raw_env)]
            if (raw_env and raw_env.strip())
            else None
        )
        candidates = list_candidate_interfaces()
        detected = [str(n) for n in detect_local_subnets()]
        needs_confirmation = (
            configured is None
            and (
                len(candidates) > 1
                or any(c.get("prefixlen") != 24 for c in candidates)
                or (len(candidates) > 0 and len(detected) == 0)
            )
        )
        result = {
            "configured": configured,
            "detected": detected,
            "candidates": candidates,
            "needs_confirmation": bool(needs_confirmation),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
