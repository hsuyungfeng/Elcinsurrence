"""候選補強敘述生成（D-05/C2）：缺口（薄弱/裸奔）生成 1~3 條，可注入。

C2 約束：
1. 只能基於既有線索擴寫（半年病史、當次 SOAP、規則要求的記載格式）
2. 無線索時生成提示型候選（「若實際有執行，請補充：…」），事實留給醫師
3. 每條附規則出處（article_location）
"""

from __future__ import annotations

import json
import re
from typing import Callable

from elc_audit_engine.prompt_safety import DATA_ISOLATION_NOTICE, fence
from elc_audit_engine.rule_repository.mapping.llm_client import chat_completion

from .models import (
    SUPPORT_NONE,
    SUPPORT_WEAK,
    CandidateNarrative,
    CheckItem,
)

_SYSTEM_PROMPT = (
    "你是病歷補強敘述助手。醫令的健保規則檢核項未被病歷充分支持，"
    "請生成 1~3 條「候選補強敘述」供醫師採用。硬性約束："
    "1. 只能基於病歷段落中既有線索擴寫，不得憑空編造事實；"
    "2. 若病歷無任何相關線索，改寫成提示型敘述（以「若實際有執行，"
    "請補充：」開頭），事實補充留給醫師；"
    "3. 只輸出一個 JSON 陣列：[{\"text\": \"敘述\", \"prompt_only\": true/false}]。"
    "不要輸出任何其他文字。\n"
    + DATA_ISOLATION_NOTICE
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


def _parse_json_array(text: str) -> list[dict] | None:
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except json.JSONDecodeError:
        pass
    match = _JSON_ARRAY_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            return None
    return None


NarrativeFn = Callable[[CheckItem, str, str], list[CandidateNarrative]]

_PROMPT_PREFIX = "若實際有執行，請補充："
_OVERLAP_NGRAM = 4


def _parse_bool(value) -> bool:
    """只把布林 True 或字串 "true" 視為真（bool("false") 為 True，B-WR-10）。"""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def _has_overlap(text: str, evidence: str, n: int = _OVERLAP_NGRAM) -> bool:
    """敘述與病歷段落是否共享至少一段連續 n 字（去空白）——C2「只能基於既有線索擴寫」的近似檢查。"""
    t = "".join(text.split())
    e = "".join(evidence.split())
    if len(t) < n:
        return t in e if t else False
    return any(t[i : i + n] in e for i in range(len(t) - n + 1))


class LLMNarrativeGenerator:
    """以 llama.cpp chat_completion 為後端的候選補強生成器（C2）。"""

    def __init__(self, *, max_tokens: int | None = None):
        self._max_tokens = max_tokens

    def generate(
        self, check_item: CheckItem, evidence: str, support_level: str
    ) -> list[CandidateNarrative]:
        if support_level not in (SUPPORT_WEAK, SUPPORT_NONE):
            return []
        # P1-2：rule_location/rule_text（LLM 生成後回流）與病歷原文皆不可信，
        # 以標籤定界隔離。
        user_prompt = (
            "規則檢核項出處：\n"
            f"{fence(check_item.rule_location or '未知', 'rule_location')}\n\n"
            "規則檢核項：\n"
            f"{fence(check_item.rule_text, 'rule')}\n\n"
            "病歷段落：\n"
            f"{fence(evidence, 'record')}"
        )
        # LLM 呼叫失敗不再吞成 []：交由 compare_case 標記 narrative_error，
        # 讓「生成失敗」與「沒有建議」可區分（B-WR-10）。
        raw = chat_completion(_SYSTEM_PROMPT, user_prompt, max_tokens=self._max_tokens)
        items = _parse_json_array(raw)
        if items is None:
            raise ValueError("候選補強回覆無法解析為 JSON 陣列")
        if not items:
            return []

        narratives: list[CandidateNarrative] = []
        for item in items[:3]:
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            prompt_only = _parse_bool(item.get("prompt_only", False)) or text.startswith(_PROMPT_PREFIX)
            if not prompt_only and not _has_overlap(text, evidence):
                # 宣稱基於病歷線索卻與病歷段落毫無重疊：視為可能捏造的事實，
                # 強制改為提示型，事實留給醫師確認（C2）。
                text = _PROMPT_PREFIX + text
                prompt_only = True
            elif prompt_only and not text.startswith(_PROMPT_PREFIX):
                text = _PROMPT_PREFIX + text
            narratives.append(
                CandidateNarrative(
                    text=text,
                    rule_location=check_item.rule_location,
                    prompt_only=prompt_only,
                )
            )
        return narratives


def create_generator(
    narrative_fn: NarrativeFn | None = None,
) -> NarrativeFn:
    """建立候選補強生成器：傳入 narrative_fn 走注入替身，否則 LLM 路徑。"""
    if narrative_fn is not None:
        return narrative_fn
    return LLMNarrativeGenerator().generate
