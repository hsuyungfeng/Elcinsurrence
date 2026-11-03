# Phase 22: 核心可靠性、邊界修復與架構服務層重構

## 背景與目標
依據 `codeimproveplan.md` 的「第二波：P1 核心可靠性與邊界修正」與「第三波：P2 代碼衛生與模組重構」，Phase 22 聚焦於系統核心元件之健全性、邊界安全、自動化 CI 與超大模組服務層解耦。

本階段核心任務：
1. **地端 Agent 橋接佇列（bridge_queue.py）升級（P1-1, P1-2）**：
   - 取消記憶體端篩選與 1000 筆查詢視窗，改於 CaseStore SQL 層直接以狀態過濾與分頁。
   - 實作 `SENDING` 狀態之租約逾時自動回收機制（Lease Timeout Recovery）。
   - 實作重試計數（Retry Count）與最大重試次數限制，防止毒藥任務永久重試。
   - 加入 CAS（條件狀態更新）防範並發競態。

2. **查詢截斷揭露與例外透明度（P1-10, P1-11, P1-12）**：
   - 批次查詢超過上限時，API 回應中主動揭露 `total_count`、`truncated: true` 與 `limit`，杜絕靜默丟件。
   - 規則查詢與核心比對流程僅允許降級預期的 `RuleRepositoryError`，禁止以 `except Exception` 吞掉未預期程式錯誤。
   - 全面清理 `sampling.py` 與 `appeal.py` 中的 bare `except:`，明確指定捕獲型別。

3. **工具鏈與 CI 流程健全化（P1-13, P1-14）**：
   - 在 `pyproject.toml` 補全執行期必要依賴（`pypdf`, `Pillow`），並加入 `[tool.ruff]` 規範與 `pytest-cov`。
   - 建立 GitHub Actions CI 工作流程（`.github/workflows/ci.yml`），覆蓋 `uv sync --locked`、`ruff check` 與 `pytest`。

4. **服務層抽取與超大模組解耦（P2-1, P2-2）**：
   - 建立 `src/elc_audit_engine/services/`，拆分超過 750 行的 `routes/sampling.py` 與 860 行的 `unified_review_report.py`。
   - 抽取 `services/sampling_service.py` 處理抽樣挑選、多源證據組裝與業務流程。
   - 抽取 `services/date_utils.py` 統一全專案 8 處以上的民國/西元日期解析與轉換。
   - 維持既有 API 契約 100% 向後相容。

## 多代理人協作機制（Herdr）
在執行與驗證階段， Antigravity 將透過 Herdr 控制終端分工：
- **Claude Code (`w7:p2`)**：作為執行者（Executor），實施程式碼改寫與檔案拆分。
- **Hermes Agent (`w7:p3`)**：作為測試者（Tester），執行端點請求驗證與抽樣比對。
- **Antigravity CLI (`w7:p1`)**：作為總指揮（Orchestrator），監控 Herdr 各終端狀態、審查變更並修正缺陷（Check and Fix）。
