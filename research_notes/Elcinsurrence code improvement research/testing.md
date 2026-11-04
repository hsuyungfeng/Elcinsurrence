# 測試覆蓋、測試品質與開發工具研究

研究範圍：`/home/hsu/Desktop/Elcinsurrence`（分支 `feat/phase-17-evidence-vault`）。僅讀取程式碼與設定，未執行測試；`.venv/`、`graphify-out/` 未納入。

方法說明：
- 模組對應以「import 比對」為主（搜尋 `elc_audit_engine.<模組>` 與 `from elc_audit_engine... import <名稱>`），並以檔名比對輔助。純檔名比對會漏判（例如 `test_gold_standard.py` 對 `gold_standard.py`），因此以 import 結果為準。
- 統計規模：`src/elc_audit_engine/` 下非 `__init__.py` 的模組共 103 個；`tests/` 下 `test_*.py` 共 67 個（約 862 個 `def test_`）；`doc/tests/` 下 26 個（約 108 個 `def test_`）。
- 「直接 import」只代表有測試以該模組路徑匯入；經由 HTTP 路由或套件 `__init__` re-export 間接覆蓋者，另列於下方說明。

---

## Key Question 1：哪些原始碼模組沒有直接測試檔？

### Takeaway
沒有任何 coverage 工具可量化缺口。以 import 比對，約 23 個非 `__init__` 模組在測試中沒有直接 import（其中部分經套件 re-export 或 HTTP 路由間接覆蓋）。本分支新增或變動的模組中，`appeal_linkage.py` 與 `sampling_closed_loop.py` 的覆蓋情況差異很大：前者只靠 API 整合測試間接覆蓋，後者有專屬單元測試。

### Cited Findings
- 分支新增模組 `evidence_vault.py` 有專屬測試 `tests/test_evidence_vault.py`（約 30+ 個測試，含 zip 炸彈、路徑穿越、symlink 逃逸、API 驗證）；`evidence_vault.py` 的上限常數為 `MAX_ZIP_MEMBERS = 500`、`MAX_MEMBER_BYTES`、`MAX_ZIP_TOTAL_BYTES`（[evidence_vault.py:38-40](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/evidence_vault.py#L38-L40)），測試以 `monkeypatch.setattr(ev, "MAX_ZIP_MEMBERS", 2)` 覆寫（[test_evidence_vault.py:141-142](/home/hsu/Desktop/Elcinsurrence/tests/test_evidence_vault.py#L141-L142)），覆蓋良好。
- `sampling_sampler.py`、`sampling_preview.py`、`sampling_closed_loop.py`、`unified_review_report.py` 各有對應的 `tests/test_sampling_*.py` 或 `tests/test_unified_review_report.py`（`sampling_closed_loop` 由 `from elc_audit_engine import sampling_closed_loop as loop` 直接匯入，見 [test_sampling_closed_loop.py:10](/home/hsu/Desktop/Elcinsurrence/tests/test_sampling_closed_loop.py#L10)）。
- `appeal_linkage.py`（212 行，分支新增的第 2→3 階申復連動）**沒有任何測試直接 import**。唯一覆蓋來自 `tests/test_phase20_stage_batch.py` 的 API 測試（如 [test_phase20_stage_batch.py:191](/home/hsu/Desktop/Elcinsurrence/tests/test_phase20_stage_batch.py#L191)、[:209](/home/hsu/Desktop/Elcinsurrence/tests/test_phase20_stage_batch.py#L209)、[:249](/home/hsu/Desktop/Elcinsurrence/tests/test_phase20_stage_batch.py#L249)）。這些測試透過 HTTP 走完整路徑，失敗時難以定位到 `link_stage2_to_appeal` 的分支（例如 `seed=None` 的隨機分支，見 [appeal_linkage.py:35](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/appeal_linkage.py#L35) 與 `random.Random(seed)`，測試皆傳入固定 seed，[test_phase20_stage_batch.py:193](/home/hsu/Desktop/Elcinsurrence/tests/test_phase20_stage_batch.py#L193)）。
- `bridge_queue.py`（146 行）無直接 import，僅由 `tests/test_bridge_api.py` 透過 `/api/bridge` 路由間接覆蓋（路由在 [api/routes/bridge.py:15](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/bridge.py#L15) 匯入 `bridge_queue`）。
- 路由層：`api/routes/appeal.py`（450 行）、`monthly.py`（326 行）、`rules.py`（97 行）、`vault.py`（88 行）、`_lists.py`、`misc.py` 皆無直接 import；以 URL 字串計算，`/api/appeal` 出現於 12 個測試檔、`/api/sampling` 於 17 個、`/api/monthly` 於 3 個、`/api/rules` 僅於 1 個（`test_rules_api.py` 另以路徑組合呼叫）。`api/routes/sampling.py`（752 行，分支新增變動最大的路由）由多個測試間接覆蓋，但沒有 route 級別的專屬測試檔。
- 以 import 比對無直接覆蓋者（未逐一判斷是否間接覆蓋）：`api/context.py`、`api/demo_data.py`、`api/errors.py`、`api/validation.py`、`case_store/db.py`、`comparator/support.py`、`generators/tracking.py`、`ingest/zip_support.py`（`tests/test_zip_import.py` 經 API 間接覆蓋）、`rule_repository/scripts/build_docx_trees.py`。`scripts/build_chroma_index.py` 由 `doc/tests/test_build_chroma_index_script.py` 直接覆蓋（該檔 [:3](/home/hsu/Desktop/Elcinsurrence/doc/tests/test_build_chroma_index_script.py#L3)）。
- `case_store/` 子目錄：`store.py`（591 行）、`monthly.py`、`states.py` 有覆蓋（`test_case_store.py`、`test_case_states.py`、`test_monthly_*`）；`case_store/db.py`（135 行）沒有直接 import，只被 `rule_repository` 相關測試的字串匹配誤中，實際覆蓋需 coverage 確認。
- `monthly_*.py`：`monthly_audit.py`、`monthly_pregen.py`、`monthly_reasoning.py`、`monthly_report_html.py` 皆有對應測試檔（`test_monthly_*.py`）。

### Inferences
- 分支新增的 `appeal_linkage.py` 缺少單元測試是最明顯的缺口：其有分支邏輯（排序、seed 抽樣、重複建案偵測 `duplicates`、規則庫錯誤傳遞），但目前只能靠整合測試驗證，回歸定位成本高。
- 路由檔案普遍以 HTTP 整合測試覆蓋，這在 Flask 專案中是合理做法，但 `api/routes/sampling.py`（752 行）與 `appeal.py`（450 行）體量大，缺少以 `test_client` 為單位的分組測試檔，後續修改時難以判斷哪些端點受影響。

### Gaps
- 沒有 coverage 數據，無法給出行覆蓋率百分比。依 `pyproject.toml` 與 `uv.lock`，專案未安裝 `pytest-cov` 或 `coverage`（見 Key Question 3）。
- 本研究未執行測試，無法確認間接覆蓋的實際分支覆蓋率。

---

## Key Question 2：哪些測試依賴真實檔案系統、網路、LibreOffice、OCR 或外部服務？是否能乾淨略過？

### Takeaway
多數環境相依測試都有 `skipif` 保護，但仍有數個關鍵問題：`test_zip_import.py` 直接讀取 `data/TOTFA.zip`（以 CWD 相對路徑）且**沒有** skip 保護；`test_monthly_reasoning.py` 與 `test_totfa_rule_matching.py` 依賴 63MB 的真實 `data/db/rules.sqlite3`（有 skip，但會靜默跳過）；`test_llama_smoke.py` 在 collection 階段就會做 HTTP 探測。LibreOffice 相關測試皆有 skip，但 soffice 不存在時會整批跳過，CI 環境無法確認覆蓋。

### Cited Findings
- `tests/test_zip_import.py` 直接以相對路徑開啟 `data/TOTFA.zip`：[test_zip_import.py:38](/home/hsu/Desktop/Elcinsurrence/tests/test_zip_import.py#L38)、[:52](/home/hsu/Desktop/Elcinsurrence/tests/test_zip_import.py#L52)。兩處都沒有 `skipif`，若從非專案根目錄執行或檔案不存在，會直接以 `FileNotFoundError` 失敗（而非 skip）。
- 同一類真實資料測試其他檔案有 skip：`test_totfa_monthly.py:287`（`REAL_ZIP`）、`test_totfa_rule_matching.py:500`（`REAL_RULES`）、`test_monthly_reasoning.py:236`（`REAL_RULES`），皆以 `os.path.exists` 判斷後 `skipif`。`REAL_RULES` 指向 `data/db/rules.sqlite3`（[test_monthly_reasoning.py:35](/home/hsu/Desktop/Elcinsurrence/tests/test_monthly_reasoning.py#L35)），目前本機該檔約 63MB。
- `tests/test_submission_xml_parser.py:24` 與 `:233` 以 `REAL_FILE = ".../TOTFA.xml"` 搭配 `skipif(not os.path.isfile(...))`。
- LibreOffice 相關：`requires_soffice = pytest.mark.skipif(...)` 出現於 `test_doc_converter.py:17`、`test_evidence_packet_pdf.py:8`、`test_deduction_print.py:92`、`test_docx_tree_coverage.py:18`、`test_appeal_print.py:23`；`doc/tests/test_warnings_conversion.py:70` 以 `shutil.which("soffice")` 判斷。`test_deduction_print.py:106` 另有執行期 `pytest.skip("Real template missing")`。`test_appeal_print.py:21` 的註解說明 soffice 只影響轉檔段落。
- OCR：`tests/test_table_ocr.py` 以 `_TABLE_HTML` 字串直接測解析（不呼叫真實引擎），[:29](/home/hsu/Desktop/Elcinsurrence/tests/test_table_ocr.py#L29) 斷言 `result.source == "paddle"`，屬於純解析測試，乾淨。`src/elc_audit_engine/ingest/table_ocr.py:60` 才會 `from paddleocr import PPStructureV3`，但測試未涵蓋此匯入路徑（無 `importorskip`，`grep` 未找到任何 `importorskip`）。`tests/test_ingest.py:319` 以假函式回傳 `"tesseract"`，屬於 mock。
- 網路：
  - `tests/test_llama_smoke.py:21` 設定 `pytestmark = pytest.mark.live_llm`（預設被 `addopts` 排除）。但 `:26-30` 的 `_llama_server_is_up()` 在 **decorator 求值時**（模組 import 時，即 collection 階段）就會呼叫 `requests.get(f"{LLAMA_CPP_BASE_URL}/health", timeout=3)`（[test_llama_smoke.py:39-43](/home/hsu/Desktop/Elcinsurrence/tests/test_llama_smoke.py#L39-L43)）。因此即使 `-m "not live_llm"` 排除了該測試，每次 pytest 收集仍會發出一次 HTTP 探測，且最長可能等待 3 秒。
  - `tests/conftest.py:130` 的 autouse fixture `_offline_llm` 會把 LLM 呼叫站替換為立即拋出 `requests.ConnectionError` 的假函式（[conftest.py:118-141](/home/hsu/Desktop/Elcinsurrence/tests/conftest.py#L118-L141)），設計良好，可確保預設測試不連網。
  - `tests/test_his_integration_api.py:230-261` 以 `monkeypatch.setattr(his_integration.urllib.request, "urlopen", ...)` 替換網路呼叫，屬於正確的隔離。
  - `tests/test_config.py:14-15` 斷言 `LLAMA_CPP_BASE_URL == "http://localhost:8080"`，依賴環境變數未被覆寫，屬於環境相依斷言。
  - `doc/tests/test_info_security.py:31` 以 `localhost` 字串做參數化，不是真的連線。
- 永久跳過的測試：`tests/test_chroma_store.py:119-122` 的 `@pytest.mark.skipif(True, reason="Network-dependent best-effort test: requires ONNX embedding model download...")` 永遠不會執行；同檔 `:176-179` 也是 `skipif(True, ...)`。這兩個測試等同於停用，且理由是「需要網路下載模型」，若要保留應改為依環境變數或 marker 控制（例如 `live_embedding`）。
- 專案中沒有任何 `xfail` 標記（`grep` 未找到）；`skipif` 裝飾器合計約 13 處（含上列 LibreOffice、真實資料、LLM、ChromaDB 測試）；`pytest.skip(` 僅 `test_deduction_print.py:106` 一處。
- 測試使用真實 `data/` 路徑的其他位置：`tests/test_zip_import.py` 之外，`data/` 目錄在 `.gitignore` 中多數子目錄已忽略，但 `data/TOTFA.zip` 目前由 git 追蹤（`git ls-files` 可見 `data/TOTFA.zip`），而 `.gitignore:45-47` 規定 `TOTFA.xml` 與 `*.xml` 皆不入版控（註解稱為「真實病患資料（PHI）」）。`data/TOTFA.zip` 內僅含一個 `TOTFA.xml`，大小 795681 bytes，與專案根目錄的 `TOTFA.xml`（795681 bytes）相同。**這是一個需要人工確認的資料外洩風險**：若該 XML 為真實申報資料，則已被 git 追蹤的 zip 等於繞過 `.gitignore` 的 PHI 進版控。研究未解開內容確認是否為真實病患資料，僅依大小與註解判斷。
- `tests/conftest.py:18` 以 `os.environ.setdefault("ELC_API_KEYS", ...)` 設定測試用金鑰；此為 process 級全域變數，但因為是 `setdefault` 且測試檔再以 `monkeypatch` 覆寫 `app.config`，影響可控。
- `config/settings.py:9-13`、`:29`、`:38`、`:44` 在 import 時讀取 `DATA_DIR`、`DB_DIR`、`RECORDS_DIR`、`AUDIT_LOG_PATH`、`ATTACHMENTS_DIR` 等環境變數。多數測試以 `monkeypatch.setattr(settings, "DATA_DIR", ...)` 替換（如 [test_evidence_vault.py:21](/home/hsu/Desktop/Elcinsurrence/tests/test_evidence_vault.py#L21)、[test_sampling_closed_loop.py:193](/home/hsu/Desktop/Elcinsurrence/tests/test_sampling_closed_loop.py#L193)），屬於正確做法。但 `evidence_vault.py:93-95` 的註解說明「每次呼叫時讀取 settings」，因此替換有效；其他模組若在 import 期快取路徑，替換會失效（未逐一確認）。

### Inferences
- `test_zip_import.py` 是唯一沒有 skip、又依賴真實檔案的測試，且因為 `.gitignore` 與 git 追蹤狀態不一致，在 clone 乾淨倉庫時只會因檔案存在而通過，但仍會把 PHI 樣本的內容送進 `/api/sampling/import` 與 `/api/appeal/import`。
- 目前 `tests/` 的「預設跑法」仍依賴 `data/db/rules.sqlite3`（63MB）與 `data/TOTFA.zip`。在乾淨環境（只有 `git clone`）中，這些 skip 會讓覆蓋率下降而不報錯，容易誤以為全數通過。

### Gaps
- 無法在不執行測試的前提下確認 `skip` 數量實際值（`pytest -rs` 才能看到）。
- 未確認 `data/TOTFA.zip` 的 XML 內容是否真為病患資料（研究限定不執行、不解析真實資料）。
- 未確認 LibreOffice (`soffice`) 與 PaddleOCR 在目前機器上是否可用，因此無法判斷 skip 是否會實際發生。

---

## Key Question 3：是否設定 coverage 工具？缺口大約多少？

### Takeaway
專案沒有任何 coverage 設定：`pyproject.toml` 無 `[tool.coverage]`，`uv.lock` 中找不到 `pytest-cov` 或 `coverage` 套件。因此無法給出實際行覆蓋率數字。以模組 import 比對估算，約 23/103 個非 `__init__` 模組沒有直接 import（約 22%），但實際覆蓋應以 coverage 量測確認。

### Cited Findings
- `pyproject.toml` 的 `[tool.pytest.ini_options]` 只有 `testpaths = ["tests"]`、`addopts = '-m "not live_llm"'` 與 `markers`（[pyproject.toml:44-50](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L44-L50)），沒有 `--cov` 或 `[tool.coverage.run]`。
- `pyproject.toml:31-34` 的 `[dependency-groups] dev` 只有 `pypdf>=6.15.0` 與 `pytest>=8.0`。
- `uv.lock` 搜尋 `pytest-cov`、`coverage`、`ruff`、`mypy`、`pre-commit` 皆無對應 `name =` 條目（僅有 `pytest` 9.1.1，見 `uv.lock:2615`）。
- 但 `tests/__pycache__` 中同時存在 `pytest-8.3.5` 與 `pytest-9.1.1` 的 `.pyc`（如 `tests/__pycache__/test_sampling_sampler.cpython-312-pytest-8.3.5.pyc`），顯示本機曾用不同 pytest 版本跑過測試，與 lock 不一致。
- `doc/tests/` 共 26 個測試檔（約 108 個 `def test_`）**不在** `testpaths` 內（`pyproject.toml:45` 只有 `tests`），預設 `pytest` 指令不會執行。`README.md`/`AGENTS.md` 是否已說明須另外執行 `pytest doc/tests`，本研究未檢視（僅見 `doc/tests/conftest.py:4` 註解寫「執行：uv run pytest doc/tests」）。

### Inferences
- 缺少 coverage 量測，使得「哪些分支沒測」只能靠人工判斷；對分支新增的 `appeal_linkage.py`、`sampling_*`、`evidence_vault.py` 尤其難以評估。
- `doc/tests/` 未納入預設路徑，等於 108 個回歸測試有可能被忽略，屬於高優先的工具缺口。

### Gaps
- 無法量測行覆蓋率與分支覆蓋率。建議後續以 `uv add --dev pytest-cov` 後執行 `pytest --cov=elc_audit_engine --cov-report=term-missing`，但本研究未執行。

---

## Key Question 4：`pyproject.toml` 的依賴是否合理？是否有版本衝突或不可重現的風險？

### Takeaway
執行期依賴有 **實際漏宣告**：`pypdf` 只列在 dev 群組，但 `src/` 的 runtime 模組在頂層 import 它；`Pillow` 完全未直接宣告，卻被 src 直接 import。`uv.lock` 有釘住實際版本，可重現性尚可，但 `pyproject.toml` 本身多為下限（`>=`），不鎖主要套件。

### Cited Findings
- `pypdf` 只在 dev 群組：[pyproject.toml:31-34](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L31-L34)。但執行期程式碼直接使用：
  - [src/elc_audit_engine/attachment_store.py:22](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/attachment_store.py#L22) `from pypdf import PdfReader`（頂層 import）
  - [src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py:4](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py#L4) `from pypdf import PdfReader, PdfWriter`
  - 因此以 `uv sync --no-dev`（或 production 只裝 `[project].dependencies`）安裝後，`attachment_store` 與 PDF 匯出會 `ImportError`。
- `Pillow` 未宣告：src 直接 import `PIL`（[attachment_store.py:20](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/attachment_store.py#L20)、[generators/evidence_packet/image_processor.py:2](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/evidence_packet/image_processor.py#L2)、[unified_review_report.py:283](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/unified_review_report.py#L283)）。目前僅因 `pillow-heif` 間接依賴 `pillow` 而可用（`uv.lock` 有 `pillow` 條目，約 `uv.lock:1971`），屬隱性依賴。
- `pyproject.toml` 註解（[:6-11](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L6-L11)）說明 P0-2 依賴漂移曾發生過（`flask` 被誤刪），顯示團隊已意識到依賴宣告問題，但 `pypdf` 與 `Pillow` 仍未修正。
- 下限宣告：`chromadb>=0.4.0`（[pyproject.toml:15](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L15)）範圍極寬，`uv.lock` 實際為 `chromadb` 1.5.9；若刪除 lock 重新解析，主版本 1.x 與 0.4.x 行為差異大。`python-docx>=1.1.0` 實際鎖定 1.2.0；`flask>=3.0` 鎖定 3.1.3；`requests>=2.28` 鎖定 2.34.2。
- OCR 可選依賴釘版：`paddlepaddle==3.2.2`、`paddleocr==3.7`、`paddlex[ocr]>=3.7,<3.8`（[:24-29](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L24-L29)），並附註 3.3.1 有 bug（與 `deepflash4improve.md` §8.2 相關）。此為良好實踐。
- `uv.lock` 為 `version = 1`、`revision = 3`，已存在 Python 3.12 限定；`.python-version` 為 `3.12`。
- `pyproject.toml` 中 `[project]` 無 `requires-python` 之外的上限（[pyproject.toml:5](/home/hsu/Desktop/Elcinsurrence/pyproject.toml#L5)），`requires-python = ">=3.12"` 合理。

### Inferences
- 目前的可重現性主要依賴 `uv.lock`；只要 lock 存在且使用 `uv sync --locked`，安裝結果一致。但 `pypdf` 漏宣告會讓「只裝 runtime 依賴」的部署在 import 時才爆錯，風險不易被測試發現（測試環境有 dev 群組，永遠裝得到 pypdf）。
- 測試環境與部署環境的依賴差異，正是 `pypdf` 漏宣告的根源：本專案的 `tests/` 會安裝 dev 群組，因此沒有暴露此問題。

### Gaps
- 未實際執行 `uv sync --no-dev` 驗證 ImportError（依研究限制不執行），此結論來自程式碼與宣告的靜態比對。
- 未檢視 `uv.lock` 的完整依賴樹是否有衝突（例如 `chromadb` 與 `onnxruntime` 版本），因 lock 檔超過 3,700 行且僅需確認摘要。

---

## Key Question 5：是否有 CI 或 pre-commit hooks？缺少什麼？

### Takeaway
專案**沒有任何 CI 或 pre-commit 設定**：無 `.github/`、無 `.pre-commit-config.yaml`、無 `tox.ini`、`setup.cfg`、`pytest.ini`、`Makefile`、`noxfile.py`，`.git/hooks/` 中只有 sample 檔。Linter ruff 沒有任何專案設定（無 `[tool.ruff]`、無 `ruff.toml`），雖然 repo 中存在 `.ruff_cache/`，表示曾在本機執行過，但使用的是 ruff 預設規則。

### Cited Findings
- 檢查結果：`ls .github` 不存在；`.pre-commit-config.yaml`、`tox.ini`、`setup.cfg`、`pytest.ini`、`.coveragerc` 皆不存在；`find` 未找到 `Makefile` 或 `noxfile.py`；`.git/hooks/` 僅有 `*.sample`。
- `pyproject.toml` 無 `[tool.ruff]` 區段（`grep` 結果為空）。`.ruff_cache/` 存在於專案根目錄（時間戳 `Oct 28`），顯示有執行過 ruff。
- `.gitignore` 內容涵蓋 PHI 與本機資料（`data/evidence_vault/`、`*.sqlite3`、`data/audit/` 等，見 [.gitignore](/home/hsu/Desktop/Elcinsurrence/.gitignore)），但經 `grep` 確認未包含 `.ruff_cache/`、`.pytest_cache/`、`.coverage`、`htmlcov/` 等工具產物條目。
- 測試設定層面缺少的工具（以 `uv.lock` 比對）：`ruff`、`mypy`、`pytest-cov`、`pytest-timeout`、`pre-commit` 皆未列於 dev 群組。

### Inferences
- 缺 CI 意味著 `doc/tests/`（108 個測試）、`live_llm` 以外的 skip 情況、以及依賴漂移，都沒有自動化把關。
- 缺 pre-commit 意味著 PHI 相關檔案（如 `data/TOTFA.zip`）若誤加入，沒有 hook 攔截。結合 Key Question 2 的發現，這是實際風險。
- 建議的最小工具鏈（僅列出缺口，不實作）：
  - `[tool.pytest.ini_options]` 加上 `testpaths = ["tests", "doc/tests"]` 或另建 CI 工作。
  - `[tool.ruff]` 指定 `line-length`、`select`（至少 `E`, `F`, `I`, `B`），並以 `ruff check` 與 `ruff format --check` 作為 CI 步驟。
  - `[tool.coverage.run]` 與 `fail_under`，並以 `pytest-cov` 量測。
  - `.pre-commit-config.yaml`：包含 `ruff`、`detect-private-key`、以及針對 `data/**`、`*.xml`、`*.zip` 的自訂攔截（防止 PHI 進版控）。
  - CI（如 GitHub Actions）：以 `uv sync --locked` 安裝、執行 `pytest`、`pytest doc/tests`、`ruff check`，並確認 `live_llm` 不會被誤跑。

### Gaps
- 未檢視 `README.md`（37 KB）與 `AGENTS.md` 是否描述了本機執行測試或 lint 的手動流程，因此無法確認是否僅靠文件約定。
- 本機是否設定了全域 git hooks（`core.hooksPath`）未檢查。

---

## 其他測試品質發現

### 弱測試與斷言品質
- 專案 862 + 108 個測試函式，僅 0 個測試檔「完全沒有 assert」（以 `assert`、`pytest.raises`、`.status_code` 任一關鍵字計算）。
- `grep` 發現約 24 處 `assert ... is not None` 結尾的斷言（僅檢查存在性），例如 `tests/test_rule_repository_models.py` 等。此類斷言在結果為空時仍會通過不一定能抓到錯誤，但數量不大，不構成系統性問題。
- 未發現 `assert True`（`grep` 無結果）。
- `tests/test_evidence_packet_pdf.py` 含 mock、patch 或 monkeypatch 的行數約 43 行（以關鍵字計數，含 monkeypatch），但 assert 只有 12 行（4 個測試函式），屬於 mock 比例偏高的測試，可能過度依賴替身而未驗證實際 PDF 輸出內容。研究未逐行確認其 mock 是否掩蓋真實行為。
- `tests/test_attachment_store.py` 以 3 個測試、5 個 assert、6 處 mock 運作，比例偏高，同樣值得檢視。

### 順序相依與全域狀態
- `grep` 未找到 `global` 宣告或 `sys.modules[...]` 直接操作於 `tests/` 與 `doc/tests/`。
- `tests/conftest.py` 的 `_offline_llm` 以 `monkeypatch` 替換，會在測試結束時還原，屬於隔離良好的寫法。
- `tests/test_sampling_sampler.py:108` 以 `for s in range(200)` 搜尋一個會讓 `top_id` 被抽中的 seed，屬於決定性的 brute-force 搜尋，不依賴執行順序，但較脆弱：若 `sample` 的演算法或輸入順序改變，搜尋可能找不到 seed 而導致 `StopIteration`。
- `tests/test_phase20_stage_batch.py:73` 使用 `"seed": 42`，`:193` 使用 `"seed": 7`，皆為固定 seed，符合可重現性要求。

### 時間相依
- `tests/` 與 `doc/tests/` 中未找到 `datetime.now()`、`utcnow()`、`date.today()` 或 `time.time()`（僅 `time.sleep` 未發現）。
- 測試資料中的日期多為固定字串（如 `20260710` 轉為 `2026-07-10`，見 `tests/test_table_ocr.py` 的 `_TABLE_HTML` 與 `test_parse_sampling_tables_maps_columns`），不依賴 wall-clock。
- 注意：`tests/test_reinforcement_report.py:208` 使用固定 `reviewed_at="2026-08-03T10:00:00+00:00"`，屬於決定性輸入。

### 測試檔名碰撞
- `tests/` 與 `doc/tests/` 之間沒有重複的 `test_*.py` basename（`find ... | uniq -d` 無輸出）。`tests/` 有 `__init__.py`，`doc/tests/` 沒有，兩者的 rootdir/conftest 機制不同，目前不會衝突，但若日後在 `doc/tests` 加入同名檔案，會因 `rootdir` 差異出現 import mismatch。

### 其他
- `tests/test_config.py:14-15` 斷言預設的 `LLAMA_CPP_BASE_URL`，依賴環境變數未被設定；若開發者在 `.env` 或 shell 中設定了不同值，測試會失敗。
- `tests/test_totfa_rule_matching.py:46` 與 `test_monthly_reasoning.py:35` 把 `REAL_RULES` 指向 `data/db/rules.sqlite3`，該檔為本機產物（`.gitignore` 含 `data/db/*`），不應被視為測試的一部分。
- `tests/test_zip_import.py` 雖位於 `tests/` 但與 `tests/conftest.py` 的 `app_client` fixture 之間的依賴未在檔案中說明（本研究未逐行確認 `app_client` 定義位置）。

---

## 優先建議（依風險排序，僅列出，不實作）

1. **確認 `data/TOTFA.zip` 是否含真實病患資料**，若是，應自 git 歷史移除並加入 `.gitignore`（目前 `git ls-files` 仍追蹤）；同時修正 `tests/test_zip_import.py:38,52` 改用 fixture 或加上 skip。
2. **將 `pypdf`（以及明確宣告 `pillow`）移至 `[project].dependencies`**，因為 `attachment_store.py:22` 與 `pdf_exporter.py:4` 在執行期會匯入。
3. **將 `doc/tests` 納入預設 pytest 執行路徑**（`testpaths` 或 CI 指令），避免 108 個測試被忽略。
4. **為 `appeal_linkage.py` 補上單元測試**，特別是 `seed=None` 分支、`duplicates` 回報與 `RuleRepositoryError` 傳遞。
5. **加入 `[tool.ruff]` 與 `[tool.coverage]`**，並在 `pyproject.toml` 的 dev 群組加入 `ruff`、`pytest-cov`。
6. **修正 `tests/test_llama_smoke.py:39-43`**，避免 collection 階段做 HTTP 探測（改為 fixture 或 `pytest_collection_modifyitems` 中判斷）。
7. **處理 `tests/test_chroma_store.py:119`、`:176` 的永久 `skipif(True)`**：改為環境變數或 marker 控制，並在 README 說明。
8. **新增 `.pre-commit-config.yaml` 與 CI 工作流程**，包含 ruff、pytest、doc/tests、PHI 檔案攔截。

---

## Key Question 總結對照

| 問題 | 結論 | 主要證據 |
|---|---|---|
| 哪些模組沒有直接測試 | 約 23 個（含間接覆蓋）；`appeal_linkage.py`、`bridge_queue.py` 僅間接覆蓋 | 見 Q1 |
| 環境相依與 skip 乾淨性 | 多數有 skip；`test_zip_import.py` 無 skip；`test_llama_smoke.py` collection 時探測網路 | `test_zip_import.py:38,52`；`test_llama_smoke.py:39-43` |
| coverage 工具與缺口 | 未設定；無法量測 | `pyproject.toml:44-50`；`uv.lock` 無 pytest-cov |
| 依賴宣告合理性 | `pypdf` 與 `Pillow` 漏宣告為執行期依賴；lock 釘版 | `pyproject.toml:31-34`；`attachment_store.py:20,22` |
| CI / pre-commit | 皆無；ruff 無專案設定 | 目錄檢查與 `.git/hooks` 僅 sample |
