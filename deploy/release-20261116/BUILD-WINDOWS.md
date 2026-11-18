# Windows 建置與驗收指引（release-20261116）

> 本包必須在 **Windows 10/11 64 位元** 機器上建置。PyInstaller 無法在 Linux 產出 `.exe`。

## 一、發布包內容

| 檔案 | 用途 | SHA256 |
|---|---|---|
| `ElcAgent-src-2a6fea3.zip` | ElcAgent 原始碼（主倉庫 HEAD `2a6fea3`，git archive，不含未追蹤之現場設定） | 見 `SHA256SUMS.txt` |
| `SoapVoice-client-src-a6a9112.zip` | SoapVoice 診間客戶端原始碼（SoapVoice 倉庫 HEAD `a6a9112`）＋ `soapvoice_client.spec` | 見 `SHA256SUMS.txt` |
| `ElcAgent-bin/bin/` | `agent-desktop.exe`、`agent_desktop_ffi.dll`（沿用舊版 ElcAgent-win64 的二進位檔，雜湊已記錄） | 見 `SHA256SUMS.txt` |
| `31-WINDOWS-MANUAL-VERIFY.md` | 12 項實機人工驗收清單 | 見 `SHA256SUMS.txt` |
| `驗收結果.md` | 驗收結果記錄表（由測試者填寫） | — |

請先核對雜湊：

```powershell
Get-FileHash *.zip, ElcAgent-bin\bin\* | Format-List Path, Hash
```

## 二、建置 ElcAgent

1. 解壓 `ElcAgent-src-2a6fea3.zip` 至 `C:\build\Elcinsurrence`。
2. 把 `ElcAgent-bin\bin\` 內兩個檔案複製到 `C:\build\Elcinsurrence\deploy\windows_agent\bin\`。
   > `ElcAgent.spec` 會直接打包這個目錄；缺少時建置會失敗。
3. 建立環境並建置：

   ```powershell
   cd C:\build\Elcinsurrence
   uv sync --no-config
   uv pip install pyinstaller
   uv run pyinstaller deploy\windows_agent\ElcAgent.spec --noconfirm
   ```

4. 產物：`dist\ElcAgent\ElcAgent.exe`。執行 `ElcAgent.exe --selftest`，應回傳 0（若回傳 2 代表 agent-desktop 缺失）。

## 三、建置 SoapVoice 診間客戶端

> 必須在**僅含客戶端依賴**的環境中建置（D-32-26）。不要安裝 `--extra server`，否則會把 torch、faster-whisper 等大型套件打包進來。

1. 解壓 `SoapVoice-client-src-a6a9112.zip` 至 `C:\build\SoapVoice`。
2. 建置：

   ```powershell
   cd C:\build\SoapVoice
   uv sync --no-config
   uv pip install pyinstaller
   uv run pyinstaller soapvoice_client.spec --noconfirm
   ```

3. 產物：`dist\SoapVoiceClient\`（one-folder）。
4. **瘦身檢查**（必做）：

   ```powershell
   dir /s /b dist\SoapVoiceClient | findstr /i "torch whisper llama ctranslate2"
   ```

   此指令**不應有任何輸出**。若有輸出，代表打包內容含有伺服器端依賴，停止並回報。

## 四、組裝安裝程式

1. 以 Inno Setup 6 開啟 `C:\build\Elcinsurrence\installer\elc_agent.iss` 並編譯。
2. **編譯前請確認**：`.iss` 中有把 `SoapVoiceClient` 目錄（或 `SoapVoice.exe`）收錄進安裝檔，符合 D-32-21 與 D-32-26 的「同一安裝檔、由 ElcAgent 看管」。目前尚未核對此項，這是待確認事項。
3. 安裝程式產生於 Inno Setup 設定的輸出目錄。

## 五、實機驗收（第 10 項）

1. 在一台乾淨的 Windows 診間機（或測試機）安裝上一步產出的安裝程式。
2. 依 `31-WINDOWS-MANUAL-VERIFY.md` 逐項測試 12 項，並把結果填入 `驗收結果.md`。
3. **不得**在真實 HIS 上使用 `--test-vendor`（見 AGENTS.md §5b）。
4. 每項記錄 PASS 或 FAIL、時間與證據（截圖或日誌）。FAIL 時保留日誌，連同說明回報。

## 六、已知限制

- 本包在 Linux 上準備，未實際完成 Windows 建置，因此 `.exe` 與安裝程式**尚未驗證**。
- `soapvoice_client.spec` 目前未被 SoapVoice 倉庫追蹤，屬於待修正事項（應提交進倉庫，否則無法重現建置）。
- 桌面上 `eleinsurrencewinapp/mock_his/` 為舊副本，與倉庫的 `deploy/windows_agent/mock_his/` 內容不同。以倉庫版本為準。
