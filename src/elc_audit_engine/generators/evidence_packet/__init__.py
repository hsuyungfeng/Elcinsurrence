from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from elc_audit_engine.safe_paths import safe_filename
from .builder import build_evidence_packet_docx
from .pdf_exporter import convert_docx_and_merge_pdfs

__all__ = ["render_evidence_packet", "write_evidence_packet"]

def render_evidence_packet(
    payload: dict,
    facility: dict,
    *,
    tracking: dict | None = None,
    timeline: dict | None = None,
    attachments: list[dict] | None = None,
) -> tuple[bytes, list[str]]:
    """Pure function rendering filled Evidence Packet DOCX bytes and warnings. No side effects."""
    if not isinstance(payload, dict):
        raise TypeError(f"payload 必須為 dict，收到 {type(payload).__name__}")
    if not isinstance(facility, dict):
        raise TypeError(f"facility 必須為 dict，收到 {type(facility).__name__}")

    tracking = tracking or {}
    timeline = timeline or {}
    attachments = attachments or []

    # Scaffolding DOCX doc using builder.py
    doc, warnings = build_evidence_packet_docx(
        cover_info={
            "case_class": payload.get("case_class", "01"),
            "case_seq": payload.get("case_seq", ""),
            "case_record_no": payload.get("case_record_no", ""),
            "visit_date": payload.get("visit_date", ""),
            "fee_year_month": payload.get("fee_year_month", ""),
            "total_denied_orders": len(payload.get("orders", [])),
            "total_non_reimbursed_points": sum(order.get("deduct_amount", 0) for order in payload.get("orders", [])),
            "total_claimed_points": sum(order.get("p6", 0) for order in payload.get("orders", [])),
            "total_attachments": len(attachments)
        },
        facility=facility,
        tracking_data=tracking,
        timeline_data=timeline,
        appeal_draft=payload,
        attachment_records=attachments
    )
    
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), warnings

def write_evidence_packet(
    output_dir: str,
    payload: dict,
    facility: dict,
    *,
    tracking: dict | None = None,
    timeline: dict | None = None,
    attachments: list[dict] | None = None,
) -> tuple[str, list[str]]:
    """
    Writes the evidence packet PDF to output_dir / 申復佐證包_{case_seq}.pdf.
    """
    case_seq = str(payload.get("case_seq", "unknown"))
    safe_case_seq = safe_filename(case_seq, "case_seq")
    output_pdf_path = os.path.join(output_dir, f"申復佐證包_{safe_case_seq}.pdf")

    # Path traversal check on output_dir
    if os.pardir in output_dir.split(os.sep):
        raise ValueError("Invalid output_dir containing path traversal components.")

    docx_bytes, warnings = render_evidence_packet(
        payload, facility, tracking=tracking, timeline=timeline, attachments=attachments
    )

    pdf_attachments = []
    if attachments:
        for att in attachments:
            if att.get("mime_type") == "application/pdf":
                file_path = att.get("file_path")
                if file_path and os.path.isfile(file_path):
                    pdf_attachments.append(file_path)

    convert_docx_and_merge_pdfs(docx_bytes, output_pdf_path, pdf_attachments)
    
    return output_pdf_path, warnings
