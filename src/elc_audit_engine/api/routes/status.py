"""System status and deep health check routes (Phase 32 Plan 32-08, D3, D5, D6)."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, send_from_directory
import requests

from elc_audit_engine.capacity import (
    DEFAULT_RED_DAYS,
    DEFAULT_YELLOW_DAYS,
    classify_runway,
    days_until_full,
    directory_size_bytes,
)
from ..context import case_store

logger = logging.getLogger("elc_audit_engine.api.routes.status")

bp = Blueprint("status", __name__)


def _probe_engine() -> Dict[str, Any]:
    return {
        "key": "engine",
        "name": "審核引擎",
        "color": "green",
        "message": "電子抽審引擎運作中",
    }


def _probe_llm() -> Dict[str, Any]:
    custom_probe = current_app.config.get("ELC_LLM_PROBE")
    if callable(custom_probe):
        try:
            is_ok = bool(custom_probe())
        except Exception as exc:
            logger.debug("Custom LLM probe exception: %s", exc)
            is_ok = False
    else:
        try:
            from config import settings

            base_url = getattr(settings, "LLAMA_CPP_BASE_URL", "http://localhost:8080")
            r = requests.get(f"{base_url}/health", timeout=1.5)
            is_ok = r.status_code == 200
        except Exception:
            is_ok = False

    if is_ok:
        return {
            "key": "llm",
            "name": "本機 AI 模型",
            "color": "green",
            "message": "本機 AI 模型運作中",
        }
    else:
        return {
            "key": "llm",
            "name": "本機 AI 模型",
            "color": "red",
            "message": "AI 審核暫停中，其餘功能正常",
        }


def _probe_disk() -> Dict[str, Any]:
    data_dir = Path("data")
    used_bytes = directory_size_bytes(data_dir)

    try:
        usage = shutil.disk_usage(data_dir if data_dir.exists() else ".")
        free_bytes = usage.free
    except OSError:
        free_bytes = 0

    samples_path = Path(
        current_app.config.get("ELC_CAPACITY_SAMPLES_FILE", "logs/capacity-samples.json")
    )
    samples: List[tuple[str, int]] = []
    if samples_path.is_file():
        try:
            content = json.loads(samples_path.read_text(encoding="utf-8"))
            if isinstance(content, list):
                samples = [(s["date"], s["bytes"]) for s in content if "date" in s and "bytes" in s]
        except Exception as exc:
            logger.warning("Failed to parse capacity samples: %s", exc)

    runway = days_until_full(samples, free_bytes)
    color = classify_runway(runway)

    used_mb = used_bytes // (1024 * 1024)
    free_gb = free_bytes / (1024 * 1024 * 1024)

    if runway is not None:
        msg = f"目前資料用量 {used_mb}MB，預估磁碟可用 {int(runway)} 天"
    else:
        msg = f"目前資料用量 {used_mb}MB，磁碟可用 {free_gb:.1f}GB（取樣建立中）"
        if color == "unknown":
            color = "green" if free_gb >= 10.0 else "yellow"

    return {
        "key": "disk",
        "name": "磁碟空間與成長預警",
        "color": color,
        "message": msg,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "runway_days": runway,
    }


def _probe_database() -> Dict[str, Any]:
    try:
        store = case_store()
        store.list_all(limit=1)
        return {
            "key": "database",
            "name": "資料庫",
            "color": "green",
            "message": "資料庫連線正常",
        }
    except Exception as exc:
        return {
            "key": "database",
            "name": "資料庫",
            "color": "red",
            "message": f"資料庫讀取異常: {exc}",
        }


def _probe_backup() -> Dict[str, Any]:
    status_file = Path(
        current_app.config.get("ELC_BACKUP_STATUS_FILE", "logs/backup-status.json")
    )
    if status_file.is_file():
        try:
            bdata = json.loads(status_file.read_text(encoding="utf-8"))
            last_at = bdata.get("last_backup_at", "")
            return {
                "key": "backup",
                "name": "資料備份",
                "color": "green",
                "message": f"最近備份正常 ({last_at})",
            }
        except Exception:
            return {
                "key": "backup",
                "name": "資料備份",
                "color": "yellow",
                "message": "備份紀錄讀取異常",
            }
    else:
        return {
            "key": "backup",
            "name": "資料備份",
            "color": "yellow",
            "message": "尚未建立備份紀錄",
        }


def _probe_clients() -> Dict[str, Any]:
    try:
        from .clients import list_clients

        resp = list_clients()
        data = resp.get_json() if hasattr(resp, "get_json") else {}
        rooms = data.get("rooms", []) if isinstance(data, dict) else []
        active_rooms = len(rooms)
        if active_rooms > 0:
            return {
                "key": "clients",
                "name": "各診間連線",
                "color": "green",
                "message": f"{active_rooms} 個診間連線運作中",
            }
        else:
            return {
                "key": "clients",
                "name": "各診間連線",
                "color": "green",
                "message": "尚無診間連線（待命中）",
            }
    except Exception as exc:
        return {
            "key": "clients",
            "name": "各診間連線",
            "color": "yellow",
            "message": f"診間狀態檢查例外: {exc}",
        }


def collect_system_status() -> Dict[str, Any]:
    """Execute all 6 checks and compute overall health status."""
    checks = [
        _probe_engine(),
        _probe_llm(),
        _probe_disk(),
        _probe_database(),
        _probe_backup(),
        _probe_clients(),
    ]

    colors = [c["color"] for c in checks]
    if "red" in colors:
        overall = "red"
    elif "yellow" in colors:
        overall = "yellow"
    else:
        overall = "green"

    return {
        "status": "ok",
        "overall": overall,
        "checks": checks,
    }


@bp.route("/api/status", methods=["GET"])
def api_status():
    """系統狀態 API（D3：一頁 6 項紅黃綠燈＋白話說明）。"""
    return jsonify(collect_system_status()), 200


@bp.route("/api/health/deep", methods=["GET"])
def health_deep():
    """深度健康檢查：若任一關鍵項目紅燈回 503，否則 200 (D3)。"""
    status_data = collect_system_status()
    code = 503 if status_data["overall"] == "red" else 200
    return jsonify(status_data), code


@bp.route("/status")
def status_page():
    """呈現 D3 系統狀態靜態頁。"""
    static_folder = current_app.static_folder or "static"
    return send_from_directory(static_folder, "status.html")
