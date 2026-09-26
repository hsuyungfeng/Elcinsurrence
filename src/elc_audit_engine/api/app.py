"""Flask app factory（IN-04）：組裝設定、服務、安全 hooks、錯誤處理與 blueprints。

匯入本套件不產生任何副作用；載入 API key、建立 CaseStore、遷移舊快照等
全部延後到 `create_app()` 呼叫時，測試可注入暫存資源。
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask

from config import settings
from elc_audit_engine.case_store import CaseStore

from .cases import migrate_legacy_uploads
from .context import EXTENSION_KEY, Services
from .errors import register_error_handlers
from .routes import ALL_BLUEPRINTS
from .security import load_allowed_hosts, load_api_keys_or_fail, register_security

# 請求大小上限（A-WR-04）：單檔上限 10MB，另留 1MB 給 multipart 欄位與 JSON。
MAX_CONTENT_LENGTH = 11 * 1024 * 1024


def create_app(
    config: dict[str, Any] | None = None,
    *,
    case_store: CaseStore | None = None,
    migrate_legacy: bool = True,
) -> Flask:
    """建立 API app。

    Args:
        config: 覆寫 app.config，常用鍵：
            - ELC_API_KEYS：{key: caller_id}；未提供時自環境變數載入（fail-fast）。
            - ELC_ALLOWED_HOSTS：Host 白名單（iterable）；未提供時讀 ELC_ALLOWED_HOSTS。
            - ELC_UPLOAD_DIR／ELC_RAW_DIR：匯入暫存目錄（預設 DATA_DIR/uploads[/raw]）。
            - TESTING 等 Flask 設定。
        case_store: 注入的 CaseStore；未提供時使用 settings.CASES_DB_PATH。
        migrate_legacy: 是否將舊版 data/uploads/*.json 快照遷入 CaseStore（冪等）。
    """
    app = Flask(
        __name__,
        static_folder=os.path.join(settings.PROJECT_ROOT, "static"),
        static_url_path="/static",
    )
    upload_dir = os.path.join(settings.DATA_DIR, "uploads")
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        ELC_UPLOAD_DIR=upload_dir,
        ELC_RAW_DIR=os.path.join(upload_dir, "raw"),
    )
    app.config.update(config or {})
    if "ELC_API_KEYS" not in app.config:
        app.config["ELC_API_KEYS"] = load_api_keys_or_fail(app)
    app.config["ELC_ALLOWED_HOSTS"] = frozenset(
        h.lower() for h in app.config.get("ELC_ALLOWED_HOSTS") or load_allowed_hosts()
    )

    store = case_store if case_store is not None else CaseStore()
    app.extensions[EXTENSION_KEY] = Services(case_store=store)

    register_security(app)
    register_error_handlers(app)
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    if migrate_legacy:
        result = migrate_legacy_uploads(store, app.config["ELC_UPLOAD_DIR"])
        app.logger.info("啟動期遷移 data/uploads/*.json → CaseStore：%s", result)
    return app
