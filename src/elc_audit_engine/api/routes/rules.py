"""規則庫管理 API：上傳最新規則 CSV 與觸發同步。

認證：兩個端點皆需 X-API-Key（不列入 AUTH_EXEMPT_ENDPOINTS）。理由：上傳會寫入磁碟、
同步會改寫正式規則庫；若免認證，任何能連到服務的網頁（經 CSRF 表單）或程序都能改寫規則。
儀表板已有 API Key 欄位，本機操作不需額外步驟。
"""

from __future__ import annotations

import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine.rule_repository.loaders._csv_table import RuleCsvFormatError
from elc_audit_engine.rule_repository.scripts.sync_latest_rules import (
    default_rules_dir,
    rule_csv_kind,
    sync_latest_rules,
    validate_rule_csv_header,
)

from ..errors import ApiError

bp = Blueprint("rules", __name__)

MAX_RULE_CSV_BYTES = 64 * 1024 * 1024  # 藥品 CSV 實測約 34MB


def _rules_dir() -> str:
    return current_app.config.get("ELC_RULES_DIR") or default_rules_dir()


def _save_stream(stream, dest: str) -> None:
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = stream.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RULE_CSV_BYTES:
                out.close()
                os.remove(dest)
                raise ApiError("檔案超過 64MB 上限", status=413)
            out.write(chunk)


@bp.route("/api/rules/upload", methods=["POST"])
def upload_rule_csv():
    """上傳來源 CSV 到規則目錄（檔名須符合「藥品項查詢項目檔*.csv」或「醫療服務給付項目*.csv」）。

    先寫入暫存檔並驗證表頭，通過才以原子替換放入目錄；失敗不留下半成品。
    上傳後須另行呼叫 `POST /api/rules/sync` 才會更新規則庫。
    """
    upload = request.files.get("file")
    if upload is None:
        raise ApiError("請以 multipart 欄位 file 上傳 CSV")
    filename = (upload.filename or "").strip()
    kind = rule_csv_kind(filename)
    if kind is None:
        raise ApiError("檔名不符合規則來源格式（藥品項查詢項目檔*.csv 或 醫療服務給付項目*.csv）")

    directory = _rules_dir()
    os.makedirs(directory, exist_ok=True)
    temp = os.path.join(directory, f".upload-{uuid.uuid4().hex}.part")
    final = os.path.join(directory, filename)
    try:
        _save_stream(upload.stream, temp)
        try:
            validate_rule_csv_header(temp, kind)
        except RuleCsvFormatError as exc:
            raise ApiError(f"CSV 格式不符：{exc}")
        except (OSError, UnicodeDecodeError):
            raise ApiError("CSV 無法以 UTF-8（含 BOM）讀取")
        replaced = os.path.exists(final)
        os.replace(temp, final)  # 原子替換：不會留下半寫入的來源檔
    finally:
        if os.path.exists(temp):
            os.remove(temp)

    return jsonify({"status": "success", "saved_as": filename, "kind": kind, "replaced": replaced})


@bp.route("/api/rules/sync", methods=["POST"])
def sync_rules():
    """執行每月規則同步：自規則目錄取最新藥品與給付項目 CSV，更新 rules.sqlite3。"""
    try:
        result = sync_latest_rules(
            db_path=current_app.config.get("ELC_RULES_DB_PATH"),
            rules_dir=_rules_dir(),
        )
    except FileNotFoundError:
        raise ApiError("找不到規則來源檔（請先上傳藥品與給付項目 CSV）")
    except RuleCsvFormatError as exc:
        raise ApiError(f"規則來源格式不符：{exc}")
    return jsonify({"status": "success", **result.to_dict()})
