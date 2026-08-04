"""Elcinsurrence Web Dashboard Backend API Server (Flask).

支援兩大核心獨立工作流：
1. 抽樣事前預審工作流 (/api/sampling/*)
   - 上傳 CSV 抽樣清單
   - 審核原有病歷並評估「醫令支持度」（充分/薄弱/裸奔）
   - 產出「病歷補強報告」供抽審送出前先補強

2. 核減事後申復工作流 (/api/appeal/*)
   - 導入核減明細 (刪減醫令)
   - 啟動針對刪減醫令之多源證據補強（整合門診 SOAP、檢驗、影像、雲端病歷）
   - 生成 4 段式申復理由草稿 (≤2000字) 與申復 XML 欄位
"""

import os

from flask import Flask, jsonify, request, send_from_directory

from elc_audit_engine.generators import build_appeal_draft
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.models import (
    DeductionRecord,
    OrderRecord,
    SubmissionCase,
)
from elc_audit_engine.pipeline import run_presubmission_check
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

app = Flask(__name__, static_folder='static')

# 入參長度上限（P1-5：端點原本零校驗）。SOAP 全文取 10KB，
# 其餘識別欄位取短上限——正常值都是代碼/流水號等級的長度。
_MAX_SOAP_CHARS = 10_000
_MAX_FIELD_CHARS = 200


class ApiError(Exception):
    """可安全回傳給前端的錯誤（訊息不含內部細節）。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def _handle_api_error(exc: ApiError):
    return jsonify({"status": "error", "message": exc.message}), exc.status


@app.errorhandler(Exception)
def _handle_unexpected(exc: Exception):
    """統一脫敏：不把 traceback／內部路徑回給前端（P0-1 debug 回顯）。"""
    app.logger.exception("unhandled error: %s", exc)
    return jsonify({"status": "error", "message": "伺服器內部錯誤，請聯繫系統管理員"}), 500


def _clean_str(data: dict, key: str, *, required: bool = False, max_len: int = _MAX_FIELD_CHARS) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ApiError(f"欄位 {key} 必須為字串")
    value = value.strip()
    if required and not value:
        raise ApiError(f"缺少必要欄位 {key}")
    if len(value) > max_len:
        raise ApiError(f"欄位 {key} 超過長度上限（{max_len} 字）")
    return value


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ==============================================================================
# 1. 抽樣事前預審 API
# ==============================================================================
@app.route('/api/sampling/cases', methods=['GET'])
def get_sampling_cases():
    """回傳門診抽樣事前預審案例"""
    return jsonify([
        {
            "id": "SAMP-001",
            "case_seq": "101",
            "record_no": "M1001",
            "patient_name": "林聰明",
            "order_code": "14050B",
            "order_name": "糖化血色素檢驗 HbA1c",
            "visit_date": "115/07/10",
            "clinic": "家醫科",
            "support_level": "薄弱",
            "verdict": "部分支持",
            "soap": "S: 糖尿病追蹤，無發燒不適。\nO: BP 120/80\nA: DM Type 2\nP: 開立 HbA1c 抽血追蹤",
            "missing_reason": "病歷 SOAP A 欄僅記載簡寫 DM，未附上近三次血糖趨勢與檢驗必要性說明。"
        },
        {
            "id": "SAMP-002",
            "case_seq": "102",
            "record_no": "M1002",
            "patient_name": "黃淑芬",
            "order_code": "33084B",
            "order_name": "胸部 X 光攝影 (單視角)",
            "visit_date": "115/07/12",
            "clinic": "胸腔內科",
            "support_level": "充分",
            "verdict": "支持",
            "soap": "S: 咳嗽持續超過兩週，伴隨發燒與黃痰。\nO: Breathing sound: Right lower lung crackles (+), Temp 38.5C\nA: Suspected Pneumonia\nP: Order CXR (Single view)",
            "missing_reason": "病歷完整記載發燒、聽診囉音與臨床適應症，符合預審強支持標準。"
        }
    ])


@app.route('/api/sampling/audit', methods=['POST'])
def audit_sampling_case():
    """執行事前預審支持度評估與病歷補強建議（接 run_presubmission_check）。

    本端點呼叫真實引擎（Phase 5 三方比對）：查規則庫 → LLM 逐檢核項判定
    → 三級分類 → 缺口候選補強。原實作以硬編碼關鍵字 if/else 假判定，
    看似可用但結論全屬虛構（P0-1），已移除。

    注意：LLM 判定需 llama.cpp 服務可用；判定失敗時回傳
    support_level=null（待判定），呼叫端不得顯示為「裸奔」（P1-1）。
    """
    data = request.json or {}
    if not isinstance(data, dict):
        raise ApiError("請求主體必須為 JSON 物件")

    order_code = _clean_str(data, 'order_code', required=True)
    order_name = _clean_str(data, 'order_name')
    soap_text = _clean_str(data, 'soap_text', max_len=_MAX_SOAP_CHARS)
    record_no = _clean_str(data, 'record_no')

    case = SubmissionCase(
        record_no=record_no,
        orders=(OrderRecord(code=order_code),),
    )
    # 用 Phase 3 真實解析器分段（marker/keyword 兩層＋信度），不自行組模型
    soap_doc = parse_soap_text(soap_text) if soap_text else None

    try:
        result = run_presubmission_check(case, soap_doc, None)
    except RuleRepositoryError as exc:
        # D-06/P0-2：規則庫故障不得偽裝成「查無規則」或「裸奔」。
        app.logger.error("rule repository failure during presubmission: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)

    judgments = result.comparison.order_judgments
    if not judgments:
        raise ApiError("無有效醫令可預審")
    oj = judgments[0]

    if not oj.rule_found:
        advice = "查無此醫令的規則依據，建議人工查核後再送件。"
    elif oj.support_level is None:
        advice = "系統未能完成判定（判定服務異常），請人工複核後再送件。"
    elif oj.narratives:
        advice = "\n".join(f"- {n.text}" for n in oj.narratives)
    else:
        advice = "病歷記載足以支撐本醫令，可逕行送出抽審。"

    return jsonify({
        "status": "success",
        "order_code": order_code,
        "order_name": order_name,
        # support_level=null 代表「待判定」（系統未能判定），前端須與
        # 「裸奔」分開呈現——兩者意義完全不同（P1-1）。
        "support_level": oj.support_level,
        "rule_found": oj.rule_found,
        "undetermined": oj.support_level is None and oj.rule_found,
        "verdict": oj.judgment.verdict if oj.judgment else None,
        "quote": oj.judgment.quote if oj.judgment else "",
        "rule_location": oj.check_item.rule_location if oj.check_item else None,
        "reinforcement_advice": advice,
        "candidates": [
            {
                "text": n.text,
                "rule_location": n.rule_location,
                "prompt_only": n.prompt_only,
            }
            for n in oj.narratives
        ],
        "records_degraded": result.comparison.records_degraded,
    })


# ==============================================================================
# 2. 核減事後申復 API (多源證據補強: 影像/檢驗/雲端病歷)
# ==============================================================================
@app.route('/api/appeal/cases', methods=['GET'])
def get_appeal_cases():
    """回傳核減需申復案件清單 (多源證據已載入)"""
    return jsonify([
        {
            "id": "APP-001",
            "case_seq": "201",
            "record_no": "M2001",
            "patient_name": "王大明",
            "order_code": "64140C",
            "order_name": "手腕韌帶縫合術",
            "deduct_amount": 3200,
            "deduction_reason": "病歷未載明肌腱撕裂之影像是項與術前評估",
            "visit_date": "115/06/20",
            "soap": "S: 右手腕外傷挫傷後劇痛。\nO: 局部壓痛腫脹，活動受限。\nA: Wrist injury\nP: Schedule surgery.",
            "multisource_evidence": {
                "labs": [
                    {"date": "2026-06-20", "name": "CBC/WBC", "result": "11,500 /uL (異常偏高)", "unit": "/uL"}
                ],
                "images": [
                    {"date": "2026-06-20", "name": "Wrist MRI", "report": "Complete tear of TFCC ligament (三角纖維軟骨複合體完全撕裂)", "dicom_id": "DICOM-9982"}
                ],
                "cloud_sync": [
                    {"date": "2026-05-15", "source": "健保雲端跨院病歷", "note": "外院 X 光顯示右腕關節腔狹窄與不穩定"}
                ]
            }
        },
        {
            "id": "APP-002",
            "case_seq": "202",
            "record_no": "M2002",
            "patient_name": "張美玲",
            "order_code": "14050B",
            "order_name": "糖化血色素檢驗 HbA1c",
            "deduct_amount": 150,
            "deduction_reason": "費用申報與上一次檢驗間隔未滿3個月",
            "visit_date": "115/07/01",
            "soap": "S: 門診追蹤 DM。\nO: FPG 168\nA: DM control poor\nP: Adjust insulin, recheck HbA1c",
            "multisource_evidence": {
                "labs": [
                    {"date": "2026-07-01", "name": "HbA1c", "result": "9.1 %", "unit": "%"}
                ],
                "images": [],
                "cloud_sync": [
                    {"date": "2026-03-25", "source": "本院歷程", "note": "上次 HbA1c 檢驗日為 2026-03-25 (間隔已達 97 天，符合健保規定)"}
                ]
            }
        }
    ])


@app.route('/api/appeal/generate', methods=['POST'])
def generate_appeal_draft():
    """生成 D10 四段式申復理由草稿（接 build_appeal_draft）。

    原實作以模板字串拼接四段，其中「規則依據」段是把醫令碼代入一句固定
    句型——等於為任何醫令捏造法規依據；字數檢查也用了錯誤的「合計 2000」
    而非官方問答集 Q15 的「p8/p9 各 ≤1000」（P0-1）。現改為呼叫核心
    產生器，規則全文一律來自規則庫 get_rule，查無則誠實標示查無。
    """
    data = request.json or {}
    if not isinstance(data, dict):
        raise ApiError("請求主體必須為 JSON 物件")

    case_seq = _clean_str(data, 'case_seq', required=True)
    order_code = _clean_str(data, 'order_code', required=True)
    deduction_reason = _clean_str(data, 'deduction_reason', max_len=_MAX_SOAP_CHARS)
    record_no = _clean_str(data, 'record_no')

    is_appealing = data.get('is_appealing', True)
    if not isinstance(is_appealing, bool):
        raise ApiError("欄位 is_appealing 必須為布林值")

    def _opt_int(key: str) -> int | None:
        value = data.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(f"欄位 {key} 必須為整數")
        if value < 0:
            raise ApiError(f"欄位 {key} 不得為負數")
        return value

    # D-15：申復點數不得超過不予核銷金額，由 build_appeal_draft 硬檢查。
    deduct_amount = _opt_int('deduct_amount')
    claimed_points = _opt_int('claimed_points')

    record = DeductionRecord(
        case_seq=case_seq,
        order_code=order_code,
        deduction_reason=deduction_reason or None,
        non_reimbursed_amount=deduct_amount,
    )

    # 規則全文一律取自規則庫，不得自行拼造（原實作的核心問題）。
    rule_text = rule_location = None
    try:
        rule = get_rule(order_code)
    except RuleRepositoryError as exc:
        app.logger.error("rule repository failure during appeal: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)
    if rule.found:
        rule_text = rule.article_full_text or rule.payment_text
        rule_location = rule.article_location

    # 醫師採用的補強敘述（Phase 6 審核軌跡），前端未提供時為空。
    evidence = data.get('evidence', [])
    if isinstance(evidence, list):
        evidence = [e for e in evidence if isinstance(e, str)]
    else:
        evidence = []

    draft = build_appeal_draft(
        record,
        is_appealing=is_appealing,
        claimed_points=claimed_points,
        rule_text=rule_text,
        rule_location=rule_location,
        evidence=evidence,
        has_attachment=bool(data.get('has_attachment', False)),
    )

    return jsonify({
        "status": "success",
        "case_seq": draft.case_seq,
        "order_code": draft.order_code,
        "record_no": record_no,
        "appeal_sections": [
            {"key": s.key, "title": s.title, "text": s.text} for s in draft.sections
        ],
        "reason1": draft.reason1,
        "reason2": draft.reason2,
        "p6_points": draft.p6_points,
        "total_char_count": draft.total_chars,
        "rule_found": rule.found,
        # 官方問答集 Q15：p8/p9 各 ≤1000（不是合計 2000）。
        "xml_p8_p9_valid": (
            len(draft.reason1) <= 1000 and len(draft.reason2) <= 1000
        ),
        "over_limit": draft.over_limit,
        "validation_errors": list(draft.validation_errors),
    })


if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    # 安全預設（P0-1）：綁定 127.0.0.1、debug 關閉。
    # 原設定 host='0.0.0.0' + debug=True 等於無認證對全網卡開放，且
    # 例外會回顯堆疊；本服務會接觸病歷資料，不得如此。
    # 需對外提供時請置於反向代理／VPN 後，並以環境變數覆寫：
    #   ELC_SERVER_HOST=0.0.0.0 ELC_SERVER_PORT=5000 python server.py
    host = os.getenv('ELC_SERVER_HOST', '127.0.0.1')
    port = int(os.getenv('ELC_SERVER_PORT', '5000'))
    debug = os.getenv('ELC_SERVER_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
