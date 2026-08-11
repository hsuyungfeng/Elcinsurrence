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

from flask import Flask, g, jsonify, request, send_from_directory

from config import settings
from elc_audit_engine.record_aggregator import (
    LocalFileProvider,
    PatientTimeline,
    build_timeline,
)
from elc_audit_engine.auth import (
    API_KEY_HEADER,
    AuthConfigError,
    AuthenticationError,
    load_api_keys,
    require_api_key,
    resolve_caller,
)
from elc_audit_engine.audit_log import record_access
from elc_audit_engine.case_store import (
    CaseNotFoundError,
    CaseStore,
    DuplicateCaseError,
    IllegalTransitionError,
)
from elc_audit_engine.generators import build_appeal_draft, render_appeal_json
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

from elc_audit_engine import attachment_store
from elc_audit_engine.attachment_store import AttachmentStoreError, InvalidAttachmentError

app = Flask(__name__, static_folder='static')

# 入參長度上限（P1-5：端點原本零校驗）。SOAP 全文取 10KB，
# 其餘識別欄位取短上限——正常值都是代碼/流水號等級的長度。
_MAX_SOAP_CHARS = 10_000
_MAX_FIELD_CHARS = 200

# 審計豁免清單：靜態頁與健康檢查不含病歷存取，記錄會被探測流量淹沒。
# 這份清單只決定「寫不寫審計」，與是否強制認證無關——業務端點即使
# 免強制 API Key，仍接觸病歷資料，審計軌跡不可因此消失。
_AUDIT_EXEMPT_ENDPOINTS = frozenset({"index", "health", "static"})

# 認證豁免清單：依使用者裁示，目前所有業務端點直接開放供 HIS 對接，
# 不強制 API Key。**僅決定認證是否強制，不得沿用來判斷審計**——
# 兩份清單刻意分開（歷史教訓：曾共用一份清單，導致免認證的業務端點
# 連審計日誌都被一併跳過，違反「認證可選、審計必留」的設計）。
_AUTH_EXEMPT_ENDPOINTS = _AUDIT_EXEMPT_ENDPOINTS | frozenset({
    "get_sampling_cases",
    "audit_sampling_case",
    "import_sampling_cases",
    "get_appeal_cases",
    "generate_appeal_draft",
    "import_appeal_cases",
    "upload_appeal_attachment",
    "get_appeal_attachments",
    "delete_appeal_attachment",
    "generate_deduction_print",
})


def _init_api_keys(flask_app) -> None:
    """啟動期載入 ELC_API_KEYS 並注入 app.config（fail-fast，不降級）。

    正常路徑：AuthConfigError 直接重新拋出，服務啟動即失敗——本服務
    會接觸病歷資料，設定缺失／格式錯誤時繼續啟動等同於「無認證對外
    開放」，比啟動失敗更危險。

    測試環境相容：僅在環境變數 ELC_ALLOW_NO_AUTH_FOR_TESTS == "1" 時
    允許以空 dict 啟動（並大聲警告）。**此旗標只准測試使用**——
    正式環境設定此旗標等同於關閉認證，絕不可用於生產部署。
    """
    try:
        flask_app.config["ELC_API_KEYS"] = load_api_keys()
    except AuthConfigError:
        if os.environ.get("ELC_ALLOW_NO_AUTH_FOR_TESTS") == "1":
            flask_app.logger.warning(
                "ELC_ALLOW_NO_AUTH_FOR_TESTS=1：以空 API key 表啟動（僅限測試環境！"
                "正式環境設定此旗標等同於關閉認證，絕不可用於生產部署）"
            )
            flask_app.config["ELC_API_KEYS"] = {}
        else:
            raise


_init_api_keys(app)


class ApiError(Exception):
    """可安全回傳給前端的錯誤（訊息不含內部細節）。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class UploadFileError(Exception):
    """上傳檔案不合法（副檔名／大小）。"""


#: P1-5 縱深防禦：即使前端某處遺漏轉義，CSP 也擋掉外部腳本與資料外送。
#  外鏈字型已移除（D2 個資不出本機），故 default-src 收斂到 'self'。
#  inline style/script 暫留 'unsafe-inline'——頁面目前為單檔 inline 樣板，
#  待拆出外部 .css/.js 後可移除此例外。
_CSP = "; ".join(
    (
        "default-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    )
)


@app.before_request
def _enforce_api_key():
    """Phase 9-01：統一強制 X-API-Key 認證（豁免需顯式列入白名單）。

    採 before_request 而非逐一端點 decorator：**新增端點時預設受保護**，
    避免「忘記加 decorator 就等於裸奔」的失敗模式——豁免必須顯式列入
    `_AUTH_EXEMPT_ENDPOINTS`，而非預設放行。`require_api_key` decorator
    仍保留供未來 blueprint 使用。
    """
    if request.endpoint in _AUTH_EXEMPT_ENDPOINTS:
        # 免強制認證，但若呼叫方仍帶了合法 key，順便解析 caller_id，
        # 讓審計日誌不必然落成 anonymous（key 錯誤或缺失則靜默忽略，
        # 因為這裡不強制擋，錯誤 key 也不該是 401 的理由）。
        presented_key = request.headers.get(API_KEY_HEADER)
        if presented_key:
            try:
                g.caller_id = resolve_caller(presented_key, app.config["ELC_API_KEYS"])
            except AuthenticationError:
                pass
        return None
    if request.endpoint is None:
        # 未匹配任何路由（404），交給 Flask 內建處理，不在此攔截。
        return None
    presented_key = request.headers.get(API_KEY_HEADER)
    keys = app.config["ELC_API_KEYS"]
    g.caller_id = resolve_caller(presented_key, keys)
    return None


@app.after_request
def _security_headers(response):
    """統一補安全標頭（P1-5）。"""
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.after_request
def _record_access_audit(response):
    """Phase 9-01：受保護端點每次呼叫留下無 PHI 審計列。

    只在非豁免端點記錄——靜態頁與健康檢查不含病歷存取，記錄會被
    探測流量淹沒。審計寫檔失敗不得讓已完成的業務回應變成 500，但
    必須在 application log 留痕（不靜默無痕）。
    不得把 request.json／request.form 內容放進 detail（PHI 風險）。
    """
    if request.endpoint not in _AUDIT_EXEMPT_ENDPOINTS:
        try:
            record_access(
                caller_id=getattr(g, "caller_id", "anonymous"),
                method=request.method,
                path=request.path,
                status=response.status_code,
            )
        except OSError as exc:
            app.logger.error("寫入審計日誌失敗，但業務回應照常回傳：%s", exc)
    return response


@app.errorhandler(AuthenticationError)
def _handle_authentication_error(exc: AuthenticationError):
    """認證失敗一律回 401，且必須與「查無資料」可區分（P0-2／P1-1 同源原則）。"""
    return jsonify({"status": "error", "message": exc.message}), 401


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

_case_store = CaseStore()


def _persist_cases(kind: str, cases: list[dict], actor: str | None) -> tuple[int, list[str]]:
    """將解析後的案件逐筆持久化至 CaseStore (state=imported)。

    重複的 case_id 會被記錄在 conflicts 清單中並被拒絕建案，
    但其餘非重複案件仍會正常建案。非 DuplicateCaseError (如 UnsafeIdentifierError)
    則不捕捉，直接向上傳播。
    """
    persisted = 0
    conflicts: list[str] = []
    for case in cases:
        try:
            _case_store.create(
                case_id=case["id"],
                kind=kind,
                case_seq=case.get("case_seq"),
                order_code=case.get("order_code"),
                payload=case,
                actor=actor,
            )
            persisted += 1
        except DuplicateCaseError:
            conflicts.append(case["id"])
    return persisted, conflicts


def _migrate_legacy_uploads(store: CaseStore) -> dict[str, int]:
    """伺服器啟動時，一次性且冪等地將 data/uploads/*.json 內尚未入庫的案件遷移進 CaseStore。"""
    migrated_counts = {"sampling": 0, "appeal": 0}
    for kind in ("sampling", "appeal"):
        cases = _load_latest_cases(kind)
        if not cases:
            continue
        for case in cases:
            try:
                store.create(
                    case_id=case["id"],
                    kind=kind,
                    case_seq=case.get("case_seq"),
                    order_code=case.get("order_code"),
                    payload=case,
                )
                migrated_counts[kind] += 1
            except DuplicateCaseError:
                pass
    return migrated_counts


_migration_result = _migrate_legacy_uploads(_case_store)
app.logger.info("啟動期遷移 data/uploads/*.json → CaseStore：%s", _migration_result)


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
        # W5 數據流（D-05 前置）：透傳 rec.id_number（健保署已遮罩後 4 碼，
        # models.py:166/189，與 field_mapping.py:19-22 語意一致）——僅透傳不
        # 重組完整字號；缺省 None 時照印 None、不捏造。patient_name/case_class/
        # orders 屬 09.1-03 轉換層缺欄誠實留空＋warning 範圍，不在此補。
        "id_number": rec.id_number,
        "patient_name": None,
        "order_code": rec.order_code,
        "order_name": name or rec.order_code,
        # W5 數據流（11.1-01）：透傳 rec.order_seq（欄 10「醫令序號」，
        # models.py:190，對應申報 XML p13）——僅透傳不轉型（None 時照印
        # None，與既有 id_number 透傳同一語意）；points 映射由轉換層
        # （case_to_submission.py 單筆分支）負責，本函式不新增 orders。
        "order_seq": rec.order_seq,
        "deduct_amount": rec.non_reimbursed_amount,
        "deduction_reason": rec.deduction_reason or rec.institution_note or "",
        "visit_date": rec.visit_date,
        "soap": "",
        "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
        "source": "csv",
    }


# 11.1-02（BLOCKER-1）：records_degraded 原因文案（固定中文模板，不含
# RECORDS_DIR 路徑／病歷號，T-1112-01）。records_source 四態：
# ok（實查成功）／absent（已查詢、病患缺席，C5 降級）／unconfigured
# （病歷來源未設定，未嘗試查詢）／no_record_no（有來源但請求未帶病歷號）。
_RECORDS_DEGRADED_REASONS = {
    "unconfigured": "病歷來源未設定（病歷目錄不存在）",
    "no_record_no": "請求未提供病歷號",
    "absent": "查無此病患病歷檔案",
}


def _records_provider() -> LocalFileProvider | None:
    """具現化病歷 Provider（Phase 4 LocalFileProvider，BLOCKER-1 接線）。

    RECORDS_DIR 目錄存在 → LocalFileProvider（實查半年病史）；不存在 →
    None（代表「病歷來源未設定」，不是「病患缺席」——兩者語意不同）。

    實際查詢走 build_timeline：PatientRecordsNotFound 內捕降級（absent），
    RecordProviderError（JSON 損毀等 infra 故障）向外穿透至統一 500
    （P0-2/T-1112-03，不吞成業務結論）。
    """
    if os.path.isdir(settings.RECORDS_DIR):
        return LocalFileProvider(settings.RECORDS_DIR)
    return None


def _resolve_records_source(
    provider: LocalFileProvider | None, record_no: str
) -> tuple[PatientTimeline | None, str]:
    """依 Provider 具現化與 record_no 解析 timeline 與 records_source 四態。

    Returns:
        (timeline, records_source)：timeline 為 PatientTimeline | None；
        records_source ∈ ok/absent/unconfigured/no_record_no。
    """
    timeline = None
    if provider is not None and record_no:
        agg = build_timeline(provider, record_no)
        timeline = agg.timeline
        return timeline, ("absent" if agg.degraded else "ok")
    if provider is not None:
        return None, "no_record_no"
    return None, "unconfigured"


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/health', methods=['GET'])
def health():
    """健康檢查（供 HIS 與監控探測，豁免 API key，不含任何案件資料）。"""
    return jsonify({"status": "ok"})


# ==============================================================================
# 1. 抽樣事前預審 API
# ==============================================================================
@app.route('/api/sampling/cases', methods=['GET'])
def get_sampling_cases():
    """回傳門診抽樣事前預審案例。

    優先改讀 CaseStore.list_all(kind='sampling') 為單一真實來源；
    若 CaseStore 中無案件，才 fallback 至示範資料。
    """
    records = _case_store.list_all(kind="sampling")
    if records:
        return jsonify([r.payload for r in records if r.payload is not None])
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
    case_id = _clean_str(data, 'case_id')

    case = SubmissionCase(
        record_no=record_no,
        orders=(OrderRecord(code=order_code),),
    )
    # 用 Phase 3 真實解析器分段（marker/keyword 兩層＋信度），不自行組模型
    soap_doc = parse_soap_text(soap_text) if soap_text else None

    try:
        # 11.1-02（BLOCKER-1）：以 Provider 具現化＋timeline 解析取代寫死的
        # timeline=None——RECORDS_DIR 存在且請求帶病歷號時，LocalFileProvider
        # 實查半年病史並傳入 run_presubmission_check（Success Criteria 1）。
        # RecordProviderError（JSON 損毀等 infra 故障）不在此捕捉，穿透至
        # errorhandler 統一 500（P0-2/T-1112-03）；PatientRecordsNotFound 由
        # build_timeline 內捕為 degraded=True（C5 正常降級）。
        provider = _records_provider()
        timeline, records_source = _resolve_records_source(provider, record_no)
        result = run_presubmission_check(case, soap_doc, timeline)
    except RuleRepositoryError as exc:
        # D-06/P0-2：規則庫故障不得偽裝成「查無規則」或「裸奔」。
        app.logger.error("rule repository failure during presubmission: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)

    if case_id:
        actor = getattr(g, "caller_id", None)
        try:
            _case_store.transition(case_id, "parsed", actor=actor)
            _case_store.transition(case_id, "reviewing", actor=actor)
            _case_store.transition(case_id, "reviewed", actor=actor)
        except (CaseNotFoundError, IllegalTransitionError) as exc:
            app.logger.warning("sampling case_id=%s 狀態轉換失敗（不阻斷回應）：%s", case_id, exc)

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
        "case_id": case_id or None,
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
        "records_source": records_source,
        # 降級原因文案（固定中文模板，不含路徑／病歷號，T-1112-01）；
        # 僅 records_degraded=True 時提供，否則 None。
        "records_degraded_reason": (
            _RECORDS_DEGRADED_REASONS.get(records_source)
            if result.comparison.records_degraded
            else None
        ),
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
    persisted, conflicts = _persist_cases('sampling', cases, getattr(g, "caller_id", None))
    return jsonify({
        'status': 'success',
        'media_type': media_type,
        'source': source,
        'imported': len(cases),
        'rejected': len(rejected),
        'rejected_rows': rejected,
        'saved_to': saved,
        'case_store_persisted': persisted,
        'case_store_conflicts': conflicts,
    })


# ==============================================================================
# 2. 核減事後申復 API (多源證據補強: 影像/檢驗/雲端病歷)
# ==============================================================================
@app.route('/api/appeal/cases', methods=['GET'])
def get_appeal_cases():
    """回傳核減需申復案件清單。

    優先改讀 CaseStore.list_all(kind='appeal') 為單一真實來源；
    若 CaseStore 中無案件，才 fallback 至示範資料。
    """
    records = _case_store.list_all(kind="appeal")
    if records:
        return jsonify([r.payload for r in records if r.payload is not None])
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
    case_id = _clean_str(data, 'case_id')
    # 11.1-02（BLOCKER-1）：病歷號＝Phase 3 d3＝LocalFileProvider 的
    # patient_id。選填：前端 appeal 面板病歷號輸入欄（aRecordNoInput）送出；
    # CSV 匯入案件 payload.record_no 恆 None，此欄是 generate 端點 timeline
    # 查詢的唯一真實來源——有值才查，無值由下方 timeline 解析誠實標記
    # no_record_no（plan-checker BLOCKER 2 使用者裁示）。
    record_no = _clean_str(data, 'record_no')
    # 11.1-01：透傳 order_seq（欄 10 醫令序號）至 DeductionRecord，經
    # render_appeal_json 的 order_seq/p1_order_seq（appeal.py:486/494）流入
    # 紙本 build_rows 的 _find_order_by_seq——醫令序對應 API 路徑閉合。
    # 選填、沿用 _MAX_FIELD_CHARS 上限（T-1111-01 _clean_str 既有防護）。
    order_seq = _clean_str(data, 'order_seq')

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
        # 選填：缺省時 _clean_str 回 ""，以 or None 維持「缺省 None、不捏造」
        # （與 deduction_reason 同模式），render_appeal_json 誠實輸出 null。
        order_seq=order_seq or None,
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

    # 11.1-02（BLOCKER-1）：timeline 解析（共用 _records_provider() helper，
    # 與 /api/sampling/audit 同一語意）。PatientRecordsNotFound 由
    # build_timeline 內捕降級；RecordProviderError（infra 故障）向外穿透
    # 統一 500，不吞成業務結論（P0-2/T-1112-03）。
    provider = _records_provider()
    timeline, records_source = _resolve_records_source(provider, record_no)

    draft = build_appeal_draft(
        record,
        is_appealing=is_appealing,
        claimed_points=claimed_points,
        timeline=timeline,
        rule_text=rule_text,
        rule_location=rule_location,
        evidence=evidence,
        has_attachment=data.get('has_attachment') if 'has_attachment' in data else None,
    )

    if case_id:
        actor = getattr(g, "caller_id", None)
        try:
            _case_store.transition(case_id, "appealed", actor=actor)
        except (CaseNotFoundError, IllegalTransitionError) as exc:
            app.logger.warning("appeal case_id=%s 狀態轉換至 appealed 失敗（不阻斷回應）：%s", case_id, exc)

    # W4 契約橋（D-03）：回應主體為 render_appeal_json 標準契約
    # （sections/word_stats/p1-p9），前端可直接落盤 appeal_{流水號}.json
    # 餵 build_appeal_xml/build_appeal_print。舊鍵（appeal_sections/reason1/
    # reason2/p6_points/total_char_count/xml_p8_p9_valid/record_no/頂層
    # over_limit/case_seq/order_code）已整段移除——單一契約、不做雙契約兼容。
    payload = json.loads(render_appeal_json(draft))
    # 僅併入補充鍵：status/case_id/rule_found（rule_found 來自規則庫
    # get_rule 的 :754 rule.found，不在 AppealDraft 內）＋11.1-02 新增
    # records_degraded/records_source/records_degraded_reason 三鍵。
    payload["status"] = "success"
    payload["case_id"] = case_id or None
    payload["rule_found"] = rule.found
    # 11.1-02（BLOCKER-1）：records_degraded＝timeline is None（與 comparator
    # records_degraded = timeline is None 同語意）；原因文案固定中文模板，
    # 不含路徑／病歷號（T-1112-01），僅降級時提供否則 None。
    payload["records_degraded"] = timeline is None
    payload["records_source"] = records_source
    payload["records_degraded_reason"] = (
        _RECORDS_DEGRADED_REASONS.get(records_source) if timeline is None else None
    )
    return jsonify(payload)


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
    persisted, conflicts = _persist_cases('appeal', cases, getattr(g, "caller_id", None))
    return jsonify({
        'status': 'success',
        'media_type': 'csv',
        'source': 'csv',
        'imported': len(cases),
        'rejected': len(rejected),
        'rejected_rows': rejected,
        'saved_to': saved,
        'case_store_persisted': persisted,
        'case_store_conflicts': conflicts,
    })


@app.route('/api/appeal/attachments/upload', methods=['POST'])
def upload_appeal_attachment():
    """上傳佐證影像附件。"""
    case_seq = request.form.get("case_seq") or request.args.get("case_seq")
    if not case_seq:
        raise ApiError("缺少案件流水號 case_seq")

    order_seq = request.form.get("order_seq") or request.args.get("order_seq")
    order_code = request.form.get("order_code") or request.args.get("order_code")

    file = request.files.get("file")
    if not file or not (file.filename or "").strip():
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")

    file_bytes = file.read()
    try:
        rec = attachment_store.save_attachment(
            case_seq=case_seq,
            file_bytes=file_bytes,
            filename=file.filename,
            order_seq=order_seq,
            order_code=order_code,
        )
    except InvalidAttachmentError as exc:
        raise ApiError(str(exc))
    except Exception as exc:
        app.logger.error("attachment upload error: %s", exc)
        raise ApiError("附件儲存失敗")

    return jsonify({
        "status": "success",
        "attachment": {
            "id": rec.id,
            "case_seq": rec.case_seq,
            "order_seq": rec.order_seq,
            "order_code": rec.order_code,
            "filename": rec.filename,
            "file_size": rec.file_size,
            "mime_type": rec.mime_type,
            "created_at": rec.created_at,
        }
    })


@app.route('/api/appeal/attachments/<case_seq>', methods=['GET'])
def get_appeal_attachments(case_seq: str):
    """查詢某案件下的佐證附件清單。"""
    order_seq = request.args.get("order_seq")
    records = attachment_store.list_attachments(case_seq, order_seq)
    return jsonify({
        "status": "success",
        "case_seq": case_seq,
        "attachments": [
            {
                "id": r.id,
                "case_seq": r.case_seq,
                "order_seq": r.order_seq,
                "order_code": r.order_code,
                "filename": r.filename,
                "file_size": r.file_size,
                "mime_type": r.mime_type,
                "created_at": r.created_at,
            }
            for r in records
        ]
    })


@app.route('/api/appeal/attachments/<case_seq>/<attachment_id>', methods=['DELETE'])
def delete_appeal_attachment(case_seq: str, attachment_id: str):
    """刪除指定佐證附件。"""
    deleted = attachment_store.delete_attachment(case_seq, attachment_id)
    if not deleted:
        raise ApiError("找不到指定附件或刪除失敗", status=404)
    return jsonify({
        "status": "success",
        "message": "附件已刪除"
    })


@app.route('/api/deduction/print', methods=['POST'])
def generate_deduction_print():
    """生成核減明細原格式 PDF（Phase 13-03）"""
    data = request.json or {}
    if not isinstance(data, dict):
        raise ApiError("請求主體必須為 JSON 物件")

    case_id = _clean_str(data, 'case_id', required=False)
    payload_records = data.get('records')

    records = []
    if payload_records and isinstance(payload_records, list):
        records = payload_records
    elif case_id:
        try:
            case = _case_store.get(case_id)
            if case.payload:
                records = [case.payload]
        except CaseNotFoundError:
            raise ApiError(f"找不到案件 '{case_id}'", status=404)
    else:
        raise ApiError("必須提供 records 陣列或 case_id")

    if not records:
        raise ApiError("無有效核減資料可供列印")

    facility = settings.load_facility_config()

    from elc_audit_engine.safe_paths import safe_filename
    stem = safe_filename(case_id or uuid.uuid4().hex[:8], "file_stem")

    from elc_audit_engine.generators.deduction_print import write_deduction_print
    from config import settings
    PRINT_BASE_ODT = os.path.join(
        settings.PROJECT_ROOT,
        "officialdocument",
        "電子申復文件格式",
        "RCPI2012R01_核減明細表_print_base.odt",
    )

    try:
        pdf_path, warnings = write_deduction_print(
            settings.OUTPUT_DIR,
            stem,
            records,
            facility,
            template_odt_path=PRINT_BASE_ODT,
        )
    except Exception as exc:
        raise ApiError(f"產生 PDF 失敗: {exc}")

    pdf_url = f"/output/{os.path.basename(pdf_path)}"
    
    return jsonify({
        "status": "success",
        "pdf_url": pdf_url,
        "warnings": warnings,
    })


if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    # 安全預設（P0-1）：綁定 127.0.0.1、debug 關閉。
    # 原設定 host='0.0.0.0' + debug=True 等於無認證對全網卡開放，且
    # 例外會回顯堆疊；本服務會接觸病歷資料，不得如此。
    # 需對外提供時請置於反向代理／VPN 後，並以環境變數覆寫：
    #   ELC_SERVER_HOST=0.0.0.0 ELC_SERVER_PORT=5000 python server.py
    # Phase 9-01：認證已由 before_request 強制，除 / 與 /api/health 外
    # 一律需帶 X-API-Key；ELC_API_KEYS 未設定時服務啟動即失敗（fail-fast）。
    host = os.getenv('ELC_SERVER_HOST', '127.0.0.1')
    port = int(os.getenv('ELC_SERVER_PORT', '5000'))
    debug = os.getenv('ELC_SERVER_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
