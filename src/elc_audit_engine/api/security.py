"""認證、Host 白名單、安全標頭與存取審計（Phase 9-01／A-CR-01）。

端點名稱為 blueprint 限定名（`<blueprint>.<函式>`）。
"""

from __future__ import annotations

import os

from flask import Flask, current_app, g, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.auth import (
    API_KEY_HEADER,
    AuthConfigError,
    AuthenticationError,
    load_api_keys,
    resolve_caller,
)

# 審計豁免清單：靜態頁與健康檢查不含病歷存取，記錄會被探測流量淹沒。
# 這份清單只決定「寫不寫審計」，與是否強制認證無關——業務端點即使
# 免強制 API Key，仍接觸病歷資料，審計軌跡不可因此消失。
AUDIT_EXEMPT_ENDPOINTS = frozenset({"misc.index", "misc.health", "static"})

# 認證豁免清單：**僅決定認證是否強制，不得沿用來判斷審計**——兩份清單刻意
# 分開（歷史教訓：曾共用一份清單，導致免認證的業務端點連審計日誌都被一併
# 跳過，違反「認證可選、審計必留」的設計）。
#
# 2026-09 部分強制（code review A-CR-01，使用者裁示選項 2）：批次讀出 PHI 的
# 端點（案件清單、附件清單、列印產出下載）與破壞性操作（刪除附件）必須帶
# X-API-Key；其餘以單筆請求為單位、由呼叫方自帶資料的端點維持選填。
AUTH_EXEMPT_ENDPOINTS = AUDIT_EXEMPT_ENDPOINTS | frozenset({
    "sampling.audit_sampling_case",
    "sampling.import_sampling_cases",
    "appeal.generate_appeal_draft",
    "appeal.import_appeal_cases",
    "attachments.upload_appeal_attachment",
    "printing.generate_deduction_print",
    "printing.generate_evidence_packet_print",
})

#: P1-5 縱深防禦：即使前端某處遺漏轉義，CSP 也擋掉外部腳本與資料外送。
#  外鏈字型已移除（D2 個資不出本機），故 default-src 收斂到 'self'。
#  inline style/script 暫留 'unsafe-inline'——頁面目前為單檔 inline 樣板，
#  待拆出外部 .css/.js 後可移除此例外。
CSP = "; ".join(
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


def load_allowed_hosts() -> frozenset[str]:
    """Host header 白名單（防 DNS rebinding：惡意網域解析到 127.0.0.1 後，
    瀏覽器會帶攻擊者網域的 Host，藉此讀取免認證端點）。

    ELC_ALLOWED_HOSTS 以逗號分隔（不含 port 亦可）；未設定時僅允許本機名稱。
    """
    raw = os.getenv("ELC_ALLOWED_HOSTS", "")
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return frozenset(hosts or {"127.0.0.1", "localhost", "[::1]"})


def load_api_keys_or_fail(app: Flask) -> dict[str, str]:
    """啟動期載入 ELC_API_KEYS（fail-fast，不降級）。

    AuthConfigError 直接重新拋出，服務啟動即失敗——本服務會接觸病歷資料，
    設定缺失時繼續啟動等同於「無認證對外開放」。僅在
    ELC_ALLOW_NO_AUTH_FOR_TESTS == "1" 時允許以空表啟動（**只准測試使用**）。
    """
    try:
        return load_api_keys()
    except AuthConfigError:
        if os.environ.get("ELC_ALLOW_NO_AUTH_FOR_TESTS") == "1":
            app.logger.warning(
                "ELC_ALLOW_NO_AUTH_FOR_TESTS=1：以空 API key 表啟動（僅限測試環境！"
                "正式環境設定此旗標等同於關閉認證，絕不可用於生產部署）"
            )
            return {}
        raise


def _host_allowed(allowed: frozenset[str]) -> bool:
    host = (request.host or "").lower()
    hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    return host in allowed or hostname in allowed


def register_security(app: Flask) -> None:
    @app.before_request
    def _enforce_host_and_api_key():
        """統一強制 Host 白名單與 X-API-Key 認證（豁免需顯式列入白名單）。

        採 before_request 而非逐一端點 decorator：**新增端點時預設受保護**，
        豁免必須顯式列入 AUTH_EXEMPT_ENDPOINTS。
        """
        if not _host_allowed(current_app.config["ELC_ALLOWED_HOSTS"]):
            return jsonify({"status": "error", "message": "不允許的 Host"}), 400
        keys = current_app.config["ELC_API_KEYS"]
        presented_key = request.headers.get(API_KEY_HEADER)
        if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
            # 免強制認證，但呼叫方帶了合法 key 時解析 caller_id，讓審計日誌不必然
            # 落成 anonymous（key 錯誤或缺失靜默忽略——這裡不強制擋）。
            if presented_key:
                try:
                    g.caller_id = resolve_caller(presented_key, keys)
                except AuthenticationError:
                    pass
            return None
        if request.endpoint is None:
            return None  # 未匹配路由（404）交給 HTTPException handler
        g.caller_id = resolve_caller(presented_key, keys)
        return None

    @app.after_request
    def _security_headers(response):
        """統一補安全標頭（P1-5）。"""
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.after_request
    def _record_access_audit(response):
        """非豁免端點每次呼叫留下無 PHI 審計列。

        審計寫檔失敗不得讓已完成的業務回應變成 500，但必須在 application
        log 留痕。不得把 request.json／request.form 內容放進 detail（PHI 風險）。
        """
        if request.endpoint not in AUDIT_EXEMPT_ENDPOINTS:
            try:
                audit_log.record_access(
                    caller_id=getattr(g, "caller_id", "anonymous"),
                    method=request.method,
                    path=request.path,
                    status=response.status_code,
                )
            except OSError as exc:
                current_app.logger.error("寫入審計日誌失敗，但業務回應照常回傳：%s", exc)
        return response
