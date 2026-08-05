"""申復理由草稿組裝器（Phase 7，純組裝層）。

D10 四段組裝：①案情摘要 ②醫療必要性 ③規則依據 ④病歷佐證；每筆核減
醫令（`DeductionRecord` 一列）獨立生成。字數上限依官方問答集 **Q15**
（p8/p9 各 1000 中文字、合計放寬至 2000），裁剪優先 ④→②（C4，①③為
骨架不動）；P6 不申覆強制填 0 為 pure function 硬檢查（C3/Q13）。

純組裝層：**無 LLM、無規則庫查詢** — 規則全文由呼叫端經 `get_rule()`
取得後以字串注入（07-CONTEXT.md domain）。輸出
`申復草稿_{案件流水號}.md` ＋ `appeal_{流水號}.json`（C7）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence

from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.safe_paths import safe_filename
from elc_audit_engine.record_aggregator.models import PatientTimeline

from .tracking import STATUS_ADOPT, STATUS_ADOPT_EDITED

# Q15：p8/p9 各 1000 中文字、合計 2000（官方問答集，取代 C8 舊 2000/欄）。
MAX_TOTAL_CHARS = 2000
MAX_FIELD_CHARS = 1000

# 四段鍵（D10；①③骨架不動，②④可裁）。
KEY_CASE_SUMMARY = "case_summary"
KEY_NECESSITY = "necessity"
KEY_RULE_BASIS = "rule_basis"
KEY_EVIDENCE = "evidence"

_TITLES = {
    KEY_CASE_SUMMARY: "①案情摘要",
    KEY_NECESSITY: "②醫療必要性（半年病史）",
    KEY_RULE_BASIS: "③規則依據（條文原文）",
    KEY_EVIDENCE: "④病歷佐證（醫師採用補強敘述）",
}

# 裁剪優先序（C4）：④ 引文摘短 → ② 病史壓縮。
_TRIM_ORDER = (KEY_EVIDENCE, KEY_NECESSITY)

_EVIDENCE_PLACEHOLDER = "（本筆醫令尚無醫師採用的補強敘述）"


@dataclass(frozen=True)
class AppealSection:
    """申復草稿的單一段落。

    Attributes:
        key: KEY_CASE_SUMMARY/KEY_NECESSITY/KEY_RULE_BASIS/KEY_EVIDENCE。
        title: 顯示標題（①案情摘要…）。
        text: 段落文字。
        trimmed: 是否被字數控制器裁剪（C4）。
    """

    key: str
    title: str
    text: str
    trimmed: bool = False


@dataclass(frozen=True)
class AppealDraft:
    """單筆核減醫令的申復理由草稿（每筆獨立生成，D10）。

    Attributes:
        case_class/case_seq/order_seq/order_code/visit_date/fee_year_month:
            案件與醫令識別（取自 DeductionRecord，D-14d）。
        deduction_upper_bound: 核減上界（欄 1 不予核銷金額，D-15；
            申復點數不得超過）。
        deduction_reason: 追扣原因（自由中文原樣）。
        is_appealing: 是否申覆本筆醫令。
        has_attachment: p7 申復檔案連結（True=Y，透過 PACS 補證據）。
        sections: 四段（組裝後，可能已被字數控制器裁剪）。
        reason1/reason2: p8 申復理由一／p9 申復理由二（各 ≤1000 字；
            不申覆時皆空）。
        p6_points: p6 點數受理（不申覆強制 0）。
        total_chars: 四段合計字數（≤2000，超過時 over_limit=True）。
        over_limit: 全部可裁段裁完仍超上限（建議 p7=Y）。
        validation_errors: 硬檢查失敗訊息（不靜默修正，留醫師確認）。
    """

    case_class: str | None = None
    case_seq: str = ""
    order_seq: str | None = None
    order_code: str = ""
    visit_date: str | None = None
    fee_year_month: str | None = None
    deduction_upper_bound: int | None = None
    deduction_reason: str | None = None
    is_appealing: bool = True
    has_attachment: bool = False
    sections: tuple[AppealSection, ...] = ()
    reason1: str = ""
    reason2: str = ""
    p6_points: int = 0
    total_chars: int = 0
    over_limit: bool = False
    validation_errors: tuple[str, ...] = ()


def _fmt(value) -> str:
    """顯示用格式化：None/空字串 → 佔位符。"""
    if value is None or value == "":
        return "—"
    return str(value)


def _build_case_summary(record: DeductionRecord) -> str:
    """①案情摘要：案件識別＋醫令＋核減事實（D10）。"""
    seq_part = f"（序 {record.order_seq}）" if record.order_seq else ""
    lines = [
        f"本案件（分類 {_fmt(record.case_class)}、流水號 {_fmt(record.case_seq)}）"
        f"於 {_fmt(record.fee_year_month)} 費用年月、{_fmt(record.visit_date)} 就醫，"
        f"醫令 {_fmt(record.order_code)}{seq_part}"
        f"遭核減 {_fmt(record.non_reimbursed_amount)} 點。"
    ]
    if record.deduction_reason:
        lines.append(f"核減原因：{record.deduction_reason}")
    if record.appeal_item_code or record.appeal_item_desc:
        item = record.appeal_item_code or ""
        desc = record.appeal_item_desc or ""
        lines.append(f"院所申復事項：{item}-{desc}" if item else f"院所申復事項：{desc}")
    if record.institution_note:
        lines.append(f"院所說明：{record.institution_note}")
    return "\n".join(lines)


def build_necessity(timeline: PatientTimeline | None) -> str:
    """②醫療必要性：半年病史摘要（D10；timeline=None 降級，C5）。

    Args:
        timeline: Phase 4 時間軸；None＝病歷缺席（降級文字）。

    Returns:
        醫療必要性文字（就診/檢驗/檢查/影像摘要）。
    """
    if timeline is None:
        return "（病歷缺席，無半年病史可資佐證）"
    lines = [
        f"半年病史（{timeline.window_start} ~ {timeline.window_end}）："
        f"就診 {len(timeline.visits)} 次、檢驗 {len(timeline.labs)} 筆、"
        f"檢查 {len(timeline.exams)} 筆、影像 {len(timeline.imaging)} 筆。"
    ]
    for record in timeline.visits:
        soap = (record.soap_text or "").replace("\n", " ")[:40]
        lines.append(f"就診 {record.date} {record.clinic}：{soap or '（無SOAP）'}")
    for record in timeline.labs:
        lines.append(
            f"檢驗 {record.date}：{record.test_name} = {record.result} {record.unit}".rstrip()
        )
    for record in timeline.exams:
        lines.append(f"檢查 {record.date}：{record.exam_name}：{(record.finding or '')[:40]}")
    for record in timeline.imaging:
        lines.append(
            f"影像 {record.date}：{record.modality} {record.body_part}："
            f"{(record.impression or '')[:40]}"
        )
    return "\n".join(lines)


def _build_rule_basis(
    rule_text: str | None, rule_location: str | None, order_code: str
) -> str:
    """③規則依據：條文原文＋出處；無規則時誠實提示（不幻覺捏造）。"""
    if rule_text:
        line = rule_text
        if rule_location:
            line += f"\n（出處：{rule_location}）"
        return line
    return f"查無規則依據，建議人工查核（醫令 {_fmt(order_code)}）。"


def _build_evidence_text(evidence: Sequence) -> str:
    """④病歷佐證：醫師採用（採用/編輯後採用）的補強敘述。

    Args:
        evidence: 每項為 dict（text/rule_location，`adopted_narratives_from_tracking`
            的輸出）或純字串。
    """
    lines: list[str] = []
    for item in evidence:
        if isinstance(item, dict):
            text = item.get("text") or ""
            loc = item.get("rule_location")
        else:
            text = str(item)
            loc = None
        if not text.strip():
            continue
        line = f"- {text}"
        if loc:
            line += f"（{loc}）"
        lines.append(line)
    if not lines:
        return _EVIDENCE_PLACEHOLDER
    return "\n".join(lines)


def adopted_narratives_from_tracking(tracking) -> tuple[dict, ...]:
    """從 Phase 6 審核軌跡 JSON 取出「採用／編輯後採用」的補強敘述（D-08）。

    Args:
        tracking: 審核軌跡 JSON 字串或已解析的 dict（render_tracking 產出）。

    Returns:
        tuple of {text, rule_location, order_code}；edited_text 優先、其次
        narrative_text；order_code 供 Phase 7 依醫令過濾證據（08-CONTEXT
        D-03）。略過／標記不符事實／未審核 的條目一律排除。

    Raises:
        ValueError: 傳入字串但無法解析為 JSON。
    """
    if isinstance(tracking, str):
        try:
            tracking = json.loads(tracking)
        except json.JSONDecodeError as exc:
            raise ValueError(f"審核軌跡 JSON 無法解析: {exc}") from exc
    adopted: list[dict] = []
    for entry in tracking.get("entries", []):
        if entry.get("status") not in (STATUS_ADOPT, STATUS_ADOPT_EDITED):
            continue
        text = entry.get("edited_text") or entry.get("narrative_text") or ""
        if not text.strip():
            continue
        adopted.append(
            {
                "text": text,
                "rule_location": entry.get("rule_location"),
                "order_code": entry.get("order_code"),
            }
        )
    return tuple(adopted)


def resolve_p6_points(is_appealing: bool, claimed_points: int | None) -> int:
    """P6 點數受理硬檢查（C3/Q13）：不申覆 → 強制 0。

    Args:
        is_appealing: 是否申覆本筆醫令。
        claimed_points: 院所申復點數（申覆時填報）。

    Returns:
        p6 值：不申覆一律 0；申覆時為 claimed_points（負數視為 0，
        由 `validate_appeal_claim` 另行捕捉）。
    """
    if not is_appealing:
        return 0
    if claimed_points is None:
        return 0
    return max(claimed_points, 0)


def validate_appeal_claim(
    is_appealing: bool, claimed_points: int | None, upper_bound: int | None
) -> tuple[str, ...]:
    """申覆訴求硬檢查（純函式，C3/D-15）。

    Returns:
        錯誤訊息 tuple（空＝通過）。規則：
        - 不申覆 → 直接通過（P6 由 resolve_p6_points 強制 0）。
        - 申覆必須填報點數；claimed 不得為負。
        - claimed 不得超過核減上界（欄 1 不予核銷金額，D-15；
          官方 p6 勾稽「申復點數需<=核減點數」）。
    """
    if not is_appealing:
        return ()
    errors: list[str] = []
    if claimed_points is None:
        errors.append("申覆醫令必須填報申復點數（p6 點數受理）")
    else:
        if claimed_points < 0:
            errors.append(f"申復點數不得為負（收到 {claimed_points}）")
        if upper_bound is not None and claimed_points > upper_bound:
            errors.append(
                f"申復點數 {claimed_points} 超過核減上界 {upper_bound}"
                "（D-15：申復點數需<=核減點數）"
            )
    return tuple(errors)


def _split_reason(text: str) -> tuple[str, str]:
    """把組裝全文切成 p8/p9（各 ≤1000 字，官方 Q15）。"""
    return text[:MAX_FIELD_CHARS], text[MAX_FIELD_CHARS : MAX_FIELD_CHARS * 2]


def _trim_evidence_lines(text: str, excess: int) -> tuple[str, int]:
    """④病歷佐證裁剪：由尾端逐列移除證據列，最後一列再摘短（C4 引文摘短）。

    Returns:
        (裁後文字, 實際移除字數)。
    """
    lines = text.split("\n")
    removed = 0
    while lines and removed < excess:
        line = lines[-1]
        line_len = len(line)
        remaining = excess - removed
        if line_len <= remaining:
            lines.pop()
            removed += line_len
        else:
            lines[-1] = line[: line_len - remaining]
            removed += remaining
    return "\n".join(lines), removed


def _trim_sections(
    sections: tuple[AppealSection, ...], limit: int = MAX_TOTAL_CHARS
) -> tuple[tuple[AppealSection, ...], bool]:
    """字數控制器（C4/Q15）：合計 >2000 時按 ④→② 優先裁剪，①③ 不動。

    Returns:
        (裁後 sections, over_limit)。over_limit=True 表示可裁段全部裁完
        仍超上限（建議 p7=Y 以檔案連結提供）。
    """
    sections = list(sections)
    total = sum(len(s.text) for s in sections)
    if total <= limit:
        return tuple(sections), False

    excess = total - limit
    for key in _TRIM_ORDER:
        if excess <= 0:
            break
        idx = next((i for i, s in enumerate(sections) if s.key == key), None)
        if idx is None:
            continue
        sec = sections[idx]
        if key == KEY_EVIDENCE:
            new_text, removed = _trim_evidence_lines(sec.text, excess)
        else:
            keep = max(0, len(sec.text) - excess)
            new_text = sec.text[:keep]
            removed = len(sec.text) - keep
        if removed > 0:
            excess -= removed
            sections[idx] = AppealSection(key, sec.title, new_text, trimmed=True)
    return tuple(sections), excess > 0


def build_appeal_draft(
    record: DeductionRecord,
    *,
    is_appealing: bool = True,
    claimed_points: int | None = None,
    timeline: PatientTimeline | None = None,
    rule_text: str | None = None,
    rule_location: str | None = None,
    evidence: Sequence = (),
    has_attachment: bool = False,
) -> AppealDraft:
    """組裝單筆核減醫令的申復理由草稿（D10，每筆獨立生成）。

    Args:
        record: Phase 3 核減明細一列（D-14d 18 欄；non_reimbursed_amount
            為 D-15 核減上界）。
        is_appealing: 是否申覆本筆；False 時 P6 強制 0、p8/p9 免填。
        claimed_points: 院所申復點數（申覆時填報）。
        timeline: Phase 4 半年病史（②素材）；None＝病歷缺席降級（C5）。
        rule_text: 規則全文（呼叫端經 get_rule 注入；None＝查無規則）。
        rule_location: 規則出處（條文位置）。
        evidence: 醫師採用敘述（`adopted_narratives_from_tracking` 輸出
            或字串序列，④素材）。
        has_attachment: p7 申復檔案連結（True=Y）。

    Returns:
        AppealDraft：四段＋p8/p9＋p6＋字數統計＋硬檢查結果。
    """
    sections = (
        AppealSection(KEY_CASE_SUMMARY, _TITLES[KEY_CASE_SUMMARY], _build_case_summary(record)),
        AppealSection(KEY_NECESSITY, _TITLES[KEY_NECESSITY], build_necessity(timeline)),
        AppealSection(
            KEY_RULE_BASIS,
            _TITLES[KEY_RULE_BASIS],
            _build_rule_basis(rule_text, rule_location, record.order_code or ""),
        ),
        AppealSection(KEY_EVIDENCE, _TITLES[KEY_EVIDENCE], _build_evidence_text(evidence)),
    )
    sections, over_limit = _trim_sections(sections)

    total_chars = sum(len(s.text) for s in sections)
    reason1, reason2 = _split_reason("".join(s.text for s in sections))
    if not is_appealing:
        # Q13：不申覆 → P6 強制 0；p8/p9 免填（△ 無資料者免填）。
        reason1, reason2 = "", ""

    p6_points = resolve_p6_points(is_appealing, claimed_points)
    errors = validate_appeal_claim(
        is_appealing, claimed_points, record.non_reimbursed_amount
    )

    return AppealDraft(
        case_class=record.case_class,
        case_seq=record.case_seq or "",
        order_seq=record.order_seq,
        order_code=record.order_code or "",
        visit_date=record.visit_date,
        fee_year_month=record.fee_year_month,
        deduction_upper_bound=record.non_reimbursed_amount,
        deduction_reason=record.deduction_reason,
        is_appealing=is_appealing,
        has_attachment=has_attachment,
        sections=sections,
        reason1=reason1,
        reason2=reason2,
        p6_points=p6_points,
        total_chars=total_chars,
        over_limit=over_limit,
        validation_errors=errors,
    )


def render_appeal_markdown(draft: AppealDraft) -> str:
    """渲染申復草稿 Markdown（醫師審閱版，C7）。"""
    lines = ["# 申復理由草稿", ""]
    lines.append(
        f"- 案件分類：{_fmt(draft.case_class)}｜流水號：{_fmt(draft.case_seq)}"
    )
    lines.append(
        f"- 就醫日期：{_fmt(draft.visit_date)}｜費用年月：{_fmt(draft.fee_year_month)}"
    )
    lines.append(
        f"- 醫令：`{_fmt(draft.order_code)}`"
        + (f"（序 {draft.order_seq}）" if draft.order_seq else "")
    )
    if draft.deduction_upper_bound is not None:
        lines.append(f"- 核減上界（不予核銷金額）：{draft.deduction_upper_bound} 點")
    lines.append(
        f"- 申復與否：{'申覆' if draft.is_appealing else '不申覆'}｜"
        f"P6 點數受理：{draft.p6_points}"
    )
    lines.append(
        f"- 字數：{draft.total_chars} / {MAX_TOTAL_CHARS}"
        f"（每欄上限 {MAX_FIELD_CHARS} 字）"
    )
    lines.append("")

    for sec in draft.sections:
        lines.append(f"## {sec.title}" + ("（已裁剪）" if sec.trimmed else ""))
        lines.append("")
        lines.append(sec.text)
        lines.append("")

    lines.append("## 申復理由欄位（p8/p9）")
    lines.append("")
    lines.append(f"- p8 申復理由一（≤{MAX_FIELD_CHARS}字）：{draft.reason1 or '（免填）'}")
    lines.append(f"- p9 申復理由二（≤{MAX_FIELD_CHARS}字）：{draft.reason2 or '（免填）'}")
    lines.append("")

    warnings: list[str] = []
    if draft.over_limit:
        warnings.append(
            f"⚠ 全文超過 {MAX_TOTAL_CHARS} 字上限且已盡最大裁剪；"
            "建議 p7 申復檔案連結填 Y，以檔案連結提供完整資料（官方 Q15）"
        )
    for sec in draft.sections:
        if sec.trimmed:
            warnings.append(f"⚠ 已裁剪：{sec.title}（請醫師確認內容完整）")
    for err in draft.validation_errors:
        warnings.append(f"⚠ 硬檢查：{err}")
    if not draft.is_appealing:
        warnings.append(
            "⚠ 本筆不申覆：P6 點數受理已強制填 0（官方 Q13），p8/p9 免填"
        )
    if warnings:
        lines.append("## ⚠ 注意事項")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def render_appeal_json(draft: AppealDraft) -> str:
    """渲染申復草稿 JSON（appeal_{流水號}.json，Phase 2 轉申復 XML，C7/D-06）。"""
    payload = {
        "format": "appeal-draft/v1",
        "case_class": draft.case_class,
        "case_seq": draft.case_seq,
        "order_seq": draft.order_seq,
        "order_code": draft.order_code,
        "visit_date": draft.visit_date,
        "fee_year_month": draft.fee_year_month,
        "deduction_upper_bound": draft.deduction_upper_bound,
        "deduction_reason": draft.deduction_reason,
        "is_appealing": draft.is_appealing,
        # 申復 XML 醫令段欄位（C8：p1-p9）
        "p1_order_seq": draft.order_seq,
        "p2_order_code": draft.order_code,
        "p3_change_seq": None,
        "p4_rate": None,
        "p5_quantity": None,
        "p6_points": draft.p6_points,
        "p7_attachment": "Y" if draft.has_attachment else "N",
        "p8_reason1": draft.reason1,
        "p9_reason2": draft.reason2,
        "sections": [
            {"key": s.key, "title": s.title, "text": s.text, "trimmed": s.trimmed}
            for s in draft.sections
        ],
        "word_stats": {
            "total_chars": draft.total_chars,
            "max_total": MAX_TOTAL_CHARS,
            "per_field_max": MAX_FIELD_CHARS,
            "over_limit": draft.over_limit,
        },
        "validation_errors": list(draft.validation_errors),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_appeal(
    output_dir: str | os.PathLike[str],
    case_seq: str,
    draft: AppealDraft,
    *,
    file_stem: str | None = None,
) -> tuple[str, str]:
    """寫出申復草稿.md 與 appeal.json（D-05，薄包裝；C7 命名）。

    Args:
        output_dir: 輸出目錄（可注入；預設由呼叫端傳 config.settings.OUTPUT_DIR）。
        case_seq: 案件流水號（檔名一部分，C7）。
        draft: 組裝完成的草稿。
        file_stem: 檔名主幹（不含副檔名）；預設為 case_seq。
            同一案件多筆核減醫令時可傳 `{case_seq}_{order_seq}` 避免覆寫
            （預設維持 C7 命名）。

    Returns:
        (md 路徑, json 路徑)。
    """
    # P1-3：stem 進檔名，未校驗會造成寫入型路徑穿越。校驗組合後的結果——
    # `{case_seq}_{order_seq}` 的底線在白名單內，合法組合不受影響。
    stem = safe_filename(file_stem or (case_seq or "unknown"), "file_stem/case_seq")
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f"申復草稿_{stem}.md")
    json_path = os.path.join(output_dir, f"appeal_{stem}.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_appeal_markdown(draft))
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(render_appeal_json(draft))

    return md_path, json_path
