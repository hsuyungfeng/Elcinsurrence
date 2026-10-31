"""MONTHLY 批次手術處置醫令的通用範本預生成（Plan 15-05）。

對批次中「點數 > 350 且非藥品」的不重複醫令代碼，依其給付規定原文呼叫本機 LLM 生成
標準範本，通過 `validate_soap_quality` 後存入 `soap_templates`（primary_diagnosis=''）。

- 無給付規定原文的醫令：跳過（不憑空生成規定）。
- 已有通用範本：跳過（不重複呼叫 LLM）。
- LLM 失敗或品質未過：記錄結果，不存庫。

用法：
    uv run python scripts/pregen_monthly_procedures.py --batch MONTHLY-202307 --dry-run
    uv run python scripts/pregen_monthly_procedures.py --batch MONTHLY-202307 --limit 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (_ROOT, os.path.join(_ROOT, "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from config import settings  # noqa: E402
from elc_audit_engine.case_store.store import CaseStore  # noqa: E402
from elc_audit_engine.monthly_audit import BatchAudit, audit_batch  # noqa: E402
from elc_audit_engine.monthly_pregen import (  # noqa: E402
    STATUS_GENERATED,
    STATUS_QUALITY_FAILED,
    STATUS_UNDETERMINED,
    is_procedure_finding,
    pregen_template,
)

GENERAL_DX = ""


def collect_general_targets(batch: BatchAudit) -> list[tuple[str, str, str]]:
    """批次內處置／手術高價醫令的不重複代碼 (醫令代碼, 醫令名稱, 給付規定原文)，依首次出現排序。"""
    seen: dict[str, tuple[str, str]] = {}
    for case in batch.cases:
        for finding in case.findings:
            if not is_procedure_finding(finding):
                continue
            code = finding.code.strip().upper()
            if code and code not in seen:
                seen[code] = (finding.rule_name or finding.code, finding.rule_full_text or "")
    return [(code, name, text) for code, (name, text) in seen.items()]


def run(
    batch_id: str,
    *,
    db_path: str,
    template_db_path: str,
    rules_db_path: str | None,
    dry_run: bool,
    limit: int,
) -> dict:
    """批次來源（db_path）與範本存放（template_db_path）可分開；範本應存於正式 cases.sqlite3。"""
    source = CaseStore(db_path=db_path)
    audit = audit_batch(source, batch_id, rules_db_path=rules_db_path, persist=False)
    store = CaseStore(db_path=template_db_path)
    targets = collect_general_targets(audit)

    results: list[dict] = []
    llm_calls = 0
    for code, name, rule_text in targets:
        entry = {"order_code": code, "order_name": name}
        if store.get_soap_template(code, GENERAL_DX, fallback_general=False) is not None:
            entry["result"] = "cached"
        elif not rule_text.strip():
            entry["result"] = "skipped_no_rule_text"
        elif dry_run:
            entry["result"] = "would_generate"
        elif llm_calls >= limit:
            entry["result"] = "skipped_limit"
        else:
            llm_calls += 1
            outcome = pregen_template(
                store,
                order_code=code,
                order_name=name,
                primary_diagnosis=GENERAL_DX,
                rule_text=rule_text,
            )
            entry["result"] = outcome.status
            if outcome.quality is not None:
                entry["quality_score"] = outcome.quality.get("quality_score")
                entry["issues"] = [i["code"] for i in outcome.quality.get("issues", [])]
        results.append(entry)

    summary: dict[str, int] = {}
    for entry in results:
        summary[entry["result"]] = summary.get(entry["result"], 0) + 1
    return {
        "batch": batch_id,
        "distinct_procedure_codes": len(targets),
        "summary": summary,
        "results": results,
        "stored_statuses": [STATUS_GENERATED, STATUS_QUALITY_FAILED, STATUS_UNDETERMINED],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MONTHLY 批次手術處置通用範本預生成")
    parser.add_argument("--batch", required=True, help="批次名，例如 MONTHLY-202307")
    parser.add_argument("--db", default=settings.CASES_DB_PATH, help="批次來源 cases.sqlite3（含該批次案件）")
    parser.add_argument("--template-db", default=settings.CASES_DB_PATH, help="範本存放 cases.sqlite3（預設正式庫）")
    parser.add_argument("--rules-db", default=None, help="rules.sqlite3 路徑（預設為系統設定）")
    parser.add_argument("--limit", type=int, default=30, help="本次最多呼叫 LLM 的醫令數")
    parser.add_argument("--dry-run", action="store_true", help="只列出目標，不呼叫 LLM、不寫入")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit 須介於 1～100")

    report = run(
        args.batch,
        db_path=args.db,
        template_db_path=args.template_db,
        rules_db_path=args.rules_db,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
