"""Phase 11 紙本申復清單列印測試（Wave 0 脚手架）。

Test matrix（RESEARCH Validation Architecture）：
- `-k mapping`：欄位組裝純函式（官方欄 ← 資料來源對應、缺欄誠實降級、分頁）
- `-k odt`：content.xml 注入（ET 解析產出 XML 斷言院所/案件/醫令/分頁/頁數欄/合計僅末頁）
- `-k e2e`／`-k copies`／`-k security`／`-k config`：由 11-02/11-03 依序添加
"""

import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import pytest

from elc_audit_engine.rule_repository.docx_tree.doc_converter import (
    soffice_is_functional,
)

# Module 級 skip：soffice 依賴測試（-k e2e/copies/security 的轉檔段）在
# headless 轉檔不可用環境下整組略過（比照 test_doc_converter.py）。
requires_soffice = pytest.mark.skipif(
    not soffice_is_functional(),
    reason="soffice headless conversion unavailable (real-conversion probe failed) — .odt→PDF tests need it",
)

# 官方模板路徑（git-tracked 版控資產，D-02）。
OFFICIAL_ODT = (
    "officialdocument/電子申復文件格式/"
    "30396_1_1050105-1門診診療費用申復清單.odt"
)
OFFICIAL_ODT_3 = (
    "officialdocument/電子申復文件格式/"
    "30396_3_無刪除線1050105-OD-門診診療費用申復清單-.odt"
)

# ── 資料構造器（比照 test_appeal.py `_record`/`_draft` 模式）───


def _facility(**overrides):
    """院所層資料（D-04 dict；與 conftest facility_config 同值域）。"""
    base = {
        "code": "01015C",
        "name": "測試醫療院所",
        "address": "測試市測試區測試路1號",
        "physician_name": "測試醫師",
    }
    base.update(overrides)
    return base


def _submission(**overrides):
    """submission dict（患者層欄位唯一來源；自由 dict 契約）。"""
    base = {
        "case_class": "D2",
        "case_seq": "18",
        "id_number": "F10291****",
        "patient_name": "陳小明",
        "primary_diagnosis": "J189",
        "clinic": "內科",
        "submit_date": "2021-08-03",
        "orders": [
            {
                "code": "E5002C",
                "total_qty": "1",
                "points": "300",
                "seq": "1",
            }
        ],
    }
    base.update(overrides)
    return base


def _payload(**overrides):
    """appeal_{流水號}.json 內容（render_appeal_json 格式 dict）。"""
    base = {
        "format": "appeal-draft/v1",
        "case_class": "D2",
        "case_seq": "18",
        "order_seq": "1",
        "order_code": "E5002C",
        "visit_date": "2021-06-23",
        "fee_year_month": "202106",
        "deduction_upper_bound": 300,
        "deduction_reason": "VPN資料複核不通過",
        "is_appealing": True,
        "p1_order_seq": "1",
        "p2_order_code": "E5002C",
        "p6_points": 300,
        "p8_reason1": "申復理由一",
        "p9_reason2": "申復理由二",
    }
    base.update(overrides)
    return base


# ── Task 1: -k mapping（欄位組裝純函式）───────────────────────


def test_mapping_build_rows_full_source_14_columns():
    """Test 1：完整資料來源（payload＋submission 層＋facility）產出 14 鍵 dict。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_rows

    rows, warnings = build_rows(_payload(), _facility(), submission=_submission())

    assert len(rows) == 1
    row = rows[0]
    assert list(row.keys()) == [
        "案件分類",
        "流水號",
        "身份證字號",
        "姓名",
        "傷病名稱",
        "醫令序",
        "內容",
        "數量",
        "金額",
        "理由",
        "審核意見",
        "補付數量",
        "單價",
        "補付金額",
    ]
    # 案件層
    assert row["案件分類"] == "D2"          # ← payload.case_class
    assert row["流水號"] == "18"             # ← payload.case_seq
    # 患者層（submission）
    assert row["身份證字號"] == "F10291****"  # ← submission.id_number 遮罩照印
    assert row["姓名"] == "陳小明"            # ← submission.patient_name
    assert row["傷病名稱"] == "J189"          # ← submission.primary_diagnosis
    # 醫令層
    assert row["醫令序"] == "1"              # ← payload.order_seq（p1_order_seq）
    assert row["內容"] == "E5002C"           # ← payload.order_code（p2_order_code）
    assert row["數量"] == "1"                # ← submission.orders[seq=1].total_qty（p10）
    assert row["金額"] == "300"              # ← submission.orders[seq=1].points（p12）
    # 理由 = p8/p9 非空段合併
    assert row["理由"] == "申復理由一申復理由二"
    # 健保署填列欄位一律留空
    assert row["審核意見"] == ""
    assert row["補付數量"] == ""
    assert row["單價"] == ""
    assert row["補付金額"] == ""
    # 完整來源無警告
    assert warnings == []


def test_mapping_build_rows_submission_absent_degrades():
    """Test 2：submission 缺席 → 患者層/數量/金額留空＋warnings，不拋錯不捏造。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_rows

    rows, warnings = build_rows(_payload(), _facility())  # submission 缺席

    assert len(rows) == 1
    row = rows[0]
    assert row["身份證字號"] == ""
    assert row["姓名"] == ""
    assert row["傷病名稱"] == ""
    assert row["數量"] == ""
    assert row["金額"] == ""
    # 案件層欄位仍在（payload 有）
    assert row["案件分類"] == "D2"
    assert row["醫令序"] == "1"
    # warnings 含欄位名（審查科別屬 submission 層，也納入）
    for field in ("身份證字號", "姓名", "傷病名稱", "審查科別", "數量", "金額"):
        assert field in warnings


def test_mapping_paginate_splits_16_rows():
    """Test 3：16 行醫令 → [15 行, 1 行] 兩頁。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import paginate

    rows = [{"流水號": str(i)} for i in range(16)]
    pages = paginate(rows, per_page=15)

    assert [len(p) for p in pages] == [15, 1]
    assert pages[0][0]["流水號"] == "0"
    assert pages[1][0]["流水號"] == "15"


def test_mapping_build_header_7_fields():
    """Test 4：頭表 7 欄組裝（代號字碼/院所名稱/審查科別/原申報類別/原申報日期/年度/月份）。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_header

    header = build_header(_facility(), _payload(), _submission())

    assert header["代號字碼"] == "01015C"
    assert header["醫療院所名稱"] == "測試醫療院所"
    assert header["審查科別"] == "內科"
    # 原申報類別：預設「□送核」
    assert header["原申報類別"] == "□送核"
    # 原申報日期：submit_date 主（ISO→民國年月日）；年度/月份由 fee_year_month 拆解
    assert header["原申報日期"] == "110年8月3日"
    assert header["年度"] == "110"
    assert header["月份"] == "06"


def test_mapping_build_header_report_type_override():
    """Test 4b：原申報類別可由 report_type 覆寫為「□補報」。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_header

    header = build_header(_facility(), _payload(), _submission(), report_type="補報")
    assert header["原申報類別"] == "□補報"


def test_mapping_build_header_date_fallback_fee_year_month():
    """Test 4c：無 submit_date → 原申報日期備援 fee_year_month。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_header

    submission = _submission()
    del submission["submit_date"]
    header = build_header(_facility(), _payload(), submission)
    assert header["原申報日期"] == "110年6月"


# ── Task 2: -k odt（content.xml 注入＋zip 重打包＋分頁）──────────


def _read_content_xml(odt_path):
    """讀取產出 ODT 的 content.xml 並回傳 ET root（供斷言）。"""
    import re as _re

    with zipfile.ZipFile(odt_path) as zf:
        content_raw = zf.read("content.xml").decode("utf-8")
    root_open = _re.search(r"<office:document-content[^>]*>", content_raw).group(0)
    for m in _re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', root_open):
        ET.register_namespace(m.group(1) or "", m.group(2))
    root_el = ET.fromstring(content_raw)
    return content_raw, root_el


def _find_tables(root_el):
    """以完整命名空間路徑取得全部 table。"""
    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }
    body = root_el.find("office:body/office:text", ns)
    return body.findall("table:table", ns)


def _cell_full_text(cell):
    return "".join(cell.itertext())


def test_odt_fill_template_injects_14_columns(tmp_path):
    """Test 1：注入後主表 row2 的 14 資料欄 cell 文本與傳入資料一致（cell[13] 留空）。"""
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    rows = [
        {
            "案件分類": "D2",
            "流水號": "18",
            "身份證字號": "F10291****",
            "姓名": "陳小明",
            "傷病名稱": "J189",
            "醫令序": "1",
            "內容": "E5002C",
            "數量": "1",
            "金額": "300",
            "理由": "申復理由一申復理由二",
            "審核意見": "",
            "補付數量": "",
            "單價": "",
            "補付金額": "",
        }
    ]
    header = {
        "代號字碼": "01015C",
        "醫療院所名稱": "測試醫療院所",
        "審查科別": "內科",
        "原申報類別": "□送核",
        "原申報日期": "110年8月3日",
        "年度": "110",
        "月份": "06",
    }
    out_path = str(tmp_path / "filled1.odt")
    result = fill_template(OFFICIAL_ODT, header, [rows], out_path)
    assert result == out_path

    _, root_el = _read_content_xml(out_path)
    tables = _find_tables(root_el)
    assert len(tables) == 9  # 單頁：3 聯 × 3 tables
    main = tables[1]  # 第一聯主表
    rows_els = main.findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")
    row2 = rows_els[2].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
    assert len(row2) == 15
    # cell[0..12]＋cell[14]＝14 資料欄；cell[13] 單價續列留空跳過
    assert _cell_full_text(row2[0]) == "D2"
    assert _cell_full_text(row2[1]) == "18"
    assert _cell_full_text(row2[2]) == "F10291****"
    assert _cell_full_text(row2[3]) == "陳小明"
    assert _cell_full_text(row2[4]) == "J189"
    assert _cell_full_text(row2[5]) == "1"
    assert _cell_full_text(row2[6]) == "E5002C"
    assert _cell_full_text(row2[7]) == "1"
    assert _cell_full_text(row2[8]) == "300"
    assert _cell_full_text(row2[9]) == "申復理由一申復理由二"
    assert _cell_full_text(row2[10]) == ""
    assert _cell_full_text(row2[11]) == ""
    assert _cell_full_text(row2[12]) == ""
    assert _cell_full_text(row2[13]) == ""  # 單價續列：留空
    assert _cell_full_text(row2[14]) == ""


def test_odt_fill_template_paginates_16_rows(tmp_path):
    """Test 2：16 行 → 每聯 2 組（頭表＋主表），頁數 1/2、2/2，合計列與說明表僅末組。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import paginate
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    rows = [
        {
            "案件分類": "D2",
            "流水號": str(i),
            "身份證字號": "",
            "姓名": "",
            "傷病名稱": "",
            "醫令序": str(i),
            "內容": f"O{i}",
            "數量": "1",
            "金額": "100",
            "理由": "",
            "審核意見": "",
            "補付數量": "",
            "單價": "",
            "補付金額": "",
        }
        for i in range(16)
    ]
    pages = paginate(rows, per_page=15)
    assert [len(p) for p in pages] == [15, 1]

    header = {
        "代號字碼": "01015C",
        "醫療院所名稱": "測試醫療院所",
        "審查科別": "內科",
        "原申報類別": "□送核",
        "原申報日期": "110年8月3日",
        "年度": "110",
        "月份": "06",
    }
    out_path = str(tmp_path / "filled2.odt")
    fill_template(OFFICIAL_ODT, header, pages, out_path)

    _, root_el = _read_content_xml(out_path)
    tables = _find_tables(root_el)
    # 3 聯 × 每聯 2 頁（每頁 頭表+主表，+末頁說明表）→ 每聯 5 tables
    assert len(tables) == 15, f"expected 15 tables, got {len(tables)}"

    # 每聯：tables[0]=頁1頭表, [1]=頁1主表, [2]=頁2頭表, [3]=頁2主表, [4]=說明表
    for copy_idx in range(3):
        base = copy_idx * 5
        # 頁數欄：頭表最後一個 cell 值
        h1 = tables[base].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")[0]
        h1_cells = h1.findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
        assert _cell_full_text(h1_cells[-1]) == "1/2"
        h2 = tables[base + 2].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")[0]
        h2_cells = h2.findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
        assert _cell_full_text(h2_cells[-1]) == "2/2"

        # 頁1主表：15 rows（無合計列）；頁2主表：18 rows（含合計列）
        t1 = tables[base + 1].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")
        t2 = tables[base + 3].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")
        assert len(t1) == 17, f"page1 main rows: {len(t1)}"
        assert len(t2) == 18, f"page2 main rows: {len(t2)}"

        # 頁1主表 row2 填 15 行、頁2主表 row2 填 1 行
        p1_row2 = t1[2].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
        assert _cell_full_text(p1_row2[0]) == "D2"
        assert _cell_full_text(p1_row2[5]) == "0"
        p2_row2 = t2[2].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
        assert _cell_full_text(p2_row2[0]) == "D2"
        assert _cell_full_text(p2_row2[5]) == "15"

        # 末頁合計列 row17：cell[0]＝「合計」、cell[2]＝16、補付欄空
        total_row = t2[17].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
        assert _cell_full_text(total_row[0]) == "合計"
        assert _cell_full_text(total_row[2]) == "16"
        assert _cell_full_text(total_row[6]) == "補付金額"  # 標題保留
        assert _cell_full_text(total_row[7]) == ""          # 補付金額值留空


def test_odt_fill_template_escapes_xml_specials(tmp_path):
    """Test 3：欄位含 `<script>` 與 `&` → 產出 content.xml 可被 ET 解析且文本等於原值。"""
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    evil = '<script>alert("x&y")</script>'
    rows = [
        {
            "案件分類": "D2",
            "流水號": "99",
            "身份證字號": "",
            "姓名": "",
            "傷病名稱": "",
            "醫令序": "1",
            "內容": evil,
            "數量": "",
            "金額": "",
            "理由": "a & b < c",
            "審核意見": "",
            "補付數量": "",
            "單價": "",
            "補付金額": "",
        }
    ]
    header = {
        "代號字碼": "01015C",
        "醫療院所名稱": "測試醫療院所",
        "審查科別": "內科",
        "原申報類別": "□送核",
        "原申報日期": "110年8月3日",
        "年度": "110",
        "月份": "06",
    }
    out_path = str(tmp_path / "filled3.odt")
    fill_template(OFFICIAL_ODT, header, [rows], out_path)

    content_raw, root_el = _read_content_xml(out_path)
    # ET 已成功解析（無 XML 損毀）；原始 raw 含轉義、解析後文本還原
    tables = _find_tables(root_el)
    main = tables[1]
    rows_els = main.findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row")
    row2 = rows_els[2].findall("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell")
    assert _cell_full_text(row2[6]) == evil
    assert _cell_full_text(row2[9]) == "a & b < c"
    assert "&lt;" in content_raw and "&amp;" in content_raw


def test_odt_fill_template_missing_template_raises(tmp_path):
    """Test 4：模板路徑不存在 → FileNotFoundError。"""
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    with pytest.raises(FileNotFoundError):
        fill_template(
            str(tmp_path / "no_such_template.odt"),
            {},
            [[]],
            str(tmp_path / "out.odt"),
        )


def test_odt_fill_zip_mimetype_first_stored(tmp_path):
    """產出 ODT：mimetype 為首條目且 compress_type=ZIP_STORED。"""
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    rows = [
        {
            "案件分類": "D2",
            "流水號": "1",
            "身份證字號": "",
            "姓名": "",
            "傷病名稱": "",
            "醫令序": "1",
            "內容": "E5002C",
            "數量": "",
            "金額": "",
            "理由": "",
            "審核意見": "",
            "補付數量": "",
            "單價": "",
            "補付金額": "",
        }
    ]
    header = {"代號字碼": "01015C", "醫療院所名稱": "測試醫療院所"}
    out_path = str(tmp_path / "filled4.odt")
    fill_template(OFFICIAL_ODT, header, [rows], out_path)

    with zipfile.ZipFile(out_path) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/vnd.oasis.opendocument.text"


# ── Task 1 (11-02): -k base（壓縮基準模板 build_print_base）────────


def _build_print_base(tmp_path) -> tuple[str, str]:
    """以官方 ODT 產生壓縮基準模板（tmp_path 隔離），回傳 (odt, sha256)。"""
    from elc_audit_engine.generators.appeal_print.template import build_print_base

    out_odt = str(tmp_path / "print_base.odt")
    sha_out = str(tmp_path / "print_base.sha256")
    result = build_print_base(OFFICIAL_ODT, out_odt, sha256_out=sha_out)
    assert result == out_odt
    return out_odt, sha_out


@requires_soffice
def test_base_build_print_base_pdf_3_pages(tmp_path):
    """Test 1（base, @requires_soffice）：壓縮基準模板經 soffice 轉 PDF → 總頁數=3（每聯一頁）。"""
    from pypdf import PdfReader

    out_odt, _ = _build_print_base(tmp_path)
    # soffice 輸出檔名＝輸入檔名去副檔名＋.pdf
    pdf_path = str(tmp_path / "print_base.pdf")
    # 比照 write_appeal_print 的 soffice 呼叫（-env:UserInstallation 導向 tmp profile）
    import subprocess
    from pathlib import Path

    profile_dir = tmp_path / "lo_profile"
    profile_dir.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "soffice",
            f"-env:UserInstallation={Path(profile_dir).as_uri()}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            out_odt,
        ],
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0
    assert os.path.isfile(pdf_path), "soffice 未產出 PDF"
    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 3, f"壓縮基準模板應為 3 頁（每聯一頁），實際 {len(reader.pages)}"


def test_base_build_print_base_odt_structure_9_tables(tmp_path):
    """Test 2（base）：產物 *_print_base.odt 存在、content.xml 可解析（9 tables 結構不破壞）。"""
    import os as _os

    out_odt, _ = _build_print_base(tmp_path)
    assert _os.path.isfile(out_odt)

    content_raw, root_el = _read_content_xml(out_odt)
    tables = _find_tables(root_el)
    assert len(tables) == 9, f"壓縮模板應保留 9 tables（3 聯×3），實際 {len(tables)}"
    # 主表 18 rows（row0 大標題/row1 表頭/row2~16 資料/row17 合計）結構不變
    main = tables[1]
    rows_el = main.findall(
        "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"
    )
    assert len(rows_el) == 18
    # 資料行 row2 的 15 cells 保留
    row2 = rows_el[2].findall(
        "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"
    )
    assert len(row2) == 15


def test_base_build_print_base_sha256_file_matches(tmp_path):
    """Test 3（base）：產物 sha256 與同目錄 *_print_base.sha256 內容一致。"""
    import hashlib as _hashlib

    out_odt, sha_out = _build_print_base(tmp_path)

    digest = _hashlib.sha256()
    with open(out_odt, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)

    with open(sha_out, encoding="utf-8") as f:
        recorded = f.read().strip()
    assert recorded == digest.hexdigest()


def test_base_official_print_base_asset_committed(tmp_path):
    """基準模板資產已入庫（git-tracked 路徑存在；T-11-06 供應鏈資產）。"""
    import os as _os

    base_asset = (
        "officialdocument/電子申復文件格式/"
        "30396_1_1050105-1門診診療費用申復清單_print_base.odt"
    )
    sha_asset = base_asset[: -len(".odt")] + ".sha256"
    assert _os.path.isfile(base_asset), "壓縮基準模板資產未產生"
    assert _os.path.isfile(sha_asset), "壓縮基準模板 sha256 資產未產生"
    # 與入庫 sha256 檔內容一致（防竄改基準）
    from elc_audit_engine.generators.appeal_print.odt_fill import (
        verify_template_hash,
    )

    with open(sha_asset, encoding="utf-8") as f:
        expected = f.read().strip()
    verify_template_hash(base_asset, expected)


# ── Task 2 (11-02): -k e2e／-k security（write/render 端到端）────────

# 壓縮基準模板資產（11-02 Task 1 產出，git-tracked）。
PRINT_BASE_ODT = (
    "officialdocument/電子申復文件格式/"
    "30396_1_1050105-1門診診療費用申復清單_print_base.odt"
)


def extract_pdf_text(pdf_path) -> str:
    """從 PDF 提取全部文本（A2 fallback 鏈）。

    優先 pypdf；若 pypdf 提取為空/拋例外（RESEARCH A2 未成立）→ 切換
    `pdftotext`（poppler，soffice 同屬系統套件）；兩路皆無法提取才回傳
    ""。測試內註記實際採用路徑。
    """
    try:
        from pypdf import PdfReader

        text = "".join(p.extract_text() or "" for p in PdfReader(pdf_path).pages)
        if text.strip():
            return text
    except Exception:  # A2：pypdf 中文提取失敗 → fallback
        pass
    try:
        r = subprocess.run(
            ["pdftotext", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    return ""


@requires_soffice
def test_e2e_write_appeal_print_pdf_3_pages_key_text(tmp_path):
    """Test 1（e2e）：write_appeal_print 產出 3 頁 PDF，文本含關鍵欄位值。"""
    from elc_audit_engine.generators.appeal_print import write_appeal_print

    output_dir = tmp_path / "out"
    pdf_path, warnings = write_appeal_print(
        output_dir,
        "test_case_001",
        _payload(),
        _facility(),
        template_odt_path=PRINT_BASE_ODT,
        submission=_submission(),
    )
    assert os.path.isfile(pdf_path)
    assert pdf_path.endswith("申復清單_test_case_001.pdf")

    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 3, f"單醫令應為 3 頁（每聯一頁），實際 {len(reader.pages)}"

    text = extract_pdf_text(pdf_path)
    assert text, "pypdf/pdftotext 皆無法提取文本（A2 fallback 兩路皆敗）"
    # 官方頭表標題為直排文字，pdftotext 會拆成多行——去空白後斷言子串
    compact = re.sub(r"\s+", "", text)
    for key in ("代號字碼", "醫療院所名稱", "測試醫療院所", "01015C", "E5002C", "D2", "18"):
        assert key in compact, f"關鍵文本缺失：{key}"


@requires_soffice
def test_e2e_print_base_pagination_15_vs_16_rows(tmp_path):
    """Test 2（e2e）：15 行不分頁（3 頁）、16 行分頁（6 頁）——D-06 與壓縮模板相容。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import paginate
    from elc_audit_engine.generators.appeal_print.odt_fill import fill_template

    header = {
        "代號字碼": "01015C",
        "醫療院所名稱": "測試醫療院所",
        "審查科別": "內科",
        "原申報類別": "□送核",
        "原申報日期": "110年8月3日",
        "年度": "110",
        "月份": "06",
    }

    def _rows(n):
        return [
            {
                "案件分類": "D2",
                "流水號": str(i + 1),
                "身份證字號": f"F10291****{i}",
                "姓名": f"測試{i}",
                "傷病名稱": "J189",
                "醫令序": str(i + 1),
                "內容": f"E5002C{i}",
                "數量": "1",
                "金額": "300",
                "理由": "理由",
                "審核意見": "",
                "補付數量": "",
                "單價": "",
                "補付金額": "",
            }
            for i in range(n)
        ]

    import subprocess as _subprocess
    from pathlib import Path

    def _convert(filled_odt, outdir, pdf_name):
        profile_dir = outdir / "lo_profile"
        profile_dir.mkdir(exist_ok=True)
        r = _subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation={Path(profile_dir).as_uri()}",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(filled_odt),
            ],
            capture_output=True,
            timeout=120,
        )
        assert r.returncode == 0
        from pypdf import PdfReader

        return len(PdfReader(outdir / pdf_name).pages)

    filled15 = tmp_path / "filled15.odt"
    fill_template(PRINT_BASE_ODT, header, paginate(_rows(15)), str(filled15))
    assert _convert(filled15, tmp_path, "filled15.pdf") == 3

    filled16 = tmp_path / "filled16.odt"
    fill_template(PRINT_BASE_ODT, header, paginate(_rows(16)), str(filled16))
    assert _convert(filled16, tmp_path, "filled16.pdf") == 6


def test_security_write_appeal_print_rejects_traversal(tmp_path):
    """Test 3（security）：file_stem 含 `../` → UnsafeIdentifierError，外部目錄未被寫入。"""
    from elc_audit_engine.generators.appeal_print import write_appeal_print
    from elc_audit_engine.safe_paths import UnsafeIdentifierError

    output_dir = tmp_path / "out"
    for evil in ("../escape", "..", "a/b"):
        with pytest.raises(UnsafeIdentifierError):
            write_appeal_print(
                output_dir,
                evil,
                _payload(),
                _facility(),
                template_odt_path=PRINT_BASE_ODT,
                submission=_submission(),
            )
    # 非法輸入在 makedirs 之前即被拒絕：output_dir 未被建立
    assert not os.path.exists(output_dir)


def test_security_injection_does_not_break_odt(tmp_path):
    """Test 4（security）：欄位含 `<script>` 與 `&` → render 成功回傳 bytes；soffice 可用時轉檔成功。"""
    from elc_audit_engine.generators.appeal_print import (
        render_appeal_print,
        write_appeal_print,
    )

    payload = _payload(p8_reason1='<script>alert("x&y")</script>')
    submission = _submission(patient_name="張<三>&李四")

    # render 層：純函式組 bytes（不 raise、不寫專案目錄）
    data, warnings = render_appeal_print(
        payload,
        _facility(),
        template_odt_path=PRINT_BASE_ODT,
        submission=submission,
    )
    assert isinstance(data, bytes) and len(data) > 0
    # 產出 ODT 可被 zipfile+ET 解析（自動轉義，無 XML 損毀）
    content_raw, root_el = _read_content_xml_bytes(data)
    tables = _find_tables(root_el)
    assert len(tables) == 9

    # write 層：soffice 可用時轉檔成功（不 raise）
    if soffice_is_functional():
        pdf_path, _ = write_appeal_print(
            tmp_path / "out2",
            "inject_case",
            payload,
            _facility(),
            template_odt_path=PRINT_BASE_ODT,
            submission=submission,
        )
        assert os.path.isfile(pdf_path)


def _read_content_xml_bytes(odt_bytes: bytes):
    """從 bytes 讀 content.xml（security 測試用，迴避落盤）。"""
    import io as _io

    with zipfile.ZipFile(_io.BytesIO(odt_bytes)) as zf:
        content_raw = zf.read("content.xml").decode("utf-8")
    import re as _re

    root_open = _re.search(r"<office:document-content[^>]*>", content_raw).group(0)
    for m in _re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', root_open):
        ET.register_namespace(m.group(1) or "", m.group(2))
    root_el = ET.fromstring(content_raw)
    return content_raw, root_el


# ── Task 3 (11-02): -k copies（三聯版式差異）───────────────────────
#
# 11-01 使用者裁示（見 11-01-SUMMARY.md）：「中央健康保險署填列」的
# 核定|複核|初核|審查委員 空白欄在**第二聯**（健保署存查聯）說明表 row1，
# 第一/三聯無此欄；系統不填該欄（留空供健保署複核）。ROADMAP SC3 與
# REQUIREMENTS 驗收標準 3 已由 orchestrator 更新為「第二聯」（commit ba1f211）。


def _rendered_filled_bytes():
    """以壓縮基準模板跑 render_appeal_print，回傳 filled ODT bytes。"""
    from elc_audit_engine.generators.appeal_print import render_appeal_print

    data, _ = render_appeal_print(
        _payload(),
        _facility(),
        template_odt_path=PRINT_BASE_ODT,
        submission=_submission(primary_diagnosis="J189"),
    )
    return data


def _copies_note_row1_texts(root_el):
    """回傳 3 聯說明表 row1 的 cell 文本清單（以聯組內說明表定位，非寫死索引）。"""
    tables = _find_tables(root_el)
    assert len(tables) == 9
    out = []
    for copy_idx in range(3):
        note = tables[copy_idx * 3 + 2]  # 聯組內第 3 個＝說明表
        rows = note.findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"
        )
        row1 = rows[1]
        cells = row1.findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"
        )
        out.append([_cell_full_text(c) for c in cells])
    return out


def test_copies_second_copy_review_columns_only():
    """第二聯說明表 row1 含「核定|複核|初核|審查委員」；第一/三聯無（系統不填）。"""
    _, root_el = _read_content_xml_bytes(_rendered_filled_bytes())
    row1_texts = _copies_note_row1_texts(root_el)

    # 第二聯（健保署存查聯）：4 個標題 cell（11-01 使用者裁示以官方模板第二聯為準）
    assert row1_texts[1] == ["核定", "複核", "初核", "審查委員"]
    # 第一聯：無此 4 個標題 cell（文本為空）
    assert row1_texts[0] == ["", "", "", ""]
    # 第三聯：無此 4 個標題 cell（2 cells，文本為空）
    assert len(row1_texts[2]) == 2
    assert all(t == "" for t in row1_texts[2])


def test_copies_review_cells_unfilled():
    """核定/複核/初核/審查委員 欄位系統未填值（留空供健保署複核）。"""
    _, root_el = _read_content_xml_bytes(_rendered_filled_bytes())
    tables = _find_tables(root_el)
    note2 = tables[1 * 3 + 2]
    rows = note2.findall(
        "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"
    )
    # row1 標題下的填寫 cell（row2/row3）須為空——系統不產出健保署複核結果
    for ri in (2, 3):
        cells = rows[ri].findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"
        )
        for c in cells:
            assert _cell_full_text(c) == ""


def test_copies_total_row_and_diagnosis_cell():
    """各聯末頁合計列值＋資料列 cell[4] 傷病名稱（與 build_rows 鍵值一致）。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_rows

    # 先算 build_rows 的傷病名稱鍵值（單醫令 → 1 行）
    rows, _ = build_rows(_payload(), _facility(), submission=_submission())
    assert len(rows) == 1
    diagnosis_key = rows[0]["傷病名稱"]

    _, root_el = _read_content_xml_bytes(_rendered_filled_bytes())
    tables = _find_tables(root_el)
    for copy_idx in range(3):
        main = tables[copy_idx * 3 + 1]
        mrows = main.findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"
        )
        # 資料列 row2 cell[4]＝傷病名稱欄（14 鍵注入不逐欄錯位，SC1 防護）
        row2 = mrows[2].findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"
        )
        assert _cell_full_text(row2[4]) == diagnosis_key
        # 合計列 row17：cell[0]＝「合計」、數量欄 cell[2]＝該聯資料行數（人次）、
        # 金額/理由/審核意見/補付金額值 cell 為空（健保署填列欄留空）
        total = mrows[17].findall(
            "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-cell"
        )
        assert _cell_full_text(total[0]) == "合計"
        assert _cell_full_text(total[2]) == str(len(rows))  # 人次加總
        assert _cell_full_text(total[3]) == ""  # 金額
        assert _cell_full_text(total[4]) == ""  # 理由
        assert _cell_full_text(total[5]) == ""  # 審核意見
        assert _cell_full_text(total[7]) == ""  # 補付金額值


# ── Task 1 (11-03): -k config（facility.json＋load_facility_config，D-04）──


def test_config_load_facility_config_missing_file_raises(monkeypatch):
    """Test 1（config）：FACILITY_CONFIG_PATH 指向不存在的路徑 → FileNotFoundError（fail-fast）。"""
    from config import settings

    monkeypatch.setattr(
        settings, "FACILITY_CONFIG_PATH", "/nonexistent/path/facility.json"
    )
    with pytest.raises(FileNotFoundError):
        settings.load_facility_config()


def test_config_load_facility_config_missing_required_field_raises(tmp_path, monkeypatch):
    """Test 2（config）：facility.json 缺必填欄（code）→ ValueError（訊息含欄位名）。"""
    import json as _json

    from config import settings

    bad = tmp_path / "facility_missing_code.json"
    bad.write_text(_json.dumps({"name": "測試醫療院所"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(bad))
    with pytest.raises(ValueError, match="code"):
        settings.load_facility_config()


def test_config_load_facility_config_valid_returns_dict(tmp_path, monkeypatch):
    """Test 3（config）：合法 facility.json → 回傳 dict 且含全部鍵（含 code/name）。"""
    import json as _json

    from config import settings

    good = tmp_path / "facility.json"
    good.write_text(
        _json.dumps(
            {
                "code": "01015C",
                "name": "測試醫療院所",
                "address": "測試市測試區測試路1號",
                "physician_name": "測試醫師",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(good))
    cfg = settings.load_facility_config()
    assert cfg["code"] == "01015C"
    assert cfg["name"] == "測試醫療院所"
    for key in ("code", "name", "address", "physician_name"):
        assert key in cfg


def test_config_load_facility_config_invalid_json_raises(tmp_path, monkeypatch):
    """facility.json 內容非合法 JSON → ValueError（fail-fast，不靜默回傳空 dict）。"""
    from config import settings

    bad = tmp_path / "facility_bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(bad))
    with pytest.raises(ValueError):
        settings.load_facility_config()


# ── Task 2 (11-03): -k cli（scripts/build_appeal_print.py 入口）────────────


def test_cli_build_appeal_print_missing_args():
    """0 個或過多參數 → 印 usage 且 return 1。"""
    from scripts.build_appeal_print import main

    assert main([]) == 1
    assert main(["a", "b", "c", "d"]) == 1


def test_cli_build_appeal_print_nonexistent_file():
    """缺檔案路徑 → return 1。"""
    from scripts.build_appeal_print import main

    assert main(["nonexistent.json"]) == 1


def test_cli_build_appeal_print_invalid_json(tmp_path):
    """appeal JSON 內容非合法 JSON → return 1。"""
    from scripts.build_appeal_print import main

    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert main([str(bad)]) == 1


def test_cli_build_appeal_print_unsafe_stem_rejected(tmp_path, monkeypatch, capsys, facility_config):
    """case_seq 含 `../` → return 1 且輸出目錄未被寫入（safe_filename 校驗後拒絕，T-11-04）。"""
    import json as _json

    from config import settings
    from scripts.build_appeal_print import main

    appeal_file = tmp_path / "appeal_evil.json"
    appeal_file.write_text(
        _json.dumps(_payload(case_seq="../evil")), encoding="utf-8"
    )
    out_dir = tmp_path / "out"
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(out_dir))

    ret = main([str(appeal_file)])
    assert ret == 1
    assert "不安全的檔名" in capsys.readouterr().err
    assert not out_dir.exists()  # 外部目錄未被寫入


def test_cli_build_appeal_print_warnings_presented(tmp_path, monkeypatch, capsys, facility_config):
    """不帶 case payload → return 0 且 stdout 含「警告：」行（fake_write 隔離 soffice）。

    soffice 隔離：以 monkeypatch 替換模組內 write_appeal_print 為 fake_write
    （回傳 (tmp_path/fake.pdf, warnings)，不實際轉檔、不回寫 data/output），
    故本測試不標 @requires_soffice、不觸 soffice。
    """
    import json as _json

    from config import settings
    from scripts import build_appeal_print

    appeal_file = tmp_path / "appeal_18.json"
    appeal_file.write_text(_json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(tmp_path / "out"))

    fake_pdf = tmp_path / "fake.pdf"

    def fake_write(
        output_dir,
        file_stem,
        payload,
        facility,
        *,
        template_odt_path,
        submission=None,
        soffice_timeout=120,
    ):
        return str(fake_pdf), ["身份證字號", "姓名", "數量", "金額"]

    monkeypatch.setattr(build_appeal_print, "write_appeal_print", fake_write)

    ret = build_appeal_print.main([str(appeal_file)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "已成功輸出申復清單 PDF" in out
    # 缺欄 warnings 於成功訊息後逐條以「警告：」列印（不隱藏、不 raise）
    for w in ("身份證字號", "姓名", "數量", "金額"):
        assert f"警告：{w}" in out
    # fake 未實際轉檔：fake.pdf 不存在、未回寫 data/output
    assert not fake_pdf.exists()


def test_cli_build_appeal_print_two_args_output_path(tmp_path, monkeypatch, facility_config):
    """長度 2：第 2 個參數視為 output_pdf_path（後向兼容 build_appeal_xml 習慣）。"""
    import json as _json

    from scripts import build_appeal_print

    appeal_file = tmp_path / "appeal_18.json"
    appeal_file.write_text(_json.dumps(_payload()), encoding="utf-8")

    captured = {}

    def fake_write(
        output_dir,
        file_stem,
        payload,
        facility,
        *,
        template_odt_path,
        submission=None,
        soffice_timeout=120,
    ):
        captured["output_dir"] = output_dir
        captured["stem"] = file_stem
        captured["submission"] = submission
        return str(tmp_path / "fake.pdf"), []

    monkeypatch.setattr(build_appeal_print, "write_appeal_print", fake_write)

    out_pdf = str(tmp_path / "custom" / "out.pdf")
    ret = build_appeal_print.main([str(appeal_file), out_pdf])
    assert ret == 0
    # output_dir＝output_pdf 的 dirname；stem＝去「申復清單_」前綴與 .pdf 之基底
    assert captured["output_dir"] == str(tmp_path / "custom")
    assert captured["stem"] == "out"
    assert captured["submission"] is None


def test_cli_build_appeal_print_three_args_submission(tmp_path, monkeypatch, facility_config):
    """長度 3：第 2 個為 case_payload_json_path、第 3 個為 output_pdf_path；submission 透傳。"""
    import json as _json

    from scripts import build_appeal_print

    appeal_file = tmp_path / "appeal_18.json"
    appeal_file.write_text(_json.dumps(_payload()), encoding="utf-8")
    case_payload = _submission()
    case_file = tmp_path / "case_payload.json"
    case_file.write_text(
        _json.dumps(case_payload, ensure_ascii=False), encoding="utf-8"
    )

    captured = {}

    def fake_write(
        output_dir,
        file_stem,
        payload,
        facility,
        *,
        template_odt_path,
        submission=None,
        soffice_timeout=120,
    ):
        captured["submission"] = submission
        captured["stem"] = file_stem
        return str(tmp_path / "fake.pdf"), []

    monkeypatch.setattr(build_appeal_print, "write_appeal_print", fake_write)

    out_pdf = str(tmp_path / "out" / "appeal.pdf")
    ret = build_appeal_print.main([str(appeal_file), str(case_file), out_pdf])
    assert ret == 0
    assert captured["submission"] == case_payload
    assert captured["stem"] == "appeal"


@requires_soffice
def test_cli_build_appeal_print_success_soffice(tmp_path, monkeypatch, facility_config):
    """完整流程（appeal JSON＋case payload）→ return 0 且輸出 PDF 存在、pypdf 頁數=3。"""
    import json as _json

    from config import settings
    from scripts.build_appeal_print import main

    appeal_file = tmp_path / "appeal_18.json"
    appeal_file.write_text(_json.dumps(_payload()), encoding="utf-8")
    case_file = tmp_path / "case_payload.json"
    case_file.write_text(
        _json.dumps(_submission(), ensure_ascii=False), encoding="utf-8"
    )

    out_dir = tmp_path / "out"
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(out_dir))

    # 3 參數：appeal JSON、case payload JSON、輸出 PDF 路徑
    ret = main([str(appeal_file), str(case_file), str(out_dir / "appeal.pdf")])
    assert ret == 0

    pdf = out_dir / "申復清單_appeal.pdf"
    assert pdf.is_file()
    from pypdf import PdfReader

    assert len(PdfReader(pdf).pages) == 3
