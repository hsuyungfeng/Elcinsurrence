"""Phase 22-04 測試：服務層拆分、ROC 日期工具、報告 onclick 注入修正（P1-18）與佐證庫槽位保留。"""

from __future__ import annotations

from datetime import date

import pytest

from elc_audit_engine.services import report_assets
from elc_audit_engine.services.date_utils import (
    iso_to_roc,
    roc7_to_date,
    roc_date_text,
    roc_to_iso,
    roc_year_month,
)
from elc_audit_engine.services.report_renderer import ReviewCaseView, render_unified_review_html


# ---------------------------------------------------------------- ROC 日期工具（P2-2）


@pytest.mark.parametrize("roc, iso", [("1120718", "2023-07-18"), ("0990101", "2010-01-01")])
def test_roc_to_iso_round_trip(roc, iso):
    assert roc_to_iso(roc) == iso
    assert iso_to_roc(iso) == roc


@pytest.mark.parametrize("bad", ["", "1121301", "112071", "abcdefg", "1120230"])
def test_roc_to_iso_rejects_invalid(bad):
    with pytest.raises(ValueError):
        roc_to_iso(bad)


def test_iso_to_roc_rejects_invalid_calendar_date():
    with pytest.raises(ValueError):
        iso_to_roc("2023-02-30")


def test_roc7_to_date_returns_none_instead_of_raising():
    assert roc7_to_date("1120718") == date(2023, 7, 18)
    assert roc7_to_date("1121340") is None
    assert roc7_to_date(None) is None


def test_roc_year_month_and_date_text_match_printer_format():
    assert roc_year_month("202307") == "112年7月"
    assert roc_year_month("2023-07") == "2023-07"  # 非六碼原樣回傳
    assert roc_date_text("2023-07-18") == "112年7月18日"
    assert roc_date_text("20230718") == "112年7月18日"
    assert roc_date_text("not-a-date") == "not-a-date"


# ---------------------------------------------------------------- P1-18：onclick 注入修正


_INJECTION = "x');alert(document.cookie);//"


def test_soap_modal_button_removed_no_output():
    """範例病歷功能已取消：不再產生任何彈窗按鈕（即使輸入含注入字元）。"""
    assert report_assets.soap_modal_button(_INJECTION, _INJECTION, _INJECTION) == ""


def test_unified_report_modal_button_uses_data_attributes_not_onclick():
    view = ReviewCaseView(
        case_id="C-INJ",
        stage=2,
        soap={"s": "S", "o": "O", "a": "A", "p": "P"},
        soap_source="case",
        order_code=_INJECTION,
        primary_diagnosis=_INJECTION,
    )
    html = render_unified_review_html(view)
    assert "openSoapModal('" not in html
    assert "btn-soap-modal" not in html  # 範例病歷功能已取消，不再產生按鈕


def test_shared_script_has_no_example_modal_delegation():
    assert "btn-soap-modal" not in report_assets.SHARED_SCRIPT
    assert "openSoapModal" not in report_assets.SHARED_SCRIPT


# ---------------------------------------------------------------- 保留：佐證庫預留槽位與點擊檢視


def test_vault_placeholder_slots_and_lightbox_are_preserved():
    """1.2.3 階視覺化審核卡片：無檔案時顯示預留槽位；有影像縮圖時提供燈箱點擊檢視。"""
    empty = render_unified_review_html(
        ReviewCaseView(case_id="C-P", stage=2, vault_key="A123456789-2307", order_code="14050B")
    )
    assert "預留位置／未附加" in empty
    assert 'id="lb"' not in empty  # 無影像不輸出燈箱

    with_image = render_unified_review_html(
        ReviewCaseView(
            case_id="C-I",
            stage=2,
            vault_key="A123456789-2307",
            order_code="14050B",
            vault_files={"images": ("wound.png",)},
            thumbnails={"wound.png": "data:image/jpeg;base64,AAAA"},
        )
    )
    assert 'id="lb"' in with_image
    # 案件明細版面（月審風格）：影像以佐證庫檔案連結呈現，點擊於新視窗開啟
    assert "/api/vault/A123456789-2307/files/images/wound.png" in with_image


# ---------------------------------------------------------------- 向後相容與無循環匯入


def test_legacy_unified_module_path_still_exports_public_api():
    from elc_audit_engine import unified_review_report as legacy

    for name in ("SECTION_ORDER", "ReviewCaseView", "RuleBlock", "build_review_case_view",
                 "render_unified_review_html", "render_aggregated_review_html", "make_thumbnail_data_uri"):
        assert hasattr(legacy, name), name


def test_sampling_service_imports_without_circular_error():
    """回歸：服務層不得經由 api 套件匯入（否則與路由層形成循環匯入）。"""
    import importlib
    import subprocess
    import sys

    code = "import elc_audit_engine.services.sampling_service as s; assert s.SamplingServiceError"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    importlib.invalidate_caches()
