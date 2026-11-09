"""標準 SOAP 範本比對模組（Phase 29 §5，advisory）。

純函式設計：
比對 LLM 預生成草稿（S/O/A/P）與該醫令之標準範本。
產出欄位相似度（difflib）、長度統計、缺漏欄位、ICD-10 一致性比對。

注意：
比對結果僅供醫師審查參考（advisory only），不得作為自動核准/退回的硬性門檻，
亦不得藉由比對結果將草稿變更為 validated 以外之狀態。
"""

from __future__ import annotations

import difflib
import re
from typing import Any

_SOAP_SECTIONS = ("s", "o", "a", "p")
_ICD10_RE = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\b")


def extract_icd10_codes(text: str) -> list[str]:
    """自文字中擷取所有符合 ICD-10 格式的代碼（排序並去重）。"""
    if not text:
        return []
    matches = _ICD10_RE.findall(text)
    return sorted(set(m.upper() for m in matches))


def compare_soap_with_template(
    draft_soap: dict[str, Any],
    template_soap: dict[str, Any],
    rule_text: str = "",
) -> dict[str, Any]:
    """比對 LLM 草稿與標準範本（純函式）。

    Args:
        draft_soap: 預生成或醫師編修之草稿字典（含 s, o, a, p 鍵）。
        template_soap: 該醫令之標準範本字典（含 s, o, a, p 鍵）。
        rule_text: 健保支付規定原文（選填，用於比對規定中提及之 ICD-10）。

    Returns:
        包含以下鍵的字典：
        - advisory_only: 固定為 True
        - section_similarities: 各欄位的 difflib SequenceMatcher 相似度 (0.0 ~ 1.0)
        - overall_similarity: 四欄平均相似度 (0.0 ~ 1.0)
        - missing_sections: 草稿中未填寫的欄位列表
        - section_lengths: 各欄位字元長度與總長度
        - icd10_comparison: ICD-10 萃取與比對結果
    """
    draft = draft_soap if isinstance(draft_soap, dict) else {}
    template = template_soap if isinstance(template_soap, dict) else {}

    similarities: dict[str, float] = {}
    missing_sections: list[str] = []
    section_lengths: dict[str, int] = {}

    for sec in _SOAP_SECTIONS:
        d_val = str(draft.get(sec) or "").strip()
        t_val = str(template.get(sec) or "").strip()

        section_lengths[sec] = len(d_val)
        if not d_val:
            missing_sections.append(sec)

        if not d_val and not t_val:
            sim = 1.0
        elif not d_val or not t_val:
            sim = 0.0
        else:
            matcher = difflib.SequenceMatcher(None, d_val.lower(), t_val.lower())
            sim = round(matcher.ratio(), 4)
        similarities[sec] = sim

    section_lengths["total"] = sum(section_lengths[s] for s in _SOAP_SECTIONS)

    # 4 欄平均相似度
    overall_sim = round(sum(similarities.values()) / 4.0, 4)

    # ICD-10 代碼比對（主要檢查 A 欄診斷評估）
    draft_a = str(draft.get("a") or "")
    template_a = str(template.get("a") or "")

    draft_icds = extract_icd10_codes(draft_a)
    template_icds = extract_icd10_codes(template_a)
    rule_icds = extract_icd10_codes(rule_text)

    # 檢查草稿 ICD-10 是否有涵蓋範本或規定中的代碼
    expected_icds = sorted(set(template_icds) | set(rule_icds))
    matched_icds = sorted(set(draft_icds) & set(expected_icds))

    icd_comparison = {
        "draft_icds": draft_icds,
        "template_icds": template_icds,
        "rule_icds": rule_icds,
        "matched_icds": matched_icds,
        "consistent_with_template": bool(set(draft_icds) & set(template_icds)) if template_icds else None,
        "consistent_with_rule": bool(set(draft_icds) & set(rule_icds)) if rule_icds else None,
    }

    return {
        "advisory_only": True,
        "section_similarities": similarities,
        "overall_similarity": overall_sim,
        "missing_sections": missing_sections,
        "section_lengths": section_lengths,
        "icd10_comparison": icd_comparison,
    }
