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
    "You are an expert clinical medical reviewer and National Health Insurance (NHI) audit specialist in Taiwan.\n"
    "Your mission: Compare the physician's preliminary outpatient SOAP record with the patient's longitudinal history and cloud EHR records.\n"
    "Provide a professionally structured SOAP recommendation and clinical review checklist for the attending physician's approval.\n\n"
    "CRITICAL BILINGUAL CONSTRAINTS:\n"
    "1. `recommended_soap` (S, O, A, P fields) MUST be written in professional Medical English (including standard clinical abbreviations, terminology, and formatting commonly used by Taiwan physicians in HIS).\n"
    "2. `comparison` and `approval_advice` MUST be written in Traditional Chinese (繁體中文，台灣健保審查語境), explaining the regulatory requirements, potential non-reimbursement risks, and explicit approval/rejection guidance.\n\n"
    "Output ONLY a single valid JSON object in the following format (no extra text or markdown wrappers):\n"
    "{\n"
    '  "comparison": "病史與雲端比對重點分析（以繁體中文說明給付間隔、處方或檢驗衝突、及佐證不足之處）",\n'
    '  "recommended_soap": {\n'
    '    "s": "Subjective complaint in concise clinical Medical English (expanded strictly based on existing clues, do not hallucinate)",\n'
    '    "o": "Objective findings in Medical English (vital signs, physical examination, relevant lab/imaging values)",\n'
    '    "a": "Assessment in Medical English (including primary ICD-10 diagnosis code and disease status)",\n'
    '    "p": "Plan and interventions in Medical English (management plan conforming to NHI payment guidelines)"\n'
    "  },\n"
    '  "approval_advice": "供主治醫師審批核可的具體補強要點與注意事項（繁體中文）"\n'
    "}\n"
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
