# Phase 3: 解析器 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-03
**Phase:** 3-解析器
**Areas discussed:** XML 測試資料來源, 欄位缺漏分級標準, SOAP 分段策略, 核減清單格式

---

## 領域選擇

| Option | Description | Selected |
|--------|-------------|----------|
| XML 測試資料來源 | 電子抽審.md 有跳脫過的 XML 範例，要怎麼變成可用 fixture | ✓ |
| 欄位缺漏分級標準 | C5 只給兩個例子，完整的致命/可容忍清單在哪 | ✓ |
| SOAP 分段策略 | 已有 JS 分類器可移植 vs 標記偵測 | ✓ |
| 核減清單格式 | 三種輸入中最不明確的，repo 無樣本 | ✓ |

**User's choice:** 四項全選

---

## XML 測試資料來源

### Q1：手上有真實的申報 XML 嗎？

| Option | Description | Selected |
|--------|-------------|----------|
| 沒有，只能用文件範例 | 以 電子抽審.md 的範例為唯一基準 | |
| 有，但不在這個 repo | 檔案在別處，規劃/執行階段再提供 | |
| 有，我可以現在放進來 | 馬上放進專案目錄 | ✓ |

**User's choice:** 有，我可以現在放進來 → 提供 `TOTFA.xml`（777KB）

**Notes:** 實測分析後推翻兩個文件層級的假設：
1. 檔案宣告 `encoding="Big5"`，Python stdlib ElementTree **無法直接解析**（`ValueError: multi-byte encodings are not supported`）——此限制任何既有文件都沒提到
2. C11 欄位表是精選子集，真實檔多出 18 個 dbody 欄位 + `p24`
3. 意外確認：電子抽審.md 的 XML 範例正是本檔第 1 筆案件（`M220518024`）的節錄，文件屬實

同時發現 `TOTFA.xml` 含 348 位真實病患姓名／病歷號／生日，且**未被 gitignore 保護**——已即時修補 `.gitignore`（`*.xml` + `!tests/fixtures/**/*.xml` 例外）。

### Q2：測試要用什麼當 fixture？

| Option | Description | Selected |
|--------|-------------|----------|
| 去識別化小樣本進版控 | 抽 3-5 筆代表性案例，洗掉個資後版控 | ✓ |
| 雙軌：小 fixture + 真實檔選跑 | 版控 fixture 跑 CI，另加「若真實檔存在則跑」的全檔測試 | |
| 只用真實檔，不進版控 | 測試直接讀 TOTFA.xml | |

**User's choice:** 去識別化小樣本進版控

### Q3：C11 沒記載的 18 個欄位怎麼處理？

| Option | Description | Selected |
|--------|-------------|----------|
| 全數保留 + 次診斷升為一級欄位 | d20-d26 明確建模為次診斷代碼清單 | ✓ |
| 全數保留但不特別建模 | 一律收進通用 extra 字典 | |
| 只取 C11 列的欄位 | 嚴格照文件規格，其餘丟棄 | |

**User's choice:** 全數保留 + 次診斷升為一級欄位

**Notes:** `d20` 出現於 464/633 筆（73.3%），值為 ICD-10 碼（`S67191A`、`E782`、`K644`）。這是 Phase 5 判斷醫療必要性的關鍵臨床佐證。

### Q4：編碼怎麼處理？

| Option | Description | Selected |
|--------|-------------|----------|
| 自動偵測＋寬容回退 | big5 → cp950 → big5hkscs → utf-8 依序嘗試 | ✓ |
| 固定 Big5，不符則失敗 | 只支援 encoding="Big5" | |
| 依 XML 宣告為準 | 完全信任檔頭宣告 | |

**User's choice:** 自動偵測＋寬容回退

### Q5：去識別化要洗哪些欄位？

| Option | Description | Selected |
|--------|-------------|----------|
| d49 姓名 | 真實病患姓名 | ✓ |
| d3 病歷號 | 診所內部可反查到本人的主鍵 | |
| d11 出生年月日 | 搭配就醫日期可算年齡 | |
| d30/d31 醫師代號 | 醫事人員個資 | |

**User's choice:** 只選 d49 姓名

**Notes:** Claude 提出風險確認——只洗 d49 的話，fixture 進版控後仍含真實病歷號 + 生日 + 診斷碼，三者合併在小型診所通常足以反推到個人。使用者回覆「i know」並重新確認選擇「只洗 d49，其餘保留」。**此為知情後的明示決定，已在 CONTEXT.md D-20 標註不得由下游 agent 自行擴大清洗範圍。**

---

## 欄位缺漏分級標準

### Q1：「致命」的定義要多嚴？

| Option | Description | Selected |
|--------|-------------|----------|
| 只有「無法識別或無醫令」才致命 | 缺 d1/d2、缺 d3、或整筆無 pdata | ✓ |
| 加上「無診斷碼」也致命 | 上述再加 d19 主診斷 | |
| 嚴格：一級欄位缺任一即致命 | 16 個 100% 出現的 dbody 欄位缺任一即拒收 | |

**User's choice:** 只有「無法識別或無醫令」才致命

**Notes:** 理由是醒審目的為盡量救回案件，不是把資料不完美的案子擋在門外。

### Q2：解析到有缺陷的案件時回傳什麼？

| Option | Description | Selected |
|--------|-------------|----------|
| 整檔結果物件，含成功＋拒收清單 | ParseResult：成功案件 + 拒收案件(含原因) + 每案警告 | ✓ |
| 遇致命即拋例外 | 任一案件致命即中斷整個解析 | |
| 只回傳成功的，失敗的寫 log | 拒收案件只記 log 不進回傳值 | |

**User's choice:** 整檔結果物件，含成功＋拒收清單

**Notes:** 符合 C5「不阻斷整案」精神；633 筆中 1 筆壞掉不應停擺全部。

### Q3：可容忍的缺漏要不要分輕重？

| Option | Description | Selected |
|--------|-------------|----------|
| 兩級：警告 vs 正常缺席 | 出現率 <50% 的欄位視為正常可空不發警告 | ✓ |
| 一律發警告 | C11 有列而實際缺席就記一條 | |
| 不分級，只記缺哪些欄位 | 客觀記錄，解釋權交給 Phase 5 | |

**User's choice:** 兩級：警告 vs 正常缺席

**Notes:** 避免 633 筆產生上千條雜訊警告淹沒真正異常。真實出現率數據支撐了這條線的畫法。

### Q4：醫令碼查不到規則時該由誰處理？

| Option | Description | Selected |
|--------|-------------|----------|
| 不在 Phase 3 處理 | 解析器只取出 p4 碼，不呼叫 get_rule() | ✓ |
| Phase 3 順便標記 | 解析時就查規則庫標記未知醫令 | |

**User's choice:** 不在 Phase 3 處理

**Notes:** 保持解析器純粹——無外部依賴、可單獨測試、不需 SQLite 檔就能跑。

---

## SOAP 分段策略

### Q1：診所實際的 SOAP 病歷長什麼樣？

| Option | Description | Selected |
|--------|-------------|----------|
| 有 S:/O:/A:/P: 標記 | 病歷本身就分四段，分段是正則切割問題 | |
| 純自由文字，無標記 | 關鍵詞分類器的主場 | |
| 兩種都有 | 先試標記偵測，失敗才回退關鍵詞分類 | ✓ |
| 我也不確定 | 列為規劃階段前置問題 | |

**User's choice:** 兩種都有

**Notes:** Claude 事前分析了 `soap-classifier.js` 的實際演算法（split → 關鍵詞計分 → argmax，約 30 行實質邏輯 + 330 行關鍵詞表），並指出該分類器原本解的是「語音轉錄無結構文字」問題；用它處理已標記病歷等於把確定性問題變成機率問題。這催生了兩層＋信度標記的設計。

### Q2：關鍵詞回退層要怎麼做？

| Option | Description | Selected |
|--------|-------------|----------|
| 移植關鍵詞庫，重寫演算法 | 240+ 關鍵詞表轉 Python，分類邏輯重寫 | ✓ |
| 完整移植（含演算法） | 連計分、預設行為都還原 | |
| 不用關鍵詞，無標記就整段不分 | 交給 Phase 5 的 LLM 處理 | |

**User's choice:** 移植關鍵詞庫，重寫演算法

**Notes:** 重寫時應修正原版「無關鍵詞命中時預設歸類 subjective」的可疑行為，改為「未分類」。

### Q3：SOAP 文字從哪裡來？

| Option | Description | Selected |
|--------|-------------|----------|
| 獨立文字檔（.txt/.md） | 一案一檔或一批檔，解析器吃檔案路徑 | ✓ |
| 不確定，先接字串就好 | 主介面只接字串，讀檔是薄薄一層 helper | |
| 從病歷系統匯出的結構化檔 | HIS 匯出的 CSV/JSON，SOAP 是其中一欄 | |

**User's choice:** 獨立文字檔（.txt/.md）

---

## 核減清單格式

### Q1：手上有真實的核減通知／樣本清單嗎？

| Option | Description | Selected |
|--------|-------------|----------|
| 沒有，依規格造測試資料 | 照 progress.md 第 75 行既定策略 | |
| 有，我可以放進來 | 像 TOTFA.xml 一樣直接提供 | ✓ |
| 有，但要一段時間才拿得到 | 先造測試資料，樣本到手再驗證 | |

**User's choice:** 有，我可以放進來

**Notes:** 截至討論結束檔案尚未放入專案（`git status` 與最近修改檔案掃描皆未發現新檔）。已在 CONTEXT.md D-18 記錄此狀態：規劃階段先依官方規格書建模並造測試資料，介面保留替換空間，真實樣本到手後補一輪驗證。

### Q2：整件核減（d4=Y）與逐醫令核減怎麼建模？

| Option | Description | Selected |
|--------|-------------|----------|
| 同一型別，用旗標區分 | DeductionCase + whole_case_deducted 布林旗標 | ✓ |
| 兩種獨立型別 | WholeCaseDeduction vs OrderLevelDeduction | |
| 不特別建模 | d4 當一般欄位存起來 | |

**User's choice:** 同一型別，用旗標區分

**Notes:** 符合官方規格書「整件核減，整件申復，則醫令免申報」的語意。

### 本領域的文件探勘發現

討論此領域時 Claude 轉換並讀取了 `officialdocument/電子申復文件格式/電子申復格式及填表說明門診.doc`，發現這是**官方規格書（版本 104.02.11）**，含四段式 XML 完整欄位定義。兩項關鍵發現：

1. **核減清單的正式身分是「原送核補報樣本清單」**，且申復 XML 每個欄位都須與之勾稽，並有硬約束 `申復點數<=核減點數`、`申復成數<=核減成數`、`申復數量<=核減數量`——即核減清單是**申復值域的上界來源**。
2. **C8 的 p8/p9 字數描述與官方規格書不符**：C8 稱「支援最多 2,000 個中文字」，官方規格書實為每欄位 2000 字元／各 1000 個中文字，p8 超過 1000 中文字才填 p9。影響 Phase 7 字數控制器門檻，已列入 CONTEXT.md 的 deferred。

---

## Claude's Discretion

- 三種解析器是否共用統一的回傳基底型別
- 民國年日期轉換是否直接重用 Phase 2 的 `parse_flexible_date()` 或抽到共用模組
- 解析結果是否落盤成 JSON 中間檔
- dataclass 的確切欄位命名（建議保留 `d3`/`p4` 原始代號作為別名）

## Deferred Ideas

- **C8 的 p8/p9 字數上限修正** → Phase 7（本階段僅記錄發現，不動 LOCKED 文件）
- **rule_mapping 版本追蹤** → Phase 5 或獨立補洞計畫（Phase 2 code review 遺留）
- **ChromaDB 檢索改善 46% 無匹配率** → Phase 5 設計輸入（Phase 2 code review 遺留）
- **README 依賴說明、ruff + pytest CI** → 非階段阻塞，可隨時處理（Phase 2 code review 遺留）

討論全程未出現超出本階段範圍（新能力）的提議。
