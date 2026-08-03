"""單一 .docx 檔案的有序區塊擷取與階層樹狀建置。

使用 python-docx 的 `iter_inner_content()` 依文件順序（段落與表格交錯）
擷取內容區塊，再以 `patterns.detect_heading_depth` 進行階層標記，
建置出巢狀樹狀結構（node: title, level, path, full_text, children,
table_refs）。表格區塊會被序列化併入所在節點的 `full_text`（P1-3），
讓表格承載的條文可被關鍵字／向量／LLM 檢索。
"""

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from elc_audit_engine.rule_repository.docx_tree import patterns


def extract_ordered_blocks(path: str) -> list[dict]:
    """依文件順序擷取所有段落與表格區塊。

    Args:
        path: .docx 檔案路徑。

    Returns:
        依文件原始順序排列的區塊清單。段落區塊：
        `{"type": "paragraph", "style": <樣式名稱>, "text": <文字>}`；
        表格區塊：`{"type": "table", "rows": [[儲存格文字, ...], ...]}`。
        空白（strip 後為空字串）的段落會被略過。
    """
    document = docx.Document(path)
    blocks: list[dict] = []

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text
            if not text.strip():
                continue
            style_name = block.style.name if block.style is not None else None
            blocks.append({"type": "paragraph", "style": style_name, "text": text})
        elif isinstance(block, Table):
            rows = [[cell.text for cell in row.cells] for row in block.rows]
            blocks.append({"type": "table", "rows": rows})

    return blocks


def _new_node(title: str, level: int, path: str) -> dict:
    return {
        "title": title,
        "level": level,
        "path": path,
        "full_text": "",
        "children": [],
        "table_refs": [],
    }


def _serialize_table(rows: list[list[str]]) -> str:
    """將表格區塊序列化為可被全文檢索的文字。

    以 `|` 分隔同列儲存格、換行分隔不同列。表格在審查注意事項中承載
    大量結構化條文（給付項目、點數、條件對照），若只留在 `table_refs`，
    會讓關鍵字候選計分、ChromaDB chunk、LLM 候選 prompt 全部看不到
    表格內容 —— 這是先前「46% 無匹配率／6,582 筆無匹配」的結構性成因
    之一（P1-3）。序列化後併入節點 `full_text`，`table_refs` 仍保留
    原始結構供精確處理。
    """
    lines = []
    for row in rows:
        cells = [(cell or "").replace("\n", " ").strip() for cell in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def build_tree_for_file(path: str, doc_label: str) -> dict:
    """擷取單一檔案的有序區塊並建置階層樹狀結構。

    Args:
        path: .docx 檔案路徑（可為原生 .docx 或 LibreOffice 轉換後的暫存 .docx）。
        doc_label: 樹狀結構根節點的識別名稱（通常為不含副檔名的原始檔名）。

    Returns:
        根節點 dict：`{"title": doc_label, "level": 0, "path": doc_label,
        "full_text": "", "children": [...], "table_refs": []}`。
    """
    blocks = extract_ordered_blocks(path)

    root = _new_node(doc_label, 0, doc_label)
    # stack of (node, ancestor_titles) — index 0 is root, deeper entries are
    # currently-open headings at increasing depth.
    stack: list[tuple[dict, list[str]]] = [(root, [])]

    for block in blocks:
        if block["type"] == "paragraph":
            text = block["text"]
            depth = patterns.detect_heading_depth(text)

            if depth is not None:
                # Pop the stack down so that the new node's parent is the
                # deepest still-open node with level < depth.
                while stack and stack[-1][0]["level"] >= depth:
                    stack.pop()

                parent_node, parent_ancestors = stack[-1]
                if parent_node is root:
                    ancestor_titles: list[str] = []
                else:
                    ancestor_titles = parent_ancestors + [parent_node["title"]]

                new_path = " > ".join(ancestor_titles + [text]) if ancestor_titles else text
                node = _new_node(text, depth, new_path)
                parent_node["children"].append(node)
                stack.append((node, ancestor_titles))
            else:
                current_node, _ = stack[-1]
                if current_node["full_text"]:
                    current_node["full_text"] += "\n" + text
                else:
                    current_node["full_text"] = text
        elif block["type"] == "table":
            current_node, _ = stack[-1]
            current_node["table_refs"].append(block["rows"])
            serialized = _serialize_table(block["rows"])
            if serialized.strip():
                if current_node["full_text"]:
                    current_node["full_text"] += "\n" + serialized
                else:
                    current_node["full_text"] = serialized

    return root
