"""ingest/table_ocr 測試：PP-StructureV3 表格 HTML → 記錄（不跑真實引擎）。

- parse_sampling_tables：表頭對映、欄位填入、重複表頭/代碼、缺必填拒絕、無表頭退路
- parse_image_tables／parse_pdf_tables：引擎不可用／無表格 → None（降級訊號）
"""

from __future__ import annotations

import pytest

from elc_audit_engine.ingest.table_ocr import (
    parse_image_tables,
    parse_pdf_tables,
    parse_sampling_tables,
)

_TABLE_HTML = (
    "<html><body><table>"
    "<tr><td>醫令代碼</td><td>醫令名稱</td><td>就醫日期</td></tr>"
    "<tr><td>14050B</td><td>糖化血色素檢驗 HbA1c</td><td>20260710</td></tr>"
    "<tr><td>33084B</td><td>胸部X光攝影</td><td>20260712</td></tr>"
    "</tbody></table></body></html>"
)


def test_parse_sampling_tables_maps_columns():
    result = parse_sampling_tables([_TABLE_HTML])
    assert len(result.records) == 2
    assert result.source == "paddle"
    r0 = result.records[0]
    assert r0.order_code == "14050B"
    assert r0.order_name == "糖化血色素檢驗 HbA1c"
    assert r0.visit_date == "2026-07-10"  # 8 碼 → ISO
    assert r0.source == "paddle"


def test_parse_sampling_tables_duplicate_header_skipped():
    """跨頁重複表頭：第二個表格帶相同表頭列，不得產生空記錄。"""
    second = _TABLE_HTML.replace("14050B", "64140C").replace("33084B", "05307C")
    result = parse_sampling_tables([_TABLE_HTML, second])
    codes = [r.order_code for r in result.records]
    assert codes == ["14050B", "33084B", "64140C", "05307C"]
    assert len(result.records) == 4
    assert len(result.rejected) == 0


def test_parse_sampling_tables_duplicate_code_rejected():
    result = parse_sampling_tables([_TABLE_HTML, _TABLE_HTML])
    assert len(result.records) == 2
    assert len(result.rejected) == 2
    assert "重複" in result.rejected[0].reason


def test_parse_sampling_tables_missing_code_rejected():
    html = (
        "<table>"
        "<tr><td>醫令代碼</td><td>醫令名稱</td></tr>"
        "<tr><td>14050B</td><td>正常</td></tr>"
        "<tr><td></td><td>缺代碼</td></tr>"
        "</table>"
    )
    result = parse_sampling_tables([html])
    assert len(result.records) == 1
    assert len(result.rejected) == 1
    assert "醫令代碼" in result.rejected[0].reason


def test_parse_sampling_tables_no_header_falls_back_first_col():
    """無表頭對映（表頭不在契約別名內）時，退路假設第一欄為醫令代碼。"""
    html = (
        "<table>"
        "<tr><td>項目</td><td>說明</td></tr>"
        "<tr><td>14050B</td><td>糖化血色素</td></tr>"
        "</table>"
    )
    result = parse_sampling_tables([html])
    assert len(result.records) == 1
    assert result.records[0].order_code == "14050B"
    assert result.records[0].order_name == "糖化血色素"  # 第二欄名稱
    assert result.records[0].patient_name is None


def test_parse_sampling_tables_empty():
    result = parse_sampling_tables([])
    assert len(result.records) == 0
    assert len(result.rejected) == 0


class _FakeBlock:
    """LayoutBlock 替身：僅有 label/content 屬性。"""

    def __init__(self, label, content):
        self.label = label
        self.content = content


def test_parse_image_tables_engine_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr("elc_audit_engine.ingest.table_ocr._get_engine", lambda: None)
    assert parse_image_tables("/tmp/whatever.png") is None


def test_parse_image_tables_no_table_element_returns_none(monkeypatch):
    class _FakeEngine:
        def predict(self, input):
            return [{"parsing_res_list": [_FakeBlock("text", "純文字")]}]

    monkeypatch.setattr("elc_audit_engine.ingest.table_ocr._get_engine", lambda: _FakeEngine())
    assert parse_image_tables("/tmp/whatever.png") is None


def test_parse_image_tables_with_table(monkeypatch):
    class _FakeEngine:
        def predict(self, input):
            return [{"parsing_res_list": [_FakeBlock("table", _TABLE_HTML)]}]

    monkeypatch.setattr("elc_audit_engine.ingest.table_ocr._get_engine", lambda: _FakeEngine())
    result = parse_image_tables("/tmp/whatever.png")
    assert result is not None
    assert len(result.records) == 2


def test_parse_pdf_tables_engine_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr("elc_audit_engine.ingest.table_ocr._get_engine", lambda: None)
    assert parse_pdf_tables("/tmp/whatever.pdf") is None


def test_parse_pdf_tables_render_failure_returns_none(monkeypatch):
    monkeypatch.setattr("elc_audit_engine.ingest.table_ocr._get_engine", lambda: object())
    from elc_audit_engine.ingest.media import MediaExtractError

    def fake_render(path, out_dir, dpi=200):
        raise MediaExtractError("render 失敗")

    # parse_pdf_tables 在函數內 from media import render_pdf_pages，
    # 故須替身 media 模組的符號（from-import 引用者命名空間教訓）。
    monkeypatch.setattr("elc_audit_engine.ingest.media.render_pdf_pages", fake_render)
    assert parse_pdf_tables("/tmp/whatever.pdf") is None
