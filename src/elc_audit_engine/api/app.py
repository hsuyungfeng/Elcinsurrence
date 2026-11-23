"""Flask app factory（IN-04）：組裝設定、服務、安全 hooks、錯誤處理與 blueprints。

匯入本套件不產生任何副作用；建立 CaseStore、遷移舊快照等
全部延後到 `create_app()` 呼叫時，測試可注入暫存資源。
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask

from config import settings
from elc_audit_engine.case_store import CaseStore

from elc_audit_engine.lan_trust import describe_trust, load_trusted_subnets

from .cases import migrate_legacy_uploads
from .context import EXTENSION_KEY, Services
from .errors import register_error_handlers
from .routes import ALL_BLUEPRINTS
from .security import register_security

# 請求大小上限（A-WR-04 / Phase 33）：對齊 /api/soap/recordings 25MB 音檔契約＋1MB 表單餘裕。
# 非錄音路由（monthly.py、uploads.py、attachment_store.py）各自強制 10MB 串流上限，不受放寬影響。
MAX_CONTENT_LENGTH = 26 * 1024 * 1024


def create_app(
    config: dict[str, Any] | None = None,
    *,
    case_store: CaseStore | None = None,
    migrate_legacy: bool = True,
) -> Flask:
    """建立 API app。

    Args:
        config: 覆寫 app.config，常用鍵：
            - ELC_TRUSTED_SUBNETS：信任網段清單（`ipaddress` 網路物件的
              iterable）；未提供時讀環境變數或自動偵測伺服器所在子網。
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
    # 院內信任模式（Phase 32-A）：無金鑰，以來源位址判定。信任範圍於啟動時
    # 解析一次——逐請求偵測網路介面既慢又可能中途變動。
    if "ELC_TRUSTED_SUBNETS" not in app.config:
        app.config["ELC_TRUSTED_SUBNETS"] = load_trusted_subnets()
    else:
        app.config["ELC_TRUSTED_SUBNETS"] = list(app.config["ELC_TRUSTED_SUBNETS"])
    # 安裝人員必須看得見信任範圍，才能確認訪客網段未被誤納。
    app.logger.info(
        "院內信任模式：信任來源 %s",
        describe_trust(app.config["ELC_TRUSTED_SUBNETS"]),
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
