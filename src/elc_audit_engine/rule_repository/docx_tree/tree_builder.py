"""orchestrate 整批來源文件的樹狀索引建置。

`build_all_trees` 是本模組對外的唯一入口：
1. 呼叫 `doc_converter.convert_doc_files` 將所有 `.doc` 轉為 `.docx`（暫存目錄）
2. 直接 glob `source_dir` 內原生 `.docx` 檔案
3. 對合併後的所有檔案呼叫 `extractor.build_tree_for_file` 建置樹狀結構
4. 以「原始來源檔名」為 key（轉換後的檔案仍以原始 .doc 檔名為 key，
   而非暫存目錄的 .docx 路徑），回傳 `dict[str, dict]`

內部會斷言處理檔案數與來源檔案數一致，避免任何檔案被靜默略過
（對應 02-RESEARCH.md Pitfall 6 的涵蓋率斷言建議）。
"""

import glob
import os

from elc_audit_engine.rule_repository.docx_tree import doc_converter, extractor


def build_all_trees(source_dir: str, staging_dir: str) -> dict[str, dict]:
    """建置 `source_dir` 內所有 .doc/.docx 來源檔案的樹狀索引。

    Args:
        source_dir: 來源文件目錄（同時包含 .doc 與 .docx）。
        staging_dir: LibreOffice 轉換 .doc -> .docx 的暫存輸出目錄。

    Returns:
        以原始來源檔名（含副檔名）為 key、樹狀結構 dict 為 value 的字典，
        每個來源檔案恰好一筆。

    Raises:
        AssertionError: 若最終處理檔案數與來源檔案數（.doc + .docx glob 數）
            不一致，訊息中會列出缺漏的檔名，避免任何檔案被靜默略過。
    """
    doc_source_paths = sorted(
        p
        for p in glob.glob(os.path.join(source_dir, "*.doc"))
        if not p.lower().endswith(".docx")
    )
    docx_source_paths = sorted(glob.glob(os.path.join(source_dir, "*.docx")))

    expected_filenames = {os.path.basename(p) for p in doc_source_paths} | {
        os.path.basename(p) for p in docx_source_paths
    }

    converted_docx_paths = doc_converter.convert_doc_files(source_dir, staging_dir)

    # Map converted staging .docx path -> original source .doc filename, so
    # the result dict is keyed by the file as it appears in source_dir, not
    # by the staging directory's converted filename.
    converted_key_by_path = {}
    for original_doc_path, converted_path in zip(doc_source_paths, converted_docx_paths):
        converted_key_by_path[converted_path] = os.path.basename(original_doc_path)

    results: dict[str, dict] = {}

    for converted_path in converted_docx_paths:
        source_filename = converted_key_by_path[converted_path]
        doc_label = os.path.splitext(source_filename)[0]
        results[source_filename] = extractor.build_tree_for_file(converted_path, doc_label)

    for native_path in docx_source_paths:
        source_filename = os.path.basename(native_path)
        doc_label = os.path.splitext(source_filename)[0]
        results[source_filename] = extractor.build_tree_for_file(native_path, doc_label)

    if len(results) != len(expected_filenames):
        missing = expected_filenames - set(results.keys())
        raise AssertionError(
            f"build_all_trees processed {len(results)} files but expected "
            f"{len(expected_filenames)}; missing: {sorted(missing)}"
        )

    return results
