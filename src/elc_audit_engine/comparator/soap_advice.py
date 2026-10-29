"""LLM SOAP 智慧補強與比對建議模組。

比對原始門診 SOAP 與雲端病歷/病史時間軸，產出具體的 SOAP 改進建議與醫師審批重點。
支援 Qwen3.8-27B-FP8 / Qwen3.8-27B-UD-Q4_K_XL（禁用 thinking token，保證低延遲快速回應）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from elc_audit_engine.prompt_safety import DATA_ISOLATION_NOTICE, fence
from elc_audit_engine.rule_repository.mapping.llm_client import chat_completion

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)

_SYSTEM_PROMPT = (
    "你是專業的健保審查輔助醫師。請比對醫師原始門診 SOAP 病歷與病患歷史/雲端病歷紀錄，"
    "給出結構化 SOAP 與病歷補強建議，以供主治醫師審批。\n"
    "請輸出繁體中文 JSON 格式：\n"
    "{\n"
    '  "comparison": "病史與雲端比對重點分析（說明是否有用藥/檢驗衝突、給付間隔、或不足之處）",\n'
    '  "recommended_soap": {\n'
    '    "s": "主訴建議（基於既有病歷擴寫，不憑空捏造）",\n'
    '    "o": "客觀檢查建議（包含相關數據或檢查項目）",\n'
    '    "a": "評估診斷建議（包含 ICD 與病情描述）",\n'
    '    "p": "處置與處方建議（包含符合健保規範之計畫）"\n'
    "  },\n"
    '  "approval_advice": "供主治醫師審批核可的具體補強建議與注意事項"\n'
    "}\n"
    "請只輸出 JSON，勿輸出其他 markdown 或說明文字。\n"
    + DATA_ISOLATION_NOTICE
)


def _parse_llm_json(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(raw_text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def generate_soap_advice(
    order_code: str,
    order_name: str,
    soap_text: str,
    patient_history: str = "",
    rule_text: str = "",
    max_tokens: int = 700,
) -> dict[str, Any]:
    """呼叫本機 LLM 生成比對分析與 SOAP 補強建議。"""
    user_prompt = (
        f"醫令代碼：{order_code}\n"
        f"醫令名稱：{order_name}\n"
        f"原始門診 SOAP：\n{fence(soap_text or '（未填寫原始 SOAP）', 'soap')}\n\n"
        f"病患病史與雲端病歷紀錄：\n{fence(patient_history or '（無雲端病歷紀錄）', 'history')}\n\n"
        f"健保給付規定：\n{fence(rule_text or '（依健保常規給付規範）', 'rule')}"
    )

    try:
        resp = chat_completion(_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)
        parsed = _parse_llm_json(resp)
        if parsed and "recommended_soap" in parsed:
            return {
                "status": "success",
                "comparison": parsed.get("comparison", ""),
                "recommended_soap": parsed.get("recommended_soap", {}),
                "approval_advice": parsed.get("approval_advice", ""),
                "raw_response": resp,
            }
        # 若 JSON 格式未完全符合，回傳退化文字
        return {
            "status": "fallback",
            "comparison": "模型未回傳完整結構，以下為原始文字：",
            "recommended_soap": {"s": "", "o": "", "a": "", "p": resp},
            "approval_advice": "請醫師人工查核病歷支持度。",
            "raw_response": resp,
        }
    except Exception as exc:
        return {
            "status": "error",
            "comparison": f"LLM 服務無法連線或判定逾時：{exc}",
            "recommended_soap": {"s": "", "o": "", "a": "", "p": ""},
            "approval_advice": "請人工查核病歷支持度。",
            "raw_response": "",
        }
