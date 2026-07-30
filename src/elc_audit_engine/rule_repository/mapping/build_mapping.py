"""rule_mapping 一次性批次建置腳本（D-04/D-05）。

對 `payment_rules` UNION `drug_rules` 中每一個代碼，決定
`(article_location, article_full_text)`：

1. 快速路徑（CSV 重用）：若該代碼在 CSV 的 `payment_text` 欄位本身已包含
   實質的審查規定全文（長度 > 60 字），直接重用該欄位內容，
   不需呼叫 LLM 或查詢 docx tree（RESEARCH.md Open Question #3，
   約可避免 49% 的付款代碼需要 LLM 呼叫）。
2. LLM 輔助路徑：否則，從 docx tree 中以關鍵字預先篩選出候選節點，
   呼叫本地 llama.cpp server 提出比對建議。

LLM 僅在此建置步驟使用一次；查詢階段（Phase 3-5）完全零 LLM，只走
`rule_mapping` 表查表（D-05）。若 smoke test 未通過，本函式會優雅降級
（寫入 `article_source=None`），絕不把 schema-descriptor 之類的垃圾文字
寫進快取表。
"""

import json
import logging

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.mapping import llm_client, prompts

logger = logging.getLogger(__name__)

_CSV_SUBSTANTIVE_THRESHOLD = 60
_MAX_LLM_CANDIDATES = 5

_SOURCE_TABLES = ("payment_rules", "drug_rules")

# 靜態、非動態組裝的查詢語句表 —— table 名稱固定寫死於此，
# 滿足 T-02-08 的參數化查詢要求。
_SELECT_ALL_CODES_QUERIES = {
    "payment_rules": "SELECT code, name, payment_text FROM payment_rules",
    "drug_rules": "SELECT code, name, payment_text FROM drug_rules",
}


def _flatten_tree_nodes(docx_trees: dict) -> list[dict]:
    """把 `docx_trees.json` 的巢狀樹狀結構攤平成單一節點列表。

    Args:
        docx_trees: `json.load` 讀入的完整 docx tree 字典
            （key 為檔名，value 為根節點 dict）。

    Returns:
        所有節點（含根節點與所有子孫節點）攤平後的列表，
        每個節點至少含 `title`/`path`/`full_text` 鍵。
    """
    flattened: list[dict] = []

    def _walk(node: dict) -> None:
        flattened.append(node)
        for child in node.get("children", []) or []:
            _walk(child)

    for root_node in docx_trees.values():
        _walk(root_node)

    return flattened


def _score_candidate(node: dict, name: str) -> int:
    """依 `name` 與節點 `title`/`full_text` 的簡單子字串重疊計分。

    Args:
        node: docx tree 節點。
        name: 代碼對應的中文名稱，用來與節點內容比對關鍵字重疊。

    Returns:
        重疊分數（越高代表越相關），用於候選節點排序篩選。
    """
    if not name:
        return 0
    title = node.get("title", "") or ""
    full_text = node.get("full_text", "") or ""
    haystack = title + full_text
    score = 0
    # 以 name 的每個字元作為關鍵字重疊計分的最小單位（中文詞彙無空白斷詞，
    # 用單字重疊作為輕量、免額外依賴的近似關鍵字比對）。
    for ch in name:
        if ch.strip() and ch in haystack:
            score += 1
    return score


def _select_top_candidates(all_nodes: list[dict], name: str, limit: int = _MAX_LLM_CANDIDATES) -> list[dict]:
    """從攤平後的節點列表中，依關鍵字重疊分數挑出前 `limit` 個候選節點。

    只挑有實質全文內容的節點（避免把純結構性、無內容的節點也送進 prompt）。
    """
    scored = [
        (_score_candidate(node, name), node)
        for node in all_nodes
        if (node.get("full_text") or "").strip()
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [node for score, node in scored[:limit] if score > 0]


def _parse_llm_response(response_text: str) -> tuple[str | None, str | None]:
    """解析 LLM 回應，取出 `條文位置：`/`條文摘要：` 兩個欄位。

    若回應為「查無相關條文」或格式無法解析，回傳 `(None, None)`。
    """
    if not response_text or "查無相關條文" in response_text:
        return None, None

    location = None
    summary = None
    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("條文位置："):
            location = line[len("條文位置："):].strip() or None
        elif line.startswith("條文摘要："):
            summary = line[len("條文摘要："):].strip() or None

    if location is None and summary is None:
        # 完全無法解析出預期格式 —— 視為不可信回應，優雅降級。
        return None, None

    return location, summary


def build_rule_mapping(db_path: str, docx_trees_path: str) -> dict:
    """建置 `rule_mapping` 快取表：CSV 重用快速路徑 + LLM 輔助 docx-tree 比對路徑。

    Args:
        db_path: `rules.sqlite3` 路徑（含 `payment_rules`/`drug_rules`，
            此函式會確保 `rule_mapping` schema 存在）。
        docx_trees_path: Plan 03 產生的 `docx_trees.json` 路徑。

    Returns:
        建置結果摘要：`{"csv_reuse_count": int, "llm_matched_count": int, "no_match_count": int}`。
    """
    conn = db.get_connection(db_path)
    db.init_schema(conn)

    with open(docx_trees_path, "r", encoding="utf-8") as f:
        docx_trees = json.load(f)
    all_nodes = _flatten_tree_nodes(docx_trees)

    # 在真正開始 LLM 呼叫之前，重新驗證一次 smoke test —— 若失敗，
    # 整個 LLM 分支優雅降級（article_source=None），絕不寫入垃圾文字。
    llm_available = True
    try:
        llm_client.smoke_test()
    except Exception as exc:  # noqa: BLE001 - 任何 smoke test 失敗都視為 LLM 不可用
        llm_available = False
        logger.warning(
            "llama.cpp smoke test failed at build_rule_mapping start (%s); "
            "degrading gracefully — all non-CSV-reuse codes will be marked article_source=None",
            exc,
        )

    csv_reuse_count = 0
    llm_matched_count = 0
    no_match_count = 0
    processed_count = 0

    for table_name in _SOURCE_TABLES:
        cursor = conn.execute(_SELECT_ALL_CODES_QUERIES[table_name])
        for row in cursor.fetchall():
            code = row["code"]
            name = row["name"]
            payment_text = row["payment_text"]
            processed_count += 1

            if payment_text and len(payment_text.strip()) > _CSV_SUBSTANTIVE_THRESHOLD:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=f"CSV:{table_name}.payment_text",
                    article_full_text=payment_text,
                    article_source="csv",
                )
                csv_reuse_count += 1
                continue

            if not llm_available:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=None,
                    article_full_text=None,
                    article_source=None,
                )
                no_match_count += 1
                continue

            candidates = _select_top_candidates(all_nodes, name)
            system_prompt, user_prompt = prompts.build_candidate_matching_prompt(
                code=code,
                name=name,
                category_hint=table_name,
                candidate_nodes=candidates,
            )
            try:
                response_text = llm_client.chat_completion(system_prompt, user_prompt)
            except Exception as exc:  # noqa: BLE001 - LLM 呼叫失敗，優雅降級為單一代碼的 no-match
                logger.warning("LLM call failed for code %s: %s", code, exc)
                response_text = ""

            location, summary = _parse_llm_response(response_text)
            if location is None and summary is None:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=None,
                    article_full_text=None,
                    article_source=None,
                )
                no_match_count += 1
            else:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=location,
                    article_full_text=summary,
                    article_source="docx",
                )
                llm_matched_count += 1

            # 每 100 筆 commit 一次並記錄進度 —— 這是一個可能長達數小時的
            # 批次作業（LLM 呼叫佔多數時間），定期 commit 讓中途中斷時
            # 已完成的部分不會遺失，也方便從旁監控進度。
            if processed_count % 100 == 0:
                conn.commit()
                logger.info(
                    "progress: processed=%d csv_reuse=%d llm_matched=%d no_match=%d",
                    processed_count,
                    csv_reuse_count,
                    llm_matched_count,
                    no_match_count,
                )

    conn.commit()
    conn.close()

    return {
        "csv_reuse_count": csv_reuse_count,
        "llm_matched_count": llm_matched_count,
        "no_match_count": no_match_count,
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    result = build_rule_mapping("data/db/rules.sqlite3", "data/db/docx_trees.json")
    print(result, file=sys.stderr)
