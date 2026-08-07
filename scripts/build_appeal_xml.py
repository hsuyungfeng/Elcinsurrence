"""Package Builder — 背景腳本：讀 appeal_{流水號}.json → 輸出申復 XML。

Usage:
    python scripts/build_appeal_xml.py <appeal_json_path> [output_xml_path]

範圍聲明：
    本次僅支援單筆醫令申復 (tdata + ddata + pdata)，不含 edata 統扣段。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from elc_audit_engine.generators import (
    AppealXmlEncodingError,
    build_appeal_xml,
    draft_json_to_appeal_xml_fields,
    write_appeal_xml,
)
from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or len(argv) > 2:
        print("用法: python scripts/build_appeal_xml.py <appeal_json_path> [output_xml_path]", file=sys.stderr)
        return 1

    input_path = argv[0]
    if not os.path.exists(input_path):
        print(f"錯誤：找不到檔案 '{input_path}'", file=sys.stderr)
        return 1

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            appeal_json = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"錯誤：無法解析 JSON 檔案 '{input_path}': {exc}", file=sys.stderr)
        return 1

    if not isinstance(appeal_json, dict):
        print(f"錯誤：JSON 內容需為物件 (appeal_{{流水號}}.json 格式)", file=sys.stderr)
        return 1

    try:
        tdata, ddata_list = draft_json_to_appeal_xml_fields(appeal_json)
        root = build_appeal_xml(tdata, ddata_list)
    except Exception as exc:
        print(f"錯誤：組裝 XML 結構失敗: {exc}", file=sys.stderr)
        return 1

    if len(argv) == 2:
        output_path = argv[1]
    else:
        p = Path(input_path)
        try:
            safe_stem = safe_filename(p.stem, "output_stem")
        except UnsafeIdentifierError as exc:
            print(f"錯誤：不安全的檔名 '{p.stem}': {exc}", file=sys.stderr)
            return 1
        output_path = str(p.parent / f"{safe_stem}.xml")

    try:
        write_appeal_xml(root, output_path)
    except AppealXmlEncodingError as exc:
        print(f"錯誤：寫入 XML 失敗（Big5 編碼錯誤）: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"錯誤：無法寫入檔案 '{output_path}': {exc}", file=sys.stderr)
        return 1

    print(f"已成功輸出申復 XML：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
