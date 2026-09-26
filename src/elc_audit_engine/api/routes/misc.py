"""靜態頁、健康檢查、列印產出下載。"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, send_from_directory

from config import settings

from ..errors import ApiError

bp = Blueprint("misc", __name__)


def output_url(pdf_path: str) -> str:
    """產出 PDF 的下載 URL（對應 download_output 路由）。"""
    return f"/api/output/{os.path.basename(pdf_path)}"


@bp.route("/")
def index():
    return send_from_directory(current_app.static_folder, "index.html")


@bp.route("/api/health", methods=["GET"])
def health():
    """健康檢查（供 HIS 與監控探測，豁免 API key，不含任何案件資料）。"""
    return jsonify({"status": "ok"})


@bp.route("/api/output/<name>", methods=["GET"])
def download_output(name: str):
    """下載列印端點產出的 PDF（A-CR-05）。

    內容含 PHI：刻意不列入認證豁免，須帶 X-API-Key，並照常寫審計日誌。
    <name> 不接受斜線；send_from_directory 另以 safe_join 擋路徑穿越。只開放 .pdf。
    """
    if not name.lower().endswith(".pdf"):
        raise ApiError("找不到檔案", status=404)
    return send_from_directory(settings.OUTPUT_DIR, name, as_attachment=True)
