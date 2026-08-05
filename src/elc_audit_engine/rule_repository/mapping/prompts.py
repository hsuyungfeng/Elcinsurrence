"""rule_mapping LLM 候選條文比對的 prompt 樣板。

僅供 `build_mapping.py` 的一次性批次建置流程使用（D-04）。

P1-2：代碼／名稱與候選節點全文皆來自外部檔案（CSV／docx 樹），以
`<candidates>` 等標籤定界隔離，避免條文內容中的文字被當成指令。
"""

from elc_audit_engine.prompt_safety import DATA_ISOLATION_NOTICE, fence

SYSTEM_PROMPT = (
    "你是健保醫療給付規則比對助手。你會收到一個醫令/藥品代碼與其名稱，"
    "以及若干候選條文樹節點（含標題與路徑）。請從候選節點中選出最相關的一個，"
    "並以此格式回答：條文位置：<path>\n條文摘要：<最相關的一段全文，至多200字>。"
    "若候選節點都不相關，回答：查無相關條文。\n"
    + DATA_ISOLATION_NOTICE
)

_MAX_CANDIDATES = 5
_FULL_TEXT_PREVIEW_LEN = 100


def build_candidate_matching_prompt(
    code: str,
    name: str,
    category_hint: str,
    candidate_nodes: list[dict],
) -> tuple[str, str]:
    """建立候選條文比對用的 (system_prompt, user_prompt)。

    Args:
        code: 醫令代碼／藥品代號。
        name: 代碼對應的中文名稱。
        category_hint: 額外分類線索（例如來源表名 payment_rules/drug_rules）。
        candidate_nodes: 候選 docx tree 節點列表，每個節點至少含 `path` 與
            `full_text` 鍵。此函式只取前 `_MAX_CANDIDATES` 筆——呼叫端應先
            用關鍵字比對做預先篩選，不要把整棵樹的節點都傳進來。

    Returns:
        `(system_prompt, user_prompt)` tuple。
    """
    candidates_block_lines = []
    for idx, node in enumerate(candidate_nodes[:_MAX_CANDIDATES], start=1):
        path = node.get("path", "")
        full_text = node.get("full_text", "") or ""
        preview = full_text[:_FULL_TEXT_PREVIEW_LEN]
        candidates_block_lines.append(f"{idx}. 路徑：{path}\n   全文開頭：{preview}")
    candidates_block = "\n".join(candidates_block_lines) if candidates_block_lines else "（無候選節點）"

    user_prompt = (
        f"代碼：{fence(code, 'code')}\n"
        f"名稱：{fence(name, 'name')}\n"
        f"分類線索：{fence(category_hint, 'category_hint')}\n"
        f"候選條文節點：\n{fence(candidates_block, 'candidates')}\n"
    )

    return SYSTEM_PROMPT, user_prompt
