"""當月申報高風險醫令的給付條件推理樹與 SOAP 補強清單（Phase 15-03）。

設計（借鏡 VectifyAI/PageIndex 的樹狀推理，但**不使用 LLM 做樹搜尋**）：

- 樹的節點全部來自 `OrderFinding.evidence`（規則原文逐字句）與結構化欄位
  （ICD 代碼、生效期間、比對標籤）。節點只「分類」原文，不生成新的醫療要求。
- 分類層次（Tree of Criteria）：
  適應症（Indications）→ 前置檢查與文件（Prerequisite tests / documents）
  → 診斷條件（Diagnosis）→ 用法頻次（Frequency）→ 其他限制（Other）；
  另附結構事實節點：規則狀態、觸發旗標、生效期間、診斷比對結果。
- SOAP 補強項目的文字為**固定模板**，唯一可變的是引述欄位（原文逐字句）與
  代碼（原文擷取的 ICD 字串）。每一項在輸出前都驗證為來源原文的子字串；
  驗證失敗的項目**丟棄並計數**（fail closed），不修補、不改寫。
- 病歷 SOAP 不在申報檔內，因此每一項的狀態固定為「待病歷比對」，本模組**不宣告
  任何病歷缺漏**。
"""

from __future__ import annotations

from dataclasses import dataclass

from elc_audit_engine.monthly_audit import (
    RULE_STATUS_LABELS,
    STATUS_NO_TEXT,
    STATUS_NOT_FOUND,
    STATUS_UNDETERMINED,
    CaseAudit,
    Evidence,
    OrderFinding,
)

VERIFY_PENDING = "待病歷比對"

# 證據句的分類優先序（一句只歸入一個類別）。
_PRIORITY = ("diagnosis", "frequency", "test", "documentation", "indication")

# 類別：key → (樹上標題, 對應 SOAP 區段)
CATEGORY_TITLES: dict[str, tuple[str, str]] = {
    "indication": ("1. 適應症（Indications）", "S/O"),
    "prerequisite": ("2. 前置檢查與文件（Prerequisite tests / documents）", "O / ATT"),
    "diagnosis": ("3. 診斷條件（Diagnosis requirement）", "A"),
    "frequency": ("4. 用法與頻次（Frequency / dosage）", "P"),
    "other": ("5. 其他限制（Other restrictions，需人工比對）", "—"),
}
CATEGORY_ORDER = ("indication", "prerequisite", "diagnosis", "frequency", "other")

_CHECK_LABELS = {
    "matched": "案件診斷落在條文代碼之下（前綴相符）",
    "not_listed": "案件診斷未列於條文代碼",
    "no_icd_in_rule_text": "條文未列出可擷取的 ICD 代碼",
    "not_applicable": "不適用",
}
_PERIOD_LABELS = {
    "in_period": "就醫日在生效期間內",
    "out_of_period": "就醫日不在規則庫所載生效期間（以目前唯一版本判定）",
    "unknown": "生效期間缺漏，無法判定",
    "no_visit_date": "就醫日缺漏或格式不符",
    "not_applicable": "不適用",
}


# ── 資料型別 ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReasoningNode:
    """推理樹節點。`quote`／`source` 只在條件節點上有值，且皆為原文逐字。"""

    node_id: str
    label: str
    kind: str  # root / category / criterion / fact
    quote: str | None = None
    source: str | None = None
    children: tuple[ReasoningNode, ...] = ()

    def to_dict(self) -> dict:
        data: dict = {"node_id": self.node_id, "label": self.label, "kind": self.kind}
        if self.quote is not None:
            data["quote"] = self.quote
            data["source"] = self.source
        if self.children:
            data["children"] = [child.to_dict() for child in self.children]
        return data


@dataclass(frozen=True)
class SoapItem:
    """單一 SOAP 補強項目。`quote` 與 `codes` 皆須為來源原文的子字串。"""

    section: str
    category: str
    prompt: str
    quote: str | None
    source: str | None
    codes: tuple[str, ...] = ()
    verify_status: str = VERIFY_PENDING

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "category": self.category,
            "prompt": self.prompt,
            "quote": self.quote,
            "source": self.source,
            "codes": list(self.codes),
            "verify_status": self.verify_status,
        }


@dataclass(frozen=True)
class OrderReasoning:
    order_seq: str | None
    code: str
    tree: ReasoningNode
    soap_checklist: tuple[SoapItem, ...]
    dropped_unverified: int = 0

    def to_dict(self) -> dict:
        return {
            "order_seq": self.order_seq,
            "code": self.code,
            "tree": self.tree.to_dict(),
            "soap_checklist": [item.to_dict() for item in self.soap_checklist],
            "dropped_unverified": self.dropped_unverified,
        }


# ── 驗證（防幻覺） ───────────────────────────────────────────────


def _sources(finding: OrderFinding) -> dict[str, str]:
    return dict(finding.source_texts)


def is_verbatim(text: str, source_name: str | None, finding: OrderFinding) -> bool:
    """`text` 是否為指定來源（或任一規則來源，若 source_name 為 None）原文的逐字子字串。"""
    sources = _sources(finding)
    if source_name is not None:
        original = sources.get(source_name)
        return original is not None and text in original
    return any(text in original for original in sources.values())


def _verified(item: SoapItem, finding: OrderFinding) -> bool:
    if item.quote is not None and not is_verbatim(item.quote, item.source, finding):
        return False
    return all(is_verbatim(code, None, finding) for code in item.codes)


# ── 分類 ─────────────────────────────────────────────────────────


def _category_of(evidence: Evidence) -> str:
    for kind in _PRIORITY:
        if kind in evidence.kinds:
            if kind in ("test", "documentation"):
                return "prerequisite"
            return kind
    if "indication" in evidence.kinds:
        return "indication"
    return "other"


def _grouped(finding: OrderFinding) -> dict[str, list[Evidence]]:
    groups: dict[str, list[Evidence]] = {key: [] for key in CATEGORY_ORDER}
    for evidence in finding.evidence:
        groups[_category_of(evidence)].append(evidence)
    return groups


def _diagnosis_codes_clause(finding: OrderFinding, case_dx: str) -> str:
    codes = "、".join(finding.icd_in_rule) if finding.icd_in_rule else "（無）"
    check = _CHECK_LABELS.get(finding.diagnosis_check, finding.diagnosis_check)
    return f"條文列出代碼：{codes}；案件主診斷：{case_dx or '（缺漏）'}；系統比對：{check}"


# ── 推理樹 ───────────────────────────────────────────────────────


def build_reasoning_tree(finding: OrderFinding, *, case_dx: str | None = None) -> ReasoningNode:
    """依 OrderFinding 建立 Tree of Criteria（節點全部來自原文或結構化欄位）。"""
    counter = iter(range(1, 10_000))

    def nid(prefix: str) -> str:
        return f"{prefix}.{next(counter)}"

    def fact(label: str) -> ReasoningNode:
        return ReasoningNode(node_id=nid("f"), label=label, kind="fact")

    rule_label = finding.rule_name or "（規則名稱缺漏）"
    children: list[ReasoningNode] = [
        fact(f"規則狀態：{RULE_STATUS_LABELS.get(finding.rule_status, finding.rule_status)}"),
        fact("觸發旗標：" + "、".join(finding.flags)),
    ]

    if finding.rule_status == STATUS_UNDETERMINED:
        children.append(fact(f"待判定（規則庫查詢失敗，非判定結果）：{finding.error or ''}"))
        return ReasoningNode(node_id=nid("r"), label=f"{finding.code} {rule_label}", kind="root", children=tuple(children))
    if finding.rule_status == STATUS_NOT_FOUND:
        children.append(fact("查無規則，無條件可推理"))
        return ReasoningNode(node_id=nid("r"), label=f"{finding.code} {rule_label}", kind="root", children=tuple(children))
    if finding.rule_status == STATUS_NO_TEXT:
        children.append(fact("規則無給付文字，無可引述條件"))

    groups = _grouped(finding)
    for key in CATEGORY_ORDER:
        title, _section = CATEGORY_TITLES[key]
        criteria = [
            ReasoningNode(node_id=nid("c"), label=ev.sentence, kind="criterion", quote=ev.sentence, source=ev.source)
            for ev in groups[key]
        ]
        if criteria:
            children.append(ReasoningNode(node_id=nid("g"), label=title, kind="category", children=tuple(criteria)))

    # 無內容的事實節點不輸出（規則無 ICD 代碼、無生效期間資料時，不顯示空白說明）。
    if finding.icd_in_rule:
        children.append(fact("診斷比對：" + _diagnosis_codes_clause(finding, case_dx or "")))
    if finding.effective_from or finding.effective_to or finding.period_check in ("unknown", "no_visit_date"):
        period = _PERIOD_LABELS.get(finding.period_check, finding.period_check)
        if finding.effective_from or finding.effective_to:
            period += f"（規則生效：{finding.effective_from or '—'} ～ {finding.effective_to or '—'}）"
        children.append(fact(f"生效期間：{period}"))

    return ReasoningNode(node_id=nid("r"), label=f"{finding.code} {rule_label}", kind="root", children=tuple(children))


# ── SOAP 補強 ─────────────────────────────────────────────────────


def _prompts_for(key: str, quote: str) -> tuple[str, str]:
    """回傳 (SOAP 區段, 固定模板句)；模板本身不含任何醫療事實，只引述原文。"""
    if key == "indication":
        return "S/O", f"病歷 S／O 應能呈現符合此條文適應症的描述：「{quote}」"
    if key == "prerequisite":
        return "O / ATT", f"病歷 O 或附件應記載此條文要求之檢查、檢驗或文件：「{quote}」"
    if key == "frequency":
        return "P", f"病歷 P 應記載此條文要求之用量、頻次或療程：「{quote}」"
    return "—", f"需人工比對此條文：「{quote}」"


def build_soap_checklist(finding: OrderFinding, *, case_dx: str | None = None) -> tuple[tuple[SoapItem, ...], int]:
    """依條文產生 SOAP 補強清單；回傳 (通過驗證的項目, 因驗證失敗被丟棄的數量)。"""
    items: list[SoapItem] = []
    groups = _grouped(finding)
    for key in CATEGORY_ORDER:
        for ev in groups[key]:
            if key == "other":
                section, prompt = "—", f"需人工比對此條文：「{ev.sentence}」"
            else:
                section, prompt = _prompts_for(key, ev.sentence)
            items.append(SoapItem(section=section, category=key, prompt=prompt, quote=ev.sentence, source=ev.source))

    if finding.icd_in_rule:
        quote_ev = next(
            (ev for ev in finding.evidence if any(code in ev.sentence for code in finding.icd_in_rule)),
            None,
        )
        items.append(
            SoapItem(
                section="A",
                category="diagnosis",
                prompt="病歷 A 應記載與條文相符之診斷。" + _diagnosis_codes_clause(finding, case_dx or ""),
                quote=quote_ev.sentence if quote_ev else None,
                source=quote_ev.source if quote_ev else None,
                codes=finding.icd_in_rule,
            )
        )

    kept = [item for item in items if _verified(item, finding)]
    return tuple(kept), len(items) - len(kept)


def build_order_reasoning(finding: OrderFinding, *, case_dx: str | None = None) -> OrderReasoning:
    checklist, dropped = build_soap_checklist(finding, case_dx=case_dx)
    return OrderReasoning(
        order_seq=finding.order_seq,
        code=finding.code,
        tree=build_reasoning_tree(finding, case_dx=case_dx),
        soap_checklist=checklist,
        dropped_unverified=dropped,
    )


def case_reasoning(case: CaseAudit) -> tuple[OrderReasoning, ...]:
    """案件內每個有旗標醫令的推理結果（與 case.findings 同順序）。"""
    dx = case.primary_diagnosis or ""
    return tuple(build_order_reasoning(f, case_dx=dx) for f in case.findings)


def attach_reasoning(case_dict: dict, case: CaseAudit) -> dict:
    """把推理結果併入 CaseAudit.to_dict() 的每個 finding（回傳新 dict，不改原物件）。"""
    reasonings = case_reasoning(case)
    findings = []
    for finding_dict, reasoning in zip(case_dict["findings"], reasonings):
        findings.append({**finding_dict, "reasoning": reasoning.to_dict()})
    return {**case_dict, "findings": findings}


__all__ = [
    "CATEGORY_TITLES",
    "OrderReasoning",
    "ReasoningNode",
    "SoapItem",
    "attach_reasoning",
    "build_order_reasoning",
    "build_reasoning_tree",
    "build_soap_checklist",
    "case_reasoning",
    "is_verbatim",
]
