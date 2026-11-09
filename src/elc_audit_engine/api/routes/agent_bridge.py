"""Windows Agent 心跳與狀態 API（Phase 29 §7.2、§7.3）。

提供端點：
- POST /api/agent/heartbeat  Agent 定期回報心跳（含 agent_id、版號、HIS 狀態、時間戳）
- GET  /api/agent/status     查詢所有 Agent 連線與在線狀態（>30 分鐘無心跳標記離線）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request

from ..context import caller_id, case_store
from ..errors import ApiError

bp = Blueprint("agent_bridge", __name__)


def _json_object() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求內容必須為 JSON 物件")
    return data


@bp.route("/api/agent/heartbeat", methods=["POST"])
def agent_heartbeat():
    """接收 Windows Agent 心跳。"""
    data = _json_object()
    agent_id = str(data.get("agent_id") or caller_id() or "").strip()
    if not agent_id:
        raise ApiError("缺少 agent_id", status=422)

    version = str(data.get("version") or "")
    his_status = str(data.get("his_status") or "")
    client_timestamp = str(data.get("timestamp") or "")

    store = case_store()
    store.record_agent_heartbeat(
        agent_id=agent_id,
        version=version,
        his_status=his_status,
        client_timestamp=client_timestamp,
    )

    server_time = datetime.now(UTC).isoformat()
    return jsonify({"status": "ok", "agent_id": agent_id, "server_time": server_time}), 200


@bp.route("/api/agent/status", methods=["GET"])
def get_agent_status():
    """列出註冊 Agent 之最後心跳與是否在線。"""
    store = case_store()
    agents = store.list_agent_heartbeats()
    return jsonify({"status": "success", "count": len(agents), "agents": agents}), 200
