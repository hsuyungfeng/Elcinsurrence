"""病歷證據組裝（D-02）：當次 SOAP ＋ 半年病史時間軸 → 病歷段落。

組裝結果是給 LLM 判定器（C1：檢核項＋病歷段落）與候選補強生成器
（C2：只能基於既有線索擴寫）的「病歷段落」文字。含長度上限
（9B 模型 token 考量）：每類至多 3 筆、每筆截斷 500 字。
"""

from __future__ import annotations

from elc_audit_engine.parsers.models import SOAPDocument, SubmissionCase
from elc_audit_engine.record_aggregator.models import PatientTimeline

_MAX_ITEMS_PER_CATEGORY = 3
_MAX_TEXT_PER_ITEM = 500


def _truncate(text: str, limit: int = _MAX_TEXT_PER_ITEM) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _soap_block(soap_doc: SOAPDocument | None) -> list[str]:
    """當次 SOAP 分段 → 段落區塊（marker/keyword 兩層皆可用）。"""
    if soap_doc is None:
        return []
    lines = ["【當次 SOAP】"]
    for letter in ("S", "O", "A", "P"):
        texts = soap_doc.sections.get(letter, ())
        if texts:
            lines.append(f"[{letter}] " + _truncate("；".join(texts)))
    if soap_doc.unclassified:
        lines.append("[未分類] " + _truncate("；".join(soap_doc.unclassified)))
    return lines


def _timeline_block(timeline: PatientTimeline | None) -> list[str]:
    """半年病史時間軸 → 段落區塊（四類，每類至多 3 筆）。"""
    if timeline is None:
        return []
    lines = [f"【半年病史 {timeline.window_start}~{timeline.window_end}】"]
    for record in list(timeline.visits)[:_MAX_ITEMS_PER_CATEGORY]:
        clinic = record.clinic or "（無科別）"
        soap = record.soap_text or "（無 SOAP 內容）"
        lines.append(f"[就診 {record.date} {clinic}] {_truncate(soap)}")
    for record in list(timeline.labs)[:_MAX_ITEMS_PER_CATEGORY]:
        abnormal = "（異常）" if record.abnormal is True else ""
        lines.append(
            f"[檢驗 {record.date}] {record.test_name} = {record.result} "
            f"{record.unit}{abnormal}"
        )
    for record in list(timeline.exams)[:_MAX_ITEMS_PER_CATEGORY]:
        lines.append(f"[檢查 {record.date}] {record.exam_name}：{_truncate(record.finding)}")
    for record in list(timeline.imaging)[:_MAX_ITEMS_PER_CATEGORY]:
        lines.append(
            f"[影像 {record.date}] {record.modality} {record.body_part}："
            f"{_truncate(record.impression)}"
        )
    return lines


def build_evidence_blocks(
    case: SubmissionCase,
    soap_doc: SOAPDocument | None,
    timeline: PatientTimeline | None,
) -> str:
    """組裝病歷段落文字（D-02）。

    Args:
        case: 申報案件（提供病歷號/診斷碼作上下文）。
        soap_doc: 當次 SOAP 分段結果；None 時該區塊省略。
        timeline: 半年病史時間軸；None（病歷缺席）時只輸出 SOAP 區塊。

    Returns:
        組裝後的病歷段落文字（多行，含區塊標題）。
    """
    lines: list[str] = []
    if case.record_no:
        lines.append(f"【案件】病歷號 {case.record_no}")
    if case.primary_diagnosis:
        diag = case.primary_diagnosis
        if case.secondary_diagnoses:
            diag += "（次診斷：" + "、".join(case.secondary_diagnoses) + "）"
        lines.append(f"【診斷】{diag}")

    lines.extend(_soap_block(soap_doc))
    lines.extend(_timeline_block(timeline))
    return "\n".join(lines)
