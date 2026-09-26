#!/usr/bin/env python
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from elc_audit_engine.safe_paths import safe_filename
from elc_audit_engine.generators.evidence_packet import write_evidence_packet
from config import settings

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Generate Evidence Packet PDF")
    parser.add_argument(
        "--case-seq", required=True,
        help="輸出檔名主幹（申復佐證包_<值>.pdf）；建議傳 CaseStore case_id 以免流水號跨月撞名",
    )
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--payload", required=True, help="Path to JSON payload")
    parser.add_argument("--facility-config", help="Path to facility config JSON")
    args = parser.parse_args(argv)

    if os.pardir in args.output_dir.split(os.sep):
        print("錯誤：輸出路徑含路徑穿越成分", file=sys.stderr)
        return 1

    try:
        with open(args.payload, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"Error reading payload: {e}", file=sys.stderr)
        return 1

    facility = {}
    if args.facility_config:
        try:
            with open(args.facility_config, "r", encoding="utf-8") as f:
                facility = json.load(f)
        except Exception as e:
            print(f"Error reading facility config: {e}", file=sys.stderr)
            return 1

    try:
        file_stem = safe_filename(args.case_seq, "case_seq")
    except ValueError as e:
        print(f"錯誤：不安全的 --case-seq：{e}", file=sys.stderr)
        return 1

    try:
        out_path, warnings = write_evidence_packet(
            output_dir=args.output_dir,
            payload=payload,
            facility=facility,
            tracking={},
            timeline=None,  # CLI 未查詢病史：標示「未查詢」而非「無就醫紀錄」
            attachments=[],
            file_stem=file_stem,
        )
        print(f"Successfully generated: {out_path}")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"- {w}")
    except Exception as e:
        print(f"Error generating packet: {e}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
