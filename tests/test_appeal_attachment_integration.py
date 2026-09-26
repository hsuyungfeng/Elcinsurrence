import io
import json

from PIL import Image

from config import settings
from elc_audit_engine.parsers.deduction import DeductionRecord
from elc_audit_engine.generators.appeal import build_appeal_draft, render_appeal_json


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
    return buf.getvalue()


def test_p7_follows_caller_supplied_has_attachment(tmp_path, monkeypatch):
    """p7 由呼叫端傳入的 has_attachment 決定（A-IN-01：build_appeal_draft 為純組裝層）。

    原本 has_attachment=None 時以 record.case_seq 查 attachment_store——流水號跨月
    重複，別案附件會讓本案 p7=Y。附件查詢改由 server 依 CaseStore case_id 進行
    （見 doc/tests/test_attachment_case_key.py::test_appeal_p7_uses_case_id_not_case_seq）。
    """
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    from elc_audit_engine import attachment_store

    rec = DeductionRecord(
        case_seq="case202",
        order_seq="1",
        order_code="64140C",
        non_reimbursed_amount=1000,
        deduction_reason="D14",
    )
    # 同流水號目錄下有附件，但呼叫端未宣告 → 不得自行查出 Y
    attachment_store.save_attachment("case202", _png(), "test.png", order_seq="1")

    draft_no = build_appeal_draft(rec)
    assert draft_no.has_attachment is False
    assert json.loads(render_appeal_json(draft_no))["p7_attachment"] == "N"

    draft_yes = build_appeal_draft(rec, has_attachment=True)
    assert json.loads(render_appeal_json(draft_yes))["p7_attachment"] == "Y"
