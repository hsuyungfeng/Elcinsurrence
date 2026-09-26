"""影像佐證附件 API（Phase 12；A-CR-03 起以 case_id 為鍵）。"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine import attachment_store
from elc_audit_engine.attachment_store import InvalidAttachmentError
from elc_audit_engine.case_store import CaseNotFoundError
from elc_audit_engine.safe_paths import safe_filename

from ..context import case_store
from ..errors import ApiError

bp = Blueprint("attachments", __name__)


def resolve_attachment_case(case_ref: str):
    """把呼叫方給的案件識別轉成 CaseStore 案件（A-CR-03）。

    附件一律以全域唯一的 case_id 為儲存鍵。健保流水號 case_seq 只在單一費用
    年月／案件分類內唯一，舊版以它當鍵會把別的病患影像併進本案佐證包。為相容
    既有 HIS 呼叫仍接受 case_seq：僅在它唯一對應一筆申復案件時採用，多筆 →
    409，查無 → 404，絕不猜測。
    """
    safe_filename(case_ref, "case_id")
    store = case_store()
    try:
        return store.get(case_ref)
    except CaseNotFoundError:
        pass
    matches = [r for r in store.list_all(kind="appeal") if r.case_seq == case_ref]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ApiError(
            f"流水號 '{case_ref}' 對應 {len(matches)} 筆申復案件，請改用 case_id 指定",
            status=409,
        )
    raise ApiError(f"找不到案件 '{case_ref}'", status=404)


def _attachment_json(rec, case) -> dict:
    return {
        "id": rec.id,
        "case_id": case.case_id,
        "case_seq": case.case_seq,
        "order_seq": rec.order_seq,
        "order_code": rec.order_code,
        "filename": rec.filename,
        "file_size": rec.file_size,
        "mime_type": rec.mime_type,
        "created_at": rec.created_at,
    }


@bp.route("/api/appeal/attachments/upload", methods=["POST"])
def upload_appeal_attachment():
    """上傳佐證影像附件（case_id，或可唯一對應的 case_seq）。"""
    case_ref = (
        request.form.get("case_id") or request.args.get("case_id")
        or request.form.get("case_seq") or request.args.get("case_seq")
    )
    if not case_ref:
        raise ApiError("缺少案件識別 case_id（或可唯一對應的 case_seq）")
    case = resolve_attachment_case(case_ref)

    file = request.files.get("file")
    if not file or not (file.filename or "").strip():
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")

    try:
        rec = attachment_store.save_attachment(
            case.case_id,
            file.read(),
            file.filename,
            order_seq=request.form.get("order_seq") or request.args.get("order_seq"),
            order_code=request.form.get("order_code") or request.args.get("order_code"),
        )
    except InvalidAttachmentError as exc:
        raise ApiError(str(exc))
    except Exception as exc:
        current_app.logger.error("attachment upload error: %s", exc)
        raise ApiError("附件儲存失敗")

    return jsonify({"status": "success", "attachment": _attachment_json(rec, case)})


@bp.route("/api/appeal/attachments/<case_ref>", methods=["GET"])
def get_appeal_attachments(case_ref: str):
    """查詢某案件下的佐證附件清單。"""
    case = resolve_attachment_case(case_ref)
    records = attachment_store.list_attachments(case.case_id, request.args.get("order_seq"))
    return jsonify({
        "status": "success",
        "case_id": case.case_id,
        "case_seq": case.case_seq,
        "attachments": [_attachment_json(r, case) for r in records],
    })


@bp.route("/api/appeal/attachments/<case_ref>/<attachment_id>", methods=["DELETE"])
def delete_appeal_attachment(case_ref: str, attachment_id: str):
    """刪除指定佐證附件。"""
    case = resolve_attachment_case(case_ref)
    if not attachment_store.delete_attachment(case.case_id, attachment_id):
        raise ApiError("找不到指定附件或刪除失敗", status=404)
    return jsonify({"status": "success", "message": "附件已刪除"})
