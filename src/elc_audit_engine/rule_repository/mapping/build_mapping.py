"""rule_mapping 批次建置腳本（D-04/D-05，P1-4 增量）。

對 `payment_rules` UNION `drug_rules` 中每一個代碼，決定
`(article_location, article_full_text)`：

1. 快速路徑（CSV 重用）：若該代碼在 CSV 的 `payment_text` 欄位本身已包含
   實質的審查規定全文（長度 > 60 字），直接重用該欄位內容，
   不需呼叫 LLM 或查詢 docx tree（RESEARCH.md Open Question #3，
   約可避免 49% 的付款代碼需要 LLM 呼叫）。
2. LLM 輔助路徑：否則，從 docx tree 中以關鍵字預先篩選出候選節點，
   呼叫本地 llama.cpp server 提出比對建議。
   **藥品碼（drug_rules）例外：不送 LLM。** 審查注意事項語料是「診療項目」
   審查規定，幾乎不含藥品給付條文；送 LLM 只會得到「查無」或誤配章節標題
   （品質抽看 ③ 的成因）。藥品碼僅走 CSV 重用快速路徑，其餘直接誠實
   無匹配並鎖定版本。

LLM 僅在此建置步驟使用一次；查詢階段（Phase 3-5）完全零 LLM，只走
`rule_mapping` 表查表（D-05）。若 smoke test 未通過，本函式會優雅降級
（寫入 `article_source=None`），絕不把 schema-descriptor 之類的垃圾文字
寫進快取表。
"""

import json
import logging

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.mapping import llm_client, prompts, versions

logger = logging.getLogger(__name__)

_CSV_SUBSTANTIVE_THRESHOLD = 60
_MAX_LLM_CANDIDATES = 5
# 候選節點 full_text 至少要有這個長度，才視為「有實質內容」。
# 文件標題節點的 full_text 往往等於標題本身（如「西醫基層醫療費用審查
# 注意事項-婦產科」），對比對無價值且會誤導 LLM 選出無效條文（品質抽看
# ③ 的成因）。小於此長度直接排除。
_MIN_SUBSTANTIVE_FULL_TEXT = 20
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

    只挑「有實質全文內容」的節點：
    - `full_text` 非空且長度 >= `_MIN_SUBSTANTIVE_FULL_TEXT`
    - `full_text` 不等於節點標題（標題-only 節點對比對無價值）

    這兩個條件擋掉「文件標題節點」這類無效候選（品質抽看 ③ 的成因），
    避免把純結構性節點送進 prompt 誤導 LLM。
    """
    scored = [
        (_score_candidate(node, name), node)
        for node in all_nodes
        if (node.get("full_text") or "").strip()
        and len(node["full_text"].strip()) >= _MIN_SUBSTANTIVE_FULL_TEXT
        and node["full_text"].strip() != (node.get("title") or "").strip()
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [node for score, node in scored[:limit] if score > 0]




def _is_low_value_article(location: str | None, full_text: str | None) -> bool:
    """判斷配對結果是否為「低價值條文」（標題/無實質內容）。

    當 LLM 回報的條文全文只是章節標題本身（例如位置只有一層、全文就是
    標題），對下游 Phase 5 的「引用原文佐證」沒有價值。此類結果不應寫成
    正式 docx 匹配，應降級為無匹配（待日後改進語料/候選後重試）。

    Args:
        location: LLM 回報的條文位置。
        full_text: LLM 回報的條文摘要/全文。

    Returns:
        `True` 表示低價值（應降級）。
    """
    if not full_text or not full_text.strip():
        return True
    text = full_text.strip()
    if len(text) < _MIN_SUBSTANTIVE_FULL_TEXT:
        return True
    # 全文與位置的最後一層標題相同（如 location 只有一層且等於全文）
    if location:
        last_title = location.split(" > ")[-1].strip()
        if text == last_title:
            return True
    return False


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


def build_rule_mapping(
    db_path: str,
    docx_trees_path: str,
    source_version: str | None = None,
    payment_csv_path: str | None = None,
    drug_csv_path: str | None = None,
    incremental: bool = False,
) -> dict:
    """建置（或增量更新）`rule_mapping` 快取表：CSV 重用快速路徑 + LLM 輔助 docx-tree 比對路徑。

    Args:
        db_path: `rules.sqlite3` 路徑（含 `payment_rules`/`drug_rules`，
            此函式會確保 `rule_mapping` schema 存在）。
        docx_trees_path: Plan 03 產生的 `docx_trees.json` 路徑。
        source_version: 本次建置的來源語料版本；不提供時由
            `payment_csv_path`/`drug_csv_path`/`docx_trees_path` 自動推導，
            兩者皆無則為 `None`（不寫版本）。
        payment_csv_path: 給付項目 CSV 路徑（用於推導 `source_version`）。
        drug_csv_path: 藥品項目 CSV 路徑（用於推導 `source_version`）。
        incremental: 若為 `True`，只處理「mapping 缺列」或「既有
            `source_version` 與本次版本不符」的碼，其餘沿用快取
            （來源未換版時 LLM 零呼叫、速度大幅提升）。預設 `False`
            維持原本的全量重建語意。

    Returns:
        建置結果摘要：
        `{"csv_reuse_count": int, "llm_matched_count": int,
          "no_match_count": int, "degraded_count": int,
          "processed_count": int, "skipped_count": int,
          "source_version": str | None}`。

        降級語意（P1-4）：當 smoke test 失敗或單一碼 LLM 呼叫失敗時，
        該碼會寫入 `source_version=None`，代表「本次因故障未完成、待重試」
        —— 避免增量模式把降級結果鎖死成永久 no-match。
    """
    if source_version is None and payment_csv_path and drug_csv_path:
        source_version = versions.build_source_version(
            payment_csv_path, drug_csv_path, docx_trees_path
        )

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
    degraded_count = 0
    processed_count = 0
    skipped_count = 0

    for table_name in _SOURCE_TABLES:
        cursor = conn.execute(_SELECT_ALL_CODES_QUERIES[table_name])
        for row in cursor.fetchall():
            code = row["code"]
            name = row["name"]
            payment_text = row["payment_text"]

            if incremental:
                existing = conn.execute(
                    "SELECT source_version FROM rule_mapping WHERE code = ?",
                    (code,),
                ).fetchone()
                if existing is not None and existing["source_version"] == source_version:
                    skipped_count += 1
                    continue

            processed_count += 1

            if payment_text and len(payment_text.strip()) > _CSV_SUBSTANTIVE_THRESHOLD:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=f"CSV:{table_name}.payment_text",
                    article_full_text=payment_text,
                    article_source="csv",
                    source_version=source_version,
                )
                csv_reuse_count += 1
                continue

            if table_name == "drug_rules":
                # 藥品碼不送 LLM（設計決定）：審查注意事項語料是「診療項目」
                # 審查規定，幾乎不含藥品給付條文；送 LLM 只會得到「查無」或
                # 誤配章節標題。直接誠實無匹配並鎖定版本（此為正常結果，
                # 非故障，故寫 source_version 讓增量不再重試）。
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=None,
                    article_full_text=None,
                    article_source=None,
                    source_version=source_version,
                )
                no_match_count += 1
                continue

            if not llm_available:
                # 降級：不寫版本（source_version=None），下次增量會重試，
                # 避免把「server 故障」鎖死成永久 no-match（P1-4）。
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=None,
                    article_full_text=None,
                    article_source=None,
                    source_version=None,
                )
                no_match_count += 1
                degraded_count += 1
                continue

            candidates = _select_top_candidates(all_nodes, name)
            system_prompt, user_prompt = prompts.build_candidate_matching_prompt(
                code=code,
                name=name,
                category_hint=table_name,
                candidate_nodes=candidates,
            )
            llm_failed = False
            try:
                response_text = llm_client.chat_completion(system_prompt, user_prompt)
            except Exception as exc:  # noqa: BLE001 - LLM 呼叫失敗，優雅降級為單一代碼的 no-match
                logger.warning("LLM call failed for code %s: %s", code, exc)
                response_text = ""
                llm_failed = True

            location, summary = _parse_llm_response(response_text)
            if location is None and summary is None or _is_low_value_article(location, summary):
                # 單一碼故障（llm_failed）不寫版本，下次增量重試；
                # 真正「查無相關條文」或「低價值條文（僅標題）」才寫版本鎖定（P1-4）。
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=None,
                    article_full_text=None,
                    article_source=None,
                    source_version=None if llm_failed else source_version,
                )
                no_match_count += 1
                if llm_failed:
                    degraded_count += 1
            else:
                db.upsert_rule_mapping(
                    conn,
                    code=code,
                    article_location=location,
                    article_full_text=summary,
                    article_source="docx",
                    source_version=source_version,
                )
                llm_matched_count += 1

            # 每 100 筆 commit 一次並記錄進度 —— 這是一個可能長達數小時的
            # 批次作業（LLM 呼叫佔多數時間），定期 commit 讓中途中斷時
            # 已完成的部分不會遺失，也方便從旁監控進度。
            if processed_count % 100 == 0:
                conn.commit()
                logger.info(
                    "progress: processed=%d csv_reuse=%d llm_matched=%d no_match=%d degraded=%d skipped=%d",
                    processed_count,
                    csv_reuse_count,
                    llm_matched_count,
                    no_match_count,
                    degraded_count,
                    skipped_count,
                )

    conn.commit()
    conn.close()

    return {
        "csv_reuse_count": csv_reuse_count,
        "llm_matched_count": llm_matched_count,
        "no_match_count": no_match_count,
        "degraded_count": degraded_count,
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "source_version": source_version,
    }

if __name__ == "__main__":
    import sys

    from config.settings import DB_DIR, RULE_SOURCE_DIR
    from elc_audit_engine.rule_repository.scripts.build_sqlite import (
        _resolve_drug_csv_path,
        _resolve_payment_csv_path,
    )

    logging.basicConfig(level=logging.INFO)
    db_path = f"{DB_DIR}/rules.sqlite3"
    docx_trees_path = f"{DB_DIR}/docx_trees.json"
    payment_csv = _resolve_payment_csv_path()
    drug_csv = _resolve_drug_csv_path()
    result = build_rule_mapping(
        db_path,
        docx_trees_path,
        payment_csv_path=payment_csv,
        drug_csv_path=drug_csv,
        incremental=True,
    )
    print(result, file=sys.stderr)
