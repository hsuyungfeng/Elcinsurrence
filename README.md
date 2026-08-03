# Elcinsurrence

健保電子抽審與申復自動化引擎（`elc-audit-engine`）。

## 概覽

電子抽審自動化病歷補強 ＋ 申復自動化補充理由與病歷資料整理。
設計決策、架構與路線圖見 [`progress.md`](progress.md)；深度調查與改進意見見 [`deepflash4improve.md`](deepflash4improve.md)。

## 規則庫建置管線（Phase 2，依序執行）

```bash
# 1) 來源 CSV -> SQLite（payment_rules / drug_rules）
.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_sqlite

# 2) 審查注意事項 .doc/.docx -> docx 樹狀索引（docx_trees.json）
.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_docx_trees

# 3) docx 樹 -> ChromaDB 向量索引（輔助層，non-blocking）
.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_chroma_index

# 4) docx 樹 -> rule_mapping 預編譯快取（LLM 輔助；預設增量、只重算版本不符的碼）
.venv/bin/python -m elc_audit_engine.rule_repository.mapping.build_mapping
```

- 步驟 1、2 會寫入 `data/db/`（`rules.sqlite3`、`docx_trees.json`）；步驟 3 寫入 `data/rag/`。
- 步驟 2 需要本機可用的 LibreOffice（`soffice`）來轉換舊版 `.doc`。
- 步驟 4 需要 `llama.cpp server`（`localhost:8080`，設定見 `config/llama_config.json`）；伺服器未啟動時會優雅降級（該批碼記為無匹配），不會寫入垃圾文字。
- 步驟 4 支援增量：`--incremental`（預設）只重算「缺列」或「來源版本不符」的碼；來源 CSV/docx 換版時自動偵測並重算。

## 查詢介面

`get_rule(code)` 對外唯一查詢入口，零 LLM、零網路（D-05）：

```python
from elc_audit_engine.rule_repository import get_rule
result = get_rule("64140C")   # RuleResult
```

- `found=False` = 此醫令/藥品確實查無規則（正常結果）。
- 拋 `RuleRepositoryError` = 資料庫系統性故障（檔案/表不存在、損毀、鎖定），與「查無」不同。

## 測試

```bash
.venv/bin/python -m pytest -q
```

- LibreOffice 轉檔相關測試使用「真實轉檔探測」決定 skip：若環境無法實際 headless 轉檔（如沙箱/CI），會自動 skip 而非誤報失敗。
- llama.cpp / 網路相依測試在伺服器未啟動時自動 skip。
