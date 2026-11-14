# Phase 32 Plan 13: 網頁版初次設定與診間清單 API Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：D2、D-32-19  

---

## 執行成果

1. **初次設定與診間清單 API (`src/elc_audit_engine/api/routes/setup.py`)**：
   - `GET /setup`：回傳初次設定頁面 `static/setup.html`。
   - `GET /api/setup/state`：回傳目前設定狀態，包含 `needs_setup`（未設院所代碼時為 True）、`facility`、`rooms`、`write_allowed`（僅 loopback 為 True）、`write_hint`。
   - `POST /api/setup`（`setup.save_setup`）：
     - 欄位驗證：院所代碼必須為 10 位數字、院所名稱非空且 ≤64 字、診間 1–30 間、診間代號符合 `validate_room_id`、診間名稱與代號不重複；驗證失敗回傳 422 及中文錯誤訊息。
     - 原子寫入：保留 `facility.json` 既有其他鍵（如地址等），以暫存檔＋`os.replace` 確保寫入不毀損。
     - 納入 `src/elc_audit_engine/api/security.py` 的 `ADMIN_WRITE_ENDPOINTS`，非本機寫入一律回傳 403。
   - `GET /api/rooms`：回傳 `{"rooms": [...]}`，供 Windows 客戶端首次設定精靈下拉選單使用。
   - 於 `src/elc_audit_engine/api/routes/__init__.py` 註冊 `setup_bp`。

2. **初次設定靜態網頁與互動腳本 (`static/setup.html`、`static/js/setup.js`)**：
   - 建立大字（內文 18px、輸入框高 44px）之一頁式表單。
   - 支援動態新增與刪除診間列，即時輸入驗證與白話提示。
   - 透過 `/api/setup/state` 自動判定：若由非本機開啟則停用表單並顯示白話提示；若已完成設定則標註可隨時修改。
   - 儲存完成後呈現成功提示與直接跳轉「審查工作台 (`/`)」與「系統狀態 (`/status`)」之按鈕。
   - 程式碼完全外置於 `static/js/setup.js`，無任何 inline script 或 on* 事件屬性。

3. **測試與驗證 (`tests/test_setup_api.py`)**：
   - 測試初始需要設定狀態 (`test_setup_state_needs_setup`)。
   - 測試區域網路讀取時唯讀提示 (`test_setup_state_write_not_allowed_for_lan`)。
   - 測試完整欄位與診間驗證失敗處理 (`test_save_setup_validation_errors`)。
   - 測試儲存成功、原子寫入與保留既有其他欄位 (`test_save_setup_success_and_preserves_other_keys`)。
   - 測試區域網路非本機寫入被 403 拒絕 (`test_save_setup_forbidden_from_lan`)。
   - 測試診間清單 API (`test_get_rooms_api`) 與靜態頁面讀取 (`test_get_setup_html_page`)。
   - 測試全數通過（29 passed in 9.70s），且真實 `config/facility.json` 未受測試污染。
