"""院內網路信任、CSRF 防護、安全標頭與存取審計（Phase 32-A）。

端點名稱為 blueprint 限定名（`<blueprint>.<函式>`）。

**Phase 32-A 變更（使用者裁示 2026-11-13）**：移除 `X-API-Key` 認證，改以
來源位址判定信任（見 `elc_audit_engine.lan_trust` 的完整理由）。因此：

- `AUTH_EXEMPT_ENDPOINTS` 不再需要——沒有金鑰可豁免，信任與否只看來源
  位址，對所有端點一致。
- 新增 CSRF 防護：金鑰移除後瀏覽器成為攻擊面，寫入請求必須驗跨站來源。
- 審計日誌仍然保留（「驗證可省、軌跡不可省」）。
"""

from __future__ import annotations


from flask import Flask, current_app, g, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.lan_trust import (
    BAD_HOST_MESSAGE,
    CROSS_SITE_MESSAGE,
    UNTRUSTED_MESSAGE,
    caller_id_for,
    is_allowed_host,
    is_cross_site_read,
    is_cross_site_request,
    is_trusted_source,
)

# 審計豁免清單：靜態頁與健康檢查不含病歷存取，記錄會被探測流量淹沒
# （客戶端每數秒探測一次 /api/health 與心跳）。
# 這份清單**只**決定寫不寫審計；是否放行一律由來源位址決定。
AUDIT_EXEMPT_ENDPOINTS = frozenset({
    "misc.index",
    "misc.health",
    "static",
    "clients.monitor_page",
    "clients.client_heartbeat",
})

#: P1-5 縱深防禦：即使前端某處遺漏轉義，CSP 也擋掉外部腳本與資料外送。
#  外鏈字型已移除（D2 個資不出本機），故 default-src 收斂到 'self'。
#  E8 已拆檔並移除 inline 事件，script 採用 'self'；
#  Phase 32.1 已將靜態頁 inline styles 抽出至獨立 css 檔，style-src 收緊為 'self'。
#  Python 產生之獨立匯出／下載報表檔不受 app CSP 約束。
CSP = "; ".join(
    (
        "default-src 'self'",
        "style-src 'self'",
        "script-src 'self'",
        # blob:：佐證庫（Phase 17-02）以 fetch 取回檔案後轉 blob URL 顯示；
        # <img>/<audio> 只能用同源 blob。blob: 僅能由頁面自行建立，不外送資料。
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    )
)


def register_security(app: Flask) -> None:
    @app.before_request
    def _enforce_lan_trust():
        """統一強制「來源位址須在院內網段」與跨站寫入防護。

        採 before_request 而非逐一端點 decorator：**新增端點時預設受保護**。
        不設任何豁免清單——信任判準對所有端點一致，包含健康檢查
        （院外來源連 /api/health 都不該得到回應，那會洩漏服務存在）。
        """
        # Host 檢查先行：DNS rebinding 的請求來源位址是可信的院內位址，
        # 來源檢查無法分辨，且 GET 讀取不受 CSRF 檢查保護。
        if not is_allowed_host(request.host):
            return jsonify({"status": "error", "message": BAD_HOST_MESSAGE}), 400

        # 反向代理防線（execurator 審查）：若前方有同機反向代理，所有外部請求
        # 的 remote_addr 都是 127.0.0.1，loopback 會被無條件信任。信任模式不支援
        # 反向代理，故一律拒絕帶轉發標頭的請求（fail closed）。
        if any(h in request.headers for h in ("X-Forwarded-For", "Forwarded", "X-Real-IP")):
            current_app.logger.warning("拒絕帶轉發標頭的請求（信任模式不支援反向代理）：%s", request.path)
            return jsonify({"status": "error", "message": UNTRUSTED_MESSAGE}), 403

        trusted = current_app.config["ELC_TRUSTED_SUBNETS"]
        if not is_trusted_source(request.remote_addr, trusted):
            # 不回報信任網段內容，避免協助攻擊者推測內網結構。
            current_app.logger.warning(
                "拒絕非信任來源：%s %s from %s",
                request.method,
                request.path,
                request.remote_addr,
            )
            return jsonify({"status": "error", "message": UNTRUSTED_MESSAGE}), 403

        g.caller_id = caller_id_for(request.remote_addr)

        if is_cross_site_request(
            request.method,
            request.headers.get("Origin"),
            request.headers.get("Sec-Fetch-Site"),
            request.host_url,
        ):
            current_app.logger.warning(
                "拒絕跨站寫入：%s %s origin=%r from %s",
                request.method,
                request.path,
                request.headers.get("Origin"),
                request.remote_addr,
            )
            return jsonify({"status": "error", "message": CROSS_SITE_MESSAGE}), 403

        # 跨站 GET 讀取檢查（D-32-18）
        if is_cross_site_read(request.method, request.headers.get("Sec-Fetch-Site")):
            current_app.logger.warning(
                "拒絕跨站讀取：%s %s sec_fetch_site=%r from %s",
                request.method,
                request.path,
                request.headers.get("Sec-Fetch-Site"),
                request.remote_addr,
            )
            return jsonify({"status": "error", "message": CROSS_SITE_MESSAGE}), 403

        # 規則 CSV 上傳單路由放寬至 65 MB（對齊 rules.py MAX_RULE_CSV_BYTES=64MB + 1MB 表單餘裕；
        # 全域 MAX_CONTENT_LENGTH 維持 26 MB，不影響其他路由安全邊界）。
        if request.method == "POST" and request.path == "/api/rules/upload":
            request.max_content_length = 65 * 1024 * 1024

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
                    caller_id=getattr(g, "caller_id", "lan:unknown"),
                    method=request.method,
                    path=request.path,
                    status=response.status_code,
                )
            except OSError as exc:
                current_app.logger.error("寫入審計日誌失敗，但業務回應照常回傳：%s", exc)
        return response
