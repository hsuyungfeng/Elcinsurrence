"""一次性建置腳本：產生 data/db/docx_trees.json。

執行方式：
    uv run python -m elc_audit_engine.rule_repository.scripts.build_docx_trees

此腳本呼叫 `tree_builder.build_all_trees` 處理 `RULE_SOURCE_DIR` 內所有
.doc/.docx 來源文件，並將結果寫入 `DB_DIR/docx_trees.json`，供 Plan 04
的 rule_mapping 建置流程作為候選節點來源。
"""

import json
import os

from config import settings
from elc_audit_engine.rule_repository.docx_tree import tree_builder


def _count_nodes(node: dict) -> int:
    total = 1
    for child in node.get("children", []):
        total += _count_nodes(child)
    return total


def main() -> None:
    staging_dir = os.path.join(settings.DATA_DIR, "converted_docx")
    trees = tree_builder.build_all_trees(settings.RULE_SOURCE_DIR, staging_dir)

    os.makedirs(settings.DB_DIR, exist_ok=True)
    output_path = os.path.join(settings.DB_DIR, "docx_trees.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(trees, f, ensure_ascii=False, indent=2)

    total_nodes = sum(_count_nodes(tree) for tree in trees.values())
    print(f"processed {len(trees)} files, {total_nodes} total tree nodes")
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
