"""三方比對器的結構化結果型別（frozen dataclass，沿用 RuleResult 慣例）。

Phase 5 把「醫令↔規則↔病歷」三方比對成逐檢核項判定（C1）、醫令三級
分類（D7）、與候選補強敘述（D8/C2）。`CaseComparisonResult` 是 Phase 6
（病歷補強報告）的唯一輸入。
"""

from dataclasses import dataclass, field

# 判定結果（C1）：支持／部分支持／無記載／待人工（LLM 失敗降級，C5）。
VERDICT_SUPPORTED = "支持"
VERDICT_PARTIAL = "部分支持"
VERDICT_UNSUPPORTED = "無記載"
VERDICT_MANUAL = "待人工"
VERDICTS = (VERDICT_SUPPORTED, VERDICT_PARTIAL, VERDICT_UNSUPPORTED, VERDICT_MANUAL)

# 醫令支持度三級（D7）。
SUPPORT_SUFFICIENT = "充分"
SUPPORT_WEAK = "薄弱"
SUPPORT_NONE = "裸奔"


@dataclass(frozen=True)
class CheckItem:
    """單一檢核項（D-01：檢核項＝規則全文＋出處）。

    Attributes:
        rule_text: 規則要求全文（payment_text 或 article_full_text）。
        rule_source: 規則來源（csv/docx/unknown）。
        rule_location: 規則出處位置（article_location；無則 None）。
    """

    rule_text: str
    rule_source: str = "unknown"
    rule_location: str | None = None


@dataclass(frozen=True)
class Judgment:
    """單一檢核項的判定結果（C1：verdict＋引用原文）。

    Attributes:
        verdict: VERDICT_* 之一（支持/部分支持/無記載/待人工）。
        quote: 引用病歷原文句子（無記載時可為空）。
        reason: 一句話理由（供 Phase 6 報告呈現）。
    """

    verdict: str = VERDICT_UNSUPPORTED
    quote: str = ""
    reason: str = ""


@dataclass(frozen=True)
class OrderJudgment:
    """單筆醫令的三方比對結果。

    Attributes:
        order_code: 醫令代碼（p4）。
        order_seq: 醫令序（p13，無則 None）。
        rule_found: 規則庫是否找到該醫令（False=未知醫令）。
        rule_source: 規則來源（payment/drug/unknown）。
        check_item: 檢核項（規則全文＋出處）；未知醫令時 None。
        judgment: 檢核項判定結果；未知醫令時 None。
        support_level: 三級分類（充分/薄弱/裸奔）；未知醫令時 None。
        manual_review: 是否有「待人工」判定（C5 降級，不阻斷）。
        note: 補充說明（未知醫令→「查無規則依據，建議人工查核」）。
        narratives: 候選補強敘述清單（僅薄弱/裸奔生成，0~3 條）。
    """

    order_code: str = ""
    order_seq: str | None = None
    rule_found: bool = False
    rule_source: str = "unknown"
    check_item: CheckItem | None = None
    judgment: Judgment | None = None
    support_level: str | None = None
    manual_review: bool = False
    note: str = ""
    narratives: tuple["CandidateNarrative", ...] = ()


@dataclass(frozen=True)
class CandidateNarrative:
    """候選補強敘述（D8/C2）。

    Attributes:
        text: 敘述文字。
        rule_location: 規則出處（article_location；C2 第 3 條每條附出處）。
        prompt_only: True=提示型候選（「若實際有執行，請補充：…」），
            無線索時生成（C2 第 2 條）；False=基於既有線索擴寫。
    """

    text: str = ""
    rule_location: str | None = None
    prompt_only: bool = False


@dataclass(frozen=True)
class CaseComparisonResult:
    """單一案件的完整比對結果（Phase 6 的唯一輸入）。

    Attributes:
        case_record_no: 案件病歷號（SubmissionCase.record_no，d3）。
        order_judgments: 逐醫令比對結果。
        records_degraded: 病歷缺席（timeline=None，C5：報告標
            「⚠本報告未含病史佐證」）。
        unknown_orders: 未知醫令代碼清單（C5：查無規則依據）。
        manual_review_orders: 有「待人工」判定的醫令代碼清單。
    """

    case_record_no: str = ""
    order_judgments: tuple[OrderJudgment, ...] = ()
    records_degraded: bool = False
    unknown_orders: tuple[str, ...] = ()
    manual_review_orders: tuple[str, ...] = ()
