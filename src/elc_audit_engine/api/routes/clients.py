"""Phase 31: 多連線監控 (Clients / Heartbeat) API (契約 §3, §5, §6)."""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict

from flask import Blueprint, current_app, g, jsonify, request, send_from_directory

from elc_audit_engine import audit_log
from elc_audit_engine.api.context import case_store
from elc_audit_engine.cycles.presence import (
    list_presence_grouped,
    notification_for_machine,
    upsert_presence,
    validate_machine_id,
    validate_presence_field,
    validate_room_id,
)

bp = Blueprint("clients", __name__)


def _offline_seconds() -> int:
    val = os.environ.get("ELC_CLIENT_OFFLINE_SECONDS")
    if val:
        try:
            return max(5, int(val))
        except ValueError:
            pass
    return 15


@bp.route("/api/clients/heartbeat", methods=["POST"])
def client_heartbeat():
    """工作站心跳回報與通知搭便車 (契約 §3, §6)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "請求必須為 JSON 物件"}), 422

    machine_id = body.get("machine_id")
    if not validate_machine_id(machine_id):
        return jsonify({"status": "error", "message": "machine_id 格式不合 (需為 UUID4)"}), 422

    room_id = body.get("room_id")
    if not validate_room_id(room_id):
        return jsonify({"status": "error", "message": "room_id 格式不合法"}), 422

    machine_name = body.get("machine_name")
    bar_state = body.get("bar_state")
    soapvoice_state = body.get("soapvoice_state")
    app_version = body.get("app_version")

    for name, val in [
        ("machine_name", machine_name),
        ("bar_state", bar_state),
        ("soapvoice_state", soapvoice_state),
        ("app_version", app_version),
    ]:
        if not validate_presence_field(val, max_len=64):
            return jsonify({"status": "error", "message": f"{name} 超過 64 字元或含控制字元"}), 422

    chunks_pending = body.get("chunks_pending")
    if chunks_pending is not None:
        if not isinstance(chunks_pending, int) or chunks_pending < 0:
            return jsonify({"status": "error", "message": "chunks_pending 需為非負整數"}), 422

    store = case_store()
    caller_id = getattr(g, "caller_id", None)
    client_ip = request.remote_addr

    first_seen = upsert_presence(
        store,
        machine_id=machine_id,
        machine_name=machine_name,
        room_id=room_id,
        bar_state=bar_state,
        soapvoice_state=soapvoice_state,
        chunks_pending=chunks_pending,
        app_version=app_version,
        client_ip=client_ip,
        caller_id=caller_id,
    )

    if first_seen:
        detail: Dict[str, Any] = {"action": "client_first_seen", "machine_id": machine_id}
        if room_id:
            detail["room_id"] = room_id
        try:
            audit_log.record_access(
                caller_id=caller_id or "anonymous",
                method="POST",
                path=request.path,
                status=200,
                detail=detail,
            )
        except Exception as exc:
            current_app.logger.error("首次工作站審計記錄寫入失敗: %s", exc)

    notify = notification_for_machine(store, machine_id)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return jsonify({
        "status": "ok",
        "server_time": now_iso,
        "notify": notify,
    }), 200


@bp.route("/api/clients", methods=["GET"])
def list_clients():
    """依 room_id 分組列出所有工作站 (契約 §3, §5)."""
    store = case_store()
    grouped = list_presence_grouped(store, offline_seconds=_offline_seconds())
    return jsonify(grouped), 200


@bp.route("/clients", methods=["GET"])
def monitor_page():
    """多連線監控靜態頁 (契約 §3)."""
    resp = send_from_directory(current_app.static_folder, "clients.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
