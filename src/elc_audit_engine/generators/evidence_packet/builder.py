import os
import io
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from elc_audit_engine.generators.evidence_packet.image_processor import process_and_scale_image

def _fmt(value) -> str:
    """Defensive display formatter converting None/empty to em-dash placeholder."""
    if value is None or value == "":
        return "—"
    return str(value)

def _add_warning_callout(doc: Document, text: str):
    tbl = doc.add_table(rows=1, cols=1)
    cell = tbl.cell(0, 0)
    p = cell.paragraphs[0]
    run = p.add_run(f"⚠ {text}")
    run.font.color.rgb = RGBColor(180, 0, 0)

def build_evidence_packet_docx(
    cover_info: dict,
    tracking_data: dict | None,
    timeline_data: dict | None,
    appeal_draft: dict,
    attachment_records: list,
    facility: dict | None = None,
) -> tuple[Document, list[str]]:
    doc = Document()
    warnings = []

    # A4 Page Setup (2.54cm margins)
    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(2.54)
        section.right_margin = Cm(2.54)

    # Section 1: Cover Page
    doc.add_heading("申復佐證包", level=0)
    
    doc.add_heading("Section 1: Cover Page", level=1)
    # A-IN-03：封面實際呈現院所與統計欄位（原本已計算卻未使用）；缺值顯示「—」
    facility = facility or {}
    cover_lines = [
        ("醫療院所", f"{_fmt(facility.get('name'))}（{_fmt(facility.get('code'))}）"),
        ("案件分類", _fmt(cover_info.get("case_class"))),
        ("案件流水號", _fmt(cover_info.get("case_seq"))),
        ("就醫日期", _fmt(cover_info.get("visit_date"))),
        ("費用年月", _fmt(cover_info.get("fee_year_month"))),
        ("核減醫令筆數", _fmt(cover_info.get("total_denied_orders"))),
        ("不予核銷點數合計", _fmt(cover_info.get("total_non_reimbursed_points"))),
        ("申復點數合計", _fmt(cover_info.get("total_claimed_points"))),
        ("影像佐證附件數", _fmt(cover_info.get("total_attachments"))),
    ]
    for label, value in cover_lines:
        doc.add_paragraph(f"{label}: {value}")

    # Section 2: Audit Trail
    doc.add_heading("Section 2: Audit Trail", level=1)
    entries = (tracking_data or {}).get("entries", [])
    if not entries:
        doc.add_paragraph("無審核軌跡")
    for entry in entries:
        if "to_state" in entry:
            # CaseStore 轉換歷史（TransitionRecord）
            line = (
                f"{_fmt(entry.get('created_at'))}  "
                f"{_fmt(entry.get('from_state'))} → {_fmt(entry.get('to_state'))}  "
                f"操作者: {_fmt(entry.get('actor'))}"
            )
            if entry.get("reason"):
                line += f"  原因: {entry['reason']}"
            doc.add_paragraph(line)
        else:
            doc.add_paragraph(f"醫令: {entry.get('order_code', '')}, 狀態: {entry.get('status', '')}")

    # Section 3: Record Summary
    doc.add_heading("Section 3: Record Summary", level=1)
    if timeline_data is None:
        # 「未查詢」與「查無紀錄」必須可區分（P1-1）
        doc.add_paragraph("病史未查詢（本佐證包未附病歷摘要）")
        events = []
    else:
        events = timeline_data.get("events", [])
        if not events:
            doc.add_paragraph("查詢期間無就醫紀錄")
    for event in events:
        doc.add_paragraph(f"{event.get('date', '')}: {event.get('desc', '')}")

    # Section 4: Appeal Draft
    doc.add_heading("Section 4: Appeal Draft", level=1)
    draft_sections = appeal_draft.get("sections", [])
    for sec in draft_sections:
        doc.add_heading(sec.get("title", ""), level=2)
        doc.add_paragraph(sec.get("text", ""))

    # Appendix (Images)
    if attachment_records:
        doc.add_page_break()
        doc.add_heading("Appendix: Attachments", level=1)
        
        for record in attachment_records:
            file_path = record.get("file_path")
            filename = record.get("filename") or (
                os.path.basename(file_path) if file_path else "未知檔名"
            )

            doc.add_heading(f"附件: {filename}", level=2)

            if record.get("mime_type") == "application/pdf":
                # PDF 附件於文件尾端整份併入（pdf_exporter），不送 PIL（A-WR-08）
                doc.add_paragraph("PDF 附件，全文附於本佐證包末頁之後。")
                continue

            if not file_path or not os.path.exists(file_path):
                msg = f"附件檔【{filename}】載入失敗: 檔案不存在"
                warnings.append(msg)
                _add_warning_callout(doc, msg)
                continue

            try:
                buf, w, h = process_and_scale_image(file_path)
                doc.add_picture(buf, width=Cm(w), height=Cm(h))
            except Exception as e:
                # 錯誤訊息不含伺服器路徑（PIL 例外字串常帶完整路徑）
                msg = f"附件檔【{filename}】載入失敗（{type(e).__name__}）"
                warnings.append(msg)
                _add_warning_callout(doc, msg)

    return doc, warnings
