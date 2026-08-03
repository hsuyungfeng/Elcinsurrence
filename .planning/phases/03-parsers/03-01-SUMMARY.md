# Phase 3 Plan 01 Summary — 三個解析器交付

**Plan:** [03-01-PLAN.md](03-01-PLAN.md)
**Status:** ✅ Complete — 95 passed / 5 skipped（前 49 passed / 5 skipped，新增 46 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `src/elc_audit_engine/parsers/models.py` | 解析結果型別：SubmissionCase／OrderRecord／SubmissionParseResult／RejectedCase／DeductionRecord／RejectedRow／DeductionParseResult／SOAPSegment／SOAPDocument（frozen dataclass + 中文 docstring，沿用 RuleResult 慣例） |
| `src/elc_audit_engine/parsers/submission_xml.py` | 申報 XML：`parse_submission_xml(path)`；binary 讀檔、宣告編碼偵測、big5→cp950→big5hkscs→utf-8 回退（D-01）、CRLF 相容（D-04）、三種致命缺漏（D-05）、d19 只警告（D-06）、raw 全保留（D-02）、次診斷清單（D-03）、高出現率欄位警告（D-08） |
| `src/elc_audit_engine/parsers/deduction.py` | 核減明細：`parse_deduction_file(path, encoding=, delimiter=, has_header=)`；D-14d 18 欄、欄 17 拆分、雙數字格式 int() 正規化、8 碼西元日期、欄 16 原樣保留、欄數不符列拒收不中斷 |
| `src/elc_audit_engine/parsers/soap.py` | SOAP 分段：`parse_soap_text(text)`；marker（high）→ keyword（low）兩層（D-10/D-11）、無命中→UNKNOWN（D-12 修正） |
| `src/elc_audit_engine/parsers/soap_keywords.py` | 由 soap-classifier.js 程式化移植的關鍵詞表：317 詞（S 83 / O 74 / A 66 / P 94），權重 1.0/0.95/1.0/0.95 與 JS 一致 |
| `tests/fixtures/submission_sample.xml` | 由 TOTFA.xml 抽取 4 案（多醫令＋次診斷／單醫令／缺 d10＋p24／多醫令＋p8），d49 姓名置換為測試患者（D-19/D-20） |
| `tests/fixtures/deduction_sample.csv` | 依 D-14d 官方範例 2 筆資料列建置（身分證號已遮罩） |
| `tests/test_submission_xml_parser.py`（20 測試） | 編碼偵測/回退/失敗、Big5+CRLF、三種拒收、d19 警告、raw 保留、D-09 不 import 規則庫、**真實檔回放 633 案/2624 醫令/0 拒收**（TOTFA.xml 存在才跑，功能探測 skip 慣例） |
| `tests/test_deduction_parser.py`（13 測試） | 欄序、雙數字格式、西元日期、欄 17 拆分、欄 16 原樣、join key、表頭自動偵測、Big5 自動偵測、Tab 注入、欄數不符拒收、解碼失敗 |
| `tests/test_soap_parser.py`（13 測試） | 關鍵詞表數量/權重、marker 五種變體、多行內文、標記前內容 unclassified、keyword 回退、UNKNOWN 修正、計分 |

## Real-Data Verification

```
[申報XML] cases=633 rejected=0 orders=2624
  首案 d1=02 d2=1 d3=M220518024 d19=S90221A pdata=11 raw欄位=24
[核減明細] records=2 rejected=0 encoding=utf-8-sig delim=','
  上界=300 拆帳=300 join=(D2,18,1,E5002C) 申復事項=(A, 檢驗結果確實於時效內上傳)
[SOAP keyword] method=keyword confidence=low 四類皆有
[SOAP marker] method=marker confidence=high S=('頭痛三天',) P=('多喝水',)
```

## 決策落地與差異記錄

- **D-16 衝突**：03-CONTEXT.md D-16 稱 d3=樣本註記（列舉 0-4），但真實檔 d3=病歷號（M220518024）。依「真實檔優先」原則，`SubmissionCase.record_no` 以病歷號建模；`SAMPLE_MARK_LABELS` 列舉保留於 models.py 供未來抽樣樣本檔 reader 使用（已在 models.py docstring 記錄差異）。
- **join key 勘誤**：D-14d 稱欄 10 醫令序號對應「申復 XML p1」；與申報 XML join 時對應的是 **p13（醫令序）**。`DeductionRecord.order_seq` 與 `OrderRecord.seq`（p13）對齊，docstring 已註明。
- **編碼實作**：ElementTree 對「帶 encoding 宣告的 str」會拋 ValueError，實作先 decode 成 str 再改寫宣告為 utf-8 後餵給 parser（D-01 的原意）。
- **解析器純度**：submission_xml.py 測試明確斷言不 import `rule_repository`／不呼叫 `get_rule`（D-09）。

## 已遵守的 Blocking Constraints（03-parsers/.continue-here.md）

- [x] 核減欄位表以 **D-14d** 為唯一來源（未參照任何 `電子申復格式` 輸出規格書）
- [x] `grep pageindex src/ tests/` 無實際 import（僅 docx_tree/__init__.py docstring 提及「不使用」）
- [x] fixture 去識別化只洗 d49 姓名；d3/d11/d19-d26 保留真實值（D-20 明示決定）

## 未竟事項（不阻擋）

- 核減明細實體檔仍未取得：reader 參數（分隔符/表頭/編碼）已參數化，拿到實體檔後只調參數不改欄位映射（D-18）
- 抽樣樣本檔 CSV（D-14c）尚未取得：`SAMPLE_MARK_LABELS` 與 enum 已備好，reader 可沿用 deduction.py 模式
- 測試數差異說明：本 session 起點 49 passed / 5 skipped（非 03-CONTEXT 記載的 51/1——soffice 功能探測在部分環境多跳 4 個 .doc 轉檔測試），0 failures
