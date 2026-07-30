"""規則庫對外查詢介面的結構化結果型別（D-07/D-08）。

RuleResult 是 rule_repository 模組對下游（Phase 3-5）曝露的單一查詢函式
`get_rule(code)` 的回傳型別。所有內部三層（SQLite/docx tree/rule_mapping）
的組合細節都封裝在查詢函式內部；下游只需要認識這個 dataclass 的欄位。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleResult:
    """單一醫令代碼查詢結果。

    Attributes:
        code: 醫令代碼（診療項目代碼或藥品代號）。
        source: 代碼來源，`"payment"`、`"drug"` 或 `"unknown"`（查無時）。
        name: 中文名稱（中文項目名稱／藥品中文名稱）。
        payment_text: SQLite 來源的支付規定／給付規定原始文字。
        effective_from: 生效起日，ISO `YYYY-MM-DD` 格式，若無則為 None。
        effective_to: 生效迄日，ISO `YYYY-MM-DD` 格式，若無則為 None。
        article_location: docx 樹狀索引中的條文位置路徑，
            例如 `"西醫基層-內科 > 壹、一般原則 > 三"`。
        article_full_text: 條文全文。
        article_source: 條文全文的來源，`"docx"`、`"csv"` 或 None。
            當 payment_text/給付規定欄位本身已包含具體審查原則全文時，
            可直接以該欄位文字作為 article_full_text，並標記
            article_source="csv"，不強制走 docx 樹查找（見 02-RESEARCH.md
            Open Question #3）。
        found: 是否找到對應的規則資料。
    """

    code: str
    source: str
    name: str
    payment_text: str | None
    effective_from: str | None
    effective_to: str | None
    article_location: str | None
    article_full_text: str | None
    article_source: str | None
    found: bool


def not_found(code: str) -> RuleResult:
    """建立查無規則時的 RuleResult。

    Args:
        code: 查詢時使用的醫令代碼（原樣保留於回傳結果中，方便呼叫端記錄）。

    Returns:
        found=False 的 RuleResult，所有選填欄位皆為 None，source="unknown"。
    """
    return RuleResult(
        code=code,
        source="unknown",
        name="",
        payment_text=None,
        effective_from=None,
        effective_to=None,
        article_location=None,
        article_full_text=None,
        article_source=None,
        found=False,
    )
