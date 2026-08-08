"""Phase 11 紙本申復清單列印（appeal_print 子套件）。

render/write 由 11-02 填充（render_appeal_print／write_appeal_print）；
本 Wave（11-01）提供純資料層：`field_mapping`（官方欄位 ←
AppealDraft/CaseStore payload/facility/submission 逐欄對應＋分頁決定）
與 `odt_fill`（content.xml 注入＋zip 重打包）。
"""
