"""SoapVoice Recording Ingestion & Cross-Repo Contract (Phase 30: D-30-02, D-30-03).

Provides:
- parse_soap_txt: Parses [S] [O] [A] [P] sectioned text into SOAP dictionary.
- validate_recording_payload: Pure validation against cross-repo contract.
- POST /api/soap/recordings: Ingests audio and SOAP draft with idempotency and safe storage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, g, jsonify, request

from config import settings
from elc_audit_engine import audit_log
from elc_audit_engine.api.context import case_store
from elc_audit_engine.api.errors import ApiError
from elc_audit_engine.api.routes.soap_review import (
    _create_draft_record,
    _maybe_auto_accept,
)

logger = logging.getLogger("soap_recording")

bp = Blueprint("soap_recording", __name__)

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SOAP_SECTION_RE = re.compile(
    r"\[S\](?P<s>.*?)\[O\](?P<o>.*?)\[A\](?P<a>.*?)\[P\](?P<p>.*)",
    re.DOTALL | re.IGNORECASE,
)


def parse_soap_txt(raw_text: str) -> Tuple[Dict[str, str], List[str]]:
    """Parse text formatted with [S], [O], [A], [P] sections (UTF-8).

    Missing sections or empty section content are treated as missing columns and rejected.
    Diagnostic codes, medical orders, and prescriptions are NOT part of this text.
    """
    errors: List[str] = []
    if not raw_text or not raw_text.strip():
        return {}, ["SOAP 內容為空"]

    match = _SOAP_SECTION_RE.search(raw_text)
    if not match:
        # Detect which specific tags are missing
        missing_tags = []
        for tag in ("[S]", "[O]", "[A]", "[P]"):
            if tag.lower() not in raw_text.lower():
                missing_tags.append(tag)
        if missing_tags:
            errors.append(f"SOAP 格式錯誤：缺少標籤 {'、'.join(missing_tags)}")
        else:
            errors.append("SOAP 格式錯誤：標籤順序必須為 [S]、[O]、[A]、[P]")
        return {}, errors

    soap = {
        "s": match.group("s").strip(),
        "o": match.group("o").strip(),
        "a": match.group("a").strip(),
        "p": match.group("p").strip(),
    }

    empty_sections = [k.upper() for k, v in soap.items() if not v]
    if empty_sections:
        errors.append(f"SOAP 欄位內容不得為空：{', '.join(empty_sections)}")
        return {}, errors

    return soap, []


def validate_recording_payload(form: Dict[str, Any], file_meta: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Pure validator for cross-repo recording submission.

    Validates session_id, visit_date, patient_ref, soap, and audio file metadata.
    Does NOT access DB or filesystem.
    """
    errors: List[str] = []
    normalized: Dict[str, Any] = {}

    # 1. Reject client-provided caller field (spoofing prevention)
    if "caller" in form:
        errors.append("不得於請求中提供 caller 欄位，caller 僅由伺服器認證解析")

    # 2. session_id validation
    session_id = str(form.get("session_id") or "").strip()
    if not session_id:
        errors.append("缺少 session_id 欄位")
    elif not _SESSION_ID_RE.match(session_id):
        errors.append("session_id 格式不符：僅允許 1-64 字元之英數字、底線與連字號，禁止路徑字元")
    else:
        normalized["session_id"] = session_id

    # 3. visit_date validation
    visit_date = str(form.get("visit_date") or "").strip()
    if not visit_date:
        errors.append("缺少 visit_date 欄位")
    else:
        try:
            parsed_date = datetime.strptime(visit_date, "%Y-%m-%d")
            normalized["visit_date"] = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            errors.append("visit_date 格式錯誤：必須為 ISO 日期格式（YYYY-MM-DD）")

    # 4. patient_ref & case_id
    patient_ref = str(form.get("patient_ref") or "").strip()
    if not patient_ref:
        errors.append("缺少 patient_ref 欄位")
    elif len(patient_ref) > 64:
        errors.append("patient_ref 長度不得超過 64 字元")
    else:
        normalized["patient_ref"] = patient_ref

    case_id = str(form.get("case_id") or "").strip()
    normalized["case_id"] = case_id if case_id else patient_ref

    normalized["order_code"] = str(form.get("order_code") or "").strip() or None
    normalized["primary_diagnosis"] = str(form.get("primary_diagnosis") or "").strip() or None

    # 5. SOAP validation (either from dict, or parsed from soap_txt)
    soap = form.get("soap")
    soap_txt = form.get("soap_txt") or form.get("soap_text")

    if isinstance(soap, dict):
        required_keys = ("s", "o", "a", "p")
        missing_keys = [k for k in required_keys if k not in soap]
        if missing_keys:
            errors.append(f"soap 物件缺少必要鍵：{', '.join(missing_keys)}")
        else:
            cleaned_soap = {}
            for k in required_keys:
                val = str(soap.get(k) or "").strip()
                if not val:
                    errors.append(f"soap.{k} 內容不得為空")
                elif len(val) > 4000:
                    errors.append(f"soap.{k} 長度超過 4000 字元上限")
                cleaned_soap[k] = val
            normalized["soap"] = cleaned_soap
    elif soap_txt and isinstance(soap_txt, str):
        parsed_soap, parse_errs = parse_soap_txt(soap_txt)
        if parse_errs:
            errors.extend(parse_errs)
        else:
            normalized["soap"] = parsed_soap
    else:
        errors.append("缺少 soap 或 soap_txt 欄位")

    # 6. Audio file metadata validation
    if not file_meta:
        errors.append("缺少 audio 音檔")
    else:
        size_bytes = file_meta.get("size_bytes", 0)
        content_type = (file_meta.get("content_type") or "").lower()
        filename = (file_meta.get("filename") or "").lower()

        if size_bytes <= 0:
            errors.append("音檔內容為空")
        elif size_bytes > MAX_AUDIO_BYTES:
            errors.append(f"音檔大小超過 {MAX_AUDIO_BYTES // (1024 * 1024)} MB 上限")

        valid_mimes = ("audio/wav", "audio/x-wav", "audio/wave")
        is_wav_mime = any(m in content_type for m in valid_mimes)
        is_wav_ext = filename.endswith(".wav")

        if not (is_wav_mime or is_wav_ext):
            errors.append("音檔格式錯誤：僅支援 audio/wav 格式之 .wav 檔案")

    return normalized, errors


@bp.route("/api/soap/recordings", methods=["POST"])
def receive_recording():
    """Ingest audio file and SOAP draft from SoapVoice (Phase 30: D-30-02, D-30-03)."""
    form_data = request.form.to_dict()
    audio_file = request.files.get("audio")

    # Check if SOAP text is sent as a file
    soap_file = request.files.get("soap_file") or request.files.get("soap")
    if soap_file:
        try:
            form_data["soap_txt"] = soap_file.read().decode("utf-8")
        except UnicodeDecodeError:
            return jsonify({"status": "error", "message": "SOAP 檔案必須為 UTF-8 編碼"}), 422

    # Also handle JSON soap field if present in form as string
    if "soap" in form_data and isinstance(form_data["soap"], str):
        try:
            form_data["soap"] = json.loads(form_data["soap"])
        except ValueError:
            # 非 JSON 字串：保留原字串，交由後續欄位驗證決定是否拒收
            logger.warning("soap 欄位不是合法 JSON，保留原字串交由後續驗證")

    file_meta = {}
    if audio_file:
        # Seek end to measure size without reading all into memory
        audio_file.seek(0, os.SEEK_END)
        size_bytes = audio_file.tell()
        audio_file.seek(0)
        file_meta = {
            "filename": audio_file.filename,
            "content_type": audio_file.content_type,
            "size_bytes": size_bytes,
        }

    normalized, errors = validate_recording_payload(form_data, file_meta)
    if errors:
        return jsonify({"status": "error", "message": "請求資料未通過契約驗證", "errors": errors}), 422

    session_id = normalized["session_id"]
    store = case_store()

    # 1. Idempotency check via soap_recording_sessions table
    existing = store.get_recording_session(session_id)
    if existing:
        logger.info("Idempotent hit for session_id=%s, returning draft_id=%s", session_id, existing["draft_id"])
        return jsonify({
            "status": "success",
            "idempotent": True,
            "session_id": session_id,
            "draft_id": existing["draft_id"],
        }), 200

    # 2. Persist audio file to <DATA_DIR>/recordings/<session_id>.wav
    recordings_dir = Path(settings.DATA_DIR) / "recordings"
    recordings_dir.mkdir(parents=True, exist_ok=True)
    audio_path = recordings_dir / f"{session_id}.wav"

    try:
        audio_file.save(str(audio_path))
    except Exception as exc:
        logger.exception("Failed to save recording audio for session_id=%s: %s", session_id, exc)
        return jsonify({"status": "error", "message": "音檔寫入磁碟失敗"}), 500

    # 3. Create SOAP draft record with quality checks
    try:
        draft = _create_draft_record(
            store,
            case_id=normalized["case_id"],
            soap=normalized["soap"],
            order_code=normalized.get("order_code"),
            primary_diagnosis=normalized.get("primary_diagnosis"),
        )
    except Exception as exc:
        # Clean up audio file on draft creation failure to prevent orphans
        if audio_path.exists():
            try:
                audio_path.unlink()
            except OSError as unlink_exc:
                logger.warning("清除孤兒錄音檔失敗 %s: %s", audio_path, unlink_exc)
        logger.exception("Failed to create draft for session_id=%s: %s", session_id, exc)
        return jsonify({"status": "error", "message": "建立 SOAP 草稿失敗"}), 500

    # 4. Save mapping into idempotency table
    caller = getattr(g, "caller_id", None) or "anonymous"
    try:
        store.put_recording_session(session_id, draft.draft_id, caller=caller)
    except Exception as exc:
        logger.exception("Failed to record recording session idempotency for session_id=%s: %s", session_id, exc)

    # 4.1 Auto-accept gate (D-30-04)
    draft = _maybe_auto_accept(store, draft, caller)

    # 5. Safe logging (NO PHI or SOAP text)
    logger.info(
        "Recording session ingested: session_id=%s draft_id=%s caller=%s state=%s",
        session_id,
        draft.draft_id,
        caller,
        draft.state,
    )

    return jsonify({
        "status": "success",
        "idempotent": False,
        "session_id": session_id,
        "draft_id": draft.draft_id,
        "state": draft.state,
        "quality_score": draft.quality_score,
    }), 201
