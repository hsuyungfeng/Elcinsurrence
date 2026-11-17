"""全民健保電子病歷抽審與申覆「批次打包與檔名自動化重命名」引擎。

規格依據：emr-batch-packaging-naming-spec.md
1. 11 碼標準檔名編碼邏輯：[第1階 2碼] + [第2階 1碼 A/B/C/D] + [案件分類 2碼] + [流水號 6碼] + [-N 擴充]
2. 四大資料屬性分類：
   - A: 病歷本文（SOAP 紀錄、病歷首頁、處方箋、手術/麻醉紀錄）
   - B: 影像類（X光、CT、MRI、超音波、臨床處置照片、DICOM）
   - C: 非影像檢驗報告（生化 CBC/HbA1c、病理、心電圖）
   - D: 其他書類/同意書（手術同意書、事前審查核准函、自費同意書）
3. 500MB ZIP 封包命名與動態分包：{機構代碼 10碼}_{民國日期 7碼}_{序號 3碼}.zip，450MB 動態裁切。
4. A 類病歷本文 PDF 樹狀書籤（Bookmarks）與電子簽章。
5. 源頭端品質驗證（Validation-at-Source）。
"""

from __future__ import annotations

import hashlib
import html as _html
import io
import os
import re
import zipfile
from datetime import datetime
from typing import Any


# 健保許可格式白名單與阻斷清單
ALLOWED_EMR_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    ".txt", ".html", ".htm", ".xml", ".mp4", ".mpeg",
})
BLOCKED_EMR_EXTENSIONS = frozenset({".zip", ".rar", ".exe", ".7z", ".tar"})

_STAGE1_RE = re.compile(r"^\d{2}$")
_STAGE2_RE = re.compile(r"^[ABCD]$")
_CASE_CLASS_RE = re.compile(r"^\d{1,2}$")
_CASE_SEQ_RE = re.compile(r"^\d{1,6}$")
_11CODE_FULL_RE = re.compile(r"^[0-9]{2}[ABCD][0-9]{2}[0-9]{6}(-[0-9]+)?\.[a-zA-Z0-9]+$")


class EmrPackagingError(ValueError):
    """EMR 批次打包或檔名規則錯誤。"""


class EmrClassifier:
    """四大資料屬性分類器 (A:病歷本文, B:影像, C:非影像檢驗, D:同意書附件)。"""

    IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".mp4", ".mpeg"})
    REPORT_EXTS = frozenset({".pdf", ".txt", ".html", ".xml", ".csv"})

    @classmethod
    def classify(
        cls,
        category: str | None = None,
        filename: str | None = None,
        description: str | None = None,
    ) -> str:
        cat_lower = (category or "").lower().strip()
        name_lower = (filename or "").lower().strip()
        desc_lower = (description or "").lower().strip()

        # 1. 顯式指定或關鍵字判斷
        if cat_lower in ("a", "records", "soap", "progress_note", "consultation"):
            return "A"
        if cat_lower in ("b", "images", "radiology", "dicom", "xray", "sono"):
            return "B"
        if cat_lower in ("c", "reports", "labs", "laboratory", "blood", "biochem"):
            return "C"
        if cat_lower in ("d", "consents", "attachments", "agreements"):
            return "D"

        # 2. 檔名關鍵字識別
        if any(k in name_lower or k in desc_lower for k in ("同意書", "核准函", "consent", "agreement")):
            return "D"
        if any(k in name_lower or k in desc_lower for k in ("xray", "sono", "ct", "mri", "dicom", "photo", "image", "截圖", "影像")):
            return "B"
        if any(k in name_lower or k in desc_lower for k in ("cbc", "lab", "hba1c", "biochem", "pathology", "檢驗", "抽血")):
            return "C"
        if any(k in name_lower or k in desc_lower for k in ("soap", "record", "chart", "門診", "病歷", "處方")):
            return "A"

        # 3. 副檔名預設分流
        ext = os.path.splitext(name_lower)[1]
        if ext in cls.IMAGE_EXTS:
            return "B"

        # 預設歸入 A（病歷本文類）
        return "A"


class Emr11CodeNaming:
    """11 碼標準檔名編碼與擴充命名引擎。"""

    @classmethod
    def build_base_name(
        cls,
        stage1: str,
        stage2: str,
        case_class: str | int,
        case_seq: str | int,
    ) -> str:
        s1 = str(stage1 or "").strip()
        s2 = str(stage2 or "").strip().upper()
        cc = str(case_class or "").strip()
        seq = str(case_seq or "").strip()

        if not _STAGE1_RE.match(s1):
            raise EmrPackagingError(f"第一階層代碼不合法（須為 2 碼數字，如 11 診所門診）：{s1}")
        if not _STAGE2_RE.match(s2):
            raise EmrPackagingError(f"第二階層代碼不合法（須為 A/B/C/D 四大屬性）：{s2}")
        if not _CASE_CLASS_RE.match(cc):
            raise EmrPackagingError(f"案件分類代碼不合法（須為 1~2 碼數字）：{cc}")
        if not _CASE_SEQ_RE.match(seq):
            raise EmrPackagingError(f"案件流水號不合法（須為 1~6 碼數字）：{seq}")

        cc_int = int(cc)
        seq_int = int(seq)
        return f"{s1}{s2}{cc_int:02d}{seq_int:06d}"

    @classmethod
    def format_filename(
        cls,
        base_name: str,
        extension: str = ".pdf",
        sub_index: int | None = None,
    ) -> str:
        ext = extension.lower()
        if not ext.startswith("."):
            ext = "." + ext
        if sub_index is not None and sub_index > 0:
            return f"{base_name}-{sub_index}{ext}"
        return f"{base_name}{ext}"


class SourceQualityValidator:
    """源頭端品質預檢模組 (Validation-at-Source)。"""

    @classmethod
    def validate_filename(cls, filename: str) -> tuple[bool, str | None]:
        if not filename:
            return False, "檔名不得為空"
        if not _11CODE_FULL_RE.match(filename):
            return False, f"檔名不符合健保 11 碼標準編碼格式（例如 11A09001352.pdf 或 11B09001352-1.jpg）：{filename}"
        return True, None

    @classmethod
    def validate_extension(cls, filename: str) -> tuple[bool, str | None]:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext in BLOCKED_EMR_EXTENSIONS:
            return False, f"禁止上傳之壓縮或執行檔副檔名：{ext}"
        if ext == ".dcm":
            return False, "獨立裸 DICOM 檔 (.dcm) 格式不符，健保規範需具備 DICOMDIR 引導目錄"
        if ext not in ALLOWED_EMR_EXTENSIONS:
            return False, f"非健保白名單許可之檔案格式：{ext}"
        return True, None

    @classmethod
    def validate_dicom_bundle(cls, filenames: list[str]) -> tuple[bool, str | None]:
        has_dicom = any(f.lower().endswith(".dcm") or "dicom" in f.lower() for f in filenames)
        has_dicomdir = any(os.path.basename(f).upper() == "DICOMDIR" for f in filenames)
        if has_dicom and not has_dicomdir:
            return False, "DICOM 影像封包中缺少必要之 DICOMDIR 引導目錄檔"
        return True, None


class StructuredSoapHtmlBuilder:
    """A 類病歷本文 HTML 產製（2026-11-17 決定改用 HTML，取代空白頁的 PDF 產製）。

    輸出為單一自包含 UTF-8 HTML：病歷首頁、門診處方箋、門診 SOAP 紀錄單三段，
    以錨點目錄取代 PDF 樹狀書籤。所有欄位一律 HTML 轉義，缺漏欄位顯示「（未提供）」，不捏造內容。
    """

    SECTION_TITLES = ("病歷首頁", "門診處方箋", "門診 SOAP 紀錄單")

    @staticmethod
    def _v(value: Any) -> str:
        text = "" if value is None else str(value).strip()
        return _html.escape(text) if text else "（未提供）"

    @classmethod
    def _soap_parts(cls, soap_text: str | dict) -> dict[str, str]:
        if isinstance(soap_text, dict):
            return {
                "S": str(soap_text.get("s") or soap_text.get("subjective") or ""),
                "O": str(soap_text.get("o") or soap_text.get("objective") or ""),
                "A": str(soap_text.get("a") or soap_text.get("assessment") or ""),
                "P": str(soap_text.get("p") or soap_text.get("plan") or ""),
            }
        return {"S": str(soap_text or ""), "O": "", "A": "", "P": ""}

    @classmethod
    def build_soap_html(
        cls,
        case_info: dict[str, Any],
        soap_text: str | dict,
        prescriptions: list[dict[str, Any]] | None = None,
    ) -> bytes:
        v = cls._v
        parts = cls._soap_parts(soap_text)
        secondary = case_info.get("secondary_diagnoses") or []
        rx_rows = []
        for o in prescriptions or []:
            rx_rows.append(
                "<tr><td>{code}</td><td>{name}</td><td>{points}</td></tr>".format(
                    code=v(o.get("code")), name=v(o.get("name")), points=v(o.get("points")),
                )
            )
        rx_table = (
            "<table><thead><tr><th>醫令代碼</th><th>醫令名稱</th><th>點數</th></tr></thead>"
            "<tbody>" + ("".join(rx_rows) if rx_rows else '<tr><td colspan="3">（未提供）</td></tr>')
            + "</tbody></table>"
        )
        soap_rows = "".join(
            "<tr><th>{k}</th><td class=\"pre\">{t}</td></tr>".format(k=k, t=v(parts[k]))
            for k in ("S", "O", "A", "P")
        )
        title = f"門診病歷紀錄單 - {_html.escape(str(case_info.get('patient_name') or '未具名'))}"
        toc = "".join(
            f'<li><a href="#sec{i}">{t}</a></li>' for i, t in enumerate(cls.SECTION_TITLES, start=1)
        )
        doc = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: "Noto Sans CJK TC", "Microsoft JhengHei", sans-serif; color:#111; margin:24px; }}
  h1 {{ font-size:20px; border-bottom:2px solid #333; padding-bottom:6px; }}
  h2 {{ font-size:16px; margin-top:28px; border-bottom:1px solid #999; }}
  table {{ border-collapse:collapse; width:100%; margin-top:8px; }}
  th, td {{ border:1px solid #888; padding:6px 8px; vertical-align:top; text-align:left; }}
  th {{ background:#f0f0f0; width:110px; }}
  td.pre {{ white-space:pre-wrap; }}
  nav ul {{ list-style:none; padding:0; }}
  nav li {{ display:inline-block; margin-right:16px; }}
  .sign {{ margin-top:32px; }}
  @media print {{ nav {{ display:none; }} h2 {{ page-break-before:always; }} }}
</style>
</head>
<body>
<h1>{title}</h1>
<nav aria-label="目錄"><ul>{toc}</ul></nav>

<section id="sec1">
<h2>病歷首頁</h2>
<table>
<tr><th>病患姓名</th><td>{v(case_info.get('patient_name'))}</td></tr>
<tr><th>身分證字號 / 病歷號</th><td>{v(case_info.get('id_card'))}</td></tr>
<tr><th>就醫日期</th><td>{v(case_info.get('visit_date'))}</td></tr>
<tr><th>門診科別</th><td>{v(case_info.get('clinic'))}</td></tr>
<tr><th>主診斷</th><td>{v(case_info.get('primary_diagnosis'))}</td></tr>
<tr><th>次要診斷</th><td>{v(', '.join(str(x) for x in secondary) if secondary else None)}</td></tr>
<tr><th>總點數</th><td>{v(case_info.get('total_points'))}</td></tr>
</table>
</section>

<section id="sec2">
<h2>門診處方箋</h2>
{rx_table}
</section>

<section id="sec3">
<h2>門診 SOAP 紀錄單</h2>
<table>{soap_rows}</table>
</section>

<p class="sign">醫師簽章：__________________　日期：__________</p>
</body>
</html>
"""
        return doc.encode("utf-8")


class BatchZipPackager:
    """500MB ZIP 批次打包引擎，支援動態裁切分包與健保標準命名。"""

    MAX_BYTES = 500 * 1024 * 1024  # 500MB 嚴格上限
    SPLIT_THRESHOLD_BYTES = 450 * 1024 * 1024  # 450MB 動態裁切分包臨界值

    @classmethod
    def generate_zip_name(
        cls,
        facility_code: str,
        system_date_roc: str | None = None,
        seq: int = 1,
    ) -> str:
        fac = str(facility_code or "").strip()
        if not fac:
            fac = "3503250461"
        date_str = str(system_date_roc or "").strip()
        if not date_str:
            now = datetime.now()
            date_str = f"{now.year - 1911:03d}{now.strftime('%m%d')}"
        return f"{fac}_{date_str}_{seq:03d}.zip"

    @classmethod
    def package_emr_batch(
        cls,
        cases_files: list[dict[str, Any]],
        *,
        facility_code: str = "3503250461",
        system_date_roc: str | None = None,
        submission_type: int = 1,
        old_accept_no: str | None = None,
        split_threshold: int = SPLIT_THRESHOLD_BYTES,
    ) -> list[tuple[str, bytes, dict[str, Any]]]:
        """將多案 EMR 檔案依據容量限制動態分包為多個 500MB ZIP。

        Args:
            cases_files: 各案件檔案清單，每項格式如下：
                {
                    "case_id": "...",
                    "base_11code": "11A09001352",
                    "files": [
                        {"filename": "11A09001352.pdf", "data": b"...", "original_name": "soap.pdf", "tier": "A"},
                        {"filename": "11B09001352-1.jpg", "data": b"...", "original_name": "xray.jpg", "tier": "B"},
                    ]
                }
            facility_code: 10 碼機構代碼。
            submission_type: 申報類別（1:初審送核, 2:初審補報, 4:申覆送核, 5:申覆補報）。
            old_accept_no: 原初審受理編號（申覆案件必填）。

        Returns:
            [(zip_filename, zip_bytes, manifest_report), ...]
        """
        packages: list[tuple[str, bytes, dict[str, Any]]] = []
        current_seq = 1
        current_bytes = 0

        current_zip_buffer = io.BytesIO()
        current_zip = zipfile.ZipFile(current_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED)
        manifest_entries = []
        checksum_entries = []

        def _close_current_package():
            nonlocal current_zip, current_zip_buffer, current_seq, current_bytes
            nonlocal manifest_entries, checksum_entries

            # 寫入 MANIFEST.txt
            manifest_lines = [
                "全民健保電子病歷審查批次封包清單",
                f"醫事機構代碼：{facility_code}",
                f"申報類別：{submission_type}（{'申覆送核' if submission_type == 4 else '初審送核'}）",
            ]
            if old_accept_no and submission_type in (4, 5):
                manifest_lines.append(f"原初審受理編號 (oldAcptNo)：{old_accept_no}")
            manifest_lines.extend([
                f"打包時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 70,
                f"{'健保11碼檔名':<25} {'屬性':<6} {'檔案大小':<12} {'原檔名'}",
                "-" * 70,
            ])
            for m in manifest_entries:
                manifest_lines.append(f"{m['filename']:<25} {m['tier']:<6} {m['size']:<12} {m['original_name']}")
            manifest_lines.append("=" * 70)
            manifest_lines.append(f"總計收錄檔案數：{len(manifest_entries)} 件")

            current_zip.writestr("MANIFEST.txt", "\n".join(manifest_lines) + "\n")

            # 寫入 SHA256_CHECKSUM.txt
            current_zip.writestr("SHA256_CHECKSUM.txt", "\n".join(checksum_entries) + "\n")

            current_zip.close()
            zip_data = current_zip_buffer.getvalue()
            zip_name = cls.generate_zip_name(facility_code, system_date_roc, current_seq)

            report = {
                "zip_filename": zip_name,
                "facility_code": facility_code,
                "submission_type": submission_type,
                "file_count": len(manifest_entries),
                "total_bytes": len(zip_data),
                "manifest": manifest_entries,
            }
            packages.append((zip_name, zip_data, report))

            # 重設下一包
            current_seq += 1
            current_bytes = 0
            manifest_entries = []
            checksum_entries = []
            current_zip_buffer = io.BytesIO()
            current_zip = zipfile.ZipFile(current_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED)

        for case_item in cases_files:
            files = case_item.get("files") or []
            for f in files:
                fname = f["filename"]
                data = f["data"]
                original = f.get("original_name") or fname
                tier = f.get("tier") or "A"
                f_size = len(data)

                # 品質預檢：副檔名與 11 碼格式
                valid_name, err_name = SourceQualityValidator.validate_filename(fname)
                if not valid_name:
                    raise EmrPackagingError(f"源頭端檢核失敗（檔名）：{err_name}")

                valid_ext, err_ext = SourceQualityValidator.validate_extension(fname)
                if not valid_ext:
                    raise EmrPackagingError(f"源頭端檢核失敗（格式）：{err_ext}")

                # 檢查容量是否達臨界值
                if current_bytes + f_size > split_threshold and manifest_entries:
                    _close_current_package()

                # 寫入壓縮檔
                current_zip.writestr(fname, data)
                current_bytes += f_size

                # 計算 SHA-256
                sha = hashlib.sha256(data).hexdigest()
                checksum_entries.append(f"{sha}  {fname}")
                manifest_entries.append({
                    "filename": fname,
                    "original_name": original,
                    "tier": tier,
                    "size": f_size,
                    "sha256": sha,
                })

        if manifest_entries:
            _close_current_package()

        return packages
