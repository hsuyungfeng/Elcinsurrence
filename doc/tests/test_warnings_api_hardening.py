"""Warning 第二批：API 強化（A-WR-02/04/11）。"""
from elc_audit_engine.api.app import MAX_CONTENT_LENGTH
from elc_audit_engine.api.routes.printing import MAX_PRINT_RECORDS
from elc_audit_engine.api.uploads import import_error_message
import io
from unittest.mock import MagicMock


def test_oversized_request_rejected_with_413(client):
    body = b"x" * (MAX_CONTENT_LENGTH + 1)
    resp = client.post("/api/sampling/import", data={"file": (io.BytesIO(body), "a.csv")},
                       content_type="multipart/form-data")
    assert resp.status_code == 413


def test_print_records_must_be_bounded_dicts(client):
    assert client.post("/api/deduction/print", json={"records": ["x"]}).status_code == 400
    many = [{"case_seq": "1"}] * (MAX_PRINT_RECORDS + 1)
    assert client.post("/api/deduction/print", json={"records": many}).status_code == 400


def test_pdf_failure_does_not_leak_details(client, monkeypatch):
    boom = MagicMock(side_effect=RuntimeError("soffice stderr /tmp/tmpabc123/secret path hash=deadbeef"))
    monkeypatch.setattr("elc_audit_engine.generators.deduction_print.write_deduction_print", boom)
    resp = client.post("/api/deduction/print", json={"records": [{"case_seq": "1"}]})
    assert resp.status_code == 500
    msg = resp.get_json()["message"]
    assert "tmp" not in msg and "deadbeef" not in msg


def test_import_error_hides_os_details():
    from elc_audit_engine.ingest import MediaExtractError
    from elc_audit_engine.parsers.deduction import DeductionFileError

    assert "/tmp" not in import_error_message(MediaExtractError("tesseract failed on /tmp/x.png"))
    try:
        try:
            raise OSError("/data/uploads/raw/abc.csv: permission denied")
        except OSError as os_exc:
            raise DeductionFileError(f"無法讀取核減明細檔: {os_exc}") from os_exc
    except DeductionFileError as exc:
        assert "/data" not in import_error_message(exc)
    assert "18 欄" in import_error_message(DeductionFileError("需為 18 欄"))


def test_import_does_not_write_phi_snapshot(client, tmp_path):
    csv = "流水號,病歷號,病患姓名,醫令代碼,醫令名稱,就醫日期,科別,SOAP\n1,M1,甲,14050B,HbA1c,20260701,家醫科,S\n"
    resp = client.post("/api/sampling/import",
                       data={"file": (io.BytesIO(csv.encode("utf-8-sig")), "a.csv")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert "saved_to" not in resp.get_json()
    assert not list((tmp_path / "uploads").glob("*.json"))
