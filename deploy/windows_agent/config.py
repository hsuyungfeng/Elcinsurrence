"""Windows Agent Configuration and Local Storage (Phase 30: D-30-08, D-30-09).

Manages client settings stored in %LOCALAPPDATA%\\ElcAgent\\config.json.
Security rules:
- agent_key and operator_key are hidden from repr() to prevent credential leakage into logs.
- Atomic writes via temporary files to avoid corrupted configs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure src is on sys.path
_src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from elc_audit_engine.his_calibration import new_machine_id

logger = logging.getLogger("windows_agent.config")


def default_calibration_dir() -> Path:
    """Return platform-appropriate directory for per-machine HIS calibration profiles.

    Windows: %LOCALAPPDATA%\\ElcAgent\\calibration（見 30-RESEARCH §4）。
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "ElcAgent" / "calibration"
    return Path.home() / ".elcagent" / "calibration"


def default_settings_path() -> Path:
    """Return platform-appropriate default settings file path."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "ElcAgent" / "config.json"
        return Path.home() / "AppData" / "Local" / "ElcAgent" / "config.json"
    return Path.home() / ".elcagent" / "config.json"


@dataclass
class AgentSettings:
    """Windows Agent client workstation settings."""

    last_server_url: Optional[str] = None
    vendor_key: str = "vision"
    app_name: str = "VisionHIS.exe"
    agent_id: str = "agent-clinic-01"
    agent_key: str = field(default="", repr=False)
    operator_key: str = field(default="", repr=False)
    machine_id: str = field(default_factory=new_machine_id)
    schema_version: int = 1


def bundled_template_path() -> Optional[Path]:
    """Return the config template shipped inside the packaged app, if present.

    PyInstaller 一資料夾模式下資源位於 sys._MEIPASS；開發環境則位於本目錄。
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "config.template.json")
    candidates.append(Path(__file__).resolve().parent / "config.template.json")
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_settings(path: Optional[Path] = None) -> AgentSettings:
    """Load settings from JSON file.

    若設定檔不存在（首次啟動），改讀打包內附的範本並寫入本機設定檔，
    讓建置時注入的 operator_key 不需要使用者手動輸入。
    """
    target_path = path or default_settings_path()
    if not target_path.exists():
        template = bundled_template_path()
        if template is not None:
            try:
                data = json.loads(template.read_text(encoding="utf-8"))
                settings = AgentSettings(
                    last_server_url=data.get("last_server_url"),
                    vendor_key=data.get("vendor_key", "vision"),
                    app_name=data.get("app_name", "VisionHIS.exe"),
                    agent_id=data.get("agent_id", "agent-clinic-01"),
                    agent_key=data.get("agent_key", ""),
                    operator_key=data.get("operator_key", ""),
                    machine_id=data.get("machine_id") or new_machine_id(),
                    schema_version=data.get("schema_version", 1),
                )
                save_settings(target_path, settings)
                return settings
            except Exception as exc:
                logger.warning("Failed to bootstrap settings from template: %s", exc)
        return AgentSettings(last_server_url=None)

    try:
        raw_text = target_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        return AgentSettings(
            last_server_url=data.get("last_server_url"),
            vendor_key=data.get("vendor_key", "vision"),
            app_name=data.get("app_name", "VisionHIS.exe"),
            agent_id=data.get("agent_id", "agent-clinic-01"),
            agent_key=data.get("agent_key", ""),
            operator_key=data.get("operator_key", ""),
            machine_id=data.get("machine_id") or new_machine_id(),
            schema_version=data.get("schema_version", 1),
        )
    except Exception as exc:
        logger.warning(
            "Failed to load settings from %s, falling back to defaults: %s",
            target_path,
            exc,
        )
        return AgentSettings(last_server_url=None)


def save_settings(path: Optional[Path], settings: AgentSettings) -> Path:
    """Save settings atomically to file path using a temporary file."""
    target_path = path or default_settings_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = target_path.with_suffix(".json.tmp")
    data: Dict[str, Any] = {
        "last_server_url": settings.last_server_url,
        "vendor_key": settings.vendor_key,
        "app_name": settings.app_name,
        "agent_id": settings.agent_id,
        "agent_key": settings.agent_key,
        "operator_key": settings.operator_key,
        "machine_id": settings.machine_id,
        "schema_version": settings.schema_version,
    }

    raw_json = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_path.write_text(raw_json, encoding="utf-8")
    os.replace(tmp_path, target_path)
    return target_path
