"""LLM 判定器（D-03/C1/C5）：逐檢核項小問題判定，可注入替身。

- 強制 JSON：`{"verdict": "支持|部分支持|無記載", "quote": "...", "reason": "..."}`
- 解析失敗換措辭重試一次；仍失敗 → `待人工`（C5，不阻斷整案）
- `create_judger(judge_fn=None)` 提供注入點：測試傳入關鍵字規則式替身，
  零 LLM 依賴（D-08）
"""

from __future__ import annotations

import json
import re
from typing import Callable

from elc_audit_engine.prompt_safety import DATA_ISOLATION_NOTICE, fence
from elc_audit_engine.rule_repository.mapping.llm_client import chat_completion

from .models import CheckItem, Judgment, VERDICTS, VERDICT_MANUAL

_SYSTEM_PROMPT = (
    "你是病歷佐證判定助手。你會收到一個「檢核項」（健保規則要求，在 <rule> "
    "標籤內）與「病歷段落」（在 <record> 標籤內）。請判定病歷是否支持該檢核項，"
    "只輸出一個 JSON 物件，"
    "格式：{\"verdict\": \"支持\" 或 \"部分支持\" 或 \"無記載\", "
    "\"quote\": \"病歷原文中支持判定的一句話（無記載時為空字串）\", "
    "\"reason\": \"一句話理由\"}。不要輸出任何其他文字。\n"
    + DATA_ISOLATION_NOTICE
)

_RETRY_SYSTEM_PROMPT = (
    "你上次的回覆不是有效 JSON。請只輸出一個 JSON 物件，不要有前言、"
    "結語或 Markdown 程式碼區塊，格式：{\"verdict\": \"支持\" 或 "
    "\"部分支持\" 或 \"無記載\", \"quote\": \"...\", \"reason\": \"...\"}。\n"
    + DATA_ISOLATION_NOTICE
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def _parse_json_response(text: str) -> dict | None:
    """從 LLM 回覆中解析 JSON 物件（容忍 ```json 包覆與前後文字）。"""
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _to_judgment(data: dict | None) -> Judgment | None:
    """把解析出的 JSON dict 轉成 Judgment；欄位缺漏/verdict 非法回傳 None。"""
    if data is None:
        return None
    verdict = str(data.get("verdict", "")).strip()
    if verdict not in VERDICTS or verdict == VERDICT_MANUAL:
        return None
    return Judgment(
        verdict=verdict,
        quote=str(data.get("quote", "") or "").strip(),
        reason=str(data.get("reason", "") or "").strip(),
    )


JudgeFn = Callable[[CheckItem, str], Judgment]


class LLMJudger:
    """以 llama.cpp chat_completion 為後端的判定器（C1 JSON schema）。"""

    def __init__(self, *, max_tokens: int | None = None):
        self._max_tokens = max_tokens

    def _call(self, system_prompt: str, user_prompt: str) -> str:
        return chat_completion(system_prompt, user_prompt, max_tokens=self._max_tokens)

    def judge(self, check_item: CheckItem, evidence: str) -> Judgment:
        # P1-2：rule_text（LLM 生成後回流）與病歷原文（使用者可控）皆為
        # 不可信輸入，以標籤定界隔離，不與指令同層拼接。
        user_prompt = (
            "檢核項（規則要求）：\n"
            f"{fence(check_item.rule_text, 'rule')}\n\n"
            "病歷段落：\n"
            f"{fence(evidence, 'record')}"
        )
        try:
            raw = self._call(_SYSTEM_PROMPT, user_prompt)
            judgment = _to_judgment(_parse_json_response(raw))
            if judgment is not None:
                return judgment
            # 換措辭重試一次（C1：解析失敗換措辭重試）
            raw = self._call(_RETRY_SYSTEM_PROMPT, user_prompt)
            judgment = _to_judgment(_parse_json_response(raw))
            if judgment is not None:
                return judgment
        except Exception as exc:  # 網路/JSON/伺服器異常皆降級待人工（C5）
            return Judgment(
                verdict=VERDICT_MANUAL,
                quote="",
                reason=f"LLM 判定失敗，改待人工：{type(exc).__name__}",
            )
        return Judgment(
            verdict=VERDICT_MANUAL,
            quote="",
            reason="LLM 回覆無法解析為有效判定，改待人工",
        )


def create_judger(judge_fn: JudgeFn | None = None) -> JudgeFn:
    """建立判定器：傳入 judge_fn 走注入替身（測試用），否則回傳 LLMJudger。

    Args:
        judge_fn: 可呼叫物件 `(check_item, evidence) -> Judgment`；
            測試注入關鍵字規則式替身，零 LLM 依賴（D-08）。

    Returns:
        判定函式。
    """
    if judge_fn is not None:
        return judge_fn
    return LLMJudger().judge
