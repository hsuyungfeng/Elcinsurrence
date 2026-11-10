"""SOAP Draft Review Queue API (Phase 30: D-30-03, D-30-12).

Provides GET /api/soap/drafts/pending-review for physician review window.
Only returns drafts with state == STATE_VALIDATED.
Masks patient identifier and attaches read-only advisory suggestions.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from elc_audit_engine.api.context import case_store
from elc_audit_engine.case_store.soap_draft_states import STATE_VALIDATED

bp = Blueprint("soap_review_queue", __name__)


def _mask_patient_ref(ref: str) -> str:
    """Mask patient ref: first 2 chars plus '***' (e.g., P1***)."""
    clean = str(ref or "").strip()
    if len(clean) <= 2:
        return clean + "***"
    return clean[:2] + "***"


@bp.route("/api/soap/drafts/pending-review", methods=["GET"])
def list_pending_review():
    """List drafts in validated state waiting for physician review."""
    raw_limit = request.args.get("limit", "50")
    try:
        limit = max(1, min(int(raw_limit), 50))
    except ValueError:
        limit = 50

    store = case_store()
    records = store.list_soap_drafts_by_state(STATE_VALIDATED, limit=limit)

    results = []
    for rec in records:
        comp = rec.comparison or {}
        icd10_suggestions = comp.get("icd10_suggestions", [])
        order_suggestions = comp.get("order_suggestions", [])
        med_suggestions = comp.get("med_suggestions", [])

        if not icd10_suggestions and isinstance(comp.get("advice"), dict):
            icd10_suggestions = comp.get("advice", {}).get("icd10", [])

        results.append({
            "draft_id": rec.draft_id,
            "version": rec.version,
            "content_hash": rec.content_hash,
            "patient_ref": _mask_patient_ref(rec.case_id),
            "soap": rec.soap,
            "quality_score": rec.quality_score,
            "advisory": {
                "icd10_suggestions": icd10_suggestions,
                "order_suggestions": order_suggestions,
                "med_suggestions": med_suggestions,
                "read_only": True,
            },
            "created_at": rec.created_at,
        })

    return jsonify({"status": "success", "count": len(results), "drafts": results}), 200
