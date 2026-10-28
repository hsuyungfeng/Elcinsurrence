"""每月規則同步：自 `data/rules/` 讀取最新的藥品與給付項目 CSV，更新 `rules.sqlite3`。

用法：
    uv run python -m elc_audit_engine.rule_repository.scripts.sync_latest_rules

來源檔（取檔名中首個 6 位數版本日期最新者；多版並存時印出實際使用的檔名）：
- `藥品項查詢項目檔*.csv` → `drug_rules`（代碼、名稱、給付規定、有效期、**支付價**、AI 摘要）
- `醫療服務給付項目*.csv` → `payment_rules`

安全性：
- 每份 CSV 先整檔讀完並驗證表頭，才開交易整表取代；來源損毀時既有規則不受影響。
- 藥品「給付規定」占位字串（`未找到給付規定`）存為 NULL，**不以 AI 摘要替代**；
  AI 摘要另存 `ai_note`，僅供參考，不是官方給付規定。
- 支付價非數字（來源欄位錯位）存為 NULL，不猜測數值。
"""

from __future__ import annotations

import csv
import fnmatch
import glob
import os
import re
import sqlite3
import sys
from dataclasses import dataclass

from config import settings
from elc_audit_engine.rule_repository.loaders._csv_table import RuleCsvFormatError
from elc_audit_engine.rule_repository.loaders.drug_loader import load_drug_csv_full
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv

DRUG_PATTERN = "藥品項查詢項目檔*.csv"
PAYMENT_PATTERN = "醫療服務給付項目*.csv"

DRUG_REQUIRED_COLUMNS = (
    "藥品代號", "藥品中文名稱", "給付規定", "有效起日", "有效迄日", "支付價", "AI-note",
)
PAYMENT_REQUIRED_COLUMNS = ("診療項目代碼", "中文項目名稱", "支付規定", "生效起日", "生效迄日")

_VERSION_RE = re.compile(r"\d{6}")


def rule_csv_kind(filename: str) -> str | None:
    """依檔名判定來源類別（`drug`／`payment`）；不符合任一來源樣式回 None。

    只看檔名的 basename（不接受路徑成分）。
    """
    if os.path.basename(filename) != filename or filename.startswith("."):
        return None
    if fnmatch.fnmatchcase(filename, DRUG_PATTERN):
        return "drug"
    if fnmatch.fnmatchcase(filename, PAYMENT_PATTERN):
        return "payment"
    return None


def validate_rule_csv_header(path: str, kind: str) -> None:
    """讀取表頭並確認必要欄位存在（只讀表頭，不載入整檔）。

    Raises:
        RuleCsvFormatError: 缺必要欄位，或 kind 不合法。
    """
    required = {"drug": DRUG_REQUIRED_COLUMNS, "payment": PAYMENT_REQUIRED_COLUMNS}.get(kind)
    if required is None:
        raise RuleCsvFormatError(f"未知的規則來源類別：{kind!r}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), [])
    missing = [column for column in required if column not in header]
    if missing:
        raise RuleCsvFormatError(f"缺少必要欄位：{', '.join(missing)}")


@dataclass(frozen=True)
class SyncResult:
    """一次同步的結果（供 CLI 與 API 回報）。"""

    drug_file: str
    payment_file: str
    drug_rows: int
    payment_rows: int
    # 資料庫中存在、但最新來源檔已不含的代碼數（upsert 模式保留不刪，需人工確認）。
    drug_stale: int = 0
    payment_stale: int = 0
    replaced: bool = False

    def to_dict(self) -> dict:
        return {
            "drug_file": os.path.basename(self.drug_file),
            "payment_file": os.path.basename(self.payment_file),
            "drug_rows": self.drug_rows,
            "payment_rows": self.payment_rows,
            "drug_stale_not_in_source": self.drug_stale,
            "payment_stale_not_in_source": self.payment_stale,
            "mode": "replace" if self.replaced else "upsert",
        }


def _source_codes(csv_path: str, code_column: str) -> set[str]:
    """來源 CSV 的代碼集合（與 loader 相同的正規化：去空白、轉大寫）。"""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return {
            (row.get(code_column) or "").strip().upper()
            for row in csv.DictReader(f)
        } - {""}


def _db_codes(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute(f"SELECT code FROM {table}")}
    finally:
        conn.close()


def default_rules_dir() -> str:
    return os.getenv("RULES_DIR", os.path.join(settings.DATA_DIR, "rules"))


def default_db_path() -> str:
    return os.path.join(settings.DB_DIR, "rules.sqlite3")


def pick_latest(directory: str, pattern: str) -> str:
    """回傳 `directory` 內符合 `pattern` 且版本日期最新的檔案路徑。

    Raises:
        FileNotFoundError: 找不到任何符合檔案。
    """
    matches = glob.glob(os.path.join(directory, pattern))
    if not matches:
        raise FileNotFoundError(f"在 {directory!r} 找不到 {pattern!r}")

    def version(path: str) -> str:
        found = _VERSION_RE.search(os.path.basename(path))
        return found.group(0) if found else ""

    ordered = sorted(matches, key=lambda p: (version(p), os.path.basename(p)))
    return ordered[-1]


def sync_latest_rules(
    db_path: str | None = None,
    rules_dir: str | None = None,
    *,
    replace: bool = False,
) -> SyncResult:
    """執行同步：更新 `drug_rules`（含支付價、AI 摘要）與 `payment_rules`。

    預設 **upsert**：來源有的代碼覆寫，來源沒有的舊列保留，並於結果回報
    `*_stale_not_in_source` 數量。原因：實測最新給付項目檔只涵蓋 C 類（1890 筆），
    整表取代會刪除 779 個既有代碼；藥品同理刪除 3535 筆。自動刪除規則不可接受，
    是否下架需由人工決定，因此 `replace=True` 必須明確指定。

    兩張表各自為一個交易。

    Args:
        db_path: 目標 rules.sqlite3；預設 `DB_DIR/rules.sqlite3`。
        rules_dir: 來源目錄；預設 `RULES_DIR` 環境變數或 `DATA_DIR/rules`。
        replace: True 時整表取代（會刪除來源沒有的代碼）。

    Raises:
        FileNotFoundError: 來源檔缺漏。
        RuleCsvFormatError: 來源檔缺必要欄位。
    """
    directory = rules_dir if rules_dir is not None else default_rules_dir()
    target = db_path if db_path is not None else default_db_path()

    drug_file = pick_latest(directory, DRUG_PATTERN)
    payment_file = pick_latest(directory, PAYMENT_PATTERN)

    drug_rows = load_drug_csv_full(target, drug_file, replace=replace)
    payment_rows = load_payment_csv(target, payment_file, replace=replace)

    drug_stale = len(_db_codes(target, "drug_rules") - _source_codes(drug_file, "藥品代號"))
    payment_stale = len(_db_codes(target, "payment_rules") - _source_codes(payment_file, "診療項目代碼"))
    return SyncResult(
        drug_file=drug_file,
        payment_file=payment_file,
        drug_rows=drug_rows,
        payment_rows=payment_rows,
        drug_stale=drug_stale,
        payment_stale=payment_stale,
        replaced=replace,
    )


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="同步 data/rules/ 最新規則到 rules.sqlite3")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="整表取代（會刪除來源檔沒有的代碼）；預設為 upsert，不刪除任何既有規則。",
    )
    args = parser.parse_args(argv)

    result = sync_latest_rules(replace=args.replace)
    print(
        f"[sync_latest_rules] 藥品：{os.path.basename(result.drug_file)} → {result.drug_rows} 筆"
        f"（DB 中不在來源檔的代碼：{result.drug_stale}）；"
        f"給付項目：{os.path.basename(result.payment_file)} → {result.payment_rows} 筆"
        f"（DB 中不在來源檔的代碼：{result.payment_stale}）；模式：{'整表取代' if args.replace else 'upsert'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
