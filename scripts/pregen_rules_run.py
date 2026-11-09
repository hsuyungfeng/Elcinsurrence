"""依支付規定 CSV（260801）批次預生成範例病歷範本（本機 LLM）。

目標（同時滿足）：
  1. 健保支付點數 > 350
  2. 有支付規定原文（非空、非 "null"）
  並排除：診療費（001 開頭）、病理檢查（25 開頭、25003C、25004C）。

來源 CSV 為唯一依據（與 rules.sqlite3 的規定原文已逐筆核對一致）。
範本為通用範本（primary_diagnosis=''），已快取者略過，除非 --force 或列於 --codes。

安全機制：
- 單次最多呼叫 LLM `--limit` 次（快取命中不計）。
- LLM 連續失敗 `--max-consecutive-undetermined` 次即中止（視為服務故障，不繼續浪費時間）。
- 每筆結果寫入 JSONL（logs/pregen_rules_run.jsonl），可續跑（快取自動跳過）。
- 不寫入任何病患資料；只記錄醫令代碼、狀態與品質問題代碼。

用法：
    uv run python scripts/pregen_rules_run.py --dry-run
    uv run python scripts/pregen_rules_run.py --limit 20
    uv run python scripts/pregen_rules_run.py --limit 1000            # 全量（可多次執行續跑）
    uv run python scripts/pregen_rules_run.py --codes 19001C,48010C --force
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (_ROOT, os.path.join(_ROOT, "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from config import settings  # noqa: E402
from elc_audit_engine.case_store.store import CaseStore  # noqa: E402
from elc_audit_engine.comparator.soap_advice import generate_template_soap_condensed  # noqa: E402
from elc_audit_engine.monthly_pregen import (  # noqa: E402
    STATUS_CACHE,
    STATUS_GENERATED,
    STATUS_QUALITY_FAILED,
    STATUS_UNDETERMINED,
    pregen_template,
)

DEFAULT_CSV = os.path.join(
    _ROOT, "data", "rules",
    "醫療服務給付項目_醫療服務給付項目及支付標準260801_C類已填支付規定.csv",
)
DEFAULT_LOG = os.path.join(_ROOT, "logs", "pregen_rules_run.jsonl")
POINTS_THRESHOLD = 350


@dataclass(frozen=True)
class RuleRow:
    code: str
    name: str
    points: int
    rule_text: str


def _is_excluded(code: str) -> bool:
    upper = code.strip().upper()
    return upper.startswith("001") or upper.startswith("25") or upper in {"25003C", "25004C"}


def load_targets(csv_path: str) -> list[RuleRow]:
    """讀取 CSV，回傳符合目標條件的醫令（依 CSV 順序、代碼去重）。"""
    seen: set[str] = set()
    rows: list[RuleRow] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            code = (raw.get("診療項目代碼") or "").strip()
            if not code or code in seen or _is_excluded(code):
                continue
            try:
                points = int(float(raw.get("健保支付點數") or 0))
            except ValueError:
                continue
            text = (raw.get("支付規定") or "").strip()
            if points <= POINTS_THRESHOLD or not text or text == "null":
                continue
            seen.add(code)
            name = (raw.get("中文項目名稱") or raw.get("英文項目名稱") or code).strip()
            rows.append(RuleRow(code=code, name=name, points=points, rule_text=text))
    return rows


def _log(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(
    targets: list[RuleRow],
    *,
    store: CaseStore,
    limit: int,
    force_codes: set[str],
    log_path: str,
    max_consecutive_undetermined: int,
    generator=None,
) -> dict[str, int]:
    counts = {"targets": len(targets), "cached": 0, "generated": 0, "quality_failed": 0,
              "undetermined": 0, "skipped_limit": 0}
    llm_calls = 0
    consecutive_undetermined = 0
    for row in targets:
        force = row.code in force_codes
        if not force and store.get_soap_template(row.code, "") is not None:
            counts["cached"] += 1
            continue
        if llm_calls >= limit:
            counts["skipped_limit"] += 1
            continue
        llm_calls += 1
        started = time.time()
        outcome = pregen_template(
            store,
            order_code=row.code,
            order_name=row.name,
            primary_diagnosis="",
            rule_text=row.rule_text,
            force=force,
            generator=generator or generate_template_soap_condensed,
        )
        elapsed = round(time.time() - started, 1)
        record = {"code": row.code, "points": row.points, "status": outcome.status,
                  "seconds": elapsed, "forced": force}
        if outcome.quality:
            record["quality_score"] = outcome.quality.get("quality_score")
            record["issues"] = sorted({i["code"] for i in outcome.quality.get("issues", [])})
        _log(log_path, record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

        if outcome.status == STATUS_GENERATED:
            counts["generated"] += 1
        elif outcome.status == STATUS_QUALITY_FAILED:
            counts["quality_failed"] += 1
        elif outcome.status == STATUS_UNDETERMINED:
            counts["undetermined"] += 1
        elif outcome.status == STATUS_CACHE:
            counts["cached"] += 1

        consecutive_undetermined = consecutive_undetermined + 1 if outcome.status == STATUS_UNDETERMINED else 0
        if consecutive_undetermined >= max_consecutive_undetermined:
            print(f"中止：LLM 連續 {consecutive_undetermined} 次失敗（視為服務故障），請檢查 8080 服務後續跑。",
                  file=sys.stderr)
            break
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=DEFAULT_CSV, help="支付規定 CSV（預設 260801 C 類）")
    parser.add_argument("--limit", type=int, default=20, help="本次最多呼叫 LLM 的醫令數（預設 20）")
    parser.add_argument("--codes", default="", help="逗號分隔醫令代碼；列出者一律重新生成（配合 --force 語意）")
    parser.add_argument("--force", action="store_true", help="目標中已快取者亦重新生成")
    parser.add_argument("--dry-run", action="store_true", help="只列出目標與快取狀態，不呼叫 LLM")
    parser.add_argument("--log", default=DEFAULT_LOG, help="JSONL 紀錄路徑")
    parser.add_argument("--max-consecutive-undetermined", type=int, default=3)
    args = parser.parse_args()

    explicit = {c.strip() for c in args.codes.split(",") if c.strip()}
    if explicit:
        # 指定代碼不受點數門檻限制（用於重生成既有範本），但仍需有規定原文
        by_code = {r.code: r for r in load_all_with_text(args.csv)}
        missing = sorted(c for c in explicit if c not in by_code)
        if missing:
            print(f"警告：以下代碼無規定原文或不存在，已略過：{missing}", file=sys.stderr)
        targets = [by_code[c] for c in sorted(explicit) if c in by_code]
    else:
        targets = load_targets(args.csv)

    store = CaseStore(db_path=settings.CASES_DB_PATH)
    if args.dry_run:
        cached = sum(1 for t in targets if store.get_soap_template(t.code, "") is not None)
        print(json.dumps({"targets": len(targets), "cached": cached,
                          "to_generate": len(targets) - cached}, ensure_ascii=False))
        return 0

    counts = run(
        targets,
        store=store,
        limit=args.limit,
        force_codes=({t.code for t in targets} if args.force else set()) | explicit,
        log_path=args.log,
        max_consecutive_undetermined=args.max_consecutive_undetermined,
    )
    print(json.dumps({"summary": counts}, ensure_ascii=False))
    return 0


def load_all_with_text(csv_path: str) -> list[RuleRow]:
    """指定代碼用：不套用點數門檻，但仍需有規定原文且非排除項目。"""
    rows: list[RuleRow] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            code = (raw.get("診療項目代碼") or "").strip()
            text = (raw.get("支付規定") or "").strip()
            if not code or _is_excluded(code) or not text or text == "null":
                continue
            try:
                points = int(float(raw.get("健保支付點數") or 0))
            except ValueError:
                points = 0
            name = (raw.get("中文項目名稱") or raw.get("英文項目名稱") or code).strip()
            rows.append(RuleRow(code=code, name=name, points=points, rule_text=text))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
