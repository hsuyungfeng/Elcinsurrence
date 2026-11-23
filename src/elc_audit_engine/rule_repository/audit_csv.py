"""規則庫來源 CSV 只讀資料品質稽核工具（Phase 35 Wave 1）。

設計原則（AGENTs.md 硬不變量）：
- **嚴格唯讀**：絕不修改原始 CSV，絕不自動憑空改寫或捏造健保法規條文。
- **確定性檢核**：檢出字面占位字串、引用不存在醫令代碼、非標準尾碼、AI 預填樣板痕跡
  與結構異常，輸出脫敏 JSON／Markdown 稽核報告，供人工比對官方原檔覆核。

用法：
    uv run python -m elc_audit_engine.rule_repository.audit_csv
    uv run python -m elc_audit_engine.rule_repository.audit_csv --csv path/to/file.csv --json-out out.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from elc_audit_engine.rule_repository.loaders._csv_table import PLACEHOLDER_TEXTS
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

_CODE_REF_RE = re.compile(r"(?<![A-Za-z0-9])(\d{5}[A-Za-z])(?![A-Za-z0-9])")
_STANDARD_NHI_SUFFIXES = frozenset({"A", "B", "C", "E", "G", "H"})
_AI_PREFILL_MARKERS = ("審查原則：(202", "Version 1.0", "版 1.0", "```", "**")


def _detect_columns(fieldnames: list[str]) -> tuple[str, str, str, str, str, str]:
    """自動辨識給付項目（payment）或藥品（drug）CSV 欄位。"""
    fset = set(fieldnames)
    if "診療項目代碼" in fset:
        return ("payment", "診療項目代碼", "中文項目名稱", "支付規定", "生效起日", "生效迄日")
    if "藥品代號" in fset:
        return ("drug", "藥品代號", "藥品中文名稱", "給付規定", "有效起日", "有效迄日")
    raise ValueError(f"無法辨識規則 CSV 欄位結構：{fieldnames}")


def audit_rule_csv(csv_path: str | Path, *, max_examples: int = 50) -> dict[str, Any]:
    """對單一規則來源 CSV 執行唯讀確定性品質稽核。"""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"規則 CSV 檔案不存在：{path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        kind, code_col, name_col, text_col, from_col, to_col = _detect_columns(fieldnames)
        rows = list(reader)

    all_codes = {(r.get(code_col) or "").strip().upper() for r in rows if (r.get(code_col) or "").strip()}

    counts: Counter[str] = Counter()
    seen_code_text: dict[str, str] = {}
    anomalies: dict[str, list[dict[str, Any]]] = {
        "non_standard_suffix_ref": [],
        "missing_code_ref": [],
        "structural_anomaly": [],
    }

    for line_no, rec in enumerate(rows, start=2):
        code = (rec.get(code_col) or "").strip().upper()
        raw_text = rec.get(text_col) or ""
        stripped = raw_text.strip()
        eff_from = parse_flexible_date(rec.get(from_col) or "")
        eff_to = parse_flexible_date(rec.get(to_col) or "")

        if not code:
            counts["empty_code"] += 1
            if len(anomalies["structural_anomaly"]) < max_examples:
                anomalies["structural_anomaly"].append({"line": line_no, "reason": "empty_code"})
            continue

        if eff_from and eff_to and eff_from > eff_to:
            counts["invalid_date_range"] += 1
            if len(anomalies["structural_anomaly"]) < max_examples:
                anomalies["structural_anomaly"].append(
                    {
                        "line": line_no,
                        "code": code,
                        "reason": "effective_from_after_to",
                        "effective_from": eff_from,
                        "effective_to": eff_to,
                    }
                )

        if code in seen_code_text and seen_code_text[code] != stripped:
            counts["duplicate_code_diff_text"] += 1
            if len(anomalies["structural_anomaly"]) < max_examples:
                anomalies["structural_anomaly"].append(
                    {"line": line_no, "code": code, "reason": "duplicate_code_diff_text"}
                )
        else:
            seen_code_text[code] = stripped

        if not stripped:
            counts["empty_text"] += 1
            continue
        if stripped.lower() in PLACEHOLDER_TEXTS:
            counts["literal_placeholder"] += 1
            continue

        counts["has_text"] += 1

        if any(marker in stripped for marker in _AI_PREFILL_MARKERS):
            counts["ai_prefill_marker"] += 1

        if kind == "payment":
            refs = sorted({m.upper() for m in _CODE_REF_RE.findall(stripped)})
            missing_refs = [ref for ref in refs if ref not in all_codes]
            non_std_refs = [ref for ref in refs if ref[-1] not in _STANDARD_NHI_SUFFIXES]
            if missing_refs:
                counts["missing_code_ref"] += 1
                if len(anomalies["missing_code_ref"]) < max_examples:
                    anomalies["missing_code_ref"].append(
                        {"line": line_no, "code": code, "missing_refs": missing_refs}
                    )
            if non_std_refs:
                counts["non_standard_suffix_ref"] += 1
                if len(anomalies["non_standard_suffix_ref"]) < max_examples:
                    anomalies["non_standard_suffix_ref"].append(
                        {"line": line_no, "code": code, "non_standard_refs": non_std_refs}
                    )

    return {
        "file": path.name,
        "kind": kind,
        "total_rows": len(rows),
        "unique_codes": len(all_codes),
        "counts": {
            "has_text": counts["has_text"],
            "empty_text": counts["empty_text"],
            "literal_placeholder": counts["literal_placeholder"],
            "ai_prefill_marker": counts["ai_prefill_marker"],
            "missing_code_ref": counts["missing_code_ref"],
            "non_standard_suffix_ref": counts["non_standard_suffix_ref"],
            "empty_code": counts["empty_code"],
            "invalid_date_range": counts["invalid_date_range"],
            "duplicate_code_diff_text": counts["duplicate_code_diff_text"],
        },
        "anomalies": anomalies,
    }


def format_audit_markdown(reports: list[dict[str, Any]]) -> str:
    """將稽核結果轉為簡明 Markdown 報告（無 PHI）。"""
    lines = ["# 規則庫 CSV 品質稽核報告（唯讀掃描）", ""]
    for rep in reports:
        c = rep["counts"]
        lines.append(f"## {rep['file']} (`{rep['kind']}`)")
        lines.append(f"- 總列數：{rep['total_rows']}（不重複代碼：{rep['unique_codes']}）")
        lines.append(f"- 有效條文：{c['has_text']}｜空白：{c['empty_text']}｜字面占位字串：{c['literal_placeholder']}")
        lines.append(
            f"- AI 預填標記：{c['ai_prefill_marker']}｜引用不存在碼：{c['missing_code_ref']}｜"
            f"非標準尾碼引用：{c['non_standard_suffix_ref']}"
        )
        lines.append(
            f"- 結構異常：空代碼 {c['empty_code']}、日期倒置 {c['invalid_date_range']}、"
            f"重複碼異文 {c['duplicate_code_diff_text']}"
        )
        non_std = rep["anomalies"].get("non_standard_suffix_ref") or []
        if non_std:
            lines.append("- 非標準尾碼範例（前 10 筆）：")
            for item in non_std[:10]:
                lines.append(f"  - 第 {item['line']} 列 `{item['code']}` → `{', '.join(item['non_standard_refs'])}`")
        lines.append("")
    return "\n".join(lines)


def _discover_default_csvs() -> list[Path]:
    from config import settings

    candidates: list[Path] = []
    for base in (Path(settings.RULE_SOURCE_DIR), Path(settings.DATA_DIR) / "rules"):
        if not base.is_dir():
            continue
        for pat in ("醫療服務給付項目*.csv", "藥品項查詢項目檔*.csv"):
            for m in sorted(glob.glob(os.path.join(str(base), pat))):
                p = Path(m)
                if p not in candidates:
                    candidates.append(p)
    return candidates


_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_P_PROJECT_PREFIXES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "PA", "PB", "PC")


def classify_payment_code_category(code: str) -> str:
    """依固定互斥順序將健保給付代碼分類為 8 類（先 strip().upper() 正規化）。"""
    c = (code or "").strip().upper()
    if c.endswith("C"):
        return "C類一般診療項目"
    if c.endswith("D"):
        return "D類（門診藥事服務費／助產）"
    if c.endswith("E"):
        return "E類"
    if c.startswith(("PT", "OT", "ST")):
        return "復健／職能／語言治療計畫碼（PT/OT/ST）"
    if c.startswith(_P_PROJECT_PREFIXES):
        return "P專案計畫碼（慢性病／家醫／牙醫／安寧等）"
    if c.startswith("N"):
        return "N類專案／護理／長照碼"
    if _ASCII_DIGITS_RE.fullmatch(c):
        return "預防保健／篩檢純數字碼（兒童衛教／癌症篩檢等）"
    return "其他特項碼（K/F/G/H/Q/CH等非純數字碼）"


def analyze_stale_payment_codes(
    db_path: str | Path,
    payment_csv_path: str | Path,
    *,
    max_samples_per_category: int = 10,
) -> dict[str, Any]:
    """唯讀比對既有規則庫 payment_rules 與目標給付 CSV，分類不在 CSV 中的既有代碼（無 PHI）。

    嚴守不自動刪除原則：只要 stale_count > 0，recommended_mode 一律回傳 "upsert"；
    僅當 stale_count == 0 才回傳 "no_stale"。
    """
    db_file = Path(db_path)
    csv_file = Path(payment_csv_path)
    if not db_file.is_file():
        raise FileNotFoundError(f"規則庫檔案不存在：{db_file}")
    if not csv_file.is_file():
        raise FileNotFoundError(f"規則 CSV 檔案不存在：{csv_file}")

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if "診療項目代碼" not in fieldnames:
            raise ValueError("來源 CSV 缺少必要欄位：診療項目代碼")
        csv_codes = {
            (r.get("診療項目代碼") or "").strip().upper()
            for r in reader
            if (r.get("診療項目代碼") or "").strip()
        }

    uri = db_file.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_rules'"
            ).fetchone()
            if not has_table:
                raise ValueError("資料庫缺少 payment_rules 資料表")
            db_rows: dict[str, str | None] = {}
            for code, text in conn.execute("SELECT code, payment_text FROM payment_rules"):
                norm = (code or "").strip().upper()
                if norm:
                    db_rows[norm] = text
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"資料庫檔案損毀或非有效 SQLite 格式：{exc}") from exc

    stale_codes = sorted(set(db_rows) - csv_codes)
    by_category: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    ai_prefill_count = 0
    null_text_count = 0
    other_text_count = 0

    for code in stale_codes:
        cat = classify_payment_code_category(code)
        by_category[cat] += 1
        bucket = samples.setdefault(cat, [])
        if len(bucket) < max_samples_per_category:
            bucket.append(code)

        txt = db_rows.get(code)
        stripped = (txt or "").strip()
        if not stripped or stripped.lower() in PLACEHOLDER_TEXTS:
            null_text_count += 1
        elif any(mk in stripped for mk in _AI_PREFILL_MARKERS):
            ai_prefill_count += 1
        else:
            other_text_count += 1

    recommended_mode = "upsert" if stale_codes else "no_stale"
    return {
        "db_file": db_file.name,
        "payment_csv": csv_file.name,
        "db_payment_count": len(db_rows),
        "csv_payment_count": len(csv_codes),
        "stale_count": len(stale_codes),
        "recommended_mode": recommended_mode,
        "by_category": dict(by_category.most_common()),
        "ai_prefill_count": ai_prefill_count,
        "null_text_count": null_text_count,
        "other_text_count": other_text_count,
        "sample_codes_by_category": samples,
    }


def format_stale_markdown(analysis: dict[str, Any]) -> str:
    """將舊碼差異分類分析結果格式化為脫敏 Markdown 報告。"""
    lines = [
        "# 規則庫既有給付代碼差異分類分析（唯讀掃描）",
        "",
        f"- 規則庫：`{analysis['db_file']}`（`payment_rules`：{analysis['db_payment_count']} 碼）",
        f"- 目標給付 CSV：`{analysis['payment_csv']}`（{analysis['csv_payment_count']} 碼）",
        f"- 不在目標 CSV 中的既有代碼數：**{analysis['stale_count']} 碼**",
        f"- 條文構成：AI 預填標記 {analysis['ai_prefill_count']} 碼｜NULL／空值 {analysis['null_text_count']} 碼｜其他條文 {analysis['other_text_count']} 碼",
        f"- 建議同步模式：**`{analysis['recommended_mode']}`**（`stale_count > 0` 一律建議 `upsert` 保留，是否下架須對照健保署官方公告由人工確認）",
        "",
        "## 各類別統計",
        "",
        "| 類別 | 代碼數 | 代表代碼（前 10 筆） |",
        "|---|---:|---|",
    ]
    samples = analysis.get("sample_codes_by_category") or {}
    for cat, cnt in (analysis.get("by_category") or {}).items():
        ex = ", ".join(f"`{c}`" for c in (samples.get(cat) or []))
        lines.append(f"| {cat} | {cnt} | {ex} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="規則庫 CSV 唯讀品質稽核工具")
    parser.add_argument("--csv", action="append", default=[], help="指定欲稽核之 CSV 檔案路徑（可重複傳入）")
    parser.add_argument(
        "--stale-vs-db",
        help="唯讀比對指定 rules.sqlite3 與單一給付項目 --csv，分類不在來源檔中的既有代碼",
    )
    parser.add_argument("--json-out", help="將 JSON 報告輸出至指定檔案")
    parser.add_argument("--md-out", help="將 Markdown 報告輸出至指定檔案")
    args = parser.parse_args(argv)

    if args.stale_vs_db:
        if len(args.csv) != 1:
            print("錯誤：使用 --stale-vs-db 時必須提供恰好 1 份 --csv 給付項目檔。", file=sys.stderr)
            return 1
        try:
            analysis = analyze_stale_payment_codes(args.stale_vs_db, args.csv[0])
        except (FileNotFoundError, ValueError) as exc:
            print(f"錯誤：{exc}", file=sys.stderr)
            return 1
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.md_out:
            Path(args.md_out).write_text(format_stale_markdown(analysis), encoding="utf-8")
        if not args.json_out and not args.md_out:
            print(format_stale_markdown(analysis))
        return 0

    targets = [Path(p) for p in args.csv] if args.csv else _discover_default_csvs()
    if not targets:
        print("找不到可稽核的規則 CSV 檔案。", file=sys.stderr)
        return 1

    reports = [audit_rule_csv(p) for p in targets]
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md_out:
        Path(args.md_out).write_text(format_audit_markdown(reports), encoding="utf-8")
    if not args.json_out and not args.md_out:
        print(format_audit_markdown(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
