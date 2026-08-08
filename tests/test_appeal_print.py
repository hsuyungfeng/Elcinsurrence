"""Phase 11 紙本申復清單列印測試（Wave 0 脚手架）。

Test matrix（RESEARCH Validation Architecture）：
- `-k mapping`：欄位組裝純函式（官方欄 ← 資料來源對應、缺欄誠實降級、分頁）
- `-k odt`：content.xml 注入（ET 解析產出 XML 斷言院所/案件/醫令/分頁/頁數欄/合計僅末頁）
- `-k e2e`／`-k copies`／`-k security`／`-k config`：由 11-02/11-03 依序添加
"""

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
