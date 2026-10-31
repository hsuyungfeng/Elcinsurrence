"""第 2、3 階審查報告統一格式（Plan 18-02 骨架）。

比照 MONTHLY-202307 當月申報預審報告（`monthly_report_html.py`）的版面，讓第 2 階
（抽審事前預審）與第 3 階（核減事後申復）共用同一套區塊順序與視覺樣式。

骨架狀態：
- 型別、常數與公開函式簽章已定義；實作函式以 NotImplementedError 佔位。
- 對應測試：tests/test_unified_review_report.py（strict xfail，實作後須移除標記）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Stage = Literal[2, 3]

# 區塊呈現順序（比照 MONTHLY-202307）：KPI → 案件基本資訊 → 給付規定 → SOAP → 佐證庫清單。
SECTION_ORDER: tuple[str, ...] = ("kpi", "header", "rule", "soap", "vault")

STAGE_TITLES: dict[Stage, str] = {
    2: "第 2 階｜抽審事前預審",
    3: "第 3 階｜核減事後申復",
}


@dataclass(frozen=True)
class RuleBlock:
    """給付規定／條文依據的一段文字。

    is_payment_text=True 時直接展開（對應 payment_text）；否則以 <details> 折疊。
    """

    label: str
    text: str
    is_payment_text: bool = False


@dataclass(frozen=True)
class ReviewCaseView:
    """統一報告的單一案件檢視模型（與 HTML 渲染解耦，便於測試）。

    Attributes:
        case_id: 案件識別（流水號或抽樣案件 ID）。
        stage: 2 或 3，決定標題與 KPI 集合。
        header: 案件基本資訊（label → value），缺值的欄位不輸出。
        kpis: KPI 數值（label → count）。
        rules: 給付規定與條文依據區塊。
        soap: {"s","o","a","p"}；None 表示整段省略。
        soap_source: "case"（案件本身）／"template"（範本降級）／"none"。
        vault_key: 佐證庫鍵（身分證-YYMM）；None 表示無佐證庫。
        vault_files: 分類（images/audio/reports/records）→ 檔名清單。
    """

    case_id: str
    stage: Stage
    header: dict[str, str] = field(default_factory=dict)
    kpis: dict[str, int] = field(default_factory=dict)
    rules: tuple[RuleBlock, ...] = ()
    soap: dict[str, str] | None = None
    soap_source: str = "none"
    vault_key: str | None = None
    vault_files: dict[str, tuple[str, ...]] = field(default_factory=dict)


def build_review_case_view(
    stage: Stage,
    case_id: str,
    payload: dict,
    *,
    rules: tuple[RuleBlock, ...] = (),
    vault_listing: dict[str, list[dict]] | None = None,
    soap_template: dict | None = None,
) -> ReviewCaseView:
    """把案件 payload、規則文字、佐證庫清單組成統一檢視模型。

    SOAP 來源優先序：payload["soap"]（案件本身）→ soap_template["soap"]（範本降級）→ 無。

    TODO(Plan 18-02)：
    - header 欄位順序（比照 monthly_report_html._case_header）與缺值過濾。
    - stage 3 的 KPI 集合（申復理由數、可申復點數）與 stage 2 不同，待確認欄位來源。
    """
    raise NotImplementedError("Plan 18-02: build_review_case_view 尚未實作")


def render_unified_review_html(view: ReviewCaseView) -> str:
    """回傳自包含 HTML（已 html.escape、無外部資源），依 SECTION_ORDER 輸出。

    空區塊整段省略（與 sampling_preview 一致）。SOAP 區塊需提供一鍵複製；
    頁尾沿用 PHI 警語（含身分證字號、姓名、出生日期）。

    TODO(Plan 18-02)：沿用 monthly_report_html._CSS 的設計 token；
    第 2 階預審卡片（preview-html）與第 3 階申復草稿共用本函式輸出。
    """
    raise NotImplementedError("Plan 18-02: render_unified_review_html 尚未實作")


__all__ = [
    "SECTION_ORDER",
    "STAGE_TITLES",
    "ReviewCaseView",
    "RuleBlock",
    "Stage",
    "build_review_case_view",
    "render_unified_review_html",
]
