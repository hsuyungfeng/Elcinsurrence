"""Phase 31: 工作站心跳 (Presence)、在線判定與診所網段歸屬 (契約 §3, §5, §6).

提供：
- upsert_presence: 寫入/更新工作站心跳與狀態
- subnet_of: 來源 IP 轉 /24 (IPv4) 或 /64 (IPv6)
- in_clinic_subnet: 判斷是否為診所網段 (依 ELC_CLINIC_SUBNETS 或私有/loopback)
- notification_for_machine: 查詢工作站當前未終結循環之通知物件 (零 PHI)
- list_presence_grouped: 依 room_id 分組列出工作站狀態 (零 PHI)
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import re
from typing import Any, Dict, List, Optional

from elc_audit_engine.cycles.states import display_state
from elc_audit_engine.cycles.store import get_active_cycle, get_last_cycle

_RE_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_RE_ROOM_ID = re.compile(r"^[\w\-]{1,32}$", re.UNICODE)


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def subnet_of(ip: Optional[str]) -> Optional[str]:
    """將 IP 位址字串轉換為網段字串：IPv4 為 /24，IPv6 為 /64。無法解析回傳 None。"""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
        if addr.version == 4:
            net = ipaddress.ip_network(f"{addr}/24", strict=False)
            return str(net)
        elif addr.version == 6:
            net = ipaddress.ip_network(f"{addr}/64", strict=False)
            return str(net)
        return None
    except ValueError:
        return None


def in_clinic_subnet(subnet: Optional[str], configured: Optional[str] = None) -> bool:
    """判斷指定網段是否屬於診所網段。

    若 configured 未提供，則讀取環境變數 ELC_CLINIC_SUBNETS。
    若設定了 CIDR 清單，則檢查 subnet 是否落在其中；
    若未設定，則私有位址 (RFC 1918 / ULA) 與 loopback 均視為本診所。
    """
    if not subnet:
        return False
    try:
        net = ipaddress.ip_network(subnet.strip(), strict=False)
    except ValueError:
        return False

    cfg = configured if configured is not None else os.environ.get("ELC_CLINIC_SUBNETS", "")
    cfg = cfg.strip()
    if cfg:
        cidrs = [c.strip() for c in cfg.split(",") if c.strip()]
        for c in cidrs:
            try:
                allowed_net = ipaddress.ip_network(c, strict=False)
                if net.subnet_of(allowed_net):
                    return True
            except ValueError:
                continue
        return False

    return net.is_private or net.is_loopback


def validate_machine_id(machine_id: Any) -> bool:
    """驗證 machine_id 是否符合 UUID4 格式。"""
    if not isinstance(machine_id, str):
        return False
    return bool(_RE_UUID4.match(machine_id.strip()))


def validate_room_id(room_id: Any) -> bool:
    """驗證 room_id 格式：1-32 字元 Unicode 字母、數字、底線或連字號。可為 None。"""
    if room_id is None:
        return True
    if not isinstance(room_id, str):
        return False
    return bool(_RE_ROOM_ID.match(room_id))


def has_control_chars(s: str) -> bool:
    """檢查字串是否包含控制字元。"""
    return any(ord(c) < 32 or ord(c) == 127 for c in s)


def validate_presence_field(val: Any, max_len: int = 64) -> bool:
    """驗證一般字串欄位：非空時需為字串、不可超過長度限制且不可含控制字元。"""
    if val is None:
        return True
    if not isinstance(val, str):
        return False
    if len(val) > max_len:
        return False
    if has_control_chars(val):
        return False
    return True


def upsert_presence(
    store,
    *,
    machine_id: str,
    machine_name: Optional[str] = None,
    room_id: Optional[str] = None,
    bar_state: Optional[str] = None,
    soapvoice_state: Optional[str] = None,
    chunks_pending: Optional[int] = None,
    app_version: Optional[str] = None,
    client_ip: Optional[str] = None,
    caller_id: Optional[str] = None,
) -> bool:
    """寫入或更新工作站 presence 紀錄。

    回傳：
        is_first_seen: 若該 machine_id 首次出現回傳 True，否則 False。
    """
    client_subnet = subnet_of(client_ip)
    now_iso = _now_utc().isoformat()

    conn = store._connect()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM client_presence WHERE machine_id = ?", (machine_id,))
            first_seen = cur.fetchone() is None

            cur.execute(
                """
                INSERT INTO client_presence (
                    machine_id, machine_name, room_id, bar_state, soapvoice_state,
                    chunks_pending, app_version, client_subnet, caller_id, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    machine_name = excluded.machine_name,
                    room_id = excluded.room_id,
                    bar_state = excluded.bar_state,
                    soapvoice_state = excluded.soapvoice_state,
                    chunks_pending = excluded.chunks_pending,
                    app_version = excluded.app_version,
                    client_subnet = excluded.client_subnet,
                    caller_id = excluded.caller_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    machine_id,
                    machine_name,
                    room_id,
                    bar_state,
                    soapvoice_state,
                    chunks_pending,
                    app_version,
                    client_subnet,
                    caller_id,
                    now_iso,
                ),
            )
            return first_seen
    finally:
        conn.close()


def notification_for_machine(store, machine_id: str) -> Optional[Dict[str, Any]]:
    """取得工作站當前未終結循環之通知物件 (契約 §3)。

    嚴格僅包含 cycle_id, state, draft_id, draft_version 四個鍵；
    絕無 soap、transcript、extras、patient_name 等任何 PHI。
    若無未終結循環，回傳 None。
    """
    active = get_active_cycle(store, machine_id)
    if not active:
        return None

    cycle_id = active["cycle_id"]
    state = active["state"]
    draft_id = active.get("draft_id")
    draft_version = None

    if draft_id:
        try:
            d = store.get_soap_draft(draft_id)
            if d:
                draft_version = d.version
        except Exception:
            draft_version = None

    return {
        "cycle_id": cycle_id,
        "state": state,
        "draft_id": draft_id,
        "draft_version": draft_version,
    }


def list_presence_grouped(
    store,
    *,
    now: Optional[datetime.datetime] = None,
    offline_seconds: int = 15,
) -> Dict[str, Any]:
    """依 room_id 分組列出所有工作站狀態 (契約 §3, §5)。

    未設定 room_id 者歸入 room_id 為 None 的分組。
    """
    curr_now = now or _now_utc()
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT machine_id, machine_name, room_id, bar_state, soapvoice_state,
                   chunks_pending, app_version, client_subnet, caller_id, last_seen_at
            FROM client_presence
            ORDER BY room_id ASC, machine_name ASC, machine_id ASC
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # 按 room_id 分組暫存
    rooms_map: Dict[Optional[str], List[Dict[str, Any]]] = {}

    for row in rows:
        m_id = row["machine_id"]
        last_seen_str = row["last_seen_at"]
        try:
            last_seen_dt = datetime.datetime.fromisoformat(last_seen_str)
            if last_seen_dt.tzinfo is None:
                last_seen_dt = last_seen_dt.replace(tzinfo=datetime.timezone.utc)
            delta = (curr_now - last_seen_dt).total_seconds()
            online = delta <= offline_seconds
        except Exception:
            online = False

        active = get_active_cycle(store, m_id)
        if active:
            cycle_id = active["cycle_id"]
            cycle_state = active["state"]
            disp = display_state(cycle_state=cycle_state, last_cycle_state=None, online=online)
        else:
            cycle_id = None
            cycle_state = None
            last_c = get_last_cycle(store, m_id)
            last_state = last_c["state"] if last_c else None
            disp = display_state(cycle_state=None, last_cycle_state=last_state, online=online)

        c_subnet = row["client_subnet"]
        in_clinic = in_clinic_subnet(c_subnet)

        client_dict = {
            "machine_id": m_id,
            "machine_name": row["machine_name"],
            "room_id": row["room_id"],
            "display_state": disp,
            "cycle_id": cycle_id,
            "cycle_state": cycle_state,
            "last_seen_at": last_seen_str,
            "online": online,
            "client_subnet": c_subnet,
            "in_clinic_subnet": in_clinic,
        }

        r_id = row["room_id"]
        if r_id not in rooms_map:
            rooms_map[r_id] = []
        rooms_map[r_id].append(client_dict)

    # 排序：有設定 room_id 者以 room_id 升冪排列，None 放在最後
    sorted_rooms = []
    sorted_keys = sorted(rooms_map.keys(), key=lambda x: (x is None, x or ""))
    for k in sorted_keys:
        sorted_rooms.append({
            "room_id": k,
            "clients": rooms_map[k],
        })

    return {"rooms": sorted_rooms}
