"""Phase 32 Plan 13: 網頁版初次設定 (Setup) 與診間清單 API (D2).

(D-32-19)
提供：
- GET /setup: 初次設定頁 (static/setup.html)
- GET /api/setup/state: 取得設定狀態 (needs_setup, facility, rooms, write_allowed, write_hint)
- POST /api/setup: 儲存初次設定 (院所代碼、名稱、醫師姓名、診間清單)
- GET /api/rooms: 取得診間清單供客戶端精靈下拉使用
"""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from elc_audit_engine.cycles.presence import validate_room_id

bp = Blueprint("setup", __name__)

_RE_FACILITY_CODE = re.compile(r"^\d{10}$")


def _get_facility_path() -> Path:
    from config.settings import FACILITY_CONFIG_PATH
    return Path(FACILITY_CONFIG_PATH)


def _load_facility_raw() -> Dict[str, Any]:
    path = _get_facility_path()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _is_write_allowed(remote_addr: Optional[str]) -> bool:
    """判斷來源是否允許寫入管理設定 (D-32-19 僅限 loopback)。"""
    if not remote_addr:
        return False
    try:
        return ipaddress.ip_address(remote_addr).is_loopback
    except ValueError:
        return False


@bp.route("/setup", methods=["GET"])
def setup_page():
    """傳回初次設定靜態網頁。"""
    static_folder = current_app.static_folder or "static"
    return send_from_directory(static_folder, "setup.html")


@bp.route("/api/setup/state", methods=["GET"])
def setup_state():
    """回傳目前設定狀態，供設定頁判斷是否啟用表單及提示。"""
    cfg = _load_facility_raw()
    code = str(cfg.get("code") or "").strip()
    needs_setup = not bool(code)

    write_allowed = _is_write_allowed(request.remote_addr)
    write_hint = "" if write_allowed else "此設定只能在伺服器本機修改，請至伺服器主機開啟此頁面完成設定。"

    facility_info = {
        "code": code,
        "name": str(cfg.get("name") or "").strip(),
        "physician_name": str(cfg.get("physician_name") or "").strip(),
    }
    rooms = cfg.get("rooms", [])
    if not isinstance(rooms, list):
        rooms = []

    return jsonify({
        "needs_setup": needs_setup,
        "facility": facility_info,
        "rooms": rooms,
        "write_allowed": write_allowed,
        "write_hint": write_hint,
    })


@bp.route("/api/setup", methods=["POST"])
def save_setup():
    """儲存初次設定 (院所代碼、名稱、醫師姓名、診間清單)。"""
    # 權限檢查由 security.py 中的 ADMIN_WRITE_ENDPOINTS 攔截 (非本機回 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "請求必須為 JSON 物件"}), 422

    code = str(body.get("code") or "").strip()
    name = str(body.get("name") or "").strip()
    physician_name = str(body.get("physician_name") or "").strip()
    rooms = body.get("rooms")

    errors: Dict[str, str] = {}

    if not _RE_FACILITY_CODE.match(code):
        errors["code"] = "院所代碼必須為 10 位數字"

    if not name or len(name) > 64:
        errors["name"] = "院所名稱為必填且不可超過 64 字"

    if len(physician_name) > 64:
        errors["physician_name"] = "醫師姓名不可超過 64 字"

    if not isinstance(rooms, list) or len(rooms) < 1 or len(rooms) > 30:
        errors["rooms"] = "診間數量必須在 1 至 30 間之間"
    else:
        seen_ids = set()
        seen_names = set()
        validated_rooms = []
        for idx, r in enumerate(rooms):
            if not isinstance(r, dict):
                errors["rooms"] = f"第 {idx+1} 間診間資料格式不合"
                break
            rid = str(r.get("id") or "").strip()
            rname = str(r.get("name") or "").strip()

            if not validate_room_id(rid):
                errors["rooms"] = f"診間代號 '{rid}' 格式不合 (僅限英數字與橫線底線，1-32 字元)"
                break
            if not rname or len(rname) > 64:
                errors["rooms"] = f"診間名稱 '{rname}' 為必填且不可超過 64 字"
                break

            if rid in seen_ids:
                errors["rooms"] = f"診間代號 '{rid}' 重複"
                break
            if rname in seen_names:
                errors["rooms"] = f"診間名稱 '{rname}' 重複"
                break

            seen_ids.add(rid)
            seen_names.add(rname)
            validated_rooms.append({"id": rid, "name": rname})

    if errors:
        return jsonify({
            "status": "error",
            "message": "輸入資料有誤，請依提示更正",
            "errors": errors,
        }), 422

    # 原子寫入 facility.json (保留既有其他欄位)
    current_cfg = _load_facility_raw()
    current_cfg["code"] = code
    current_cfg["name"] = name
    if physician_name:
        current_cfg["physician_name"] = physician_name
    elif "physician_name" in current_cfg and not physician_name:
        current_cfg["physician_name"] = ""
    current_cfg["rooms"] = validated_rooms

    target_path = _get_facility_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(current_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp_path), str(target_path))

    return jsonify({
        "status": "ok",
        "message": "設定已儲存",
        "facility": {
            "code": code,
            "name": name,
            "physician_name": physician_name,
            "rooms": validated_rooms,
        },
    }), 200


@bp.route("/api/rooms", methods=["GET"])
def get_rooms():
    """回傳診間清單，供 Windows 客戶端首次設定精靈使用。"""
    cfg = _load_facility_raw()
    rooms = cfg.get("rooms", [])
    if not isinstance(rooms, list):
        rooms = []
    return jsonify({"rooms": rooms})
