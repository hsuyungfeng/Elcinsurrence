"""核減／申復明細解析器測試（03-01-PLAN Task 2）。

涵蓋：D-14d 18 欄欄序、雙數字格式正規化、8 碼西元日期分支、欄 17 拆分、
欄 16 原樣保留、表頭自動偵測、reader 參數注入（編碼/分隔符）、
欄數不符拒收不中斷。
"""

import os

import pytest

from elc_audit_engine.parsers.deduction import (
    COLUMN_NAMES,
    DeductionFileError,
    parse_deduction_file,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "deduction_sample.csv")


def test_fixture_parses_two_records():
    """D-14d：官方範例 2 筆列全部解析成功，欄序正確。"""
    result = parse_deduction_file(FIXTURE)
    assert len(result.records) == 2
    assert result.rejected == ()
    assert len(result.header) == 18
    assert result.header == COLUMN_NAMES


def test_zero_padded_and_plain_numbers_normalized():
    """欄 1 零填補 10 碼與欄 14 純數字同值（300）皆正規化為 int。"""
    result = parse_deduction_file(FIXTURE)
    for rec in result.records:
        assert rec.non_reimbursed_amount == 300
        assert rec.split_amount == 300


def test_dates_parse_as_gregorian():
    """欄 4/7/8/12/15 全為西元 8 碼 → ISO 日期（非民國分支）。"""
    result = parse_deduction_file(FIXTURE)
    r1 = result.records[0]
    assert r1.submit_date == "2021-08-03"
    assert r1.visit_date == "2021-06-23"
    assert r1.birth_date == "1944-09-01"
    assert r1.exec_start == "2021-06-23"
    assert r1.pay_date == "2021-08-20"
    # 欄 3 費用年月為 6 碼 YYYYMM，原樣保留（非日期）
    assert r1.fee_year_month == "202106"


def test_appeal_item_split_on_dash():
    """欄 17 `A-檢驗結果確實於時效內上傳` → code=A / desc=說明。"""
    result = parse_deduction_file(FIXTURE)
    for rec in result.records:
        assert rec.appeal_item_code == "A"
        assert rec.appeal_item_desc == "檢驗結果確實於時效內上傳"


def test_appeal_item_without_dash_keeps_code():
    """欄 17 無 `-` 時 code=整串、desc=None。"""
    csv_text = (
        "0000000300,1234567890,202106,20210803,D2,18,20210623,19440901,"
        "F10291****,1,E5002C,20210623,1,300,20210820,原因,B,說明\n"
    )
    path = _write_tmp_csv(csv_text, "utf-8")
    result = parse_deduction_file(path, encoding="utf-8")
    assert result.records[0].appeal_item_code == "B"
    assert result.records[0].appeal_item_desc is None


def test_deduction_reason_preserved_verbatim():
    """欄 16 追扣原因自由中文原樣保留（不得正規化）。"""
    result = parse_deduction_file(FIXTURE)
    assert result.records[0].deduction_reason == "VPN資料複核不通過"
    assert result.records[1].deduction_reason == "查無檢驗日期相符之檢驗結果"


def test_join_keys_exposed():
    """欄 5/6/10/11 與申報 XML 的 join key 完整取出。"""
    result = parse_deduction_file(FIXTURE)
    r1 = result.records[0]
    assert r1.case_class == "D2"
    assert r1.case_seq == "18"
    assert r1.order_seq == "1"
    assert r1.order_code == "E5002C"


def test_headerless_file_parses():
    """無表頭列（純 18 欄資料）可解析。"""
    lines = open(FIXTURE, encoding="utf-8").read().strip().splitlines()
    csv_text = "\n".join(lines[1:]) + "\n"
    path = _write_tmp_csv(csv_text, "utf-8")
    result = parse_deduction_file(path, encoding="utf-8")
    assert len(result.records) == 2
    assert result.header == ()


def test_big5_encoded_file_autodetect():
    """Big5 編碼檔案（無指定 encoding）自動偵測解碼。"""
    csv_text = (
        "0000000300,1234567890,202106,20210803,D2,18,20210623,19440901,"
        "F10291****,1,E5002C,20210623,1,300,20210820,VPN資料複核不通過,"
        "A-檢驗結果確實於時效內上傳,檢附VPN佐證資料。\n"
    )
    path = _write_tmp_csv(csv_text, "big5")
    result = parse_deduction_file(path)
    assert result.encoding_used == "big5"
    assert result.records[0].deduction_reason == "VPN資料複核不通過"


def test_tab_delimited_injected():
    """分隔符可注入（Tab 分隔檔）。"""
    csv_text = (
        "0000000300\t1234567890\t202106\t20210803\tD2\t18\t20210623\t19440901\t"
        "F10291****\t1\tE5002C\t20210623\t1\t300\t20210820\t原因\t"
        "A-說明\t備註\n"
    )
    path = _write_tmp_csv(csv_text, "utf-8")
    result = parse_deduction_file(path, encoding="utf-8", delimiter="\t")
    assert len(result.records) == 1
    assert result.delimiter_used == "\t"
    assert result.records[0].order_code == "E5002C"


def test_wrong_column_count_row_rejected_but_continues():
    """欄數不符列進 rejected（含列號與原因），其餘列正常解析。"""
    good = (
        "0000000300,1234567890,202106,20210803,D2,18,20210623,19440901,"
        "F10291****,1,E5002C,20210623,1,300,20210820,原因,A-說明,備註\n"
    )
    bad = "1,2,3\n"
    path = _write_tmp_csv(good + bad + good, "utf-8")
    result = parse_deduction_file(path, encoding="utf-8")
    assert len(result.records) == 2
    assert len(result.rejected) == 1
    assert result.rejected[0].row_number == 2
    assert "欄數不符" in result.rejected[0].reason
    assert result.rejected[0].raw == ("1", "2", "3")


def test_missing_file_raises():
    """讀檔失敗拋 DeductionFileError。"""
    with pytest.raises(DeductionFileError):
        parse_deduction_file("/nonexistent/path/foo.csv")


def test_decode_failure_raises():
    """所有編碼皆失敗時拋 DeductionFileError。"""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(b"\xff\xfe\x00\x01\x02\xff\xff\xff")
    with pytest.raises(DeductionFileError):
        parse_deduction_file(path)


def _write_tmp_csv(text: str, encoding: str) -> str:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)
    return path
