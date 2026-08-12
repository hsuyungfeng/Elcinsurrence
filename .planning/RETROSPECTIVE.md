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

## Milestone: v1.1 — 紙本→數位化整合三項輸出

**Shipped:** 2026-08-11（audit gap 修復收尾 2026-08-12）
**Phases:** 3 | **Plans:** 7 | **Tasks:** 13 | **Commits:** 36（v1.0 tag → HEAD）
**Timeline:** 2026-08-10 → 2026-08-12（3 天）

### What Was Built
- 影像佐證上傳（`attachment_store.py`：Magic Bytes 驗證＋路徑安全＋HEIC 支援），`has_attachment`/`p7` 由實體檔案真實驅動
- 核減明細原格式列印（ODT ElementTree 動態列展開＋soffice headless PDF），CLI＋API 雙通道
- 審核軌跡＋病歷摘要＋申復理由＋影像佐證包合成 PDF（python-docx＋Pillow＋pypdf），CLI＋API 雙通道
- 測試基線由 458 提升至 460 passed（新增 2 個 case_seq/case_id 迴歸測試），2 skipped，0 failed

### What Worked
- **milestone-close 稽核在完成前一次抓到真實跨 phase 缺陷**：REQUIREMENTS.md／VERIFICATION.md 兩份標準文件都缺失（此 milestone 未經過 `/gsd-new-milestone` 標準流程），仍以 SUMMARY.md frontmatter＋live 程式碼直讀重建 3-source cross-reference，未讓文件債擋住稽核品質
- **稽核發現後立即修復再重新稽核**：發現 gap → 直接讀程式碼驗證（不只信 subagent 報告）→ 修復＋補迴歸測試 → 更新 audit 文件為 passed → 才進入 archive，形成單 session 內的完整閉環
- **v1.0 的「不可只信 SUMMARY 宣告」教訓在 v1.1 重演並被抓住**：Phase 12→14 的 `case_id`/`case_seq` 混用正是同一失敗模式（各 phase 自己測試綠燈，接起來卻斷），這次稽核步驟本身就是為此設計，確實攔下了

### What Was Inefficient
- **v1.1 從未建立 REQUIREMENTS.md**：三個 phase 直接從 ROADMAP.md 的 `Requirements:` 行規劃執行，跳過了標準的需求訪談/追溯表建立步驟，導致 milestone-close 稽核時必須手動重建 traceability（比 v1.0 當時「REQUIREMENTS.md 文件債累積」教訓還退一步——這次是完全沒建立，不是建立後維護不佳）
- **Phase 12 的 VALIDATION.md 簽核清單從未 flip 到 approved**（仍顯示 `status: draft`／`nyquist_compliant: false`），與 SUMMARY.md 記錄的實際完成狀態不符，直到 milestone 稽核才被發現並記錄為 tech debt——執行時的簽核步驟被跳過但沒有任何 gate 擋下它

### Patterns Established
- **case_id vs case_seq 是兩個獨立、可為 null 的欄位**：任何跨 phase 功能若涉及案件識別，必須明確選定其中一個作為 key space 並在程式碼中一致使用，不能假設兩者同值
- **稽核 3-source cross-reference 在缺少標準文件時仍可執行**：SUMMARY.md frontmatter（`requirements-completed`）＋ROADMAP.md 的 per-phase `Requirements:` 行＋live 程式碼直讀，三者可在無 REQUIREMENTS.md/VERIFICATION.md 時重建等效的追溯證據

### Key Lessons
1. v1.0 的核心教訓（跨 phase 整合須核實程式碼，不能信 SUMMARY 宣告）不是一次性修復，是需要每個 milestone 稽核步驟持續執行的常設檢查——這次它確實抓到了新的一次同類缺陷
2. 標準流程被跳過（未建立 REQUIREMENTS.md、未完成 VALIDATION.md 簽核）不會讓功能不能用，但會讓「這功能真的做完了嗎」在缺乏稽核時失去可驗證性——省下的規劃時間會在收尾稽核時以「重建追溯表」的形式付出
3. 發現真實缺陷後，同一 session 內修復＋補測試＋更新稽核文件，比留給下一個 milestone 當 known gap 更符合這類資料遺失風險（醫療佐證包漏附件）的嚴重度

### Cost Observations
- Model mix：整合稽核用 gsd-integration-checker (sonnet)；修復＋測試由 orchestrator 直接執行（未額外派 executor）
- Sessions：1 個 session 內完成 resume → audit → gap 修復 → milestone complete 全流程
- Notable：background subagent 的 SendMessage resume 機制在此 session 中多次僅回覆「Task complete」而未重新輸出完整報告內容——最終改用直接讀取 subagent transcript JSONL 並以 Python 解析取出目標文字區塊取得報告全文；未來若需 subagent 重新輸出已完成的報告，直接請求「輸出報告的實際內容」可能仍不可靠，讀 transcript 是更穩健的 fallback

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | 11+ | 13 | 稽核驅動的 INSERTED 閉合 phase；plan-checker 對抗性驗證導入 |
| v1.1 | 1 | 3 | 單 session 內完成 audit→gap 修復→milestone close 全流程；REQUIREMENTS.md 標準流程首次被跳過 |

### Cumulative Quality

| Milestone | Tests | Base | Zero-Dep Additions |
|-----------|-------|------|-------------------|
| v1.0 | 440 collected（438 passed / 2 skipped） | 374（Phase 11 前） | 紙本 PDF 鏈（pypdf）、Flask API、Provider 接線全為既有依賴 |
| v1.1 | 462 collected（460 passed / 2 skipped） | 440（v1.0 後） | 影像佐證（pillow_heif）、DOCX 生成（python-docx）全為既有依賴；無新增外部套件 |

### Top Lessons (Verified Across Milestones)

1. 整合缺口靠稽核抓、靠 INSERTED phase 閉合、靠端到端測試驗證——三環缺一不可
2. 「不捏造」語意（缺欄留空＋警告、故障穿透）是資料誠實性的根基，測試必須錨定它
3. 「跨 phase 整合須核實程式碼，不能信 SUMMARY 宣告」在 v1.0 與 v1.1 各抓到一次同類缺陷（v1.0：Provider 未接生產路徑；v1.1：case_id/case_seq 混用）——這是常設檢查，不是一次性修復
