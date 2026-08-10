# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — elc-audit-engine MVP

**Shipped:** 2026-08-10
**Phases:** 13（12 complete＋Phase 10 外部阻塞） | **Plans:** 25 | **Tasks:** 38 | **Commits:** 164
**Timeline:** 2026-07-29 → 2026-08-10（12 天）

### What Was Built
- 獨立電子抽審引擎：三解析器（申報 XML/核減清單/SOAP）＋規則庫（SQLite 14k 碼＋樹狀索引＋預編譯快取）＋三方比對器（醫令↔規則↔病歷）
- 兩條輸出通道：病歷補強報告.md／申復理由草稿＋申復 XML，v1.0 新增紙本申復清單三聯 PDF
- HIS 服務化：Flask API（案件匯入/預審/申復生成/狀態機＋任務佇列）＋Phase 4 病歷時間軸生產路徑接入（LocalFileProvider）
- 測試基線 438 passed / 2 skipped（440 collected），端到端測試五層 1-4 完整

### What Worked
- **INSERTED 小數 phase（09.1、11.1）有效**：milestone 中段稽核發現的整合缺口以「after N」插入階段快速閉合，不重排既有 phase 編號，語意清晰
- **第 2 輪稽核重新判定價值高**：把「Phase 4 未接入」從「屬 Phase 10 外部阻塞」誤判更正為「本機可修的整合缺口」——稽核核實程式碼而非信任 phase 宣告
- **誠實降級原則貫徹**（缺欄留空＋警告、infra 故障穿透 500 不偽裝）：「不捏造」成為跨 phase 的穩定語意，測試也以此為錨
- **plan-checker 對抗性驗證抓到真問題**：generate 端點病歷號無真實來源、既有測試斷言衝突——兩者都在執行前修正，避免測試通過但斷鏈仍在的假綠

### What Was Inefficient
- **audit 第 1 輪把 BLOCKER-1 誤分類為外部阻塞**，導致該缺口拖延到第 2 輪才修——分類時未核實 LocalFileProvider 為純本機交付物
- **W5 契約橋在 09.1 只修了一半**（加了轉換層但缺欄映射），第 2 輪才升級為 BLOCKER-2——部分修復未做端到端驗證就宣告解決
- **REQUIREMENTS.md 文件債累積**：多個 REQ 缺 Status 欄位、REQ-project-skeleton 誤標 NOT STARTED——稽核時需要手動重建 traceability

### Patterns Established
- **透傳型補欄**：上游只透傳不轉型（None 照印），下游映射層負責轉換——單一關注點拆分，避免 server 層造 orders list
- **records_source 四態**（ok/absent/unconfigured/no_record_no）：「已查詢病患缺席」vs「來源未設定」明確區分，前端可見
- **整合鏈測試必須走真實資料流**：不得用手工完整 fixture 繞過斷裂環節（11.1 Success Criteria 4）
- **Provider 具現化＋狀態解析抽共用 helper**：audit/generate 兩端點同一語意

### Key Lessons
1. 跨 phase 整合檢查必須核實程式碼（grep 呼叫端），不能只信任 phase 的 SUMMARY 宣告——「各 phase 自己測試綠燈，接起來卻斷」是最高發作率的失敗模式
2. 契約橋（payload↔submission）的修復必須端到端驗證（真實資料流），部分修復（如只加轉換層不補欄位映射）比不修更難察覺
3. INSERTED 小數 phase 是閉合稽核缺口的正確機制——但閉合後應重跑全量稽核確認無新缺口
4. plan-checker 的 BLOCKER 幾乎都是真的，執行前修比執行後修省一個完整 cycle

### Cost Observations
- Model mix：規劃與驗證用 opus/sonnet 混合，執行用 sonnet；planner=opus、executor/verifier/checker=sonnet
- Sessions：11 個 phase 各自獨立 session（/clear 後 fresh context）
- Notable：11.1 的 2 個 executor 在 reasonix 沙箱下無法 commit（.git 唯讀），改由 orchestrator 代執行建議 commit 序列——功能無影響，但 per-task commit 協定需宿主配合

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | 11+ | 13 | 稽核驅動的 INSERTED 閉合 phase；plan-checker 對抗性驗證導入 |

### Cumulative Quality

| Milestone | Tests | Base | Zero-Dep Additions |
|-----------|-------|------|-------------------|
| v1.0 | 440 collected（438 passed / 2 skipped） | 374（Phase 11 前） | 紙本 PDF 鏈（pypdf）、Flask API、Provider 接線全為既有依賴 |

### Top Lessons (Verified Across Milestones)

1. 整合缺口靠稽核抓、靠 INSERTED phase 閉合、靠端到端測試驗證——三環缺一不可
2. 「不捏造」語意（缺欄留空＋警告、故障穿透）是資料誠實性的根基，測試必須錨定它
