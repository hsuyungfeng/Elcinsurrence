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

def test_api_generate_evidence_packet(monkeypatch):
    import server
    from unittest.mock import MagicMock
    
    mock_case_store = MagicMock()
    mock_case = MagicMock()
    mock_case.payload = {"mock": "data"}
    mock_case_store.get.return_value = mock_case
    monkeypatch.setattr(server, "_case_store", mock_case_store)
    
    mock_attachment_store = MagicMock()
    mock_attachment_store.list_attachments.return_value = []
    monkeypatch.setattr(server, "attachment_store", mock_attachment_store)
    
    # Mock write_evidence_packet to return fake paths
    mock_write = MagicMock(return_value=("/tmp/output/packet.pdf", ["warning1"]))
    # Since write_evidence_packet is imported locally in the endpoint, we need to patch it in the module where it is imported from, or just patch the engine function.
    monkeypatch.setattr("elc_audit_engine.generators.evidence_packet.write_evidence_packet", mock_write)
    
    client = server.app.test_client()
    resp = client.post('/api/appeal/evidence-packet/print', json={"case_id": "TEST-123"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["pdf_url"] == "/output/packet.pdf"
    assert "warning1" in data["warnings"]
