# Phase 32 Plan 14: Inno Setup 安裝檔與輕量 SoapVoice 打包 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：B3、B4、D-32-09、D-32-10、D-32-21  

---

## 執行成果

1. **SoapVoice 客戶端輕量打包規格 (`SoapVoice/soapvoice_client.spec`)**：
   - 依據 D-32-09（診間端只錄音與上傳），以 `client/main.py` 為入口，產出一資料夾（one-folder）輸出至 `dist/SoapVoiceClient/`。
   - 嚴格排除 `torch`、`torchaudio`、`whisper`、`faster_whisper`、`ctranslate2`、`chromadb`、`llama_cpp` 等推論依賴。
   - `console=False`、`upx=False`，不打包 `models/` 或 `.env`。
   - AST 語法檢查通過。

2. **Inno Setup 安裝腳本實作 (`installer/elc_agent.iss`)**：
   - 滿足 `PrivilegesRequired=lowest`（免管理者權限安裝至 `{autopf}\ElcAgent`）。
   - 設定 `CloseApplications=yes`，升級安裝時自動關閉舊版進程，避免檔案被鎖。
   - 建立桌面與開機啟動捷徑（`{userstartup}\ELC Agent.lnk`）。
   - 依 D-32-21 將 SoapVoiceClient 安裝至 `{app}\SoapVoice\`，由 ElcAgent 統一啟動與監控。
   - `[UninstallDelete]` 保留 `%LOCALAPPDATA%\ElcAgent` 的設定、校正與暫存檔，解除安裝不遺失資料。
   - 遵循 D-32-10（不購買簽章憑證），不嘗試進行數位簽章。
   - 排除所有禁止指令（`{commonstartup}`、`{pf}\`、`PrivilegesRequired=admin`、`LittleB`、`npx`）。

3. **建置自動化腳本 (`installer/build_installer.py`)**：
   - 支援 `--check` 參數於 Linux/CI 環境預先檢查相依目錄是否齊全。
   - 實作 `compute_sha256` 計算並輸出 `dist/ElcAgentSetup.exe.sha256`。
   - 提供編譯工作流程（編譯 ElcAgent → 編譯 SoapVoiceClient → 呼叫 iscc 編譯安裝檔）。

4. **測試與驗證 (`tests/test_installer_script.py`)**：
   - 移除 Wave 0 xfail 標記。
   - 驗證 Inno Setup 契約規則與禁止指令。
   - 驗證 SHA256 計算正確性。
   - 驗證 `--check` 模式在缺漏與正常情況下的行為。
   - 測試全數通過（3 passed in 1.27s）。
