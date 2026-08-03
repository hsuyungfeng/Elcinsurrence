"""SOAP 分段器測試（03-01-PLAN Task 3）。

涵蓋：D-10 兩層策略（marker 優先、keyword 回退）、D-11 信度標記、
D-12 關鍵詞移植（數量/權重）＋「無命中→UNKNOWN」修正。
"""

import pytest

from elc_audit_engine.parsers.soap import parse_soap_text
from elc_audit_engine.parsers.soap_keywords import (
    KEYWORD_COUNT,
    SOAP_KEYWORDS,
    TOTAL_KEYWORDS,
)


# ---------------------------------------------------------------- 關鍵詞表

def test_keyword_table_ported_from_js():
    """D-12：四類關鍵詞皆移植（每類 > 50），總數 >= 240，權重與 JS 一致。"""
    assert TOTAL_KEYWORDS >= 240
    for cat, count in KEYWORD_COUNT.items():
        assert count > 50, f"{cat} 關鍵詞過少: {count}"
    assert SOAP_KEYWORDS["subjective"]["weight"] == 1.0
    assert SOAP_KEYWORDS["objective"]["weight"] == 0.95
    assert SOAP_KEYWORDS["assessment"]["weight"] == 1.0
    assert SOAP_KEYWORDS["plan"]["weight"] == 0.95


def test_representative_keywords_present():
    """代表性關鍵詞存在（血壓/感冒/抗生素/疼痛 分屬 O/A/P/S）。"""
    def has(cat, kw):
        return kw in SOAP_KEYWORDS[cat]["keywords"]

    assert has("objective", "血壓")
    assert has("assessment", "感冒")
    assert has("plan", "抗生素")
    assert has("subjective", "疼痛")


# ---------------------------------------------------------------- marker 路徑

@pytest.mark.parametrize(
    "text",
    [
        "S：頭痛三天\nO：體溫39度\nA：感冒\nP：多喝水",
        "S: 頭痛三天\nO: 體溫39度\nA: 感冒\nP: 多喝水",
        "S) 頭痛三天\nO) 體溫39度\nA) 感冒\nP) 多喝水",
        "【S】頭痛三天\n【O】體溫39度\n【A】感冒\n【P】多喝水",
        "主訴：頭痛三天\n客觀：體溫39度\n評估：感冒\n計劃：多喝水",
    ],
)
def test_marker_variants(text):
    """D-10：`S:`、`S)`、`S：`、`【S】`、`主訴：` 等變體皆可定位。"""
    doc = parse_soap_text(text)
    assert doc.method == "marker"
    assert doc.confidence == "high"
    assert doc.sections["S"] == ("頭痛三天",)
    assert doc.sections["O"] == ("體溫39度",)
    assert doc.sections["A"] == ("感冒",)
    assert doc.sections["P"] == ("多喝水",)


def test_marker_multiline_content():
    """標記段落內的多行內文合併為同一段。"""
    text = "S：頭痛三天\n持續疼痛\nO：體溫正常\n"
    doc = parse_soap_text(text)
    assert doc.sections["S"] == ("頭痛三天\n持續疼痛",)


def test_marker_prefix_unclassified():
    """首個標記前的內容歸 unclassified，不猜測段落。"""
    text = "病患自述不適\nS：頭痛\nO：體溫正常\n"
    doc = parse_soap_text(text)
    assert doc.method == "marker"
    assert doc.unclassified == ("病患自述不適",)
    assert "S" in doc.sections


# ---------------------------------------------------------------- keyword 路徑

def test_keyword_fallback_on_unmarked_text():
    """D-10：無標記文字（JS demo 範例）走關鍵詞：low 信度、四類皆有。"""
    text = (
        "患者主訴頭痛、發燒、喉嚨痛已3天。"
        "昨晚體溫39.5度，心跳90次/分，血壓140/90。"
        "白血球計數12000，胸部X光顯示肺部浸潤。"
        "初步診斷為社區取得性肺炎。"
        "開立抗生素，建議服用3天後回診複查。"
    )
    doc = parse_soap_text(text)
    assert doc.method == "keyword"
    assert doc.confidence == "low"
    assert set(doc.sections.keys()) == {"S", "O", "A", "P"}
    assert any("頭痛" in s for s in doc.sections["S"])
    assert any("血壓" in s for s in doc.sections["O"])
    assert any("診斷" in s for s in doc.sections["A"])
    assert any("抗生素" in s for s in doc.sections["P"])


def test_keyword_no_hit_is_unclassified_not_subjective():
    """D-12 修正：無關鍵詞命中的句子歸 UNKNOWN（原 JS 預設 subjective）。"""
    doc = parse_soap_text("今天天氣很好。")
    assert doc.segments[0].category == "UNKNOWN"
    assert doc.segments[0].method == "keyword"
    # 斷句時句號被剝離，UNKNOWN 段落文字不含「。」
    assert doc.unclassified == ("今天天氣很好",)
    assert doc.sections == {}


def test_keyword_weight_scoring():
    """關鍵詞計分：命中越多分越高，且 weight 影響結果。"""
    text = "患者主訴頭痛與咳嗽。"
    doc = parse_soap_text(text)
    assert doc.segments[0].category == "S"
    # 頭痛(1.0) + 咳嗽(1.0) + 痛(1.0) + 咳(1.0) = 4.0（JS 原表即含 咳）
    assert doc.segments[0].score == 4.0


def test_empty_text():
    """空文字 → 無段落、keyword 路徑。"""
    doc = parse_soap_text("")
    assert doc.segments == ()
    assert doc.sections == {}
    assert doc.method == "keyword"
