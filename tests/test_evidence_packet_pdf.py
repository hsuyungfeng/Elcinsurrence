import os
import pytest
from docx import Document
from pypdf import PdfReader
from elc_audit_engine.generators.evidence_packet.pdf_exporter import convert_docx_and_merge_pdfs
from elc_audit_engine.rule_repository.docx_tree.doc_converter import soffice_is_functional

requires_soffice = pytest.mark.skipif(
    not soffice_is_functional(),
    reason="soffice not functional"
)

@requires_soffice
def test_convert_docx_and_merge_pdfs(tmp_path):
    # Create a dummy docx
    doc = Document()
    doc.add_heading("Test PDF", level=1)
    
    import io
    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    output_pdf = tmp_path / "output.pdf"
    
    convert_docx_and_merge_pdfs(
        docx_bytes,
        str(output_pdf),
        []
    )
    
    assert output_pdf.exists()
    
    reader = PdfReader(str(output_pdf))
    assert len(reader.pages) >= 1
