# 32-06-SUMMARY: 院內信任模式強化（真實遮罩、介面過濾、跨站 GET 拒絕與管理寫入限制）(D-32-16..D-32-19)

## 執行成果摘要
- 依據 Plan 32-06 與鎖定裁示 D-32-16..D-32-19，完成院內網路信任邊界之安全性與可維護性強化：
  1. 網段偵測與介面篩選（D-32-16 & D-32-17）：
     - 實作 `list_candidate_interfaces`：可注入解析 `ip -j -4 addr` 資訊，自動排除 loopback 與虛擬/VPN 介面（tun、tap、ppp、wg、docker、br-、veth、virbr、zt、tailscale 等），僅挑選私有 IPv4。
     - `detect_local_subnets` 改採介面實際 prefixlen（如 /23、/22），不再硬編碼截斷為 /24；若有多個候選介面且未指定 `ELC_TRUSTED_INTERFACE` 或 `ELC_TRUSTED_SUBNETS`，自動退回 loopback 信任（fail-closed），並記錄警告。
     - 模組支援 CLI 命令列入口：`python -m elc_audit_engine.lan_trust --describe` 輸出包含 `configured`、`detected`、`candidates`、`needs_confirmation` 之標準 JSON 結構，供 `install.sh` 介面選用。
  2. 跨站 GET 讀取拒絕（D-32-18）：
     - 新增 `is_cross_site_read(method, sec_fetch_site)`：針對 GET/HEAD 請求，若標頭帶有 `Sec-Fetch-Site: cross-site`，一律拒絕（403 回傳 `CROSS_SITE_MESSAGE`）。其餘 `same-origin`、`same-site`、`none` 或原生客戶端請求（缺漏標頭）維持放行。
  3. 管理類端點寫入權限限制（D-32-19）：
     - 定義 `ADMIN_WRITE_ENDPOINTS` 涵蓋 `misc.update_facility` 與 `soap_review.update_auto_accept_setting`。
     - 於 `security._enforce_lan_trust` 限制此類端點之狀態變更請求（POST/PUT/PATCH/DELETE）僅限伺服器本機 `loopback`（`127.0.0.1` / `::1`）；區網端點發動寫入回傳 403（中文訊息「此設定只能在伺服器本機修改」），讀取（GET）則維持區網開放。
  4. 測試驗證：
     - `tests/test_lan_trust.py` 與 `tests/test_lan_trust_api.py` 擴充後 75 passed。
     - `tests/test_soap_review_api.py` 與 `tests/test_auto_accept_toggle.py` 整合測試全數通過（合計 93 passed）。

## 驗證輸出
```
93 passed in 9.80s
```

## 產出狀態
- Plan 32-06 完成。
