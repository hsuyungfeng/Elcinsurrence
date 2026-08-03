"""rule_mapping 來源版本解析與語料雜湊（P1-4）。

來源語料會換版（CSV 檔名內含版本日期，如 `醫療服務給付項目251027...csv`、
`藥品項查詢項目檔260605...csv`；docx 審查注意事項也會更新）。`rule_mapping`
快取表加了 `source_version` 欄位後，增量建置可以判斷「來源是否換版」：
版本不符（或舊版 NULL）的碼需要重算，版本相符的碼直接沿用。

版本字串格式：`{payment_csv_version}|{drug_csv_version}|{docx_trees_hash}`
"""

import hashlib
import os


def extract_csv_version(csv_path: str) -> str:
    """從來源 CSV 檔名抽出版本日期碼（YYYYMMDD 或 RRMMDD）。

    例：`醫療服務給付項目251027準確板_已優化填入支付規定.csv` -> `251027`；
        `藥品項查詢項目檔260605 AI 摘要支付價大於0.csv` -> `260605`。

    找不到 6 位數字時回傳 `unknown`（不讓版本解析失敗阻斷建置）。
    """
    base = os.path.basename(csv_path)
    digits = "".join(ch for ch in base if ch.isdigit())
    for i in range(len(digits) - 5):
        candidate = digits[i : i + 6]
        if candidate.isdigit():
            return candidate
    return "unknown"


def hash_docx_trees(docx_trees_path: str) -> str:
    """計算 docx 語料（docx_trees.json）的 SHA-1 前 12 碼。

    內容變更（新增/修改條文、表格併入 full_text 等）會改變 hash，
    讓增量建置能偵測到 docx 語料換版。
    """
    hasher = hashlib.sha1()
    with open(docx_trees_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]


def build_source_version(payment_csv_path: str, drug_csv_path: str, docx_trees_path: str) -> str:
    """組出目前來源語料的版本字串。

    Args:
        payment_csv_path: 給付項目 CSV 路徑。
        drug_csv_path: 藥品項目 CSV 路徑。
        docx_trees_path: docx 樹狀索引 JSON 路徑。

    Returns:
        `{payment版本}|{drug版本}|{docx hash}`。
    """
    return (
        f"{extract_csv_version(payment_csv_path)}|"
        f"{extract_csv_version(drug_csv_path)}|"
        f"{hash_docx_trees(docx_trees_path)}"
    )
