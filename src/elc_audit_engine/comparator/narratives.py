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
    "不要輸出任何其他文字。"
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


class LLMNarrativeGenerator:
    """以 llama.cpp chat_completion 為後端的候選補強生成器（C2）。"""

    def __init__(self, *, max_tokens: int | None = None):
        self._max_tokens = max_tokens

    def generate(
        self, check_item: CheckItem, evidence: str, support_level: str
    ) -> list[CandidateNarrative]:
        if support_level not in (SUPPORT_WEAK, SUPPORT_NONE):
            return []
        user_prompt = (
            f"規則檢核項（出處：{check_item.rule_location or '未知'}）：\n"
            f"{check_item.rule_text}\n\n病歷段落：\n{evidence}"
        )
        try:
            raw = chat_completion(
                _SYSTEM_PROMPT, user_prompt, max_tokens=self._max_tokens
            )
            items = _parse_json_array(raw)
        except Exception:
            return []
        if not items:
            return []

        narratives: list[CandidateNarrative] = []
        for item in items[:3]:
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            prompt_only = bool(item.get("prompt_only", False))
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
