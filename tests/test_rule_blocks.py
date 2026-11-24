"""給付規定共用 helper（services/rule_blocks.py）單元測試。"""

from __future__ import annotations

from elc_audit_engine.services.rule_blocks import PAYMENT_TITLE, is_payment_text, payment_box_html


def test_is_payment_text_by_source_name():
    assert is_payment_text("payment_text")
    assert not is_payment_text("article_full_text")


def test_is_payment_text_by_flag_or_label():
    assert is_payment_text("給付規定", flagged=True)
    assert is_payment_text("給付規定（payment_text）")
    assert is_payment_text("payment_text", flagged=False)
    assert not is_payment_text("官方條文全文（外科 > (十三)）", flagged=False)


def test_payment_box_html_wraps_title_and_escapes_text():
    html = payment_box_html("限<b>糖尿病</b>患者使用")
    assert f'<div class="rule-payment-title">{PAYMENT_TITLE}</div>' in html
    assert '<div class="rule-payment-text">限&lt;b&gt;糖尿病&lt;/b&gt;患者使用</div>' in html
    assert html.startswith('<div class="rule-payment">') and html.endswith("</div>")
