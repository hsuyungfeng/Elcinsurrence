import pytest
import io
import os
from unittest.mock import patch, MagicMock

# The module imports will be used for testing
try:
    from elc_audit_engine.generators.evidence_packet.image_processor import process_and_scale_image
    from elc_audit_engine.generators.evidence_packet.builder import build_evidence_packet_docx
except ImportError:
    pass

@pytest.fixture
def cover_info():
    return {
        "case_seq": "T-12345",
        "patient_name": "張三",
        "hospital": "測試醫院"
    }

@pytest.fixture
def tracking_data():
    return {
        "entries": [
            {"order_code": "12345C", "status": "adopt", "edited_text": "測試採用"}
        ]
    }

@pytest.fixture
def timeline_data():
    return {
        "events": [
            {"date": "2023-01-01", "desc": "門診"}
        ]
    }

@pytest.fixture
def appeal_draft():
    return {
        "sections": [
            {"key": "case_summary", "title": "①案情摘要", "text": "測試摘要", "trimmed": False}
        ]
    }

@pytest.fixture
def attachment_records():
    return [
        {"filename": "test1.jpg", "file_path": "/tmp/test1.jpg"}
    ]


def test_image_processing_valid(tmp_path):
    from PIL import Image
    import io
    img_path = tmp_path / "valid.jpg"
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save(img_path)
    
    buf, w, h = process_and_scale_image(str(img_path))
    assert isinstance(buf, io.BytesIO)
    assert w > 0
    assert h > 0

def test_image_processing_corrupt(tmp_path):
    img_path = tmp_path / "corrupt.jpg"
    img_path.write_bytes(b"not an image")
    
    with pytest.raises(Exception):
        process_and_scale_image(str(img_path))

def test_build_evidence_packet_docx(cover_info, tracking_data, timeline_data, appeal_draft, attachment_records):
    doc, warnings = build_evidence_packet_docx(
        cover_info, tracking_data, timeline_data, appeal_draft, attachment_records
    )
    assert doc is not None
    assert isinstance(warnings, list)
    assert len(warnings) > 0  # Should warn about /tmp/test1.jpg missing

