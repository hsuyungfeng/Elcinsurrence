"""CLI Tool: 產生核減明細列印 PDF

Usage:
    python scripts/build_deduction_print.py -h
    python scripts/build_deduction_print.py --csv <csv_path> [--output <pdf_path>]
    python scripts/build_deduction_print.py --json <json_path> [--output <pdf_path>]
    python scripts/build_deduction_print.py --case-id <case_id> [--output <pdf_path>]

參數說明：
    --csv <path>        CSV 檔案路徑
    --json <path>       JSON 檔案路徑（如 CaseStore payload）
    --case-id <id>      從資料庫中提取指定 case_id 之核減資料
    --output <path>     輸出 PDF 檔案路徑，未提供時預設產生於 data/output
"""

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import settings
from elc_audit_engine.case_store import CaseStore, CaseNotFoundError
from elc_audit_engine.generators.deduction_print import write_deduction_print
from elc_audit_engine.parsers.deduction import parse_deduction_file
from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename

PRINT_BASE_ODT = os.path.join(
    settings.PROJECT_ROOT,
    "officialdocument",
    "電子申復文件格式",
    "RCPI2012R01_核減明細表_print_base.odt",
)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生核減明細 PDF")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv", help="核減明細 CSV 檔案路徑")
    group.add_argument("--json", help="核減明細 JSON 檔案路徑")
    group.add_argument("--case-id", help="從資料庫提取之案件 ID")
    parser.add_argument("--output", help="輸出 PDF 檔案路徑")

    args = parser.parse_args(argv)

    records = []
    file_stem = "deduction"

    if args.csv:
        if not os.path.exists(args.csv):
            print(f"錯誤：找不到檔案 '{args.csv}'", file=sys.stderr)
            return 1
        with open(args.csv, "rb") as f:
            try:
                res = parse_deduction_file(f.read())
                records = [vars(r) for r in res.records]
                file_stem = Path(args.csv).stem
            except Exception as e:
                print(f"錯誤：解析 CSV 失敗: {e}", file=sys.stderr)
                return 1
    elif args.json:
        if not os.path.exists(args.json):
            print(f"錯誤：找不到檔案 '{args.json}'", file=sys.stderr)
            return 1
        with open(args.json, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    records = data
                else:
                    records = [data]
                file_stem = Path(args.json).stem
            except Exception as e:
                print(f"錯誤：解析 JSON 失敗: {e}", file=sys.stderr)
                return 1
    elif args.case_id:
        store = CaseStore()
        try:
            case = store.get(args.case_id)
            if not case.payload:
                print(f"錯誤：案件 {args.case_id} 缺乏 payload", file=sys.stderr)
                return 1
            records = [case.payload]
            file_stem = args.case_id
        except CaseNotFoundError:
            print(f"錯誤：找不到案件 '{args.case_id}'", file=sys.stderr)
            return 1

    if not records:
        print("錯誤：找不到任何核減資料", file=sys.stderr)
        return 1

    try:
        facility = settings.load_facility_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"錯誤：院所設定載入失敗: {exc}", file=sys.stderr)
        return 1

    output_dir = settings.OUTPUT_DIR
    if args.output:
        if os.pardir in args.output.split(os.sep):
            print(f"錯誤：不安全的檔名 '{args.output}': 輸出路徑含路徑穿越成分", file=sys.stderr)
            return 1
        output_dir = os.path.dirname(args.output) or "."
        file_stem = Path(args.output).stem
        if file_stem.startswith("核減明細_"):
            file_stem = file_stem[len("核減明細_"):]
            
    try:
        stem = safe_filename(file_stem, "file_stem")
    except UnsafeIdentifierError as exc:
        print(f"錯誤：不安全的檔名 '{file_stem}': {exc}", file=sys.stderr)
        return 1

    try:
        pdf_path, warnings = write_deduction_print(
            output_dir,
            stem,
            records,
            facility,
            template_odt_path=PRINT_BASE_ODT,
        )
    except Exception as exc:
        print(f"錯誤：產生 PDF 失敗: {exc}", file=sys.stderr)
        return 1

    print(f"{pdf_path}")
    if warnings:
        for w in warnings:
            print(f"警告：{w}", file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
