import json
import pytest
from config import settings
from elc_audit_engine.parsers.deduction import DeductionRecord
from elc_audit_engine.generators.appeal import build_appeal_draft, render_appeal_json

def test_appeal_has_attachment_driven_by_attachment_store(tmp_path, monkeypatch):
    """Test build_appeal_draft and render_appeal_json dynamically query attachment_store when has_attachment is None."""
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    from elc_audit_engine import attachment_store

    rec = DeductionRecord(
        case_seq="case202",
        order_seq="1",
        order_code="64140C",
        non_reimbursed_amount=1000,
        deduction_reason="D14",
    )

    # 1. No physical files -> has_attachment == False -> p7 == "N"
    draft_no = build_appeal_draft(rec)
    assert draft_no.has_attachment is False
    json_no = json.loads(render_appeal_json(draft_no))
    assert json_no["p7_attachment"] == "N"

    import io
    from PIL import Image
    img_buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(img_buf, format="PNG")
    png_bytes = img_buf.getvalue()

    # 2. Add physical attachment
    attachment_store.save_attachment("case202", png_bytes, "test.png", order_seq="1")

    # 3. Dynamic lookup -> has_attachment == True -> p7 == "Y"
    draft_yes = build_appeal_draft(rec)
    assert draft_yes.has_attachment is True
    json_yes = json.loads(render_appeal_json(draft_yes))
    assert json_yes["p7_attachment"] == "Y"
