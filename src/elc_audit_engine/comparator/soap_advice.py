"""LLM SOAP 智慧補強與比對建議模組。

比對原始門診 SOAP 與雲端病歷/病史時間軸，產出具體的 SOAP 改進建議與醫師審批重點。
支援 Gemma 4 E4B（Q4_K_M / Q8_0）與 Qwen3.8-27B（禁用 thinking token，保證低延遲快速回應）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from elc_audit_engine.comparator.icd10_validator import validate_icd10_in_assessment
from elc_audit_engine.prompt_safety import DATA_ISOLATION_NOTICE, fence
from elc_audit_engine.rule_repository.mapping.llm_client import chat_completion

_MARKDOWN_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_SOAP_SECTIONS = ("s", "o", "a", "p")
_MIN_SECTION_CHARS = 20
_MAX_SECTION_CHARS = 500
# 範例病歷總長：目標 200–400 字元，硬上限 500（超過即不通過）。
_MIN_TOTAL_CHARS = 200
_MAX_TOTAL_CHARS = 500
# 品質檢核設定檔（Phase 33）：區分「短版預生成範例」與「真實長門診錄音 SOAP」。
_QUALITY_PROFILES: dict[str, dict[str, int]] = {
    "template": {
        "min_section": _MIN_SECTION_CHARS,
        "max_section": _MAX_SECTION_CHARS,
        "min_total": _MIN_TOTAL_CHARS,
        "max_total": _MAX_TOTAL_CHARS,
    },
    "clinical": {
        "min_section": _MIN_SECTION_CHARS,
        "max_section": 800,
        "min_total": _MIN_TOTAL_CHARS,
        "max_total": 2000,
    },
}
_PASS_SCORE = 70
# 佔位符／未完成用語（大小寫不敏感）：代表模型未實際寫出內容。
_PLACEHOLDER_RE = re.compile(
    r"not\s+(?:explicitly\s+|consistently\s+)?documented|not\s+recorded|pending|missing|placeholder|"
    r"to be determined|\btbd\b|\bn/a\b|lorem|xxx+|\[[^\]]*\]|待補|待填|未記載|未提供|尚未",
    re.IGNORECASE,
)
# Phase 36：clinical profile 兩步防繞過檢核：
# 第一步硬攔截「診斷／代碼／計畫／處置待定」等未完成語意（即使後面接檢驗詞如 "diagnosis pending ultrasound" 亦絕不豁免）
_BARE_DIAG_PENDING_RE = re.compile(
    r"\b(?:diagnosis|diagnoses|diagnostic|differential|ddx|dx|icd(?:\s*-?\s*10)?|"
    r"code|codes|assessment|impression|plan|treatment|problem)\s+pending\b",
    re.IGNORECASE,
)
# 第二步僅於第一步未命中時，剝離明確臨床檢驗／影像／病理／會診追蹤語境之 pending 片語
_CLINICAL_PENDING_ALLOWED_RE = re.compile(
    r"\bpending\s+(?:urinalysis|ua|lab(?:s|oratory)?|imaging|x-?ray|ultrasound|sonography|"
    r"ct|mri|ekg|ecg|culture|biopsy|pathology|results?|workup|evaluation|follow-?up|consult(?:ation)?|review)\b|"
    r"\b(?:urinalysis|ua|lab(?:s|oratory)?|imaging|x-?ray|ultrasound|sonography|"
    r"ct|mri|ekg|ecg|culture|biopsy|pathology|results?|workup)\s+pending\b",
    re.IGNORECASE,
)


def _has_placeholder(text: str, *, profile: str) -> bool:
    """依 profile 判定是否含佔位或未完成用語（template 嚴格禁止 pending；clinical 採兩步防繞過檢核）。"""
    if profile == "clinical":
        if _BARE_DIAG_PENDING_RE.search(text):
            return True
        scrubbed = _CLINICAL_PENDING_ALLOWED_RE.sub("", text)
        return bool(_PLACEHOLDER_RE.search(scrubbed))
    return bool(_PLACEHOLDER_RE.search(text))
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_ICD10_RE = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\b")


def validate_soap_quality(soap_dict: Any, *, profile: str = "template") -> dict[str, Any]:
    """檢核 LLM 產生的 recommended_soap 或門診草稿品質（確定性規則，不呼叫 LLM）。

    Args:
        soap_dict: 含 s/o/a/p 鍵的 dict。
        profile: ``"template"``（預設，短版預生成範例 200–500 字元）或
            ``"clinical"``（真實門診錄音／醫師審核草稿 200–2000 字元）。

    檢核項目：
    - 結構：S/O/A/P 四欄皆存在且為非空字串（缺漏即不通過）。
    - 佔位符：出現 pending／missing／not documented／[...] 等未完成用語（不通過）。
    - 長度：依 profile 驗證單欄與總字元上限（不通過）。
    - 語言：醫學英文主體，CJK 字元佔比須 ≤ 10%（不通過；中文應只出現在審批欄）。
    - 診斷碼：A 欄應含 ICD-10 形式代碼（缺漏僅扣分），並核對高風險語意誤碼（非阻斷警告）。

    Returns:
        {"pass": bool, "quality_score": 0..100, "issues": [{"section", "code", "detail"}]}
        `pass` 為 True 須同時滿足無結構／佔位符／語言問題且分數 ≥ 70。
    """
    if profile not in _QUALITY_PROFILES:
        raise ValueError(f"不支援的品質檢核 profile：{profile!r}（僅支援 {tuple(_QUALITY_PROFILES)}）")
    limits = _QUALITY_PROFILES[profile]

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
        if len(text) < limits["min_section"]:
            issues.append({"section": key, "code": "too_short", "detail": f"{key.upper()} 欄過短（<{limits['min_section']} 字元）"})
            score -= 15
            blocking = True
        if len(text) > limits["max_section"]:
            issues.append({"section": key, "code": "too_long", "detail": f"{key.upper()} 欄過長（>{limits['max_section']} 字元）"})
            score -= 10
        if _has_placeholder(text, profile=profile):
            issues.append({"section": key, "code": "placeholder", "detail": f"{key.upper()} 欄含佔位或未完成用語"})
            score -= 20
            blocking = True
        cjk = len(_CJK_RE.findall(text))
        if cjk / max(len(text.replace(" ", "")), 1) > 0.10:
            issues.append({"section": key, "code": "not_english", "detail": f"{key.upper()} 欄應為醫學英文，卻含大量中文"})
            score -= 15
            blocking = True
        if key == "a":
            if not _ICD10_RE.search(text):
                issues.append({"section": "a", "code": "no_icd10", "detail": "A 欄未見 ICD-10 代碼"})
                score -= 5
            else:
                for chk in validate_icd10_in_assessment(text):
                    if chk.warning:
                        issues.append({"section": "a", "code": "icd10_warning", "detail": f"{chk.code}: {chk.warning}"})
                        score -= 5

    total_chars = sum(len((soap_dict.get(k) or "").strip()) for k in _SOAP_SECTIONS)
    if total_chars < limits["min_total"]:
        issues.append({"section": "*", "code": "total_too_short", "detail": f"SOAP 總字元數過短（{total_chars} < {limits['min_total']}）"})
        score -= 20
        blocking = True
    elif total_chars > limits["max_total"]:
        issues.append({"section": "*", "code": "total_too_long", "detail": f"SOAP 總字元數過長（{total_chars} > {limits['max_total']}）"})
        score -= 20
        blocking = True

    score = max(0, min(100, score))
    return {"pass": (not blocking) and score >= _PASS_SCORE, "quality_score": score, "issues": issues}


_SYSTEM_PROMPT = (
    "You are an expert clinical documentation specialist and National Health Insurance (NHI) audit physician in Taiwan.\n"
    "Your mission: Produce a high-quality, professional, and fully fleshed-out outpatient SOAP progress note and NHI audit guidance for the target order code.\n\n"
    "CRITICAL CLINICAL TEMPLATE DIRECTIVE:\n"
    "- If the physician provides partial or empty preliminary SOAP, you MUST GENERATE A REALISTIC, GOLD-STANDARD CLINICAL SCENARIO TEMPLATE for the given order code and clinical context.\n"
    "- NEVER output generic meta-complaints or placeholders like 'data not documented', 'symptoms missing', 'ICD pending', 'prescription issued as per standard', or 'please verify'.\n"
    "- Instead, construct a complete, plausible outpatient case with standard Taiwan clinical phrasing, specific physical exam details, exact ICD-10 diagnostic codes, and concrete procedural/management steps that fully justify the medical necessity under NHI guidelines.\n\n"
    "CRITICAL CONCISENESS & LENGTH CONSTRAINT:\n"
    "- Total character length across S + O + A + P fields combined MUST BE BETWEEN 200 AND 400 CHARACTERS, and must NEVER exceed 500 CHARACTERS.\n"
    "- Keep clinical documentation focused, concise, and professional without redundant fluff, while strictly meeting Taiwan NHI audit guidelines.\n\n"
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


# ── 範例病歷範本（通用、長度受控）──────────────────────────────────
# 與 generate_soap_advice 不同：只輸出 SOAP JSON、逐欄字數上限、不含中文審批。
# 用於批次預生成；總長目標 200–380 字元（硬上限 500 由 validate_soap_quality 把關）。
_TEMPLATE_SYSTEM_PROMPT = (
    "You write concise English SOAP example templates for Taiwan NHI audit training.\n"
    "Output ONLY one JSON object with string keys: s, o, a, p. No markdown, no commentary.\n"
    "LENGTH (characters, counted per key):\n"
    "- s: 60 to 90, o: 80 to 110, a: 50 to 70, p: 100 to 150.\n"
    "- The four values together must be 240 to 380 characters (never below 200, never above 500).\n"
    "Style: telegraphic clinical English, no placeholders, no Chinese characters, no 'missing' or 'pending'.\n"
    "Content must be consistent with the rule text provided. Put an ICD-10 code in a ONLY if the rule text states one;\n"
    "never invent diagnosis codes or rule content."
)


def generate_template_soap(
    *,
    order_code: str,
    order_name: str,
    soap_text: str = "",
    patient_history: str = "",
    rule_text: str = "",
    max_tokens: int = 500,
) -> dict[str, Any]:
    """批次範本生成（長度受控）。回傳與 generate_soap_advice 相同形狀，供 pregen_template 使用。"""
    user_prompt = (
        f"Order code: {order_code}\n"
        f"Order name: {order_name}\n"
        f"Payment rule text (authoritative, do not contradict):\n{fence(rule_text or '(none)', 'rule')}\n\n"
        "Return the JSON object now."
    )
    try:
        resp = chat_completion(_TEMPLATE_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)
        parsed = _parse_llm_json(resp)
        if not parsed:
            return {"status": "error", "recommended_soap": {}, "raw_response": resp}
        soap = parsed.get("recommended_soap") if isinstance(parsed.get("recommended_soap"), dict) else parsed
        if not all(isinstance(soap.get(k), str) for k in ("s", "o", "a", "p")):
            return {"status": "error", "recommended_soap": {}, "raw_response": resp}
        return {"status": "success", "recommended_soap": {k: soap[k].strip() for k in ("s", "o", "a", "p")},
                "comparison": "", "approval_advice": "", "raw_response": resp}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "recommended_soap": {}}


_CONDENSE_SYSTEM_PROMPT = (
    "You condense an English SOAP example template.\n"
    "Output ONLY one JSON object with string keys: s, o, a, p. No markdown, no commentary.\n"
    "The four values together must be 240 to 380 characters. Keep the same clinical meaning, "
    "remove redundancy, keep telegraphic clinical English. Do not add new facts, codes, or Chinese text."
)


def _total_chars(soap: dict[str, str]) -> int:
    return sum(len(str(soap.get(k) or "").strip()) for k in ("s", "o", "a", "p"))


def generate_template_soap_condensed(**kwargs: Any) -> dict[str, Any]:
    """先以 generate_template_soap 生成；若總長超過 500 字，再請 LLM 壓縮一次（不新增事實）。"""
    result = generate_template_soap(**kwargs)
    if result.get("status") != "success":
        return result
    soap = result["recommended_soap"]
    if _total_chars(soap) <= _MAX_TOTAL_CHARS:
        return result
    try:
        resp = chat_completion(
            _CONDENSE_SYSTEM_PROMPT,
            "Condense this SOAP JSON:\n" + json.dumps(soap, ensure_ascii=False),
            max_tokens=400,
        )
        parsed = _parse_llm_json(resp)
        if parsed and all(isinstance(parsed.get(k), str) for k in ("s", "o", "a", "p")):
            condensed = {k: parsed[k].strip() for k in ("s", "o", "a", "p")}
            return {**result, "recommended_soap": condensed, "condensed": True}
    except Exception:
        pass
    return result


# ── 真實門診逐字稿轉 SOAP（Phase 33：clinical profile、嚴禁佔位句）──────────
_CLINICAL_TRANSCRIPT_SOAP_PROMPT = (
    "You are an expert clinical documentation specialist and Taiwan outpatient physician.\n"
    "Convert the provided outpatient doctor-patient consultation transcript into a structured outpatient SOAP note.\n\n"
    "HARD CONSTRAINTS:\n"
    "1. NEVER fabricate symptoms, exam findings, lab values, imaging results, diagnoses, or procedures not mentioned in the transcript.\n"
    "2. NEVER write placeholder or meta-commentary phrases such as 'not documented', 'not explicitly documented', "
    "'not recorded', 'pending', 'missing', 'N/A', 'TBD', or '[...]'. If vital signs or a specific exam were not mentioned, "
    "simply OMIT that sentence and state ONLY the physical maneuvers, visual/ultrasound observations, or prior reports actually discussed.\n"
    "3. `s`, `o`, `a`, `p` MUST be written entirely in professional Medical English (no Chinese characters). "
    "Keep each section concise and clinical (total across s+o+a+p between 300 and 1500 characters; each section 40 to 600 characters).\n"
    "4. `a` (Assessment) MUST include the exact ICD-10 code(s) justified by the consultation.\n"
    "5. `conversation_summary` MUST be written in Traditional Chinese (繁體中文，約 60–120 字).\n\n"
    "Output ONLY one valid JSON object (no markdown wrappers, no extra text):\n"
    "{\n"
    '  "s": "Medical English Subjective",\n'
    '  "o": "Medical English Objective (only actual observed/discussed findings, zero placeholder statements)",\n'
    '  "a": "Medical English Assessment with ICD-10 code(s)",\n'
    '  "p": "Medical English Plan",\n'
    '  "conversation_summary": "繁體中文對話摘要"\n'
    "}\n"
    + DATA_ISOLATION_NOTICE
)


_CLINICAL_SOAP_RETRY_PROMPT = (
    "You are an expert clinical documentation specialist and Taiwan outpatient physician.\n"
    "Revise the previous SOAP JSON to fix ONLY the specific quality issues listed below, "
    "strictly verifying every clinical fact against the original consultation transcript.\n\n"
    "HARD CONSTRAINTS:\n"
    "1. NEVER fabricate symptoms, exam findings, lab values, imaging results, diagnoses, or procedures "
    "not explicitly mentioned in the transcript.\n"
    "2. Remove all placeholder or meta-commentary phrases ('not documented', 'not recorded', 'pending', "
    "'missing', 'N/A', 'TBD', '[...]'). Simply omit unmentioned items instead.\n"
    "3. `s`, `o`, `a`, `p` MUST be entirely in professional Medical English (no Chinese characters), "
    "total length 300–1500 characters, each section 40–600 characters.\n"
    "4. `conversation_summary` MUST be written in Traditional Chinese (繁體中文，約 60–120 字).\n\n"
    "Output ONLY one valid JSON object with keys s, o, a, p, conversation_summary.\n"
    + DATA_ISOLATION_NOTICE
)

_CLINICAL_SUMMARY_BACKFILL_PROMPT = (
    "You are a Taiwan outpatient clinical documentation assistant.\n"
    "Write a concise Traditional Chinese (繁體中文) summary (60–120 characters) of the doctor-patient "
    "consultation transcript below.\n"
    "HARD CONSTRAINT: Include ONLY facts explicitly stated in the transcript. NEVER fabricate symptoms, "
    "diagnoses, lab values, or medications. Output plain Traditional Chinese text only (no JSON, no markdown).\n"
    + DATA_ISOLATION_NOTICE
)


def _retry_clinical_soap_once(
    cleaned_tr: str,
    prev_soap: dict[str, str],
    prev_quality: dict[str, Any],
    *,
    max_tokens: int,
) -> tuple[dict[str, str], str, dict[str, Any], str] | None:
    """針對未通過 clinical 品質檢核的 SOAP 進行最多 1 次定向修正（強制對照原始逐字稿）。"""
    issues_text = "\n".join(
        f"- [{it.get('section', '?')}] {it.get('code', '')}: {it.get('detail', '')}"
        for it in (prev_quality.get("issues") or [])
    )
    user_prompt = (
        "以下為原始門診逐字稿，請嚴格對照逐字稿修正下方 SOAP 品質問題（嚴禁捏造逐字稿未提及之事實）：\n"
        f"{fence(cleaned_tr[:18000], 'transcript')}\n\n"
        f"需修正之品質問題：\n{issues_text}\n\n"
        f"原 SOAP JSON：\n{fence(json.dumps(prev_soap, ensure_ascii=False), 'previous_soap')}"
    )
    try:
        resp = chat_completion(
            _CLINICAL_SOAP_RETRY_PROMPT,
            user_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        parsed = _parse_llm_json(resp)
        if not parsed or not all(isinstance(parsed.get(k), str) for k in _SOAP_SECTIONS):
            return None
        new_soap = {k: parsed[k].strip() for k in _SOAP_SECTIONS}
        new_quality = validate_soap_quality(new_soap, profile="clinical")
        improved = (
            (bool(new_quality.get("pass")) and not bool(prev_quality.get("pass")))
            or (int(new_quality.get("quality_score", 0)) > int(prev_quality.get("quality_score", 0)))
        )
        if not improved:
            return None
        new_summary = str(parsed.get("conversation_summary") or "").strip()
        return new_soap, new_summary, new_quality, resp
    except Exception:
        return None


def _backfill_summary_once(cleaned_tr: str) -> str:
    """當 SOAP 已合格但繁體中文摘要為空時，對照原始逐字稿進行最多 1 次輕量摘要補齊。"""
    user_prompt = (
        "請依據以下台灣門診醫病對話逐字稿，撰寫 60–120 字繁體中文摘要（嚴禁捏造未提及之事實）：\n"
        f"{fence(cleaned_tr[:18000], 'transcript')}"
    )
    try:
        resp = chat_completion(
            _CLINICAL_SUMMARY_BACKFILL_PROMPT,
            user_prompt,
            max_tokens=200,
            temperature=0.0,
        )
        text = (resp or "").strip().strip("`").strip()
        return text[:200]
    except Exception:
        return ""


def generate_clinical_soap_from_transcript(
    transcript: str,
    *,
    max_tokens: int = 1024,
    allow_retry: bool = True,
) -> dict[str, Any]:
    """將本機 ASR 轉錄之門診逐字稿轉換為結構化臨床 SOAP（並以 clinical profile 檢核）。"""
    cleaned_tr = (transcript or "").strip()
    if not cleaned_tr:
        return {
            "status": "error",
            "error": "逐字稿內容為空",
            "soap": {},
            "conversation_summary": "",
            "quality": validate_soap_quality({}, profile="clinical"),
            "icd10_checks": [],
            "retried": False,
            "summary_backfilled": False,
        }

    user_prompt = (
        "以下為台灣門診醫病對話逐字稿，請依規定產出結構化臨床 SOAP JSON：\n"
        f"{fence(cleaned_tr[:18000], 'transcript')}"
    )
    try:
        resp = chat_completion(
            _CLINICAL_TRANSCRIPT_SOAP_PROMPT,
            user_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        parsed = _parse_llm_json(resp)
        if not parsed or not all(isinstance(parsed.get(k), str) for k in _SOAP_SECTIONS):
            return {
                "status": "fallback",
                "soap": {},
                "conversation_summary": "",
                "raw_response": resp,
                "quality": validate_soap_quality({}, profile="clinical"),
                "icd10_checks": [],
                "retried": False,
                "summary_backfilled": False,
            }
        soap = {k: parsed[k].strip() for k in _SOAP_SECTIONS}
        summary = str(parsed.get("conversation_summary") or "").strip()
        quality = validate_soap_quality(soap, profile="clinical")
        retried = False
        summary_backfilled = False

        # 1. 品質未過關時，對照原始逐字稿執行最多 1 次定向修正
        if allow_retry and not bool(quality.get("pass")):
            retry_out = _retry_clinical_soap_once(cleaned_tr, soap, quality, max_tokens=max_tokens)
            if retry_out is not None:
                soap, retry_summary, quality, resp = retry_out
                if retry_summary:
                    summary = retry_summary
                retried = True

        # 2. SOAP 已合格但繁中摘要為空時，對照原始逐字稿執行最多 1 次輕量摘要補齊
        if allow_retry and bool(quality.get("pass")) and not summary:
            backfilled = _backfill_summary_once(cleaned_tr)
            if backfilled:
                summary = backfilled
                summary_backfilled = True

        icd_checks = [c.to_dict() for c in validate_icd10_in_assessment(soap["a"])]
        return {
            "status": "success",
            "soap": soap,
            "conversation_summary": summary,
            "quality": quality,
            "icd10_checks": icd_checks,
            "raw_response": resp,
            "retried": retried,
            "summary_backfilled": summary_backfilled,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"LLM 服務無法連線或判定逾時：{type(exc).__name__}",
            "soap": {},
            "conversation_summary": "",
            "quality": validate_soap_quality({}, profile="clinical"),
            "icd10_checks": [],
            "retried": False,
            "summary_backfilled": False,
        }
