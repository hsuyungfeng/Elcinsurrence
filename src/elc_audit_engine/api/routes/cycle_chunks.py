"""Phase 31: 循環音訊分段上傳與 finalize API 路由.

端點：
- POST /api/cycles/<cycle_id>/chunks
- POST /api/cycles/<cycle_id>/finalize

規範：
- 受全域 API Key 保護（非 Agent 專用 key；Agent 金鑰 403）。
- 不套用 /api/soap/recordings 的私有 IP 免金鑰例外（D-31-09）。
- 日誌與回應絕不含音訊位元組或病人資訊。
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.api.context import caller_id, case_store
from elc_audit_engine.api.errors import ApiError
from elc_audit_engine.cycles.chunks import (
    AudioHashMismatchError,
    ChunkConflictError,
    ChunkFormatError,
    ChunkHashMismatchError,
    ChunkSizeExceededError,
    ChunkStateError,
    MissingChunksError,
    finalize_cycle_audio,
    store_chunk,
)

logger = logging.getLogger(__name__)

bp = Blueprint("cycle_chunks", __name__)

_CYCLE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_CHUNK_UPLOAD_BYTES = 4 * 1024 * 1024


@bp.route("/api/cycles/<cycle_id>/chunks", methods=["POST"])
def upload_chunk(cycle_id: str):
    """接收單一分段音訊上傳 (multipart/form-data)。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        return jsonify({"error": "not_found", "message": f"Cycle not found: {cycle_id}"}), 404

    # 預檢 Content-Length
    if request.content_length and request.content_length > MAX_CHUNK_UPLOAD_BYTES:
        return jsonify({"error": "payload_too_large", "message": "分段超過 4 MiB 上限"}), 413

    raw_seq = request.form.get("seq")
    if raw_seq is None:
        raise ApiError("缺少必要欄位 seq", status=422)
    try:
        seq = int(raw_seq)
        if seq < 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ApiError(f"seq 必須為非負整數：{raw_seq!r}", status=422)

    declared_sha256 = request.form.get("sha256")
    if not declared_sha256 or not _SHA256_RE.match(declared_sha256):
        raise ApiError(f"缺少或不合法的 sha256 格式：{declared_sha256!r}", status=422)

    if "audio" not in request.files:
        raise ApiError("缺少 audio 檔案欄位", status=422)

    audio_file = request.files["audio"]
    data = audio_file.read()
    if len(data) > MAX_CHUNK_UPLOAD_BYTES:
        return jsonify({"error": "payload_too_large", "message": "分段超過 4 MiB 上限"}), 413

    store = case_store()
    try:
        res = store_chunk(
            store,
            cycle_id=cycle_id,
            seq=seq,
            declared_sha256=declared_sha256,
            data=data,
            actor=caller_id(),
        )
    except LookupError as exc:
        return jsonify({"error": "not_found", "message": str(exc)}), 404
    except ChunkConflictError as exc:
        return jsonify({"error": "chunk_conflict", "message": str(exc)}), 409
    except ChunkStateError as exc:
        return jsonify({"error": "invalid_cycle_state", "message": str(exc)}), 409
    except ChunkHashMismatchError as exc:
        return jsonify({"error": "hash_mismatch", "message": str(exc)}), 422
    except ChunkFormatError as exc:
        return jsonify({"error": "invalid_wav_format", "message": str(exc)}), 422
    except ChunkSizeExceededError as exc:
        return jsonify({"error": "payload_too_large", "message": str(exc)}), 413

    status_code = 200 if res.get("duplicate") else 201

    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            endpoint=request.path,
            status_code=status_code,
            detail={
                "action": "store_chunk",
                "cycle_id": cycle_id,
                "seq": seq,
                "duplicate": res.get("duplicate"),
            },
        )
    except Exception:
        logger.exception("Audit log failure in upload_chunk")

    return jsonify(res), status_code


@bp.route("/api/cycles/<cycle_id>/finalize", methods=["POST"])
def finalize_audio(cycle_id: str):
    """驗證分段到齊、比對 PCM 串接雜湊、產出 full.wav 並完成音訊上傳。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        return jsonify({"error": "not_found", "message": f"Cycle not found: {cycle_id}"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求內文必須為 JSON 物件", status=400)

    raw_total = data.get("total_chunks")
    if raw_total is None:
        raise ApiError("缺少必要欄位 total_chunks", status=422)
    try:
        total_chunks = int(raw_total)
        if total_chunks <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ApiError(f"total_chunks 必須為正整數：{raw_total!r}", status=422)

    audio_sha256 = data.get("audio_sha256")
    if not audio_sha256 or not isinstance(audio_sha256, str) or not _SHA256_RE.match(audio_sha256):
        raise ApiError(f"缺少或不合法的 audio_sha256 格式：{audio_sha256!r}", status=422)

    store = case_store()
    try:
        res = finalize_cycle_audio(
            store,
            cycle_id=cycle_id,
            total_chunks=total_chunks,
            audio_sha256=audio_sha256,
            actor=caller_id(),
        )
    except LookupError as exc:
        return jsonify({"error": "not_found", "message": str(exc)}), 404
    except MissingChunksError as exc:
        return jsonify({
            "error": "missing_chunks",
            "missing": exc.missing,
            "message": str(exc),
        }), 409
    except AudioHashMismatchError as exc:
        return jsonify({"error": "audio_hash_mismatch", "message": str(exc)}), 422
    except ChunkStateError as exc:
        return jsonify({"error": "invalid_cycle_state", "message": str(exc)}), 409

    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            endpoint=request.path,
            status_code=200,
            detail={
                "action": "finalize_cycle_audio",
                "cycle_id": cycle_id,
                "total_chunks": total_chunks,
            },
        )
    except Exception:
        logger.exception("Audit log failure in finalize_audio")

    return jsonify(res), 200
