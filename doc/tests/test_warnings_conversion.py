"""Warning 第二批：轉檔與附件（A-WR-06/08、B-WR-18/20）。"""
from elc_audit_engine.api.uploads import import_error_message
import io
import os
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfWriter

from elc_audit_engine.generators import _soffice
from elc_audit_engine.generators._soffice import SofficeConvertError, convert_to_pdf
from elc_audit_engine.generators.evidence_packet.builder import build_evidence_packet_docx
from elc_audit_engine.generators.evidence_packet.pdf_exporter import convert_docx_and_merge_pdfs
from elc_audit_engine.ingest import media


def test_soffice_exit0_without_output_does_not_return_stale_pdf(tmp_path, monkeypatch):
    """A-WR-06：soffice 回 0 卻未產出時，不得把既有同名舊 PDF 當成結果。"""
    dest = tmp_path / "out.pdf"
    dest.write_bytes(b"%PDF-OLD")
    src = tmp_path / "in.odt"
    src.write_bytes(b"x")
    monkeypatch.setattr(_soffice.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stderr=b""))
    with pytest.raises(SofficeConvertError):
        convert_to_pdf(str(src), str(dest))
    assert dest.read_bytes() == b"%PDF-OLD"  # 失敗不動既有檔，但也不回傳它


def test_soffice_timeout_is_wrapped(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("soffice", 1)

    monkeypatch.setattr(_soffice.subprocess, "run", boom)
    with pytest.raises(SofficeConvertError):
        convert_to_pdf(str(tmp_path / "a.odt"), str(tmp_path / "a.pdf"))


def _blank_pdf(path, encrypted=False):
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    if encrypted:
        w.encrypt("pw")
    with open(path, "wb") as f:
        w.write(f)


def test_pdf_attachment_not_rendered_via_pil_and_no_path_leak(tmp_path):
    """A-WR-08"""
    pdf = tmp_path / "scan.pdf"
    _blank_pdf(pdf)
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    doc, warnings = build_evidence_packet_docx(
        {}, None, None, {},
        [
            {"file_path": str(pdf), "filename": "scan.pdf", "mime_type": "application/pdf"},
            {"file_path": str(bad), "filename": "broken.png", "mime_type": "image/png"},
            {"file_path": None, "filename": None, "mime_type": "image/png"},
        ],
    )
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "PDF 附件，全文附於本佐證包末頁之後。" in texts
    assert not any("scan.pdf" in w for w in warnings)
    assert all(str(tmp_path) not in w for w in warnings)


@pytest.mark.skipif(not __import__("shutil").which("soffice"), reason="needs soffice")
def test_encrypted_pdf_attachment_skipped_with_warning(tmp_path):
    from docx import Document

    buf = io.BytesIO()
    Document().save(buf)
    enc = tmp_path / "locked.pdf"
    _blank_pdf(enc, encrypted=True)
    ok = tmp_path / "ok.pdf"
    _blank_pdf(ok)
    out = tmp_path / "packet.pdf"
    warnings = convert_docx_and_merge_pdfs(buf.getvalue(), str(out), [str(enc), str(ok)])
    assert out.exists()
    assert any("locked.pdf" in w for w in warnings)


def test_pdf_page_limit(tmp_path, monkeypatch):
    """B-WR-20"""
    monkeypatch.setattr(media, "pdf_page_count", lambda p: media.MAX_PDF_PAGES + 1)
    with pytest.raises(media.MediaLimitError):
        media.render_pdf_pages("x.pdf", str(tmp_path))
    msg = import_error_message(media.MediaLimitError("PDF 共 51 頁，超過 50 頁上限"))
    assert "50 頁上限" in msg


def test_doc_converter_requires_output(tmp_path, monkeypatch):
    """B-WR-18"""
    from elc_audit_engine.rule_repository.docx_tree import doc_converter

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.doc").write_bytes(b"x")
    monkeypatch.setattr(doc_converter.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    with pytest.raises(RuntimeError, match="未產出"):
        doc_converter.convert_doc_files(str(tmp_path / "src"), str(tmp_path / "stage"))
