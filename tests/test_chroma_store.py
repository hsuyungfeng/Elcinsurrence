"""chroma_store 模組驗收測試（Plan 02-06 Task 1）。

D-09 ChromaDB 輔助基礎建設：測試涵蓋純函式 flatten_tree_nodes（無外部
相依，永遠執行）以及 build_chroma_collection 的 non-blocking 合約
（任何攝取失敗皆須優雅降級為 "skipped"，絕不拋出未捕捉例外）。
"""

import json

import pytest

from elc_audit_engine.rule_repository.embeddings import chroma_store


def test_flatten_tree_nodes_extracts_only_non_empty_full_text():
    tree = {
        "title": "root",
        "level": 0,
        "path": "root",
        "full_text": "",
        "children": [
            {
                "title": "第一章",
                "level": 1,
                "path": "root/1",
                "full_text": "第一章條文內容",
                "children": [],
                "table_refs": [],
            },
            {
                "title": "第二章",
                "level": 1,
                "path": "root/2",
                "full_text": "",
                "children": [
                    {
                        "title": "第二章第一節",
                        "level": 2,
                        "path": "root/2/1",
                        "full_text": "第二章第一節條文內容",
                        "children": [],
                        "table_refs": [],
                    }
                ],
                "table_refs": [],
            },
        ],
        "table_refs": [],
    }

    chunks = chroma_store.flatten_tree_nodes(tree, doc_label="測試文件")

    assert len(chunks) == 2
    assert chunks[0]["id"] == "測試文件::root/1"
    assert chunks[0]["text"] == "第一章條文內容"
    assert chunks[0]["metadata"] == {"doc": "測試文件", "path": "root/1", "level": 1}
    assert chunks[1]["id"] == "測試文件::root/2/1"
    assert chunks[1]["text"] == "第二章第一節條文內容"
    assert chunks[1]["metadata"] == {"doc": "測試文件", "path": "root/2/1", "level": 2}


def test_flatten_tree_nodes_returns_empty_list_when_all_text_blank():
    tree = {
        "title": "root",
        "level": 0,
        "path": "root",
        "full_text": "   ",
        "children": [],
        "table_refs": [],
    }

    chunks = chroma_store.flatten_tree_nodes(tree, doc_label="空文件")

    assert chunks == []


def test_build_chroma_collection_returns_skipped_when_persist_dir_is_a_file(tmp_path):
    # 準備一個最小的 docx_trees.json fixture
    docx_trees_path = tmp_path / "docx_trees.json"
    docx_trees_path.write_text(
        json.dumps(
            {
                "doc1": {
                    "title": "doc1",
                    "level": 0,
                    "path": "doc1",
                    "full_text": "",
                    "children": [
                        {
                            "title": "第一章",
                            "level": 1,
                            "path": "doc1/1",
                            "full_text": "條文內容",
                            "children": [],
                            "table_refs": [],
                        }
                    ],
                    "table_refs": [],
                }
            }
        ),
        encoding="utf-8",
    )

    # persist_dir 刻意指向一個「檔案」而非目錄，讓 PersistentClient 初始化必定失敗
    broken_persist_dir = tmp_path / "not_a_directory"
    broken_persist_dir.write_text("this is a file, not a directory")

    result = chroma_store.build_chroma_collection(
        docx_trees_path=str(docx_trees_path),
        persist_dir=str(broken_persist_dir),
    )

    assert result["status"] == "skipped"
    assert result["chunks_ingested"] == 0
    assert result["reason"] is not None


@pytest.mark.skipif(
    True,
    reason=(
        "Network-dependent best-effort test: requires ONNX embedding model "
        "download on first use. Run manually to verify ingestion succeeds "
        "when network is available; skipped by default for offline CI runs."
    ),
)
def test_build_chroma_collection_ingests_or_gracefully_skips(tmp_path):
    docx_trees_path = tmp_path / "docx_trees.json"
    docx_trees_path.write_text(
        json.dumps(
            {
                "doc1": {
                    "title": "doc1",
                    "level": 0,
                    "path": "doc1",
                    "full_text": "",
                    "children": [
                        {
                            "title": "第一章",
                            "level": 1,
                            "path": "doc1/1",
                            "full_text": "條文內容一",
                            "children": [],
                            "table_refs": [],
                        },
                        {
                            "title": "第二章",
                            "level": 1,
                            "path": "doc1/2",
                            "full_text": "條文內容二",
                            "children": [],
                            "table_refs": [],
                        },
                    ],
                    "table_refs": [],
                }
            }
        ),
        encoding="utf-8",
    )

    persist_dir = tmp_path / "rag"

    result = chroma_store.build_chroma_collection(
        docx_trees_path=str(docx_trees_path),
        persist_dir=str(persist_dir),
    )

    assert result["status"] in ("ok", "skipped")
    if result["status"] == "ok":
        assert result["chunks_ingested"] >= 1
    else:
        assert result["reason"] is not None
