# Milestone v1.0 — Project Summary

**Generated:** 2026-08-08
**Purpose:** Team onboarding and project review
**Project:** elc-audit-engine（健保抽審核減自動化引擎）

---

## 1. Project Overview

`elc-audit-engine` 是一套**本地、file-in/file-out** 的健保電子抽審自動化引擎，為醫療院所自動化電子抽審流程的兩個階段：

1. **病歷補強（pre-submission）** — 抽審送審前，找出哪些醫令對支付規則缺乏病歷佐證，產生候選補強敘述供醫師逐條審核。
2. **申復生成（post-denial）** — 核減後，依規則條文與病歷證據生成申復理由草稿（p8/p9 ≤2000 字），並可輸出紙本申復清單三聯 PDF。

兩階段共享單一「醫令 ↔ 規則 ↔ 病歷」三方比對引擎，僅輸出層不同。全程本機執行（患者資料不出機器），不需院所雲端 HIS 先存在。

**Milestone 現況：** 10/11 phases 完成（Phase 1–9 + 11 全數落地），Phase 10（VPN/實機 HIS 串接）因外部依賴阻塞——對應兩階段 roadmap 的 Phase 1（獨立引擎）實質完成。

## 2. Architecture & Technical Decisions

```text
輸入層                      共用比對引擎 (Core)                     輸出層
申報XML/核減清單 ──► ①解析器 ②病歷彙整器 ③規則庫 ──► 病歷補強報告.md
SOAP 文字        ──► ④三方比對器 ⑤生成器        ──► 申復草稿.md + appeal_{流水號}.json
                                                  ──► 申復XML(Big5) + 紙本三聯PDF
```

**技術棧（沿用 DrtoolboxLocalServer 慣例）：** Python 3.12 + uv + Flask + pandas + python-docx + SQLite + ChromaDB（輔助）+ 本地 llama.cpp（Ornith-1.0-9B, n_ctx 32768, localhost:8080, OpenAI-compatible API）。

**關鍵技術決策（含執行期實證）：**

- **決策：** 規則庫三層架構（SQLite 核心欄位 + 自建 PageIndex 式 docx 樹 + rule_mapping 預編譯快取）— **Why:** 查詢零 LLM、單一 `get_rule(code)` 入口；`pageindex` PyPI 包實為付費雲 SaaS（違反 D2 本地化）改自建 — **Phase 2**
- **決策：** LLM 僅於批次建置時使用（`enable_thinking=false` 把單次呼叫 ~30s 降至 ~0.6s）；比對判定強制 JSON、失敗重試一次、再失敗降級「待人工」— **Why:** 批次建置可容忍慢、線上查詢必須快且不阻斷 — **Phase 2/5**
- **決策：** 缺欄誠實降級原則貫穿全專案（d3 病歷號、id_number 遮罩照印不重建、SOAP 無命中標 UNKNOWN、規則無匹配標「查無規則依據」）— **Why:** 醫療場域禁止猜測/捏造 — **Phase 3/5/7/11**
- **決策：** 五層測試策略（單元/規則庫驗收/LLM 金標準 30 組/端到端 3 案例/真實樣本回放），judge/narrative/rule_lookup 全可注入、測試零 LLM — **Why:** LLM 不確定性隔離，測試可重現 — **Phase 5/8**
- **決策：** HIS 服務認證採 API key（constant-time 比對）非 JWT；業務端點 2026-08-07 起依使用者裁示改為選填；同步任務佇列不引 Celery/Redis — **Why:** 呼叫方是 HIS 服務非瀏覽器 — **Phase 9**
- **決策：** 紙本申復清單以官方 30396 ODT 為排版依據，一次性「布局壓縮基準模板」（9 頁→3 頁，關閉 ODF 佈局網格＋0.18in 資料行，行高 26.4pt 對齊官方 27pt）＋ stdlib ET 注入 content.xml ＋ soffice 轉 PDF — **Why:** 零新增執行期依賴、版面逐欄對齊官方範本 — **Phase 11**
- **決策：** 申復 XML 用 stdlib ElementTree 手刻、半形特殊字元轉全形（官方表 8）、Big5 fail-fast — **Phase 9**
- **決策：** 去識別化只洗 d49 姓名（使用者知情決定）；`safe_filename` 為檔名唯一防線（P1-3）— **Phase 3/9**

## 3. Phases Delivered

| Phase | Name | Status | One-Liner |
|-------|------|--------|-----------|
| 01 | project-skeleton | ✅ complete | uv+Python 3.12 骨架、config（env 覆寫 + llama_config.json）、5 空殼子系統包 |
| 02 | rule-repository | ✅ complete | 三層規則庫：SQLite（2,669+11,273 列）、自建 docx 樹（32 檔/1,633 節點）、rule_mapping 快取（13,942 碼，20/20 人工核對） |
| 03 | parsers | ✅ complete | 申報 XML（633 案/2,624 醫令，Big5）、核減明細（D-14d 18 欄）、SOAP 分段；真實檔回放 0 拒收 |
| 04 | record-aggregator | ✅ complete | RecordProvider 抽象 + 四類紀錄 + 半年時間軸，degraded 語義區分病歷缺席/故障 |
| 05 | three-way-comparator | ✅ complete | 引擎核心：逐檢核項支持度判定 + 三級分類（充分/薄弱/裸奔）+ 候選補強生成 |
| 06 | output-reinforcement-report | ✅ complete | 病歷補強報告.md（checkbox 逐條審）+ 審核軌跡 JSON（五狀態） |
| 07 | output-appeal-draft | ✅ complete | 申復草稿四段組裝 + 字數控制器（Q15 官方值）+ P6 硬檢查 |
| 08 | e2e-testing | ✅ complete | 30 組 LLM 金標準 + 回放 harness + `run_case_pipeline` 端到端 + E2E-01 分類修正 |
| 09 | his-servicing | ✅ complete | API key 認證 + 零 PHI 審計日誌 + 七狀態 CaseStore + server 端點 + 申復 XML |
| 10 | vpn | ⏸ blocked | 雲端病歷 Provider／NHI_EIIAPI wrapper／Local Gateway — 外部依賴（doctor-toolbox 存取權、Windows+VPN 實機） |
| 11 | paper-appeal-print | ✅ complete | 官方 ODT 套版 → 壓縮基準模板 → ET 注入 → 三聯 PDF，CLI + facility.json（VERIFICATION 3/3） |

## 4. Requirements Coverage

- ✅ **REQ-project-skeleton** — uv 專案、config、目錄結構（REQUIREMENTS.md 狀態欄未同步，實際已於 Phase 1 完成）
- ✅ **REQ-rule-repository** — SQLite/PageIndex/rule_mapping 3/3 驗收，20 碼人工核對 20/20
- ✅ **REQ-parsers** — 申報 XML tdata/ddata/pdata、缺漏分級、SOAP 分段；真實檔回放 633 案/0 拒收
- ✅ **REQ-record-aggregator** — Provider 抽象、本地檔案 Provider、半年時間軸
- ✅ **REQ-three-way-comparator** — 逐檢核項判定＋三級分類＋候選補強（139 passed）
- ✅ **REQ-output-reinforcement-report** — checkbox 逐條審格式＋軌跡（152 passed）
- ✅ **REQ-output-appeal-draft** — 四段組裝＋字數控制器＋P6 硬檢查（176 passed）
- ⚠️ **REQ-e2e-testing** — 五層 1–4 全 ✅；第 5 層「真實樣本回放」介面就緒，**待核減實體檔/抽樣 CSV 到位**
- ✅ **REQ-paper-appeal-print** — 版面逐欄一致、直接消費 AppealDraft、第二聯核定欄正確反映（VERIFICATION 3/3，411 passed）
- ⚠️ **REQ-phase2-his-integration** — Phase 2 placeholder；Phase 9 已交付「本機可驗證範圍」（server 端點＋認證＋CaseStore），雲端串接屬 Phase 10 阻塞項

## 5. Key Decisions Log

| ID | Decision | Phase | Rationale |
|----|----------|-------|-----------|
| D1 | 兩階段 roadmap：獨立引擎 → doctor-toolbox HIS 模組 | 全 | 不依賴雲端整合即可先落地 |
| D2 | 本地 LLM（llama.cpp, Ornith-1.0-9B, n_ctx 32768） | 全 | 患者資料不出機器 |
| D3 | 補強＋申復共享同一比對引擎 | 全 | 僅輸出不同 |
| D4 | 技術棧沿用 DrtoolboxLocalServer（uv/Flask/pandas/python-docx/SQLite） | 01 | 院所既有生態 |
| D5–D8 | Provider 抽象／PageIndex+預編譯／三方比對／候選補強 | 02–05 | 查詢零 LLM、判定可注入 |
| D9–D10 | 逐條審＋軌跡／四段申復組裝 | 06–07 | 醫師為最終責任人 |
| D11–D12 | 分層降級＋五層測試／回饋迴路＋雙層隱私 | 05–08 | LLM 不確定性治理 |
| D-03(11) | 三聯核定欄以**官方模板第二聯**為準（推翻初稿「第三聯」） | 11 | 實測 30396 ODT/PDF 交叉比對，使用者裁示 |
| D-20(03) | 去識別化只洗 d49 姓名 | 03 | 使用者知情決定 |
| 09 | API key 認證（constant-time）、狀態機防呆、Big5 XML | 09 | HIS 服務場景、官方表 8 |

## 6. Tech Debt & Deferred Items

**數據缺口（多期阻塞驗收，最高優先）：**
- 核減明細實體檔（D-14b-rev reader 參數鎖定）、門診抽樣樣本 CSV、過去人工申復案例 ground truth 未取得 — 擋住 Phase 3 reader 鎖定、Phase 8 第 5 層回放、Phase 7 真實驗收

**規則庫品質：**
- rule_mapping 46% 無匹配率（6,582/13,942 碼 `article_source=None`）— recall 限制非 bug，ChromaDB 檢索改善 deferred
- `rule_mapping` 版本追蹤未做

**安全 carry-in（09-CONTEXT）：**
- P0-1/P0-2/P1-1/P1-2/P1-3/P1-5 已修復；**P1-4（CSV 內容 hash＋ChromaDB 版本綁定）與全部 P2 未處理** — 獨立安全項可隨時插入

**Phase 10 阻塞拆分（外部依賴）：** 雲端病歷 Provider（doctor-toolbox 存取權）、NHI_EIIAPI wrapper（Windows+VPN+SAM 實機）、Local Gateway 七元件

**其他：** server 端點 rate limiting/key 輪替刻意未做；紙本**抽審**清單列印（非申復）未確認官方範本；沙箱 `data/` 唯讀致 2 個 server 上傳測試環境性失敗（非回歸）；README 依賴說明、ruff+pytest CI 未做

## 7. Getting Started

- **啟動本機服務：** `uv run python server.py`（需 `ELC_API_KEYS="caller:>=16字元key"`）→ 瀏覽器開 `http://127.0.0.1:5000`（預審/申復介面）
- **CLI 入口：** `scripts/build_appeal_xml.py`（申復 XML）、`scripts/build_appeal_print.py`（紙本三聯 PDF）、`scripts/run_e2e.py`（端到端回放）
- **測試：** `uv run pytest`（411 passed / 2 skipped，~2.5 分鐘）；LLM 依賴測試經注入替身零 LLM
- **關鍵目錄：** `src/elc_audit_engine/`（parsers/record_repository/rule_repository/comparator/generators）、`officialdocument/`（官方規則/範本）、`config/`（settings/facility.json）
- **從哪看起：** `src/elc_audit_engine/pipeline.py`（`run_case_pipeline` 單一入口）→ `comparator/`（三方比對核心）→ `generators/`（輸出通道）
- **規劃文物：** `.planning/ROADMAP.md`、`.planning/PROJECT.md`（D1–D12 LOCKED）、`.planning/intel/`（完整決策/約束/需求追溯）

---

## Stats

- **Timeline:** 2026-07-29 → 2026-08-08（11 天）
- **Phases:** 10 complete / 11 total（Phase 10 外部依賴阻塞）
- **Commits:** 134（Claude Code 133 + hsuyungfeng 1）
- **Files changed:** 215 files, +35,393 insertions（首次 commit → HEAD）
- **Contributors:** Claude Code, hsuyungfeng
