"""院內網路信任模式（Phase 32-A：取代 API key 認證）。

**設計決策（使用者裁示 2026-11-13）**

本系統僅供診所區域網路內使用，不對外提供服務。醫師不應被要求輸入任何
金鑰——原本的 `X-API-Key` 機制既增加操作負擔，又因「院所代碼可當金鑰」
而實質上沒有保護力（院所代碼是公開資訊，且免認證端點就會回傳）。

因此改以**來源位址**作為唯一的信任判準：

- 請求來自 loopback 或伺服器所在子網 → 放行。
- 其他來源 → **一律拒絕 403**（不是降級成要求金鑰）。

**這等於把「院內網路」當成安全邊界**，其成立前提是訪客 Wi-Fi 與診間
網段已隔離（使用者已確認）。任何連上診間網段的裝置都能讀取病歷，這是
此設計刻意接受的取捨。

**信任範圍**：預設為伺服器所在網路介面的實際子網（而非整個 RFC 1918
位址空間）。`_is_private_ip` 式的寬鬆判定會信任一千七百萬個位址，包含
完全不相干的網段；收斂到實際子網才符合「院內」的語意。可用
`ELC_TRUSTED_SUBNETS` 覆寫。

**為何仍需 CSRF 防護**：金鑰移除後，瀏覽器成為新的攻擊面。醫師在診間
電腦瀏覽到惡意網頁時，該網頁可對 `http://<院內 IP>:5000` 發出寫入請求，
且瀏覽器會從院內位址發出——來源位址檢查無法分辨。故所有變更狀態的
請求必須另驗 `Origin`／`Sec-Fetch-Site`（見 `is_cross_site_request`）。
原生客戶端（ElcAgent／SoapVoice）不帶 `Origin`，不受影響。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket

logger = logging.getLogger(__name__)

#: 環境變數：覆寫信任網段（逗號分隔的 CIDR，例如 `192.168.1.0/24,10.0.5.0/24`）。
ENV_TRUSTED_SUBNETS = "ELC_TRUSTED_SUBNETS"

#: 拒絕訊息（固定字串，不洩漏信任網段的內容）。
UNTRUSTED_MESSAGE = "本服務僅限院內網路使用，您的來源位址不在信任範圍內"

#: 跨站請求拒絕訊息。
CROSS_SITE_MESSAGE = "拒絕跨站請求：請直接開啟本系統頁面操作"

#: Host 標頭不合法的拒絕訊息。
BAD_HOST_MESSAGE = "不允許的 Host"

#: 會變更狀態、需檢查跨站來源的 HTTP 方法。
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: `Sec-Fetch-Site` 中屬於同源／同站的值（瀏覽器自動帶，無法由網頁偽造）。
_SAME_SITE_VALUES = frozenset({"same-origin", "same-site", "none"})


class TrustConfigError(RuntimeError):
    """信任網段設定格式錯誤（啟動期 fail-fast）。

    設定錯誤不得降級為「信任所有來源」——那會讓本服務對全網開放病歷。
    """


def parse_trusted_subnets(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析 `ELC_TRUSTED_SUBNETS`（逗號分隔 CIDR）。

    Args:
        raw: 例如 `"192.168.1.0/24, 10.0.5.0/24"`。

    Returns:
        網段清單。

    Raises:
        TrustConfigError: 任一項無法解析，或解析結果為空。
    """
    items = [item.strip() for item in raw.split(",") if item.strip()]
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in items:
        try:
            # strict=False：允許 `192.168.1.5/24` 這種帶主機位的寫法，
            # 部署者從 `ip addr` 複製時常是這個形式。
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise TrustConfigError(
                f"{ENV_TRUSTED_SUBNETS} 設定錯誤：{item!r} 不是合法的網段（CIDR）寫法"
            ) from exc
    if not networks:
        raise TrustConfigError(f"{ENV_TRUSTED_SUBNETS} 設定錯誤：未解析出任何網段")
    return networks


def detect_local_subnets(
    local_ip: str | None = None,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """偵測伺服器所在的子網（預設信任範圍）。

    以不實際送出封包的 UDP socket 取得對外介面位址（與
    `deploy/windows_agent/discovery.py` 同手法），再推得 /24 子網。

    **為何固定 /24**：診所網路幾乎都是家用／小型商用分享器的 /24；由
    socket 無法取得真實遮罩（需平台相依的 netlink／GetAdaptersInfo）。
    /24 是安全的保守估計：猜太小只會讓少數機器需要手動加
    `ELC_TRUSTED_SUBNETS`（失敗時看得見、可修正），猜太大則會靜默信任
    不該信任的網段。遮罩非 /24 的院所請明示設定。

    Args:
        local_ip: 直接指定本機位址（測試用）；None 時自動偵測。

    Returns:
        信任網段清單；偵測失敗時只回傳 loopback（服務仍可在本機使用）。
    """
    if local_ip is None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # 不會真的送出封包，只讓 kernel 選出對外介面。
                s.connect(("10.255.255.255", 1))
                local_ip = s.getsockname()[0]
        except OSError as exc:
            logger.warning("無法偵測本機網段（%s）；僅信任本機 loopback", exc)
            return []

    try:
        ip = ipaddress.ip_address(local_ip)
    except ValueError:
        logger.warning("偵測到的本機位址 %r 無法解析；僅信任本機 loopback", local_ip)
        return []

    if ip.is_loopback:
        # 只有 loopback 介面（未接網路）：不擴張信任範圍。
        return []

    return [ipaddress.ip_network(f"{ip}/24", strict=False)]


def load_trusted_subnets(
    raw: str | None = None,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """載入信任網段：有 `ELC_TRUSTED_SUBNETS` 用它，否則自動偵測。

    Args:
        raw: 直接提供的設定字串（測試用）；None 時讀環境變數。

    Returns:
        信任網段清單（loopback 一律放行，不含在此清單內）。

    Raises:
        TrustConfigError: 明示的設定格式錯誤。
    """
    if raw is None:
        raw = os.environ.get(ENV_TRUSTED_SUBNETS)
    if raw and raw.strip():
        return parse_trusted_subnets(raw)
    return detect_local_subnets()


def is_trusted_source(
    remote_addr: str | None,
    trusted_subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """判斷來源位址是否可信（loopback 或信任網段內）。

    Args:
        remote_addr: `request.remote_addr`。
        trusted_subnets: `load_trusted_subnets()` 的結果。

    Returns:
        True 表示放行。位址缺失或無法解析時回傳 False（保守拒絕）。
    """
    if not remote_addr:
        return False
    try:
        ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    if ip.is_loopback:
        return True

    return any(ip in net for net in trusted_subnets)


def caller_id_for(remote_addr: str | None) -> str:
    """產生審計日誌用的呼叫方識別。

    不再有金鑰可辨識身分，改以來源位址標記「哪一台電腦」。客戶端另在
    請求中帶 `machine_id`／`room_id`，由各端點自行記錄；本函式只負責
    網路層的識別。

    Args:
        remote_addr: `request.remote_addr`。

    Returns:
        例如 `"lan:192.168.1.42"`；位址缺失時回傳 `"lan:unknown"`。
    """
    return f"lan:{remote_addr}" if remote_addr else "lan:unknown"


def is_cross_site_request(
    method: str,
    origin: str | None,
    sec_fetch_site: str | None,
    host_url_root: str,
) -> bool:
    """判斷是否為應拒絕的跨站寫入請求（CSRF 防護）。

    只檢查會變更狀態的方法；GET／HEAD 不在範圍內（本服務的讀取端點不
    應有副作用）。

    判定順序：

    1. `Sec-Fetch-Site`（現代瀏覽器自動附加，網頁無法偽造）為權威依據。
       `same-origin`／`same-site` 放行；`none`（使用者直接輸入網址或書籤）
       放行；`cross-site` 拒絕。
    2. 無 `Sec-Fetch-Site` 時退回比對 `Origin` 與本服務的 URL root。
    3. 兩者都沒有 → 放行：原生客戶端（ElcAgent／SoapVoice，使用
       `urllib`）不會帶這兩個標頭。瀏覽器**一定**會在跨站寫入時帶
       `Origin`，故「兩者皆無」可安全視為非瀏覽器來源。

    Args:
        method: HTTP 方法。
        origin: `Origin` 標頭。
        sec_fetch_site: `Sec-Fetch-Site` 標頭。
        host_url_root: `request.host_url`（例如 `http://192.168.1.50:5000/`）。

    Returns:
        True 表示應拒絕。
    """
    if method.upper() not in UNSAFE_METHODS:
        return False

    if sec_fetch_site:
        return sec_fetch_site.strip().lower() not in _SAME_SITE_VALUES

    if origin:
        # 去掉尾端斜線後比對 scheme://host:port。
        return origin.rstrip("/").lower() != host_url_root.rstrip("/").lower()

    # 非瀏覽器來源（原生客戶端）。
    return False


def is_allowed_host(host: str | None) -> bool:
    """驗證 `Host` 標頭，防 DNS rebinding。

    **為何來源位址檢查不足以取代此項**：DNS rebinding 讓惡意網域解析到
    院內 IP，瀏覽器因此連上本服務——請求來源位址是**可信的院內位址**，
    `is_trusted_source` 無法分辨。CSRF 檢查能擋住寫入，但 `GET` 讀取
    （病歷清單、佐證檔）不在 CSRF 範圍內，仍會外洩。故必須另驗 Host：
    攻擊者的網域名稱不會是私有 IP 字面值或 `.local` 形式。

    放行條件（任一）：

    - IP 字面值且為 loopback 或私有位址（涵蓋所有院內部署形式）。
    - `localhost`。
    - 以 `.local` 結尾的主機名稱（mDNS，見改進計畫 C2）。
    - 本機主機名稱（診所可能以主機名稱連線）。

    刻意**不**提供環境變數白名單：原本的 `ELC_ALLOWED_HOSTS` 需要部署者
    手填 IP，換分享器或 DHCP 重發就全院連不上（改進計畫 A5／C 的根因）。
    以形式判定即可達到同等防護且無須維護。

    Args:
        host: `request.host`（可能含埠號）。

    Returns:
        True 表示放行。
    """
    if not host:
        return False

    raw = host.strip().lower()
    # 去掉埠號：IPv6 字面值寫作 `[::1]:5000`，需先判斷是否為方括號形式。
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
    """回傳人類可讀的信任範圍描述（供啟動日誌與系統狀態頁顯示）。

    安裝人員必須看得見「目前信任哪些網段」，才能確認訪客網段未被誤納。
    """
    if not trusted_subnets:
        return "僅本機（127.0.0.1）"
    return "、".join(str(net) for net in trusted_subnets) + "（及本機 127.0.0.1）"
