"""一次性建置腳本：將 docx_trees.json 攤平並攝取進本機持久化 ChromaDB collection。

執行方式：
    uv run python -m elc_audit_engine.rule_repository.scripts.build_chroma_index

此腳本呼叫 `chroma_store.build_chroma_collection`，讀取 Plan 03 產出的
`DB_DIR/docx_trees.json`，切塊後寫入 `RAG_DIR` 下的本機持久化 ChromaDB
collection（D-09 輔助基礎建設，供 Phase 5 三方比對器日後查詢使用）。

本腳本為 non-blocking：無論攝取成功（status="ok"）或因故優雅跳過
（status="skipped"，例如首次使用 ONNX embedding model 需要下載但無
網路），皆會印出結果摘要並以 exit code 0 正常結束，不會拋出例外。
"""

import os

from config import settings
from elc_audit_engine.rule_repository.embeddings import chroma_store


def main() -> None:
    docx_trees_path = os.path.join(settings.DB_DIR, "docx_trees.json")
    
    # Attempt to calculate source_version if data files exist (P1-4)
    source_ver = None
    if os.path.exists(settings.PAYMENT_RULES_CSV) and os.path.exists(settings.DRUG_RULES_CSV) and os.path.exists(docx_trees_path):
        from elc_audit_engine.rule_repository.mapping import versions
        source_ver = versions.build_source_version(
            payment_csv_path=settings.PAYMENT_RULES_CSV,
            drug_csv_path=settings.DRUG_RULES_CSV,
            docx_trees_path=docx_trees_path,
        )

    result = chroma_store.build_chroma_collection(
        docx_trees_path=docx_trees_path,
        persist_dir=settings.RAG_DIR,
        source_version=source_ver,
    )
    print(result)


if __name__ == "__main__":
    main()
