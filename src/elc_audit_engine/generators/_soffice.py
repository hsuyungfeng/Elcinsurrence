"""LibreOffice headless 轉 PDF 的共用實作（review A-WR-06）。

原本三處各自呼叫 soffice，且直接 `--outdir` 寫到正式輸出目錄：
- soffice 常在失敗時仍回 exit 0；若上次同名 PDF 還在，會把**過期的 PDF**
  當成本次結果回傳（appeal_print），或完全不檢查輸出檔（deduction_print）。
- 同一 stem 的併發請求會互相覆寫。

這裡一律輸出到私有暫存目錄，確認 PDF 存在且非空後，才以同目錄暫存名
＋`os.replace` 原子地放到目的地。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class SofficeConvertError(RuntimeError):
    """soffice 轉檔失敗（逾時、環境錯誤、exit 非 0、未產出或產出空檔）。

    訊息可能含 soffice stderr 摘要，只供日誌使用，不得原樣回給 API 呼叫端。
    """


def convert_to_pdf(src_path: str, dest_pdf_path: str, *, timeout: int = 120) -> str:
    """把 `src_path`（.odt／.docx 等）轉成 PDF 並原子寫到 `dest_pdf_path`。

    Returns:
        `dest_pdf_path`。

    Raises:
        SofficeConvertError: 任何轉檔失敗。
    """
    dest_dir = os.path.dirname(os.path.abspath(dest_pdf_path))
    os.makedirs(dest_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="elc_soffice_") as tmp:
        out_dir = os.path.join(tmp, "out")
        profile_dir = os.path.join(tmp, "lo_profile")
        os.makedirs(out_dir)
        os.makedirs(profile_dir)
        try:
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
                    out_dir,
                    src_path,
                ],
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SofficeConvertError(f"soffice 轉檔逾時（{timeout}s）") from exc
        except OSError as exc:
            raise SofficeConvertError(f"soffice 無法執行：{exc}") from exc

        produced = os.path.join(out_dir, Path(src_path).stem + ".pdf")
        if result.returncode != 0 or not os.path.isfile(produced) or os.path.getsize(produced) == 0:
            stderr = result.stderr.decode("utf-8", errors="ignore")[:500]
            raise SofficeConvertError(
                f"soffice 轉 PDF 失敗（exit={result.returncode}，未產出或空檔）：{stderr}"
            )

        fd, staging = tempfile.mkstemp(dir=dest_dir, prefix=".pdf_", suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(produced, staging)
            os.replace(staging, dest_pdf_path)
        except BaseException:
            if os.path.exists(staging):
                os.remove(staging)
            raise
    return dest_pdf_path
