"""LibreOffice headless `.doc` -> `.docx` 批次轉換。

不使用任何雲端服務：呼叫本機安裝的 LibreOffice (`soffice --headless`)
將舊版二進位 `.doc` 檔案轉換為可被 python-docx 讀取的 OOXML `.docx` 檔案。
"""

import glob
import os
import subprocess


def convert_doc_files(source_dir: str, staging_dir: str) -> list[str]:
    """將 `source_dir` 內所有 `.doc`（排除 `.docx`）轉換為 `.docx`，輸出至 `staging_dir`。

    Args:
        source_dir: 來源文件目錄（可能同時包含 .doc 與 .docx）。
        staging_dir: 轉換後 .docx 輸出目錄，若不存在會自動建立。

    Returns:
        轉換完成的 .docx 檔案完整路徑清單（於 staging_dir 內）。

    Raises:
        RuntimeError: 若本機找不到 `soffice`（LibreOffice）執行檔。
        subprocess.CalledProcessError: 若轉換過程中 soffice 回傳非 0。
        subprocess.TimeoutExpired: 若單一檔案轉換超過 120 秒。
    """
    os.makedirs(staging_dir, exist_ok=True)

    doc_paths = sorted(
        p
        for p in glob.glob(os.path.join(source_dir, "*.doc"))
        if not p.lower().endswith(".docx")
    )

    converted_paths = []
    for doc_path in doc_paths:
        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    staging_dir,
                    doc_path,
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "soffice (LibreOffice) not found on PATH — required for .doc conversion"
            ) from exc

        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        converted_path = os.path.join(staging_dir, f"{base_name}.docx")
        converted_paths.append(converted_path)

    return converted_paths
