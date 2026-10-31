"""佐證庫 API（Phase 17-01）：依 vault_key（身分證字號-年月）查詢、上傳與讀取佐證檔案。"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, send_file

from elc_audit_engine import evidence_vault
from elc_audit_engine.evidence_vault import VaultError

from ..errors import ApiError

bp = Blueprint("vault", __name__)


def _file_json(vf: evidence_vault.VaultFile) -> dict:
    return {
        "category": vf.category,
        "filename": vf.filename,
        "size": vf.size,
        "url": f"/api/vault/{vf.vault_key}/files/{vf.category}/{vf.filename}",
    }


def _structure_json(vault_key: str, grouped: dict[str, list[evidence_vault.VaultFile]]) -> dict:
    return {
        "status": "success",
        "vault_key": vault_key,
        "total": sum(len(files) for files in grouped.values()),
        "categories": {
            category: {"count": len(files), "files": [_file_json(f) for f in files]}
            for category, files in grouped.items()
        },
    }


@bp.route("/api/vault/<vault_key>", methods=["GET"])
def get_vault(vault_key: str):
    """取得某病患月份的佐證檔案結構與各分類數量。"""
    try:
        grouped = evidence_vault.list_vault_files(vault_key)
    except VaultError as exc:
        raise ApiError(str(exc))
    return jsonify(_structure_json(vault_key, grouped))


@bp.route("/api/vault/<vault_key>/upload", methods=["POST"])
def upload_vault(vault_key: str):
    """上傳佐證檔案（multipart 欄位 `file`，可多個）；ZIP 會自動解壓並分類。"""
    try:
        evidence_vault.validate_vault_key(vault_key)
    except VaultError as exc:
        raise ApiError(str(exc))

    uploads = [f for f in request.files.getlist("file") if (f.filename or "").strip()]
    if not uploads:
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")

    saved: list[evidence_vault.VaultFile] = []
    for upload in uploads:
        name = upload.filename or ""
        try:
            if name.lower().endswith(".zip"):
                saved.extend(evidence_vault.store_zip(vault_key, upload.read()))
            else:
                saved.append(evidence_vault.store_single_file(vault_key, name, upload.read()))
        except VaultError as exc:
            raise ApiError(str(exc))
        except Exception as exc:  # noqa: BLE001 — I/O 等非預期錯誤：記 log 並脫敏回傳，不外洩內部細節
            current_app.logger.error("vault upload error: %s", exc)
            raise ApiError("佐證檔案儲存失敗")

    return jsonify({
        "status": "success",
        "vault_key": vault_key,
        "saved": [_file_json(f) for f in saved],
    })


@bp.route("/api/vault/<vault_key>/files/<category>/<filename>", methods=["GET"])
def get_vault_file(vault_key: str, category: str, filename: str):
    """串流回傳單一佐證檔案（inline，供前端播放音訊、顯示影像或檢視 PDF）。"""
    try:
        vf = evidence_vault.get_vault_file(vault_key, category, filename)
    except FileNotFoundError:
        raise ApiError("找不到指定的佐證檔案", status=404)
    except VaultError as exc:
        raise ApiError(str(exc))
    return send_file(vf.path, download_name=vf.filename)
