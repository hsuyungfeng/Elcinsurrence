---
phase: 11
slug: paper-appeal-print
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-08
updated: 2026-08-10
approved: 2026-08-10
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> 資料來源：`11-RESEARCH.md` § Validation Architecture（研究階段已實證工具鏈）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1（`pyproject.toml [tool.pytest.ini_options] testpaths=["tests"]`） |
| **Config file** | `pyproject.toml`（無 pytest.ini） |
| **Quick run command** | `uv run pytest tests/test_appeal_print.py -x` |
| **Full suite command** | `uv run pytest`（Phase 11.1 完成後基線 438 passed / 2 skipped） |
| **Estimated runtime** | ~30 秒（含 soffice 端到端；soffice 不可用時該組 skip） |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_appeal_print.py -x`（或 `-k <task>`）
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green（含既有 374 基線）
- **Max feedback latency:** ~30 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | REQ-paper-appeal-print | T-11-05 | 身分證字號遮罩值照印／留空，不猜測補全 | unit | `pytest tests/test_appeal_print.py -k mapping -x` | ✅ | ✅ green |
| 11-01-02 | 01 | 1 | REQ-paper-appeal-print | T-11-01 / T-11-06 | 欄位值經 ET 文本節點寫入（自動轉義）、模板 sha256 校驗 | unit | `pytest tests/test_appeal_print.py -k odt -x` | ✅ | ✅ green |
| 11-02-01 | 02 | 2 | REQ-paper-appeal-print | T-11-04 | 檔名經 `safe_filename()` 校驗後拒絕 | unit | `pytest tests/test_appeal_print.py -k security -x` | ✅ | ✅ green |
| 11-02-02 | 02 | 2 | REQ-paper-appeal-print | T-11-02 / T-11-03 | 輸出進 `data/output/*`（gitignore）、錯誤訊息不含 PHI | integration | `pytest tests/test_appeal_print.py -k e2e -x` | ✅ | ✅ green |
| 11-03-01 | 03 | 3 | REQ-paper-appeal-print | — | 端到端：頁數＝3（×N）、關鍵欄位文本出現、三聯版式差異 | integration | `pytest tests/test_appeal_print.py -k e2e -x` | ✅ | ✅ green |
| 11-03-02 | 03 | 3 | REQ-paper-appeal-print | — | config 載入 fail-fast 與 env 覆寫 | unit | `pytest tests/test_appeal_print.py -k config -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Wave 結構為初估，實際以 PLAN.md 為準。*

---

## Wave 0 Requirements

- [x] `tests/test_appeal_print.py` — 上述全部測試檔（37 測試，mapping/odt/base/e2e/security/copies/config/cli 全綠，2026-08-10 實測 37 passed）
- [x] `tests/conftest.py` 擴充 — `requires_soffice` skip 標記（比照 test_doc_converter.py 的 `soffice_is_functional()` 真轉檔探測，見 conftest.py:23）、`facility_config` fixture（conftest.py:36）、`sample_appeal_draft()` fixture（conftest.py:59）
- [x] 依賴：`pypdf>=6.15.0`（pyproject.toml:31，dev deps）
- [x] 基準資產：`officialdocument/電子申復文件格式/30396_1_..._print_base.odt`＋`.sha256`（git 版控，VERIFICATION 實測 hash 一致）
- [x] `config/facility.json` 範例檔（測試用 fixture）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 版面與官方範本「逐欄核對一致」的**視覺**最終確認（Success Criteria 1） | REQ-paper-appeal-print | 自動化只能斷言欄位文本與頁數；行高／對齊／框線的視覺一致需人眼 | 產出一案三聯 PDF，與 `30396_4_無刪除線1050105-PDF門診診療費用申復清單-.pdf` 並排逐欄目視比對 |
| 第二聯「核定/複核/初核/審查委員」欄位留空的正確性（與 CONTEXT D-03 敘述相反，實體在第二聯） | REQ-paper-appeal-print | 屬與使用者的裁示確認，非自動化可判定 | 向使用者確認：以官方模板實體（第二聯）為準 |

*註：除上述兩項外，所有行為皆有自動化驗證。*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved（2026-08-10，執行後回填：37 passed 實測＋11-VERIFICATION 3/3 passed＋UAT 7/7）

---

## Validation Audit 2026-08-10

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

*State A 回填：11-VALIDATION.md 為規劃階段草稿快照（status: draft, nyquist_compliant: false），執行完成後實測全部 6 個 task 對應測試存在且綠（`tests/test_appeal_print.py` 37 passed），Wave 0 依賴（fixtures/pypdf/基準模板）全部落地，無 gap——回填為 approved。*
