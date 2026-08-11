import os
import pytest

from config import settings
from elc_audit_engine.safe_paths import UnsafeIdentifierError

# Note: Implementation module elc_audit_engine.attachment_store will be imported in Wave 1.

def test_save_attachment_valid_png_jpeg_pdf_heic(tmp_path, monkeypatch):
    """Test saving valid attachments across supported formats."""
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    from elc_audit_engine import attachment_store
    from elc_audit_engine.attachment_store import save_attachment, list_attachments, has_attachment

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    rec = save_attachment("case101", png_bytes, "xray.png", order_seq="1")
    assert rec.case_seq == "case101"
    assert rec.order_seq == "1"
    assert os.path.exists(rec.file_path)
    assert has_attachment("case101", "1") is True
    assert len(list_attachments("case101")) == 1

def test_save_attachment_unsafe_path_rejected(tmp_path, monkeypatch):
    """Test that unsafe case_seq or order_seq raises UnsafeIdentifierError."""
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    from elc_audit_engine.attachment_store import save_attachment

    with pytest.raises(UnsafeIdentifierError):
        save_attachment("../etc/passwd", b"\x89PNG\r\n\x1a\n", "test.png")

    with pytest.raises(UnsafeIdentifierError):
        save_attachment("case101", b"\x89PNG\r\n\x1a\n", "test.png", order_seq="..\\1")

def test_save_attachment_invalid_format_rejected(tmp_path, monkeypatch):
    """Test that pseudo or corrupted files raise InvalidAttachmentError."""
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    from elc_audit_engine.attachment_store import save_attachment, InvalidAttachmentError

    with pytest.raises(InvalidAttachmentError):
        save_attachment("case101", b"CORRUPTED_BYTES", "fake.png")
