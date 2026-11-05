"""健保 11 碼 EMR 批次打包與標準檔名重命名 API 路由。

規格依據：emr-batch-packaging-naming-spec.md
端點：
- POST /api/emr/batch-package: 執行第2階（抽審）或第3階（申覆）批次 11 碼重命名與 500MB ZIP 封包產製
- GET /api/emr/packages: 查詢已產製之 EMR 封包清單
- GET /api/emr/download/<filename>: 下載已產製之 500MB ZIP 封包
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_from_directory

from elc_audit_engine.api.context import case_store
from elc_audit_engine.api.demo_data import DEMO_APPEAL_CASES, DEMO_SAMPLING_CASES
from elc_audit_engine.api.errors import ApiError
from elc_audit_engine.case_store.store import CaseNotFoundError
from elc_audit_engine.packagers.emr_batch_packager import (
    BatchZipPackager,
    Emr11CodeNaming,
    EmrClassifier,
    EmrPackagingError,
    SourceQualityValidator,
    StructuredSoapPdfBuilder,
)
from elc_audit_engine.reconciliation.soap_reconciler import format_soap_to_text
from elc_audit_engine.evidence_vault import list_vault_files

bp = Blueprint("emr_packaging", __name__)

_SAFE_ZIP_NAME_RE = re.compile(r"^[0-9A-Za-z_-]+\.zip$")


def _get_emr_output_dir() -> Path:
    base = (Path(current_app.config.get("ELC_DATA_DIR", "data")) / "output" / "emr_packages").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


@bp.route("/api/emr/batch-package", methods=["POST"])
def create_emr_batch_package():
    """執行批次 EMR 500MB ZIP 打包。"""
    body = request.get_json(silent=True) or {}
    target = (body.get("target") or "sampling").strip().lower()
    facility_code = str(body.get("facility_code") or "3503250461").strip()
    submission_type = int(body.get("submission_type") or (4 if target == "appeal" else 1))
    old_accept_no = body.get("old_accept_no")

    store = case_store()
    cases_records = store.list_all(kind=target, limit=1000)

    # 若資料庫中尚無案件，回退使用展示案件以供即時預覽體驗
    raw_cases: list[dict[str, Any]] = []
    if cases_records:
        for r in cases_records:
            payload = dict(r.payload or {})
            payload.setdefault("id", r.case_id)
            raw_cases.append(payload)
    else:
        raw_cases = list(DEMO_APPEAL_CASES if target == "appeal" else DEMO_SAMPLING_CASES)

    if not raw_cases:
        raise ApiError(f"目前無可供打包之 {target} 案件", status=400)

    cases_files: list[dict[str, Any]] = []
    stage1 = "11"  # 西醫基層門診

    for idx, c in enumerate(raw_cases, start=1):
        case_id = c.get("id") or f"CASE-{idx:04d}"
        case_class = c.get("case_class") or "09"
        soap_raw = c.get("soap") or c.get("soap_text") or ""
        soap_text = format_soap_to_text(soap_raw) if isinstance(soap_raw, dict) else str(soap_raw)

        # 1. 產生 A 類標準 SOAP 紀錄單 PDF（含三大樹狀書籤）
        case_info = {
            "facility_code": facility_code,
            "patient_name": c.get("patient_name") or c.get("name") or "病患",
            "id_card": c.get("id_card") or c.get("record_no") or "A123456789",
            "record_no": c.get("record_no"),
            "visit_date": c.get("visit_date") or c.get("date"),
            "primary_diagnosis": c.get("primary_diagnosis") or c.get("d18") or "E11.9",
            "secondary_diagnoses": c.get("secondary_diagnoses") or [],
            "total_points": c.get("total_points") or c.get("points") or 100,
            "case_class": case_class,
            "orders": c.get("orders") or [],
        }

        pdf_bytes = StructuredSoapPdfBuilder.build_soap_pdf(
            case_info=case_info,
            soap_text=soap_raw or soap_text,
            prescriptions=case_info["orders"],
        )

        base_a = Emr11CodeNaming.build_base_name(stage1, "A", case_class, idx)
        soap_filename = Emr11CodeNaming.format_filename(base_a, ".pdf")

        case_file_entries = [
            {
                "filename": soap_filename,
                "data": pdf_bytes,
                "original_name": "門診SOAP病歷紀錄.pdf",
                "tier": "A",
            }
        ]

        # 2. 檢索掛載之 Evidence Vault 佐證檔案並歸入 B/C/D 類
        vault_key = c.get("vault_key")
        if vault_key:
            tier_counters: dict[str, int] = {"B": 0, "C": 0, "D": 0}
            try:
                vault_dict = list_vault_files(vault_key)
                for category, v_files in vault_dict.items():
                    for vf in v_files:
                        try:
                            file_bytes = Path(vf.path).read_bytes()
                        except Exception:
                            continue
                        tier = EmrClassifier.classify(filename=vf.filename, category=category)
                        if tier not in tier_counters:
                            tier = "B"
                        tier_counters[tier] += 1
                        sub_idx = tier_counters[tier] if tier_counters[tier] > 1 else None

                        ext = os.path.splitext(vf.filename)[1] or ".jpg"
                        base_tier = Emr11CodeNaming.build_base_name(stage1, tier, case_class, idx)
                        formatted_name = Emr11CodeNaming.format_filename(base_tier, ext, sub_index=sub_idx)

                        case_file_entries.append({
                            "filename": formatted_name,
                            "data": file_bytes,
                            "original_name": vf.filename,
                            "tier": tier,
                        })
            except Exception:
                pass

        cases_files.append({
            "case_id": case_id,
            "base_11code": base_a,
            "files": case_file_entries,
        })

    try:
        packages = BatchZipPackager.package_emr_batch(
            cases_files,
            facility_code=facility_code,
            submission_type=submission_type,
            old_accept_no=old_accept_no,
        )
    except EmrPackagingError as exc:
        raise ApiError(str(exc), status=400)

    out_dir = _get_emr_output_dir()
    results = []
    for zip_name, zip_bytes, report in packages:
        file_path = out_dir / zip_name
        file_path.write_bytes(zip_bytes)
        results.append({
            "filename": zip_name,
            "size_bytes": len(zip_bytes),
            "file_count": report["file_count"],
            "download_url": f"/api/emr/download/{zip_name}",
            "manifest": report["manifest"],
        })

    return jsonify({
        "status": "success",
        "message": f"成功產製 {len(packages)} 個標準健保 EMR 審查封包（共 {sum(r['file_count'] for r in results)} 個檔案）",
        "packages": results,
    })


@bp.route("/api/emr/packages", methods=["GET"])
def list_emr_packages():
    """取得現有 EMR 打包 ZIP 檔案清單。"""
    out_dir = _get_emr_output_dir()
    packages = []
    for f in sorted(out_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        packages.append({
            "filename": f.name,
            "size_bytes": st.st_size,
            "modified_time": st.st_mtime,
            "download_url": f"/api/emr/download/{f.name}",
        })
    return jsonify({"status": "success", "packages": packages})


@bp.route("/api/emr/download/<filename>", methods=["GET"])
def download_emr_package(filename: str):
    """下載指定 EMR 批次 ZIP 檔。"""
    if not _SAFE_ZIP_NAME_RE.match(filename):
        raise ApiError("不合法的檔案名稱", status=400)
    out_dir = _get_emr_output_dir()
    target_file = out_dir / filename
    if not target_file.exists():
        raise ApiError(f"檔案不存在：{filename}", status=404)
    return send_from_directory(str(out_dir), filename, as_attachment=True)
