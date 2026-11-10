"""靜態頁、健康檢查、列印產出下載。"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from config import settings
from elc_audit_engine.monthly_package import PROFILE_CONFIRMED_KEY

from ..errors import ApiError

bp = Blueprint("misc", __name__)


def output_url(pdf_path: str) -> str:
    """產出 PDF 的下載 URL（對應 download_output 路由）。"""
    return f"/api/output/{os.path.basename(pdf_path)}"


@bp.route("/")
def index():
    resp = send_from_directory(current_app.static_folder, "index.html")
    # 支援前端防快取（User Requirement: reflash brower then clear cath）
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@bp.route("/api/health", methods=["GET"])
def health():
    """健康檢查（供 HIS 與監控探測，豁免 API key，不含任何案件資料）。"""
    return jsonify({"status": "ok", "service": "elc-audit-engine"})


@bp.route("/api/facility", methods=["GET"])
def get_facility():
    """取得當前院所機構設定（code, name, address, physician_name）。"""
    try:
        cfg = settings.load_facility_config()
    except Exception:
        cfg = {"code": "", "name": ""}
    return jsonify({"status": "success", "facility": cfg})


@bp.route("/api/facility", methods=["POST", "PUT"])
def update_facility():
    """更新院所機構設定並持久化至 config/facility.json。"""
    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict()
    if not isinstance(payload, dict):
        raise ApiError("請求格式錯誤：需為 JSON 物件或表單")
    allowed = ("code", "name", "email", "address", "physician_name")
    updates = {k: str(payload[k]).strip() for k in allowed if k in payload and payload[k] is not None}
    # Phase 29：使用者於診所表單確認院所資料後設為 true（下載前的首次確認）。
    if PROFILE_CONFIRMED_KEY in payload:
        updates[PROFILE_CONFIRMED_KEY] = payload[PROFILE_CONFIRMED_KEY] is True
    if not updates:
        raise ApiError("無提供任何院所欄位進行更新")
    # 若為 Web 介面儲存或指定驗證，檢查必填欄位 (code, name, email) 須填寫才可存入診所檔案
    if payload.get("source") == "web" or "email" in payload:
        if not updates.get("code"):
            raise ApiError("醫事機構代碼為必填欄位，須填寫才可存入診所檔案")
        if not updates.get("name"):
            raise ApiError("醫療院所名稱為必填欄位，須填寫才可存入診所檔案")
        if not updates.get("email"):
            raise ApiError("聯絡信箱 (Mail Address) 為必填欄位，須填寫才可存入診所檔案")

    saved = settings.save_facility_config(updates)
    return jsonify({"status": "success", "facility": saved})



@bp.route("/api/output/<name>", methods=["GET"])
def download_output(name: str):
    """下載列印端點產出的 PDF（A-CR-05）。

    內容含 PHI：刻意不列入認證豁免，須帶 X-API-Key，並照常寫審計日誌。
    <name> 不接受斜線；send_from_directory 另以 safe_join 擋路徑穿越。只開放 .pdf。
    """
    if not name.lower().endswith(".pdf"):
        raise ApiError("找不到檔案", status=404)
    return send_from_directory(settings.OUTPUT_DIR, name, as_attachment=True)
