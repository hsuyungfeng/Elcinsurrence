"""D-09 ChromaDB 輔助基礎建設：docx 樹狀節點文字切塊 + 向量索引攝取。

本模組將 Plan 03 產出的 `data/db/docx_trees.json` 中每個節點的
`full_text` 攤平抽取，並寫入本機持久化的 ChromaDB collection（使用
ChromaDB 內建的本機 ONNX all-MiniLM-L6-v2 embedding function，「不」
依賴 llama.cpp 的 `/v1/embeddings` — 依 02-RESEARCH.md 記載，目前
server 啟動設定並未支援該端點）。

重要：`build_chroma_collection` 為 non-blocking 設計。任何攝取失敗
（例如首次使用 ONNX embedding model 需要下載但無網路、磁碟權限問題等）
皆會被廣義 try/except 捕捉，回傳乾淨的 "skipped" 狀態，絕不向呼叫端
拋出未捕捉例外 —— 本 Phase 核心驗收標準（Plan 02/03/04）不得因此受影響。

本 Phase 僅建置寫入/攝取路徑，查詢邏輯依 CONTEXT.md Deferred Ideas
延後至 Phase 5 實作。
"""

import json
import warnings

_BATCH_SIZE = 500


def flatten_tree_nodes(tree: dict, doc_label: str) -> list[dict]:
    """遞迴走訪單一文件的樹狀結構，抽取所有 full_text 非空節點。

    Args:
        tree: Plan 03 `build_all_trees` / `docx_trees.json` 中單一文件
            對應的樹狀 dict（含 title/level/path/full_text/children/table_refs）。
        doc_label: 該文件的識別名稱（通常為 docx_trees.json 的頂層 key，
            即不含副檔名的來源檔名），用於組成 chunk id 與 metadata。

    Returns:
        攤平後的 chunk 清單，每個元素為
        `{"id": f"{doc_label}::{node_path}", "text": node["full_text"],
          "metadata": {"doc": doc_label, "path": node["path"], "level": node["level"]}}`，
        僅包含 `full_text.strip()` 非空的節點。
    """
    chunks: list[dict] = []

    def _walk(node: dict) -> None:
        full_text = node.get("full_text", "") or ""
        if full_text.strip():
            chunks.append(
                {
                    "id": f"{doc_label}::{node['path']}",
                    "text": full_text,
                    "metadata": {
                        "doc": doc_label,
                        "path": node["path"],
                        "level": node["level"],
                    },
                }
            )
        for child in node.get("children", []) or []:
            _walk(child)

    _walk(tree)
    return chunks


def build_chroma_collection(
    docx_trees_path: str,
    persist_dir: str,
    collection_name: str = "rule_articles",
    source_version: str | None = None,
) -> dict:
    """將 docx_trees.json 全部文件節點切塊後攝取進本機持久化 ChromaDB collection。

    Args:
        docx_trees_path: Plan 03 產出的 docx_trees.json 路徑。
        persist_dir: ChromaDB PersistentClient 的本機儲存目錄
            （通常為 `config.settings.RAG_DIR`）。
        collection_name: ChromaDB collection 名稱，預設 "rule_articles"。
        source_version: 來源語料版本字串 (P1-4)。若傳入，會綁定至 chunk metadata["source_version"]。

    Returns:
        `{"status": "ok" | "skipped", "chunks_ingested": int, "reason": str | None}`。
        任何攝取失敗（ChromaDB client 初始化、embedding model 下載、
        collection.add 等）皆會被捕捉並回傳 "skipped"，本函式絕不拋出
        未捕捉例外（D-09 non-blocking 合約）。
    """
    # B-WR-14：
    # (a) 先寫入 staging collection，全部成功才刪舊並改名替換——中途失敗
    #     （embedding 下載失敗等）時舊索引完整保留；
    # (b) 未帶版本時一律重建（原本 add 同 id 會被忽略，內容永遠停在舊版）；
    # (c) 讀檔也納入 try，維持「絕不拋出」的 D-09 合約。
    staging_name = f"{collection_name}__staging"
    client = None
    try:
        with open(docx_trees_path, "r", encoding="utf-8") as f:
            docx_trees = json.load(f)

        all_chunks: list[dict] = []
        for doc_label, tree in docx_trees.items():
            all_chunks.extend(flatten_tree_nodes(tree, doc_label=doc_label))

        if not all_chunks:
            return {"status": "ok", "chunks_ingested": 0, "reason": None}

        # Attach source_version to chunk metadata if provided (P1-4)
        if source_version:
            for chunk in all_chunks:
                chunk["metadata"]["source_version"] = source_version

        # ChromaDB requires globally-unique ids within a collection.add() call.
        seen_id_counts: dict[str, int] = {}
        for chunk in all_chunks:
            base_id = chunk["id"]
            count = seen_id_counts.get(base_id, 0)
            seen_id_counts[base_id] = count + 1
            if count > 0:
                chunk["id"] = f"{base_id}::dup{count}"

        import chromadb

        client = chromadb.PersistentClient(path=persist_dir)
        existing_names = {c if isinstance(c, str) else c.name for c in client.list_collections()}

        if source_version and collection_name in existing_names:
            current = client.get_collection(collection_name)
            if current.count() == len(all_chunks):
                existing = current.get(limit=1, include=["metadatas"])
                metas = existing.get("metadatas") if existing else None
                if metas and metas[0] and metas[0].get("source_version") == source_version:
                    return {"status": "ok", "chunks_ingested": 0, "reason": "Already up to date (version match)"}

        if staging_name in existing_names:
            client.delete_collection(staging_name)
        staging = client.create_collection(staging_name)
        for start in range(0, len(all_chunks), _BATCH_SIZE):
            batch = all_chunks[start : start + _BATCH_SIZE]
            staging.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )

        if collection_name in existing_names:
            client.delete_collection(collection_name)
        staging.modify(name=collection_name)
    except Exception as e:  # noqa: BLE001 - deliberately broad, D-09 non-blocking contract
        if client is not None:
            try:
                client.delete_collection(staging_name)
            except Exception:  # noqa: BLE001 - staging 可能尚未建立
                pass
        warnings.warn(f"ChromaDB ingestion skipped (non-blocking, D-09): {e}")
        return {"status": "skipped", "chunks_ingested": 0, "reason": str(e)}

    return {"status": "ok", "chunks_ingested": len(all_chunks), "reason": None}
