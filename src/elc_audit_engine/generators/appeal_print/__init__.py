"""Phase 11 紙本申復清單列印（appeal_print 子套件）。

- `field_mapping`：官方 14 主表資料欄＋7 頭表欄逐欄對應純函式
  （build_rows/build_header/paginate），缺欄誠實降級。
- `odt_fill`：content.xml 注入＋zip 重打包＋超行分頁
  （fill_template/verify_template_hash/AppealPrintFillError）。
- `template`：一次性把官方 ODT 壓縮成每聯一頁的基準模板
  （build_print_base，產物入 git 並產出 sha256）。
- 本檔案：`render_appeal_print`（純函式，回傳 filled ODT bytes＋
  warnings）與 `write_appeal_print`（薄包裝，回傳 PDF 路徑＋warnings）。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from elc_audit_engine.generators.appeal_print.field_mapping import (
    build_header,
    build_rows,
    paginate,
)
from elc_audit_engine.generators.appeal_print.odt_fill import (
    AppealPrintFillError,
    fill_template,
    verify_template_hash,
)
from elc_audit_engine.safe_paths import safe_filename

__all__ = ["render_appeal_print", "write_appeal_print"]


def _load_expected_sha256(template_odt_path: str) -> str | None:
    """讀取模板旁同名的 `*.sha256` sidecar（T-11-06）。

    基準模板（`*_print_base.odt`）入庫時附帶 `*_print_base.sha256`；
    官方未壓縮模板無 sidecar → 回傳 None（不校驗 hash）。

    Raises:
        ValueError: 基準模板（`*_print_base.odt`）缺少 sidecar——基準模板
            屬 git 版控資產，缺 hash 即無法偵測竄改，拒絕靜默跳過校驗
            （T-11-06 防線完整性）。
    """
    sidecar = os.path.splitext(template_odt_path)[0] + ".sha256"
    if os.path.isfile(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            value = f.read().strip()
        return value or None
    if template_odt_path.endswith("_print_base.odt"):
        raise ValueError(
            "基準模板缺少 *.sha256 sidecar，無法校驗完整性（T-11-06）；"
            "請確認 *_print_base.odt 與其 *.sha256 均已入庫"
        )
    return None


def render_appeal_print(
    payload: dict,
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
) -> tuple[bytes, list[str]]:
    """組裝並回傳 filled 申復清單 ODT bytes（**純函式，無專案目錄副作用**）。

    Args:
        payload: appeal_{流水號}.json 內容（render_appeal_json dict）。
        facility: 院所層資料 dict（code/name/...）。
        template_odt_path: 基準模板 `.odt` 路徑（git-tracked 版控資產）。
        submission: 患者層資料 dict（id_number/patient_name/
            primary_diagnosis/clinic/orders；缺席即留空＋warnings）。

    Returns:
        (filled ODT bytes, warnings)。warnings＝build_rows 缺欄欄位名
        清單，沿 render→write→CLI 鏈傳出供使用者知悉誠實降級。

    Raises:
        TypeError/ValueError: payload/facility 非 dict（含欄位名定位）。
        FileNotFoundError: 模板路徑不存在。
        AppealPrintFillError: 注入/序列化失敗（訊息不含值全文）。

    Note:
        本函式**不寫入 data/output 或任何專案資料目錄**——暫存 filled
        ODT 走 `tempfile.TemporaryDirectory()`（系統 tmp，用完即清），
        回傳 bytes 由呼叫端決定落盤位置。
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload 必須為 dict，收到 {type(payload).__name__}")
    if not isinstance(facility, dict):
        raise TypeError(f"facility 必須為 dict，收到 {type(facility).__name__}")

    header = build_header(facility, payload, submission)
    rows, warnings = build_rows(payload, facility, submission=submission)
    pages = paginate(rows)

    with tempfile.TemporaryDirectory(prefix="elc_appeal_print_") as tmp:
        filled_path = os.path.join(tmp, "filled.odt")
        fill_template(template_odt_path, header, pages, filled_path)
        with open(filled_path, "rb") as f:
            return f.read(), warnings


def write_appeal_print(
    output_dir: str | os.PathLike[str],
    file_stem: str,
    payload: dict,
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
    soffice_timeout: int = 120,
) -> tuple[str, list[str]]:
    """產出紙本申復清單 PDF（薄包裝，比照 `write_appeal`）。

    Args:
        output_dir: 輸出目錄（正式流程為 data/output，已 gitignore）。
        file_stem: 檔名主幹（經 safe_filename 校驗後拒絕，P1-3/T-11-04）。
        payload: appeal_{流水號}.json 內容。
        facility: 院所層資料 dict。
        template_odt_path: 基準模板 `.odt` 路徑；旁附 `*.sha256` 時
            生成前以 verify_template_hash 校驗（T-11-06）。
        submission: 患者層資料 dict。
        soffice_timeout: soffice 轉檔逾時秒數（預設 120）。

    Returns:
        (pdf_path, warnings)。PDF 檔名為 `申復清單_{stem}.pdf`。

    Raises:
        UnsafeIdentifierError: file_stem 含路徑穿越/非法字元（不寫出）。
        TypeError/ValueError: payload/facility 非 dict。
        FileNotFoundError: 模板路徑不存在。
        AppealPrintFillError: 注入或 soffice 轉檔失敗（訊息含失敗階段
            與模板路徑，不含 payload/欄位值全文——T-11-03）。
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload 必須為 dict，收到 {type(payload).__name__}")
    if not isinstance(facility, dict):
        raise TypeError(f"facility 必須為 dict，收到 {type(facility).__name__}")

    # P1-3：stem 進檔名，未校驗會造成寫入型路徑穿越（校驗後拒絕）。
    stem = safe_filename(file_stem, "file_stem")
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(os.fspath(output_dir), f"申復清單_{stem}.pdf")

    # T-11-06：基準模板 sha256 校驗（讀 sidecar；無 sidecar 不校驗）。
    verify_template_hash(template_odt_path, _load_expected_sha256(template_odt_path))

    filled_odt_bytes, warnings = render_appeal_print(
        payload,
        facility,
        template_odt_path=template_odt_path,
        submission=submission,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="elc_appeal_convert_") as tmp:
            # filled ODT 檔名與目標 PDF 同名（soffice 輸出＝輸入去副檔名＋.pdf）
            filled_path = os.path.join(tmp, f"申復清單_{stem}.odt")
            with open(filled_path, "wb") as f:
                f.write(filled_odt_bytes)

            profile_dir = os.path.join(tmp, "lo_profile")
            os.makedirs(profile_dir, exist_ok=True)
            result = subprocess.run(
                [
                    "soffice",
                    f"-env:UserInstallation={Path(profile_dir).as_uri()}",
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    os.fspath(output_dir),
                    filled_path,
                ],
                capture_output=True,
                timeout=soffice_timeout,
            )
    except subprocess.TimeoutExpired as exc:
        raise AppealPrintFillError(
            "soffice 轉檔逾時（階段：convert，模板："
            f"{os.path.basename(template_odt_path)}）"
        ) from exc
    except OSError as exc:
        raise AppealPrintFillError(
            "soffice 轉檔環境失敗（階段：convert）"
        ) from exc

    if result.returncode != 0 or not os.path.isfile(pdf_path):
        raise AppealPrintFillError(
            "soffice 轉 PDF 失敗或輸出檔不存在（階段：convert，模板："
            f"{os.path.basename(template_odt_path)}）"
        )

    return pdf_path, warnings
