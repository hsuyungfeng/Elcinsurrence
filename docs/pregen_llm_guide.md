# 範例病歷預生成操作指南（本機 LLM）

> 適用：當月申報預審的「💾 下載到本機（範例病歷）」、「🔍 比對範例病歷（缺項）」與批次預生成。範本只依「醫令（＋必要時主診斷）」快取，不含真實病患資料。

## 一、目前資料庫狀態（快照）

來源：`data/db/cases.sqlite3`（唯讀查詢，2026-11-06）

| 項目 | 數量 | 說明 |
|---|---|---|
| 預生成範本 `soap_templates` | **25 筆 / 25 個醫令代碼** | 全部 `primary_diagnosis=''`（通用範本）、`source=llm_validated`；品質分數 1 筆低於 90 |
| 當月申報案件 `kind='monthly'` | **0 筆** | 目前無任何申報批次；需先上傳「申報壓縮檔」才會有批次與待生成醫令 |
| 其他案件 | bridge 14、his 1、sampling 1 | 與當月申報無關 |

要重新查詢：

```bash
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect("file:data/db/cases.sqlite3?mode=ro", uri=True)
print(c.execute("SELECT COUNT(*), COUNT(DISTINCT order_code) FROM soap_templates").fetchone())
print(c.execute("SELECT kind, COUNT(*) FROM cases GROUP BY kind").fetchall())
EOF
```

## 二、預生成的目標醫令

- **處置／手術高價醫令**：點數 > 350、非藥品、非病理檢查。
- **給付限制醫令**（`restriction_present`）：所有有給付限制的醫令，包括限制藥品。
- 排除：診療費（`001` 開頭）與病理檢查（`25` 開頭或 25003C、25004C）。
- 只有**有給付規定原文**的醫令才會生成；無規定原文者跳過，不憑空生成。
- 已有範本（通用範本）者直接跳過，不重複呼叫 LLM。

## 三、本機 LLM 服務

| 項目 | 設定 |
|---|---|
| 端點 | `LLAMA_CPP_BASE_URL`（預設 `http://localhost:8080`），呼叫 `/v1/chat/completions` |
| 設定檔 | `config/llama_config.json`（`max_tokens`、`temperature` 等） |
| 安全限制 | `assert_local_llm_url` 只允許本機位址，不會外送病歷 |
| 關閉思考 | 請求固定帶 `chat_template_kwargs.enable_thinking=false`，避免 content 為空 |

檢查服務是否在線、實際提供的模型：

```bash
curl -sS http://localhost:8080/v1/models
```

> **注意**：`config/llama_config.json` 的 `model.name` 寫的是 `Ornith-1.0-9B`，但目前 8080 上實際服務的是 `Qwen3.8-27B-FP8`。設定檔與實際模型不一致時，以服務端回報為準；若要統一，請修改設定檔的 `model` 區塊。

## 四、如何產生其他的預生成病例

### 方式 A：批次預生成（建議）

前提：已上傳申報壓縮檔，批次存在。

```bash
# 先取得批次名（含機構代碼），例如 MONTHLY-202307-3503250461
curl -sS -H "X-API-Key: <金鑰>" http://127.0.0.1:5000/api/monthly/batches

# 每次最多生成 N 筆（1～50，預設 10），已快取者不計入
curl -sS -X POST -H "X-API-Key: <金鑰>" \
  "http://127.0.0.1:5000/api/monthly/batch/MONTHLY-202307-3503250461/pregen?limit=10"
```

回傳欄位：`targets`（目標醫令數）、`cached`（已快取）、`generated`（本次新生成）、`quality_failed`（品質未過，未存庫）、`undetermined`（LLM 失敗，未存庫）、`skipped_limit`（超過上限，留待下次）。

UI 上的功能說明（已更新）：

- **💾 下載到本機（範例病歷）**：只針對「沒有 SOAP、只上傳申報檔」的外來機構案件，產生範例病歷（ZIP）下載到本機。缺少的範本由本機 LLM 生成，數量由 `?generate=N` 控制（0～50，預設 20）；通過品質檢核才存庫，其餘標示「尚未預生成」。首次下載需先填寫並確認院所（診所表單）。
- **🔍 比對範例病歷（缺項）**：針對「已有每個月 SOAP 與語音紀錄」的案件，與標準範例病歷比對，列出缺少的必要描述。只讀快取範本、不呼叫 LLM，結果僅供醫師參考。
- 「🧾 產生範例病歷」功能已取消。

### 方式 B：單一醫令（指定主診斷）

```bash
curl -sS -X POST -H "X-API-Key: <金鑰>" -H "Content-Type: application/json" \
  -d '{"order_code":"19001C","primary_diagnosis":"K76.89","order_name":"腹部超音波","force":false}' \
  http://127.0.0.1:5000/api/monthly/template
```

- `force: true` 會略過快取、重新生成並覆寫。
- 回應 `422`：品質未過，未存庫。`503`：LLM 或規則庫故障（系統故障，不是判定結果）。

### 方式 C：命令列（不經 API）

```bash
# 先列出目標，不呼叫 LLM
uv run python scripts/pregen_monthly_procedures.py --batch MONTHLY-202307 --dry-run

# 實際生成，最多 30 次 LLM 呼叫
uv run python scripts/pregen_monthly_procedures.py --batch MONTHLY-202307 --limit 30

# 強制覆寫既有範本
uv run python scripts/pregen_monthly_procedures.py --batch MONTHLY-202307 --force
```

> 命令列版本的 `--batch` 使用舊格式時仍可讀取；若批次名含機構代碼，請寫完整名稱。

## 五、品質與安全規則（不可違反）

1. **不捏造**：範本只能依給付規定原文生成；失敗或品質未過就不存庫。
2. **品質檢核**：`validate_soap_quality` 要求 S/O/A/P 皆有內容、總長 500–1000 字元、英文為主、A 欄含 ICD-10。
3. **系統故障不等於判定**：LLM 逾時或連線失敗回 `undetermined`，不寫入範本，也不標為「已完成」。
4. **範本不是病歷**：下載檔中範本一律標示「非實際病歷，須醫師審核」。

## 六、建議流程

1. 確認 `curl http://localhost:8080/v1/models` 正常。
2. 上傳申報壓縮檔，取得批次名。
3. `--dry-run` 或 `GET .../batch/<id>/report` 查看目標醫令數。
4. 以 `limit` 分批執行（例如每次 10–30 筆），直到 `skipped_limit` 為 0。
5. 檢查 `quality_failed` 與 `undetermined` 的醫令，必要時以 `force` 重試。
6. 下載範例病歷前，確認院所資料已確認（否則回 412）。
