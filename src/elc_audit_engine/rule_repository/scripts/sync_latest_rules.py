"""每月規則同步：自 `data/rules/` 讀取最新的藥品與給付項目 CSV，原子更新 `rules.sqlite3`。

用法：
    uv run python -m elc_audit_engine.rule_repository.scripts.sync_latest_rules

來源檔（取檔名中獨立 6 位數版本日期最新者；多版並存時印出實際使用的檔名）：
- `藥品項查詢項目檔*.csv` → `drug_rules`（代碼、名稱、給付規定、有效期、**支付價**、AI 摘要）
- `醫療服務給付項目*.csv` → `payment_rules`

安全性：
- 透過 `O_EXCL` 排他鎖檔（`rules.sqlite3.lock`）防併發寫入遺失更新；遇鎖檔或
  `-wal`/`-shm`/`-journal` 側車檔一律拒絕並拋 `RulesSyncConflictError`（絕不自動刪鎖檔或側車檔）。
- 雙表先於暫存庫（`rules.sqlite3.staging.<uuid>`，自既有庫複製以保留 `rule_mapping` 與舊列）
  寫入並驗證，成功後自動備份原庫（保留最近 5 份 `.bak.*`）再以 `os.replace` 單一原子替換整庫。
- 藥品／給付項目占位字串存為 NULL，**不以 AI 摘要替代**。
"""

from __future__ import annotations

import csv
import datetime
import fnmatch
import glob
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import settings
from elc_audit_engine.rule_repository.audit_csv import audit_rule_csv
from elc_audit_engine.rule_repository.loaders._csv_table import PLACEHOLDER_TEXTS, RuleCsvFormatError
from elc_audit_engine.rule_repository.loaders.drug_loader import load_drug_csv_full
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv

DRUG_PATTERN = "藥品項查詢項目檔*.csv"
PAYMENT_PATTERN = "醫療服務給付項目*.csv"

DRUG_REQUIRED_COLUMNS = (
    "藥品代號", "藥品中文名稱", "給付規定", "有效起日", "有效迄日", "支付價", "AI-note",
)
PAYMENT_REQUIRED_COLUMNS = ("診療項目代碼", "中文項目名稱", "支付規定", "生效起日", "生效迄日")

_VERSION_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
REPLACE_CONFIRM_TOKEN = "REPLACE_RULES"


class RulesSyncConflictError(RuntimeError):
    """同步衝突：鎖檔或 SQLite 側車檔存在，拒絕寫入（API 對應 409 Conflict）。"""


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
    backup_file: str | None = None
    audit: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "drug_file": os.path.basename(self.drug_file),
            "payment_file": os.path.basename(self.payment_file),
            "drug_rows": self.drug_rows,
            "payment_rows": self.payment_rows,
            "drug_stale_not_in_source": self.drug_stale,
            "payment_stale_not_in_source": self.payment_stale,
            "mode": "replace" if self.replaced else "upsert",
            "backup_file": self.backup_file,
        }
        if self.audit is not None:
            payload["audit"] = self.audit
        return payload


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
    """回傳 `directory` 內符合 `pattern` 且獨立 6 位數版本日期最新的檔案路徑。

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


def _assert_no_sidecars(db_path: str) -> None:
    """檢查目標 SQLite 旁是否存在 -wal/-shm/-journal 側車檔；存在即拒絕覆寫且不自行刪除。"""
    present = [os.path.basename(db_path + suf) for suf in _SIDECAR_SUFFIXES if os.path.exists(db_path + suf)]
    if present:
        raise RulesSyncConflictError(
            f"偵測到資料庫側車檔（{', '.join(present)}），資料庫可能有進行中的交易，拒絕同步且不會自動刪除側車檔。"
        )


def _acquire_sync_lock(db_path: str) -> str:
    """以 O_EXCL 取得規則同步行程鎖；若鎖檔已存在則拒絕並提示人工恢復程序（絕不自動刪鎖檔）。"""
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock_path = f"{db_path}.lock"
    lock_name = os.path.basename(lock_path)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RulesSyncConflictError(
            f"規則庫同步鎖定中（{lock_name}）；若確認無同步行程執行中"
            f"（可檢視鎖檔內 PID 並以 ps -p <pid> 確認），請手動移除 {lock_name} 後再重試。"
        ) from exc
    try:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        os.write(fd, f"pid={os.getpid()}\ncreated_at={now_iso}\n".encode("utf-8"))
    finally:
        os.close(fd)
    return lock_path


def _backup_and_rotate(db_path: str, *, max_backups: int = 5) -> str | None:
    """若原規則庫存在，備份至同目錄並僅保留最近 max_backups 份 `.bak.*`。"""
    if not os.path.isfile(db_path):
        return None
    parent = os.path.dirname(os.path.abspath(db_path))
    base = os.path.basename(db_path)
    ts = int(time.time())
    bak_name = f"{base}.bak.{ts}"
    bak_path = os.path.join(parent, bak_name)
    # 同一秒連續備份時加短尾碼避免覆寫
    if os.path.exists(bak_path):
        bak_name = f"{base}.bak.{ts}_{uuid.uuid4().hex[:6]}"
        bak_path = os.path.join(parent, bak_name)
    shutil.copy2(db_path, bak_path)

    if max_backups > 0:
        pattern = os.path.join(parent, f"{base}.bak.*")

        def _bak_sort_key(path: str) -> tuple[int, str]:
            name = os.path.basename(path)
            suffix = name.split(".bak.", 1)[-1]
            ts_part = suffix.split("_", 1)[0]
            try:
                return (int(ts_part), name)
            except ValueError:
                return (0, name)

        existing = sorted(glob.glob(pattern), key=_bak_sort_key)
        excess = len(existing) - max_backups
        for old_bak in existing[: max(0, excess)]:
            try:
                os.remove(old_bak)
            except OSError:
                pass
    return bak_name


def _summarize_audit(csv_path: str) -> dict[str, int]:
    rep = audit_rule_csv(csv_path)
    c = rep["counts"]
    return {
        "total_rows": rep["total_rows"],
        "literal_placeholder": c["literal_placeholder"],
        "ai_prefill_marker": c["ai_prefill_marker"],
        "missing_code_ref": c["missing_code_ref"],
        "non_standard_suffix_ref": c["non_standard_suffix_ref"],
    }


def rules_status(
    db_path: str | None = None,
    rules_dir: str | None = None,
) -> dict[str, Any]:
    """唯讀回報目前規則庫列數、NULL 數與來源目錄最新 CSV 檔名（僅 basename，無伺服器路徑）。"""
    directory = rules_dir if rules_dir is not None else default_rules_dir()
    target = db_path if db_path is not None else default_db_path()

    db_info: dict[str, Any] = {
        "exists": os.path.isfile(target),
        "payment_rows": 0,
        "payment_null_rows": 0,
        "payment_literal_placeholder_rows": 0,
        "drug_rows": 0,
        "drug_null_rows": 0,
        "drug_literal_placeholder_rows": 0,
    }
    if db_info["exists"]:
        uri = Path(target).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            placeholders = ",".join("?" for _ in PLACEHOLDER_TEXTS)
            ph_vals = tuple(PLACEHOLDER_TEXTS)
            for prefix, tbl in (("payment", "payment_rules"), ("drug", "drug_rules")):
                try:
                    db_info[f"{prefix}_rows"] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    db_info[f"{prefix}_null_rows"] = conn.execute(
                        f"SELECT COUNT(*) FROM {tbl} WHERE payment_text IS NULL"
                    ).fetchone()[0]
                    db_info[f"{prefix}_literal_placeholder_rows"] = conn.execute(
                        f"SELECT COUNT(*) FROM {tbl} WHERE lower(trim(payment_text)) IN ({placeholders})",
                        ph_vals,
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    pass
        finally:
            conn.close()

    sources: dict[str, Any] = {
        "payment_file": None,
        "payment_size_bytes": None,
        "drug_file": None,
        "drug_size_bytes": None,
    }
    if os.path.isdir(directory):
        for key, pat in (("payment", PAYMENT_PATTERN), ("drug", DRUG_PATTERN)):
            try:
                chosen = pick_latest(directory, pat)
                sources[f"{key}_file"] = os.path.basename(chosen)
                sources[f"{key}_size_bytes"] = os.path.getsize(chosen)
            except FileNotFoundError:
                pass

    return {"db": db_info, "sources": sources}


def sync_latest_rules(
    db_path: str | None = None,
    rules_dir: str | None = None,
    *,
    replace: bool = False,
    confirm: str | None = None,
    backup: bool = True,
    max_backups: int = 5,
    include_audit: bool = True,
) -> SyncResult:
    """執行原子同步：更新 `drug_rules`（含支付價、AI 摘要）與 `payment_rules`。

    預設 **upsert**：來源有的代碼覆寫，來源沒有的舊列保留，並於結果回報
    `*_stale_not_in_source` 數量。自動刪除規則不可接受，是否下架需由人工決定，
    因此 `replace=True` 必須同時明確傳入 `confirm="REPLACE_RULES"`，否則於任何
    鎖檔、側車檢查或寫入之前即拋出 `ValueError`。

    雙表先寫入暫存庫再以 `os.replace` 整庫原子替換，避免半切換；全程持 `O_EXCL` 鎖檔。
    """
    if replace and confirm != REPLACE_CONFIRM_TOKEN:
        raise ValueError(
            f"整表取代須明確提供 confirm={REPLACE_CONFIRM_TOKEN!r} 以防誤刪既有規則"
        )

    directory = rules_dir if rules_dir is not None else default_rules_dir()
    target = db_path if db_path is not None else default_db_path()

    drug_file = pick_latest(directory, DRUG_PATTERN)
    payment_file = pick_latest(directory, PAYMENT_PATTERN)

    lock_path = _acquire_sync_lock(target)
    staging = f"{target}.staging.{uuid.uuid4().hex[:8]}"
    try:
        _assert_no_sidecars(target)

        # 複製既有庫到暫存庫（保留 rule_mapping 表與 upsert 舊列）
        if os.path.isfile(target):
            shutil.copy2(target, staging)

        drug_rows = load_drug_csv_full(staging, drug_file, replace=replace)
        payment_rows = load_payment_csv(staging, payment_file, replace=replace)

        # 確認 staging 寫入後無殘留側車檔
        for suf in _SIDECAR_SUFFIXES:
            sc = staging + suf
            if os.path.exists(sc):
                os.remove(sc)

        drug_stale = len(_db_codes(staging, "drug_rules") - _source_codes(drug_file, "藥品代號"))
        payment_stale = len(_db_codes(staging, "payment_rules") - _source_codes(payment_file, "診療項目代碼"))

        audit_summary: dict[str, Any] | None = None
        if include_audit:
            audit_summary = {
                "payment": _summarize_audit(payment_file),
                "drug": _summarize_audit(drug_file),
            }

        backup_file = _backup_and_rotate(target, max_backups=max_backups) if backup else None
        os.replace(staging, target)
    finally:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass
        for suf in _SIDECAR_SUFFIXES:
            sc = staging + suf
            if os.path.exists(sc):
                try:
                    os.remove(sc)
                except OSError:
                    pass
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass

    return SyncResult(
        drug_file=drug_file,
        payment_file=payment_file,
        drug_rows=drug_rows,
        payment_rows=payment_rows,
        drug_stale=drug_stale,
        payment_stale=payment_stale,
        replaced=replace,
        backup_file=backup_file,
        audit=audit_summary,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="同步 data/rules/ 最新規則到 rules.sqlite3")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="整表取代（會刪除來源檔沒有的代碼，必須同時搭配 --confirm REPLACE_RULES）；預設為 upsert。",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        help="搭配 --replace 使用之明確確認碼（須為 REPLACE_RULES）。",
    )
    args = parser.parse_args(argv)

    try:
        result = sync_latest_rules(replace=args.replace, confirm=args.confirm)
    except ValueError as exc:
        print(f"[sync_latest_rules] 錯誤：{exc}", file=sys.stderr)
        return 1

    print(
        f"[sync_latest_rules] 藥品：{os.path.basename(result.drug_file)} → {result.drug_rows} 筆"
        f"（DB 中不在來源檔的代碼：{result.drug_stale}）；"
        f"給付項目：{os.path.basename(result.payment_file)} → {result.payment_rows} 筆"
        f"（DB 中不在來源檔的代碼：{result.payment_stale}）；"
        f"模式：{'整表取代' if args.replace else 'upsert'}；備份：{result.backup_file or '無'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
