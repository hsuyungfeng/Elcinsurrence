# Constraints Intel (from SPEC + DOC technical detail)

## From SPEC — docs/plans/2026-07-29-elc-audit-engine-design.md (precedence 1)

### C1 — 比對器判定輸出格式 (api-contract)
LLM 收到「檢核項＋病歷段落」只回答 `支持/部分支持/無記載`＋引用原文句子。判定任務強制 JSON schema，解析失敗換措辭重試，仍失敗降級「待人工」。
source: docs/plans/2026-07-29-elc-audit-engine-design.md §4, §7
type: api-contract

### C2 — 候選補強敘述約束 (nfr)
1. 只能基於既有線索擴寫（半年病史、當次 SOAP、規則要求的記載格式）
2. 無線索時生成提示型候選（「若實際有執行，請補充：…」），事實補充留給醫師
3. 每條附規則出處
source: docs/plans/2026-07-29-elc-audit-engine-design.md §4 步驟3
type: nfr

### C3 — 硬性檢查（pure function，不走 LLM） (nfr)
- P6 填 0（不申覆醫令）
- 2000 字上限（p8/p9）
- 檔名編碼（2+1+2+6 碼）
- 申復 XML 必填欄位
source: docs/plans/2026-07-29-elc-audit-engine-design.md §6, §7
Cross-confirmed by: 電子抽審.md §二.2 (檔名編碼規則：第一階層代碼2碼+第二階層代碼1碼+案件分類代碼2碼+案件流水號6碼), §三 (P6強制填0, p8/p9≤2000中文字)

### C4 — 字數控制器 (nfr)
>2000 字按 ④病歷佐證(引文摘短) → ②醫療必要性(病史壓縮) 優先裁剪；①案情摘要 ③規則依據 為骨架不動。
source: docs/plans/2026-07-29-elc-audit-engine-design.md §6

### C5 — 錯誤處理故障表 (nfr)
| 故障點 | 處理 |
|---|---|
| llama.cpp :8080 未啟動/逾時 | 健康檢查；逾時60s重試2次→標「待人工」，不阻斷整案 |
| LLM回傳格式跑掉 | 強制JSON schema，解析失敗換措辭重試→仍失敗降級「待人工」 |
| 申報XML欄位缺漏 | 致命(無d1/d3→整案拒收) vs 可容忍(缺d10→警告繼續) |
| 規則庫查無醫令 | 入「未知醫令」清單→即時PageIndex導航→仍無→標「查無規則依據，建議人工查核」 |
| 病史Provider不可用 | 降級：只用當次SOAP，報告開頭標「⚠本報告未含病史佐證」 |
source: docs/plans/2026-07-29-elc-audit-engine-design.md §7

### C6 — 測試策略五層 (nfr)
1. 單元測試（解析器用電子抽審.md 內真實XML範例當fixture、字數裁剪、硬性檢查）
2. 規則庫驗收（抽20個常見醫令如01015C、64140C人工核對rule_mapping正確率）
3. LLM判定評測（30組「檢核項×病歷段落」金標準，換模型時回歸基準）
4. 端到端（規格造3個完整案例：充分/薄弱/裸奔各一）
5. 真實樣本回放（真實核減案與過去人工申復比對品質）
source: docs/plans/2026-07-29-elc-audit-engine-design.md §8

### C7 — 申復輸出檔案 (api-contract)
`申復草稿_{案件流水號}.md`（醫師審閱版）＋ `appeal_{流水號}.json`（Phase 2 轉申復XML）
source: docs/plans/2026-07-29-elc-audit-engine-design.md §6

---

## From DOC — 電子抽審.md (precedence 2, context/constraint detail)

### C8 — 申覆 XML 欄位規範 (api-contract)
- P3（改支序號）：須精準填報健保署核算資料醫令改支檔案（第九欄位）中的變更代碼
- P4/P5（成數/數量受理）：院所自填的申覆訴求值
- P6（點數受理）：申覆點數；若該筆案件中有「不申覆」的醫令，此欄位必須強制填0，不可漏報
- p7（申覆檔案連結）：填 Y 代表透過PACS上傳新事證，系統自動連結
- p8/p9（申覆理由）：長文字欄位，支援最多2,000個中文字
- t38/t39（申覆總件數/總金額）：同次上傳中不同診別的申覆件數與金額加總
source: 電子抽審.md §三
Relation to progress.md D10 / SPEC §6: fully consistent — no conflict. P6=0 rule and 2000-char cap match exactly.

### C9 — 電子抽審檔案格式限制 (api-contract)
- 文字病歷：WORD/TXT/HTML/PDF/電子病歷XML；嚴禁EXE/ZIP/RAR
- 醫療影像：DICOM v3.0，須以DICOMDIR為引導檔；非DICOM可接受GIF/JPEG/PICT/TIFF/BMP
- 檔名編碼：第一階層代碼(2碼)+第二階層代碼(1碼)+案件分類代碼(2碼)+案件流水號(6碼)；多張影像檔尾碼加數字編號
- 一筆個案所有送審電子檔案須一次性上傳，禁止分開多次上傳
source: 電子抽審.md §二
Note: primarily relevant to Phase 2 (HIS/cloud upload integration), not Phase 1 local engine — flagged for Phase 2 backlog.

### C10 — API 介接參數 sTypeCode (protocol)
- `00`：電子化專業審查系統使用（單筆或病歷影像上傳）
- `15`：費用抽審XML格式批次上傳
- `07`：醫療費用電子申復資料
- `09`：預檢醫療費用電子申復資料
NHI_SendA/NHI_SendB 回傳 sLocal_ID/sNHI_ID；NHI_Query 追蹤狀態（A12檔案已就緒、A99已傳送完成）。
source: 電子抽審.md §四
Note: Phase 2 scope (地端Agent/NHI_EIIAPI介接), not required for Phase 1 file-in/file-out engine.

### C11 — 申報 XML 欄位格式 (schema)
tdata: t1(資料格式) t2(服務機構代號) t3(費用年月) t4(申報方式) t5(申報類別) t6(申報日期) t9/t10(西醫專案案件申請件數/點數) t17/t18(西醫申請件數/點數小計) t37/t38(申請件數/點數總計) t39/t40(部分負擔件數/點數總計)
ddata/dhead: d1(案件分類) d2(流水編號)
ddata/dbody: d3(病歷號) d8(就醫科別) d9(就醫日期) d10(治療結束日期) d11(出生年月日) d14(給付類別) d15(部分負擔代號) d17(轉診/處方調劑/特定檢查資源共享服務機構代號) d18(病患是否轉出) d19(主診斷代碼) d27(給藥日份) d28(處方調劑方式) d29(就醫序號) d30(診治醫事人員代號) d33(診療明細點數小計) d35(診察費項目代號) d36(診察費點數) d39(合計點數) d40(部分負擔點數) d41(申請點數) d49(姓名)
pdata: p1(藥品給藥日份) p2(醫令調劑方式) p3(醫令類別) p4(藥品/項目代號) p5(藥品用量) p7(藥品使用頻率) p8(支付成數) p9(給藥途徑/作用部位) p10(總量) p11(單價) p12(點數) p13(醫令序) p14/p15(執行時間起迄) p16(執行醫事人員代號) p17(慢性病連續處方箋/同一療程/排程檢查案件註記)
source: 電子抽審.md (XML 上傳必要欄位格式範例, 末段)
Relation to progress.md D1/M3, SPEC §9 M3: directly supports the M3 解析器 milestone (申報XML tdata/ddata/pdata) — provides field-level schema detail the ADR/SPEC reference only at a high level. No conflict; this is the authoritative field reference DOC contributes.

### C12 — FHIR/HL7 對照 Mapping (schema, Phase 2 reference only)
Patient→PID→P01, Encounter→PV1→P02, Practitioner→PRD→P03, Organization→MSH→P04, Observation→OBX→P05, DiagnosticReport→OBR→P06, MedicationRequest→RXE→P07, Procedure→PR1→P08, ImagingStudy→OBX→P09, Claim→FT1→C01, ExplanationOfBenefit→BAR→A01, Communication→TXA→Appeal
source: 電子抽審.md §5.4
Note: research-stage Phase 2 concept (cloud HIS FHIR repository), not part of Phase 1 scope per progress.md D1.
