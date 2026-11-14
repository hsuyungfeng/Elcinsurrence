# Phase 32 Plan 01: 前置決策與基準驗證 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **產出文件**：`.planning/phases/32-fable5-2improvplan-md/32-CONTEXT.md`（鎖定 D-32-16..D-32-21）  

---

## 執行成果

1. **第一期基準驗證（P1-VERIFY）**：
   - 提交基準 `01e1a13` 存在。
   - `tests/` 全數通過（1537 passed），`doc/tests/` 全數通過（138 passed）。
   - `src/elc_audit_engine/auth.py` 已完全刪除，`ElcAgent.spec` 確認包含 `console=False`，`main.py` 不含寫死 IP `192.168.68.118`。
2. **D-32-09 依賴檢查（D-32-09-CHECK）**：
   - 清查 `SoapVoice/client/` 共 16 個 Python 模組之所有 imports。
   - 確認**完全不包含** torch、whisper、faster_whisper、ctranslate2、funasr、sentence_transformers、chromadb、llama_cpp 等推論套件。
   - 診間客戶端依賴輕量，100% 符合 D-32-09「只錄音與上傳，不做本機轉錄」。
3. **第三批裁示取得（D-32-16..D-32-21）**：
   - 使用者已裁示全部採納研究建議（每題 a）：
     - **D-32-16**：網段偵測讀取實際遮罩，`install.sh` 顯示並要求安裝人員確認後寫入 `ELC_TRUSTED_SUBNETS`。
     - **D-32-17**：列舉主機網路介面，自動排除 VPN/虛擬網卡（tun/tap/ppp/wg/docker/veth）。
     - **D-32-18**：跨站 GET 請求（帶 `Sec-Fetch-Site: cross-site`）一律回傳 403 拒絕。
     - **D-32-19**：`PUT /api/soap/settings/auto-accept` 與 `POST/PUT /api/facility` 寫入權限僅限本機 `127.0.0.1`。
     - **D-32-20**：客戶端雙軌清理調和：超過 3 個月且已上傳刪除，超過容量（2GB）刪已上傳最舊者，未上傳永不刪除並於介面警示。
     - **D-32-21**：同一 Inno Setup 安裝檔內包含 ElcAgent 與輕量 SoapVoice 客戶端，版本分離、由 ElcAgent 看管。

---

## 下游計畫解鎖狀態

- OPEN-32-01..06 全數關閉，下游計畫 `32-02` 至 `32-24` 全部解鎖，依據 D-32-16..21 推進實作。
