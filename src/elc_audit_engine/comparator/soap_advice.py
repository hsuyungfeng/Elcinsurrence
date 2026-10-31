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

_MARKDOWN_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_SOAP_SECTIONS = ("s", "o", "a", "p")
_MIN_SECTION_CHARS = 20
_MAX_SECTION_CHARS = 1500
_PASS_SCORE = 70
# 佔位符／未完成用語（大小寫不敏感）：代表模型未實際寫出內容。
_PLACEHOLDER_RE = re.compile(
    r"not documented|not recorded|pending|missing|placeholder|to be determined|\btbd\b|\bn/a\b|lorem|"
    r"xxx+|\[[^\]]*\]|待補|待填|未記載|未提供|尚未",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_ICD10_RE = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\b")


def validate_soap_quality(soap_dict: Any) -> dict[str, Any]:
    """檢核 LLM 產生的 recommended_soap 品質（確定性規則，不呼叫 LLM）。

    檢核項目：
    - 結構：S/O/A/P 四欄皆存在且為非空字串（缺漏即不通過）。
    - 佔位符：出現 pending／missing／not documented／[...] 等未完成用語（不通過）。
    - 長度：每欄至少 20 字元、至多 1500 字元（不通過）。
    - 語言：醫學英文主體，CJK 字元佔比須 ≤ 10%（不通過；中文應只出現在審批欄）。
    - 診斷碼：A 欄應含 ICD-10 形式代碼（缺漏僅扣分）。

    Returns:
        {"pass": bool, "quality_score": 0..100, "issues": [{"section", "code", "detail"}]}
        `pass` 為 True 須同時滿足無結構／佔位符／語言問題且分數 ≥ 70。
    """
    issues: list[dict[str, str]] = []
    score = 100
    if not isinstance(soap_dict, dict):
        return {"pass": False, "quality_score": 0, "issues": [{"section": "*", "code": "not_a_dict", "detail": "SOAP 非物件"}]}

    blocking = False
    for key in _SOAP_SECTIONS:
        raw = soap_dict.get(key)
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            issues.append({"section": key, "code": "missing", "detail": f"{key.upper()} 欄缺漏或為空"})
            score -= 25
            blocking = True
            continue
        if len(text) < _MIN_SECTION_CHARS:
            issues.append({"section": key, "code": "too_short", "detail": f"{key.upper()} 欄過短（<{_MIN_SECTION_CHARS} 字元）"})
            score -= 15
            blocking = True
        if len(text) > _MAX_SECTION_CHARS:
            issues.append({"section": key, "code": "too_long", "detail": f"{key.upper()} 欄過長（>{_MAX_SECTION_CHARS} 字元）"})
            score -= 10
        if _PLACEHOLDER_RE.search(text):
            issues.append({"section": key, "code": "placeholder", "detail": f"{key.upper()} 欄含佔位或未完成用語"})
            score -= 20
            blocking = True
        cjk = len(_CJK_RE.findall(text))
        if cjk / max(len(text.replace(" ", "")), 1) > 0.10:
            issues.append({"section": key, "code": "not_english", "detail": f"{key.upper()} 欄應為醫學英文，卻含大量中文"})
            score -= 15
            blocking = True
        if key == "a" and not _ICD10_RE.search(text):
            issues.append({"section": "a", "code": "no_icd10", "detail": "A 欄未見 ICD-10 代碼"})
            score -= 5

    score = max(0, min(100, score))
    return {"pass": (not blocking) and score >= _PASS_SCORE, "quality_score": score, "issues": issues}


_SYSTEM_PROMPT = (
    "You are an expert clinical documentation specialist and National Health Insurance (NHI) audit physician in Taiwan.\n"
    "Your mission: Produce a high-quality, professional, and fully fleshed-out outpatient SOAP progress note and NHI audit guidance for the target order code.\n\n"
    "CRITICAL CLINICAL TEMPLATE DIRECTIVE:\n"
    "- If the physician provides partial or empty preliminary SOAP, you MUST GENERATE A REALISTIC, GOLD-STANDARD CLINICAL SCENARIO TEMPLATE for the given order code and clinical context.\n"
    "- NEVER output generic meta-complaints or placeholders like 'data not documented', 'symptoms missing', 'ICD pending', 'prescription issued as per standard', or 'please verify'.\n"
    "- Instead, construct a complete, plausible outpatient case with standard Taiwan clinical phrasing, specific physical exam details, exact ICD-10 diagnostic codes, and concrete procedural/management steps that fully justify the medical necessity under NHI guidelines.\n\n"
    "CRITICAL BILINGUAL CONSTRAINTS:\n"
    "1. `recommended_soap` (S, O, A, P fields) MUST be written entirely in professional Medical English with standard clinical terminology and abbreviations used in Taiwan hospital/clinic EHR systems.\n"
    "   - S (Subjective): Realistic chief complaint, onset, mechanism of injury/illness, severity, and negative findings (e.g., denies loss of consciousness or visual changes).\n"
    "   - O (Objective): Realistic vitals, detailed anatomical physical exam (wound site, size in cm, depth, margin, active bleeding, nerve/vascular intactness, range of motion or specialized exams).\n"
    "   - A (Assessment): Definite primary ICD-10 clinical diagnosis code with description directly justifying the procedure/medication.\n"
    "   - P (Plan): Explicit procedural details (local anesthesia, wound irrigation, debridement, specific suture technique/layers, order code documentation), medications with dosage/frequency, post-op care, wound red flags, and follow-up timing.\n"
    "2. `comparison` and `approval_advice` MUST be written in Traditional Chinese (繁體中文，台灣健保審查語境), explaining the regulatory requirements, payment rules, documentation traps to avoid核減, and key items for the attending physician to verify before signing.\n\n"
    "Output ONLY a single valid JSON object in the following format (no extra text or markdown wrappers):\n"
    "{\n"
    '  "comparison": "病史與給付規則重點分析（以繁體中文說明適應症、給付限制、部位同側規範與佐證要求）",\n'
    '  "recommended_soap": {\n'
    '    "s": "Detailed clinical Subjective history in professional Medical English",\n'
    '    "o": "Detailed Objective physical examination and vital signs in professional Medical English",\n'
    '    "a": "Explicit ICD-10 diagnosis code and disease assessment in professional Medical English",\n'
    '    "p": "Comprehensive procedural, medication, and management plan in professional Medical English"\n'
    "  },\n"
    '  "approval_advice": "供主治醫師審批核可的具體審核要點與防核減注意事項（繁體中文）"\n'
    "}\n"
    + DATA_ISOLATION_NOTICE
)


def _parse_llm_json(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 嘗試抓取 ```json ... ``` 代碼塊
    md_match = _MARKDOWN_JSON_RE.search(cleaned)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 嘗試抓取最外層 JSON 物件
    match = _JSON_BLOCK_RE.search(cleaned)
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
    max_tokens: int = 1500,
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
