import os
import pytest
from elc_audit_engine.generators.deduction_print.template import (
    verify_template_hash,
    _load_expected_sha256,
)
from elc_audit_engine.generators.deduction_print.field_mapping import (
    build_deduction_header,
    build_deduction_rows,
)

PRINT_BASE_ODT = os.path.join(
    os.path.dirname(__file__),
    "../officialdocument/電子申復文件格式/RCPI2012R01_核減明細表_print_base.odt",
)

def test_verify_template_hash():
    # Wave 0 test skeleton
    if os.path.isfile(PRINT_BASE_ODT):
        expected = _load_expected_sha256(PRINT_BASE_ODT)
        verify_template_hash(PRINT_BASE_ODT, expected)

def test_deduction_print_mapping():
    records = [{
        "institution_code": "000001",
        "fee_year_month": "202310",
        "submit_date": "20231105",
        "case_class": "01",
        "chart_no": "A001",
        "visit_date": "20231001",
        "id_number": "A123456789",
        "birth_date": "19900101",
        "order_seq": "001",
        "order_code": "12345C",
        "claimed_points": "100",
        "total_qty": "1",
        "non_reimbursed_amount": "50",
        "appeal_item_code": "X01",
        "appeal_item_desc": "Not needed"
    }]
    facility = {"facility_name": "Test Clinic"}
    
    header = build_deduction_header(records, facility)
    assert header["醫療院所名稱"] == "Test Clinic"
    assert header["費用年月"] == "112年10月"
    assert header["申請申報日期"] == "112年11月5日"
    assert header["核減件數"] == "1"
    assert header["總核減點數"] == "50"
    
    rows, warnings = build_deduction_rows(records)
    assert len(rows) == 1
    assert "缺病患姓名" in warnings[0]
    assert "缺醫令名稱" in warnings[1]
    
    row = rows[0]
    assert "****" in row["身分證號/出生日期"]
    assert "A12345****" in row["身分證號/出生日期"]
    assert row["案件分類/病歷號"] == "01 / A001"
    assert row["不予核銷金額/核減點數"] == "50"

def create_mock_odt(path: str):
    import zipfile
    import hashlib
    content_xml = '<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><table:table><table:table-row><table:table-cell><text:p>{機構代碼}</text:p></table:table-cell></table:table-row><table:table-row><table:table-cell><text:p>{序號}</text:p></table:table-cell><table:table-cell><text:p>{姓名}</text:p></table:table-cell></table:table-row></table:table></office:text></office:body></office:document-content>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zout.writestr("content.xml", content_xml.encode("utf-8"))

def test_deduction_print_odt(tmp_path):
    import xml.etree.ElementTree as ET
    from elc_audit_engine.generators.deduction_print.odt_fill import fill_template
    
    base_odt = str(tmp_path / "base.odt")
    create_mock_odt(base_odt)
        
    out_odt = str(tmp_path / "out.odt")
    header = {"機構代碼": "123", "醫療院所名稱": "Test", "核減件數": "2"}
    rows = [{"序號": "1", "姓名": "A"}, {"序號": "2", "姓名": "B"}]
    
    fill_template(base_odt, header, rows, out_odt)
    
    assert os.path.exists(out_odt)
    import zipfile
    with zipfile.ZipFile(out_odt, "r") as zin:
        content = zin.read("content.xml").decode("utf-8")
        
    assert "123" in content
    assert ">A<" in content
    assert ">B<" in content

from elc_audit_engine.rule_repository.docx_tree.doc_converter import soffice_is_functional
requires_soffice = pytest.mark.skipif(
    not soffice_is_functional(),
    reason="soffice not functional"
)

@requires_soffice
def test_deduction_print_e2e(tmp_path):
    from elc_audit_engine.generators.deduction_print import write_deduction_print
    
    real_odt = os.path.join(
        os.path.dirname(__file__),
        "../officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.odt",
    )
    if not os.path.isfile(real_odt):
        pytest.skip("Real template missing")
        
    base_odt = str(tmp_path / "base_e2e.odt")
    import zipfile
    with zipfile.ZipFile(real_odt, "r") as zin:
        infos = zin.infolist()
        content = zin.read("content.xml").decode("utf-8")
    
    # 替換原模板中的文字成為 placeholders，使用短字眼避免被 tag 切斷
    content = content.replace("數量", "{案件分類/病歷號}").replace("金額", "{序號}").replace("代號字碼", "{機構代碼}").replace("醫療院所名稱", "{醫療院所名稱}")
    
    with zipfile.ZipFile(real_odt, "r") as zin:
        with zipfile.ZipFile(base_odt, "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
            for info in infos:
                if info.filename == "mimetype": continue
                if info.filename == "content.xml":
                    zout.writestr("content.xml", content.encode("utf-8"))
                else:
                    zout.writestr(info.filename, zin.read(info.filename))
    
    # We also need a sidecar sha256 for base_e2e.odt so template verification passes
    import hashlib
    digest = hashlib.sha256()
    with open(base_odt, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    with open(str(tmp_path / "base_e2e.sha256"), "w", encoding="utf-8") as f:
        f.write(digest.hexdigest())
    
    records = [{
        "case_class": "01",
        "chart_no": "A001",
        "patient_name": "TestE2E"
    }]
    facility = {"facility_name": "ClinicE2E"}
    
    out_dir = tmp_path / "out"
    pdf_path, warnings = write_deduction_print(
        output_dir=out_dir,
        file_stem="test1",
        records=records,
        facility=facility,
        template_odt_path=base_odt,
        soffice_timeout=30
    )
    
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith("核減明細_test1.pdf")
    
    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    assert len(reader.pages) >= 1
    text = reader.pages[0].extract_text().replace("\n", "")
    assert "A001" in text
    assert "ClinicE2E" in text

def test_deduction_print_security(tmp_path):
    from elc_audit_engine.generators.deduction_print.odt_fill import fill_template
    
    base_odt = str(tmp_path / "base_sec.odt")
    create_mock_odt(base_odt)
        
    out_odt = str(tmp_path / "out_sec.odt")
    header = {"機構代碼": "123"}
    rows = [{"序號": "1", "姓名": "<script>alert(1)</script>&\"'"}]
    
    fill_template(base_odt, header, rows, out_odt)
    
    import zipfile
    with zipfile.ZipFile(out_odt, "r") as zin:
        content = zin.read("content.xml").decode("utf-8")
        
    # The literal characters should be escaped in XML
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
