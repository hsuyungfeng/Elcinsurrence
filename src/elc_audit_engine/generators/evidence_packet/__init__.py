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
    # timeline 保留 None（＝未查詢）與 {}／空 events（＝查詢後無紀錄）的差別
    attachments = attachments or []
    orders = payload.get("orders")
    if orders:
        total_orders = len(orders)
        total_deducted = sum(order.get("deduct_amount", 0) or 0 for order in orders)
        total_claimed = sum(order.get("p6", 0) or 0 for order in orders)
    else:
        # 單筆申復草稿（render_appeal_json 契約）：一筆醫令
        total_orders = 1 if payload.get("order_code") else 0
        total_deducted = payload.get("deduction_upper_bound") or payload.get("deduct_amount") or 0
        total_claimed = payload.get("p6_points") or 0

    # Scaffolding DOCX doc using builder.py
    doc, warnings = build_evidence_packet_docx(
        cover_info={
            # 缺值不捏造（A-IN-03：原預設 "01"）
            "case_class": payload.get("case_class"),
            "case_seq": payload.get("case_seq", ""),
            "case_record_no": payload.get("case_record_no", ""),
            "visit_date": payload.get("visit_date", ""),
            "fee_year_month": payload.get("fee_year_month", ""),
            "total_denied_orders": total_orders,
            "total_non_reimbursed_points": total_deducted,
            "total_claimed_points": total_claimed,
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
    file_stem: str | None = None,
) -> tuple[str, list[str]]:
    """
    Writes the evidence packet PDF to output_dir / 申復佐證包_{file_stem}.pdf.

    file_stem 應傳全域唯一的 case_id；未提供時退回 payload 的 case_seq
    （流水號跨月重複，不同案件會互相覆寫，僅供舊呼叫端相容）。
    """
    stem = file_stem or str(payload.get("case_seq", "unknown"))
    safe_stem = safe_filename(stem, "file_stem")
    output_pdf_path = os.path.join(output_dir, f"申復佐證包_{safe_stem}.pdf")

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

    warnings = list(warnings) + convert_docx_and_merge_pdfs(
        docx_bytes, output_pdf_path, pdf_attachments
    )
    
    return output_pdf_path, warnings
