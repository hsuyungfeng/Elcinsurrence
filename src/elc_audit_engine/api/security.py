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

import ipaddress

from flask import Flask, current_app, g, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.lan_trust import (
    ADMIN_WRITE_MESSAGE,
    BAD_HOST_MESSAGE,
    CROSS_SITE_MESSAGE,
    UNSAFE_METHODS,
    UNTRUSTED_MESSAGE,
    caller_id_for,
    is_allowed_host,
    is_cross_site_read,
    is_cross_site_request,
    is_trusted_source,
)

#: 管理類寫入端點（D-32-19：僅限伺服器本機 loopback 修改）。
ADMIN_WRITE_ENDPOINTS = frozenset({
    "misc.update_facility",
    "soap_review.update_auto_accept_setting",
    "setup.save_setup",
})

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
#  E8 已拆檔並移除 inline 事件，script 不再需要 unsafe-inline；style 仍有 292 處 inline style 屬性，待 E3 子批次（32-18）改為 class 後移除。
CSP = "; ".join(
    (
        "default-src 'self'",
        "style-src 'self' 'unsafe-inline'",
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

        # 管理類寫入端點限制僅限 loopback（D-32-19）
        if request.endpoint in ADMIN_WRITE_ENDPOINTS and request.method in UNSAFE_METHODS:
            is_loopback = False
            if request.remote_addr:
                try:
                    is_loopback = ipaddress.ip_address(request.remote_addr).is_loopback
                except ValueError:
                    pass
            if not is_loopback:
                current_app.logger.warning(
                    "拒絕非本機寫入管理設定：%s %s from %s",
                    request.method,
                    request.path,
                    request.remote_addr,
                )
                return jsonify({"status": "error", "message": ADMIN_WRITE_MESSAGE}), 403

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
