"""Package Builder — 背景腳本：讀 appeal_{流水號}.json → 輸出紙本申復清單 PDF。

Usage:
    python scripts/build_appeal_print.py <appeal_json_path> [case_payload_json_path] [output_pdf_path]

參數說明：
    <appeal_json_path>          必填。Phase 7 產出之 appeal_{流水號}.json（render_appeal_json 格式）。
    [case_payload_json_path]    選填。案件層 payload（CaseStore payload 或 SubmissionCase dict），
                                提供 id_number/patient_name/primary_diagnosis/clinic/orders 等
                                患者層欄位以 join 進清單（11-01 submission 契約）。
    [output_pdf_path]           選填。指定輸出 PDF 路徑（目錄由路徑推導）；缺省時輸出至
                                settings.OUTPUT_DIR（data/output），stem 由 appeal JSON 的
                                case_seq 與 order_seq 組出（`{case_seq}_{order_seq}`）。

範圍聲明：
    純 CLI 入口，不觸碰 server.py（Open Q#6：CLI 先行）；缺欄 warnings 於成功訊息後
    以「警告：」逐條列印（誠實降級不隱藏，T-11-03 只印欄位名不印值全文）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 確保專案根可解析：`config` 為專案根層級模組（非 package 安裝範圍）。
# 直接執行 `python scripts/build_appeal_print.py` 時 sys.path[0] 為 scripts/ 目錄，
# 須自行把專案根插入 sys.path（比照 tests/conftest.py 的 sys.path 插入模式）。
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from elc_audit_engine.generators import write_appeal_print
from elc_audit_engine.generators.appeal_print.case_to_submission import (
    build_submission_from_case,
)
from elc_audit_engine.generators.appeal_print.odt_fill import AppealPrintFillError
from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename
from config import settings

# 基準模板（11-02 產物，git 版控資產；write_appeal_print 內建 sha256 校驗，T-11-06）。
PRINT_BASE_ODT = os.path.join(
    settings.PROJECT_ROOT,
    "officialdocument",
    "電子申復文件格式",
    "30396_1_1050105-1門診診療費用申復清單_print_base.odt",
)

USAGE = (
    "用法: python scripts/build_appeal_print.py <appeal_json_path> "
    "[case_payload_json_path] [output_pdf_path]"
)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # 接受 1~3 個位置參數；0 個或 >3 個 → 印 usage 至 stderr + return 1。
    if not argv or len(argv) > 3:
        print(USAGE, file=sys.stderr)
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
        print("錯誤：JSON 內容需為物件 (appeal_{流水號}.json 格式)", file=sys.stderr)
        return 1

    # 參數解析：長度 2 時第 2 個為 output_pdf_path（後向兼容 build_appeal_xml 習慣）；
    # 長度 3 時第 2 個為 case_payload_json_path、第 3 個為 output_pdf_path。
    case_payload_json_path = argv[1] if len(argv) == 3 else None
    output_pdf_path = argv[1] if len(argv) == 2 else (argv[2] if len(argv) == 3 else None)

    submission = None
    case_warnings: list[str] = []
    if case_payload_json_path:
        if not os.path.exists(case_payload_json_path):
            print(f"錯誤：找不到檔案 '{case_payload_json_path}'", file=sys.stderr)
            return 1
        try:
            with open(case_payload_json_path, "r", encoding="utf-8") as f:
                raw_case_payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"錯誤：無法解析 case payload JSON 檔案 '{case_payload_json_path}': {exc}",
                file=sys.stderr,
            )
            return 1
        if not isinstance(raw_case_payload, dict):
            print(
                "錯誤：case payload JSON 內容需為物件（CaseStore payload / SubmissionCase dict）",
                file=sys.stderr,
            )
            return 1
        # 09.1-03（D-05）：raw CaseStore payload → submission 契約 dict
        # （缺欄誠實留空＋warnings 欄名，不捏造）；取代以往直接把 raw
        # payload 當 submission 傳的語義錯誤做法。
        submission, case_warnings = build_submission_from_case(raw_case_payload)

    try:
        facility = settings.load_facility_config()
    except (FileNotFoundError, ValueError) as exc:
        print(
            "錯誤：院所設定載入失敗"
            f"（FACILITY_CONFIG_PATH={settings.FACILITY_CONFIG_PATH}）: {exc}",
            file=sys.stderr,
        )
        return 1

    # 決定輸出：未指定 output_pdf 時輸出至 settings.OUTPUT_DIR，stem 由
    # appeal JSON 的 case_seq 與 order_seq 組出，先經 safe_filename 校驗（T-11-04）。
    if output_pdf_path:
        output_dir = os.path.dirname(output_pdf_path) or "."
        base = os.path.basename(output_pdf_path)
        if base.lower().endswith(".pdf"):
            base = base[: -len(".pdf")]
        if base.startswith("申復清單_"):
            base = base[len("申復清單_") :]
        raw_stem = base
        stem_label = "output_stem"
    else:
        output_dir = settings.OUTPUT_DIR
        case_seq = appeal_json.get("case_seq")
        order_seq = appeal_json.get("order_seq")
        raw_stem = f"{case_seq or 'unknown'}_{order_seq or 'unknown'}"
        stem_label = "case_seq/order_seq"

    try:
        stem = safe_filename(raw_stem, stem_label)
    except UnsafeIdentifierError as exc:
        print(f"錯誤：不安全的檔名 '{raw_stem}': {exc}", file=sys.stderr)
        return 1

    try:
        pdf_path, warnings = write_appeal_print(
            output_dir,
            stem,
            appeal_json,
            facility,
            template_odt_path=PRINT_BASE_ODT,
            submission=submission,
        )
    except UnsafeIdentifierError as exc:
        print(f"錯誤：不安全的輸出檔名: {exc}", file=sys.stderr)
        return 1
    except AppealPrintFillError as exc:
        print(f"錯誤：產生申復清單 PDF 失敗: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"錯誤：無法寫入輸出檔案: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"錯誤：輸入資料或設定不合法: {exc}", file=sys.stderr)
        return 1

    print(f"已成功輸出申復清單 PDF：{pdf_path}")
    if case_warnings or warnings:
        for w in case_warnings + warnings:
            print(f"警告：{w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
