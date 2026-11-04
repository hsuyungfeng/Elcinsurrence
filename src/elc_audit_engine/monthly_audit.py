"""當月申報檔高風險醫令的規則庫比對與彙總報告（Phase 15-02）。

每案、每個高風險醫令的流程：
1. 高風險謂詞（`parsers.totfa`）：點數 p12 > 350；藥品行 p11 > 5；藥品行單價缺漏或 0。
2. 規則查詢：`rule_repository.get_rule`（唯讀、零 LLM）。
   - 查詢拋 `RuleRepositoryError` → **待判定**（系統故障，不是判定結果，
     絕不降級為「查無規則」或「無限制」）。
   - 代碼不在規則庫 → **查無規則**。
3. 給付限制證據：自 `payment_text` 與 `article_full_text` 取出含限制用語的
   句子。**句子為原文逐字子字串，不改寫、不生成**；依關鍵字標示
   適應症／診斷／頻次（關鍵字啟發式，僅供人工快速定位）。
4. 診斷比對：規則原文中的 ICD 代碼 vs. 案件 d19～d23，只做前綴比對，
   結果為事實標籤（相符／未列於條文／條文未列 ICD），不做醫療必要性結論。
5. 生效期間：以就醫日（d9，民國七碼）對 effective_from／effective_to 判斷。

本模組**不產生「支持／裸奔」結論**；最終判定留給審查人員。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation

from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.parsers.totfa import (
    DRUG_UNIT_PRICE_THRESHOLD,
    declared_amount,
    is_drug_over_price,
    is_drug_unpriced,
    is_points_over,
)
from elc_audit_engine.rule_repository import get_rule, is_effective_on
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult

ARTIFACT_NAME = "monthly_risk_audit"

# 限制用語（句子含任一者即視為「有限制文字」）。啟發式，僅用於定位證據。
RESTRICTION_MARKERS = ("限", "不得", "須", "需", "僅", "不予支付", "檢附")

# 證據句的關鍵字家族（僅用於標示，非判定）。
_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "indication": re.compile(r"適應症|適用|限|僅|須經|需經|符合"),
    "diagnosis": re.compile(r"診斷|ICD|病名"),
    "frequency": re.compile(r"\d+\s*次|每[日週月年]|間隔|療程|一次"),
    "test": re.compile(r"檢查|檢驗|報告|影像|X光|MRI|超音波|血液|實驗室|病理|數值|檢測"),
    "documentation": re.compile(r"檢附|附上|病歷|紀錄|記錄|證明|附件"),
}

# ICD-10 形狀：字母＋兩位數字，接 .xxxx 或 3–4 位英數（如 B27、Z94.2、S90221A）。
# 不接受 A1C、B12 之類無 ICD 語境的字串——擷取前另要求句中有 ICD／診斷／病名字樣。
_ICD_RE = re.compile(r"(?<![A-Za-z0-9])([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4}|[0-9A-Z]{3,4})?)(?![A-Za-z0-9])")
_ICD_CONTEXT_RE = re.compile(r"ICD|診斷|病名")
_SENTENCE_SPLIT_RE = re.compile(r"[。；;\n]")

# 規則文字的占位值（SQLite 中以字串 'null' 或空白出現）。
# 無實質內容的占位文字（比對前轉小寫）。命中者視同「無給付規定原文」→ STATUS_NO_TEXT，
# 不納入預審報告。例：AC43152151 的 payment_text 為「目前無」，並無任何限制條文。
_EMPTY_TEXT_SENTINELS = frozenset({
    "", "null", "none", "目前無", "無資訊", "無", "無給付規定", "未找到給付規定",
})

# 規則狀態（`OrderFinding.rule_status`）。
STATUS_UNDETERMINED = "undetermined"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_TEXT = "no_text"
STATUS_NO_MARKERS = "no_restriction_markers"
STATUS_RESTRICTION = "restriction_present"

RULE_STATUS_LABELS: dict[str, str] = {
    STATUS_UNDETERMINED: "待判定（規則庫查詢失敗，系統故障，非判定結果）",
    STATUS_NOT_FOUND: "查無規則（代碼不在規則庫）",
    STATUS_NO_TEXT: "規則無給付文字（無法判定）",
    STATUS_NO_MARKERS: "規則文字未見限制用語（需人工確認，不視為無限制）",
    STATUS_RESTRICTION: "有給付限制條文（需人工比對）",
}

LookupFn = Callable[[str], RuleResult]


# ── 資料型別 ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Evidence:
    """規則原文中一句含限制用語的句子（逐字擷取）。

    Attributes:
        source: 來源欄位，`"payment_text"` 或 `"article_full_text"`。
        sentence: 原文逐字子字串（測試保證 `sentence in 來源原文`）。
        kinds: 關鍵字家族標示，元素為 indication／diagnosis／frequency。
    """

    source: str
    sentence: str
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class OrderFinding:
    """單一高風險醫令的比對結果（僅列出有旗標的醫令）。"""

    order_seq: str | None
    code: str
    category: str | None
    points: str | None
    unit_price: str | None
    flags: tuple[str, ...]
    rule_status: str
    rule_name: str | None = None
    icd_in_rule: tuple[str, ...] = ()
    diagnosis_check: str = "not_applicable"
    period_check: str = "not_applicable"
    effective_from: str | None = None
    effective_to: str | None = None
    evidence: tuple[Evidence, ...] = ()
    error: str | None = None
    # 規則原文全文（來源欄位, 原文），供推理樹與 SOAP 補強做逐字驗證；**不寫入 to_dict**，
    # 避免把整段規則文字灌進案件產物。
    source_texts: tuple[tuple[str, str], ...] = ()
    total_qty: str | None = None  # p10 總量（顯示用）
    # 判定用單價來源：totfa（p11）或 official（藥品官方支付價，p11 缺漏時採用）。
    price_source: str = "totfa"
    official_unit_price: str | None = None  # 藥品官方支付價（顯示用）
    # 完整給付規定條文（payment_text 優先，否則 article_full_text）；只在 to_dict(include_rule_text=True) 輸出。
    rule_full_text: str | None = None

    @property
    def label(self) -> str:
        return RULE_STATUS_LABELS[self.rule_status]


@dataclass(frozen=True)
class CaseAudit:
    """單一案件的比對結果（以 case_id 為唯一鍵；case_seq 僅為顯示欄位）。"""

    case_id: str
    batch: str
    case_seq: str | None
    department: str | None
    doctor_code: str | None
    visit_date: str | None
    primary_diagnosis: str | None
    secondary_diagnoses: tuple[str, ...]
    findings: tuple[OrderFinding, ...] = field(default_factory=tuple)
    # d3 為身分證字號（如 M220518024，英文字母＋9 位數字的國民身分證格式）。欄位名沿用 patient_id。
    patient_id: str | None = None
    patient_name: str | None = None  # d49 姓名
    birth_date: str | None = None  # d11 出生年月日（民國七碼，原樣）
    total_points: str | None = None  # d39 醫療費用總點數（報告門檻：> 1000）

    def to_dict(self, *, include_rule_text: bool = False) -> dict:
        """案件序列化。預設不含規則全文（避免案件產物膨脹）；報告端點傳 include_rule_text=True。"""
        return {
            "case_id": self.case_id,
            "batch": self.batch,
            "case_seq": self.case_seq,
            "patient_id": self.patient_id,
            "patient_name": self.patient_name,
            "birth_date": self.birth_date,
            "total_points": self.total_points,
            "department": self.department,
            "doctor_code": self.doctor_code,
            "visit_date": self.visit_date,
            "primary_diagnosis": self.primary_diagnosis,
            "secondary_diagnoses": list(self.secondary_diagnoses),
            "findings": [_finding_to_dict(f, include_rule_text) for f in self.findings],
        }


@dataclass(frozen=True)
class BatchAudit:
    """批次彙總：總計、依科別／醫師／case_seq 彙總，以及有旗標案件的明細。"""

    batch: str
    cases_total: int
    cases: tuple[CaseAudit, ...]
    report: dict

    def to_dict(self, *, include_rule_text: bool = False) -> dict:
        return {
            "batch": self.batch,
            "report": self.report,
            "cases": [c.to_dict(include_rule_text=include_rule_text) for c in self.cases],
        }


def _finding_to_dict(f: OrderFinding, include_rule_text: bool = False) -> dict:
    data = {
        "order_seq": f.order_seq,
        "code": f.code,
        "category": f.category,
        "points": f.points,
        "unit_price": f.unit_price,
        "total_qty": f.total_qty,
        "price_source": f.price_source,
        "official_unit_price": f.official_unit_price,
        "flags": list(f.flags),
        "rule_status": f.rule_status,
        "rule_status_label": f.label,
        "rule_name": f.rule_name,
        "icd_in_rule": list(f.icd_in_rule),
        "diagnosis_check": f.diagnosis_check,
        "period_check": f.period_check,
        "effective_from": f.effective_from,
        "effective_to": f.effective_to,
        "evidence": [
            {"source": e.source, "sentence": e.sentence, "kinds": list(e.kinds)}
            for e in f.evidence
        ],
        "error": f.error,
    }
    if include_rule_text:
        data["rule_full_text"] = f.rule_full_text
    return data


# ── 純函式工具 ────────────────────────────────────────────────────


def extract_icd_codes(text: str) -> tuple[str, ...]:
    """自規則原文擷取 ICD 代碼（僅限含 ICD／診斷／病名字樣的句子；保留原寫法、去重、保序）。"""
    seen: dict[str, None] = {}
    for sentence in split_sentences(text):
        if not _ICD_CONTEXT_RE.search(sentence):
            continue
        for match in _ICD_RE.finditer(sentence):
            seen.setdefault(match.group(1), None)
    return tuple(seen)


def split_sentences(text: str) -> tuple[str, ...]:
    """依句號／分號／換行切句，每句 strip；每句皆為原文的逐字子字串。"""
    pieces = (p.strip() for p in _SENTENCE_SPLIT_RE.split(text))
    return tuple(p for p in pieces if p)


def _kinds_of(sentence: str) -> tuple[str, ...]:
    kinds = [name for name, pattern in _KIND_PATTERNS.items() if pattern.search(sentence)]
    if extract_icd_codes(sentence) and "diagnosis" not in kinds:
        kinds.append("diagnosis")
    return tuple(kinds)


def _is_restriction(sentence: str, kinds: tuple[str, ...]) -> bool:
    """句子是否構成給付限制證據：含限制用語，或明列頻次／診斷要求（頻次限制與診斷要求即限制本身）。"""
    if any(marker in sentence for marker in RESTRICTION_MARKERS):
        return True
    return "frequency" in kinds or "diagnosis" in kinds


def _normalize_icd(code: str) -> str:
    return code.replace(".", "").upper()


def diagnosis_matches(case_codes: tuple[str, ...], rule_codes: tuple[str, ...]) -> bool:
    """案件任一診斷碼是否落在條文列出的代碼之下（前綴比對，去掉小數點）。

    `Z942` 落在 `Z94` 之下 → 相符；`Z94` 不落在 `Z942` 之下 → 不相符。
    """
    for case_code in case_codes:
        normalized_case = _normalize_icd(case_code)
        for rule_code in rule_codes:
            if normalized_case.startswith(_normalize_icd(rule_code)):
                return True
    return False


from elc_audit_engine.services.date_utils import roc7_to_date  # noqa: E402,F401  (Phase 22-04 共用)


def order_flags(order: OrderRecord) -> tuple[str, ...]:
    flags: list[str] = []
    if is_points_over(order):
        flags.append("points_over_350")
    if is_drug_over_price(order):
        flags.append("drug_over_5")
    if is_drug_unpriced(order):
        flags.append("drug_unpriced")
    return tuple(flags)


def _order_from_raw(raw: Mapping[str, str | None]) -> OrderRecord:
    return OrderRecord(
        code=raw.get("p4"),
        category=raw.get("p3"),
        total_qty=raw.get("p10"),
        unit_price=raw.get("p11"),
        points=raw.get("p12"),
        seq=raw.get("p13"),
        raw=dict(raw),
    )


def _usable_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return None if text.lower() in _EMPTY_TEXT_SENTINELS else text


# ── 單一醫令判定 ──────────────────────────────────────────────────


def _resolve_flags_with_official_price(
    order: OrderRecord, flags: tuple[str, ...], rule: RuleResult
) -> tuple[tuple[str, ...] | None, str]:
    """藥品單價缺漏（p11 為 0 或缺）時，改以官方支付價判定。

    回傳 (旗標, 價格來源)；旗標為 None 表示官方支付價 ≤ 門檻，不列為高風險。
    官方價缺漏或非數字時維持原旗標（drug_unpriced），來源為 totfa。
    """
    if "drug_unpriced" not in flags or not rule.unit_price:
        return flags, "totfa"
    try:
        official = Decimal(rule.unit_price.strip())
    except InvalidOperation:
        return flags, "totfa"
    if not official.is_finite():
        return flags, "totfa"
    # 只替換單價相關旗標；點數旗標（points_over_350）照常保留。
    kept = tuple(flag for flag in flags if flag != "drug_unpriced")
    if official > DRUG_UNIT_PRICE_THRESHOLD:
        return kept + ("drug_over_5",), "official"
    return (kept or None), "official"


def evaluate_order(
    order: OrderRecord,
    *,
    case_diagnoses: tuple[str, ...],
    visit_date: date | None,
    lookup: LookupFn,
) -> OrderFinding | None:
    """對單一醫令做規則比對；未命中任何高風險旗標者回 None。"""
    flags = order_flags(order)
    if not flags:
        return None
    code = (order.code or "").strip()
    base = {
        "order_seq": order.seq,
        "code": code,
        "category": order.category,
        "points": order.points,
        "unit_price": order.unit_price,
        "total_qty": order.total_qty,
        "flags": flags,
    }

    try:
        rule = lookup(code)
    except RuleRepositoryError as exc:
        # 系統故障：待判定，不是判定結果。
        return OrderFinding(rule_status=STATUS_UNDETERMINED, error=str(exc), **base)

    if not rule.found:
        return OrderFinding(rule_status=STATUS_NOT_FOUND, **base)

    resolved_flags, price_source = _resolve_flags_with_official_price(order, flags, rule)
    if resolved_flags is None:
        return None  # 官方支付價未超過門檻：不列為高風險
    base = {**base, "flags": resolved_flags}

    sources = [
        ("payment_text", _usable_text(rule.payment_text)),
        ("article_full_text", _usable_text(rule.article_full_text)),
    ]
    usable = [(name, text) for name, text in sources if text]
    if not usable:
        return OrderFinding(
            rule_status=STATUS_NO_TEXT,
            rule_name=rule.name or None,
            price_source=price_source,
            official_unit_price=rule.unit_price,
            **base,
        )

    evidence: list[Evidence] = []
    rule_icd: dict[str, None] = {}
    for source, text in usable:
        for code_in_text in extract_icd_codes(text):
            rule_icd.setdefault(code_in_text, None)
        for sentence in split_sentences(text):
            kinds = _kinds_of(sentence)
            if _is_restriction(sentence, kinds):
                evidence.append(Evidence(source=source, sentence=sentence, kinds=kinds))

    icd_in_rule = tuple(rule_icd)
    if not icd_in_rule:
        diagnosis_check = "no_icd_in_rule_text"
    elif diagnosis_matches(case_diagnoses, icd_in_rule):
        diagnosis_check = "matched"
    else:
        diagnosis_check = "not_listed"

    if visit_date is None:
        period_check = "no_visit_date"
    else:
        in_period = is_effective_on(rule, visit_date)
        period_check = {True: "in_period", False: "out_of_period"}.get(in_period, "unknown")

    status = STATUS_RESTRICTION if evidence else STATUS_NO_MARKERS
    return OrderFinding(
        rule_status=status,
        rule_name=rule.name or None,
        icd_in_rule=icd_in_rule,
        diagnosis_check=diagnosis_check,
        period_check=period_check,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        evidence=tuple(evidence),
        source_texts=tuple(usable),
        rule_full_text=usable[0][1],
        price_source=price_source,
        official_unit_price=rule.unit_price,
        **base,
    )


def audit_case(
    case_id: str,
    payload: Mapping[str, object] | None,
    *,
    lookup: LookupFn,
) -> CaseAudit:
    """依 CaseStore 的 payload 比對單一案件（只列有旗標的醫令）。"""
    data = dict(payload or {})
    primary = data.get("primary_diagnosis")
    secondary = tuple(data.get("secondary_diagnoses") or ())
    case_codes = tuple(c for c in ((primary,) + secondary) if isinstance(c, str) and c)
    visit = roc7_to_date(data.get("visit_date") if isinstance(data.get("visit_date"), str) else None)

    findings: list[tuple[OrderRecord, OrderFinding]] = []
    for raw in data.get("orders") or []:
        order = _order_from_raw(raw)
        finding = evaluate_order(order, case_diagnoses=case_codes, visit_date=visit, lookup=lookup)
        if finding is not None:
            findings.append((order, finding))

    # 依申報金額由高到低排序（p12 點數，缺漏退回 p11 單價；皆缺者排最後）。穩定排序保留原醫令序。
    def _amount_key(pair: tuple[OrderRecord, OrderFinding]) -> tuple[int, Decimal]:
        amount = declared_amount(pair[0])
        return (0, -amount) if amount is not None else (1, Decimal(0))

    ordered = sorted(findings, key=_amount_key)

    return CaseAudit(
        case_id=case_id,
        batch=str(data.get("batch") or ""),
        case_seq=_str_or_none(data.get("case_seq")),
        patient_id=(
            _str_or_none(data.get("record_no"))
            or _str_or_none(data.get("id_card"))
            or _str_or_none(data.get("patient_id"))
            or _str_or_none(data.get("id_number"))
            or _str_or_none(data.get("d3"))
        ),
        patient_name=_str_or_none(data.get("patient_name")),
        birth_date=_str_or_none(data.get("birth_date")),
        total_points=_str_or_none(data.get("total_points")),
        department=_str_or_none(data.get("clinic")),
        doctor_code=_str_or_none(data.get("doctor_code")),
        visit_date=_str_or_none(data.get("visit_date")) or _str_or_none(data.get("d9")),
        primary_diagnosis=_str_or_none(primary),
        secondary_diagnoses=secondary,
        findings=tuple(finding for _order, finding in ordered),
    )


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# ── 批次彙總 ──────────────────────────────────────────────────────


def _empty_bucket() -> dict:
    return {"cases_flagged": 0, "findings": 0, "rule_status": Counter()}


def _bucket_to_dict(bucket: dict) -> dict:
    return {
        "cases_flagged": bucket["cases_flagged"],
        "findings": bucket["findings"],
        "rule_status": dict(bucket["rule_status"]),
    }


def aggregate_batch(cases_total: int, cases: tuple[CaseAudit, ...]) -> dict:
    """彙總為 totals／by_department／by_doctor／by_case_seq（case_seq 可重複，列出全部 case_id）。"""
    totals = {
        "cases_total": cases_total,
        "cases_flagged": 0,
        "findings": 0,
        "rule_status": Counter(),
        "flags": Counter(),
        "diagnosis_check": Counter(),
        "period_check": Counter(),
    }
    by_department: dict[str, dict] = {}
    by_doctor: dict[str, dict] = {}
    by_case_seq: dict[str, list[str]] = {}

    for case in cases:
        if not case.findings:
            continue
        totals["cases_flagged"] += 1
        totals["findings"] += len(case.findings)
        dept = case.department or "未記錄"
        doctor = case.doctor_code or "未記錄"
        by_department.setdefault(dept, _empty_bucket())
        by_doctor.setdefault(doctor, _empty_bucket())
        by_case_seq.setdefault(case.case_seq or "未記錄", []).append(case.case_id)
        for bucket in (by_department[dept], by_doctor[doctor]):
            bucket["cases_flagged"] += 1
            bucket["findings"] += len(case.findings)
        for finding in case.findings:
            totals["rule_status"][finding.rule_status] += 1
            totals["flags"].update(finding.flags)
            if finding.diagnosis_check != "not_applicable":
                totals["diagnosis_check"][finding.diagnosis_check] += 1
            if finding.period_check != "not_applicable":
                totals["period_check"][finding.period_check] += 1
            by_department[dept]["rule_status"][finding.rule_status] += 1
            by_doctor[doctor]["rule_status"][finding.rule_status] += 1

    return {
        "totals": {
            **{k: dict(v) if isinstance(v, Counter) else v for k, v in totals.items()},
        },
        "by_department": {k: _bucket_to_dict(v) for k, v in sorted(by_department.items())},
        "by_doctor": {k: _bucket_to_dict(v) for k, v in sorted(by_doctor.items())},
        "by_case_seq": {k: sorted(v) for k, v in sorted(by_case_seq.items())},
    }


# ── 報告檢視（納入規則） ─────────────────────────────────────────
# 審計結果（audit_batch）保留所有旗標醫令；報告（HTML／JSON／Email）只納入符合下列條件者。

CASE_TOTAL_POINTS_MIN = Decimal(1000)  # 醫療費用總點數（d39）須大於此值
# 「有給付規定」：規則有官方文字（有限制用語，或有文字但無限制用語）。無文字／查無規則不納入。
REPORT_RULE_STATUSES = frozenset({STATUS_RESTRICTION, STATUS_NO_MARKERS})

# 排除診療費（001開頭）與病理檢查（25001C～25004C）
EXCLUDED_ORDER_CODES = frozenset({"25001C", "25002C", "25003C", "25004C"})


def is_excluded_order_code(code: str | None) -> bool:
    """判斷醫令是否為排除之診療費（001開頭）或病理切片檢查（25001C-25004C）。"""
    c = (code or "").strip().upper()
    return c.startswith("001") or c in EXCLUDED_ORDER_CODES


def _total_points_over_min(case: CaseAudit) -> bool:
    if not case.total_points:
        return False
    try:
        total = Decimal(case.total_points.strip())
    except InvalidOperation:
        return False
    return total.is_finite() and total > CASE_TOTAL_POINTS_MIN


def report_view(batch: BatchAudit) -> BatchAudit:
    """套用報告納入規則並重算彙總。

    - 案件醫療總點數（d39）須 > 1000，缺漏或非數字者不納入。
    - 排除診療費（001開頭）與病理檢查（25001C～25004C）。
    - 案件內只保留「有給付規定」的旗標醫令（查無規則、無文字、待判定皆排除）。
    - 沒有任何符合醫令的案件不納入。
    """
    included: list[CaseAudit] = []
    for case in batch.cases:
        if not _total_points_over_min(case):
            continue
        findings = tuple(
            f for f in case.findings
            if f.rule_status in REPORT_RULE_STATUSES and not is_excluded_order_code(f.code)
        )
        if findings:
            included.append(replace(case, findings=findings))
    kept = tuple(included)
    return BatchAudit(
        batch=batch.batch,
        cases_total=batch.cases_total,
        cases=kept,
        report=aggregate_batch(batch.cases_total, kept),
    )


def audit_batch(
    store: CaseStore,
    batch: str,
    *,
    rules_db_path: str | None = None,
    lookup: LookupFn | None = None,
    persist: bool = False,
    page_size: int = 500,
) -> BatchAudit:
    """比對整個批次。同一批次內同一代碼只查一次規則庫（快取）。

    Args:
        store: 案件存放區（kind='monthly' 的批次案件）。
        batch: 批次名，如 `MONTHLY-202307`。
        rules_db_path: `rules.sqlite3` 路徑；None 則用預設規則庫。
        lookup: 注入查詢函式（測試用）；提供時忽略 rules_db_path。
        persist: True 時把每案結果寫入 `case_artifacts`（name=monthly_risk_audit）。

    Raises:
        RuleRepositoryError: 此處不會拋出（系統故障已逐醫令轉為「待判定」）。
    """
    if lookup is None:
        def lookup(code: str) -> RuleResult:
            return get_rule(code, db_path=rules_db_path)

    cache: dict[str, RuleResult | RuleRepositoryError] = {}

    def cached_lookup(code: str) -> RuleResult:
        key = (code or "").strip().upper()
        if key not in cache:
            try:
                cache[key] = lookup(key)
            except RuleRepositoryError as exc:
                cache[key] = exc
        outcome = cache[key]
        if isinstance(outcome, RuleRepositoryError):
            raise outcome
        return outcome

    cases_total = store.count_by_batch(batch)
    audits: list[CaseAudit] = []
    offset = 0
    while True:
        records = store.list_by_batch(batch, limit=page_size, offset=offset)
        if not records:
            break
        for record in records:
            audit = audit_case(record.case_id, record.payload, lookup=cached_lookup)
            if persist:
                store.set_artifact(record.case_id, ARTIFACT_NAME, audit.to_dict())
            audits.append(audit)
        offset += len(records)

    flagged = tuple(c for c in audits if c.findings)
    return BatchAudit(
        batch=batch,
        cases_total=cases_total,
        cases=flagged,
        report=aggregate_batch(cases_total, flagged),
    )
