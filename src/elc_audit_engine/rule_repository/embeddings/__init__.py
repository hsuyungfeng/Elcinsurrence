"""ChromaDB 向量索引模組（D-09 輔助基礎建設）。

本模組將 docx 樹狀索引（Plan 03 產出的 `data/db/docx_trees.json`）中
每個節點的 `full_text` 切塊後，寫入本機持久化的 ChromaDB collection。

注意：本模組僅低優先度、非阻斷性（non-blocking）基礎建設，供 Phase 5
（三方比對器）日後查詢使用。本 Phase 僅建置寫入/攝取路徑，不含查詢邏輯
（查詢邏輯依 CONTEXT.md Deferred Ideas 延後至 Phase 5 實作）。任何攝取
失敗（例如首次使用 ONNX embedding model 需要下載但無網路）皆會被優雅
捕捉並回傳 "skipped" 狀態，不得拋出例外影響 Phase 2 核心驗收標準。
"""
