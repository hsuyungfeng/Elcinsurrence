# MockHIS 探針驗證成果報告

本文件記錄於 Windows 測試機上執行 MockHIS 探針之「寫入 → 讀回 → 比對」完整驗證成果，以及對區域網路（Intra-net）後端工作台伺服器之連線檢測報告。

---

## 一、驗證背景與目標

- **驗證項目**：Phase 30-09 MockHIS 替身探針寫入與讀回安全檢測（Readback Check）
- **主要目的**：驗證 ElcAgent 校正機制（`agent-desktop` 探針）能在完全不接觸真實 HIS、不讀寫真實病歷之前提下，透過 UI 自動化（Win32 原生 Edit 控制項無障礙樹）正確定位欄位、寫入隨機 Nonce、讀回並完成雜湊比對。
- **安全規範**：
  - 僅操作標題包含「MockHIS」之測試替身視窗。
  - 所有欄位資料為動態隨機產生的 `PROBE-*` Nonce，不含敏感醫療資料。
  - 測試完成後視窗與程序全數正常關閉，無任何殘留。

---

## 二、測試機環境資訊

| 項目 | 規格 / 版本 |
|---|---|
| **作業系統** | Microsoft Windows 11 Pro for Workstations |
| **系統版本碼** | Microsoft Windows NT 10.0.26200.0 |
| **Python 執行環境** | Python 3.12.10 (64-bit) |
| **探針自動化工具** | `agent-desktop.exe` (v1.2.0 / Protocol 2.6) |
| **測試目錄** | `C:\MockHIS_Probe_Bundle` |

---

## 三、探針執行結果紀錄（完整 Console 輸出）

依據《MockHIS 探針操作說明》第六節規範回傳完整探針日誌：

```text
Starting MockHIS test window (keep it open)...
Running readback probe...
============================================================
【Phase 30-09】MockHIS 替身探針寫入與讀回安全檢測
============================================================
[OK] 使用 agent-desktop: C:\MockHIS_Probe_Bundle\agent-desktop.exe
[CHECK] 尋找標題含 'MockHIS' 的視窗快照...
[OK] 成功鎖定測試替身視窗 (app=pythonw.exe (id=w-132292))，安全確認通過。
[OK] 鎖定測試欄位: 主訴 (S) (ref=@s1xkha19192spo:e1)
[PROBE] 產生隨機探針 Nonce: PROBE-715069B3B663
[PROBE] 預期 SHA-256: 604183cccaaaf15d1500fcbba3d66f651153ae66b3b1e69a1ffaff10c0ead5bf
[WRITE] 正在將探針寫入欄位 @s1xkha19192spo:e1...
[OK] 探針寫入成功。
[READ] 正在從欄位 @s1xkha19192spo:e1 讀回值...
[READ] 讀回字串: PROBE-715069B3B663
[READ] 讀回 SHA-256: 604183cccaaaf15d1500fcbba3d66f651153ae66b3b1e69a1ffaff10c0ead5bf
------------------------------------------------------------
【PASS】讀寫比對完全一致！
  - 探針寫入值: PROBE-715069B3B663
  - 欄位讀回值: PROBE-715069B3B663
  - 雜湊一致性: 604183cccaaaf15d1500fcbba3d66f651153ae66b3b1e69a1ffaff10c0ead5bf == 604183cccaaaf15d1500fcbba3d66f651153ae66b3b1e69a1ffaff10c0ead5bf
  - 結論: readback_test_passed 驗證通過，符合 30-09 探針驗收標準。
------------------------------------------------------------

Probe finished. Copy the output above.
```

---

## 四、區域網路（Intra-net）伺服器連線與 API 檢測

針對區域網路網段進行連線探測，成功定位並驗證後端服務：

| 檢測項目 | 檢測結果 |
|---|---|
| **伺服器位址** | `http://<內網伺服器 IP>:5000` |
| **平台名稱** | **Elcinsurrence - 健保雙軌自動化審核與申復工作台** |
| **後端核心服務** | `elc-audit-engine` (Python / Gunicorn) |
| **API 端點** | `GET /api/health` |
| **HTTP 回應** | **200 OK**：`{"service":"elc-audit-engine","status":"ok"}` |
| **連線結論** | 測試機與內網伺服器通訊正常，API 健檢狀態正常。 |

---

## 五、相容性優化與問題修復紀錄

在驗證過程中，針對 Windows 11 環境進行了兩項相容性優化：

1. **`run_probe.bat` 批次檔語法修復**：
   - 原檔案中 `if not exist "%PY%" (` 區塊內的 `echo ... (first run only)...` 包含小括號，導致 CMD 解析器提早閉合 `if` 條件區塊，引發 `... was unexpected at this time.` 語法錯誤。已將文字修正並改以非互動式延遲命令替代。
2. **`probe_readback_check.py` 視窗鎖定增強**：
   - 在 Windows 11 上，`pythonw.exe` 啟動時系統輸入法（IME / Cicero）會建立無標題之輔助視窗，導致 `agent-desktop snapshot --app pythonw` 觸發 `AMBIGUOUS_TARGET` 阻斷。
   - 強化了鎖定邏輯：先透過 `list-windows` 提取標題精確包含 `MockHIS` 的視窗 ID，再以 `--window-id` 指定快照，徹底解決多視窗干擾問題。

---
**驗證結論**：`readback_test_passed` 驗證完全通過，已達交付與驗收標準。
