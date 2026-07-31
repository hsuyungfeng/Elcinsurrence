"""docx 樹狀索引全語料涵蓋測試（REQ-rule-repository 驗收標準 2）。

Wave 0 預期紅燈：`docx_tree.tree_builder` 尚未實作（Plan 03 落地），
本檔案應以 ImportError/ModuleNotFoundError 收集失敗，而非語法錯誤。
"""

import glob
import os
import shutil
import subprocess

import pytest

from config.settings import RULE_SOURCE_DIR
from elc_audit_engine.rule_repository.docx_tree import tree_builder


def _soffice_is_functional() -> bool:
    """實際探測 soffice 是否能執行，不只是檢查 PATH 上有沒有這個檔案。

    某些沙箱/容器環境裡 soffice 存在於 PATH 但因 profile/dconf 權限問題
    執行時會直接失敗（非 0 結束碼），單用 shutil.which 判斷會誤判環境健康。
    """
    if shutil.which("soffice") is None:
        return False
    try:
        result = subprocess.run(["soffice", "--version"], capture_output=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


requires_soffice = pytest.mark.skipif(
    not _soffice_is_functional(),
    reason="soffice (LibreOffice) not available/functional — .doc conversion tests need it",
)


@requires_soffice
def test_all_source_files_converted_and_processed(tmp_path):
    # NOTE: 02-01-PLAN.md's acceptance criteria and 02-RESEARCH.md both state
    # "34 total: 11 .doc + 23 .docx". Actual glob count verified this session
    # is 11 .doc + 21 .docx = 32 (not 34) -- the plan's docx figure is stale.
    # Per deviation Rule 1, this test asserts against the live glob count
    # (the real acceptance contract: "tree-build file count == source file
    # count", not a hardcoded magic number) so it doesn't spuriously fail
    # once Plan 03 lands with a correct implementation.
    doc_files = glob.glob(os.path.join(RULE_SOURCE_DIR, "*.doc"))
    docx_files = glob.glob(os.path.join(RULE_SOURCE_DIR, "*.docx"))
    total_source_files = len(doc_files) + len(docx_files)
    assert total_source_files > 0, "expected source .doc/.docx files, found none"

    staging_dir = str(tmp_path / "staging")
    trees = tree_builder.build_all_trees(RULE_SOURCE_DIR, staging_dir)
    assert len(trees) == total_source_files


@requires_soffice
def test_flat_structure_doc_produces_nested_tree(tmp_path):
    target = "2-2-7第二部第二章第七節手術-113.12.01.docx"
    staging_dir = str(tmp_path / "staging")
    trees = tree_builder.build_all_trees(RULE_SOURCE_DIR, staging_dir)

    # build_all_trees returns dict[str, dict] keyed by original source filename
    # (see 02-03-PLAN.md interfaces/key_links). Look up directly by key, with a
    # fallback scan for dict-shaped values in case keys are stored without
    # extension or in another normalized form.
    tree = trees.get(target)
    if tree is None:
        tree = next(
            (
                v
                for k, v in trees.items()
                if os.path.basename(k) == target or k == os.path.splitext(target)[0]
            ),
            None,
        )
    assert tree is not None, f"tree for {target} not found in build_all_trees output"

    def max_depth(node, current=1):
        children = getattr(node, "children", None) or node.get("children", [])
        if not children:
            return current
        return max(max_depth(child, current + 1) for child in children)

    depth = max_depth(tree)
    assert depth >= 3, f"expected at least 3 depth levels, got {depth}"
