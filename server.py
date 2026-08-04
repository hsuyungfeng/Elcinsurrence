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

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from elc_audit_engine.generators import build_appeal_draft
from elc_audit_engine.ingest import (
    MediaExtractError,
    SamplingImportError,
    detect_media_type,
    extract_text,
    parse_image_tables,
    parse_pdf_tables,
    parse_sampling_csv,
    parse_sampling_ocr_text,
)
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.deduction import DeductionFileError, parse_deduction_file
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


class UploadFileError(Exception):
    """上傳檔案不合法（副檔名／大小）。"""


@app.errorhandler(ApiError)
def _handle_api_error(exc: ApiError):
    return jsonify({"status": "error", "message": exc.message}), exc.status


@app.errorhandler(UploadFileError)
def _handle_upload_error(exc: UploadFileError):
    return jsonify({"status": "error", "message": str(exc)}), 400


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


# ==============================================================================
# 批次匯入（CSV / PDF / JPEG 影像）— 2026-08-04 新增
# ==============================================================================
_UPLOAD_DIR = os.path.join("data", "uploads")
_RAW_DIR = os.path.join(_UPLOAD_DIR, "raw")
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTS = {".csv", ".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

# 導入後案件清單（None＝尚未導入，回傳示範資料）。落盤於 data/uploads/*.json，
# server 啟動時載入最新一份，重啟不丟失。
_sampling_cases: list[dict] | None = None
_appeal_cases: list[dict] | None = None


def _save_upload(file_storage) -> tuple[str, str]:
    """儲存上傳檔到 data/uploads/raw/（uuid 檔名，防路徑穿越 P1-3）。

    Returns:
        (儲存路徑, 原始檔名)。
    """
    filename = (file_storage.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise UploadFileError(f"不支援的檔案類型: {ext or '(無副檔名)'}（支援 CSV / PDF / JPEG 等）")
    os.makedirs(_RAW_DIR, exist_ok=True)
    dest = os.path.join(_RAW_DIR, f"{uuid.uuid4().hex}{ext}")
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = file_storage.stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                out.close()
                os.remove(dest)
                raise UploadFileError("檔案超過 10MB 上限")
            out.write(chunk)
    return dest, filename


def _save_cases_json(kind: str, cases: list[dict]) -> str:
    """把導入的案件清單落盤 data/uploads/{kind}_{timestamp}.json。"""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_UPLOAD_DIR, f"{kind}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    return path


def _load_latest_cases(kind: str) -> list[dict] | None:
    """載入最新一份導入清單；無檔案或損毀回 None（回退示範資料）。"""
    files = sorted(Path(_UPLOAD_DIR).glob(f"{kind}_*.json"))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


_sampling_cases = _load_latest_cases("sampling")
_appeal_cases = _load_latest_cases("appeal")


def _to_sampling_case(idx: int, rec) -> dict:
    """SamplingCaseRecord → 前端列表契約 dict。"""
    return {
        "id": f"SAMP-{idx:04d}",
        "demo": False,
        "case_seq": rec.case_seq or str(idx),
        "record_no": rec.record_no,
        "patient_name": rec.patient_name,
        "order_code": rec.order_code,
        "order_name": rec.order_name,
        "visit_date": rec.visit_date,
        "clinic": rec.clinic,
        "soap": rec.soap_text or "",
        "support_level": None,
        "missing_reason": None,
        "source": rec.source,
        "ocr_line": rec.ocr_line,
    }


def _to_appeal_case(idx: int, rec) -> dict:
    """DeductionRecord → 前端列表契約 dict（醫令名稱以規則庫為準）。"""
    name = None
    try:
        rule = get_rule(rec.order_code or "")
        if rule.found:
            name = rule.name
    except RuleRepositoryError:
        pass  # 名稱缺失不阻斷導入，前端以代碼顯示
    return {
        "id": f"APP-{idx:04d}",
        "demo": False,
        "case_seq": rec.case_seq or str(idx),
        "record_no": None,
        "patient_name": None,
        "order_code": rec.order_code,
        "order_name": name or rec.order_code,
        "deduct_amount": rec.non_reimbursed_amount,
        "deduction_reason": rec.deduction_reason or rec.institution_note or "",
        "visit_date": rec.visit_date,
        "soap": "",
        "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
        "source": "csv",
    }


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ==============================================================================
# 1. 抽樣事前預審 API
# ==============================================================================
@app.route('/api/sampling/cases', methods=['GET'])
def get_sampling_cases():
    """回傳門診抽樣事前預審案例（示範資料）。

    demo=true：無真實資料源（CSV 匯入）前的 UI 展示用；
    support_level 欄位僅為版面初始值，判定一律以 /api/sampling/audit
    引擎結果為準（前端已不直接顯示此欄位，P1-1/P0-1 教訓）。
    已有導入清單（POST /api/sampling/import）時優先回傳導入資料。
    """
    if _sampling_cases is not None:
        return jsonify(_sampling_cases)
    return jsonify([
        {
            "id": "SAMP-001",
            "demo": True,
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
            "demo": True,
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


@app.route('/api/sampling/import', methods=['POST'])
def import_sampling_cases():
    """批次匯入抽樣清單：CSV（digital）／PDF／JPEG 影像（paper→OCR）。

    CSV 走自訂欄位契約（ingest.sampling，2026-08-04 使用者裁示）；PDF／影像
    經本機系統工具（pdftotext/pdftoppm/tesseract，D2 不出本機）提取文字後
    以 OCR 行解析——僅結構化醫令代碼＋名稱，其餘欄位留空供前端人工補齊
    （誠實降級：OCR 猜欄位比留空更危險）。匯入成功後覆蓋案例清單並落盤。
    """
    global _sampling_cases
    file = request.files.get('file')
    if file is None or not (file.filename or '').strip():
        raise ApiError('缺少上傳檔案（multipart 欄位名 file）')
    try:
        path, filename = _save_upload(file)
    except UploadFileError as exc:
        raise ApiError(str(exc))

    try:
        media_type = detect_media_type(filename)
        if media_type == 'csv':
            with open(path, 'rb') as f:
                result = parse_sampling_csv(f.read())
            source = 'csv'
        else:
            # 紙本（PDF/影像）：優先 PP-StructureV3 表格結構化（欄位級），
            # 引擎不可用／無表格時降級 tesseract 全文 OCR → 醫令代碼行解析。
            if media_type == 'pdf':
                text, tool = extract_text(path, media_type=media_type)
                result = parse_sampling_ocr_text(text)
                source = 'ocr'
                if tool != 'pdftotext':  # 掃描型 PDF（無文字層）→ 再試表格結構化
                    t_result = parse_pdf_tables(path)
                    if t_result is not None:
                        result = t_result
                        source = 'paddle'
            else:
                t_result = parse_image_tables(path)
                if t_result is not None:
                    result = t_result
                    source = 'paddle'
                else:
                    text, _tool = extract_text(path, media_type=media_type)
                    result = parse_sampling_ocr_text(text)
                    source = 'ocr'
    except (MediaExtractError, SamplingImportError) as exc:
        app.logger.warning('sampling import failed: %s', exc)
        raise ApiError(f'匯入失敗：{exc}')
    finally:
        os.remove(path)  # 暫存檔即時清除（PHI 最小化）

    cases = [
        _to_sampling_case(i, rec) for i, rec in enumerate(result.records, start=1)
    ]
    rejected = [
        {'row': r.row_number, 'reason': r.reason, 'raw': list(r.raw)}
        for r in result.rejected
    ]

    if not cases:
        return jsonify({
            'status': 'error',
            'media_type': media_type,
            'imported': 0,
            'rejected': len(rejected),
            'rejected_rows': rejected,
            'message': (
                '未匯入任何案件：找不到可識別的醫令代碼（OCR 品質不足，'
                '請改以 CSV 匯出後上傳）。'
                if source == 'ocr'
                else '未匯入任何案件（請檢查 CSV 欄位契約：需含「醫令代碼」）。'
            ),
        }), 400

    saved = _save_cases_json('sampling', cases)
    _sampling_cases = cases
    return jsonify({
        'status': 'success',
        'media_type': media_type,
        'source': source,
        'imported': len(cases),
        'rejected': len(rejected),
        'rejected_rows': rejected,
        'saved_to': saved,
    })


# ==============================================================================
# 2. 核減事後申復 API (多源證據補強: 影像/檢驗/雲端病歷)
# ==============================================================================
@app.route('/api/appeal/cases', methods=['GET'])
def get_appeal_cases():
    """回傳核減需申復案件清單 (示範資料，多源證據已載入)。

    demo=true：無真實資料源（核減明細 CSV 匯入）前的 UI 展示用。
    醫令名稱一律以規則庫為準（64140C＝甲床與手指重建術；原示範資料
    誤標為「手腕韌帶縫合術」，progress.md 2026-08-04 已記錄此教訓）。
    已有導入清單（POST /api/appeal/import）時優先回傳導入資料。
    """
    if _appeal_cases is not None:
        return jsonify(_appeal_cases)
    return jsonify([
        {
            "id": "APP-001",
            "demo": True,
            "case_seq": "201",
            "record_no": "M2001",
            "patient_name": "王大明",
            "order_code": "64140C",
            "order_name": "甲床與手指重建術",
            "deduct_amount": 3200,
            "deduction_reason": "病歷未記載甲床損傷範圍與術前影像評估",
            "visit_date": "115/06/20",
            "soap": "S: 右手食指重物壓砸傷後劇痛出血。\nO: 食指末端甲床撕裂，指甲剝離。\nA: Nail bed injury\nP: Schedule nail bed repair surgery.",
            "multisource_evidence": {
                "labs": [
                    {"date": "2026-06-20", "name": "CBC/WBC", "result": "11,500 /uL (異常偏高)", "unit": "/uL"}
                ],
                "images": [
                    {"date": "2026-06-20", "name": "Finger X-ray", "report": "Distal phalanx fracture with nail bed defect (遠端指骨骨折併甲床缺損)", "dicom_id": "DICOM-9982"}
                ],
                "cloud_sync": [
                    {"date": "2026-05-15", "source": "健保雲端跨院病歷", "note": "外院 X 光顯示右食指遠端指骨骨折"}
                ]
            }
        },
        {
            "id": "APP-002",
            "demo": True,
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


@app.route('/api/appeal/import', methods=['POST'])
def import_appeal_cases():
    """批次匯入核減刪減醫令清單。

    CSV：走 D-14d 18 欄 parser（parse_deduction_file）。
    PDF／影像（紙本）：**誠實降級**——18 欄結構無法由 OCR 可靠重建，提取
    文字供參考並提示改用 CSV；不自動產生可能錯誤的記錄（P0-1 教訓：
    錯誤的資料比沒有資料更危險）。
    """
    global _appeal_cases
    file = request.files.get('file')
    if file is None or not (file.filename or '').strip():
        raise ApiError('缺少上傳檔案（multipart 欄位名 file）')
    try:
        path, filename = _save_upload(file)
    except UploadFileError as exc:
        raise ApiError(str(exc))

    try:
        media_type = detect_media_type(filename)
        if media_type != 'csv':
            text, tool = extract_text(path, media_type=media_type)
            return jsonify({
                'status': 'partial',
                'media_type': media_type,
                'tool': tool,
                'imported': 0,
                'message': (
                    '紙本核減清單（PDF／影像）無法自動結構化為 18 欄，'
                    '請以 CSV 匯出後上傳，或改用逐筆新增。'
                ),
                'extracted_text_preview': text[:500],
            })
        result = parse_deduction_file(path)
    except (MediaExtractError, DeductionFileError) as exc:
        app.logger.warning('appeal import failed: %s', exc)
        raise ApiError(f'匯入失敗：{exc}')
    finally:
        if os.path.exists(path):
            os.remove(path)  # 暫存檔即時清除（PHI 最小化）

    cases = [_to_appeal_case(i, rec) for i, rec in enumerate(result.records, start=1)]
    rejected = [
        {'row': r.row_number, 'reason': r.reason, 'raw': list(r.raw)}
        for r in result.rejected
    ]
    if not cases:
        return jsonify({
            'status': 'error',
            'media_type': 'csv',
            'imported': 0,
            'rejected': len(rejected),
            'rejected_rows': rejected,
            'message': '未匯入任何案件（請檢查核減明細欄位數是否為 18 欄）。',
        }), 400

    saved = _save_cases_json('appeal', cases)
    _appeal_cases = cases
    return jsonify({
        'status': 'success',
        'media_type': 'csv',
        'source': 'csv',
        'imported': len(cases),
        'rejected': len(rejected),
        'rejected_rows': rejected,
        'saved_to': saved,
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
