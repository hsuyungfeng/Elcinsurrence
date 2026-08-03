"""Phase 3 解析器的結構化結果型別（frozen dataclass，沿用 RuleResult 慣例）。

三個解析器（申報 XML／核減明細／SOAP）各自把輸入轉成下方的資料型別，
供 Phase 4/5/7 消費。所有型別皆為純資料容器：不查規則庫、不做支持度
判定、不呼叫 LLM（03-CONTEXT.md domain）。
"""

from dataclasses import dataclass, field
from typing import Literal

# 樣本註記列舉（D-16：0-統扣 / 1-立意 / 2-歸戶 / 3-隨機 / 4-全審）。
# 註：03-CONTEXT.md D-16 原稱 d3 為樣本註記，但真實檔 TOTFA.xml 的
# d3 為病歷號（如 M220518024）；依「規格與真實檔衝突時以真實檔為準」
# 的原則，申報 XML 的 d3 以病歷號建模。此列舉保留給未來的抽樣樣本檔
# （CSV，D-14c）reader 使用。
SAMPLE_MARK_LABELS: dict[str, str] = {
    "0": "統扣",
    "1": "立意",
    "2": "歸戶",
    "3": "隨機",
    "4": "全審",
}


@dataclass(frozen=True)
class OrderRecord:
    """申報 XML 中單筆 pdata 醫令。

    欄位語意依 C11（電子抽審.md）與 TOTFA.xml 實測。C11 記載的欄位以
    具名屬性提供（原樣字串），未記載欄位（如 p8/p16/p24）保留於 raw。
    C11 未記載 p6，真實檔亦未出現，故不建模。

    Attributes:
        days: p1 藥品給藥日份。
        dispense: p2 醫令調劑方式。
        category: p3 醫令類別。
        code: p4 藥品(項目)代號 — Phase 5 查規則庫的鍵。
        dose: p5 藥品用量。
        frequency: p7 藥品使用頻率。
        route: p9 給藥途徑／作用部位。
        total_qty: p10 總量。
        unit_price: p11 單價。
        points: p12 點數。
        seq: p13 醫令序（與核減明細欄 10「醫令序號」對應）。
        start_time: p14 執行時間-起。
        end_time: p15 執行時間-迄。
        chronic_mark: p17 慢性病連續處方箋／同一療程及排程檢查案件註記。
        raw: 全部 pdata 欄位（含 C11 未記載者，D-02 不丟棄）。
    """

    days: str | None = None
    dispense: str | None = None
    category: str | None = None
    code: str | None = None
    dose: str | None = None
    frequency: str | None = None
    route: str | None = None
    total_qty: str | None = None
    unit_price: str | None = None
    points: str | None = None
    seq: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    chronic_mark: str | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmissionCase:
    """申報 XML 中單一 ddata 案件（dhead + dbody + pdata）。

    具名屬性只涵蓋 C11 記載且對下游有意義的欄位；其餘（含 C11 未記載
    欄位如 d4/d5/d6/d31/d32/d37/d38/d43/d44/d55/d57）一律保留於 raw
    （D-02：未知欄位全數保留，不丟棄）。

    Attributes:
        case_class: d1 案件分類（與核減明細欄 5 join）。
        case_seq: d2 流水編號（與核減明細欄 6 join）。
        record_no: d3 病歷號。真實檔為病歷號（如 M220518024）；
            03-CONTEXT.md D-16 曾以規格記載稱樣本註記，與真實檔衝突，
            依真實檔為準（見 SAMPLE_MARK_LABELS 註解）。
        clinic: d8 就醫科別。
        visit_date: d9 就醫日期（7 碼民國原樣，如 1120718）。
        treatment_end_date: d10 治療結束日期（出現率 18.6%，常缺）。
        birth_date: d11 出生年月日（7 碼民國原樣）。
        pay_category: d14 給付類別。
        copay_code: d15 部分負擔代號。
        refer_hosp: d17 轉診／處方調劑或特定檢查資源共享案件之服務機構代號。
        transferred_out: d18 病患是否轉出。
        primary_diagnosis: d19 主診斷代碼（ICD-10）。
        secondary_diagnoses: d20-d26 次診斷代碼清單（ICD-10，非空才列入）。
            出現率 73.3%→0.2%，Phase 5 醫療必要性判定的關鍵佐證（D-03）。
        patient_name: d49 姓名（去識別化後 fixture 中為測試姓名）。
        orders: 本案件全部 pdata 醫令（可能為空 tuple，代表無任何醫令）。
        raw: 全部 dhead+dbody 欄位（不含 pdata）。
        warnings: 本案件層級的警告清單（D-08 兩級：高出現率欄位缺席才警告）。
    """

    case_class: str | None = None
    case_seq: str | None = None
    record_no: str | None = None
    clinic: str | None = None
    visit_date: str | None = None
    treatment_end_date: str | None = None
    birth_date: str | None = None
    pay_category: str | None = None
    copay_code: str | None = None
    refer_hosp: str | None = None
    transferred_out: str | None = None
    primary_diagnosis: str | None = None
    secondary_diagnoses: tuple[str, ...] = ()
    patient_name: str | None = None
    orders: tuple[OrderRecord, ...] = ()
    raw: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RejectedCase:
    """被拒收的案件（D-05：缺 d1/d2、缺 d3、或整案無 pdata）。

    Attributes:
        case_class: 可取得的 d1（若存在），否則 None。
        case_seq: 可取得的 d2（若存在），否則 None。
        reason: 拒收原因（人類可讀中文）。
        raw: 可取得的原始欄位（dhead+dbody，不含 pdata）。
    """

    case_class: str | None = None
    case_seq: str | None = None
    reason: str = ""
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmissionParseResult:
    """整份申報 XML 的解析結果（D-07：單一物件，成功案＋拒收案＋警告）。

    Attributes:
        header: tdata 全部欄位（原樣字串，如 t2 服務機構代號）。
        cases: 成功解析的案件清單。
        rejected: 被拒收的案件清單（含原因）。
        warnings: 檔層級警告（例如編碼回退），案件層級警告在各案內。
    """

    header: dict[str, str] = field(default_factory=dict)
    cases: tuple[SubmissionCase, ...] = ()
    rejected: tuple[RejectedCase, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeductionRecord:
    """核減／申復明細資料檔的單列（D-14d 的 18 欄）。

    Attributes:
        non_reimbursed_amount: 欄 1 不予核銷金額（申復值域上界，D-15）。
            10 碼零填補定寬數字（0000000300＝300），已 int() 正規化。
        institution_code: 欄 2 醫事機構代碼。
        fee_year_month: 欄 3 費用年月（西元 YYYYMM 原樣，6 碼非日期）。
        submit_date: 欄 4 申請申報日期（ISO）。
        case_class: 欄 5 案件分類（對應申報 XML d1）。
        case_seq: 欄 6 流水號（無零填補，對應 d2）。
        visit_date: 欄 7 就醫日期（ISO）。
        birth_date: 欄 8 出生日期（ISO，未遮罩，PHI）。
        id_number: 欄 9 身分證號（健保署已遮罩後 4 碼，PHI）。
        order_seq: 欄 10 醫令序號（對應申報 XML p13；D-14d 指申復 XML p1）。
        order_code: 欄 11 醫令代碼（對應 p4／get_rule() 查詢鍵）。
        exec_start: 欄 12 執行時間起（ISO）。
        region: 欄 13 分區別。
        split_amount: 欄 14 拆帳金額（純數字，與欄 1 同值不同格式，已正規化）。
        pay_date: 欄 15 核付日期（ISO）。
        deduction_reason: 欄 16 追扣原因（自由中文，原樣保留 — Phase 5/7
            的主要輸入訊號，不得正規化）。
        appeal_item_code: 欄 17 院所申復事項之代碼（`A-說明` 拆出 A）。
        appeal_item_desc: 欄 17 院所申復事項之說明（拆出「檢驗結果確實於時效內上傳」）。
        institution_note: 欄 18 院所說明（自由中文）。
        raw: 原始 18 欄值（tuple，欄序即 D-14d 順序）。
    """

    non_reimbursed_amount: int | None = None
    institution_code: str | None = None
    fee_year_month: str | None = None
    submit_date: str | None = None
    case_class: str | None = None
    case_seq: str | None = None
    visit_date: str | None = None
    birth_date: str | None = None
    id_number: str | None = None
    order_seq: str | None = None
    order_code: str | None = None
    exec_start: str | None = None
    region: str | None = None
    split_amount: int | None = None
    pay_date: str | None = None
    deduction_reason: str | None = None
    appeal_item_code: str | None = None
    appeal_item_desc: str | None = None
    institution_note: str | None = None
    raw: tuple[str, ...] = ()


@dataclass(frozen=True)
class RejectedRow:
    """核減明細中欄數不符而被拒收的列。

    Attributes:
        row_number: 資料列號（1-based，不含表頭）。
        reason: 拒收原因。
        raw: 原始欄位值（原樣）。
    """

    row_number: int = 0
    reason: str = ""
    raw: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeductionParseResult:
    """整份核減明細檔的解析結果。

    Attributes:
        records: 成功解析的列。
        rejected: 被拒收的列（含原因）。
        header: 偵測到的表頭列（若有），否則空 tuple。
        encoding_used: 實際使用的編碼（自動偵測或注入）。
        delimiter_used: 實際使用的分隔符。
    """

    records: tuple[DeductionRecord, ...] = ()
    rejected: tuple[RejectedRow, ...] = ()
    header: tuple[str, ...] = ()
    encoding_used: str = ""
    delimiter_used: str = ","


SOAPCategory = Literal["S", "O", "A", "P", "UNKNOWN"]


@dataclass(frozen=True)
class SOAPSegment:
    """SOAP 分段結果中的單一段落（一句或一段）。

    Attributes:
        text: 段落文字（原樣）。
        category: S/O/A/P，或 UNKNOWN（關鍵詞無命中，D-12 修正：
            不預設 subjective）。
        method: 分段方式，`marker`（高信度）或 `keyword`（低信度）。
        score: keyword 路徑的最高分類分數；marker 路徑為 1.0。
    """

    text: str = ""
    category: SOAPCategory = "UNKNOWN"
    method: str = "keyword"
    score: float = 0.0


@dataclass(frozen=True)
class SOAPDocument:
    """SOAP 病歷文字的完整分段結果（D-10/D-11）。

    Attributes:
        sections: 依類別彙整的段落文字，鍵為 S/O/A/P（UNKNOWN 不列入）。
        segments: 全部段落（含 UNKNOWN），依原文順序。
        method: 整份使用的方法 — 偵測到標記為 `marker`，否則 `keyword`。
        confidence: 分段信度 — `high`（marker）或 `low`（keyword）。
            供 Phase 5 判斷分段可不可信（D-11）。
        unclassified: 未分類段落文字（marker 文件的首個標記前內容，
            或 keyword 路徑的 UNKNOWN 句）。
    """

    sections: dict[str, tuple[str, ...]] = field(default_factory=dict)
    segments: tuple[SOAPSegment, ...] = ()
    method: str = "keyword"
    confidence: str = "low"
    unclassified: tuple[str, ...] = ()
